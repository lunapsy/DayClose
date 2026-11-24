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
| DB | SQLite (표준 `sqlite3`), WAL 모드 | 단일 사용자, 기기당 DB 하나(§8.1), 서버 불필요. 백업=파일 복사. |
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
Core 개발: `pytest`, `ruff`, `mypy`, `hypothesis`(속성 기반 테스트), `jsonschema`(계약 테스트) — 11 문서.
외부 도구(있으면 사용, 없으면 기능 축소 + 경고): `git`, `brew`, `gitleaks`, `mdls`, `defaults`, `osascript`. 호출 규칙은 §6(`run_tool`, 절대경로).
결정(2026-11-24 조정): AI 공급자 SDK(`anthropic`, `openai`)와 MCP SDK 는 의존성으로 넣지 않는다. 세 공급자(ollama/anthropic/openai) 모두 표준 라이브러리 `urllib.request` + JSON 으로 호출한다(`ai/providers/` 안에서만). 이유: 런타임 의존성 최소화, 기동 시간(NFR-PERF-003), import 경계 검사 단순화. 재검토 조건: 구조화 출력·재시도 등 SDK 전용 기능이 필요해질 때 이 목록을 고치는 PR 로.
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
- 외부로 노출되는 ID 는 접두사 문자열: `run_12`, `ent_9031`, `evt_77`, `itm_128`, `grp_12`, `dec_40`, `pln_7`, `op_33`, `apv_7`, `ast_5`, `fnd_9`, `prj_3`, `app_21`, `pkg_8`, `rul_2`(protection_rules), `prl_2`(policy_rules), `sup_4`, `ses_15`, `root_1`. (2026-11-24: `rul_` 이 두 테이블을 가리키던 것을 분리) DB 는 INTEGER PK(06 문서). 변환은 `common/ids.py` 한 곳에서.
- 시간: JSON 에서는 RFC 3339 UTC(`2026-11-24T12:03:11.402Z`), 날짜는 로컬 `YYYY-MM-DD`(`review_date`).
- 경로: 절대경로 문자열. 홈 축약(`~`)은 표시용 필드 `display_path` 에만.

### 5.2 전역 플래그

| 플래그 | 의미 |
|---|---|
| `--json` | 봉투 출력. 앱·Skill·테스트는 항상 지정. 미지정 시 사람용 텍스트(같은 데이터). |
| `--home PATH` | 상태 디렉터리 재지정(= `DAYCLOSE_HOME`). 테스트 필수. |
| `--progress ndjson` | 장시간 명령(`scan.run`, `plan.apply`)이 stderr 로 진행 이벤트 출력. |
| `--wait-lock SEC` | 쓰기 잠금 대기 시간(기본 10). 초과 시 `E_LOCKED`. |
| `--channel cli\|app\|skill\|mcp\|schedule` | 호출 출처. 기본 `cli`. 앱은 `app`, Skill 은 `skill`. **실효 채널** = 이 값을 에이전트 환경 표식으로 승격한 것(표식이 있으면 `cli` 도 `skill` 로, 10 §8.5). 권한 판단(§10.3)은 모두 실효 채널로 한다 |
| `--log-level debug\|info\|warn\|error` | 기본 `info`. |

### 5.3 명령 목록 (v1)

마일스톤(M#)은 처음 구현되는 시점. 표시 `W` = 쓰기 잠금 필요(DB 변경), `F` = 사용자 파일 변경.

| 명령 ID | CLI 시그니처 | M | 비고 |
|---|---|---|---|
| `core.version` | `dayclose version` | M1a | core/스키마/계약 버전 |
| `core.init` | `dayclose init [--device-name NAME] [--no-default-roots]` | M1a | W. 홈 디렉터리·DB·설정 생성, 기본 루트 등록. 멱등. **스캔하지 않고**, 필드 암호화 키도 만들지 않는다(키는 첫 암호화 필드 저장 시, M2 — 06 §6) |
| `core.doctor` | `dayclose doctor` | M1a | M1: 루트 접근성(`ok\|tcc_denied\|timeout\|missing`), DB 무결성, 파일 권한, DB↔설정 `device_id` 불일치(`W_DEVICE_MISMATCH`). 이후 마일스톤에서 외부 도구, FDA 프로브, host UUID(M5) 추가 |
| `core.schema` | `dayclose schema [COMMAND_ID]` | M2 | 명령별 `data` JSON Schema 출력(에이전트용) |
| `config.get` / `config.set` / `config.list` | `dayclose config get KEY` / `set KEY VALUE` / `list` | M1a | set 은 W |
| `root.list` / `root.add` / `root.remove` | `dayclose root list [--all]` / `root add PATH --kind KIND [--max-depth N] [--icloud-synced auto\|yes\|no]` / `remove ROOT_ID` | M1a | W. KIND = `scan_root_kind`. `--all` = 제거된 루트 포함. `root.list` 는 루트마다 `icloud_synced`(실효값), `icloud_synced_mode`, `icloud_synced_source`(`detected`/`user`/`assumed`)를 보여 준다 |
| `root.set` | `dayclose root set ROOT_ID [--icloud-synced auto\|yes\|no] [--max-depth N]` | M2 | W. iCloud 동기화 여부를 손으로 지정(09 §12 V17 의 대체 수단). `no` 로 바꾸면 그 루트 항목의 trash/move 제한이 풀리므로 사람 작업 — MCP 비노출 |
| `scan.run` | `dayclose scan run [--root ROOT_ID]... [--collectors fs,git,vault,apps,brew,login_items] [--trigger manual\|schedule\|app\|agent]` | M1b | W. 기본 collectors = 해당 마일스톤까지 구현된 전부 |
| `scan.list` / `scan.show` | `dayclose scan list` / `scan show RUN_ID` | M1b | |
| `change.list` | `dayclose change list [--run RUN_ID \| --since RFC3339] [--event created,modified,deleted,moved] [--root ROOT_ID] [--limit N] [--cursor C]` | M1b | |
| `review.summary` | `dayclose review summary [--review-date DATE]` | M2 | W(오늘 세션이 없으면 `ensure_session`). 과거 날짜에 세션이 없으면 `E_NOT_FOUND`(만들지 않음), 미래 날짜 `E_USAGE`. 일일 결산 지표 + 그룹 목록 |
| `review.close` | `dayclose review close [--review-date DATE]` | M2 | W |
| `group.list` / `group.show` | `dayclose group list [--review-date DATE]` / `group show GROUP_ID` | M2 | |
| `item.list` | `dayclose item list [--group GROUP_ID] [--state S,...] [--category C,...] [--review-date DATE] [--open] [--deferred] [--carried] [--limit N] [--cursor C]` | M2 | `--open` = 미결 항목(이월 포함), `--deferred` = 보류 중, `--carried` = `carry_count>0` |
| `item.show` | `dayclose item show ITEM_ID` | M2 | 이력·결정·연산 포함. 제안 설명 신호는 저장하지 않고 이 명령에서 재계산(07 §6) |
| `decision.set` | `dayclose decision set (ITEM_ID... \| --group GROUP_ID) --action ACTION [--dest PATH] [--note TEXT] [--defer-until DATE]` | M2 | W. 파일 변경 없음 |
| `decision.undo` | `dayclose decision undo (ITEM_ID... \| --last)` | M2 | W. `planned` 이전까지만 |
| `decision.list` | `dayclose decision list [--since DATE] [--limit N]` | M2 | |
| `vault.list` / `vault.show` / `vault.health` | `dayclose vault list [--kind K] [--status S]` / `vault show ASSET_ID` / `vault health` | M3 | 읽기 전용 |
| `vault.annotate` | `dayclose vault annotate ASSET_ID [--label TEXT] [--note TEXT] [--expires DATE] [--backup verified\|none\|unknown] [--status active\|retired]` | M3 | W. 암호화 필드. `--backup` 이 `backup_status` 의, `--status` 가 `retired` 의 유일한 갱신 경로. 발견 사항 확인은 별도 명령 없이 해당 항목의 `decision.set --action acknowledge` 로(05 §8.3) |
| `app.list` | `dayclose app list [--new] [--removed]` | M3 | |
| `package.list` | `dayclose package list [--manager brew_formula\|brew_cask] [--new]` | M3 | |
| `project.list` | `dayclose project list [--active]` | M2 | git 저장소/프로젝트 |
| `report.daily` | `dayclose report daily [--review-date DATE] [--format json\|md]` | M2 | |
| `rule.list` / `rule.add` / `rule.remove` | `dayclose rule list [--source builtin\|user\|config]` / `rule add --kind KIND --pattern P --protection CLASS [--sensitivity S]` / `rule remove RUL_ID` | M2 | W. 보호 규칙(`rul_`) |
| `suppression.list` / `suppression.add` / `suppression.remove` | `dayclose suppression list` / `suppression add --match path\|path_glob\|sha256 --value V [--category C] [--expires DATE]` / `remove SUP_ID` | M2 | W. “다시 묻지 않기” 규칙. `add` 는 사용자가 명시하는 매칭(06 §4.3). `security_asset`·`patient_data` 항목에는 적용되지 않음(`sha256` 은 `file_entries.sha256` 이 있는 파일만) |
| `plan.create` | `dayclose plan create (--items ITEM_ID,... \| --all-decided)` | M5 | W. `draft` plan + `plan_hash` |
| `plan.show` / `plan.list` | `dayclose plan show PLAN_ID` / `plan list [--state S]` | M5 | |
| `plan.approve` | `dayclose plan approve PLAN_ID --hash PLAN_HASH` (+ stdio 전용 인자 `app_signature`) | M5 | W. 사람 확인 필수(§10.3). `--hash` 는 전체 64자 |
| `core.app_key` | `dayclose app-key register` / `app-key show` / `app-key revoke` | M5 | W. 앱의 Secure Enclave 공개키 등록·조회·폐기(08 §6.5). register 는 **실효 채널 `app` 에서만**(skill 승격·mcp 거부), register/revoke 는 사람 확인 필수 — register 확인 문구: “앱 설정에서 방금 [승인 키 만들기]를 누른 경우에만 승인하세요”. `revoke` 는 채널 제한이 없다(키를 없애는 쪽은 보호를 약화하지 않음 — 어느 채널에서든 사람 확인 후 폐기). MCP 비노출 |
| `plan.apply` | `dayclose plan apply PLAN_ID [--dry-run]` | M5 | W, F |
| `plan.cancel` | `dayclose plan cancel PLAN_ID` | M5 | W |
| `plan.undo` | `dayclose plan undo PLAN_ID [--op OP_ID]... [--on-conflict fail\|rename]` | M5 | W, F |
| `plan.recover` | `dayclose plan recover` | M5 | W. 중단된 연산 정합성 복구(08 문서) |
| `audit.list` | `dayclose audit list [--since DATE] [--limit N]` | M5 | |
| `policy.suggestions` / `policy.accept` / `policy.reject` | `dayclose policy suggestions [--state suggested\|active\|rejected\|disabled]` / `accept PRL_ID` / `reject PRL_ID` | M6 | 학습 규칙(`prl_`, 07 문서). `reject`: `suggested → rejected`, `active → disabled` |
| `ai.status` / `ai.classify` | `dayclose ai status` / `ai classify [--review-date DATE] [--dry-run]` | M6 | 옵트인. `--dry-run` = 게이트 통과 페이로드 요약만, 전송 없음 |
| `ai.key.set` / `ai.key.remove` | `dayclose ai key set PROVIDER` (키는 **stdin 으로만**) / `ai key remove PROVIDER` | M6 | W. Keychain `com.dayclose.ai`/`<provider>`. 키 값은 응답·로그·감사에 없음. 앱의 키 입력도 이 명령으로(09 §11.4) |
| `core.serve` | `dayclose serve --stdio` | M4 | 전송 계층 |
| `mcp.serve` | `dayclose mcp serve` | M8 | 전송 계층 |

목록 명령(`*.list`, `change.list`, `item.list`, `audit.list` 등)은 모두 `--limit N` 과 `--cursor C` 를 받는다(10 §1.4). 위 시그니처에서는 반복 표기하지 않는다.

ACTION(= `decision_action` enum, 06 문서): `keep`, `keep_always`, `trash`, `move`, `archive`, `rename`(M6), `defer`, `acknowledge`. `rename` 은 `--dest` 에 같은 디렉터리 안의 새 전체 경로. 어떤 항목에 어떤 ACTION 이 허용되는지는 항목 JSON 의 `allowed_actions` 가 유일한 기준이다(§5.6).

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
결정: `serve --stdio` 기동 시 마이그레이션은 진행 이벤트를 내지 않는다(`migrate` phase 없음). 마이그레이션은 ready 핸드셰이크 전에 끝나며, 실패하면 ready 대신 `E_DB_MIGRATION` 봉투(10 §3).

### 5.5 종료 코드

| 코드 | 의미 | 대표 error.code |
|---|---|---|
| 0 | 성공(경고 포함 가능) | — |
| 2 | 사용법 오류 | `E_USAGE` |
| 3 | 대상 없음 | `E_NOT_FOUND`, `E_NOT_INITIALIZED` |
| 4 | 상태 충돌 | `E_INVALID_STATE`, `E_STALE`, `E_DEST_EXISTS`, `E_APPROVAL_MISMATCH`, `E_UNDO_IMPOSSIBLE` |
| 5 | 안전 정책 거부 | `E_PROTECTED`, `E_APPROVAL_REQUIRED`, `E_APPROVAL_DENIED`, `E_SANDBOX_VIOLATION`, `E_PATH_OUTSIDE_ROOTS`, `E_AI_BLOCKED_SENSITIVE`, `E_DEVICE_MISMATCH` |
| 6 | 권한/환경/설정 | `E_PERMISSION`, `E_TCC_DENIED`, `E_VOLUME_UNAVAILABLE`, `E_VOLUME_TIMEOUT`, `E_TOOL_MISSING`, `E_CONFIG_INVALID`, `E_AI_DISABLED`, `E_ARCHIVE_TARGET_MISSING` |
| 7 | 잠금 | `E_LOCKED` |
| 8 | 부분 실패 | `E_PARTIAL` (plan.apply/undo 일부 연산 실패. `data` 는 null 이 아니라 결과를 담는다 — 유일한 예외) |
| 10 | 내부 오류 | `E_INTERNAL`, `E_DB_CORRUPT`, `E_DB_MIGRATION` |
| 130 | 사용자 취소 | `E_CANCELLED` (CLI SIGINT, serve 요청 취소. 요청 취소가 가능한 명령은 `scan.run`, `ai.classify` 뿐) |

`plan.apply` 멈추기(08 §7.6.2가 계약): serve 프로토콜에 apply 취소 요청은 **없다**. 유일한 멈춤 수단은 프로세스 신호(CLI Ctrl-C, 앱은 자식 serve 에 `SIGINT`)이며, 진행 중인 이름변경은 끝까지, 진행 중인 복사는 임시 파일을 지우고 `pending` 으로 되돌린 뒤 남은 연산을 시작하지 않는다. 결과는 `E_CANCELLED` 가 아니라 `E_PARTIAL` + `data.resumable=true`(계획은 `executing`, 재개 또는 `plan.cancel`).

`E_PARTIAL` 예외: `ok=false`, `error.code="E_PARTIAL"`, `data` 에 연산별 결과를 담는다. 소비자는 반드시 `data.operations[*].state` 를 확인한다. 하나 이상의 연산을 **시도**했고 전부 `done` 이 아니면 `E_PARTIAL` 이다(시도했는데 `done` 0개인 경우 포함 — 계획 상태는 `failed`). 전역 검사(08 §7.1)에서 막혀 아무것도 시도하지 않았으면 해당 오류 코드.

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
  "blocked_reasons": {},
  "origin_root_kind": "desktop",
  "is_dataless": false,
  "icloud_synced": false,
  "vault": null
}
```

- `allowed_actions` 는 core 의 `policy` 가 계산한다. UI 는 이 목록에 없는 동작을 비활성화하고, core 는 `decision.set` 과 `plan.apply` 에서 **다시** 검증한다(이중 검증).
- `preview_policy`: `full` | `ephemeral`(미리보기 허용, 썸네일 디스크 캐시 금지) | `metadata_only`(내용 미리보기 금지).
- `ai_policy`: `external_ok` | `local_only` | `none`. `protection=active_repo` 항목은 sensitivity 와 무관하게 최대 `local_only`(리뷰 #17, CONTEXT 턴0 “활성 Git 프로젝트 파일명 외부 미전송”). 프로젝트 이름은 `ai.send_project_names=true` 일 때만 외부 공급자에 전달(기본 false).
- `protection = security_asset` 이면 `display_name` 은 마스킹(`AuthKey_••••••.p8`)되고 `vault` 에 자산 요약이 들어간다.
- `blocked_reasons`: 파일 동작(`trash`, `move`, `archive`, `rename`) 중 `allowed_actions` 에서 빠진 것 → 이유 코드. 이유 코드: `security_asset`, `patient_data`, `active_repo`, `system`, `user_rule`, `icloud_synced`, `dataless`, `subject_type`, `secret_content`(protection 과 무관하게 `sensitivity=secret` — move/archive 금지), `contains_secret_content`(폴더 안에 비밀 파일 — move/archive 금지), `hardlink_to_protected`(보호된 엔트리와 같은 inode), `archive_root_unset`, `not_yet_available`(해당 마일스톤 전). 한 동작에 이유가 여럿이면 위 순서의 첫 번째.
- `origin_root_kind`(`scan_root_kind`), `is_dataless`(§10.6), `icloud_synced`(§10.1 예외 2 — `true` 이고 `allowed_actions` 에 `trash` 가 있으면 UI 는 “다른 기기에서도 삭제됨” 표시) 는 03·04 가 화면·판정에 쓴다.
- 에이전트 채널 투영(`--channel skill|mcp`, `api` 의 `agent_view` 한 곳): `sensitivity ∈ {patient, secret}` 항목은 `path`, `display_name`, `display_path`, vault subject·메모를 `null` 로 내보낸다(05 §11.5, 10 §9.4). 채널은 자기 신고이므로 이는 위생 규칙이며 보안 경계가 아니다(§10.3 잔여 위험).

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
| `api` | 명령 레지스트리, 인자 검증, 잠금 획득(`common/paths` 의 잠금 함수 호출), 감사 기록, 봉투 생성 | 전송 형식, 파일 직접 쓰기 | 10 |
| `cli`, `serve`, `mcp` | 전송 계층(argv/stdio/MCP ↔ api) | 로직 | 10 |

규칙:
- 사용자 파일에 대해 `os.rename`, `os.replace`, `shutil.move`, `os.unlink`, `os.remove`, `shutil.rmtree`, `open(..., 'w'|'a')`, `os.chmod`, xattr 쓰기를 호출할 수 있는 곳은 `dayclose/executor/` 뿐이다. 다른 모듈에서 쓰면 `tests/safety/test_no_mutation_outside_executor.py` 가 실패해야 한다(정적 검사, 11 문서).
- DayClose 자신의 상태 파일(`DAYCLOSE_HOME` 아래) 쓰기는 `store`, `config`, `common/logging`, `common/paths`(디렉터리 생성과 `state.lock` 생성·열기 — `open_state_lock()`) 만. `api` 는 잠금 파일을 직접 열지 않는다(정적 검사의 쓰기 허용 목록과 일치, 08 §15.2).
- `vault/signals.py`: 이름·확장자 신호 판정 **순수 함수**(`name_matches(path)` 등, 파일 I/O 없음). 예외적으로 `collect`·`intel`·`policy` 가 import 할 수 있다(M2 해시 저장 규칙에 필요, 06 §6·§7). vault 의 나머지(내용 검사, `vault/io.py`)는 M3.
- `common/textread.py`: 크기 상한이 있는 **읽기 전용** 텍스트 읽기(`read_text_prefix(path, max_bytes)`) — dataless 재확인 후에만 연다. `policy` 의 로컬 텍스트 주민등록번호 탐지(M2)가 쓴다(`vault` 에 의존하지 않기 위해 `common` 에 둠, 07 §3.1, 04 §2.6).
- 서브프로세스 호출은 `common/proc.py` 의 `run_tool(tool, args, timeout, input_bytes=None, env=None)` 만 사용. 허용 도구 목록 고정(`git`, `brew`, `gitleaks`, `mdls`, `defaults`, `osascript`, `dayclose-native`), 셸 미경유(`shell=False`), 타임아웃 필수.
  - 허용 목록은 도구 이름이 아니라 **절대경로 후보 목록**이다(`common/paths.system_path(tool)`): `/usr/bin/osascript`, `/usr/bin/git`, `/usr/bin/mdls`, `/usr/bin/defaults`, `/opt/homebrew/bin/brew`, `/opt/homebrew/bin/gitleaks`, `/usr/local/bin/gitleaks`, 앱 번들의 `dayclose-native`(`DAYCLOSE_NATIVE`). PATH 검색 금지. Homebrew 후보(`/opt/homebrew/bin/*`, `/usr/local/bin/*`)는 `realpath` 가 기대하는 접두사(`/opt/homebrew/`, `/usr/local/`) 안에 있을 때만 채택한다(심볼릭 링크로 다른 곳을 가리키면 거부). root 소유 확인은 **승인 경로의 도구**에만 적용한다(Homebrew 도구는 사용자 소유이므로 대상 아님): **승인 경로의 도구**(`osascript`)는 실행 전 `lstat` 으로 일반 파일·root 소유·그룹/기타 쓰기 불가를 확인하고, 아니면 `E_APPROVAL_DENIED{reason:untrusted_tool}`(08 §6.4). 샌드박스에서만 `$DAYCLOSE_SANDBOX/bin` 을 먼저 본다(가짜 도구, 11 §2.3).
  - 환경은 고정 최소 집합(`PATH=/usr/bin:/bin:/usr/sbin:/sbin`, `LANG`, `HOME`, `TMPDIR` + 호출부가 넘긴 `env`)으로 새로 만든다. 사용자 셸 환경을 물려주지 않는다(`GIT_*`·`DYLD_*` 주입 차단).
  - `input_bytes` 는 stdin 으로 전달(예: gitleaks stdin 모드, 05 §5). `osascript` 는 `--` 뒤 argv 를 가공 없이 그대로 넘긴다(08 §6.4 — 요약 텍스트를 스크립트에 끼워 넣지 않기 위함).
- `common/fsmeta.py`: ctypes 기반 **읽기 전용** 메타데이터 헬퍼(볼륨 정보, 대소문자 구분, `gethostuuid`(기기 검사, 08 §7.11), `has_gui_session()`(`SessionGetInfo` — 승인 수단 선택의 “GUI 세션 있음” 판정, §10.3 ④), `volume_encrypted(path)`(보관 폴더 경고용 — `True`/`False`/`None`; `None`=알 수 없음 → `W_ARCHIVE_UNENCRYPTED` 와 같은 경고) 등 — 허용 함수 목록은 08 §15.2). 쓰기 API 는 넣지 않는다.
- executor 안에서도 원본 제거(`unlink`/`rmtree`)는 `executor/fsops.remove_verified_source`(검증된 볼륨 간 이동의 원본)와 `executor/fsops.remove_own_artifact`(엔진이 만든 임시 사본 정리) 두 함수에서만(정적 검사).
- 네트워크 모듈(`urllib.request`, `http.client`, `socket`, `ssl`)을 import 할 수 있는 곳은 `ai/providers/` 뿐이고, 그것을 import 하는 곳은 `ai/client.py` 뿐(07 §3, 정적 검사).
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
| 예약 실행(M7) | launchd → `DayClose.app/Contents/MacOS/DayCloseScheduler` → 자식 `dayclose scan run --trigger schedule --channel schedule --json` → `dayclose review summary --channel schedule --json`(알림 숫자 출처) → 알림. 인증서 만료 수는 `review.summary` 의 세션 지표 `vault_expiring_soon`·`vault_expiring_critical`(06 §5.2)에서 얻는다(일일 알림에 포함, critical 이면 별도 알림). **채널 `schedule` 이 쓸 수 있는 명령은 `scan.run`, `review.summary` 둘뿐**이며 core 가 강제한다 — 그 밖의 명령은 `api` 진입 시 `E_PROTECTED{channel_not_allowed}`(§10.3 3). 예약 실행은 승인·실행을 하지 않는다(채널 `schedule` 의 `plan.approve`·`plan.apply` 는 거부) |
| 에이전트 | Claude Code/Codex → `dayclose … --json --channel skill` (M8: MCP stdio) |

동시성:
- DB 는 WAL. 읽기는 동시에 가능.
- 쓰기 명령(§5.3의 W)은 `common/paths.open_state_lock()` 으로 연 `DAYCLOSE_HOME/state.lock` 에 `fcntl.flock(LOCK_EX)` 를 `--wait-lock` 초 동안 시도, 실패 시 `E_LOCKED`(retryable=true). `serve --stdio` 는 요청 단위로 잠금을 잡고 놓는다(세션 전체를 잡지 않는다).
- `plan.apply` 는 연산마다 커밋한다(한 트랜잭션으로 묶지 않음). 중간 종료 시 `plan.recover` 가 정리(08 문서). apply/undo/recover 연결은 `synchronous=FULL`, `fullfsync=ON`, `checkpoint_fullfsync=ON`(08 §7.1).
- 리뷰 세션은 `review.ensure_session(D)` 한 곳에서만 만든다. 오늘 세션이 없으면 `scan.run` 의 review 단계나 `review.summary` 중 먼저 오는 쪽이 만들고, 이월은 **세션을 처음 만드는 트랜잭션**에서 1회(06 §4.2).

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

### 8.1 두 기기 운용 (2026-11-24 확정)

MacBook 과 Mac mini 에 **서로 독립된 설치** 두 개를 둔다. 각 기기는 자체 `DAYCLOSE_HOME`·DB·`config.toml`·학습 규칙·suppression 을 갖고, `device_id`(init 시 생성, `app_meta`·`config.toml`·봉투 `meta`)로 식별된다. 동기화·병합·통합 리포트는 비목표.

- 결과 1: 한 기기에서 만든 규칙·suppression·결정 이력은 다른 기기가 모른다. 같은 결정을 두 번 할 수 있다.
- 결과 2: iCloud 동기화 경로의 같은 파일이 두 기기 리뷰에 각각 나타난다. 다운로드된 파일은 해제 후 각 기기에서 항목 단위 `trash` 를 할 수 있으므로(§10.1 예외 2, C11) **한 기기의 휴지통 처리가 다른 기기에서 그 파일을 사라지게 할 수 있다**. 다른 기기의 열린 항목은 다음 scan 에서 `stale`(`subject_gone`)로 정리되고, 그 기기의 계획에 들어 있었다면 실행 직전 사전조건에서 `skipped`(`E_STALE`)가 된다. 이동·보관·이름 변경은 iCloud 경로에서 불가하므로 그 밖의 충돌은 없다.
- 결과 3: 기본값은 디스크 구성을 가정하지 않는다. 기본 루트는 홈 아래만, `archive.root` 기본값은 빈 값, `/Volumes/*` 경로는 사용자가 기기별로 `root add`·`config set` 한다(Mac mini: 작은 내장 + `/Volumes/External`).
- 결과 4: DB·설정을 기기 간에 복사하지 않는다. 복사된 DB 는 `app_meta.device_id ≠ config.device_id` 또는 `app_meta.host_uuid_sha256` 불일치(DB 와 설정을 함께 복사해도 걸림, 08 §7.11)로 판정 — `core.doctor` 가 경고(`W_DEVICE_MISMATCH`), 파일 변경 명령은 `E_DEVICE_MISMATCH` 로 거부. 고치는 명령은 없다: 그 Mac 에서 `dayclose init` 으로 새로 시작.
- 개발 기기는 Mac mini. 개발 중 테스트는 샌드박스에서만(AGENTS.md §3).
- 후보(현재 범위 밖): 규칙·suppression 을 파일로 내보내기/가져오기.

## 9. 설정 (`config.toml`)

```toml
schema_version = 1
device_id = "dev_5f2c9a1e"          # init 시 생성. 바꾸지 않음
device_name = "MacBook Pro"        # init 기본값 = 컴퓨터 이름(`platform.node()` 에서 `.local` 제거). 기기별

[review]
daily_time = "21:00"                # 알림/예약 실행 시각 (M7)
day_boundary = "04:00"              # 결정: 자정~04:00 작업은 전날 결산에 포함 (야간 작업 습관)
carryover = true

[scan]
exclude_globs = ["**/.DS_Store", "**/node_modules/**", "**/.git/**", "**/*.photoslibrary/**", "**/Library/**"]  # 루트 기준 상대경로에 매칭 (iCloud Drive 루트 자체가 ~/Library 아래에 있으므로)
package_dirs_as_files = true        # .app, .bundle, .photoslibrary 등은 하나의 항목으로
hash_max_bytes = 67108864           # 64MB 초과 파일은 SHA-256 생략(중복 탐지 제외)
hash_budget_bytes = 2147483648      # 한 scan 에서 해시 계산 총량 상한 (04 §2.5)
settle_seconds = 60                 # mtime 이 이보다 최근인 파일은 다음 scan 까지 **리뷰 항목 생성만** 보류(M2). 수집기는 엔트리 생성·갱신과 이벤트 기록을 항상 한다 (04 §2.2)
content_scan_max_bytes = 1048576    # policy 의 로컬 텍스트 주민등록번호 탐지가 읽는 최대 바이트 (리뷰 #7, M2)
max_entries_per_root = 300000       # 초과 시 W_TRUNCATED (04 §14)
devcache_min_bytes = 104857600      # 개발 캐시 표시 최소 크기 100MB (04 §10)
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
extra_paths = ["~/.ssh", "~/.aws", "~/.azure", "~/.docker", "~/.config/gh", "~/.config/gcloud", "~/.kube", "~/.gnupg", "~/Library/Preferences/NPKI"]
content_scan_max_bytes = 1048576    # vault 내용 패턴 검사 상한 (05). scan.content_scan_max_bytes 와 별개
expiry_warn_days = 30

[ai]                                # M6
enabled = false
provider = "none"                   # none | ollama | anthropic | openai
model = ""
allow_external = false              # 외부 공급자(anthropic/openai) 사용 허용(소유자 승인 2026-11-24). 옵트인: enabled=true + allow_external=true + Keychain 키 존재 시에만.
                                    # 키가 없으면 enabled=true 여도 E_AI_DISABLED. sensitivity 게이트는 무조건 적용(patient/secret → 어떤 모델에도 안 보냄)
ollama_url = "http://127.0.0.1:11434"  # 루프백이 아니면 외부로 취급 (07 §3.2)
timeout_s = 60                      # 외부 공급자는 min(timeout_s, 30)
max_items_per_request = 100
send_project_names = false          # 외부 공급자에게 프로젝트 이름을 보낼지 (리뷰 #17, 기본 false). active_repo 항목은 언제나 local_only

[policy]                            # M6 학습 (07 §4)
learn_window_days = 60
learn_min_evidence = 5
learn_min_days = 3
learn_consistency = 0.9
reject_cooldown_days = 30
auto_apply = true                   # active 규칙이 제안을 자동으로 채움 — 실행은 여전히 승인 필요
auto_apply_daily_cap = 200

[icloud]                            # M5 (02 §10.1 예외 2)
allow_trash = true                  # 소유자 허용(C11). 코드 게이트 TRASH_UNLOCK_VERIFIED 가 참일 때만 효력. false 면 iCloud 동기화 항목 trash 불가

[archive]                           # M5
root = ""                           # 보관 폴더(로컬/외장). 비어 있으면 archive 동작 불가(E_ARCHIVE_TARGET_MISSING).
                                    # 배치: <root>/<YYYY>/<MM>/<원래 이름>. YYYY/MM = 파일 mtime 의 로컬 날짜(총괄 최종 결정 2026-11-24, 08 §4.4). 충돌 시 08 규칙. NAS/SMB·원격 대상은 비목표

[core]
log_level = "info"
```

- 스캔 루트는 설정이 아니라 DB(`scan_roots`)에 둔다. 결정: 항목·이벤트가 루트를 FK 로 참조하므로.
- AI API 키 등 비밀은 Keychain(`service="com.dayclose.ai"`, `account=<provider>`)에만. 등록은 `ai.key.set`(stdin).
- 앱이 core 를 찾는 경로(`core.command`)는 `config.toml` 키가 아니라 **앱의 UserDefaults** 키다(09 §3.2). core 는 이 값을 모른다.
- `init` 기본 루트에 Xcode `~/Library/Developer/Xcode/DerivedData` 가 있으면 `custom` 루트로 등록(`file_level=0`, `max_depth=1`) — 개발 캐시 탐지용(04 §10, M3 부터 사용).
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

추가 규칙(protection 과 별개로 적용):
- **디렉터리 안의 보호 규칙**(리뷰 #3): 디렉터리·패키지 항목은 켜진 `protection_rules` 의 대상(path_prefix 접두사, glob, extension, project)이 그 디렉터리 **아래**에 있으면 보호 신호로 본다 → 그 디렉터리의 `trash`/`move`/`archive`/`rename` 불가(이유 = 그 규칙의 protection 코드). 실행 직전 검사(08 §7.2.1 F7)도 하위 경로에 규칙이 일치하면 `E_PROTECTED{contains_protected_rule}`.
- **비밀이 든 일반 파일**(리뷰 #6): `sensitivity=secret` 이면 protection 과 무관하게 `move`·`archive` 불가(`blocked_reasons` = `secret_content`), 그룹 결정에서 제외(`W_PROTECTED_SKIPPED{reason:secret_content}`). `trash`·`keep` 등은 항목 단위로 가능.
- **비밀 파일을 담은 폴더**(05 §8.2): 디렉터리·패키지 항목 아래에 `sensitivity=secret` 엔트리가 있으면 그 디렉터리의 `move`·`archive` 불가(`contains_secret_content`).
- **보호는 객체를 따른다 — 하드 링크**(08): 어떤 엔트리가 보호된 엔트리와 같은 `(dev, inode)` 를 가지면 그 보호 등급을 물려받는다. 파일 동작은 불가(`hardlink_to_protected`), 실행 직전 검사도 같은 코드로 `E_PROTECTED{hardlink_to_protected}`.

예외 2 — **iCloud 동기화 경로**(2026-11-24 소유자 결정 C11 반영). iCloud 동기화 경로 = `icloud_drive` 루트, 그리고 루트 디렉터리의 실제 경로가 iCloud Drive 아래이거나 “데스크탑 및 문서 폴더” 동기화가 켜진 `~/Desktop`·`~/Documents`(판정 04 §1, 실기기 확인 09 §12). 판정은 루트 단위 `scan_roots.icloud_synced`(저장된 실효값), 항목 JSON 의 `icloud_synced`. **실시간 신호 우선**(08 §9.2): `allowed_actions`·`icloud_propagates`·실행 직전 재검증에 쓰는 iCloud 여부 = `저장된 실효값 OR 양성 실시간 신호`. 양성 신호(`lstat`/`realpath` 만 사용, 내용 읽기 없음): 경로가 `~/Library/Mobile Documents/` 또는 `~/Library/CloudStorage/` 아래, desktop/documents 루트이면서 CloudDocs 안에 `Desktop`/`Documents` 폴더가 있음, 파일에 `SF_DATALESS`. 사용자가 지정한 `no` 는 양성 신호를 이기지 못한다. 사용자는 `root add/set --icloud-synced yes|no|auto` 로 지정할 수 있고, `auto` 인데 판정 신호가 없으면 `desktop`/`documents` 루트는 **동기화된 것으로 간주**(안전 쪽, `icloud_synced_source=assumed`).

| 항목 상태 | `trash` | `move` / `archive` / `rename` |
|---|---|---|
| dataless(미다운로드) — 위치 무관 | 불가 `dataless` | 불가 `dataless` |
| iCloud 동기화 + 다운로드됨, **해제 전**(아래 게이트 거짓) | 불가 `icloud_synced` | 불가 `icloud_synced` |
| iCloud 동기화 + 다운로드됨, **해제 후** | **허용**(전파 확인 필요, §10.3 7) | 불가 `icloud_synced` — **v1 에서 허용하지 않음**(08 §9.1 결론: 이동은 다른 기기에서 삭제처럼 보이고, 볼륨 간 보관은 iCloud “최근 삭제된 항목”에도 남지 않으며, 이름 변경은 충돌 사본을 만들 수 있음). 여는 것은 새 소유자 결정이 필요 |

- 해제 게이트 = (a) 코드 상수 `policy/icloud.py: TRASH_UNLOCK_VERIFIED`(08 §9.1 의 네 조건을 두 Mac 에서 확인·09 §12 에 기록한 뒤 이 상수를 `True` 로 바꾸는 리뷰된 변경으로만 — M5 종료 기준) **그리고** (b) 설정 `icloud.allow_trash`(기본 `true`, 소유자가 끌 수 있음). 둘 중 하나라도 거짓이면 “해제 전” 행.
- **항목 단위 결정만**: iCloud 동기화 항목의 `trash` 는 `decision.set ITEM_ID...`(사용자, 항목 지정)로만 기록된다. `decision.set --group` 은 이 항목들을 `trash` 대상에서 건너뛰고 `W_PROTECTED_SKIPPED{reason:icloud_synced}` 를 낸다. 학습 규칙(`actor=rule`, 07)은 iCloud 동기화 항목에 `trash` 결정을 만들지 않는다(제안 표시는 가능, 결정은 사람이 항목 단위로). 또한 iCloud 휴지통 결정은 `decisions.channel ∈ {cli, app}`(실효 채널, 리뷰 #5)일 때만 받는다 — `decision.set` 과 계획 검증(08 §4.2 V3) 양쪽에서 검사하고, skill/mcp 에서 온 결정은 `E_PROTECTED{owner_only}`.
- 실행 시 재검증: 연산 직전 파일이 dataless 가 됐거나 게이트가 거짓이면 그 연산은 `skipped`(`E_PROTECTED`).
이유: 휴지통 이동이 다른 기기의 삭제로 전파되고, 기기 밖 복사는 다운로드를 유발.
예외 1: `active_repo` 안이라도 `category=dev_cache`(재생성 가능한 산출물) 항목은 항목 단위 `trash` 허용(06 §3.1, 목록은 04).
결정: 환자 자료는 `trash` 를 허용하지 않는다. 이유: 조제·처방 관련 기록의 법정 보존 가능성 — 폐기는 DayClose 밖에서 사람이 한다.
결정: 앱·패키지·저장소·로그인 항목(`subject_type != file/dir`)은 MVP~M5 에서 `acknowledge`, `keep_always`, `defer` 만. 앱 삭제는 범위 밖(PRD 비목표).

### 10.2 실행 불변식 (executor)
1. `plan.state = approved` 이고 `approvals.plan_hash == plans.plan_hash == (저장된 plan_operations 행에서 다시 계산한 해시)` 이며 §10.3 의 감사 교차 검사·유효 기간을 통과할 때만 실행(08 §7.1 G1~G10).
2. 연산 직전 사전조건 재검증: 원본이 존재하고 (dev, inode, size, mtime_ns) 가 계획 시점과 같다. 다르면 해당 연산 `skipped`, 항목 `stale`(`closed_reason=subject_changed` 또는 `subject_gone`), `E_STALE`. 완료 후 목적지의 (dev, inode, mtime_ns) 를 `post_*` 로 기록(undo·recover 의 동일성 증명).
3. 연산 직전 `policy` 재평가: 지금 `protection` 이 해당 동작을 허용하지 않으면 `E_PROTECTED`. **undo 도 같다**(리뷰 #15): 되돌릴 파일의 현재 위치가 활성 저장소 안의 git 추적 파일이거나 지금 vault 자산이면 `undo_failed` + `E_PROTECTED`.
4. 목적지가 존재하면 덮어쓰지 않는다(`E_DEST_EXISTS`). 이름 충돌 회피는 계획 단계에서 결정된 경로로만.
5. 영구 삭제 없음. `trash` = 볼륨별 휴지통으로 rename. 볼륨 간 `move` 와 `archive` 만 복사→검증(크기+SHA-256, 디렉터리는 매니페스트 해시, 08 §4.6)→원본 제거.
6. 연산 상태를 `running` 으로 커밋한 **뒤** 파일시스템 호출, 완료 후 `done` 커밋. 크래시 시 `plan.recover` 가 실제 상태로 정합화.
7. `DAYCLOSE_SANDBOX` 가 설정되면 그 경로 밖의 src/dst 는 무조건 `E_SANDBOX_VIOLATION`.

### 10.3 승인 프로토콜 (상세·근거는 08 §6, §7.1 — 08 이 정한 내용을 계약으로 옮김)

원칙: **에이전트는 승인을 요청할 수 있지만 수행할 수는 없다.** 승인 = 사람이 특정 `plan_id` + 전체 `plan_hash`(64자)를 확인한 기록.

1. **수단은 core 가 환경으로 고른다**(호출자가 고르는 플래그 없음, 08 §6.2). 순서: ① **유효한 샌드박스**(§10.4) + `DAYCLOSE_TEST_APPROVE=1` → `test` ② 유효한 샌드박스인데 TEST_APPROVE 없음 → `E_APPROVAL_DENIED`(테스트 중 실제 대화상자 금지) ③ 채널 `app` 이고 요청에 `app_signature` 가 있으며, `core.app_key` 로 등록된 앱 공개키로 `"dayclose.approve.v1\n" + device_id + "\n" + plan_id + "\n" + plan_hash` 에 대한 **Secure Enclave ECDSA P-256 서명 검증이 성공**(서명마다 Touch ID/로그인 암호, 08 §6.5) → `app_button`. 부모 프로세스 경로·번들 ID 검사는 쓰지 않는다(가짜 번들로 흉내 낼 수 있어 보장처럼 보이게 하지 않기 위함). 키 미등록·서명 없음·검증 실패면 거부하지 않고 다음 순서로 넘어간다. 실기기 검증(09 §12 V11) 전에는 앱이 서명 없이 보내므로 앱 경로는 **`native_dialog` 로 저하**되는 것이 기본. (미정 설계 G11, V11 결과로 결정: M7 의 `dayclose-native confirm` 이 앱의 Secure Enclave 키를 함께 쓸 수 없으면 `core.app_key` 는 헬퍼용 **두 번째 공개키**를 같은 사람 확인 절차로 등록받아야 한다 — 지금 정하지 않는다) ④ `/dev/tty` 를 직접 열 수 있고 **에이전트 환경 표식이 없으며**, (표식 없는 pty 에서 도는 에이전트 — Codex 등 — 의 실기기 확인 전까지, 리뷰 B3) **GUI 세션이 없음**(`common/fsmeta.has_gui_session()` 거짓) → `cli_tty`(표준입력 파이프 무시, 화면의 해시 앞 8자를 입력). GUI 세션이 있으면 TTY 가 있어도 ⑤ 로 간다 ⑤ 그 외(TTY 없음, 에이전트 표식 있음, Skill) → `native_dialog`.
2. **에이전트 표식이 있으면 TTY 수단을 쓰지 않고 대화상자로 강제**한다(표식 목록은 `plan/approval.py` 상수, 예 `CLAUDECODE`; 10 §8.5 와 함께 유지). 대화상자는 기본 버튼 “취소”, 120초 후 거부, 요약 텍스트는 `osascript` 의 `--` 뒤 argv 로 전달(주입 방지). GUI 세션이 없으면(ssh·launchd) `E_APPROVAL_DENIED{reason:no_gui}`.
3. **채널 `schedule` 허용 목록**: `scan.run`, `review.summary` 만. 그 밖의 모든 명령(승인·실행 포함)은 `api` 진입 시 core 가 `E_PROTECTED{channel_not_allowed}` 로 거부한다 — 스케줄러의 선한 행동에 기대지 않는다. 채널 `mcp` 의 `plan.approve` 는 `E_APPROVAL_DENIED{channel_not_allowed}`(MCP 는 애초에 노출도 안 함).
   **MCP 노출 원칙**: 에이전트는 읽기, 결정 기록·취소, 스캔 실행, 계획 생성, 승인 **요청**까지 할 수 있지만, 파일을 바꾸거나 DayClose 가 **무엇을 보고 어떻게 보호하는지**(범위·설정·보호 규칙·다시 묻지 않기·학습 규칙·키·보안 자산 기록)를 바꾸는 명령은 쓸 수 없다. 새 명령은 이 한 문장으로 분류한다.
   - MCP 비노출(M8, 10 §9.3): `plan.approve`, `plan.apply`, `plan.undo`, `plan.recover`, `core.app_key`, `core.init`, `config.set`, `root.add`, `root.remove`, `root.set`, `rule.add`, `rule.remove`, `suppression.add`, `suppression.remove`, `policy.accept`, `policy.reject`, `ai.key.set`, `ai.key.remove`, `ai.classify`, `vault.annotate`, 그리고 전송 계층 `core.serve`, `mcp.serve`, 중복인 `core.schema`.
   - MCP 노출: 모든 읽기 명령(`*.list`, `*.show`, `config.get`, `core.version`, `core.doctor`, `review.summary`, `vault.health`, `report.daily`, `ai.status`, `policy.suggestions`, `audit.list`) + `scan.run`, `review.close`, `decision.set`, `decision.undo`, `plan.create`, `plan.cancel`.
   - Skill(에이전트가 CLI 채널로 실행)도 같은 목록을 따른다: SKILL.md 의 `allowed-tools` 사전 허용은 ‘노출’ 목록의 CLI 형태로만 하고, 승인 요청(`plan approve`)은 사전 허용하지 않는다(실행 시 사용자 화면에 확인이 뜸).
4. 시스템 도구(`osascript` 등)는 절대경로·root 소유 확인·호출마다 새로 만든 고정 환경으로 실행(§6 `run_tool`) — PATH 의 가짜 `osascript` 로 “승인”을 흉내 낼 수 없게.
4a. **기기 검사**(08 §7.11): `app_meta.device_id == config.device_id`, `app_meta.host_uuid_sha256 ==` 지금 계산한 값, 계획 정규 객체의 `device_id == app_meta.device_id`. 하나라도 다르면 `plan.create`/`plan.approve`/`plan.apply`(`--dry-run` 포함)/`plan.undo`/`plan.recover` 는 파일 시스템을 건드리기 **전에** `E_DEVICE_MISMATCH` 로 거부(+`W_DEVICE_MISMATCH`). 읽기 명령은 경고만.
4b. **소유자 전용 명령**(리뷰 #19a): 실효 채널이 `skill`·`mcp` 이면 core 가 직접 `E_PROTECTED{owner_only}` 로 거부한다 — `config.set` 의 `protection.*`, `vault.*`, `scan.exclude_globs`, `icloud.*`, `ai.allow_external` 키; `rule.remove`; `suppression.add`·`suppression.remove`; `root.add`·`root.remove`·`root.set`; `policy.accept`·`policy.reject`; `core.init`. 이로써 MCP 비노출 목록의 해당 부분이 Skill(CLI) 채널에서도 강제된다. **각 명령이 생기는 마일스톤에서 함께 적용**한다: M1a — 실효 채널 계산(에이전트 표식 승격)과 `core.init`, 보호 키에 대한 `config.set`, `root.add`·`root.remove` 거부 / M2 — `rule.remove`, `suppression.add`·`suppression.remove`, `root.set`, 4c 의 `keep_always` 낮춤 / M6 — `policy.accept`·`policy.reject`.
   **샌드박스와 승격**(결정 2026-11-24): 승격(실효 채널 계산)은 **항상** 한다. 테스트와 코딩 에이전트는 에이전트 표식(예 `CLAUDECODE`)이 있는 환경에서 CLI 를 돌리므로, **유효한 샌드박스(§10.4) 안에서만** 표식 승격으로 생긴 `skill` 에 대해서는 소유자 전용 거부를 건너뛴다. 단 호출이 `--channel skill|mcp` 를 **명시**하면 샌드박스 안에서도 거부한다(거부 경로 테스트용). 샌드박스 밖에는 우회가 전혀 없다 — 실제 데이터에서 표식이 있으면 항상 거부. 샌드박스는 실제 홈·기본 상태 디렉터리를 가리킬 수 없으므로(§10.4) 이 예외로 실제 보호 규칙이 약해지지 않는다.
4c. **에이전트의 `keep_always`**(리뷰 #19b): 실효 채널이 `skill`·`mcp` 인 `decision.set --action keep_always` 는 `keep` 으로 기록하고 `W_OWNER_ONLY_DOWNGRADED` 를 낸다 — 에이전트는 suppression 을 만들 수 없다.
5. **실행 시 재검증**: `plan.apply` 는 저장된 `plan_operations` 행에서 해시를 다시 계산해 `plans.plan_hash`·`approvals.plan_hash` 와 비교하고, `approvals.request_id` 와 같은 `request_id` 의 `audit_log` 행(`command='plan.approve'`, `ok=1`)이 있어야 하며(감사 교차 검사), 승인 후 **24시간** 이내여야 한다(유효 기간, 재개 포함). `method=test` 승인은 실행 시에도 유효한 샌드박스(§10.4)와 `DAYCLOSE_TEST_APPROVE=1` 이 다시 있어야 유효.
5a. **기본이 아닌 `DAYCLOSE_HOME`**(리뷰 #19c): 기본 경로가 아닌 상태 디렉터리를 쓰면 모든 승인 문구(대화상자, `cli_tty` 요약, 앱 화면 — 앱은 03 의 계약)에 그 경로를 별도 줄로 보여 준다(다른 DB 에는 소유자의 보호 규칙이 없을 수 있으므로).
6. 사람 확인을 기다리는 동안 쓰기 잠금을 잡지 않고, 확인 후 잠금을 잡아 상태·해시를 다시 검사한 뒤 기록(08 §6.1).
7. **iCloud 전파 확인**(C11): 계획에 `plan_operations.icloud_propagates=1` 연산(iCloud 동기화 경로의 `trash`)이 하나라도 있으면, 모든 승인 수단의 확인 화면(대화상자 문구, `cli_tty` 요약, 앱 승인 화면)에 “N개 파일은 iCloud 를 통해 다른 기기에서도 삭제됩니다”를 **별도 줄로** 보여 주고, 승인 행에 `approvals.icloud_ack=1` 을 기록한다. `icloud_propagates` 는 `plan_hash` 정규 객체에 들어가므로 승인이 그 사실을 덮는다 — 이것이 core 쪽 보장이다(`app_button` 은 서명이 그 해시를 덮음). 경고 줄은 `cli_tty`·`native_dialog` 에서는 core 가 직접 넣고, 앱 승인 화면에서는 03 의 계약으로 표시한다(core 는 앱 화면을 볼 수 없음). `plan.apply` 는 그런 연산이 있는데 `icloud_ack=0` 이면 `E_APPROVAL_REQUIRED{reason:icloud_ack_missing}`. 별도 확인 단계를 두지 않고 승인 자체가 확인이다(결정: 승인 화면이 하나여야 사람이 실제로 읽는다).

**무인 기기(Mac mini, 08 §6.7)**: 승인에는 그 Mac 앞의 사람이 필요하다. `native_dialog` 와 `app_button` 은 그 Mac 의 화면(또는 화면 공유)에서만 응답할 수 있다. SSH 세션에서는 사람이 TTY 로 직접 `dayclose plan approve` 를 입력하는 `cli_tty` 만 가능하다(에이전트 표식이 없을 때). GUI 세션이 없으면 대화상자는 `no_gui` 로 거부된다. 다른 Mac 에서 승인하는 경로는 없다(서명이 `device_id` 에 묶임, 기기 간 통신은 비목표). 따라서 Mac mini 에서는 예약 스캔 결과가 쌓이고, 소유자가 그 Mac 앞(또는 화면 공유)에 있을 때 검토·승인한다.

**잔여 위험(닫지 못함, 08 §19.3)**: 같은 사용자 권한으로 도는 적대적 프로세스는 (a) DB 의 승인 행과 감사 행을 함께 위조하고, (b) 서명 승인이 동작하지 않는 동안(저하 모드) 대화상자로 넘어간 앱 경로를 아래 (c) 방식으로 누르고, (c) 접근성·화면 제어 권한(원격 지원 도구, 에이전트의 computer-use 기능 포함)으로 대화상자의 “승인”을 누르거나 `cli_tty` 창에 8자를 입력하고(08 §6.8 — 서명 승인이 동작하는 기기의 `app_button` 은 Touch ID/암호가 필요해 이 위험이 없다), (d) `script(1)` 로 TTY 를 만들고 표식 없는 환경에서 8자를 입력할 수 있다. 에이전트 표식은 우회 가능한 휴리스틱이다. 이런 프로세스는 DayClose 없이도 파일을 지울 수 있으므로 위협 경계 밖이며, 통제는 Skill/MCP 계약과 에이전트 도구의 권한 확인에 의존한다. 강화 계획(리뷰 #2 #4 #13 B2):
- **M5**: core 의 서명 검증·`core.app_key`(register 는 실효 채널 `app` 만). **앱 서명은 M5 부터** — V11 을 통과한 Mac 에서 앱은 서명해 보내고, 서명 전에 화면에 표시한 연산으로 `plan_hash` 를 다시 계산해 다르면 서명하지 않는다. 앱은 기동마다 `app-key show` 의 지문을 자기 Secure Enclave 공개키와 비교해 다르면 경고하고 폐기를 제안한다.
- **M7**(M6 의 `dayclose-native` 필요): `native_dialog` 의 구현을 `dayclose-native confirm`(LocalAuthentication `.deviceOwnerAuthentication`)으로 교체. confirm 은 앱 승인과 **같은 페이로드에 대한 Secure Enclave 서명**을 돌려주고 core 가 등록된 `core.app_key` 공개키로 검증한다 — 헬퍼의 stdout 성공 표시는 근거가 아니다. 승인 경로의 헬퍼는 **앱 번들 안의 것만**(`DAYCLOSE_NATIVE`·`~/.local/bin` 무시). osascript 는 대체 수단으로만 남는다. **V11 을 통과한 Mac 에서는** confirm 헬퍼가 없거나 서명을 검증할 수 없으면 osascript 로 내려가지 않고 `E_APPROVAL_DENIED{confirm_unverified}` 로 거부한다(가짜·누락 헬퍼가 약한 수단으로의 저하를 유도하지 못하게). V11 미통과 Mac 은 osascript 대화상자 유지.
- **C12 의 예외**: M7 이후에도 `cli_tty` 는 GUI 세션이 없는 경우(SSH)에만 남으며, 이것이 “승인할 때마다 인증”(C12)의 문서화된 유일한 예외다.

### 10.4 테스트 샌드박스
- 모든 파일 조작 테스트는 `tmp_path` 아래 `home/`(DAYCLOSE_HOME)과 `user/`(가짜 홈: Downloads, Desktop …)를 만들고 `DAYCLOSE_SANDBOX=<tmp_path>` 를 설정한다.
- `conftest.py` 의 autouse 픽스처가 `DAYCLOSE_HOME`·`DAYCLOSE_SANDBOX` 미설정 상태에서 core 를 부르는 테스트를 실패시킨다.
- **샌드박스 유효성**(리뷰 #1): `DAYCLOSE_SANDBOX` 가 설정되면 core 는 시작 시 다음을 **모두** 확인하고, 하나라도 아니면 `E_SANDBOX_VIOLATION` 으로 시작을 거부한다(테스트 환경변수만 무시하고 계속하지 않는다).
  1. `realpath(DAYCLOSE_SANDBOX)` 가 사용자 임시 디렉터리(`os.confstr("CS_DARWIN_USER_TEMP_DIR")` 의 realpath) 또는 `/private/tmp` 아래에 있다.
  2. 그것이 실제 홈(`pwd.getpwuid(os.getuid()).pw_dir` — `$HOME` 아님), `/Volumes`, 기본 `DAYCLOSE_HOME`(`~/Library/Application Support/DayClose`)과 같지 않고 그 조상도 아니다.
  3. 그 안에 표식 파일 `.dayclose-sandbox` 가 있다(테스트 픽스처가 만든다).
  4. `DAYCLOSE_HOME` 이 샌드박스 안에 있다.
  이 검사는 `common/paths.sandbox_status()` **한 함수**가 하며, 모든 명령 시작 시(전송 계층 공통 진입점) 호출된다. 결과는 `valid` / `invalid(reason)` / `off` 이고, 다른 모듈은 환경변수를 직접 보지 않고 이 결과만 쓴다.
  통과하면 `sys.addaudithook` 가드를 설치해 샌드박스 밖 경로에 대한 쓰기·이름변경·삭제 시도를 예외로 막는다(11 §2). `DAYCLOSE_TEST_APPROVE`·`DAYCLOSE_TEST_NOW`·`DAYCLOSE_TEST_FAULT` 와 `method=test` 승인은 **유효한 샌드박스에서만** 효력이 있다. 거부 사례마다 테스트 1개. M1a 부터.
- 샌드박스 전용 환경 변수(샌드박스 밖에서는 무시): `DAYCLOSE_TEST_APPROVE=1`(test 승인), `DAYCLOSE_TEST_NOW`(고정 시각, `common/clock`), `DAYCLOSE_TEST_FAULT=<name>:<n>[:exit|enospc|eio|eperm|exdev]`(체크포인트 `<name>` 의 `<n>` 번째 도달 시 장애 주입, 기본 `exit`. 체크포인트 이름 목록은 08 §15.3 소유, 11 이 사용). 모두 `sandbox_status()==valid` 일 때만 읽는다.
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
- 루트 중첩(“데스크탑 및 문서 폴더” iCloud 동기화로 경로가 겹치는 경우, 리뷰 B1): 수집기는 심볼릭 링크를 따라가지 않고, 순회 중 만나는 하위 디렉터리의 **`(dev, inode)` 가 다른 활성 루트의 `(dev, inode)` 와 같으면** 바깥 루트 순회에서 건너뛴다(경로 비교가 아님 — 같은 디렉터리가 두 경로로 보이는 경우까지 막기 위함). 같은 `(dev, inode)` 루트는 한 번만 순회. M1b 부터.
- iCloud 경로 접근도 EPERM 이면 `W_TCC_DENIED`.
- iCloud 여부는 항상 “저장된 실효값 OR 양성 실시간 신호”(§10.1 예외 2)로 판정한다. `root set --icloud-synced no` 는 신호가 없을 때의 기본값만 바꾼다.

## 11. 오류 모델

Python: `common/errors.py`

```
DayCloseError(code: str, message: str, details: dict = {}, retryable: bool = False)
  ├─ UsageError            E_USAGE
  ├─ NotFoundError         E_NOT_FOUND, E_NOT_INITIALIZED
  ├─ StateError            E_INVALID_STATE, E_STALE, E_DEST_EXISTS, E_APPROVAL_MISMATCH, E_UNDO_IMPOSSIBLE
  ├─ SafetyError           E_PROTECTED, E_APPROVAL_REQUIRED, E_APPROVAL_DENIED, E_SANDBOX_VIOLATION,
  │                        E_PATH_OUTSIDE_ROOTS, E_AI_BLOCKED_SENSITIVE, E_DEVICE_MISMATCH
  ├─ EnvironmentError_     E_PERMISSION, E_TCC_DENIED, E_VOLUME_UNAVAILABLE, E_VOLUME_TIMEOUT, E_TOOL_MISSING,
  │                        E_CONFIG_INVALID, E_AI_DISABLED, E_ARCHIVE_TARGET_MISSING
  ├─ LockError             E_LOCKED (retryable)
  ├─ PartialError          E_PARTIAL (data 동반)
  ├─ CancelledError        E_CANCELLED (종료 코드 130)
  └─ InternalError         E_INTERNAL, E_DB_CORRUPT, E_DB_MIGRATION
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
| `E_APPROVAL_DENIED` | 승인되지 않음. `details.reason`: `cancelled`, `timeout`, `no_gui`, `untrusted_tool`, `channel_not_allowed`, `no_human_channel_in_sandbox`, `confirm_unverified`(V11 통과 Mac 에서 confirm 헬퍼 누락·서명 검증 실패) |
| `E_PROTECTED` | 보호 정책상 허용 안 되는 동작. `details.reason` 예: 보호 등급 코드, `icloud_synced`, `dataless`, `secret_content`, `contains_protected_rule`(디렉터리 아래 보호 규칙), `owner_only`(에이전트 채널에서 소유자 전용 명령·결정), `contains_secret_content`, `hardlink_to_protected`, `channel_not_allowed`(채널 `schedule` 이 허용 목록 밖 명령을 부름, §7) |
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
| `E_UNDO_IMPOSSIBLE` | 되돌릴 수 없음 — 상태 충돌(종료 4). `details.reason`: `trash_emptied`(휴지통을 비움·외부 정리 도구), `gone`, `edited_after_move` 등(08 §11). 휴지통 접근이 EPERM 이면 이 코드가 아니라 `E_TCC_DENIED`(retryable) |
| `E_CANCELLED` | 사용자가 취소함(SIGINT, serve 요청 취소). `plan.apply` 의 신호 중단은 이 코드가 아니라 `E_PARTIAL`+resumable |
| `E_DEVICE_MISMATCH` | 이 DB 는 다른 Mac(또는 재설치된 Mac)에서 만들어짐 — 파일 변경 명령 거부(§10.3 4a). 안전 정책 거부(종료 5) |
| `E_DB_MIGRATION` | 마이그레이션 실패(백업에서 복원 안내) |
| `E_DB_CORRUPT` | `PRAGMA integrity_check` 실패 |
| `E_INTERNAL` | 예상치 못한 예외 |

경고 코드: `W_PERMISSION_SKIPPED`, `W_TCC_DENIED`, `W_ROOT_UNAVAILABLE`, `W_TOOL_MISSING`, `W_PROTECTED_SKIPPED`, `W_PARTIAL_SCAN`, `W_TRUNCATED`, `W_CONFIG_UNKNOWN_KEY`, `W_DATALESS_SKIPPED`, `W_HASH_SKIPPED_LARGE`, `W_FIELD_KEY_UNAVAILABLE`, `W_DEVICE_MISMATCH`, `W_AI_REQUEST_FAILED`(공급자 시간 초과·연결·HTTP 오류, 다른 배치는 계속), `W_AI_OUTPUT_REJECTED`(응답 검증 실패, 반영 없음), `W_OWNER_ONLY_DOWNGRADED`(에이전트 채널의 `keep_always` 를 `keep` 으로 기록), `W_ARCHIVE_UNENCRYPTED`(`archive.root` 가 암호화되지 않은 볼륨 — `config.set archive.root`, `doctor`, 보관 연산이 있는 `plan.create`/승인 화면에서. 차단하지 않음, C13).

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
│   ├── serve.schema.json         # serve --stdio 요청/응답·이벤트 (10 §3)
│   └── fixtures/                 # 명령별 예시 응답 (Python·Swift 공용), fixtures/serve/
├── core/                         # Python core (uv 프로젝트)
│   ├── pyproject.toml  uv.lock  .python-version
│   ├── src/dayclose/
│   │   ├── __main__.py
│   │   ├── common/   config/   store/ (migrations/0001_*.sql …)
│   │   ├── collect/  intel/    vault/    policy/   review/   plan/   executor/
│   │   ├── ai/ (M6)
│   │   ├── api/ (schemas/ = 명령별 data JSON Schema 원본, 10 §4.1)   cli/   serve/ (M4)   mcp/ (M8)
│   └── tests/
│       ├── conftest.py           # 샌드박스 강제 픽스처
│       ├── unit/  integration/  safety/  contract/
│       └── fixtures/             # 가짜 파일 생성기 (실제 비밀 아님)
├── app/                          # M4
│   ├── DayClose.xcodeproj
│   ├── DayClose/                 # 앱 타깃 소스
│   ├── DayCloseKit/              # SwiftPM: Package.swift, Sources/, Tests/
│   └── DayCloseUITests/          # 앱 UI 테스트 타깃 (11)
├── native/                       # M6: dayclose-native (SwiftPM 실행파일)
├── skill/                        # M8: SKILL.md, references/, agents/openai.yaml (Claude Code·Codex 공용, 10 §8)
└── scripts/                      # 개발 보조 스크립트 (샌드박스 생성 등)
```

## 15. 다른 명세가 따라야 할 계약

### 15.1 공유 이름 (이 목록 밖의 이름을 새로 만들지 말고, 필요하면 02/06을 먼저 고친다)

- 모듈: `common`, `config`, `store`, `collect`, `intel`, `vault`, `policy`, `review`, `plan`, `executor`, `ai`, `api`, `cli`, `serve`, `mcp`. (`archive` 모듈은 2026-11-24 삭제 — 보관은 executor 의 `archive` 연산) Swift: `DayCloseKit`, `DayClose`, `DayCloseScheduler`, `dayclose-native`.
- 명령 ID: §5.3 표. 봉투 필드: `schema`, `command`, `ok`, `data`, `warnings`, `error{code,message,details,retryable}`, `meta{request_id,core_version,contract_version,db_schema_version,device_id,duration_ms}`.
- ID 접두사: §5.1. 오류·경고 코드: §11. 종료 코드: §5.5.
- 항목 JSON 필드: §5.6 (`allowed_actions`, `blocked_reasons`, `origin_root_kind`, `is_dataless`, `preview_policy`, `ai_policy`, `protection`, `sensitivity`, `suggestion{action,dest,source,reason,confidence}`).
- enum·상태·테이블·컬럼: `06-DATA-MODEL.md` §3~§5 (특히 `item_state`, `decision_action`, `plan_state`, `op_type`, `op_state`, `protection_class`, `sensitivity`, `item_category`, `subject_type`, `vault_asset_kind`).
- 환경 변수: `DAYCLOSE_HOME`, `DAYCLOSE_SANDBOX`, `DAYCLOSE_TEST_APPROVE`, `DAYCLOSE_TEST_NOW`, `DAYCLOSE_TEST_FAULT`(뒤 셋은 샌드박스 전용), `DAYCLOSE_NATIVE`(core 가 `dayclose-native` 를 찾는 경로 — 앱/스케줄러가 앱 번들 안 경로로 설정, 09. **승인 경로에서는 무시**하고 앱 번들 안의 헬퍼만 쓴다 — §10.3).
- 경로: `~/Library/Application Support/DayClose/`, `~/Library/Logs/DayClose/core.log`, `~/Library/Caches/DayClose/`, `state.lock`, `config.toml` 키(§9).
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
