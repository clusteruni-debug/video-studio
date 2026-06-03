# Claude in Chrome — grok/Gemini 영상 생성 핸드오프

> 새 세션에서 "grok 영상 이어가자"라고 하면 이 파일을 읽고 이어간다.

## 상태: ✅ 검증 완료 (2026-06-03)
grok·Gemini 둘 다 Claude in Chrome으로 **생성 + 다운로드 완주 검증됨**. 방향은 **C1 반자동 확정** (유료 API 미사용, 구독 세션 재사용).

## 목표
Claude Code가 사용자의 **로그인된 Chrome 기본 프로필**에서 grok.com/imagine + gemini.google.com Veo로
직접 영상을 생성한다. xAI/Gemini 유료 API 미사용 — 구독 세션 재사용.

## 확정된 방향 (변경 금지)
- **CDP/브리지 방식 폐기**: `routes_grok.py`의 CDP attach는 Chrome 136+ 기본 프로필 remote-debugging
  차단으로 로그인 세션에 부적합. 격리 프로필만 CDP 동작(로그인 없음).
- **Claude in Chrome 확장 방식 채택 + 검증 완료**: "shares browser login state" — 로그인 세션 그대로.
- **C1 반자동 확정 (2026-06-03 사용자 결정)**: API 안 씀. 아래 "API 분기 검토" 참조 — grok 공식 API가
  생겼지만($0.07/초) 사용자가 **0원 유지 + 실험적 사용**을 위해 반자동을 명시 선택.

## API 분기 검토 결과 (2026-06-03 리서치, 기록용)
- **Grok Imagine 공식 API 존재** (2026.1 출시): 720p **$0.07/초**, 10초 $0.70, 오디오 포함, Python SDK.
  → 핸드오프 최초 작성 시 "유료 API 미사용" 전제는 *API 없던 시절* 기준. 이제 grok은 API 선택지 있음.
- **Gemini Veo 3.1 API**: Fast $0.15/초, Standard $0.40/초 (grok의 2~6배). 무료 티어 없음.
- **결정**: 사용자가 C1(반자동, $0) 선택. C2(grok API adapter, 영상당 ~$0.5, 완전 자동)는 보류.
  볼륨/무인 배치 수요가 생기면 C2 재검토 (video-studio에 이미 `scripts/veo3_video.py` adapter 패턴 존재).

## 이번 세션 검증 결과 (2026-06-03)
프롬프트 동일: `A golden retriever puppy running on a sandy beach at sunset, slow motion, cinematic`

### grok.com/imagine ✅ (자동화 친화)
- 좌표·`read_page` ref·스크린샷 전부 동작. ref 기반 클릭이 레이아웃 리플로우에 강함(좌표는 깨짐).
- 동영상 모드 + 720p + 9:16, 제출 버튼 = `제출`[type=submit].
- 생성 **~25초**. 다운로드 결과: `grok-video-5dffd932-...mp4` **4.7MB**.

### gemini.google.com Veo ⚠️ (JS-only 우회 필요)
- **스크린샷·read_page·find 전부 45초 타임아웃** — Gemini SPA가 지속적 스트리밍으로 `document_idle`에
  안 들어감. 시각 도구 전멸 → **`javascript_tool`로만** 조작.
- 동작 시퀀스(재현용): `업로드 및 도구` 버튼 pointer-event 클릭 → 메뉴에서 텍스트가 정확히
  `동영상 만들기`인 **leaf 요소** 찾아 클릭가능 조상으로 이벤트 전파 → `.ql-editor`(Quill)에
  `document.execCommand('insertText', ...)` 로 프롬프트 입력 → `메시지 보내기` 클릭 → `video` 요소
  나타날 때까지 폴링 → `동영상 다운로드` 버튼 클릭.
- 생성 **몇 분** (grok보다 느림). 다운로드 결과: `A_golden_retriever_puppy_runni.mp4` **4.0MB**.
- 주의: `video.src`가 쿼리스트링 URL이라 JS 반환 시 보안 필터에 `[BLOCKED]` — src는 존재 여부(boolean)만 확인.

### 공통 병목
- **OS 저장 대화상자는 사용자 수동 클릭 필요**. Claude in Chrome은 웹페이지 내부만 조작, 브라우저 밖
  OS 네이티브 창은 못 건드림(보안 경계).
- **해소법**: `chrome://settings/downloads` → "다운로드하기 전에 각 파일의 저장 위치 확인" OFF
  (= `download.prompt_for_download=false`) → 클릭 없이 다운로드 폴더로 자동 저장. (chrome:// 설정은
  확장이 못 건드려 사용자가 직접 OFF)

## 반자동 워크플로 (C1 확정 절차)
1. **생성**: Claude in Chrome으로 grok(주력)/gemini → 영상 생성 → 다운로드 (위 시퀀스)
2. **import**: 다운로드된 mp4를 video-studio 브리지 `upload-mp4` "operator-saved local MP4 import"
   경로로 넣음 (아래 통합 경로 참조)
3. **합성**: 기존 compose 파이프라인 (`python -m worker.render.compose --project-id <id>`)

## video-studio 통합 경로 (발견 — 2026-06-03)
- **import 엔드포인트**: `POST http://127.0.0.1:5161/api/grok-handoff/<projectId>/upload-mp4`
- `routes_media.py:9689` `_source_recovery_direct_import_runway` 의 `allowedRoutes`에
  **"operator-owned already-saved local MP4 import"** 명시 = **우리가 다운로드한 mp4가 바로 이 경로**.
- `forbiddenActions`: "Chrome native download prompt", "Downloads watcher fallback" 등 — *자동 감시*
  경로는 금지. 우리는 *이미 저장된* 파일을 POST하는 거라 금지 대상 아님(operator-saved 경로).
- 영상 자산은 manifest에서 `provider:"upload"`, `outputPath/sourcePath =
  storage/inputs/<pid>/uploads/scene-NN/<file>.mp4`. **manifest 직접 편집 금지** — 브리지 import가 갱신.

## 다음 구현 단계
1. ✅ **import 헬퍼 작성 완료** (`scripts/import_chrome_video.py`, 2026-06-03):
   - base64 JSON으로 `upload-mp4` POST. `--project-id`/`--scene-id` + `--file` 또는 `--latest`
     (다운로드 폴더 최신 mp4 자동 선택), `--dry-run`, `--overwrite`. `grok_video.py` urllib 패턴 재사용.
   - upload-mp4 입력 형식 확정: `operatorApproved`+`sceneId`+`fileBase64`+`fileName(.mp4)`
     (routes_grok.py:9691 `_decode_uploaded_mp4`, :12625 라우트 핸들러).
   - **자체 검증됨**: `python -m compileall` 통과 + dry-run으로 파일읽기→base64(4.42MB→5.89M chars)→
     payload/URL 구성 확인 + 빈 폴더 "mp4 없음" 에러핸들링 정상. (POST는 미실행)
2. ⏳ **E2E 검증 (미완료 — 브리지 필요)**: `npm run bridge`(5161) + handoff 프로젝트 생성 후
   → 헬퍼로 실제 import → manifest에 `provider:"upload"` asset 등록 + compose 입력으로 잡히는지 확인.
   사용자가 브리지 띄울 수 있을 때 (WSL은 Windows localhost 접근 불가). 신규 스크립트라 이때 리뷰 1패스 병행.
3. ⏳ **handoff 프로젝트 생성 흐름**: import의 전제(프로젝트 선행 — 없으면 404). `POST /api/grok-handoff`
   (`grok_video.py` create_handoff 참고). 헬퍼에 `--create-handoff` 옵션 추가 검토 (현재는 import 전담).

## 정리 대상 (디스크/코드 청소)
- `scripts/grok_video.py` + `tests/test_grok_video_cli.py`: CDP 방식 — **폐기 가능 확정**
  (Claude in Chrome 방식 검증 완료). 단 삭제 전 사용자 확인.
- `storage/grok-handoffs/*`: 이전 CDP 시도의 Chrome browser-profile/cdp-profile 잔여물 **대량**
  (model.tflite/manifest 등 수백 파일). 디스크 낭비 — 정리 후보. 삭제 전 사용자 확인.

## 환경 (확인됨)
- Claude Code 2.1.161 (요구 2.0.73+ 충족), Chrome 기본 프로필 로그인 상태
- Anthropic 플랜 + Gemini Pro/Ultra + SuperGrok 구독 보유
- Claude in Chrome 사이트 권한: "모든 사이트 허용" 상태 (사용자 설정)
- 연결: `claude --chrome`로 시작 → `/chrome` connected → `list_connected_browsers` → `select_browser`
