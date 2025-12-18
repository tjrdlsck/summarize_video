import os
import subprocess
import re
import json
import torch
import soundfile as sf
import numpy as np
import stable_whisper
import time
import multiprocessing
import sys
import platform  # [Add] 플랫폼 감지용

# [New] MLX Whisper (Mac용) - 조건부 임포트
try:
    import mlx_whisper
except ImportError:
    mlx_whisper = None

# [New] NVIDIA Worker (Windows/Linux용) - 조건부 임포트
try:
    from services.transcriber_runner import run_faster_whisper_worker
except ImportError:
    run_faster_whisper_worker = None

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

def run_whisper_worker(wav_path, model_path, result_queue, total_duration):
    """
    [Worker Process] 별도 프로세스에서 실행되는 Whisper 추론 함수입니다.
    stdout을 캡처하여 진행률을 실시간으로 보고합니다.
    """
    try:
        print(f"[Whisper Worker] PID {os.getpid()} started processing...")
        
        # [New] stdout을 Hook 클래스로 리다이렉트
        # 이제부터 print()나 라이브러리의 stdout 출력은 hook.write()로 전달됨
        hook = WhisperProgressHook(result_queue, total_duration)
        sys.stdout = hook
        
        # MLX Whisper 추론 실행
        output = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=model_path,
            language="ko",
            verbose=True,  # [중요] True여야 타임스탬프 로그가 출력되어 Hook이 작동함
            word_timestamps=True,
            condition_on_previous_text=False,
            temperature=(0.0, 0.2, 0.4) 
        )
        
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

class VideoTranscriber:
    """
    영상 파일에서 오디오를 추출하고, Whisper 모델을 통해 텍스트로 변환(STT)하는 클래스.
    VAD(Voice Activity Detection)를 통해 환각(Hallucination)을 제거하고,
    Web UI에서 사용하기 쉬운 JSON 구조와 다운로드용 SRT 파일을 생성합니다.
    """

    def __init__(self, output_dir="static/results"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        # [New] Hardware Detection Logic
        self.mode = "cpu"  # 기본값
        
        try:
            if torch.cuda.is_available():
                self.mode = "nvidia"
                print(f"[Transcriber] NVIDIA GPU Detected. Mode: {self.mode}")
            elif platform.system() == "Darwin" and platform.processor() == "arm":
                self.mode = "mac"
                print(f"[Transcriber] Apple Silicon Detected. Mode: {self.mode}")
        except Exception as e:
            print(f"[Transcriber] Hardware detection failed: {e}. Fallback to CPU.")

        # Model Configuration
        if self.mode == "mac":
            # Mac: MLX용 모델 경로
            self.model_path = "mlx-community/whisper-large-v3-turbo-q4"
            # self.model_path = "mlx-community/whisper-large-v3-mlx-4bit"
        elif self.mode == "nvidia":
            # NVIDIA: Faster-Whisper용 모델 사이즈 문자열
            self.model_path = "large-v3"
        else:
            # Fallback (CPU)
            self.model_path = "base"

    def _transcribe_nvidia(self, wav_path, progress_callback, task_manager, task_id):
        """
        [NVIDIA Mode] Multiprocessing을 사용하여 Faster-Whisper 워커 실행
        """
        print(" -> Spawning Faster-Whisper Worker (NVIDIA)...")
        queue = multiprocessing.Queue()
        
        # 워커 프로세스 생성 (2단계에서 만든 함수 실행)
        worker_process = multiprocessing.Process(
            target=run_faster_whisper_worker,
            args=(wav_path, self.model_path, queue, "int8") # int8 양자화 사용
        )
        worker_process.start()
        
        output = None
        
        # Supervisor Loop
        while worker_process.is_alive():
            # (A) 취소 확인
            if task_manager and task_id and task_manager.is_cancelled(task_id):
                worker_process.terminate()
                worker_process.join(timeout=1)
                if worker_process.is_alive(): worker_process.kill()
                raise TaskCancelledError("NVIDIA inference cancelled by user")
            
            # (B) Queue 처리
            while not queue.empty():
                msg = queue.get()
                if msg["status"] == "progress":
                    # 워커 진행률(0~100) -> 전체 파이프라인(20~85) 매핑
                    local_pct = msg["percent"]
                    global_pct = 20 + int(local_pct * 0.65)
                    if progress_callback:
                        progress_callback(global_pct, f"자막 생성 중 (CUDA)... ({local_pct}%)")
                
                elif msg["status"] == "success":
                    output = msg["data"]
                    break
                
                elif msg["status"] == "error":
                    raise Exception(f"NVIDIA Worker Error: {msg.get('message')}")
            
            if output: break
            time.sleep(0.1)
            
        worker_process.join()
        
        # 프로세스가 끝났는데 output이 없는 경우 (큐 잔여 확인)
        if not output and not queue.empty():
             msg = queue.get()
             if msg["status"] == "success": output = msg["data"]

        if not output:
             raise Exception("Faster-Whisper worker failed without result.")
             
        return output

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

        # 2. FFmpeg 변환 시작
        cmd = [
            "ffmpeg", "-i", input_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-vn",
            output_wav, "-y", "-hide_banner", "-loglevel", "info" # [Change] info 레벨이어야 time= 로그가 나옴
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
        """Silero VAD를 사용하여 실제 음성이 있는 구간(초 단위)을 추출"""
        try:
            model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                          model='silero_vad',
                                          force_reload=False,
                                          trust_repo=True)
            (get_speech_timestamps, _, _, _, _) = utils
            
            audio_data, sr = sf.read(audio_path)
            wav = torch.from_numpy(audio_data).float()
            
            # 차원 및 샘플링 레이트 보정
            if wav.ndim > 1: wav = wav.mean(dim=0, keepdim=True) # Stereo -> Mono
            if wav.ndim == 1: wav = wav.unsqueeze(0)
            
            speech_timestamps = get_speech_timestamps(wav, model, threshold=0.5)
            
            # Sample -> Seconds 변환
            segments = []
            for item in speech_timestamps:
                segments.append((item['start'] / 16000, item['end'] / 16000))
            
            return segments
        except Exception as e:
            print(f"[Warning] VAD execution failed: {e}")
            return []

    def _filter_hallucinations(self, whisper_segments, vad_segments):
        """Whisper 세그먼트가 VAD 구간과 겹치지 않으면(환각이면) 제거"""
        if not vad_segments: return whisper_segments
        
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
        [Sanitizer v2] 강력한 중복 제거 및 타임스탬프 교정
        - 긴 영상에서 발생하는 슬라이딩 윈도우 중복(Sliding Window Duplication)을 제거합니다.
        - 텍스트 유사도를 검사하여 겹치는 구간을 병합하거나 삭제합니다.
        """
        if not segments:
            return []

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
                overlap_duration = prev['end'] - current['start']
                
                # (A) 텍스트 중복 검사 (핵심)
                # 앞 문장의 뒷부분과 뒷 문장의 앞부분이 겹치는지 확인
                prev_text = prev['text'].strip()
                curr_text = current['text'].strip()
                
                # 텍스트가 완전히 포함되거나 매우 유사하면 -> 현재 세그먼트 삭제 (Duplicate)
                if curr_text in prev_text or prev_text in curr_text:
                    # 더 긴 쪽을 유지 (정보량이 많은 쪽)
                    if len(curr_text) > len(prev_text):
                        sanitized.pop()
                        sanitized.append(current)
                    continue # 현재 루프 건너뜀 (삭제 효과)

                # (B) 시간 조정 (Trimming)
                # 텍스트는 다르지만 시간이 겹침 -> 이전 세그먼트를 잘라서 겹침 해소
                # 단, 이전 세그먼트가 너무 짧아지면(0.2초 미만) 삭제
                prev['end'] = current['start']
                if prev['end'] - prev['start'] < 0.2:
                    sanitized.pop()
            
            sanitized.append(current)

        return sanitized

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
    def transcribe(self, video_path, progress_callback=None, task_manager=None, task_id=None):
        """
        [Main Pipeline] Hardware-aware Transcribe
        하드웨어 모드(NVIDIA vs Mac/CPU)에 따라 최적화된 추론 엔진을 선택하여 실행합니다.
        """
        print(f"--- [Transcriber] Start processing ({self.mode}): {video_path} ---")
        
        self._check_cancel(task_manager, task_id)
        
        # 1. 오디오 변환 (공통) - FFmpeg가 0~20% 진행률 담당
        wav_path = self._convert_to_16k_wav(video_path, task_manager, task_id)
        if not wav_path: raise Exception("Audio conversion failed")

        try:
            self._check_cancel(task_manager, task_id)
            output = None
            vad_segments = []

            # --- [Branch A: NVIDIA Mode] ---
            if self.mode == "nvidia":
                if progress_callback: progress_callback(20, "AI 모델 로딩 중 (CUDA)...")
                
                # Faster-Whisper는 내장 VAD 성능이 우수하므로 별도 VAD 단계 생략하고 바로 실행
                # 워커 프로세스 실행 (NVIDIA 전용)
                raw_result = self._transcribe_nvidia(wav_path, progress_callback, task_manager, task_id)
                
                # 결과 포맷 통일 (Stable Whisper 호환 구조로 변환)
                output = {
                    "segments": raw_result["segments"],
                    "language": raw_result.get("language", "ko"),
                    "text": raw_result.get("text", "")
                }

            # --- [Branch B: Mac / CPU Mode] ---
            else:
                # [New] 오디오 길이 계산 (진행률 표시용)
                try:
                    audio_info = sf.info(wav_path)
                    total_duration = audio_info.duration
                except Exception:
                    total_duration = 100.0

                # 2. VAD 실행 (Mac 모드일 때만 수행하여 환각 최소화)
                if progress_callback: progress_callback(20, "음성 구간 탐지(VAD) 실행 중...")
                vad_segments = self._get_vad_timestamps(wav_path)
                
                self._check_cancel(task_manager, task_id)
                if progress_callback: progress_callback(25, "AI 자막 생성 준비 중...")
                
                # 3. Whisper 실행 (기존 Mac/MLX 로직)
                print(" -> Spawning Whisper Worker Process (MLX)...")
                queue = multiprocessing.Queue()
                
                # 기존에 정의된 run_whisper_worker 함수 실행
                worker_process = multiprocessing.Process(
                    target=run_whisper_worker, 
                    args=(wav_path, self.model_path, queue, total_duration)
                )
                worker_process.start()
                
                # [Supervisor Loop for Mac] 자식 프로세스 감시 및 메시지 처리
                while worker_process.is_alive():
                    # (A) 취소 확인
                    if task_manager and task_id and task_manager.is_cancelled(task_id):
                        worker_process.terminate()
                        worker_process.join(timeout=1)
                        if worker_process.is_alive(): worker_process.kill()
                        raise TaskCancelledError("Whisper inference cancelled by user")
                    
                    # (B) Queue 메시지 처리
                    while not queue.empty():
                        msg = queue.get()
                        if msg["status"] == "progress":
                            # Mac Whisper 진행률(0~100) -> 전체 파이프라인(25~85) 매핑
                            local_pct = msg["percent"]
                            global_pct = 25 + int(local_pct * 0.6)
                            if progress_callback: 
                                progress_callback(global_pct, f"자막 생성 중... ({local_pct}%)")
                        
                        elif msg["status"] == "success":
                            output = msg["data"]
                            break # 성공 메시지 받으면 루프 탈출 가능
                            
                        elif msg["status"] == "error":
                            raise Exception(f"Worker Error: {msg.get('message')}")
                    
                    if output: break # 결과 받았으면 루프 종료
                    time.sleep(0.1) # CPU 과부하 방지
                
                worker_process.join()

                # 프로세스 종료 후 큐에 남은 메시지 확인
                if not output and not queue.empty():
                     msg = queue.get()
                     if msg["status"] == "success": output = msg["data"]
                     elif msg["status"] == "error": raise Exception(f"Worker Error: {msg.get('message')}")
                
                if not output: 
                    raise Exception("Whisper process failed or crashed.")

            # --- [Common: Post Processing] ---
            # 4. 후처리 (85% ~ 100%)
            if progress_callback: progress_callback(85, "데이터 정제 및 저장 중...")
            
            raw_segments = output.get('segments', [])
            
            # NVIDIA 모드가 아니면 VAD 기반 환각 필터링 적용 (Faster-Whisper는 이미 내부 VAD 적용됨)
            if self.mode != "nvidia":
                clean_segments = self._filter_hallucinations(raw_segments, vad_segments)
            else:
                clean_segments = raw_segments

            # 텍스트 정제
            for seg in clean_segments:
                if 'text' in seg: seg['text'] = self._clean_text(seg['text'])
            
            # 구간 중복 제거 및 시간 보정
            clean_segments = self._sanitize_segments(clean_segments)

            # 저장 로직 (Stable Whisper 활용)
            composition = {
                "text": " ".join([s['text'] for s in clean_segments]),
                "segments": clean_segments,
                "language": output.get("language", "ko")
            }
            result_obj = stable_whisper.WhisperResult(composition)
            
            # 자막 분할 규칙 적용 (가독성 향상)
            result_obj.split_by_length(max_chars=25, max_words=None)
            result_obj.split_by_gap(0.5)

            base_name = os.path.splitext(os.path.basename(video_path))[0]
            srt_path = os.path.join(self.output_dir, f"{base_name}.srt")
            vtt_path = os.path.join(self.output_dir, f"{base_name}.vtt")
            json_path = os.path.join(self.output_dir, f"{base_name}_transcript.json")

            # [Step 1] JSON 저장 (원본 텍스트 유지)
            final_data = []
            for idx, seg in enumerate(result_obj.segments, 1):
                final_data.append({
                    "id": idx,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip()
                })

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(final_data, f, ensure_ascii=False, indent=2)

            # [Step 2] 자막 파일 생성 (SRT, VTT)
            result_obj.to_srt_vtt(srt_path, word_level=False)
            result_obj.to_srt_vtt(vtt_path, word_level=False)

            # 문장 부호 제거 (선택 사항)
            self._remove_punctuation_from_subtitle_file(srt_path)
            self._remove_punctuation_from_subtitle_file(vtt_path)

            print(f"--- [Transcriber] Done. Saved to {self.output_dir} ---")
            return {
                "status": "success",
                "srt_path": srt_path,
                "vtt_path": vtt_path,
                "json_path": json_path,
                "segments": final_data 
            }

        except TaskCancelledError:
            print(f"[Transcriber] Cleanup initiated for task {task_id}")
            raise 

        finally:
            if os.path.exists(wav_path):
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