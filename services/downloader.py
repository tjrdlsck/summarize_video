import os
import re
import yt_dlp
import uuid
import shutil
import json
import sys
import subprocess
from urllib.request import urlopen
import anyio # [Add] 비동기 파일 I/O를 위해 추가
from yt_dlp.utils import DownloadError
from services.logger import get_logger, log_error_with_traceback, log_task_error

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
        # [Add] 유니코드 정규화 (NFC) 적용
        import unicodedata
        title = unicodedata.normalize('NFC', title)

        # 1. 윈도우/리눅스 금지 문자 제거
        clean_name = re.sub(r'[\\/*?:"<>|]', "", title)
        # 2. 공백 -> 언더스코어
        clean_name = clean_name.strip().replace(" ", "_")
        return clean_name

    def _is_update_required_error(self, error_message: str) -> bool:
        """
        yt-dlp 최신 버전 설치가 필요한 오류 메시지인지 판별합니다.
        """
        message = (error_message or "").lower()
        update_hints = [
            "you should update yt-dlp",
            "this version of yt-dlp is outdated",
            "please update yt-dlp",
            "upgrade yt-dlp",
            "update yt-dlp to the latest version",
            "confirm you are on the latest version",
            "using  yt-dlp -u",
            "using yt-dlp -u",
        ]
        return any(hint in message for hint in update_hints)

    def _get_latest_ytdlp_version(self):
        """
        PyPI에서 최신 yt-dlp 버전을 조회합니다.
        네트워크 문제 시 None을 반환합니다.
        """
        try:
            with urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("info", {}).get("version")
        except Exception:
            return None

    def _attempt_ytdlp_upgrade(self):
        """
        현재 파이썬 인터프리터 기준으로 yt-dlp를 업그레이드합니다.
        """
        current_version = getattr(yt_dlp.version, "__version__", "unknown")
        latest_version = self._get_latest_ytdlp_version()

        if latest_version and current_version == latest_version:
            return {
                "status": "up_to_date",
                "current_version": current_version,
                "latest_version": latest_version,
                "message": "yt-dlp is already at latest version",
            }

        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]
        process = subprocess.run(cmd, capture_output=True, text=True)
        if process.returncode != 0:
            return {
                "status": "failed",
                "current_version": current_version,
                "latest_version": latest_version,
                "message": (process.stderr or process.stdout or "yt-dlp upgrade failed").strip(),
            }

        return {
            "status": "updated",
            "current_version": current_version,
            "latest_version": latest_version,
            "message": "yt-dlp upgraded successfully",
        }

    async def save_uploaded_file(self, upload_file, original_filename, task_manager=None, task_id=None):
        """
        [New] 사용자가 직접 업로드한 파일을 저장하는 메서드 (비동기 방식)
        [수정] anyio를 사용한 Non-blocking 스트림 저장 적용
        
        Args:
            upload_file: FastAPI의 UploadFile 객체
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

            # [수정] anyio를 사용한 비동기 파일 저장
            # 1MB씩 청크 단위로 읽어서 기록하여 메모리 효율성 및 이벤트 루프 응답성 확보
            async with await anyio.open_file(final_path, "wb") as f:
                while chunk := await upload_file.read(1024 * 1024): # 1MB 청크
                    await f.write(chunk)

            print(f"--- [Upload] File saved to: {final_path} ---")
            return {
                "status": "success",
                "file_path": final_path,
                "filename": unique_name,
                "original_filename": original_filename
            }

        except Exception as e:
            logger = get_logger("downloader")
            if task_id:
                log_task_error(task_id, "save_uploaded_file", e)
            else:
                log_error_with_traceback(logger, "Upload failed", e)
            print(f"[Error] Upload failed: {e}")
            return {"status": "error", "message": str(e)}

    async def get_uploaded_size(self, identifier: str) -> int:
        """현재 업로드된 임시 파일의 크기를 반환합니다. (이어올리기 용도)"""
        temp_path = os.path.join(self.download_dir, f"{identifier}.part")
        if os.path.exists(temp_path):
            return os.path.getsize(temp_path)
        return 0

    async def append_chunk(self, identifier: str, chunk_data: bytes):
        """청크 데이터를 임시 파일에 비동기로 추가(Append)합니다."""
        temp_path = os.path.join(self.download_dir, f"{identifier}.part")
        async with await anyio.open_file(temp_path, "ab") as f:
            await f.write(chunk_data)
        return True

    async def finalize_upload(self, identifier: str, original_filename: str):
        """모든 청크 전송 완료 후 임시 파일을 최종 파일로 변환합니다."""
        temp_path = os.path.join(self.download_dir, f"{identifier}.part")
        if not os.path.exists(temp_path):
            return {"status": "error", "message": "임시 파일을 찾을 수 없습니다."}

        safe_name = self._sanitize_filename(original_filename)
        base_name, ext = os.path.splitext(safe_name)
        
        final_filename = safe_name
        final_path = os.path.join(self.download_dir, final_filename)
        
        counter = 1
        while os.path.exists(final_path):
            final_filename = f"{base_name}({counter}){ext}"
            final_path = os.path.join(self.download_dir, final_filename)

        os.rename(temp_path, final_path)
        print(f"--- [Upload Complete] File finalized at: {final_path} ---")

        return {
            "status": "success",
            "file_path": final_path,
            "filename": final_filename,
            "original_filename": original_filename
        }

    def download_from_url(self, url, progress_callback=None, task_manager=None, task_id=None):
        """
        YouTube URL을 통해 영상을 다운로드합니다.
        [Safari Fix] 포맷 선택 규칙을 변경하여 모바일/Safari 호환성이 높은 H.264(avc1) 코덱을 우선 다운로드합니다.
        """
        print(f"--- [Downloader] Processing URL: {url} ---")
        
        # 내부 Hook 함수 정의
        def _progress_hook(d):
            # [Check Cancel] 다운로드 중간에 취소 여부 확인
            if task_manager and task_id:
                if task_manager.is_cancelled(task_id):
                    raise Exception("Download cancelled by user")

            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes', 0)
                
                if total:
                    percent = int(downloaded / total * 100)
                    if progress_callback:
                        progress_callback(percent, f"영상 다운로드 중... ({percent}%)")
            
            elif d['status'] == 'finished':
                if progress_callback:
                    progress_callback(100, "다운로드 완료! 파일 처리 중...")

        # [Safari/Mobile 호환성 핵심]
        # bestvideo[vcodec^=avc1]: 비디오 코덱이 avc1(H.264)으로 시작하는 것 중 최고 화질
        # bestaudio[ext=m4a]: 오디오는 m4a(AAC) 우선
        # 만약 H.264가 없으면 차선책으로 mp4 포맷을 선택
        ydl_opts = {
            'format': 'bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': f'{self.download_dir}/%(title)s.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [_progress_hook],
            # [Fix 403 Forbidden] 클라이언트 위장 (ios, android 클라이언트가 보안 체크가 느슨함)
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'web'],
                    'player_skip': ['webpage', 'configs']
                }
            },
            # [Fix 403 Forbidden] User-Agent & Referer 최적화
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': 'https://www.youtube.com/',
                'Sec-Fetch-Mode': 'navigate'
            },
            'nocheckcertificate': True,
        }
        
        # [Windows Cookie 이슈 대응]
        # 만약 위의 설정으로도 403이 발생하면, 크롬이 아닌 'edge' 쿠키 사용을 시도해볼 수 있습니다.
        # Edge는 보통 잠금 이슈가 덜하며, 아래 주석을 해제하여 테스트 가능합니다.
        # if os.name == 'nt':
        #     ydl_opts['cookiesfrombrowser'] = ('edge', )

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

                # 3. 다운로드 수행
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
            logger = get_logger("downloader")
            if task_id:
                log_task_error(task_id, "download_from_url", e)
            else:
                log_error_with_traceback(logger, f"Download failed for URL: {url}", e)

            if "cancelled by user" in str(e):
                print(f"[Downloader] Task {task_id} cancelled. Cleaning up partial files...")
                if 'final_path' in locals() and final_path:
                    self._cleanup_partial_files(final_path)
                return {"status": "error", "message": "User cancelled the download"}

            if isinstance(e, DownloadError) and self._is_update_required_error(str(e)):
                upgrade_result = self._attempt_ytdlp_upgrade()
                if upgrade_result.get("status") == "updated":
                    print(f"[Downloader] yt-dlp upgraded ({upgrade_result.get('current_version')} -> {upgrade_result.get('latest_version')}). Restart required.")
                    if 'final_path' in locals() and final_path:
                        self._cleanup_partial_files(final_path)
                    return {
                        "status": "restart_required",
                        "message": "yt-dlp 업데이트가 완료되었습니다. 서버를 재시작한 뒤 다시 시도해주세요.",
                        "reason": "yt-dlp_updated",
                        "details": upgrade_result,
                    }
                print(f"[Downloader] yt-dlp auto-upgrade skipped/failed: {upgrade_result.get('message')}")
            
            print(f"[Error] Download failed: {e}")
            if 'final_path' in locals() and final_path:
                self._cleanup_partial_files(final_path)
            return {
                "status": "error",
                "message": str(e)
            }

    def _cleanup_partial_files(self, final_path):
        """
        다운로드 중단 시 남겨진 임시 파일(.part, .ytdl 등)을 정리합니다.
        """
        try:
            base_dir = os.path.dirname(final_path)
            full_name = os.path.basename(final_path)
            # 확장자를 제외한 순수 파일명 (예: Apple.mp4 -> Apple)
            base_name = os.path.splitext(full_name)[0]
            
            if not os.path.exists(base_dir):
                return

            print(f"[Cleanup] Scanning for partial files starting with: {base_name}")
            
            # 해당 파일명으로 시작하는 모든 파일을 검사
            for f in os.listdir(base_dir):
                # 1. 원본 파일명과 정확히 일치하는 경우
                # 2. 확장자 제외 파일명(base_name)을 포함하면서 임시 확장자를 가진 경우
                if f == full_name or (base_name in f and (".part" in f or ".ytdl" in f or ".temp" in f)):
                    file_path = os.path.join(base_dir, f)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"[Cleanup] Removed partial file: {f}")
        except Exception as e:
            print(f"[Cleanup Error] Failed to remove partial files: {e}")

# --- [Module Test Code] ---
if __name__ == "__main__":
    # 이 파일을 직접 실행했을 때만 작동하는 테스트 코드
    downloader = VideoDownloader(download_dir="../static/videos")
    
    # Test URL Download
    test_url = "https://chzzk.naver.com/video/10561205" # 테스트용 URL
    result = downloader.download_from_url(test_url)
    print("Result:", result)
