import os
import sys
import traceback
import time

# [주의] 이 파일은 NVIDIA 환경(faster-whisper 설치)에서만 실행되어야 합니다.
# Mac 환경에서 실수로 import 될 경우를 대비해 try-except 처리합니다.
try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

def run_faster_whisper_worker(audio_path, model_size, result_queue, compute_type="int8"):
    """
    [NVIDIA Worker Process]
    별도 프로세스에서 faster-whisper를 구동합니다.
    [Update] word_timestamps=True를 활성화하여 stable-whisper 호환성을 확보했습니다.
    """
    try:
        if WhisperModel is None:
            raise ImportError("faster_whisper module is not installed. Please install requirements-nvidia.txt")

        print(f"[Faster-Whisper Worker] PID {os.getpid()} initializing model: {model_size} ({compute_type})...")
        
        model = WhisperModel(
            model_size, 
            device="cuda", 
            compute_type=compute_type
        )
        
        print(f"[Faster-Whisper Worker] Model loaded. Starting transcription for: {audio_path}")

        # [수정 포인트 1] word_timestamps=True 추가
        # 단어 단위 타임스탬프를 추출해야 stable-whisper가 경고 없이 작동합니다.
        segments_generator, info = model.transcribe(
            audio_path, 
            beam_size=5, 
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=True,  # 핵심 수정 사항
            language="ko"
        )
        
        total_duration = info.duration
        if total_duration is None or total_duration <= 0:
            total_duration = 1.0

        result_segments = []
        
        for segment in segments_generator:
            # [수정 포인트 2] 단어 정보(words) 추출 및 구조화
            words_list = []
            if segment.words:
                for w in segment.words:
                    words_list.append({
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability
                    })

            # 결과 저장 (words 필드 추가)
            result_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": words_list  # stable-whisper를 위한 데이터
            })
            
            percent = int((segment.end / total_duration) * 100)
            percent = min(99, max(0, percent))
            
            result_queue.put({"status": "progress", "percent": percent})

        print(f"[Faster-Whisper Worker] Transcription finished. Total segments: {len(result_segments)}")
        
        final_data = {
            "segments": result_segments,
            "language": info.language,
            "duration": total_duration,
            "text": " ".join([s['text'] for s in result_segments])
        }
        
        result_queue.put({"status": "success", "data": final_data})

    except Exception as e:
        print(f"[Faster-Whisper Worker] Error: {e}")
        traceback.print_exc()
        result_queue.put({"status": "error", "message": str(e)})
    
    finally:
        try:
            del model
        except:
            pass