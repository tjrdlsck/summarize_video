import os
import re
import sys
import subprocess
import zipfile
import asyncio
import uuid                     # [추가] UUID 생성을 위해 필수
from functools import partial   # [추가] 비동기 실행 시 인자 전달을 위해 필수

class VideoClipper:
    """
    FFmpeg를 사용하여 영상을 자르고, 자막(SRT/VTT)의 타임스탬프를 동기화하여
    클립을 생성하는 클래스입니다.
    """

    def __init__(self, temp_dir="static/temp"):
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)

    def _is_nvenc_available(self):
        """
        NVIDIA NVENC 가속 인코더가 현재 시스템에서 사용 가능한지 확인합니다.
        """
        try:
            # 1. nvidia-smi 명령어를 실행하여 NVIDIA GPU 및 드라이버가 작동 중인지 확인
            result = subprocess.run(
                ["nvidia-smi"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if result.returncode != 0:
                return False
            
            # 2. ffmpeg에서 h264_nvenc 인코더를 지원하는지 확인
            result = subprocess.run(
                ["ffmpeg", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )
            return "h264_nvenc" in result.stdout
        except Exception:
            return False

    def _is_cuda_hwaccel_available(self):
        """
        NVIDIA CUDA 디코딩 가속(-hwaccel cuda)이 지원되는지 확인합니다.
        """
        if not self._is_nvenc_available():
            return False
        try:
            result = subprocess.run(
                ["ffmpeg", "-hwaccels"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )
            return "cuda" in result.stdout
        except Exception:
            return False

    def _seconds_to_time_str(self, seconds, separator=","):
        """
        초(float)를 SRT/VTT 시간 포맷(HH:MM:SS,mmm)으로 변환
        separator: SRT는 ',', VTT는 '.' 사용
        """
        if seconds < 0: seconds = 0
        
        ms = int((seconds - int(seconds)) * 1000)
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        
        return f"{h:02}:{m:02}:{s:02}{separator}{ms:03}"

    def _time_str_to_seconds(self, time_str):
        """
        시간 문자열(00:00:00,000 or 00:00:00.000)을 초(float)로 변환
        """
        # 구분자 통일 (SRT ',' -> '.')
        time_str = time_str.replace(',', '.')
        try:
            parts = time_str.split(':')
            h = int(parts[0])
            m = int(parts[1])
            s = float(parts[2])
            return h * 3600 + m * 60 + s
        except Exception:
            return 0.0

    async def cut_video(self, input_path, start_sec, end_sec, output_filename="clip.mp4", task_manager=None, task_id=None):
        """
        [Async] FFmpeg를 비동기 프로세스로 실행하며, stderr을 파싱하여 실시간 진행률을 반영합니다.
        [Quality & Fix] 원본 화질 유지를 위해 품질 기반 인코딩(VBR)을 사용하되, Safari 호환성을 위해 yuv420p를 강제합니다.
        [New] 오디오 끊김 방지를 위해 Fade-in/out 필터를 적용합니다.
        """
        output_path = os.path.join(self.temp_dir, output_filename)
        
        # 잘라낼 영상의 길이 (진행률 분모)
        duration = end_sec - start_sec
        if duration <= 0: duration = 1 # 0으로 나누기 방지

        # [FFmpeg Filter Configuration]
        # 오디오 페이드 적용 (시작 0.1초 인, 종료 0.2초 아웃)
        fade_duration_in = 0.1
        fade_duration_out = 0.2
        audio_filter = f"afade=t=in:st=0:d={fade_duration_in},afade=t=out:st={duration - fade_duration_out}:d={fade_duration_out}"

        # [FFmpeg Encoder & Quality Configuration]
        input_opts = []
        if self._is_cuda_hwaccel_available():
            input_opts = ["-hwaccel", "cuda"]
            encoder = "h264_nvenc"
            quality_opts = ["-rc", "vbr", "-cq", "24", "-preset", "p2"]
        elif self._is_nvenc_available():
            encoder = "h264_nvenc"
            quality_opts = ["-rc", "vbr", "-cq", "24", "-preset", "p2"]
        elif sys.platform == 'darwin':
            encoder = "h264_videotoolbox"
            quality_opts = ["-q:v", "65"]
        else:
            encoder = "libx264"
            quality_opts = ["-crf", "23", "-preset", "superfast"]

        # [FFmpeg Command Configuration]
        cmd = ["ffmpeg", "-nostdin"]
        cmd.extend(input_opts)
        cmd.extend([
            "-ss", str(start_sec),
            "-t", str(duration),
            "-i", input_path,
            "-filter_complex", f"[0:a]{audio_filter}[af]",
            "-map", "0:v", "-map", "[af]",
            "-c:v", encoder,
        ])
        cmd.extend(quality_opts)
        
        # [Safari 호환성 유지]
        cmd.extend([
            "-pix_fmt", "yuv420p",       # 모바일/웹 표준 색상 포맷
            "-profile:v", "main",        # 호환성 프로필
            "-c:a", "aac", "-b:a", "192k",
            "-y",
            "-hide_banner",
            "-loglevel", "info",
            output_path
        ])

        print(f"--- [Clipper] Starting Async Cut (High Quality + Fade): {output_filename} ---")
        
        # 에러 발생 시 원인을 파악하기 위해 stderr 로그를 모아둘 버퍼
        stderr_log = []

        try:
            # 1. 비동기 서브프로세스 생성 (stderr Pipe 연결)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )

            # 2. stderr 비동기 읽기 Loop (Real-time Parsing)
            while True:
                # [Check Cancel] 작업 취소 확인
                if task_manager and task_id and task_manager.is_cancelled(task_id):
                    try:
                        process.terminate() 
                        await process.wait() 
                        print(f"--- [Clipper] Killed process for task {task_id}")
                    except Exception:
                        pass
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    raise Exception("Clip generation cancelled by user")

                try:
                    # FFmpeg 진행률 로그 캐치 (\r)
                    line_bytes = await process.stderr.readuntil(b'\r')
                except asyncio.IncompleteReadError as e:
                    line_bytes = e.partial
                    if not line_bytes:
                        break 
                except Exception:
                    break

                # 디코딩
                line = line_bytes.decode('utf-8', errors='replace').strip()
                
                # 로그 버퍼에 저장 (에러 분석용)
                if line:
                    stderr_log.append(line)
                
                # time=00:00:00.00 패턴 파싱
                if 'time=' in line:
                    match = re.search(r'time=(\d{2}:\d{2}:\d{2}\.\d+)', line)
                    if match:
                        time_str = match.group(1)
                        try:
                            # 시:분:초.밀리초 -> 초 단위 변환
                            h, m, s = time_str.split(':')
                            current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                            
                            # 로컬 진행률 계산
                            percent = int((current_seconds / duration) * 100)
                            percent = min(100, max(0, percent))
                            
                            # TaskManager 업데이트 (구간: 10% -> 60%)
                            global_progress = 10 + int(percent * 0.5)
                            
                            if task_manager and task_id:
                                task_manager.update_progress(
                                    task_id, 
                                    global_progress, 
                                    f"영상 자르는 중... ({percent}%)"
                                )
                        except Exception:
                            pass 

            # 3. 프로세스 종료 대기 및 결과 확인
            await process.wait()
            
            if process.returncode != 0:
                error_details = "\n".join(stderr_log[-10:]) 
                print(f"[Clipper FFmpeg Error Log]\n{error_details}")
                raise Exception(f"FFmpeg failed with return code {process.returncode}.")

            print(f"--- [Clipper] Cut Success: {output_path} ---")
            
            if task_manager and task_id:
                task_manager.update_progress(task_id, 60, "영상 자르기 완료")
                
            return output_path
            
        except Exception as e:
            print(f"[Clipper Error] {e}")
            if os.path.exists(output_path):
                try: os.remove(output_path)
                except: pass
            raise e

    def cut_subtitle(self, sub_path, start_sec, end_sec, output_filename="clip.srt"):
        """
        자막 파일을 파싱하여 구간 내 자막만 추출하고 시간을 이동(Shift)시킵니다.
        SRT와 VTT 포맷을 모두 지원합니다.
        """
        if not os.path.exists(sub_path):
            return None

        ext = os.path.splitext(sub_path)[1].lower()
        is_vtt = (ext == '.vtt')
        time_sep = '.' if is_vtt else ','
        
        output_path = os.path.join(self.temp_dir, output_filename)
        
        with open(sub_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        if is_vtt:
            new_lines.append("WEBVTT\n\n")

        # 시간 패턴 정규식 (00:00:00,000 --> 00:00:00,000)
        # VTT의 경우 .으로 구분되므로 [.,]로 처리
        time_pattern = re.compile(r'(\d{2}:\d{2}:\d{2}[.,]\d{3})\s-->\s(\d{2}:\d{2}:\d{2}[.,]\d{3})')
        
        index_counter = 1
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # 시간 정보가 있는 줄 찾기
            match = time_pattern.search(line)
            if match:
                t_start_str = match.group(1)
                t_end_str = match.group(2)
                
                t_start = self._time_str_to_seconds(t_start_str)
                t_end = self._time_str_to_seconds(t_end_str)

                # [필터링 로직]
                # 1. 자막이 구간 완전히 앞에 있는 경우 -> Skip
                if t_end < start_sec:
                    i += 1
                    continue
                # 2. 자막이 구간 완전히 뒤에 있는 경우 -> Stop (더 볼 필요 없음)
                if t_start > end_sec:
                    break
                
                # 3. 겹치는 경우 (Overlap) -> 시간 보정 및 추가
                # 잘린 영상 기준 0초부터 시작해야 하므로 start_sec을 뺌
                new_start = t_start - start_sec
                new_end = t_end - start_sec
                
                # 텍스트 추출 (다음 빈 줄까지)
                text_lines = []
                j = i + 1
                while j < len(lines) and lines[j].strip() != "":
                    text_lines.append(lines[j])
                    j += 1
                
                # 새 포맷 작성
                if not is_vtt:
                    new_lines.append(f"{index_counter}\n")
                
                start_fmt = self._seconds_to_time_str(new_start, time_sep)
                end_fmt = self._seconds_to_time_str(new_end, time_sep)
                
                new_lines.append(f"{start_fmt} --> {end_fmt}\n")
                new_lines.extend(text_lines)
                new_lines.append("\n")
                
                index_counter += 1
                i = j # 텍스트 읽은 만큼 점프
            else:
                i += 1

        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
            
        return output_path

    def create_zip(self, file_paths, zip_filename="result.zip", destination_dir=None):
        """
        여러 파일을 하나의 Zip 파일로 압축합니다.
        
        Args:
            file_paths (list): 압축할 파일들의 경로 리스트
            zip_filename (str): 생성될 Zip 파일의 이름
            destination_dir (str, optional): 저장될 디렉토리 경로. 
                                           None일 경우 클래스 초기화 시 설정한 temp_dir을 사용합니다.
        """
        # 저장 경로 결정: 인자로 받은 경로가 우선, 없으면 temp_dir 사용
        save_dir = destination_dir if destination_dir else self.temp_dir
        
        # 해당 경로가 없으면 생성 (안전장치)
        os.makedirs(save_dir, exist_ok=True)
        
        zip_path = os.path.join(save_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in file_paths:
                if file and os.path.exists(file):
                    # 압축 내부에는 경로를 제외한 파일명만 저장
                    zf.write(file, arcname=os.path.basename(file))
                    
        return zip_path
    # [Add] 이 메서드를 VideoClipper 클래스 내부에 새로 추가하세요. (메서드 위치는 상관없으나 _merge_subtitles 근처 권장)
    def _srt_to_vtt(self, srt_path):
        """
        [Helper] 생성된 SRT 파일을 웹 표준인 WEBVTT 포맷으로 변환합니다.
        """
        if not os.path.exists(srt_path):
            return None
            
        vtt_path = srt_path.replace('.srt', '.vtt')
        
        try:
            with open(srt_path, 'r', encoding='utf-8') as f_in:
                lines = f_in.readlines()
            
            vtt_lines = ["WEBVTT\n\n"]
            
            for line in lines:
                # 타임스탬프 변환: 00:00:00,000 -> 00:00:00.000 (쉼표를 마침표로)
                if '-->' in line:
                    vtt_lines.append(line.replace(',', '.'))
                else:
                    vtt_lines.append(line)
            
            with open(vtt_path, 'w', encoding='utf-8') as f_out:
                f_out.writelines(vtt_lines)
                
            return vtt_path
            
        except Exception as e:
            print(f"[Clipper] VTT conversion failed: {e}")
            return None

    async def merge_segments(self, input_path, segments, output_filename="shorts.mp4", sub_input_path=None, progress_callback=None, task_manager=None, task_id=None):
        """
        [Async] 불연속적인 여러 구간을 병합합니다.
        [Quality & Fix] 원본 화질 유지를 위해 품질 기반 VBR 인코딩을 사용하며, yuv420p 포맷으로 호환성을 보장합니다.
        [New] 각 구간의 연결부 오디오 끊김 방지를 위해 개별 Fade 필터를 적용합니다.
        """
        output_video_path = os.path.join(self.temp_dir, output_filename)
        output_sub_path = None
        output_vtt_path = None
        
        # 1. 자막 병합 처리
        if sub_input_path and os.path.exists(sub_input_path):
            try:
                base_name = os.path.splitext(output_filename)[0]
                sub_filename = f"{base_name}.srt"
                full_sub_path = os.path.join(self.temp_dir, sub_filename)
                
                loop = asyncio.get_running_loop()
                output_sub_path = await loop.run_in_executor(
                    None, 
                    partial(self._merge_subtitles, sub_input_path, segments, full_sub_path)
                )
                
                if output_sub_path:
                    output_vtt_path = await loop.run_in_executor(
                        None,
                        self._srt_to_vtt,
                        output_sub_path
                    )
            except Exception as e:
                print(f"[Clipper] Warning: Failed to merge subtitles: {e}")

        # 2. 영상 병합 처리 (FFmpeg)
        total_duration = sum(seg['end'] - seg['start'] for seg in segments)
        if total_duration <= 0: total_duration = 1

        filter_parts = []
        concat_input = ""
        
        # 페이드 설정
        f_in = 0.1
        f_out = 0.2

        for i, seg in enumerate(segments):
            start = f"{seg['start']:.3f}"
            end = f"{seg['end']:.3f}"
            duration = seg['end'] - seg['start']
            
            # 비디오 트림
            filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]")
            
            # [New] 오디오 트림 + 세그먼트 길이 연동 동적 페이드 인/아웃 적용
            effective_f_in = min(f_in, max(0.01, duration / 2.0))
            effective_f_out = min(f_out, max(0.01, duration / 2.0))
            fade_out_st = max(0.0, duration - effective_f_out)
            audio_fade = f"afade=t=in:st=0:d={effective_f_in:.3f},afade=t=out:st={fade_out_st:.3f}:d={effective_f_out:.3f}"
            filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,{audio_fade}[a{i}]")
            
            concat_input += f"[v{i}][a{i}]"

        filter_parts.append(f"{concat_input}concat=n={len(segments)}:v=1:a=1[outv][outa]")
        filter_complex_str = ";".join(filter_parts)

        # [FFmpeg Encoder & Quality Configuration]
        input_opts = []
        if self._is_cuda_hwaccel_available():
            input_opts = ["-hwaccel", "cuda"]
            encoder = "h264_nvenc"
            quality_opts = ["-rc", "vbr", "-cq", "24", "-preset", "p2"]
        elif self._is_nvenc_available():
            encoder = "h264_nvenc"
            quality_opts = ["-rc", "vbr", "-cq", "24", "-preset", "p2"]
        elif sys.platform == 'darwin':
            encoder = "h264_videotoolbox"
            quality_opts = ["-q:v", "65"]
        else:
            encoder = "libx264"
            quality_opts = ["-crf", "23", "-preset", "superfast"]

        # [FFmpeg Command Configuration]
        cmd = ["ffmpeg", "-nostdin"]
        cmd.extend(input_opts)
        cmd.extend([
            "-i", input_path,
            "-filter_complex", filter_complex_str,
            "-map", "[outv]", 
            "-map", "[outa]",
            "-c:v", encoder,
        ])
        cmd.extend(quality_opts)
        
        # [Safari 호환성 유지]
        cmd.extend([
            "-pix_fmt", "yuv420p",       # 모바일/웹 표준 색상 포맷
            "-profile:v", "main",        # 호환성 프로필
            "-c:a", "aac", 
            "-b:a", "192k",
            "-y",
            "-hide_banner",
            "-loglevel", "info", 
            output_video_path
        ])

        print(f"--- [Clipper] Starting Merge Segments (High Quality + Audio Refinement): {len(segments)} cuts ---")

        stderr_log = []
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )

            while True:
                if task_manager and task_id and task_manager.is_cancelled(task_id):
                    try:
                        process.terminate()
                        await process.wait()
                    except Exception: pass
                    
                    if os.path.exists(output_video_path): os.remove(output_video_path)
                    if output_sub_path and os.path.exists(output_sub_path): os.remove(output_sub_path)
                    if output_vtt_path and os.path.exists(output_vtt_path): os.remove(output_vtt_path)
                    
                    raise Exception("Shorts generation cancelled by user")

                line_bytes = await process.stderr.readline()
                if not line_bytes: break

                line = line_bytes.decode('utf-8', errors='replace').strip()
                if line: stderr_log.append(line)

                if 'time=' in line:
                    match = re.search(r'time=(\d{2}:\d{2}:\d{2}\.\d+)', line)
                    if match:
                        time_str = match.group(1)
                        try:
                            h, m, s = time_str.split(':')
                            current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                            
                            percent = int((current_seconds / total_duration) * 100)
                            percent = min(100, max(0, percent))
                            
                            if progress_callback:
                                progress_callback(percent)

                        except Exception: pass

            await process.wait()

            if process.returncode != 0:
                error_details = "\n".join(stderr_log[-10:])
                print(f"[Clipper Merge Error] Log:\n{error_details}")
                raise Exception(f"FFmpeg merge failed with code {process.returncode}")

            print(f"--- [Clipper] Merge Success: {output_video_path} ---")
            
            return {
                "video": output_video_path,
                "subtitle": output_sub_path,
                "subtitle_vtt": output_vtt_path
            }

        except Exception as e:
            print(f"[Clipper Error] {e}")
            if os.path.exists(output_video_path): os.remove(output_video_path)
            if output_sub_path and os.path.exists(output_sub_path): os.remove(output_sub_path)
            if output_vtt_path and os.path.exists(output_vtt_path): os.remove(output_vtt_path)
            raise e
        
    def _merge_subtitles(self, original_sub_path, segments, output_sub_path):
        """
        [Helper] 여러 구간의 자막을 추출하여 하나의 타임라인(0초 시작)으로 병합합니다.
        SRT 파일 포맷을 기준으로 처리하며, 각 구간(Segment)의 길이만큼 시간을 이동(Shift)시킵니다.
        """
        if not os.path.exists(original_sub_path):
            return None
        
        merged_lines = []
        current_offset = 0.0 # 병합된 타임라인에서의 현재 위치 (초)
        index_counter = 1
        
        # 시간 패턴 정규식 (SRT: 00:00:00,000 / VTT: 00:00:00.000 호환)
        time_pattern = re.compile(r'(\d{2}:\d{2}:\d{2}[.,]\d{3})\s-->\s(\d{2}:\d{2}:\d{2}[.,]\d{3})')
        
        try:
            for seg in segments:
                # 1. 해당 구간의 자막을 임시 파일로 추출 (기존 cut_subtitle 메서드 활용)
                temp_sub_name = f"temp_sub_{uuid.uuid4().hex[:8]}.srt"
                
                temp_sub_path = None
                try:
                    temp_sub_path = self.cut_subtitle(
                        original_sub_path, 
                        seg['start'], 
                        seg['end'], 
                        output_filename=temp_sub_name
                    )
                    
                    if temp_sub_path and os.path.exists(temp_sub_path):
                        with open(temp_sub_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                        
                        # 2. 추출된 자막의 타임스탬프를 current_offset 만큼 뒤로 밀기(Shift)
                        for line in lines:
                            if '-->' in line:
                                match = time_pattern.search(line)
                                if match:
                                    t1_str = match.group(1).replace(',', '.')
                                    t2_str = match.group(2).replace(',', '.')
                                    
                                    t1 = self._time_str_to_seconds(t1_str)
                                    t2 = self._time_str_to_seconds(t2_str)
                                    
                                    # 병합된 타임라인 기준 시간으로 변환
                                    new_t1 = t1 + current_offset
                                    new_t2 = t2 + current_offset
                                    
                                    s1 = self._seconds_to_time_str(new_t1, ',')
                                    s2 = self._seconds_to_time_str(new_t2, ',')
                                    
                                    merged_lines.append(f"{index_counter}\n")
                                    merged_lines.append(f"{s1} --> {s2}\n")
                                    index_counter += 1
                            
                            # 인덱스 번호(숫자만 있는 줄)는 건너뛰고, 타임라인도 아니면(텍스트) 그대로 추가
                            elif line.strip().isdigit():
                                continue 
                            elif line.strip() == "WEBVTT":
                                continue
                            elif line.strip() == "":
                                merged_lines.append("\n")
                            else:
                                merged_lines.append(line)
                finally:
                    if temp_sub_path and os.path.exists(temp_sub_path):
                        try:
                            os.remove(temp_sub_path)
                        except Exception:
                            pass

                # 다음 구간을 위해 오프셋 증가 (현재 구간 길이만큼)
                seg_duration = seg['end'] - seg['start']
                current_offset += seg_duration
            
            # 최종 병합된 자막 파일 저장
            if merged_lines:
                with open(output_sub_path, 'w', encoding='utf-8') as f:
                    f.writelines(merged_lines)
                return output_sub_path
            else:
                return None
            
        except Exception as e:
            print(f"[Clipper] Subtitle merge error: {e}")
            return None