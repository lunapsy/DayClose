# 13 — 오픈소스 조사 (OPEN-SOURCE RESEARCH)

> 조사일: **2026-11-24**. 방법: 각 저장소를 GitHub API(`gh api repos/<owner>/<repo>`, README, 파일 트리, 최신 커밋·릴리스, 라이선스 파일)로 직접 확인하고 핵심 소스 파일 일부를 읽었다. 별 수·커밋 날짜는 조사 시점 값이며 바뀐다.
> CONTEXT 턴0 의 프로젝트 목록은 채팅 도우미가 제시한 것이라 그대로 믿지 않고 하나씩 존재와 내용을 확인했다. 확인하지 못한 값은 “확인 불가” 로 적는다.
> **DayClose 는 MIT 라이선스 오픈소스, 수익화 없음**(소유자 결정 2026-11-24). 판정 기준: MIT·BSD·Apache-2.0 등 허용형(permissive) 라이선스 코드는 고지를 지키면 가져올 수 있고, **GPL/AGPL 코드는 복사 불가 — 별도 프로세스로 실행하는 외부 도구로만** 쓸 수 있다(02 §15.2).
> 이 문서의 결론이 02 의 기술 선택을 바꾸지는 않는다(바꿀 필요가 있는 항목은 §5 에 제안으로만 적음).

## 1. 결론 요약

| 프로젝트 | 존재 | 라이선스 | 언어 | 활동(마지막 커밋) | 결정 | 한 줄 이유 |
|---|---|---|---|---|---|---|
| Mole (`tw93/Mole`) | 확인 | GPL-3.0 | Shell(+Go) | 2026-11-23, 릴리스 V1.74.0 | **아이디어만** (+ 사용자에게 별도 도구로 안내) | 정리 명령 일부가 **영구 삭제**·휴지통 비우기 → DayClose 안전 모델과 충돌. GPL 코드 복사 불가 |
| agentic-mac-skills (`iselur/agentic-mac-skills`) | 확인 | MIT | Python/Shell | 2026-06-24 (생성 다음 날 이후 없음) | **아이디어만** | 읽기 전용 감사 스크립트 모음. 범위·스캔 대상 목록 참고 가치 |
| Sorty (`sorty-organizer/Sorty`) | 확인 | GPL-3.0 | Swift | 2026-11-19, v1.3.1 | **아이디어만** | AI 정리·학습 구조 참고. GPL·Swift 앱이라 재사용 불가 |
| Declutter (`vamgan/declutter`) | 확인 | MIT | Python | 2026-08-31 | **아이디어만** | 안전 규칙(거부 목록·백업·“내용은 데이터”)과 동기화 충돌 사본 패턴 참고 |
| FileMorrow (`M-Nabeegh/FileMorrow`) | 확인 | MIT | Swift | 2026-11-10, v1.8.0 | **아이디어만** (가장 직접 유용) | 설치 파일↔설치 앱 매칭, 압축 해제 완료 zip 판정 알고리즘을 04 에 채택 |
| FolderSorter (`kodlbegiko/FolderSorter`) | 확인 | MIT | Swift(+Python CLI) | 2026-06-17, v0.2.0 | **무시**(참고 수준 낮음) | 확장자 규칙 정리기. 새 아이디어 없음 |
| Composio file-organizer (`ComposioHQ/awesome-claude-skills/file-organizer`) | 확인 | README 상 Apache-2.0, 루트 `LICENSE` 파일 없음 | Markdown(SKILL.md) | 해당 폴더 2025-10-17 | **무시** | 일반 지침 문서. macOS 에서 그대로 동작하지 않는 명령 포함 |
| Sortwise (`fabioderiu/sortwise`) | 확인 | MIT | Python core + Swift 메뉴바 | 2026-08-14, v0.1.0 | **무시**(반면교사로만 언급) | 파일명을 외부 AI 로 그대로 전송 — DayClose 가 피해야 할 패턴 |
| Binky (`heyderekj/binky`) | 확인 | MIT | Swift | 2026-10-30, v1.7.0 | **아이디어만** | 다운로드 안정화 대기(stable-file gate), 불확실 항목 Review 격리 |
| gitleaks (`gitleaks/gitleaks`) | 확인 | MIT | Go | 2026-10-28, v8.30.1 | **외부 도구로 호출**(02 §3 그대로) | 선택 설치, `run_tool` 허용 목록에 이미 있음 |
| age (`FiloSottile/age`) | 확인 | BSD-3-Clause | Go | 2026-08-29, v1.3.2 | **무시(범위 밖)** | NAS·원격 암호화 백업이 비목표가 되어 쓰지 않음(02 §3). 라이선스상으로는 문제 없음 |

### 1.1 MIT 기준 라이선스 판정

| 프로젝트 | 라이선스 | MIT 프로젝트에 코드 복사 | 외부 도구로 실행 | 비고 |
|---|---|---|---|---|
| Mole, Sorty | GPL-3.0 | **불가** | 가능(라이선스상) | Mole 은 안전 모델 때문에 실행도 하지 않음(§2.1). Sorty 는 앱이라 실행 대상 아님 |
| agentic-mac-skills, Declutter, FileMorrow, FolderSorter, Sortwise, Binky | MIT | 가능(저작권·허락 고지 유지) | 가능 | 실제로는 재구현만(§4) |
| gitleaks | MIT | 가능 | 가능 — **채택**(외부 도구) | |
| age | BSD-3-Clause | 가능(고지 유지) | 가능 | 사용 안 함(범위 밖) |
| Composio file-organizer | README 에 Apache-2.0 선언, LICENSE 파일 없음 | **보류** — 라이선스 파일로 확인되기 전에는 복사 안 함 | 해당 없음(문서) | Apache-2.0 이라면 MIT 프로젝트에 포함 가능(NOTICE·변경 표시 의무) |

AGPL 프로젝트는 이번 목록에 없다.

**의존성으로 코드에 포함(라이브러리 재사용)하는 프로젝트는 없다.** 결정: 조사한 정리 도구는 모두 앱/CLI/스킬이지 Python 라이브러리가 아니고, 핵심 로직(안전·보호·undo)은 DayClose 가 직접 가져야 한다(02 §4 “엔진은 하나”).

---

## 2. 프로젝트별 상세

### 2.1 Mole — `https://github.com/tw93/Mole`

- **확인 값**: GPL-3.0(LICENSE 파일 확인), 주 언어 Shell, 별 약 75,900, 포크 약 2,700, 기여자 100명 이상(API 페이지 상한), 최신 릴리스 V1.74.0(2026-11-21), 마지막 커밋 2026-11-23. Homebrew core 에 `mole` formula 존재(stable 1.74.0, 이 머신 미설치). macOS 외에 Windows·Linux 브랜치, 별도 상용 네이티브 앱(mole.fit) 존재.
- **실제 기능**: `mo clean`(캐시·로그·삭제된 앱 잔여물), `mo uninstall`(앱 + 잔여물), `mo optimize`(DNS·Quick Look·DB 정비), `mo analyze`(디스크 탐색 TUI, `--json`), `mo status`(시스템 상태), `mo purge`(프로젝트 빌드 산출물: `node_modules`, `target`, `.build`, `build`, `dist`), `mo installer`(DMG/PKG/MPKG/ISO/XIP/설치형 ZIP 찾기), `mo history --json`. `--dry-run` 미리보기와 화이트리스트, 작업 로그(`~/Library/Logs/mole/operations.log`) 제공.
- **Agent Skill**: 사실. README 가 `npx skills add tw93/Mole -a claude-code codex cursor -g -y` 와 Claude Code/Codex 플러그인 마켓플레이스를 안내하고 저장소에 `.agents/skills/mole` 이 있다.
- **CONTEXT 와 다른 점(중요)**:
  - README 의 안전 절: `clean`, `purge`, `installer` 는 **영구 삭제**한다(휴지통 아님). `uninstall`·`analyze`·`slim` 만 기본 휴지통.
  - `mo clean` 은 기본으로 **`~/.Trash` 를 비운다**(화이트리스트에서 끌 수 있음). DayClose 의 “삭제 = 휴지통 이동 + undo” 모델과 정면으로 충돌한다: 사용자가 `mo clean` 을 돌리면 DayClose 가 휴지통에 넣은 항목의 undo 가 `E_UNDO_IMPOSSIBLE` 이 된다. → 08 의 undo 불가 조건·안내 문구에 “Mole 등 정리 도구가 휴지통을 비운 경우”를 명시할 것(보고서 참고).
  - `mo installer` 는 설치 파일을 찾지만 **해당 앱이 설치됐는지 대조한다는 설명은 README 에 없다**(위치·크기 기준). DayClose 의 FR-SO-001 판정에는 FileMorrow 방식이 더 맞다.
- **결정: 아이디어만 참고.**
  - 이유 1: GPL-3.0 — MIT 인 DayClose 에 코드 복사 불가. 별도 프로세스로 실행하는 외부 도구 사용은 라이선스상 허용되지만,
  - 이유 2: 실행 위임 자체가 안전 모델 위반이다 — DayClose 의 파일 변경은 `executor` 만, 영구 삭제 금지(02 §6, AGENTS §3-2). `mo` 는 `run_tool` 허용 목록에 넣지 않는다.
  - 이유 3: 시스템 캐시·앱 삭제는 PRD 비목표(§7). 사용자에게는 “시스템 정리가 필요하면 Mole 을 따로 쓰되, 휴지통 비우기 화이트리스트 설정을 권장” 정도로 README/리포트에서 안내만.
  - 차용 아이디어: (a) `purge` 의 보호 조건 — 최근 7일 활동 산출물은 기본 미선택, git 추적 파일·중첩 저장소 포함 디렉터리 보호 → 04 §10 에 반영. (b) 단계별 타임아웃 환경변수 설계(빠른 탐지 2초, 트리 탐색 5초 등) → 04 §14 예산 표의 발상. (c) 실행 직전 “확인된 identity” 재검증 → 이미 02 §10.2 와 같음. (d) 부분 스캔을 `complete/partial/unavailable` 로 명시하는 JSON → 04 §2.4 “보이지 않음 ≠ 삭제”.

### 2.2 agentic-mac-skills — `https://github.com/iselur/agentic-mac-skills`

- **확인 값**: MIT, Python 약 100KB + Shell 약 30KB, 별 0, 포크 0, 기여자 1, 생성 2026-06-23, 마지막 커밋 2026-06-24, 릴리스 없음.
- **실제 기능**: Codex/Claude 공용 스킬 **13개**(CONTEXT 는 5개만 언급): `macos-system-data-audit`, `downloads-desktop-triage`, `mac-app-inventory`, `image-batch-convert`, `backup-audit`, `browser-profile-audit`, `launch-agent-audit`, `developer-cache-audit`, `csv-clean-room`, `archive-batch-tools`, `pdf-file-audit`, `plist-defaults-audit`, `screenshot-organizer`. 모두 기본 읽기 전용, 보고서를 임시 디렉터리에 쓰고 삭제하지 않는다. 대부분 `find`/`du`/`stat` 셸 스크립트. 나머지 저장소 내용은 앱스토어 차트 분석(research/).
- **CONTEXT 와 다른 점**: 언급된 5개 스킬은 실제로 있다. 다만 “직접 만들 때 스캔 엔진의 참고 자료로 적합” 하다는 평가는 과하다 — 스크립트는 단순 목록화(파일명 패턴 `^(screenshot|screen recording)` 정도, 영어만)이며, 1인·이틀 활동의 초기 저장소다. CONTEXT 의 추천도 ★★★★★ 는 근거가 약하다.
- **결정: 아이디어만.** 이유: 기능이 단순하고 셸 기반이라 Python core 에 가져올 것이 없다. 차용: `developer-cache-audit` 의 알려진 개발 캐시 위치 목록(`~/Library/Developer/Xcode/DerivedData`, `CoreSimulator`, `~/.npm`, `~/.cache/uv` 등)은 04 §10 의 범위 확장 후보로만 기록(현재 04 는 프로젝트 내부 캐시 + DerivedData 만 다룬다 — 전역 패키지 캐시는 “시스템 정리” 영역이라 비목표).

### 2.3 Sorty — `https://github.com/sorty-organizer/Sorty`

- **확인 값**: GPL-3.0, Swift, 별 61, 포크 5, 기여자 9, 최신 릴리스 v1.3.1(2026-11-05), 마지막 커밋 2026-11-19. 서명·공증 안 된 배포(README 가 `xattr -cr` 안내).
- **실제 기능**: SwiftUI 앱. AI 공급자 다수(OpenAI 호환, Anthropic, Gemini, Groq, OpenRouter, Ollama, Apple Foundation Models), 이미지 내용 분석(Vision 지원 공급자), Finder 확장, 감시 폴더 자동 정리, 미리보기 후 적용, 이력·롤백, 정확 중복 검토, 학습 프로필(“Learnings”, AES-256 암호화 로컬 저장), 에이전트용 Sorty Skill(Codex/Claude Code/OpenCode 등), 네트워크 차단 모드(루프백만 허용, `NetworkPrivacyPolicy.swift`).
- **CONTEXT 와 다른 점**: 서술은 대체로 맞다. 덧붙일 사실 — README 가 명시하듯 **학습 문맥과 폴더 구조·파일 메타데이터를 선택한 AI 공급자에 보낸다**(Deep Scan 은 내용 요약까지). 규칙 추론 엔진(`LocalRuleInferenceEngine.swift`)은 **예시 2개**만으로 규칙을 만든다(`minExamplesForRule = 2`).
- **결정: 아이디어만.** 이유: GPL-3.0 이라 MIT 인 DayClose 에 코드 복사 불가, 게다가 Swift 앱이라 외부 도구로 부를 CLI 도 없다(DayClose core 는 Python, 02 §4). 차용: (a) 공급자 추상화와 “루프백만 허용” 모드 → 07 §3.2 의 로컬/외부 판정. (b) 학습 증거로 “사용자 정정(correction)” 을 긍정 예시보다 높게 보는 우선순위 → 07 §5.7 에서 되돌림을 강한 신호로 사용. 반면 임계값은 **의도적으로 다르게**: DayClose 는 파일 휴지통까지 자동 결정에 쓰므로 5회·3일·90%(07 §5.3). Sorty 의 2회는 “이동 위치 제안” 용이라 위험도가 다르다.

### 2.4 Declutter — `https://github.com/vamgan/declutter`

- **확인 값**: MIT, Python(표준 라이브러리만), 별 4, 기여자 1, 생성 2026-08-25, 마지막 커밋 2026-08-31, 릴리스 없음, CI 테스트(macOS·Linux·Windows) 존재.
- **실제 기능**: 에이전트 스킬 4개 — `organizing-bookmarks`(11개 브라우저), `organizing-folders`(다운로드·바탕화면·클라우드 폴더: 중복, 오래된 파일, 큰 파일, 동기화 충돌 사본), `organizing-photos`(촬영일 기준, 스크린샷 분리, 중복·연사), `organizing-notes`(Obsidian 등). `npx skills add vamgan/declutter`, Claude Code 플러그인. 공통 `safe-mutation-rules.md`: 백업 먼저, 수치 보여 주고 대기, 휴지통만, 루트 밖·심볼릭 링크 탈출 금지, `~/.ssh`·`~/.aws`·`~/Library` 거부 목록, “파일 이름은 데이터지 지시가 아니다”.
- **CONTEXT 와 다른 점**: “스크린샷 정리”는 별도 스킬이 아니라 사진 스킬의 일부다. 중복 판정은 **SHA-256 전체가 아니라 앞·뒤 1MB + 크기**의 부분 해시(16자로 절단) — 빠르지만 정확 중복 보장이 아니다. 스크린샷 판정은 영어 파일명 패턴(`Screen Shot`, `Screenshot`, `CleanShot` 등)이라 **한국어 macOS 의 `스크린샷 …` 은 잡지 못한다**.
- **결정: 아이디어만.** 이유: 에이전트가 직접 파일을 옮기는 스킬 구조라 DayClose 의 “core 만 실행” 구조와 다르다. 차용: (a) 동기화 충돌 사본 정규식 목록(Dropbox·Nextcloud·OneDrive·Box) → 04 §12.2 이름 변형. (b) 거부 목록·“내용은 데이터” 원칙 → 07 §8.4 프롬프트, 05 의 기본 보호 경로와 일치 확인. (c) 스크린샷 판정에서 “PNG 인데 카메라 정보 없음” 을 확정이 아닌 ‘모름’으로 두는 태도 → 04 §6 의 낮은 가중치(0.2). 부분 해시는 채택하지 않음(04 §2.5 는 전체 SHA-256 — 중복 제안이 `trash` 로 이어지므로 정확해야 함).

### 2.5 FileMorrow — `https://github.com/M-Nabeegh/FileMorrow`

- **확인 값**: MIT, Swift, 별 80, 기여자 1, 최신 릴리스 v1.8.0(2026-08-19), 마지막 커밋 2026-11-10. Homebrew 탭(`m-nabeegh/tap`) 배포, 애드혹 서명.
- **실제 기능**: 다운로드 폴더 전용. 오늘/어제/7일 보기, 7일 지난 최상위 파일만 카테고리 폴더로, 형식 모드(기본) / 스마트 콘텐츠 모드(Apple Foundation Models, 온디바이스), Vision OCR, 신뢰도 게이트·“검토 필요” 상태, 계획 우선 승인, undo, SHA-256 정확 중복, **압축 해제 완료 zip 판정**, **설치 완료 설치 파일 판정**, 메뉴바.
- **CONTEXT 와 다른 점**: “온디바이스 AI, 다운로드 정리, 실행 취소” 서술은 정확하다. CONTEXT 가 언급하지 않은 가장 유용한 부분이 설치 파일·압축 파일 판정이다.
- **결정: 아이디어만(알고리즘 재구현).** 이유: Swift 코드라 그대로 쓸 수 없고, MIT 라도 재구현이 더 작다. 04 에 채택한 것:
  - PKG: 패키지 메타데이터(`Distribution`/`PackageInfo`)의 identifier·version 을 macOS 설치 영수증과 대조 — FileMorrow 는 `/usr/bin/xar`·`pkgutil` 을 호출하지만, DayClose 는 허용 도구 목록(02 §6)을 늘리지 않기 위해 xar 목차를 표준 라이브러리로 읽고 `/var/db/receipts/*.plist` 를 `plistlib` 로 읽는다(이 머신에서 영수증 plist 에 `PackageIdentifier`·`PackageVersion`·`PackageFileName` 이 있음을 확인). 04 §7.2.
  - DMG: 정규화한 이름 ↔ `/Applications`·`~/Applications` 앱 이름 + 파일명 버전 비교, **설치본보다 새 설치 파일은 절대 정리 제안하지 않음**. 04 §7.2.
  - ZIP: 모든 항목이 같은 상대경로·같은 크기로 풀려 있을 때만, `__MACOSX`/`.DS_Store`/`._*` 무시, 경로 탈출 항목이 있으면 판정 무효, 압축 해제된 폴더는 건드리지 않음. 04 §7.3.
  - “처음 본 날짜를 따로 기억해 이동해도 대기 기간이 초기화되지 않음” → DayClose 는 엔트리 행 계보(04 §2.4)로 같은 효과.

### 2.6 FolderSorter — `https://github.com/kodlbegiko/FolderSorter`

- **확인 값**: MIT, Swift + Python(`pip install foldersorter`), 별 3, 기여자 1, 릴리스 v0.2.0(2026-06-16), 마지막 커밋 2026-06-17.
- **실제 기능**: 확장자·이름 토큰 규칙(JSON)으로 Images/Videos/Documents/Archives/Installers/Audio/Code/Screenshots 폴더에 복사(기본) 또는 이동, 미리보기, 마지막 작업 undo, 충돌 시 rename/skip/**replace**.
- **CONTEXT 와 다른 점**: 서술(“SwiftUI GUI, Python CLI, 사전 검토 및 복구”)은 맞다. 다만 충돌 정책에 덮어쓰기(replace)가 있어 DayClose 의 “목적지 덮어쓰기 금지”(02 §10.2-4)와 다르다.
- **결정: 무시.** 이유: 확장자 기반 정리기로 04 §5 카테고리 표 이상의 정보가 없다. 활동이 짧다.

### 2.7 Composio file-organizer — `https://github.com/ComposioHQ/awesome-claude-skills/blob/master/file-organizer/SKILL.md`

- **확인 값**: 경로 존재(`file-organizer/SKILL.md` 한 파일). 저장소(`ComposioHQ/awesome-claude-skills`, 별 약 80,000)는 스킬 모음 목록이다. **라이선스: GitHub 가 인식하는 루트 LICENSE 파일 없음.** README 는 “Apache License 2.0” 이라고 쓰고 “개별 스킬은 다른 라이선스일 수 있다” 고 한다. `file-organizer/` 폴더에는 별도 LICENSE 파일이 없다 → 이 스킬의 정확한 라이선스는 **확인 불가**(README 선언을 따르면 Apache-2.0). 해당 폴더 마지막 변경 2025-10-17.
- **실제 기능**: 코드 없는 지침 문서. 범위 질문 → 구조 분석(`find`, `du`) → 중복 찾기 → 정리 계획 → 승인 후 이동.
- **CONTEXT 와 다른 점**: “범용 파일 정리 Skill” 은 맞다. 그러나 문서의 예시 명령은 macOS 에서 그대로 동작하지 않는다: `find … -printf` 는 GNU 전용이다(이 머신 `/usr/bin/find` 에서 `-printf: unknown primary or operator` 확인). 중복 찾기 예시 `find … -exec md5 {} \; | sort | uniq -d` 는 macOS `md5` 출력이 `MD5 (경로) = 해시` 형식이라 줄마다 경로가 달라 **중복을 하나도 찾지 못한다**.
- **결정: 무시.** 이유: 재사용할 알고리즘이 없고 예시 명령이 부정확하다. DayClose 의 Skill(M8, 10 문서)은 core CLI 를 호출하는 얇은 지침이어야 하며 셸 명령으로 파일을 다루지 않는다.

### 2.8 Sortwise — `https://github.com/fabioderiu/sortwise`

- **확인 값**: MIT, GitHub 언어 표기는 Swift(바이트 기준 Swift 38KB, Python 26KB — 실제 정리 로직은 Python `sortwise/core.py`, Swift 는 메뉴바 앱), 별 0, 기여자 1, 릴리스 v0.1.0(2026-04-25), 마지막 커밋 2026-08-14.
- **실제 기능**: 다운로드/문서/바탕화면 파일 **이름 목록을 Claude Haiku 에 보내** receipts·travel·work 같은 범주로 분류 후 하위 폴더로 이동, 30일 지난 것은 `_old/<범주>/`, `--no-ai` 확장자 모드, 4시간마다 자동 정리, launchd plist.
- **CONTEXT 와 다른 점**: “Claude 기반 분류, 메뉴바 앱” 은 맞다. 덧붙일 사실: 기본 동작이 파일명을 마스킹 없이 외부 API 로 전송하고, 승인 없이 주기적으로 이동한다(`--move` 설정 시).
- **결정: 무시.** 반면교사로만 07 에 반영: 파일명 자체가 개인 정보(환자 이름, 견적서 번호)를 담는다 → DayClose 는 민감도 게이트 + 마스킹 + 기본 외부 전송 금지(07 §3, §8.3).

### 2.9 Binky — `https://github.com/heyderekj/binky`

- **확인 값**: MIT, Swift(SwiftUI + AppKit, `BinkyCore` SwiftPM + `binky` CLI), 별 389, 포크 24, 기여자 4, 최신 릴리스 v1.7.0(2026-10-30), 마지막 커밋 2026-10-30. README 에 따르면 2.0 공식 빌드는 유료 라이선스 예정이나 소스는 MIT 유지.
- **실제 기능**: Quick Sort(한 번 정리), Routines(이름 붙은 감시자), 파일 안정화 대기 후 라우팅, 규칙(확장자·이름·출처·OCR 영수증 힌트·Finder 태그, 동작: 이동·zip·압축 해제·DMG 설치·태그·휴지통·이름변경), 모르는 확장자는 Review 폴더로, 세션 이력.
- **CONTEXT 와 다른 점**: “폴더 감시, 규칙 기반 반복 정리” 는 맞다. 원본을 실제로 이동하는 자동화 도구다(“Moves originals”).
- **결정: 아이디어만.** 차용: (a) 다운로드가 끝날 때까지 기다리는 안정화 게이트 → 04 §2.2-4 settle 규칙. (b) 불확실한 것은 별도 검토 상태로 — DayClose 는 이미 “모든 것을 검토”가 기본이라 동일 개념이 confidence < 0.6 제안 없음으로 표현됨.

### 2.10 gitleaks — `https://github.com/gitleaks/gitleaks`

- **확인 값**: MIT, Go, 별 약 31,300, 기여자 100+, 최신 릴리스 v8.30.1(2026-03-21), 마지막 커밋 2026-10-28. 이 머신에 Homebrew 로 8.30.1 설치되어 있음(`/opt/homebrew/bin/gitleaks`).
- **확인한 CLI 사실**(`gitleaks dir --help`, 8.30.1): `gitleaks dir [path]`(별칭 `file`, `directory`), `--redact[=N]`(기본 100%), `-f/--report-format json|csv|junit|sarif|template`, `-r/--report-path`(`-` = stdout), `--max-target-megabytes`, `--timeout`(초), `--exit-code`(기본 1), `--no-banner`, `--max-archive-depth`(기본 0), `-c/--config`. 설정 탐색 순서에 **대상 경로의 `.gitleaks.toml`** 이 포함된다.
- **결정: 외부 도구로 호출**(02 §3·§6 과 동일, 상세 통합은 05). 이 조사가 05 에 넘기는 주의 사항:
  - 대상 경로에 있는 `.gitleaks.toml` 이 자동으로 쓰일 수 있다(사용자/제3자 파일이 탐지 규칙을 바꿈) → 항상 `-c <DayClose 내장 설정>` 을 명시하거나 `GITLEAKS_CONFIG` 를 고정한다.
  - `.gitleaksignore`(`-i` 기본 `.`) 와 `gitleaks:allow` 주석도 결과에 영향 → 작업 디렉터리를 `DAYCLOSE_HOME` 아래 빈 디렉터리로 두고 `-i` 를 그쪽으로.
  - `--redact` 를 쓰더라도 JSON 리포트에는 `Match`/`Secret` 필드가 존재한다 → 05 §(gitleaks) 의 “결과에서 즉시 폐기” 규칙 유지, 리포트는 파일이 아니라 stdout(`-r -`)으로 받아 메모리에서만 파싱.
  - 누출 발견 시 종료 코드 1이 정상 결과다(`--exit-code` 로 조정 가능).

### 2.11 age — `https://github.com/FiloSottile/age`

- **확인 값**: BSD-3-Clause, Go, 별 약 24,400, 기여자 60, 최신 릴리스 v1.3.2(2026-08-29). Homebrew `age` stable 1.3.2. **이 머신 미설치**. `rage`(Rust 구현)도 미설치.
- **결정: 무시(범위 밖).** CONTEXT 턴2 는 NAS 암호화 백업용으로 age 를 제안했지만, 소유자 결정(2026-11-24)으로 NAS·원격 암호화 백업이 비목표가 되었고 02 §3 이 age 를 쓰지 않는다고 확정했다. 보관(`archive`)은 로컬/외장 폴더 이동뿐이다. 라이선스(BSD-3)는 MIT 와 호환되므로 나중에 범위가 바뀌면 외부 도구로 다시 검토할 수 있다.

---

## 3. CONTEXT 서술과 다른 점 (요약)

1. **Mole 의 `clean`/`purge`/`installer` 는 영구 삭제**이고 `mo clean` 은 기본으로 휴지통을 비운다. CONTEXT 는 “삭제 전 미리보기 가능” 만 언급해 안전 성격을 실제보다 좋게 보이게 한다. “설치 앱과 개발 환경 정리 부분은 Mole 을 활용해도 될 것 같다” 는 권고는 **채택하지 않는다**(§2.1).
2. agentic-mac-skills 는 스킬이 5개가 아니라 13개이고, 별 0·1인·이틀 활동의 초기 저장소다. 추천도 ★★★★★ 의 근거가 약하다.
3. Declutter 의 스크린샷 정리는 사진 스킬의 일부이며, 한국어 스크린샷 파일명을 인식하지 못하고 중복 판정이 부분 해시다.
4. Composio file-organizer 의 예시 명령은 macOS 에서 동작하지 않거나(`find -printf`) 의도대로 동작하지 않는다(`md5 | uniq -d`). 라이선스 파일이 없다.
5. Sortwise 는 파일명을 마스킹 없이 외부 AI 에 보낸다(CONTEXT 는 기능만 서술).
6. CONTEXT 턴0 결론 “Mole + Declutter + Agentic Mac Skills 를 참고해서 일일 정리 전용 Skill 을 직접 만들라” 중, 실제로 DayClose 알고리즘에 가장 많이 기여한 것은 목록 4번째의 **FileMorrow**(설치 파일·압축 파일 판정)였다.
7. 모든 저장소가 존재했다 — 찾지 못한 프로젝트는 없다. URL 도 모두 CONTEXT 에 적힌 그대로 유효했다.

---

## 4. 라이선스·코드 차용 규칙

DayClose 는 MIT 다. 규칙:

1. **기본은 재구현.** 위 프로젝트의 소스를 DayClose 저장소에 붙여 넣지 않고, 알고리즘·아이디어는 이 문서와 04/07 의 서술로부터 다시 작성한다(아이디어 자체는 저작권 대상이 아님). 이번 조사 결과로는 복사가 필요한 코드가 없다.
2. **GPL/AGPL(Mole, Sorty)**: 코드 조각·주석·정규식 목록 포함 어떤 텍스트도 복사 금지. 별도 프로세스로 실행하는 외부 도구로만 쓸 수 있고, 그 경우에도 02 §6 의 `run_tool` 허용 목록에 들어가야 한다(현재 GPL 도구는 없음). GPL 프로그램의 출력(JSON 등)을 읽는 것은 문제없다.
3. **MIT/BSD/Apache-2.0 코드**를 짧게라도 그대로 가져와야 하면:
   - 해당 파일 상단에 출처 주석: `# Derived from <repo URL> @ <commit SHA> (<SPDX>), Copyright (c) <holder>`.
   - 저장소 루트 `THIRD_PARTY_NOTICES.md` 에 프로젝트명·URL·커밋·라이선스 전문을 추가(첫 차용 시 파일 생성).
   - Apache-2.0 은 원본의 `NOTICE` 내용을 함께 싣고, 수정한 파일에 변경 사실을 표시.
   - 라이선스 파일로 확인되지 않는 소스(Composio file-organizer)는 복사하지 않는다.
4. **외부 도구 호출(gitleaks, git, brew)**: 코드 포함이 아니므로 DayClose 의 MIT 라이선스에 영향 없음. 앱 번들에 바이너리를 **동봉**하게 되면(M7 배포 결정, 09/12) 번들 안 `Resources/Licenses/` 에 해당 라이선스 고지를 포함하고, GPL 바이너리는 동봉하지 않는다(결정: 배포물 전체의 라이선스 판단을 단순하게 유지).
5. 새 런타임 의존성(라이브러리)은 02 §3 목록 변경으로만, 그 PR 에 SPDX 라이선스를 적는다(AGENTS.md). **GPL/AGPL 라이브러리는 의존성으로 추가하지 않는다**(파이썬 import 는 결합으로 본다). LGPL 은 개별 검토.

## 5. 02/다른 문서에 넘기는 제안 (이 문서는 수정하지 않음)

- 08: undo 불가 조건에 “외부 정리 도구(Mole `mo clean` 기본값 등)가 휴지통을 비운 경우” 와 사용자 안내 문구 추가.
- 05: gitleaks 호출 시 설정·ignore 파일 경로 고정(§2.10).
- 02 §3: 변경 없음. (`pkgutil`/`xar` 를 허용 목록에 넣지 않고 표준 라이브러리로 처리하기로 04 가 결정.)
