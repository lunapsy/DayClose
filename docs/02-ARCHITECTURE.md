# 02 — 아키텍처 (ARCHITECTURE)

> 상태: 기준 문서(contract). 03~13 문서는 이 문서와 `06-DATA-MODEL.md`의 이름·경로·코드를 그대로 써야 한다.
> 변경하려면 이 문서를 먼저 고치고, 영향받는 문서를 같은 커밋에서 맞춘다.

## 1. 한 장 요약

```
            ┌─────────────────────────── 사용자 ───────────────────────────┐
            │                                                              │
   DayClose.app (SwiftUI, M4~)     터미널 CLI       Claude Code/Codex Skill, MCP (M8)
            │  stdio JSON-lines          │ argv + --json          │ argv + --json / MCP stdio
            └──────────────┬─────────────┴───────────┬────────────┘
                           ▼                         ▼
                 ┌──────────────── dayclose core (Python) ────────────────┐
                 │ transport: cli / serve(stdio) / mcp                     │
                 │ api: 명령 레지스트리 (item.list, plan.apply …)           │
                 │ ────────────────────────────────────────────────────── │
                 │ collect   intel   vault   policy   review   plan   ai  │  ← 읽기/판단 (파일 변경 없음)
                 │ ────────────────────────────────────────────────────── │
                 │ executor  (유일하게 사용자 파일을 변경하는 모듈)          │  ← 승인된 plan만
                 │ store (SQLite, migrations)   common (errors, log, paths)│
                 └─────────────────────────────────────────────────────────┘
                           │                         │
                ~/Library/Application Support/DayClose     사용자 파일 (scan roots)
```

- **엔진은 하나(Python core)**, UI·에이전트는 모두 같은 명령 계약(§5)을 통해서만 엔진을 쓴다.
- **판단과 실행의 분리**: `collect/intel/vault/policy/review/plan/ai` 는 사용자 파일을 읽기만 한다. 사용자 파일을 이동·이름변경·휴지통 처리할 수 있는 코드는 `executor` 하나뿐이며, `executor` 는 승인(`approvals`)이 붙은 `plan` 만 실행한다.
- **상주 데몬 없음**: 모든 호출은 짧은 프로세스. 예약 실행은 launchd(M7), 앱 세션 동안만 장수명 자식 프로세스(`dayclose serve --stdio`, M4).

## 2. 설계 원칙 → 구조적 장치

| 원칙 (CONTEXT 턴1·턴4) | 구조적 장치 |
|---|---|
| Local-first | 모든 상태는 로컬 SQLite 1개 파일. 네트워크 호출은 `ai`(옵트인)에만 존재. 보관(`archive`)도 로컬/외장 폴더로만. |
| AI optional | `ai` 모듈 없이 전체 플로우 동작. `ai.enabled=false` 가 기본값. 제안은 `heuristic`/`rule` 출처로도 생성. |
| Human-in-the-loop | 파일 변경 = `plan` → `approval`(사람만 생성 가능) → `executor`. 우회 경로 없음. |
| Reversible | 영구 삭제 연산이 엔진에 존재하지 않음(“삭제”=휴지통 이동). 모든 연산은 `plan_operations` 에 사전 기록 후 실행, `undo` 지원. |
| Incremental | `file_entries` 현재 상태 + `file_events` 변경 로그. 스캔은 (dev, inode, size, mtime_ns) 비교로 변경분만 기록. |
| Privacy-first | `sensitivity` 등급이 AI 전송·로그·미리보기·캐시를 일괄 통제(§9, 06 문서 §6). |
| Agent-ready | CLI 전 명령이 `--json` 봉투(envelope)를 출력. 같은 핸들러를 stdio 서버·MCP가 재사용. |
| 보안·복구 설계 선행 (턴4) | 보호 정책(`policy`)은 M2, 실행 엔진 계약·저널·샌드박스 가드는 M1부터 코드에 존재(§10). |

## 3. 기술 선택

| 영역 | 선택 | 이유 |
|---|---|---|
| Core 언어 | Python ≥3.13 (개발 기준 3.14) | 1단계 결정 사항. 파일 스캔·SQLite·서브프로세스(git/brew/gitleaks) 오케스트레이션에 충분. |
| 패키지/실행 | `uv` (`core/pyproject.toml`, `uv.lock`) | 이 머신에 설치됨. 재현 가능한 잠금, `uv run`/`uv tool install` 로 CLI 배포. |
| CLI 파서 | 표준 `argparse` | 결정: 기동 시간(앱이 프로세스를 자주 띄움)과 의존성 최소화. typer/click 의 import 비용 회피. |
| DB | SQLite (표준 `sqlite3`), WAL 모드 | 단일 사용자·단일 기기, 서버 불필요. 백업=파일 복사. |
| 설정 | TOML (`tomllib` 읽기, `tomli-w` 쓰기) | 사람이 직접 고칠 수 있는 포맷. |
| 암호화(필드) | `cryptography` AES-256-GCM | 민감 필드 암호화(06 §6). X.509 인증서 파싱도 같은 라이브러리로 처리 → `openssl` CLI 불필요. |
| 키 보관 | macOS Keychain via `keyring` | 키를 argv/파일에 노출하지 않음(`security -w` 는 argv 노출 위험). |
| 비밀 탐지 | `gitleaks` (Homebrew, 선택) + 자체 패턴 | CONTEXT 턴2. 없으면 자체 패턴만으로 동작하고 경고 `W_TOOL_MISSING`. |
| UI | SwiftUI (macOS 26), Swift 6 strict concurrency | 2단계 결정 사항. QuickLook·QuickLookThumbnailing·AVKit 네이티브 사용. |
| Swift 공용 로직 | SwiftPM 패키지 `DayCloseKit` | `swift test` 로 계약 디코딩·클라이언트 로직을 Xcode 없이 검증. |
| OCR (M6) | Apple Vision, 소형 Swift CLI `dayclose-native` | Vision 은 Swift/ObjC 전용. core 는 이 헬퍼를 서브프로세스로 호출해 JSON을 받음. |
| 스케줄 (M7) | launchd + `SMAppService` (앱 번들 내 LaunchAgent) | TCC 권한을 앱 번들 하나에 귀속시키기 위함(§11). |
| 알림 (M7) | UserNotifications (앱/헬퍼 측) | core 는 알림을 직접 띄우지 않음. |

### 의존성 목록

Core 런타임: `cryptography`, `keyring`, `tomli-w`. 그 외는 표준 라이브러리(`sqlite3`, `argparse`, `json`, `hashlib`, `plistlib`, `subprocess`, `fcntl`, `logging`).
Core 개발: `pytest`, `ruff`, `mypy`.
외부 도구(있으면 사용, 없으면 기능 축소 + 경고): `git`, `brew`, `gitleaks`, `mdls`, `defaults`, `osascript`.
Swift: 서드파티 의존성 없음. 시스템 프레임워크만.
`age` 는 쓰지 않는다(2026-11-24: NAS·원격 암호화 백업이 범위에서 빠짐).

라이선스(2026-11-24 확정): 저장소는 **MIT**(`LICENSE`, © 2026 Lunap Lee, 공개 저장소 `lunapsy/DayClose`). 따라서 GPL/AGPL 등 카피레프트 코드는 저장소에 복사·벤더링·링크하지 않는다. 그런 도구는 **별도 설치된 외부 실행파일로 호출**만 한다(`run_tool`). MIT/BSD/Apache-2.0 코드는 출처·라이선스 표기를 남기고 가져올 수 있다(13 문서가 프로젝트별 판정).

새 런타임 의존성 추가는 이 목록을 고치는 PR 로만 한다(AGENTS.md).

## 4. 결정: UI ↔ Core 계약과 장기 구조

**결정: Swift 앱은 장기적으로도 Python core 를 자식 프로세스로 호출한다. core 를 Swift 로 포팅하지 않는다.**
이유: 파일 변경·보호 정책·undo 는 안전이 걸린 로직이라 구현이 둘이 되면 안 된다. 하나의 엔진, 하나의 테스트 스위트로 유지하고, Swift 는 네이티브만 할 수 있는 일(미리보기, 썸네일, 알림, 메뉴바, 권한 획득)만 맡는다.

전송(transport)은 두 가지이며 **같은 명령 핸들러와 같은 봉투**를 쓴다.

| 전송 | 사용처 | 형태 |
|---|---|---|
| CLI | 터미널, Skill, launchd, 테스트 | `dayclose <noun> <verb> [flags] --json` → stdout 에 봉투 1개, stderr 에 진행 이벤트(NDJSON, 옵션) |
| stdio 서버 (M4) | DayClose.app 세션 | `dayclose serve --stdio` 장수명 자식 프로세스. 한 줄 = 요청 JSON 하나, 한 줄 = 응답 봉투 하나 |
| MCP (M8) | 에이전트 | `dayclose mcp serve` — MCP tool 하나당 api 명령 하나. 단, 승인 관련 명령은 노출하지 않음(§10.3) |

결정: 로컬 소켓/HTTP 서버는 만들지 않는다. 이유: 포트·인증·데몬 수명관리·TCC 귀속 문제가 생기고, stdio 는 부모 프로세스(앱)가 죽으면 같이 정리된다.
결정: 앱은 키 입력마다 프로세스를 띄우지 않도록 M4 부터 `serve --stdio` 를 쓴다. 이유: Python 기동 100~200ms 가 K/D 연타 UX 를 해친다.
재검토 조건: `serve --stdio` 의 p95 응답이 `item.list`(200건) 기준 300ms 를 넘으면 그때 병목 지점만 최적화(인덱스·쿼리)하고, 포팅은 여전히 하지 않는다.
결정(2026-11-24): Developer ID 서명·공증은 하지 않는다. 개인 로컬 빌드만. 결과: TCC(전체 디스크 접근 포함)는 코드 서명의 designated requirement 로 앱을 식별하므로, ad-hoc 서명(`codesign -s -`) 빌드는 재빌드마다 cdhash 가 바뀌어 FDA 승인이 풀릴 수 있다. 대응: 앱·스케줄러 헬퍼를 **항상 같은 로컬 서명 인증서**(Xcode 의 무료 “Apple Development” 인증서, 없으면 키체인 접근에서 만든 자체 서명 코드 서명 인증서)로 서명해 designated requirement 를 고정한다. 재빌드 후 FDA 유지 여부는 M7 에서 실기기 검증 항목(09 문서).
결정: core 배포는 M3까지 `uv tool install --editable ./core`(→ `~/.local/bin/dayclose`). 앱은 설정 `core.command`(기본 `~/.local/bin/dayclose`)로 찾는다. 앱 번들에 Python 런타임을 동봉할지는 M7 에서 결정(12 문서).

## 5. 명령 계약 (CLI 표면 + JSON 봉투)

### 5.1 명명 규칙

- CLI: `dayclose <noun> <verb>`. 명령 ID(봉투의 `command`, stdio/MCP 의 이름): `<noun>.<verb>`. 예: `dayclose plan apply` ↔ `plan.apply`.
- 플래그는 kebab-case(`--review-date`), JSON 인자는 snake_case(`review_date`). 1:1 대응.
- 외부로 노출되는 ID 는 접두사 문자열: `run_12`, `ent_9031`, `evt_77`, `itm_128`, `grp_12`, `dec_40`, `pln_7`, `op_33`, `apv_7`, `ast_5`, `fnd_9`, `prj_3`, `app_21`, `pkg_8`, `rul_2`, `sup_4`, `ses_15`, `root_1`. DB 는 INTEGER PK(06 문서). 변환은 `common/ids.py` 한 곳에서.
- 시간: JSON 에서는 RFC 3339 UTC(`2026-11-24T12:03:11.402Z`), 날짜는 로컬 `YYYY-MM-DD`(`review_date`).
- 경로: 절대경로 문자열. 홈 축약(`~`)은 표시용 필드 `display_path` 에만.

### 5.2 전역 플래그

| 플래그 | 의미 |
|---|---|
| `--json` | 봉투 출력. 앱·Skill·테스트는 항상 지정. 미지정 시 사람용 텍스트(같은 데이터). |
| `--home PATH` | 상태 디렉터리 재지정(= `DAYCLOSE_HOME`). 테스트 필수. |
| `--progress ndjson` | 장시간 명령(`scan.run`, `plan.apply`)이 stderr 로 진행 이벤트 출력. |
| `--wait-lock SEC` | 쓰기 잠금 대기 시간(기본 10). 초과 시 `E_LOCKED`. |
| `--channel cli\|app\|skill\|mcp\|schedule` | 호출 출처(감사 로그용). 기본 `cli`. 앱은 `app`, Skill 은 `skill`. |
| `--log-level debug\|info\|warn\|error` | 기본 `info`. |

### 5.3 명령 목록 (v1)

마일스톤(M#)은 처음 구현되는 시점. 표시 `W` = 쓰기 잠금 필요(DB 변경), `F` = 사용자 파일 변경.

| 명령 ID | CLI 시그니처 | M | 비고 |
|---|---|---|---|
| `core.version` | `dayclose version` | M1 | core/스키마/계약 버전 |
| `core.init` | `dayclose init [--device-name NAME] [--no-default-roots]` | M1 | W. 홈 디렉터리·DB·설정 생성(필드 암호화 키는 M2 부터 생성). 멱등. |
| `core.doctor` | `dayclose doctor` | M1 | 외부 도구, 권한(TCC/FDA 프로브), 루트 접근성, DB 무결성 |
| `core.schema` | `dayclose schema [COMMAND_ID]` | M2 | 명령별 `data` JSON Schema 출력(에이전트용) |
| `config.get` / `config.set` / `config.list` | `dayclose config get KEY` / `set KEY VALUE` / `list` | M1 | set 은 W |
| `root.list` / `root.add` / `root.remove` | `dayclose root add PATH --kind KIND [--max-depth N]` / `remove ROOT_ID` | M1 | W. KIND = `scan_root_kind` |
| `scan.run` | `dayclose scan run [--root ROOT_ID]... [--collectors fs,git,vault,apps,brew,login_items] [--trigger manual\|schedule\|app\|agent]` | M1 | W. 기본 collectors = 해당 마일스톤까지 구현된 전부 |
| `scan.list` / `scan.show` | `dayclose scan list [--limit N]` / `scan show RUN_ID` | M1 | |
| `change.list` | `dayclose change list [--run RUN_ID \| --since RFC3339] [--event created,modified,deleted,moved] [--root ROOT_ID] [--limit N] [--cursor C]` | M1 | |
| `review.summary` | `dayclose review summary [--review-date DATE]` | M2 | W(세션 열기·이월 처리). 일일 결산 지표 + 그룹 목록 |
| `review.close` | `dayclose review close [--review-date DATE]` | M2 | W |
| `group.list` / `group.show` | `dayclose group list [--review-date DATE]` / `group show GROUP_ID` | M2 | |
| `item.list` | `dayclose item list [--group GROUP_ID] [--state S,...] [--category C,...] [--review-date DATE] [--open] [--limit N] [--cursor C]` | M2 | `--open` = 미결 항목(이월 포함) |
| `item.show` | `dayclose item show ITEM_ID` | M2 | 이력·결정·연산 포함 |
| `decision.set` | `dayclose decision set (ITEM_ID... \| --group GROUP_ID) --action ACTION [--dest PATH] [--note TEXT] [--defer-until DATE]` | M2 | W. 파일 변경 없음 |
| `decision.undo` | `dayclose decision undo (ITEM_ID... \| --last)` | M2 | W. `planned` 이전까지만 |
| `decision.list` | `dayclose decision list [--since DATE] [--limit N]` | M2 | |
| `vault.list` / `vault.show` / `vault.health` | `dayclose vault list [--kind K] [--status S]` / `vault show ASSET_ID` / `vault health` | M3 | 읽기 전용 |
| `vault.annotate` | `dayclose vault annotate ASSET_ID [--label TEXT] [--note TEXT] [--expires DATE] [--backup verified\|none\|unknown]` | M3 | W. 암호화 필드. `--backup` 이 `backup_status` 의 유일한 갱신 경로(PRD §9 O2) |
| `app.list` | `dayclose app list [--new] [--removed]` | M3 | |
| `package.list` | `dayclose package list [--manager brew_formula\|brew_cask] [--new]` | M3 | |
| `project.list` | `dayclose project list [--active]` | M2 | git 저장소/프로젝트 |
| `report.daily` | `dayclose report daily [--review-date DATE] [--format json\|md]` | M2 | |
| `rule.list` / `rule.add` / `rule.remove` | `dayclose rule add --kind KIND --pattern P --protection CLASS [--sensitivity S]` | M2 | W. 보호 규칙 |
| `suppression.list` / `suppression.remove` | `dayclose suppression remove SUP_ID` | M2 | W. “다시 묻지 않기” 해제 |
| `plan.create` | `dayclose plan create (--items ITEM_ID,... \| --all-decided)` | M5 | W. `draft` plan + `plan_hash` |
| `plan.show` / `plan.list` | `dayclose plan show PLAN_ID` / `plan list [--state S]` | M5 | |
| `plan.approve` | `dayclose plan approve PLAN_ID --hash PLAN_HASH` | M5 | W. 사람 확인 필수(§10.3) |
| `plan.apply` | `dayclose plan apply PLAN_ID [--dry-run]` | M5 | W, F |
| `plan.cancel` | `dayclose plan cancel PLAN_ID` | M5 | W |
| `plan.undo` | `dayclose plan undo PLAN_ID [--op OP_ID]... [--on-conflict fail\|rename]` | M5 | W, F |
| `plan.recover` | `dayclose plan recover` | M5 | W. 중단된 연산 정합성 복구(08 문서) |
| `audit.list` | `dayclose audit list [--since DATE] [--limit N]` | M5 | |
| `policy.suggestions` / `policy.accept` / `policy.reject` | `dayclose policy suggestions` / `accept RULE_ID` / `reject RULE_ID` | M6 | 학습 규칙 제안(07 문서) |
| `ai.status` / `ai.classify` | `dayclose ai status` / `ai classify [--review-date DATE]` | M6 | 옵트인 |
| `core.serve` | `dayclose serve --stdio` | M4 | 전송 계층 |
| `mcp.serve` | `dayclose mcp serve` | M8 | 전송 계층 |

ACTION(= `decision_action` enum, 06 문서): `keep`, `keep_always`, `trash`, `move`, `archive`, `defer`, `acknowledge`. 어떤 항목에 어떤 ACTION 이 허용되는지는 항목 JSON 의 `allowed_actions` 가 유일한 기준이다(§5.6).

### 5.4 봉투(envelope)

성공:

```json
{
  "schema": "dayclose.v1",
  "command": "scan.run",
  "ok": true,
  "data": {
    "run_id": "run_12",
    "status": "completed",
    "stats": {"roots": 4, "entries_seen": 18234, "created": 42, "modified": 18, "deleted": 3, "moved": 2, "skipped_unreadable": 1},
    "duration_ms": 2381
  },
  "warnings": [
    {"code": "W_PERMISSION_SKIPPED", "message": "읽을 수 없는 하위 경로 1개를 건너뛰었습니다.", "details": {"count": 1}}
  ],
  "error": null,
  "meta": {"request_id": "req_01JD6Q…", "core_version": "0.1.0", "contract_version": 1, "db_schema_version": 1, "device_id": "dev_5f2c…", "duration_ms": 2390}
}
```

실패:

```json
{
  "schema": "dayclose.v1",
  "command": "plan.apply",
  "ok": false,
  "data": null,
  "warnings": [],
  "error": {
    "code": "E_APPROVAL_REQUIRED",
    "message": "승인되지 않은 계획은 실행할 수 없습니다.",
    "details": {"plan_id": "pln_7", "plan_state": "draft"},
    "retryable": false
  },
  "meta": {"request_id": "req_01JD6R…", "core_version": "0.1.0", "contract_version": 1, "db_schema_version": 5, "device_id": "dev_5f2c…", "duration_ms": 14}
}
```

규칙:
- stdout 에는 **봉투 1개만** 출력한다(`--json` 일 때). 그 외 출력은 전부 stderr.
- `ok=false` 이면 `data=null`, `error` 필수. `ok=true` 이면 `error=null`.
- `message` 는 한국어 사용자 문구, 분기 로직은 반드시 `code` 로 한다.
- `details` 에 비밀값·파일 내용을 넣지 않는다. 보안 자산/환자 자료 경로는 `item_id`/`asset_id` 로만 참조한다.
- 목록 응답: `data = {"items": [...], "next_cursor": "opaque" | null, "total": 123}`.
- 봉투에 필드를 **추가**하는 것은 하위 호환, 이름 변경·삭제·의미 변경은 `contract_version` 을 올린다(§12).

stdio 서버 요청 형식(M4):

```json
{"id": "42", "command": "decision.set", "args": {"item_ids": ["itm_128", "itm_129"], "action": "trash"}, "channel": "app"}
```
응답은 위 봉투에 `"id": "42"` 를 추가한 한 줄. 진행 이벤트는 `{"id":"42","event":"progress",...}` 줄로 응답 전에 올 수 있다.

진행 이벤트(NDJSON, stderr 또는 stdio):

```json
{"event": "progress", "command": "scan.run", "phase": "fs", "root_id": "root_1", "done": 5120, "total": null, "ts": "2026-11-24T12:03:09.001Z"}
```
`phase` 값: `fs`, `git`, `vault`, `apps`, `brew`, `login_items`, `review`, `apply`, `undo`.

### 5.5 종료 코드

| 코드 | 의미 | 대표 error.code |
|---|---|---|
| 0 | 성공(경고 포함 가능) | — |
| 2 | 사용법 오류 | `E_USAGE` |
| 3 | 대상 없음 | `E_NOT_FOUND`, `E_NOT_INITIALIZED` |
| 4 | 상태 충돌 | `E_INVALID_STATE`, `E_STALE`, `E_DEST_EXISTS`, `E_APPROVAL_MISMATCH` |
| 5 | 안전 정책 거부 | `E_PROTECTED`, `E_APPROVAL_REQUIRED`, `E_APPROVAL_DENIED`, `E_SANDBOX_VIOLATION`, `E_PATH_OUTSIDE_ROOTS`, `E_AI_BLOCKED_SENSITIVE` |
| 6 | 권한/환경 | `E_PERMISSION`, `E_TCC_DENIED`, `E_VOLUME_UNAVAILABLE`, `E_VOLUME_TIMEOUT`, `E_TOOL_MISSING` |
| 7 | 잠금 | `E_LOCKED` |
| 8 | 부분 실패 | `E_PARTIAL` (plan.apply/undo 일부 연산 실패. `data` 는 null 이 아니라 결과를 담는다 — 유일한 예외) |
| 10 | 내부 오류 | `E_INTERNAL`, `E_DB_CORRUPT`, `E_DB_MIGRATION` |

`E_PARTIAL` 예외: `ok=false`, `error.code="E_PARTIAL"`, `data` 에 연산별 결과를 담는다. 소비자는 반드시 `data.operations[*].state` 를 확인한다.

### 5.6 항목(item) JSON — UI·Skill 이 의존하는 핵심 형태

```json
{
  "id": "itm_128",
  "subject_type": "file",
  "category": "screenshot",
  "state": "proposed",
  "path": "/Users/lunap/Desktop/스크린샷 2026-11-24 오후 2.02.11.png",
  "display_name": "스크린샷 2026-11-24 오후 2.02.11.png",
  "display_path": "~/Desktop",
  "size_bytes": 482113,
  "mtime": "2026-11-24T05:02:11.000Z",
  "detected_at": "2026-11-24T12:03:10.220Z",
  "review_date": "2026-11-24",
  "carry_count": 0,
  "deferred_until": null,
  "group_id": "grp_12",
  "protection": "none",
  "sensitivity": "normal",
  "preview_policy": "full",
  "ai_policy": "external_ok",
  "project": {"id": "prj_3", "name": "PL-Agent"},
  "suggestion": {"action": "move", "dest": "/Users/lunap/dev/PL-Agent/screenshots/", "source": "heuristic", "reason": "PL-Agent 작업 시간대에 생성된 스크린샷", "confidence": 0.62},
  "decision": null,
  "allowed_actions": ["keep", "keep_always", "trash", "move", "archive", "defer"],
  "vault": null
}
```

- `allowed_actions` 는 core 의 `policy` 가 계산한다. UI 는 이 목록에 없는 동작을 비활성화하고, core 는 `decision.set` 과 `plan.apply` 에서 **다시** 검증한다(이중 검증).
- `preview_policy`: `full` | `ephemeral`(미리보기 허용, 썸네일 디스크 캐시 금지) | `metadata_only`(내용 미리보기 금지).
- `ai_policy`: `external_ok` | `local_only` | `none`.
- `protection = security_asset` 이면 `display_name` 은 마스킹(`AuthKey_••••••.p8`)되고 `vault` 에 자산 요약이 들어간다.

## 6. 모듈 경계

Python 패키지 `dayclose` (위치 `core/src/dayclose/`). 화살표는 “import 가능” 방향. **역방향 import 금지**(ruff/테스트로 검사, 11 문서).

```
cli, serve, mcp  →  api  →  review, plan, vault, intel, collect, policy, ai, executor
                                  ↓
                          store, config, common
```

| 모듈 | 책임 | 하지 않는 것 | 주 문서 |
|---|---|---|---|
| `common` | 오류 타입, 봉투, ID 변환, 경로 유틸, 시계(테스트 주입), 로깅·마스킹, 필드 암호화 | 비즈니스 로직 | 02, 06 |
| `config` | `config.toml` 로드/검증/저장, 기본값 | DB 접근 | 02 |
| `store` | SQLite 연결, PRAGMA, 마이그레이션, 리포지토리 함수 | 파일시스템 스캔 | 06 |
| `collect` | 수집기: `fs`, `git`, `apps`, `brew`, `login_items`. 변경 이벤트 생성 | 분류·제안 | 04, 09 |
| `intel` | 카테고리 판정, 그룹핑, 중복 탐지(SHA-256), 프로젝트 매칭, 휴리스틱 제안 | AI 호출 | 04 |
| `vault` | 보안 자산 탐지(확장자·매직바이트·내용 패턴·gitleaks), 인증서 파싱, 건강 점검 | 자산 이동 | 05 |
| `policy` | 보호 등급·민감도 계산, `allowed_actions`, 보호 규칙, suppression, (M6) 학습 규칙 | 실행 | 07, 08 |
| `review` | 리뷰 세션, 항목 생성·상태 전이, 결정, 이월, 일일 리포트 | 파일 변경 | 03, 06 |
| `plan` | 결정 → 연산 목록, `plan_hash`, 승인 기록 | 파일 변경 | 08 |
| `executor` | 승인된 plan 실행, 사전조건 재검증, 휴지통/이동, undo, 복구 | 결정·정책 수정 | 08 |
| `ai` (M6) | 공급자 추상화(none/ollama/anthropic/openai), 전송 게이트(마스킹·차단), 요청 감사 | 파일 접근(받은 메타데이터만 다룸) | 07 |
| `api` | 명령 레지스트리, 인자 검증, 잠금 획득, 감사 기록, 봉투 생성 | 전송 형식 | 10 |
| `cli`, `serve`, `mcp` | 전송 계층(argv/stdio/MCP ↔ api) | 로직 | 10 |

규칙:
- 사용자 파일에 대해 `os.rename`, `os.replace`, `shutil.move`, `os.unlink`, `os.remove`, `shutil.rmtree`, `open(..., 'w'|'a')`, `os.chmod`, xattr 쓰기를 호출할 수 있는 곳은 `dayclose/executor/` 뿐이다. 다른 모듈에서 쓰면 `tests/safety/test_no_mutation_outside_executor.py` 가 실패해야 한다(정적 검사, 11 문서).
- DayClose 자신의 상태 파일(`DAYCLOSE_HOME` 아래) 쓰기는 `store`, `config`, `common/logging` 만.
- 서브프로세스 호출은 `common/proc.py` 의 `run_tool(argv, timeout, allow=...)` 만 사용. 허용 도구 목록 고정(`git`, `brew`, `gitleaks`, `mdls`, `defaults`, `osascript`, `dayclose-native`), 셸 미경유(`shell=False`), 타임아웃 필수.
- `ai` 는 `run_tool` 과 `executor` 를 import 할 수 없다. AI 출력은 `suggestion` 필드(데이터)로만 저장되며 명령으로 해석되지 않는다.

Swift 측(M4~):

| 대상 | 위치 | 책임 |
|---|---|---|
| `DayCloseKit` | `app/DayCloseKit/` (SwiftPM 라이브러리) | 봉투/모델 `Codable`, `CoreClient`(serve --stdio 프로세스 관리, 요청 ID 매칭, 타임아웃, 재기동), 오류 매핑 |
| `DayClose` 앱 | `app/DayClose/` (Xcode 프로젝트 `app/DayClose.xcodeproj`) | 화면(03 문서), Quick Look, 썸네일, 키보드, 승인 버튼, 메뉴바(M7) |
| `DayCloseScheduler` | 앱 번들 내 헬퍼 실행파일(M7) | launchd 가 띄우는 예약 실행기. core 실행 후 알림 |
| `dayclose-native` | `native/` (SwiftPM 실행파일, M6) | Vision OCR 등 core 가 필요로 하는 macOS 전용 API를 JSON CLI로 제공 |

Swift 코드는 사용자 파일을 변경하지 않는다(휴지통·이동 포함). 모든 변경은 `plan.apply` 로만.

## 7. 프로세스 모델

| 시나리오 | 프로세스 |
|---|---|
| 수동 CLI | 셸 → `dayclose …` (1회성) |
| 앱 사용 | DayClose.app → 자식 `dayclose serve --stdio` 1개(창이 열린 동안). 앱 종료 시 stdin EOF → 자식 종료 |
| 예약 실행(M7) | launchd → `DayClose.app/Contents/MacOS/DayCloseScheduler` → 자식 `dayclose scan run --trigger schedule --json` → 결과로 알림 |
| 에이전트 | Claude Code/Codex → `dayclose … --json --channel skill` (M8: MCP stdio) |

동시성:
- DB 는 WAL. 읽기는 동시에 가능.
- 쓰기 명령(§5.3의 W)은 `DAYCLOSE_HOME/state.lock` 에 `fcntl.flock(LOCK_EX)` 를 `--wait-lock` 초 동안 시도, 실패 시 `E_LOCKED`(retryable=true). `serve --stdio` 는 요청 단위로 잠금을 잡고 놓는다(세션 전체를 잡지 않는다).
- `plan.apply` 는 연산마다 커밋한다(한 트랜잭션으로 묶지 않음). 중간 종료 시 `plan.recover` 가 정리(08 문서).

## 8. 디스크 위치 (앱 상태)

| 용도 | 기본 경로 | 비고 |
|---|---|---|
| 상태 루트 `DAYCLOSE_HOME` | `~/Library/Application Support/DayClose/` | 권한 0700 |
| DB | `$DAYCLOSE_HOME/dayclose.db` (+ `-wal`, `-shm`) | 권한 0600 |
| 설정 | `$DAYCLOSE_HOME/config.toml` | 0600. 비밀값 금지 |
| 쓰기 잠금 | `$DAYCLOSE_HOME/state.lock` | |
| DB 백업 | `$DAYCLOSE_HOME/backups/dayclose-<YYYYMMDD-HHMMSS>-pre-v<N>.db` | 마이그레이션 직전 자동 생성, 최근 3개만 유지 |
| 로그 | `~/Library/Logs/DayClose/core.log` (JSON Lines) | 5MB × 5개 회전 |
| 캐시 | `~/Library/Caches/DayClose/` | 앱 썸네일 캐시 상한 200MB. `preview_policy != full` 항목은 캐시 금지 |
| 테스트 | `DAYCLOSE_HOME=<tmp>/home`, 사용자 파일 루트 `<tmp>/user` | §10.4 |

`DAYCLOSE_HOME` 이 지정되면 로그·캐시도 그 아래(`logs/`, `cache/`)로 간다(테스트 격리).

용량 예산(결정: 내장 디스크 245GB 가 자주 가득 차므로): DB 목표 < 200MB(파일 50만 개 기준). 이를 위해 파일 내용·썸네일은 DB 에 저장하지 않고, `file_events` 는 90일, 종결 항목(`executed`/`undone`/`stale`/`suppressed`)의 세부 이력은 180일 후 압축(06 문서 §8). DayClose 는 1GB 이상 산출물을 만들지 않는다. `archive` 결정의 보관 폴더는 사용자가 지정한 로컬/외장 경로(`archive.root`, 예 `/Volumes/External/DayCloseArchive`).

## 9. 설정 (`config.toml`)

```toml
schema_version = 1
device_id = "dev_5f2c9a1e"          # init 시 생성. 바꾸지 않음
device_name = "MacBook Pro"

[review]
daily_time = "21:00"                # 알림/예약 실행 시각 (M7)
day_boundary = "04:00"              # 결정: 자정~04:00 작업은 전날 결산에 포함 (야간 작업 습관)
carryover = true

[scan]
exclude_globs = ["**/.DS_Store", "**/node_modules/**", "**/.git/**", "**/*.photoslibrary/**", "**/Library/**"]  # 루트 기준 상대경로에 매칭 (iCloud Drive 루트 자체가 ~/Library 아래에 있으므로)
package_dirs_as_files = true        # .app, .bundle, .photoslibrary 등은 하나의 항목으로
hash_max_bytes = 67108864           # 64MB 초과 파일은 SHA-256 생략(중복 탐지 제외)
read_dataless = false               # iCloud 미다운로드(dataless) 파일 내용 읽기 금지 — 변경 불가 고정값 (§10.6)
volume_probe_timeout_s = 5

[projects]
roots = ["~/dev"]
active_days = 30                    # 결정: 최근 30일 커밋/수정 또는 미커밋 변경이 있으면 활성

[protection]
# 결정(2026-11-24): 환자 자료 전용 폴더 설정은 두지 않는다(이 Mac 에 없음). 판정은 아래 기본 패턴만.
# 필요하면 일반 보호 규칙(`rule add --protection patient_data`)으로 추가.
patient_filename_patterns = ["*처방*", "*조제*", "*환자*"]
detect_rrn_in_text = true           # 주민등록번호 패턴 탐지 (로컬)

[vault]
gitleaks = "auto"                   # auto | off
extra_paths = ["~/.ssh", "~/.aws", "~/.config/gcloud", "~/.kube", "~/.gnupg", "~/Library/Preferences/NPKI"]
content_scan_max_bytes = 1048576
expiry_warn_days = 30

[ai]                                # M6
enabled = false
provider = "none"                   # none | ollama | anthropic | openai
model = ""
allow_external = false              # 외부 공급자(anthropic/openai) 사용 허용(소유자 승인 2026-11-24). 옵트인: enabled=true + allow_external=true + Keychain 키 존재 시에만.
                                    # 키가 없으면 enabled=true 여도 E_AI_DISABLED. sensitivity 게이트는 무조건 적용(patient/secret → 어떤 모델에도 안 보냄)

[archive]                           # M5
root = ""                           # 보관 폴더(로컬/외장). 비어 있으면 archive 동작 불가(E_ARCHIVE_TARGET_MISSING).
                                    # 배치: <root>/<YYYY>/<MM>/<원래 이름> (충돌 시 08 문서 규칙). NAS/SMB·원격 대상은 비목표

[core]
log_level = "info"
```

- 스캔 루트는 설정이 아니라 DB(`scan_roots`)에 둔다. 결정: 항목·이벤트가 루트를 FK 로 참조하므로.
- AI API 키 등 비밀은 Keychain(`service="com.dayclose.ai"`, `account=<provider>`)에만.
- 알 수 없는 키 → 경고 `W_CONFIG_UNKNOWN_KEY`, 타입 오류 → `E_CONFIG_INVALID`.

## 10. 안전 아키텍처 (상세는 08·05·07 문서)

### 10.1 보호 등급과 허용 동작

항목의 `protection` 은 아래 우선순위 중 가장 높은 하나(06 문서 `protection_class`).

| protection | 판정 | 허용 동작(`allowed_actions`) | 그룹 일괄 결정 |
|---|---|---|---|
| `security_asset` | vault 탐지 | `acknowledge`, `keep`, `keep_always`, `defer` | 제외(경고 `W_PROTECTED_SKIPPED`) |
| `patient_data` | 환자 경로/패턴/내용 | `keep`, `keep_always`, `defer`, `move`, `archive` | 제외 — 항목 단위만 |
| `active_repo` | 활성 git 저장소 내부 | `acknowledge`, `keep`, `keep_always`, `defer` | 포함 가능(동작이 비파괴이므로) |
| `system` | `/System`, `/Library`, `/Applications/*.app` 내부, 앱 번들 | `acknowledge`, `keep_always`, `defer` | 포함 가능 |
| `user_rule` | 사용자 보호 규칙 | `keep`, `keep_always`, `defer`, `acknowledge` | 포함 가능 |
| `none` | 그 외 | 카테고리별(04 문서). 파일: `keep`, `keep_always`, `trash`, `move`, `archive`, `defer` | 포함 가능 |

예외 2: iCloud Drive 루트(`icloud_drive`) 항목과 dataless(미다운로드) 파일은 `trash`·`move`·`archive` 를 `allowed_actions` 에서 뺀다(`keep`, `keep_always`, `defer` 만). 이유: 휴지통 이동이 다른 기기의 삭제로 전파되고, 기기 밖 복사는 다운로드를 유발. 08 문서가 실기기 검증 절차를 정한 뒤에만 완화.
예외 1: `active_repo` 안이라도 `category=dev_cache`(재생성 가능한 산출물) 항목은 항목 단위 `trash` 허용(06 §3.1, 목록은 04).
결정: 환자 자료는 `trash` 를 허용하지 않는다. 이유: 조제·처방 관련 기록의 법정 보존 가능성 — 폐기는 DayClose 밖에서 사람이 한다.
결정: 앱·패키지·저장소·로그인 항목(`subject_type != file/dir`)은 MVP~M5 에서 `acknowledge`, `keep_always`, `defer` 만. 앱 삭제는 범위 밖(PRD 비목표).

### 10.2 실행 불변식 (executor)
1. `plan.state = approved` 이고 `approvals.plan_hash == plans.plan_hash` 일 때만 실행.
2. 연산 직전 사전조건 재검증: 원본이 존재하고 (dev, inode, size, mtime_ns) 가 계획 시점과 같다. 다르면 해당 연산 `skipped`, 항목 `stale`, `E_STALE`.
3. 연산 직전 `policy` 재평가: 지금 `protection` 이 해당 동작을 허용하지 않으면 `E_PROTECTED`.
4. 목적지가 존재하면 덮어쓰지 않는다(`E_DEST_EXISTS`). 이름 충돌 회피는 계획 단계에서 결정된 경로로만.
5. 영구 삭제 없음. `trash` = 볼륨별 휴지통으로 rename. 볼륨 간 `move` 만 복사→검증(크기+SHA-256)→원본 제거.
6. 연산 상태를 `running` 으로 커밋한 **뒤** 파일시스템 호출, 완료 후 `done` 커밋. 크래시 시 `plan.recover` 가 실제 상태로 정합화.
7. `DAYCLOSE_SANDBOX` 가 설정되면 그 경로 밖의 src/dst 는 무조건 `E_SANDBOX_VIOLATION`.

### 10.3 승인 프로토콜
- `plan.approve` 는 사람만 할 수 있다. 수단: (a) 앱의 승인 버튼(`method=app_button`), (b) TTY 가 있는 CLI 에서 plan 요약 확인 후 `plan_hash` 앞 8자리 입력(`cli_tty`), (c) TTY 가 없을 때(Skill 등) core 가 `osascript` 네이티브 확인 대화상자를 띄우고 사용자가 “승인”을 눌러야 함(`native_dialog`).
- 결정: 에이전트 세션에서도 사람 게이트가 유지되도록 (c)를 둔다. 대화상자를 거부·시간초과(120초)하면 `E_APPROVAL_DENIED`.
- MCP(M8)는 `plan.approve`, `plan.undo`, `suppression.remove`, `rule.remove` 를 노출하지 않는다.
- 테스트 전용 `method=test` 는 `DAYCLOSE_SANDBOX` 가 설정되고 `DAYCLOSE_TEST_APPROVE=1` 일 때만 허용. 둘 중 하나라도 없으면 무시.

### 10.4 테스트 샌드박스
- 모든 파일 조작 테스트는 `tmp_path` 아래 `home/`(DAYCLOSE_HOME)과 `user/`(가짜 홈: Downloads, Desktop …)를 만들고 `DAYCLOSE_SANDBOX=<tmp_path>` 를 설정한다.
- `conftest.py` 의 autouse 픽스처가 `DAYCLOSE_HOME`·`DAYCLOSE_SANDBOX` 미설정 상태에서 core 를 부르는 테스트를 실패시킨다.
- 실제 `~` 경로가 등장하면 실패(`Path.home()` 은 테스트에서 sandbox 의 `user/` 로 패치).

### 10.5 TCC / 외장 볼륨 행(hang) 방지 (상세 09 문서)
- launchd 로 뜬 프로세스는 FDA 없이 `/Volumes` 에 접근하면 **오류 없이 멈춘다**(이 머신에서 확인된 사실). 따라서 `/Volumes/*` 아래 루트·보관 대상에 접근하기 전 반드시 `common/paths.probe(path, timeout=volume_probe_timeout_s)` 로 별도 스레드에서 `stat`/`scandir` 1회를 시도한다. 시간 초과 → `W_ROOT_UNAVAILABLE`(scan) 또는 `E_VOLUME_TIMEOUT`(apply), 해당 루트 건너뜀. 멈춘 스레드는 데몬 스레드로 버린다.
- `~/Desktop`, `~/Documents`, `~/Downloads` 는 TCC 보호 폴더. `PermissionError`(EPERM) → `E_TCC_DENIED` / `W_TCC_DENIED` 로 구분해 보고(일반 `E_PERMISSION` 과 다름).
- 예약 실행은 앱 번들 헬퍼가 core 를 자식으로 띄워 TCC 책임 프로세스를 DayClose.app 으로 만든다. 사용자는 DayClose.app 에 전체 디스크 접근 권한을 준다. Python 인터프리터 자체에 FDA 를 주는 방식은 금지(모든 Python 스크립트에 권한이 새어 나감).
- `core.doctor` 는 각 루트에 대해 `ok | tcc_denied | timeout | missing` 을 보고한다. 진단 순서는 “셸 직접 실행 vs launchd 실행 비교”(09 문서).
- 로컬 빌드 서명 고정(§4 결정)이 깨지면 재빌드 후 FDA 가 풀린 것처럼 보인다 → `doctor` 가 `timeout`/`tcc_denied` 를 보고할 때 안내 문구에 “재서명 여부 확인”을 포함.

### 10.6 iCloud Drive 와 미다운로드 파일
- 기본 루트에 `~/Documents`(documents)와 iCloud Drive `~/Library/Mobile Documents/com~apple~CloudDocs`(`icloud_drive`)를 포함한다(2026-11-24 확정).
- dataless 판정: `st_flags & SF_DATALESS (0x40000000)`. 구형 자리표시자 `.<이름>.icloud` 파일도 dataless 로 취급(원래 이름으로 표시).
- dataless 파일에 대해 core 는 `open`/읽기/해시/매직바이트·내용 패턴 검사/gitleaks 를 **하지 않는다**(`lstat`·`scandir` 메타데이터만). `W_DATALESS_SKIPPED` 로 집계. 앱은 썸네일을 만들지 않고 아이콘만, Space 미리보기는 “다운로드됨” 경고 후에만.
- 루트 중첩(“데스크탑 및 문서 폴더” iCloud 동기화로 경로가 겹치는 경우): 수집기는 심볼릭 링크를 따라가지 않고, 다른 루트의 하위에 있는 경로는 바깥 루트 순회에서 건너뛴다. 같은 (dev, inode) 루트 디렉터리는 한 번만 순회.
- iCloud 경로 접근도 EPERM 이면 `W_TCC_DENIED`.

## 11. 오류 모델

Python: `common/errors.py`

```
DayCloseError(code: str, message: str, details: dict = {}, retryable: bool = False)
  ├─ UsageError            E_USAGE
  ├─ NotFoundError         E_NOT_FOUND, E_NOT_INITIALIZED
  ├─ StateError            E_INVALID_STATE, E_STALE, E_DEST_EXISTS, E_APPROVAL_MISMATCH
  ├─ SafetyError           E_PROTECTED, E_APPROVAL_REQUIRED, E_APPROVAL_DENIED, E_SANDBOX_VIOLATION,
  │                        E_PATH_OUTSIDE_ROOTS, E_AI_BLOCKED_SENSITIVE
  ├─ EnvironmentError_     E_PERMISSION, E_TCC_DENIED, E_VOLUME_UNAVAILABLE, E_VOLUME_TIMEOUT, E_TOOL_MISSING,
  │                        E_CONFIG_INVALID, E_AI_DISABLED, E_ARCHIVE_TARGET_MISSING
  ├─ LockError             E_LOCKED (retryable)
  ├─ PartialError          E_PARTIAL (data 동반)
  └─ InternalError         E_INTERNAL, E_DB_CORRUPT, E_DB_MIGRATION, E_UNDO_IMPOSSIBLE
```

전체 코드표:

| code | 의미 |
|---|---|
| `E_USAGE` | 인자 오류, 알 수 없는 명령/플래그 |
| `E_NOT_INITIALIZED` | `dayclose init` 전 |
| `E_NOT_FOUND` | ID/경로 없음 |
| `E_INVALID_STATE` | 허용되지 않는 상태 전이(06 문서 §4) |
| `E_STALE` | 계획/결정 이후 파일이 바뀌었거나 사라짐 |
| `E_DEST_EXISTS` | 목적지 존재 |
| `E_APPROVAL_REQUIRED` | 승인 없는 plan 실행 시도 |
| `E_APPROVAL_MISMATCH` | 승인 해시와 plan 해시 불일치 |
| `E_APPROVAL_DENIED` | 사용자가 승인 거부/시간초과 |
| `E_PROTECTED` | 보호 정책상 허용 안 되는 동작 |
| `E_SANDBOX_VIOLATION` | 샌드박스 밖 경로 |
| `E_PATH_OUTSIDE_ROOTS` | 등록된 루트/목적지 허용 목록 밖의 경로 |
| `E_AI_DISABLED` | AI 비활성 상태에서 AI 명령 |
| `E_AI_BLOCKED_SENSITIVE` | 민감 항목을 AI 로 보내려 함 |
| `E_ARCHIVE_TARGET_MISSING` | `archive.root` 미설정 또는 접근 불가 |
| `E_PERMISSION` | 일반 권한 오류 |
| `E_TCC_DENIED` | macOS 개인정보 보호(TCC) 거부 |
| `E_VOLUME_UNAVAILABLE` | 볼륨 미마운트 |
| `E_VOLUME_TIMEOUT` | 볼륨 접근 시간 초과(FDA 미부여 의심) |
| `E_TOOL_MISSING` | 필수 외부 도구 없음 |
| `E_CONFIG_INVALID` | 설정 오류 |
| `E_LOCKED` | 쓰기 잠금 획득 실패 |
| `E_PARTIAL` | 일부 연산 실패 |
| `E_UNDO_IMPOSSIBLE` | 되돌릴 수 없음(휴지통 비워짐 등) |
| `E_DB_MIGRATION` | 마이그레이션 실패(백업에서 복원 안내) |
| `E_DB_CORRUPT` | `PRAGMA integrity_check` 실패 |
| `E_INTERNAL` | 예상치 못한 예외 |

경고 코드: `W_PERMISSION_SKIPPED`, `W_TCC_DENIED`, `W_ROOT_UNAVAILABLE`, `W_TOOL_MISSING`, `W_PROTECTED_SKIPPED`, `W_PARTIAL_SCAN`, `W_TRUNCATED`, `W_CONFIG_UNKNOWN_KEY`, `W_DATALESS_SKIPPED`, `W_HASH_SKIPPED_LARGE`, `W_FIELD_KEY_UNAVAILABLE`.

예상치 못한 예외는 `E_INTERNAL` + `request_id` 로 봉투에 나가고, 트레이스백은 로그에만(마스킹 후). `--log-level debug` 에서도 봉투에 트레이스백을 넣지 않는다.

## 12. 버전 관리

- `core_version`: SemVer, `core/pyproject.toml`.
- `contract_version`: 정수. 봉투/명령 data 의 호환 깨짐 시 +1. 앱은 시작 시 `core.version` 으로 확인하고 다르면 “core 업데이트 필요” 화면.
- `db_schema_version`: 마이그레이션 번호(06 문서 §7).
- 계약 픽스처: `contracts/fixtures/<command>.<case>.json` — Python 테스트가 생성 결과와 비교하고, `DayCloseKit` 테스트가 디코딩한다. 계약 변경 = 픽스처 변경이 PR 에 드러난다.

## 13. 로깅 규칙

- 형식: JSON Lines. 필드 `ts`, `level`, `request_id`, `command`, `channel`, `event`, `msg`, 그리고 허용된 키만.
- **절대 기록 금지**: 파일 내용, OCR 텍스트, 비밀값/토큰/키, 환경변수 값, gitleaks `Match`/`Secret`, AI 요청·응답 본문, 사용자 메모(`*_enc` 필드의 평문).
- 보안 자산·환자 자료 항목은 경로 대신 `item_id`/`asset_id` 만 기록. 일반 파일 경로는 기록 가능하되 홈은 `~` 로 축약.
- 방어선 2중: (1) 로그 호출부에서 허용 필드만 전달, (2) `common/logging.RedactingFilter` 가 고엔트로피 문자열·알려진 키 패턴(`AKIA…`, `sk-…`, `ghp_…`, PEM 헤더 등)을 `[REDACTED]` 로 치환.
- 11 문서의 회귀 테스트: 비밀 픽스처를 스캔한 뒤 로그·DB·stdout 어디에도 원문이 없어야 한다.

## 14. 저장소 디렉터리 구조

```
DayClode/                         # 폴더명은 DayClode, 제품명은 DayClose (이름 변경 금지)
├── AGENTS.md  README.md  CONTEXT.md  LICENSE (MIT)  .gitignore
├── docs/                         # 01~13 명세
├── contracts/
│   ├── envelope.schema.json      # 봉투 JSON Schema
│   └── fixtures/                 # 명령별 예시 응답 (Python·Swift 공용)
├── core/                         # Python core (uv 프로젝트)
│   ├── pyproject.toml  uv.lock  .python-version
│   ├── src/dayclose/
│   │   ├── __main__.py
│   │   ├── common/   config/   store/ (migrations/0001_*.sql …)
│   │   ├── collect/  intel/    vault/    policy/   review/   plan/   executor/
│   │   ├── ai/ (M6)
│   │   ├── api/      cli/      serve/ (M4)   mcp/ (M8)
│   └── tests/
│       ├── conftest.py           # 샌드박스 강제 픽스처
│       ├── unit/  integration/  safety/  contract/
│       └── fixtures/             # 가짜 파일 생성기 (실제 비밀 아님)
├── app/                          # M4
│   ├── DayClose.xcodeproj
│   ├── DayClose/                 # 앱 타깃 소스
│   └── DayCloseKit/              # SwiftPM: Package.swift, Sources/, Tests/
├── native/                       # M6: dayclose-native (SwiftPM 실행파일)
├── skill/                        # M8: SKILL.md (Claude Code·Codex 공용)
└── scripts/                      # 개발 보조 스크립트 (샌드박스 생성 등)
```

## 15. 다른 명세가 따라야 할 계약

### 15.1 공유 이름 (이 목록 밖의 이름을 새로 만들지 말고, 필요하면 02/06을 먼저 고친다)

- 모듈: `common`, `config`, `store`, `collect`, `intel`, `vault`, `policy`, `review`, `plan`, `executor`, `ai`, `api`, `cli`, `serve`, `mcp`. (`archive` 모듈은 2026-11-24 삭제 — 보관은 executor 의 `archive` 연산) Swift: `DayCloseKit`, `DayClose`, `DayCloseScheduler`, `dayclose-native`.
- 명령 ID: §5.3 표. 봉투 필드: `schema`, `command`, `ok`, `data`, `warnings`, `error{code,message,details,retryable}`, `meta{request_id,core_version,contract_version,db_schema_version,device_id,duration_ms}`.
- ID 접두사: §5.1. 오류·경고 코드: §11. 종료 코드: §5.5.
- 항목 JSON 필드: §5.6 (`allowed_actions`, `preview_policy`, `ai_policy`, `protection`, `sensitivity`, `suggestion{action,dest,source,reason,confidence}`).
- enum·상태·테이블·컬럼: `06-DATA-MODEL.md` §3~§5 (특히 `item_state`, `decision_action`, `plan_state`, `op_type`, `op_state`, `protection_class`, `sensitivity`, `item_category`, `subject_type`, `vault_asset_kind`).
- 경로: `DAYCLOSE_HOME`, `DAYCLOSE_SANDBOX`, `DAYCLOSE_TEST_APPROVE`, `~/Library/Application Support/DayClose/`, `~/Library/Logs/DayClose/core.log`, `~/Library/Caches/DayClose/`, `state.lock`, `config.toml` 키(§9).
- Keychain: `com.dayclose.db` / `field-key-v1`(필드 암호화 키), `com.dayclose.ai` / `<provider>`(AI 키).
- 번들 ID(M4~): 앱 `com.dayclose.app`, 스케줄러 LaunchAgent 라벨 `com.dayclose.scheduler`.

### 15.2 나머지 9개 문서의 범위

- **03-UI-UX-SPEC** — DayClose.app 의 화면·상호작용 명세: 일일 결산 메인(지표 카드·그룹 목록), 그룹 상세의 갤러리/리스트/비교 모드, Quick Look·썸네일, 키보드 단축키(Space, ←→, K/D/A/M/S, ⌘Z)와 `decision_action` 매핑, 계획 검토·승인 화면, Secure Vault 화면(마스킹·메타데이터 중심), 빈 상태·오류 상태·로딩, 접근성. 데이터는 §5 명령으로만 얻고 `allowed_actions`/`preview_policy` 를 존중한다. 메뉴바·알림의 *화면* 은 여기, *등록·권한* 은 09.
- **04-FILE-INTELLIGENCE** — `collect`(fs·git·apps·brew·login_items 수집기)와 `intel` 의 알고리즘: 증분 스캔(비교 키, 이동/이름변경 판정, 제외 규칙, 패키지 디렉터리, dataless 파일), 카테고리 판정 표(`item_category`), 어떤 변경이 리뷰 항목이 되는지, 그룹 키 규칙, SHA-256 중복 탐지, 프로젝트 매칭·활성 저장소 판정, 휴리스틱 제안 규칙, 성능 목표. 보안 자산 판정은 05에 위임.
- **05-SECURE-VAULT** — `vault` 모듈: 자산 종류(`vault_asset_kind`)별 탐지 규칙(확장자·매직바이트·내용 패턴·gitleaks 통합 방식), 인증서/키 메타데이터 추출과 지문, 건강 점검(`vault_finding_type`: 만료·git 추적·중복·권한·백업 미확인), 마스킹 규칙, 시드 구문 비수집 원칙, Git 노출 키의 폐기·재발급 권고 문구, `backup_status` 판정(기본: 사용자 표시 — PRD 미결 사항). NAS·원격 암호화 백업은 비목표. 일반 executor 가 자산을 건드리지 못하게 하는 규칙의 근거.
- **07-AI-MEMORY-POLICY** — `policy` 의 기억/학습 부분과 `ai` 모듈: `keep_always` suppression 매칭 규칙, 반복 결정 → 규칙 제안(`policy_rules`, 1일차/1주/1개월 시나리오), 규칙 자동 적용 시에도 승인 필수, AI 공급자(none/ollama/anthropic/openai) 인터페이스, `sensitivity` → `ai_policy` 게이트, 전송 페이로드 스키마와 마스킹, AI 출력 검증(데이터로만 취급), `ai_requests` 감사.
- **08-SAFE-EXECUTION** — `plan`·`executor`: 결정→연산 변환, `plan_hash` 정규화 방식, 승인 프로토콜 3수단 상세, 연산별(trash/move/archive/rename/restore) 절차와 사전조건, 볼륨별 휴지통 경로, 볼륨 간 이동, 충돌 처리, 크래시 복구(`plan.recover`), undo 규칙과 불가 조건, 보호 등급 재평가, 샌드박스 가드, 실패 시나리오 표.
- **09-MACOS-INTEGRATION** — macOS 시스템 연동: TCC/FDA 요구 사항과 진단 절차(셸 vs launchd 비교), 볼륨 프로브, `SMAppService` 기반 LaunchAgent·스케줄러 헬퍼, 알림(UserNotifications) 등록·문구, 메뉴바 등록, 스크린샷 저장 위치 읽기(`defaults read com.apple.screencapture location`), 앱 인벤토리 소스(Info.plist, `mdls kMDItemLastUsedDate`), 로그인 항목·LaunchAgents 수집, 로컬 빌드 코드 서명 고정과 재빌드 후 FDA 유지 검증(공증 없음), iCloud Drive 경로·dataless 처리, core 실행파일 탐색, 앱↔core 프로세스 수명관리.
- **10-CLI-SKILL-MCP** — §5 계약의 완전한 레퍼런스: 명령별 인자·`data` 스키마·오류 케이스·예시, `serve --stdio` 프로토콜 세부, `contracts/` 픽스처 규칙, `core.schema` 출력, Skill(SKILL.md) 작성(에이전트가 따라야 할 승인 흐름), MCP 도구 매핑과 비노출 명령. (`archive.*` 명령 그룹은 없음 — 보관은 `decision.set --action archive` + `config.archive.root`)
- **11-TEST-PLAN** — 테스트 전략: 샌드박스 픽스처 규약, 단위/통합/안전/계약/UI 테스트 구분, 안전 회귀 스위트(비밀 누출 0, executor 외 변경 금지 정적 검사, 승인 없는 실행 불가, 보호 항목 불변), 장애 주입(크래시 중 apply, 볼륨 분리, TCC 거부, 휴지통 비움 후 undo), 성능 기준, 마일스톤별 인수 테스트 목록, CI 명령.
- **13-OPEN-SOURCE-RESEARCH** — CONTEXT 턴0 의 프로젝트들(agentic-mac-skills, Mole, Sorty, Declutter, FileMorrow, FolderSorter, Composio file-organizer, Sortwise, Binky)과 gitleaks 등 도구의 라이선스·재사용 가능 부분·참고할 설계·채택/비채택 결정. 저장소가 MIT 이므로 GPL/AGPL 코드는 복사 불가·외부 도구 호출만 가능하다는 기준으로 판정하고, 코드 복사 시 라이선스 표기 규칙을 정한다. 이 문서의 결론이 02 의 기술 선택을 바꾸려면 02 를 먼저 수정.
