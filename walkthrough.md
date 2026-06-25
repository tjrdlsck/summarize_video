# 💡 버그 분석 및 해결 보고서: 쇼츠(Shorts) 자동생성 클립 미삭제 현상 및 과거 고아 파일(Orphaned Files) 정리

## 🔍 문제 정의 (Problem Definition)
초기화면에서 카드(분석된 영상 내역)를 삭제할 때, 영상과 관련된 대부분의 결과 파일은 삭제되나 **AI 쇼츠 기획/자동생성으로 만들어진 클립 파일(`.mp4`, `.srt`, `.vtt`, `.zip`)이 삭제되지 않고 고아 파일(Orphaned File)로 남는 현상**이 발생했습니다. 

### 🧨 근본 원인 (Root Cause)
1. **파일명 매칭 규칙의 불일치:**
   - 기존 `app/api/routers/history.py`의 `delete_history()` 로직은 `CLIPS_DIR` 내부를 순회하며 클립의 파일명에 `base_name`(원본 영상의 확장자 제외 이름)이 포함되어 있는지(`if base_name in clip_name:`) 확인하여 삭제를 진행했습니다.
   - 하지만 AI 숏츠는 `AI_Shorts_{index}_{safe_title}.mp4` 와 같은 독자적인 네이밍 규칙을 사용하여 저장되므로, 파일명에 원본 영상의 `base_name`이 존재하지 않습니다. 이로 인해 조건에 일치하지 않아 삭제 루프에서 누락되었습니다.
2. **청소(Cleanup) 데몬 로직의 동일한 문제:**
   - 서버 시작 시 동작하는 `app/application/cleanup.py`의 `cleanup_orphaned_files()`에서도 원본 영상이 없는 '좀비(Zombie)' 결과를 삭제할 때, 단순 메타데이터 파일 자체만 삭제하고 실제 숏츠 비디오는 지우지 못하는 동일한 취약점이 있었습니다.
3. **과거에 발생한 고아 파일 방치 위험:**
   - 버그 픽스 이전(과거)에 삭제된 카드의 경우 이미 `_clips.json` 메타데이터마저 삭제되었기 때문에, 메타데이터를 기반으로 한 삭제 픽스조차 이들을 구제할 수 없어 영구적인 용량 누수(Storage Leak)가 발생할 수 있습니다.

## 🛠️ 해결 메커니즘 (Resolution Mechanics)

### 1. `app/api/routers/history.py` 수정 (정상적인 카드 삭제 시)
*   카드(History) 삭제 요청 시, `_clips.json` 파일이 존재하는지 가장 먼저 확인합니다.
*   파일이 있다면 JSON 객체 배열을 파싱하여, 각각의 `clip` 딕셔너리에서 `filename_video`, `filename_zip`, `filename_vtt` 값을 추출하고 쌍을 이루는 자막 파일(`.srt`, `.vtt`)도 함께 구성하여 명시적으로 삭제하도록 했습니다.

### 2. `app/application/cleanup.py` 수정 (서버 기동 시 Deep Cleanup)
*   **좀비 레코드 삭제 보완:** 서버 기동 시 고아 레코드를 탐지했을 때, 삭제 대상(`zombie_targets`) 목록을 비우기 전에 동일하게 `_clips.json`을 읽어들여 AI 숏츠 실물 파일들을 지우도록 로직을 갱신했습니다.
*   **Deep Orphan Cleanup 도입 (안전한 전체 스캔):** 
    - 서버 기동 시 한 번, `RESULTS_DIR` 내의 모든 `_clips.json`을 순회하며 **현재 유효한 모든 AI 숏츠 실물 파일명들의 집합(Set)** 을 생성합니다. (`valid_clip_files`)
    - 또한 `VIDEOS_DIR` 내의 유효한 비디오들의 `base_name` 집합도 구성합니다. (`valid_base_names`)
    - 그 후 `CLIPS_DIR` 내부를 전수 검사하여, **1) 유효한 클립 파일 목록에 없고, 2) 유효한 비디오의 `base_name`을 이름에 포함하지 않은 파일**은 완벽한 고아 파일(과거 버그로 인해 버려진 파일)로 간주하고 일괄 삭제하는 로직을 마지막 단계에 주입했습니다.
    - 이를 통해 기존 작업물(살아있는 카드)의 클립은 절대 날아가지 않도록 안전하게 보호하면서도, 과거의 찌꺼기 파일들까지 모두 청소(GC: Garbage Collection)합니다.

## 🎓 교훈 (Lessons Learned)
*   **메타데이터 기반의 의존성 관리:** 리소스 간의 생명 주기(Lifecycle)를 관리할 때, 파일명 규칙에 의존하는 하드코딩 방식은 예기치 않은 데이터 누수(Memory/Storage Leak)를 초래할 수 있습니다.
*   **Deep Cleanup (가비지 컬렉션):** 에러가 수정되기 전 누적된 고아 파일들을 청소할 때는 항상 **"지워야 할 것"을 찾는 것보다 "살려야 할 유효한 리소스(Set)"를 확정하고 그 외의 것을 지우는 방식**이 훨씬 안전하며 기존 데이터를 유실할 위험을 원천 차단합니다.

---

> [!NOTE]
> 해당 수정 사항은 현재 브랜치에 코드 레벨로 직접 반영되었습니다. 로컬 단위 테스트가 완료되면 확인 후 Commit 및 Push를 진행하시면 됩니다.

## 🔍 추가 수정: 요약노트 `<mark>` 하이라이팅 프론트엔드 미출력 문제
- **원인:** LLM 프롬프트에 `` `<mark>핵심 문장</mark>` `` 형식으로 백틱(\`) 기호와 함께 프롬프트를 주입하여, LLM이 실제로 백틱까지 텍스트로 생성해버리는 문제가 있었습니다. 이로 인해 프론트엔드의 `marked.js`가 이를 실제 HTML 태그가 아닌 인라인 코드(`<code>`) 블록으로 해석하여 렌더링이 무시되었습니다. (프론트엔드의 CSS 자체는 정상적으로 `.markdown-body mark` 로 구현되어 있었습니다.)
- **수정:** `services/summarizer.py`와 `services/refiner.py`의 프롬프트를 수정하여 백틱을 제거하고, 순수 HTML 태그만 출력하도록 가이드라인을 명확하게 갱신했습니다.

---

# 💡 버그 분석 및 해결 보고서: 동영상 시간 포맷팅 방식 오류 (hh:mm:ss 미적용)

## 🔍 문제 정의 (Problem Definition)
비디오 요약 및 쇼츠 자동생성 도구의 재생 시간 혹은 챕터 표시 영역에서 시간 타임스탬프가 `98:23`과 같이 60분을 초과하여 `mm:ss` 형식으로 노출되는 현상이 발생했습니다. 동영상의 전체 길이가 1시간 이상인 경우 시(hour) 단위로 올바르게 파싱되지 않아 가독성이 저해되었습니다.

### 🧨 근본 원인 (Root Cause)
`static/js/app.js` 파일 내의 `formatTimeSimple` 함수는 입력받은 초(seconds) 단위 시간을 단순히 분(minute)과 초(second)로만 변환하도록 설계되어 있었습니다.
```javascript
    const formatTimeSimple = (s) => {
        if (!s && s !== 0) return "0:00";
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0' : ''}${sec}`;
    };
```
이로 인해 `s = 5903`초(98분 23초)와 같이 3600초(1시간)를 넘는 값에 대해서도 `Math.floor(s / 60)`이 적용되어 `98:23`으로 표시되는 버그가 발생했습니다.

## 🛠️ 해결 메커니즘 (Resolution Mechanics)
사용자 인터페이스(UI) 측면에서 1시간 미만의 동영상에 대해서는 직관적인 `mm:ss` 포맷을 유지하고, 1시간 이상의 동영상에 대해서만 `h:mm:ss` 형식으로 자동 전환되어 가독성을 높일 수 있도록 조건부 렌더링 로직을 도입했습니다.

### 1. `static/js/app.js` 수정
`formatTimeSimple` 함수를 다음과 같이 수정하여 시간(`h`), 분(`m`), 초(`sec`) 단위를 구분하여 계산하도록 하였습니다.
```javascript
    const formatTimeSimple = (s) => {
        if (!s && s !== 0) return "0:00";
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = Math.floor(s % 60);
        if (h > 0) {
            return `${h}:${m < 10 ? '0' : ''}${m}:${sec < 10 ? '0' : ''}${sec}`;
        }
        return `${m}:${sec < 10 ? '0' : ''}${sec}`;
    };
```
- **1시간 이상인 경우 (`h > 0`):** `h:mm:ss` 형식으로 변환하여 반환합니다. (예: `1:38:23`)
- **1시간 미만인 경우 (`h == 0`):** 기존 `mm:ss` 형식으로 변환하여 반환합니다. (예: `05:30`)

## 🎓 교훈 (Lessons Learned)
* **시간 계산의 한계 설정:** 시간 단위를 변환할 때 다루는 데이터의 최대값 범위(여기서는 1시간 이상의 동영상 지원 여부)를 미리 파악하고 설계해야 합니다.
* **조건부 포맷팅의 유용성:** 고정된 포맷(`hh:mm:ss`)을 강제하기보다는, 데이터의 규모에 맞는 가변 포맷을 적용함으로써 사용자 경험(UX)을 극대화할 수 있습니다.
