import os
import cv2
import json
import torch
import platform
import numpy as np
from scenedetect import detect, ContentDetector
from PIL import Image

# [Condition Import] 플랫폼별 추론 엔진 로드
try:
    if torch.cuda.is_available():
        # NVIDIA: Transformers + bitsandbytes(4/8bit) 가속
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
        from accelerate import Accelerator
    elif platform.system() == "Darwin" and platform.processor() == "arm":
        # Mac: MLX-VLM 가속
        import mlx_vlm
        from mlx_vlm.utils import load, generate
except ImportError:
    pass

class VisionAnalyzer:
    """
    Qwen3-VL 모델을 사용하여 영상의 시각적 맥락을 분석하는 클래스입니다.
    장면 전환 감지(VAD for Vision)를 통해 분석 효율을 높입니다.
    """
    def __init__(self, model_path="Qwen/Qwen2-VL-2B-Instruct"): # Qwen3-VL 정식 출시 전 Qwen2-VL 최신버전 기준
        self.device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
        self.model_path = model_path
        self.model = None
        self.processor = None
        
        print(f"[VisionAnalyzer] Initialized in {self.device} mode.")

    def _extract_keyframes(self, video_path, threshold=27.0):
        """
        [Segment-aware Extraction] 
        장면 전환 경계를 감지하여 각 샷(Shot)의 시작/종료 시간과 대표 프레임을 추출합니다.
        """
        print(f"[VisionAnalyzer] Detecting scene segments: {video_path}")
        # PySceneDetect의 ContentDetector를 사용하여 컷(Cut) 지점 탐지
        scene_list = detect(video_path, ContentDetector(threshold=threshold))
        
        scene_segments = []
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        for scene in scene_list:
            # 샷의 시작과 종료 프레임 번호 획득
            start_frame = scene[0].get_frames()
            end_frame = scene[1].get_frames()
            
            # 샷의 정중앙(Middle)을 대표 프레임(Keyframe)으로 선정 (안정성 확보)
            mid_frame = (start_frame + end_frame) // 2
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame)
            ret, frame = cap.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # 프레임 번호를 초(seconds) 단위 시간으로 변환
                start_time = start_frame / fps
                end_time = end_frame / fps
                
                scene_segments.append({
                    "start": start_time,
                    "end": end_time,
                    "duration": end_time - start_time,
                    "image": Image.fromarray(frame_rgb)
                })
        
        cap.release()
        print(f"[VisionAnalyzer] Identified {len(scene_segments)} segments.")
        return scene_segments

    def _analyze_frames_nvidia(self, keyframes, task_manager, task_id):
        """
        [Structured Multimodal Inference] 
        NVIDIA 가속을 사용하여 각 샷의 Action, Mood, Text를 정밀 분석합니다.
        """
        if self.model is None:
            from transformers import BitsAndBytesConfig
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True
            )
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                self.model_path, quantization_config=bnb_config, device_map="auto", trust_remote_code=True
            )
            self.processor = AutoProcessor.from_pretrained(
                self.model_path, min_pixels=128 * 28 * 28, max_pixels=480 * 28 * 28 
            )

        results = []
        for i, seg in enumerate(keyframes):
            if task_manager and task_id and task_manager.is_cancelled(task_id):
                break
            
            # [Prompt Engineering] 전문 에디터 페르소나 및 구조화된 요구사항 주입
            prompt = (
                "Analyze this video shot for professional editing. Answer in Korean.\n"
                "Format your response as follows:\n"
                "1. Action: Describe the main movement or event.\n"
                "2. Mood: Describe the visual atmosphere (lighting, color, emotion).\n"
                "3. Text: List all visible on-screen text or captions. (If none, write 'None')"
            )
            
            messages = [{"role": "user", "content": [{"type": "image", "image": seg['image']}, {"type": "text", "text": prompt}]}]
            text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            
            try:
                inputs = self.processor(text=[text], images=[seg['image']], padding=True, return_tensors="pt").to(self.device)
                # repetition_penalty를 통해 'system' 반복 출력 오류 방지
                output_ids = self.model.generate(**inputs, max_new_tokens=128, repetition_penalty=1.2, do_sample=False)
                
                # 입력 토큰을 제외한 순수 생성 토큰만 슬라이싱
                generated_ids = output_ids[:, inputs.input_ids.shape[1]:]
                raw_output = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

                # [Parsing Logic] 결과를 구조화된 딕셔너리로 분리
                lines = raw_output.split('\n')
                action = next((l.split('Action:')[1] for l in lines if 'Action:' in l), raw_output).strip()
                mood = next((l.split('Mood:')[1] for l in lines if 'Mood:' in l), "").strip()
                text_content = next((l.split('Text:')[1] for l in lines if 'Text:' in l), "").strip()

                results.append({
                    "start": seg['start'],
                    "end": seg['end'],
                    "duration": seg['duration'],
                    "action": action,
                    "mood": mood,
                    "text": text_content,
                    "description": f"[{action}] 분위기: {mood} (자막: {text_content})" # 하위 호환성 유지
                })
                
            except Exception as e:
                print(f"[VisionAnalyzer Error at {seg['start']}s]: {e}")
                results.append({"start": seg['start'], "end": seg['end'], "description": "분석 오류 발생"})
            
            if task_manager and task_id:
                prog = int((i / len(keyframes)) * 100)
                task_manager.update_progress(task_id, prog, f"비전 구간 분석 중... ({i+1}/{len(keyframes)})")

        return results

    def _analyze_frames_mac(self, keyframes, task_manager, task_id):
        """
        [Apple Silicon Optimized] 
        MLX-VLM 가속을 사용하여 각 샷의 구간별 Action, Mood, Text를 정밀 분석합니다.
        """
        # MLX-VLM 모델 로드 (가벼우며 메모리 효율적임)
        if self.model is None:
            import mlx_vlm
            self.model, self.processor = mlx_vlm.utils.load(self.model_path)

        results = []
        for i, seg in enumerate(keyframes):
            if task_manager and task_id and task_manager.is_cancelled(task_id):
                break
                
            # [Prompt Engineering] 전문 에디터 페르소나 주입 (NVIDIA 버전과 동일한 전략)
            prompt = (
                "Analyze this video shot for professional editing. Answer in Korean.\n"
                "Format your response as follows:\n"
                "1. Action: Describe the main movement or event.\n"
                "2. Mood: Describe the visual atmosphere (lighting, color, emotion).\n"
                "3. Text: List all visible on-screen text or captions. (If none, write 'None')"
            )
            
            try:
                # MLX-VLM 특유의 generate 함수 호출
                # verbose=False로 설정하여 불필요한 로그 생성을 방지합니다.
                import mlx_vlm
                raw_output = mlx_vlm.utils.generate(
                    self.model, 
                    self.processor, 
                    seg['image'], 
                    prompt, 
                    max_tokens=256, # 구조화된 답변을 위해 토큰 상한 상향
                    verbose=False
                ).strip()
                
                # [Parsing Logic] 텍스트 결과에서 Action, Mood, Text 항목을 분리하여 구조화
                # 줄바꿈과 키워드 매칭을 통해 데이터를 추출합니다.
                lines = raw_output.split('\n')
                action = next((l.split('Action:')[1] for l in lines if 'Action:' in l), raw_output).strip()
                mood = next((l.split('Mood:')[1] for l in lines if 'Mood:' in l), "").strip()
                text_content = next((l.split('Text:')[1] for l in lines if 'Text:' in l), "").strip()

                # '점' 데이터가 아닌 '구간' 데이터로 결과 저장
                results.append({
                    "start": seg['start'],
                    "end": seg['end'],
                    "duration": seg['duration'],
                    "action": action,
                    "mood": mood,
                    "text": text_content,
                    "description": f"[{action}] 분위기: {mood} (자막: {text_content})" # 하위 호환성 유지
                })
                
            except Exception as e:
                print(f"[VisionAnalyzer Mac Error at {seg['start']}s]: {e}")
                results.append({
                    "start": seg['start'], 
                    "end": seg['end'], 
                    "description": "Mac 가속 추론 중 오류 발생"
                })
            
            # 실시간 진행률 보고 (0~100%)
            if task_manager and task_id:
                prog = int((i / len(keyframes)) * 100)
                task_manager.update_progress(task_id, prog, f"비전 구간 분석 중 (Apple 가속)... ({i+1}/{len(keyframes)})")

        return results

    def analyze_video(self, video_path, task_manager=None, task_id=None):
        """
        [Main Pipeline] 영상의 시각적 구간 분석 및 JSON 영속화
        """
        try:
            # 1. 샷 경계 기반 구간 추출
            scene_segments = self._extract_keyframes(video_path)
            if not scene_segments:
                return []

            # 2. 하드웨어별 구간 추론 (NVIDIA/Mac)
            if self.device == "cuda":
                descriptions = self._analyze_frames_nvidia(scene_segments, task_manager, task_id)
            elif self.device == "mps":
                descriptions = self._analyze_frames_mac(scene_segments, task_manager, task_id)
            else:
                descriptions = []

            # 3. [New] 결과 영속화 (Data Persistence)
            try:
                base_name = os.path.splitext(os.path.basename(video_path))[0]
                results_dir = os.path.join(os.path.dirname(os.path.dirname(video_path)), "results")
                os.makedirs(results_dir, exist_ok=True)
                
                vision_json_path = os.path.join(results_dir, f"{base_name}_vision.json")
                with open(vision_json_path, 'w', encoding='utf-8') as f:
                    json.dump(descriptions, f, ensure_ascii=False, indent=2)
                print(f"[VisionAnalyzer] Persistence success: {vision_json_path}")
            except Exception as e:
                print(f"[VisionAnalyzer Serialization Error]: {e}")

            return descriptions

        finally:
            self.unload_model()

    def unload_model(self):
        """메모리 확보를 위한 모델 명시적 해제"""
        self.model = None
        self.processor = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        import gc
        gc.collect()