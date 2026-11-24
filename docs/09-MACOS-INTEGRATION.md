# 09 — macOS 연동 (MACOS INTEGRATION)

> 상태: 구현 명세. 이름·명령·경로는 `02-ARCHITECTURE.md` §15, `06-DATA-MODEL.md` 를 그대로 쓴다.
> 범위: Swift 패키지·타깃 구성, 앱↔core 프로세스 수명관리, core 탐색·배포, 미리보기·썸네일·OCR·동영상 API, 썸네일 캐시 규칙, TCC/전체 디스크 접근(FDA)과 진단, 스케줄러(SMAppService)·알림·메뉴바, 파일시스템 연동(FSEvents·Spotlight·스크린샷 위치·앱/로그인 항목 소스·iCloud·휴지통), 샌드박스·서명, 실기기 검증.
> 화면·문구는 `03-UI-UX-SPEC.md`. 명령 `data` 스키마와 `serve --stdio` 세부는 `10-CLI-SKILL-MCP.md`. 휴지통·이동 실행 절차는 `08-SAFE-EXECUTION.md`.
>
> API 이름은 이 머신의 SDK(Xcode 27.2, `MacOSX27.2.sdk`) 헤더·`.swiftinterface` 에서 확인했다(2026-11-24). SDK 로 확인할 수 없는 **동작**(TCC 판정, launchd 귀속 등)은 “확인 필요” 로 표시했고 §12 실기기 검증 항목으로 넘긴다.

## 1. 기준 환경

| 항목 | 값 | 비고 |
|---|---|---|
| 최소 macOS | **26.0** (deployment target) | 결정: 02 §3 의 “SwiftUI (macOS 26)”. 소유자 기기 2대 모두 26.x. 이전 OS 호환 코드를 두지 않는다 |
| 개발 OS / 도구 | macOS 26.6.2 arm64, Xcode 27.2, Swift 6.4.2, SDK 27.2 | |
| CPU 아키텍처 | arm64 전용 | 결정: 소유자 기기가 모두 Apple silicon. Universal 이 필요해지면 `ARCHS` 설정 변경만으로 가능 |
| Swift 언어 모드 | Swift 6 (strict concurrency `complete`) | 02 §3, AGENTS §6 |
| 서드파티 Swift 의존성 | 없음 | 02 §3 |

사용 시스템 프레임워크: SwiftUI, AppKit, QuickLookUI(`QLPreviewPanel`, `QLPreviewView`), QuickLookThumbnailing, `_QuickLook_SwiftUI`(사용 안 함 — §5.1), ImageIO, PDFKit, AVFoundation/AVKit, UniformTypeIdentifiers, UserNotifications, ServiceManagement, Vision(`dayclose-native` 만), CoreServices(FSEvents — v1 미사용, §10.1), CryptoKit/LocalAuthentication(§11.3 제안 채택 시).

## 2. 저장소 내 Swift 구성

### 2.1 디렉터리

```
app/
├── DayClose.xcodeproj
├── Config/
│   ├── Base.xcconfig                 # MACOSX_DEPLOYMENT_TARGET=26.0, ARCHS=arm64, SWIFT_VERSION=6, ENABLE_HARDENED_RUNTIME=YES
│   ├── Signing.xcconfig              # #include? "Signing.local.xcconfig"
│   └── Signing.local.xcconfig        # (.gitignore) DEVELOPMENT_TEAM, CODE_SIGN_IDENTITY — 개인 값은 공개 저장소에 커밋하지 않음
├── DayClose/                         # 앱 타깃 소스
│   ├── App/            DayCloseApp.swift, AppModel.swift, AppDelegate.swift, Commands.swift
│   ├── Features/       Review/, GroupDetail/, Plan/, Vault/, Health/, Inventory/, History/, Settings/, Onboarding/
│   ├── Preview/        QuickLookCoordinator.swift, ThumbnailProvider.swift, VolumeProbe.swift, DatalessCheck.swift
│   ├── System/         PermissionMonitor.swift, SchedulerRegistration.swift, NotificationController.swift
│   ├── MenuBar/        MenuBarContentView.swift
│   ├── Resources/      Localizable.xcstrings (ko), Assets.xcassets
│   └── DayClose.entitlements         # 빈 dict (§11.2)
├── DayCloseScheduler/                # 명령행 도구 타깃 (M7)
│   ├── main.swift
│   └── com.dayclose.scheduler.plist  # LaunchAgent (§8.2)
├── DayCloseUITests/                  # XCUITest (11 문서)
└── DayCloseKit/                      # SwiftPM 라이브러리 (Xcode 없이 swift test)
    ├── Package.swift                 # swift-tools-version 6.x, platforms: [.macOS("26.0")]
    ├── Sources/DayCloseKit/
    │   ├── Envelope.swift            # 02 §5.4 봉투 Codable
    │   ├── Models/                   # Item, Group, ReviewSummary, Plan, VaultAsset, Finding … (10 문서 스키마)
    │   ├── Enums.swift               # 06 §3 enum → Swift enum (rawValue = 06 문자열, 알 수 없는 값은 .unknown(String))
    │   ├── CoreLocator.swift         # §3
    │   ├── CoreClient.swift          # §4 (actor)
    │   ├── CoreEnvironment.swift     # 자식 프로세스 환경 구성 §3.3
    │   └── SchedulerState.swift      # 스케줄러↔앱 공유 상태 키 §8.5 (앱·스케줄러 둘 다 import)
    └── Tests/DayCloseKitTests/
        ├── FixtureDecodingTests.swift   # ../../../contracts/fixtures/*.json 전부 디코딩 (#filePath 기준 상대경로)
        ├── CoreClientTests.swift        # 가짜 core(Tests/Fixtures/fake-core.sh)로 ID 매칭·타임아웃·재기동
        └── CoreLocatorTests.swift
native/                               # M6
├── Package.swift                     # executable "dayclose-native", platforms: [.macOS("26.0")]
└── Sources/dayclose-native/
    ├── main.swift                    # 서브명령 분기
    └── OCR.swift                     # §5.6
```

결정: enum 디코딩은 관대하게(`.unknown(String)`) 한다. 이유: core 가 06 enum 에 값을 추가(하위 호환, 02 §5.4)해도 앱이 깨지지 않게. 알 수 없는 `decision_action` 은 버튼으로 노출하지 않는다.

### 2.2 타깃과 번들 배치

| 타깃 | 종류 | 산출물 위치 | 링크 |
|---|---|---|---|
| `DayClose` | macOS App | `DayClose.app` | DayCloseKit |
| `DayCloseScheduler` | Command Line Tool (M7) | `DayClose.app/Contents/MacOS/DayCloseScheduler` (Copy Files: Executables) | DayCloseKit |
| `dayclose-native` | SwiftPM executable (M6) | `DayClose.app/Contents/Helpers/dayclose-native` (빌드 단계 스크립트가 `swift build -c release --package-path native` 결과를 복사·서명) | — |
| LaunchAgent plist | 리소스 (M7) | `DayClose.app/Contents/Library/LaunchAgents/com.dayclose.scheduler.plist` (Copy Files: Wrapper, subpath `Contents/Library/LaunchAgents`) | — |
| `DayCloseUITests` | UI Test Bundle | — | — |

번들 ID: 앱 `com.dayclose.app`(02 §15.1). 스케줄러 실행파일은 별도 번들 ID 를 갖지 않는다(앱 번들 안의 실행파일). LaunchAgent 라벨 `com.dayclose.scheduler`.

```
DayClose.app/Contents/
├── Info.plist                (CFBundleIdentifier=com.dayclose.app, LSMinimumSystemVersion=26.0, CFBundleURLTypes: dayclose)
├── MacOS/DayClose
├── MacOS/DayCloseScheduler   (M7)
├── Helpers/dayclose-native   (M6)
├── Library/LaunchAgents/com.dayclose.scheduler.plist (M7)
├── Resources/…
└── _CodeSignature/
```

URL 스킴 `dayclose://`: `dayclose://review?date=YYYY-MM-DD`(결산 열기), `dayclose://notify-daily`(§8.4 대체 경로). 결정: 경로·파일 이름을 URL 인자로 받지 않는다(외부에서 임의 경로 미리보기를 유발하지 못하게).

### 2.3 앱 실행 인자 (개발·테스트용)

| 인자 | 효과 | 빌드 |
|---|---|---|
| `--home PATH` | core 자식에 `--home PATH` 전달(= `DAYCLOSE_HOME`). 앱 캐시·UserDefaults 도메인은 바꾸지 않음 | Debug·Release |
| `--sandbox PATH` | core 자식 환경에 `DAYCLOSE_SANDBOX=PATH`. 앱 미리보기도 PATH 밖 경로는 열지 않음 | **Debug 전용** |
| `--core PATH` | core 실행파일 지정(§3.2 1순위) | Debug·Release |
| `--no-scheduler` | 스케줄러 등록/해제 UI 비활성 | Debug 기본값 켬 |

결정: 앱은 `DAYCLOSE_TEST_APPROVE` 를 어떤 경우에도 설정하지 않는다(02 §10.3). UI 테스트의 승인은 앱 버튼(`app_button`)으로 하되 `--sandbox` 안에서만.

### 2.4 Swift 쪽 파일 변경 금지 검사

AGENTS §3-2, 12 M4 종료 기준. `scripts/check-swift-no-mutation.sh` (11 문서의 안전 스위트가 호출)가 `app/` 와 `native/` 의 `.swift` 에서 다음 심볼이 나오면 실패한다: `removeItem`, `moveItem`, `trashItem`, `replaceItem`, `copyItem`, `createDirectory`, `createFile`, `linkItem`, `.write(to:`, `FileHandle(forWritingTo`, `FileHandle(forUpdating`, `rename(`, `renameat`, `unlink(`, `rmdir(`, `chmod(`, `setxattr(`, `removexattr(`, `NSWorkspace.shared.recycle`, `performFileOperation`.
예외 0 개(M4). 앱이 쓰는 파일은 `UserDefaults`(시스템 관리)뿐이며 썸네일은 메모리 캐시만 쓴다(§6). 디스크 캐시를 도입하면 예외 1곳이 필요하다 → §13 G6.

## 3. core 탐색·배포

### 3.1 배포 방식 (결정 — M7 확정 대상, 권고안)

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A (권고)** | `uv tool install --editable ./core` → `~/.local/bin/dayclose` 를 앱이 자식으로 실행 | 소유자 1명·로컬 빌드(02 §4) 에 맞음. core 수정이 즉시 반영. 앱 번들 서명 대상이 Swift 실행파일뿐 | 앱 단독 설치 불가. `uv` 가 관리하는 Python 경로에 의존 |
| B | Python standalone 빌드 + venv 를 `Contents/Resources/core/` 에 동봉 | 자급자족 | 번들 +60~100MB, 모든 `.so`/`.dylib` 를 같은 인증서로 서명, core 수정마다 앱 재빌드 |

결정(권고): **A**. 이유: 공증·배포를 하지 않으므로(02 §4) B 의 이점이 작고, 재서명 범위가 커질수록 FDA 유지(§7.6) 위험이 커진다. B 로 바꾸는 조건: §12 V3(앱 자식 core 의 TCC 귀속) 검증이 A 에서 실패할 때.

### 3.2 `CoreLocator` 탐색 순서

| 순위 | 후보 | 비고 |
|---|---|---|
| 1 | 실행 인자 `--core PATH` | |
| 2 | 앱 설정 `core.command` (`UserDefaults`, 설정 > 고급) | 결정: 02 §4 의 “설정 `core.command`” 는 **앱 쪽 UserDefaults 키**로 둔다. 이유: core 를 찾기 전에는 `config.toml` 을 읽을 수 없음(닭과 달걀). §13 G1 |
| 3 | `DayClose.app/Contents/Resources/core/bin/dayclose` | 안 B 채택 시에만 존재 |
| 4 | `~/.local/bin/dayclose` | 안 A 기본 |
| 5 | `/opt/homebrew/bin/dayclose`, `/usr/local/bin/dayclose` | |

각 후보: 실행 가능 파일인지 `access(X_OK)` → `dayclose version --json` 1회 실행(타임아웃 5초) → 봉투 `ok` 이고 `meta.contract_version == DayCloseKit.contractVersion`(현재 1) 이면 채택. 다르면 다음 후보를 보지 않고 `coreIncompatible`(03 §3.2). 전부 실패 → `coreMissing`, 시도한 경로와 각 실패 사유를 화면에 표시(03 §4.15).
셸 PATH 는 보지 않는다(Finder 에서 실행된 앱의 PATH 는 `/usr/bin:/bin:/usr/sbin:/sbin` 뿐이고, 셸 설정을 실행해 PATH 를 얻는 것은 사용자 셸 스크립트 실행이 되므로).

### 3.3 자식 프로세스 환경 (`CoreEnvironment`)

결정: 앱 환경을 상속하지 않고 **허용 목록으로 새로 만든다**. 이유: 사용자 환경변수에 API 키 등이 있을 수 있고(02 §13 “환경변수 값 기록 금지”), core 가 예상 밖 변수(`PYTHONPATH` 등)에 영향받지 않게.

| 변수 | 값 |
|---|---|
| `HOME`, `USER`, `LOGNAME`, `TMPDIR` | 앱 프로세스 값 그대로 |
| `PATH` | `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` (git·brew·gitleaks 탐색용. core 의 `run_tool` 이 허용 목록 도구를 이 PATH 에서 찾음) |
| `LANG`, `LC_ALL` | `ko_KR.UTF-8` |
| `PYTHONUNBUFFERED` | `1` (stdio 줄 단위 즉시 전송) |
| `PYTHONDONTWRITEBYTECODE` | `1` |
| `DAYCLOSE_HOME` | `--home` 지정 시에만 |
| `DAYCLOSE_SANDBOX` | `--sandbox` 지정 시에만(Debug) |
| `DAYCLOSE_NATIVE` | `DayClose.app/Contents/Helpers/dayclose-native` 가 있으면 그 절대경로(M6) — §13 G2 |

### 3.4 `dayclose-native` 탐색 (core 쪽, M6)

core 는 `DAYCLOSE_NATIVE` → `/Applications/DayClose.app/Contents/Helpers/dayclose-native` → `~/.local/bin/dayclose-native` 순으로 찾는다. 없으면 OCR 단계 건너뜀 + `W_TOOL_MISSING`. 앱 번들 안의 사본을 쓰는 이유: core 가 앱의 자식일 때 TCC 책임 프로세스가 앱으로 유지되고(§7.1), 같은 인증서로 서명되어 있음. `DAYCLOSE_NATIVE` 는 02 §15.1 경로 목록에 없는 새 이름 → §13 G2.

## 4. 앱 ↔ core 프로세스 수명관리 (`DayCloseKit.CoreClient`)

### 4.1 구조

```swift
public actor CoreClient {
  public init(executable: URL, extraArgs: [String], environment: [String: String])
  public func start() async throws(CoreClientError)                 // spawn + handshake
  public func send<D: Decodable & Sendable>(_ command: String, args: some Encodable & Sendable,
                   as: D.Type, timeout: Duration?,
                   progress: (@Sendable (ProgressEvent) -> Void)?) async throws(CoreClientError) -> Envelope<D>
  public func stop(grace: Duration = .seconds(2)) async
  public var state: State { get }                                     // .stopped | .starting | .running(pid) | .restarting(attempt) | .failed(reason)
}

public enum CoreClientError: Error, Sendable {
  case notFound([LocatorAttempt]), incompatible(core: Int, app: Int), spawnFailed(String),
       timeout(command: String), terminated(exitCode: Int32?), decoding(command: String), protocolViolation(String)
}
```

- core 의 실패 봉투(`ok=false`)는 **오류로 던지지 않고** `Envelope` 로 돌려준다(분기는 `error.code` 로, 02 §5.4). `CoreClientError` 는 전송 계층 실패만. 결정: Swift 쪽 오류를 `E_*` 코드로 위장하지 않는다(02 §11 코드표는 core 전용).
- `E_PARTIAL` 은 `ok=false` 이면서 `data` 가 있으므로 `Envelope.data` 는 `ok` 와 무관하게 디코딩 시도.

### 4.2 기동과 핸드셰이크

1. `Process`: `executableURL` = 탐색된 core, `arguments` = `["serve", "--stdio", "--channel", "app"] + (home ? ["--home", P] : [])`, `environment` = §3.3, stdin/stdout/stderr 각각 `Pipe`. (`--channel` 이 `serve` 의 전역 플래그로 받아지는지는 10 문서. 요청 줄마다 `"channel": "app"` 도 넣는다.)
2. stdout 은 `FileHandle.bytes.lines` 를 별도 `Task` 에서 읽어 한 줄 = JSON 1개로 디코딩. 줄 길이 상한 16MB(초과 → `protocolViolation`, 재기동).
3. 첫 요청 `core.version` → `contract_version` 확인. 불일치 → `incompatible`, 프로세스 종료.
4. 성공 후 `state = .running(pid)`.

### 4.3 요청·응답

- 요청 줄: `{"id": "<단조 증가 정수 문자열>", "command": "...", "args": {...}, "channel": "app"}` + `\n` (02 §5.4). 쓰기는 actor 안에서 직렬.
- 응답 매칭: `id` 로 `CheckedContinuation` 을 찾는다. `id` 없는 줄, 모르는 `id` → 디버그 로그 후 무시.
- 진행 이벤트(`{"id": "...", "event": "progress", ...}`) → 해당 요청의 `progress` 콜백(MainActor 로 hop 은 호출 측 책임).
- 동시 요청: 여러 개를 보낼 수 있다(파이프라이닝). core 가 순차 처리하더라도 앱은 응답 순서를 가정하지 않는다. 같은 항목에 대한 결정 직렬화는 03 §3.4 의 `ReviewStore` 책임.

명령별 타임아웃(결정):

| 명령 | 타임아웃 | 시간 초과 시 |
|---|---|---|
| 읽기 명령(`*.list`, `*.show`, `vault.health`, `core.version`) | 15s | `timeout` → 재시도 1회 → 실패 시 프로세스 재기동 |
| `review.summary` | 30s (첫 열기의 이월 처리) | 〃 |
| `decision.set/undo`, `config.set`, `root.*`, `rule.*`, `suppression.*`, `vault.annotate`, `plan.create/approve/cancel` | 15s (+ core `--wait-lock` 10s 포함) | **재전송하지 않는다.** 화면은 대상 재조회로 실제 상태를 맞춤(03 §3.4) |
| `core.doctor` | 60s (볼륨 프로브 포함) | 결과 없음으로 표시 |
| `scan.run` | 없음(진행 이벤트가 60s 동안 없으면 경고 배너만) | — |
| `plan.apply`, `plan.undo`, `plan.recover` | 없음 | — |

### 4.4 표준 오류(stderr)

core 의 stderr 는 줄 단위로 `os.Logger(subsystem: "com.dayclose.app", category: "core-stderr")` 에 `.debug` 수준, `privacy: .private` 로만 남긴다. 화면에 표시하지 않는다. 결정: 파일로 따로 저장하지 않는다(core 자체 로그 `core.log` 가 마스킹된 공식 기록, 02 §13).

### 4.5 비정상 종료와 재기동

| 사건 | 처리 |
|---|---|
| core 프로세스 종료(`terminationHandler`) | 대기 중 요청 전부 `terminated` 로 실패. 즉시 재기동 1회 → 실패 시 1s, 5s 후 재시도. **2분 안에 3회 비정상 종료** → `state = .failed`, 03 `coreCrashed` 화면 |
| 재기동 후 | `ReviewStore` 가 `review.summary` 재조회, 진행 중이던 `plan.apply` 가 있었다면 `plan.list --state executing` 확인 → 03 §4.12 복구 배너 |
| 프로토콜 위반(디코딩 불가 줄 연속 3회) | 프로세스 종료 후 재기동 |

### 4.6 종료

- 앱 종료(`applicationShouldTerminate`): 실행 중 요청이 `plan.apply/undo/recover` 면 `.terminateLater` + 대화상자 “정리 작업이 끝날 때까지 기다립니다(6/9)” [기다리기] [강제 종료](강제 종료 시 다음 실행에서 `plan.recover`, 08). 그 외에는 stdin 닫기(EOF) → 2s 대기 → `SIGTERM` → 2s → `SIGKILL`.
- 결정: 메인 창이 모두 닫히고 메뉴바만 남은 상태에서 **10분간 요청이 없으면 core 를 종료**하고, 다음 요청 때 다시 띄운다. 이유: 메뉴바 상주 중 Python 프로세스를 계속 유지할 필요가 없음. 02 §7 의 “창이 열린 동안” 보다 넓지 않으므로 충돌 없음(창이 열린 동안은 항상 유지).
- 앱이 충돌하면 stdin EOF 로 core 가 종료된다(02 §4). EOF 시 core 가 진행 중 요청을 끝내고 나가는지(특히 `plan.apply`)는 10 문서가 정한다 — 앱은 다음 기동 때 `plan.recover` 배너로 대응.

## 5. 미리보기·썸네일·OCR·동영상

모든 사용자 파일 접근은 **읽기 전용**이며 항목의 `preview_policy` 와 dataless·볼륨 검사를 통과한 뒤에만 한다(03 §6 표).

### 5.0 공통 사전 검사 (콘텐츠에 닿기 전 매번)

```
canTouchContent(item):
  1. preview_policy == metadata_only            → 거부 (아이콘도 파일에서 읽지 않음)
  2. path 가 --sandbox 밖(Debug)                  → 거부
  3. path 가 /Volumes/* 아래 → VolumeProbe(path, 2s) 실패 → 거부(“응답 없음”), 그 볼륨 접두사를 60s 동안 차단
  4. DatalessCheck(path) == dataless             → 거부(사용자가 03 §4.3.1 대화상자에서 내려받기를 고른 경우만 Quick Look 허용)
  5. 통과
```

- `VolumeProbe`: Swift 동시성 협력 스레드 풀을 막지 않도록 **전용 `Thread`** 에서 `stat()` 1회, `DispatchSemaphore` 로 2초 대기. 시간 초과면 스레드를 버리고(02 §10.5 와 같은 전략) `false`. 결과는 볼륨 루트(`/Volumes/<이름>`)별 60초 캐시.
- `DatalessCheck`: `lstat()` 의 `st_flags & SF_DATALESS (0x40000000)`(SDK `sys/stat.h` 확인), 또는 파일 이름이 `.<이름>.icloud` 자리표시자. 보조로 `URLResourceValues.ubiquitousItemDownloadingStatus == .notDownloaded`. 결정: core 의 항목 JSON 에 dataless 표시가 생기면(03 §13 R4) 그것을 1차로 쓰고 앱 검사는 방어선으로 유지.
- 파일 메타데이터·썸네일 작업은 `@MainActor` 밖에서. 한 화면에서 동시에 진행하는 썸네일 작업은 최대 8개(`TaskGroup` + 세마포어), 셀이 화면에서 사라지면 취소.

### 5.1 Quick Look 패널 — `QLPreviewPanel` (QuickLookUI)

결정: SwiftUI `quickLookPreview(_:in:)`(`_QuickLook_SwiftUI`, SDK 확인)를 쓰지 않고 AppKit `QLPreviewPanel` 을 직접 쓴다. 이유: 패널이 열린 동안 K/D/A/M/S 를 앱이 받아야 하고(03 §4.3.1), 정책상 제외할 항목을 데이터 소스에서 걸러야 하기 때문. 패널의 키 이벤트는 `QLPreviewPanelDelegate.previewPanel(_:handle:)`(헤더 `previewPanel:handleEvent:` 확인)로 받을 수 있다.

`QuickLookCoordinator`(NSResponder, 메인 창 응답 체인에 삽입):
- `acceptsPreviewPanelControl(_:)` → `true`; `beginPreviewPanelControl(_:)` 에서 `dataSource`/`delegate` 를 자신으로; `endPreviewPanelControl(_:)` 에서 해제.
- 데이터 소스: `numberOfPreviewItems(in:)`, `previewPanel(_:previewItemAt:)` → `canTouchContent` 를 통과한 항목의 `URL`(`QLPreviewItem` 으로 `NSURL` 사용). `ephemeral` 은 Space 로 연 경우에만 포함.
- 동기화: `currentPreviewItemIndex` 변경을 관찰해 목록 포커스를 옮기고, 목록 포커스 변경 시 `currentPreviewItemIndex` 를 설정.
- `previewPanel(_:handle:)`: `keyDown` 의 문자가 k/d/a/m/s(⇧ 포함)면 `ReviewStore` 의 결정 입력으로 보내고 `true`. 그 외(←/→/Space/Esc)는 `false`(패널 기본 동작).
- 패널 띄우기: `QLPreviewPanel.shared()` → `makeKeyAndOrderFront(nil)`, 토글은 `isVisible` 확인 후 `orderOut`.

비교 모드·인스펙터 안 미리보기: `QLPreviewView(frame:style: .compact)` 를 `NSViewRepresentable` 로 감싸 `previewItem` 지정(`metadata_only`·`ephemeral`·dataless 는 만들지 않음). 뷰가 사라질 때 `close()`.

확인 필요(§12 V9): `QLPreviewPanel`/`QLPreviewView` 가 생성한 미리보기를 시스템이 디스크에 캐시하는지. `ephemeral` 은 패널만 허용하고 썸네일 생성기는 쓰지 않는 것으로 위험을 줄인다(§6).

### 5.2 썸네일 생성 — `ThumbnailProvider`

| 대상 | API | 이유 |
|---|---|---|
| 이미지·스크린샷(`UTType.image` 준수) | ImageIO: `CGImageSourceCreateWithURL(url, [kCGImageSourceShouldCache: false])` → `CGImageSourceCreateThumbnailAtIndex(src, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: px, kCGImageSourceCreateThumbnailWithTransform: true, kCGImageSourceShouldCacheImmediately: true])` (키 이름 SDK 확인) | 프로세스 안에서 디코딩 → 시스템 썸네일 캐시를 거치지 않음. 스크린샷은 `personal` 이고 OCR(M6) 후 `patient` 로 오를 수 있어 시스템 캐시에 남지 않는 쪽이 안전 |
| PDF | PDFKit `PDFDocument(url:)?.page(at: 0)?.thumbnail(of:for: .mediaBox)` | 프로세스 안 |
| 동영상 | AVFoundation `AVAssetImageGenerator(asset:)` + `generateCGImageAsynchronously(for:completionHandler:)`(헤더 `generateCGImageAsynchronouslyForTime:` 확인; Swift async 변형 이름은 확인 필요), `appliesPreferredTrackTransform = true`, 시각 1s | 프로세스 안 |
| 그 외(`full` 만: Office·Keynote·텍스트 등) | QuickLookThumbnailing: `QLThumbnailGenerationRequest(fileAt:size:scale:representationTypes: .thumbnail)` → `QLThumbnailGenerator.shared.generateBestRepresentation(for:completion:)`(SDK 확인, async 변형 사용), 셀 해제 시 `cancel(_:)` | 형식별 생성기를 직접 만들 수 없음. 시스템 썸네일 캐시를 쓸 수 있으므로 `ephemeral`·`metadata_only` 에는 절대 쓰지 않는다 |
| `ephemeral`·dataless·차단 | 썸네일 없음. 아이콘은 `NSWorkspace.shared.icon(for: UTType)`(파일이 아니라 형식으로 — `iconForContentType:` SDK 확인) | 파일 내용·Finder 사용자 지정 아이콘에 닿지 않음 |
| `metadata_only` | SF Symbol 만 | 파일 접근 0 (FR-VR-006) |
| 앱(`.app`) | `NSWorkspace.shared.icon(forFile:)` | 앱 번들 아이콘 |

픽셀 크기: 셀 크기 × `backingScaleFactor`, 160/240/320/480 단계로 반올림(캐시 적중률).

### 5.3 동영상 재생 — AVKit

인스펙터의 [재생]: SwiftUI `VideoPlayer(player:)`(`_AVKit_SwiftUI`, SDK 확인) + `AVPlayer(url:)`, `isMuted = true` 로 시작. 재생 시간은 `AVURLAsset(url:).load(.duration)`. `full` 만. `ephemeral` 은 Quick Look 패널로만 재생.

### 5.4 문서·텍스트

- Markdown: 256KB 이하일 때 `String(contentsOf:)` → `AttributedString(markdown:options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))`. 이미지·링크 원격 로딩 없음(네트워크 0, NFR-PRIV-002).
- 소스 코드: 앞 200줄을 고정폭 `Text`. 문법 강조 없음(서드파티 금지). “변경 내역(git diff)” 은 v1 범위 밖.
- ZIP 내부 목록: 앱은 압축을 열지 않는다. Quick Look 패널이 보여주는 범위만. 목록 표시는 core 가 항목 데이터로 줄 때만(§13 G7).
- 폴더: `FileManager.contentsOfDirectory(at:includingPropertiesForKeys:[.fileSizeKey], options: [.skipsHiddenFiles])` 1단계, 최대 200개, `full` 만(읽기 전용).

### 5.5 Finder 연동

[Finder 에서 보기] = `NSWorkspace.shared.activateFileViewerSelecting([url])`(SDK 확인). 읽기 동작이므로 `metadata_only` 에도 허용(03 §4.9 결정). 파일 열기(`NSWorkspace.open`)는 제공하지 않는다 — 결정: 다른 앱이 파일을 수정·자동 저장할 수 있어 “앱은 파일을 바꾸지 않는다” 를 보장하기 어렵기 때문.

### 5.6 Vision OCR — `dayclose-native ocr` (M6)

앱이 아니라 core 가 `run_tool(["dayclose-native", "ocr", "--json"], timeout=…)` 으로 호출한다(02 §3, §6). 언제·무엇을 OCR 하는지는 04·07 문서.

- 입력: stdin 으로 `{"paths": ["/…/a.png", …], "languages": ["ko-KR", "en-US"], "max_chars": 16384}`. 결정: 경로를 argv 로 받지 않는다(프로세스 목록 노출 최소화, argv 길이 제한 회피).
- 처리: Swift Vision `RecognizeTextRequest`(macOS 15+, SDK `.swiftinterface` 확인) — `recognitionLevel = .accurate`, `recognitionLanguages = [Locale.Language(identifier: "ko-KR"), Locale.Language(identifier: "en-US")]`, `usesLanguageCorrection = true`. 파일마다 `lstat` 으로 dataless 재검사(dataless → 건너뜀). 파일당 10초, 최대 이미지 변 4096px 로 다운샘플(ImageIO).
- 출력: stdout 에 `{"results": [{"index": 0, "ok": true, "text": "…", "lang": "ko"}, {"index": 1, "ok": false, "error": "dataless"}]}` — 경로를 되풀이하지 않고 입력 `index` 로 대응. 텍스트는 `max_chars` 에서 자름.
- 금지: 디스크 쓰기(임시 파일 포함), 로그에 텍스트 출력, 네트워크. 종료 코드 0(부분 실패는 `ok:false`), 2(입력 오류).
- 한국어 인식 지원 여부: `RecognizeTextRequest.supportedRecognitionLanguages` 로 시작 시 확인, 없으면 `{"error": "language_unsupported"}`(확인 필요 §12 V12).

## 6. 썸네일 캐시 규칙 (비밀이 캐시에 남지 않게)

결정(M4): **디스크 썸네일 캐시를 만들지 않는다.** 메모리 캐시만 쓴다.
이유: (1) 02 §8 의 `~/Library/Caches/DayClose/` 는 상한(200MB)을 정한 것이지 필수 아님, (2) 이미지 썸네일은 ImageIO 로 빠르게 다시 만들 수 있음, (3) 디스크 캐시는 정책 변경(예: OCR 후 `patient` 로 상향) 시 삭제가 필요한데 Swift 코드의 파일 삭제는 금지 검사 대상(§2.4), (4) FR-VR-006 AC 를 구조적으로 만족.

메모리 캐시(`ThumbnailMemoryCache`):

| 규칙 | 값 |
|---|---|
| 구현 | `NSCache<ThumbKey, CGImageBox>`, `totalCostLimit = 256MB`(cost = 픽셀 바이트) |
| 키 | `item_id` + `mtime` + `size_bytes` + 픽셀 크기. 파일이 바뀌면 키가 달라져 자연 무효화 |
| 넣을 수 있는 항목 | `preview_policy == full` 이고 dataless 아님 |
| 즉시 제거 | 새로 받은 항목 JSON 의 `preview_policy != full` 이면 그 `item_id` 의 모든 키 제거. 리뷰 날짜 변경, 메모리 경고(`NSApplication` 메모리 압박 알림) 시 전체 비움 |
| 영속 | 없음. 앱 종료 시 사라짐 |

시스템 쪽 캐시(앱이 통제 못 함):
- QuickLookThumbnailing 은 시스템 썸네일 캐시(`$(getconf DARWIN_USER_CACHE_DIR)com.apple.QuickLook.thumbnailcache/`, 위치 확인 필요)를 쓸 수 있다 → `full` 의 비이미지 형식에만 사용(§5.2).
- `ephemeral`·`metadata_only` 는 어떤 썸네일 API 도 호출하지 않는다.

디스크 캐시를 나중에 도입한다면(측정상 필요할 때만) 지켜야 할 조건: `preview_policy == full` **그리고** `sensitivity == normal` 만, 파일 이름 = SHA-256(`item_id|dev|inode|mtime_ns|size|px`) 16진(원래 이름 금지), 위치 `~/Library/Caches/DayClose/thumbs/`, 200MB LRU, 항목 정책이 바뀌면 즉시 삭제, 삭제 코드는 캐시 디렉터리 접두사 단언이 있는 파일 1곳에만 두고 §2.4 검사의 예외로 등록(AGENTS·12 변경 필요 → §13 G6).

검증(FR-VR-006, 11 문서 UI 테스트): 샌드박스의 보안 자산·환자 패턴 픽스처를 갤러리·리스트·인스펙터에서 열람(Space 포함) 후 (1) `~/Library/Caches/DayClose`(또는 `--home` 지정 시 그 아래 `cache/`)에 파일 0개, (2) 앱 프로세스가 해당 파일을 `open()` 한 기록이 `metadata_only` 에 대해 0회(`fs_usage -w -f filesys DayClose` 로 실기기 확인, §12 V9).

## 7. TCC 와 전체 디스크 접근(FDA)

### 7.1 사실과 전제

| # | 사실 | 출처/상태 |
|---|---|---|
| F1 | launchd 가 띄운 프로세스가 FDA 없이 `/Volumes/*` 에 접근하면 **오류 없이 멈춘다** | 이 머신에서 확인된 사실(02 §10.5, 사용자 운영 노트: `brew services` 프로세스가 같은 증상) |
| F2 | `~/Desktop`, `~/Documents`, `~/Downloads`, iCloud Drive 는 TCC 보호 폴더. 권한 없으면 `EPERM` | 02 §10.5 |
| F3 | TCC 는 “책임 프로세스(responsible process)” 로 판정한다. 앱이 `posix_spawn`/`Process` 로 띄운 자식(core Python, git 등)은 앱이 책임 프로세스 | 일반적으로 알려진 동작 — **확인 필요 §12 V3** |
| F4 | `SMAppService.agent(plistName:)` 로 등록한 번들 내 LaunchAgent 가 띄운 `Contents/MacOS/DayCloseScheduler` 는 DayClose.app 의 TCC 승인을 따른다 | **확인 필요 §12 V4** |
| F5 | TCC 는 코드 서명의 designated requirement(DR)로 앱을 식별. ad-hoc 서명은 재빌드마다 바뀜 | 02 §4 결정 |
| F6 | 터미널에서 실행한 `dayclose` 는 **터미널 앱의** TCC 권한을 쓴다. 터미널에 FDA 가 있으면 셸에서는 잘 되고 앱·launchd 에서만 실패하는 차이가 생긴다 | 진단 절차의 핵심(§7.5) |
| F7 | Python 인터프리터에 FDA 를 주는 방식은 금지(모든 Python 스크립트로 권한이 샘) | 02 §10.5 |

결정: DayClose 는 FDA 를 **권장하되 필수로 하지 않는다.** FDA 없이도 수동 스캔은 macOS 의 폴더별 허용 대화상자(데스크탑·문서·다운로드)로 동작하고, 외장 볼륨 루트와 예약 실행은 경고로 끝난다(FR-MI-004, NFR-REL-001).

### 7.2 FDA 프로브 설계

세 실행 맥락에서 각각 판정한다(03 §4.14.2).

| 맥락 | 누가 | 방법 |
|---|---|---|
| 앱 | `PermissionMonitor`(Swift) | 아래 프로브를 전용 스레드에서 실행, 2초 제한 |
| core(앱의 자식) | `core.doctor` (channel `app`) | core 의 같은 프로브(10 문서가 `doctor` 출력 필드 확정 → §13 G3) |
| 예약 실행 | `DayCloseScheduler` 가 `dayclose doctor --channel schedule --json` 실행 후 결과 요약 저장(§8.5) | 하루 1회 + 스캔 경고에 `W_TCC_DENIED`/`W_ROOT_UNAVAILABLE` 이 있을 때 |

프로브(읽기 전용, 내용을 읽지 않음):

```
probe_fda():
  target = ~/Library/Application Support/com.apple.TCC/TCC.db
  fd = open(target, O_RDONLY | O_NONBLOCK)    # 내용은 읽지 않고 즉시 close
  성공            → granted
  EPERM / EACCES → denied
  ENOENT         → 보조 대상으로: ~/Library/Safari 에 opendir() → 성공 granted / EPERM denied / 그 외 unknown
  시간 초과       → unknown
```

확인 필요(§12 V1): macOS 26 에서 위 두 대상이 FDA 유무를 정확히 가르는지. 맞지 않으면 대상만 바꾼다(프로브 구조는 유지).

폴더 접근 상태는 FDA 와 따로 본다: `core.doctor` 의 루트별 `ok | tcc_denied | timeout | missing`(02 §10.5)를 그대로 표시.

`PermissionMonitor` 갱신 시점: 앱 기동, 앱 활성화(`NSApplication.didBecomeActiveNotification`), 온보딩 FDA 단계에서는 2초마다(창이 활성일 때만), 설정 > 권한 [진단 다시 실행].

### 7.3 사용자 안내 흐름

| 상황 | 안내(화면은 03) |
|---|---|
| 온보딩 | 03 §4.14.1 단계. [나중에 하기] 허용 |
| 스캔 결과에 `W_TCC_DENIED` | 배너 + [권한 설정 열기] |
| `W_ROOT_UNAVAILABLE`/`E_VOLUME_TIMEOUT` 이고 루트가 `/Volumes/*` | “외장 볼륨이 응답하지 않습니다. 예약 실행에서 외장 디스크를 쓰려면 전체 디스크 접근 권한이 필요합니다.” |
| 예약 실행에서만 denied (앱·core 는 granted) | 03 §4.14.2 문구 + §7.5 진단 요약 |
| 이전 granted → 지금 denied | 재서명 안내(02 §10.5 마지막 줄): “앱을 다시 빌드했다면 목록에서 DayClose 를 껐다 켜 주세요” |
| 사용자가 FDA 를 켰는데 unknown | “DayClose 를 다시 시작하세요”(일부 승인은 재시작 후 반영 — 확인 필요) |

### 7.4 시스템 설정 열기

| 대상 | 방법 | 상태 |
|---|---|---|
| 전체 디스크 접근 권한 | `NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!)` | 확인 필요(§12 V2) — 실패하면 `x-apple.systempreferences:com.apple.preference.security` 후 문구 안내 |
| 로그인 항목(백그라운드 허용) | `SMAppService.openSystemSettingsLoginItems()` | SDK 확인 |
| 알림 | `x-apple.systempreferences:com.apple.Notifications-Settings.extension` | 확인 필요 |

### 7.5 진단 절차: 셸 실행 vs launchd 실행 비교

“같은 명령이 어디서는 되고 어디서는 멈춘다” 를 가장 빨리 가르는 방법(사용자 운영 노트, 02 §10.5). `scripts/diagnose-tcc.sh` 가 아래를 순서대로 수행하고 표로 출력한다(사용자 파일을 바꾸지 않음, `doctor` 만 실행).

| 단계 | 실행 맥락 | 명령 | 해석 |
|---|---|---|---|
| D1 | 터미널(셸) | `dayclose doctor --json` | 터미널 앱의 권한 기준(F6). 여기서도 실패하면 권한 문제가 아니라 경로·볼륨 문제 |
| D2 | 앱의 자식 | 앱 설정 > 권한 [진단 다시 실행] (= `core.doctor`, channel app) | F3 검증 |
| D3 | launchd(스케줄러 헬퍼) | `launchctl kickstart -k gui/$(id -u)/com.dayclose.scheduler` 후, 헬퍼가 `--diagnose` 모드일 때(§8.3) 실행한 doctor 결과를 `defaults read com.dayclose.app scheduler.lastDoctor` 로 확인 | F4 검증 |
| D4 | launchd + 외장 | D3 를 외장 루트가 등록된 상태에서. `volume_probe_timeout_s`(5)+2초 안에 끝나야 함 | F1 이 프로브로 막히는지(NFR-REL-001) |

판정표:

| D1 | D2 | D3 | 원인 | 조치 |
|---|---|---|---|---|
| ok | ok | ok | 정상 | — |
| ok | denied | denied | DayClose.app 에 FDA 없음(터미널만 있음) | 앱에 FDA 부여 |
| ok | ok | denied/timeout | 헬퍼가 앱 승인을 못 물려받음(F4 실패) 또는 앱 위치·서명이 등록 시점과 다름 | 앱을 `/Applications` 에서 실행·재등록, 서명 확인(§7.6). 계속 실패 시 §8.4 대체 구조 검토 |
| denied | denied | denied | 터미널·앱 모두 권한 없음 | FDA 부여 |
| timeout(외장) | timeout | timeout | 볼륨 자체 문제(분리·슬립·네트워크) | 볼륨 확인 |

### 7.6 서명 고정과 재빌드 후 FDA 유지 (공증 없음)

02 §4 결정(Developer ID·공증 안 함)에 따른 운영 규칙:

- 앱·스케줄러·`dayclose-native` 를 **같은 인증서**로 서명: Xcode 의 무료 “Apple Development”(개인 팀) 인증서, 없으면 키체인 접근에서 만든 자체 서명 코드 서명 인증서. `CODE_SIGN_IDENTITY`·`DEVELOPMENT_TEAM` 은 `Signing.local.xcconfig`(커밋 금지).
- ad-hoc(`-`) 서명 금지. Release 빌드 스크립트가 `codesign -dr - DayClose.app` 결과에 `cdhash` 만 있는 DR 이면 실패.
- 일상 사용 위치는 **`/Applications/DayClose.app` 하나**. 결정: Xcode DerivedData 의 Debug 사본은 `--home` 샌드박스 + `--no-scheduler` 로만 실행. 이유: 같은 번들 ID 의 사본이 여러 곳에 있으면 LaunchServices·TCC·SMAppService 가 어느 사본을 가리키는지 흐려짐.
- 설치 스크립트 `scripts/install-app.sh`: `xcodebuild -configuration Release` → 새 번들 서명 검증(`codesign --verify --deep --strict`) → DR 이 직전 설치본과 같은지 비교(`codesign -dr -`) → 다르면 경고 “FDA 를 다시 켜야 합니다” → 실행 중인 앱 종료 → `ditto` 로 임시 이름에 복사 → 검증 → 기존 번들과 교체. (이 스크립트가 바꾸는 것은 `/Applications/DayClose.app` 하나뿐이며 사용자 실행 시에만.)
- 검증 항목 §12 V5: 같은 인증서로 재빌드·재설치 후 FDA 가 유지되는지, 인증서 갱신(1년) 후 유지되는지.

#### 7.6.1 공증하지 않는 로컬 빌드가 의미하는 것

| 대상 | Developer ID·공증이 없을 때 | DayClose 의 대응 | 검증 |
|---|---|---|---|
| FDA·폴더 접근(TCC) | TCC 는 DR 로 앱을 기억한다. ad-hoc 서명의 DR 은 `cdhash` 그 자체라 **재빌드할 때마다 다른 앱**으로 보여 승인이 풀린다(목록에는 DayClose 가 켜진 채 남아 있어도 실제로는 거부될 수 있음 — 확인 필요). “Apple Development” 인증서의 DR 은 번들 ID + 인증서 주체·Apple 중간 인증서 조건이라 같은 인증서로 서명하면 재빌드 후에도 같다(인증서 갱신 시 주체가 같으면 유지될 것으로 봄 — 확인 필요). 자체 서명 인증서는 DR 이 인증서 해시라 그 인증서를 계속 쓰는 한 유지 | 서명 고정(위 규칙), 설치 스크립트의 DR 비교, `core.doctor` 가 `tcc_denied`/`timeout` 을 보고하면 안내에 “앱을 다시 빌드했다면 서명을 확인하세요”(02 §10.5) + 앱 설정 > 권한에 현재 DR 요약(인증서 이름·팀)과 직전 설치 DR 일치 여부 표시 | V5 |
| `SMAppService` LaunchAgent | 공증은 필요 없다(Gatekeeper 격리가 없는 로컬 빌드). 다만 백그라운드 항목 관리(BTM)는 등록한 앱을 서명 정보로 기억하므로, 서명이 바뀐 번들로 교체하면 등록이 `.requiresApproval`/`.notRegistered` 로 돌아가거나 “새 백그라운드 항목” 알림이 다시 뜰 수 있다 — 확인 필요 | 앱 기동마다 `status` 확인(§8.1). 설치 스크립트가 DR 변경을 감지하면 앱 첫 기동 시 “예약 실행을 다시 켜 주세요” 배너 + [다시 켜기](`unregister` → `register`) | V15 |
| 헬퍼·`dayclose-native` | 앱과 다른 인증서·ad-hoc 이면 TCC 가 다른 주체로 볼 수 있다 | 세 실행파일 모두 같은 인증서. 빌드 단계에서 `codesign -dvv` 의 `TeamIdentifier`/`Authority` 가 앱과 같은지 검사, 다르면 빌드 실패 | V5 |
| Gatekeeper | 로컬 빌드에는 격리 속성이 없어 그대로 실행 | 빌드 산출물을 기기 간에 복사하지 않고 각 Mac 에서 빌드(§11.5) | — |
| 다른 Mac | 인증서(개인키 포함)가 그 Mac 키체인에 없으면 같은 DR 로 서명할 수 없다 | Mac 마다 자기 인증서로 빌드·설치하고 FDA·예약 실행을 **그 Mac 에서 각각** 승인(02 §8.1). 기기 간 TCC 승인은 옮겨지지 않는다 | V-표의 기기 열 |

## 8. 예약 실행·알림 (M7)

### 8.1 등록 — `SMAppService`

| 동작 | API (ServiceManagement, SDK 확인) |
|---|---|
| 서비스 객체 | `SMAppService.agent(plistName: "com.dayclose.scheduler.plist")` — plist 는 `Contents/Library/LaunchAgents/` 에 있어야 함(헤더 주석) |
| 켜기 | `try service.register()` |
| 끄기 | `try await service.unregister()` |
| 상태 | `service.status`: `.notRegistered` / `.enabled` / `.requiresApproval` / `.notFound` |
| 사용자 승인 유도 | `SMAppService.openSystemSettingsLoginItems()` |

상태 → 설정 화면(03 §4.13 알림·예약 탭): `.enabled` “켜짐”, `.requiresApproval` “시스템 설정에서 허용이 필요합니다” [로그인 항목 설정 열기], `.notRegistered` “꺼짐”, `.notFound` “앱 번들에 예약 실행 구성 요소가 없습니다(빌드 확인)”. 등록 시 macOS 가 “백그라운드 항목이 추가됨” 알림을 띄울 수 있음을 온보딩 문구에 미리 적는다.
앱 기동 시마다 `status` 를 읽어 설정과 맞지 않으면(사용자가 시스템 설정에서 끔) 앱 설정 표시를 시스템 상태에 맞춘다(재등록하지 않음 — 사용자 선택 존중).

### 8.2 LaunchAgent plist (`com.dayclose.scheduler.plist`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key>              <string>com.dayclose.scheduler</string>
  <key>BundleProgram</key>      <string>Contents/MacOS/DayCloseScheduler</string>
  <key>ProgramArguments</key>   <array><string>DayCloseScheduler</string><string>--tick</string></array>
  <key>StartInterval</key>      <integer>900</integer>
  <key>RunAtLoad</key>          <true/>
  <key>ProcessType</key>        <string>Background</string>
  <key>LowPriorityIO</key>      <true/>
</dict></plist>
```

결정: `StartCalendarInterval`(고정 시각) 대신 **`StartInterval` 900초 + 헬퍼 안의 시각 판정**.
이유: (1) plist 는 서명된 번들 안에 있어 `review.daily_time` 을 바꿔도 plist 를 고칠 수 없다, (2) 잠자기·로그아웃으로 놓친 실행을 헬퍼가 “마지막 실행 시각” 으로 정확히 한 번 보충할 수 있다(FR-MI-002). 비용: 15분마다 Swift 헬퍼가 수십 ms 깨어남(Python 은 실행 시각에만 기동). 정밀도: 지정 시각 + 최대 15분.
`BundleProgram` 은 헤더 주석상 번들 상대 경로를 허용하고 앱 이동에도 따라간다. `ProgramArguments` 와의 병용 동작은 확인 필요(§12 V4).

### 8.3 `DayCloseScheduler` 동작

```
main(--tick | --diagnose):
  s = SchedulerState.load()                       # §8.5 (UserDefaults)
  if !s.enabled: exit 0
  now = Date()
  core = CoreLocator.locate()                     # §3.2 (실패 → lastResult = core_missing, 하루 1회 알림 “정리 엔진을 찾을 수 없습니다”)
  gap = now - s.lastTickAt;  s.lastTickAt = now

  # 1) 일일 결산 (FR-MI-002/003)
  due = 가장 최근의 예정 시각 ≤ now
        (예정 시각 = 각 날짜의 dailyTime. 날짜는 “now - dayBoundary” 의 로컬 날짜 기준 — 04:00 전의 새벽은 전날로)
  if s.lastDailyRunAt < due:
       run_daily(); s.lastDailyRunAt = now; exit

  # 2) 로그인·깨어남 직후 조용한 스캔 (FR-MI-002 “로그인 시”)
  if gap > 2 × 900s and now - s.lastScanAt > 1h:
       run_scan(notify: false); exit

  # 3) 진단 (--diagnose 또는 하루 1회)
  if --diagnose or now - s.lastDoctorAt > 24h: run_doctor()
  exit 0
```

`run_daily`:
1. `dayclose scan run --trigger schedule --channel schedule --json --progress ndjson --wait-lock 30` — 전체 시간 제한 15분(초과 시 `SIGTERM` → 10s → `SIGKILL`, 결과 `timeout`). 진행 이벤트가 5분간 없으면 같은 방식으로 종료(NFR-REL-001). 외장 볼륨 멈춤은 core 의 프로브가 막는다(02 §10.5); 헬퍼의 제한 시간은 그 위의 두 번째 방어선.
2. `dayclose review summary --channel schedule --json` (30s 제한) — 알림 숫자의 출처.
3. 결과 요약을 `scheduler.lastResult` 에 저장(경로 없음, §8.5), `DistributedNotificationCenter.default().postNotificationName(.init("com.dayclose.scanCompleted"), object: nil, userInfo: nil, deliverImmediately: true)` — 앱이 떠 있으면 새로고침(03 §3.6). userInfo 는 비움(다른 프로세스가 엿들을 수 있으므로).
4. 알림 발송(§8.4). `E_LOCKED`(앱에서 사용자가 작업 중) → 5분 뒤 다음 tick 에서 재시도(`lastDailyRunAt` 을 갱신하지 않음), 3회 연속이면 그날은 알림 없이 종료.
5. 스캔 경고에 `W_TCC_DENIED`/`W_ROOT_UNAVAILABLE` 이 있으면 `run_doctor()` 도 실행.

결정: 헬퍼는 **승인·결정·계획 명령을 호출하지 않는다**(AGENTS §3-3). 허용 명령: `core.version`, `scan.run`, `review.summary`, `core.doctor`. 이를 코드 상수 목록으로 두고 그 밖의 명령 문자열은 실행 전 거부.

### 8.4 알림 — UserNotifications

| 항목 | 값 |
|---|---|
| 권한 요청 | 앱(온보딩 ⑥ 또는 설정)에서 `UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])`. 결정: 임시 승인(`.provisional`)은 쓰지 않음 — 매일 1회 알림이 핵심 기능이라 명시 승인 |
| 범주 `DAILY_REVIEW` | 동작 `REVIEW_NOW` “지금 검토”(`.foreground`), `LATER` “나중에”(옵션 없음) |
| 범주 `PERMISSION` | 동작 `OPEN_SETTINGS` “설정 열기”(`.foreground`) |
| 내용 | `title`, `body` = 03 §10 문구. `threadIdentifier = "daily"`, `interruptionLevel = .active`(Time Sensitive 아님 — 엔타이틀먼트 불필요), `userInfo = ["kind": "daily", "review_date": "2026-11-24"]` — 경로·이름 금지 |
| 식별자 | `daily-<review_date>`(같은 날 중복 발송 시 교체), `daily-<review_date>-later`, `permission-<YYYY-MM-DD>` |
| 응답 처리 | 앱의 `UNUserNotificationCenterDelegate.userNotificationCenter(_:didReceive:)`: `REVIEW_NOW`/기본 탭 → 메인 창 + `review_date`; `LATER` → `UNTimeIntervalNotificationTrigger(timeInterval: 3600, repeats: false)` 로 같은 내용 1회 예약(식별자 `-later`, 이미 있으면 무시); `OPEN_SETTINGS` → 설정 > 권한 |
| 앱이 앞에 있을 때 | `willPresent` → `[.banner, .list]` |

발송 주체 (결정 + 확인 필요):
- 1안(기본): 헬퍼가 직접 `UNUserNotificationCenter.current().add(_:)`. 헬퍼는 `Contents/MacOS` 안의 실행파일이므로 `Bundle.main` 이 DayClose.app 으로 해석되어 앱과 같은 알림 권한·이름을 쓸 것으로 본다 — **확인 필요 §12 V6.** 알림을 누르면 시스템이 DayClose.app 을 띄워 앱의 delegate 로 응답을 전달하는지도 V6 에서 확인.
- 2안(대체): 1안이 안 되면 헬퍼는 결과만 저장하고 `NSWorkspace.shared.open(URL("dayclose://notify-daily"), configuration: .init() with activates = false)` 로 앱을 백그라운드로 깨우고, 앱이 `scheduler.lastResult` 를 읽어 알림을 발송한다. 앱은 창을 열지 않고 메뉴바 상주 상태로 남는다.
- `LATER` 처럼 `.foreground` 가 아닌 동작에서 앱이 백그라운드로 실행되어 응답을 받는지 확인 필요(V6). 안 되면 “나중에” 는 단순 닫기로 동작(재알림 없음)하고 03 §10 문구를 그에 맞춘다.

### 8.5 스케줄러 ↔ 앱 공유 상태 (`SchedulerState`)

저장소: `UserDefaults.standard` (헬퍼의 `Bundle.main` 이 앱 번들이면 도메인 `com.dayclose.app` 공유 — 확인 필요 §12 V6. 아니면 `UserDefaults(suiteName: "com.dayclose.shared")` 로 바꾼다).
결정: 일정의 원본은 `config.toml`(`review.daily_time`, `review.day_boundary`)이다. 앱이 기동할 때와 설정을 바꿀 때 `config.get` 값을 아래 키로 **복사**한다. 이유: 헬퍼가 15분마다 Python 을 띄워 설정을 읽지 않게.

| 키 | 타입 | 쓰는 쪽 | 내용 |
|---|---|---|---|
| `scheduler.enabled` | Bool | 앱 | 예약 실행 켜짐(SMAppService 상태와 별개로 사용자의 의도) |
| `scheduler.dailyTime` / `scheduler.dayBoundary` | String `HH:MM` | 앱 | config 복사본 |
| `scheduler.notify` | Bool | 앱 | false 면 `run_daily` 는 스캔·summary 만 하고 알림 생략(권한 문제 알림은 그래도 발송) |
| `scheduler.lastTickAt`, `scheduler.lastDailyRunAt`, `scheduler.lastScanAt`, `scheduler.lastDoctorAt` | Date | 헬퍼 | |
| `scheduler.lastResult` | Dict | 헬퍼 | `at`, `kind`(daily/quiet), `ok`, `error_code`, `warning_codes[]`, `review_date`, `new_files`, `modified_files`, `items_open`, `estimated_review_minutes`, `vault_critical_new` — **경로·이름 없음** |
| `scheduler.lastDoctor` | Dict | 헬퍼 | `at`, `fda`(granted/denied/unknown), `roots`: `[{"root_id","status"}]` — 경로 없음 |

두 기기(02 §8.1): `UserDefaults`·SMAppService 등록·알림 권한은 Mac 마다 따로 있고 동기화하지 않는다(iCloud 키-값 동기화 사용 안 함). 각 Mac 의 `config.toml` 시각이 그 Mac 의 스케줄을 정한다. 무인으로 도는 Mac mini 는 알림을 볼 사람이 없을 수 있으므로 설정 > 알림·예약에서 “알림 없이 스캔만” 을 고를 수 있다(앱 키 `scheduler.notify`, 기본 켬 — 결정: PRD O1 의 무인 기기 알림 방식이 확정될 때까지의 최소 선택지).

앱은 메뉴바 숫자(03 §9)를 core 가 꺼져 있을 때 `scheduler.lastResult.items_open` 으로 표시한다.

## 9. 메뉴바 (M7)

- `MenuBarExtra(isInserted: $menuBarShown) { MenuBarContentView() } label: { MenuBarLabel(count:, warning:) }` + `.menuBarExtraStyle(.window)`(SDK 확인: `MenuBarExtra`, `WindowMenuBarExtraStyle`). 표시 여부는 설정(기본 켬, M7).
- 마지막 창을 닫아도 앱 유지: `AppDelegate.applicationShouldTerminateAfterLastWindowClosed` → `menuBarShown`.
- Dock 아이콘: 결정 — 메인 창이 열려 있으면 `.regular`, 모든 창이 닫히고 메뉴바만 있으면 `NSApp.setActivationPolicy(.accessory)`. 메뉴바에서 [지금 검토] 시 `.regular` 로 바꾸고 창을 연다. 정책 전환 시 창 순서·포커스가 어긋나는지 확인 필요(§12 V10).
- 숫자 갱신: core 가 떠 있으면 마지막 `review.summary`; 메뉴바 창이 열릴 때 core 가 꺼져 있으면 그때 띄워 `review.summary`(03 §9); 그 사이에는 `scheduler.lastResult`; 분산 알림 `com.dayclose.scanCompleted` 수신 시 갱신.

## 10. 파일시스템 연동

### 10.1 FSEvents vs 스캔

결정: **v1 은 FSEvents 를 쓰지 않는다. 증분 스캔(02 §2, 04 문서)이 유일한 변경 감지 수단.**
이유: PRD §7 비목표(“MVP 의 실시간 감시”), 상주 프로세스 없음(02 §1), NFR-PERF-001(10만 엔트리 웜 스캔 ≤10초)을 스캔만으로 목표.

재검토 조건과 설계 방향(구현하지 않음, 기록만): 웜 스캔이 NFR-PERF-001 을 넘으면 `dayclose-native fsevents-since` 서브명령을 추가해, 상주 없이 FSEvents 이력을 재생한다 — `FSEventStreamCreate` 에 `sinceWhen` = 마지막 이벤트 ID, 이력 끝은 `HistoryDone` 플래그로 판별(헤더 확인), 볼륨 UUID(`FSEventsCopyUUIDForDevice`)가 바뀌었거나 `kFSEventStreamEventFlagMustScanSubDirs` 가 오면 전체 스캔으로 되돌아감. 결과(변경된 디렉터리 목록)는 스캔 범위를 좁히는 힌트일 뿐이고 (dev, inode, size, mtime_ns) 비교가 여전히 진실. 마지막 이벤트 ID 저장 위치(06 `app_meta`)·04 알고리즘 변경이 필요하므로 그때 02/04/06 을 먼저 고친다.

### 10.2 Spotlight (`mdls`, `mdfind`)

결정: `mdls` 만 쓰고 `mdfind` 는 쓰지 않는다.
- `mdls` 는 02 §6 `run_tool` 허용 목록에 있다. 쓰는 속성: `kMDItemLastUsedDate`(앱 마지막 사용, 06 `inventory_apps.last_used_at`), `kMDItemWhereFroms`(→ 호스트만 저장, 06 `where_from_host`), `kMDItemIsScreenCapture`(스크린샷 판정 보조 — 04 문서가 채택 여부 결정). 한 번에 여러 경로를 넘겨 호출 수를 줄인다(경로 수·출력 형식은 04, 타임아웃 필수).
- `mdls` 결과가 없을 수 있다(Spotlight 색인 꺼짐, 외장 볼륨 미색인): 값 없음 = “알 수 없음”. 미사용 앱 판정(FR-AM-006)은 값이 있을 때만.
- `/Volumes/*` 경로에 `mdls` 를 호출하기 전에도 볼륨 프로브(02 §10.5).
- `mdfind` 비채택 이유: 허용 목록 밖(추가하려면 02 를 먼저 수정), 색인 상태에 따라 결과가 달라 결정론적 스캔과 어긋남, 외장 볼륨 대부분 미색인.
- Python 표준 `os` 에는 macOS 용 `getxattr` 이 없어 `com.apple.metadata:kMDItemWhereFroms` 확장 속성을 직접 읽을 수 없다 → `mdls` 경유가 맞다.

### 10.3 스크린샷 저장 위치

core(`core.init`, 기본 루트 등록, FR-CORE-002): `run_tool(["defaults", "read", "com.apple.screencapture", "location"])`.
- 종료 코드 ≠ 0(키 없음) → 기본값 `~/Desktop` → Desktop 루트와 같으므로 screenshots 루트를 따로 만들지 않음.
- 값이 `~` 로 시작하면 확장, 상대경로·존재하지 않는 경로면 무시 + 경고.
- 같은 도메인의 `target` 키가 `clipboard` 등이면 파일이 생기지 않으므로 screenshots 루트를 만들지 않음(값 확인 필요).
- 위치는 사용자가 바꿀 수 있으므로 `core.doctor` 가 현재 값과 등록된 screenshots 루트를 비교해 다르면 경고(10 문서 출력 필드).
- 파일 이름 규칙은 언어 설정에 따라 다르다(한국어 “스크린샷 2026-11-24 오후 2.02.11.png”, 영어 “Screenshot 2026-11-24 at 2.02.11 PM.png”). 판정은 이름 패턴보다 `kMDItemIsScreenCapture` 를 우선할 것을 04 에 권고.

### 10.4 앱 인벤토리 소스 (`collect/apps.py`, M3 — 알고리즘은 04)

| 정보 | 소스 | 비고 |
|---|---|---|
| 대상 | `/Applications`, `~/Applications` 아래 `.app`(깊이 2까지, `/Applications/Utilities` 포함). `/System/Applications` 제외 | 앱 번들은 패키지 1개(02 §9 `package_dirs_as_files`) |
| 이름·번들 ID·버전 | `Contents/Info.plist` → `plistlib`: `CFBundleIdentifier`, `CFBundleDisplayName`/`CFBundleName`, `CFBundleShortVersionString`, `CFBundleVersion` | 읽기 실패 → `source=unknown` |
| 출처 `app_store` | `Contents/_MASReceipt/receipt` 존재 | |
| 출처 `brew_cask` | `brew info --cask --installed --json=v2` 의 cask `artifacts` 중 app 이름과 일치 | brew 없음 → `W_TOOL_MISSING` |
| 출처 `manual` | 위 둘 다 아님 | |
| 마지막 사용 | `mdls -name kMDItemLastUsedDate` | §10.2 |
| 크기 | 번들 내부 `lstat` 합계 | 새 앱·버전 변경 시에만 계산(비용) |
| 아이콘 | 앱 쪽 `NSWorkspace.icon(forFile:)` | core 는 다루지 않음 |

`system_profiler SPApplicationsDataType` 은 쓰지 않는다(수십 초 걸림, `run_tool` 허용 목록 밖). 앱 번들 읽기는 TCC 보호 대상이 아니다(“앱 관리” 권한은 앱 **수정**에 대한 것 — DayClose 는 수정하지 않음).

### 10.5 로그인 항목·LaunchAgents 소스 (`collect/login_items.py`, M3)

| `login_item_kind` | 소스 | 비고 |
|---|---|---|
| `launch_agent_user` | `~/Library/LaunchAgents/*.plist` | `plistlib`: `Label`, `Program` 또는 `ProgramArguments[0]`, `Disabled` |
| `launch_agent_global` | `/Library/LaunchAgents/*.plist` | 읽기 전용 |
| `launch_daemon` | `/Library/LaunchDaemons/*.plist` | 읽기 전용(일반 사용자 읽기 가능 — 확인 필요) |
| `login_item` | **v1 수집 안 함** | 결정: 공개 API 로 다른 앱의 로그인 항목·`SMAppService` 등록 항목을 열거할 수 없다. `sfltool dumpbtm` 은 관리자 권한·허용 목록 밖, `osascript`(System Events)는 자동화 권한 대화상자를 띄워 예약 실행에서 쓸 수 없음 → 04 에 범위 축소로 전달(§13 G8) |

DayClose 자신의 `com.dayclose.scheduler` 는 앱 번들 안 plist 로 등록되므로 위 디렉터리에 나타나지 않는다(나타나면 무시 목록에 둔다).

### 10.6 iCloud Drive

- 루트: `~/Library/Mobile Documents/com~apple~CloudDocs`(`icloud_drive`, 02 §10.6). “데스크탑 및 문서” 동기화가 켜져 있으면 `~/Desktop`·`~/Documents` 도 iCloud 경로가 될 수 있음 → 루트 중첩 처리는 02 §10.6·04.
- 앱의 규칙: dataless 는 썸네일·QL·ImageIO·PDFKit·AVFoundation·`contentsOfDirectory` 모두 호출 금지(이들은 내용을 읽어 다운로드를 일으킴). §5.0 검사.
- `trash/move/archive` 는 `allowed_actions` 에서 빠진다(02 §10.1 예외 2) — 앱은 그대로 따른다.
- TCC: iCloud Drive 접근도 `EPERM` 이면 `W_TCC_DENIED`(02 §10.6). FDA 가 iCloud Drive 를 포함하는지 확인 필요(§12 V7).

### 10.7 휴지통 의미 (실행은 08 문서 · executor)

DayClose 에서 “휴지통” 은 executor 가 하는 **볼륨별 휴지통으로의 rename** 이다(02 §10.2-5). Swift 코드는 `FileManager.trashItem(at:resultingItemURL:)`(SDK 확인)을 포함해 어떤 이동 API 도 호출하지 않는다(§2.4). 이 절은 08 이 지켜야 할 macOS 쪽 사실과 앱 표시 규칙을 정리한다.

| 사실 | 영향 | 상태 |
|---|---|---|
| 부팅 볼륨: `~/.Trash`. 다른 볼륨: `/Volumes/<V>/.Trashes/<uid>/` | 08 의 휴지통 경로 결정 | 일반적 macOS 구조 |
| `FileManager.trashItem` 은 올바른 휴지통 선택·이름 충돌 회피·결과 URL 을 제공 | executor(Python)는 같은 규칙을 직접 구현해야 함 — 08 | SDK 확인 |
| `~/.Trash` 는 TCC 보호 위치일 수 있음: FDA 없이 목록 읽기·`lstat` 이 `EPERM` 인지, 그 안으로 rename 은 되는지 | undo 의 사전조건 확인(`actual_dst_path` 존재 확인)이 FDA 없이 실패할 수 있음 → 08 은 `E_TCC_DENIED` 로 보고, 앱은 FDA 안내 | **확인 필요 §12 V8** |
| executor 가 rename 으로 넣은 항목에는 Finder 의 “되돌려 놓기” 가 동작하지 않을 수 있음(Finder 전용 메타데이터) | 앱 문구는 “DayClose 기록에서 되돌리기” 로 통일(03 §4.6) | 확인 필요 V8 |
| 네트워크 볼륨(SMB 등)·읽기 전용 볼륨에는 휴지통이 없을 수 있음 | 08 은 이런 볼륨의 `trash` 를 계획 단계에서 거부하도록 정할 것 | 08 결정 사항 |
| 사용자가 휴지통을 비우면 되돌릴 수 없음 | `E_UNDO_IMPOSSIBLE`(02 §11), 앱 문구 03 §4.7 | — |
| iCloud Drive 항목의 휴지통 이동은 다른 기기 삭제로 전파 | 02 §10.1 예외 2 로 차단됨 | — |

## 11. 샌드박스·엔타이틀먼트·서명·보안

### 11.1 App Sandbox — 결정: 사용하지 않는다

대상: DayClose.app, DayCloseScheduler, dayclose-native 모두.
이유:
1. 사용자가 지정한 임의 루트(`~/Downloads`, `~/dev`, `/Volumes/External` …)와 `/Applications` 를 매일 읽어야 한다. 샌드박스의 사용자 선택 파일 접근(보안 범위 북마크)으로는 예약 실행·새 루트 탐지가 번거롭고, FDA 와의 관계도 복잡해진다.
2. 샌드박스 앱이 띄운 자식 프로세스는 샌드박스를 상속한다 → `~/.local/bin/dayclose`(Python core)가 샌드박스 안에서 돌게 되어 휴지통 rename·git·brew 실행이 막힌다.
3. Mac App Store 배포 계획이 없다(02 §4: 개인 로컬 빌드).
보완: 파일 변경은 core 의 executor 한 곳(02 §6), Swift 쪽 정적 검사(§2.4), 앱의 네트워크 코드 없음(Markdown 원격 로딩 금지 등 §5.4).

### 11.2 Hardened Runtime·엔타이틀먼트

- Hardened Runtime: **켬**(공증은 안 하지만 DYLD 주입 차단 등 보호를 그대로 얻음). JIT·서명 안 된 메모리·라이브러리 검증 해제 등 예외 엔타이틀먼트 없음.
- `DayClose.entitlements`: 빈 dict. Apple Events 자동화(`com.apple.security.automation.apple-events`) 불필요 — 앱은 AppleScript 를 보내지 않는다(core 의 `native_dialog` 승인은 core 가 `osascript` 로 띄우며 앱 채널에서는 쓰지 않음, 02 §10.3).
- Time Sensitive 알림·푸시 엔타이틀먼트 없음(§8.4).
- §11.3 제안을 채택하면 Secure Enclave 키 저장을 위한 키체인 접근 그룹 엔타이틀먼트가 필요할 수 있음(확인 필요).

### 11.3 앱 승인(`app_button`) 보강 제안 — 08 문서가 결정

문제: `plan.approve` 의 `method=app_button` 은 “앱의 승인 버튼을 사람이 눌렀다” 는 뜻이지만, 같은 사용자 권한의 어떤 프로세스(에이전트 포함)든 `dayclose serve --stdio --channel app` 을 직접 띄워 승인 요청을 보낼 수 있다. core 는 요청이 진짜 DayClose.app 에서 왔는지 알 수 없다 → 02 §10.3 “사람만 승인” 의 앱 경로가 구조적으로 보장되지 않는다(§13 G4).

제안(채택 여부·세부는 08):
1. 온보딩에서 앱이 CryptoKit `SecureEnclave.P256.Signing.PrivateKey` 를 만들고, 접근 제어는 `SecAccessControlCreateWithFlags(…, [.privateKeyUsage, .userPresence])`(Touch ID 또는 로그인 암호, `kSecAccessControlUserPresence` SDK 확인).
2. 공개키 등록은 사람 게이트로만: core 가 `native_dialog`(osascript) 또는 `cli_tty` 로 지문 일부를 보여주고 확인받아 DB 에 저장.
3. 앱 승인 요청에 `signature = Sign(plan_id ‖ plan_hash ‖ nonce)` 를 붙이고, core 는 `cryptography` 로 P-256 ECDSA 검증. 서명이 없거나 틀리면 `app_button` 을 거부.
4. 효과: 승인마다 Touch ID/암호 확인 → 사람 게이트가 앱 경로에서도 실제로 강제됨. 에이전트는 Secure Enclave 키를 쓸 수 없다.
비용: 비샌드박스 앱의 Secure Enclave 키가 데이터 보호 키체인을 필요로 하는지, 개인 팀 서명으로 가능한지 확인 필요(§12 V11). 08 이 채택하지 않으면 최소한 앱의 [승인하고 실행] 앞에 `LAContext.evaluatePolicy(.deviceOwnerAuthentication)` 를 두어 UI 실수 승인을 줄인다(이 경우 core 쪽 보장은 없음을 08 에 명시).

### 11.4 Keychain

- 필드 암호화 키(`com.dayclose.db` / `field-key-v1`)와 AI 키(`com.dayclose.ai` / `<provider>`)는 core(`keyring`)가 만들고 읽는다(02 §3, §9). 앱은 이 항목을 읽거나 쓰지 않는다.
- 이유: macOS 파일 기반 키체인 항목은 만든 앱이 기본 신뢰 앱이 되므로, 앱이 AI 키를 만들면 Python 이 읽을 때마다 “키체인 접근 허용” 대화상자가 뜬다(확인 필요). 따라서 설정 화면의 AI 키 입력은 core 명령으로 전달해야 한다 — 그런 명령이 02 §5.3 에 없음(§13 G5, 03 §13 R9).
- Python 인터프리터가 키체인 항목의 신뢰 목록에 들어가는 문제(uv 가 Python 을 업데이트하면 경로가 바뀜)는 07/10 이 다룬다.

### 11.5 Gatekeeper

로컬에서 빌드한 앱은 격리 속성(`com.apple.quarantine`)이 없어 공증 없이 실행된다. 다른 기기(Mac mini, PRD O1)로 옮길 때는 그 기기에서 직접 빌드한다(복사 시 격리 속성·서명 신뢰 문제 회피). 결정: 빌드 산출물을 배포하지 않는다(02 §4).

## 12. 실기기 검증 항목

M4·M7 종료 전에 소유자 기기에서 수행하고 결과를 이 표의 “결과” 열과 12 문서 해당 마일스톤에 기록한다.
**두 기기는 독립 설치**(02 §8.1)이므로 TCC·서명·예약 실행 항목(V1, V3~V6, V13~V15)은 **MacBook 과 Mac mini 각각** 수행하고 결과를 기기별로 적는다. Mac mini 는 내장 디스크가 작고 `/Volumes/External` 이 상시 연결되어 있으므로, Mac mini 의 V3·V4·V14 는 반드시 `/Volumes/External` 아래 루트(그리고 `archive.root` 를 외장으로 둔 경우 그 경로)를 등록한 상태에서 한다 — F1(멈춤)이 실제로 재현된 곳이 이 구성이다. MacBook 은 외장 없이 홈 루트 + iCloud Drive 로 수행하고, 외장을 연결할 수 있으면 V14 를 추가로.

결과 기록 형식: `V3 | Mac mini | 2026-12-01 | ok | D1 ok, D2 ok, D3 ok, 외장 3.1s`. 모든 검증은 `doctor`·미리보기 같은 읽기 동작 또는 샌드박스 데이터로 한다(실제 사용자 파일 변경 없음).

| # | 확인할 것 | 방법 | 실패 시 | 마일스톤 | 결과 |
|---|---|---|---|---|---|
| V1 | FDA 프로브 대상(TCC.db open, `~/Library/Safari` opendir)이 FDA 유무를 정확히 가르는지 | FDA 끔/켬 상태에서 앱 설정 > 권한 | 다른 보호 경로로 대상 교체 | M4 | |
| V2 | `x-apple.systempreferences:…?Privacy_AllFiles` 가 macOS 26 에서 해당 패널을 여는지 | 버튼 클릭 | 상위 패널 + 문구 | M4 | |
| V3 | 앱의 자식 core(Python, `~/.local/bin/dayclose`)가 앱의 FDA 로 `/Volumes/External`·`~/Desktop` 에 접근하는지(F3) | 터미널 FDA 를 끈 상태에서 §7.5 D1·D2 비교 | 배포 안 B 검토(§3.1) | M4 | |
| V4 | SMAppService 로 등록한 헬퍼가 앱의 FDA 를 따르는지(F4), `BundleProgram`+`ProgramArguments` 병용 동작 | §7.5 D3·D4 | 헬퍼를 앱 번들 대신 앱 자체(`dayclose://` 백그라운드 실행)로 바꾸는 구조 검토 | M7 | |
| V5 | 같은 인증서로 재빌드·재설치 후 FDA 유지 / 인증서 갱신 후 유지 | `scripts/install-app.sh` 후 V1 | 재설치 안내 문구 강화 | M7 | |
| V6 | 헬퍼의 `Bundle.main`·`UserDefaults.standard` 도메인이 `com.dayclose.app` 인지, 헬퍼가 보낸 알림이 앱 이름·권한으로 표시되고 탭 시 앱이 응답을 받는지, `LATER` 응답 시 앱이 백그라운드 실행되는지 | 헬퍼 `--tick` 강제 실행 | §8.4 2안, §8.5 suite 변경 | M7 | |
| V7 | FDA 가 iCloud Drive 접근을 포함하는지 | FDA 켬/끔 + iCloud 루트 doctor | 03 문구 보강 | M4 | |
| V8 | FDA 없이 `~/.Trash` 목록/`lstat`/rename 결과, rename 한 항목의 Finder “되돌려 놓기” 동작 | **샌드박스용 테스트 파일 1개**로 08 실험 절차(08 이 정함) | 08 의 undo 사전조건 수정 | M5 | |
| V9 | `metadata_only`·`ephemeral` 열람 후 앱이 해당 파일을 `open()` 하지 않는지(`metadata_only`), 시스템 QL 캐시에 파생물이 생기는지 | `fs_usage -w -f filesys DayClose`, QL 캐시 디렉터리 변화 | §6 규칙 강화(ephemeral 의 QL 패널 금지 등) | M4 | |
| V10 | 활성화 정책 `.accessory`↔`.regular` 전환 시 창·포커스 문제 | 메뉴바만 남기고 [지금 검토] | Dock 아이콘 상시 표시로 단순화 | M7 | |
| V11 | 비샌드박스·개인 팀 서명 앱에서 Secure Enclave 서명 키 생성·`.userPresence` 사용 가능 여부 | 시험 빌드 | §11.3 대안(LAContext) | M5 | |
| V12 | `RecognizeTextRequest` 의 한국어(`ko-KR`) 지원과 정확도 | 샌드박스 스크린샷 픽스처 | 언어 목록 조정 | M6 | |
| V13 | 잠자기 중 21:00 을 넘긴 뒤 깨어나면 15분 안에 1회만 결산 실행·알림 | 실제 잠자기 | §8.3 판정 수정 | M7 | |
| V14 | FDA 없는 상태에서 외장 루트가 있어도 예약 실행이 제한 시간 안에 경고로 끝남(NFR-REL-001) | §7.5 D4 | core 프로브·헬퍼 제한 시간 조정 | M7 | |
| V15 | 같은 인증서 재빌드·재설치 후 `SMAppService.status` 가 `.enabled` 로 유지되는지, “백그라운드 항목 추가” 알림이 다시 뜨는지. 의도적으로 다른 인증서(또는 ad-hoc)로 서명한 시험 빌드에서 FDA·예약 실행이 어떻게 깨지는지(실패 모습을 안내 문구에 반영) | 재빌드 → `install-app.sh` → 앱 설정 > 알림·예약, 다음 tick 확인 | §7.6.1 의 재등록 배너 | M7 | |
| V16 | 복사된 DB(다른 Mac 의 `DAYCLOSE_HOME`)로 앱을 띄우면 `W_DEVICE_MISMATCH` 배너가 뜨고 승인 버튼이 비활성인지 | `--home` 에 다른 기기 상태 사본(샌드박스 사본) 지정 | 03 §7.2 | M4 | |

## 13. 기반 문서(02/06/AGENTS/12)와 다른 문서에 대한 요구

| # | 대상 | 내용 |
|---|---|---|
| G1 | 02 §4·§9 | “설정 `core.command`” 가 `config.toml` 키인지 불명확. 이 문서는 앱 UserDefaults 키로 결정(§3.2). 02 §9 에 없다는 점을 02 에 한 줄 명시 필요 |
| G2 | 02 §15.1 | 새 환경변수 `DAYCLOSE_NATIVE`(core 가 앱 번들 안 `dayclose-native` 를 찾는 경로) 추가 필요 |
| G3 | 10 | `core.doctor` 출력에 `full_disk_access: granted\|denied\|unknown`, 루트별 상태(02 §10.5), 스크린샷 위치 불일치 경고, 실행 채널 |
| G4 | 02 §10.3 / 08 | `app_button` 승인이 앱에서 왔다는 것을 core 가 검증할 수단이 없음. §11.3 제안 |
| G5 | 02 §5.3 / 07 / 10 | AI 키를 Keychain 에 넣는 core 명령이 없음(§11.4) |
| G6 | AGENTS §3-2 / 12 M4 | 디스크 썸네일 캐시를 도입하면 Swift 파일 삭제 금지 검사에 캐시 디렉터리 한정 예외가 필요. M4 는 메모리 캐시만이라 현재는 불필요 |
| G7 | 04 / 10 | ZIP 내부 목록·DMG/PKG “설치 대상” 표시용 데이터를 항목에 줄지 |
| G8 | 04 | `login_item` 종류(BTM 로그인 항목)는 v1 에서 수집 불가 — FR-AM-004 의 범위를 LaunchAgents/Daemons plist 로 한정 |
| G9 | 02 §7 | 스케줄러가 `scan.run` 뒤 `review.summary --channel schedule` 도 호출(알림 숫자 출처). 02 §7 표의 예약 실행 줄에 추가 필요 |
| G10 | 10 | `serve --stdio` 가 `--channel` 전역 플래그를 받는지, stdin EOF 시 진행 중 `plan.apply` 처리 방식, 진행 중 요청 취소 수단 |
