# 11 — 테스트 계획과 인수 기준 (TEST PLAN)

> 상태: 상세 명세. 이름·경로·코드·enum 은 `02-ARCHITECTURE.md`, `06-DATA-MODEL.md` 를 따른다. FR/NFR ID 는 `01-PRD.md`, 마일스톤 종료 기준은 `12-IMPLEMENTATION-ROADMAP.md`.
> 각 기능의 **동작**(실행 알고리즘 08, vault 탐지 05, 수집·분류 04, 학습·게이트 07, macOS 연동 09, 화면 03, 명령 인터페이스 10)은 해당 문서가 정한다. 이 문서는 그것을 **어떻게 검증하는지**와 **무엇이 통과해야 다음 단계로 가는지**를 정한다.
> 최우선 원칙(AGENTS.md §3): 어떤 테스트도 실제 사용자 경로를 건드리지 않는다. 모든 파일 조작은 임시 샌드박스에서만.

---

## 1. 테스트 계층

| 계층 | 위치 | 대상 | 실행 | 머지 조건 |
|---|---|---|---|---|
| 단위 | `core/tests/unit/` | 순수 함수·모듈(diff, ID, 봉투, 정책 매트릭스, 해시 정규화, 투영, 커서) | `uv run pytest tests/unit` | 필수 |
| 계약 | `core/tests/contract/` | 봉투·명령별 `data` JSON Schema, 픽스처, 종료 코드, serve/MCP 전사 | `uv run pytest tests/contract` | 필수 |
| 통합 | `core/tests/integration/` | 샌드박스 트리 위에서 CLI(서브프로세스)·serve·MCP 를 실제로 실행, 장애 주입 | `uv run pytest tests/integration` | 필수(`perf` 표식 제외) |
| 안전 | `core/tests/safety/` | 안전 불변식(§4), 정적 검사, 누출 스캐너, 실행기 속성 기반 테스트 | `uv run pytest tests/safety` | **필수·차단**(NFR-SAFE-001) |
| 성능 | `core/tests/integration/perf/` (`@pytest.mark.perf`) | NFR-PERF-*, NFR-DISK-001 | `uv run pytest -m perf` | 마일스톤 종료 시 |
| Swift 단위 | `app/DayCloseKit/Tests/` | `Codable` 디코딩(모든 픽스처), `CoreClient` | `swift test --package-path app/DayCloseKit` | M4~ 필수 |
| Swift UI | `app/DayCloseUITests/` (XCUITest 타깃) | 키보드 흐름, 미리보기 정책, 승인 버튼 바인딩, 접근성 | `xcodebuild test -scheme DayClose -destination 'platform=macOS'` | M4~ 마일스톤 종료 시 |
| 수동 실기기 | §9 체크리스트 | TCC/FDA, 알림, Quick Look, launchd, 외장 볼륨 | 소유자 직접 | 마일스톤 종료 시 |

결정: 02 §14 의 테스트 디렉터리(`unit/ integration/ safety/ contract/`)를 늘리지 않는다. 속성 기반 테스트는 대상에 따라 `unit/`(순수 로직)·`safety/`(실행기 불변식)에, 장애 주입은 `integration/faults/` 하위에, 성능은 `integration/perf/` 하위에 둔다. UI 테스트 타깃 `DayCloseUITests` 는 02 §14 의 `app/` 아래 새 타깃이다(02 에 이름 추가 요청 — §11).

### 1.1 pytest 표식(marker)

| 표식 | 의미 | 기본 실행 |
|---|---|---|
| `perf` | 성능 측정(수 분) | 제외 |
| `hdiutil` | 디스크 이미지로 두 번째 볼륨을 만드는 테스트(볼륨 간 이동, 볼륨 분리) | 포함(macOS 에서만; 실패 시 건너뜀 아닌 실패) |
| `needs_git` | 실제 `git` 필요 | 포함(`git` 은 개발 전제) |
| `needs_gitleaks` | 실제 `gitleaks` 와의 통합 | `gitleaks` 있을 때만, 없으면 **사유 있는** skip |
| `nightly` | Hypothesis 대량 예제·장시간 장애 주입 | 제외 |

pytest 설정(`core/pyproject.toml` 의 `[tool.pytest.ini_options]`): `addopts = "--strict-markers -m 'not perf and not nightly'"`, `faulthandler_timeout = 120`(행 탐지 — 외부 플러그인 없이 pytest 내장 faulthandler), `.pytest_cache`·`.hypothesis/` 는 gitignore.

### 1.2 개발 의존성

02 §3 의 core 개발 의존성은 `pytest`, `ruff`, `mypy` 뿐이다. 이 계획은 두 개를 더 요구한다 — 02 §3 목록 수정 후 추가(§11).

| 패키지 | 용도 | 대안을 쓰지 않는 이유 |
|---|---|---|
| `hypothesis` | 실행기·상태 기계·투영·해시 속성 기반 테스트(§5) | 브리프의 필수 계층. 직접 구현은 축소(shrinking)가 없어 실패 재현이 어렵다. |
| `jsonschema` | 계약 테스트(draft 2020-12 검증) | 직접 구현 시 스키마 검증 자체가 테스트 대상이 된다. |

테스트 전용 런타임 도구(저장소 밖, macOS 기본 제공): `/usr/bin/hdiutil`, `/usr/bin/xattr`, `/usr/bin/chflags`, `git`. 샌드박스 생성기만 사용하고 core 코드는 쓰지 않는다.

---

## 2. 실제 사용자 경로 차단 (샌드박스 강제)

AGENTS.md §3.1, 02 §10.4 의 규칙을 **세 겹**으로 강제한다. 하나라도 우회되면 안전 스위트가 실패해야 한다.

### 2.1 1겹: `conftest.py` 픽스처

`core/tests/conftest.py`

| 픽스처 | 범위 | 동작 |
|---|---|---|
| `_real_home_snapshot` | session, autouse | 패치 전에 실제 홈(`pwd.getpwuid(os.getuid()).pw_dir`)과 저장소 경로를 기록. 이후 가드의 금지 목록 기준. |
| `sandbox` | function, autouse | `tmp_path/{home,user,sys,bin,vol}` 생성. env `DAYCLOSE_SANDBOX=tmp_path`, `DAYCLOSE_HOME=tmp_path/home`, `HOME=tmp_path/user`, `CFFIXED_USER_HOME=tmp_path/user`, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, `PATH=tmp_path/bin:<원래 PATH>`. `Path.home`·`os.path.expanduser` 패치. `DAYCLOSE_TEST_APPROVE` 는 **기본 미설정**(승인이 필요한 테스트만 `approve_in_tests` 픽스처로 켬). |
| `_guard_env` | function, autouse | 테스트 시작·끝에 `DAYCLOSE_HOME`·`DAYCLOSE_SANDBOX` 가 `tmp_path` 아래인지 검사. 테스트가 이를 지우거나 바꾸면 실패. |
| `_audit_guard` | function, autouse | 2겹 감사 훅의 테스트 프로세스 쪽을 켠다(§2.2). |
| `_no_network` | function, autouse | `socket.connect`·`socket.getaddrinfo` 감사 이벤트에서 AF_UNIX 외 연결 시도 → 실패(NFR-PRIV-002). AI 공급자 테스트는 `allow_loopback(port)` 로 로컬 가짜 서버만 허용. |
| `cli` | function | `run_cli(*argv, input=None, env=None) -> CliResult(returncode, envelope, stdout, stderr)`. 항상 `--json --home $DAYCLOSE_HOME` 을 붙여 `sys.executable -m dayclose` 를 서브프로세스로 실행. 모든 stdout/stderr 를 세션 수집기(`leak_corpus`)에 추가(§4.4). |
| `day` | function | 샌드박스 생성기로 표준 하루(§3.3 `day_m2`)를 만들고 매니페스트 반환. |
| `clock` | function | in-process 테스트용 고정 시계(`common/clock` 주입). 서브프로세스에는 아래 주의. |

주의(`clock`): 02 는 `common/clock` 주입만 정하고, 서브프로세스 CLI 에 고정 시각을 전달하는 방법이 없다. 통합 테스트는 날짜 경계(FR-DR-002)·이월(FR-DR-006)을 서브프로세스로 검증해야 하므로 **환경 변수 `DAYCLOSE_TEST_NOW`(샌드박스에서만 유효, `DAYCLOSE_TEST_APPROVE` 와 같은 가드)** 가 필요하다. 02 §15.1 경로·환경 변수 목록에 추가 요청(§11). 추가 전까지 날짜 관련 테스트는 in-process(`api` 직접 호출 + `clock` 주입)로만 작성한다.

### 2.2 2겹: 감사 훅(audit hook) 가드 — core 자신에 내장

결정: `DAYCLOSE_SANDBOX` 가 설정되면 core 는 시작 시(`cli/main`, `serve`, `mcp` 진입점) `common/paths.install_sandbox_guard()` 로 `sys.addaudithook` 을 설치한다. 테스트 프로세스(`_audit_guard`)와 서브프로세스 CLI 가 같은 함수를 쓴다. 이유: 서브프로세스에는 conftest 가 닿지 않는다.

| 감사 이벤트 | 규칙 |
|---|---|
| `open`(쓰기 모드), `os.rename`, `os.replace`(→`os.rename`), `os.remove`, `os.rmdir`, `os.mkdir`, `os.chmod`, `os.chflags`, `os.utime`, `os.truncate`, `os.link`, `os.symlink`, `shutil.rmtree`, `shutil.copyfile`, `shutil.copytree`, `shutil.move` | 모든 경로 인자가 `realpath` 기준 `DAYCLOSE_SANDBOX` 아래가 아니면 `SafetyError(E_SANDBOX_VIOLATION)` |
| `open`(읽기), `os.listdir`, `os.scandir` | 샌드박스 ∪ 읽기 허용 목록(파이썬 `sys.prefix`/`sys.base_prefix`, 가상환경, 저장소 `core/src`·`contracts/`, `/usr`, `/System`, `/Library/Frameworks`, `/dev/null`, `/dev/tty`, `/dev/urandom`, 임시 디렉터리 루트) 밖이면 위반. 특히 **실제 홈, `/Volumes`, `/Applications`** 는 읽기도 금지. |
| `subprocess.Popen` | 실행 파일이 `run_tool` 허용 목록(02 §6) + 테스트 도구(`hdiutil`, `xattr`, `chflags` — 테스트 프로세스에서만)가 아니면 위반 |
| `socket.connect` | §2.1 `_no_network` 와 같음 |

- 가드는 감사 이벤트가 없는 호출(`os.stat`, `os.lstat`)은 막지 못한다 — 3겹(경로 재매핑)이 담당.
- `DAYCLOSE_SANDBOX` 가 설정됐는데 `DAYCLOSE_HOME` 이 그 밖이면 core 는 시작 단계에서 `E_SANDBOX_VIOLATION`(종료 5). 테스트 `test_sandbox_home_outside_sandbox_rejected`.
- 가드 자체 테스트(`safety/test_sandbox_guard.py`): 샌드박스 모드에서 실제 홈 아래 경로(존재하지 않는 임의 이름이라도)로 `open('w')`·`scandir`·`rename` 을 시도하면 즉시 예외, 파일시스템에는 아무 일도 없음(대상 경로는 실제로 만들지 않고 `realpath` 계산만으로 거부되는지 확인 — 거부가 실패하면 쓰기가 일어날 수 있으므로 대상은 `/nonexistent-dayclose-guard-probe/…` 같은 생성 불가 경로를 쓴다).

### 2.3 3겹: 시스템 위치 재매핑

collector·executor 가 쓰는 **고정 시스템 경로**는 모두 `common/paths.system_path(name)` 한 함수로 얻는다. 샌드박스 모드에서는 샌드박스 아래로 재매핑된다. 이 규칙이 04·08·09 의 구현 요구 사항이다(§11 에 각 문서 확인 요청).

| name | 실제 | 샌드박스 |
|---|---|---|
| `applications` | `/Applications` | `$SANDBOX/sys/Applications` |
| `user_applications` | `~/Applications` | `$SANDBOX/user/Applications` |
| `launch_agents_user` | `~/Library/LaunchAgents` | `$SANDBOX/user/Library/LaunchAgents` |
| `launch_agents_global` | `/Library/LaunchAgents` | `$SANDBOX/sys/Library/LaunchAgents` |
| `launch_daemons` | `/Library/LaunchDaemons` | `$SANDBOX/sys/Library/LaunchDaemons` |
| `user_trash` | `~/.Trash` | `$SANDBOX/user/.Trash` |
| `volume_trash(vol)` | `<vol>/.Trashes/<uid>` | 볼륨이 샌드박스 디스크 이미지면 그 아래(`$SANDBOX/vol/<n>/.Trashes/<uid>`) |
| `volumes_root` | `/Volumes` | `$SANDBOX/vol` |
| `tool_dir` | (없음 — 절대경로) | `$SANDBOX/bin` (가짜 도구 우선) |

외부 도구 해석(보안 요구 사항, 결정): 프로덕션에서 `run_tool` 은 시스템 도구를 **절대경로**로만 실행한다(`/usr/bin/osascript`, `/usr/bin/defaults`, `/usr/bin/mdls`; `git`·`brew`·`gitleaks` 는 `init`/`doctor` 가 찾은 절대경로를 설정·DB 에 고정). `PATH` 앞쪽에 가짜 `osascript` 를 둔 에이전트가 `native_dialog` 승인을 위조하는 경로를 막기 위함. 샌드박스 모드에서만 `tool_dir` 의 가짜 도구가 우선한다. 02 §6·§10.3-4 에 반영됨. 테스트 `test_fake_osascript_on_path_not_executed`(§4.1).

### 2.4 정적 검사로 보강

- `safety/test_tests_do_not_reference_real_paths.py`: `core/tests/**/*.py`, `scripts/*` 에서 문자열 리터럴 `"/Users/"`, `"~/"`(재매핑 표 테스트 제외 목록), `"/Volumes/"`, `Path.home()` 직접 사용(conftest 제외)을 AST 로 찾아 실패.
- `safety/test_conftest_guard_present.py`: `conftest.py` 에서 `sandbox`·`_audit_guard`·`_no_network` 가 `autouse=True` 인지 AST 로 확인(가드 비활성화 방지).

---

## 3. 샌드박스 픽스처 생성기

### 3.1 인터페이스

위치: `core/tests/fixtures/sandbox.py`(라이브러리), `core/tests/fixtures/secrets.py`(가짜 비밀 생성, 02 §14·AGENTS.md §3.6), `scripts/make-sandbox.py`(데모용 CLI 래퍼 — `scripts/demo-m2.sh`·`demo-m3.sh` 가 사용).

```python
def build_sandbox(root: Path, preset: str, *, seed: int = 0, now: datetime) -> Manifest: ...
# preset: "minimal" | "day_m2" | "vault_m3" | "apps_m3" | "exec_m5" | "odd_names" | "perf_100k"

@dataclass
class Manifest:
    root: Path
    files: list[FileSpec]            # 생성한 모든 엔트리
    secrets: list[SecretSpec]        # 생성한 가짜 비밀 값(메모리에만; 디스크에 별도 기록하지 않음)
    expectations: list[Expect]       # 오라클: path → 기대 category/protection/sensitivity/vault_kind/finding/group_key
    def expect(self, **filters) -> list[Expect]: ...
    def tree_digest(self) -> str: ...   # §4.1 의 트리 해시
```

- 결정론: `seed` 로 내용·이름 생성, 시각은 `now` 기준 상대값으로 `os.utime` 설정. 같은 `(preset, seed, now)` → 같은 트리(inode 제외).
- `Manifest.secrets` 는 디스크에 쓰지 않는다. 결정: 누출 스캐너가 같은 프로세스에서 매니페스트를 받는다. 서브프로세스 데모(`make-sandbox.py`)는 매니페스트를 출력하지 않는다(가짜라도 비밀 형태 문자열을 터미널에 남기지 않음).
- 생성기는 core 를 import 하지 않는다(테스트 대상과 오라클 분리). 단 시드 구문 단어는 05 가 정한 단어 목록 모듈을 읽는다(탐지기와 같은 목록을 써야 하므로 — 유일한 예외).

### 3.2 트리 구성 요소

모든 경로는 `$SANDBOX/` 기준. `user/` = 가짜 홈.

| 구성 | 생성 내용 | 검증 대상 |
|---|---|---|
| downloads | `user/Downloads/`: 최소 유효 PDF 3, 실제 ZIP(`zipfile`, 내부 3개 항목) 1, JPEG/PNG(작은 유효 이미지) 4, `report-final.pdf`·`report-final (1).pdf`, `kMDItemWhereFroms` xattr(`/usr/bin/xattr -wx`, binary plist; 호스트 `example.com`, 쿼리 포함 URL) 2개 | FR-CORE-003, 카테고리(04), `where_from_host` 에 쿼리·경로 미저장 |
| desktop | `user/Desktop/`: 문서 5(docx/xlsx/pptx 는 최소 OOXML ZIP), 임시 파일(`~$report.docx`, `untitled.tmp`), 스크린샷 3 | 04 카테고리·임시 파일 규칙 |
| screenshots | `user/Pictures/Screenshots/`(가짜 `defaults` 가 이 위치를 반환) 에 `스크린샷 2026-11-24 오후 2.02.11.png` 형식 12개(시각 분산, NFC·NFD 혼합 2개) | FR-CORE-002(별도 위치 등록), `screenshot:day` 그룹, `personal` 민감도 |
| installers | `Foo-2.3.1.dmg`(끝 512바이트 `koly` 트레일러), `Bar.pkg`(`xar!` 매직), `Baz.dmg`(대응 앱 없음) + `sys/Applications/Foo.app/Contents/Info.plist`(`CFBundleIdentifier=com.example.foo`, `CFBundleShortVersionString=2.3.1`), `Bar.app` | FR-SO-001(Foo·Bar 는 trash 제안, Baz 는 제안 없음) |
| duplicates | 같은 내용 3개(Downloads·Desktop·Documents, mtime 다름), 64MB 초과 희소 파일 2개(`os.truncate` — 디스크 실사용 거의 0, 내용 동일) | FR-SO-002(최신 keep 제안), `W_HASH_SKIPPED_LARGE` |
| git repo (활성) | `user/dev/PL-Agent/`: 실제 `git init`, 고정 `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` 로 커밋 3개(최근 5일), 미커밋 변경 4개, 120일 전 커밋만 있는 브랜치 1개, 추적되는 `.env`(가짜 비밀), `.gitignore`, `node_modules/left-pad/`(dev cache), 저장소 밖 Downloads 에 `PL-Agent-spec.pdf` | FR-AM-003, FR-SO-003, FR-SO-004, `tracked_in_git`(FR-SV-007), dev_cache 예외 |
| git repo (비활성) | `user/dev/old-tool/`: 200일 전 커밋, 모든 mtime 200일 전, `node_modules/`, `.build/` | FR-AM-005(비활성 저장소 캐시만 trash 제안) |
| packages | `Thing.app/Contents/{Info.plist,MacOS/thing}`, `x.bundle/`, `Lib.photoslibrary/` | 패키지 디렉터리 = 1 항목(FR-CORE-003) |
| iCloud Drive | `user/Library/Mobile Documents/com~apple~CloudDocs/`(`icloud_drive` 루트, `icloud_synced=1`): 내려받은 일반 파일 3, 구형 자리표시자 `.계약서.pdf.icloud`·`.photo.heic.icloud`(실제로 만들 수 있는 작은 plist 파일), **dataless 흉내** 파일 2(내용 있는 파일 + 매니페스트에 `dataless=true` — `st_flags` 주입으로 `SF_DATALESS` 보고, §3.9), dataless 흉내 `.env`·`id_ed25519` 이름 파일 각 1(내용 검사가 일어나면 안 되는 미끼), `Desktop/` 하위 폴더(“데스크탑 및 문서” 동기화 흉내 — 별도 `desktop` 루트로도 등록해 중첩) | FR-CORE-002, FR-CORE-008, 02 §10.6 |
| 보안 자산 | §3.4 | FR-SV-001~008 |
| 환자 유사 | `user/약국/`(테스트가 `rule add --kind path_prefix --protection patient_data` 로 등록 — 전용 설정 키는 02 §9 에서 삭제됨) 아래 `처방전_2026-11-24_테스트.pdf`; Downloads 에 `조제기록_11월.xlsx`, `환자명단_테스트.csv`; `메모.txt` 에 합성 주민등록번호(§3.5); 스크린샷 1장 이름은 일반이지만 매니페스트상 "OCR 시 환자 판정"(M6) | FR-PM-002, FR-DR-009(리포트 마스킹), 그룹 결정 제외 |
| symlinks | 루트 안 파일을 가리키는 링크, 샌드박스 밖(`$SANDBOX/outside/`)을 가리키는 링크, 끊어진 링크, 디렉터리 순환 링크(`a → .`), **Desktop 의 `deploy-key` → `user/.ssh/id_ed25519`**, 하드링크 2개(같은 inode) | `entry_kind=symlink` 처리, 링크를 따라가지 않음(§4.3 S2·S9), 하드링크 중복 판정(04) |
| odd names | §3.6 | 경로 처리·표시·투영 |
| cross-volume | §3.7 | FR-EX-005, 볼륨 분리 |
| 시스템 위치 | `sys/Library/LaunchAgents/com.example.agent.plist`, `user/Library/LaunchAgents/com.example.helper.plist` | FR-AM-004 |
| 가짜 도구 | §3.8 | brew·defaults·mdls·osascript 의존 기능 |

프리셋 구성:

| preset | 포함 | 쓰는 곳 |
|---|---|---|
| `minimal` | Downloads 에 파일 3 | 대부분의 단위·계약 테스트 |
| `day_m2` | downloads, desktop, documents, iCloud Drive(일반 파일만), screenshots 5, installers(DMG 2), duplicates 3, 활성 repo + 프로젝트 파일 4, 환자 패턴 파일 1 — "새 파일 42, 수정 18" 이 되도록 2단계(기준 스캔 → 변경 적용 → 스캔)로 구성 | M2 통합, FR-DR-001, `scripts/demo-m2.sh`(12 문서) |
| `vault_m3` | §3.4 전부 + 활성 repo | M3 통합, 누출 스캐너, `scripts/demo-m3.sh` |
| `apps_m3` | 앱 번들 3(신규·버전 변경·삭제 시나리오), brew 픽스처, LaunchAgents | FR-AM-* |
| `exec_m5` | `day_m2` + cross-volume + 쓰기 금지 디렉터리 | M5 실행·장애 주입 |
| `odd_names` | §3.6 | 경로 회귀 |
| `icloud` | iCloud Drive 행 + downloads 일부 | FR-CORE-008, 루트 중첩 |
| `perf_100k` | §7 | 성능 |

### 3.3 `day_m2` 의 수치 고정

FR-DR-001 AC("새 파일 42, 수정 18")를 테스트가 직접 계산하지 않고 매니페스트에서 읽도록, 생성기는 `expectations` 에 `{"metric": "new_files", "value": 42}` 등을 넣는다. 테스트 `test_fr_dr_001_summary_counts_match_manifest` 는 `review.summary.stats` 와 매니페스트를 비교한다.

### 3.4 가짜 보안 자산 (실행 시 생성, 비밀 아님)

규칙: 저장소에는 어떤 키·인증서도 커밋하지 않는다(AGENTS.md §3.6). `secrets.py` 가 테스트 실행 시 `cryptography` 로 일회용 키를 만든다. 모든 값은 무작위이며 어떤 서비스에도 등록되지 않는다. AWS 공식 예시 키(`AKIAIOSFODNN7EXAMPLE`)처럼 탐지기 허용 목록에 있을 수 있는 값은 쓰지 않는다 — 형식만 맞춘 무작위 값.

| 파일(샌드박스 경로) | 생성 방법 | 기대 `vault_asset_kind` / 발견 사항 |
|---|---|---|
| `user/Downloads/AuthKey_TEST4X9Q2Z.p8` | EC P-256 PKCS#8 PEM | `apple_signing`, `exposed_location` |
| `user/Desktop/distribution.p12` | 자체 서명 인증서(not_after = now+23일) + 키, 암호 `test` | `pkcs12`, `needs_password=1`, 만료일 미확인 |
| `user/Desktop/dev-nopass.p12` | 암호 없는 PKCS#12, 같은 인증서 | `pkcs12`, `expiring_soon`(high, FR-SV-005) |
| `user/Documents/old-server.crt` | 만료된 자체 서명 인증서(not_after = now−10일) | `certificate`, `expired` |
| `user/Downloads/firebase-admin.json` | `{"type":"service_account","private_key":"-----BEGIN PRIVATE KEY-----…"}` (RSA 2048 생성) | `cloud_credential` |
| `user/dev/PL-Agent/.env` (git 추적) | `API_KEY=sk-test-<무작위 40>`, `AWS_ACCESS_KEY_ID=AKIA<무작위 16, base32 문자>` + `AWS_SECRET_ACCESS_KEY=<무작위 40>` | `env_file`, `tracked_in_git`(critical, 폐기·재발급 문구) |
| `user/.ssh/id_ed25519` (+`.pub`) | Ed25519 OpenSSH 형식, 권한 0600 | `ssh_private_key`, 발견 없음 |
| `user/Documents/backup/id_ed25519` | 위와 **같은 키**, 권한 0644 | `duplicate`, `bad_permissions` |
| `user/Downloads/server-key` (확장자 없음) | 위와 같은 키 3번째 사본 | 매직바이트 탐지(FR-SV-002), `duplicate` 3경로 |
| `user/.ssh/config` | `Host test` 블록 | `ssh_config` |
| `user/Downloads/notes.txt` | 일반 메모 중간에 `AKIA…` + secret 한 쌍 | `plaintext_secret`(asset 아님, `line_no` 만) |
| `user/Downloads/release.keystore`, `key.properties` | JKS 매직 `FEEDFEED` + 무작위, `storePassword=<무작위>` | `android_keystore` |
| `user/Downloads/office.ovpn`, `wg0.conf` | `<key>` PEM 블록, `PrivateKey = <base64 32바이트>` | `vpn_config` |
| `user/Downloads/UTC--…--wallet.json` | Ethereum keystore v3 구조, 무작위 ciphertext | `crypto_wallet` |
| `user/Documents/seed-backup.txt` | 05 단어 목록에서 12단어 | `crypto_seed_suspected`, `seed_phrase_suspected`, **지문 NULL**(FR-SV-008) |
| `user/Documents/github-recovery-codes.txt` | `xxxxx-xxxxx` 16줄 | `recovery_codes` |
| `user/dev/PL-Agent/config/database.yml` | `password: <무작위>` | `db_credential` |
| `user/Library/Preferences/NPKI/yessign/USER/cn=테스트사용자()…/signCert.der`, `signPri.key` | 자체 서명 DER(subject CN=테스트사용자) + 무작위 바이트 | `npki_cert`, `cert_subject_enc` 만 존재(평문 subject 는 DB 에 없어야 함) |
| `user/Downloads/profile.mobileprovision` | 최소 plist 바이트(CMS 서명 없음) | `apple_signing` |

각 `SecretSpec` 은 `value`(비밀 본문 문자열/바이트), `kind`, `path`, `must_not_appear_in` 대상 목록(§4.4)을 가진다.

### 3.5 합성 주민등록번호

생성기는 검증 숫자 규칙을 만족하지만 생년월일 부분이 `000101`·성별 숫자 `3`(2000년대 남) 처럼 테스트용으로 명확한 값을 만든다. 05/04 의 탐지기가 날짜 유효성까지 검사하면 그 규칙에 맞춘다(탐지기 단어/규칙 모듈을 참조). 실제 인물과 일치할 가능성을 줄이기 위해 고정 목록 3개만 쓰고, 테스트 코드 안에서도 리터럴로 쓰지 않고 생성 함수로만 만든다(누출 스캐너가 자기 자신을 오탐하지 않게).

### 3.6 이상한 이름 (`odd_names`)

| 이름 | 목적 |
|---|---|
| `스크린샷.png`(NFC) 와 `스크린샷.png`(NFD) 를 각각 다른 디렉터리에 | 정규화하지 않음(06 §1), 표시는 같게 |
| `a.txt` → `A.txt` 대소문자만 바꾸는 이름 변경 | APFS 대소문자 무시 볼륨에서 이동 판정(같은 inode) |
| 줄바꿈 포함 `line\nbreak.txt`, 탭, 선행 `-rf.txt`, 선행 공백 | 사람용 표 출력·로그 한 줄 유지(JSON 이스케이프), 서브프로세스 인자 주입 없음 |
| 255바이트 UTF-8 이름(한글 85자), 깊이 40 디렉터리 | 길이 한계, 목적지 경로 초과 시 `E_USAGE`/연산 실패 처리(08) |
| `콜론:이름.txt`(Finder 에서 `/` 로 보이는 이름) | 표시 경로 |
| 이모지·결합 문자, `.hidden`, `Icon\r` | 제외 규칙, 표시 |
| 잘못된 UTF-8 바이트 이름 | APFS 가 거부(EILSEQ)하면 생성기가 매니페스트에 `unsupported_fs` 로 기록하고 해당 기대만 생략 |

### 3.7 두 번째 볼륨 (`hdiutil` 표식)

```
hdiutil create -size 64m -fs APFS -volname DCTESTVOL -type SPARSE "$SANDBOX/img/vol2"
hdiutil attach -nobrowse -mountpoint "$SANDBOX/vol/DCTESTVOL" "$SANDBOX/img/vol2.sparseimage"
```
- 마운트 지점은 **샌드박스 아래**(`/Volumes` 를 쓰지 않음). `system_path("volumes_root")` 재매핑으로 core 는 이것을 "외장 볼륨"으로 본다.
- 변형: 16MB 이미지(디스크 가득 참), `-readonly` 재마운트(쓰기 불가 볼륨), 연산 중 `hdiutil detach -force`(볼륨 소실).
- 세션 범위 픽스처가 만들고 teardown 에서 강제 분리·삭제. 분리 실패 시 다음 테스트를 실패시켜(누수 방지) 사람이 보게 한다.
- 결정: 루트 권한이 필요한 방법(RAM 디스크 `diskutil erasevolume` 등)은 쓰지 않는다.

### 3.8 가짜 외부 도구 (`$SANDBOX/bin`)

| 도구 | 동작 | 제어 |
|---|---|---|
| `brew` | `brew info --installed --json=v2` 에 `$SANDBOX/.tooldata/brew.json` 출력, 다른 인자는 종료 1 | 테스트가 JSON 교체(설치·삭제 시나리오) |
| `defaults` | `read com.apple.screencapture location` 에 `$SANDBOX/user/Pictures/Screenshots` | 파일로 값 지정, 키 없음 시나리오(종료 1) |
| `mdls` | `kMDItemLastUsedDate` 를 `.tooldata/mdls.json` 에서 | 미사용 앱(FR-AM-006) |
| `osascript` | **함정(tripwire)**: 샌드박스에서는 승인 대화상자를 띄우지 않으므로(02 §10.3-1 ②) 호출되면 기록 후 종료 1 → `_guard_env` 가 그 테스트를 실패시킨다. 대화상자 동작은 실행기 주입 단위 테스트로 검증(§4.1 `test_native_dialog_runner`) | FR-EX-002 |
| `gitleaks` | 기본은 **없음**(PATH 에서 제거된 상태 시나리오 = FR-SV-002 의 "없을 때"). `needs_gitleaks` 테스트만 실제 도구 경로를 노출 | |

가짜 도구는 Python 스크립트(`#!/usr/bin/env python3 -I`)이며 받은 argv 를 `.tooldata/calls.jsonl` 에 기록한다 → 테스트가 "셸 미경유·허용 인자만" 을 검증(02 §6 `run_tool`).

---

### 3.9 iCloud 자리표시자 (FR-CORE-008)

진짜 dataless 파일은 iCloud 계정 없이 만들 수 없고, `SF_DATALESS` 는 사용자가 `chflags` 로 설정할 수 없다. 그래서 두 수단을 쓴다.

| 수단 | 방법 | 검증 범위 |
|---|---|---|
| 플래그 주입 | 04 가 정하는 `collect/fs` 의 `lstat` 대체 지점에서 매니페스트의 dataless 경로에 `st_flags |= 0x40000000` 을 돌려준다. 파일 자체는 내용이 있는 보통 파일(미끼) | core 가 그 경로를 **열지 않는지**를 감사 훅이 잡는다 — 열면 내용이 있으므로 해시·패턴 검사가 실제로 일어나 버그가 드러난다 |
| 구형 자리표시자 | `.<이름>.icloud` 파일을 실제로 생성 | 원래 이름(`계약서.pdf`)으로 표시, dataless 취급, 자리표시자 파일 자체도 열지 않음 |
| 실기기 | §9.3 수동 | 실제 다운로드가 일어나지 않음 |

테스트(`integration/test_icloud.py`, `safety/test_no_open_on_dataless.py`):

| 테스트 | 기대 |
|---|---|
| `test_fr_core_008_dataless_never_opened` | 스캔·vault·review·`item.show`·`report.daily` 전체 실행 동안 감사 훅의 `open` 이벤트 중 dataless/자리표시자 경로 0건. `sha256` NULL, vault 내용 패턴·gitleaks 미실행(미끼 `.env`·`id_ed25519` 가 내용 근거로 탐지되지 않음 — 이름 기반 탐지는 05 가 허용하면 `detect_methods` 에 `content_pattern` 없음), `W_DATALESS_SKIPPED` 집계 |
| `test_fr_core_008_icloud_allowed_actions` | 게이트 거짓(저장소 기본)에서 `icloud_drive` 루트 항목과 다른 루트의 dataless 항목 모두 `allowed_actions == [keep, keep_always, defer]`(게이트 참일 때는 §3.10), `blocked_reasons` 의 파일 동작 4개(`trash`,`move`,`archive`,`rename`)가 `icloud_synced`/`dataless`, `trash/move/archive` 결정 → `E_PROTECTED`, 그룹 결정은 건너뜀(`W_PROTECTED_SKIPPED`) |
| `test_fr_core_008_legacy_placeholder_display_name` | `.계약서.pdf.icloud` → `display_name="계약서.pdf"`, `is_dataless=true` |
| `test_icloud_synced_desktop_documents` | “데스크탑 및 문서” 동기화 흉내: `user/Desktop`·`user/Documents` 를 `user/Library/Mobile Documents/com~apple~CloudDocs/{Desktop,Documents}` 로 가는 심볼릭 링크로 만들고 `desktop`·`documents` 루트로 등록 → 두 루트 `icloud_synced=1`(04 §1 의 realpath 판정), 그 항목은 `keep/keep_always/defer` 만, `blocked_reasons=icloud_synced`. 동기화가 꺼진 일반 `Desktop` 디렉터리 루트는 `icloud_synced=0` |
| `test_fr_core_008_nested_roots_no_duplicates` | iCloud 루트 안 `Desktop/` 을 `desktop` 루트로도 등록 → 같은 (dev, inode) 항목 1개, 바깥 루트 순회는 안쪽 루트 경로를 건너뜀(02 §10.6) |
| `test_exclude_globs_relative_to_root` | `**/Library/**` 가 iCloud 루트(`~/Library/Mobile Documents/...`) 자체를 제외하지 않고, 루트 안의 `Library/` 하위만 제외(02 §9) |
| `test_fr_core_008_app_no_thumbnail_for_dataless` (Swift UI) | dataless 항목은 아이콘만, 썸네일 생성 호출 0, Space 는 경고 후에만(03) |

### 3.10 iCloud 휴지통 해제(FR-EX-008)와 루트 수동 표시

게이트 = 코드 상수 `policy/icloud.py: TRASH_UNLOCK_VERIFIED`(저장소 기본 `False`) **그리고** 설정 `icloud.allow_trash`. 테스트는 상수를 픽스처 `icloud_gate(True|False)` 로 `monkeypatch` 한다(저장소 값은 바꾸지 않는다).

| 테스트 | 기대 |
|---|---|
| `test_fr_ex_008_gate_false_blocks_trash` | 게이트 거짓(상수 `False` 또는 `allow_trash=false`): 다운로드된 iCloud 동기화 항목 `allowed_actions` 에 파일 동작 없음, `blocked_reasons` 의 `trash/move/archive/rename` 모두 `icloud_synced` |
| `test_fr_ex_008_gate_true_allows_item_trash` | 게이트 참: 다운로드된 항목은 `trash` 허용, `move/archive/rename` 은 `icloud_synced`; dataless 항목은 `blocked_reasons.trash=dataless`(게이트와 무관) |
| `test_fr_ex_008_group_and_rule_excluded` | 게이트 참에서 `decision set --group … --action trash` → iCloud 항목은 `skipped` + `W_PROTECTED_SKIPPED{reason:"icloud_synced"}`, 같은 그룹의 일반 항목만 결정. `actor=rule` 자동 결정(07)도 iCloud 항목에 `trash` 를 만들지 않음(제안 표시는 가능) |
| `test_fr_ex_008_plan_marks_propagation` | 항목 지정 `trash` → 계획 연산 `icloud_propagates=true`, `summary.icloud_propagates_count=1`. 그 값만 바꾼 정규 객체는 `plan_hash` 가 다름(08 §5) |
| `test_icloud_propagates_check_constraint` | `plan_operations` 에 `op ≠ 'trash'` 이면서 `icloud_propagates=1` 인 행 INSERT → `sqlite3.IntegrityError`(06 CHECK) |
| `test_fr_ex_008_approval_text_and_ack` | 수단 선택·문구 단위 테스트: `cli_tty` 요약과 대화상자 인자에 별도 줄 "N개 파일은 iCloud 를 통해 다른 기기에서도 삭제됩니다"(N=연산 수) 포함, `test` 승인 행 `icloud_ack=1`. 그런 연산이 없으면 그 줄 없음·`icloud_ack=0` |
| `test_fr_ex_008_icloud_ack_missing` | `icloud_propagates` 연산이 있는 계획에 `icloud_ack=0` 승인 행(감사 행 포함)을 직접 넣고 apply → `E_APPROVAL_REQUIRED{reason:"icloud_ack_missing"}`, 트리 불변(08 G9a) |
| `test_fr_ex_008_turned_dataless_before_apply` | 승인 후 그 파일을 dataless 로 흉내(§3.9 플래그 주입) → 해당 op `skipped`, `E_PROTECTED{reason:"dataless"}`, 파일 미개방. 루트의 `icloud_synced` 가 계획 후 바뀐 경우도 08 F5 대로 `skipped` |
| `test_icloud_gate_constant_false_without_record` | 저장소의 `TRASH_UNLOCK_VERIFIED` 가 `True` 이면 `docs/09-MACOS-INTEGRATION.md` §12 의 iCloud 휴지통 검증 행(V18~V21)이 두 기기 모두 `ok` 로 채워져 있어야 통과(08 §9.1 `test_icloud_gate_requires_verification_record` 와 같은 테스트 — 이름은 08 을 따른다). 검증 기록이 없는 지금은 상수가 `False` 여야 녹색 |
| `test_config_allow_trash_owner_only` | `config set icloud.allow_trash false` 는 `cli`(에이전트 표식 없음)에서 성공, `--channel skill`·에이전트 표식 승격·serve `channel=mcp` 에서는 `E_PROTECTED{reason:"owner_only_key"}`. MCP 도구 목록에 `config_set` 없음 |
| `test_root_icloud_override_precedence` | `root add --icloud-synced yes` → 신호 없어도 `icloud_synced=1`, `source=user`; `--icloud-synced no` → 감지 신호(심볼릭 링크 실제 경로가 iCloud 아래)가 있어도 0, `source=user`; `auto` → 04 판정, `source=detected` |
| `test_root_icloud_assumed_default` | `auto` 이고 신호가 없는 `desktop`·`documents` 루트 → `icloud_synced=1`, `source=assumed`; 같은 조건의 `downloads` 루트 → 0, `detected`. `root.list` 가 루트마다 세 값을 모두 반환 |
| `test_root_set_reevaluates_items` | `root set ROOT_ID --icloud-synced yes` → 그 루트 열린 항목의 `allowed_actions` 즉시 재계산, 새로 막힌 동작의 기존 결정 철회(`proposed`). 인자 없는 `root set` → `E_USAGE` |
| `test_root_set_not_in_mcp` | MCP `tools/list` 에 `root_set` 없음, Skill `allowed-tools` 에 `root set` 패턴 없음 |
| `test_archive_unencrypted_warns` | 볼륨 암호화 판정 함수를 주입(`False`/`None`)한 상태에서 `config set archive.root …`, 보관 연산이 있는 `plan.create`, `core.doctor` 가 모두 `W_ARCHIVE_UNENCRYPTED` 를 내고 차단하지 않음. `True` 면 경고 없음(PRD C14) |

## 4. 안전 불변식 — 실행 가능한 검사

모두 `core/tests/safety/`. 하나라도 실패하면 머지 금지(NFR-SAFE-001). 각 불변식은 **정적 검사 + 동적 검사 + 속성 기반 검사**의 조합이다.

### 4.1 S1 — 승인된 plan(해시 일치) 없이는 아무것도 변경되지 않는다

| 테스트 | 방법 |
|---|---|
| `test_no_mutation_outside_executor.py` | `core/src/dayclose/**/*.py` AST 순회: `os.rename/replace/remove/unlink/rmdir/chmod/chflags/utime/truncate/link/symlink`, `shutil.move/rmtree/copy*`, `Path.rename/replace/unlink/rmdir/chmod/write_*/touch/mkdir`, `open()` 의 쓰기 모드, `xattr` 쓰기가 `executor/` 밖에 있으면 실패. 허용 예외 목록은 파일 상단 상수(`store`·`config`·`common/logging` 의 `DAYCLOSE_HOME` 내부 쓰기, 02 §6)이며 각 예외에 이유 주석 필수. M5 이후 `os.unlink`/`os.remove` 는 executor 의 볼륨 간 이동 경로 1곳만(12 M5 종료 기준). |
| `test_no_mutation_in_swift.py` | `app/`, `native/` 의 `*.swift` 에서 `removeItem`, `moveItem`, `trashItem`, `replaceItem`, `rename(`, `unlink(`, `copyItem`(사용자 경로로) 를 찾으면 실패(12 M4 종료 기준). |
| `test_tree_unchanged_by_non_apply_commands` | `day_m2`(M5 이후 `exec_m5`)에서 `plan.apply`·`plan.undo` 를 제외한 **모든** 명령(§10 문서 §6 표 전체, 성공·실패 케이스)을 실행한 전후 `tree_digest` 동일. digest = 정렬된 (상대경로, 종류, inode, 크기, mtime_ns, 모드, st_flags, xattr 이름·값 해시, 파일 SHA-256) 의 SHA-256. FR-DR-005 AC 포함. |
| `test_executor_requires_approval` | `plan.apply` 를 draft·cancelled·completed 에서 호출 → `E_APPROVAL_REQUIRED`/`E_INVALID_STATE`, 트리 불변. |
| `test_apply_rejects_hash_mismatch` | `approvals.plan_hash` 를 DB 에서 직접 바꾼 뒤 apply → `E_APPROVAL_MISMATCH`, 트리 불변. |
| `test_apply_rejects_tampered_operations` | 승인 후 `plan_operations.dst_path` 또는 행 추가를 DB 에서 직접 수행 → apply 는 연산 행에서 `plan_hash` 를 **다시 계산**해 불일치를 거부해야 함. (08 요구 사항 — 저장된 해시끼리 비교만 하면 이 테스트가 실패한다. §11) |
| `test_test_approval_requires_both_env` | 샌드박스에서 `DAYCLOSE_TEST_APPROVE` 없이 `plan approve` → 즉시 `E_APPROVAL_DENIED`(02 §10.3-1 ②, 테스트 중 실제 대화상자 금지), 가짜 `osascript` 호출 기록 0건. `method=test` 로 승인한 뒤 apply 시점에 `DAYCLOSE_TEST_APPROVE` 를 지우면 `E_APPROVAL_REQUIRED`(08 G4). |
| `unit/test_approval_method_selection.py` | 수단 선택 순수 함수(`plan/approval.select_method(env, tty_openable, channel, signature_ok, gui)`)의 표 전체: 에이전트 표식(`CLAUDECODE`, `AI_AGENT`, `CODEX_SANDBOX` 등 상수 목록 각각) + TTY 가능 → `native_dialog`(TTY 수단 금지); 표식 없음 + TTY → `cli_tty`; 채널 `app` + 서명 검증 성공 → `app_button`, 서명 없음/실패 → 다음 순서(`native_dialog`); 채널 `mcp`·`schedule` → 거부; GUI 없음 → `E_APPROVAL_DENIED{reason:"no_gui"}`. 실제 대화상자·TTY 는 열지 않는다. |
| `unit/test_native_dialog_runner.py` | 대화상자 함수에 가짜 실행기(`run_tool` 대체 callable)를 주입: 반환 `approve`/`deny`/시간 초과/무응답 → 각각 승인/`E_APPROVAL_DENIED`; 요약 텍스트가 `osascript` 의 `--` 뒤 argv 로만 전달되고 스크립트 본문에 없으며, 호출자가 준 문자열(결정 메모 등)이 없고 연산 수·`plan_hash_short` 가 있음(F31). |
| `test_app_signature_verification` | 테스트 키쌍(`cryptography` EC P-256, 실행 시 생성)으로 `core.app_key` 등록(샌드박스 test 확인) → 올바른 서명 `"dayclose.approve.v1\n"+device_id+"\n"+plan_id+"\n"+plan_hash` 은 검증 성공, 다른 `plan_hash`·다른 `device_id`·변조 서명은 실패 → 선택 함수가 `app_button` 을 고르지 않음. |
| `test_app_key_unregistered_or_bad_signature_degrades` | (a) 키 미등록 + `app_signature` 있음 (b) 등록 + 잘못된 서명 (c) 등록 + 서명 없음 — 모두 거부하지 않고 다음 순서로 넘어감: 선택 함수 결과 `native_dialog`(TTY 없음) 또는 `cli_tty`(표식 없음+TTY), 샌드박스 통합 테스트에서는 ② 규칙대로 `E_APPROVAL_DENIED`. `app_button` 승인 행 0개. `app-key register/revoke` 는 사람 확인 없이 성공하지 않음(test 승인 외 `E_APPROVAL_DENIED`), MCP 에 `core_app_key` 없음 |
| `test_fake_osascript_on_path_not_executed` | `PATH` 맨 앞에 `$SANDBOX/evil/`(가짜 `osascript`·`defaults` — 실행되면 표식 파일을 씀)를 두고 `run_tool('defaults', …)` 와 승인 경로를 실행 → 표식 파일 없음. 실행된 경로는 `$SANDBOX/bin/…` 또는 `system_path` 의 절대경로뿐(호출 기록으로 확인). 단위: 샌드박스가 아닐 때 `system_path('osascript') == '/usr/bin/osascript'`(실행 없음). |
| `test_apply_rejects_unaudited_approval` | `approvals` 행을 DB 에 직접 넣고(감사 행 없음) apply → `E_APPROVAL_REQUIRED{reason:"approval_not_audited"}`, 트리 불변(08 G5). |
| `test_apply_rejects_expired_approval` | `DAYCLOSE_TEST_NOW` 로 승인 후 24시간+1초 → apply 와 재개 모두 `E_APPROVAL_REQUIRED{reason:"approval_expired"}`(08 G6). |
| `test_mcp_has_no_approval_tools` | MCP `tools/list` 의 이름 집합 ∩ 02 §10.3 비노출 목록(`plan_approve`, `plan_apply`, `plan_undo`, `plan_recover`, `core_app_key`, `core_init`, `config_set`, `root_add`, `root_remove`, `root_set`, `rule_add`, `rule_remove`, `suppression_add`, `suppression_remove`, `policy_accept`, `policy_reject`, `ai_key_set`, `ai_key_remove`, `ai_classify`, `vault_annotate`, `core_schema`, `core_serve`, `mcp_serve`) = ∅, 그리고 노출 목록 = 02 §5.3 전체 − 02 §10.3 비노출 목록(FR-EX-002, FR-AG-003). |

### 4.2 S2 — 보호 등급 항목은 파괴적 연산에 들어가지 않는다

"파괴적 연산" = `op_type ∈ {trash, move, archive, rename}`.

| 테스트 | 방법 |
|---|---|
| `test_fr_pm_001_allowed_actions_matrix` | `protection_class` × `subject_type` × `category`(dev_cache 예외 포함) 전 조합의 `allowed_actions` 가 02 §10.1 표와 정확히 일치(표를 테스트 데이터로 그대로 옮김). |
| `test_security_asset_never_in_plan` | `vault_m3` 의 모든 보안 자산 항목에 대해 trash/move/archive 결정 시도 → `E_PROTECTED`(FR-SV-003). DB 를 직접 조작해 `decided_action=trash` 로 만든 뒤 `plan.create` → `excluded`(E_PROTECTED). 연산 행을 직접 삽입한 뒤 apply → 연산 직전 재평가로 `skipped`(E_PROTECTED), 파일 불변. |
| `test_patient_never_trashed` | 환자 항목 `trash` 불가, `move`/`archive` 는 항목 단위만, 그룹 결정에서 제외(`W_PROTECTED_SKIPPED`). |
| `test_protection_raised_between_plan_and_apply` | 승인 후 `rule add --protection patient_data` 로 대상 보호 상향 → apply 시 해당 op `skipped`(E_PROTECTED). |
| `test_symlink_to_secret_not_followed` | Desktop 의 `deploy-key`(→ `.ssh/id_ed25519`) 링크 항목: 어떤 결정·연산도 링크 대상 파일의 inode·내용·위치를 바꾸지 않음. 링크 자체를 trash 하면 링크만 이동(대상 불변). |
| `test_seed_recovery_rows_have_no_derivatives` | 마이그레이션 적용 DB 에 `kind ∈ {crypto_seed_suspected, recovery_codes}` 이면서 `fingerprint_sha256`/`key_fingerprint`/`cert_subject_enc` 중 하나라도 NULL 이 아닌 행을 직접 INSERT/UPDATE → `sqlite3.IntegrityError`(06 §5.3 CHECK). 정상 스캔 결과 해당 행의 세 컬럼 NULL(FR-SV-008) |
| `test_suppression_never_applies_to_protected` | `suppression add --match path_glob --value '**'`·`--match sha256 --value <보안 자산 파일의 해시>` 등으로 보안 자산·환자 항목과 일치하는 규칙 생성 → 응답 `protected_not_applied ≥ 1`, 그 항목은 `suppressed` 가 아니라 계속 `proposed`, 다음 스캔에서도 질문됨. `keep_always` 가 만든 suppression 도 보호 상향 후에는 적용되지 않음. 64MB 초과·dataless 파일은 `sha256` 규칙과 일치하지 않음 |
| `prop_no_protected_in_destructive_ops`(Hypothesis) | §5.1 상태 기계에서 임의 보호 규칙 추가·제거·결정·계획·실행을 섞어도, `done` 상태의 파괴적 연산 대상 항목의 **실행 시점** protection 이 `security_asset` 이었던 적이 없고, `patient_data` 에 `trash` 가 없다. |

### 4.3 S3 — 실행된 모든 연산은 되돌릴 수 있거나, 명시적으로 불가 표시된다

| 테스트 | 방법 |
|---|---|
| `test_done_ops_have_undo_state` | 모든 apply 테스트의 teardown 훅: `state=done` 인 op 의 `undo_state ∈ {undoable, not_undoable}`, `not_applicable` 금지. `not_undoable` 이면 08 이 정한 사유 코드가 있어야 함. |
| `test_fr_ex_006_undo_roundtrip` | apply → undo 후 `tree_digest`(휴지통 디렉터리 제외)가 apply 전과 같다. trash/move(같은 볼륨)/move(볼륨 간)/archive 각각. |
| `prop_apply_undo_roundtrip`(Hypothesis) | 임의 결정 집합 → plan → apply → 전체 undo → 원상 복구. |
| `test_undo_impossible_reported` | 휴지통에서 파일을 지운 뒤 undo → op `undo_failed` + `E_UNDO_IMPOSSIBLE`, 다른 op 는 계속(`E_PARTIAL`). |
| S9 `test_executor_touches_only_src_dst` | apply 중 감사 훅으로 기록한 모든 쓰기 경로가 각 op 의 `src_path`, `dst_path`/`actual_dst_path`, `creates_dirs`, 휴지통 경로 집합의 부분집합. |

### 4.4 S4 — 비밀·환자 정보는 DB·로그·캐시·출력에 남지 않는다 (누출 스캐너)

`core/tests/safety/leakscan.py` + `test_leak_*.py`. NFR-PRIV-001, FR-SV-004, FR-SV-008, FR-DR-009, 02 §13.

**탐지 대상(needles)** — 매니페스트에서 생성:

| needle | 출처 |
|---|---|
| 비밀 본문 전체와 그 변형: 원문, base64(표준·URL), 16진(소·대문자), 줄바꿈 제거본, URL 인코딩 | `SecretSpec.value` |
| 비밀 본문의 연속 16자 창(window) 전부(PEM 은 헤더 제외 본문 기준) | 부분 누출 |
| PEM 개인키 헤더 `-----BEGIN (RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----` | 일반 규칙 |
| 시드 단어 12개 연속(공백 정규화) 및 그 SHA-256·SHA-1·MD5 16진 | FR-SV-008 "어떤 파생값도" |
| 시드 파일의 파일 SHA-256 | FR-SV-008 (`fingerprint_sha256` NULL 검증) |
| 합성 주민등록번호(하이픈 유무), 환자 유사 파일 이름·경로(로그·리포트·에이전트 출력 대상만) | FR-PM-002, FR-DR-009 |
| NPKI 인증서 subject 평문(`테스트사용자`) | 06 §6 `cert_subject_enc` |
| 사용자 메모로 넣은 표식 문자열 `DCNOTE-<uuid>` | `decisions.note_enc`, `vault.annotate` |

**검사 대상(haystacks)** 과 허용 예외:

| 대상 | 읽는 방법 | 비밀 본문 | 보안 자산 경로 | 환자 파일 경로·이름 | 메모 표식 |
|---|---|---|---|---|---|
| `$DAYCLOSE_HOME/dayclose.db`, `-wal`, `-shm`, `backups/*.db` | **원시 바이트**(해제된 페이지 포함) + `iterdump()` 텍스트 | 금지 | 허용(06 §6 경로 평문) | 허용 | 금지(암호문만) |
| `logs/core.log*` | 텍스트 | 금지 | 금지(ID 만, 02 §13) | 금지 | 금지 |
| `cache/**`(테스트에서 `DAYCLOSE_HOME/cache`) | 바이트 | 금지 | 금지 | 금지 | 금지 |
| 세션 동안 모든 CLI/serve/MCP stdout·stderr(`leak_corpus`) | 텍스트 | 금지 | `cli`/`app` 채널 `vault.list/show`·`item.*` 의 `path` 필드만 허용, 그 외 금지 | 위와 같음(`cli`/`app` 의 항목 `path` 만) | `cli`/`app` 의 `decision.list`·`item.show` 만 허용 |
| 에이전트 채널(`skill`, `mcp`) 출력 | 텍스트 | 금지 | **금지** | **금지** | 금지 |
| `report.daily`(json·md, 모든 채널) | 텍스트 | 금지 | 금지 | 금지(FR-DR-009) | 금지 |
| 봉투 `error.details`·`warnings[].details`(모든 채널) | JSON | 금지 | 금지 | 금지 | 금지 |
| 가짜 `osascript` 호출 기록(`calls.jsonl`) | 텍스트 | 금지 | 금지 | 금지 | 금지 |
| `contracts/fixtures/**`(저장소) | 텍스트 | 금지 | 금지 | 금지 | 금지 |
| Swift 썸네일 캐시(UI 테스트) | 파일 존재 여부 | — | 파생물 0개(FR-VR-006) | `ephemeral` 디스크 캐시 0개 | — |

- 검사기는 needle 을 바이트 수준(UTF-8, UTF-16LE 둘 다)으로 찾는다. 결정: SQLite TEXT 는 UTF-8 이지만 Swift 측 캐시·plist 에 UTF-16 이 섞일 수 있어서.
- 실패 메시지에 needle 원문을 찍지 않는다(가짜라도 CI 로그에 비밀 형태 문자열을 남기지 않음) — `needle_id`, 대상 파일, 오프셋만.
- 보조 검사: `gitleaks` 가 있으면 `gitleaks dir --no-banner --redact <대상들>` 결과 0건(`needs_gitleaks`).
- 테스트 목록: `test_leak_after_vault_scan`(vault_m3 전체 스캔 + 모든 읽기 명령, FR-SV-004 · M3 종료 기준), `test_leak_agent_channels`(같은 명령을 `skill`/`mcp` 로), `test_leak_report_masking`(FR-DR-009), `test_leak_seed_no_derivatives`(FR-SV-008), `test_leak_notes_encrypted`, `test_leak_logs_debug_level`(`--log-level debug` 에서도), `test_leak_error_paths`(일부러 실패시킨 명령들의 봉투·로그), `test_leak_ai_payload`(M6: 가짜 공급자가 받은 페이로드 — FR-SO-005, FR-PM-005), `test_leak_crash_traceback`(일부러 `E_INTERNAL` 유발 — 트레이스백은 로그에만, 마스킹 후).
- `RedactingFilter` 단위 테스트(`unit/test_redacting_filter.py`): `AKIA…`, `sk-…`, `ghp_…`, PEM 헤더, 고엔트로피 40자 문자열 → `[REDACTED]`, 일반 경로·한국어 문장은 보존.

### 4.5 S5·S6·S7 요약

| ID | 불변식 | 테스트 |
|---|---|---|
| S5 | 실제 사용자 경로 미접촉 | §2 전체 (`test_sandbox_guard.py`, `test_tests_do_not_reference_real_paths.py`, `test_conftest_guard_present.py`) |
| S6 | 외부 네트워크 0 (AI 비활성 또는 외부 공급자 미허용) | `_no_network` 가 모든 테스트에 적용 + `test_nfr_priv_002_no_network_when_ai_disabled`(M6: `ai.enabled=false` 로 전체 플로우) |
| S7 | 모듈 import 방향(02 §6) | `test_import_boundaries.py`: AST 로 `dayclose.<a>` → `dayclose.<b>` 엣지를 모아 02 §6 의 허용 그래프 밖 엣지·`ai`→`executor`/`common.proc` 엣지가 있으면 실패 |

---

## 5. 속성 기반 테스트 (Hypothesis)

프로필: `ci`(기본, `max_examples=200`, `deadline=None`, `derandomize=True` — 머지 게이트가 무작위로 깨지지 않게), `nightly`(`max_examples=5000`, 무작위 시드, 실패 예제는 `.hypothesis/` 에 보관 후 회귀 테스트로 승격). `HYPOTHESIS_PROFILE` 환경 변수로 선택.

### 5.1 `safety/test_prop_executor.py` — 실행기 상태 기계

`hypothesis.stateful.RuleBasedStateMachine` 하나로 사용자·외부 변경·크래시를 섞는다.

| 규칙(rule) | 동작 |
|---|---|
| `create_file(name, root, size, protection_hint)` | 샌드박스에 파일 생성(이름 전략은 §3.6 포함) |
| `external_modify / external_delete / external_rename / replace_same_name` | 계획과 실행 사이 외부 변경 |
| `scan()` | `scan.run` |
| `decide(item, action, dest)` | `decision.set`(허용 여부와 무관하게 시도 — 거부도 정상 경로) |
| `add_protection_rule / remove_user_rule` | 보호 등급 변화 |
| `plan_create(subset)`, `approve_test(plan)`, `cancel(plan)` | |
| `apply(plan, crash_at)` | `crash_at` ∈ {None} ∪ 08 의 체크포인트 목록(§6.1) — 크래시면 서브프로세스 종료 후 `plan.recover` |
| `undo(plan, ops)` | |
| `empty_trash_item()` | 휴지통 파일 외부 삭제 |

불변식(`@invariant`, 매 단계):
1. **유실 0**: 생성된 모든 파일 내용(SHA-256)이 정확히 한 곳에 존재 — 원위치, 계획 목적지, 휴지통 기록 위치(`actual_dst_path`) 중 하나. 예외: 사용자가 외부에서 지운 파일, `empty_trash_item` 으로 지운 파일(기록됨).
2. **DB–FS 정합**: `recover` 직후 `done` op 는 목적지에 파일 있음·원본 없음, `pending`/`skipped` op 는 원본 있음, `failed` 는 원본 있음(볼륨 간 이동 실패 시 목적지 잔여물 없음).
3. S1(승인·해시), S2(보호), S3(undo_state) 그대로.
4. 항목 상태가 06 §4.1 전이 표의 허용 전이로만 바뀜(직전 상태와 비교).

### 5.2 그 밖의 속성

| 테스트 | 속성 |
|---|---|
| `unit/test_prop_plan_hash.py` | 같은 연산 집합의 입력 순서 순열 → 같은 해시. 연산의 어느 필드(src, dst, op, pre_* 4개, item_id)를 바꿔도 해시가 바뀜(FR-EX-001). 정규화 규칙은 08. |
| `unit/test_prop_item_transitions.py` | 임의 명령 열을 항목 상태 기계에 적용 — 허용 전이 외에는 `E_INVALID_STATE`, DB CHECK 위반 없음. |
| `unit/test_prop_agent_view.py` | 임의 Item(모든 sensitivity·protection·이름 전략) 을 `agent_view` 로 투영 — `patient`/`secret` 의 `path`·`display_name`·`display_path` 는 null 이고 원래 파일 이름의 4자 이상 부분 문자열이 투영 결과 어디에도 없음, `normal`·`personal` 은 이름·경로 그대로(PRD C15) — 없음(10 §1.5). |
| `unit/test_prop_pagination.py` | 임의 데이터·임의 `limit` 로 커서 순회 → 전체 집합과 같고 중복 없음. 순회 중 행 삽입해도 중복 없음. |
| `unit/test_prop_fs_diff.py` | 임의 FS 변경 열 → `collect/fs` 이벤트가 생성/수정/삭제/이동 각각 정확히 1개(FR-CORE-003), 변경 없으면 0. |
| `unit/test_prop_review_date.py` | 임의 시각·시간대·DST 전환 → `review_date` 가 `day_boundary` 규칙과 일치(FR-DR-002). |

---

## 6. 장애 주입

### 6.1 주입 수단

| 수단 | 쓰는 곳 |
|---|---|
| 체크포인트 크래시: executor 의 연산 단계 경계마다 `executor/_checkpoint(name)` 호출. 샌드박스 모드에서 `DAYCLOSE_TEST_FAULT=<name>:<n>`(n번째 도달 시) 이면 `os._exit(137)`(= SIGKILL 과 같은 효과, 정리 코드 미실행) 또는 `raise OSError(errno.X)` | 크래시·ENOSPC·EIO 결정론적 재현. **환경 변수는 02 §15.1 추가 필요**(§11). 체크포인트 이름 목록은 08 이 정한다(예: `op.running_committed`, `op.fs_done`, `xdev.copy_partial`, `xdev.verified`, `xdev.src_removed`, `undo.fs_done`, `migrate.mid`). |
| 진행 이벤트 기반 SIGKILL: `plan.apply --progress ndjson` 의 k번째 `op_id` 이벤트를 받은 직후 `os.kill(pid, SIGKILL)` | 주입 지점 없는 실제 크래시(체크포인트 누락 검출용) |
| 실제 환경 조건: `chmod 000`, `chflags uchg`, 16MB 디스크 이미지 가득 채움, `hdiutil detach -force`, 읽기 전용 재마운트 | 커널이 돌려주는 실제 오류 |
| in-process 패치: `common/paths.probe` 의 `stat` 을 무한 대기로, `EPERM` 반환 래퍼 | 볼륨 행·TCC 거부(실제 재현 불가 — §9 수동 검증으로 보완) |

### 6.2 시나리오 표

위치 `core/tests/integration/faults/`. 공통 사후 검사: `assert_no_loss(manifest)`, `plan.recover` 후 §5.1 불변식 2, 트리 해시가 기대 상태와 일치.

| ID | 시나리오 | 주입 | 기대 결과 | FR/NFR |
|---|---|---|---|---|
| F01 | 연산 `running` 커밋 직후 크래시 | 체크포인트 `op.running_committed` | recover: 원본 존재 → op `pending`(재실행 가능) 또는 08 판정, 유실 0 | FR-EX-006, NFR-SAFE-002 |
| F02 | rename 완료 후 `done` 커밋 전 크래시 | `op.fs_done` | recover: 목적지 존재·원본 없음 → `done`, `undo_state=undoable` | FR-EX-006 |
| F03 | 볼륨 간 복사 도중 크래시 | `xdev.copy_partial` | recover: 목적지 부분 파일 제거(executor 가), 원본 보존, op `pending`/`failed`(08) | FR-EX-005 |
| F04 | 검증 후 원본 삭제 전 크래시 | `xdev.verified` | recover: 양쪽 존재 → 목적지 해시 재검증 후 원본 제거 또는 목적지 제거(08 판정), 유실·중복 0 | FR-EX-005 |
| F05 | 원본 삭제 후 커밋 전 크래시 | `xdev.src_removed` | recover: `done` | |
| F06 | 임의 지점 실제 SIGKILL | 진행 이벤트 k=1..N | F01~F05 중 하나로 수렴, 유실 0 | NFR-SAFE-002 |
| F07 | 디스크 가득 참(볼륨 간 이동) | 16MB 이미지 + 20MB 파일 | op `failed`(`E_PARTIAL` 전체 결과), 목적지 잔여물 0, 원본 보존 | FR-EX-005 |
| F08 | ENOSPC 주입(같은 볼륨 휴지통 디렉터리 생성) | `OSError(ENOSPC)` | op `failed`, 다음 op 계속 | |
| F09 | 원본 디렉터리 권한 없음 | `chmod 000` 부모 | op `failed`(`E_PERMISSION`), 나머지 계속 | |
| F10 | 원본 불변 플래그 | `chflags uchg` | op `failed`(`E_PERMISSION`) | |
| F11 | TCC 거부 | `EPERM` 래퍼(Desktop 경로) | scan: `W_TCC_DENIED`·루트 `tcc_denied`; apply: `E_TCC_DENIED` 로 op failed | FR-CORE-005 |
| F12 | 계획 후 내용 수정 | 파일에 1바이트 추가 | op `skipped`, 항목 `stale`, `E_STALE`, 나머지 계속 | FR-EX-003 |
| F13 | 계획 후 mtime 만 변경 | `os.utime` | F12 와 같음 | FR-EX-003 |
| F14 | 같은 이름 다른 파일로 교체(새 inode) | 삭제 후 재생성 | `skipped`(E_STALE), 새 파일 불변 | FR-EX-003 |
| F15 | 계획 후 원본 삭제 / 다른 루트로 이동 | | `skipped`, 항목 `stale` | |
| F16 | 계획 후 원본을 심볼릭 링크로 교체 | | `skipped`, 링크 대상 불변 | S2 |
| F17 | 목적지에 파일 생성 | apply 전 `dst` 생성 | `E_DEST_EXISTS`, 덮어쓰기 0 | 02 §10.2-4 |
| F18 | 대소문자만 다른 목적지 존재 | `dst`=`A.txt`, 기존 `a.txt` | `E_DEST_EXISTS`(대소문자 무시 볼륨) | |
| F19 | 목적지 볼륨 분리 | apply 전 `hdiutil detach` | `E_VOLUME_UNAVAILABLE`, 원본 보존 | FR-EX-005 |
| F20 | 복사 도중 볼륨 분리 | `xdev.copy_partial` 에서 detach | op `failed`, 원본 보존, 재마운트 후 recover 로 잔여물 정리 | |
| F21 | 볼륨 응답 없음 | probe 무한 대기 | apply `E_VOLUME_TIMEOUT`, scan `W_ROOT_UNAVAILABLE`, 제한 시간 = `volume_probe_timeout_s`+2초 | FR-CORE-006, NFR-REL-001 |
| F22 | 읽기 전용 목적지 볼륨 | `-readonly` 재마운트 | op `failed`(`E_PERMISSION`) | |
| F23 | 휴지통 비운 뒤 undo | 휴지통 파일 삭제 | `undo_failed`, `E_UNDO_IMPOSSIBLE` | FR-EX-006 |
| F24 | undo 시 원위치에 새 파일 | | `--on-conflict fail` → `E_DEST_EXISTS`; `rename` → 08 이름으로 복원 | |
| F25 | 승인 후 보호 등급 상향 | `rule add` | `skipped`(E_PROTECTED) | 02 §10.2-3 |
| F26 | 동시 쓰기 | 두 프로세스 `scan run`, `--wait-lock 0` | 하나 성공, 하나 `E_LOCKED`(종료 7) | FR-CORE-007 |
| F27 | apply 중 다른 프로세스의 `decision.set` | | `E_LOCKED`(대기 초과) 또는 대기 후 성공, plan 연산 영향 없음 | |
| F28 | DB 손상 | DB 파일 중간 4KB 를 0 으로 | 일반 명령 `E_DB_CORRUPT`(종료 10), `doctor` 는 `healthy=false` | |
| F29 | 마이그레이션 중 크래시 | `migrate.mid` | 다음 실행에서 트랜잭션 롤백 상태 확인, 백업 파일 존재, 재시도 성공 | 06 §7 |
| F30 | 적용된 마이그레이션 파일 체크섬 변경 / DB 버전이 코드보다 높음 | | `E_DB_MIGRATION`, 읽기·쓰기 거부, `details.backup_path` | 06 §7 |
| F31 | 승인 대화상자 거부 / 시간 초과 / 응답 없음 | 대화상자 함수에 실행기 주입(`unit/test_native_dialog_runner.py`) | `E_APPROVAL_DENIED`, plan `draft` 유지, 잠금을 잡지 않은 채 기다림(02 §10.3-6) | FR-EX-002 |
| F32 | serve 프로세스 크래시 | serve 에 SIGKILL | `CoreClient` 재기동(Swift 테스트), 실행 중이던 plan 은 recover 대상으로 표시 | 10 §3.7 |
| F33 | 스캔 중 SIGINT / serve 취소 | CLI 에 SIGINT, serve 에 `{"control":"cancel"}` | `E_CANCELLED`(종료 130), `scan_runs.status=interrupted`, 커밋된 루트 결과 유지, 다음 스캔이 정상 진행 | 02 §5.5 |
| F39 | apply 중 SIGINT | 진행 이벤트 1개 후 SIGINT(CLI) / serve 프로세스에 SIGINT | `E_PARTIAL` + `data.resumable=true`(`E_CANCELLED` 아님), 이름변경 중 op 는 `done`, 복사 중 op 는 임시 파일 제거 후 `pending`, 남은 op `pending`, 계획 `executing`, serve 세션 유지. 다시 `plan apply` → 남은 op 만 실행. 또는 `plan cancel` → 남은 op `skipped`, 계획 `partial`/`cancelled` | 08 §7.6.2, §7.7, §7.10 |
| F40 | undo 중 크래시 | 체크포인트 `undo.undoing_committed`(파일 호출 전), `undo.fs_done`(파일 호출 후) | recover: 앞의 경우 원위치 없음·목적지 있음 → `undoable` 로 되돌림, 뒤의 경우 원위치 있음 → `undone`. 유실 0 | 06 §4.5, 08 §10 |
| F34 | 필드 암호화 키 없음 | 테스트 키 파일 삭제 | 메모 필드 `null` + `W_FIELD_KEY_UNAVAILABLE`, 나머지 동작 | 06 §6 |
| F36 | 다른 Mac 의 DB 복사 | (a) 샌드박스 A 의 `dayclose.db` 만 B 로 복사(다른 `config.device_id`) (b) DB 와 `config.toml` 을 함께 복사(device_id 일치) 후 `app_meta.host_uuid_sha256` 을 다른 값으로 바꿔 다른 Mac 을 흉내 | 둘 다: `doctor` 가 `ok=true`, `healthy=false`, `W_DEVICE_MISMATCH`; `plan.create`/`plan.approve`/`plan.apply`(`--dry-run` 포함)/`plan.undo`/`plan.recover` 가 파일 시스템을 건드리기 전에 `E_DEVICE_MISMATCH`(종료 5) + `W_DEVICE_MISMATCH`; `plan.show`/`plan.list`/`audit.list` 는 경고만; 트리·DB 불변. 원 host UUID 는 DB·로그 어디에도 없음(누출 스캐너 needle) | 02 §8.1, §10.3-4a, 08 §7.11 |
| F37 | 보관 폴더 미설정·소실 | `archive.root=""` 에서 archive 결정 → `E_ARCHIVE_TARGET_MISSING`; 설정 후 계획 → 볼륨 분리 → `plan.create` 시 `excluded`(E_ARCHIVE_TARGET_MISSING), 승인 후 분리 → apply `E_VOLUME_UNAVAILABLE` op failed, 원본 보존 | FR-AB-001 |
| F38 | 보관 폴더 볼륨 행 | `archive.root` 가 응답 없는 볼륨(probe 무한 대기) | `config set`·`plan.create`·`apply`·`doctor` 모두 `volume_probe_timeout_s`+2초 안에 `E_VOLUME_TIMEOUT`/`access: timeout` | 02 §10.5 |
| F35 | 시계 역행·시간대 변경 | `clock` 주입 | 리뷰 날짜 계산이 단조성을 요구하지 않고 이월이 중복 증가하지 않음(FR-DR-006 멱등) | FR-DR-002 |

---

## 7. 성능 검사

`core/tests/integration/perf/`, `@pytest.mark.perf`. 결과는 JSON 한 줄로 stdout 에 출력하고 마일스톤 종료 PR 본문에 붙인다(12 문서 M1 "측정값 기록"). 저장소에 결과 파일을 커밋하지 않는다.

| 테스트 | 조건 | 기준 | 근거 |
|---|---|---|---|
| `test_nfr_perf_003_version_startup` | `dayclose version --json` 20회, 첫 회 제외 중앙값·p95 | p95 ≤ 250ms | NFR-PERF-003 |
| `test_m1_warm_scan_10k` | 1만 엔트리 샌드박스, 변경 없음 재스캔 | ≤ 2초 | 12 M1 종료 기준 |
| `test_nfr_perf_001_warm_scan_100k` | `perf_100k`: 10만 엔트리(대부분 0바이트 파일 — 디스크 사용 최소화), 1% 변경 후 재스캔 | ≤ 10초 | NFR-PERF-001 |
| `test_nfr_perf_002_serve_latency` | serve 에 `review.summary` 100회, `item.list`(limit=200) 100회, DB 는 50만 엔트리·2만 항목을 `store` 함수로 직접 채움 | 각 p95 ≤ 300ms | NFR-PERF-002, 02 §4 재검토 조건 |
| `test_nfr_disk_001_db_size` | 위 50만 엔트리 DB 에서 `VACUUM` 후 크기 | ≤ 200MB | NFR-DISK-001 |
| `test_log_rotation_cap` | 로그 20MB 분량 기록 | 파일 5개 × 5MB 이하 | NFR-DISK-001 |
| `test_fr_core_006_probe_deadline` | 응답 없는 모의 루트 | 전체 `scan run` ≤ `volume_probe_timeout_s`+2초 | FR-CORE-006 |
| Swift `testGalleryScroll200`(XCUITest, `XCTOSSignpostMetric.scrollDecelerationMetric`) | 200장 그룹 | 히치 비율 목표 60fps 상당(03 이 수치 확정) | FR-VR-002 |

디스크 예산: `perf_100k` 와 50만 엔트리 DB 는 샌드박스 안 희소 디스크 이미지(`hdiutil create -type SPARSE -size 2g`)에 만들고 테스트 후 분리·삭제한다. 실사용 크기는 1GB 미만이어야 하며(AGENTS.md §3.8), 테스트가 시작 시 `shutil.disk_usage(tmp)` 의 여유가 5GB 미만이면 성능 테스트를 사유 있는 skip 으로 건너뛴다(내장 디스크가 자주 가득 차는 환경).

---

## 8. 계약 테스트와 Swift 테스트

### 8.1 Python 계약 (`core/tests/contract/`)

| 테스트 | 내용 |
|---|---|
| `test_fr_core_004_every_command_envelope` | 10 문서 §6 표의 모든 명령을 성공 1회·대표 실패 1회 실행 → stdout 이 정확히 한 줄, `envelope.schema.json` 통과, `ok`/`data`/`error` 규칙(02 §5.4), 종료 코드가 10 §1.3 표와 일치 |
| `test_data_schema_per_command` | 각 성공 봉투의 `data` 가 `api/schemas/<command>.json` 의 `data` 스키마 통과 |
| `test_args_schema_matches_argparse` | 각 명령의 argparse 정의와 `args` 스키마의 필드 이름·필수 여부·enum 이 일치(드리프트 방지) |
| `test_fixtures_regenerate_identically` | `scripts/gen-fixtures.py` 결과(정규화 후) == 커밋된 `contracts/fixtures/` |
| `test_usage_error_is_json` | 알 수 없는 플래그·잘못된 ID 접두사 + `--json` → `E_USAGE` 봉투, 종료 2 |
| `test_partial_has_data` | `plan.apply.E_PARTIAL`, `plan.undo.E_PARTIAL` 만 `ok=false` 이면서 `data != null` |
| `test_serve_transcripts` | `contracts/fixtures/serve/*.jsonl` 재생: ready 첫 줄, id 매칭, 순서 뒤바뀐 응답, 진행 이벤트가 응답 전에만, 제어 메시지, 1MiB 초과 줄, 잘못된 JSON, 중복 id, EOF 드레인 |
| `test_mcp_tools_snapshot` (M8) | `tools/list` 결과(이름·설명·`inputSchema`·`annotations`)가 스냅숏 픽스처와 동일, 비노출 목록 부재 |
| `test_mcp_protocol_basics` (M8) | modern(2026-07-28): `server/discover`, 요청별 `_meta` 버전 검사·미지원 시 `-32022`, 모든 결과 `resultType`, `tools/list` 의 `ttlMs`/`cacheScope`·결정론적 순서. legacy(2025-11-25): `initialize`→`initialized`→`ping`. 공통: 알 수 없는 도구 `-32602` vs 인자 검증 실패 `isError: true`, `structuredContent` 가 `outputSchema` 통과(오류 포함), 취소된 요청에 이후 메시지 0, `progress` 단조 증가, stdout 에 JSON-RPC 외 출력 0, stdin EOF 시 종료 |
| `test_schema_command_lists_all` | `dayclose schema` 목록 == 02 §5.3 명령 ID 집합(`archive.*` 없음) |

### 8.2 Swift (`app/DayCloseKit/Tests/`)

| 테스트 | 내용 |
|---|---|
| `FixtureDecodingTests` | `contracts/fixtures/**/*.json` 전부 디코딩 성공, 모르는 필드 무시(`*.ok-extra-field.json`), 모르는 enum 값 → `.unknown` |
| `CoreClientTests` | 가짜 core(스크립트가 `serve` 전사를 재생)로: ready 버전 불일치 → `.versionMismatch`, 응답 순서 뒤바뀜, 진행 이벤트 전달, 타임아웃, 프로세스 종료 시 대기 요청 실패 + 재기동, stdin EOF 시 정상 종료 |
| `ErrorMappingTests` | 02 §11 전체 코드 → 앱 오류 타입 매핑 누락 0 |

### 8.3 Swift UI (`app/DayCloseUITests/`, M4~)

앱은 실행 인자 `--home <샌드박스>` 로 `scripts/make-sandbox.py day_m2` 데이터를 쓴다(12 M4). UI 테스트도 사용자 파일을 만들지 않는다 — 샌드박스는 테스트 실행 전 스크립트가 `$TMPDIR` 아래 생성.

| 테스트 | FR |
|---|---|
| `testMainSummaryMatchesCore` — 지표 카드 수치 == `review.summary` | FR-VR-001 |
| `testKeyboardOnlyGroupReview` — K/D/A/M/S/←/→/⌘Z 만으로 그룹 하나 완료, 결정이 core 에 기록 | FR-VR-005 |
| `testDisallowedKeyShowsReason` — 보안 자산에서 D → 무시 + 이유 표시 | FR-VR-005 |
| `testGalleryLazyThumbnails` | FR-VR-002 |
| `testSpaceOpensQuickLook` — 리스트 모드 Space | FR-VR-003 |
| `testCompareModeKeepsSelected` — 중복 그룹 비교 모드 | FR-VR-004 |
| `testMetadataOnlyNoPreviewNoCache` — 보안 자산 열람 후 캐시 디렉터리 파생물 0 | FR-VR-006 |
| `testEphemeralPreviewNotCached` — 환자 항목 Space 미리보기 후 디스크 캐시 0 | FR-VR-006 |
| `testApproveBindsDisplayedHash` — 화면의 해시와 다른 plan 이 그 사이 생성돼도 버튼은 표시 중인 해시로만 승인(M5) | FR-VR-007 |
| `testAccessibilityAudit` — `XCUIApplication.performAccessibilityAudit()` (확인 필요: Xcode 27 API 유지 여부) | NFR-A11Y-001 |

---

## 9. 수동 실기기 검증 목록

자동화할 수 없는 항목. **소유자가 직접** 실행하며, 에이전트는 체크리스트를 제시만 한다(AGENTS.md §3.7: TCC 변경·LaunchAgent 등록은 사용자 확인 없이 하지 않음). 실제 데이터 대신 소유자가 만든 테스트 폴더(`~/DayCloseTest/`)와 테스트용 USB/외장 폴더를 쓴다. 결과는 마일스톤 종료 PR 에 체크 표시로 기록.

### 9.0 두 기기 원칙 (02 §8.1)

아래 체크리스트는 **MacBook 과 Mac mini 에서 각각** 실행하고 기기별로 따로 기록한다(설치가 독립이므로 한 기기의 결과가 다른 기기를 보증하지 않는다). Mac mini 는 `/Volumes/External` 이 상시 연결된 상태에서 외장 관련 항목을 수행한다. 기본 루트는 홈 아래만이므로 외장 루트·보관 폴더는 각 기기에서 사용자가 직접 `root add`·`config set archive.root` 한 뒤 점검한다.

### 9.1 TCC / 전체 디스크 접근 (M1·M7, 09 문서 절차)

- [ ] FDA 없이 셸에서 `dayclose doctor` — `~/Desktop`·`~/Documents`·`~/Downloads` 각각 `ok` 또는 `tcc_denied` 가 실제 상태와 일치(FR-CORE-005).
- [ ] 같은 명령을 launchd(테스트 LaunchAgent, 09 의 비교 절차)로 실행해 결과 비교 기록.
- [ ] FDA 없는 launchd 실행에서 `/Volumes/External` 아래 루트가 있어도 `volume_probe_timeout_s`+2초 안에 `W_ROOT_UNAVAILABLE` 로 종료(NFR-REL-001, 실제 행 재현).
- [ ] DayClose.app 에 FDA 부여 후 예약 실행에서 같은 루트가 `ok`(M7).
- [ ] FDA 미부여 안내가 알림·앱에 나오고 설정 경로 문구가 실제 macOS 26 메뉴와 일치(FR-MI-004).
- [ ] Python 인터프리터에 FDA 를 주지 않았음을 시스템 설정에서 확인(02 §10.5).
- [ ] (M7) 앱을 다시 빌드한 뒤 FDA 가 유지되는지 확인: 재빌드 → 예약 실행 → `doctor` 의 `full_disk_access`·외장 루트 `access`. 풀렸으면 09 의 대응 절차 기록.
- [ ] Mac mini: FDA 없는 launchd 실행에서 `/Volumes/External` 루트·`archive.root` 가 있어도 멈추지 않고 경고로 끝남(실제 TCC 행 재현).

### 9.2 알림·메뉴바·스케줄 (M7)

- [ ] 첫 실행 알림 권한 요청 표시, 거부 시 앱 안 배너로 대체(09).
- [ ] 21:00 알림 문구가 FR-MI-003 형식, [지금 검토] 클릭 → 결산 화면, [나중에] → 알림 해제.
- [ ] 잠자기 중 놓친 예약 → 깨어난 뒤 1회만 실행(FR-MI-002).
- [ ] 메뉴바 미결 수 == `item list --open` total(FR-MI-001).
- [ ] `SMAppService` 등록 상태가 시스템 설정 → 일반 → 로그인 항목에 DayClose 로 표시.

### 9.3 Quick Look·썸네일 (M4)

- [ ] CONTEXT 턴1 표의 유형별 미리보기: 이미지, PDF, docx/xlsx/pptx, 동영상, ZIP(내부 목록), 소스코드, Markdown, DMG/PKG(메타데이터 패널), 앱(아이콘·버전·용량·마지막 사용일), 폴더(FR-VR-003).
- [ ] 테스트 보안 자산(샌드박스 생성 `.p12`)은 Space 를 눌러도 내용 미리보기 없음, 이름 마스킹(FR-VR-006).
- [ ] 미리보기 후 `~/Library/Caches/DayClose` 에 해당 항목 파생물 없음(Finder 로 확인 + `find` 크기 기록).
- [ ] iCloud Drive 의 dataless 파일(소유자가 고른 테스트 파일, 저장 공간 최적화로 내려간 상태)을 스캔·`vault health`·앱 목록·미리보기 목록에 두어도 다운로드가 시작되지 않음: 전후 `ls -lO` 의 `dataless` 플래그 유지, Finder 의 구름 아이콘 유지(FR-CORE-008). 같은 파일이 두 기기 리뷰에 각각 나오고 `keep/keep_always/defer` 만 가능.

### 9.4 승인·실행 (M5)

- [ ] Claude Code 세션(테스트 폴더 대상)에서 `plan approve` → 네이티브 대화상자가 전면에 뜨고 plan 요약·해시 앞 8자리 표시, "승인" 클릭 전에는 실행 안 됨, 120초 방치 시 `E_APPROVAL_DENIED`.
- [ ] 터미널(TTY)에서 해시 8자리 입력 승인, 오입력 3회 거부.
- [ ] 실제 `~/.Trash` 로 이동한 테스트 파일이 Finder 휴지통에 보이고 `plan undo` 로 원위치. (Finder 의 "되돌려 놓기"는 지원 대상 아님 — 08 결정 확인.)
- [ ] 외장 볼륨(테스트 USB)으로 이동 도중 케이블 분리 → 원본 보존, 재연결 후 `plan recover` 정상(FR-EX-005).
- [ ] `archive.root` 를 외장(Mac mini: `/Volumes/External/DayCloseArchive` 아래 테스트 폴더)으로 두고 테스트 파일 보관 → `<root>/<YYYY>/<MM>/` 배치, `plan undo` 로 원위치(FR-AB-001).
- [ ] 08 의 "소유자 첫 실사용 전 체크리스트" 서명(12 M5).
- [ ] **iCloud 휴지통 해제 검증(08 §9.1, 09 V18~V21 — MacBook·Mac mini 각각)**: 사람이 만든 테스트 파일 1개로 (1) 이 엔진의 `trash` 후 다른 기기에서 삭제 전파·iCloud.com "최근 삭제된 항목" 보존·`plan undo` 후 다른 기기 복원 (2) 이름변경이 다운로드·재업로드 외 트래픽을 만들지 않음(`fs_usage`·네트워크 관찰) (3) 업로드 미완료 파일 판정 방법 확인 (4) §3.10 모의 시나리오 녹색. 네 조건이 두 Mac 모두 `ok` 일 때만 `TRASH_UNLOCK_VERIFIED=True` 변경(Security 리뷰). 승인 화면에 "N개 파일은 iCloud 를 통해 다른 기기에서도 삭제됩니다" 줄이 보이는지 대화상자·TTY·앱에서 확인.

### 9.5 Skill·MCP (M8)

- [ ] Skill 설치 위치: Claude Code `~/.claude/skills/dayclose`, Codex `~/.agents/skills/dayclose` 링크가 각 도구의 Skill 목록에 보임(10 §8.1).

- [ ] Claude Code·Codex 각각에서 Skill 이 "오늘 정리하자" 류 요청에 트리거되고, 승인 단계에서 반드시 사람에게 넘김(10 §8).
- [ ] Claude Code 의 MCP 도구 목록에 승인·undo·apply 도구가 없음.
- [ ] 에이전트 화면(대화)에 환자 유사 테스트 파일 이름·보안 자산 경로가 나오지 않음(10 §1.5).

---

### 9.6 기기별 기록 양식

| 항목 | MacBook | Mac mini |
|---|---|---|
| M3 읽기 전용 실사용(`scan run` + `review summary` + `vault health`, 소유자 직접) | | |
| M7 셸 vs launchd 비교 | | |
| M7 재빌드 후 FDA 유지 | | |
| `/Volumes/External` 행 재현(FDA 없음) | 해당 시 | 필수 |
| iCloud 자리표시자 비다운로드 | | |
| V17 “데스크탑 및 문서” 동기화 판정(M4) | | |
| iCloud 휴지통 해제 V18~V21(M5, 08 §9.1) | | |

### 9.7 09 실기기 검증 항목(V1~V16)의 마일스톤 배정

09 §12 의 V 항목은 12 로드맵과 같은 마일스톤에 배정하고, 각 마일스톤 종료 PR 에 §9.6 기록표와 함께 기기별 결과를 남긴다. 절차·대안은 09 가 정한다.

| 마일스톤 | V 항목 | 이 문서의 관련 절 |
|---|---|---|
| M4 | V1(FDA 프로브 정확도), V2(설정 패널 URL), V3(자식 core 가 앱의 FDA 를 따름), V7(FDA 와 iCloud), V9(`metadata_only`·`ephemeral` 열람 후 파일 미개방·QL 캐시), V16(복사된 DB 배너·승인 버튼 비활성), V17(“데스크탑 및 문서” 동기화 판정 — 실패 시 `root set --icloud-synced` 로 대체) | §9.1, §9.3, F36, §3.10 |
| M5 | V8(`~/.Trash` 와 Finder 되돌려 놓기), V11(Secure Enclave 서명 승인 가능 여부), V18~V21(iCloud 휴지통 해제 근거 — 08 §9.1 의 네 조건, **두 Mac 각각**) | §9.4, §4.1, §3.10 |
| M6 | V12(Vision 한국어 OCR) | M6 표 |
| M7 | V4(헬퍼가 앱 FDA 를 따름), V5(재빌드 후 FDA 유지), V6(헬퍼 번들·알림 도메인), V10(활성화 정책 전환), V13(잠자기 보충 실행), V14(FDA 없는 예약 실행 제한 시간), V15(재빌드 후 SMAppService 상태·다른 서명의 실패 모습) | §9.1, §9.2 |

## 10. 마일스톤별 인수 체크리스트

형식: 요구사항 ID → 테스트 이름(AGENTS.md §5 규칙: 이름에 FR ID). 통합 테스트는 `integration/`, 안전은 `safety/`. "종료 기준"은 12 문서 그대로이며 각 줄에 검증 수단을 붙였다.

### M1 — Core 골격 + 스냅샷·변경 감지

| ID | 테스트 |
|---|---|
| FR-CORE-001 | `test_fr_core_001_init_idempotent`, `test_fr_core_001_home_0700_db_0600` |
| FR-CORE-002 | `test_fr_core_002_default_roots_in_fake_home`(downloads·desktop·documents·icloud_drive·projects, iCloud 폴더가 없으면 건너뛰고 경고),  `test_fr_core_002_missing_root_warns`, `test_fr_core_002_screenshot_location_differs`(가짜 `defaults`), `test_fr_core_002_root_add_remove_list` |
| FR-CORE-003 | `test_fr_core_003_create_modify_delete_rename_one_event_each`, `test_fr_core_003_rescan_no_events`, `test_fr_core_003_package_dir_single_entry`, `test_fr_core_003_excludes_ds_store_node_modules_git`, `prop_fs_diff`(§5.2) |
| FR-CORE-004 | `test_fr_core_004_every_command_envelope`(M1 명령) |
| FR-CORE-005 | `test_fr_core_005_doctor_root_access`(tcc_denied 는 EPERM 주입), `test_fr_core_005_tcc_vs_permission_distinct` |
| FR-CORE-006 | `test_fr_core_006_probe_deadline`, `test_fr_core_006_dataless_not_hashed`(`st_flags` 주입) |
| FR-CORE-007 | `test_fr_core_007_concurrent_scan_one_locked` |
| FR-CORE-008 | §3.9 의 `test_fr_core_008_*` 전부, `test_exclude_globs_relative_to_root` |
| 02 §8.1 | `test_doctor_device_mismatch_copied_db`(F36 a·b — host UUID 포함), `test_default_roots_never_under_volumes` |
| 02 §5.3 root icloud | `test_root_icloud_override_precedence`, `test_root_icloud_assumed_default`(M1 `root add --icloud-synced`), `test_root_set_reevaluates_items`, `test_root_set_not_in_mcp`(M2) |
| 02 §10.4 | `test_sandbox_home_outside_sandbox_rejected`(샌드박스인데 `DAYCLOSE_HOME` 이 밖이면 시작 거부 `E_SANDBOX_VIOLATION`, 아무 파일도 안 만듦), `test_sandbox_guard.py` |

종료 기준 검증: pytest·ruff·mypy 녹색(CI 명령 §12) / FR-CORE-008(§3.9) / 루트 기준 상대 제외·겹치는 루트 처리(`test_exclude_globs_relative_to_root`, `test_fr_core_008_nested_roots_no_duplicates`) / 재스캔 이벤트 0(`test_fr_core_003_rescan_no_events`) / 1만 웜 스캔 ≤ 2초(`test_m1_warm_scan_10k`, 측정값 기록) / 실제 `~` 접근 0(§2 전체) / 계약 픽스처 4종 존재(`test_fixtures_regenerate_identically`).

### M2 — 리뷰 모델 + 보호 정책 + 프로젝트 문맥

| ID | 테스트 |
|---|---|
| FR-DR-001 | `test_fr_dr_001_summary_counts_match_manifest`, `test_fr_dr_001_estimated_minutes_formula` |
| FR-DR-002 | `test_fr_dr_002_0130_belongs_to_previous_day`, `prop_review_date` |
| FR-DR-003 | `test_fr_dr_003_group_keys_per_04`, `test_fr_dr_003_group_without_suggestion_listed` |
| FR-DR-004 | `test_fr_dr_004_group_decision_skips_protected_warns`, `test_fr_dr_004_disallowed_action_e_protected`, `test_fr_dr_004_item_list_atomic` |
| FR-DR-005 | `test_fr_dr_005_decision_does_not_touch_files`(S1 트리 해시), `test_fr_dr_005_undo_after_planned_invalid_state` |
| FR-DR-006 | `test_fr_dr_006_carryover_increments_once`, `test_fr_dr_006_carryover_disabled` |
| FR-DR-007 | `test_fr_dr_007_defer_hides_until_date` |
| FR-DR-008 | `test_fr_dr_008_keep_always_survives_move_to_other_root`, `test_fr_dr_008_suppression_remove_reasks`, `test_fr_dr_008_quietly_kept_count` |
| FR-DR-009 | `test_fr_dr_009_report_masks_secret_and_patient`(누출 스캐너) |
| FR-SO-001 | `test_fr_so_001_installed_dmg_suggest_trash` |
| FR-SO-002 | `test_fr_so_002_three_duplicates_one_group_newest_keep` |
| FR-SO-003 | `test_fr_so_003_project_name_in_filename_confidence`, `test_fr_so_003_missing_dest_marked_create` |
| FR-SO-004 | `test_fr_so_004_repo_file_trash_move_protected`, `test_fr_so_004_dev_cache_item_trash_allowed` |
| FR-AM-003 | `test_fr_am_003_dirty_repo_item_dirty_count` |
| FR-PM-001 | `test_fr_pm_001_allowed_actions_matrix` |
| FR-PM-002 | `test_fr_pm_002_patient_pattern_sensitivity_no_trash`, `test_fr_pm_002_rrn_in_text` |
| FR-PM-003 | `test_fr_pm_003_rule_add_path_prefix_protects`, `test_fr_pm_003_builtin_rule_not_removable`, `test_rule_ids_use_rul_prefix`(`rule.*` 는 `rul_`, `prl_` 를 주면 `E_USAGE`) |
| 02 §5.3 suppression.add | `test_suppression_add_path_glob_suppresses_open_items`, `test_suppression_never_applies_to_protected` |

종료 기준 검증: 06 §4.1 전이 전부(`test_item_transitions_allowed[*]` 파라미터화 + `prop_item_transitions` 의 비허용 → `E_INVALID_STATE`) / 결정 전후 트리 해시 불변(S1) / 환자 패턴 파일이 리포트·로그에 실경로로 없음(`test_leak_report_masking`) / `scripts/demo-m2.sh` 가 샌드박스에서 종료 0.

### M3 — Secure Vault 읽기 전용 + App Manager

| ID | 테스트 |
|---|---|
| FR-SV-001 | `test_fr_sv_001_each_kind_detected[<kind>]`(§3.4 표 파라미터화, `vault_asset_kind` 17종 중 `unknown_secret` 제외 전부) |
| FR-SV-002 | `test_fr_sv_002_extensionless_openssh_key`, `test_fr_sv_002_aws_key_in_notes_txt`, `test_fr_sv_002_without_gitleaks_warns_only`, `test_fr_sv_002_gitleaks_redact_no_match_stored`(`needs_gitleaks`) |
| FR-SV-003 | `test_fr_sv_003_trash_move_archive_e_protected`, `test_fr_sv_003_group_auto_excluded` |
| FR-SV-004 | `test_leak_after_vault_scan`, `test_fr_sv_004_masked_names` |
| FR-SV-005 | `test_fr_sv_005_23_days_expiring_soon_high`, `test_fr_sv_005_password_p12_expiry_unknown`, `test_fr_sv_005_annotate_expires` |
| FR-SV-006 | `test_fr_sv_006_finding[<vault_finding_type>]`(9종), `test_vault_annotate_backup_resolves_no_backup`(`--backup verified` 만이 `backup_status` 를 바꾸고 `no_backup` 이 `resolved`), `test_backup_status_unchanged_by_scan` |
| FR-SV-007 | `test_fr_sv_007_tracked_key_revoke_advice_acknowledge_only` |
| FR-SV-008 | `test_fr_sv_008_seed_no_fingerprint_no_path_in_log`, `test_leak_seed_no_derivatives` |
| FR-AM-001 | `test_fr_am_001_app_added_version_changed_removed` |
| FR-AM-002 | `test_fr_am_002_brew_fixture_new_removed_on_request`, `test_fr_am_002_brew_missing_warns` |
| FR-AM-004 | `test_fr_am_004_new_launch_agent_item`, `test_fr_am_004_weekly_only` |
| FR-AM-005 | `test_fr_am_005_inactive_repo_cache_trash_suggested_only` |
| FR-AM-006 | `test_fr_am_006_unused_90_days_monthly_report` |

종료 기준 검증: §9.6 의 M3 실사용을 두 기기 각각 / 누출 스캐너가 `core.log`·DB 원시 바이트+`.dump`·모든 stdout 에서 0건 / gitleaks 없는 PATH 에서 녹색(`test_fr_sv_002_without_gitleaks_warns_only` + 전체 스위트를 `PATH` 에서 gitleaks 제거한 상태로 1회) / `scripts/demo-m3.sh` 종료 0 / 소유자 실 `~` 수동 실행(§9 아님 — 12 M3 의 읽기 전용 실행, 소유자 직접).

### M4 — SwiftUI 검토 앱 (첫 MVP)

| ID | 테스트 |
|---|---|
| FR-VR-001~006 | §8.3 표의 UI 테스트 |
| NFR-PERF-002 | `test_nfr_perf_002_serve_latency` |
| NFR-A11Y-001(키보드) | `testKeyboardOnlyGroupReview`, `testAccessibilityAudit` |
| serve 프로토콜 | `test_serve_transcripts`, `CoreClientTests` |

종료 기준 검증: 09 V1·V2·V3·V7·V9·V16·V17(§9.7) 기기별 기록 / `swift test` 녹색·모든 픽스처 디코딩(`FixtureDecodingTests`) / 보안·환자 항목 열람 후 캐시 파생물 0(`testMetadataOnlyNoPreviewNoCache`, `testEphemeralPreviewNotCached`, §9.3 수동) / 앱 코드 파일 변경 API 0(`test_no_mutation_in_swift.py`) / 실행 버튼 비활성(`testExecuteDisabledInMvp`).

### M5 — 안전 실행

| ID | 테스트 |
|---|---|
| FR-EX-001 | `test_fr_ex_001_same_input_same_hash`, `test_fr_ex_001_create_does_not_touch_files`, `prop_plan_hash` |
| FR-EX-002 | `test_fr_ex_002_non_tty_dialog_denied`, `test_fr_ex_002_hash_mismatch`, `test_mcp_has_no_approval_tools`(M8 에서 실제 서버로 재검증), §4.1 승인 테스트 전부 |
| FR-EX-003 | F12~F16 |
| FR-EX-004 | `test_fr_ex_004_trash_is_rename_to_volume_trash`, `test_fr_ex_004_undo_restores`, `test_no_mutation_outside_executor.py` |
| FR-EX-005 | `test_fr_ex_005_cross_volume_hash_verified`(`hdiutil`), F03~F05·F07·F19·F20 |
| FR-EX-006 | F01~F06, F39, F40, `test_fr_ex_006_undo_roundtrip`, `prop_executor`(§5.1) |
| FR-EX-007 | `test_fr_ex_007_audit_list_channel_no_paths` |
| FR-EX-008 | §3.10 의 `test_fr_ex_008_*`, `test_icloud_propagates_check_constraint`, `test_icloud_gate_constant_false_without_record`, `test_config_allow_trash_owner_only` |
| FR-AB-001 | `test_archive_unencrypted_warns`, `test_fr_ab_001_archive_root_layout_year_month`(`<root>/<YYYY>/<MM>/<이름>`, 충돌 시 08 규칙), `test_fr_ab_001_archive_decision_rejects_dest`, `test_fr_ab_001_archive_root_unset_missing`, `test_fr_ab_001_cross_volume_archive_hash_verified`(`hdiutil`), `test_fr_ab_001_archive_undo_restores`, F37·F38 |
| FR-VR-007 | `testApproveBindsDisplayedHash`, `testApplyProgressAndUndo` |

종료 기준 검증: 09 V8·V11·V18~V21(§9.7, 두 Mac) / §3.10 FR-EX-008 테스트 전부(게이트 상수는 V18~V21 기록이 없으면 `False` 유지) / 장애 주입 스위트 F01~F40 녹색, §4.1 승인 무결성 테스트 전부, 모든 시나리오 `assert_no_loss` / 정적 검사 executor 외 0, `os.unlink`·`os.remove` 1곳 / §9.4 수동 + 08 체크리스트 서명.

### M6 — AI + 학습

| ID | 테스트 |
|---|---|
| FR-SO-005 | `test_fr_so_005_ai_disabled_zero_network`, `test_fr_so_005_patient_secret_not_in_payload`(가짜 로컬 공급자) |
| FR-SO-006 | `test_fr_so_006_ocr_rrn_sets_patient`(가짜 `dayclose-native` 출력), `test_fr_so_006_ocr_text_encrypted` |
| FR-PM-004 | `test_policy_ids_use_prl_prefix`(`policy.*` 응답·인자는 `prl_`, `rul_` 를 주면 `E_USAGE`), `test_policy_reject_active_to_disabled`, `test_fr_pm_004_five_trash_decisions_suggest_rule`(임계값은 07), `test_fr_pm_004_active_rule_fills_suggestion_still_needs_approval` |
| FR-PM-005 | `test_fr_pm_005_gate_strips_none_policy_secret_patient`, `test_leak_ai_payload`, `test_fr_pm_005_ai_requests_metadata_only` |
| NFR-PRIV-002 | `test_nfr_priv_002_no_network_when_ai_disabled` |

종료 기준 검증: 09 V12(§9.7) / 위 + 게이트 회귀(`prop_agent_view` 와 같은 생성기로 게이트 입력 생성) / ollama 실제 연동은 `needs_ollama` 사유 skip 가능(설치된 경우만).

### M7 — 메뉴바·자동 실행·알림·TCC

| ID | 검증 |
|---|---|
| FR-MI-001~004 | §9.1·§9.2 수동 + `test_fr_mi_004_schedule_channel_never_blocks`(F21 를 `--channel schedule` 로), `test_schedule_cannot_approve` |
| NFR-REL-001 | F21 + §9.1 실제 launchd 행 재현 |

종료 기준 검증: 09 V4·V5·V6·V10·V13·V14·V15(§9.7) / 09 의 "셸 vs launchd" 비교 결과와 "재빌드 → FDA 유지" 결과를 **MacBook·Mac mini 각각** PR 에 기록(§9.6).

### M8 — Skill·MCP

| ID | 테스트 |
|---|---|
| FR-AG-002 | `test_skill_md_frontmatter_valid`(frontmatter 키가 Claude Code·Codex 교집합 `name, description, allowed-tools` 뿐, 이름 ≤ 64자, 설명 ≤ 1024자, 10 §8.1), `test_skill_allowed_tools_exclude_mutations`(`allowed-tools` 에 `plan approve/apply/undo`, `rule remove`, `config set` 패턴 없음), `test_skill_commands_exist`(SKILL.md 의 모든 `dayclose …` 예시가 `dayclose schema` 에 있는 명령·플래그), `test_skill_never_instructs_approval_by_agent`, §9.5 수동 |
| FR-AG-003 | `test_mcp_tools_snapshot`, `test_mcp_protocol_basics`, `test_mcp_has_no_approval_tools`, `test_leak_agent_channels`(mcp) |

---

## 11. 이 계획이 다른 문서에 요구하는 것

| 대상 | 요구 | 상태(2026-11-24 재조정 후) |
|---|---|---|
| 02 §3 | 개발 의존성 `hypothesis`, `jsonschema` | 반영됨 |
| 02 §10.4·§15.1 | `DAYCLOSE_TEST_NOW`, `DAYCLOSE_TEST_FAULT`(샌드박스 전용), 감사 훅 가드, `DAYCLOSE_HOME` 이 샌드박스 밖이면 시작 거부 | 반영됨 |
| 02 §6·§10.3-4 | `run_tool` 절대경로·고정 환경, 샌드박스에서만 `$SANDBOX/bin` 우선 | 반영됨 |
| 02 §6, 04, 08, 09 | 고정 시스템 경로는 `common/paths.system_path(name)` 경유(§2.3 표) | 02 반영됨, 04·09 의 경로 목록과 §2.3 표 대조 필요 |
| 02 §14 | `app/DayCloseUITests/` | 반영됨 |
| 08 | apply 시 해시 재계산·감사 교차·24시간 | 반영됨(08 §7.1 G4~G6) |
| 08 | **체크포인트 이름 목록**(§6.1 F01~F05·F20·F29·F40 이 쓰는 `op.running_committed`, `op.fs_done`, `xdev.copy_partial`, `xdev.verified`, `xdev.src_removed`, `undo.undoing_committed`, `undo.fs_done`, `migrate.mid`) | **남음** — 08 에 이름이 없다. 08 이 다른 이름을 정하면 그쪽을 쓴다 |
| 04 | `collect/fs` 의 `lstat` 대체 지점(dataless `st_flags` 주입, §3.9) | **남음**(확인 필요) |
| 05 | 시드 단어 목록 모듈 위치, 합성 주민등록번호 검증 규칙 | **남음**(확인 필요) |
| 03 | 갤러리 스크롤 성능의 측정 지표·수치 | **남음**(확인 필요) |

---
## 12. 실행 명령

```bash
# 머지 전 (core)
cd core
uv sync
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
uv run pytest                                  # unit + contract + integration + safety (perf·nightly 제외)
uv run pytest tests/safety                     # 안전 스위트 단독 (머지 차단)

# M4 이후
swift test --package-path app/DayCloseKit
xcodebuild -project app/DayClose.xcodeproj -scheme DayClose -configuration Debug build
xcodebuild test -project app/DayClose.xcodeproj -scheme DayClose -destination 'platform=macOS'   # 마일스톤 종료 시

# 마일스톤 종료 시
uv run pytest -m perf
HYPOTHESIS_PROFILE=nightly uv run pytest -m "not perf" tests/unit tests/safety   # nightly 표식 포함

# 커밋 전 비밀 검사 (AGENTS.md §3.6)
gitleaks git --staged --redact --no-banner .      # gitleaks 8.30.1 에서 하위 명령·플래그 확인함(2026-11-24)
gitleaks dir --redact --no-banner contracts/
```

- 결정: 테스트 순서 무작위화 플러그인은 도입하지 않는다(개발 의존성 최소화). 순서 의존성은 함수 범위 샌드박스로 차단한다.
- CI 서버는 없다(단일 개발자, 로컬 머신). 결정: `scripts/check.sh` 가 위 "머지 전" 블록을 순서대로 실행하고 하나라도 실패하면 종료 1. 에이전트는 완료 보고 전에 이 스크립트의 실제 출력을 확인한다(AGENTS.md §5).
