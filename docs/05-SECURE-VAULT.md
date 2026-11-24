# 05 — Secure Vault (보안 자산 탐지·인벤토리·건강 점검)

> 범위: `core/src/dayclose/vault/` 모듈과, 그 결과를 쓰는 `policy`(보호 등급 판정)·`executor`(자산 차단)의 규칙 근거.
> 이름·enum·테이블·명령·오류 코드는 `02-ARCHITECTURE.md`, `06-DATA-MODEL.md` 를 그대로 쓴다. 이 문서는 그것들을 새로 만들지 않는다. 이 문서가 요청했던 기준 문서 변경의 반영 상태는 §19.2.
> 관련: 수집 파이프라인 순서·dataless 판정은 `04-FILE-INTELLIGENCE.md`, 실행 차단은 `08-SAFE-EXECUTION.md`, 민감도→AI 게이트는 `07-AI-MEMORY-POLICY.md`, 명령 `data` 스키마의 최종 레퍼런스는 `10-CLI-SKILL-MCP.md`, 픽스처·누출 스캐너는 `11-TEST-PLAN.md`.
> 마일스톤: 전부 M3(읽기 전용). 이 문서의 어떤 기능도 사용자 파일을 바꾸지 않는다(§16 에서 증명 방법을 정한다).

---

## 0. 원칙 (CONTEXT 턴2 §6 → 이 문서의 장치)

| CONTEXT 원칙 | 장치 |
|---|---|
| 키·인증 정보 원문은 외부 LLM 에 보내지 않는다 | 자산은 `sensitivity=secret` → `ai_policy=none`(06 §3.1). vault 는 원문을 어떤 구조체에도 담아 반환하지 않는다(§2.3 V3). |
| 일반 파일 정리와 보안 자산 정리의 실행 권한 분리 | `protection=security_asset` 의 `allowed_actions` 에 파괴적 동작 없음(02 §10.1). vault 에는 실행 코드가 없다. executor 는 자산 경로를 사전조건에서 다시 거부(§14, 08). |
| 사용 중인 키의 경로를 임의로 변경하지 않는다 | 제자리 인벤토리(§14). DayClose 는 자산에 `move` 를 제안하지도 실행하지도 않는다. |
| 암호화 백업은 복구 가능성을 검증한다 | 2026-11-24 소유자 결정으로 암호화 백업 자체가 비목표(§15). `backup_status` 는 사용자 표시로만. |
| 로그·SQLite·썸네일 캐시에 비밀이 남지 않는다 | 저장 금지 목록(§2.3), 매치 문자열 비저장, 키 지문은 공개키 기반·파일 지문은 키 입력 HMAC(§7), 누출 경로 표(§17). |
| 개인키와 복구 구문은 일반 휴지통 일괄 이동에서도 제외 | 그룹 결정에서 제외(02 §10.1) + plan.create 거부 + executor 디렉터리 내부 검사(08 §7.2.1). |
| Git 에 노출된 키는 삭제가 아닌 폐기·재발급 권고 | `tracked_in_git` 문구와 동작 제안 `acknowledge` 고정(§9.4). |
| 지갑 시드·복구 구문은 Vault 에 수집하지 않는다 | `crypto_seed_suspected`: 존재·위치만, 어떤 파생값도 없음(§13). |

결정: Keychain 항목은 인벤토리하지 않는다. 이유: Keychain 읽기는 사용자 확인 대화상자를 띄우고(ACL), Keychain 은 이미 보호된 저장소이므로 “흩어진 파일”이라는 이 기능의 문제 정의에 해당하지 않는다. CONTEXT 턴2 §3 그림의 “Keychain” 가지는 “여기로 옮기라고 권고할 수 있는 장소”로만 문구에 등장한다.

---

## 1. 위협 모델과 불변식

다루는 위협:
1. DayClose 자신이 비밀을 새는 것(로그, DB, stdout 봉투, 리포트, 썸네일, AI 페이로드, 예외 메시지, 서브프로세스 인자).
2. DayClose 가 키를 옮기거나 지워 서비스가 멈추는 것.
3. 흩어진 키를 사용자가 모르는 것(노출 위치, Git 추적, 만료, 중복, 권한, 백업 없음).

다루지 않는 위협(범위 밖, §19 남은 위험): 같은 사용자 권한으로 임의 코드를 실행하는 적대적 프로세스(그것은 DayClose 없이도 파일을 읽는다), 디스크 도난(FileVault 담당), 메모리 덤프·스왑.

불변식(테스트로 고정 — 11 문서의 안전 스위트):

| ID | 불변식 |
|---|---|
| V1 | vault 는 사용자 파일을 쓰기·이름변경·삭제·권한변경·xattr 쓰기 하지 않는다. 열기는 항상 `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`. |
| V2 | dataless(`st_flags & SF_DATALESS`) 와 `.<이름>.icloud` 자리표시자는 열지 않는다(02 §10.6). 이름·위치 신호만 쓴다. |
| V3 | 파일 내용(바이트·문자열)은 vault 내부 함수의 지역 변수를 벗어나지 않는다. 함수 경계 밖으로 나가는 값은 §2.3 의 “반환 허용 값”뿐이다. |
| V4 | 비밀값, 매치 문자열, gitleaks `Match`/`Secret`, 줄 내용, 개인키, 시드 단어는 DB·로그·봉투·리포트·예외 메시지 어디에도 기록되지 않는다. |
| V5 | `crypto_seed_suspected` 는 경로·종류·마스킹 이름·탐지 방법·시각 외 어떤 값도 갖지 않는다(지문·해시·줄 번호 포함 금지). |
| V6 | 보안 자산의 실제 경로·원래 파일명은 로그·리포트·`vault.list`/`vault.health` 에 나가지 않는다(`asset_id`, 마스킹 이름만). 실제 값은 `vault.show`/`item.show` 와 02 §5.6 계약의 항목 `path` 에만, 그것도 `skill`/`mcp` 채널에서는 null(§10.3, §11.5). |
| V7 | 보안 자산(활성 `vault_assets` 행이 가리키는 엔트리)은 `trash`/`move`/`archive`/`rename` 연산의 대상이 될 수 없다. 자산을 포함하는 디렉터리도 마찬가지. |
| V8 | M3~M4 빌드에는 사용자 파일을 변경하는 코드 경로가 존재하지 않는다(§16). |

---

## 2. 스캔 대상과 후보 선정

vault 는 `scan.run` 의 `phase=vault` 단계로 실행된다(04 §0 의 4단계: fs → git → **vault** → apps… → intel). 입력은 이번 run 에서 fs 수집기가 기록한 엔트리 변화와, 시간에 따라 바뀌는 조건(만료·Git 추적·권한)을 다시 보기 위한 기존 자산 목록이다.

### 2.1 루트

| 대상 | 등록 방식 | 항목 생성 | 비고 |
|---|---|---|---|
| `file_level=1` 루트(`downloads`, `desktop`, `screenshots`, `documents`, `icloud_drive`, `custom`) | 04 §1.1 | 새 자산이면 `vault:new` 항목(§8.3) | 내용 검사 클래스 A·B·C·D 전부 |
| `projects` 루트(`file_level=0`) | 04 §1.1 | 새 자산이면 항목(§8.3) | 클래스 A(이름·확장자·구조)만. 결정: 저장소 소스 전체의 내용 검사는 하지 않는다. 이유: 수만 개 소스 파일·테스트 픽스처의 오탐, 그리고 그것은 저장소 자체의 CI(gitleaks git)가 할 일. `.env`·키 파일은 이름으로 잡힌다. |
| `vault_extra` 루트 | 아래 2.1.1 | 새 자산이면 항목(§8.3) | 클래스 A·B(위치 기반 전수 검사) |
| 잘 알려진 단일 파일(2.1.2) | 루트 아님 | 새 자산이면 항목 | 클래스 B |

#### 2.1.1 `vault_extra` 루트 등록

- `core.init` 과 매 `scan.run` 시작 시 `config.vault.extra_paths` 를 동기화한다: 각 항목을 `~` 확장 → `os.path.realpath` 하지 **않고**(사용자가 적은 경로 그대로) `lstat` 해서 디렉터리이면 `scan_roots(kind='vault_extra', file_level=0, max_depth=4)` 로 등록(이미 있으면 그대로), 없으면 등록하지 않고 경고 없음(대부분의 사람은 `~/.kube` 등이 없다). 설정에서 빠진 경로의 루트는 `removed_at` 설정.
- 기본값(02 §9): `~/.ssh`, `~/.aws`, `~/.azure`, `~/.docker`, `~/.config/gh`, `~/.config/gcloud`, `~/.kube`, `~/.gnupg`, `~/Library/Preferences/NPKI`.
- `scan.exclude_globs` 의 `**/Library/**` 는 **루트 기준 상대경로**에 매칭된다(02 §9 주석). 따라서 루트 자체가 `~/Library/Preferences/NPKI` 인 경우 그 아래는 제외되지 않는다. 이 성질에 의존한다 — 04 가 glob 기준을 바꾸면 이 루트가 깨진다(11 문서의 회귀 테스트 `test_npki_root_not_excluded`).
- `vault_extra` 루트 순회에서도 `**/.git/**` 제외는 유지한다.

#### 2.1.2 잘 알려진 단일 파일

홈 디렉터리 바로 아래 파일들은 어떤 루트에도 속하지 않는다. vault 는 아래 고정 목록을 매 run 마다 `lstat` 하고(디렉터리 순회 없음), 존재하는 일반 파일만 검사한다. 이 경로들의 자산은 `entry_id = NULL`(06: `vault_assets.entry_id` nullable)이고 경로로 식별한다.

`~/.netrc`, `~/.git-credentials`, `~/.npmrc`, `~/.pypirc`, `~/.pgpass`, `~/.my.cnf`, `~/.mylogin.cnf`, `~/.android/debug.keystore`, `~/.gradle/gradle.properties`, `~/.config/solana/id.json`.

(`~/.azure`, `~/.docker`, `~/.config/gh` 는 02 §9 의 `extra_paths` 기본값이라 `vault_extra` 루트로 들어온다 — 이 목록에 넣지 않는다.)

결정: 이 목록은 설정이 아니라 코드 상수(`vault/locations.py`)다. 이유: 사용자가 비울 이유가 없고, 디렉터리가 아닌 단일 파일이라 `scan_roots` 로 표현할 수 없다.

### 2.2 후보 클래스

이번 run 의 엔트리 변화(`created`, `modified`, `moved`)와 기준선 엔트리에 대해, 아래 중 하나라도 해당하면 “후보”다. 후보가 아닌 파일은 vault 가 읽지 않는다.

| 클래스 | 조건 | 읽는 양 |
|---|---|---|
| A — 이름·확장자 | §3 표의 이름/확장자 신호에 일치 | 종류별 상한(§3) |
| B — 위치 | `vault_extra` 루트 안이거나 §2.1.2 목록 | `content_scan_max_bytes`(기본 1 MiB) 이하 일반 파일 전부 |
| C — 일반 내용 | `file_level=1` 루트의 `created`/`modified` 엔트리 중 텍스트로 보이는 파일(아래) | `content_scan_max_bytes` |
| D — 확장자 없음 | `file_level=1` 루트의 확장자 없는 일반 파일(크기 ≤ 64 KiB) | 앞 4 KiB(헤더 검사만) — 헤더가 일치하면 클래스 A 처리로 승격 |

클래스 C 의 “텍스트로 보이는 파일”: `ext ∈ {txt, md, markdown, rtf(일반 텍스트 부분만이 아니라 전체 바이트를 텍스트로 검사), json, jsonc, yaml, yml, toml, ini, cfg, conf, cnf, properties, csv, tsv, log, xml, plist(XML 일 때만), sh, bash, zsh, fish, ps1, py, js, mjs, cjs, ts, rb, go, java, kt, swift, php, sql, env, tf, tfvars, hcl}` 이고, 앞 8 KiB 에 NUL 바이트가 없고 UTF-8(오류 시 `surrogateescape`)로 디코드 가능한 것. PDF·Office·이미지·압축 파일은 클래스 C 가 아니다(이미지 속 비밀은 M6 OCR 이 07 문서의 민감도 경로로 처리).

기준선(04 §3.4, 첫 순회) 규칙: 기준선 run 에서는 클래스 A·B·D 만 수행하고 클래스 C 는 하지 않는다. 결정: 설치 첫날 `~/Documents` 의 수만 개 텍스트 파일을 내용 검사하지 않는다. 이유: 수 분 이상 걸리고, 과거 누적분 전수 정리는 비목표(PRD §7). 이후 run 에서는 변경분만 클래스 C 대상이 된다. 사용자가 전수 검사를 원하는 경우는 M3 범위 밖(§19 열린 질문).

### 2.3 안전한 읽기와 반환 허용 값

모든 읽기는 `vault/io.py` 의 함수 하나 `read_bounded(path, max_bytes, expect: Stat) -> bytes | Skip` 로만 한다.

1. `st = os.lstat(path)`. 일반 파일(`S_ISREG`)이 아니면 `Skip('not_regular')`. 심볼릭 링크는 따라가지 않는다.
2. `st.st_flags & SF_DATALESS` 또는 이름이 `.*.icloud` → `Skip('dataless')`, 경고 집계 `W_DATALESS_SKIPPED`.
3. `st.st_size > max_bytes` → `Skip('too_large')`(종류별 처리: §3 의 “크기 초과 시” 열).
4. `fd = os.open(path, O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC)`. `ELOOP`(경로가 그 사이 링크로 바뀜) → `Skip('changed')`. `EPERM` → `Skip('tcc')`(`W_TCC_DENIED`), `EACCES` → `Skip('perm')`(`W_PERMISSION_SKIPPED`).
5. `fst = os.fstat(fd)`. `(st_dev, st_ino) != (st.st_dev, st.st_ino)` 또는 `S_ISREG` 아님 → 닫고 `Skip('changed')`. (FIFO·장치 파일을 열어 멈추는 것을 막는 2중 방어 — `O_NONBLOCK` 가 1차.)
6. `max_bytes+1` 까지 읽는다. 읽은 양이 `max_bytes` 초과면 `Skip('too_large')`.
7. 다시 `fstat` — `st_mtime_ns` 또는 크기가 바뀌었으면 `Skip('changed')`(쓰는 중인 파일).
8. 닫는다. 바이트를 반환한다.

`read_bounded` 는 바이트를 받은 호출자 함수(§3·§4·§6 의 판정 함수) 안에서만 쓰인다. 판정 함수가 반환할 수 있는 값(**반환 허용 값**)은 다음으로 한정한다. 타입으로 강제(`vault/types.py` 의 `Detection`, `CertMeta`, `KeyMeta`, `PatternHit` 데이터클래스 — 문자열 필드는 아래 목록의 것만 존재).

- 자산 종류, 탐지 방법 목록, confidence
- 규칙 ID(`dc.*` 또는 `gitleaks:<RuleID>`), 줄 번호(정수, 시드 제외)
- 인증서: `not_before`, `not_after`(정수 ms), issuer 요약(§6.1), subject(암호화 저장용, §6.1), 인증서 개수, 자체 서명 여부
- 공개키 지문(SPKI SHA-256 hex), 키 알고리즘 이름(`rsa`/`ec-p256`/`ed25519`…), 키 비트 수
- `needs_password` 불리언
- 파일 지문(§7.1 의 HMAC hex)
- 개수 값(예: env 변수 개수) — 저장하지 않으면 반환하지도 않는다(현재 저장 컬럼 없음 → 반환 안 함)

예외 처리 규칙(V4 의 핵심, 실제 누출 경로):
- 판정 함수 안의 모든 파서 호출(`cryptography`, `json`, `plistlib`, `int()`, 정규식, DER 파서)은 `try/except Exception` 으로 감싸고, 실패는 고정 사유 코드(`parse_failed` 등)로만 바꾼다. **`str(e)`·`repr(e)` 를 로그·반환값에 쓰지 않는다.** 예: `int('sk_live_…')` 의 `ValueError` 메시지에는 입력 문자열이 그대로 들어간다. `json.JSONDecodeError.doc` 에는 문서 전체가 들어 있다.
- 다시 던질 때는 `raise VaultParseError(code) from None`(예외 체인 `__context__` 로 원래 메시지가 트레이스백에 찍히는 것을 끊는다).
- vault 모듈 최상위에서 잡히지 않은 예외는 `E_INTERNAL` 이 되기 전에 `vault.run` 경계에서 잡아 해당 엔트리를 `Skip('internal')` 로 처리하고 계속한다. 트레이스백은 로그에 남기되 프레임 지역 변수는 출력하지 않는다(표준 `logging` 의 기본 동작. `rich`/`better_exceptions` 같은 지역 변수 출력 라이브러리 도입 금지).

### 2.4 예산과 백로그

한 run 의 vault 내용 검사 예산: 파일 5,000개 또는 읽기 200 MiB, gitleaks 호출 500회(§5). 초과분은 처리하지 않고 `W_TRUNCATED`(details `{"phase":"vault","deferred":N}`) 를 내고, 엔트리 ID 를 `app_meta` 키 `vault.backlog_entry_ids`(JSON 배열, 최대 20,000개, 초과 시 오래된 것부터 버림)에 넣어 다음 run 에서 먼저 처리한다. 결정: 백로그를 위해 새 컬럼을 만들지 않는다(06 변경 회피). 이유: 일일 델타는 수십~수백 개라 백로그는 드문 경우.

---

## 3. 자산 종류별 탐지 규칙

표기: **신호** = 후보가 되는 이름·확장자·위치(대소문자 무시, `ext` 는 06 의 소문자 확장자). **검증** = 확장자를 믿지 않고 내용으로 확인하는 방법. 검증이 실패하면 그 종류가 아니다(다른 종류 또는 비자산으로 계속 판정). **메타데이터** = 저장할 수 있는 값(§2.3 반환 허용 값의 부분집합)과 대상 컬럼. **저장 금지** = 그 종류에서 특히 주의할 것.

PEM 헤더 정규식(바이트, 줄 시작 기준, 파일 어디에 있어도 됨):
`^-----BEGIN (?P<label>[A-Z0-9 ]{1,40})-----\r?$` — 라벨로 분기한다.

### 3.1 `certificate` — X.509 인증서

- 신호: `ext ∈ {pem, cer, crt, der, p7b, p7c, spc}`. 클래스 D 의 PEM 헤더 `CERTIFICATE`/`PKCS7`.
- 크기 상한: 1 MiB. 초과 → 비자산(인증서 번들 아님 판단 불가 → 무시).
- 검증(순서대로, 첫 성공):
  1. PEM 라벨 `CERTIFICATE`/`TRUSTED CERTIFICATE` → `cryptography.x509.load_pem_x509_certificates(data)`.
  2. PEM 라벨 `PKCS7` 또는 DER `ext ∈ {p7b,p7c,spc}` → `cryptography.hazmat.primitives.serialization.pkcs7.load_pem_pkcs7_certificates` / `load_der_pkcs7_certificates`.
  3. 첫 바이트 `0x30` → `x509.load_der_x509_certificate(data)`.
- 같은 파일에 개인키 PEM 라벨(§3.2)이 있으면 종류는 `private_key`(§3.2)이고 인증서 메타데이터도 함께 저장.
- 비자산 예외: 인증서가 3개 이상이고 개인키가 없는 파일(CA 번들 — `cacert.pem`, `certifi`), 그리고 경로에 `/site-packages/`, `/.venv/`, `/venv/`, `/vendor/`, `/node_modules/`, `/.cargo/registry/` 가 있는 공개 인증서. 이유: 공개 데이터이고 수백 개의 오탐.
- Apple 개발자 인증서 판정: 잎 인증서의 issuer CN 이 `Apple Worldwide Developer Relations Certification Authority` 또는 `Developer ID Certification Authority` 로 시작하거나 subject CN 이 `Apple Development:`/`Apple Distribution:`/`iPhone Developer:`/`iPhone Distribution:`/`Developer ID Application:`/`Developer ID Installer:`/`Mac Developer:`/`3rd Party Mac Developer` 로 시작 → 종류 `apple_signing`.
- 메타데이터: 첫 인증서(잎)의 `not_before`/`not_after` → `cert_not_before`/`cert_not_after`(epoch **ms** UTC — 결정: 06 의 `*_at` 과 같은 단위), `expiry_source='file'`, issuer 요약 → `cert_issuer`, subject → `cert_subject_enc`, SPKI 지문 → `key_fingerprint`(인증서의 공개키. 같은 키의 개인키 파일과 짝을 맺는 데 씀).
- 저장 금지: 없음(공개 데이터)이지만 subject 에 실명·이메일이 있을 수 있어 암호화 컬럼에만.

### 3.2 `private_key` — 일반 개인키

- 신호: `ext ∈ {key, pem, pkcs8, pk8, p8(Apple 판정 실패 시), ppk, asc, gpg}`, GPG `private-keys-v1.d/*.key`, `secring.gpg`, 클래스 D 의 PEM 라벨.
- 크기 상한: 256 KiB.
- 검증(하나라도):
  - PEM 라벨 ∈ {`PRIVATE KEY`, `RSA PRIVATE KEY`, `EC PRIVATE KEY`, `DSA PRIVATE KEY`, `ENCRYPTED PRIVATE KEY`} (`OPENSSH PRIVATE KEY` 는 §3.3).
  - 라벨 `PGP PRIVATE KEY BLOCK`.
  - PuTTY: 첫 줄이 `PuTTY-User-Key-File-2:` 또는 `PuTTY-User-Key-File-3:` → 종류는 `ssh_private_key`(§3.3).
  - GPG keybox 개인키: 내용이 `(private-key` 또는 `Key: (protected-private-key` 로 시작하는 S-식 / `Created:` 헤더가 있는 확장 키 형식.
  - DER: 첫 바이트 `0x30` 이고 `serialization.load_der_private_key(data, None)` 성공, 또는 `TypeError`(암호 필요) → 암호화된 PKCS#8.
- `.key` 확장자 함정: Keynote 문서는 패키지 디렉터리(04 가 `kind='package'`, `document`)이거나 ZIP(`PK\x03\x04`)이다 → 검증 실패 → 비자산. 검증에 통과하지 못한 `.key` 는 절대 자산으로 만들지 않는다.
- 메타데이터:
  - 암호 없는 PEM/DER: `load_pem_private_key(data, None)` → `.public_key()` → SPKI 지문, 알고리즘·비트. 개인키 객체는 즉시 버린다(`del`). `needs_password=0`.
  - `ENCRYPTED PRIVATE KEY`, `Proc-Type: 4,ENCRYPTED` 헤더, 로드 시 `TypeError` → `needs_password=1`, 키 지문은 같은 디렉터리의 짝 파일(같은 stem 의 `.pub`, `.crt`, `.cer`, `.pem` 인증서)에서 얻을 수 있으면 그 공개키 지문, 없으면 NULL.
  - 암호 추측 금지: 빈 암호(`b""`)를 포함해 어떤 암호도 시도하지 않는다(PKCS#12 §3.4 의 빈 암호 시도는 예외 — 이유는 거기에).
- 저장 금지: 개인키 바이트·파생값(공개키 지문 제외).

### 3.3 `ssh_private_key`, `ssh_config`

- 신호(`ssh_private_key`): 이름 `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`, `id_ecdsa_sk`, `id_ed25519_sk`, `identity`, 그리고 `~/.ssh` 아래의 `.pub` 가 아닌 모든 일반 파일(클래스 B), `ext=ppk`, 클래스 D.
- 크기 상한: 64 KiB.
- 검증: PEM 라벨 `OPENSSH PRIVATE KEY`, 또는 §3.2 의 PEM 개인키 라벨(구형 `id_rsa`), 또는 PuTTY 헤더.
- 메타데이터(OpenSSH 형식): base64 본문을 디코드해 `openssh-key-v1\0` 매직 확인 → `string ciphername`, `string kdfname`, `string kdfoptions`, `uint32 N`, `string publickey[0]` 순서로 읽는다. **공개키 블롭은 암호화되어 있지 않으므로** 암호가 걸린 키도 공개키 지문을 얻는다. `ciphername != "none"` → `needs_password=1`. 공개키 블롭 → `serialization.load_ssh_public_key(b"<type> " + base64(blob))` → SPKI DER → `key_fingerprint`. 개인키 부분(암호화 여부와 무관)은 파싱하지 않는다. 길이 필드가 남은 바이트를 넘으면 `parse_failed` → 종류는 유지(헤더로 확인됨), 지문 NULL.
- PuTTY: `Public-Lines:` 다음 base64 블롭이 SSH 공개키 블롭 → 같은 방법. `Encryption: none` 이 아니면 `needs_password=1`.
- `.pub` 파일은 자산이 아니다(공개). 단 짝 지문 조회(§3.2)에는 읽을 수 있다(64 KiB 이하, 한 줄 `<type> <base64> [comment]` — comment 는 버린다).
- 신호(`ssh_config`): `~/.ssh/config`, `~/.ssh/config.d/*`, `~/.ssh/*.conf`. 검증: 줄 단위 `^\s*(Host|Match|Include|IdentityFile|HostName|ProxyJump|User)\s` 가 1줄 이상. 메타데이터: 없음(지문만). 결정: 호스트 이름·`IdentityFile` 경로는 저장하지 않는다(인프라 지도).
- 저장 금지: SSH 키 comment(보통 `user@host`), 호스트 목록.

### 3.4 `pkcs12` — `.p12` / `.pfx`

- 신호: `ext ∈ {p12, pfx}`, 그리고 `ext ∈ {keystore, jks, bks}` 중 DER 로 시작하는 파일(§3.8 이 PKCS#12 형식 keystore 를 여기로 넘김).
- 크기 상한: 1 MiB.
- 검증: 첫 바이트 `0x30`, 그리고 DER 최상위 SEQUENCE 안 첫 원소가 INTEGER 3(버전, 바이트 `02 01 03`). (실측: openssl 로 만든 `.p12` 는 `30 82 xx xx 02 01 03 30 82 …` 로 시작.)
- 메타데이터 — `cryptography.hazmat.primitives.serialization.pkcs12.load_key_and_certificates(data, password)` 를 **`None` 다음 `b""` 로 두 번만** 시도한다:
  - 성공 → `needs_password=0`. 잎 인증서(키와 공개키가 같은 인증서, 없으면 첫 인증서)로 §3.1 메타데이터, 키의 SPKI 지문 → `key_fingerprint`. 키 객체는 즉시 버린다.
  - 둘 다 `ValueError` → `needs_password=1`, 인증서 메타데이터 NULL, `expiry_source='unknown'`. 표시 문구 “만료일 미확인(암호 필요)”(FR-SV-005).
  - 결정: 빈 암호 시도는 허용한다. 이유: macOS·Java 도구가 빈 암호 `.p12` 를 흔히 만들고, 빈 암호는 추측이 아니라 “암호 없음” 확인이다. 그 외 암호는 받지도 시도하지도 않는다(사용자에게 암호를 입력받는 기능도 만들지 않는다 — DayClose 가 비밀번호를 다루는 순간 비밀 관리자가 된다, PRD §7).
- 실측 근거(2026-11-24, 이 머신, OpenSSL 4.1.0 / cryptography 49.0.0, 임시 픽스처): 암호 걸린 `.p12` 는 인증서 가방을 암호화하지 않은 경우(`-certpbe NONE`)에도 `cryptography` 로는 MAC 검증 때문에 읽히지 않는다. `openssl pkcs12 -nokeys -nomacver -passin pass:` 는 이 경우 인증서를 출력하지만, 기본값(인증서 가방 PBES2/AES-256 암호화)과 `-legacy`(RC2) 파일은 openssl 로도 암호 없이 읽을 수 없다. 결정: openssl CLI 는 쓰지 않는다(02 §3: X.509 파싱은 `cryptography`, `openssl` 은 `run_tool` 허용 목록에 없음). 비암호화 인증서 가방만 있는 드문 경우를 위해 자체 DER 파서를 넣는 것은 M3 범위 밖(§19).
- Apple 판정: 잎 인증서가 §3.1 의 Apple 조건이면 종류 `apple_signing`.
- 저장 금지: 암호, 개인키 파생값(공개키 지문 제외).

### 3.5 `env_file` — `.env` 계열

- 신호(이름 정규식, 대소문자 무시): `^\.env$`, `^\.env\.[A-Za-z0-9_.-]+$`, `^[A-Za-z0-9_.-]+\.env$`, `^\.envrc$`, `^\.flaskenv$`.
- 예시 파일: `.env.example`, `.env.sample`, `.env.template`, `.env.dist`, `.env.defaults` 는 **신호에는 일치하지만** 검증 2단계에서 비밀로 보이는 값이 없으면 비자산.
- 크기 상한: 256 KiB.
- 검증:
  1. 줄의 50% 이상(빈 줄·주석 `#` 제외)이 `^\s*(export\s+)?[A-Za-z_][A-Za-z0-9_.]*\s*[=:]` 형태. 아니면 비자산.
  2. 예시 파일이면: §4 내부 패턴 또는 gitleaks 가 1건 이상일 때만 자산. 일반 `.env*` 는 1단계만으로 자산.
- 메타데이터: 없음(지문, Git 상태, 권한만). 결정: 변수 이름 목록도 저장하지 않는다. 이유: 저장 컬럼이 없고(06), 이름(`STRIPE_SECRET_KEY`)만으로도 사용 서비스 지도가 된다.
- `.env` 안의 비밀 패턴 적중은 `plaintext_secret` 발견 사항을 만들지 않는다(비밀이 있는 것이 정상인 파일). 대신 gitleaks/내부 패턴 규칙 ID 는 Git 추적 판정의 심각도 계산에 쓰지 않는다 — `.env` 는 그 자체로 비밀 보유 종류(§9.1).
- 저장 금지: 값, 변수 이름.

### 3.6 `cloud_credential` — AWS / GCP / Azure / Firebase / Kubernetes

| 하위 유형 | 신호 | 검증 |
|---|---|---|
| AWS 자격 파일 | `~/.aws/credentials`, `~/.aws/config`, 이름 `credentials` 가 `.aws` 디렉터리 안 | INI 섹션 `[...]` + 키 `aws_access_key_id` 또는 `aws_secret_access_key` 또는 `aws_session_token`. `config` 는 이 키가 있을 때만 자산(SSO 설정만 있으면 비자산) |
| AWS 콘솔 CSV | 이름 `*accessKeys*.csv`, `credentials.csv` | 첫 줄에 `Access key ID` 와 `Secret access key` |
| GCP 서비스 계정 | 모든 `.json`(클래스 A: 이름에 `service-account`, `serviceaccount`, `-sa-`, `firebase-adminsdk`, `credentials`, `gcp`, `gcloud`; 클래스 B·C: 전부) | JSON 객체, `type == "service_account"` 이고 `private_key` 와 `client_email` 키 존재 |
| GCP 사용자 자격 | `~/.config/gcloud/application_default_credentials.json`, `legacy_credentials/*/adc.json`, `credentials.db`, `access_tokens.db` | JSON: `type ∈ {"authorized_user","external_account","impersonated_service_account"}` + `refresh_token`/`credential_source`. `.db`: 앞 16바이트 `SQLite format 3\0` (SQLite 파일은 열지 않는다 — 헤더 바이트만) |
| Firebase Admin | GCP 서비스 계정과 같음(`client_email` 이 `firebase-adminsdk` 포함이면 표시 종류 문구만 “Firebase Admin”) | 같음 |
| Azure | `~/.azure`(`vault_extra`) 안의 `accessTokens.json`, `msal_token_cache.json`, `msal_token_cache.bin`, 서비스 주체 JSON | 토큰 캐시: JSON 이고 `AccessToken`/`RefreshToken` 최상위 키(또는 `.bin` 은 이름만, confidence 0.7). 서비스 주체: JSON 에 `appId`·`tenant`·(`password` 또는 `clientSecret`) |
| Kubernetes | `~/.kube/config`, `kubeconfig*`, `*.kubeconfig` | YAML 텍스트에 `^\s*(client-key-data|token|client-certificate-data|password)\s*:` 가 있음. `apiVersion`/`clusters:` 만 있고 위 키가 없으면 비자산 |

- 크기 상한: 1 MiB(`.db` 는 헤더 16바이트만 읽음).
- 비자산 예외(결정): `google-services.json`, `GoogleService-Info.plist` — Firebase **클라이언트** 설정. 포함된 API 키는 공개 배포를 전제로 한 식별자라 자산으로 만들지 않고, 이 두 이름의 파일에서 나온 `gitleaks:gcp-api-key` / `dc.google_api_key` 적중은 버린다. 이유: 거의 모든 모바일 저장소가 이 파일을 커밋하고, 경고 피로가 실제 경고를 묻는다.
- 메타데이터: 없음. GCP 서비스 계정의 `client_email`·`project_id` 는 저장하지 않는다(결정: 컬럼이 없고 계정 식별자). 서비스 계정 JSON 의 `private_key` 는 PEM 이므로 공개키 지문을 낼 수 있다: JSON 파싱 → `private_key` 문자열 → `load_pem_private_key` → SPKI 지문 → `key_fingerprint`(같은 키 JSON 의 복사본을 중복으로 잡기 위함). 키 객체·문자열은 즉시 버린다.

### 3.7 `apple_signing` — Apple 개발자 자산

| 하위 유형 | 신호 | 검증 | 메타데이터 |
|---|---|---|---|
| App Store Connect / APNs / 기타 API 키 | `ext=p8`, 이름 `AuthKey_*.p8`, `ApiKey_*.p8`, `SubscriptionKey_*.p8` | PEM 라벨 `PRIVATE KEY`, 로드한 키가 EC P-256 | SPKI 지문. 만료 없음(`expiry_source='unknown'` — Apple 키는 만료되지 않음, 사용자 표시로 덮어쓸 수 있음) |
| 프로비저닝 프로파일 | `ext ∈ {mobileprovision, provisionprofile}` | 첫 바이트 `0x30`, 그리고 바이트열에 `<?xml` … `</plist>` 가 있음 | `<?xml` 부터 첫 `</plist>` 끝까지 잘라 `plistlib.loads` → `ExpirationDate` → `cert_not_after`, `CreationDate` → `cert_not_before`, `expiry_source='file'`. `Name`·`TeamIdentifier[0]` 는 `cert_subject_enc` 에 JSON `{"profile":…, "team":…}` 로 암호화 저장(결정: 별도 컬럼 없이 subject 칸 재사용). `cert_issuer='Apple Provisioning Profile'` 고정. CMS 서명은 검증하지 않는다(메타데이터 용도) |
| 개발자 인증서 | §3.1 Apple 조건의 `.cer`/`.pem`/`.p12` | §3.1/§3.4 | §3.1 |
| 인증서 서명 요청 | `ext=certSigningRequest` | — | 자산 아님(공개 데이터) |

- `.p8` 이 EC P-256 이 아니면 `private_key`.
- 저장 금지: 프로파일의 `Entitlements`, `ProvisionedDevices`(기기 UDID 목록), `DeveloperCertificates` 본문.

### 3.8 `android_keystore`

| 하위 유형 | 신호 | 검증 |
|---|---|---|
| JKS | `ext ∈ {jks, keystore}` | 매직 `FE ED FE ED` |
| JCEKS | `ext ∈ {jceks, keystore}` | 매직 `CE CE CE CE` |
| PKCS#12 keystore | `ext ∈ {jks, keystore, p12}` | §3.4 검증 → 종류 판정은 이 표(이름이 keystore 계열이면 `android_keystore`) |
| BKS | `ext=bks` | 앞 4바이트 big-endian 버전 1 또는 2 (약한 검증, confidence 0.7) |
| 서명 설정 | 이름 `key.properties`, `keystore.properties`, `signing.properties`, `~/.gradle/gradle.properties` | `^\s*(storePassword|keyPassword|storeFile|keyAlias|[A-Za-z_.]*(STORE|KEY)_PASSWORD)\s*=` 가 1줄 이상. `gradle.properties` 는 `*PASSWORD*=` 키가 있을 때만 |

- 크기 상한: 1 MiB.
- JKS/JCEKS 메타데이터(암호 없이): JKS 형식은 인증서 체인을 **암호화하지 않고** 저장한다. `vault/jks.py` 의 제한 파서: 매직, 버전(1|2), 항목 수(≤ 64), 각 항목 태그(1=PrivateKeyEntry, 2=TrustedCertEntry, 3=SecretKeyEntry(JCEKS)), alias(UTF, **버린다**), timestamp, PrivateKeyEntry 는 보호된 키 길이만큼 건너뛰고 체인 길이(≤ 10) → 각 인증서 type 문자열 + DER 길이(≤ 64 KiB) + DER. 첫 PrivateKeyEntry 의 첫 인증서 → §3.1 메타데이터(만료, issuer, subject 암호화) + SPKI 지문(그 키의 공개키). 무결성 해시(끝 20바이트, 암호 기반)는 검증하지 않는다. 어떤 길이 필드라도 남은 바이트를 넘으면 `parse_failed`, 종류는 유지, 메타데이터 NULL. `needs_password` 는 1(키 자체는 항상 암호 보호).
- `debug.keystore`(이름 일치) → 종류는 `android_keystore` 이지만 `no_backup`·`exposed_location` 발견 사항을 만들지 않는다(결정: 재생성 가능한 디버그 키, 알려진 기본 암호).
- 저장 금지: alias, 암호, `key.properties` 의 값.

### 3.9 `vpn_config`

| 하위 유형 | 신호 | 검증 |
|---|---|---|
| OpenVPN | `ext=ovpn`, `ext=conf` 이면서 내용 확인 | 줄 `^\s*(client|remote\s|dev\s+tun|<ca>|<cert>|<key>|<tls-auth>|<tls-crypt>)` 2개 이상 |
| WireGuard | `ext=conf`, 경로에 `wireguard`/`wg` 포함 또는 이름 `wg*.conf` | `[Interface]` 섹션과 `^\s*PrivateKey\s*=` |
| Tunnelblick | 패키지 `*.tblk` | 이름만(confidence 0.7). 패키지 내부 `.ovpn` 은 별도 후보 |
| 구성 프로파일 | `ext=mobileconfig` | XML plist(또는 CMS 안의 plist, §3.7 과 같은 추출)에서 `PayloadType` 이 `com.apple.vpn.managed` 또는 `com.apple.wifi.managed` 이고 `Password`/`SharedSecret`/`PrivateKey` 류 키가 있음 |

- 크기 상한: 256 KiB.
- 메타데이터: 없음. `remote` 호스트·포트는 저장하지 않는다.
- OpenVPN 인라인 `<key>` 가 있거나 WireGuard `PrivateKey` 가 있으면 “개인키 보유”(§9.1 의 비밀 보유 종류 판정에 씀). 인라인 `<cert>` 블록은 §3.1 로 만료를 읽는다(첫 인증서).

### 3.10 `crypto_wallet`

| 하위 유형 | 신호 | 검증 |
|---|---|---|
| Ethereum keystore V3 | 이름 `UTC--*--*`, `*.json`(클래스 A: 이름에 `keystore`/`wallet`; B·C 전부) | JSON 객체, `version == 3`, `crypto`(또는 `Crypto`) 안에 `cipher`, `ciphertext`, `kdf`, `mac` |
| Solana | `~/.config/solana/id.json`, `*keypair*.json` | JSON 배열, 길이 64, 모든 원소 0~255 정수 → **평문 개인키** |
| Bitcoin Core | 이름 `wallet.dat` | Berkeley DB: 오프셋 12 의 4바이트가 `00 05 31 62` 또는 `62 31 05 00`; 또는 SQLite 헤더 `SQLite format 3\0`(신형 descriptor 지갑) |
| Electrum | `~/.electrum/wallets/*` (사용자가 `extra_paths` 에 넣은 경우), 이름 `default_wallet` | JSON 에 `wallet_type` 또는 `keystore` 키, 또는 내용이 `BIE1` 로 시작하는 base64(암호화 지갑) |

- 크기 상한: 16 MiB(`wallet.dat` 은 헤더 16바이트만 읽음).
- 메타데이터: 없음. Ethereum 주소(파일 이름·JSON 의 `address`)는 저장하지 않는다 — `masked_name` 규칙(§10)이 이름의 40자 hex 를 가린다.
- 결정: 지갑 파일은 `fingerprint_sha256` 을 저장한다(암호화된 keystore 의 HMAC 은 시드가 아니다). 단 Solana 평문 키 배열은 시드와 같은 등급으로 보고 **지문을 저장하지 않는다**(§13 과 같은 규칙, kind 는 `crypto_wallet` 유지 — 복구 불가능성 경고는 같음).

### 3.11 `db_credential`

| 하위 유형 | 신호 | 검증 |
|---|---|---|
| PostgreSQL | `~/.pgpass`, 이름 `.pgpass`, `pgpass.conf` | 줄 `^[^:#\s]+:[^:]*:[^:]*:[^:]*:.+$` 1줄 이상 |
| MySQL | `~/.my.cnf`, `*.cnf` 중 `[client]`/`[mysql]` 섹션 | 섹션 안 `^\s*password\s*=` |
| MySQL 난독화 | `~/.mylogin.cnf` | 이름만(바이너리, confidence 0.8) |
| 앱 설정 | `database.yml`, `database.json`, `ormconfig.*`, `knexfile.*`, `*.dbeaver`, `credentials-config.json`(DBeaver), `connections.json` | 내용에 §4 의 `dc.db_url_with_password` 또는 `password:`/`"password":` 키가 비어 있지 않은 값과 함께 있음 |
| 클라이언트 인증서·키 | `client-key.pem`, `client-cert.pem` 등 | §3.1/§3.2 가 판정(종류는 거기 따름) |

- 크기 상한: 256 KiB. 메타데이터: 없음(호스트·DB 이름·사용자 저장 금지).

### 3.12 `recovery_codes`

- 신호(이름, 대소문자 무시, 구분자 `-_ .` 무시): `recovery`, `recoverykey`, `backupcode`, `backup-codes`, `2fa`, `otp`, `mfa`, `복구`, `복구코드`, `복구키`, `백업코드`, `emergency kit`, `Emergency Kit`(1Password PDF), `github-recovery-codes`, `*-recovery-codes*`. 그리고 클래스 C 의 내용 신호.
- 크기 상한: 256 KiB(PDF 는 이름만 — 내용을 읽지 않는다).
- 검증(텍스트):
  - 아래 코드 줄 패턴 중 하나가 연속 5줄 이상(빈 줄 허용): `^\s*([0-9]{4,10}|[0-9a-z]{4,6}[- ][0-9a-z]{4,6}|[0-9a-f]{5}-[0-9a-f]{5}|[A-Z0-9]{4}(-[A-Z0-9]{4}){3,7})\s*$`
  - 또는 macOS FileVault/Apple 복구 키 형식 `[A-Z0-9]{4}(-[A-Z0-9]{4}){5}` 1개 이상 + 이름 신호.
  - 이름 신호만 있고 텍스트 검증 실패 → 비자산. 이름 신호 + PDF(`%PDF-` 헤더 5바이트만 확인) → 자산, confidence 0.7, 방법 `filename`.
- 메타데이터: 없음. **줄 번호를 저장하지 않는다**(코드 위치 = 코드 개수 추정 단서는 무해하지만 규칙을 단순히: 복구 수단은 시드와 같은 취급 — 줄 번호·지문 없음, §13).
- 결정: `recovery_codes` 는 `fingerprint_sha256` 을 저장하지 않는다. 이유: 코드 10개짜리 파일의 HMAC 은 안전하지만, “복구 구문은 어떤 파생값도 수집하지 않는다”(CONTEXT 턴2 §6)를 복구 수단 전반에 같은 규칙으로 적용하는 편이 검증 가능하다. 결과: 복구 코드 파일은 내용 기반 중복 탐지를 하지 않는다.

### 3.13 `npki_cert` — 공동인증서(NPKI)

- 신호(위치): 경로 구성요소 중 `NPKI`(대소문자 무시)가 있고 그 아래 파일 이름이 `signCert.der`, `signPri.key`, `kmCert.der`, `kmPri.key`. 기본 위치 `~/Library/Preferences/NPKI/<CA>/USER/<cn=…>/`(vault_extra 루트). 이동식 디스크의 `/Volumes/*/NPKI/` 는 사용자가 그 볼륨을 루트로 등록한 경우에만.
- 신호(이름만): 위 네 이름이 `NPKI` 밖에서 발견 — 같은 규칙으로 검증.
- 크기 상한: 64 KiB.
- 검증:
  - `signCert.der`/`kmCert.der`: §3.1 DER 인증서 로드 성공.
  - `signPri.key`/`kmPri.key`: 첫 바이트 `0x30`, 그리고 DER 안에 KISA 알고리즘 OID 접두 `1.2.410.200004.1.` 의 인코딩 바이트 `2A 83 1A 8C 9A 44 01`(예: `pbeWithSHA1AndSEED-CBC` = `06 08 2A 83 1A 8C 9A 44 01 0F`, `seedCBC` = `… 01 04`) 또는 PKCS#5 PBES2 OID `2A 86 48 86 F7 0D 01 05 0D` 가 있음. 복호화는 시도하지 않는다.
  - 공동인증서 `.pfx` 내보내기 파일은 §3.4 로 판정하되 잎 인증서 issuer O 가 아래 CA 목록이면 종류 `npki_cert`.
- CA 목록(issuer `O=`): `yessign`, `CrossCert`, `KICA`, `signGATE`, `KTNET`, `TradeSign`, `NCASign`(정부), 그리고 `OU=AccreditedCA` 또는 `OU=LicensedCA` 포함.
- 메타데이터: `signCert.der` → 만료·issuer 요약(CA 이름) → `cert_issuer`, subject(실명 포함) → `cert_subject_enc`(06 §6), SPKI 지문 → `key_fingerprint`. `signPri.key` 는 같은 디렉터리의 `signCert.der` 의 지문을 `key_fingerprint` 로 갖는다(짝). `needs_password=1`.
- 저장 금지: subject 평문, 디렉터리 이름의 `cn=` 값(실명+주민번호 파생 일련번호) — 경로 컬럼 `path` 에는 그대로 들어가지만(06: 경로는 평문 허용), 표시 경로·로그·리포트에서는 §10 으로 가린다.

### 3.14 `api_credential`, `unknown_secret`

| 대상 | 신호 | 검증 |
|---|---|---|
| `.netrc` | `~/.netrc`, 이름 `.netrc`/`_netrc` | `^\s*machine\s+\S+` 와 `password\s+\S+` |
| `.git-credentials` | 이름 | `^https?://[^:\s]+:[^@\s]+@` 1줄 이상 |
| `.npmrc` | 이름 | `_authToken\s*=` 또는 `_auth\s*=` 또는 `_password\s*=` |
| `.pypirc` | 이름 | `[pypi]`/`[distutils]` + `password\s*[=:]` |
| Docker | `~/.docker/config.json`(`vault_extra`) | JSON `auths.*.auth` 비어 있지 않음(credsStore 만 있으면 비자산) |
| GitHub CLI | `~/.config/gh/hosts.yml`(`vault_extra`) | `oauth_token:` |
| OAuth 클라이언트 | `client_secret*.json`, `credentials.json` | JSON `installed` 또는 `web` 객체에 `client_secret` |
| OAuth 토큰 | `token.json`, `token.pickle`(이름만 0.6) | JSON 에 `refresh_token` |
| htpasswd | `.htpasswd` | 줄 `^[^:\s]+:(\$apr1\$|\$2[aby]\$|\{SHA\}|[./0-9A-Za-z]{13}$)` |
| 단일 토큰 파일 | 클래스 B 의 이름 `token`, `*.token`, `api_key*`, `apikey*` | §4 서비스 토큰 패턴 1개가 파일의 유일한 비공백 내용 |
| `unknown_secret` | 클래스 B·C 에서 §4 의 강한 패턴은 없지만 이름 신호(`secret`, `secrets`, `password`, `passwords`, `비밀번호`, `암호`)가 있고 `[=:]` 할당 줄이 있음 | confidence 0.55 |

- 크기 상한: 256 KiB. 메타데이터: 없음.

### 3.15 종류 결정 순서와 confidence

한 파일에 여러 종류가 일치하면 위에서 먼저 일치한 것:

1. `crypto_seed_suspected`(§13) — 다른 판정보다 먼저, 일치하면 다른 내용 검사(§4·§5)를 **하지 않는다**.
2. 이름·구조로 정의되는 “전용 형식” 종류: `npki_cert` → `apple_signing` → `android_keystore` → `ssh_private_key` → `pkcs12` → `crypto_wallet` → `private_key` → `cloud_credential` → `vpn_config` → `db_credential` → `env_file` → `api_credential` → `recovery_codes` → `ssh_config` → `certificate`.
3. 전용 형식이 아닌 “담는 파일”(클래스 C 의 텍스트·코드·JSON)에서 §4 강한 패턴 또는 gitleaks 적중 → 적중 규칙의 대응 종류(§4 표의 “종류” 열; 여러 개면 표 순서상 먼저 나오는 것) + 발견 사항 `plaintext_secret`(§9).
4. `unknown_secret`.

confidence(같은 파일에 여러 방법이 있으면 최댓값):

| 근거 | confidence |
|---|---|
| 구조 검증 성공(매직·PEM·파서 로드) | 0.95 |
| §4 강한 패턴(접두사가 고정된 토큰, PEM 개인키 헤더) | 0.9 |
| 잘 알려진 위치의 정확한 이름(`~/.aws/credentials`, `~/.ssh/id_*`) + 내용 미확인(dataless 등) | 0.8 |
| gitleaks 특정 서비스 규칙 | 0.85 |
| 이름 신호 + 약한 검증 | 0.7 |
| 이름 신호만(내용 확인 불가: dataless·TCC·크기 초과) | 0.6 |
| `unknown_secret` | 0.55 |
| gitleaks `generic-api-key` 만 | 0.4 |

- 자산 생성 임계값: **0.5**. 미만(현재 `generic-api-key` 단독)은 자산이 아니라 엔트리 단위 발견 사항(`vault_findings.entry_id`, `asset_id=NULL`, `plaintext_secret`, severity `info`)만 만들고, 그 엔트리의 `sensitivity` 를 `secret` 으로 올린다(AI·미리보기 차단). `protection` 은 올리지 않는다(오탐 가능성이 높은 신호로 파일을 묶어 두지 않음).
- 검증이 **실패한** 신호는 confidence 0 — 자산 없음. 확장자만으로 자산을 만드는 경로는 “내용을 볼 수 없는 경우(0.6)”뿐이다.

`detect_methods_json` 값(06 `vault_detect_method`): 이름 규칙 → `filename`, 확장자 규칙 → `extension`, 위치(vault_extra·§2.1.2·`NPKI` 경로) → `location`, 구조 검증 → `magic`, §4 → `content_pattern`, gitleaks → `gitleaks`. 정렬된 고유 배열.

---

## 4. 내부 내용 패턴 (`vault/patterns.py`)

gitleaks 가 없어도 FR-SV-002 를 만족하기 위한 최소 집합. 정규식은 바이트가 아니라 `surrogateescape` 로 디코드한 줄 단위로 적용하고, 한 줄이 16 KiB 를 넘으면 그 줄은 PEM 헤더 패턴만 검사한다(역추적 폭주 방지). 모든 수량자는 상한이 있다. 매치 객체에서는 **줄 번호만** 꺼내고 매치 문자열은 즉시 버린다.

| 규칙 ID | 패턴(요지) | 종류 | 강함 |
|---|---|---|---|
| `dc.pem_private_key` | `-----BEGIN (RSA \|EC \|DSA \|ENCRYPTED \|OPENSSH )?PRIVATE KEY-----` | `private_key` | 강 |
| `dc.pgp_private_key` | `-----BEGIN PGP PRIVATE KEY BLOCK-----` | `private_key` | 강 |
| `dc.private_key_json` | `"private_key"\s*:\s*"-----BEGIN` | `cloud_credential` | 강 |
| `dc.aws_access_key_id` | `(?<![A-Z0-9])(AKIA\|ASIA\|ABIA\|ACCA)[A-Z0-9]{16}(?![A-Z0-9])` | `cloud_credential` | 강 |
| `dc.aws_secret_assignment` | `aws_secret_access_key\s*[=:]\s*["']?[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])` (대소문자 무시) | `cloud_credential` | 강 |
| `dc.github_token` | `\b(gh[pousr]_[A-Za-z0-9]{36,255}\|github_pat_[A-Za-z0-9_]{80,255})\b` | `api_credential` | 강 |
| `dc.slack_token` | `\bxox[abprs]-[A-Za-z0-9-]{10,200}\b` | `api_credential` | 강 |
| `dc.anthropic_key` | `\bsk-ant-[A-Za-z0-9_-]{20,200}` | `api_credential` | 강 |
| `dc.openai_key` | `\bsk-(proj-\|svcacct-)?[A-Za-z0-9_-]{20,200}` (단 `sk-ant-` 제외) | `api_credential` | 강 |
| `dc.stripe_secret` | `\b(sk\|rk)_live_[A-Za-z0-9]{20,200}` | `api_credential` | 강 |
| `dc.google_api_key` | `\bAIza[0-9A-Za-z_-]{35}\b` | `api_credential` | 약(§3.6 예외 적용) |
| `dc.db_url_with_password` | `\b(postgres(ql)?\|mysql\|mariadb\|mongodb(\+srv)?\|redis\|rediss\|amqps?)://[^:\s/@]{1,128}:[^@\s]{1,256}@` | `db_credential` | 강 |
| `dc.basic_auth_url` | `\bhttps?://[^:\s/@]{1,128}:[^@\s]{3,256}@[^\s/]+` | `api_credential` | 약 |
| `dc.password_assignment` | `\b(password\|passwd\|pwd\|비밀번호)\s*[=:]\s*\S{6,}` (대소문자 무시) | `unknown_secret` | 약 |

- “강” 하나 이상 → 자산(§3.15 3단계). “약”만 → 이름 신호가 있으면 `unknown_secret`(0.55), 없으면 엔트리 단위 `info` 발견 사항만(자산 없음).
- 자리표시자 억제: 적중 줄이 `EXAMPLE`, `example`, `xxxx`, `XXXX`, `<your`, `your_`, `changeme`, `placeholder`, `dummy`, `${`, `{{` 를 포함하면 버린다(예: AWS 문서의 `AKIAIOSFODNN7EXAMPLE`). 결정: 테스트 픽스처는 이 단어를 쓰지 않는 가짜 값을 생성해야 한다(11 문서, `tests/fixtures/secrets.py`).
- 주민등록번호 패턴은 vault 가 아니라 `policy`(07 문서, 환자 판정)의 것이다. vault 는 다루지 않는다.

---

## 5. gitleaks 통합

실측(2026-11-24, 이 머신, gitleaks 8.30.1, 임시 픽스처만 사용):
- `gitleaks stdin` 은 표준입력 내용을 검사한다. `-f json -r -` 이면 결과 JSON 배열이 stdout 으로 나온다. 결과가 없으면 `[]`.
- `--redact`(=100) 이면 `Match`·`Secret` 이 `"REDACTED"` 로 나온다. `--redact=50` 은 앞부분을 보여 준다 → 쓰지 않는다.
- 대상 경로의 `.gitleaks.toml` 이 기본 설정보다 우선한다(전부 허용 목록에 넣는 설정으로 적중 0 확인). `-c` 로 설정을 주면 무시된다.
- 현재 디렉터리의 `.gitleaksignore` 가 적용된다(`-i` 기본값 `.`). 소스 줄의 `gitleaks:allow` 주석은 `--ignore-gitleaks-allow` 없이는 적중을 숨긴다.
- 설정 파일을 열 수 없으면 종료 코드 1, stderr 에 오류.
- stdin 1회 호출 ≈ 25ms.

### 5.1 호출 방식

결정: `gitleaks dir <경로>` 가 아니라 **`gitleaks stdin`** 으로, 파일 하나당 1회, vault 가 §2.3 으로 읽은 바이트를 파이프로 넘긴다. 이유: (1) gitleaks 가 사용자 파일 시스템을 직접 열지 않으므로 심볼릭 링크·dataless·FIFO·TCC 처리를 vault 한 곳이 통제한다. (2) 파일 경로가 argv(프로세스 목록)에 나타나지 않는다. (3) 대상 디렉터리의 `.gitleaks.toml`/`.gitleaksignore` 가 개입할 수 없다.

호출(고정, `common/proc.run_tool("gitleaks", args, timeout=15, input_bytes=data)` — 02 §6 시그니처 `run_tool(tool, args, timeout, input_bytes=None, env=None)`, `shell=False`). `args`:

```
gitleaks stdin
  --config <DAYCLOSE 패키지 데이터>/vault/data/gitleaks.toml
  --gitleaks-ignore-path /var/empty
  --ignore-gitleaks-allow
  --redact
  --no-banner --no-color
  --log-level error
  --report-format json --report-path -
  --exit-code 42
  --max-decode-depth 5
  --timeout 10
```

- `vault/data/gitleaks.toml` 내용: `[extend]` `useDefault = true` 한 섹션뿐(설치된 gitleaks 의 기본 규칙 사용). 허용 목록을 넣지 않는다.
- `/var/empty`: macOS 의 root 소유 빈 디렉터리(실측 존재). `.gitleaksignore` 가 있을 수 없는 경로.
- 실행 파일: `run_tool` 이 `common/paths.system_path("gitleaks")` 의 **절대경로 고정 후보**(`/opt/homebrew/bin/gitleaks`, `/usr/local/bin/gitleaks`)로만 실행한다(02 §6 — `PATH` 검색 없음). vault 의 추가 요구: 후보의 `realpath`(Homebrew 는 `Cellar/…` 로의 링크)가 그 Homebrew 접두사 아래여야 한다 — `system_path` 의 구현 조건으로 02/10 과 맞춘다. 이유: `PATH` 앞에 둔 가짜 `gitleaks` 가 항상 `[]` 를 돌려주면 탐지가 조용히 꺼진다(08 §6.4 와 같은 원칙). 샌드박스 테스트만 `$DAYCLOSE_SANDBOX/bin` 의 가짜 gitleaks(11 §2.3)를 먼저 본다 — §17 L4 의 “가짜 gitleaks” 테스트가 이것을 쓴다. git 도 `/usr/bin/git` 고정(Xcode CLT 미설치 시 이 경로는 설치 대화상자를 띄우는 shim 이므로, `core.doctor` 가 `xcode-select -p` 대신 `/Library/Developer/CommandLineTools` 또는 Xcode 존재를 먼저 확인하고 없으면 git 단계를 `W_TOOL_MISSING` 으로 건너뛴다 — 09 와 조율).
- 작업 디렉터리 `cwd="/"`. 환경: `run_tool` 이 고정 최소 집합으로 새로 만든다(02 §6 — 사용자 셸 환경을 물려주지 않으므로 `GITLEAKS_CONFIG`, `GITLEAKS_CONFIG_TOML`(설정 우선순위 2·3위)은 애초에 전달되지 않는다). vault 는 `env={"HOME": "/var/empty", "LANG": "C"}` 를 덧붙인다. 회귀 테스트: 부모 환경에 `GITLEAKS_CONFIG=<전부 허용 설정>` 을 두어도 적중이 나와야 한다.
- 입력: `input_bytes=data`(stdin). stdout 상한 1 MiB(초과 → 결과 폐기 + 아래 실패 처리), stderr 는 읽어서 **길이만** 쓰고 버린다(오류 메시지에 경로·내용이 섞일 수 있음).

### 5.2 사용 가능성 판정 (run 당 1회, 메모이즈)

1. `config.vault.gitleaks == "off"` → 사용 안 함, 경고 없음.
2. `run_tool("gitleaks", ["version"], timeout=5)` 실패(후보 경로에 없음) → 사용 안 함, `W_TOOL_MISSING` `{"tool":"gitleaks"}`.
3. `gitleaks stdin --help` 종료 코드 0, 그리고 `gitleaks --help` 출력에 `--redact` 와 `--ignore-gitleaks-allow` 와 `--gitleaks-ignore-path` 가 모두 있음 → 사용. 아니면 `W_TOOL_MISSING` `{"tool":"gitleaks","reason":"unsupported_version"}`. 결정: 버전 번호가 아니라 기능 탐지. 이유: 플래그 존재가 안전 조건 그 자체.
4. 자가 시험: 빌드에 포함된 가짜 토큰 한 줄(런타임에 문자열 조합으로 만든 `ghp_` + 36자, 저장소에 완성 문자열이 없게)을 stdin 으로 넣어 적중 1건이고 `Match == Secret == "REDACTED"` 인지 확인. 실패 → 사용 안 함, `W_TOOL_MISSING` `{"reason":"self_test_failed"}`.

### 5.3 결과 파싱과 즉시 정리

1. 종료 코드 0 → 적중 없음(stdout 이 `[]` 가 아니면 실패로 취급). 42 → 적중 있음. 그 외/시간 초과 → 이 파일의 gitleaks 결과 없음, run 경고 `W_TOOL_MISSING` `{"tool":"gitleaks","reason":"run_failed","count":N}`(집계 1회). 실패는 “비밀 없음”이 아니다 — 내부 패턴(§4) 결과는 그대로 쓴다.
2. `json.loads(stdout)` → 리스트가 아니면 실패.
3. 각 원소에서 **허용 키만** 꺼낸다: `RuleID`(문자열, `^[a-z0-9-]{1,64}$` 아니면 버림), `StartLine`(정수 ≥ 1). 나머지(`Match`, `Secret`, `Line`(일부 버전에 존재), `Description`, `Fingerprint`, `File`, `Entropy`, `Commit`, `Author`, `Email`, `Message`, `Tags` …)는 읽지 않는다.
4. 방어: 원소에 `Match` 또는 `Secret` 이 있고 값이 `"REDACTED"` 가 아니면 **이 run 의 gitleaks 결과 전체 폐기**, 이후 호출 중단, `W_TOOL_MISSING` `{"reason":"redaction_failed"}`. 로그에는 사유 코드만.
5. 파싱이 끝나면 `stdout` 변수와 파싱 결과 원본을 `del`. 반환은 `[(rule_id, start_line)]` 뿐.
6. 규칙 ID 저장 형식: `gitleaks:<RuleID>`(예 `gitleaks:aws-access-token`). 강함 분류: `generic-api-key` 만 약(confidence 0.4), 나머지는 강(0.85).
7. 같은 파일·같은 규칙의 여러 적중은 첫 줄 번호 하나로 접는다(발견 사항 행 폭증 방지).

### 5.4 대상

gitleaks 는 다음에만 돌린다: 클래스 C 후보, 클래스 B 후보 중 전용 형식이 아닌 텍스트, `env_file` 예시 파일. 이미 전용 형식(§3.15 2단계)으로 확정된 파일·시드 의심 파일·바이너리(NUL 포함)에는 돌리지 않는다. 결정: 저장소 이력 검사(`gitleaks git`)는 하지 않는다. 이유: 저장소 전체 이력 검사는 무겁고, “이미 커밋된 키” 판정은 §9.3 의 `git log` 경로 단위 조회로 충분.

---

## 6. 인증서·키 메타데이터와 만료

### 6.1 X.509 공통

- 라이브러리: `cryptography`(02 §3). 함수 내부 지연 import(AGENTS §6).
- `not_valid_before_utc`/`not_valid_after_utc` → epoch ms.
- issuer 요약(`cert_issuer`, 평문): issuer 의 `O` 와 `CN` 만 `"O=<o>, CN=<cn>"` 형식(없는 것은 생략, 각 64자 절단). **자체 서명**(issuer == subject)이면 `"(self-signed)"`. 이유: 자체 서명 인증서의 issuer 는 곧 subject 이고, subject 에는 실명·이메일이 있을 수 있다.
- subject(`cert_subject_enc`): `subject.rfc4514_string()` 을 AES-256-GCM(06 §6, AAD `"vault_assets.cert_subject_enc"`)으로. 필드 키 없음(`W_FIELD_KEY_UNAVAILABLE`) → NULL.
- 체인 파일에서는 첫 인증서가 잎이라고 가정한다(PEM/PKCS#7 관례). PKCS#12·JKS 는 키와 짝인 인증서.
- 만료 표시 값 `days_left = floor((cert_not_after - now_ms) / 86_400_000)`. `now` 는 `common/clock` 주입.

### 6.2 만료 출처

| `expiry_source` | 조건 |
|---|---|
| `file` | 위 파서가 `not_after` 를 얻음(인증서, 프로비저닝 프로파일, JKS/p12 의 인증서) |
| `user` | 파일에서 못 얻었고 사용자가 `vault.annotate --expires` 로 입력 |
| `unknown` | 그 외. 표시 “만료일 미확인”, 암호 때문이면 “만료일 미확인(암호 필요)” |

규칙: 파일 만료가 있으면 사용자 입력 만료는 무시된다(§12 에서 거부). 발견 사항 계산의 만료일 = `cert_not_after` 또는 (`expiry_source='user'` 일 때) `user_expires_on` 의 로컬 날짜 23:59:59.999.

---

## 7. 지문

### 7.1 파일 지문 `fingerprint_sha256`

결정: 06 의 `vault_assets.fingerprint_sha256` 에는 **평문 SHA-256 이 아니라 키 입력 HMAC-SHA256** 을 저장한다:

```
fp_key = HMAC-SHA256(field_key_v1, b"dayclose.vault.fingerprint.v1")   # 필드 암호화 키(06 §6)에서 파생, AES 키와 분리
fingerprint_sha256 = hex(HMAC-SHA256(fp_key, file_bytes))
```

이유: `.env`·`.pgpass` 처럼 작고 엔트로피가 낮을 수 있는 비밀 파일의 평문 해시는 DB 만 유출돼도 사전 공격으로 원문을 맞힐 수 있다. 같은 기기 안 중복 판정에는 키 입력 해시로 충분하다. (06 §5.3 컬럼 주석에 반영됨.)

- 필드 키가 없으면(`W_FIELD_KEY_UNAVAILABLE`) NULL.
- 저장하지 않는 종류: `crypto_seed_suspected`, `recovery_codes`(06 §5.3 CHECK 가 이 두 종류의 `fingerprint_sha256`·`key_fingerprint`·`cert_subject_enc` 를 NULL 로 강제), Solana 평문 키(§3.10 — kind 는 `crypto_wallet` 이라 CHECK 밖, store 리포지토리 함수가 강제하고 안전 테스트로 고정).
- 연관 규칙(04 와의 계약): vault 가 자산으로 판정한 엔트리에 대해 **`file_entries.sha256` 을 쓰지 않으며**, 이미 값이 있으면 같은 트랜잭션에서 `sha256=NULL, sha256_mtime_ns=NULL` 로 지운다. intel 의 중복 탐지 후보에서 보안 자산은 이미 빠져 있다(04 §12.1 “보안 자산 아님”). 시드 의심 판정 전에 fs 수집기의 볼륨 간 이동 2차 매칭(04 §2.4)이 해시를 계산했을 수 있으므로 이 삭제 규칙이 필요하다.
- **평문 해시가 어디에도 살아남지 않는다**(리뷰 #19d, 06 §6·§7):
  - M3 이후: 해시 저장은 vault 판정 **뒤에만**(06 §6 해시 저장 규칙). 판정 전에 계산한 해시는 메모리에서만.
  - M2(vault 가 아직 없음): 04 의 중복 탐지가 `file_entries.sha256` 을 저장하기 전에, §3 의 **이름·확장자 신호**(`vault/signals.py: name_matches(path)` — 내용을 읽지 않는 순수 함수, 02 §6 의 예외로 `collect`·`intel`·`policy` 가 import 가능, M2 에 먼저 들어간다)에 일치하는 파일은 해시를 저장하지 않는다. 내용으로만 비밀인 파일(예: 이름이 평범한 `notes.txt`)의 M2 평문 해시는 남을 수 있다 → 0003 마이그레이션(M3)이 적용 직후 한 번, 모든 `file_entries.sha256` 중 `ext` 가 §2.2 클래스 C 확장자이거나 이름 신호에 일치하는 행을 NULL 로 지운다(다음 필요 시 재계산 — 비용은 중복 탐지 재해시뿐).
  - 마이그레이션 직전 자동 백업(`backups/dayclose-…-pre-v3.db`, 06 §7)에는 M2 의 해시가 그대로 있다 → 0003 적용과 위 NULL 처리가 성공하면 **그 `pre-v3` 백업 파일을 즉시 지우고**(store 소관 — DAYCLOSE_HOME 안 파일), 결과 확인 후의 DB 로 새 백업을 만든다. 결정: 마이그레이션 롤백 수단을 잃는 대가보다 평문 해시가 남는 쪽이 나쁘다(0003 은 테이블 추가뿐이라 롤백 필요성이 낮다). 06 §7 의 백업 규칙에 이 예외를 넣도록 요청.
  - collect 단계(분류 전)의 로그는 경로를 남기지 않는다 — 그 시점에는 그 파일이 비밀인지 모르기 때문(02 §13 의 “보안 자산 항목은 경로 금지” 규칙이 분류 전에는 적용될 수 없음). collect 로그는 개수·루트 ID·소요 시간만.

### 7.2 키 지문 `key_fingerprint`

```
key_fingerprint = hex(SHA-256(DER(SubjectPublicKeyInfo)))   # 소문자 64자
```

- 모든 형식(PEM, DER, OpenSSH, PuTTY, PKCS#12, JKS 인증서, 서비스 계정 JSON 의 PEM)을 공개키 객체로 만든 뒤 `public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)`. 같은 키가 PEM 과 OpenSSH 형식으로 따로 있어도 같은 지문이 된다(실측: 같은 RSA 키의 인증서·개인키 지문 일치 확인).
- 공개 데이터이므로 평문 저장. 표시용 축약은 앞 16자.
- SSH 사용자를 위한 `SHA256:<base64>`(OpenSSH 표기)는 저장하지 않는다(공개키 블롭이 필요). 표시가 필요하면 `vault.show` 가 “`ssh-keygen -lf <경로>.pub` 로 확인” 안내 문구를 준다.

### 7.3 중복 판정

같은 키·같은 파일이 서로 다른 **식별자**(`(dev, inode)`, `entry_id=NULL` 자산은 경로)에 2곳 이상 있으면 중복이다. 하드 링크(같은 dev/inode)는 중복이 아니다.

1. 키 중복: `status='active'` 이고 “개인키 보유”(§9.1) 자산 중 같은 `key_fingerprint` 그룹. 인증서(공개)와 그 개인키는 짝이지 중복이 아니다 — 그룹 원소를 “개인키 보유” 자산으로만 센다.
2. 파일 중복: `status='active'` 자산 중 같은 `fingerprint_sha256` 그룹(공개 인증서·프로파일 포함).
3. 각 그룹 원소마다 `duplicate` 발견 사항 1개(그룹 크기 ≥ 2). `rule_id = 'dc.duplicate.key'` 또는 `'dc.duplicate.file'`(둘 다 해당하면 key 우선 1개만).

### 7.4 자산 동일성과 재연결

- 1순위: `entry_id`(fs 수집기가 `(dev, inode)` 로 이동을 추적 — 04 §2.4). 엔트리의 `moved` 는 같은 자산 행의 `path` 를 갱신.
- 엔트리가 `deleted` 되면 자산을 바로 `missing` 으로 두지 않고, 이번 run 의 새 자산 후보 중 같은 `kind` 이고 같은 `fingerprint_sha256`(NULL 이면 같은 `key_fingerprint`, 둘 다 NULL 이면 재연결 안 함)인 것을 찾는다:
  - 정확히 1개 → 기존 자산 행에 재연결(`entry_id`, `path` 갱신, `status='active'`), 새 후보 행은 만들지 않음. 사용자 표시(label/note/backup)가 유지된다.
  - 2개 이상 → 같은 basename 인 것 1개에 재연결, 나머지는 새 자산(→ `duplicate`).
  - 0개 → `status='missing'`.
- `missing` 자산은 이후 run 에서 같은 규칙으로 다시 나타나면 재연결된다. 결정: `missing` 자산 행은 지우지 않는다(사용자 표시 보존, 행당 작음).
- 볼륨 간 복사(`dev` 변경)는 새 엔트리다 → 위 재연결 규칙이 처리.
- `entry_id=NULL` 자산(§2.1.2)은 경로가 같으면 같은 자산. 내용이 바뀌어도 같은 자산(지문만 갱신).

---

## 8. 자산 생명주기, 항목, 보호 판정

### 8.1 upsert 알고리즘 (`vault.run`, 한 트랜잭션 묶음 — 04 의 scan 트랜잭션 안)

1. 후보 목록 = 이번 run 의 `created`/`modified`/`moved` 엔트리 중 §2.2 후보 + 백로그(§2.4) + §2.1.2 고정 파일.
2. 각 후보를 §3 순서로 판정 → `Detection | None`.
3. `None` 이고 기존 자산이 그 엔트리를 가리키면(내용이 바뀌어 더 이상 비밀이 아님 — 예: `.env` 를 비움): 자산을 `missing` 이 아니라 **유지**하되 `confidence` 를 낮추지 않는다. 결정: 한 번 자산이었던 파일은 사용자가 `vault.annotate --status retired`(02 §5.3) 하기 전까지 자산으로 남는다. 이유: 비밀을 지운 `.env` 도 Git 이력·백업에는 남아 있고, 보호 해제를 내용 변화에 맡기면 “내용을 잠깐 바꾼 뒤 휴지통” 경로가 생긴다.
4. `Detection` 이면 insert 또는 update: `kind`(바뀌면 갱신), `detect_methods_json`, `confidence`, `masked_name`(§10), 지문, 인증서 컬럼, `needs_password`, `permissions_mode = st_mode & 0o7777`, `project_id`(04 의 프로젝트 매칭 — 경로가 `projects.root_path` 아래), `in_git_repo`/`git_tracked`/`git_ignored`(§9.3), `last_seen_run_id`, `updated_at`. 새 행이면 `first_seen_run_id`, `status='active'`, `backup_status='unknown'`.
5. 지문이 바뀌었고 `backup_status='verified'` → `backup_status='stale'`(§12.3).
6. 엔트리 `deleted` 처리(§7.4).
7. 시간 의존 재평가: 이번 run 에 엔트리 변화가 없던 **모든** `active` 자산에 대해 `lstat`(권한·소유자·dataless·존재), Git 상태(§9.3), 만료 계산을 다시 한다. 이유: `git add`, `chmod`, 날짜 경과는 파일 mtime 을 바꾸지 않는다.
8. 발견 사항 평가(§9.5).

### 8.2 보호 판정 술어 (policy 가 사용)

`policy` 는 엔트리 `e` 에 대해:

```
is_security_asset(e) :=
    EXISTS vault_assets a WHERE a.entry_id = e.id AND a.status IN ('active','missing','retired')
```

- `retired` 도 보호한다. 결정: “폐기 표시”는 인벤토리 표시·발견 사항 억제용이지 보호 해제가 아니다. 폐기한 키 파일을 지우는 일은 사용자가 Finder 에서 직접 한다(§14). 이유: DayClose 가 지워 줄 수 있게 하는 순간 “자산 보호 해제 → 휴지통” 2단계 경로가 생기고, 그 경로의 첫 단계는 에이전트도 부를 수 있는 쓰기 명령이다.
- 참이면 `protection='security_asset'`, `sensitivity='secret'`(06 §3.1).
- `entry_id=NULL` 자산(홈 바로 아래 파일)은 스캔 루트 밖이라 항목·계획의 대상이 될 수 없다(08 의 `E_PATH_OUTSIDE_ROOTS`). 보호 술어가 필요 없다.
- 엔트리 단위 `info` 발견 사항만 있는 파일(§3.15 임계값 미만 — 자산이 아닌 비밀 포함 파일)은 `sensitivity='secret'` 이고 `protection` 은 변경 없음. **`sensitivity=secret` 이 자산 지위 없이 뜻하는 것**(리뷰 #6, 02 §10.1):
  - `preview_policy=metadata_only`, `ai_policy=none`(06 §3.1) — 미리보기·썸네일·AI 전송 없음.
  - `allowed_actions` 에서 `archive`·`move` 제거(`blocked_reasons` = `secret_content`) — 비밀이 든 파일을 기기 안 다른 곳(특히 암호화되지 않을 수 있는 보관 폴더)으로 복사·이동하지 않는다. `trash` 는 남는다(비밀을 퍼뜨리지 않음).
  - 그룹 결정(`decision.set --group`)과 학습 규칙 결정(`actor='rule'`)에서 제외(`W_PROTECTED_SKIPPED{reason:secret_content}`) — 항목 단위 사람 결정만.
  - 이 파일을 담은 디렉터리의 `move`/`archive` 도 막힌다(08 §7.2.1 `contains_secret_content`).
  - 해제: 내용이 바뀌어 다음 vault 판정에서 적중이 없어지면 그 엔트리의 `sensitivity` 는 다음 정책 계산에서 원래 값으로 돌아간다(자산과 달리 “한 번 비밀이면 계속” 규칙(§8.1-3)은 적용하지 않는다 — 약한 신호이기 때문). 결정: 이 비대칭은 의도적이다 — 강한 신호(자산)는 내용 변화로 풀리지 않고, 약한 신호는 풀린다.

### 8.3 리뷰 항목 생성

- 새 자산 행이 만들어지고 그 run 이 해당 루트의 기준선이 **아니면**(04 §3.4), 그 엔트리에 대해 `subject_type='file'`, `category='security_asset'`, `group_key='vault:new'`(04 §13), `vault_asset_id` 설정된 항목을 만든다. 같은 `subject_key` 의 열린 항목이 이미 있으면(같은 run 에 fs/intel 이 만든 것) 새로 만들지 않고 그 항목의 `category`, `protection`, `sensitivity`, `vault_asset_id` 를 덮어쓴다(열린 항목이 `decided` 이고 `decided_action ∈ {trash, move, archive}` 이면 → `decision.undo` 와 같은 효과로 `proposed` 로 되돌리고 `last_error_code='E_PROTECTED'`).
- 루트 종류와 무관하게(`vault_extra`, `projects` 포함) 만든다. 이유: 오늘 새로 만든 SSH 키·오늘 저장소에 생긴 `.env` 는 결산에 보여야 한다.
- 기준선 run 의 자산은 항목을 만들지 않는다 — `vault.list`·`vault.health` 에만 나온다(설치 첫날 결재함 폭주 방지).
- 재연결(§7.4)은 새 자산이 아니므로 항목 없음.
- `entry_id=NULL` 자산은 항목이 아니라 `vault.health` 와 세션 지표 `vault_new` 에만 반영.
- 항목의 `suggestion`: `action='acknowledge'`, `source='heuristic'`, `reason` = 자산 종류 문구 + 가장 높은 심각도 발견 사항 요약(마스킹 규칙 적용, 경로 없음), `confidence` = 자산 confidence.
- `allowed_actions` = 02 §10.1 의 `security_asset` 행: `acknowledge`, `keep`, `keep_always`, `defer`.
- 항목에 `acknowledge` 또는 `keep`/`keep_always` 결정이 기록되면, 그 시점에 열려 있던 그 자산의 모든 발견 사항을 `acknowledged`(+`acknowledged_at`)로 바꾼다(02 §5.3 계약 — 발견 사항 확인 전용 명령은 두지 않는다). 이후 새로 생기는 발견 사항은 다시 `open`.

### 8.4 `missing`·`retired` 의 효과

| status | 발견 사항 | 목록 기본 표시 |
|---|---|---|
| `active` | 전부 평가 | 예 |
| `missing` | 평가 중단. 열린 것은 `resolved` | `--status missing` 일 때만. 마지막 관측 365일 후 행 삭제(06 §8, 발견 사항 함께) |
| `retired` | `tracked_in_git`, `exposed_location`, `bad_permissions`, `duplicate`, `plaintext_secret` 만 계속 평가(폐기한 키도 노출은 노출). `expiring_soon`, `expired`, `no_backup` 은 `resolved` | `--status retired` 일 때만. `vault.annotate --status active` 로 되돌리면 전부 재평가 |

보존(06 §8): `resolved` 발견 사항은 `resolved_at` 180일 후 삭제. `active`·`retired` 자산은 삭제하지 않는다.

---

## 9. 발견 사항 (Security Health)

### 9.1 분류 보조 개념

**개인키 보유(private-bearing)** 자산: `private_key`, `ssh_private_key`, `pkcs12`, `android_keystore`(서명 설정 파일 포함), `npki_cert` 중 `signPri.key`/`kmPri.key`/`.pfx`, `apple_signing` 중 `.p8`/`.p12`, `crypto_wallet`, `cloud_credential`, `api_credential`, `db_credential`, `env_file`, `vpn_config`(인라인 키/`PrivateKey` 있을 때), `recovery_codes`, `unknown_secret`, `crypto_seed_suspected`.
**공개 전용(public-only)** 자산: `certificate`, `ssh_config`, `apple_signing` 중 프로파일·인증서, `npki_cert` 중 `*Cert.der`, `vpn_config`(키 없음).

**대체 불가(irreplaceable)** 자산(잃으면 재발급으로도 복구가 어렵거나 비용이 큼): `apple_signing` `.p8`(Apple 은 다운로드를 1회만 허용), `android_keystore`(업로드 키, `debug.keystore` 제외), `crypto_wallet`, `npki_cert` 의 `signPri.key`, `pkcs12`, `ssh_private_key`, `private_key`, `recovery_codes`.

**노출 위치**: 항목의 `origin_root_kind ∈ {downloads, desktop, screenshots}`(약), 또는 경로가 `icloud_drive` 루트 안·`~/Library/Mobile Documents/` 아래·`~/Library/CloudStorage/` 아래(강 — 기기 밖 동기화).

### 9.2 규칙과 심각도 (`vault_finding_type` → `finding_severity`)

| finding | 대상 | 조건(정확히) | severity | `rule_id` | `line_no` |
|---|---|---|---|---|---|
| `expiring_soon` | 만료일 있는 `active` 자산 | `0 ≤ days_left ≤ config.vault.expiry_warn_days`(기본 30) | `days_left ≤ 7` → `critical`, 그 외 `high` (FR-SV-005 AC: 23일 → `high`) | `dc.expiry.file` / `dc.expiry.user` | NULL |
| `expired` | 〃 | `days_left < 0` | `warn` | 〃 | NULL |
| `tracked_in_git` | 모든 자산(§8.4 참고) | §9.3 의 `tracked` 또는 `history` | 개인키 보유 → `critical`; 공개 전용 → `info` | `dc.git.tracked` / `dc.git.history` | NULL |
| `duplicate` | `active` | §7.3 | `crypto_wallet`·`crypto_seed_suspected` 무관(시드는 지문 없음 → 해당 없음); 그룹에 노출 위치(강)가 있으면 `high`, 그 외 `warn` | `dc.duplicate.key` / `dc.duplicate.file` | NULL |
| `bad_permissions` | `active`(§9.4) | §9.4 | §9.4 | `dc.perm.*` | NULL |
| `no_backup` | 대체 불가 `active` | `backup_status ∈ {unknown, none, stale}` 이고 자산이 처음 발견된 지 7일 이상(`first_seen_run_id` 의 시작 시각 기준). `debug.keystore` 제외 | `apple_signing .p8`, `android_keystore`, `crypto_wallet` → `high`; 나머지 `warn`. `stale` 이면 같은 심각도 | `dc.backup.unknown` / `.none` / `.stale` | NULL |
| `exposed_location` | 개인키 보유 `active` | 노출 위치 | 강 → `high`; 약 → `warn`. `debug.keystore` 제외 | `dc.location.sync` / `dc.location.downloads` | NULL |
| `plaintext_secret` | §3.15 3단계(담는 파일)의 자산, 또는 임계값 미만 엔트리 | 적중 규칙마다 1개 | 자산 → `high`; 엔트리 단위(약) → `info` | `dc.*` 또는 `gitleaks:*` | 적중 첫 줄 |
| `seed_phrase_suspected` | `crypto_seed_suspected` | 자산 존재 | `critical` | `dc.seed.bip39` / `dc.seed.name` | **항상 NULL** |

결정: `no_backup` 7일 유예. 이유: 오늘 받은 키에 오늘 “백업 없음”을 띄우면 첫날 경고가 넘친다. 결정: `expired` 는 `warn`. 이유: 이미 만료된 인증서는 대부분 교체가 끝난 잔재이고, 교체가 안 된 경우는 서비스 장애로 사용자가 먼저 안다. 만료 직전(`expiring_soon`)이 행동을 바꿀 수 있는 시점.

### 9.3 Git 상태 판정

자산 경로 `p` 에 대해(엔트리 변화가 있거나 시간 의존 재평가 시):

1. 저장소 루트 찾기: `p` 의 부모부터 위로 올라가며 `.git`(디렉터리 또는 `gitdir:` 파일)을 `lstat`. 스캔 루트의 부모를 넘어가면 중단. 결과 없음 → `in_git_repo=0, git_tracked=0, git_ignored=0`, 끝.
2. 이후 git 호출 공통: `run_tool("git", ["-C",R, "-c","core.fsmonitor=false", "-c","core.untrackedCache=false", "--no-pager", …], timeout=5, env={…})`(실행 파일은 `system_path("git")` = `/usr/bin/git`), 덧붙이는 환경 `GIT_OPTIONAL_LOCKS=0`(색인 갱신 쓰기 방지), `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`, `LANG=C`. 이유: `core.fsmonitor` 는 저장소 설정으로 임의 프로그램을 실행시킬 수 있고, `GIT_OPTIONAL_LOCKS=0` 이 없으면 일부 읽기 명령이 `.git/index` 를 다시 쓴다. `safe.directory` 는 건드리지 않는다(소유자가 다른 저장소의 설정을 읽지 않게 하는 git 의 보호를 유지) — git 이 “dubious ownership”(종료 128)으로 거부하면 Git 상태 미확인으로 두고 발견 사항을 만들지 않는다.
3. 추적 여부: `ls-files --error-unmatch -z -- <R 기준 상대경로>` → 종료 0 이면 `git_tracked=1`(`tracked`).
4. 무시 여부: `check-ignore -q -- <상대경로>` → 종료 0 이면 `git_ignored=1`, 1 이면 0, 그 외 미확인(02 의 주의: `check-ignore` 는 무시되면 0).
5. 이력: `git_tracked=0` 이면 `log --all -1 --format=%H -- <상대경로>` → 출력이 있으면 `history`(지금은 추적 안 하지만 과거 커밋에 있음). 커밋 해시는 저장하지 않는다. 결정: `-p`/`--stat` 를 쓰지 않는다(diff 드라이버·textconv 실행 방지).
6. 같은 저장소의 자산이 여러 개면 3단계를 `ls-files -z -- <p1> <p2> …` 한 번으로 묶을 수 있다(출력된 경로 = 추적됨). 인자 경로는 argv 에 나타나지만 사용자 자신의 프로세스 목록이므로 허용(로그에는 쓰지 않는다).
7. `in_git_repo=1`.

(실측: 임시 저장소에서 `GIT_OPTIONAL_LOCKS=0 git -c core.fsmonitor=false ls-files --error-unmatch`, `check-ignore -q`, `log --all -1 --format=%H` 실행 전후 `.git/index` 해시 불변.)

### 9.4 권한 검사 (`bad_permissions`)

`st = lstat(p)`, `mode = st.st_mode & 0o777`, 현재 사용자 `uid = os.getuid()`.

| 규칙 ID | 대상 | 조건 | severity |
|---|---|---|---|
| `dc.perm.ssh_key` | `ssh_private_key` | `mode & 0o077 != 0` (OpenSSH 가 키 사용을 거부하는 조건과 같음) | `high` |
| `dc.perm.ssh_dir` | `~/.ssh` 디렉터리(자산 아님, `vault_extra` 루트 자체 — 발견 사항은 그 안의 `ssh_private_key` 자산마다 하나) | 디렉터리 `mode & 0o022 != 0`(그룹·기타 쓰기) | `high` |
| `dc.perm.ssh_config` | `ssh_config` | `mode & 0o022 != 0` | `high` |
| `dc.perm.world_read` | 그 외 개인키 보유 | `mode & 0o004 != 0` | 대체 불가 → `warn`, 그 외 `info` |
| `dc.perm.group_read` | 그 외 개인키 보유 | `mode & 0o040 != 0` 이고 world_read 아님 | `info` |
| `dc.perm.owner` | 개인키 보유 | `st.st_uid != uid` | `warn` |
| `dc.perm.acl` | 개인키 보유 | 확장 ACL 에 소유자 외 주체에게 `read` 를 허용하는 `allow` 항목이 있음(아래) | `ssh_private_key` → `high`, 그 외 `warn` |

- 한 자산에 여러 규칙이 걸리면 규칙마다 1행(`rule_id` 로 구분 — 06 의 유니크 인덱스가 허용).
- ACL 읽기: `ctypes` 로 libSystem `acl_get_link_np(path, ACL_TYPE_EXTENDED=0x100)` → NULL 이면 ACL 없음(`ENOENT`) 또는 오류(검사 생략, 발견 사항 없음) → `acl_to_text` → 줄 형식 `<user|group>:<uuid>:<name>:<id>:<allow|deny>:<perms>` 에서 `allow` 이고 perms 에 `read` 가 있고 (user 이고 id ≠ uid) 또는 group 인 줄이 있으면 적중 → `acl_free` 두 번(텍스트·acl). 결정: ctypes 호출은 `common/` 의 읽기 전용 헬퍼(`common/fsmeta.py`)에 둔다. 그 파일에는 `acl_set_*` 계열 심볼을 바인딩하지 않는다(§16 정적 검사).
- DayClose 는 권한을 고치지 않는다(V1). 문구로 명령을 안내만: “`chmod 600 <파일>` 로 고칠 수 있습니다.” — 문구 안의 `<파일>` 은 마스킹하지 않은 실제 경로가 아니라 `vault.show` 화면에서만 실제 경로로 채운다(§11.5).

### 9.5 평가·해소 알고리즘

매 vault run 끝에(트랜잭션 안):

1. 평가 대상 집합 = `active` 자산 전부 + `retired` 자산(§8.4 의 부분 규칙) + 이번 run 의 엔트리 단위 적중.
2. 각 (대상, finding, rule_id, line_no) 조합에 대해 조건이 참이면:
   - 같은 키의 `state <> 'resolved'` 행이 있으면 `last_seen_run_id` 갱신, `severity` 갱신(만료 임박 7일 경계 통과 등).
   - 없으면 insert(`state='open'`, `detected_run_id`).
3. 이번 run 에서 다시 확인되지 않은 `state <> 'resolved'` 행은 `state='resolved'`, `resolved_at`. 단 그 자산이 이번 run 에서 평가되지 못한 경우(루트 접근 불가·TCC·volume timeout)에는 해소하지 않는다 — “보이지 않음 ≠ 해결”(04 §1.2 와 같은 원칙).
4. `plaintext_secret` 의 `line_no` 가 바뀌면(내용 편집) 이전 행은 해소, 새 행 생성.
5. 세션 지표: `vault_new`(이번 리뷰 날짜에 생성된 자산 수), `vault_findings_open`(`state='open'` 이고 severity ≥ `warn` 수) — 06 §5.2 `stats_json` 키. 그리고 `vault_expiring_soon`(열린 `expiring_soon` 수, 심각도 무관), `vault_expiring_critical`(그중 `critical`, 즉 ≤ 7일), `vault_expiring_min_days`(열린 `expiring_soon` 중 가장 작은 `days_left`, 없으면 null), `vault_expiring_nearest_kind`(그 자산의 kind 표시 문구 — 이름·경로 없음).
6. **만료 알림**(리뷰 C, 09 가 표시): 일일 알림(FR-MI-003)에 열린 `expiring_soon` 이 1개 이상이면 한 줄 “인증서 만료 임박 N개(가장 가까운 것: <kind_label> D-<n>)”를 넣는다 — `high` 도 포함(일일 알림의 critical 전용 규칙의 예외). 어떤 `expiring_soon` 이 `critical`(≤ 7일)이 되면 **별도 알림**을 하루 1회, 그 발견 사항이 `acknowledged`·`resolved` 되거나 만료될 때까지 보낸다. 알림 문구에는 `masked_name` 도 쓰지 않고 `kind_label` 과 남은 일수만(잠금 화면 노출) — 예 “Apple 배포 인증서 만료까지 5일”. `retired` 자산은 제외(§8.4). 예약 실행의 알림 데이터는 `review.summary` 의 세션 지표(`vault_expiring_soon`, `vault_expiring_critical`, `vault_expiring_min_days`(정수, 없으면 null), `vault_expiring_nearest_kind`(kind 표시 문구만) — 06 §5.2 `stats_json`)에서만 얻는다 — 스케줄 채널은 `scan.run`·`review.summary` 만 부를 수 있다(02 §7). 앱 화면은 `vault.health` 를 쓴다.

### 9.6 문구 (한국어, 경로·이름 없음 — 마스킹 이름은 화면이 따로 표시)

| finding | message | remediation |
|---|---|---|
| `expiring_soon` | “만료까지 N일 남았습니다.” | “발급처에서 갱신하고, 새 파일을 같은 위치에 두세요. 기존 파일은 갱신 확인 후 직접 정리하세요.” |
| `expired` | “N일 전에 만료되었습니다.” | “더 이상 쓰지 않는다면 ‘폐기 표시’로 목록에서 숨길 수 있습니다.” |
| `tracked_in_git` | “이 파일은 Git 저장소에 커밋되어 있습니다.” / 이력만: “지금은 추적되지 않지만 과거 커밋에 남아 있습니다.” | (개인키 보유) “파일을 지우거나 .gitignore 에 추가해도 이미 커밋된 사본은 저장소 이력과 원격 저장소에 남습니다. **키를 발급처에서 폐기(revoke)하고 새로 발급**한 뒤, 새 키는 저장소 밖이나 .gitignore 된 경로에 두세요. 이력 정리(git filter-repo 등)는 폐기 후 선택 사항입니다.” (공개 전용) “공개 인증서라 위험은 낮습니다. 의도한 것인지 확인하세요.” |
| `duplicate` | “같은 키(또는 파일)가 N곳에 있습니다.” | “실제로 쓰는 위치 하나를 정하고, 나머지 사본은 필요 여부를 확인한 뒤 직접 정리하세요. 사용 중인 경로는 바꾸지 마세요.” |
| `bad_permissions` | 규칙별: “다른 사용자가 읽을 수 있습니다.” / “SSH 가 이 권한의 키 사용을 거부합니다.” / “소유자가 현재 사용자가 아닙니다.” / “ACL 이 다른 사용자에게 읽기를 허용합니다.” | “`chmod 600` 으로 소유자만 읽게 하세요.”(ssh_dir: “`chmod 700 ~/.ssh`”) |
| `no_backup` | “복구 가능한 백업이 확인되지 않았습니다.” | “안전한 곳(비밀번호 관리자, 암호화된 외장 디스크 등)에 사본을 두고 ‘백업 확인’으로 표시하세요. DayClose 는 키를 복사하지 않습니다.” |
| `exposed_location` | 강: “다른 기기와 동기화되는 위치에 있습니다.” / 약: “다운로드·데스크탑에 있습니다.” | “쓰는 위치로 직접 옮기세요(예: SSH 키는 ~/.ssh). 이미 공유·동기화되었다면 폐기·재발급을 검토하세요.” |
| `plaintext_secret` | “일반 파일 안에 비밀값으로 보이는 문자열이 있습니다 (N번째 줄, 규칙 R).” | “비밀번호 관리자나 Keychain 으로 옮기고, 이 파일에서는 지우세요. 다른 곳에 공유했다면 폐기·재발급하세요.” |
| `seed_phrase_suspected` | “암호화폐 복구 구문으로 보이는 파일이 있습니다.” | “복구 구문은 디지털 파일로 두지 않는 것이 원칙입니다. 종이·금속 백업으로 옮긴 뒤 파일을 직접 지우고, 이 기기가 노출되었다면 새 지갑으로 자산을 옮기세요. DayClose 는 이 파일의 내용·지문을 저장하지 않습니다.” |

FR-SV-007: `tracked_in_git` 항목의 제안 동작은 `acknowledge` 하나(§8.3), `allowed_actions` 에 파괴적 동작 없음.

---

## 10. 마스킹 규칙 (`vault/mask.py`)

`masked_name`(06 `vault_assets.masked_name`)과 표시 경로를 만든다. 같은 입력 → 같은 출력(결정적). 가린 부분은 길이와 무관하게 항상 `••••••`(U+2022 × 6) — 원래 길이를 드러내지 않는다.

### 10.1 `masked_name`

1. basename 을 NFC 로 정규화.
2. 안전 이름 목록(정확히 일치, 대소문자 무시)이면 그대로: `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`, `id_ecdsa_sk`, `id_ed25519_sk`, `config`, `credentials`, `signCert.der`, `signPri.key`, `kmCert.der`, `kmPri.key`, `key.properties`, `keystore.properties`, `debug.keystore`, `.netrc`, `.git-credentials`, `.npmrc`, `.pypirc`, `.pgpass`, `.my.cnf`, `config.json`, `hosts.yml`, `.env`, `.envrc`, `wallet.dat`, `id.json`.
3. `crypto_seed_suspected` 와 `recovery_codes`: stem 전체를 가린다 → `••••••` + 확장자(없으면 `••••••`).
4. 그 외: 확장자 분리. `.env.*` 계열은 `.env.` 뒤 접미어를 확장자로 보지 않고 아래 토큰 규칙만 적용(`.env.production` → 그대로).
5. stem 을 구분자 `[-_. @+=,()]` 로 토큰화하고(구분자는 보존), 다음 토큰을 `••••••` 로 바꾼다:
   - 숫자 4자 이상 포함
   - 길이 ≥ 8 이고 영문·숫자가 섞인 토큰(키 ID·해시·주소 — `AuthKey_ABCD1234EF` 의 `ABCD1234EF`)
   - `[A-Z0-9]{10}` (Apple 키·팀 ID)
   - UUID, 40자 hex(Ethereum 주소), 이메일(토큰에 `@` 가 끼면 앞뒤 토큰 둘 다)
   - `cn=…` 형태(NPKI)
   - 한글 2~4음절 토큰이고 kind 가 `npki_cert`(실명 추정)
6. 길이 상한 80자(초과 시 가운데를 `…`).

예: `AuthKey_ABCD1234EF.p8` → `AuthKey_••••••.p8`, `UTC--2024-01-02T03-04-05.000Z--0123…cdef` → `UTC--••••••--••••••`, `distribution.p12` → 그대로, `firebase-adminsdk-x1y2z-0a1b2c3d4e.json` → `firebase-adminsdk-••••••-••••••.json`, `my seed words.txt` → `••••••.txt`.

### 10.2 표시 경로 `display_path`

- 홈 접두사 → `~`.
- 각 디렉터리 구성요소에 10.1 의 5단계 토큰 규칙을 적용(안전 이름 목록 없음). `NPKI/yessign/USER/cn=홍길동()0011…` → `~/Library/Preferences/NPKI/yessign/USER/cn=••••••`.
- 디렉터리까지만(파일명 제외). 화면은 `display_path` + `masked_name` 을 붙여 보여 준다.

### 10.3 어디에 무엇을

| 출력 | 이름 | 경로 |
|---|---|---|
| 항목 JSON(`item.list`) | `display_name` = `masked_name`(02 §5.6) | `display_path` = 10.2. `path` 는 02 §5.6 계약대로 실제 경로 |
| `vault.list`, `vault.health` | `masked_name` | `display_path` 만(실제 경로 없음) |
| `vault.show`, `item.show` | `masked_name` + `name`(실제) | `path`(실제) + `display_path` — 단 채널 `skill`/`mcp` 이면 실제 값 필드는 `null`(§11.5) |
| `report.daily`(md/json) | `masked_name` | `display_path` |
| 그룹 제목·`suggestion.reason`·`review_groups.title` | 이름 없음(“새 보안 자산 3개”) | 없음 |
| 로그(`core.log`) | 없음 | 없음 — `asset_id` 만 |
| `audit_log.summary`, 봉투 `error.details`·`warnings[].details` | 없음 | 없음 — `asset_id`/`item_id` 만 |

---

## 11. `vault.*` 명령 응답 (data 형태 — 최종 스키마는 10 문서)

모두 읽기 전용(`vault.annotate` 제외, §12). 비밀 원문·매치 문자열·subject 평문은 어떤 채널에서도 `vault.list`/`vault.health` 에 나오지 않는다.

### 11.1 공통 자산 요약 객체

```json
{
  "id": "ast_5",
  "kind": "apple_signing",
  "kind_label": "Apple 개발자 API 키",
  "masked_name": "AuthKey_••••••.p8",
  "display_path": "~/Downloads",
  "status": "active",
  "confidence": 0.95,
  "detect_methods": ["extension", "filename", "magic"],
  "needs_password": false,
  "expiry": {"not_after": null, "source": "unknown", "days_left": null},
  "backup_status": "unknown",
  "project": null,
  "git": {"in_repo": false, "tracked": false, "ignored": false},
  "permissions": "0644",
  "key_fingerprint_short": "0f694fe0618d74d7",
  "findings_open": {"critical": 0, "high": 1, "warn": 1, "info": 0},
  "label": "App Store Connect CI 키",
  "first_seen_at": "2026-11-24T12:03:10.220Z",
  "last_seen_at": "2026-11-24T12:03:10.220Z"
}
```

- `label`: `user_label_enc` 복호화 값. 채널 `skill`/`mcp` 에서는 `null`(사용자 메모는 에이전트 컨텍스트로 보내지 않는다). 필드 키 없음 → `null` + `W_FIELD_KEY_UNAVAILABLE`.
- `crypto_seed_suspected`: `key_fingerprint_short=null`, `permissions` 는 표시(위치 정보 수준), `expiry`·`git` 은 표시.
- `display_path` 는 `entry_id=NULL` 자산도 같은 규칙.

### 11.2 `vault.list [--kind K] [--status S]`

`data = {"items": [자산 요약…], "next_cursor": null, "total": N}`. 기본 `--status active`. 정렬: 가장 높은 열린 발견 사항 심각도 내림차순 → kind → `masked_name`. 페이지 크기 200.

### 11.3 `vault.show ASSET_ID`

자산 요약 + 다음:

```json
{
  "asset": { "…요약…": "…" },
  "name": "AuthKey_ABCD1234EF.p8",
  "path": "/Users/…/Downloads/AuthKey_ABCD1234EF.p8",
  "cert": {"issuer": "O=Apple Inc., CN=Apple Worldwide Developer Relations Certification Authority", "subject": "…복호화…", "not_before": "…", "not_after": "…"},
  "note": "…복호화된 사용자 메모…",
  "user_expires_on": null,
  "findings": [
    {"id": "fnd_9", "finding": "exposed_location", "severity": "warn", "state": "open", "rule_id": "dc.location.downloads", "line_no": null,
     "message": "다운로드·데스크탑에 있습니다.", "remediation": "쓰는 위치로 직접 옮기세요…", "detected_at": "…", "acknowledged_at": null}
  ],
  "related": [{"id": "ast_6", "relation": "same_key", "masked_name": "distribution.p12", "display_path": "~/Desktop"}],
  "item_id": "itm_301"
}
```

- `related.relation`: `same_key`(같은 `key_fingerprint`, 키↔인증서 짝 또는 중복), `same_file`(같은 `fingerprint_sha256`), `same_dir_pair`(NPKI `signCert.der`↔`signPri.key`).
- 채널 `skill`/`mcp`: `name`, `path`, `cert.subject`, `note` 는 `null`.
- 없는 ID → `E_NOT_FOUND`.

### 11.4 `vault.health`

```json
{
  "summary": {"assets_active": 6, "needs_review": 3, "reviewed": 0,
              "by_severity": {"critical": 1, "high": 2, "warn": 3, "info": 1},
              "by_finding": {"expiring_soon": 1, "tracked_in_git": 1, "duplicate": 3, "no_backup": 2, "bad_permissions": 0}},
  "checks": [
    {"finding": "bad_permissions", "status": "ok", "count": 0, "message": "SSH 파일 접근 권한 검사 정상"}
  ],
  "findings": [
    {"id": "fnd_12", "finding": "expiring_soon", "severity": "high", "state": "open",
     "asset_id": "ast_6", "entry_id": null, "kind": "apple_signing", "masked_name": "distribution.p12", "display_path": "~/Desktop",
     "title": "인증서 만료 임박", "message": "만료까지 23일 남았습니다.", "remediation": "…"}
  ],
  "tools": {"gitleaks": "ok"}
}
```

- `needs_review` = 열린 항목(`is_open=1`)이 있는 자산 수, `reviewed` = 그 외 활성 자산 중 결정이 기록된 수(CONTEXT 턴2 UI 의 “보호 검토 필요 / 검토 완료”).
- `checks`: 9개 발견 사항 유형 **전부**에 대해 항상 한 줄씩(통과한 검사 포함) `{finding, status, count, title, message}`. `status`: `ok`(열린 것 0건) / `attention`(warn 이상 1건 이상) / `info_only` / `unavailable`(도구 없음·평가 불가 — 예: Git 미설치면 `tracked_in_git` 은 `unavailable`). UI 는 `title`·`message`·`remediation` 을 그대로 표시한다(03) — 문구의 원천은 core 하나.
- `title`(짧은 제목): `expiring_soon` “인증서 만료 임박”, `expired` “만료된 인증서”, `tracked_in_git` “Git 저장소 내 인증 정보”, `duplicate` “중복 키”, `bad_permissions` “파일 접근 권한”, `no_backup` “백업 미확인”, `exposed_location` “노출된 위치”, `plaintext_secret` “일반 파일 속 비밀값”, `seed_phrase_suspected` “복구 구문 의심 파일”.
- `findings`: `state ∈ {open, acknowledged}`, 심각도 내림차순, 최대 100개(초과 시 `W_TRUNCATED`).
- 엔트리 단위 발견 사항: `asset_id=null`, `entry_id` 는 외부 ID(`ent_…`), `masked_name` 은 엔트리 이름에 10.1 의 5단계를 적용한 것.
- `tools.gitleaks`: `ok` | `missing` | `off` | `unsupported` | `redaction_failed`.

### 11.5 채널별 실제 경로 노출 규칙

결정: 실제 경로·실제 파일명·subject·메모는 채널 `cli`, `app` 에서 `vault.show`/`item.show` 를 **명시적으로 한 건 조회**할 때만 나간다. `skill`/`mcp` 채널에서는 같은 필드가 `null`. 이유: AGENTS §3.4 — 보안 자산 경로를 외부 모델(코딩 에이전트의 LLM)에 보내지 않는다. 한계: `--channel` 은 호출자가 스스로 밝히는 값이라, 셸 권한이 있는 에이전트가 `--channel cli` 로 호출하는 것은 막지 못한다(§19 남은 위험). MCP(M8)는 전송 계층이 채널을 강제하므로 이 규칙이 실효를 갖는다. 항목 JSON 의 `path`(02 §5.6)도 `skill`/`mcp` 채널에서 `protection ∈ {security_asset, patient_data}` 이면 `null` 이어야 한다 — 10 문서에 반영 요청(§19).

---

## 12. 사용자 표시 (`vault.annotate`)

시그니처(02 §5.3): `dayclose vault annotate ASSET_ID [--label TEXT] [--note TEXT] [--expires DATE] [--backup verified|none|unknown] [--status active|retired]`. W(쓰기 잠금), 파일 변경 없음, `audit_log` 기록(`target_type='asset'`, `summary="vault.annotate label,backup"` 처럼 바뀐 필드 이름만). MCP 비노출(02 §10.3).

`--status`: `retired` ↔ `active` 만(`missing` 은 스캔만 설정하므로 `E_USAGE`). 효과는 §8.4 — 보호(§8.2)는 바뀌지 않는다. `missing` 자산에 `--status retired` 는 허용(사라진 키를 폐기로 정리).

### 12.1 검증

1. 자산 없음 → `E_NOT_FOUND`. 인자가 하나도 없음 → `E_USAGE`.
2. `--label`: 1~100자(빈 문자열 `""` = 지우기). `--note`: 0~2,000자.
3. 비밀 입력 방지: label·note 에 §4 의 “강” 패턴 또는 PEM 헤더가 있으면 `E_USAGE`(`message`: “메모에 비밀값처럼 보이는 문자열이 있습니다. 비밀값은 DayClose 에 저장하지 않습니다.”, `details` 에 매치 없음). 이유: 사용자가 “용도” 칸에 비밀번호를 붙여 넣는 사고 — 암호화되더라도 DayClose 를 비밀 저장소로 만들지 않는다.
4. `--expires YYYY-MM-DD` 또는 `none`(지우기). 자산의 `expiry_source='file'` 이면 `E_USAGE`(“파일에서 읽은 만료일이 있어 직접 입력할 수 없습니다.”). 과거 날짜 허용(이미 만료).
5. `--backup`: enum 검사. `crypto_seed_suspected` 에는 `E_USAGE`(시드는 백업 상태를 추적하지 않는다 — §13).

### 12.2 저장

- `user_label_enc`, `user_note_enc`: AES-256-GCM, AAD `"vault_assets.user_label_enc"` / `"vault_assets.user_note_enc"`. 결정: 필드 키가 없으면 `W_FIELD_KEY_UNAVAILABLE` 경고와 함께 label/note 변경만 건너뛰고 나머지 인자는 적용, `ok=true`. 이유: 키 분실 시에도 백업·만료 표시는 평문 컬럼이라 쓸 수 있어야 한다.
- `--expires` → `user_expires_on`, `expiry_source = 'user'`(지우면 `'unknown'`).
- `--backup` → `backup_status`. 이것이 `backup_status` 의 **유일한** 갱신 경로다(02 §5.3, PRD §9.2 O2) — 예외는 §12.3 의 `verified → stale` 자동 전이 하나.
- 같은 트랜잭션에서 그 자산의 발견 사항을 재평가(§9.5 의 2~3단계, 해당 자산만) → `no_backup`, `expiring_soon` 이 즉시 열리거나 해소된다.
- 응답 `data` = `vault.show` 와 같은 형태.

### 12.3 백업 상태의 의미

| `backup_status` | 의미 | 설정 |
|---|---|---|
| `unknown` | 모름(기본) | 생성 시, 또는 사용자가 `--backup unknown` |
| `none` | 사용자가 “백업 없음”이라고 표시 | 사용자 |
| `verified` | 사용자가 “복구 가능한 사본이 있다”고 표시 | 사용자 |
| `stale` | `verified` 표시 뒤 파일 지문이 바뀜(키를 갈아 끼움 — 예전 백업은 새 키의 백업이 아님) | vault 자동(§8.1 5단계). 지문이 NULL 인 종류는 자동 전이 없음 |

소유자 확정(PRD C10): “백업됨” = 사용자가 `vault annotate --backup verified` 로 표시한 경우뿐. 결정: DayClose 는 “백업이 실제로 존재하는지”를 검증하지 않는다(사본 위치를 알 수도, 읽을 수도 없다 — 비밀번호 관리자·종이 등). 같은 기기의 다른 경로에 있는 사본(`duplicate`)은 백업으로 치지 않는다(같은 디스크 고장에 함께 사라짐).

---

## 13. 시드·복구 구문 비수집 (`crypto_seed_suspected`)

### 13.1 탐지

- 대상: 클래스 A·B·C·D 의 텍스트 파일(64 KiB 이하), 그리고 이름 신호.
- 이름 신호(대소문자·구분자 무시): `seed`, `mnemonic`, `recovery phrase`, `recoveryphrase`, `secret phrase`, `seedphrase`, `wallet words`, `니모닉`, `시드`, `복구구문`, `복구 문구`.
- 내용 판정: 소문자로 바꾼 뒤 `[a-z]+` 토큰열에서, BIP-39 영어 단어 목록(2048개, `vault/data/bip39_english.txt` — BIP-0039 원문 저장소의 단어 목록, 라이선스·출처는 13 문서에 기록)에 속하는 토큰이 **연속 12개 이상**인 구간이 있으면 적중. 번호 매김(`1. abandon 2. ability …`)은 숫자가 토큰이 아니므로 자연히 무시된다.
- 이름 신호만 있고 내용 판정이 거짓 → 자산 아님(파일명에 `seed` 가 들어간 DB 시드 스크립트 등). 이름 신호 + 내용 확인 불가(dataless, TCC, PDF·이미지) → 자산, confidence 0.6, 방법 `filename`.
- 결정: 한국어 BIP-39 목록은 M3 에 넣지 않는다(영어 목록이 압도적 다수). 열린 질문 §19.

### 13.2 수집하지 않는 것 (V5)

| 값 | 저장 |
|---|---|
| `vault_assets.path`, `kind`, `masked_name`(stem 전체 가림), `detect_methods_json`, `confidence`, `status`, `first/last_seen_run_id`, `updated_at`, `permissions_mode`, `in_git_repo`/`git_tracked`/`git_ignored` | 예 — “존재·위치” |
| `fingerprint_sha256`, `key_fingerprint`, `cert_*` | **NULL 고정**(DB CHECK 가 없으므로 store 리포지토리 함수가 강제 + 안전 테스트) |
| `file_entries.sha256` | NULL 로 지운다(§7.1) |
| `vault_findings.line_no` | NULL. `rule_id` 는 `dc.seed.bip39`/`dc.seed.name` 뿐 |
| `user_label_enc`/`user_note_enc` | `vault.annotate` 가 label/note 를 받되 §12.1 3단계 검사에 더해 BIP-39 연속 12단어 검사도 한다 |
| 로그 | `asset_id` 와 `kind` 만. 같은 run 의 다른 로그 줄과 시각으로 경로를 추정할 수 없게, 시드 판정 로그 줄은 run 끝에 집계 1줄(`vault.seed_suspected count=N`)로만 남긴다 |
| gitleaks·내부 패턴 | 돌리지 않는다(§3.15 1단계) |
| 백업 상태 | 추적하지 않음(`--backup` 거부), `no_backup` 발견 사항 없음 |

- 메모리: 토큰 리스트는 판정 함수 안에서만 존재한다. 판정 결과는 불리언 하나.
- 리뷰 항목: 만든다(§8.3) — 사용자에게 알리는 것이 이 기능의 목적. 항목 `display_name` 은 마스킹 이름.

---

## 14. 제자리 인벤토리와 실행 차단의 근거

1. vault 에는 이동·복사·삭제 코드가 없다(V1, §16 정적 검사). 자산을 “Vault 폴더”로 모으는 기능은 만들지 않는다(PRD §7 비목표: 중앙 폴더 집결). 이유: 키 경로는 설정 파일(`~/.ssh/config` 의 `IdentityFile`, Xcode·Gradle 서명 설정, CI 스크립트, `GOOGLE_APPLICATION_CREDENTIALS`)이 참조한다 — 옮기면 서비스가 멈추고, 그 참조를 DayClose 가 모두 알 수 없다.
2. `allowed_actions`(02 §10.1)에 `trash`/`move`/`archive` 가 없다 → `decision.set` 이 `E_PROTECTED`.
3. 그룹 결정에서 자동 제외 + `W_PROTECTED_SKIPPED`(FR-SV-003).
4. `plan.create` 는 결정 시점과 무관하게 지금 보호 술어(§8.2)를 다시 평가해 자산을 제외한다(08 §4.2 V3).
5. executor 는 연산 직전 다시 평가하고, **디렉터리·패키지 연산은 그 안에 자산이 있는지**(DB 의 자산 경로 접두사 + 연산 직전의 제한된 이름 검사)를 본다(08 §7.2.1). 예: `~/Downloads/old-project/` 폴더를 휴지통에 넣는 결정은, 그 안에 `.env` 나 `id_rsa` 가 있으면 `E_PROTECTED` 로 건너뛴다.
6. 제안 문구는 “직접 옮기세요”로만 안내한다(§9.6). DayClose 가 키를 옮기는 날은, 경로 참조 갱신까지 책임질 수 있을 때(범위 밖)다.

---

## 15. 백업·암호화 보관 — 범위 밖 (2026-11-24 소유자 결정)

- NAS·SMB·원격 보관, age 암호화 업로드, Vault 원격 백업은 **비목표**다(PRD §7, §9.1 C6, FR-SV-009 삭제, 02 §3 “age 는 쓰지 않는다”). 이 문서는 그 설계를 하지 않는다. AGENTS §1: 확정 사항을 다시 열지 않는다.
- 결정: 로컬 “암호화 내보내기”(자산을 암호화된 파일 하나로 묶어 사용자가 직접 보관)도 만들지 않는다. 이유: 그 기능은 DayClose 가 모든 개인키의 사본을 한곳에 만드는 기능이라 “제자리 인벤토리”(§14)와 정면으로 충돌하고, 암호 관리·복구 검증을 다시 들여온다. 사용자에게는 §9.6 의 `no_backup` 문구로 기존 도구(비밀번호 관리자, 암호화된 외장 디스크 이미지)를 안내한다.
- 남는 것: `backup_status` 는 사용자 표시로만 갱신(§12.3), `no_backup` 발견 사항은 사용자가 스스로 백업하도록 알리는 장치.
- `archive` 동작(로컬/외장 `archive.root`, 08)은 보안 자산에 허용되지 않는다(02 §10.1). 따라서 DayClose 는 어떤 경로로도 보안 자산의 사본을 만들지 않는다 — 이 문서의 안전 테스트가 이 성질을 고정한다(“자산 엔트리를 `src` 로 하는 `plan_operations` 행 0”, “executor 의 복사 함수가 자산 경로로 호출되지 않음”).
- 재도입 시 지켜야 할 조건(기록용, 설계 아님): 클라이언트 측 암호화 후에만 기기 밖 복사, 복호화 왕복 검증 후에만 “verified”, 암호화 키를 같은 사본 옆에 두지 않음, 시드·복구 코드 제외, 원본 경로 불변. 이 조건을 바꾸려면 PRD §7 부터 고친다.

---

## 16. M3 읽기 전용 증명

M3(그리고 M4)에서 사용자 파일이 한 바이트도 바뀌지 않는다는 것을 아래 5겹으로 보인다. 각 항목은 11 문서의 `tests/safety/` 테스트 이름과 1:1.

| # | 증명 | 방법 | 테스트 |
|---|---|---|---|
| P1 | **변경 코드가 존재하지 않는다** | M3~M4 빌드의 `dayclose/executor/` 는 빈 패키지(또는 미존재). 정적 검사(08 §15 의 AST 규칙)가 `executor/` 밖의 변경 호출 0 을 확인하고, M5 이전에는 추가로 **`executor/` 안에도** 변경 호출 0 을 확인한다(`roadmap_milestone < 5` 분기, `core/pyproject.toml` 의 `[tool.dayclose] milestone` 값). | `test_no_mutation_outside_executor`, `test_executor_empty_before_m5` |
| P2 | **vault 의 열기 플래그** | AST: `vault/` 안의 `open(` 호출은 모드 리터럴 `'rb'` 만, `os.open(` 은 `vault/io.py` 한 곳에서 플래그 상수 `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC` 만(`O_WRONLY`, `O_RDWR`, `O_CREAT`, `O_TRUNC`, `O_APPEND` 이름 등장 금지). `shutil`, `tempfile`, `subprocess`, `xattr`, `os.utime`, `os.chmod`, `os.chown`, `os.chflags`, `Path.write_*`/`touch`/`mkdir`/`unlink`/`rename`/`replace`/`rmdir`/`chmod` 사용 금지. `ctypes` 는 `common/fsmeta.py` 에서만, 바인딩 심볼 허용 목록(`acl_get_link_np`, `acl_to_text`, `acl_free`, `statfs`)만. | `test_vault_static_readonly` |
| P3 | **서브프로세스 부작용 없음** | `run_tool` 호출을 가로채 vault 단계의 argv 를 기록하고 허용 형태만 통과: `gitleaks stdin …`(§5.1 고정 argv), `git -C R -c core.fsmonitor=false … (ls-files|check-ignore|log --all -1 --format=%H)`. `gitleaks dir`/`git status`/`git add`/`git update-index` 등은 실패. | `test_vault_subprocess_allowlist` |
| P4 | **실행 전후 스냅샷 동일** | 샌드박스 픽스처 트리(모든 kind 의 가짜 자산, 저장소 2개 — 하나는 `.env` 추적)에서 `scan run`(전체 collectors) 전후로 각 경로의 (type, size, mtime_ns, ctime_ns, mode, uid, gid, st_flags, xattr 이름·값 해시, 내용 SHA-256, 심볼릭 링크 대상) 비교 → 완전 일치. 저장소의 `.git/index`, `.git/` 전체 트리도 포함. **atime 은 비교에서 제외**(읽기는 atime 을 바꿀 수 있고, 이는 내용·메타데이터 변경이 아니다 — 명시적 예외). | `test_fr_sv_m3_scan_is_readonly_snapshot` |
| P5 | **커널 강제 쓰기 거부 하에서 동작** | 같은 시나리오를 `sandbox-exec -p '(version 1)(allow default)(deny file-write* (subpath "<sandbox>/user"))'` 아래 실행 → 정상 완료(`ok=true`)하고, 쓰기 시도가 있었다면 EPERM 으로 실패했어야 하므로 “성공 + 경고 없음”이 곧 쓰기 시도 0 의 증거. (실측: 이 머신에서 `sandbox-exec` 가 해당 경로 쓰기를 `Operation not permitted` 로 거부하고 바깥 쓰기는 허용함을 확인.) `sandbox-exec` 는 사용 중단 표기된 도구라, 없어지면 이 테스트는 `pytest.skip(reason="sandbox-exec unavailable")` 사유 명시 건너뜀(AGENTS DoD 의 “사유 있는 skip”). | `test_fr_sv_m3_scan_under_kernel_write_deny` |

추가: M3 의 DB 쓰기 명령(`scan.run`, `vault.annotate`)은 `DAYCLOSE_HOME` 아래만 쓴다 — P5 의 프로파일에 `(deny file-write* (subpath "<sandbox>/user"))` 만 있고 `home/` 은 허용되므로 같은 테스트가 이를 함께 보인다.

---

## 17. 비밀 누출 경로와 통제

| # | 누출 경로 | 통제 | 검증 |
|---|---|---|---|
| L1 | 로그에 경로·이름·값 | 로그 호출부는 `asset_id`/`kind`/개수만(02 §13 1차), `RedactingFilter`(2차) | 누출 스캐너(11): 픽스처의 모든 비밀값·실제 파일명·경로 문자열이 `core.log` 에 0회 |
| L2 | 봉투 `details`·`message` | 02 §5.4 규칙 + vault 오류 생성 함수가 ID 만 받음 | 누출 스캐너: 모든 명령 stdout |
| L3 | DB 에 비밀 | 저장 컬럼 목록(§2.3), 매치 미저장, 파일 지문 HMAC(§7.1), subject·메모 암호화 | `sqlite3 .dump` 에 비밀값·subject 평문 0, 시드 행의 지문·줄 번호 NULL |
| L4 | gitleaks 출력 | `--redact` + 허용 키만 파싱 + 비-REDACTED 시 전체 폐기 + stderr 미기록 | 가짜 gitleaks(테스트 더블)가 `Match` 에 원문을 넣으면 결과 0 + `redaction_failed` |
| L5 | 예외 메시지·트레이스백 | §2.3 예외 규칙(`from None`, `str(e)` 금지) | 파서에 비밀 포함 깨진 입력을 넣고 `--log-level debug` 로그·봉투에 원문 0 |
| L6 | 서브프로세스 argv | gitleaks 는 stdin(경로·내용 argv 없음). git argv 의 경로는 사용자 자신의 프로세스 | P3 |
| L7 | 임시 파일 | vault 는 임시 파일을 만들지 않는다(`tempfile` 금지, P2) | P2 |
| L8 | 썸네일·Quick Look 캐시 | `preview_policy=metadata_only`(06 §3.1) → 앱은 썸네일·미리보기 없음(03, FR-VR-006) | FR-VR-006 AC |
| L9 | AI 페이로드 | `ai_policy=none`(07 게이트) | FR-PM-005 게이트 테스트 |
| L10 | 리포트(md/json) | 마스킹 이름·표시 경로만(§10.3) | FR-DR-009 AC |
| L11 | 에이전트 컨텍스트 | `skill`/`mcp` 채널 null 규칙(§11.5) | 채널별 계약 픽스처 |
| L12 | 사용자 메모에 비밀 붙여넣기 | §12.1 3단계 거부 | 단위 테스트 |
| L13 | 시드 파생값 | §13.2 | FR-SV-008 AC |
| L14 | 개발 중 에이전트가 실제 키를 열어 봄 | AGENTS §3.4·§3.6: 실제 `~/.ssh` 등 접근 금지, 픽스처는 런타임 생성 | 코드 리뷰(Security 패스) |
| L15 | 커밋에 가짜가 아닌 키 | AGENTS §3.6 `gitleaks git --staged` | 개발 절차 |

---

## 18. 픽스처 요구 (11 문서가 구현)

`tests/fixtures/secrets.py` 는 테스트 실행 시 `tmp_path` 아래에 생성한다(저장소에 완성된 비밀 문자열 없음 — 토큰은 접두사와 무작위 부분을 런타임에 조합, §4 의 자리표시자 단어 금지).

| 픽스처 | 기대 |
|---|---|
| 확장자 없는 OpenSSH 개인키(암호 없음/있음 각 1) | `ssh_private_key`, 둘 다 `key_fingerprint` 있음, 암호 있는 쪽 `needs_password=1` |
| `.key` 이름의 ZIP(Keynote 흉내) | 비자산 |
| 23일 남은 자체 서명 인증서 PEM/DER | `certificate`, `expiring_soon` `high`, `cert_issuer='(self-signed)'` |
| 5일 남은 인증서 | `expiring_soon` `critical` |
| 빈 암호 `.p12`, 암호 `.p12`, `-legacy` `.p12` | 빈 암호: 만료 있음 / 나머지: `needs_password=1`, 만료 `unknown` |
| Apple 형식 `AuthKey_XXXXXXXXXX.p8`(EC P-256) | `apple_signing`, `masked_name='AuthKey_••••••.p8'` |
| 가짜 `.mobileprovision`(DER 바이트 + 내장 plist) | `apple_signing`, 만료 = `ExpirationDate` |
| JKS(테스트가 `keytool` 없이 바이트로 직접 생성) + `key.properties` | `android_keystore` ×2, JKS 만료 추출 |
| 저장소에 추적된 `.env` / 무시된 `.env` / 과거 커밋에만 있는 `.env` | `tracked_in_git` `critical`(tracked·history) / 없음 |
| 같은 키 3곳 복사(PEM, 다른 디렉터리) + 같은 inode 하드 링크 1개 | `duplicate` 3개(하드 링크는 세지 않음) |
| `notes.txt` 속 가짜 AWS 키 | `cloud_credential`, `plaintext_secret` `high`, gitleaks 없을 때도 |
| `google-services.json` | 비자산 |
| BIP-39 12단어 `my seed words.txt` | `crypto_seed_suspected`, 지문·줄 번호 NULL, `file_entries.sha256` NULL, 로그에 경로 0 |
| `mode 0644` SSH 키, `0777` `~/.ssh` | `bad_permissions` `high` |
| NPKI 디렉터리 `NPKI/yessign/USER/cn=홍길동()0011…/signCert.der+signPri.key` | `npki_cert` ×2, 표시 경로에 실명 없음, subject 암호화 |
| dataless 플래그 주입 `id_rsa` | 읽기 호출 0, confidence 0.6, `W_DATALESS_SKIPPED` |
| FIFO 이름 `id_rsa` | 멈추지 않음, 비자산 |

---

## 19. 결정·변경 요청·남은 위험·열린 질문

### 19.1 이 문서의 결정 요약

1. Keychain 항목은 인벤토리하지 않는다(§0).
2. projects 루트는 이름·구조 검사만, 기준선 run 은 일반 내용 검사 생략(§2.1, §2.2).
3. 홈 직속 자격 파일은 코드 상수 목록으로 `entry_id=NULL` 자산(§2.1.2).
4. 백로그는 `app_meta.vault.backlog_entry_ids`(§2.4).
5. 인증서 시각은 epoch ms(§3.1). 자체 서명 issuer 는 `(self-signed)`(§6.1).
6. PKCS#12 는 `None`/빈 암호만 시도, openssl CLI 미사용(§3.4).
7. JKS 인증서 체인을 암호 없이 읽는다(§3.8). `debug.keystore` 예외.
8. Firebase 클라이언트 설정 파일은 비자산(§3.6).
9. `recovery_codes`·Solana 평문 키는 시드와 같이 지문 없음(§3.10, §3.12).
10. 자산 임계값 0.5, `generic-api-key` 단독은 엔트리 `info`(§3.15).
11. gitleaks 는 `stdin` 모드·고정 argv·대상 설정 무시(§5).
12. 파일 지문은 키 입력 HMAC(§7.1). 자산 엔트리의 `file_entries.sha256` 은 지운다.
13. 한 번 자산이면 내용이 바뀌어도 자산 유지, `retired` 도 보호(§8.1, §8.2).
14. 항목 확인 결정이 그 자산의 열린 발견 사항을 확인 처리(§8.3).
15. `no_backup` 7일 유예, `expired` 는 `warn`(§9.2).
16. `skill`/`mcp` 채널에서 실제 경로·이름·subject·메모는 null(§11.5).
17. 메모에 비밀 패턴이면 거부(§12.1).

### 19.2 기준 문서 변경 요청 — 반영 상태 (2026-11-24 재조정 후)

| # | 요청 | 상태 |
|---|---|---|
| R1 | `vault.annotate --status active\|retired` | 반영(02 §5.3). §12 |
| R2 | 발견 사항 단위 확인 명령 | **거부** — 전용 명령 없음. 항목의 `acknowledge`/`keep`/`keep_always` 결정이 그 자산의 열린 발견 사항을 확인 처리(§8.3, 02 §5.3). 앱(03)의 발견 사항별 [확인] 은 해당 자산 항목의 `decision.set --action acknowledge` 로 매핑해야 한다 → 03 확인 필요 |
| R3 | `run_tool(tool, args, timeout, input_bytes, env)`, 절대경로 허용 목록, 고정 환경 | 반영(02 §6). §5.1, §9.3. 남은 세부: `system_path` 가 Homebrew 후보의 `realpath` 를 접두사 안으로 제한하는지 02/10 에 명시 필요 |
| R4 | `extra_paths` 에 `~/.azure`, `~/.docker`, `~/.config/gh` | 반영(02 §9). §2.1.1, §2.1.2 |
| R5 | `fingerprint_sha256` = 키 입력 HMAC, 인증서 시각 epoch ms | 반영(06 §5.3) |
| R6 | 복구 수단 행의 파생값 NULL CHECK | 반영 — `crypto_seed_suspected` 와 `recovery_codes` 둘 다(06 §5.3) |
| R7 | vault 판정 전 해시 비저장 | 반영(06 §6) |
| R8 | `skill`/`mcp` 채널에서 보호 항목 `path` null | 10 문서 소관 — 확인 필요 |
| R9 | 보존 기간 | 반영(06 §8: `missing` 365일, `resolved` 발견 사항 180일). §8.4 |
| — | `app_meta` 키 `vault.backlog_entry_ids` | 반영(06 §5.1 키 목록) |
| R10 | (리뷰 #6) `blocked_reason` 에 `secret_content`, 02 §10.1 에 “`sensitivity=secret` → archive/move 불가·그룹 제외” | 02·06 소관 — §8.2 |
| R11 | (리뷰 #19d) 06 §7 백업 규칙 예외: 0003 적용 성공 후 `pre-v3` 백업 즉시 삭제 + 새 백업, 0003 직후 텍스트·이름 신호 파일의 `file_entries.sha256` NULL 처리. 04: M2 해시 저장 전에 `vault.signals.name_matches` 확인(이 함수는 M2 에 먼저 구현) | §7.1 |
| R12 | (리뷰 C) 06 §5.2 `stats_json` 키 `vault_expiring_soon`, `vault_expiring_critical`. 09: 일일 알림의 만료 줄과 ≤7일 별도 알림 | §9.5-5·6 |

### 19.3 남은 위험 (닫지 못함)

1. 셸 권한이 있는 에이전트는 `--channel cli` 로 실제 경로를 얻거나 파일을 직접 읽을 수 있다. DayClose 는 같은 사용자 권한의 프로세스를 막을 수 없다(§1). 통제는 Skill/MCP 계약(10)과 AGENTS 규칙뿐.
2. Python 문자열은 메모리에서 지워지지 않는다(`del` 은 참조만 끊음). 스왑·크래시 리포트·코어 덤프에 남을 수 있다. FileVault 전제.
3. `--channel` 자기 신고 — MCP 이전에는 §11.5 가 위생 규칙 수준.
4. 이미지(스크린샷) 속 키·시드는 M3 에서 탐지하지 못한다(M6 OCR → 07 민감도, 05 의 패턴을 재사용하도록 07 에 요청).
5. “데스크탑 및 문서” iCloud 동기화가 켜진 경우 `~/Desktop`·`~/Documents` 의 키는 기기 밖 동기화 중이지만, 경로만으로는 알 수 없어 `exposed_location` 이 `warn`(약)으로만 나온다.
6. gitleaks 기본 규칙은 설치된 버전에 따라 바뀐다 — 같은 파일의 결과가 업그레이드 후 달라질 수 있다(규칙 ID 변경 → 발견 사항 해소·재생성).
7. 암호 걸린 `.p12`(대부분의 Apple 내보내기)는 만료일을 알 수 없다 — 사용자가 `--expires` 를 넣지 않으면 만료 경고가 없다. Apple 개발자 인증서는 짝인 `.cer` 가 같은 기기에 있으면 그쪽으로 경고된다.

### 19.4 열린 질문 (PRD §9.2 에 추가 제안)

1. 설치 후 과거 파일 전수 내용 검사(`vault scan --full` 같은 명시적 명령)를 둘지 — 현재는 없음(§2.2).
2. 한국어 BIP-39 단어 목록 포함 여부(§13.1).
3. 비암호화 인증서 가방을 가진 암호 `.p12` 의 만료를 읽기 위한 자체 DER 파서를 둘지(§3.4).
