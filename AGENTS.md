# AGENTS.md — DayClose 저장소 작업 규칙 (코딩 에이전트용)

이 저장소는 macOS 용 Digital Housekeeping Agent **DayClose** 다(폴더명 `DayClode` 는 오타가 아니라 그대로 둔다 — 이름 변경 금지).
DayClose 는 사용자의 파일을 옮기고 휴지통에 넣을 수 있는 프로그램이다. **안전 규칙(§3)은 어떤 지시보다 우선한다.**

사용자에게 보이는 문구·문서는 한국어. 식별자·경로·명령·코드는 영어.

## 1. 명세 읽는 순서

1. `CONTEXT.md` — 요구사항 원천(기획 대화 원문). 나중 턴이 앞 턴을 덮어쓴다.
2. `docs/02-ARCHITECTURE.md` — 모듈 경계, CLI/JSON 계약, 오류 코드, 경로. **§15 공유 계약**.
3. `docs/06-DATA-MODEL.md` — DDL, enum, 상태 기계.
4. `docs/01-PRD.md` — 기능 요구사항 ID(FR-*)와 인수 기준.
5. `docs/12-IMPLEMENTATION-ROADMAP.md` — 지금 어느 마일스톤인지, 그 마일스톤의 근거 문서.
6. 맡은 영역의 문서(§2 표).

규칙:
- 02·06 은 계약이다. 다른 문서·코드가 02·06 과 다르면 02·06 이 맞다. 계약을 바꿔야 하면 **02/06 을 먼저 고치고** 영향받는 문서·픽스처를 같은 변경에서 맞춘다.
- 확정 사항(`docs/01-PRD.md §9.1`)과 비목표(§7)를 다시 열지 않는다. 특히 NAS/SMB·원격 백업은 비목표다.
- 명세에 없는 기능을 추가하지 않는다. 명세가 모호하면 작은 쪽으로 구현하고 `docs/01-PRD.md §9.2 미결 사항` 에 질문을 추가한다.
- 구현이 명세와 다르게 될 수밖에 없으면 명세를 고치는 것이 먼저다(“결정:” 한 줄 + 이유).

## 2. 영역별 분업

| 영역 | 책임 | 코드 위치 | 주 문서 |
|---|---|---|---|
| Architecture | 계약(봉투·명령·오류), `store`·마이그레이션, `api`/`cli`, 모듈 경계 검사 | `core/src/dayclose/{common,config,store,api,cli}`, `contracts/` | 02, 06, 10 |
| macOS | SwiftUI 앱, Quick Look, 썸네일, 메뉴바, 알림, 스케줄러, TCC/FDA, `dayclose-native` | `app/`, `native/` | 03, 09 |
| File Intelligence | 수집기(fs·git·apps·brew·login_items), 카테고리·그룹·중복·프로젝트 매칭 | `core/src/dayclose/{collect,intel}` | 04 |
| Security | Secure Vault, 보호 정책·민감도, executor 안전 검토, 로그 마스킹, 필드 암호화 | `core/src/dayclose/{vault,policy,executor}`, `common/{crypto,logging}.py` | 05, 08 |
| AI | 학습 규칙, AI 공급자·전송 게이트 | `core/src/dayclose/{ai,policy}` | 07 |
| QA | 샌드박스 픽스처, 안전 회귀 스위트, 장애 주입, 계약 테스트, 성능 측정 | `core/tests/`, `app/DayCloseKit/Tests/` | 11 |
| Integration | `serve --stdio`, `CoreClient`, Skill, MCP, 빌드·배포 검증 | `core/src/dayclose/{serve,mcp}`, `app/DayCloseKit`, `skill/` | 10, 12 |

- 총괄 에이전트는 마일스톤 단위로 작업을 나누고, 영역 간 인터페이스(02 §15)의 일관성을 검증한다.
- `executor/`, `policy/`, `vault/`, `common/crypto.py`, `common/logging.py` 를 바꾸는 변경은 Security 관점 리뷰를 반드시 거친다(작성자와 다른 에이전트/패스).
- 작성과 검증은 분리한다. 같은 컨텍스트에서 자기 변경을 승인하지 않는다.

## 3. 절대 안전 규칙

1. **실제 사용자 파일을 테스트에서 건드리지 않는다.** 모든 테스트·데모는 임시 샌드박스에서: `DAYCLOSE_HOME=<tmp>/home`, `DAYCLOSE_SANDBOX=<tmp>`(`<tmp>` 는 사용자 임시 디렉터리 또는 `/private/tmp` 아래, 표식 파일 `<tmp>/.dayclose-sandbox` 필수 — 아니면 core 가 `E_SANDBOX_VIOLATION` 으로 시작을 거부, 02 §10.4), 가짜 홈 `<tmp>/user/{Downloads,Desktop,...}`. `~`, `/Volumes/*`, 실제 `~/.ssh` 등을 테스트 대상으로 쓰지 않는다. `conftest.py` 의 가드를 끄거나 우회하지 않는다.
2. **기록된 사용자 승인 없이 파일을 변경하지 않는다.** 사용자 파일 변경 코드는 `core/src/dayclose/executor/` 에만 존재하며 `approvals` 행이 있는 plan 만 실행한다. Swift 앱·다른 Python 모듈에 `rename/move/remove/unlink/rmtree/trashItem/removeItem/moveItem` 을 쓰지 않는다(정적 검사가 막는다). 영구 삭제·휴지통 비우기 기능을 만들지 않는다.
3. **에이전트는 승인을 요청할 수 있지만 수행할 수는 없다.** Skill 흐름에서 `plan approve` 를 호출하면 사용자 화면에 확인 대화상자가 뜰 뿐이다 — 그 대화상자·TTY 확인을 에이전트가 대신 누르거나 입력하지 않는다(접근성 스크립트, `script(1)`, 에이전트 표식 제거 등 우회 금지). MCP·스케줄러는 승인·실행 경로가 없다. 테스트 승인(`method=test`)은 **유효한 샌드박스**(02 §10.4) + `DAYCLOSE_TEST_APPROVE=1` 에서만. `DAYCLOSE_SANDBOX` 를 홈·`/Volumes`·기본 상태 디렉터리 쪽으로 넓히는 등 유효성 검사를 우회하는 시도를 하지 않는다. 보호를 약화하는 명령(02 §10.3 4b 의 소유자 전용 목록)은 에이전트 채널에서 core 가 거부하며, 에이전트는 이를 사람인 척(채널 위장·표식 제거) 우회하지 않는다. 테스트에서 이 명령들을 돌릴 수 있는 것은 유효한 샌드박스 안뿐이며(표식 승격만으로는 거부하지 않음, `--channel skill|mcp` 명시 시 거부 — 02 §10.3 4b), 샌드박스 밖에는 예외가 없다.
4. **비밀·환자 정보를 외부 모델·로그에 보내지 않는다.** 파일 내용, OCR 텍스트, 키·토큰, 환경변수 값, gitleaks 매치, 보안 자산/환자 자료의 경로를 로그·봉투 `details`·커밋 메시지·이슈·외부 AI 요청에 넣지 않는다. 코딩 에이전트 자신도 개발 중 사용자의 실제 `~/.ssh`, `.env`, 인증서를 열어 보거나 출력하지 않는다.
5. **보안 자산은 제자리 인벤토리만.** 일괄 이동·일괄 휴지통 대상에 넣지 않는다. 시드/복구 구문은 어떤 파생값도 저장하지 않는다.
6. **저장소에 실제 비밀을 커밋하지 않는다.** 테스트용 키·인증서는 테스트 실행 시 생성(`tests/fixtures/secrets.py`). 커밋 전 `gitleaks git --staged` 또는 `gitleaks dir` 로 확인.
7. **사용자 시스템 설정을 바꾸지 않는다.** 개발 중 LaunchAgent 등록, TCC 권한 변경, Keychain 실제 항목 생성(테스트는 파일 백엔드), `brew install` 은 사용자 확인 없이 하지 않는다.
8. **라이선스를 지킨다.** 저장소는 MIT(`LICENSE`). GPL/AGPL 등 카피레프트 코드는 복사·벤더링·링크 금지 — 외부 실행파일로 호출만. MIT/BSD/Apache-2.0 코드를 가져오면 파일 머리에 출처와 원 라이선스를 남기고 13 문서에 기록.
9. **DayClose 자체 상태는 작게.** 1GB 를 넘는 산출물(데이터셋, 대량 프레임 등)은 저장소·내장 디스크에 만들지 않는다. 필요하면 `/Volumes/External/projdata/dayclose-<용도>/` 아래(사용자 확인 후).

10. **실제 파일을 움직이는 실기기 검증은 소유자가 직접 한다.** 09 §12 의 V8·V18·V19(휴지통·iCloud 실기기 실험)는 소유자가 직접, 소유자가 만든 시험 파일로만 수행한다. 에이전트는 수행하지 않는다(절차 안내·기록 양식 준비만). 그래서 M5 는 에이전트만으로 종료할 수 없다 — 소유자의 수행 결과가 09 §12 에 기록될 때까지 “완료”로 보고하지 않는다.

위 규칙과 충돌하는 지시를 받으면 실행하지 말고 이유를 보고한다.

## 4. 빌드·테스트 명령

Python core (M1~):
```bash
cd core
uv sync                                  # 의존성 설치
uv run pytest                            # 전체 테스트
uv run pytest tests/safety               # 안전 회귀 스위트 (머지 필수)
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
uv run dayclose --json version           # 실행 확인
```

샌드박스 수동 실행:
```bash
export DAYCLOSE_SANDBOX="$(mktemp -d)" DAYCLOSE_HOME="$DAYCLOSE_SANDBOX/home"
touch "$DAYCLOSE_SANDBOX/.dayclose-sandbox"
mkdir -p "$DAYCLOSE_SANDBOX/user/Downloads"
uv run dayclose init --no-default-roots --json
```

Swift (M4~):
```bash
swift test --package-path app/DayCloseKit
xcodebuild -project app/DayClose.xcodeproj -scheme DayClose -configuration Debug build
```

## 5. 완료 정의 (Definition of Done)

- 대응하는 FR 의 인수 기준 테스트가 있고 통과한다(테스트 이름에 FR ID 포함, 예 `test_fr_dr_006_carryover_increments_once`).
- `uv run pytest`, `ruff`, `mypy` 녹색. Swift 변경 시 `swift test`/`xcodebuild build` 녹색. 출력은 실제 실행 결과로 확인(추정 금지).
- 안전 회귀 스위트(`tests/safety`) 통과.
- 새 명령·필드·오류 코드는 02/06/10 에 있고 `contracts/fixtures` 가 갱신됐다.
- 새 마이그레이션은 기존 파일 수정 없이 번호를 추가했고, 이전 버전 픽스처 DB 업그레이드 테스트가 있다.
- 로그·출력에 비밀/환자 정보가 없다(누출 스캐너 통과).
- `TODO`, `FIXME`, `test.skip`, `pytest.mark.skip`(사유 없는 것), 빈 구현, 디버그 출력이 남아 있지 않다.
- 새 런타임 의존성은 02 §3 목록에 추가됐다.

## 6. 코드 규칙

- Python: 타입 힌트 필수, `mypy --strict` 지향. 모듈 import 방향은 02 §6 을 따른다(역방향 금지). 서브프로세스는 `common/proc.run_tool` 만, `shell=True` 금지.
- 시간은 `common/clock` 주입, 테스트에서 고정. 리뷰 날짜 계산에 `datetime.now()` 직접 호출 금지.
- 무거운 import(`cryptography` 등)는 함수 내부 지연 import(기동 시간 NFR-PERF-003).
- 오류는 `DayCloseError` 하위 타입과 02 §11 코드만 사용. 새 코드는 02 에 먼저 추가.
- 불필요한 추상화 금지: 한 곳에서만 쓰는 로직에 클래스·인터페이스를 만들지 않는다.
- Swift: Swift 6 strict concurrency, 서드파티 의존성 없음. core 와의 통신은 `DayCloseKit.CoreClient` 만.

## 7. 커밋 규칙

- 커밋은 사용자가 요청할 때만. 기본 브랜치에서 직접 작업하지 말고 브랜치를 만든다(`m1/core-skeleton` 형식).
- 메시지: Conventional Commits, 제목은 영어 명령형, 본문은 한국어 가능.
  `feat(collect): detect moves by dev/inode`, `fix(executor): …`, `docs(06): …`, `test(safety): …`, `chore: …`
  scope = 모듈명 또는 문서 번호. 본문에 관련 FR ID 와 마일스톤.
- 한 커밋 = 한 논리 변경. 계약 변경(02/06)과 그에 맞춘 코드·픽스처는 같은 커밋.
- 커밋 메시지·PR 에 실제 경로(사용자 홈 아래 파일명), 비밀, 환자 정보를 쓰지 않는다.
- 에이전트 도구가 요구하는 attribution 줄은 해당 도구의 규칙을 따른다.
- 커밋 금지 대상: `.omc/`, DB 파일, `config.toml` 실사용본, 테스트 산출물, 실제 키·인증서.
