# [버그 수정] 동영상 구간 자르기 시 두 번째(중간 구간) 내보내기부터 오디오(소리) 유실되는 버그 해결 계획

동영상 구간 잘라내기(Export) 기능을 사용할 때, 첫 번째 내보내기(영상 시작점인 0초 부근을 포함하는 경우)에는 소리가 정상적으로 포함되지만, 두 번째 내보내기(영상 중간 구간을 자르는 경우)부터는 오디오 스트림은 존재하나 소리가 완전히 안 나오는(무음, -91dB) 현상이 발생합니다.

## User Review Required

> [!NOTE]
> 본 수정은 FFmpeg 명령어 내부의 `-ss`와 `-to` 옵션의 배치 순서 및 옵션 정의를 변경합니다.
> 기존에 입력 파일(`-i`) 뒤에 두었던 **출력 옵션** 방식에서, 입력 파일 앞쪽으로 배치하는 **입력 옵션** 방식으로 변경합니다. 
> 이와 동시에 `-to` 대신 **길이(Duration)**를 지정하는 `-t` 옵션으로 전환하여 FFmpeg 버전에 관계없이 정확한 프레임 이동(Seek)과 오디오 필터 타임라인 일치를 확보합니다.
> 이 변경은 비디오 인코딩 속도를 대폭 개선하며 프레임 정확도는 그대로 유지됩니다.

## Proposed Changes

### Video Processing Service

#### [MODIFY] [services/clipper.py](file:///home/radi/cli/summarize_video/services/clipper.py)
- `cut_video` 메서드 내부의 FFmpeg 명령어 리스트(`cmd`) 구성을 변경합니다.
- `duration = end_sec - start_sec` 값을 구한 뒤, `-ss`와 `-t`를 `-i` 앞에 추가합니다.
- 기존 `-i input_path -ss start -to end` 순서에서 `-ss start -t duration -i input_path` 순서로 마이그레이션합니다.

```diff
@@ -80,48 +80,49 @@
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
         # OS 및 그래픽 카드 가속 여부에 따른 인코더 설정
         if self._is_nvenc_available():
             # NVIDIA NVENC 가속 사용 (Windows / Linux 공용)
             encoder = "h264_nvenc"
             quality_opts = ["-rc", "vbr", "-cq", "24", "-preset", "p4"]
         elif sys.platform == 'darwin':
             # macOS: Apple Silicon 가속 사용
             encoder = "h264_videotoolbox"
             quality_opts = ["-q:v", "65"]
         else:
             # Linux 및 기타 OS: CPU 기반 범용 libx264 사용
             encoder = "libx264"
             quality_opts = ["-crf", "23", "-preset", "medium"]
 
         # [FFmpeg Command Configuration]
         cmd = [
             "ffmpeg", 
             "-nostdin",
-            "-i", input_path,
-            "-ss", str(start_sec),
-            "-to", str(end_sec),
+            "-ss", str(start_sec),
+            "-t", str(duration),
+            "-i", input_path,
             "-filter_complex", f"[0:a]{audio_filter}[af]", # 오디오 필터 적용
             "-map", "0:v", "-map", "[af]",                 # 비디오는 그대로, 오디오는 필터 거친 것 사용
             "-c:v", encoder,                               # 자동 선택된 인코더
         ]
```

## Verification Plan

### Automated Tests
1. 기존 Clipper 유닛 테스트 실행하여 인코더 선택 모킹 로직이 정상 작동하는지 확인합니다.
   - Command: `./venv/bin/pytest tests/test_clipper.py`
2. **[신규] 영상 중간 구간 자르기 및 오디오 볼륨 검증 테스트 (`tests/test_clipper_audio_leak.py`)**:
   - `start_time = 0` (영상 처음)인 경우와 `start_time > 5.0` (영상 중간)인 경우를 모두 테스트하여, 생성된 모든 클립의 오디오 볼륨이 무음($-91.0\text{ dB}$)이 아닌 정상적인 오디오 볼륨 범위(예: $-30\text{ dB} \sim 0\text{ dB}$)를 갖는지 FFmpeg `volumedetect` 필터를 통해 검증하는 자동화 테스트 코드를 구현하고 커밋에 포함합니다.
   - Command: `./venv/bin/pytest tests/test_clipper_audio_leak.py -s`

### Manual Verification
- 테스트용 비디오 파일을 직접 컷팅하는 스크립트를 수동으로 실행해 보고, 생성된 클립 파일들의 오디오 스트림 유효성과 볼륨을 확인합니다.
