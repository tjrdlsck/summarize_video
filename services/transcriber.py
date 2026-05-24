import os
import subprocess
import re
import json
import torch
import ssl
import certifi
import urllib.request

# [Add] Mac 환경 SSL 인증서 에러의 근본적/보안적 해결 (certifi 사용)
ssl_context = ssl.create_default_context(cafile=certifi.where())
urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context)))

try:
    import mlx_whisper
except ImportError:
    mlx_whisper = None

import soundfile as sf
import numpy as np
import stable_whisper
import time
import multiprocessing
import sys
import gc # [Add] 가비지 컬렉션을 위해 추가
from services.content_profiles import get_content_profile
from services.system_manager import ConfigManager

class TaskCancelledError(Exception):
    """작업이 사용자에 의해 취소되었을 때 발생하는 예외"""
    pass

class WhisperProgressHook:
    """
    [New] Whisper 모델의 stdout 출력을 가로채서 진행률을 계산하고 Queue로 보냅니다.
    예: [00:12.000 --> 00:15.000] ... 형태의 로그를 파싱합니다.
    """
    def __init__(self, queue, total_duration):
        self.queue = queue
        self.total_duration = total_duration if total_duration > 0 else 1
        self.last_percent = -1
        self.terminal = sys.stdout  # 원래의 stdout 저장

    def write(self, message):
        # 1. 원래 터미널에도 출력 (디버깅용)
        self.terminal.write(message)
        
        # 2. 타임스탬프 파싱 (정규식)
        # 패턴: [00:00.000 --> 00:05.000] 또는 [00:00 --> 00:05]
        match = re.search(r'\[(\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?) --> (\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)\]', message)
        if match:
            end_time_str = match.group(2)
            try:
                # 시간 문자열을 초(seconds)로 변환
                parts = end_time_str.replace('.', ':').split(':')
                seconds = 0.0
                if len(parts) == 3: # MM:SS.ms
                    seconds = int(parts[0]) * 60 + float(f"{parts[1]}.{parts[2]}")
                elif len(parts) >= 4: # HH:MM:SS.ms
                    seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(f"{parts[2]}.{parts[3]}")
                
                # 퍼센트 계산
                percent = int((seconds / self.total_duration) * 100)
                percent = min(99, max(0, percent)) # 0~99 사이로 제한

                # 진행률이 변경되었을 때만 큐 전송 (부하 감소)
                if percent > self.last_percent:
                    self.queue.put({"status": "progress", "percent": percent})
                    self.last_percent = percent
            except Exception:
                pass # 파싱 실패 시 무시

    def flush(self):
        self.terminal.flush()

def run_vad_worker(audio_path, result_queue):
    """
    [Worker Process] 별도 프로세스에서 실행되는 VAD 추론 함수입니다.
    완료 후 프로세스가 종료되며 VRAM 점유를 완전히 해제합니다.
    """
    import torch
    import soundfile as sf
    import gc
    try:
        model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                      model='silero_vad',
                                      force_reload=False,
                                      trust_repo=True)
        (get_speech_timestamps, _, _, _, _) = utils
        
        # [하드웨어 가속 최적화 - 롤백]
        # Silero VAD는 순차적 오디오 청크를 처리하는 초경량 모델이므로
        # GPU 통신 오버헤드(PCIe)로 인해 오히려 속도가 느려질 수 있어 CPU로 고정합니다.
        device = torch.device('cpu')
        model = model.to(device)
        
        audio_data, sr = sf.read(audio_path)
        wav = torch.from_numpy(audio_data).float()
        
        if wav.ndim > 1: 
            wav = wav.mean(dim=1) 
        wav = wav.unsqueeze(0).to(device)
        
        speech_timestamps = get_speech_timestamps(wav, model, threshold=0.5)
        
        segments = []
        for item in speech_timestamps:
            segments.append((item['start'] / 16000, item['end'] / 16000))
            
        result_queue.put({"status": "success", "data": segments})
    except Exception as e:
        result_queue.put({"status": "error", "message": str(e)})
    finally:
        if 'model' in locals():
            del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

def run_whisper_worker(wav_path, model_path, result_queue, total_duration, initial_prompt, parent_sys_path=None):
    """
    [Worker Process] 별도 프로세스에서 실행되는 Whisper 추론 함수입니다.
    stdout을 캡처하여 진행률을 실시간으로 보고합니다.
    """
    if parent_sys_path:
        import sys
        for p in parent_sys_path:
            if p not in sys.path:
                sys.path.append(p)
    try:
        print(f"[Whisper Worker] PID {os.getpid()} started processing with model: {model_path}...")
        
        # [New] stdout을 Hook 클래스로 리다이렉트
        # 이제부터 print()나 라이브러리의 stdout 출력은 hook.write()로 전달됨
        hook = WhisperProgressHook(result_queue, total_duration)
        sys.stdout = hook
        
        output = None

        if sys.platform == "darwin" and mlx_whisper is not None:
            # --- [Mac] MLX Whisper Engine ---
            print("[Whisper Worker] Using MLX Engine (Apple Silicon Optimized)")
            # MLX Whisper 추론 실행
            output = mlx_whisper.transcribe(
                wav_path,
                path_or_hf_repo=model_path,
                language="ko",
                verbose=True,  # [중요] True여야 타임스탬프 로그가 출력되어 Hook이 작동함
                word_timestamps=True,
                condition_on_previous_text=False,
                temperature=(0.0, 0.2, 0.4),
                initial_prompt=initial_prompt
            )
        else:
            # --- [Windows/Linux] Faster-Whisper + Stable-Whisper Engine ---
            # NVIDIA GPU(CUDA) 가속 사용
            print("[Whisper Worker] Using Faster-Whisper Engine (CUDA/CPU)")
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            # [최적화] CUDA 환경에서는 float16을 강제하여 VRAM 효율성 및 연산 속도를 극대화
            compute_type = "float16" if device == "cuda" else "int8"
            
            print(f"[Whisper Worker] Device: {device}, Compute Type: {compute_type}")
            
            # Faster-Whisper 모델 로드 (backend='faster-whisper')
            # stable-ts 2.x에서는 load_faster_whisper 함수 사용
            model = stable_whisper.load_faster_whisper(
                model_path, 
                device=device, 
                compute_type=compute_type
            )
            
            # 추론 실행
            # verbose=True로 설정해야 Hook이 진행률을 잡을 수 있음
            result = model.transcribe(
                wav_path,
                language="ko",
                vad=True, # Faster-Whisper 내장 VAD 사용
                verbose=True,
                initial_prompt=initial_prompt,
                temperature=0.0,
                condition_on_previous_text=False,
                compression_ratio_threshold=2.4,
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0
            )
            
            # MLX 결과 포맷과 호환되도록 딕셔너리로 변환
            output = result.to_dict()

        # stdout 복구
        sys.stdout = hook.terminal
        
        # 결과를 큐에 담아 부모 프로세스로 전송
        result_queue.put({"status": "success", "data": output})
        print(f"[Whisper Worker] PID {os.getpid()} finished successfully.")
        
    except Exception as e:
        # 에러 발생 시 부모에게 알림
        sys.stdout = sys.__stdout__ # 혹시 모르니 표준출력 복구
        print(f"[Whisper Worker] Error: {e}")
        result_queue.put({"status": "error", "message": str(e)})
        
        # [Add] 에러 로그 파일 기록 및 Traceback 보존
        try:
            from services.logger import get_logger, log_error_with_traceback
            logger = get_logger()
            log_error_with_traceback(logger, f"[Whisper Worker] Inference crashed in worker process {os.getpid()}", e)
        except Exception:
            # 임포트 문제 등으로 로깅 모듈이 실패할 경우를 대비한 로컬 백업 로깅
            try:
                import traceback
                log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "logs")
                os.makedirs(log_dir, exist_ok=True)
                backup_log = os.path.join(log_dir, f"worker_crash_{os.getpid()}.log")
                with open(backup_log, "w", encoding="utf-8") as f:
                    f.write(f"Worker Exception: {str(e)}\n\nTraceback:\n{traceback.format_exc()}")
            except Exception:
                pass
    finally:
        # [Add] 워커 프로세스 종료 전 메모리 정리
        gc.collect()
        # MLX의 경우 별도의 cache clear 명령어가 없으나 gc로 어느 정도 해소 가능

class VideoTranscriber:
    """
    영상 파일에서 오디오를 추출하고, Whisper 모델을 통해 텍스트로 변환(STT)하는 클래스.
    VAD(Voice Activity Detection)를 통해 환각(Hallucination)을 제거하고,
    Web UI에서 사용하기 쉬운 JSON 구조와 다운로드용 SRT 파일을 생성합니다.
    """

    def __init__(self, output_dir="static/results"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_model(self):
        """설정 매니저를 통해 실시간으로 모델명을 가져옵니다."""
        return ConfigManager.get_model("whisper")

    def _convert_to_16k_wav(self, input_path, task_manager=None, task_id=None):
        """
        FFmpeg를 사용하여 영상을 16kHz Mono WAV로 변환하며, stderr을 파싱해 진행률을 보고합니다.
        """
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_wav = os.path.join(self.output_dir, f"{base_name}_temp.wav")
        
        # 1. 전체 영상 길이(Duration) 확인 (ffprobe 사용)
        total_duration = 1.0
        try:
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration", 
                "-of", "default=noprint_wrappers=1:nokey=1", input_path
            ]
            duration_str = subprocess.check_output(probe_cmd).decode().strip()
            total_duration = float(duration_str)
        except Exception:
            print("[Transcriber] Failed to get duration via ffprobe, progress will be inaccurate.")

        # 2. FFmpeg 변환 시작 (Audio Preprocessing 적용)
        # - highpass=f=200: 웅웅거리는 저음 노이즈(Rumble) 제거
        # - lowpass=f=8000: 치찰음 등 고주파 노이즈 제거
        # - afftdn=nf=-25: FFT 기반 노이즈 제거 (White Noise 감소)
        # - loudnorm: 음량을 방송 표준(-16 LUFS)으로 정규화하여 작은 소리 증폭
        cmd = [
            "ffmpeg", "-i", input_path,
            "-vn", 
            "-ac", "1", 
            "-ar", "16000",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a", "pcm_s16le", 
            output_wav, "-y", "-hide_banner", "-loglevel", "info"
        ]
        
        try:
            # stderr=subprocess.PIPE를 통해 출력을 읽을 준비
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.PIPE,
                universal_newlines=True, # 텍스트 모드로 읽기
                encoding='utf-8',
                errors='replace'
            )
            
            # 3. 로그 파싱 Loop
            while True:
                # [Check Cancel]
                if task_manager and task_id and task_manager.is_cancelled(task_id):
                    process.terminate()
                    process.wait()
                    if os.path.exists(output_wav): os.remove(output_wav)
                    raise TaskCancelledError("Audio conversion cancelled")

                # 한 줄 읽기 (Blocking이지만 짧은 로그라 괜찮음)
                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break # 프로세스 종료됨
                
                if line:
                    # time=00:00:15.40 패턴 찾기
                    time_match = re.search(r'time=(\d{2}:\d{2}:\d{2}\.\d+)', line)
                    if time_match and total_duration > 0:
                        time_str = time_match.group(1)
                        h, m, s = time_str.split(':')
                        seconds = int(h) * 3600 + int(m) * 60 + float(s)
                        
                        percent = int((seconds / total_duration) * 100)
                        
                        # TaskManager에 업데이트 (구간: 0~20%)
                        # FFmpeg의 0~100%를 전체 파이프라인의 0~20%로 매핑
                        scaled_percent = int(percent * 0.2)
                        if task_manager and task_id:
                            task_manager.update_progress(task_id, scaled_percent, f"오디오 추출 중... ({percent}%)")

            # 4. 결과 확인
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd)
                
            return output_wav

        except subprocess.CalledProcessError as e:
            print(f"[Error] FFmpeg conversion failed: {e}")
            return None
        except Exception as e:
            raise e


    def _get_vad_timestamps(self, audio_path):
        """Silero VAD를 사용하여 실제 음성이 있는 구간(초 단위)을 추출 (별도 프로세스로 분리)"""
        ctx = multiprocessing.get_context('spawn')
        queue = ctx.Queue()
        
        worker_process = ctx.Process(
            target=run_vad_worker,
            args=(audio_path, queue),
        )
        worker_process.start()
        
        output = None
        while worker_process.is_alive():
            if not queue.empty():
                msg = queue.get()
                if msg["status"] == "success":
                    output = msg["data"]
                    break
                elif msg["status"] == "error":
                    print(f"[Warning] VAD execution failed: {msg['message']}")
                    break
            time.sleep(0.1)
            
        worker_process.join()
        
        # 잔여 메시지 확인
        if not output and not queue.empty():
            msg = queue.get()
            if msg["status"] == "success":
                output = msg["data"]
            
        return output

    def _filter_hallucinations(self, whisper_segments, vad_segments):
        """Whisper 세그먼트가 VAD 구간과 겹치지 않으면(환각이면) 제거"""
        if vad_segments is None: 
            return whisper_segments # VAD 실행 오류 시 안전장치로 필터 통과
        if not vad_segments: 
            return [] # VAD가 정상 구동되었으나 음성이 감지되지 않은 경우 환각 차단
        
        valid_segments = []
        for seg in whisper_segments:
            w_start, w_end = seg['start'], seg['end']
            duration = w_end - w_start
            if duration <= 0: continue

            # 교집합(Overlap) 시간 계산
            overlap_sum = 0.0
            for v_start, v_end in vad_segments:
                o_start = max(w_start, v_start)
                o_end = min(w_end, v_end)
                if o_end > o_start:
                    overlap_sum += (o_end - o_start)
            
            # 기준: 음성 비율이 20% 이상이거나, 절대 음성 길이가 2.0초 이상이면 통과
            if (overlap_sum / duration >= 0.2) or (overlap_sum >= 2.0):
                valid_segments.append(seg)
                
        return valid_segments

    # [Add] 이 메서드를 클래스 내부에 새로 추가하세요. (_filter_hallucinations 밑 추천)
    def _sanitize_segments(self, segments):
        """
        [Sanitizer v3] 강력한 중복 제거 및 타임스탬프 교정
        - 긴 영상에서 발생하는 슬라이딩 윈도우 중복(Sliding Window Duplication)을 제거합니다.
        - 띄어쓰기 오차를 제거한 텍스트 유사도 검사를 통해 겹치는 구간을 병합하거나 삭제합니다.
        - stable_whisper 빌드 시 발생할 수 있는 타임스탬프 순서 역행(Timestamps not in ascending order)을
          방지하기 위해 세그먼트 간 및 단어 단위 타임스탬프에 단조성(Monotonicity)을 강제합니다.
        """
        if not segments:
            return []

        import copy
        # deep copy를 수행하여 원본 데이터 조작 방지
        segments = copy.deepcopy(segments)

        # 1. 무조건 시작 시간순 정렬 (ID 순서 무시)
        segments.sort(key=lambda x: x['start'])

        sanitized = []
        
        for current in segments:
            # 유효성 검사 1: 종료 시간이 시작 시간보다 빨라선 안 됨 (역행 방지)
            if current['end'] <= current['start']:
                continue

            # 첫 세그먼트는 무조건 추가
            if not sanitized:
                sanitized.append(current)
                continue

            prev = sanitized[-1]

            # 2. 중첩(Overlap) 감지
            # 허용 오차(tolerance) 0.1초: 미세한 겹침은 무시하되, 큰 겹침은 처리
            if prev['end'] > current['start'] + 0.1:
                # 띄어쓰기 차이로 인한 매칭 실패를 막기 위해 공백 제거 정규화 적용
                prev_text_norm = re.sub(r'\s+', '', prev['text'])
                curr_text_norm = re.sub(r'\s+', '', current['text'])
                
                # (A) 텍스트 중복 검사 (핵심)
                if curr_text_norm in prev_text_norm or prev_text_norm in curr_text_norm:
                    # 더 긴 쪽을 유지 (정보량이 많은 쪽)
                    if len(curr_text_norm) > len(prev_text_norm):
                        sanitized.pop()
                        sanitized.append(current)
                    continue # 현재 루프 건너뜀 (현재 세그먼트 삭제 효과)

                # (B) 시간 조정 (Trimming)
                # 텍스트는 다르지만 시간이 겹침 -> 이전 세그먼트를 잘라서 겹침 해소
                prev['end'] = current['start']
                if prev['end'] - prev['start'] < 0.2:
                    sanitized.pop()
            
            sanitized.append(current)

        # 3. 단조성 강제 및 단어 타임스탬프 동기화 (Timestamp Enforcer)
        final_sanitized = []
        for seg in sanitized:
            # 세그먼트 자체의 최소 길이 보장 (10ms 미만 제거)
            if seg['end'] - seg['start'] < 0.01:
                continue

            if final_sanitized:
                prev_seg = final_sanitized[-1]
                if prev_seg['end'] > seg['start']:
                    # 겹치는 경계를 정렬
                    prev_seg['end'] = seg['start']
                    # 이전 세그먼트의 변경된 경계에 맞춰 내부 단어들 재정렬
                    self._align_words_with_segment_bounds(prev_seg)
                    
                    # 만약 이전 세그먼트가 너무 짧아졌다면 폐기
                    if prev_seg['end'] - prev_seg['start'] < 0.01:
                        final_sanitized.pop()

            self._align_words_with_segment_bounds(seg)
            final_sanitized.append(seg)

        return final_sanitized

    def _align_words_with_segment_bounds(self, seg):
        """
        세그먼트 내 단어들의 타임스탬프를 세그먼트의 start/end 경계 내로 조율하고,
        단어 간의 타임스탬프 단조성(Monotonicity)을 강제합니다.
        """
        if 'words' not in seg or not seg['words']:
            return

        valid_words = []
        seg_start = seg['start']
        seg_end = seg['end']

        for w in seg['words']:
            w_start = w['start']
            w_end = w['end']

            # 세그먼트 시간 범위를 완전히 벗어난 단어 필터링
            if w_start >= seg_end or w_end <= seg_start:
                continue

            # 경계 내로 클램핑 (Clamping)
            w_start = max(w_start, seg_start)
            w_end = min(w_end, seg_end)

            if w_end > w_start:
                w['start'] = w_start
                w['end'] = w_end
                valid_words.append(w)

        # 시작 시간 기준으로 재정렬
        valid_words.sort(key=lambda x: x['start'])

        # 단어들 간의 역행 방지 및 단조성 보장
        aligned_words = []
        for w in valid_words:
            if aligned_words:
                prev_w = aligned_words[-1]
                if prev_w['end'] > w['start']:
                    w['start'] = prev_w['end']
                
                if w['end'] <= w['start']:
                    continue
            aligned_words.append(w)

        seg['words'] = aligned_words

    def _remove_punctuation_from_subtitle_file(self, file_path):
        """
        주어진 자막 파일에서 문장 부호 (., ?, !, ,)를 제거하고 파일을 덮어씁니다.
        자막 시간 정보는 건드리지 않고, 텍스트 부분만 처리합니다.
        """
        if not os.path.exists(file_path):
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        cleaned_lines = []
        for line in lines:
            # 시간 정보가 포함된 라인은 건드리지 않음
            # 예: "00:00:00,000 --> 00:00:00,000" 또는 "00:00:00.000 --> 00:00:00.000"
            if re.match(r'^\d{2}:\d{2}:\d{2}[.,]\d{3} --> \d{2}:\d{2}:\d{2}[.,]\d{3}', line.strip()):
                cleaned_lines.append(line)
            # 자막 인덱스 (숫자만 있는 라인)도 건드리지 않음
            elif re.match(r'^\d+$', line.strip()):
                cleaned_lines.append(line)
            # WEBVTT 헤더 (VTT 파일용)도 건드리지 않음
            elif line.strip() == "WEBVTT":
                cleaned_lines.append(line)
            # 빈 줄도 유지
            elif not line.strip():
                cleaned_lines.append(line)
            # 그 외의 텍스트 라인에서만 문장 부호 제거
            else:
                cleaned_lines.append(re.sub(r'[.,?!]', '', line).strip() + '\n')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(cleaned_lines)

    def _clean_text(self, text):
        """반복되는 텍스트 및 무의미한 자모 제거"""
        if not text: return ""
        # 1. 유명한 환각 문구 제거
        for bad in ["아 아 아", "ㅋㅋㅋ", "으으으"]:
            text = text.replace(bad, "")
        # 2. 반복 문자 축소 (예: ㅋㅋㅋㅋㅋㅋ -> ㅋㅋ)
        text = re.sub(r'(.)\1{3,}', r'\1\1', text)
        # 3. 반복 단어 축소
        text = re.sub(r'(\S+)(?:\s+\1){3,}', r'\1 \1', text)
        return text.strip()

    def _check_cancel(self, task_manager, task_id):
        """
        작업 취소 여부를 확인하고, 취소되었다면 예외를 발생시킵니다.
        """
        if task_manager and task_id:
            if task_manager.is_cancelled(task_id):
                print(f"--- [Transcriber] Task {task_id} cancelled by user. ---")
                raise TaskCancelledError("User cancelled the task.")

    # [Modify] 시그니처 변경: task_manager와 task_id를 선택적 인자로 받음
    def transcribe(
        self,
        video_path,
        progress_callback=None,
        task_manager=None,
        task_id=None,
        content_type: str = "sermon",
    ):
        """
        [Main Pipeline] 프로세스 격리 + 정밀 진행률 추적이 적용된 Transcribe 메서드
        """
        # [Add] 로거 로딩 및 시작 로그 기록
        try:
            from services.logger import get_logger
            logger = get_logger()
            logger.info(f"--- [Transcriber] Start processing: {video_path} (Task ID: {task_id}) ---")
        except Exception:
            logger = None
            print(f"--- [Transcriber] Start processing: {video_path} ---")
            
        profile = get_content_profile(content_type)
        
        self._check_cancel(task_manager, task_id)
        
        # 1. 오디오 변환 (FFmpeg 내부에서 0~20% 진행률 자동 업데이트)
        # progress_callback은 여기서 쓰지 않고 FFmpeg 내부 로직이 task_manager를 직접 호출함
        wav_path = self._convert_to_16k_wav(video_path, task_manager, task_id)
        if not wav_path:
            exc = Exception("Audio conversion failed (FFmpeg returned None or failed)")
            if logger:
                logger.error(f"[Transcriber] FFmpeg conversion failed for {video_path}")
                if task_id:
                    from services.logger import log_task_error
                    log_task_error(task_id, "audio_conversion", exc)
            raise exc

        try:
            self._check_cancel(task_manager, task_id)

            # [New] 오디오 길이 계산 (Whisper 진행률 계산용)
            try:
                audio_info = sf.info(wav_path)
                total_duration = audio_info.duration
                if logger:
                    logger.info(f"[Transcriber] Audio duration: {total_duration:.2f} seconds")
            except Exception as e:
                total_duration = 100 # Fallback
                if logger:
                    logger.warning(f"[Transcriber] Failed to calculate audio duration: {e}. Fallback to 100s.")

            # 2. VAD 실행
            if progress_callback: progress_callback(20, "음성 구간 탐지(VAD) 실행 중...")
            vad_segments = self._get_vad_timestamps(wav_path)
            if logger:
                logger.info(f"[Transcriber] VAD completed. Detected {len(vad_segments)} speech segments.")
            
            self._check_cancel(task_manager, task_id)
            if progress_callback: progress_callback(25, "AI 자막 생성 준비 중...")
            
            # 3. Whisper 실행
            if logger:
                logger.info(f" -> Spawning Whisper Worker Process for {video_path}")
            else:
                print(" -> Spawning Whisper Worker Process...")
            ctx = multiprocessing.get_context('spawn')
            queue = ctx.Queue()
            
            # [New] total_duration을 인자로 전달
            worker_process = ctx.Process(
                target=run_whisper_worker,
                args=(wav_path, self._get_model(), queue, total_duration, profile.asr_initial_prompt, sys.path),
            )
            worker_process.start()
            
            # [Supervisor Loop] 자식 프로세스 감시 및 메시지 처리
            output = None
            
            while worker_process.is_alive():
                # (A) 취소 확인
                if task_manager and task_id and task_manager.is_cancelled(task_id):
                    worker_process.terminate()
                    worker_process.join(timeout=1)
                    if worker_process.is_alive(): worker_process.kill()
                    raise TaskCancelledError("Whisper inference cancelled by user")
                
                # (B) Queue 메시지 처리 (Non-blocking)
                while not queue.empty():
                    msg = queue.get()
                    if msg["status"] == "progress":
                        # Worker의 0~100%를 전체의 25~85% 구간에 매핑
                        local_pct = msg["percent"]
                        global_pct = 25 + int(local_pct * 0.6)
                        
                        if progress_callback:
                            progress_callback(global_pct, f"자막 생성 중... ({local_pct}%)")
                    
                    elif msg["status"] == "success":
                        output = msg["data"]
                        break # 성공 메시지 받으면 루프 탈출 가능 (프로세스는 곧 죽음)
                        
                    elif msg["status"] == "error":
                        raise Exception(f"Worker Error: {msg.get('message')}")

                if output: break # 결과 받았으면 루프 종료
                time.sleep(0.1) # CPU 과부하 방지

            # 프로세스 종료 대기
            worker_process.join()

            if not output and queue.empty():
                 # 큐에 남은 메시지 한번 더 확인 (프로세스 종료 직전 보낸 것)
                 if not queue.empty():
                    msg = queue.get()
                    if msg["status"] == "success": output = msg["data"]
                    elif msg["status"] == "error": raise Exception(f"Worker Error: {msg.get('message')}")
            
            if not output:
                 exc = Exception(f"Whisper process crashed with exit code {worker_process.exitcode}")
                 if logger:
                     logger.error(f"[Transcriber] Whisper Worker process crashed. exitcode={worker_process.exitcode}")
                 raise exc
            
            if logger:
                logger.info(f"[Transcriber] Whisper Worker process completed successfully.")
            
            # 4. 후처리 (85% ~ 100%)
            if progress_callback: progress_callback(85, "데이터 정제 및 저장 중...")
            
            raw_segments = output.get('segments', [])
            clean_segments = self._filter_hallucinations(raw_segments, vad_segments)
            for seg in clean_segments:
                if 'text' in seg: seg['text'] = self._clean_text(seg['text'])
            clean_segments = self._sanitize_segments(clean_segments)

            # 저장 로직 (Stable Whisper)
            composition = {
                "text": " ".join([s['text'] for s in clean_segments]),
                "segments": clean_segments,
                "language": output.get("language", "ko")
            }
            result_obj = stable_whisper.WhisperResult(composition)
            result_obj.split_by_length(max_chars=25, max_words=None)
            result_obj.split_by_gap(0.5)

            base_name = os.path.splitext(os.path.basename(video_path))[0]
            srt_path = os.path.join(self.output_dir, f"{base_name}.srt")
            vtt_path = os.path.join(self.output_dir, f"{base_name}.vtt")
            json_path = os.path.join(self.output_dir, f"{base_name}_transcript.json")

            # [Step 1] JSON 저장 (원본 텍스트 유지 및 단어 단위 데이터 포함)
            final_data = []
            for idx, seg in enumerate(result_obj.segments, 1):
                segment_info = {
                    "id": idx,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "words": [] # 단어 단위 데이터 추가
                }
                
                # 각 세그먼트 내의 단어들 정보 추출
                if hasattr(seg, 'words') and seg.words:
                    for w in seg.words:
                        segment_info["words"].append({
                            "word": w.word.strip(),
                            "start": w.start,
                            "end": w.end
                        })
                
                final_data.append(segment_info)

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(final_data, f, ensure_ascii=False, indent=2)

            # [Step 2] 자막 파일 생성 및 후처리 (문장 부호 제거 - 자막용)
            # stable_whisper로 자막 파일 우선 생성
            result_obj.to_srt_vtt(srt_path, word_level=False)
            result_obj.to_srt_vtt(vtt_path, word_level=False)

            # 생성된 자막 파일에서 문장 부호 제거 후 덮어쓰기
            self._remove_punctuation_from_subtitle_file(srt_path)
            self._remove_punctuation_from_subtitle_file(vtt_path)

            if logger:
                logger.info(f"--- [Transcriber] Done. Saved results to {self.output_dir} ---")
            else:
                print(f"--- [Transcriber] Done. Saved to {self.output_dir} ---")
            return {
                "status": "success",
                "srt_path": srt_path,
                "vtt_path": vtt_path,
                "json_path": json_path,
                "segments": final_data 
            }

        except TaskCancelledError as e:
            try:
                if logger:
                    logger.info(f"[Transcriber] Task {task_id} was cancelled by user.")
            except Exception:
                pass
            print(f"[Transcriber] Cleanup initiated for task {task_id}")
            raise e

        except Exception as e:
            try:
                from services.logger import log_error_with_traceback, log_task_error
                if logger:
                    log_error_with_traceback(logger, f"Transcription pipeline failed for: {video_path}", e)
                if task_id:
                    log_task_error(task_id, "transcribe", e)
            except Exception as log_err:
                print(f"[Backup Warning] Failed to write pipeline error log: {log_err}")
            raise e

        finally:
            # [Add] 최종 메모리 정리
            if 'result_obj' in locals(): del result_obj
            if 'output' in locals(): del output
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            if 'wav_path' in locals() and os.path.exists(wav_path):
                os.remove(wav_path)

# --- [Module Test] ---
if __name__ == "__main__":
    # Test execution
    tr = VideoTranscriber(output_dir="../static/results")
    # Make sure a test file exists at this path
    test_video = "../static/videos/test_video.mp4" 
    if os.path.exists(test_video):
        res = tr.transcribe(test_video)
        print(f"Result segments count: {len(res['segments'])}")
