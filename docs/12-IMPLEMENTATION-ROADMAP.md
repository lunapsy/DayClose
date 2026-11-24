# 12 — 구현 로드맵 (IMPLEMENTATION ROADMAP)

> CONTEXT 턴1의 6단계를 마일스톤 M0~M8 로 나눈다. 턴4에 따라 보호 정책·샌드박스 가드·executor 전용 변경 규칙은 M1~M2 부터 존재한다.
> 각 마일스톤은 **실행 가능한 결과물**로 끝나야 한다. 다음 마일스톤은 이전 마일스톤의 종료 기준을 모두 만족한 뒤 시작한다.

| 단계 (CONTEXT 턴1) | 마일스톤 |
|---|---|
| 1단계 Python CLI, 파일 스캔, SQLite 스냅샷, 변경 감지 | M1(M1a, M1b), M2, M3 |
| 2단계 SwiftUI 검토 화면, 이미지 갤러리, Quick Look | M4 (← 첫 MVP 완성) |
| 3단계 개별·일괄 승인, 안전한 파일 이동, 휴지통, 복구 | M5 |
| 4단계 AI 문맥 분류, 사용자 선호도 학습 | M6 |
| 5단계 메뉴바, 자동 실행, 일일 정리 알림 | M7 |
| 6단계 Claude·Codex Skill, MCP (NAS 연동은 2026-11-24 비목표로 제외) | M8 |

개발 기기: Mac mini(2026-11-24). 사용 기기: MacBook·Mac mini 각자 독립 설치(02 §8.1).

공통 종료 기준(모든 마일스톤): `AGENTS.md` 의 완료 정의(DoD) 충족 — 테스트 녹색, 안전 회귀 스위트 통과, 실제 사용자 파일 미접촉, 명세와 구현 불일치 시 명세 먼저 수정.

---

## M0 — 명세와 저장소 골격 (현재)

- 산출물: `AGENTS.md`, `README.md`, `.gitignore`, `docs/01~13`.
- 실행 결과: 없음(문서).
- 종료 기준: 13개 문서 존재, 02·06 의 공유 계약(02 §15)과 다른 문서 간 이름 불일치 0(총괄 에이전트 교차 검토), PRD 미결 사항 목록이 소유자에게 전달됨.
- 근거 문서: 전부.

## M1 — Core 골격 + 파일 스냅샷·변경 감지 (M1a + M1b, 각각 한 세션 분량)

범위를 의도적으로 좁힌다: 리뷰 항목·정책·vault 없음. “스캔하고 무엇이 바뀌었는지 JSON 으로 말해 주는 CLI” 까지. 독립 리뷰(2026-11-24) 결정으로 두 단계로 나눈다. 02·06 의 명령 표에서 `M1` 은 M1a/M1b 를 합친 것이며, 아래 표가 어느 쪽인지 정한다.

### M1a — 골격·계약·저장소·루트 (스캔 없음)

산출물:
1. `core/` uv 프로젝트: `pyproject.toml`(이름 `dayclose`, `requires-python >=3.13`, 엔트리포인트 `dayclose = "dayclose.cli.main:main"`), `.python-version`(3.14), dev 의존성 `pytest`, `ruff`, `mypy`, `jsonschema`. 런타임 의존성은 `tomli-w`(config set)만 — 02 §3 목록 내.
2. `dayclose/common/`: `errors.py`(02 §11 계층·코드), `envelope.py`(02 §5.4), `ids.py`(접두사 변환), `clock.py`(주입 가능한 시계, `DAYCLOSE_TEST_NOW`), `paths.py`(`DAYCLOSE_HOME` 해석, `probe(path, timeout)`, **`state.lock` 생성·획득 함수** — 02 §6, `system_path`), `logging.py`(JSON Lines + `RedactingFilter` 기본 패턴), `proc.py`(`run_tool`: 절대경로 허용 목록·고정 환경·타임아웃 — M1 에서는 `defaults` 만 사용).
3. `dayclose/config/`: 기본값, `config.toml` 로드/저장, `config get/set/list`.
4. `dayclose/store/`: 연결(PRAGMA), 마이그레이션 러너(체크섬·백업·user_version), `migrations/0001_core.sql`(06 §5.1 그대로).
5. `dayclose/api/` + `dayclose/cli/`: `version`, `init`(스캔하지 않음, 필드 암호화 키 만들지 않음), `doctor`, `config *`, `root list/add/remove`(`root add` 의 `--icloud-synced auto|yes|no`, `--max-depth` 생략 시 04 의 kind 별 기본값). 쓰기 잠금은 `api` 가 `common/paths` 의 잠금 함수를 호출.
   - `doctor`(M1 범위): 루트 접근성(`ok|tcc_denied|timeout|missing`), DB 무결성(`integrity_check`), 파일 권한(0700/0600), **DB 와 설정의 `device_id` 불일치**(`W_DEVICE_MISMATCH`). host UUID 검사는 M5. 루트 경로가 없는 것은 루트 접근성 결과(`missing`)이지 기기 불일치가 아니다.
6. 실효 채널 계산(에이전트 표식 승격)과 소유자 전용 거부(02 §10.3 4b): `core.init`, 보호 키에 대한 `config set`, `root add/remove` → `E_PROTECTED{owner_only}`. 유효한 샌드박스에서는 표식 승격만으로는 거부하지 않고 `--channel skill|mcp` 를 명시하면 거부. 테스트: 샌드박스 밖+표식 → 거부, 샌드박스 안+표식 → 통과, 샌드박스 안+명시 채널 → 거부.
6a. 샌드박스 가드(02 §10.4): 샌드박스 유효성 검사(사용자 임시 디렉터리 아래, 실제 홈·`/Volumes`·기본 `DAYCLOSE_HOME` 과 같거나 그 조상이 아님, 표식 파일 `.dayclose-sandbox` 존재 — 아니면 `E_SANDBOX_VIOLATION`), `DAYCLOSE_HOME` 이 샌드박스 밖이면 거부, `sys.addaudithook` 쓰기 가드. 거부 사례마다 테스트 1개.
7. `contracts/envelope.schema.json` + `contracts/fixtures/` 에 `core.version.ok.json`, `root.list.ok.json`, `error.E_NOT_INITIALIZED.json`, `error.E_SANDBOX_VIOLATION.json`.
8. 테스트: `tests/conftest.py`(샌드박스 픽스처 — 표식 파일 생성, `Path.home()` 패치), 단위(마이그레이션, 봉투, ID, 설정, 샌드박스 유효성), 통합(subprocess 로 CLI 호출), 계약(봉투 스키마), 안전(`test_no_mutation_outside_executor.py` 정적 검사 — 쓰기 허용 모듈 목록에 `common/paths.py` 포함, executor 는 비어 있으므로 “어디에도 없음”).

실행 결과(샌드박스):
```bash
cd core
export DAYCLOSE_SANDBOX="$(mktemp -d)" DAYCLOSE_HOME="$DAYCLOSE_SANDBOX/home"
touch "$DAYCLOSE_SANDBOX/.dayclose-sandbox"
mkdir -p "$DAYCLOSE_SANDBOX/user/Downloads"
uv run dayclose init --no-default-roots --json
uv run dayclose root add "$DAYCLOSE_SANDBOX/user/Downloads" --kind downloads --json
uv run dayclose root list --json
uv run dayclose doctor --json
DAYCLOSE_SANDBOX="$HOME" uv run dayclose version --json   # E_SANDBOX_VIOLATION
```

종료 기준:
- `uv run pytest` 녹색, `uv run ruff check`, `uv run mypy src` 오류 0.
- FR-CORE-001, 004, 007 의 AC, FR-CORE-002 의 루트 등록 로직(샌드박스 가짜 홈), FR-CORE-005 의 M1 범위.
- 샌드박스 유효성 거부 사례(임시 디렉터리 밖, 실제 홈과 같음/조상, `/Volumes`, 기본 `DAYCLOSE_HOME` 포함, 표식 없음) 각각 `E_SANDBOX_VIOLATION`.
- 실제 `~` 아래 파일 접근 0 (conftest 가드).

### M1b — fs 수집기·스캔·변경 목록

산출물:
1. `dayclose/collect/fs.py`: 루트별 `os.scandir` 워커, 제외 글롭(루트 기준 상대경로), 패키지 디렉터리 처리, 루트 중첩 제거(하위 디렉터리의 `(dev, inode)` 를 다른 루트들과 비교 — 02 §10.6), dataless/`.icloud` 자리표시자는 메타데이터만(02 §10.6), (dev,inode,size,mtime_ns) 비교 → `file_entries` 갱신 + `file_events`(created/modified/deleted/moved). 엔트리·이벤트는 `settle_seconds` 와 무관하게 항상 기록(settle 은 M2 의 항목 생성만 늦춤).
2. 루트 단위 `icloud_synced`/`icloud_synced_source` 를 매 스캔 계산(04 §1.1; mode·실시간 신호 규칙은 02 §10.1). 항목별 `allowed_actions` 는 M2.
3. 명령: `scan run/list/show`, `change list`.
4. 계약 픽스처: `scan.run.ok.json`, `change.list.ok.json`.
5. 테스트: fs diff 단위, 속성 기반(`hypothesis`) 트리 변경 시퀀스, 성능 측정, iCloud 루트 판정(`test_root_icloud_override_precedence`, `assumed_default`).

실행 결과(데모, M1a 의 샌드박스에 이어서):
```bash
uv run dayclose scan run --json
echo hi > "$DAYCLOSE_SANDBOX/user/Downloads/a.txt"
uv run dayclose scan run --json          # stats.created == 1
mv "$DAYCLOSE_SANDBOX/user/Downloads/a.txt" "$DAYCLOSE_SANDBOX/user/Downloads/b.txt"
uv run dayclose scan run --json          # stats.moved == 1
uv run dayclose change list --json
```

종료 기준:
- 테스트·린트·타입 검사 녹색.
- FR-CORE-003, 006, 008(스캔 부분) 의 AC.
- 변경 없는 재스캔 시 이벤트 0, 1만 파일 샌드박스 웜 스캔 ≤ 2초(측정값 기록).

근거 문서(M1 전체): 02(§3, §5, §6, §8, §10.4, §10.6, §11, §13), 06(§1, §5.1, §7), 04(증분 스캔 절), 11(샌드박스 규약, §10 M1a/M1b 표).
담당 영역: Architecture(계약·store, M1a), File Intelligence(fs 수집기, M1b), QA(픽스처·안전 테스트).

## M2 — 리뷰 모델 + 보호 정책 + 프로젝트 문맥 (CLI 결산 완성)

산출물:
- `migrations/0002_review.sql`(06 §5.2).
- `collect/git.py`: `projects.roots` 아래 저장소 탐지, 활성 판정, dirty/stale branch 수.
- `policy/`: `protection_class`·`sensitivity` 계산(내장 규칙 + 설정 + 사용자 규칙), 환자 패턴(파일명·로컬 텍스트 주민번호), `allowed_actions` + `blocked_reasons`(루트 iCloud 판정값은 M1b 가 계산한 것을 사용 + 실시간 신호), suppression 매칭(보안·환자 항목 제외).
- 로컬 텍스트 주민등록번호 탐지(리뷰 #7): `policy` 소유, `common` 의 제한 읽기 함수 사용(`vault` 의존 없음), 대상은 05 §2.2 클래스 C 텍스트 확장자, 상한 `scan.content_scan_max_bytes`, dataless 재확인·기준선 규칙 준수. 04 §2.6 의 읽기 지점 목록에 포함.
- 해시 저장 규칙(리뷰 #19d): `vault/signals.name_matches`(순수 함수, 05)를 M2 에 먼저 구현하고, 여기에 걸리는 파일은 `sha256` 을 저장하지 않음(마이그레이션 직전 백업에도 남지 않게). collect 단계 로그에는 경로를 남기지 않음.
- `intel/`: 카테고리 판정, 그룹 키, SHA-256 중복, 설치 파일 휴리스틱(`/Applications` 단순 조회), 프로젝트 매칭 휴리스틱.
- `review/`: 항목 생성 규칙(04), 상태 기계(06 §4.1 전이 표 전부), `ensure_session`(세션 최초 생성 트랜잭션에서 이월), 보류, `keep_always`, 리포트, `estimated_review_minutes`.
- `api` 의 `agent_view`(에이전트 채널 투영, 02 §5.6).
- 소유자 전용 거부 확장(02 §10.3 4b·4c): `rule remove`, `suppression add/remove`, `root set` → `E_PROTECTED{owner_only}`, 에이전트 채널의 `keep_always` → `keep` + `W_OWNER_ONLY_DOWNGRADED`.
- 명령: `review summary/close`, `group list/show`, `item list/show`(`--deferred`, `--carried`), `decision set/undo/list`, `project list`, `rule *`(`--source`), `suppression list/add/remove`, `root set`(`--icloud-synced`), `report daily`, `core schema`.
- `common/crypto.py` + Keychain 키 생성(`init` 이 아니라 **첫 암호화 필드 저장 시**), `decisions.note_enc`.
- 계약 픽스처: `review.summary`, `item.list`, `decision.set`, 오류 `E_PROTECTED`, `E_INVALID_STATE`.

실행 결과: 샌드박스 시나리오 스크립트 `scripts/demo-m2.sh` — 가짜 하루(스크린샷 5, DMG 2, 중복 3, 프로젝트 파일 4, 환자 패턴 파일 1) 생성 → scan → `review summary` 로 그룹과 지표 → 결정 → 다음 날짜로 이월 확인 → `report daily --format md`.

종료 기준:
- 06 §4.1 의 모든 허용 전이 테스트 + 모든 비허용 전이가 `E_INVALID_STATE` 인 테스트.
- FR-DR-001~009, FR-SO-001~004, FR-AM-003, FR-PM-001~003 AC 통과.
- 결정 명령 전후 샌드박스 파일 트리 해시 불변(안전 테스트).
- 환자 패턴 파일이 리포트·로그에 실명 경로로 나오지 않음.

근거 문서: 04, 06(§4, §5.2), 07(suppression·보호 규칙 절), 08(보호 등급 재평가 규칙), 10(명령 data 스키마), 11.
담당: File Intelligence(intel·git), Security(policy 환자/보호), AI·Memory(suppression), QA.

## M3 — Secure Vault 읽기 전용 + App Manager 인벤토리 (CLI MVP 완성)

산출물:
- `migrations/0003_vault_inventory.sql`(06 §5.3).
- `vault/`: 확장자·이름·위치·매직바이트·내용 패턴 탐지, `gitleaks` 통합(`--redact`, 결과에서 Match/Secret 즉시 폐기), X.509 파싱(`cryptography`), 지문·중복, 권한 검사, git 추적 여부, 마스킹 이름, 발견 사항 생성·해소.
- `collect/apps.py`(Info.plist + `mdls` 마지막 사용일), `collect/brew.py`(`brew info --installed --json=v2`), `collect/login_items.py`(LaunchAgents/Daemons plist), 개발 캐시 탐지(주간), 미사용 앱(월간).
- 명령: `vault list/show/health/annotate`(`--backup`, `--status`), `app list`, `package list`.
- 보존 규칙(06 §8): `missing` 자산 365일, `resolved` 발견 사항 180일.
- 0003 마이그레이션 예외(06 §7): 적용 직후 텍스트·이름 신호 파일의 `sha256` NULL 처리 → `pre-v3` 백업 삭제 → 새 백업.
- 비밀 픽스처 생성기(`tests/fixtures/secrets.py` — 실행 시 생성하는 가짜 키·가짜 인증서, 저장소에 실제 비밀 커밋 금지).

실행 결과: `scripts/demo-m3.sh` — 가짜 `.p8`, `.p12`, 확장자 없는 SSH 키, 저장소에 추적된 `.env`, 23일 남은 인증서, 같은 키 3곳 복사, 시드 의심 파일 생성 → scan → `vault health` 가 각 발견 사항을 보고.

종료 기준:
- FR-SV-001~008, FR-AM-001~002, 004~006 AC 통과.
- 안전 회귀: 비밀 픽스처 전체 스캔 후 `core.log`, DB 덤프(`.dump`), 모든 stdout 에 비밀 원문 0(11 문서의 누출 스캐너).
- gitleaks 미설치 환경(PATH 제거)에서도 녹색(경고만).
- **CLI 읽기 전용 MVP**: 소유자가 두 기기 각각의 실제 `~`에서 `scan run` + `review summary` + `vault health` 를 수동 실행해 볼 수 있는 상태(읽기 전용이므로 허용; 실행은 소유자가 직접).

근거 문서: 05, 04(앱/brew/login 수집 절), 09(앱 인벤토리 소스), 06(§5.3, §6), 11.
담당: Security(vault), macOS(앱·로그인 항목 소스), File Intelligence(dev cache), QA(누출 스캐너).

## M4 — SwiftUI 검토 앱 (첫 MVP 완성: Daily Review + Visual Review + Secure Vault 읽기 전용)

산출물:
- `dayclose serve --stdio`(02 §5.4 요청/응답, 요청 단위 잠금), 계약 테스트.
- `app/DayCloseKit`(SwiftPM): 봉투·모델 `Codable`, `CoreClient`(프로세스 기동·재기동, 요청 ID, 타임아웃), `contracts/fixtures` 디코딩 테스트.
- `app/DayClose.xcodeproj` + 앱 타깃: 메인 결산, 그룹 상세(갤러리/리스트/비교), Quick Look(`QLPreviewPanel`), 썸네일(`QLThumbnailGenerator`, 캐시 정책), 키보드 단축키, Secure Vault 화면, 설정(루트·보호 규칙·suppression), core 미설치/버전 불일치 화면.
- 결정은 기록되지만 실행 버튼은 “실행 기능은 다음 버전” 으로 비활성(MVP 는 파일 무변경).
- `scan.run` 취소(serve 요청 취소 → `E_CANCELLED`), `contracts/serve.schema.json`, `app/DayCloseUITests`.

실행 결과: `xcodebuild -project app/DayClose.xcodeproj -scheme DayClose build` 로 빌드한 앱이 샌드박스 `DAYCLOSE_HOME` (앱 실행 인자 `--home`) 의 데모 데이터로 전체 검토 플로우 수행.

종료 기준:
- FR-VR-001~006 AC, NFR-PERF-002, NFR-A11Y-001 키보드 부분.
- `swift test --package-path app/DayCloseKit` 녹색, 모든 계약 픽스처 디코딩 성공.
- 보안 자산·환자 항목 열람 후 캐시 디렉터리에 파생물 0.
- 앱 코드에 파일 변경 API(`FileManager.removeItem/moveItem/trashItem`, `rename`) 호출 0 (정적 검사).
- 실기기 검증(09 §12, 두 Mac 각각): V1, V2, V3, V7, V9, V16, V17(“데스크탑 및 문서” iCloud 동기화를 `scan_roots.icloud_synced` 로 판정할 수 있는지 — 안 되면 `root set --icloud-synced` 수동 지정 + `assumed` 기본값을 유지), V22(“데스크탑 및 문서” 동기화가 켜진 상태에서 겹치는 루트가 같은 파일을 두 번 기록하지 않는지) 결과 기록.

근거 문서: 03, 09(프로세스 수명관리, core 탐색), 10(serve 프로토콜), 11(UI 테스트), 02 §4.
담당: macOS(앱), Integration(serve·CoreClient), QA.

## M5 — 안전 실행: 승인, 휴지통, 이동, 보관, undo, 복구

산출물:
- `migrations/0004_execution.sql`(06 §5.4).
- `plan/`: 결정 → 연산, 목적지 충돌 회피 이름 결정, `plan_hash`(08 정규화, 저장된 연산 행에서 재계산), 승인(02 §10.3: core 의 수단 선택, 에이전트 표식 → 대화상자 강제, 앱 승인은 Secure Enclave 서명 검증, 감사 교차 검사, 24시간 유효), 테스트 승인 가드.
- `plan_operations` 의 `src_kind`, `create_dirs_json`, `post_*`, `details_json`, `undo_state=undoing`(06 §5.4), `executing` 계획의 `plan.cancel`, 신호로 멈춘 apply 의 `E_PARTIAL`+resumable 과 재개.
- 서명 승인(08 §6.5): core 의 `core.app_key register/show/revoke`(register 는 실효 채널 `app` 에서만), `plan.approve` 의 `app_signature` 검증. **앱 서명은 M5 에서 시작** — V11 을 통과한 Mac 에서는 앱이 서명해 보내고, 서명 전에 화면에 표시한 연산으로 `plan_hash` 를 다시 계산해 다르면 서명하지 않는다(리뷰 B2). V11 미통과 Mac 은 서명 없이 보내 `native_dialog` 로 저하. 앱은 기동마다 `app-key show` 지문과 자기 Secure Enclave 공개키를 비교해 다르면 경고·폐기 제안.
- 보호 강화(리뷰 #3 #5 #6 #15 #19a~c): 디렉터리 연산의 하위 보호 규칙 검사(`E_PROTECTED{contains_protected_rule}`), iCloud 휴지통 결정 채널 제한(`cli`/`app`), `sensitivity=secret` 의 move/archive 금지(`secret_content`), undo 의 보호 재평가, iCloud 휴지통·앱 키 등록의 채널 검사, 기본이 아닌 `DAYCLOSE_HOME` 의 승인 문구 표시.
- Codex 등 표식 없는 pty(리뷰 B3): 실기기 확인 전까지 `cli_tty` 는 GUI 세션이 없을 때만. 종료 기준에 실기기 검증 V23(Codex 가 pty 로 돌 때 에이전트 표식이 보이는지) 결과 기록 — 확인되기 전까지 GUI 세션이 있으면 `cli_tty` 를 제공하지 않는 상태 유지.
- 기기 검사(`host_uuid_sha256`, `E_DEVICE_MISMATCH`)를 파일 변경 명령 전부에(08 §7.11).
- iCloud 휴지통(FR-EX-008, C11): `plan_operations.icloud_propagates`, `approvals.icloud_ack`, 승인 화면 전파 경고, 그룹·규칙 결정 제외, 설정 `icloud.allow_trash`, 코드 게이트 `TRASH_UNLOCK_VERIFIED`(기본 거짓).
- `archive.root` 비암호화 볼륨 경고(`W_ARCHIVE_UNENCRYPTED`, C14).
- `executor/`: 사전조건·보호 재검증, 볼륨별 휴지통 경로, 같은 볼륨 rename / 볼륨 간 복사→검증→원본 제거, 연산별 커밋, `plan recover`, `plan undo`(충돌 정책).
- 보관 폴더: `config.archive.root` 하나(로컬/외장, FR-AB-001). 외장(`/Volumes/External`) 접근은 프로브 경유. NAS·원격 대상 없음.
- 앱: 계획 검토·승인 화면, 실행 진행, 결과·되돌리기(FR-VR-007).
- 명령: `plan create/show/list/approve/apply/cancel/undo/recover`, `audit list`.

실행 결과: 샌드박스에서 결정 → 계획 → 승인(test 방식) → 실행 → 휴지통(샌드박스 내 가짜 `.Trash`) 확인 → undo 로 원복. 앱에서 같은 플로우.

종료 기준:
- FR-EX-001~007, FR-AB-001 AC.
- 장애 주입 스위트(11 문서): 연산 중 SIGKILL, 목적지 존재, 원본 변경, 볼륨 분리, 휴지통 비움 후 undo, 보호 등급 변경 후 apply — 모두 파일 유실 0.
- 정적 검사: executor 외 변경 호출 0, 원본·임시 파일 제거는 `fsops.remove_verified_source`, `fsops.remove_own_artifact` 두 함수에서만.
- 승인 무결성 테스트: 에이전트 표식 환경, PATH 의 가짜 `osascript`, root 소유 아닌 `osascript`, 위조 서명/미등록 키, DB 에 직접 넣은 승인 행, 만료 승인, 복사된 DB(host UUID 불일치) — 모두 거부.
- 실기기 검증(09 §12, 두 Mac 각각): V8(휴지통 TCC), V11(Secure Enclave 가능 여부 — M7 승인 강화 방식 결정 근거), V18~V21(08 §9.1 의 iCloud 휴지통 네 조건 — 아래 해제 검증의 근거).
- **소유자 직접 수행**: V8·V18·V19 는 실제 파일을 움직이므로 **소유자가 직접, 소유자가 만든 시험 파일로만** 수행한다(09 §12). 에이전트는 이 항목을 수행하지 않고 절차 안내와 결과 기록 양식 준비만 한다. 따라서 **M5 는 에이전트만으로 종료할 수 없다** — 소유자가 수행하고 결과를 09 §12 에 기록해야 종료된다.
- 소유자 첫 실사용 전 체크리스트(08 문서) 서명.
- **iCloud 휴지통 해제 검증**: 08 §9.1 의 네 조건을 MacBook·Mac mini 에서 확인하고 09 §12 에 기기별로 기록. 모두 통과하면 `TRASH_UNLOCK_VERIFIED=True` 로 바꾸는 리뷰된 변경과 그 상태의 FR-EX-008 테스트가 M5 종료 조건. 하나라도 실패하면 결과를 기록하고 게이트는 거짓으로 둔 채(차단 유지) 소유자에게 보고 — 이 경우 M5 는 “검증 결과 기록”으로 종료하고 해제는 재검증 후로.

근거 문서: 08, 06(§4.4~4.5, §5.4), 03(계획 화면), 11, 02 §10.
담당: Security·Architecture(executor), macOS(승인 대화상자·앱 화면), QA(장애 주입).

## M6 — AI 문맥 분류 + 사용자 선호 학습

산출물:
- `migrations/0005_ai_memory.sql`(06 §5.5).
- `policy/` 학습: 반복 결정 → `policy_rules.suggested`, 수락/거절, 규칙 일치 시 제안 자동 채움(`suggestion_source='rule'`), “습관 항목 묶음” 그룹.
- `ai/`: 공급자 none/ollama/anthropic/openai, 전송 게이트, 출력 스키마 검증, `ai_requests` 감사. 기본 비활성.
- `native/dayclose-native`: Vision OCR CLI(JSON 출력). `file_text` 암호화 저장, OCR 기반 민감도 상향, `rename` 연산(08 문서 확장).
- `rename` 결정 동작(06 `decision_action`)과 `rename` 연산 활성화(M6 전까지 `blocked_reasons.rename = not_yet_available`).
- `policy accept/reject` 의 소유자 전용 거부(02 §10.3 4b).
- 명령: `policy suggestions/accept/reject`(`prl_` ID), `ai status/classify`(`--dry-run`), `ai key set/remove`(stdin).
- 설정 `[ai]` 추가 키·`[policy]` 절(02 §9), 경고 `W_AI_REQUEST_FAILED`·`W_AI_OUTPUT_REJECTED`. 공급자는 `urllib` 직접 호출(SDK 없음).
- 실기기 검증: 09 §12 V12.

실행 결과: 샌드박스에서 같은 패턴 결정 반복 → 규칙 제안 → 수락 → 다음 날 해당 그룹이 “습관 항목” 으로 한 번에 묶여 표시. ollama 로컬 모델(설치된 경우)로 프로젝트 그룹 제안.

종료 기준: FR-SO-005~006, FR-PM-004~005 AC, NFR-PRIV-002(AI 꺼짐 시 네트워크 0 — 소켓 차단 테스트), 게이트 회귀 테스트.
근거 문서: 07, 04(OCR·참조 탐지 절), 05(민감 판정 공유), 08(rename), 11.
담당: AI, Security(게이트 검토), macOS(native OCR), QA.

## M7 — 메뉴바, 자동 실행, 일일 알림, TCC

산출물:
- 앱 메뉴바(미결 수, 지금 검토), `DayCloseScheduler` 헬퍼, `SMAppService` LaunchAgent `com.dayclose.scheduler`, 잠자기 후 보충 실행, 알림(UserNotifications, [지금 검토]/[나중에]). 일일 알림에 열린 `expiring_soon` 인증서 포함, 7일 이하면 별도 알림(FR-MI-003).
- FDA 안내 흐름, `doctor` 의 launchd 컨텍스트 진단.
- 결정: core 배포 방식(앱 번들 동봉 Python vs `~/.local/bin/dayclose`) 확정 — 09 문서에 기록.
- 로컬 서명 고정: Developer ID·공증 없이 고정 로컬 인증서로 앱·헬퍼 서명(02 §4). 재빌드 후 FDA 유지 여부 실기기 검증.
- **승인 강화**(02 §10.3 잔여 위험 대응, 명시 항목, M6 의 `dayclose-native` 필요): `native_dialog` 의 구현을 `dayclose-native confirm`(LocalAuthentication, Touch ID/로그인 암호)으로 교체. V11 통과 Mac 에서 헬퍼가 없거나 검증 실패면 `E_APPROVAL_DENIED{confirm_unverified}`(osascript 로 저하하지 않음). confirm 은 앱 승인과 **같은 페이로드에 대한 Secure Enclave 서명**을 돌려주고 core 가 `core.app_key` 공개키로 검증한다(stdout 의 성공 표시는 근거가 아님, 리뷰 #2). 승인 경로에서 헬퍼는 **앱 번들 안의 것만** 쓰고 `DAYCLOSE_NATIVE`·`~/.local/bin` 은 무시. 이후 `cli_tty` 는 GUI 세션이 없는 경우(SSH)에만 남고, 이것이 C12(“승인할 때마다 인증”)의 문서화된 예외다. 결과에 따라 08 §6 과 02 §10.3 을 먼저 갱신.
- 실기기 검증(09 §12, 두 Mac 각각): V4, V5, V6, V10, V13, V14, V15.

실행 결과: MacBook·Mac mini 각각에서 21:00 예약 실행 → 알림 → 클릭 시 앱 결산 화면. FDA 는 기기마다 따로 부여·검증. Mac mini 에서 `/Volumes/External` 루트가 있고 FDA 가 없을 때 제한 시간 내 경고로 종료.
종료 기준: FR-MI-001~004 AC, NFR-REL-001, “셸 실행 vs launchd 실행” 비교 테스트 절차(09) 결과 기록, “재빌드 → FDA 유지” 검증 결과 기록(실패 시 대응 절차를 09 에 명시).
근거 문서: 09, 03(메뉴바·알림 화면), 11.
담당: macOS, Integration, QA.

## M8 — Skill, MCP

산출물:
- `skill/SKILL.md`(Claude Code·Codex 공용): 조회 → 결정 → 계획 → 사람 승인(네이티브 대화상자) 흐름.
- `dayclose mcp serve`: 02 §10.3-3 의 노출 목록만(읽기·결정 기록/취소·스캔·계획 생성·취소). 비노출 목록과 Skill `allowed-tools` 도 같은 원칙.

범위 밖(2026-11-24): NAS·SMB 보관, age 암호화 업로드, Vault 원격 백업(FR-AB-002/003, FR-SV-009 삭제).

실행 결과: Claude Code 세션에서 Skill 로 오늘의 결산 요약 → 계획 생성 → 소유자가 대화상자로 승인 → 실행.
종료 기준: FR-AG-002~003 AC, MCP 비노출 명령 테스트.
근거 문서: 10, 08(승인 흐름), 11.
담당: Integration, Security(비노출 명령 검토), QA.

---

## 의존성 요약

```
M1a ─▶ M1b ─▶ M2 ─▶ M3 ─▶ M4 (MVP) ─▶ M5 ─▶ M6 ─▶ M7 ─▶ M8
```
M7 은 M6 에 의존한다(승인 강화가 M6 의 `dayclose-native` 를 씀 — 리뷰 #12). M7 의 메뉴바·알림 작업은 M6 과 겹쳐 진행할 수 있지만, M7 종료는 M6 종료 뒤. M8 은 M5(실행)와 M7(앱 번들·서명) 필요.
