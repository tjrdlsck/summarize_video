# 🔍 프론트엔드 CDN 버전 고정 누락 분석 보고서 (Frontend Version Pinning Analysis)

본 보고서는 프로젝트의 프론트엔드 진입점인 `templates/index.html`에서 외부 CDN을 통해 로드하고 있는 외부 라이브러리(Dependencies)들의 버전 고정(Version Pinning) 여부를 진단하고, 잠재적 장애 가능성을 분석한 결과입니다.

---

## 1. 식별된 미지정/불안정 버전 CDN 로드 지점

현재 [templates/index.html](file:///home/radi/cli/summarize_video/templates/index.html)에서는 다음과 같은 라이브러리들을 버전을 지정하지 않은 채 최신 버전(`@latest` 또는 리다이렉트 경로)으로 불러오고 있습니다.

### ① Marked (마크다운 파서)
*   **현재 코드:** `<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>`
*   **위험도:** **상 (High)**
*   **분석:** 
    버전 정보가 누락되어 항상 `marked` 라이브러리의 최신 메이저/마이너 릴리즈를 불러옵니다.
    `marked` 라이브러리는 최근 메이저 업데이트(v4 ~ v12) 과정에서 `marked(text)` 함수 호출 방식의 직접 호출을 폐기하고 `marked.parse(text)` 형식을 표준화하는 등 파괴적인 API 변경(Breaking Changes)을 수시로 수행했습니다. 
    만약 향후 새로운 메이저 버전이 출시되고 기존 `marked.parse` 메서드가 감춰지거나 변경될 경우, UI 상에서 설교 요약 노트 및 AI 블로그 글 렌더링이 즉각 중단되며 브라우저 콘솔에 `TypeError`를 출력하게 됩니다.

### ② Axios (HTTP 비동기 통신 클라이언트)
*   **현재 코드:** `<script src="https://unpkg.com/axios/dist/axios.min.js"></script>`
*   **위험도:** **상 (High)**
*   **분석:**
    버전 명시 없이 `unpkg.com` CDN을 호출하므로 매번 최신 배포 버전을 탐색하여 로딩합니다.
    Axios 역시 0.x 대역에서 1.x 대역으로 전환되면서 에러 객체 처리(AxiosError), 인스턴스 설정 및 CancelToken 등의 스펙 변경이 있었습니다.
    프론트엔드 통신(GET, POST, DELETE 등)이 애플리케이션 전반에서 Axios에 전적으로 의존하고 있어, 라이브러리 업데이트 시 API 데이터 요청 자체가 실패하는 치명적인 네트워크 불통 장애가 발생할 위험이 있습니다.
    더불어, 버전을 생략하면 CDN 측에서 302 리다이렉션(Redirect)을 발생시켜 브라우저 로딩 지연(Latency)이 가중됩니다.

### ③ Babel Standalone (JSX 컴파일러)
*   **현재 코드:** `<script src="https://unpkg.com/@babel/standalone@7/babel.min.js"></script>`
*   **위험도:** **중 (Medium)**
*   **분석:**
    메이저 `@7` 대역만 지정되어 있어 마이너/패치 버전 업데이트에 노출되어 있습니다.
    JSX 및 최신 ESNext 자바스크립트 문법을 브라우저 런타임에서 온더플라이(On-the-fly) 컴파일해주는 중요한 중추이므로, Babel 마이너 릴리즈 오류 발생 시 컴포넌트 마운팅 시점에 문법 해석 에러를 유발할 수 있습니다.

### ④ React & React-DOM
*   **현재 코드:**
    ```html
    <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    ```
*   **위험도:** **하 (Low) ~ 성능 영향**
*   **분석:**
    `@18` 메이저 대역으로 고정되어 호환성 파괴 위험은 적으나, 상세 마이너/패치 버전까지는 명시되지 않았습니다.
    또한 프로덕션 서비스 배포 환경에서도 여전히 `.development.js`를 임포트하여 작동하므로, 불필요한 성능(Performance) 오버헤드와 함께 개발자 경고 콘솔을 브라우저에 가중시키는 문제가 있습니다.

---

## 🛠️ 권장 개선 제안 (Recommended Pinning Specs)
외부 환경 요인에 구애받지 않고 항상 프론트엔드가 동일한 동작을 수행하도록 CDN 주소를 **정확한 패치 버전까지 고정(Pinning)** 하는 것을 권장합니다.

```html
<!-- React & ReactDOM (v18.3.1 정밀 고정 및 프로덕션 빌드 전환) -->
<script crossorigin src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>

<!-- Babel Standalone (v7.24.7 고정) -->
<script src="https://unpkg.com/@babel/standalone@7.24.7/babel.min.js"></script>

<!-- Marked (v12.0.1 고정으로 parse API 호환 보장) -->
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.1/marked.min.js"></script>

<!-- Axios (v1.7.2 고정으로 API 통신 안정화 및 302 리다이렉션 오버헤드 방지) -->
<script src="https://unpkg.com/axios@1.7.2/dist/axios.min.js"></script>
```
