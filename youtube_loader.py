import os
import yt_dlp
import re

class YouTubeLoader:
    """
    yt-dlp를 래핑하여 유튜브 영상을 다운로드하는 클래스.
    - 공개(Public) 및 미등록(Unlisted) 영상 지원
    - Whisper 전사를 위해 오디오 품질 우선 고려
    """
    def __init__(self, output_dir="video"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _sanitize_filename(self, title):
        """파일 시스템에 저장하기 안전한 이름으로 변환"""
        # 윈도우/리눅스 파일명 금지 문자 제거
        clean_name = re.sub(r'[\\/*?:"<>|]', "", title)
        return clean_name.strip().replace(" ", "_")

    def download_video(self, url):
        """
        주어진 URL의 영상을 다운로드합니다.
        
        Return:
            downloaded_path (str): 다운로드된 파일의 절대 경로 (실패 시 None)
            metadata (dict): 영상 제목, 썸네일 등 메타 정보
        """
        print(f"--- [YouTube Loader] Processing URL: {url} ---")
        
        # yt-dlp 옵션 설정 (공식 문서 참조)
        # format: 비디오는 mp4 중 화질 적당한 것 + 오디오는 최고 음질(m4a/webm) 병합
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': f'{self.output_dir}/%(title)s.%(ext)s', # 저장 경로 템플릿
            'noplaylist': True,        # 플레이리스트 무시 (영상 1개만)
            'quiet': False,            # 로그 출력 허용
            'no_warnings': True,
            # 'overwrites': True,      # 덮어쓰기 허용 여부
            
            # [Progress Hook] 진행 상황 출력
            'progress_hooks': [self._progress_hook],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 1. 메타데이터 추출 (다운로드 전 정보 확인)
                info_dict = ydl.extract_info(url, download=False)
                video_title = info_dict.get('title', 'video')
                video_ext = info_dict.get('ext', 'mp4') # 예상 확장자
                
                safe_title = self._sanitize_filename(video_title)
                
                # 파일명 강제 지정을 위해 outtmpl 재설정 (파일명 깨짐 방지)
                final_filename = f"{safe_title}.mp4"
                final_path = os.path.join(self.output_dir, final_filename)
                
                ydl.params['outtmpl'] = {
                    'default': str(final_path)
                }

                print(f" -> Target Filename: {final_filename}")

                # 2. 실제 다운로드 수행
                if os.path.exists(final_path):
                    print(" -> File already exists. Skipping download.")
                else:
                    ydl.download([url])

                return final_path, info_dict

        except Exception as e:
            print(f"[Error] YouTube Download Failed: {e}")
            return None, None

    def _progress_hook(self, d):
        """다운로드 진행률 콜백"""
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%')
            print(f"   Downloading: {p}", end='\r')
        elif d['status'] == 'finished':
            print(f"\n   Download Complete!")

# --- [Test Block] ---
if __name__ == "__main__":
    # 테스트용 URL (예: 유튜브 테스트 영상)
    TEST_URL = "https://chzzk.naver.com/video/10561205" # 최초의 유튜브 영상
    
    loader = YouTubeLoader(output_dir="video_downloads")
    path, meta = loader.download_video(TEST_URL)
    
    if path:
        print(f"Success! Saved at: {path}")
        print(f"Title: {meta.get('title')}")