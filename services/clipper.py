import os
import re
import subprocess
import zipfile

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

    def cut_video(self, input_path, start_sec, end_sec, output_filename="clip.mp4"):
        """
        FFmpeg와 Apple VideoToolbox를 사용하여 하드웨어 가속으로 영상을 자릅니다.
        [개선사항] 고정 비트레이트 대신 품질 기반 VBR(-q:v)을 사용하여 
        용량을 최적화하고 원본 화질을 보존합니다.
        """
        output_path = os.path.join(self.temp_dir, output_filename)
        
        cmd = [
            "ffmpeg", 
            "-i", input_path,
            "-ss", str(start_sec),
            "-to", str(end_sec),
            
            # [Apple Silicon 하드웨어 가속 설정]
            "-c:v", "h264_videotoolbox", # 인코더: Apple M-Series Media Engine
            
            # [핵심 변경 사항: 화질 제어]
            # -q:v 65: 품질 기준 VBR (0~100). 
            # 65는 시각적 무손실(Visually Lossless)에 가까운 Apple 권장 'High' 품질입니다.
            # 복잡한 장면엔 비트레이트를 높이고, 단순한 장면엔 낮춰 용량을 최적화합니다.
            "-q:v", "65",
            
            # [오디오 설정]
            # -c:a aac: 호환성을 위해 AAC 사용
            # -b:a 192k: 오디오 음질 저하를 막기 위해 충분한 비트레이트 할당
            "-c:a", "aac", "-b:a", "192k",
            
            "-y",           # 파일 덮어쓰기 허용
            "-hide_banner", # 불필요한 로그 숨김
            output_path
        ]

        try:
            # 하드웨어 가속 디버깅을 위해 에러 발생 시에만 로그를 캡처합니다.
            result = subprocess.run(
                cmd, 
                check=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.PIPE
            )
            print(f"--- [Clipper] VBR Optimized Cut Success: {output_path} ---")
            return output_path
            
        except subprocess.CalledProcessError as e:
            error_log = e.stderr.decode() if e.stderr else "Unknown Error"
            print(f"[Clipper Error] FFmpeg failed: {error_log}")
            raise Exception(f"Video cutting failed: {error_log}")

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