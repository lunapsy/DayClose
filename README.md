# DayClose

**End your day with a clean Mac.** — 오늘의 작업은 남기고, 오늘의 어지러움은 정리하세요.

DayClose 는 macOS 용 Digital Housekeeping Agent 입니다. 매일 하루 동안의 파일 변화(다운로드, 바탕화면, 스크린샷, 작업 문서, 설치 파일, 새 앱·패키지)를 결산해 결재함처럼 보여주고, 사용자가 승인한 것만 안전하게(휴지통·이동·보관, 되돌리기 가능) 정리합니다. 키·인증서 같은 보안 자산은 정리하지 않고 제자리에서 인벤토리·건강 점검만 합니다.

원칙: Local-first · AI optional · Human-in-the-loop · Reversible · Incremental · Privacy-first · Agent-ready.

## 상태

M0 — 명세 작성 단계. 아직 실행 가능한 코드는 없습니다. 다음 마일스톤은 M1(Python core 골격 + 파일 스냅샷·변경 감지 CLI). 진행 순서는 `docs/12-IMPLEMENTATION-ROADMAP.md`.

## 빌드·실행·테스트 (M1 이후)

요구 사항: macOS 26, Python ≥ 3.13, [`uv`](https://docs.astral.sh/uv/). 선택: `gitleaks`(보안 자산 내용 탐지 보조), Xcode(M4 앱).

```bash
cd core
uv sync
uv run pytest
uv run dayclose init --json
uv run dayclose scan run --json
uv run dayclose review summary --json     # M2~
```

개발·테스트는 반드시 샌드박스(`DAYCLOSE_HOME`, `DAYCLOSE_SANDBOX`)에서 합니다. 규칙은 `AGENTS.md`.

## 문서

| 문서 | 내용 |
|---|---|
| `CONTEXT.md` | 요구사항 원천 (기획 대화 원문) |
| `AGENTS.md` | 코딩 에이전트 작업 규칙·안전 규칙·완료 정의 |
| `docs/01-PRD.md` | 제품 정의, 페르소나, 기능 요구사항(FR-*), MVP, 미결 사항 |
| `docs/02-ARCHITECTURE.md` | 모듈 구조, CLI/JSON 계약, 오류 모델, 경로, 공유 계약 |
| `docs/03-UI-UX-SPEC.md` | 앱 화면·상호작용·단축키 |
| `docs/04-FILE-INTELLIGENCE.md` | 변경 감지, 분류, 그룹, 중복, 프로젝트 매칭 |
| `docs/05-SECURE-VAULT.md` | 보안 자산 탐지·마스킹·건강 점검·암호화 백업 |
| `docs/06-DATA-MODEL.md` | SQLite 스키마, enum, 상태 기계, 마이그레이션 |
| `docs/07-AI-MEMORY-POLICY.md` | 선호 학습, AI 공급자, 전송 게이트 |
| `docs/08-SAFE-EXECUTION.md` | 계획·승인·실행·undo·복구 |
| `docs/09-MACOS-INTEGRATION.md` | TCC/FDA, launchd, 알림, 메뉴바 |
| `docs/10-CLI-SKILL-MCP.md` | 명령 레퍼런스, stdio 서버, Skill, MCP |
| `docs/11-TEST-PLAN.md` | 테스트 전략·안전 회귀·장애 주입 |
| `docs/12-IMPLEMENTATION-ROADMAP.md` | 마일스톤 M0~M8 |
| `docs/13-OPEN-SOURCE-RESEARCH.md` | 유사 오픈소스·라이선스·재사용 판단 |
