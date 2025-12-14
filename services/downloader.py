import os
import re
import yt_dlp
import uuid
import shutil

class VideoDownloader:
    """
    YouTube URL 다운로드 및 업로드 파일 저장을 담당하는 클래스.
    웹 서버(FastAPI)에서 호출하기 적합하도록 결과값을 Return 형태로 설계했습니다.
    """
    
    def __init__(self, download_dir="static/videos"):
        """
        Args:
            download_dir (str): 영상이 저장될 루트 디렉토리 (기본값: static/videos)
        """
        self.download_dir = download_dir
        # 저장 폴더가 없으면 자동으로 생성
        os.makedirs(self.download_dir, exist_ok=True)

    def _sanitize_filename(self, title):
        """
        파일 시스템 저장 시 오류를 방지하기 위해 파일명을 정제합니다.
        공백은 언더스코어(_)로 변경하고, 특수문자는 제거합니다.
        """
        # 1. 윈도우/리눅스 금지 문자 제거
        clean_name = re.sub(r'[\\/*?:"<>|]', "", title)
        # 2. 공백 -> 언더스코어
        clean_name = clean_name.strip().replace(" ", "_")
        return clean_name

    def save_uploaded_file(self, file_object, original_filename, task_manager=None, task_id=None):
        """
        [New] 사용자가 직접 업로드한 파일을 저장하는 메서드
        [수정] 저장 시작 전 취소 확인 로직 추가
        
        Args:
            file_object: FastAPI의 UploadFile.file 객체 (Binary IO)
            original_filename: 사용자가 올린 원본 파일명
            task_manager: (Optional) 취소 확인용
            task_id: (Optional) 취소 확인용
        """
        try:
            # [Check Cancel] 저장 시작 전 확인
            if task_manager and task_id and task_manager.is_cancelled(task_id):
                return {"status": "error", "message": "Upload cancelled by user"}

            # 안전한 파일명 생성
            safe_name = self._sanitize_filename(original_filename)
            # 중복 방지를 위해 UUID 부착
            unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
            final_path = os.path.join(self.download_dir, unique_name)

            # 파일 저장 (Copy stream)
            with open(final_path, "wb") as buffer:
                shutil.copyfileobj(file_object, buffer)

            print(f"--- [Upload] File saved to: {final_path} ---")
            return {
                "status": "success",
                "file_path": final_path,
                "filename": unique_name,
                "original_filename": original_filename
            }

        except Exception as e:
            print(f"[Error] Upload failed: {e}")
            return {"status": "error", "message": str(e)}

    def download_from_url(self, url, progress_callback=None, task_manager=None, task_id=None):
        """
        YouTube URL을 통해 영상을 다운로드합니다.
        [수정] Hook 내부에서 TaskManager를 조회하여 다운로드 강제 중단 기능 추가
        
        Args:
            url (str): 유튜브 URL
            progress_callback (func): 진행률 콜백
            task_manager (TaskManager): 취소 상태 확인용 인스턴스
            task_id (str): 작업 ID
        """
        print(f"--- [Downloader] Processing URL: {url} ---")
        
        # 내부 Hook 함수 정의 (yt-dlp가 다운로드 중에 계속 호출함)
        def _progress_hook(d):
            # [Check Cancel] 다운로드 중간에 취소 여부 확인
            if task_manager and task_id:
                if task_manager.is_cancelled(task_id):
                    # 예외를 발생시키면 yt-dlp가 즉시 중단됩니다.
                    raise Exception("Download cancelled by user")

            if d['status'] == 'downloading':
                # 전체 크기 대비 다운로드된 크기 계산
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes', 0)
                
                if total:
                    percent = int(downloaded / total * 100)
                    # 외부에서 주입된 콜백 호출
                    if progress_callback:
                        progress_callback(percent, f"영상 다운로드 중... ({percent}%)")
            
            elif d['status'] == 'finished':
                if progress_callback:
                    progress_callback(100, "다운로드 완료! 변환 준비 중...")

        # yt-dlp 옵션 구성 (progress_hooks 추가)
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': f'{self.download_dir}/%(title)s.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [_progress_hook]  # Hook 등록
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 1. 메타데이터 추출
                info_dict = ydl.extract_info(url, download=False)
                
                video_title = info_dict.get('title', 'video')
                video_ext = info_dict.get('ext', 'mp4')
                
                # 파일명 정제
                safe_title = self._sanitize_filename(video_title)
                filename = f"{safe_title}.{video_ext}"
                final_path = os.path.join(self.download_dir, filename)

                # 2. 저장 경로 재설정
                ydl.params['outtmpl'] = {
                    'default': final_path
                }

                # 3. 다운로드 수행 (Hook에 의해 중단될 수 있음)
                if os.path.exists(final_path):
                    print(f" -> File already exists: {final_path}")
                    if progress_callback:
                        progress_callback(100, "파일이 이미 존재합니다.")
                else:
                    print(f" -> Downloading to: {final_path}")
                    ydl.download([url])

                return {
                    "status": "success",
                    "file_path": final_path,
                    "filename": filename,
                    "meta": {
                        "title": video_title,
                        "duration": info_dict.get('duration'),
                        "thumbnail": info_dict.get('thumbnail')
                    }
                }

        except Exception as e:
            # 취소 메시지가 감지되면 명확히 로깅
            if "cancelled by user" in str(e):
                print(f"[Downloader] Task {task_id} cancelled.")
                return {"status": "error", "message": "User cancelled the download"}
            
            print(f"[Error] Download failed: {e}")
            return {
                "status": "error",
                "message": str(e)
            }

# --- [Module Test Code] ---
if __name__ == "__main__":
    # 이 파일을 직접 실행했을 때만 작동하는 테스트 코드
    downloader = VideoDownloader(download_dir="../static/videos")
    
    # Test URL Download
    test_url = "https://chzzk.naver.com/video/10561205" # 테스트용 URL
    result = downloader.download_from_url(test_url)
    print("Result:", result)