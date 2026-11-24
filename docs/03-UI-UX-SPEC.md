# 03 — UI/UX 명세 (DayClose.app)

> 상태: 구현 명세. 이름·명령·enum 은 `02-ARCHITECTURE.md`, `06-DATA-MODEL.md` 를 그대로 쓴다.
> 범위: DayClose.app 의 모든 화면·상호작용·상태. 메뉴바·알림은 *화면과 문구* 만 여기, *등록·권한·프로세스* 는 `09-MACOS-INTEGRATION.md`.
> 명령의 `data` 정확한 스키마는 `10-CLI-SKILL-MCP.md` 가 확정한다. 이 문서의 JSON 예시는 **UI 가 필요로 하는 최소 필드**이며, 10 과 다르면 10 이 맞고 이 문서를 고친다(§13 에 10 에 대한 요구를 모았다).

## 0. 원칙과 마일스톤

| 원칙 | UI 에서의 의미 |
|---|---|
| 파일은 앱이 바꾸지 않는다 | 앱의 모든 버튼·키는 core 명령(§5 of 02)으로만 동작. 결정(K/D/A/M/S)은 기록일 뿐이고 파일 변경은 계획 승인 후 `plan.apply` 뿐. 화면 문구로도 이를 반복해서 알린다(하단 고지). |
| `allowed_actions` 가 유일한 기준 | 버튼 활성/키 동작은 항목 JSON 의 `allowed_actions` 로만 결정. 앱이 보호 등급으로 동작을 추론하지 않는다(문구 선택에만 `protection` 사용). |
| `preview_policy` 준수 | `metadata_only` 는 내용·썸네일 없음, `ephemeral` 은 명시적 Space 에서만 미리보기·디스크 캐시 없음(§6). |
| 상태는 core 에 | 앱은 화면 상태(선택·포커스·모드)만 가진다. 결정·이월·보류는 전부 core 상태이며 앱을 껐다 켜도 같다. |
| 30초~1분 | 메인 화면에서 그룹 단위로 끝낼 수 있어야 하고, 개별 판단은 키보드만으로 가능해야 한다. |

| 마일스톤 | 화면 |
|---|---|
| M4 (첫 MVP) | 메인 결산, 그룹 상세(갤러리/리스트/비교), 인스펙터·Quick Look, 결정 입력, 실행 대기 목록(실행 버튼 비활성), Secure Vault, Security Health, 앱·패키지·프로젝트, 결정 기록, 설정, 온보딩(FDA 포함), core 오류 화면 |
| M5 | 계획 검토·승인 시트, 실행 진행, 완료 리포트, 실행 기록·되돌리기, 보관 설정 |
| M6 | 학습 규칙 제안 카드, AI 설정, 습관 항목 묶음 그룹 |
| M7 | 메뉴바, 일일 알림, 알림·예약 설정 |

## 1. 앱 구조

### 1.1 Scene

| Scene | SwiftUI | 내용 |
|---|---|---|
| 메인 창 | `WindowGroup(id: "main")` — 결정: 단일 창(`.handlesExternalEvents` 로 중복 창 방지). 이유: 리뷰 상태가 하나이고 두 창에서 같은 항목을 동시에 결정하는 경우를 없앰. | `RootSplitView` |
| 설정 | `Settings` | `SettingsView` (⌘,) |
| 온보딩 | 메인 창 안의 전체 화면 교체(별도 창 아님) | `OnboardingFlow` |
| 메뉴바 (M7) | `MenuBarExtra(isInserted:)` + `.menuBarExtraStyle(.window)` | `MenuBarContentView` |

최소 창 크기 960×600, 기본 1200×780. 창 위치·사이드바 폭·인스펙터 표시 여부는 `@SceneStorage`.

### 1.2 내비게이션 (`RootSplitView` = `NavigationSplitView`)

```
┌──────────────────┬──────────────────────────────────────────────────────────────┐
│ 사이드바 (220pt)  │ 콘텐츠                                                        │
│                  │                                                              │
│ 결산              │                                                              │
│  ◉ 오늘의 결산 12 │  (선택된 사이드바 항목의 화면)                                  │
│  ◷ 보류 중     2  │                                                              │
│  ⇢ 실행 대기   6  │                                                              │
│ 보안              │                                                              │
│  ⚿ Secure Vault  │                                                              │
│  ♡ Security Health 3                                                            │
│ 인벤토리          │                                                              │
│  ▦ 앱·패키지   2  │                                                              │
│  ⎇ 프로젝트       │                                                              │
│ 기록              │                                                              │
│  ↺ 기록           │                                                              │
│ ──────────────── │                                                              │
│ 마지막 스캔 21:03 │                                                              │
│ ⚠ 권한 확인 필요  │                                                              │
└──────────────────┴──────────────────────────────────────────────────────────────┘
```

| 사이드바 항목 | `SidebarItem` | 화면 | 배지 숫자 출처 |
|---|---|---|---|
| 오늘의 결산 | `.review` | `DailyReviewView` → 그룹 선택 시 `GroupDetailView` (같은 열에서 push) | `review.summary` `stats.items_open` |
| 보류 중 | `.deferred` | `DeferredItemsView` | `stats.deferred` |
| 실행 대기 | `.pending` | `PendingExecutionView` | `review.summary` `pending_plan.item_count` (§13 R1) |
| Secure Vault | `.vault` | `VaultInventoryView` | 검토 필요 자산 수(§4.9) |
| Security Health | `.health` | `SecurityHealthView` | `stats.vault_findings_open` |
| 앱·패키지 | `.inventory` | `InventoryView` | `stats.new_apps + stats.new_packages` |
| 프로젝트 | `.projects` | `ProjectsView` | 없음 |
| 기록 | `.history` | `HistoryView` | 없음 |

사이드바 하단 상태줄: 마지막 스캔 시각(`review.summary.last_scan.finished_at`, 상대시각), 스캔 진행 중이면 진행 막대, 권한 문제가 있으면 `⚠ 권한 확인 필요`(클릭 → 설정 > 권한).

### 1.3 툴바(메인 창 공통)

| 위치 | 요소 | 동작 |
|---|---|---|
| 좌 | 리뷰 날짜 `2026년 11월 24일 (화)` · 기기 이름(`config.device_name`, 기본 = 컴퓨터 이름. 두 기기가 독립 설치이므로 어느 Mac 의 결산인지 항상 보이게 — 02 §8.1) | 클릭 시 날짜 메뉴: 오늘 / 최근 7일(과거 세션 열람 = `review.summary --review-date D`, 읽기 위주) |
| 우 | `⟳ 스캔` (⌘R) | `scan.run --trigger app` (진행 이벤트 표시, §3.6) |
| 우 | 보기 모드 세그먼트(그룹 상세에서만) | 갤러리 ⌘1 / 리스트 ⌘2 / 비교 ⌘3 |
| 우 | 인스펙터 토글 (⌥⌘I) | 오른쪽 인스펙터 표시/숨김 |
| 우 | 검색 (⌘F) | 현재 목록의 `display_name` 클라이언트 필터 |

결정: 과거 날짜 열람 시 `review.summary --review-date D` 를 호출한다(이 명령은 W 이며 그 날짜 세션이 없으면 만든다 — 과거 날짜에 대해 세션을 새로 만들지 않도록 10 확인 필요, §13 R2). M4 에서는 “오늘”과 이미 존재하는 세션 날짜만 메뉴에 표시한다.

## 2. 공통 표시 규칙

### 2.1 enum → 화면 문구 (한국어, `Localizable.xcstrings` 기본 언어 ko)

`decision_action`:

| 값 | 버튼/배지 문구 | 키 | SF Symbol | 배지 색(보조 수단, 색만으로 구분 금지) |
|---|---|---|---|---|
| `keep` | 유지 | K | `checkmark.circle` | 녹색 |
| `keep_always` | 항상 유지 | ⇧K | `checkmark.seal` | 녹색 |
| `trash` | 휴지통 | D | `trash` | 빨강 |
| `move` | 이동 | M | `folder` | 파랑 |
| `archive` | 보관 | A | `archivebox` | 보라 |
| `defer` | 보류 | S | `clock` | 회색 |
| `acknowledge` | 확인 | K(대체, §5.2) | `eye` | 회색 |

`item_category`: screenshot 스크린샷 · image 이미지 · document 문서 · installer 설치 파일 · compressed 압축 파일 · media 동영상·오디오 · code 소스 코드 · folder 폴더 · misc 기타 · dev_cache 개발 캐시 · security_asset 보안 자산 · app 앱 · package 패키지 · git_repo Git 프로젝트 · login_item 로그인 항목.

`protection` (잠금 배지 툴팁): none (표시 없음) · user_rule “보호 규칙” · system “시스템 항목” · active_repo “활성 Git 저장소” · patient_data “환자 관련 자료” · security_asset “보안 자산”.

`suggestion.source`: none 제안 없음 · heuristic “규칙 기반 추천” · rule “내 규칙” · ai “AI 추천”. `confidence` 는 숫자를 보이지 않고 ≥0.8 높음 / ≥0.5 보통 / 그 외 낮음 으로 표시(VoiceOver 동일).

`item_state` 는 사용자에게 직접 보이지 않는다. 항목 카드는 “결정 배지” 만 보인다: 결정 없음 / `decided_action` 배지 / `planned` → “실행 대기” / `executed` → “완료” / `failed` → “실패(재시도 가능)” / `stale` → “파일이 바뀜”.

`vault_asset_kind` 문구는 §4.9 표.

### 2.2 값 형식

- 용량: `ByteCountFormatter(countStyle: .file)` → `482 KB`, `1.2 GB`.
- 날짜: 오늘이면 `오후 2:02`, 어제 `어제 오후 2:02`, 그 외 `11월 20일`. 툴팁에 전체 시각.
- 경로: 항상 `display_path`(홈 축약) 만 표시. `path` 는 화면 문구·복사·로그에 쓰지 않고 Quick Look/썸네일/Finder 열기의 입력으로만 쓴다.
- 보안 자산(`protection = security_asset`): `display_name` 은 core 가 준 마스킹 이름 그대로(`AuthKey_••••••.p8`). VoiceOver 는 “마스킹된 이름, Apple 서명 키” 처럼 종류로 읽는다. 이름 복사(⌘C)는 마스킹 이름만 복사.
- 이월: `carry_count ≥ 1` 이면 `“\(carry_count + 1)일째”` 배지(`carry_count=1` → “2일째”). 3일째 이상은 강조색.

### 2.3 하단 고지 (항상 표시되는 고정 문구)

| 화면 | 문구 |
|---|---|
| 메인·그룹 상세·실행 대기 | “명시적으로 승인된 항목만 정리합니다. 결정만으로는 파일이 바뀌지 않습니다.” |
| Secure Vault·Security Health | “개인키 원문은 AI에 전송하지 않습니다.” / “보안 자산은 일반 일괄 삭제 대상에서 제외됩니다.” |
| 앱·패키지 | “DayClose 는 앱·패키지를 삭제하지 않습니다.” |

## 3. 상태 모델

### 3.1 저장소(Observable 모델) 구성

모두 `@MainActor @Observable final class`. core 호출은 `DayCloseKit.CoreClient`(actor, 09 문서 §4) 를 통해서만.

| 모델 | 책임 | 주 명령 |
|---|---|---|
| `AppModel` | 앱 단계(`AppPhase`), core 연결 상태, 권한 상태 요약, 사이드바 배지 | `core.version`, `core.doctor` |
| `ReviewStore` | 오늘 세션, 그룹, 항목 페이지 캐시, 결정 낙관적 갱신, undo 스택 | `review.summary`, `item.list`, `decision.set`, `decision.undo` |
| `GroupDetailStore` | 그룹 하나의 항목 목록·선택·포커스·보기 모드·정렬 | `group.show`, `item.list --group` |
| `PlanStore` (M5) | 계획 생성·승인·실행·결과 | `plan.*` |
| `VaultStore` | 자산 목록·상세·주석 | `vault.list/show/annotate`, `item.list --category security_asset --open` |
| `HealthStore` | 발견 사항 | `vault.health` |
| `InventoryStore` | 앱·패키지·프로젝트 | `app.list`, `package.list`, `project.list` |
| `HistoryStore` | 결정·실행·감사 기록 | `decision.list`, `plan.list/show/undo`, `audit.list` |
| `SettingsStore` | 설정·루트·규칙·suppression | `config.*`, `root.*`, `rule.*`, `suppression.*` |
| `PermissionMonitor` | FDA·폴더 접근 상태(09 §7) | `core.doctor` + 앱 자체 프로브 |

### 3.2 앱 단계 `AppPhase`

```
launching ──core 탐색 실패──▶ coreMissing
    │      ──contract 불일치─▶ coreIncompatible
    │      ──E_NOT_INITIALIZED─▶ onboarding ──완료──▶ ready
    │      ──E_DB_MIGRATION/E_DB_CORRUPT──▶ fatal(code)
    └──ok──▶ ready ──core 프로세스 반복 비정상 종료(09 §4.5)──▶ coreCrashed ──[다시 시도]──▶ launching
```

| 단계 | 화면 |
|---|---|
| `launching` | 창 중앙 로고 + “DayClose 를 준비하는 중…” (500ms 이후에만 스피너, 깜빡임 방지) |
| `coreMissing` | `CoreUnavailableView(.missing)` §4.15 |
| `coreIncompatible` | `CoreUnavailableView(.incompatible(core: Int, app: Int))` |
| `onboarding` | `OnboardingFlow` §4.14 |
| `fatal` | `FatalErrorView(code)` §4.15 |
| `ready` | `RootSplitView` |

### 3.3 리뷰 화면 상태 `ReviewStore`

```swift
enum LoadState<T> { case idle, loading(previous: T?), loaded(T), failed(UIError, previous: T?) }

struct ReviewScreenState {
  var summary: LoadState<ReviewSummary>          // review.summary
  var itemPages: [GroupID: ItemPage]             // item.list --group, cursor 페이지
  var pending: [RequestID: PendingMutation]      // 응답 대기 중인 낙관적 결정
  var undoStack: [DecisionBatch]                 // ⌘Z (최대 50, 세션 날짜가 바뀌면 비움)
  var redoStack: [DecisionBatch]                 // ⇧⌘Z
  var scan: ScanState                            // idle | running(phase, done, total?) | finished(warnings)
  var banners: [Banner]                          // 권한·볼륨·잠금·날짜 변경
  var reviewDate: String                         // core 가 돌려준 review_date (앱이 계산하지 않음)
}
```

항목 표시 상태(`ItemDisplayState`, 화면 전용 파생값):

| 조건 | 표시 상태 | 카드 표현 |
|---|---|---|
| `pending` 에 이 항목의 요청이 있음 | `.saving(action)` | 결정 배지 + 작은 진행 표시. 키 입력은 계속 받음(같은 항목에 새 입력이 오면 큐잉, §3.4) |
| `decision == nil` 이고 `deferred_until` 없음/지남 | `.undecided` | 제안 칩만 |
| `deferred_until > reviewDate` | `.deferred(until)` | “11월 27일까지 보류” |
| `state == decided` | `.decided(action, dest)` | 결정 배지 |
| `state == planned` | `.planned` | “실행 대기” 배지, 결정 키 비활성(`decision.undo` 불가, 06 §4.1) |
| `state == executed/undone/failed/stale` | 해당 | §2.1 |
| 응답이 `E_NOT_FOUND`/`E_STALE` | `.gone` | 흐리게 + “파일이 사라졌거나 바뀌었습니다”, 다음 새로고침에서 목록에서 빠짐 |

### 3.4 결정 입력 프로토콜 (낙관적 갱신)

K/D/A/M/S·버튼·그룹 체크박스는 모두 이 절차를 따른다.

1. **대상 계산**: 선택 집합(없으면 포커스 항목). 각 항목에 대해 요청 동작이 `allowed_actions` 에 있는지 검사 → `eligible` / `blocked` 로 분할.
2. `eligible` 이 비면: 아무 요청도 보내지 않고 차단 안내(§5.3) 표시. 끝.
3. `DecisionBatch(items: [(item_id, before: ItemSnapshot)], action, dest?, deferUntil?)` 를 만들고 화면을 즉시 갱신(`.saving`), undo 스택에 push, redo 스택 비움.
4. 요청: `decision.set {"item_ids": eligible, "action": A, "dest"?: P, "defer_until"?: D}` (channel `app`).
5. 응답 처리:

| 응답 | 처리 |
|---|---|
| `ok` | 응답 `data.items` 로 각 항목 교체(서버 값이 진실). `warnings` 의 `W_PROTECTED_SKIPPED` → 건너뛴 항목은 `before` 로 되돌리고 안내. 지표는 `review.summary` 재조회(디바운스 400ms) |
| `E_PROTECTED` | 배치 전체 롤백, undo 스택에서 제거, §5.3 문구 + “보호 상태가 바뀌었을 수 있습니다” → 해당 항목 `item.show` 재조회 |
| `E_INVALID_STATE` | 롤백 + 해당 항목 재조회(다른 채널—Skill/CLI—에서 이미 바뀜). 토스트 “다른 곳에서 이미 처리된 항목입니다” |
| `E_NOT_FOUND`, `E_STALE` | 해당 항목 `.gone` |
| `E_PATH_OUTSIDE_ROOTS` (move) | 롤백 + 목적지 선택기 다시 열고 “이 위치로는 이동할 수 없습니다” |
| `E_LOCKED` (retryable) | 200ms, 600ms, 1.5s 후 같은 요청 재시도(같은 `item_ids`·동작이므로 중복 적용돼도 결과 동일). 3회 실패 → 롤백 + 배너 “예약 스캔 등 다른 작업이 진행 중입니다. 잠시 후 다시 시도하세요.” |
| CoreClient 시간 초과/프로세스 종료 | 롤백하지 않고 `item.list` 로 해당 항목 재조회해 실제 상태로 맞춤(결정이 반영됐을 수 있으므로 재전송 금지) |

6. 같은 항목에 대한 요청은 직렬화: 앞선 요청 응답 전에 새 키가 오면 화면은 즉시 바꾸되 요청은 앞선 응답 후 보낸다(마지막 입력만 남기고 중간 입력은 합침).

### 3.5 ⌘Z / ⇧⌘Z

- ⌘Z: undo 스택 최상단 배치를 되돌린다. 항목별로 `before` 상태에 따라:
  - `before.decision == nil` → `decision.undo {"item_ids": [...]}`.
  - `before.decision == X`(다른 결정을 덮어쓴 경우) → `decision.set` 으로 X 를 다시 기록.
  - `before.deferred_until` 이 있었으면 `defer` 로 다시 기록.
  - 현재 `state == planned` 인 항목은 되돌릴 수 없다 → 건너뛰고 “실행 대기 중인 항목은 계획을 취소해야 되돌릴 수 있습니다”(M5: [계획 열기]).
- ⇧⌘Z: redo 스택 배치를 다시 적용(§3.4 절차).
- 스택은 메모리에만. 앱 재시작·리뷰 날짜 변경 시 비운다. 그 이후 취소는 기록 화면(§4.12)의 [취소] 로(`decision.undo`).
- 완료 리포트 화면(M5)에서 ⌘Z 는 “계획 되돌리기” 확인 대화상자를 연다(즉시 실행하지 않음, §4.7).
- 메뉴 막대 `편집 > 실행 취소 “휴지통 지정 3개”` 처럼 배치 설명을 표시(`UndoManager` 와 연결해 시스템 메뉴와 일치).

### 3.6 새로고침 트리거

| 트리거 | 동작 |
|---|---|
| 앱 활성화(`scenePhase == .active`) 후 마지막 조회 5분 경과 | `review.summary` |
| 예약 스캔 완료 분산 알림(09 §8.3) | 배너 “새 스캔 결과가 있습니다” + 자동 `review.summary` (편집 중 포커스·선택은 유지) |
| ⌘R 스캔 | `scan.run --trigger app --progress ndjson` → 진행 이벤트(`phase`: fs/git/vault/apps/brew/login_items/review)를 사이드바 하단·툴바에 “파일 확인 중… 5,120개” 로 표시 → 완료 후 `review.summary` |
| 리뷰 날짜 경계(`review.day_boundary`, 기본 04:00) 통과 | 배너 “새 결산일(11월 25일)이 시작되었습니다” [새 결산 열기] → `review.summary`(날짜 인자 없이; 날짜는 core 가 계산). 자동 전환하지 않음(작업 중 화면이 바뀌지 않도록) |
| 결정 응답 | 지표만 디바운스 재조회 |

스캔 중에도 결정 입력은 가능하다. 단 `scan.run` 이 쓰기 잠금을 잡는 동안 `decision.set` 은 대기(core `--wait-lock` 기본 10초) → 툴바에 “스캔 중 — 결정은 스캔 후 저장됩니다” 표시.

## 4. 화면 명세

### 4.1 일일 결산 메인 — `DailyReviewView`

데이터: `review.summary` (인자 없음 = 오늘). UI 필요 필드(10 이 확정):

```json
{
  "review_date": "2026-11-24", "session_id": "ses_15", "closed_at": null,
  "stats": {"new_files": 42, "modified_files": 18, "deleted_files": 3, "new_apps": 2, "new_packages": 1,
            "items_total": 15, "items_open": 12, "items_decided": 3, "carried_over": 4, "deferred": 2,
            "pending_plan_bytes": 1288490188, "trash_planned": 6, "suppressed_today": 9,
            "vault_new": 1, "vault_findings_open": 3},
  "estimated_review_minutes": 1,
  "groups": [
    {"id": "grp_12", "group_key": "installer:installed", "category": "installer",
     "title": "설치가 끝난 설치 파일", "rationale": "같은 이름의 앱이 /Applications 에 있습니다.",
     "suggested_action": "trash", "suggested_dest": null, "suggestion_source": "heuristic",
     "item_count": 2, "open_count": 2, "decided_count": 0, "bytes": 1203982336,
     "protected_count": 0, "carried_count": 0, "uniform_suggestion": true, "sort_order": 1}
  ],
  "pending_plan": {"item_count": 6, "bytes": 1288490188},
  "last_scan": {"run_id": "run_12", "finished_at": "2026-11-24T12:03:11.402Z", "status": "completed",
                "warning_codes": ["W_ROOT_UNAVAILABLE"]}
}
```

레이아웃:

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ 2026년 11월 24일 (화) · MacBook Pro                                 [⟳ 스캔]     │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                            │
│ │검토 대상   │ │검토 완료   │ │휴지통 예정 │ │예상 검토    │                            │
│ │   15      │ │  3 / 15   │ │  6 · 1.2GB│ │   1분      │                            │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘                            │
│ 새 파일 42 · 수정 18 · 삭제 3 · 새 앱 2 · 새 패키지 1 · 이월 4 · 보류 2 · 조용히 유지 9 │
│                                                                                │
│ 오늘의 정리 제안                                                                 │
│ 설치가 끝난 설치 파일 2개(1.2GB)를 정리할 수 있습니다. 스크린샷 6개는 PL-Agent 로      │
│ 옮길 수 있습니다.                                                                │
│ ┌ ⚠ 외장 볼륨(/Volumes/External)이 응답하지 않아 건너뛰었습니다. [자세히]  ✕ ┐       │
│                                                                                │
│ 정리 그룹                                                         [모두 펼치기]   │
│ [☐] ⬇ 설치가 끝난 설치 파일      2개 · 1.2 GB   제안: 휴지통            ›         │
│ [▣] ◩ 오늘의 스크린샷             8개 · 4.1 MB   제안: 이동 → PL-Agent  이월 2 ›   │
│ [☐] ⧉ 중복 파일                   3개 · 88 MB    제안: 1개 유지, 2개 휴지통     ›   │
│ [—] ⚿ 새 보안 자산                1개            확인 필요         🔒 보호 1  ›   │
│ [☐] ⎇ PL-Agent 미커밋 변경        1개            확인                       ›   │
│ [—] ▤ 그 외 다운로드              5개 · 12 MB    제안 없음                  ›   │
│                                                                                │
│ 실행 대기: 6개 · 1.2 GB                       [선택한 정리 계획 검토하기]          │
│ ─────────────────────────────────────────────────────────────────────────────  │
│ 명시적으로 승인된 항목만 정리합니다. 결정만으로는 파일이 바뀌지 않습니다.              │
└────────────────────────────────────────────────────────────────────────────────┘
```

구성 요소:

| 뷰 | 내용 | 규칙 |
|---|---|---|
| `SummaryMetricsBar` | 주 카드 4개: 검토 대상 `items_total`, 검토 완료 `items_decided / items_total`, 휴지통 예정 `trash_planned` · `pending_plan_bytes`, 예상 검토 시간 `estimated_review_minutes` | 값이 없으면(구버전 core) 예상 시간은 PRD FR-DR-001 공식으로 앱이 계산: ⌈(그룹 수×5 + 그룹 없는 항목 수×3)/60⌉. 카드 클릭: 검토 대상 → 첫 미결 그룹, 휴지통 예정 → 실행 대기 |
| 보조 지표 줄 | `new_files`, `modified_files`, `deleted_files`, `new_apps`, `new_packages`, `carried_over`, `deferred`, `suppressed_today` | 0 인 값은 숨김. “이월” 클릭 → 이월 항목 필터, “보류” → 보류 중 화면, “조용히 유지” → 설정 > 다시 묻지 않는 항목 |
| 보안 카드 | `vault_new > 0` 또는 `vault_findings_open > 0` 일 때만 지표 줄 아래 “새 보안 자산 1 · 점검 필요 3 ›” | 클릭 → Secure Vault / Security Health |
| `TodaySuggestionText` | 결정: 앱이 결정론적 템플릿으로 조합(AI 없음). 제안이 있는 그룹을 `sort_order` 순으로 최대 2개: “{title} {open_count}개({bytes})를 {action 문구}할 수 있습니다.” | 제안 있는 그룹이 없으면 숨김. 보안 자산 그룹은 문구에 넣지 않음 |
| `BannerStack` | §7 배너 | 최대 3개, 닫기 가능(같은 원인은 그날 다시 안 띄움) |
| `GroupListView` / `GroupRowView` | §4.1.1 | `sort_order` 순. 열린 항목이 0 인 그룹은 하단 “완료된 그룹” 접힘 영역으로 |
| `PendingPlanFooter` | `pending_plan.item_count > 0` 일 때 “실행 대기: N개 · X” + [선택한 정리 계획 검토하기] | M4: 실행 대기 목록 시트(§4.6, 실행 비활성). M5: `plan.create` |

#### 4.1.1 그룹 행 `GroupRowView`

| 요소 | 내용 |
|---|---|
| 체크박스(3상태) | “이 그룹의 제안을 수락”. ☐ = 미수락, ▣ = 결정 가능한 모든 항목이 제안대로 결정됨, — (indeterminate) = 일부. `suggested_action == nil` 이고 `uniform_suggestion == false` 인데 항목별 제안도 없으면 비활성(툴팁 “제안이 없습니다. 열어서 직접 판단하세요”) |
| 아이콘·제목 | 카테고리 아이콘, `title` |
| 개수·용량 | `open_count`개 · `bytes` (보안 자산 그룹은 용량 숨김) |
| 제안 칩 | `suggested_action` 문구(+ move 면 목적지 폴더 이름). 중복 그룹처럼 항목별 제안이 섞이면(`uniform_suggestion=false`) “1개 유지, 2개 휴지통” 처럼 요약(요약은 `item.list --group` 첫 페이지에서 계산) |
| 배지 | `carried_count > 0` → “이월 N”, `protected_count > 0` → 🔒 “보호 N” |
| › | 그룹 상세로 이동 |

체크박스 동작(결정: 체크 = 즉시 결정 기록. 이유: 숨은 클라이언트 상태가 없어 앱을 꺼도 유지되고, 이월·Skill 과 상태가 일치):

| 동작 | 요청 |
|---|---|
| ☐ → ▣, `uniform_suggestion=true` | `decision.set {"group_id": G, "action": suggested_action, "dest"?: suggested_dest}` (scope=group). core 가 보호 항목을 건너뛰고 `W_PROTECTED_SKIPPED` → 행에 “보호 항목 1개는 제외했습니다” |
| ☐ → ▣, `uniform_suggestion=false` | 항목별 `suggestion.action` 이 같은 것끼리 묶어 `decision.set {"item_ids": [...], "action": ...}` 여러 번(§3.4, 하나의 undo 배치) |
| ▣/— → ☐ | 이 그룹에서 제안과 같은 결정을 가진 항목들에 `decision.undo {"item_ids": [...]}` (개별로 다르게 결정한 항목은 건드리지 않음) |
| move 제안인데 `suggested_dest == nil` | 체크 시 목적지 선택기(§4.4) 먼저 |

#### 4.1.2 메인 화면 키보드

| 키 | 동작 |
|---|---|
| ↑ / ↓ | 그룹 포커스 이동 |
| → 또는 Return | 그룹 상세 열기 |
| Space | 그룹의 미리보기 가능한 항목(`preview_policy == full`, dataless 아님)을 Quick Look 패널에 묶어 열기. ←/→ 로 넘김. 가능한 항목이 없으면 안내 “이 그룹은 미리보기를 제공하지 않습니다” |
| X | 체크박스 토글(결정: Space 는 전 화면에서 미리보기로 통일하므로 체크는 X) |
| K/D/A/M/S, ⇧K | 그룹 전체에 해당 동작(`decision.set --group`). 그룹 결정 규칙은 core 가 적용(보호 항목 제외). 허용 항목이 하나도 없으면 §5.3 안내 |
| ⌘Z / ⇧⌘Z | §3.5 |
| ⌘⏎ | [선택한 정리 계획 검토하기] |

#### 4.1.3 상태

| 상태 | 표시 |
|---|---|
| 첫 로딩 | 지표 카드·그룹 행 스켈레톤(회색 막대). 300ms 이내 응답이면 스켈레톤 생략 |
| 재로딩 | 기존 내용 유지 + 툴바 작은 스피너 |
| 오늘 항목 0, 스캔 기록 있음 | “오늘은 정리할 것이 없습니다. 깨끗한 Mac 입니다.” + 보조 지표 줄(새 파일 수 등) + [지금 다시 스캔] |
| 스캔 기록 없음 | “아직 스캔하지 않았습니다.” [첫 스캔 시작] |
| 스캔 루트 0개 | “확인할 폴더가 없습니다.” [폴더 추가…] → 설정 > 스캔 위치 |
| 모든 항목 결정됨 | 그룹 영역 대신 “오늘의 결정을 모두 마쳤습니다.” + 실행 대기 요약 + (M5) [계획 검토] |
| 오류 | §7 오류 표. 이전 데이터가 있으면 유지하고 배너로 |

### 4.2 그룹 상세 — `GroupDetailView`

데이터: `group.show {"group_id": G}`(머리글) + `item.list {"group_id": G, "limit": 200, "cursor": C}`(페이지). 스크롤이 마지막 40개에 닿으면 다음 페이지. 항목 JSON 은 02 §5.6.

```
┌─ ‹ 오늘의 결산 ─────────────────────────────────────────── [갤러리|리스트|비교] ⓘ ┐
│ 오늘의 스크린샷 · 8개 · 4.1 MB                                                    │
│ 제안: 이동 → ~/dev/PL-Agent/screenshots (규칙 기반 추천 · 보통)                     │
│ 이유: PL-Agent 작업 시간대에 생성된 스크린샷                                         │
│ [제안 수락 (6개)] [모두 유지] [모두 보류]      필터: (전체|미결|이월|결정됨)  정렬 ▾  │
├──────────────────────────────────────────────────────────┬───────────────────────┤
│  (콘텐츠: 갤러리 / 리스트 / 비교)                           │ 인스펙터 §4.3          │
│                                                          │                       │
├──────────────────────────────────────────────────────────┴───────────────────────┤
│ 선택 2개 · 960 KB   K 유지  D 휴지통  A 보관  M 이동  S 보류  ⇧K 항상 유지   ⌘Z 취소 │
└────────────────────────────────────────────────────────────────────────────────┘
```

- 머리글 버튼은 그룹 결정(`decision.set --group`). [제안 수락] 은 §4.1.1 체크박스와 같다.
- 필터: 전체 / 미결(`decision == nil`) / 이월(`carry_count ≥ 1`) / 결정됨. 클라이언트 필터(이미 받은 페이지 기준, 미결 필터 시 남은 페이지를 끝까지 받음).
- 정렬(리스트·갤러리 공통): 이름, 용량, 수정일(기본: 갤러리는 수정일 오름차순, 리스트는 이름), 프로젝트.
- 하단 `DecisionBar`: 선택 개수·합계 용량, 동작 버튼(키 힌트 포함). 선택 항목 중 하나라도 허용하지 않는 동작 버튼은 “일부 적용” 표시(예 `D 휴지통 (3/4)`), 전부 불허면 비활성 + 툴팁(§5.3 문구).
- 기본 보기 모드(결정): `category ∈ {screenshot, image}` → 갤러리, `group_key` 가 `duplicate:` 로 시작 → 비교, 그 외 → 리스트. 사용자가 바꾼 모드는 `group_key` 접두사(`screenshot:` 등)별로 `UserDefaults` 에 기억.

#### 4.2.1 갤러리 모드 — `GalleryGridView`

- `LazyVGrid(columns: [GridItem(.adaptive(minimum: thumbSize))])`, `thumbSize` 기본 160pt, ⌘+ / ⌘− 로 120~320pt.
- 셀 `ThumbnailCell`: 썸네일(§6 규칙), 이름(가운데 말줄임), 용량, 결정 배지(아이콘+문구), “N일째”, 🔒(보호), ☁︎(dataless).
- 선택: 클릭 = 단일, ⌘클릭 = 토글, ⇧클릭 = 범위, 빈 곳에서 드래그 = 사각 선택(셀 프레임을 `PreferenceKey` 로 모아 교차 판정), ⌘A = 전체.
- 더블클릭 = Quick Look 패널(원본 크기 확대). Space 와 같다.
- 키: ←/→ 이전·다음, ↑/↓ 위·아래 행, Home/End 처음·끝. 결정 키는 §5.
- 결정 후 자동 진행(설정 “결정 후 다음 항목으로”, 기본 켬): 단일 포커스 결정 시 다음 미결 항목으로 포커스 이동. 다중 선택 결정 시 이동하지 않음.
- 그룹의 마지막 미결 항목을 결정하면 토스트 “이 그룹을 모두 검토했습니다” [다음 그룹 ⌘]] .

#### 4.2.2 리스트 모드 — `ItemListTableView`

`Table(selection:sortOrder:)` 열:

| 열 | 값 | 정렬 |
|---|---|---|
| (아이콘) | 파일 아이콘(§6) | — |
| 이름 | `display_name` + 배지(N일째, 🔒, ☁︎) | ○ |
| 종류 | 카테고리 문구 | ○ |
| 크기 | `size_bytes` | ○ |
| 수정일 | `mtime` | ○ |
| 위치 | `display_path` | ○ |
| 프로젝트 | `project.name` | ○ |
| 제안 | 제안 칩 | — |
| 결정 | 결정 배지 | ○ |

- Space = Quick Look(선택 항목들을 패널 목록으로), ↑/↓ 이동(←/→ 도 이전·다음으로 동작 — CONTEXT 단축키 일치), 결정 키는 §5.
- 행 우클릭 메뉴: 유지/휴지통/보관/이동…/보류/항상 유지, 구분선, Finder 에서 보기, 이름 복사(보안 자산은 마스킹 이름).
- 폴더(`category = folder`) 행: 펼침 화살표로 하위 1단계 목록을 인스펙터에 표시(앱이 `FileManager.contentsOfDirectory` 로 읽기만, 최대 200개, `preview_policy == full` 일 때만).

#### 4.2.3 비교 모드 — `CompareView`

대상: 중복(`duplicate:`) 그룹, 그리고 사용자가 아무 그룹에서나 2~4개를 선택하고 ⌘3.

```
┌────────────┬────────────┬────────────┐
│  [썸네일/QL] │  [썸네일/QL] │  [썸네일/QL] │   ← 각 칸은 QLPreviewView(compact) 또는 메타데이터 카드
│ ① 보고서.pdf │ ② 보고서(1).pdf│ ③ 보고서 최종.pdf│
│ ~/Downloads │ ~/Desktop   │ ~/Documents │
│ 11/24 14:02 │ 11/20 09:11 │ 11/24 14:05 │
│ 88 MB       │ 88 MB       │ 88 MB       │
│ 제안: 휴지통 │ 제안: 휴지통 │ 제안: 유지 ★ │
│ [이것만 남기기 1]│ [이것만 남기기 2]│ [이것만 남기기 3]│
└────────────┴────────────┴────────────┘
 동일한 내용(SHA-256 일치) · 3개 중 1개를 남기면 88 MB × 2 를 정리할 수 있습니다.
```

- 한 번에 2~4개. 중복 그룹이 4개를 넘으면 위에 페이지 표시 `1–4 / 6`, ←/→ 로 다음 묶음. 남길 것으로 표시된 칸은 다음 묶음에도 고정 칸으로 유지.
- 차이 강조: 이름·위치·수정일·크기 중 다른 값은 굵게. SHA-256 일치 여부 문구는 `group_key` 가 `duplicate:` 일 때만(“동일한 내용”). 유사 스크린샷·버전 비교(그 외)는 “내용이 다를 수 있습니다”.
- 키: `1`~`4` = 그 칸만 남기기 → 그 항목 `keep`, 나머지 비교 대상 중 `trash` 허용 항목은 `trash`, 불허 항목은 변경 없음(안내). 한 번의 undo 배치. `K`/`D` 등은 포커스 칸에 개별 적용, ←/→ 는 칸 포커스 이동.
- Space = 포커스 칸 Quick Look 전체 크기.
- `metadata_only` 항목은 미리보기 칸 대신 메타데이터 카드, `ephemeral` 은 “Space 로 미리보기” 자리표시.

### 4.3 인스펙터와 미리보기 — `ItemInspectorView`

`.inspector(isPresented:)` 280~360pt. 포커스 항목 1개 기준(다중 선택이면 “N개 선택 · 합계 X” 와 공통 동작만).

| 영역 | 내용 | 출처 |
|---|---|---|
| 미리보기 | §6 정책별 미리보기(큰 썸네일, PDF 첫 페이지, 동영상 포스터+재생, 메타데이터 카드) | 앱(QuickLookThumbnailing/ImageIO/AVKit/PDFKit), 09 §5 |
| 기본 정보 | 이름, 종류, 크기, 생성·수정일, 위치(`display_path`), 프로젝트, 출처 호스트(`where_from_host` 가 있으면 “github.com 에서 다운로드”), N일째 | 항목 JSON, `item.show` |
| 제안 | 동작 + 목적지 + 출처 문구 + 신뢰도(높음/보통/낮음) + `reason` | `suggestion` |
| 결정 | 동작 버튼 7종(키 힌트, 불허는 비활성+툴팁), 현재 결정과 시각, 메모 필드(“메모 추가” → `decision.set` 재전송 시 `note`; 메모는 core 가 암호화 저장) | `allowed_actions`, `decision` |
| 보호 | 🔒 보호 등급 문구 + 이유 한 줄(§5.3) | `protection` |
| 보안 자산 요약 | `vault != null` 이면 종류, 만료, 백업 상태, 발견 사항 수 + [Secure Vault 에서 보기] | `vault` |
| 기록(접힘) | 탐지·이월·결정·계획·실행 이력 | `item.show` |
| 하단 | [Finder 에서 보기] (`NSWorkspace.activateFileViewerSelecting`, dataless·보안 자산도 허용 — 읽기 동작) | `path` |

#### 4.3.1 Quick Look

- Space: 선택 항목 목록(정책 통과분)을 `QLPreviewPanel` 에 넘겨 토글. 패널이 열린 동안 ←/→ 는 패널과 목록 선택을 함께 이동(패널 `currentPreviewItemIndex` ↔ 목록 포커스 동기화).
- 패널이 열린 동안에도 K/D/A/M/S 는 현재 미리보기 항목에 적용(패널이 키를 먹지 않도록 `QLPreviewPanelDelegate` 의 `previewPanel(_:handle:)` 에서 해당 키를 앱으로 전달 — 09 §5.1). 결정 후 자동 진행이 켜져 있으면 패널도 다음 항목으로.
- 제외: `metadata_only` → 패널을 열지 않고 인스펙터의 메타데이터 카드를 강조 + 토스트 “보안 자산은 내용을 표시하지 않습니다”. dataless(☁︎) → 확인 대화상자 “이 파일은 iCloud 에만 있습니다. 미리보려면 이 Mac 으로 내려받아야 합니다(X MB).” [내려받고 미리보기] [취소] (02 §10.6). `/Volumes` 아래 응답 없는 경로 → “외장 볼륨이 응답하지 않습니다”.
- `ephemeral`(환자 자료): Space 에서만 패널 허용. 썸네일은 만들지 않음(§6).

### 4.4 결정 입력 보조 UI

**이동 목적지 선택기 `MoveDestinationPicker`** (M 또는 [이동] — 포커스 항목 옆 팝오버):

```
┌ 어디로 옮길까요? ───────────────────────────┐
│ ★ 제안  ~/dev/PL-Agent/screenshots  (생성 필요) │
│ 최근    ~/Documents/약국/서식                  │
│         ~/dev/RxCount/docs                    │
│ 프로젝트 PL-Agent ▸ docs / references / screenshots │
│         RxCount  ▸ …                          │
│ 다른 폴더 선택…                     ⌘O          │
│                         [취소]  [이동으로 지정 ⏎] │
└──────────────────────────────────────────────┘
```

- 목록: 제안 목적지(`suggestion.dest`, 존재하지 않으면 “생성 필요” — 생성은 executor 가 계획의 일부로, FR-SO-003), 최근 목적지 5개(앱 `UserDefaults`, 환자/보안 항목에 쓴 목적지는 기록하지 않음), 활성 프로젝트(`project.list --active`)의 `docs/ references/ screenshots/`, “다른 폴더 선택…”(`NSOpenPanel`: 폴더만, `canCreateDirectories = false` — 폴더 생성도 파일 변경이므로 앱에서 하지 않음).
- ↑/↓ 선택, ⏎ 확정 → `decision.set {"action":"move","dest": P}`. 숫자 1~9 빠른 선택.
- 오류 `E_PATH_OUTSIDE_ROOTS` → 선택기 안에 “이 위치는 허용된 이동 대상이 아닙니다” (허용 목록 규칙은 08 문서).

**보류 `DeferPopover`**: S = 즉시 기본값(다음 리뷰 날짜 = core 기본, 인자 없이 `decision.set {"action":"defer"}`). ⇧S = 팝오버: 내일 / 3일 후 / 다음 주 월요일 / 날짜 선택 → `defer_until`.

**항상 유지(⇧K)**: 모달 없음. 토스트 “앞으로 이 파일은 묻지 않습니다. 설정 > 다시 묻지 않는 항목에서 해제할 수 있습니다.” [실행 취소]. 처음 1회만 토스트 대신 짧은 설명 팝오버(다시 보지 않기).

**보관(A)**: `config.archive.root` 가 비어 있으면 결정 전에 막는다 — “보관 폴더가 설정되지 않았습니다” [보관 폴더 설정…] → 설정 > 보관. 설정돼 있으면 즉시 `decision.set {"action":"archive"}`(목적지는 plan.create 가 결정, 06 decisions.dest_path 주석).

**토스트 `ActionToast`**: 화면 하단 중앙, 4초, 하나만(새 토스트가 이전 것을 교체). 결정 토스트는 “휴지통 지정 3개 [실행 취소 ⌘Z]”. VoiceOver 는 `AccessibilityNotification.Announcement` 로 같은 문구를 읽는다.

### 4.5 보류 중 — `DeferredItemsView`

데이터: `item.list {"open": true}` 결과 중 `deferred_until > review_date` 인 항목(클라이언트 필터 — §13 R3 에서 서버 필터 요청). 리스트 모드 표(“다시 표시: 11월 27일” 열 추가). 같은 키로 바로 결정 가능. 빈 상태: “보류 중인 항목이 없습니다.”

### 4.6 실행 대기 — `PendingExecutionView` 와 계획 검토·승인 시트 — `PlanReviewSheet`

**실행 대기 목록**: `item.list {"open": true, "state": ["decided","failed"]}` 중 `decided_action ∈ {trash, move, archive}`. 동작별 섹션(휴지통 N · X / 이동 N / 보관 N), 이전 날짜 결정은 “이전 결산에서” 표시. 각 행에서 결정 변경·취소 가능(§3.4).

**M4**: [선택한 정리 계획 검토하기] → 같은 목록을 시트로 보여주고 하단에 비활성 버튼 [승인하고 실행] + 문구 “실행 기능은 다음 버전에서 제공됩니다. 지금은 결정만 기록됩니다.”

**M5 흐름**:

```
[계획 검토하기] ─▶ plan.create {"all_decided": true}
                     ├ ok → PlanReviewSheet(draft)
                     └ 오류 → §7
PlanReviewSheet ─[승인하고 실행]─▶ plan.approve {"plan_id","hash": 표시 중인 plan_hash}
                                     └ ok → plan.apply {"plan_id"} (진행 이벤트) → CompletionReportView
                ─[취소]──────────▶ plan.cancel {"plan_id"} → 항목은 decided 로 남음
```

`plan.create` / `plan.show` 에서 UI 가 필요한 필드:

```json
{"id": "pln_7", "state": "draft", "plan_hash": "9f2c…e1", "op_count": 9, "total_bytes": 1288490188,
 "summary": {"trash": 6, "move": 2, "archive": 1},
 "operations": [
   {"id": "op_33", "seq": 1, "item_id": "itm_128", "op": "trash", "display_name": "Foo.dmg",
    "src_display": "~/Downloads", "dst_display": "휴지통", "size_bytes": 601991168,
    "cross_device": false, "creates_dirs": false, "state": "pending"}],
 "excluded": [{"item_id": "itm_140", "display_name": "AuthKey_••••••.p8", "reason_code": "E_PROTECTED"}]}
```

시트 레이아웃:

```
┌ 정리 계획 확인 ──────────────────────────────────────────────┐
│ 9개 항목 · 1.2 GB    휴지통 6 · 이동 2 · 보관 1                  │
│ ▾ 휴지통으로 (6)                                               │
│    Foo.dmg              ~/Downloads → 휴지통          574 MB    │
│ ▾ 이동 (2)                                                    │
│    스크린샷 …2.02.11.png ~/Desktop → ~/dev/PL-Agent/screenshots (폴더 생성) │
│ ▾ 보관 (1)                                                    │
│    보고서.pdf            ~/Documents → /Volumes/External/DayCloseArchive/2026/11 (다른 볼륨: 복사 후 확인) │
│ ▸ 제외된 항목 (1) — 보안 자산은 계획에 넣지 않습니다                 │
│                                                              │
│ 휴지통으로 보낸 항목은 DayClose 기록에서 되돌릴 수 있습니다.           │
│ 계획 번호 9f2c…e1                                              │
│                                    [취소]  [승인하고 실행 ⌘⏎]   │
└──────────────────────────────────────────────────────────────┘
```

- 승인 버튼은 시트가 보여주는 `plan_hash` 그대로 `plan.approve` 에 보낸다(FR-VR-007). 시트를 연 뒤 `plan.show` 로 다시 받은 해시가 다르면 버튼 비활성 + “계획이 바뀌었습니다. 다시 확인하세요.” [새로고침].
- 승인 버튼은 기본 버튼이지만 시트가 뜬 직후 1초간 비활성(실수 방지). ⌘⏎ 로만 키보드 승인(⏎ 단독은 안 됨).
- 오류: `E_APPROVAL_MISMATCH` → 새로고침 유도. `E_STALE`(plan.create 시점) → 해당 항목 표시 후 재생성. `E_ARCHIVE_TARGET_MISSING` → 보관 설정 유도. `E_VOLUME_TIMEOUT`/`E_VOLUME_UNAVAILABLE` → “보관 폴더가 있는 외장 볼륨이 연결되지 않았거나 응답하지 않습니다.”
- 승인 방식 강화(Touch ID 등)는 08 문서의 결정을 따른다(§13 R8, 09 §11.3).

### 4.7 실행 진행과 완료 리포트 — `PlanProgressView`, `CompletionReportView` (M5)

- 진행: `plan.apply` 의 진행 이벤트(`phase: "apply"`, `done`, `total`) → 시트 안 진행 막대 “6 / 9 처리 중”. 취소 버튼 없음(연산 단위 커밋 중 중단은 recover 대상이므로 사용자 중단을 제공하지 않음, 결정). 실행 중 앱 종료 시 09 §4.6 의 종료 지연 대화상자.
- 결과(`ok` 또는 `E_PARTIAL` 의 `data.operations[*].state`):

```
┌ 오늘의 정리를 완료했습니다 ─────────────────────────────────┐
│ ✓ 휴지통으로 이동 6개 · 1.1 GB  (휴지통을 비우면 공간이 확보됩니다) │
│ ✓ 이동 2개   ✓ 보관 1개                                       │
│ ⚠ 건너뜀 1개 — 계획 후 파일이 바뀌었습니다 (다음 결산에 다시 표시) │
│ ✕ 실패 0개                                                   │
│ 남은 미결 항목 3개 · 보류 2개                                    │
│           [기록에서 보기]  [되돌리기…]  [닫기]                    │
└──────────────────────────────────────────────────────────────┘
```

- `op.state`: done ✓, skipped ⚠(`error_code` 문구 §7), failed ✕(재시도 안내: 항목이 `failed` 로 남아 다음 계획에 포함 가능).
- [되돌리기…] 또는 ⌘Z → 확인 대화상자 “방금 실행한 9개 작업을 되돌릴까요? 휴지통·이동·보관한 파일이 원래 위치로 돌아갑니다.” [되돌리기] [취소] → `plan.undo {"plan_id"}`. 충돌(`E_DEST_EXISTS`) → “원래 위치에 같은 이름의 파일이 있습니다.” [이름을 바꿔 복원] (`on_conflict: "rename"`) [건너뛰기]. `E_UNDO_IMPOSSIBLE` → “휴지통이 비워져 되돌릴 수 없는 항목이 있습니다.”
- 닫을 때 `items_open == 0` 이면 `review.close` 호출(결정: 사용자가 그날 정리를 끝냈다는 표시. 다음 `review.summary` 는 그대로 동작).

### 4.8 (예약) M6 — 규칙 제안 카드

메인 그룹 목록 위 카드: “설치가 끝난 DMG 를 7번 모두 휴지통으로 지정하셨습니다. 기본 규칙으로 등록할까요?” [등록] [이번엔 안 함] [다시 묻지 않기] → `policy.accept` / (무시) / `policy.reject`. 등록 후에도 “실행은 계획 승인이 필요합니다” 부제. 습관 항목은 그룹 제목 앞 “습관” 배지로 묶여 [한 번에 수락] (CONTEXT 턴0 §6). 세부 조건은 07 문서.

### 4.9 Secure Vault 인벤토리 — `VaultInventoryView`

데이터: `vault.list {"status": "active"}` (+ 필터), 자산별 열린 리뷰 항목 연결은 `item.list {"category": ["security_asset"], "open": true}`. UI 필요 필드:

```json
{"id": "ast_5", "masked_name": "AuthKey_••••••.p8", "kind": "apple_signing", "display_path": "~/Downloads",
 "project": {"id": "prj_3", "name": "PL-Agent"}, "detect_methods": ["extension","content_pattern"], "confidence": 0.95,
 "expires_on": "2026-12-17", "expiry_source": "file", "needs_password": false, "backup_status": "unknown",
 "status": "active", "findings_open": 2, "max_severity": "high", "item_id": "itm_140", "item_decision": null}
```

```
┌ Secure Vault · 보안 자산 인벤토리 ──────────────────────────────────────────────┐
│ ┌발견된 자산 6┐ ┌보호 검토 필요 3┐ ┌검토 완료 0┐ ┌만료 임박 1┐                          │
│ 종류 ▾  상태: (사용 중|사라짐|폐기됨)  [검토 필요만]                                  │
│ 이름                  종류                 위치          프로젝트   만료      백업   │
│ ⚿ AuthKey_••••••.p8   Apple 개발자 키       ~/Downloads   PL-Agent  미확인     ?    │
│ ⚿ distribution.p12    Apple 배포 인증서     ~/Desktop     —         23일 남음  ?  ⚠ │
│ ⚿ firebase-admin.json 클라우드 서비스 계정   ~/Downloads   —         미확인     ?    │
│ ⚿ .env.production     환경 변수 파일        ~/dev/PL-Agent PL-Agent —         ?  ⚠ │
│ ⚿ id_ed25519          SSH 개인키            ~/.ssh        —         —          ?    │
│ ⚿ old-server.crt      TLS 인증서            ~/Documents   —         만료됨     ?    │
├──────────────────────────────────────────────────────────────────────────────┤
│ 개인키 원문은 AI에 전송하지 않습니다. · 보안 자산은 일반 일괄 삭제 대상에서 제외됩니다.     │
└──────────────────────────────────────────────────────────────────────────────┘
```

- 지표: 발견된 자산 = `total`, 보호 검토 필요 = 열린 리뷰 항목이 있는 자산, 검토 완료 = 오늘 결정된 자산, 만료 임박 = `expires_on` 이 `vault.expiry_warn_days` 이내.
- 이름 표시는 `masked_name` 만(마스킹 규칙은 05 문서). 위치는 디렉터리(`display_path`)만.
- 만료 열: `needs_password` → “미확인(암호 필요)”, `expiry_source = unknown` → “미확인” + 툴팁 “만료일을 직접 입력할 수 있습니다”, `user` → 날짜 + “(직접 입력)”.
- 백업 열: `backup_status` unknown “?”, none “없음”, verified “확인됨”, stale “오래됨”.
- 행 선택 → 오른쪽 `VaultAssetDetailView`. **Space 는 Quick Look 을 열지 않고 상세 패널을 연다**(내용 미리보기 금지).
- 키: 열린 리뷰 항목이 있는 자산에서 K(유지)·⇧K(항상 유지)·S(보류)·K 대체 확인(§5.2). D/A/M → §5.3 차단 안내. ⌘C → 마스킹 이름 복사.
- 썸네일·파일 아이콘 없음: 종류별 SF Symbol 만(`key.fill`, `lock.doc`, `terminal` 등). `NSWorkspace.icon(forFile:)` 도 호출하지 않는다(파일 접근 0, FR-VR-006).

`vault_asset_kind` 문구: certificate 인증서 · pkcs12 인증서 묶음(.p12) · private_key 개인키 · ssh_private_key SSH 개인키 · ssh_config SSH 설정 · env_file 환경 변수 파일 · api_credential API 인증 정보 · cloud_credential 클라우드 인증 정보 · apple_signing Apple 개발자 키·서명 · android_keystore Android 키스토어 · vpn_config VPN 설정 · crypto_wallet 암호화폐 지갑 · crypto_seed_suspected 복구 구문 의심 · db_credential DB 접속 정보 · recovery_codes 복구 코드 · npki_cert 공동인증서 · unknown_secret 기타 비밀.

**자산 상세 `VaultAssetDetailView`** (`vault.show {"asset_id"}`):

| 섹션 | 내용 |
|---|---|
| 머리 | 종류 아이콘, `masked_name`, 종류 문구, 상태 |
| 위치 | 디렉터리, 프로젝트, Git: “Git 에 추적됨 ⚠ / 무시됨 / 저장소 밖” |
| 탐지 | 방법 문구(확장자·파일 이름·위치·파일 형식·내용 패턴·gitleaks), 확신도(높음/보통/낮음) |
| 인증서 | 발급자, 유효 기간, 남은 일수, 주체(기본 가림 — [주체 보기] 클릭 시 표시, 복사 불가. 05 문서상 실명 포함 가능) |
| 키 | 공개키 지문 앞 16자(복사 가능 — 비밀 아님), 같은 지문의 다른 위치 수 |
| 권한 | `permissions_mode` → “0600 (정상)” / “0644 — 다른 사용자가 읽을 수 있습니다” |
| 백업 | `backup_status` + 설명 + 선택 컨트롤 [백업됨 · 백업 없음 · 모름] → `vault.annotate {"asset_id", "backup": "verified"\|"none"\|"unknown"}`. 이것이 `backup_status` 를 바꾸는 유일한 경로(02 §5.3). 결정: DayClose 는 백업을 직접 확인하지 않으므로 문구는 “내가 백업을 확인했음” 으로, 선택 시 확인 팝오버 “백업 사본에서 복구할 수 있는지 직접 확인하셨나요?” [확인했습니다]. 같은 컨트롤이 Security Health 의 `no_backup` 카드에도 있음 |
| 내 메모 | 이름표·메모·만료일 편집 → `vault.annotate {"asset_id","label"?,"note"?,"expires"?}`. 저장 시 “암호화되어 저장됩니다” |
| 발견 사항 | 이 자산의 finding 목록(§4.10 카드 축약) |
| 동작 | 리뷰 항목이 열려 있으면 결정 버튼(K/⇧K/S/확인). [Finder 에서 보기] — 결정: 허용(읽기 동작, 사용자가 명시적으로 클릭). 경로 문자열 복사는 제공하지 않음 |

`crypto_seed_suspected` 자산: 상세에 지문·내용 정보 없음. 문구 “복구 구문이 들어 있을 수 있는 파일입니다. DayClose 는 이 파일의 내용이나 지문을 저장하지 않습니다. 종이 백업 후 디지털 사본 삭제를 고려하세요.”(최종 문구는 05).

빈 상태: “발견된 보안 자산이 없습니다.” + 마지막 vault 스캔 시각. `W_TOOL_MISSING`(gitleaks) 경고가 있으면 정보 배너 “gitleaks 가 없어 기본 패턴으로만 검사했습니다.”

### 4.10 Security Health — `SecurityHealthView`

데이터: `vault.health`. UI 필요 필드(05/10 확정):

```json
{"checks": [{"finding": "bad_permissions", "status": "ok", "open_count": 0}, …],
 "findings": [{"id": "fnd_9", "finding": "expiring_soon", "severity": "high", "state": "open",
               "asset_id": "ast_6", "asset_masked_name": "distribution.p12",
               "title": "Apple Distribution 인증서 만료 임박", "message": "만료까지 23일 남았습니다.",
               "recommendation": "Apple Developer 에서 새 인증서를 발급하세요.", "detected_at": "…"}]}
```

```
┌ Security Health ─────────────────────────────────────────────┐
│ 심각 0 · 높음 2 · 주의 1 · 정보 0                                 │
│ ┌ 높음 ─ Apple Distribution 인증서 만료 임박 ─────────────────┐ │
│ │ distribution.p12 · 만료까지 23일                            │ │
│ │ 권장: Apple Developer 에서 새 인증서를 발급하세요.  [자산 보기] │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌ 높음 ─ Git 저장소 안의 인증 정보 ──────────────────────────┐ │
│ │ .env.production 이 Git 추적 대상입니다.                     │ │
│ │ 권장: 파일 삭제가 아니라 키 폐기·재발급이 필요합니다. [자산 보기] │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌ 주의 ─ 중복 개인키 ─ 같은 키가 3개 경로에 있습니다 ───────────┐ │
│ ┌ 주의 ─ 백업 미확인 인증서 2개 ──────────────────────────────┐ │
│ ✓ SSH 파일 접근 권한 — 정상                                    │
│ ✓ 만료된 인증서 — 없음                                         │
└──────────────────────────────────────────────────────────────┘
```

- 카드 정렬: severity(critical→info), 그다음 `detected_at`. 색 + 문구 + 아이콘(색만으로 구분 금지).
- 카드 문구(`title`, `message`, `recommendation`)는 core(05) 가 준 그대로 쓴다. 앱이 조합하지 않는다(특히 `tracked_in_git` 의 “폐기·재발급” 권고, FR-SV-007).
- `checks` 중 `status == ok` 는 하단 “✓ … — 정상” 줄.
- [확인함] 버튼(발견 사항 `open → acknowledged`): 이를 수행하는 명령이 02 §5.3 에 없다 → 명령이 생기기 전까지 버튼을 표시하지 않는다(§13 R5).
- `plaintext_secret`(일반 파일 속 비밀): 파일 이름은 core 가 준 표시 이름만, 줄 번호 표시 가능, 매치 내용 절대 없음. [파일 위치 보기] = Finder 에서 보기.

### 4.11 앱·패키지 — `InventoryView`, 프로젝트 — `ProjectsView`

`InventoryView` 상단 세그먼트: 앱 / Homebrew / 로그인 항목.

| 탭 | 데이터 | 열 | 필터 |
|---|---|---|---|
| 앱 | `app.list` (`--new`, `--removed`) | 아이콘(`NSWorkspace.icon(forFile:)` — 앱 번들 아이콘 읽기), 이름, 버전, 출처(App Store / Homebrew / 직접 설치 / 알 수 없음), 크기, 마지막 사용(없으면 “알 수 없음”), 처음 발견 | 전체 / 새로 설치 / 삭제됨 / 버전 바뀜 / 90일 이상 미사용 |
| Homebrew | `package.list` (`--manager`, `--new`) | 이름, 종류(formula/cask), 버전, 직접 설치 여부, 처음 발견 | 전체 / 새로 설치 / 직접 설치만 |
| 로그인 항목 | `item.list {"category": ["login_item"]}` (목록 명령이 없음 — §13 R7) | 이름(label), 종류, 프로그램 위치, 처음 발견 | 미결만 |

- 행에 열린 리뷰 항목이 있으면 결정 배지와 K(확인)·⇧K(항상 유지)·S(보류) 사용 가능. D/A/M → “DayClose 는 앱·패키지를 삭제하지 않습니다.”
- [Finder 에서 보기], 앱은 [앱 정보 보기](Finder 정보 창 대신 인스펙터에 Info.plist 요약 — core 가 준 값만).
- 빈 상태: “새로 설치된 앱이 없습니다.” `W_TOOL_MISSING`(brew) → Homebrew 탭 “Homebrew 가 설치되어 있지 않아 패키지를 확인하지 않았습니다.”

`ProjectsView`: `project.list` → 이름, 위치, 활성 여부(최근 30일), 마지막 커밋, 미커밋 파일 수(`dirty_count`), 오래된 브랜치 수, 원격 호스트. 행 → Finder 에서 보기. git_repo 리뷰 항목(미커밋 변경 알림)은 결산 그룹에 나타나며 K=확인.

### 4.12 기록 — `HistoryView`

세그먼트: 결정 / 실행(M5) / 감사(M5).

| 탭 | 데이터 | 행 | 동작 |
|---|---|---|---|
| 결정 | `decision.list {"since": D-30, "limit": 200}` | 시각, 항목 표시 이름(보안 자산 마스킹), 동작, 범위(항목/그룹), 출처 채널(앱/CLI/Skill/규칙), 취소됨 여부 | 항목이 아직 `decided`(계획 전)이면 [취소] → `decision.undo {"item_ids":[…]}` |
| 실행 | `plan.list` → 선택 시 `plan.show` | 계획 번호, 생성·실행 시각, 상태(`plan_state` 문구), 연산 수, 용량 | [전체 되돌리기] `plan.undo {"plan_id"}`, 연산 행 [되돌리기] `plan.undo {"plan_id","op_ids":[…]}`. `undo_state` 표시: 되돌릴 수 있음 / 되돌림 / 되돌리기 실패 / 되돌릴 수 없음 |
| 감사 | `audit.list {"since": D-30}` | 시각, 명령, 채널, 결과(성공/오류 코드), 요약 | 읽기 전용 |

중단된 실행: 앱 시작 시 `plan.list {"state": "executing"}` 이 비어 있지 않으면 전역 배너 “지난 실행이 중간에 멈췄습니다. 파일 상태를 확인하고 기록을 정리합니다.” [복구] → `plan.recover` → 결과 요약 시트.

`plan_state` 문구: draft 확인 대기 · approved 승인됨 · executing 실행 중 · completed 완료 · partial 일부 완료 · failed 실패 · cancelled 취소됨 · undone 되돌림 · partially_undone 일부 되돌림.

### 4.13 설정 — `SettingsView` (⌘,)

탭(`TabView`): 일반 · 스캔 위치 · 보호 규칙 · 다시 묻지 않는 항목 · 보관(M5) · AI(M6) · 알림·예약(M7) · 권한 · 고급. 저장: core 설정은 값 변경 즉시 `config.set {"key","value"}`(텍스트 필드는 포커스 이탈 시), 오류 `E_CONFIG_INVALID` → 필드 아래 빨간 문구 + 이전 값 복원.

| 탭 | 항목 | 명령/저장소 |
|---|---|---|
| 일반 | 결산 날짜 경계(`review.day_boundary`, 시각 선택), 이월(`review.carryover`), 결정 후 다음 항목으로(앱), 기본 썸네일 크기(앱), 그룹 열 때 기본 보기 모드 초기화(앱) | `config.set` / `UserDefaults` |
| 스캔 위치 | 루트 표: 경로(`display_path`), 종류(`scan_root_kind` 문구: 다운로드·데스크탑·스크린샷·문서·iCloud Drive·프로젝트·보안 추가 경로·사용자 지정), 상태(마지막 doctor: 정상 / 권한 없음 / 응답 없음 / 없음), [+] `NSOpenPanel` → 종류 선택 → `root.add {"path","kind"}`, [−] 확인 후 `root.remove {"root_id"}`. 제외 패턴 목록 편집(`scan.exclude_globs`), 프로젝트 폴더(`projects.roots`) | `root.*`, `config.set` |
| 보호 규칙 | `rule.list` 표: 종류(경로로 시작 / 글롭 / 확장자 / 프로젝트), 패턴, 보호 등급, 출처(기본 제공 / 내가 추가 / 설정). 기본 제공 규칙은 잠금(삭제 버튼 없음). [+] 시트 → `rule.add {"kind","pattern","protection","sensitivity"?}`. 환자 자료 파일 이름 패턴(`protection.patient_filename_patterns`), 주민번호 탐지(`protection.detect_rrn_in_text`) | `rule.*`, `config.set` |
| 다시 묻지 않는 항목 | `suppression.list` 표: 대상(표시 이름·종류), 일치 방식, 만든 날짜. [해제] → `suppression.remove {"suppression_id"}` + 안내 “다음 스캔에서 다시 물어봅니다” | `suppression.*` |
| 보관 | 보관 폴더(`archive.root`) 선택(`NSOpenPanel`), 배치 미리보기 `<root>/2026/11/파일명`, 외장이면 “연결되어 있을 때만 보관할 수 있습니다” | `config.set` |
| AI | §4.13.1 | `config.set`, `ai.status` |
| 알림·예약 | 매일 결산 시각(`review.daily_time`), 예약 실행 켜기(SMAppService 상태 표시: 켜짐 / 승인 필요 / 꺼짐 + [로그인 항목 설정 열기]), 알림 허용 상태 + [알림 설정 열기], 메뉴바에 표시 | `config.set` + 09 §8 |
| 권한 | §4.14.2 FDA 상태 3종(앱 / core / 예약 실행), 폴더별 접근 상태(`core.doctor` 의 루트 결과), [진단 다시 실행], [전체 디스크 접근 권한 설정 열기] | `core.doctor`, 09 §7 |
| 고급 | core 실행 파일 경로(앱 설정 `core.command`, [찾아보기…], [기본값]), core·계약·DB 버전(`core.version`), 상태 폴더 열기, 로그 폴더 열기(`~/Library/Logs/DayClose`), 로그 수준(`core.log_level`) | `UserDefaults`, `core.version` |

설정 화면에 없는 것(결정, 소유자 답변 2026-11-24): NAS·SMB·원격 보관 대상 화면, 보관 대상 목록 관리, 환자 자료 폴더 지정. 보관은 “보관 폴더” 하나(`archive.root`)뿐이고, 모든 값은 **이 Mac 에만** 적용된다는 문구를 탭 상단에 둔다(02 §8.1).

#### 4.13.1 AI 탭 (M6)

```
┌ AI ─────────────────────────────────────────────────────────────┐
│ AI 제안 사용                         [ 꺼짐 ◯ ]                    │
│ 공급자   (없음 | 로컬 ollama | Anthropic | OpenAI)   모델 [        ] │
│ 외부 공급자로 보내기 허용             [ 꺼짐 ◯ ]                    │
│ API 키   ● 저장되어 있지 않음   [키 입력…]  [키 삭제]                 │
│ 상태     외부 AI 꺼짐 — “외부 전송 허용”이 꺼져 있습니다               │
│ ─────────────────────────────────────────────────────────────── │
│ 보내는 것: 파일 이름·종류·크기·날짜·폴더 같은 메타데이터만.            │
│ 보내지 않는 것: 파일 내용, 환자 관련 자료, 보안 자산(키·인증서),        │
│   그리고 비밀·주민번호 패턴이 보이는 항목 — 설정과 관계없이 항상 제외.   │
│ 키는 macOS 키체인에만 저장되고 설정 파일·로그에 남지 않습니다.          │
│ AI 를 꺼도 DayClose 의 모든 기능은 그대로 동작합니다.                  │
└─────────────────────────────────────────────────────────────────┘
```

- 토글·선택은 `config.set`(`ai.enabled`, `ai.provider`, `ai.model`, `ai.allow_external`). “외부 공급자로 보내기 허용” 을 켤 때 확인 대화상자(위 “보내는 것/보내지 않는 것” 문구 반복) — 결정: 외부 전송은 명시적 2단계(토글 + 확인)로만.
- 상태 줄은 `ai.status` 기준. 외부 공급자는 `enabled=true` + `allow_external=true` + 키 있음 셋 다일 때만 동작하고, 아니면 core 가 `E_AI_DISABLED`(02 §9) → 빠진 조건을 문장으로 표시. `ollama` 는 키·외부 허용 불필요(로컬).
- [키 입력…]: `SecureField` 시트. 저장은 core 명령으로 보낸다(§13 R9) — 앱은 키를 `UserDefaults`·로그·클립보드에 두지 않고, 시트를 닫으면 메모리 값을 지운다. 명령이 생기기 전(임시): 시트 대신 안내 “터미널에서 `uv run --project core keyring set com.dayclose.ai anthropic` 을 실행하고 프롬프트에 키를 붙여 넣으세요(키가 명령 줄에 남지 않습니다).” 키 값 자체는 어떤 화면에도 다시 표시하지 않고 “저장됨/없음” 만.
- 민감도 게이트 설명은 고정 문구(위). 수치(“지난 7일 AI 요청 12건, 제외된 항목 30개”)는 `ai.status` 가 주면 표시(07 문서의 `ai_requests` 감사).

### 4.14 온보딩 — `OnboardingFlow`

진입: `AppPhase.onboarding`(core 가 `E_NOT_INITIALIZED`), 또는 설정 > 고급 > [온보딩 다시 보기](4단계부터).

```
① 환영 ─▶ ② core 확인 ─▶ ③ 준비(init) ─▶ ④ 전체 디스크 접근 ─▶ ⑤ 첫 스캔 ─▶ ⑥ 알림·예약(M7) ─▶ 완료
```

| 단계 | 화면 | 동작 |
|---|---|---|
| ① 환영 `WelcomeStepView` | “DayClose — End your day with a clean Mac.” 세 원칙: “승인 전에는 파일을 바꾸지 않습니다 / 지운 것도 되돌릴 수 있습니다(휴지통) / 키·인증서는 옮기지 않고 지킵니다” | [시작하기] |
| ② core 확인 `CoreCheckStepView` | `core.version` 성공 시 자동 통과. 실패 시 §4.15 의 설치 안내 내장 | [다시 확인] |
| ③ 준비 `InitStepView` | 기기 이름(기본값은 core 가 정함 = 컴퓨터 이름, 02 §9 — 앱은 빈 값이면 인자를 생략), 기본 스캔 위치 미리보기(다운로드·데스크탑·스크린샷 위치·문서·iCloud Drive·~/dev — 존재하는 것만 체크). iCloud Drive 줄 설명: “iCloud 에만 있는 파일은 내려받지 않고 이름만 확인합니다. 휴지통·이동은 하지 않습니다.” 문구 “이 Mac 의 설정입니다. 다른 Mac 은 따로 설정합니다.” + [외장 디스크 폴더 추가…](`/Volumes/*` 루트는 기기별로 사용자가 추가 — 02 §8.1 결과 3. 예: Mac mini 의 `/Volumes/External`) | [준비하기] → `core.init {"device_name"?}` → 체크 해제한 기본 루트는 `root.remove`, 추가한 외장 폴더는 `root.add {"path","kind":"custom"}`. `init` 경고(존재하지 않는 경로)는 목록에 회색 표시 |
| ④ FDA `FullDiskAccessStepView` | §4.14.1 | |
| ⑤ 첫 스캔 `FirstScanStepView` | `scan.run --trigger init` 진행(단계별 문구: 파일 확인 중 / Git 프로젝트 / 보안 자산 / 앱 / Homebrew). 완료 후 “파일 18,234개를 확인했습니다. 오늘부터의 변화를 매일 결산합니다.” — 결정: 첫 스캔은 기준선이며 기존 파일 전체를 리뷰 항목으로 쏟아내지 않는다(어떤 변경이 항목이 되는지는 04 문서) | [결산 보기] |
| ⑥ 알림·예약(M7) | “매일 21:00 에 정리할 것을 알려드릴까요?” 시각 선택 → [켜기] = 알림 권한 요청 + `SMAppService` 등록(09 §8) / [나중에] | |

#### 4.14.1 전체 디스크 접근 단계

```
┌ 전체 디스크 접근 권한 ──────────────────────────────────────────┐
│ DayClose 는 다운로드·데스크탑·문서·외장 디스크를 매일 확인합니다.     │
│ 전체 디스크 접근 권한이 없으면 예약 실행이 일부 폴더를 건너뜁니다.      │
│                                                                 │
│ 상태: ● 허용되지 않음   (2초마다 자동 확인)                          │
│                                                                 │
│ 1. [시스템 설정 열기]를 누릅니다.                                   │
│ 2. 개인정보 보호 및 보안 → 전체 디스크 접근 권한에서 DayClose 를 켭니다. │
│    목록에 없으면 [+] 를 눌러 응용 프로그램의 DayClose 를 추가합니다.     │
│ 3. 이 창으로 돌아오면 자동으로 확인됩니다.                            │
│                                                                 │
│ DayClose 는 이 권한으로 파일을 읽기만 합니다. 변경은 항상 승인 후에만.  │
│                         [나중에 하기]   [시스템 설정 열기]           │
└─────────────────────────────────────────────────────────────────┘
```

- 상태값(09 §7.2 프로브): `granted` ● 허용됨(녹색, 2초 후 자동 다음 단계) / `denied` ● 허용되지 않음 / `unknown` ● 확인할 수 없음(“권한을 켰다면 DayClose 를 다시 시작하세요” — 일부 권한은 재시작 후 반영).
- [시스템 설정 열기] → 09 §7.4 의 URL. 실패 시 “시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한” 문구만.
- [나중에 하기] → 제한 모드로 진행. 메인 사이드바 하단 `⚠ 권한 확인 필요` 상주, 수동 스캔 시 macOS 가 폴더별 접근을 따로 물을 수 있음을 안내 “macOS 가 ‘DayClose 가 데스크탑 폴더에 접근하려고 합니다’ 를 물으면 허용을 눌러 주세요.”
- 재빌드 후 풀림(02 §4·§10.5): 이전에 `granted` 였는데 지금 `denied` 면 문구 추가 “앱을 다시 빌드한 뒤라면 서명이 바뀌어 권한이 풀렸을 수 있습니다. 목록에서 DayClose 를 끄고 다시 켜 주세요.”

#### 4.14.2 권한 상태 표시(설정 > 권한, 메뉴바 경고 공통)

| 줄 | 출처 | 의미 |
|---|---|---|
| DayClose 앱 | 앱 프로세스 프로브(09 §7.2) | 미리보기·썸네일에 영향 |
| 정리 엔진(core) | `core.doctor` (channel `app`) | 수동 스캔에 영향 |
| 예약 실행 | 스케줄러가 마지막으로 기록한 doctor 결과(09 §8.5) | 매일 21:00 실행에 영향. “마지막 확인: 어제 21:00” |

세 값이 다르면 문구: “예약 실행에서만 권한이 없습니다. 예약 실행 헬퍼가 DayClose 앱 안에 있는지, 앱을 옮기거나 다시 빌드하지 않았는지 확인하세요.” [진단 방법 보기] → 09 §7.5 요약.

### 4.15 core 오류 화면 — `CoreUnavailableView`, `FatalErrorView`

| 경우 | 문구 | 버튼 |
|---|---|---|
| core 없음 | “정리 엔진(dayclose)을 찾을 수 없습니다.” + 터미널 명령 블록 `uv tool install --editable ./core` (복사 버튼) + 찾은 위치 목록(09 §3.2) | [다시 확인] [경로 지정…] |
| 계약 불일치 | “정리 엔진 버전이 앱과 맞지 않습니다(엔진 계약 v2, 앱 v1).” core 가 높으면 “앱을 업데이트하세요”, 낮으면 “엔진을 업데이트하세요” | [다시 확인] |
| `E_DB_MIGRATION` | “데이터베이스를 새 버전으로 올리지 못했습니다. 백업이 남아 있습니다.” + `error.message`(백업 경로 안내 포함) | [상태 폴더 열기] [다시 시도] |
| `E_DB_CORRUPT` | “데이터베이스가 손상되었습니다.” + 백업 복원 안내 | [상태 폴더 열기] |
| core 반복 종료 | “정리 엔진이 계속 종료됩니다.” + 로그 위치 | [다시 시도] [로그 폴더 열기] |

## 5. 키보드

### 5.1 전체 키 맵

포커스가 텍스트 입력에 있으면 한 글자 키는 동작하지 않는다(`onKeyPress` 를 목록/그리드 포커스 영역에만 부착).

| 키 | 메인(그룹 행) | 그룹 상세(갤러리/리스트) | 비교 | Quick Look 열림 | Vault 목록 |
|---|---|---|---|---|---|
| Space | 그룹 Quick Look | 선택 항목 Quick Look 토글 | 포커스 칸 QL | 닫기 | 상세 패널(QL 아님) |
| ← / → | (→ = 열기) | 이전·다음 항목 | 칸 이동 / 묶음 넘김 | 이전·다음(목록 동기화) | — |
| ↑ / ↓ | 그룹 이동 | 리스트: 이전·다음 / 갤러리: 위·아래 행 | — | — | 이전·다음 |
| K | 그룹 `keep` | `keep`(불허 시 `acknowledge`, §5.2) | 포커스 칸 | 현재 항목 | 리뷰 항목 있으면 `keep` |
| ⇧K | 그룹 `keep_always` | `keep_always` | 〃 | 〃 | 〃 |
| D | 그룹 `trash` | `trash` | 〃 | 〃 | 차단 안내 |
| A | 그룹 `archive` | `archive` | 〃 | 〃 | 차단 안내 |
| M | 목적지 선택 후 그룹 `move` | 목적지 선택기 | 〃 | 패널 닫고 선택기 | 차단 안내 |
| S / ⇧S | 그룹 `defer` / 날짜 | `defer` / 날짜 | 〃 | 〃 | 리뷰 항목 있으면 |
| 1~4 | — | — | 그 칸만 남기기 | — | — |
| X | 체크박스(제안 수락) 토글 | 항목 선택 토글 | — | — | — |
| ⌘Z / ⇧⌘Z | 결정 취소 / 다시 | 〃 | 〃 | 〃 | 〃 |
| Return | 그룹 열기 | 인스펙터 포커스 | — | — | 상세 |
| Esc / ⌘[ | — | 메인으로 | 이전 모드 | 닫기 | — |
| ⌘] / ⌘⇧] | — | 다음 미결 그룹 / 이전 그룹 | — | — | — |
| ⌘1/2/3 | — | 갤러리/리스트/비교 | 〃 | — | — |
| ⌘A | — | 전체 선택 | — | — | — |
| ⌘R | 스캔 | 스캔 | — | — | 스캔 |
| ⌘⏎ | 계획 검토 | 계획 검토 | — | — | — |
| ⌘F | 검색 | 검색 | — | — | 검색 |
| ⌥⌘I | 인스펙터 | 인스펙터 | 인스펙터 | — | — |

모든 단축키는 메뉴 막대(`결산` 메뉴: 유지 K, 항상 유지 ⇧K, 휴지통 D, 보관 A, 이동… M, 보류 S, 보류 날짜… ⇧S)에도 있어 발견 가능하고 VoiceOver 로 실행 가능하다(`.commands { CommandMenu("결산") … }`, 메뉴 항목 활성 여부 = 현재 대상의 `allowed_actions`).

### 5.2 K 의 대체 규칙 (결정)

K 는 “이대로 둔다” 하나의 의미로 쓴다: 대상의 `allowed_actions` 에 `keep` 이 있으면 `keep`, 없고 `acknowledge` 가 있으면 `acknowledge`. 이유: 앱·패키지·Git·시스템 항목(`keep` 불허, 02 §10.1)에서도 같은 키로 처리하기 위함. 버튼 문구는 실제로 보낼 동작으로 표시(“유지” 또는 “확인”). 둘 다 허용되는 보안 자산은 K=`keep`, 인스펙터에 별도 [확인] 버튼.

### 5.3 허용되지 않는 동작 키 (보호 항목)

불허 동작은 키를 누르기 전에도 **보이게** 비활성이다: 인스펙터·`DecisionBar` 의 해당 버튼은 회색 + 자물쇠 아이콘, 버튼 줄 아래에 이유 한 줄(아래 표 문구, 툴팁만으로 숨기지 않음). iCloud Drive 루트 항목과 dataless 파일은 `allowed_actions` 가 `keep`/`keep_always`/`defer` 뿐이므로(02 §10.1 예외 2) D·A·M 이 항상 이 상태로 보이고, 셀에는 ☁︎ “iCloud 에만 있음(내려받지 않음)” 배지가 붙는다.

키를 눌렀는데 대상 전부가 그 동작을 허용하지 않으면: 요청을 보내지 않고, 시스템 경고음 없이 포커스 항목 위에 말풍선(2.5초) + VoiceOver 공지. 일부만 허용하면 허용 항목에만 적용하고 토스트 “휴지통 지정 3개 · 1개는 보호 항목이라 건너뜀”.

문구 선택(앱은 `allowed_actions` 로 차단 여부를 판단하고, 이유 문구는 아래 우선순위로 고른다 — core 가 이유 필드를 주면 그것을 우선, §13 R4):

| 조건 | 차단된 키 | 문구 |
|---|---|---|
| `protection = security_asset` | D, A, M | “보안 자산은 제자리에서만 관리합니다. 휴지통·이동·보관할 수 없습니다.” |
| `protection = patient_data` | D | “환자 관련 자료는 휴지통으로 보낼 수 없습니다. 보관(A)이나 이동(M)만 가능합니다.” |
| `protection = active_repo` | D, A, M | “활성 Git 저장소 안의 파일은 옮기거나 지우지 않습니다.” |
| `protection = system` | K(keep), D, A, M | “시스템 항목은 확인(K)이나 보류(S)만 할 수 있습니다.” |
| `protection = user_rule` | D, A, M | “내 보호 규칙으로 보호된 항목입니다. 설정 > 보호 규칙에서 바꿀 수 있습니다.” |
| `subject_type ∈ {app, package, git_repo, login_item}` | D, A, M | “DayClose 는 앱·패키지·저장소를 삭제하거나 옮기지 않습니다.” |
| iCloud Drive / dataless(☁︎) | D, A, M | “iCloud Drive 항목은 휴지통·이동·보관을 지원하지 않습니다. 다른 기기에서도 지워질 수 있기 때문입니다.” |
| 그 외 | 해당 키 | “이 항목에는 ‘{동작}’ 을 사용할 수 없습니다.” |
| `state = planned` | 모든 결정 키 | “실행 대기 중인 항목입니다. 계획을 취소해야 바꿀 수 있습니다.” |

그룹 결정에서 보안 자산·환자 자료는 core 가 제외한다(`W_PROTECTED_SKIPPED`) → 행 아래 “보호 항목 N개는 그룹 결정에서 제외했습니다. 개별로 확인하세요.”

## 6. 미리보기·썸네일 정책 (화면 동작)

구현 방식(어떤 API 로 만드는지·캐시 위치)은 09 §5·§6. 여기서는 사용자가 보는 결과.

| `preview_policy` / 상태 | 그리드 썸네일 | 인스펙터 미리보기 | Space(Quick Look) | 파일 아이콘 |
|---|---|---|---|---|
| `full` | 생성(메모리 캐시, 09 §6) | 큰 썸네일/PDF 첫 페이지/동영상 포스터 | 허용 | 허용 |
| `ephemeral` (환자) | **없음** — 종류 아이콘 + “Space 로 미리보기” | 메타데이터만 + [미리보기 (Space)] | 허용(명시적 입력만) | 종류(UTType) 아이콘만 |
| `metadata_only` (보안) | 없음 — 종류 SF Symbol | 메타데이터 카드 | **차단** | 없음 |
| dataless(☁︎) | 없음 — 종류 아이콘 + ☁︎ “내려받지 않음”. **썸네일을 만들려고 내려받지 않는다**(FR-CORE-008) | 메타데이터(이름·크기·날짜만) + “iCloud 에만 있음” | 다운로드 확인 대화상자 후에만(§4.3.1) — 사용자가 명시적으로 고른 1개만 | 종류 아이콘만 |
| `/Volumes` 응답 없음 | 자리표시 “응답 없음” | 〃 | 차단 + 안내 | 종류 아이콘 |

파일 유형별 인스펙터 미리보기(`full` 기준, CONTEXT 턴1 표):

| 유형 | 인스펙터 | Space |
|---|---|---|
| 이미지·스크린샷 | 큰 썸네일, 픽셀 크기 | QL 원본 확대 |
| PDF | 첫 페이지 썸네일, 페이지 수 | QL 페이지 넘김 |
| Word·PPT·Excel·Keynote 등 | QL 썸네일 | QL 문서 미리보기 |
| 동영상 | 포스터 프레임 + 재생 시간, [재생] 시 인스펙터 안 `VideoPlayer`(음소거 시작) | QL 재생 |
| ZIP 등 압축 | 압축 크기, (core 가 제공하면) 내부 목록 상위 20개 | QL(시스템이 지원하는 범위) |
| 소스 코드 | 앞 200줄 고정폭 텍스트(문법 강조 없음, 256KB 이하) | QL 텍스트 |
| Markdown | 렌더링(`AttributedString(markdown:)`, 256KB 이하) | QL 텍스트 |
| DMG·PKG | 아이콘, 크기, 제안 이유(“같은 이름의 앱이 설치되어 있습니다”) | QL(시스템 기본) |
| 앱 | 앱 아이콘, 버전, 크기, 마지막 사용일 | — |
| 폴더 | 하위 항목 수·용량·상위 1단계 목록 | QL(폴더 정보) |

## 7. 배너·오류·빈 상태 카탈로그

### 7.1 오류 코드 → 화면

| code | 위치 | 문구(요지) | 동작 |
|---|---|---|---|
| `E_NOT_INITIALIZED` | 전역 | — | 온보딩으로 |
| `E_LOCKED` | 배너(자동 재시도 후) | “다른 작업(예약 스캔 등)이 진행 중입니다. 잠시 후 다시 시도하세요.” | [다시 시도] |
| `E_PROTECTED` | 말풍선 | §5.3 | 항목 재조회 |
| `E_INVALID_STATE` | 토스트 | “다른 곳에서 이미 처리된 항목입니다.” | 재조회 |
| `E_STALE` / `E_NOT_FOUND` | 항목 | “파일이 사라졌거나 바뀌었습니다.” | `.gone` |
| `E_PATH_OUTSIDE_ROOTS` | 선택기 | “이 위치로는 이동할 수 없습니다.” | 다시 선택 |
| `E_DEST_EXISTS` | 대화상자(undo) | “같은 이름의 파일이 있습니다.” | 이름 바꿔 복원/건너뛰기 |
| `E_APPROVAL_MISMATCH` | 계획 시트 | “계획이 바뀌었습니다. 다시 확인하세요.” | 새로고침 |
| `E_APPROVAL_REQUIRED` / `E_APPROVAL_DENIED` | 계획 시트 | “승인되지 않았습니다.” | — |
| `E_ARCHIVE_TARGET_MISSING` | 계획 시트/보관 결정 | `archive.root` 가 비어 있으면 “보관 폴더가 설정되지 않았습니다.”, 설정돼 있으면 “보관 폴더({display_path})에 접근할 수 없습니다. 외장 디스크가 연결되어 있는지 확인하세요.” | [보관 폴더 설정…] → 설정 > 보관 |
| `E_AI_DISABLED` | AI 분류 버튼·설정 | §4.13.1 의 조건 중 빠진 것을 그대로 표시(“외부 전송 허용이 꺼져 있습니다” / “API 키가 없습니다”) | 설정 > AI |
| `E_TCC_DENIED` | 배너 | “macOS 개인정보 보호 설정 때문에 일부 폴더에 접근하지 못했습니다.” | [권한 설정 열기] |
| `E_VOLUME_TIMEOUT` | 배너 | “외장 볼륨이 응답하지 않습니다. 전체 디스크 접근 권한을 확인하세요.” | [권한 설정 열기] |
| `E_VOLUME_UNAVAILABLE` | 배너 | “외장 볼륨이 연결되어 있지 않습니다.” | — |
| `E_TOOL_MISSING` | 정보 배너 | “{도구} 가 없어 일부 기능을 건너뛰었습니다.” | — |
| `E_CONFIG_INVALID` | 설정 필드 | `error.message` | 이전 값 복원 |
| `E_PARTIAL` | 완료 리포트 | 연산별 결과 | — |
| `E_UNDO_IMPOSSIBLE` | 대화상자 | “휴지통이 비워져 되돌릴 수 없습니다.” | — |
| `E_DB_MIGRATION` / `E_DB_CORRUPT` | 전체 화면 | §4.15 | — |
| `E_INTERNAL` | 토스트 | “예상하지 못한 오류가 발생했습니다(요청 req_…).” | [로그 폴더 열기] |
| CoreClient 시간 초과 | 토스트 | “정리 엔진이 응답하지 않습니다. 다시 연결합니다.” | 자동 재기동(09 §4.5) |

`error.message` 는 core 의 한국어 문구이므로 위 표에 없는 코드는 `message` 를 그대로 표시한다. 분기는 항상 `code` 로.

### 7.2 경고(`warnings`) → 배너

| code | 배너 |
|---|---|
| `W_TCC_DENIED` | “일부 폴더에 접근 권한이 없어 건너뛰었습니다.” [권한 설정 열기] |
| `W_ROOT_UNAVAILABLE` | “{display_path} 이(가) 응답하지 않아 건너뛰었습니다.” (외장이면 FDA 안내 포함) |
| `W_PERMISSION_SKIPPED` | 정보: “읽을 수 없는 파일 N개를 건너뛰었습니다.” |
| `W_DATALESS_SKIPPED` | 정보: “iCloud 에만 있는 파일 N개는 내려받지 않고 이름만 확인했습니다.” |
| `W_PROTECTED_SKIPPED` | 그룹 행/토스트: §5.3 마지막 줄 |
| `W_TOOL_MISSING` | 정보: 도구별 |
| `W_FIELD_KEY_UNAVAILABLE` | “암호화 키를 읽지 못해 메모 등 일부 정보를 표시할 수 없습니다.” |
| `W_DEVICE_MISMATCH` (`core.doctor`) | 닫을 수 없는 경고 배너(해결 전까지): “이 데이터는 다른 Mac 에서 복사된 것 같습니다(기기 ID 불일치 또는 등록된 폴더 없음). DayClose 는 Mac 마다 따로 설치합니다.” [설정 > 스캔 위치] [상태 폴더 열기]. 결정: 앱은 자동 복구하지 않는다(어느 쪽이 맞는지 사용자만 앎). 결정 입력은 막지 않되 M5 의 [승인하고 실행] 은 이 경고가 있는 동안 비활성 — 다른 기기 경로로 계획이 실행되는 것을 막기 위함 |
| `W_PARTIAL_SCAN`, `W_TRUNCATED` | 정보 |
| `W_CONFIG_UNKNOWN_KEY`, `W_HASH_SKIPPED_LARGE` | 표시 안 함(설정 > 고급 진단에만) |

배너 규칙: 같은 `code` 는 하나로 합치고 개수 표시, 닫으면 그 리뷰 날짜 동안 다시 띄우지 않음(정보 배너), 권한 배너는 해결될 때까지 사이드바 하단에 축약 표시.

## 8. 이월·보류 표시 규칙 요약

- 이월 항목은 core 가 오늘 그룹에 재배정한다(06 §4.2). 앱은 별도 “이월” 섹션을 만들지 않고 그룹 안에서 “N일째” 배지 + 그룹 행 “이월 N” 배지 + 필터로 보여준다.
- `stats.carried_over` 는 보조 지표 줄, 클릭 시 모든 그룹에 “이월” 필터를 건 목록(`item.list {"open": true}` 중 `carry_count ≥ 1`).
- 보류(`deferred_until > review_date`)는 오늘 그룹에 나타나지 않고 “보류 중” 사이드바에만. 보류 만료일에 core 가 다시 이월 대상으로 올린다.
- `keep_always` 로 조용히 유지된 항목은 화면에 나오지 않고 “조용히 유지 N” 숫자로만(FR-DR-008).
- 실행 대기(decided, 계획 전)는 날짜와 무관하게 “실행 대기” 에 남는다.

## 9. 메뉴바 (M7) — `MenuBarContentView`

메뉴바 아이콘 라벨: 미결 항목 수 > 0 이면 `☐ 12`(SF Symbol `tray.full` + 숫자), 0 이면 `checkmark.circle` 만, 권한 경고가 있으면 아이콘에 작은 느낌표 배지(`exclamationmark.triangle`). 숫자 출처: 앱이 가진 마지막 `review.summary` 의 `stats.items_open`(갱신 규칙 09 §9).

```
┌ DayClose ─────────────────────────┐
│ 11월 24일 (화) 결산                 │
│ 정리할 항목 12개 · 예상 1분           │
│ 휴지통 예정 6개 · 1.2 GB             │
│ ⚠ 전체 디스크 접근 권한이 없습니다 ›   │
│ ───────────────────────────────── │
│ [지금 검토]                  ⌘⏎    │
│ 지금 스캔                           │
│ 마지막 스캔: 21:03 (예약)            │
│ ───────────────────────────────── │
│ 설정…                        ⌘,    │
│ DayClose 종료                ⌘Q    │
└───────────────────────────────────┘
```

- [지금 검토] → 메인 창 열기/앞으로 + 오늘의 결산.
- 지금 스캔 → `scan.run --trigger app`, 진행 중이면 “스캔 중… 파일 확인” 으로 바뀜.
- 파일 이름·경로는 메뉴바에 표시하지 않는다(화면 공유·어깨너머 노출 최소화).
- 보안 critical 발견 사항이 있으면 한 줄 “보안 점검: 심각 1건 ›” → Security Health.

## 10. 일일 알림 (M7) — 문구와 동작

등록·권한·발송 주체는 09 §8. 화면 문구:

| 경우 | 제목 | 본문 | 동작 |
|---|---|---|---|
| 기본 | DayClose | “오늘도 수고하셨습니다. 오늘 생성된 파일 {new_files}개와 수정된 파일 {modified_files}개를 검토했습니다. 정리할 항목 {items_open}개가 있습니다. 예상 검토 시간: {estimated_review_minutes}분” (FR-MI-003) | [지금 검토] [나중에] |
| 정리할 항목 0 | — | 알림을 보내지 않는다(결정: 매일 “없음” 알림은 소음). 메뉴바만 ✓ | — |
| 권한 문제(`W_TCC_DENIED`/`W_ROOT_UNAVAILABLE`/`E_VOLUME_TIMEOUT`) | DayClose — 확인 필요 | “예약 정리 중 일부 폴더에 접근하지 못했습니다. 전체 디스크 접근 권한을 확인해 주세요.” (기본 알림 본문 뒤에 붙이지 않고 별도 1건, 하루 1회) | [설정 열기] |
| 보안 critical 신규 | DayClose — 보안 점검 | “새로 확인이 필요한 보안 항목이 {n}건 있습니다.” | [지금 검토] |
| 스캔 실패 | DayClose | “오늘 결산을 만들지 못했습니다. 앱을 열어 확인해 주세요.” | [지금 검토] |

- [지금 검토]: 앱 실행/활성 + 알림의 `review_date` 로 결산 화면. [나중에]: 1시간 후 같은 알림 1회 재발송(그날 최대 1회). 알림을 그냥 닫으면 재발송 없음.
- 알림 본문에 파일 이름·경로·자산 이름을 넣지 않는다(잠금 화면 노출).

## 11. 접근성

| 항목 | 규칙 |
|---|---|
| 키보드 | 모든 기능을 마우스 없이(§5). 포커스 링 항상 표시. 사각 드래그 선택의 키보드 대안 = ⇧+방향키 범위 선택 |
| VoiceOver 레이블 | 항목 셀: “{이름}, {종류}, {크기}, 제안 {동작}, {결정 또는 ‘결정 안 됨’}, {N일째}, {보호 문구}”. 보안 자산 이름은 “마스킹된 이름, {종류 문구}”. 썸네일 이미지는 장식(`accessibilityHidden`) — 정보는 레이블에 |
| 동작 | 셀마다 `accessibilityAction(named:)` 유지/휴지통/보관/이동/보류/항상 유지(허용된 것만) |
| 로터 | “미결 항목”, “이월 항목”, “보호 항목” `accessibilityRotor` |
| 공지 | 결정 저장·차단·스캔 완료는 `AccessibilityNotification.Announcement` |
| 색 | 결정·심각도는 아이콘+문구+색. 색맹 시뮬레이션(Xcode Accessibility Inspector)로 확인 |
| 대비·크기 | 시스템 “대비 증가”, “투명도 줄이기” 존중. 글자 크기는 시스템 텍스트 스타일(`.body` 등)만 써서 확대 설정에 따라감 |
| 동작 줄이기 | “동작 줄이기” 켜면 자동 진행 애니메이션·토스트 슬라이드 없음 |
| 시간 제한 | 토스트의 [실행 취소]는 ⌘Z 로 시간 제한 없이 가능(토스트가 사라져도) |

## 12. 성능 목표 (UI)

| 항목 | 목표 | 근거 |
|---|---|---|
| 키 입력 → 화면 반영 | ≤ 16ms(낙관적 갱신) | §3.4 |
| `review.summary`, `item.list`(200) 응답 | p95 ≤ 300ms | NFR-PERF-002 |
| 200장 갤러리 스크롤 | 60fps 목표, 썸네일 지연 생성·화면 밖 요청 취소 | FR-VR-002 |
| 앱 기동 → 메인 표시 | ≤ 1.5s (core 기동 포함) | — |

UI 테스트(11 문서가 목록 확정): 마우스 없이 그룹 하나 전체 판단, 보호 항목 D 키 무시+안내, ⌘Z 3단계, 보안 자산 열람 후 캐시 디렉터리 파생물 0(FR-VR-006), 이월 배지, 승인 버튼 해시 일치(M5). UI 테스트는 `--home <sandbox>/home --sandbox <sandbox>` 인자로 샌드박스 데이터만 사용(09 §2.3).

## 13. 다른 문서에 대한 요구 (10/04/05/07/08)

이 화면들이 동작하려면 아래가 필요하다. 해당 문서가 채택하거나 거부하고, 거부 시 이 문서를 고친다.

| # | 대상 | 요구 |
|---|---|---|
| R1 | 10 | `review.summary.data` 에 `estimated_review_minutes`(FR-DR-001 공식, 06 stats_json 키 목록에 없음), `pending_plan{item_count,bytes}`, `last_scan{run_id,finished_at,status,warning_codes}`, 그룹별 `open_count/decided_count/bytes/protected_count/carried_count/uniform_suggestion` |
| R2 | 10 | `review.summary --review-date` 과거 날짜에 세션이 없을 때 새로 만들지(이월 처리까지) 여부. UI 는 “만들지 않고 `E_NOT_FOUND`” 를 기대 |
| R3 | 10 | `item.list` 에 보류 필터(`--deferred`)와 이월 필터. 없으면 앱이 `--open` 전체를 받아 클라이언트 필터 |
| R4 | 10/04 | 항목 JSON 에 불허 이유(`blocked_reasons: {"trash": "icloud_drive", …}`)와 `is_dataless`/`origin_root_kind`. 없으면 §5.3 의 추론 문구 사용, dataless 는 앱이 직접 판정(09 §5.0) |
| R5 | 10/05 | 발견 사항 `open → acknowledged` 를 일으키는 명령(예: `vault.acknowledge FINDING_ID`)이 02 §5.3 에 없음. 06 §4.6 에는 상태가 있음 |
| R7 | 10 | 로그인 항목 목록 명령 없음(`inventory_login_items` 는 있음). 앱은 `item.list --category login_item` 으로 대체 |
| R8 | 08 | `app_button` 승인의 사람 확인 보강(09 §11.3 의 제안) 채택 여부 |
| R9 | 07/10 | AI 키를 Keychain(`com.dayclose.ai`)에 넣는 core 명령(예 `ai.key.set PROVIDER`, 키는 stdin/요청 본문으로만, 응답·로그·감사에 값 없음)과 `ai.status` 의 `key_present`·`blocked_reason`. 앱이 직접 만들면 Python `keyring` 이 읽을 때 키체인 접근 허용 대화상자가 뜸(09 §11.4). 명령이 생기기 전까지 §4.13.1 의 임시 안내 사용 |
| R10 | 10 | `decision.set --group` 이 (a) 이미 개별 결정된 항목을 덮어쓰는지, (b) 그 동작을 허용하지 않는 `active_repo`·iCloud 항목을 건너뛰고 `W_PROTECTED_SKIPPED` 를 주는지. UI 는 (a) 덮어쓰지 않음, (b) 건너뜀을 기대 |
| R11 | 10 | `decision.set` 응답 `data.items` 에 갱신된 항목 JSON 전체, 건너뛴 항목 `skipped[{item_id, reason_code}]` |
| R12 | 10 | `plan.create/show` 연산에 표시용 `display_name/src_display/dst_display/creates_dirs`, `excluded[]` |
| R13 | 05/10 | `vault.health` 에 통과한 점검(`checks[]`)과 카드 문구(`title/message/recommendation`) |
| R14 | 10 | `scan.run` 취소 수단(stdio 에서 진행 중 요청 취소). 없으면 앱은 스캔 취소를 제공하지 않는다 |
