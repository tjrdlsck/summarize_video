import os
import subprocess
import re
import json
import torch
import mlx_whisper
import soundfile as sf
import numpy as np
import stable_whisper
import time
import multiprocessing

class TaskCancelledError(Exception):
    """작업이 사용자에 의해 취소되었을 때 발생하는 예외"""
    pass

def run_whisper_worker(wav_path, model_path, result_queue):
    """
    [Worker Process] 별도 프로세스에서 실행되는 Whisper 추론 함수입니다.
    메인 프로세스와의 격리를 통해, 언제든 외부에서 강제 종료(Kill)할 수 있습니다.
    """
    try:
        print(f"[Whisper Worker] PID {os.getpid()} started processing...")
        
        # MLX Whisper 추론 실행
        # (옵션은 클래스와 동일하게 유지)
        output = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=model_path,
            language="ko",
            verbose=True, 
            word_timestamps=True,
            condition_on_previous_text=False,
            temperature=(0.0, 0.2, 0.4) 
        )
        
        # 결과를 큐에 담아 부모 프로세스로 전송
        result_queue.put({"status": "success", "data": output})
        print(f"[Whisper Worker] PID {os.getpid()} finished successfully.")
        
    except Exception as e:
        # 에러 발생 시 부모에게 알림
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
        # Whisper 모델 설정 (Apple Silicon 최적화 모델 사용)
        # self.model_path = "mlx-community/whisper-large-v3-mlx-4bit"
        self.model_path = "mlx-community/whisper-large-v3-turbo-q4"

    def _convert_to_16k_wav(self, input_path, task_manager=None, task_id=None):
        """
        FFmpeg를 사용하여 영상을 16kHz Mono WAV로 변환합니다.
        [수정] 변환 도중 취소 가능하도록 Polling Loop 적용
        """
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_wav = os.path.join(self.output_dir, f"{base_name}_temp.wav")

        cmd = [
            "ffmpeg", "-i", input_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-vn",
            output_wav, "-y", "-hide_banner", "-loglevel", "error"
        ]
        
        try:
            # 1. Popen으로 프로세스 시작 (Non-blocking)
            process = subprocess.Popen(cmd)
            
            # 2. 종료될 때까지 감시 (Polling)
            while process.poll() is None:
                # [Check Cancel]
                if task_manager and task_id and task_manager.is_cancelled(task_id):
                    process.terminate() # 프로세스 사살
                    process.wait()      # 자원 회수
                    if os.path.exists(output_wav):
                        os.remove(output_wav)
                    print(f"--- [Transcriber] Audio conversion cancelled for {task_id}")
                    raise TaskCancelledError("Audio conversion cancelled")
                
                time.sleep(0.1) # CPU 과부하 방지
            
            # 3. 결과 확인
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd)
                
            return output_wav

        except subprocess.CalledProcessError as e:
            print(f"[Error] FFmpeg conversion failed: {e}")
            return None
        except Exception as e:
            # TaskCancelledError는 상위로 전파
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
        [Main Pipeline] 프로세스 격리(Isolation)가 적용된 안전한 Transcribe 메서드
        """
        print(f"--- [Transcriber] Start processing: {video_path} ---")
        
        # [Checkpoint 1] 시작 전 확인
        self._check_cancel(task_manager, task_id)
        
        if progress_callback: progress_callback(0, "오디오 변환 준비 중...")
        
        # 1. 오디오 변환 (이전 단계에서 적용한 Polling 방식 사용)
        wav_path = self._convert_to_16k_wav(video_path, task_manager, task_id)
        if not wav_path: raise Exception("Audio conversion failed")

        try:
            # [Checkpoint 2] 오디오 변환 직후 확인
            self._check_cancel(task_manager, task_id)

            if progress_callback: progress_callback(10, "오디오 변환 완료")

            # 2. VAD 실행
            if progress_callback: progress_callback(15, "음성 구간 탐지(VAD) 실행 중...")
            vad_segments = self._get_vad_timestamps(wav_path)
            
            # [Checkpoint 3] VAD 완료 후 확인
            self._check_cancel(task_manager, task_id)
            
            if progress_callback: progress_callback(30, "음성 구간 분석 완료")
            
            # 3. Whisper 실행 (Process Isolation)
            print(" -> Spawning Whisper Worker Process...")
            if progress_callback: progress_callback(35, "AI 자막 생성 시작 (시간이 소요됩니다)...")
            
            # 결과 통신을 위한 큐 생성
            queue = multiprocessing.Queue()
            
            # 자식 프로세스 생성 및 시작
            worker_process = multiprocessing.Process(
                target=run_whisper_worker,
                args=(wav_path, self.model_path, queue)
            )
            worker_process.start()
            
            # [Supervisor Loop] 자식 프로세스 감시 및 취소 제어
            worker_failed = False
            output = None
            
            while worker_process.is_alive():
                # (A) 취소 요청 확인
                if task_manager and task_id and task_manager.is_cancelled(task_id):
                    print(f"--- [Supervisor] Killing Whisper Worker (PID {worker_process.pid}) ---")
                    worker_process.terminate()  # 1차 경고 (SIGTERM)
                    worker_process.join(timeout=1)
                    if worker_process.is_alive():
                        worker_process.kill()   # 2차 사살 (SIGKILL)
                    
                    raise TaskCancelledError("Whisper inference cancelled by user")
                
                # (B) CPU 과부하 방지
                time.sleep(0.5)

            # 프로세스 종료 후 결과 확인
            if not queue.empty():
                result = queue.get()
                if result["status"] == "success":
                    output = result["data"]
                else:
                    raise Exception(f"Worker Error: {result.get('message')}")
            else:
                # 큐가 비었는데 프로세스가 죽음 (OOM, Crash 등)
                if worker_process.exitcode != 0:
                     raise Exception(f"Whisper process crashed with exit code {worker_process.exitcode}")
            
            # [Milestone 90%] 추론 완료
            if progress_callback: progress_callback(90, "데이터 정제 및 타임스탬프 교정 중...")
            
            # 4. 필터링 및 정제 (기존 로직 유지)
            raw_segments = output.get('segments', [])
            clean_segments = self._filter_hallucinations(raw_segments, vad_segments)
            for seg in clean_segments:
                if 'text' in seg: seg['text'] = self._clean_text(seg['text'])
            clean_segments = self._sanitize_segments(clean_segments)

            # 5. 저장 로직 (Stable Whisper 후처리)
            composition = {
                "text": " ".join([s['text'] for s in clean_segments]),
                "segments": clean_segments,
                "language": output.get("language", "ko")
            }
            result_obj = stable_whisper.WhisperResult(composition)
            result_obj.split_by_length(max_chars=25, max_words=None)
            result_obj.split_by_gap(0.5)

            # 파일 쓰기
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            srt_path = os.path.join(self.output_dir, f"{base_name}.srt")
            vtt_path = os.path.join(self.output_dir, f"{base_name}.vtt")
            json_path = os.path.join(self.output_dir, f"{base_name}_transcript.json")

            result_obj.to_srt_vtt(srt_path, word_level=False)
            result_obj.to_srt_vtt(vtt_path, word_level=False)

            # JSON 데이터 구성
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

            print(f"--- [Transcriber] Done. Saved to {self.output_dir} ---")
            
            if progress_callback: progress_callback(100, "자막 생성 완료")
            
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
            # [중요] 임시 wav 파일은 반드시 삭제
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