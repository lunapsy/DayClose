# 01 — 제품 요구사항 (PRD)

> 요구사항 원천: `CONTEXT.md`. 나중 턴이 앞 턴을 덮어쓴다(개발 단계 = 턴1의 6단계, MVP = 턴2, 안전 설계 선행 = 턴4).
> 용어·이름은 `02-ARCHITECTURE.md`, `06-DATA-MODEL.md` 를 따른다.

## 1. 제품 정의

**DayClose — End your day with a clean Mac.**
오늘의 작업은 남기고, 오늘의 어지러움은 정리한다.

DayClose 는 macOS 용 **Digital Housekeeping Agent** 다. 디스크 청소기가 아니다.
- 청소 프로그램은 이미 어질러진 환경을 복구한다. DayClose 는 **하루의 변화량(Delta)** 을 매일 결산해 애초에 어질러지지 않게 한다.
- 결재함처럼 보여주고, 사용자가 30초~1분 안에 판단하고, 승인된 것만 안전하게 실행한다.
- 반복되는 판단은 기억해 사용자의 판단 부담을 계속 줄인다. 이것이 차별점이다(파일 분류 정확도가 아니라).
- 키·인증서 같은 중요한 디지털 자산은 “정리 대상”이 아니라 “보호·관리 대상”으로 따로 다룬다.

## 2. 페르소나

**P1 — 주 사용자 (소유자 본인)**: 약국을 운영하는 약사이자 1인 개발자.
- 기기: MacBook Pro(주 작업), Mac mini(상시 가동 서버 역할, docker 컨테이너 다수), 약국의 Synology NAS.
- 작업: 여러 개발 프로젝트(`~/dev/*`)를 동시에 진행, Claude Code·Codex 를 많이 사용 → 스크린샷·다운로드·임시 문서·설치 파일이 매일 쌓인다.
- 보유 자산: Apple Developer 키(`.p8`, `.p12`, `.mobileprovision`), Android keystore, SSH 키, `.env`, 클라우드 서비스 계정 키, 공동인증서(NPKI).
- 민감 자료: 약국·환자 관련 자료(처방·조제 관련 문서, 스크린샷). 외부 전송 절대 금지.
- 제약: 내장 SSD 245GB 가 자주 가득 참. 외장 SSD(`/Volumes/External`) 상시 연결. launchd 프로세스의 `/Volumes` 접근은 FDA 없으면 멈춤.
- 기대: 매일 저녁 1분 투자, 실수로 중요한 것을 지우지 않는다는 확신, 터미널/에이전트에서도 호출 가능.

**P2 — 코딩 에이전트 (Claude Code / Codex 세션)**: P1 을 대신해 결산을 조회하고 정리 계획을 만들 수 있다. 승인은 할 수 없다(사람 게이트).

## 3. 모듈 구성

| 모듈 | 역할 | 주 마일스톤 |
|---|---|---|
| Daily Review | 하루 동안의 변경 사항 결산, 결재함 | M2(CLI), M4(앱) |
| Smart Organizer | 파일·프로젝트 문맥별 정리 제안 | M2(휴리스틱), M6(AI) |
| Visual Review | 이미지·문서 미리보기 및 개별 판단 | M4 |
| App Manager | 앱·Homebrew·개발 환경·로그인 항목 점검 | M3(읽기 전용) |
| Secure Vault | 키·인증서·보안 자산 탐지·인벤토리·건강 점검 | M3(읽기 전용), M8(암호화 백업) |
| Archive & Backup | NAS/외장 보관, 암호화 백업, 복구 검증 | M5(로컬/외장 대상), M8(NAS) |
| 공통: Personal Policy & Memory Engine | 보호 정책, 사용자 선호, 프로젝트 문맥, 규칙, 판단 이력 | M2(보호·suppression), M6(학습) |
| 공통: Safe Execution | 승인된 계획만 실행, 휴지통, 이동, undo | M5 (설계·가드는 M1부터) |

인터페이스: CLI(M1~), SwiftUI 앱(M4~), 메뉴바·알림(M7), Agent Skill·MCP(M8).

## 4. 설계 원칙 (변경 불가)

Local-first · AI optional · Human-in-the-loop · Reversible · Incremental · Privacy-first · Agent-ready (CONTEXT 턴1).
추가 원칙(턴4): UI 와 파일 조작 엔진 분리 / AI 는 제안, 결정론적 엔진이 실행 / 미결정 항목은 다음 세션에 유지 / 활성 프로젝트·보안 자산 기본 보호 / 민감 정보 외부 모델 전송 금지 / 네이티브 API·검증된 오픈소스 우선 / 모든 주요 작업에 테스트와 실행 이력 / 불필요한 추상화 금지 / **안전 실행 엔진과 보호 정책은 처음부터**.

## 5. 기능 요구사항

형식: `ID — 요구사항` / 인수 기준(AC) / 마일스톤. AC 는 11 문서의 테스트로 1:1 검증한다.

### 5.1 Core & 스캔 (FR-CORE)

**FR-CORE-001 — 초기화.** `dayclose init` 이 상태 디렉터리·DB·설정을 만든다(필드 암호화 키는 M2 부터 함께 생성).
AC: 두 번 실행해도 결과 동일(멱등), 기존 데이터 보존. `DAYCLOSE_HOME` 권한 0700, DB 0600. M1.

**FR-CORE-002 — 기본 스캔 루트.** init 시 `~/Downloads`(downloads), `~/Desktop`(desktop), 스크린샷 저장 위치(`defaults read com.apple.screencapture location`, Desktop 과 다를 때만, screenshots), `~/Documents`(documents), `~/dev`(projects, 파일 단위 항목 없음)를 등록한다. `--no-default-roots` 로 생략.
AC: 존재하지 않는 경로는 등록하지 않고 경고. `root add/remove/list` 동작. M1.

**FR-CORE-003 — 증분 변경 감지.** `scan run` 은 직전 상태와 비교해 생성·수정·삭제·이동을 기록한다. 이동은 (dev, inode) 일치로 판정한다.
AC: 샌드박스에서 파일 생성/수정/삭제/이름변경 각각이 정확히 1개 이벤트로 기록. 변경 없는 재스캔은 이벤트 0. 패키지(`.app` 등)는 하나의 항목. 제외 규칙(`.DS_Store`, `node_modules`, `.git` 내부) 적용. M1.

**FR-CORE-004 — JSON 계약.** 모든 명령은 `--json` 에서 02 §5.4 봉투를 stdout 에 정확히 1개 출력한다.
AC: 계약 테스트가 모든 명령의 성공/실패 봉투를 `contracts/envelope.schema.json` 으로 검증. 오류 시 종료 코드가 02 §5.5 와 일치. M1.

**FR-CORE-005 — 환경 진단.** `dayclose doctor` 가 외부 도구 유무, 루트별 접근성(`ok|tcc_denied|timeout|missing`), DB 무결성·권한을 보고한다.
AC: TCC 거부(EPERM)와 일반 권한 오류를 구분. M1.

**FR-CORE-006 — 멈추지 않는 스캔.** `/Volumes/*` 아래 경로는 시간 제한 프로브 후 접근하며, 시간 초과 시 그 루트를 건너뛰고 경고한다. iCloud dataless 파일은 내용을 읽지 않는다.
AC: 프로브가 응답하지 않는 모의 경로에서 `scan run` 이 `volume_probe_timeout_s`+2초 안에 `W_ROOT_UNAVAILABLE` 로 끝남. dataless 플래그 파일은 해시 계산 안 함. M1.

**FR-CORE-007 — 쓰기 직렬화.** 쓰기 명령 동시 실행 시 하나만 진행, 나머지는 대기 후 `E_LOCKED`.
AC: 동시 `scan run` 2개 → 하나 성공, 하나 `E_LOCKED`(대기 0초 설정 시). M1.

### 5.2 Daily Review (FR-DR)

**FR-DR-001 — 일일 결산 지표.** 리뷰 날짜별로: 새 파일, 수정된 파일, 삭제된 파일, 새 앱, 새 패키지, 검토 대상 항목 수, 검토 완료 수, 휴지통 예정 수, 이월 수, 보류 수, 정리 시 확보 가능 용량, 예상 검토 시간.
결정: 예상 검토 시간 = ⌈(그룹 수 × 5초 + 그룹 밖 개별 항목 수 × 3초) / 60⌉분. 이유: “1분” 문구를 근거 있게 산출하는 최소 공식, 07 단계에서 실제 사용 기록으로 보정.
AC: 샌드박스 시나리오(새 파일 42, 수정 18)에서 `review summary` 수치 일치. M2.

**FR-DR-002 — 리뷰 날짜 경계.** 리뷰 날짜는 로컬 시간 기준이며 `review.day_boundary`(기본 04:00) 이전 활동은 전날로 귀속.
AC: 01:30 생성 파일이 전날 리뷰에 포함. M2.

**FR-DR-003 — 정리 그룹과 제안.** 항목은 그룹(설치 파일, 오늘의 스크린샷, 프로젝트별 작업, 중복, 새 보안 자산 등)으로 묶이고 그룹마다 제안 동작·이유를 가진다.
AC: 그룹 키 규칙(04 문서)대로 묶임. 제안이 없어도 그룹은 표시. M2.

**FR-DR-004 — 개별·그룹 결정.** 항목 단위와 그룹 단위로 `keep / keep_always / trash / move / archive / defer / acknowledge` 를 결정할 수 있다. 허용 동작은 `allowed_actions` 로 제한된다.
AC: 그룹 결정 시 `security_asset`·`patient_data` 항목은 건너뛰고 `W_PROTECTED_SKIPPED`. 허용되지 않은 동작은 `E_PROTECTED`. M2.

**FR-DR-005 — 결정은 파일을 바꾸지 않는다.** 결정은 계획 전까지 언제든 취소(`decision undo`, 앱의 ⌘Z)할 수 있다.
AC: `decision set` 전후 샌드박스 파일 트리 해시 동일. `planned` 이후 undo 는 `E_INVALID_STATE`. M2.

**FR-DR-006 — 이월.** 결정하지 않은 항목은 다음 리뷰 날짜에 자동 포함되고 “N일째” 가 표시된다(`carry_count`).
AC: D 일 미결 항목이 D+1 summary 에 포함, carry_count=1. 같은 날 summary 를 여러 번 호출해도 1회만 증가. M2.

**FR-DR-007 — 보류(S).** `defer` 는 지정일(기본 다음 리뷰 날짜)까지 항목을 숨긴다.
AC: `--defer-until D+3` 이면 D+1, D+2 summary 에 미포함·보류 수에 집계, D+3 에 재등장. M2.

**FR-DR-008 — 유지하고 다시 묻지 않기.** `keep_always` 는 같은 대상(파일 identity / 번들 ID / 패키지 / 저장소)을 이후 묻지 않는다. 설정 화면/CLI 에서 해제 가능.
AC: `keep_always` 후 같은 파일이 다른 루트로 이동해도 재질문 없음, 리포트의 “조용히 유지” 에 집계. `suppression remove` 후 다음 탐지 시 다시 질문. M2.

**FR-DR-009 — 일일 리포트.** `report daily` 가 Markdown/JSON 결산을 출력한다(정리 완료 후 리포트 포함).
AC: 보안 자산·환자 자료의 실제 파일명·경로가 리포트에 나오지 않음(마스킹 이름만). M2.

### 5.3 Smart Organizer (FR-SO)

**FR-SO-001 — 설치 파일.** DMG/PKG 중 대응 앱이 이미 설치된 것은 `trash` 를 제안한다.
AC: 샌드박스의 `Foo.dmg` + 설치된 `Foo.app`(가짜 Info.plist) → 제안 `trash`, 이유 “설치 완료된 설치 파일”. M2(판정은 M3 앱 인벤토리 이후 정확도 향상).

**FR-SO-002 — 중복.** 같은 SHA-256 파일은 중복 그룹으로 묶고 하나만 남기도록 제안한다.
AC: 64MB 이하 동일 파일 3개 → 그룹 1개, 최신 1개 `keep` 제안, 나머지 `trash` 제안. M2.

**FR-SO-003 — 프로젝트 문맥 매칭(휴리스틱).** 파일명·출처·생성 시각이 특정 프로젝트(`projects`)와 강하게 연관되면 해당 프로젝트의 `docs/`·`references/`·`screenshots/` 로 `move` 를 제안한다.
AC: 파일명에 프로젝트명 포함 시 confidence ≥ 0.6 제안. 목적지 폴더가 없으면 “생성 필요” 표시(생성은 executor 가 plan 의 일부로). M2.

**FR-SO-004 — 활성 저장소 보호.** 활성 git 저장소 내부 파일은 이동·휴지통 제안 대상이 아니다(`active_repo`). 예외: 재생성 가능한 개발 캐시(04 문서 목록)의 항목 단위 휴지통.
AC: 저장소 내부 파일에 `trash`/`move` 결정 시 `E_PROTECTED`. M2.
비고: “다른 코드에서 참조하는 파일” 판정(저장소 밖 파일이 코드에서 참조되는 경우)은 M6 에서 04 문서가 방법을 정한다.

**FR-SO-005 — AI 문맥 분류(선택).** AI 활성 시 `ai_policy` 가 허용하는 항목의 메타데이터로 작업 그룹·목적지를 제안한다. AI 비활성에서도 모든 기능 동작.
AC: `ai.enabled=false` 에서 네트워크 호출 0. `patient`/`secret` 항목은 페이로드에 없음(게이트 테스트). M6.

**FR-SO-006 — 스크린샷 OCR.** 스크린샷을 로컬 Vision OCR 로 분류·이름 변경 제안(`rename`). OCR 텍스트는 암호화 저장, 외부 전송 금지(로컬 모델만, 민감 판정 시 금지).
AC: OCR 결과에 주민등록번호 패턴 → 항목 `sensitivity=patient`. M6.

### 5.4 Visual Review (FR-VR) — 화면 세부는 03 문서

**FR-VR-001 — 메인 결산 화면.** 지표 카드, 그룹 목록(체크 선택), 선택 항목 확보 용량, [선택한 정리 계획 검토하기], 하단 고지 “명시적으로 승인된 항목만 정리합니다.”
AC: 모든 수치가 `review.summary` 응답과 일치. M4.

**FR-VR-002 — 갤러리 모드.** 이미지·스크린샷 그룹은 썸네일 갤러리로, 다중 드래그 선택·개별 판단·더블클릭 확대.
AC: 200장 그룹 스크롤 60fps 목표, 썸네일은 지연 생성. M4.

**FR-VR-003 — 리스트 모드.** 문서·일반 파일을 이름·용량·날짜·프로젝트로 정렬, Space 로 Quick Look.
AC: 파일 유형별 미리보기(CONTEXT 턴1 표: 이미지, PDF, Office, 동영상, ZIP 내부 목록, 소스코드, Markdown, DMG/PKG, 앱, 폴더)가 Quick Look 또는 메타데이터 패널로 제공. M4.

**FR-VR-004 — 비교 모드.** 중복·유사 스크린샷·문서 버전을 나란히 보고 남길 것을 선택.
AC: 중복 그룹에서 2~4개 나란히 표시, 선택한 것 외 `trash` 결정. M4.

**FR-VR-005 — 키보드.** `Space` 미리보기, `←/→` 이전·다음, `K` keep, `D` trash, `A` archive, `M` move, `S` defer, `⌘Z` 결정 취소.
AC: 마우스 없이 한 그룹 전체 판단 가능. 허용되지 않은 동작 키는 무시 + 이유 표시. M4.

**FR-VR-006 — 미리보기 정책 준수.** `metadata_only` 항목(보안 자산)은 내용 미리보기·썸네일 없음, 이름 마스킹. `ephemeral` 항목(환자 자료)은 명시적 Space 에만 미리보기, 썸네일 디스크 캐시 금지.
AC: 보안 자산 항목 열람 후 `~/Library/Caches/DayClose` 에 해당 파일 파생물 0. M4.

**FR-VR-007 — 계획 검토·승인 화면.** 연산 목록(동작·원본·목적지·용량), 보호 항목 제외 내역, [승인하고 실행]. 실행 결과와 [되돌리기].
AC: 승인 버튼은 표시 중인 `plan_hash` 로만 승인. M5(앱 화면은 M5 에 추가).

### 5.5 App Manager (FR-AM) — 읽기 전용

**FR-AM-001 — 앱 인벤토리.** `/Applications`, `~/Applications` 의 앱 신규 설치·삭제·버전 변경을 매일 감지. 출처(App Store/brew cask/수동) 추정.
AC: 가짜 앱 번들 추가/버전 변경 시 각각 `app` 항목 생성. M3.

**FR-AM-002 — Homebrew.** formula/cask 신규 설치·삭제 감지, 직접 설치 여부 구분.
AC: `brew` 없으면 `W_TOOL_MISSING` 후 계속. 테스트는 `brew` 출력 픽스처로. M3.

**FR-AM-003 — Git 프로젝트 상태.** `projects.roots` 아래 저장소의 미커밋 변경 수, 90일 이상 오래된 로컬 브랜치 수를 결산에 표시(`git_repo` 항목, `acknowledge` 만).
AC: 미커밋 파일 있는 샌드박스 저장소 → 항목 1개, dirty_count 정확. M2.

**FR-AM-004 — 로그인 항목(주간).** 새 LaunchAgent/LaunchDaemon/로그인 항목 감지.
AC: `~/Library/LaunchAgents` 에 새 plist → 항목 생성. 주 1회만 수집(설정). M3.

**FR-AM-005 — 개발 캐시(주간).** `node_modules`, `DerivedData`, `.build` 등 용량 큰 재생성 가능 산출물 표시(크기순).
AC: 비활성 저장소의 캐시만 `trash` 제안. M3.

**FR-AM-006 — 미사용 앱(월간).** 90일 이상 미사용 앱 표시. 삭제는 하지 않음(비목표 §7).
AC: `last_used_at` 90일 초과 앱이 월간 리포트에 표시. M3.

### 5.6 Secure Vault (FR-SV) — 세부는 05 문서

**FR-SV-001 — 확장자·이름 탐지.** CONTEXT 턴2 표의 모든 대상(인증서, 개인키, SSH, `.env*`, 클라우드 인증, Apple/Android 개발자, VPN, 지갑, DB 접속, 복구 코드, NPKI)을 `vault_asset_kind` 로 분류.
AC: 대상별 샌드박스 픽스처 각 1개 이상이 올바른 kind 로 탐지. M3.

**FR-SV-002 — 형식·내용 탐지.** 확장자에 의존하지 않고 매직바이트(PEM 헤더, PKCS#12 DER 구조, OpenSSH 키 헤더)와 로컬 패턴으로 확장자 없는 파일·TXT·JSON 속 인증 정보를 탐지. gitleaks 가 있으면 보조로 사용.
AC: 확장자 없는 OpenSSH 개인키, `notes.txt` 속 AWS 키 → 탐지. gitleaks 없을 때도 내부 패턴으로 탐지(경고만). M3.

**FR-SV-003 — 위치 보존.** 보안 자산은 원래 위치에 두고 논리 인벤토리만 만든다. 일괄 이동·일괄 휴지통 대상에서 제외. 사용 중인 키의 경로를 바꾸지 않는다.
AC: 보안 자산에 대한 `trash/move/archive` 결정 → `E_PROTECTED`. 그룹 결정에서 자동 제외. M3.

**FR-SV-004 — 마스킹.** 목록·리포트·로그에서 이름을 마스킹(`AuthKey_••••••.p8`)하고 내용은 절대 표시하지 않는다. 메타데이터(종류, 위치, 프로젝트, 만료일, 백업 상태) 중심.
AC: 비밀 픽스처 전체 스캔 후 stdout·로그·DB 어디에도 비밀 원문 없음(안전 회귀 테스트). M3.

**FR-SV-005 — 인증서 만료.** X.509 인증서의 만료일을 추출하고 `expiry_warn_days`(30일) 이내면 경고. 암호가 걸린 `.p12` 는 “만료일 미확인(암호 필요)”. 파일로 만료를 알 수 없는 API 키는 “만료일 미확인” + 사용자 입력(`vault annotate --expires`).
AC: 23일 남은 테스트 인증서 → `expiring_soon` 발견 사항, severity `high`. M3.

**FR-SV-006 — Security Health.** 발견 사항: 만료 임박/만료, Git 추적 중인 `.env`/키, 중복 개인키(같은 지문이 여러 경로), 백업 미확인, SSH 권한 이상, 노출 위치(Downloads/Desktop 의 키), 일반 파일 속 평문 비밀.
AC: 각 발견 사항 유형별 픽스처 시나리오 통과. M3.

**FR-SV-007 — Git 노출 키.** Git 에 추적된 키는 “파일 삭제가 아니라 폐기 및 재발급” 을 권고한다.
AC: `tracked_in_git` 발견 사항 문구에 폐기·재발급 권고 포함, 동작 제안은 `acknowledge` 만. M3.

**FR-SV-008 — 시드 구문 비수집.** 암호화폐 시드·복구 구문 의심 파일은 존재·위치만 경고하고 지문·내용 등 어떤 파생값도 저장하지 않는다.
AC: 시드 의심 픽스처 → `crypto_seed_suspected`, `fingerprint_sha256` NULL, 로그에 경로 없음. M3.

**FR-SV-009 — 암호화 백업(후속).** 보안 자산을 클라이언트 측 암호화 후에만 NAS 로 백업, 복구 가능성 검증. 평문 복사 금지.
AC: 05 문서가 확정. M8.

### 5.7 Safe Execution (FR-EX) — 세부는 08 문서

**FR-EX-001 — 계획.** 결정된 항목(trash/move/archive)으로 불변 `draft` 계획을 만들고 `plan_hash` 를 계산한다.
AC: 같은 입력 → 같은 해시. 계획 생성은 파일을 바꾸지 않음. M5.

**FR-EX-002 — 사람 승인.** 승인은 앱 버튼, TTY 확인 입력, 네이티브 확인 대화상자 중 하나로만 가능하다. 에이전트는 승인할 수 없다.
AC: 비 TTY·대화상자 거부 → `E_APPROVAL_DENIED`. 해시 불일치 → `E_APPROVAL_MISMATCH`. MCP 에 approve 도구 없음. M5.

**FR-EX-003 — 실행 전 재검증.** 연산 직전 파일 identity·크기·mtime 와 보호 정책을 다시 확인한다.
AC: 계획 후 파일을 수정하면 해당 연산 `skipped`, 항목 `stale`, 나머지는 계속. M5.

**FR-EX-004 — 휴지통.** “삭제” 는 볼륨별 휴지통으로 이동이다. DayClose 는 영구 삭제와 휴지통 비우기를 하지 않는다.
AC: 코드베이스에 executor 밖 파일 변경 호출 0(정적 검사). 휴지통 이동 후 undo 로 원위치. M5.

**FR-EX-005 — 이동·보관.** 같은 볼륨은 rename, 다른 볼륨은 복사→검증(크기+SHA-256)→원본 제거. 목적지 덮어쓰기 금지.
AC: 샌드박스 두 볼륨(디스크 이미지 또는 모의) 간 이동 후 해시 일치, 실패 주입 시 원본 보존. M5.

**FR-EX-006 — Undo 와 복구.** 계획 단위·연산 단위 되돌리기. 실행 중 크래시 후 `plan recover` 가 실제 파일 상태로 정합화.
AC: apply 도중 프로세스 강제 종료 → recover 후 모든 연산이 `done`/`pending`/`failed` 중 실제와 일치, 파일 유실 0. M5.

**FR-EX-007 — 실행 이력.** 모든 쓰기 명령은 감사 로그에, 모든 연산은 `plan_operations` 에 남는다.
AC: `audit list` 로 누가(channel) 무엇을 언제 했는지 확인 가능, 경로·비밀 없음. M5.

### 5.8 Policy & Memory (FR-PM) — 세부는 07 문서

**FR-PM-001 — 기본 보호.** 활성 git 저장소, 보안 자산, 환자 관련 자료, 시스템 경로는 기본 보호(02 §10.1).
AC: 보호 등급별 허용 동작 매트릭스 테스트. M2.

**FR-PM-002 — 환자 자료 판정.** `protection.patient_paths` 아래 파일, 파일명 패턴, 로컬 텍스트의 주민등록번호 패턴으로 `patient_data` 판정. 외부 모델·로그·썸네일 캐시 금지, 휴지통 금지, 그룹 결정 제외.
AC: 패턴 일치 파일 → `sensitivity=patient`, `allowed_actions` 에 `trash` 없음. M2.

**FR-PM-003 — 사용자 보호 규칙.** 경로·글롭·확장자·프로젝트 단위 보호 규칙 추가/삭제. 내장 규칙은 비활성화 불가.
AC: `rule add --kind path_prefix --pattern ~/약국 --protection patient_data` 후 해당 파일 보호. M2.

**FR-PM-004 — 결정 학습 제안.** 같은 조건에서 같은 결정을 반복하면 규칙 등록을 제안한다(1일차: 묻기 → 약 1주: “기본 규칙으로 등록할까요?” → 약 1개월: 습관 항목은 하나로 묶고 새 판단만 강조).
AC: 같은 조건의 `trash` 결정 5회(07 문서가 임계값 확정) → `policy_rules.state=suggested`. 수락 후 규칙 일치 항목은 제안이 자동 채워지되 **실행은 여전히 계획 승인 필요**. M6.

**FR-PM-005 — AI 전송 게이트.** AI 로 보내는 모든 페이로드는 게이트를 통과해야 하며, `ai_policy=none` 항목·비밀 패턴·환자 패턴을 제거한다. 요청은 메타데이터 감사 기록만 남긴다.
AC: 게이트 단위 테스트(비밀/환자 픽스처 포함 입력 → 페이로드에 없음). M6.

### 5.9 macOS 통합 (FR-MI) — 세부는 09 문서

**FR-MI-001 — 메뉴바.** 메뉴바 아이콘에 미결 항목 수, [지금 검토]. M7.
**FR-MI-002 — 예약 실행.** 매일 `review.daily_time`(기본 21:00) 및 로그인 시 스캔. 잠자기로 놓친 실행은 깨어난 뒤 1회. M7.
**FR-MI-003 — 일일 알림.** “오늘도 수고하셨습니다. 오늘 생성된 파일 N개와 수정된 파일 M개를 검토했습니다. 정리할 항목 K개가 있습니다. 예상 검토 시간: X분” + [지금 검토] [나중에]. M7.
**FR-MI-004 — 권한 안내.** FDA 미부여로 예약 실행이 루트에 접근 못 하면 알림·앱에서 설정 경로를 안내(시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한). 예약 실행은 절대 멈추지 않고 경고로 끝난다.
AC(공통): launchd 실행과 셸 실행 결과 비교 테스트 절차(09 문서) 통과. M7.

### 5.10 Archive & Backup (FR-AB)

**FR-AB-001 — 보관 대상.** 로컬/외장 경로(예 `/Volumes/External/DayCloseArchive`)를 보관 대상으로 등록하고 `archive` 결정의 목적지로 사용. M5.
**FR-AB-002 — NAS 보관.** Synology NAS(SMB 마운트) 대상, 연/월 구조 보관, 보관 후 검증. M8.
**FR-AB-003 — 암호화 보관.** `patient` 이상 민감도 항목은 클라이언트 측 암호화 대상에만 보관 가능. 복구 검증(왕복 복호화) 필수. M8.

### 5.11 Agent 연동 (FR-AG) — 세부는 10 문서

**FR-AG-001 — CLI 가 1급 인터페이스.** 앱이 하는 모든 일(승인 제외 수단은 §FR-EX-002)을 CLI 로 할 수 있다. M1~.
**FR-AG-002 — Skill.** Claude Code·Codex 공용 `skill/SKILL.md`: 결산 조회 → 요약 제시 → 결정 기록 → 계획 생성 → 사용자에게 승인 요청(대화상자) 흐름. M8.
**FR-AG-003 — MCP.** `dayclose mcp serve` 가 읽기·결정·계획 생성 도구를 노출. 승인·undo·보호 해제는 비노출. M8.

## 6. 비기능 요구사항

| ID | 요구사항 | 기준 |
|---|---|---|
| NFR-PERF-001 | 증분 스캔 | 기본 루트 합계 10만 엔트리, 변경 1% 일 때 웜 스캔 ≤ 10초 (M1 측정, M3 기준 충족) |
| NFR-PERF-002 | 앱 응답 | `serve --stdio` 에서 `review.summary`·`item.list`(200건) p95 ≤ 300ms |
| NFR-PERF-003 | 기동 | `dayclose version --json` ≤ 250ms (지연 import) |
| NFR-DISK-001 | 자체 용량 | DB ≤ 200MB(파일 50만), 로그 ≤ 25MB, 썸네일 캐시 ≤ 200MB |
| NFR-SAFE-001 | 무승인 변경 0 | 안전 회귀 스위트 100% 통과가 모든 머지 조건 |
| NFR-SAFE-002 | 크래시 안전 | 어느 시점의 강제 종료에도 파일 유실 0 |
| NFR-PRIV-001 | 비밀 누출 0 | 로그·DB·stdout·AI 페이로드·썸네일에 비밀/환자 원문 0 |
| NFR-PRIV-002 | 네트워크 | AI·NAS 기능 비활성 시 외부 네트워크 연결 0 |
| NFR-REL-001 | 멈춤 없음 | 예약 실행은 어떤 권한 상태에서도 제한 시간 내 종료 |
| NFR-A11Y-001 | 접근성 | 앱 전 기능 키보드 조작, VoiceOver 레이블 |
| NFR-L10N-001 | 언어 | 사용자 문구 한국어 기본 |

## 7. 비목표 (하지 않는 것)

- 시스템 전체 디스크 청소, 시스템 데이터 분석(Mole 등 기존 도구 영역 — 13 문서에서 연동 여부 검토).
- 앱 삭제(언인스톨), 패키지 제거 실행. App Manager 는 읽기 전용.
- 영구 삭제, 휴지통 비우기.
- 보안 자산의 일괄 이동·중앙 폴더 집결, 비밀값 자체의 보관(비밀번호 관리자 역할), 시드 구문 보관.
- 파일 내용 편집·변환.
- 브라우저 북마크·노트·사진 보관함 정리(CONTEXT 에서 요구되지 않음).
- 기기 간 DB 동기화. 각 기기는 독립 DB(통합 리포트는 M8 이후 검토).
- 클라우드 계정·서버 백엔드, 다중 사용자.
- MVP 의 실시간 감시(FSEvents 상주). 예약 스캔으로 충분 — M7 이후 필요 시.

## 8. MVP 범위

**첫 MVP (CONTEXT 턴2) = Daily Review + Visual Review + Secure Vault 읽기 전용 탐지** → M4 종료 시점.
- 포함: FR-CORE-*, FR-DR-*, FR-SO-001~004, FR-AM-001~006(읽기 전용), FR-SV-001~008, FR-PM-001~003, FR-VR-001~006, FR-AG-001.
- MVP 에서 파일은 **한 개도** 바뀌지 않는다. 결정은 기록되고 계획 대기로 남는다.
- 실행 엔진은 MVP 직후 M5(“이후 안전한 파일 이동과 복구 기능을 붙이는 순서”). 단 executor 전용 변경 규칙, 샌드박스 가드, 보호 정책은 M1~M2 부터 코드와 테스트로 존재(턴4).

이후: M5 실행(FR-EX, FR-AB-001, FR-VR-007) → M6 AI·학습(FR-SO-005/006, FR-PM-004/005) → M7 메뉴바·자동실행·알림(FR-MI) → M8 Skill·MCP·NAS(FR-AG-002/003, FR-AB-002/003, FR-SV-009).

## 9. 미결 사항 (소유자 확인 필요)

1. **환자 자료 위치·식별 기준**: 약국 PM 프로그램 내보내기 폴더, 처방전 스캔 위치 등 `protection.patient_paths` 에 넣을 경로. 기본값은 파일명 패턴(`*처방*`, `*조제*`, `*환자*`) + 주민등록번호 패턴뿐이다.
2. **`.p6` 의 실체**: `.p12`/`.pfx`/`.p8` 중 무엇을 뜻했는지, 혹은 다른 형식인지.
3. **Mac mini 운용**: Mac mini 에서도 일일 결산을 쓸지, 쓴다면 루트(서버 데이터·docker 볼륨은 제외 권장)와 알림 방식(무인 기기).
4. **NAS 연결**: Synology 접근 방식(SMB 마운트 경로, 상시 마운트 여부), 보관 폴더 구조, 암호화 백업 키(age 개인키)를 어디에 보관할지(예: 종이/오프라인 + Keychain).
5. **AI 사용**: 외부 AI(Claude API 등) 사용 의향과 키 보유 여부, 또는 로컬 ollama 모델만 쓸지. 기본값은 AI 꺼짐.
6. **`~/Documents`·iCloud Drive 범위**: Documents 를 스캔할지, iCloud Drive 를 포함할지(dataless 파일은 내용 미열람).
7. **일일 시각·날짜 경계**: 알림 21:00, 날짜 경계 04:00 이 맞는지.
8. **배포·서명**: Developer ID 서명·공증을 할지(FDA 권한 유지 안정성에 영향), 오픈소스 공개 여부와 라이선스(13 문서의 재사용 판단에 영향).
9. **보안 자산 백업 상태 판정**: “백업됨”을 무엇으로 볼지(NAS 암호화 사본 존재, Keychain 존재, 사용자가 표시) — 05 문서 초안은 사용자 표시 + M8 암호화 사본 검증.
