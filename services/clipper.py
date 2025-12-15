import os
import re
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
        [Fix] 
          1. 출력 파일 경로(output_path) 누락 수정 -> "At least one output file..." 에러 해결
          2. 인코더를 libx264로 변경하고 CRF(Constant Rate Factor) 옵션 적용 -> 화질 기반 가변 비트레이트
        """
        output_path = os.path.join(self.temp_dir, output_filename)
        
        # 잘라낼 영상의 길이 (진행률 분모)
        duration = end_sec - start_sec
        if duration <= 0: duration = 1 # 0으로 나누기 방지

        cmd = [
            "ffmpeg", 
            "-i", input_path,
            "-ss", str(start_sec),
            "-to", str(end_sec),
            "-c:v", "h264_videotoolbox", # Apple Silicon 가속 (필요시 libx264로 변경)
            "-q:v", "65",
            "-c:a", "aac", "-b:a", "192k",
            "-y",
            "-hide_banner",
            "-loglevel", "info", # [Important] 진행률 파싱을 위해 info 레벨 필수
            output_path
        ]

        print(f"--- [Clipper] Starting Async Cut: {output_filename} ---")
        
        # 에러 발생 시 원인을 파악하기 위해 stderr 로그를 모아둘 버퍼
        stderr_log = []

        try:
            # 1. 비동기 서브프로세스 생성 (stderr Pipe 연결)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )

            # 2. stderr 비동기 읽기 Loop
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

                # 비동기적으로 한 줄 읽기
                line_bytes = await process.stderr.readline()
                
                # 빈 바이트가 반환되면 EOF (프로세스 종료)
                if not line_bytes:
                    break 

                # 디코딩
                line = line_bytes.decode('utf-8', errors='replace').strip()
                
                # 로그 버퍼에 저장
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
                            
                            # TaskManager 업데이트
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
                # 실패 시 모아둔 로그를 출력하여 원인 파악
                error_details = "\n".join(stderr_log[-10:]) 
                print(f"[Clipper FFmpeg Error Log]\n{error_details}")
                raise Exception(f"FFmpeg failed with return code {process.returncode}. Check server logs for details.")

            print(f"--- [Clipper] Cut Success: {output_path} ---")
            
            if task_manager and task_id:
                task_manager.update_progress(task_id, 60, "영상 자르기 완료")
                
            return output_path
            
        except Exception as e:
            print(f"[Clipper Error] {e}")
            if os.path.exists(output_path):
                os.remove(output_path)
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

    # [Modify] 기존 merge_segments 메서드를 아래 코드로 통째로 교체하세요.
    async def merge_segments(self, input_path, segments, output_filename="shorts.mp4", sub_input_path=None, progress_callback=None, task_manager=None, task_id=None):
        """
        [Async] 불연속적인 여러 구간(Segments)을 하나의 영상으로 병합하고, 자막(SRT/VTT)도 동기화합니다.
        [Update] SRT 생성 후 VTT 변환 로직이 추가되었습니다.
        """
        output_video_path = os.path.join(self.temp_dir, output_filename)
        output_sub_path = None     # SRT 경로
        output_vtt_path = None     # VTT 경로
        
        # 1. 자막 병합 처리 (동기 처리, CPU 작업)
        # 자막 파일이 존재하고 요청이 있을 경우 수행
        if sub_input_path and os.path.exists(sub_input_path):
            try:
                base_name = os.path.splitext(output_filename)[0]
                sub_filename = f"{base_name}.srt"
                full_sub_path = os.path.join(self.temp_dir, sub_filename)
                
                loop = asyncio.get_running_loop()
                # SRT 병합
                output_sub_path = await loop.run_in_executor(
                    None, 
                    partial(self._merge_subtitles, sub_input_path, segments, full_sub_path)
                )
                
                # [New] SRT -> VTT 변환 추가
                if output_sub_path:
                    output_vtt_path = await loop.run_in_executor(
                        None,
                        self._srt_to_vtt,
                        output_sub_path
                    )
                    
            except Exception as e:
                print(f"[Clipper] Warning: Failed to merge subtitles: {e}")

        # 2. 영상 병합 처리 (FFmpeg)
        # 병합될 영상의 총 길이 계산
        total_duration = sum(seg['end'] - seg['start'] for seg in segments)
        if total_duration <= 0: total_duration = 1

        # FFmpeg Filter Complex 구문 생성
        filter_parts = []
        concat_input = ""
        
        for i, seg in enumerate(segments):
            start = f"{seg['start']:.3f}"
            end = f"{seg['end']:.3f}"
            
            # Video Trim & Reset Timestamp
            filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]")
            # Audio Trim & Reset Timestamp
            filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]")
            
            concat_input += f"[v{i}][a{i}]"

        # Concat 부분
        filter_parts.append(f"{concat_input}concat=n={len(segments)}:v=1:a=1[outv][outa]")
        filter_complex_str = ";".join(filter_parts)

        # 명령어 구성 (macOS 가속 사용, 필요시 libx264로 변경 가능)
        cmd = [
            "ffmpeg", 
            "-i", input_path,
            "-filter_complex", filter_complex_str,
            "-map", "[outv]", 
            "-map", "[outa]",
            "-c:v", "h264_videotoolbox", # macOS Hardware Acceleration (or libx264)
            "-q:v", "65",                # 품질 기반 VBR
            "-c:a", "aac", 
            "-b:a", "192k",
            "-y",
            "-hide_banner",
            "-loglevel", "info", 
            output_video_path
        ]

        print(f"--- [Clipper] Starting Merge Segments: {len(segments)} cuts, Duration: {total_duration:.2f}s ---")

        # 비동기 실행 및 진행률 파싱
        stderr_log = []
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )

            while True:
                # [Check Cancel] 작업 취소 확인
                if task_manager and task_id and task_manager.is_cancelled(task_id):
                    try:
                        process.terminate()
                        await process.wait()
                    except Exception: pass
                    
                    # 생성 중이던 파일 정리
                    if os.path.exists(output_video_path): os.remove(output_video_path)
                    if output_sub_path and os.path.exists(output_sub_path): os.remove(output_sub_path)
                    if output_vtt_path and os.path.exists(output_vtt_path): os.remove(output_vtt_path)
                    
                    raise Exception("Shorts generation cancelled by user")

                line_bytes = await process.stderr.readline()
                if not line_bytes: break

                line = line_bytes.decode('utf-8', errors='replace').strip()
                if line: stderr_log.append(line)

                # 진행률 파싱
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
            
            # [Update] VTT 경로도 함께 반환
            return {
                "video": output_video_path,
                "subtitle": output_sub_path,
                "subtitle_vtt": output_vtt_path
            }

        except Exception as e:
            print(f"[Clipper Error] {e}")
            # 에러 발생 시 잔여 파일 정리
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
                
                # cut_subtitle은 해당 구간을 0초부터 시작하도록 잘라서 저장해줍니다.
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
                    
                    # 처리가 끝난 임시 파일 삭제
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