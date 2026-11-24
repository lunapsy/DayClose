# 08 — 안전 실행 (SAFE EXECUTION): 계획 → 승인 → 실행 → 되돌리기

> 범위: `core/src/dayclose/plan/`(결정→연산, `plan_hash`, 승인 기록)과 `core/src/dayclose/executor/`(유일하게 사용자 파일을 바꾸는 모듈). 명령 `plan.create/show/list/approve/apply/cancel/undo/recover`, `audit.list`.
> 이름·enum·테이블·오류 코드는 `02-ARCHITECTURE.md`(§5, §7, §10, §11), `06-DATA-MODEL.md`(§4.4~4.5, §5.4)를 그대로 쓴다. 기준 문서에 없는 것이 필요하면 §19 에 “02/06 변경 요청”으로 적었다.
> 관련: 보호 등급 계산 `policy`(07, 02 §10.1), 보안 자산 판정 `05-SECURE-VAULT.md`, 엔트리·이동 판정 `04-FILE-INTELLIGENCE.md`, TCC·볼륨 프로브 `09-MACOS-INTEGRATION.md`, 명령 data 스키마 `10-CLI-SKILL-MCP.md`, 장애 주입·안전 스위트 `11-TEST-PLAN.md`, 승인 화면 `03-UI-UX-SPEC.md`.
> 마일스톤: M5(설계·가드·정적 검사는 M1부터 — 02 §2, 12). `rename` 연산은 M6.
> 실행 환경 사실은 2026-11-24 이 머신(macOS 26.6.2, Python 3.14.6)에서 임시 디렉터리로 확인한 것만 “실측”으로 표시했다.

---

## 0. 원칙과 위협 경계

이 엔진은 사용자의 파일을 옮기고 휴지통에 넣는다. 설계 목표는 하나다: **어떤 순서의 사건(크래시, 전원 차단, 외장 분리, 다른 앱의 동시 변경, 에이전트의 잘못된 호출)이 와도 파일이 사라지지 않고, 사람이 승인하지 않은 변경은 일어나지 않는다.**

다루는 위협:
- 승인 없이 실행되는 경로(에이전트·MCP·스케줄러·버그·테스트).
- 승인한 것과 다른 것이 실행되는 경로(계획 변경, 파일 바꿔치기, 목적지 경쟁, 대소문자·유니코드 충돌, 심볼릭 링크 교체).
- 실행 도중 중단(크래시·SIGKILL·전원·볼륨 분리)으로 인한 유실·이중 상태.
- 보호 대상(보안 자산·환자 자료·활성 저장소·iCloud)이 연산에 섞이는 경로.
- 테스트가 실제 사용자 파일을 건드리는 경로.

다루지 않는 위협(경계 — §17·§19 에서 남은 위험으로 명시): **같은 사용자 권한으로 임의 코드를 실행하는 적대적 프로세스**. 그런 프로세스는 DayClose 를 거치지 않고 `rm` 을 부를 수 있으므로 DayClose 의 승인 게이트로 막을 대상이 아니다. DayClose 가 보장하는 것은 “**문서화된 인터페이스(CLI·stdio·Skill·MCP)로만 행동하는 에이전트가 사람 없이 승인을 얻을 수 없다**”와 “우회가 일어났다면 흔적이 어긋난다(§6.6 감사 교차 검사)”이다.

---

## 1. 불변식

| ID | 불변식 | 강제 위치 |
|---|---|---|
| X1 | 사용자 파일 변경 시스템 호출은 `executor/fsops.py` 한 파일에만 있다. | 정적 검사 §15.2 |
| X2 | `fsops` 의 모든 공개 함수는 첫 문장에서 `_guard(경로들)`(샌드박스·금지 영역)를 호출한다. | 정적 검사 §15.2, 런타임 §15.1 |
| X3 | 실행되는 연산 = 승인된 plan 의 행. `approvals.plan_hash == plans.plan_hash == 지금 행들로 다시 계산한 해시` 일 때만 실행. | §7.1 |
| X4 | 승인 행은 사람 확인 수단(§6)을 거쳐서만 생긴다. MCP·스케줄러 채널은 승인 불가. | §6 |
| X5 | 덮어쓰기 없음: 모든 이름변경은 `renameatx_np(…, RENAME_EXCL)`, 모든 파일 생성은 `O_CREAT|O_EXCL`. `os.rename`/`os.replace` 는 사용자 파일에 쓰지 않는다(실측: `os.rename` 은 기존 목적지를 조용히 덮어쓴다). | §3.3 |
| X6 | 영구 삭제 없음. 사용자 파일이 사라지는 경로는 (a) 같은 볼륨 휴지통으로의 이름변경, (b) **검증된 사본이 목적지에 확정된 뒤**의 원본 제거 둘뿐. 휴지통 비우기 기능 없음. | §7.4 |
| X7 | 연산은 `running` 을 **내구적으로 커밋한 뒤** 파일 시스템을 건드리고, 결과를 확인한 뒤 `done` 을 커밋한다. 크래시 후 상태는 `plan.recover` 가 실제 파일 상태로만 판정한다. | §7.3, §10 |
| X8 | 연산 직전 사전조건 재검증: 원본 동일성·크기·mtime, 보호 등급, 목적지 비어 있음, 볼륨 도달 가능. 하나라도 어긋나면 그 연산은 실행하지 않는다. | §7.2 |
| X9 | 보호 대상을 담은 디렉터리·패키지는 통째로 옮기거나 휴지통에 넣지 않는다. | §7.2 F7 |
| X10 | `plan.recover` 는 원본을 지우지 않는다. 지우는 것은 DayClose 가 만든 임시 파일·묘비(tombstone)와, 원본과 내용이 같음이 확인된 사본뿐. | §10 |
| X11 | 테스트(`pytest` 실행 중)에서 `DAYCLOSE_SANDBOX` 밖 경로에 대한 `fsops` 호출은 무조건 실패. | §15.1 |
| X12 | dataless(iCloud 미다운로드) 파일은 어떤 연산의 원본·목적지도 아니다. **iCloud 동기화 경로**(`scan_roots.icloud_synced=1` 루트 아래, 그리고 §3.5 의 경로 규칙)는 목적지가 될 수 없고, 원본으로는 02 §10.1 예외 2 의 해제 게이트가 참이고 `icloud_propagates=1` 로 계획·승인된 **`trash`** 연산만 허용(C11, FR-EX-008). `move`/`archive`/`rename` 은 불가. | §4.3, §7.2 F5 |

---

## 2. 전체 흐름

```
decision.set (trash|move|archive)          파일 변경 없음 (06 §4.1: proposed → decided)
        │
plan.create ── 결정을 연산으로, 목적지·충돌 이름 확정, plan_hash ──▶ plans(draft), plan_operations(pending), 항목 planned
        │       (불변. 바꾸려면 cancel 후 새로)
plan.show ──── 사람이 볼 요약 + 연산 목록 + plan_hash
        │
plan.approve ─ 사람 확인(app_button | cli_tty | native_dialog | test) ──▶ approvals, plans(approved)
        │
plan.apply ─── 전역 검사 → 연산마다: 사전조건 → running 커밋 → 파일 시스템 → 확인 → done 커밋
        │       ──▶ plans(completed | partial | failed), 항목 executed | stale | failed
        │
plan.undo ──── 연산 역순으로 원위치 ──▶ plans(undone | partially_undone), 항목 undone
plan.recover ─ 크래시 후 running 연산을 실제 상태로 정합화
```

모든 단계는 쓰기 잠금 `state.lock`(02 §7)을 잡는다. 예외: `plan.show`, `plan.list`, `plan.apply --dry-run`(읽기 전용, §7.8), 그리고 `plan.approve` 의 사람 확인 대기 구간(§6.1 — 잠금 밖에서 기다린 뒤 잠금을 잡고 재검증).

---

## 3. 파일 시스템 기초 (`executor/fsops.py`, `common/fsmeta.py`)

### 3.1 동일성

- 객체 동일성 = `(st_dev, st_ino)` + 종류(`file`/`dir`/`symlink`/`package` — 06 `entry_kind`). 경로는 동일성이 아니다(06 §1).
- “원본이 계획 시점과 같다” = `lstat` 결과의 `(st_dev, st_ino, kind, st_size, st_mtime_ns)` 가 `plan_operations.(pre_dev, pre_inode, —, pre_size, pre_mtime_ns)` 와 모두 같음. 종류는 계획 시점 `file_entries.kind` 를 정규화 JSON(§5)에 넣어 고정한다.
- 경로 구성요소 교체 경쟁(부모 디렉터리가 그 사이 심볼릭 링크로 바뀜)을 막기 위해, 원본 확인과 이름변경은 **부모 디렉터리 fd** 기준으로 한다: `pfd = os.open(parent, O_RDONLY|O_DIRECTORY|O_CLOEXEC)` → `os.stat(name, dir_fd=pfd, follow_symlinks=False)` 로 동일성 확인 → 같은 `pfd` 로 `renameatx_np`. 확인과 실행 사이에 경로를 다시 해석하지 않는다.

### 3.2 볼륨 정보

`common/fsmeta.volume_info(path) -> {dev, mount_point, fstype, read_only, local, case_sensitive}`:
- `ctypes` 로 libSystem `statfs` → `f_mntonname`, `f_fstypename`, `f_flags`(`MNT_RDONLY=0x1`, `MNT_LOCAL=0x1000`).
- 대소문자 구분: `os.pathconf(dir, 11)`(`_PC_CASE_SENSITIVE` = 11, SDK `sys/unistd.h`. Python `os.pathconf_names` 에는 이 이름이 없어 숫자로 호출 — 실측: `/Users` 와 임시 디렉터리 모두 0 = 구분 안 함).
- 네트워크 파일 시스템: `fstype ∈ {smbfs, afpfs, nfs, webdav, cifs, ftp}` 또는 `local=False`. 결정: 네트워크 볼륨은 어떤 연산의 원본·목적지도 아니다(`E_VOLUME_UNAVAILABLE`, `details.reason="network_fs_unsupported"`). 이유: NAS·SMB 는 비목표(PRD §7)이고, 휴지통·원자적 이름변경·fsync 의미가 보장되지 않는다.
- `/Volumes/*` 아래 경로는 `volume_info` 전에 반드시 `common/paths.probe(path, timeout=config.scan.volume_probe_timeout_s)` 를 통과해야 한다(02 §10.5). 시간 초과 → `E_VOLUME_TIMEOUT`, 경로 없음 → `E_VOLUME_UNAVAILABLE`.

### 3.3 원자적 무덮어쓰기 이름변경

```python
# 개념 코드 — fsops 안에서만
libc.renameatx_np(src_dir_fd, src_name, dst_dir_fd, dst_name, RENAME_EXCL)   # RENAME_EXCL = 0x00000004 (SDK sys/stdio.h)
```

실측: 기존 목적지가 있으면 `-1`/`EEXIST`, 없으면 성공. 같은 파일의 **대소문자만 다른** 이름변경(`a` → `A`, 대소문자 구분 안 하는 APFS)은 `RENAME_EXCL` 로도 성공한다 → `rename` 연산(M6)의 대소문자 변경이 별도 2단계 없이 가능.
결과 errno 처리는 §16.

### 3.4 휴지통 위치

| 원본 볼륨 | 휴지통 디렉터리 | 없을 때 |
|---|---|---|
| 홈과 같은 장치(`st_dev == lstat(~).st_dev`) | `~/.Trash` | 만들지 않는다 → `E_PERMISSION` `{"reason":"trash_unavailable"}` |
| 그 외 로컬 볼륨 | `<mount_point>/.Trashes/<uid>` | `.Trashes` 가 있으면 `<uid>` 디렉터리만 `mkdir(0o700)`. `.Trashes` 자체가 없으면 만들지 않는다 → `E_PERMISSION` `{"reason":"trash_unavailable"}`. 이유: 볼륨 최상위에 디렉터리를 만드는 것은 사용자가 승인한 연산이 아니다 |
| 읽기 전용·네트워크 | — | `E_PERMISSION` `{"reason":"read_only"}` / `E_VOLUME_UNAVAILABLE` |

- 샌드박스(`DAYCLOSE_SANDBOX` 설정): 홈 장치 = `<sandbox>/user` 의 장치, 휴지통 = `<sandbox>/user/.Trash`(테스트 픽스처가 만든다). 다른 볼륨 시험은 테스트가 `hdiutil attach -mountpoint <sandbox>/vol2` 로 붙인 디스크 이미지(11 문서) — 그 마운트 지점의 `.Trashes/<uid>`.
- 휴지통은 항상 원본과 같은 볼륨이다. 따라서 `trash` 는 언제나 같은 장치 이름변경이고 복사가 없다.
- 결정: Finder 의 “되돌려 놓기(Put Back)”는 지원하지 않는다. 이유: Finder 는 그 정보를 휴지통의 `.DS_Store` 에 기록하는데, 그 형식을 쓰는 것은 비공개 형식 조작이다. 되돌리기는 `plan.undo` 로만(원래 경로는 `plan_operations.src_path`). `NSFileManager.trashItem` 을 쓰지 않는 이유: Swift/Objective-C 코드가 사용자 파일을 바꾸지 않는다는 규칙(02 §6, AGENTS §3.2)과 엔진 단일화(02 §4).

### 3.5 허용 영역 (원본·목적지)

**운영 모드**(샌드박스 아님): 모든 원본·목적지·임시·휴지통 경로는 `Path.home()` 아래이거나 `/Volumes/<이름>/` 아래여야 한다. 그 밖(`/`, `/System`, `/Library`, `/Applications`, `/usr`, `/private` …) → `E_SANDBOX_VIOLATION` 이 아니라 `E_PATH_OUTSIDE_ROOTS`. 추가로 아래는 어디에 있든 금지 영역:

- `DAYCLOSE_HOME`, `~/Library/Logs/DayClose`, `~/Library/Caches/DayClose` 아래
- 휴지통 디렉터리 안을 **원본**으로(휴지통 안의 파일을 다시 옮기는 연산 — undo 제외)
- 경로 구성요소에 `.git` 이 있는 곳
- 패키지 안(조상 구성요소 중 하나가 04 의 패키지 확장자 — `.app`, `.bundle`, `.framework`, `.photoslibrary`, `.musiclibrary`, `.tvlibrary`, `.xcodeproj`, `.xcworkspace`, `.pages`, `.numbers`, `.key`(디렉터리), `.rtfd`, `.sparsebundle`, `.lproj` 등 — 목록은 04 가 소유)
- `vault_extra` 루트 안
- iCloud 동기화 경로: `icloud_synced=1` 루트 아래, 그리고 루트 등록 여부와 무관하게 `~/Library/Mobile Documents/`, `~/Library/CloudStorage/` 아래. 목적지로는 언제나 금지, 원본으로는 X12 의 iCloud `trash` 예외만.

**`move` 목적지 허용 목록**(`E_PATH_OUTSIDE_ROOTS` 판단): 활성 스캔 루트 중 `kind ∈ {downloads, desktop, screenshots, documents, projects, custom}` 의 경로 아래, 또는 `config.projects.roots` 아래. `icloud_synced=1` 루트·`vault_extra` 루트는 목적지가 될 수 없다. `archive.root` 아래는 `move` 의 목적지가 될 수 없다(보관은 `archive` 연산으로만 — 보관 폴더 내부 구조를 엔진만 관리).

**`archive` 목적지**: `config.archive.root` 아래만(§4.4).

---

## 4. `plan.create` — 결정을 연산으로

`dayclose plan create (--items ITEM_ID,... | --all-decided)`. W. 파일 변경 없음(FR-EX-001 AC: 실행 전후 샌드박스 트리 해시 동일). 읽기는 `lstat`·`statfs`·(볼륨 간일 때) 원본 내용 해시뿐.

### 4.1 대상 선정

1. 잠금 획득. `running` 상태 연산이 하나라도 있으면 `E_INVALID_STATE` `{"reason":"recover_required"}`(§10).
2. 후보:
   - `--items`: 각 ID 가 존재해야 하고(`E_NOT_FOUND`), `state ∈ {decided, failed}` 이고 `decided_action ∈ {trash, move, archive}` 이어야 한다. 하나라도 어긋나면 **명령 전체** `E_INVALID_STATE`(details 에 해당 `item_id` 와 현재 상태). 부분 계획을 만들지 않는다.
   - `--all-decided`: 위 조건을 만족하는 열린 항목 전부, `item_id` 오름차순. 2,000개 초과면 앞 2,000개만 + `W_TRUNCATED`. 결정: 한 계획 최대 2,000 연산. 이유: 승인 화면·대화상자에서 사람이 검토할 수 있는 규모의 상한, 해시 계산·크래시 복구 범위 제한.
3. 대상이 0개 → `E_INVALID_STATE` `{"reason":"no_eligible_items"}`. 계획 행을 만들지 않는다.

### 4.2 항목별 검증 (실패한 항목은 “제외 목록”으로, 나머지로 계획 생성)

각 항목에 대해 순서대로. 첫 실패가 제외 사유다.

| # | 검사 | 실패 시 제외 코드 | 항목 상태 변화 |
|---|---|---|---|
| V1 | 대상 엔트리를 `lstat`: 없음, 또는 `(dev, inode)` 가 `review_items.subject_key`/`file_entries` 와 다름 | `E_STALE` | `decided → stale`(06 §4.1, `closed_reason='subject_gone'`). `failed` 항목은 그대로 |
| V2 | 결정 이후 내용이 바뀜: `st_mtime_ns > decided_at(ms)×10⁶` 또는 `st_size != file_entries.size_bytes` | `E_STALE` | `decided` 유지 + `last_error_code='E_STALE'`(06 §4.1: “실행 대기 — 내용이 바뀜, 다시 판단 필요”). 이 표시가 있는 항목은 이후 `plan.create` 에서도 V2 와 같이 제외되며, 사용자가 `decision.undo` 후 재결정(또는 `decision.set` 재결정)해야 표시가 지워진다. 이유: 사용자가 본 적 없는 내용을 실행 대상으로 만들지 않는다 |
| V3 | 지금 `policy` 로 다시 계산한 `allowed_actions` 에 결정 동작이 없음(보안 자산이 됨, 환자 패턴, 활성 저장소, 사용자 규칙 추가, `dataless`·`icloud_synced` — 02 §5.6 `blocked_reasons`) | `E_PROTECTED`(`details.reason` = 해당 `blocked_reason` 코드) | 변화 없음 |
| V4 | 다른 활성 계획(`draft`/`approved`/`executing`)이 이 항목을 갖고 있음 | `E_INVALID_STATE` | 변화 없음 |
| V5 | 원본이 허용 영역(§3.5) 밖 | `E_PATH_OUTSIDE_ROOTS` | 변화 없음 |
| V6 | 원본 볼륨이 네트워크·읽기 전용, 또는 프로브 실패 | `E_VOLUME_UNAVAILABLE`/`E_VOLUME_TIMEOUT` | 변화 없음 |
| V7 | 목적지 결정(§4.3~4.4) 실패 | 각 절의 코드 | 변화 없음 |
| V8 | 이 항목의 원본이 같은 계획의 다른 디렉터리 연산 원본 안에 있음(부모 폴더도 휴지통, 자식 파일도 휴지통) | `E_INVALID_STATE` `{"reason":"nested_in_plan"}` — 바깥 디렉터리 연산을 남기고 안쪽을 제외 | 변화 없음 |
| V9 | 목적지가 같은 계획의 다른 연산 원본 안 | `E_INVALID_STATE` `{"reason":"dest_inside_other_src"}` | 변화 없음 |

`--items` 로 지정했는데 모든 항목이 제외되면 `E_INVALID_STATE` `{"reason":"no_eligible_items","excluded":[…]}`.

### 4.3 `trash` 의 목적지

- **iCloud 동기화 원본**(C11): 원본이 iCloud 동기화 경로(루트 실효값 `icloud_synced=1`, §3.5 경로 규칙, 또는 §9.2 의 실시간 신호 중 하나라도)에 있으면 — V3 가 이미 해제 게이트(02 §10.1 예외 2: `policy/icloud.py: TRASH_UNLOCK_VERIFIED` **그리고** `config.icloud.allow_trash`)·dataless 아님·항목 단위 사용자 결정(`actor='user'`, `scope='item'`)을 확인했다 — 그 연산은 `icloud_propagates=1`. 하나라도 아니면 V3 에서 `E_PROTECTED`(`icloud_synced`/`dataless`)로 제외. `icloud_propagates` 는 정규 객체(§5.1)에 들어가 승인이 이 사실을 덮는다. 휴지통은 홈 볼륨의 `~/.Trash`(iCloud Drive 의 로컬 사본은 Data 볼륨) — 이름변경으로 iCloud 밖으로 나가는 것이 곧 다른 기기에서의 삭제다.

- `dst_path = NULL`(06 주석대로 실행 시 결정, `actual_dst_path` 에 기록). 계획 단계에서는 휴지통 디렉터리 존재·쓰기 가능만 확인(§3.4 의 실패 → 제외 `E_PERMISSION`).
- `cross_device = 0` 고정.

### 4.4 `move` / `archive` 의 목적지

`move`: `decisions.dest_path` 를 해석한다.
1. 절대경로가 아니거나 NUL 을 포함하거나 구성요소에 `.`/`..` 가 있으면 제외 `E_USAGE`. `~` 는 `decision.set` 시점에 이미 확장되어 있어야 한다(10).
2. `dest_path` 가 `/` 로 끝나거나 현재 디렉터리이면 → 목적지 디렉터리 `D = dest_path`, 이름 `N = basename(src)`.
   그렇지 않으면 → `D = dirname(dest_path)`, `N = basename(dest_path)`.
3. `D` 의 가장 가까운 존재하는 조상 `A` 를 찾는다. `A` 가 디렉터리가 아니면 제외 `E_DEST_EXISTS`. 없는 구성요소(`A` 아래)는 **생성할 디렉터리 목록** `create_dirs` 가 된다. 최대 3단계, 초과면 제외 `E_USAGE` `{"reason":"too_many_new_dirs"}`.
4. `realpath(A)` 를 계산하고 `D` 를 `realpath(A) + 나머지 구성요소` 로 **해석된 경로**로 바꾼다. 결정: 계획에는 심볼릭 링크가 없는 경로를 저장한다(예: `~/dev` 가 외장으로 가는 링크여도 실제 경로로). 이유: 실행 시 “경로에 새 링크가 생김”을 `realpath(parent) == parent` 한 번으로 잡기 위함.
5. `D` 가 허용 목록(§3.5) 밖 → 제외 `E_PATH_OUTSIDE_ROOTS`. 원본이 디렉터리이고 `D` 가 원본 안 → 제외 `E_INVALID_STATE` `{"reason":"dest_inside_src"}`.
6. 이름 `N` 검증: UTF-8 255바이트 이하, `/`·NUL 없음, `.`/`..` 아님, `.dayclose-` 를 포함하지 않음(엔진 임시 이름 예약). 실패 → 제외 `E_USAGE`.
7. 충돌 이름 결정(§8) → `dst_path = D/N'`.
8. `cross_device = (pre_dev != volume_info(A).dev)`. 볼륨 간이면 §4.5 의 해시.

`archive`: `decisions.dest_path` 는 NULL(06). `config.archive.root = R` 을 쓴다.
1. `R` 이 비어 있으면 **명령 전체** `E_ARCHIVE_TARGET_MISSING`(FR-AB-001 AC). 이 검사는 4.2 이전에 한 번만(archive 항목이 하나라도 있을 때).
2. `R` 검증(하나라도 실패 → 명령 전체 `E_ARCHIVE_TARGET_MISSING`, details reason): 절대경로, 존재하는 디렉터리(`R` 자체는 만들지 않는다), 허용 영역(§3.5) 안, 네트워크 볼륨 아님, iCloud 아님, **활성 스캔 루트의 안도 바깥도 아님**(`R` 이 루트 안이면 보관된 파일이 다음 스캔에서 새 파일로 다시 잡혀 무한 반복; 루트를 포함하면 루트 전체가 보관 폴더 하위가 됨 — 둘 다 `E_CONFIG_INVALID` 성격이지만 02 §11 의 정의대로 `E_ARCHIVE_TARGET_MISSING` + `details.reason="overlaps_scan_root"`), `DAYCLOSE_HOME` 과 겹치지 않음. `/Volumes/*` 면 프로브.
3. `D = R/<YYYY>/<MM>`, 연·월 = 원본 `pre_mtime_ns` 의 로컬 날짜(결정: 파일 자신의 날짜. 02 §9 의 배치 규칙 `<root>/<YYYY>/<MM>/<원래 이름>`). 없는 `YYYY`, `MM` 은 `create_dirs`.
4. `N = basename(src)` → 충돌 이름(§8) → `dst_path`.
5. `cross_device` 는 `move` 와 같이.
6. 민감도: `sensitivity=secret` 은 여기까지 올 수 없다(V3 — 보안 자산은 `archive` 불허). `sensitivity=patient` 는 허용(02 §10.1).
7. 볼륨 암호화(C14 — 제한하지 않고 경고만): `common/fsmeta.volume_encrypted(R) -> bool | None`(읽기 전용. 결정: `statfs` 의 볼륨에 대해 `getattrlist` 의 `VOL_CAP_FMT`/APFS 암호화 속성을 읽는 방법을 09 §12 에서 실기기 확인; 판정할 수 없으면 `None`). `False` 또는 `None` 이면 `plan.create` 봉투에 `W_ARCHIVE_UNENCRYPTED`(`details`: `{"archive_ops": N, "patient_count": M, "determinable": bool}`), `plan.show`·모든 승인 확인 화면에 “보관 폴더 볼륨이 암호화되어 있지 않습니다(또는 확인할 수 없음)” 한 줄. 같은 경고를 `config set archive.root` 와 `core.doctor` 도 낸다(02 §11). 차단하지 않는다.

### 4.5 볼륨 간 원본 해시 (`pre_sha256`)

`cross_device=1` 인 `move`/`archive` 에만, 계획 시점에 계산한다(06: 볼륨 간 필수).
- 파일: 원본을 1 MiB 단위로 읽어 SHA-256. 읽는 동안 `fstat` 의 `mtime_ns`/크기가 바뀌면 제외 `E_STALE`. dataless 는 V3 에서 이미 제외.
- 디렉터리·패키지: **트리 매니페스트 해시**(§4.6). 원본 트리에 일반 파일·디렉터리·심볼릭 링크 외의 것(FIFO, 소켓, 장치)이 있으면 제외 `E_INVALID_STATE` `{"reason":"special_file"}`.
- `hash_max_bytes`(64MB) 상한은 여기서 적용하지 않는다(볼륨 간 검증에 필수). 대신 한 계획의 볼륨 간 총 바이트가 원본 볼륨 여유 공간과 무관하게 **200 GiB** 를 넘으면 초과분 항목 제외 `E_USAGE` `{"reason":"plan_too_large"}`(결정: 한 번의 승인으로 몇 시간짜리 복사를 시작하지 않음).

### 4.6 트리 매니페스트

```
manifest(root) = SHA-256( 정렬된 줄들 "\n" 로 연결 )
줄 = <relpath_b64> " " <type> " " <mode&0o7777 8진수> " " <size|-> " " <sha256|linktarget_b64|->
```
- `relpath_b64` = 루트 기준 상대경로 바이트(`os.fsencode`)의 base64(정렬은 이 바이트열 기준). 루트 자신은 `"."`.
- `type ∈ {f, d, l}`. `f` 는 크기와 SHA-256, `d` 는 `-`, `l` 은 링크 대상(`os.readlink`, 따라가지 않음)의 base64.
- mtime 은 넣지 않는다(복사본 시각 정밀도 차이). 소유자·xattr 도 넣지 않는다(내용 동일성만).
- 하드 링크는 각 경로를 별개 파일로 센다(복사본도 별개 파일이 됨 — 내용은 같음).

### 4.7 저장

한 트랜잭션:
1. `plans` 행: `state='draft'`, `op_count`, `total_bytes`(원본 크기 합, 디렉터리는 `file_entries.size_bytes`), `created_channel`, `created_request_id`, `created_at`, `summary_json`(06: **집계만**):
   ```json
   {"trash": 12, "move": 3, "archive": 1,
    "bytes_by_op": {"trash": 120334, "move": 4410, "archive": 99120},
    "excluded": {"E_STALE": 1, "E_PROTECTED": 2},
    "patient_count": 0}
   ```
2. 연산을 원본 경로 바이트 오름차순으로 정렬해 `seq = 1..n`. `plan_operations` 행: `item_id`, `op`, `src_path`, `dst_path`, `pre_dev`, `pre_inode`, `pre_size`, `pre_mtime_ns`, `pre_sha256`, `src_kind`(계획 시점 `file_entries.kind`), `create_dirs_json`(이 연산 전에 만들 디렉터리 절대경로 배열, 만들 순서대로 — 없으면 `[]`), `cross_device`, `state='pending'`, `undo_state='not_applicable'`, `details_json='{}'`. `src_kind`·`create_dirs_json` 은 계획과 함께 불변이고 `plan_hash` 에 들어간다. `post_*`·`details_json`·`actual_dst_path` 는 실행 결과 칸이라 해시에 들어가지 않는다(06 주석).
3. `plan_hash` 계산(§5) 후 `plans.plan_hash` 갱신.
4. 각 항목: `state='planned'`, `plan_op_id`.
5. `audit_log`(§14).

응답 `data`: `{"plan": {id, state, plan_hash, op_count, total_bytes, summary}, "operations": [...], "excluded": [{"item_id","code","reason"}]}`. 제외가 있으면 `W_PROTECTED_SKIPPED`(코드가 `E_PROTECTED` 인 제외가 있을 때) 경고.

### 4.8 다른 활성 계획과의 목적지 충돌

§8 의 충돌 검사는 파일 시스템 `lstat` 에 더해, 다른 활성 계획(`draft`/`approved`/`executing`)의 `pending`/`running` 연산의 `dst_path` 와 그 `create_dirs_json` 도 “이미 있는 이름”으로 취급한다. 이유: 두 계획이 같은 `name 2.png` 를 고르는 것을 막는다(실행 시에는 X5 가 최종 방어).

---

## 5. 정규화와 `plan_hash`

### 5.1 정규 객체

```json
{
  "schema": "dayclose.plan.v1",
  "plan_id": "pln_7",
  "device_id": "dev_5f2c9a1e",
  "ops": [
    {
      "seq": 1,
      "item_id": "itm_128",
      "op": "trash",
      "src": "/Users/u/Desktop/스크린샷 2026-11-24 오후 2.02.11.png",
      "src_kind": "file",
      "dst": null,
      "create_dirs": [],
      "cross_device": false,
      "icloud_propagates": false,
      "pre": {"dev": 16777231, "inode": 9031, "size": 482113, "mtime_ns": 1764000131000000000, "sha256": null}
    }
  ],
  "totals": {"op_count": 1, "total_bytes": 482113}
}
```

규칙:
- 값은 모두 DB 행(`plans`, `plan_operations` — `create_dirs` 는 `create_dirs_json`, `src_kind` 는 `src_kind` 컬럼)에서 **다시 읽어** 만든다. 메모리의 계획 객체로 만들지 않는다(승인·실행 때 같은 함수로 재계산하기 위함).
- `summary_json`, `details_json`, `actual_dst_path`, `post_*`, 상태 컬럼은 정규 객체에 넣지 않는다(실행 중 바뀌는 칸).
- 경로는 DB 에 저장된 문자열 그대로(`os.fsdecode` 결과, 유니코드 정규화 안 함 — 06 §1). 비 UTF-8 바이트는 surrogateescape 문자로 남아 있다.
- 직렬화: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)`. `ensure_ascii=True` 인 이유: 비 UTF-8 경로의 외톨이 서로게이트도 `\udcxx` 로 결정적으로 표현된다(`ensure_ascii=False` 면 UTF-8 인코딩에서 실패). 정수만 쓰고 실수 없음.
- `plan_hash = hashlib.sha256(b"dayclose.plan.v1\n" + canonical_bytes).hexdigest()` (소문자 64자).
- `plan_id` 를 넣는 이유: 같은 내용의 다른 계획과 해시가 달라져, 사람이 확인하는 8자 접두사(§6.3)가 다른 계획에 재사용될 수 없다. `created_at` 은 넣지 않는다(재계산 결정성).
- FR-EX-001 AC “같은 입력 → 같은 해시”: 같은 DB 행 → 같은 바이트 → 같은 해시. 테스트는 행을 다시 읽어 3회 계산이 일치하는지, 그리고 어떤 필드 하나(경로 1바이트, inode, seq, create_dirs 원소)를 바꿔도 해시가 바뀌는지 본다.

### 5.2 계획 보기

`plan.show PLAN_ID` 의 `data`: `{"plan": {..., "plan_hash", "plan_hash_short": 앞 8자}, "operations": [{seq, item_id, op, display_name, display_path, dst_display_path, size_bytes, cross_device, state, error_code, undo_state}], "summary": ...}`. `sensitivity=patient` 항목의 `display_name` 은 “환자 관련 파일” 고정 문구(결정: 약국 화면 어깨너머 노출 방지), 보안 자산은 계획에 존재할 수 없다.

---

## 6. 승인

`dayclose plan approve PLAN_ID --hash PLAN_HASH`. 결과는 `approvals` 행 1개(06: `UNIQUE(plan_id)` — 계획당 1회).

### 6.1 공통 절차

1. **잠금 없이** 읽기: 계획 존재(`E_NOT_FOUND`), `state='draft'`(아니면 `E_INVALID_STATE`), 승인 행 없음(있으면 `E_INVALID_STATE`).
2. 행들로 해시 재계산(§5). `!= plans.plan_hash` → `E_APPROVAL_MISMATCH` `{"reason":"plan_rows_changed"}`(DB 가 생성 후 바뀜 — 정상 경로에서는 불가능). `--hash` 가 64자 소문자 hex 가 아니면 `E_USAGE`, `!= plans.plan_hash` → `E_APPROVAL_MISMATCH`.
3. 채널 검사: `--channel ∈ {mcp, schedule}` → `E_APPROVAL_DENIED` `{"reason":"channel_not_allowed"}`. (MCP 서버는 이 명령을 노출하지도 않는다 — 02 §10.3. 채널 검사는 2중 방어.)
4. 수단 선택(§6.2)과 사람 확인. 확인 화면의 내용은 2단계에서 검증한 행에서 만든다.
5. 확인 성공 후 잠금 획득 → 1·2단계를 **다시** 검사(기다리는 동안 cancel 이나 다른 승인이 있었을 수 있음) → 한 트랜잭션에서 `approvals`(plan_id, plan_hash, method, channel, request_id, approved_at) 삽입, `plans.state='approved'`, `plans.approval_id`, `audit_log` 행(§14). 
6. 응답 `data`: `{"plan_id", "approval_id", "method", "approved_at"}`.

결정: 사람 확인을 기다리는 최대 120초 동안 쓰기 잠금을 잡지 않는다. 이유: 그동안 앱의 다른 쓰기(`decision.set` 등)가 `E_LOCKED` 로 막히면 안 된다. 그 대가로 5단계의 재검사가 필수.

### 6.2 수단 선택 (호출자가 고르지 않는다 — 결정: 02 시그니처에 수단 플래그가 없으므로 core 가 환경으로 결정)

| 순서 | 조건 | 수단 |
|---|---|---|
| 1 | `DAYCLOSE_SANDBOX` 설정 **그리고** `DAYCLOSE_TEST_APPROVE=1` | `test` (확인 없이 승인) |
| 2 | `DAYCLOSE_SANDBOX` 설정, `DAYCLOSE_TEST_APPROVE != 1` | 없음 → `E_APPROVAL_DENIED` `{"reason":"no_human_channel_in_sandbox"}`. 이유: 테스트 중 실제 대화상자가 뜨면 안 된다 |
| 3 | 채널 `app` 이고 요청의 `app_signature` 가 등록된 앱 공개키로 검증됨(§6.5) | `app_button` |
| 4 | `/dev/tty` 를 읽기·쓰기로 열 수 있고, 알려진 에이전트 환경 표식이 없음(§6.3) | `cli_tty` |
| 5 | 그 외(TTY 없음, 에이전트 표식 있음, Skill 채널) | `native_dialog` |

`method=test` 승인은 실행 시에도 같은 두 환경변수가 다시 있어야 유효하다(§7.1 G4).

### 6.3 `cli_tty`

1. `/dev/tty` 를 직접 연다(표준입력이 아니다 — `yes | dayclose plan approve …` 같은 파이프 입력을 받지 않기 위함). 출력도 `/dev/tty` 로. `--json` 이면 stdout 에는 봉투만(02 §5.4).
2. 에이전트 표식: 환경변수 중 알려진 코딩 에이전트 표식(예: `CLAUDECODE`)이 하나라도 있으면 이 수단을 쓰지 않고 `native_dialog` 로 넘어간다. 표식 목록은 `plan/approval.py` 의 상수(10 문서와 함께 유지). 결정: 표식이 있을 때 `cli_tty` 를 막는 이유 — 에이전트는 `script(1)` 같은 의사 터미널 도구로 TTY 를 만들고 화면의 8자를 그대로 입력할 수 있다. 표식은 우회 가능한 휴리스틱이지만, “에이전트가 문서대로 행동하면 사람 화면이 뜬다”를 보장한다.
3. 요약 출력: 연산 종류별 개수·바이트, 볼륨 간 이동 개수, 만들 디렉터리 수, 환자 관련 파일 수(이름 없음), 처음 10개 연산의 `display_name → dst_display_path`, 제외 내역 수, `plan_hash` 앞 8자. `icloud_propagates=1` 연산이 있으면 **별도 줄**로 “N개 파일은 iCloud 를 통해 다른 기기에서도 삭제됩니다”(02 §10.3 7) — 이 줄은 요약 길이 제한으로 잘리지 않는 첫 부분에 둔다.
4. 안내 “승인하려면 위의 8자를 입력하세요(취소: 엔터):”. 120초 안에 한 줄. 대소문자 무시로 `plan_hash[:8]` 와 같으면 확인 성공. 다르거나 빈 줄·EOF·시간 초과 → `E_APPROVAL_DENIED`.

### 6.4 `native_dialog`

`osascript` 로 표준 확인 대화상자를 띄운다. **요약 텍스트는 스크립트 문자열에 끼워 넣지 않고 argv 로 넘긴다**(파일 이름에 `"` 나 AppleScript 구문이 있어도 주입되지 않게).

**실행 파일 고정**: `PATH` 를 찾지 않고 절대경로 `/usr/bin/osascript` 를 실행한다. 실행 전 `lstat` 으로 일반 파일·소유자 root(uid 0)·그룹/기타 쓰기 불가(`mode & 0o022 == 0`)를 확인하고, 아니면 `E_APPROVAL_DENIED` `{"reason":"untrusted_tool"}`. 환경은 `{"PATH": "/usr/bin:/bin", "LANG": "ko_KR.UTF-8", "HOME": <실제 홈>}` 로 새로 만든다(`DYLD_*`, `OSA_*` 등 상속 금지). 이유: `PATH` 앞쪽에 둔 가짜 `osascript` 가 `button returned:승인, gave up:false` 를 출력하면 사람 없이 승인된다. 같은 규칙(절대경로 + root 소유 + 고정 환경)을 승인 경로의 모든 시스템 도구에 적용하고, `common/proc.run_tool` 의 허용 목록을 “이름”이 아니라 “절대경로 후보 목록”으로 정의할 것을 02 에 요청한다(§19 R11).

```
/usr/bin/osascript
  -e 'on run argv'
  -e 'display dialog (item 1 of argv) with title "DayClose 정리 승인" buttons {"취소", "승인"} default button "취소" cancel button "취소" with icon caution giving up after 120'
  -e 'end run'
  -- "<요약 텍스트>"
```

- `run_tool(..., timeout=130)`. 요약 텍스트는 §6.3 의 3단계와 같은 내용, 1,500자 상한(넘으면 “외 N개”).
- 기본 버튼이 “취소”다 — 엔터 키 실수로 승인되지 않는다.
- 성공 판정: 종료 코드 0 **이고** stdout 이 정확히 `button returned:승인, gave up:false`(개행 제외). 그 외 전부(종료 코드 1 + `-128` 사용자 취소, `gave up:true` 시간 초과, GUI 세션 없음 — ssh·launchd, `osascript` 없음) → `E_APPROVAL_DENIED` `{"reason": "cancelled"|"timeout"|"no_gui"}`.
- Skill 흐름(FR-AG-002): 에이전트가 `plan.approve` 를 호출하면 사용자 화면에 이 대화상자가 뜨고, 에이전트는 결과 봉투만 받는다.
- 한계: 접근성(Accessibility) 권한을 가진 프로세스는 System Events 로 버튼을 누를 수 있다(§19 남은 위험). M7 이후 `dayclose-native` 에 LocalAuthentication(`LAContext.evaluatePolicy(.deviceOwnerAuthentication)` — Touch ID/암호) 기반 확인을 추가해 `native_dialog` 의 구현을 교체하는 것을 권고(열린 질문 §19).

### 6.5 `app_button` — 서명된 앱 승인, 그리고 M7 전·후

문제: 같은 사용자 권한의 어떤 프로세스든 `dayclose serve --stdio --channel app` 을 띄워 `plan.approve` 를 보낼 수 있다. 부모 프로세스 경로·번들 ID 검사는 가짜 번들(`/tmp/X.app/Contents/MacOS/DayClose` + 위조 `Info.plist`)로 흉내 낼 수 있다. 결정(02 §10.3 ③): **`app_button` 은 Secure Enclave 서명 검증이 성공할 때만 성립하고, 부모 프로세스 검사는 어느 마일스톤에서도 쓰지 않는다**(약한 검사를 보장처럼 보이게 하지 않기 위함).

1. **앱 키**: 앱이 `SecureEnclave.P256.Signing.PrivateKey` 를 만든다. 접근 제어 `SecAccessControlCreateWithFlags(…, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, [.privateKeyUsage, .userPresence])` — 서명할 때마다 Touch ID 또는 로그인 암호. 키는 기기 밖으로 나가지 않으므로 두 Mac(02 §8.1)은 각자 키를 갖는다.
2. **등록**: `core.app_key`(CLI `dayclose app-key register|show|revoke`, 02 §5.3, MCP 비노출). 앱이 공개키(SPKI DER)를 보내면 core 는 SPKI SHA-256 앞 8자를 `native_dialog`(§6.4) 또는 `cli_tty`(§6.3) 로 보여 주고, 사람이 앱 화면의 같은 8자와 대조해 승인하면 `app_meta` 의 `approval.app_pubkey_spki_b64`, `approval.app_pubkey_registered_at` 에 저장(06 §5.1 키 목록), `audit_log` 기록. `revoke` 도 사람 확인. 교체 = revoke 후 register. `show` 는 지문·등록 시각만.
3. **승인 요청**: 앱은 [승인하고 실행] 클릭 시 `plan.show` 로 해시를 다시 확인하고
   `msg = b"dayclose.approve.v1\n" + device_id + b"\n" + plan_id + b"\n" + plan_hash` (각 값 UTF-8, `plan_id` 는 `pln_7` 같은 외부 ID)
   를 Secure Enclave 로 ECDSA P-256/SHA-256 서명(여기서 Touch ID/암호 프롬프트)해, stdio 요청 인자 `app_signature`(DER 서명의 base64)로 보낸다.
4. **core 검증**: 등록 공개키가 있고 `cryptography` `ec.ECDSA(hashes.SHA256())` 검증 성공 → `method=app_button`. 키 미등록·서명 없음·검증 실패 → 거부하지 않고 §6.2 의 다음 순서로(채널 `app` 이면 대개 `native_dialog`). 이유: 앱 키 문제로 승인이 영영 막히지 않게 하되, 넘어간 수단도 사람 확인이다.
5. **재전송**: nonce 없음. 서명은 `(device_id, plan_id, plan_hash)` 에 묶이고 계획당 승인은 1회(`UNIQUE(plan_id)`).

**무엇이 언제 효력인가**

| 시점 | core | 앱 | 실제 사람 확인 |
|---|---|---|---|
| M5~M6, 그 Mac 의 V11(09 §12) 미확인 | 서명 검증·`core.app_key` 구현됨(12 M5) | 서명 없이 보냄 | 앱 버튼 → core 가 **`native_dialog`(osascript)** 를 띄움. 화면 제어 도구로 누를 수 있음(§6.8) |
| M5~M6, V11 통과 | 같음 | 키 등록 후 서명해 보냄 | Touch ID/암호 — 앱 경로에서 실제로 강제 |
| M7 이후(“승인 강화”, 12 M7, PRD C12) | `native_dialog` 의 구현을 `dayclose-native confirm`(LocalAuthentication `.deviceOwnerAuthentication`)으로 교체, osascript 는 `dayclose-native` 가 없을 때의 대체 수단 | V11 통과 기기에서 서명 | 대화상자 경로도 Touch ID/암호. `cli_tty` 는 그대로(ssh 의 사람 입력 경로) |

M7 이전에도 이후에도 `approval_method` 값은 같다(06: `app_button`, `cli_tty`, `native_dialog`, `test`). M7 은 `native_dialog` 의 **구현**만 바꾼다.

테스트: 서명 없는 app 채널 approve → `app_button` 기록 0(샌드박스에서는 §6.2 ②로 `E_APPROVAL_DENIED`), 다른 키의 서명·다른 `plan_hash`·다른 `device_id` 에 대한 서명 → 검증 실패.

### 6.5a iCloud 전파 확인 (`icloud_ack`, C11)

- 계획에 `icloud_propagates=1` 연산이 있으면 모든 수단의 확인 화면에 §6.3-3 의 별도 줄을 보인다: `cli_tty`·`native_dialog` 는 core 가 만든 요약에 넣고, `app_button` 은 앱 승인 화면(03)이 같은 문구를 보여야 한다(앱 서명은 `icloud_propagates` 를 포함한 `plan_hash` 를 덮으므로 화면과 기록이 어긋날 수 없다 — 앱이 그 줄을 빠뜨리는 것은 03 의 계약 위반).
- 승인 행에 `approvals.icloud_ack=1` 을 기록한다(그런 연산이 없으면 0). `method=test` 도 같은 규칙.
- 별도 확인 단계는 없다 — 승인 자체가 확인(02 §10.3 7).

### 6.6 에이전트가 스스로 승인할 수 없는 이유 (정리)

1. MCP 에 `plan.approve`·`core.app_key` 도구가 없다(02 §10.3). 채널 `mcp`/`schedule` 승인은 거부(§6.1 3단계).
2. CLI 승인은 `/dev/tty` 직접 입력 또는 사용자 화면의 대화상자를 요구한다. 표준입력 파이프는 무시된다. 에이전트 표식이 있으면 TTY 수단 자체를 쓰지 않는다.
3. `app_button` 은 등록된 Secure Enclave 키의 서명(서명마다 Touch ID/암호)이 있어야 성립한다(§6.5). `serve --stdio --channel app` 을 직접 띄워도 서명을 만들 수 없고, 서명이 없으면 대화상자로 넘어간다.
4. 대화상자 도구는 절대경로·root 소유·고정 환경으로만 실행한다(§6.4). `PATH` 앞의 가짜 `osascript` 는 실행되지 않는다.
5. `test` 수단은 샌드박스 + 명시 환경변수에서만, 그리고 실행 시 다시 검사된다. 샌드박스에서는 실제 대화상자도 뜨지 않는다.
6. 승인은 특정 `plan_id` + 전체 `plan_hash` 에 묶이고, **`plan.apply` 는 매번(재개 포함) 저장된 연산 행으로 해시를 다시 계산해 `approvals.plan_hash` 와 비교**한다(§7.1 G4). 승인 후 `plan_operations` 를 DB 에서 직접 고치면 실행이 거부된다.
7. 감사 교차 검사: `approvals.request_id` 와 같은 `request_id` 의 `audit_log` 행이 있어야 한다(§7.1 G5). `sqlite3` 로 승인 행만 넣은 경우가 걸린다.
8. 승인 유효 기간 24시간(§7.1 G6).
9. 범위 밖(§0): DB 행·감사 행·해시를 함께 위조하는 적대적 프로세스, 그리고 화면 제어(§6.8).

### 6.7 무인 기기(Mac mini)에서의 승인

- 예약 실행기는 승인도 실행도 하지 않는다(§6.1 3단계, §7.1 G10). 무인 기기에서 계획은 만들어질 수 있지만(Skill/CLI) 사람이 승인할 때까지 `draft` 로 남는다.
- 허용되는 사람 경로: (a) 화면 공유로 그 Mac 에 들어가 앱 버튼 또는 대화상자, (b) **ssh 세션의 `cli_tty`** — ssh 는 `/dev/tty` 를 주고 에이전트 표식이 없으면 §6.3 이 동작한다(사람이 8자를 직접 친다). GUI 로그인 세션이 없으면 `native_dialog` 는 `no_gui` 로 거부된다.
- 다른 기기(MacBook)에서 Mac mini 의 계획을 승인하는 경로는 만들지 않는다. 이유: 기기 간 통신·동기화가 비목표(02 §8.1)이고, 승인 서명은 `device_id` 에 묶인다.
- `draft` 계획은 만료가 없지만 결정 이후 바뀐 파일은 apply 사전조건에서 걸러진다. 오래된 `draft` 를 `review.summary` 가 “승인 대기 계획 N개”로 보여 주도록 03/10 에 요청.

### 6.8 화면 제어 도구가 대화상자를 누르는 위험

접근성(Accessibility) 또는 화면 기록·제어 권한을 가진 프로세스(원격 지원 도구, 일부 에이전트의 computer-use 기능)는 `native_dialog` 의 [승인] 을 누르거나 `cli_tty` 창에 8자를 입력할 수 있다. 이 위험은 osascript 대화상자로는 닫을 수 없다.
- 완화: 서명 승인(§6.5, V11 통과 기기)과 M7 의 LocalAuthentication 대화상자는 Touch ID 또는 암호가 필요하고, 화면 제어 도구는 지문을 대신할 수 없으며 암호를 모른다 — **그 기기에서는 사람 확인이 실제로 강제된다.**
- 남은 위험: 그 전까지, 그리고 소유자가 화면 제어 권한을 준 프로세스가 있는 동안은 대화상자 승인이 자동화될 수 있다(§19.3).

---

## 7. `plan.apply`

`dayclose plan apply PLAN_ID [--dry-run]`. W, F. `--progress ndjson` 이면 연산마다 `{"event":"progress","command":"plan.apply","phase":"apply","done":k,"total":n}`.

### 7.1 전역 검사 (하나라도 실패하면 아무 연산도 하지 않고 오류 봉투, 계획 상태 불변)

| # | 검사 | 실패 |
|---|---|---|
| G0 | 기기 일치(§7.11) | `E_DEVICE_MISMATCH`(종료 5) + `W_DEVICE_MISMATCH` |
| G1 | 잠금 획득 | `E_LOCKED` |
| G2 | `running` 연산이 어느 계획에든 있음 | `E_INVALID_STATE` `{"reason":"recover_required"}` |
| G3 | 계획 상태: `approved` 이거나, `executing` 이고 `running` 0개(재개, §7.7) | `draft` → `E_APPROVAL_REQUIRED`; 종결 상태 → `E_INVALID_STATE` |
| G4 | 승인 행 존재, `approvals.plan_hash == plans.plan_hash == 재계산 해시`. 재계산은 **매 호출마다**(재개 포함) `plan_operations` 의 저장된 행에서 §5 로 하며 캐시하지 않는다 — 승인 후 DB 에서 연산 행을 직접 고친 경우를 잡는 유일한 장치. `method='test'` 면 지금 `DAYCLOSE_SANDBOX` 와 `DAYCLOSE_TEST_APPROVE=1` | 없음 → `E_APPROVAL_REQUIRED`; 해시 불일치 → `E_APPROVAL_MISMATCH`; test 조건 불충족 → `E_APPROVAL_REQUIRED` |
| G5 | `audit_log` 에 `request_id = approvals.request_id`, `command='plan.approve'`, `ok=1` 행이 있음 | `E_APPROVAL_REQUIRED` `{"reason":"approval_not_audited"}` |
| G6 | `now - approvals.approved_at ≤ 24h` | `E_APPROVAL_REQUIRED` `{"reason":"approval_expired"}` — 결정: 24시간. 재개(`executing`)에도 같은 기한 |
| G7 | 모든 연산의 `src_path`, `dst_path`, `create_dirs_json` 원소, 휴지통 디렉터리가 §15.1 의 `_guard` 를 통과 | `E_SANDBOX_VIOLATION`(테스트) / `E_PATH_OUTSIDE_ROOTS`(운영) |
| G8 | 연산들이 쓰는 모든 볼륨(원본 볼륨, 목적지 볼륨)이 지금 도달 가능(프로브)하고 네트워크 아님 | `E_VOLUME_TIMEOUT` / `E_VOLUME_UNAVAILABLE` — FR-AB-001 AC(외장 분리 상태 apply → `E_VOLUME_UNAVAILABLE`, 원본 보존) |
| G9 | `archive` 연산이 있으면: `config.archive.root` 가 설정되어 있고 그 연산들의 `dst_path` 가 지금의 `archive.root` 아래 | `E_ARCHIVE_TARGET_MISSING` |
| G9a | `icloud_propagates=1` 연산이 있는데 `approvals.icloud_ack=0` | `E_APPROVAL_REQUIRED` `{"reason":"icloud_ack_missing"}` |
| G10 | 채널 `schedule` | `E_APPROVAL_DENIED` `{"reason":"channel_not_allowed"}` — 결정: 예약 실행기는 실행하지 않는다 |

통과하면 `plans.state='executing'`, `started_at`(재개면 유지) 커밋.

결정: 실행 트랜잭션은 `PRAGMA synchronous=FULL`, `PRAGMA fullfsync=ON`, `PRAGMA checkpoint_fullfsync=ON` 으로 연결을 연다(apply/undo/recover 명령 한정). 이유: 06 의 기본 `synchronous=NORMAL`(WAL)은 전원 차단 시 마지막 커밋을 잃을 수 있다 — `running` 커밋이 사라지면 이미 일어난 이름변경을 엔진이 모르게 된다. macOS 의 `fsync` 는 드라이브 캐시를 비우지 않으므로 `F_FULLFSYNC` 가 필요하다.

### 7.2 연산별 사전조건 (연산 직전, 순서대로, 첫 실패가 결과)

| # | 검사 | 결과 |
|---|---|---|
| F1 | `_guard`(§15.1) | `E_SANDBOX_VIOLATION` → **계획 중단**(§7.6) |
| F2 | 볼륨 도달(같은 볼륨이 이번 apply 에서 이미 실패했으면 다시 프로브하지 않고 같은 결과) | `skipped`, `E_VOLUME_TIMEOUT`/`E_VOLUME_UNAVAILABLE` |
| F3 | 부모 fd 기준 `lstat` 으로 원본 동일성(§3.1): 없음·동일성·종류·크기·mtime 불일치 | `skipped`, `E_STALE` |
| F4 | 방금 수정됨: `now_ns - st_mtime_ns < 60s`(쓰는 중일 가능성) | `skipped`, `E_STALE` `{"reason":"settling"}`, retryable |
| F5 | 플래그·위치: `SF_DATALESS`·`.icloud` 자리표시자 → `E_PROTECTED` `{"reason":"dataless"}`(FR-EX-008: 실행 직전 dataless 가 된 파일 포함). iCloud 동기화 경로 판정(원본 루트의 **현재** `scan_roots.icloud_synced` OR §3.5 경로 규칙 OR §9.2 의 실시간 신호 S1~S3)이 연산의 `icloud_propagates` 와 다르면 → `E_PROTECTED` `{"reason":"icloud_synced"}`(계획 후 동기화가 켜졌거나 꺼짐 — 승인한 사실과 달라졌으므로 실행하지 않는다). `icloud_propagates=1` 이면 해제 게이트(`TRASH_UNLOCK_VERIFIED` 그리고 `icloud.allow_trash`)를 **지금** 다시 확인, 거짓이면 `E_PROTECTED` `{"reason":"icloud_synced"}`. `UF_IMMUTABLE`/`SF_IMMUTABLE`/`UF_APPEND`/`SF_APPEND`(Finder “잠금”) → `E_PERMISSION` `{"reason":"locked"}`. DayClose 는 잠금을 풀지 않는다 | `skipped` |
| F6 | 보호 재평가: api 가 주입한 `recheck(item_id) -> allowed_actions`(§7.9)에 연산 동작이 없음 | `skipped`, `E_PROTECTED` |
| F7 | 디렉터리·패키지 내부 검사(§7.2.1) | `skipped`, `E_PROTECTED` |
| F8 | 목적지(`move`/`archive`): `create_dirs` 를 뺀 부모 경로에 대해 `realpath(parent) == parent`(계획 후 새 심볼릭 링크 없음), `dst` 가 `lstat` 으로 없음, 허용 목록(§3.5) 안, 원본 안이 아님 | 링크·허용 목록 → `E_PATH_OUTSIDE_ROOTS`; 존재 → `E_DEST_EXISTS`(충돌 이름은 계획에서 확정된 것만 쓴다 — 02 §10.2-4) |
| F9 | 볼륨 간만: 다른 프로세스가 원본을 열고 있음 — `common/fsmeta.pids_with_path_open(src)`(libproc `proc_listpidspath`, `PROC_LISTPIDSPATH_EXCLUDE_EVTONLY`, 자기 pid 제외) > 0 | `skipped`, `E_STALE` `{"reason":"in_use"}`, retryable |
| F10 | 볼륨 간만: 목적지 볼륨 여유 공간 `f_bavail × f_frsize ≥ pre_size(트리 합) + 512 MiB` | `skipped`, `E_VOLUME_UNAVAILABLE` `{"reason":"insufficient_space"}` |

F9 를 같은 볼륨 이름변경에는 적용하지 않는 이유: 이름변경은 열린 fd 를 따라가므로 다른 앱의 쓰기가 사라지지 않는다(그 앱은 휴지통·새 위치의 같은 파일에 계속 쓴다). 볼륨 간은 복사 후 원본 제거라, 복사 이후의 쓰기가 사라진다.

#### 7.2.1 디렉터리·패키지 내부 검사 (F7)

원본 `kind ∈ {dir, package}` 인 모든 연산(같은 볼륨 휴지통 포함)에 대해, 원본 트리를 `os.scandir` 로 걷는다(심볼릭 링크 따라가지 않음, 최대 100,000 엔트리, 깊이 64). 다음 중 하나라도 있으면 `E_PROTECTED`:
- 이름 `.git` 인 엔트리(저장소를 통째로 버리는 것 방지) — `details.reason="contains_repo"`
- 경로가 활성 `vault_assets.path`(`status <> 'missing'`) 중 하나를 접두사로 포함 — `"contains_security_asset"`
- 05 §3 의 **이름·확장자 신호**(내용은 읽지 않음 — `vault` 의 순수 함수 `vault.signals.name_matches(name, rel_path)`, api 가 주입) — `"contains_secret_candidate"`
- `config.protection.patient_filename_patterns` 일치(07) — `"contains_patient_candidate"`
- `SF_DATALESS` 엔트리 — `"contains_dataless"`
- 한도 초과 — `"unverifiable"`(결정: 다 보지 못한 트리는 보호된 것으로 본다)

결정: 이 검사는 DB 가 아니라 **지금의 파일 시스템**을 본다. 이유: 디렉터리 mtime 은 직계 자식 변화만 반영하므로, 계획 후 깊은 곳에 생긴 키 파일은 F3 으로 잡히지 않는다.

### 7.3 연산 공통 진행 (저널)

```
1. 사전조건 F1~F10 통과
2. create_dirs 생성 (§7.4.6)              ← 디렉터리 생성은 되돌리지 않는 부수 효과(§11.5)
3. 최종 이름 확정 (trash: §8.2)
4. COMMIT  op.state='running', started_at, actual_dst_path=<최종 경로>     ← synchronous=FULL
5. 파일 시스템 연산 (§7.4)
6. 결과 확인: lstat(actual_dst) 동일성, lstat(src) 없음
7. 두 부모 디렉터리 fd 에 fcntl(F_FULLFSYNC)
8. COMMIT  op.state='done', finished_at, undo_state='undoable', post_dev/post_inode/post_mtime_ns = lstat(actual_dst) 결과; 항목 executed(executed_at, closed_reason='executed'); file_entries 갱신(§7.5)
   실패 시: COMMIT op.state='failed'|'skipped', error_code; 항목 전이(§7.6)
```

4단계 이전에 실패한 것은 `skipped`(시도하지 않음), 5단계 이후 실패한 것은 `failed`(시도함). 06 §4.5 의 상태 정의와 같다.

### 7.4 연산별 알고리즘

#### 7.4.1 `trash`

1. 휴지통 디렉터리 `T`(§3.4). 없거나 만들 수 없으면 `skipped`, `E_PERMISSION` `{"reason":"trash_unavailable"}`.
2. 이름: §8.2. 4단계 커밋.
3. `renameatx_np(src_pfd, name, T_fd, trash_name, RENAME_EXCL)`.
   - `EEXIST`(경쟁): 대체 이름 1회 재선정 → `actual_dst_path` 갱신 커밋 → 재시도. 다시 `EEXIST` → `failed`, `E_DEST_EXISTS`.
   - `EXDEV`(같은 볼륨이라고 판단했는데 아님 — firmlink·볼륨 구성 변화): `failed`, `E_STALE` `{"reason":"cross_device"}`. 복사로 대체하지 않는다.
   - 그 외 errno: §16.
4. 공통 6~8단계.

#### 7.4.2 `move` — 같은 볼륨 (`cross_device=0`)

`trash` 와 같되 목적지는 `dst_path`(계획에서 확정), `EEXIST` 시 재선정 없이 `failed`, `E_DEST_EXISTS`.

#### 7.4.3 `move` — 볼륨 간 (`cross_device=1`): 복사 → 검증 → 원본 제거

임시 이름 `tmp = <dst 디렉터리>/.<dst 이름>.dayclose-<op_id>.partial` (UTF-8 255바이트를 넘으면 `.dayclose-<op_id>.partial`). 묘비 `tomb = <src 디렉터리>/.<src 이름>.dayclose-<op_id>.removing` (같은 길이 규칙). 두 이름 모두 `op_id` 로 결정되므로 DB 에 따로 저장하지 않는다.

1. 4단계 커밋(`actual_dst_path = dst_path`).
2. `tmp` 가 이미 있으면(같은 연산의 이전 시도 잔재) `fsops.remove_own_artifact(tmp, op_id)` — 이름 패턴 일치 + 일반 파일(또는 디렉터리) 확인 후 제거.
3. **파일**: 원본을 `O_RDONLY|O_NOFOLLOW` 로 열고 `fstat` 동일성 재확인 → `tmp` 를 `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW`, 모드 `0o600` 으로 생성 → 1 MiB 단위로 읽으며 SHA-256(h_src)을 계산하고 쓴다. 청크마다 중단 플래그(§7.6.2) 확인 → 데이터 끝나면 `fcopyfile(src_fd, tmp_fd, NULL, COPYFILE_METADATA | COPYFILE_STAT)`(xattr — 격리 속성·Finder 태그·`kMDItemWhereFroms`·리소스 포크 — ACL, 모드, 시각, 플래그 복사. 실패해도 데이터 검증이 통과하면 계속하고 경고 `details.metadata_copy_failed=true`) → `fcntl(tmp_fd, F_FULLFSYNC)`.
   **디렉터리·패키지**: `tmp` 디렉터리를 `mkdir(0o700)` 후 원본 트리를 걸으며 같은 방법으로 파일 복사, 하위 디렉터리 생성, 심볼릭 링크는 `os.symlink(readlink(…))` 로 링크 자체를 복사, 각 파일 `F_FULLFSYNC`, 끝에 디렉터리 메타데이터 `copyfile(…, COPYFILE_METADATA|COPYFILE_STAT)` 를 깊은 곳부터.
4. 검증:
   - 파일: `h_src == pre_sha256` 이어야 한다(아니면 원본이 계획 후 바뀜 → `tmp` 제거, `failed`, `E_STALE`). `tmp` 를 새로 열어 `fcntl(F_NOCACHE, 1)`(페이지 캐시가 아닌 저장 매체에서 읽기) 후 다시 SHA-256(h_tmp) → `h_tmp == pre_sha256` 이고 크기 일치.
   - 디렉터리: `manifest(tmp) == pre_sha256` **그리고** `manifest(src) == pre_sha256`(F_NOCACHE 읽기).
   - 불일치 → `tmp` 제거, `failed`, `E_STALE`(원본 변경) 또는 `E_INTERNAL`(사본 손상 — 원본은 그대로).
5. 원본 재확인: 부모 fd `lstat` 동일성·크기·mtime 이 `pre_*` 와 같음(복사 중 변경 없음). 아니면 `tmp` 제거, `failed`, `E_STALE`.
6. `renameatx_np(tmp → dst, RENAME_EXCL)`. `EEXIST` → `tmp` 제거, `failed`, `E_DEST_EXISTS`. 목적지 디렉터리 fd `F_FULLFSYNC`.
7. 원본 제거 — `fsops.remove_verified_source(op, src)`:
   - 파일: 부모 fd 로 동일성 재확인 → `os.unlink(name, dir_fd=pfd)`.
   - 디렉터리: 먼저 `renameatx_np(src → tomb, RENAME_EXCL)`(원자적으로 “제거 중” 표시) → 부모 fd `F_FULLFSYNC` → `tomb` 를 깊은 곳부터 제거(`os.scandir` + `unlink`/`rmdir` 를 dir fd 기준으로, 링크 따라가지 않음). 제거 중 실패(잠금 플래그 파일 등) → 연산은 `done`(데이터는 목적지에 검증되어 있음)으로 확정하고 `details.remnant=true`. `plan.recover` 가 나중에 다시 시도(§10.3).
   - 원본 부모 fd `F_FULLFSYNC`.
8. 공통 6~8단계(6단계의 동일성은 “`dst` 존재 + 크기 일치”, 볼륨 간은 inode 가 다르다).

#### 7.4.4 `archive`

`move` 와 같다(목적지가 `archive.root` 아래, 같은 볼륨이면 7.4.2, 다르면 7.4.3). 보관 폴더에서는 엔진이 어떤 것도 지우지 않는다(되돌리기는 §11 의 이동).

#### 7.4.5 `rename` (M6) / `restore`

- `rename`: 결정 동작 `rename`(06 `decision_action`, `file_decision_action`; 02 §5.3 — `--dest` 는 **같은 디렉터리 안의 새 전체 경로**). `plan.create` 는 `dirname(dest_path) == dirname(src_path)` 가 아니면 제외 `E_USAGE` `{"reason":"rename_must_stay_in_dir"}`, 새 이름은 §4.4 의 6단계 검증 + NFC 정규화 + §8.1 충돌 이름. `create_dirs_json` 은 항상 `[]`, `cross_device=0`. 실행은 같은 볼륨 `move`(7.4.2)와 동일. 대소문자만 다른 이름은 `RENAME_EXCL` 로 그대로 성공(§3.3 실측) — 단 §8.1 의 계획 내 충돌 비교에서 자기 자신은 충돌로 보지 않는다. undo 는 원래 이름으로 되돌리는 이름변경.
- `restore`: M5~M7 에서 만들지 않는다(예약). 되돌리기는 원래 연산 행의 `undo_state` 로 기록한다(§11). 결정: undo 를 새 계획·새 연산 행으로 만들지 않는다. 이유: 02 의 `plan.undo` 는 승인 없는 명령이고, 새 계획을 만들면 승인 규칙과 충돌한다.

#### 7.4.6 디렉터리 생성

`create_dirs_json` 의 경로를 순서대로 `fsops.make_dir(path, 0o755)`: `_guard` → `os.mkdir`. `EEXIST` 이고 `lstat` 이 디렉터리(링크 아님)면 계속(다른 연산·사용자가 만들었음). 디렉터리가 아닌 것이 있으면 `skipped`, `E_DEST_EXISTS`. 생성 후 부모 fd `F_FULLFSYNC`.

### 7.5 DB 반영 (연산 `done` 과 같은 트랜잭션)

스캔이 엔진의 변경을 “사용자의 새 변경”으로 오인하지 않게 `file_entries` 를 직접 갱신한다(04 §2.4 와의 계약, §19 R6):
- 목적지가 활성 스캔 루트 안: 같은 행의 `path`, `name`, `ext`, `root_id` 갱신(볼륨 간이면 `dev`, `inode`, `mtime_ns` 도 새 값).
- 목적지가 루트 밖(휴지통, `archive.root`): `present=0`, `deleted_run_id=NULL`.
- `file_events` 는 쓰지 않는다(`run_id` 가 필요한 스캔 산출물).
- 항목: `state='executed'`, `executed_at`, `closed_reason='executed'`.

### 7.6 부분 실패와 중단

#### 7.6.1 연산 결과 → 항목 상태

| 연산 결과 | 항목 |
|---|---|
| `done` | `executed` |
| `skipped` + `E_STALE` | `stale`(06 §4.1). `closed_reason`: 원본 없음·다른 객체 → `subject_gone`, 같은 객체인데 크기·mtime·해시가 바뀜(또는 `settling`·`in_use`) → `subject_changed`(다음 스캔에서 새 항목으로 다시 질문 — 06 §4.1 재탐지 예외) |
| `skipped`(그 외 코드) 또는 `failed` | `failed`, `last_error_code`(06 §4.1: 비-STALE skipped 도 `planned → failed`) |

연산 하나의 실패는 다음 연산을 막지 않는다. 이미 `done` 인 연산을 자동으로 되돌리지 않는다(결정: 부분 결과를 사용자에게 보여 주고 `plan.undo` 를 맡긴다. 이유: 자동 롤백은 또 하나의 파일 변경 연쇄이고, 그 실패가 더 나쁘다).

#### 7.6.2 계획 중단 조건

다음이 생기면 현재 연산을 마무리(또는 안전 지점까지 정리)한 뒤 **남은 연산을 시작하지 않는다**:
- `E_SANDBOX_VIOLATION`(버그 신호), `E_INTERNAL`(엔진 자신의 예기치 않은 예외), `E_DB_CORRUPT`.
- `SIGINT`/`SIGTERM`(02 §5.5 의 `plan.apply` 멈추기 계약): 핸들러는 플래그만 세운다. 진행 중인 **이름변경**은 원자적이라 끝까지 간다. 진행 중인 **볼륨 간 복사**는 청크마다 플래그를 보고, 서 있으면 `tmp` 를 지우고(`remove_own_artifact`) 그 연산을 `pending`, `actual_dst_path=NULL` 로 되돌리는 커밋을 한다(확정 이름변경 7.4.3-6 이후라면 원본 제거까지 마친다 — 그 시점부터는 되돌리기보다 마치는 쪽이 경로가 짧다). 그다음 연산은 시작하지 않는다.
- 같은 목적지 볼륨에서 `insufficient_space`/`ENOSPC` → 그 볼륨으로 가는 남은 볼륨 간 연산만 `skipped`(같은 코드), 나머지는 계속.

**실행 중 멈추기(사용자 요청)**: 
- CLI: Ctrl-C(`SIGINT`) — 위 규칙. 두 번째 Ctrl-C 도 같은 플래그일 뿐 강제 종료가 아니다(강제 종료는 `SIGKILL` 뿐이고 그 경우는 §10 복구).
- 앱: [중지] 버튼 → 앱이 자식 `serve --stdio` 프로세스에 `SIGINT` 를 보낸다(stdio 요청 채널은 apply 응답을 기다리는 중이라 쓸 수 없음). serve 의 핸들러는 진행 중인 요청이 있으면 그 요청의 중단 플래그만 세우고 세션은 유지한다. 진행 중 요청이 없으면 무시.
- 결과 상태: 진행 중이던 연산은 완료되었거나 `pending` 으로 되돌아감, 남은 연산 `pending`, 계획 `executing`, 봉투 `E_PARTIAL`(종료 코드 8) + `data.resumable=true` + `data.stopped_by_user=true`. `E_CANCELLED`(종료 코드 130)는 쓰지 않는다(02 §5.5). serve 프로토콜에는 apply 취소 요청이 없다 — 신호가 유일한 수단. 사용자는 재개(§7.7) 또는 `plan.cancel`(§7.10)을 고른다. 이미 `done` 인 연산은 되돌리지 않는다 — 원하면 `plan.undo`.

중단 시 남은 연산은 `pending` 그대로, 계획은 `executing` 그대로 — 재개 가능(§7.7). `E_SANDBOX_VIOLATION`·`E_INTERNAL` 중단이면 남은 연산을 `skipped`(같은 코드)로 만들고 계획을 종결한다(재개하지 않음).

#### 7.6.3 종결과 봉투

남은 `pending` 이 없으면: 전부 `done` → `completed`; `done` ≥ 1 이고 나머지 있음 → `partial`; `done` 0 → `failed`. `finished_at` 커밋.

봉투:
- 모든 연산 `done` → `ok=true`.
- 하나라도 `done` 이 아니면(중단으로 `pending` 이 남은 경우 포함) → `ok=false`, `error.code="E_PARTIAL"`, `data = {"plan": {...state...}, "operations": [{op_id, seq, item_id, op, state, error_code, actual_dst_display_path, undo_state, details}], "resumable": bool}`(02 §5.5 의 유일한 예외). 소비자는 `data.operations[*].state` 로 판단한다.
- 전역 검사 실패(§7.1)는 연산이 하나도 시작되지 않았으므로 해당 코드의 일반 오류 봉투(`data=null`).

### 7.7 재개

`executing` 이고 `running` 이 없는 계획에 `plan.apply` → G1~G10 을 다시 통과하면(G6 기한 포함) `pending` 연산만 `seq` 순서로 진행. 기한이 지났으면 `E_APPROVAL_REQUIRED` — 사용자는 `plan.cancel`(§7.10) 후 남은 항목으로 새 계획을 만든다.

### 7.8 `--dry-run`

잠금 없이, 읽기 트랜잭션 하나에서 G3~G10 과 각 연산의 F1~F10 을 **파일 시스템을 바꾸지 않고** 평가한다(`create_dirs` 는 만들지 않고 “만들 예정”으로 표시, 볼륨 간 해시는 다시 계산하지 않음 — F3 의 크기·mtime 만). `draft` 계획에도 허용(승인 전 점검). 결과 `data.operations[*].predicted ∈ {"ok", <오류 코드>}`. 계획·연산·항목 상태를 바꾸지 않고 감사 기록도 남기지 않는다. 결정: dry-run 은 G4~G6(승인 관련)을 `draft` 에서는 건너뛴다.

### 7.9 의존 방향

`executor` 는 `policy`·`vault` 를 import 하지 않는다(02 §6 의 화살표는 `api → executor → store/config/common`). `api` 의 `plan.apply` 핸들러가 `policy.recheck_allowed_actions`, `vault.signals.name_matches`, 보안 자산 경로 조회 함수를 **콜백으로 주입**한다. executor 는 주입이 없으면 시작하지 않는다(`E_INTERNAL` — 보호 검사 없는 실행 방지).

### 7.10 `plan.cancel`

`dayclose plan cancel PLAN_ID`. W.
- `draft`/`approved` → `cancelled`(06 §4.4). 연산 전부 `skipped`(`error_code='E_CANCELLED'`), 항목 `planned → decided`(`plan_op_id=NULL`).
- `executing` 이고 `running` 0개 → 남은 `pending` 을 `skipped`(`error_code='E_CANCELLED'`), 그 항목들 `planned → decided`. 계획 종결(06 §4.4): `done`=0·`failed`=0 → `cancelled`, `done`=0·`failed`>0 → `failed`, `done`>0 → `partial`. 이 명령 자체는 성공 봉투(`ok=true`)다 — `E_CANCELLED` 는 연산 행의 `error_code` 로만 쓰인다(봉투 종료 코드 130 이 아님).
- `running` 이 있으면 `E_INVALID_STATE` `{"reason":"recover_required"}`. 종결 상태면 `E_INVALID_STATE`.

### 7.11 기기 불일치 (두 기기 운용, 02 §8.1)

복사된 DB 가 다른 Mac 의 파일을 움직이면 안 된다. `device_id` 는 DB 와 `config.toml` 을 함께 복사하면 둘 다 일치하므로 그것만으로는 부족하다.

- `core.init` 은 `app_meta` 에 `host_uuid_sha256 = SHA-256(b"dayclose.host.v1" + gethostuuid())` 를 저장한다(libSystem `gethostuuid(uuid_t, timespec)` 를 `common/fsmeta.py` 가 ctypes 로 호출 — 실측: 이 머신에서 rc 0. 원 UUID 는 저장·로그하지 않는다). 06 `app_meta` key/value 라 스키마 변경 없음. 이 값이 없는 기존 DB 는 첫 `core.init`/`doctor` 실행 때 기록한다.
- **기기 검사** = (1) `app_meta.device_id == config.device_id`, (2) `app_meta.host_uuid_sha256 == 지금 계산한 값`, (3) 계획의 정규 객체 `device_id`(§5.1) == `app_meta.device_id`. 스캔 루트가 없는 것은 기기 검사에 넣지 않는다(외장 분리로도 생기므로 — 그것은 G8 이 다룬다).
- 하나라도 거짓이면: `plan.create`, `plan.approve`, `plan.apply`(G0), `plan.undo`, `plan.recover` 가 **파일 시스템을 건드리기 전에** `E_DEVICE_MISMATCH`(02 §11, 종료 코드 5) 로 거부하고 경고 `W_DEVICE_MISMATCH` 를 함께 낸다. `--dry-run` 도 거부. 읽기 명령(`plan.show`, `plan.list`, `audit.list`)은 경고만 붙이고 동작한다.
- 결정: 불일치 상태를 core 가 스스로 “고치는” 명령은 없다. 복사된 DB 는 그 기기에서 쓰지 않는 것이 정답이다(02 §8.1 결과 4). 메시지: “이 데이터베이스는 다른 Mac 에서 만들어졌습니다. 이 Mac 에서는 `dayclose init` 으로 새로 시작하세요.” `app_meta.host_uuid_sha256` 는 06 §5.1 키 목록에 있다.
- 같은 기기에서 macOS 재설치·로직보드 교체로 host UUID 가 바뀐 경우도 거부된다. 결정: 정상 사용자를 막는 비용(새 init 1회)이 다른 Mac 의 파일을 잘못 옮기는 위험보다 작다.

---

## 8. 충돌과 이름 규칙

### 8.1 `move`/`archive`/`rename` 의 충돌 이름 (계획 시 확정)

후보 `N`(원래 이름)이 “이미 있음”이면 `stem + " " + k + ext` 로 `k = 2, 3, …, 99` 를 차례로 시도한다(Finder 와 같은 꼴: `보고서 2.pdf`). 99 까지 모두 있으면 제외 `E_DEST_EXISTS`.

- `ext`: 마지막 `.` 이후. 단 `.tar.gz`, `.tar.bz2`, `.tar.xz`, `.tar.zst` 는 묶음 확장자. 점으로 시작하는 이름(`.env`)은 확장자 없음으로 본다. 디렉터리는 확장자 없음(패키지는 확장자 유지: `Foo 2.app`).
- “이미 있음”의 판정: (a) 목적지 디렉터리에서 `lstat(후보)` 성공, 또는 (b) 같은 계획에서 앞 순서 연산이 같은 디렉터리에 고른 이름, 또는 (c) 다른 활성 계획의 대기 연산 목적지(§4.8). (b)·(c) 비교 키 = `unicodedata.normalize("NFD", 이름)` 에, 목적지 볼륨이 대소문자 구분 안 함이면 `.casefold()` 까지. 이유: APFS 는 정규화 비구분(NFC/NFD 같은 이름), 기본 대소문자 비구분 — 파일 시스템 `lstat` 은 이를 자동 반영하지만 계획 내부 비교는 직접 맞춰야 한다.
- 대소문자 구분 볼륨에서는 (b)·(c) 비교에 casefold 를 하지 않는다.

### 8.2 휴지통 이름 (실행 시 확정)

1. 원래 이름이 휴지통에 없으면 그대로.
2. 있으면 `stem + " (DayClose " + op_id + ")" + ext`(예: `스크린샷 (DayClose op_33).png`). 결정: 시각 대신 `op_id` — 사용자가 휴지통에서 DayClose 가 넣은 것을 알아보고, 연산 하나에 이름 하나가 결정적으로 대응.
3. 그것도 있으면 `EEXIST` 처리(§7.4.1).
4. 255바이트를 넘으면 stem 을 UTF-8 경계에서 잘라 맞춘다.

---

## 9. 특수 파일·환경

| 대상 | 규칙 |
|---|---|
| 심볼릭 링크(항목 `kind='symlink'` — 04 는 링크에 항목을 만들지 않지만 디렉터리 안에는 있음) | 링크 자체를 옮긴다. 어떤 단계도 링크를 따라가지 않는다(`O_NOFOLLOW`, `follow_symlinks=False`, `readlink`). 상대 링크는 이동 후 깨질 수 있다 — 볼륨 간 디렉터리 이동의 승인 요약에 “심볼릭 링크 N개 포함” 표시 |
| 하드 링크(`st_nlink > 1`) | 같은 볼륨 이름변경·휴지통: 그 경로만 옮겨지고 다른 링크는 남는다 → 공간이 확보되지 않음. `plan.show` 에 `details.hardlinked=true`. 볼륨 간: 내용만 복사, 원본 경로 제거 후에도 다른 링크가 데이터를 유지 — 유실 없음 |
| 패키지·번들 | 디렉터리와 같이 처리(F7 내부 검사 포함). 실행 중인 앱 번들은 `system` 보호라 계획에 올 수 없다(02 §10.1) |
| 다른 앱이 연 파일 | 같은 볼륨: 허용(§7.2 F9 설명). 볼륨 간: `in_use` 로 건너뜀. 디렉터리 안 파일의 열림은 검사하지 않는다(libproc 경로 검사는 디렉터리 하위를 포함하지 않음 — §19 남은 위험) |
| 쓰는 중인 파일 | F4(60초 settle) + 복사 전후 동일성 비교 |
| iCloud 자리표시자·iCloud 동기화 경로 | dataless 는 계획 V3·실행 F5 에서 항상 차단. iCloud 동기화 파일은 게이트가 참일 때 항목 단위 `trash` 만(`icloud_propagates=1`, 승인 화면 경고, `icloud_ack`), 그 외 연산은 차단. “Mac 저장 공간 최적화”로 계획 후 dataless 가 된 파일, 계획 후 루트의 `icloud_synced` 가 바뀐 경우도 F5 가 잡는다 |
| 대소문자·유니코드 | §8.1. 원본 경로는 DB 문자열 그대로 사용(정규화하지 않음) — 디스크의 실제 바이트와 같기 때문 |
| 권한·소유자 | 이름변경은 부모 디렉터리 쓰기 권한만 필요. 스티키 비트 디렉터리에서 남의 파일 → `EPERM` → `E_PERMISSION`. 원본 소유자가 다른 사용자인 볼륨 간 이동은 소유자를 보존할 수 없다(일반 사용자) → 사본은 현재 사용자 소유가 된다(승인 요약에 표시) |
| 잠금 플래그(`uchg`) | F5 → `E_PERMISSION` `locked`. 해제하지 않는다 |
| 볼륨 분리 도중 | 진행 중 연산의 errno(`ENXIO`, `EIO`, `ENODEV`, `ENOENT` on 볼륨 루트) → `failed`, `E_VOLUME_UNAVAILABLE`. 목적지에 남은 `tmp` 는 다음 `plan.recover` 가 정리(§10.3) |
| TCC | §16 의 `EPERM` 판정. `~/.Trash` 자체가 TCC 보호 위치일 수 있음(실기기 검증 항목 §18) |
| 외장 볼륨 행(hang) | 모든 `/Volumes/*` 첫 접근은 프로브 경유(02 §10.5). 프로브 통과 후의 개별 호출이 멈추는 경우는 막지 못한다 — 예약 실행은 apply 를 하지 않으므로(G10) 사람 앞에서만 발생 |

---

### 9.1 iCloud 휴지통 해제 검증 (C11 — `TRASH_UNLOCK_VERIFIED` 를 켜는 조건, M5 종료 기준)

소유자는 다운로드된 iCloud 동기화 파일의 항목 단위 `trash` 를 허용했다(PRD C11, FR-EX-008). 효력은 코드 게이트 `policy/icloud.py: TRASH_UNLOCK_VERIFIED`(기본 `False`)가 `True` 가 된 뒤부터다. 아래 네 조건을 **MacBook 과 Mac mini 각각**에서 확인하고 09 §12 에 기기별로 기록한 뒤, 상수를 `True` 로 바꾸는 리뷰된 변경(Security 패스)으로만 켠다(12 M5). 하나라도 실패하면 결과를 기록하고 게이트는 거짓으로 둔다(차단 유지).

1. **전파와 보존**: iCloud Drive(그리고 “데스크탑 및 문서” 동기화를 쓰면 `~/Desktop`) 안의 사람이 직접 만든 테스트 파일 1개를 이 엔진의 `trash` 연산(`renameatx_np` → `~/.Trash`)으로 옮긴 뒤 (a) 다른 기기에서 삭제가 전파되는지, (b) iCloud.com “최근 삭제된 항목”에 남는지, (c) `plan.undo` 로 되돌린 뒤 다른 기기에 같은 내용으로 복원되는지 확인.
2. **다운로드 유발 없음**: 같은 절차에서 `fs_usage`·네트워크 관찰로 이름변경이 다운로드·재업로드 외의 트래픽을 만들지 않는지 확인(FR-CORE-008). dataless 파일은 이 검증과 무관하게 계속 차단.
3. **업로드 완료 판정**: 아직 업로드되지 않은(다른 기기에 없는) 파일을 휴지통에 넣으면 그 파일은 이 Mac 의 휴지통에만 남는다 — 그 자체로 유실은 아니지만 “다른 기기에서 삭제” 문구가 틀려진다. 메타데이터만으로(내용을 읽지 않고) 업로드 완료를 알 수 있는 방법(예: `dayclose-native` 의 `URLResourceValues.ubiquitousItemIsUploaded`)을 확인하고, 확인 가능하면 F5 에 “업로드 미완료 → `skipped` `E_STALE` `{"reason":"icloud_upload_pending"}`(retryable)”를 추가한다. 방법이 없으면 그 사실을 기록하고 승인 문구를 “다른 기기에서도 삭제될 수 있습니다”로 바꾼 뒤에만 켠다.
4. **장애 주입**: iCloud 모의 시나리오(루트 `icloud_synced` 전환, 실행 직전 dataless 전환, `icloud_ack=0`)를 11 의 스위트에 추가하고 녹색.

**결과**: 네 조건이 두 Mac 모두에서 통과하고 09 §12 에 기록되면 `TRASH_UNLOCK_VERIFIED = True` 로 바꾸는 리뷰된 변경 하나가 들어간다(M5 종료 기준, 12). 그 뒤 해제 = `TRASH_UNLOCK_VERIFIED` **그리고** `config.icloud.allow_trash`(기본 `true`). 해제되는 것은 **다운로드된 iCloud 동기화 파일의 항목 단위 `trash` 하나뿐**이다. dataless 파일은 해제 여부와 무관하게 모든 연산이 계속 차단된다. 그룹 결정(`decision.set --group`)과 학습 규칙 결정(`actor='rule'`)은 iCloud 동기화 항목을 `trash` 에 넣지 않는다(02 §10.1 예외 2 — `plan.create` V3 도 `decisions.actor='user' AND scope='item'` 을 다시 확인하고, 아니면 `E_PROTECTED` `icloud_synced` 로 제외).
게이트 상수는 `policy/icloud.py` 한 곳에 있고, 테스트 `test_icloud_gate_requires_verification_record` 가 상수가 `True` 이면 `docs/09-MACOS-INTEGRATION.md` §12 의 해당 검증 행이 두 기기 모두 `ok` 로 채워져 있는지 확인한다(검증 없이 상수만 바꾸는 변경을 CI 가 막음).

**결정: 다운로드된 iCloud 파일의 `move`/`archive`/`rename` 은 v1 에서 열지 않는다.** 이유: (a) iCloud 밖으로의 이동은 다른 기기에서 삭제로 보이는데 “이동”이라는 이름이 그 사실을 가린다, (b) 볼륨 간 `archive` 는 원본 제거가 곧 iCloud 삭제 전파라 휴지통과 달리 iCloud 의 “최근 삭제된 항목” 보존도 없다, (c) `rename` 은 다른 기기에서 충돌 사본을 만들 수 있다. 열려면 PRD 의 새 소유자 결정과 02 §10.1 예외 2 표 변경이 먼저다 — §9.1 의 검증으로는 열리지 않는다.

### 9.2 루트의 iCloud 상태 수동 지정과 실행 시 실시간 신호

`scan_roots.icloud_synced_mode ∈ {auto, yes, no}`(사용자 지정 — `root add/set --icloud-synced`, 사람 CLI/앱만, MCP 비노출), `icloud_synced`(실효값), `icloud_synced_source ∈ {detected, user, assumed}`(06 §5.1).

위험: 실제로 동기화되는 루트에 사용자가 `no` 를 지정하면 그 루트의 `trash` 가 `icloud_propagates=0` 으로 계획되고 승인 화면에 iCloud 줄이 빠진 채 다른 기기에서 삭제된다(그리고 `move`·`archive` 가 열려 전파된다).

통제(executor — 저장된 플래그만 믿지 않는다):
1. 실행 직전(F5) 원본마다 **실시간 신호**를 다시 본다(내용을 읽지 않는 `lstat`·`realpath` 뿐, 다운로드 유발 없음):
   - S1: `realpath(원본의 루트)` 또는 `realpath(원본)` 이 `~/Library/Mobile Documents/` 또는 `~/Library/CloudStorage/` 아래.
   - S2: 원본 루트가 `desktop`/`documents` 이고 `~/Library/Mobile Documents/com~apple~CloudDocs/Desktop`(또는 `/Documents`) 디렉터리가 존재(“데스크탑 및 문서 폴더” 동기화가 켜졌을 때 생기는 위치 — 09 §12 V17 에서 실기기 확인; 확인 전까지는 S2 를 “동기화됨” 신호로 쓰되 오탐은 안전 쪽).
   - S3: 원본 파일의 `st_flags & SF_DATALESS`(dataless 는 그 자체로 동기화 증거).
2. 실시간 신호가 하나라도 “동기화됨”인데 연산의 `icloud_propagates=0` 이면 → `skipped` `E_PROTECTED` `{"reason":"icloud_synced","source":"live_signal"}`. **사용자 지정 `no` 는 실시간 양성 신호를 이기지 못한다.** `no` 가 효력을 갖는 것은 신호가 하나도 없을 때(04 의 판정이 틀렸다고 사용자가 아는 경우)뿐이다.
3. 반대로 `icloud_propagates=1` 인데 신호가 모두 음성이고 실효값도 0 이면 → `skipped` `E_PROTECTED` `{"reason":"icloud_synced","source":"state_changed"}`(승인 때와 상태가 다름).
4. `plan.create` 도 같은 실시간 신호로 `icloud_propagates` 를 정한다(실효값 OR 실시간 신호). 그래서 정상 경로에서는 2단계가 거의 일어나지 않고, 일어나면 “계획 후 동기화를 켰다”는 뜻이다.
5. 04·07(policy)에도 같은 규칙(실시간 양성 신호가 `no` 를 이긴다)을 요청한다 — `allowed_actions` 단계에서 `move`/`archive` 가 열리지 않게.

## 10. 크래시 복구 (`plan.recover`)

`dayclose plan recover`. W, F(DayClose 자신의 잔재 정리와 구출 이름변경만). 앱은 시작 시, CLI 는 `E_INVALID_STATE {"reason":"recover_required"}` 를 받으면 사용자가 실행. 결정: `plan.apply` 가 recover 를 자동 실행하지 않는다. 이유: 복구는 “무엇이 일어났는지”를 사용자에게 먼저 보여 주는 단계 — 결과를 확인한 뒤 재개 여부를 고르게 한다.

### 10.1 절차

1. 잠금 획득. 실행 PRAGMA(§7.1).
2. 대상: `state='running'` 연산 전부 + `undo_state='undoing'` 연산(§10.5) + 정리 대상(10.3).
3. 각 연산의 실제 상태를 아래 표로 판정하고 한 연산씩 커밋.
4. 각 계획: `running` 이 없어졌으면 — `pending` 이 남았으면 `executing` 유지(재개 가능), 없으면 §7.6.3 으로 종결.
5. 응답 `data = {"reconciled": [{op_id, from:"running", to, reason}], "cleaned": N, "plans": [{plan_id, state, resumable}]}`. 대상이 없으면 `ok=true`, 빈 목록(멱등).

표기: **S** = 원본 경로를 부모 fd `lstat` 한 결과(`match` = 동일성·크기·mtime 이 `pre_*` 와 같음, `absent`, `other` = 다른 객체). **D** = `actual_dst_path` 의 결과(같은 볼륨: `match` = `(dev, inode) == pre`; 볼륨 간: `match` = 존재하고 크기 일치하고 SHA-256/매니페스트 == `pre_sha256`). **T** = 임시 파일, **B** = 묘비.

### 10.2 판정표 — 같은 볼륨 이름변경(`trash`, `move`/`archive` `cross_device=0`, `rename`)

| S | D | 판정 | 조치 |
|---|---|---|---|
| match | absent | 이름변경 전에 멈춤 | `pending`, `actual_dst_path=NULL` |
| match | other | 이름변경 전(목적지는 남의 것 — `RENAME_EXCL` 이 덮지 않음) | `pending` |
| absent | match | 이름변경 완료, `done` 커밋 전에 멈춤 | `done`, `undoable`, 항목 `executed`, §7.5 반영 |
| other | match | 완료 후 누군가 원본 경로에 새 파일을 만듦 | `done`(위와 같음) |
| absent 또는 other | absent 또는 other | 엔진 밖에서 누가 옮김/지움 | `failed`, `E_STALE`, 항목 `stale`. 보고서에 “위치 미확인” |
| match | match | 불가능(하드 링크로 목적지를 만들었을 때만) | `failed`, `E_INTERNAL`, 수동 확인 안내. 아무것도 지우지 않음 |

### 10.3 판정표 — 볼륨 간(`cross_device=1`)

| S | D | T/B | 판정 | 조치 |
|---|---|---|---|---|
| match | absent | T 있음/없음 | 복사·검증 중 멈춤 | T 제거(`remove_own_artifact`) → `pending` |
| match | match | — | 확정 이름변경 후, 원본 제거 전 멈춤 | **되감기**: D 제거(`remove_verified_source` — D 의 해시가 `pre_sha256` 과 같음을 다시 확인한 뒤) → `pending`. 결정: recover 는 원본을 지우지 않는다(X10). 재개하면 다시 복사한다 |
| match | other | T | 목적지에 남의 파일 | T 제거 → `pending`(재개 시 F8 이 `E_DEST_EXISTS`) |
| absent | match | T 있으면 | 원본 제거까지 끝, `done` 전 멈춤 | T 제거 → `done` |
| absent | absent | T 있고 T 의 해시 == `pre_sha256` | 원본이 엔진 밖에서 사라졌고 검증된 사본이 임시 이름에만 있음 | **구출**: `renameatx_np(T → D, RENAME_EXCL)` → `done`, `details.rescued=true`. 실패하면 T 를 그대로 두고 `failed`, `E_INTERNAL`, T 경로를 사용자에게 보고(`item.show`) |
| absent | absent | T 없음 또는 해시 불일치 | 위치 미확인 | `failed`, `E_STALE`, 항목 `stale`. T 는 지우지 않는다 |
| (디렉터리) B 있음 | match | B | 원본을 묘비로 바꾼 뒤 제거 중 멈춤 | D 매니페스트 재확인 == `pre_sha256` → B 제거 계속 → `done`. 불일치 → B 유지, `failed`, `E_INTERNAL` |
| (디렉터리) B 있음 | absent | B | 불가능한 순서(묘비는 확정 이름변경 뒤에만) | B → 원래 이름으로 `RENAME_EXCL` 되돌림 → `pending` |

추가 정리(대상 2):
- `state='done'` 이고 `details.remnant=true` 로 끝난 디렉터리 연산: D 매니페스트 재확인 후 B 제거 재시도.
- `state='failed'` 이고 `error_code ∈ {E_VOLUME_UNAVAILABLE, E_VOLUME_TIMEOUT}` 인 볼륨 간 연산: 그 볼륨이 지금 도달 가능하면 T 제거.
- 정리는 이름 패턴 `.<이름>.dayclose-<op_id>.(partial|removing)` 이 **이 DB 의 연산 ID** 와 일치하는 것만. 디렉터리를 훑어 비슷한 이름을 지우지 않는다.

이 문서의 `details.*`(`remnant`, `rescued`, `hardlinked`, `metadata_copy_failed`, `restored_as`, `blocked_by`, `not_undoable_reason`, `created_dirs`(실제로 새로 만든 것))는 `plan_operations.details_json` 에 기록한다(해시 밖, 06). 볼륨 간 판정표의 D `match` 는 `post_*` 가 있으면 `(post_dev, post_inode) == lstat(D)` + 크기 일치로, 없으면(= `done` 커밋 전에 멈춤) 내용 해시로 판정한다.

### 10.4 recover 가 하지 않는 것

연산을 새로 실행하지 않는다(구출 이름변경 제외 — 이미 검증된 사본을 원래 목표 이름으로 확정하는 것). 원본을 지우지 않는다. 휴지통을 훑지 않는다. 사용자에게 묻지 않는다.

---

### 10.5 `undoing` 연산의 판정

`O` = 원래 위치(`src_path`, 또는 `details_json.restored_as`), `C` = 현재 위치(`actual_dst_path`).

| O | C | 판정 | 조치 |
|---|---|---|---|
| 동일성 일치(같은 볼륨: `(dev,inode)==pre`; 볼륨 간: 해시 == `details_json.undo_sha256`) | 없음 | 되돌리기 완료, 커밋 전 멈춤 | `undone`, 항목 `undone`, `file_entries` 원래 경로로 |
| 없음 | `post_*`(또는 `pre`) 동일성 일치 | 되돌리기 전에 멈춤 | 임시 파일(`.…undo.partial`) 정리 → `undoable` |
| 일치 | 일치(볼륨 간: 사본 확정 후 C 제거 전) | 되감기 | O 의 사본을 `remove_verified_source` 로 제거(해시 재확인 후) → `undoable` |
| 그 외 | 그 외 | 위치 미확인 | `undo_failed`, `E_STALE`, 아무것도 지우지 않음 |

## 11. 되돌리기 (`plan.undo`)

`dayclose plan undo PLAN_ID [--op OP_ID]... [--on-conflict fail|rename]`. W, F. 승인 불필요(02 §5.3). MCP 비노출(02 §10.3). 기본 `--on-conflict fail`.

### 11.1 전제

- 계획 상태 ∈ {`completed`, `partial`, `partially_undone`} → 아니면 `E_INVALID_STATE`.
- `running` 연산 있음 → `E_INVALID_STATE` `recover_required`.
- `--op` 가 이 계획의 연산이 아니면 `E_NOT_FOUND`. 지정한 연산이 `done` 이 아니거나 `undo_state ∉ {undoable, undo_failed}` 면 그 연산은 결과에 `not_applicable` 로 보고(오류 아님).
- 대상 = 지정 연산(없으면 전부)을 `seq` **역순**으로.
- 전역 검사: G7(`_guard`), G8(볼륨 도달 — 원래 경로 볼륨과 현재 위치 볼륨).

### 11.2 연산별 절차

1. **현재 위치 확인** `C = actual_dst_path`:
   - 같은 볼륨 연산: `lstat(C)` 의 `(dev, inode, kind) == pre`. 크기·mtime 은 달라도 된다(이동 후 사용자가 편집 — 같은 객체이므로 되돌려도 유실 없음).
   - 볼륨 간 연산: `lstat(C)` 의 `(dev, inode) == (post_dev, post_inode)`(06 의 실행 후 동일성). 같으면 이동 후 사용자가 편집했어도 같은 객체이므로 되돌린다 — 이때 되돌리기 복사의 검증 기준은 `pre_sha256` 이 아니라 **되돌리기 시작 시 C 를 읽어 계산한 해시**(§11.2 4단계). `post_*` 가 NULL(06 이전 데이터·복구로 `done` 이 된 연산)이면 내용 해시 == `pre_sha256` 일 때만 되돌리고, 아니면 `E_UNDO_IMPOSSIBLE` `{"reason":"identity_unprovable"}`.
   - `lstat(C)` 가 `EPERM` 이면 “없음”으로 판단하지 **않는다** → `undo_failed`, `E_TCC_DENIED`(retryable). `~/.Trash` 는 FDA 없는 프로세스에 목록·`lstat` 이 거부될 수 있다(09 §12 V8 실기기 확인 대상). 이유: 권한 오류를 “휴지통이 비워졌다”로 오판하면 되돌릴 수 있는 파일을 포기하게 된다.
   - `C` 없음(`ENOENT`): 이미 원래 위치에 같은 객체가 있으면(`lstat(src)` 동일성 일치 — 사용자가 직접 되돌려 놓음) → `undone` 으로 기록하고 끝. 아니면 원인을 구분해 보고한다:
     - 휴지통 연산이고 휴지통 디렉터리 자체는 접근 가능 → `E_UNDO_IMPOSSIBLE` `{"reason":"trash_emptied"}`. 메시지: “휴지통에서 이 파일이 없어졌습니다. 휴지통을 비웠거나 다른 정리 도구(예: Mole 의 `mo clean` 은 기본으로 휴지통을 비움)가 지웠을 수 있습니다. 되돌릴 수 없습니다.” 결정: 휴지통 비움은 “일어나지 않는다고 가정”하지 않고 명시적인 되돌리기 불가 조건으로 감지·보고한다(13 조사). DayClose 는 정리를 외부 도구에 맡기지 않는다.
     - 그 외 → `E_UNDO_IMPOSSIBLE` `{"reason":"gone"}`(30일 자동 비우기, 사용자가 다른 곳으로 옮김).
     - 이후 다른 계획의 연산이 `src_path == C` 이고 같은 동일성으로 그것을 옮겼다면 `details.blocked_by = "<그 op_id>"`(“그 계획을 먼저 되돌리세요”).
   - `C` 에 다른 객체 → `E_UNDO_IMPOSSIBLE` `{"reason":"replaced"}`.
2. **원래 위치 준비** `O = src_path`:
   - 부모 디렉터리가 없으면, 가장 가까운 존재하는 조상이 원래 스캔 루트 경로 안(또는 루트 자신)일 때만 빠진 디렉터리를 `make_dir(0o755)` 로 만든다. 루트 자체가 없으면 볼륨 문제면 `E_VOLUME_UNAVAILABLE`, 아니면 `E_UNDO_IMPOSSIBLE` `{"reason":"origin_gone"}`.
   - `O` 에 무엇이 있으면: `fail` → `undo_failed`, `E_DEST_EXISTS`. `rename` → §8.1 규칙으로 `stem 2.ext …` 를 실행 시 골라 그 경로로 되돌린다(결과 `details.restored_as`).
3. **진행 표시 커밋**: 파일 시스템 호출 **전에** `undo_state='undoing'`(06 §4.5). 크래시로 `undoing` 이 남으면 `plan.recover` 가 판정한다(§10.5).
4. **실행**:
   - 같은 볼륨: `renameatx_np(C → O', RENAME_EXCL)`.
   - 볼륨 간(볼륨 간 `move`/`archive` 의 되돌리기): 먼저 `C` 를 읽어 기준 해시 `h_undo` 를 계산하고 `details_json.undo_sha256` 에 커밋(재시작·복구가 같은 기준을 쓰게) → §7.4.3 과 같은 복사 → 검증(`h_undo`) → 확정 → `C` 제거(`remove_verified_source`). 임시 이름 `.<이름>.dayclose-<op_id>.undo.partial`, 묘비 `.<이름>.dayclose-<op_id>.undo.removing`.
5. 확인·`F_FULLFSYNC`·커밋: `undo_state='undone'`, `undone_at`, `undo_error_code=NULL`; 항목 `executed → undone`(`undone_at`, `closed_reason='undone'`); `file_entries` 를 원래 경로로(§7.5 의 역).
6. 실패: `undo_state='undo_failed'`, `undo_error_code=<코드>`.

계획 상태: 대상이 된 `done` 연산이 모두 `undone` → `undone`; 일부 → `partially_undone`(06 §4.4). `undone_at`.
봉투: 전부 성공(또는 `not_applicable`) → `ok=true`. 하나라도 `undo_failed` → `E_PARTIAL` + 연산별 결과.

### 11.3 되돌리기의 한계 (사용자 문구로도 노출)

| 상황 | 결과 |
|---|---|
| iCloud 동기화 파일(`icloud_propagates=1`)의 되돌리기 | 원래 iCloud 경로로 이름변경 → 다시 업로드되어 다른 기기에 나타남(§9.1-1c 확인 대상). 그 사이 다른 기기에서 같은 이름의 파일이 생겼다면 iCloud 의 충돌 사본 규칙을 따른다 |
| 휴지통을 비움(사용자, macOS 30일 자동 비우기, Mole 등 외부 정리 도구) | `E_UNDO_IMPOSSIBLE` `trash_emptied`/`gone` — 감지해서 보고, 되돌릴 수 없음 |
| 휴지통 접근이 TCC 로 거부 | `E_TCC_DENIED` — 권한 부여 후 재시도(포기로 판정하지 않음) |
| Finder 에서 직접 꺼내 원래 자리에 둠 | 자동 감지 → `undone` |
| Finder 에서 꺼내 다른 곳에 둠 | `E_UNDO_IMPOSSIBLE` `gone` |
| 원래 자리에 새 파일이 생김 | `--on-conflict rename` 으로만 |
| 원래 폴더가 지워짐 | 스캔 루트 안이면 폴더를 다시 만들어 복원 |
| 외장 분리 | `E_VOLUME_UNAVAILABLE`, 나중에 재시도 |
| 볼륨 간 이동 후 편집 | 같은 객체(`post_*` 일치)면 편집본을 되돌린다. 동일성을 증명할 수 없으면 `E_UNDO_IMPOSSIBLE` `identity_unprovable` |
| `move` 로 만든 디렉터리 | 되돌린 뒤에도 남는다(빈 디렉터리 삭제도 삭제 연산이라 하지 않음 — §11.5) |
| 되돌리기의 되돌리기(redo) | 없음. 다시 하려면 새 결정 → 새 계획 |

### 11.4 undo 와 스캔

되돌린 파일은 원래 엔트리 행으로 복구되므로(§11.2 5단계) 다음 스캔에서 `created` 가 되지 않고, 항목은 `undone`(종결 — 06: 자동 재질문 안 함)으로 남는다.

### 11.5 결정: 엔진이 만든 디렉터리는 지우지 않는다

`create_dirs` 로 만든 디렉터리는 undo·cancel·recover 어디서도 지우지 않는다. 이유: 삭제 경로를 늘리지 않는다(X6). 빈 폴더는 다음 스캔에서 사용자가 판단한다.

---

## 12. 멱등성

| 명령 | 반복 호출 |
|---|---|
| `plan.create` | 같은 항목은 이미 `planned` → 두 번째는 `E_INVALID_STATE`(`no_eligible_items` 또는 V4). 계획이 두 개 생기지 않는다 |
| `plan.approve` | 두 번째는 `E_INVALID_STATE`(`UNIQUE(plan_id)` 가 최종 방어) |
| `plan.apply` | `completed`/`partial`/`failed` → `E_INVALID_STATE`. `done` 연산은 어떤 경로로도 다시 실행되지 않는다(상태 확인 후 건너뜀) |
| `plan.undo` | `undone` 연산은 건너뜀, `ok=true` |
| `plan.recover` | 대상 없으면 아무것도 안 함 |
| `plan.cancel` | 종결 상태 → `E_INVALID_STATE` |
| 앱의 재시도(serve 요청 시간 초과 후 같은 요청 재전송) | 두 번째 요청은 잠금을 기다린 뒤 위 규칙대로. 앱은 `request_id` 를 새로 만들되, 같은 계획에 대한 apply 는 응답을 받기 전 다시 보내지 않는다(03/10) |

---

## 13. 잠금과 동시성

- 모든 W 명령은 `DAYCLOSE_HOME/state.lock` `flock(LOCK_EX)`(02 §7). `plan.apply`·`plan.undo`·`plan.recover` 는 **명령 전체 동안** 보유한다(복사가 길어도). 그동안 `scan.run` 등 다른 쓰기는 `--wait-lock` 후 `E_LOCKED`(retryable). 읽기 명령(`item.list`, `plan.show`)은 WAL 로 계속 동작 — 앱은 진행 화면을 그릴 수 있다.
- `flock` 은 프로세스가 죽으면 커널이 푼다 → “잠금은 없는데 `running` 이 있음” = 크래시의 확실한 증거(G2).
- 스캔과 실행은 같은 잠금으로 직렬화되므로, 스캔이 실행 도중의 반쯤 옮겨진 상태를 보는 일은 없다. 사용자가 실행 도중 Finder 로 같은 파일을 만지는 경쟁은 F3·§7.4.3-5·`RENAME_EXCL` 이 처리한다.
- `serve --stdio` 는 요청 단위 잠금(02 §7) — apply 요청 하나가 끝날 때까지 그 세션의 다른 쓰기 요청은 대기한다.

---

## 14. 감사 기록

- `audit_log`(06 §5.1): `plan.create`, `plan.approve`, `plan.apply`, `plan.cancel`, `plan.undo`, `plan.recover` 각 호출마다 1행(성공·실패 모두 — 실패도 W 명령의 시도다). `target_type='plan'`, `target_ids_json=["pln_7"]`, `summary` 예: `"plan.apply done=12 failed=1 skipped=2"`, `"plan.approve method=native_dialog"`. 경로·파일명·비밀 금지(06).
- 승인 행 자체가 감사 증거: `approvals.method`, `channel`, `request_id`, `approved_at`.
- 연산 이력: `plan_operations`(원본·목적지 경로 포함 — DB 는 0600, 06 §6).
- 로그(`core.log`): 연산마다 `{"event":"op","op_id","plan_id","op","state","error_code","cross_device","bytes"}`. 경로는 일반 파일만, 홈은 `~` 축약(02 §13). `sensitivity ∈ {patient, secret}` 항목의 연산은 경로 없이 ID 만.
- `audit.list [--since DATE] [--limit N]`(M5): `audit_log` 를 시간 역순으로. FR-EX-007 AC: channel·명령·시각·대상 ID 로 “누가 무엇을 언제”, 경로·비밀 없음.

---

## 15. 테스트 샌드박스 가드와 정적 검사

### 15.1 `_guard` (런타임, `fsops` 내부)

```
_guard(*paths):
  1. 각 p 는 절대경로, NUL 없음, 구성요소에 '..' 없음. 아니면 E_USAGE 성격의 내부 오류 → E_INTERNAL
  2. 테스트 감지: 환경에 PYTEST_CURRENT_TEST 가 있거나 'pytest' 가 sys.modules 에 있으면 → DAYCLOSE_SANDBOX 가 반드시 설정되어 있어야 함. 없으면 E_SANDBOX_VIOLATION
  3. DAYCLOSE_SANDBOX 설정 시: q = realpath(가장 가까운 존재하는 조상) + 나머지 구성요소.
     os.path.commonpath([q, realpath(SANDBOX)]) != realpath(SANDBOX) → E_SANDBOX_VIOLATION
  4. 운영 모드: §3.5 허용 영역(홈 또는 /Volumes/<이름>) 밖 → E_PATH_OUTSIDE_ROOTS. 금지 영역(§3.5 목록, DAYCLOSE_HOME) → E_PATH_OUTSIDE_ROOTS
```
- `conftest.py` 의 autouse 픽스처(02 §10.4, 11)와 별개의 **엔진 내부** 방어선이다 — 픽스처가 꺼져도 2단계가 막는다.
- 휴지통·임시·묘비·`create_dirs` 경로도 같은 함수를 통과한다.

### 15.2 정적 검사 `tests/safety/test_no_mutation_outside_executor.py`

`core/src/dayclose/**/*.py` 의 AST 를 검사한다.

1. **금지 호출**(아래 허용 목록 밖에서 등장하면 실패): `os.rename`, `os.replace`, `os.renames`, `os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `os.link`, `os.symlink`, `os.truncate`, `os.chmod`, `os.lchmod`, `os.chown`, `os.lchown`, `os.chflags`, `os.lchflags`, `os.utime`, `os.mkdir`, `os.makedirs`; `shutil.*`(단 `shutil.which` 는 `common/proc.py` 에서만); 속성 이름 호출 `.unlink(`, `.rename(`, `.replace(`(문자열 메서드 오탐 방지: 첫 인자가 문자열 리터럴 2개인 `str.replace` 형태는 제외), `.rmdir(`, `.touch(`, `.write_text(`, `.write_bytes(`, `.chmod(`, `.symlink_to(`, `.hardlink_to(`, `.mkdir(`; `open(` 의 모드 리터럴에 `w`/`a`/`x`/`+`, 또는 모드가 리터럴이 아님; `os.open(` 의 플래그 식에 `O_WRONLY`/`O_RDWR`/`O_CREAT`/`O_TRUNC`/`O_APPEND`; `import ctypes`/`cffi`; `import subprocess`; `import tempfile`.
2. **허용 목록**:
   - `executor/fsops.py`: 전부 허용. **`executor/` 의 다른 파일은 허용하지 않는다**(엔진 내부에서도 한 파일로 집중).
   - `fsops.py` 안에서 사용자 데이터를 없애는 호출(`unlink`, `rmdir`)은 함수 `remove_verified_source`, `remove_own_artifact` 두 곳 본문에서만(12 의 “1곳” 표현을 이 두 함수로 구체화 — §19).
   - `store/`, `config/`, `common/logging.py`, `common/paths.py`: 쓰기 `open`, `os.mkdir`/`makedirs`, `os.chmod`, `os.replace`(설정 원자적 저장), `os.unlink`(백업·로그 회전) — 런타임 보조 가드(아래)가 경로가 `DAYCLOSE_HOME`(또는 로그·캐시 디렉터리) 아래인지 확인.
   - `common/proc.py`: `subprocess`.
   - `common/fsmeta.py`: `ctypes`, 바인딩 심볼 허용 목록 `statfs`, `acl_get_link_np`, `acl_to_text`, `acl_free`, `proc_listpidspath`, `gethostuuid` — 읽기 전용 함수만(05 §16 P2 목록 + 08 §7.11 의 `gethostuuid`).
   - `executor/fsops.py` 의 ctypes 심볼: `renameatx_np`, `fcopyfile`, `copyfile`.
3. **가드 선행 규칙**: `fsops.py` 의 밑줄로 시작하지 않는 모든 함수 본문 첫 문장이 `_guard(` 호출인지 AST 로 확인.
4. **M5 이전**: `[tool.dayclose] milestone < 5` 이면 `executor/` 에 금지 호출이 하나도 없어야 한다(05 §16 P1).
5. **런타임 보조 가드**(`conftest.py`, 11 문서): 테스트 동안 `os.rename/replace/unlink/remove/rmdir/mkdir/chmod`, `builtins.open`(쓰기 모드)을 감싸 호출 스택의 모듈이 `dayclose.executor.fsops` 가 아니면 경로가 `DAYCLOSE_HOME` 아래인지 확인, 아니면 실패.
6. **Swift**: `app/`, `native/` 소스에서 `removeItem`, `moveItem`, `trashItem`, `replaceItem`, `copyItem`, `createFile`, `rename(`, `unlink(`, `recycle` 등장 0(앱 캐시 디렉터리 쓰기는 03/09 가 허용 목록을 정함). 11 문서가 구현.

---

## 16. errno → 오류 코드

| errno / 상황 | 코드 | 비고 |
|---|---|---|
| `EEXIST`(RENAME_EXCL, O_EXCL) | `E_DEST_EXISTS` | trash 는 1회 재선정 후 |
| `ENOENT`(원본) | `E_STALE` | |
| `ENOENT`(목적지 부모, 볼륨 루트) | `E_VOLUME_UNAVAILABLE` if `/Volumes/*` else `E_STALE` | |
| `EXDEV` | `E_STALE` `cross_device` | 복사로 대체하지 않음 |
| `EPERM` | 경로가 TCC 보호 위치(`~/Desktop`, `~/Documents`, `~/Downloads`, `~/.Trash`, `/Volumes/*`, iCloud 동기화 경로)이고 F5 의 잠금 플래그·스티키 비트로 설명되지 않으면 `E_TCC_DENIED`, 그 외 `E_PERMISSION` | 02 §10.5 |
| `EACCES`, `EROFS` | `E_PERMISSION` | |
| `ENOSPC`, `EDQUOT` | `E_VOLUME_UNAVAILABLE` `insufficient_space` | 같은 볼륨 후속 볼륨 간 연산도 건너뜀 |
| `EIO`, `ENXIO`, `ENODEV` | `E_VOLUME_UNAVAILABLE` | |
| `ETIMEDOUT`, 프로브 시간 초과 | `E_VOLUME_TIMEOUT` | |
| `ELOOP`(O_NOFOLLOW 가 링크를 만남) | `E_STALE` `became_symlink` | |
| `ENAMETOOLONG` | `E_STALE` | 계획 검증(§4.4-6)이 막아야 정상 |
| `EBUSY` | `E_STALE` `in_use` | retryable |
| 그 외 예외 | `E_INTERNAL` | 계획 중단(§7.6.2) |

---

## 17. 위협·실패 표 — 파일이 사라지거나 비밀이 새는 모든 경로와 통제

| # | 경로 | 통제 | 검증(11 문서) |
|---|---|---|---|
| T1 | 승인 없이 실행 | G3·G4(승인 행·해시), X1(executor 만 변경) | `plan.apply` on draft → `E_APPROVAL_REQUIRED` |
| T2 | 에이전트가 MCP 로 승인 | MCP 비노출 + 채널 거부 | MCP 도구 목록에 approve 없음, `--channel mcp` approve → `E_APPROVAL_DENIED` |
| T3 | 에이전트가 CLI 승인에 파이프로 입력 | `/dev/tty` 직접 입력, 에이전트 표식 시 대화상자 | stdin 파이프 → 대화상자 경로(샌드박스에서는 `E_APPROVAL_DENIED`) |
| T4 | 에이전트가 DB 에 승인 행 직접 삽입 | G5 감사 교차 검사 | 삽입 후 apply → `E_APPROVAL_REQUIRED` `approval_not_audited` |
| T5 | 승인 후 계획 행 변경 | X3 해시 재계산 | 행 1바이트 변경 → `E_APPROVAL_MISMATCH` |
| T6 | 오래된 승인을 나중에 실행 | G6 24시간 | 시계 주입 25h → `E_APPROVAL_REQUIRED` |
| T7 | 테스트 승인이 운영에서 동작 | 승인·실행 양쪽에서 두 환경변수 확인 | 환경변수 제거 후 apply → `E_APPROVAL_REQUIRED` |
| T8 | 테스트가 실제 파일 변경 | `_guard` 2·3단계 + conftest + 정적 검사 | 샌드박스 밖 경로로 fsops 호출 → `E_SANDBOX_VIOLATION` |
| T9 | 계획 후 파일 내용 변경 | V2, F3, 볼륨 간 해시 2회·전후 동일성 | 계획 후 수정 → `skipped` `E_STALE`, 항목 `stale`, 나머지 계속(FR-EX-003) |
| T10 | 계획 후 같은 경로에 다른 파일(바꿔치기) | 동일성 `(dev, inode)` | 교체 → `E_STALE` |
| T11 | 부모 경로가 심볼릭 링크로 교체 | 부모 fd 기준 확인·이름변경, 목적지 `realpath(parent)==parent` | 교체 주입 → `E_STALE`/`E_PATH_OUTSIDE_ROOTS` |
| T12 | 목적지 덮어쓰기 | X5 `RENAME_EXCL`/`O_EXCL` | 실행 직전 목적지 생성 → `E_DEST_EXISTS`, 기존 파일 내용 불변 |
| T13 | 계획 내·계획 간 같은 이름 | §8.1, §4.8 NFD+casefold | `A.png`/`a.png` 두 연산 → 서로 다른 이름 |
| T14 | 볼륨 간 복사 중 손상 | `F_NOCACHE` 재읽기 해시, 실패 시 원본 유지 | 사본 바이트 변조 주입 → 원본 존재, `failed` |
| T15 | 복사 중 다른 앱이 원본에 씀 | F9 열림 검사, F4 settle, 복사 전후 동일성 | 복사 중 append 주입 → `E_STALE`, 원본 유지 |
| T16 | 복사 후 원본 제거 전 크래시 | 저널 + recover 되감기 | 각 단계 SIGKILL 주입 → recover 후 원본 또는 사본 중 정확히 하나 + 상태 일치(FR-EX-006) |
| T17 | 원본 제거 후 `done` 전 크래시 | recover `absent/match → done` | 주입 |
| T18 | `running` 커밋 유실(전원) | `synchronous=FULL` + `fullfsync` | (실기기 검증 항목 — 자동화 불가, §18) |
| T19 | 이름변경 결과 유실(전원) | 두 부모 디렉터리 `F_FULLFSYNC` 후 `done` | 〃 |
| T20 | 외장 분리 | G8, F2, errno 매핑, T 정리 | 분리 상태 apply → `E_VOLUME_UNAVAILABLE`, 원본 보존(FR-AB-001) |
| T21 | 디스크 가득 | F10, `ENOSPC` 처리 | 작은 디스크 이미지 → `insufficient_space`, 원본 보존 |
| T22 | 보안 자산을 휴지통에 | 02 §10.1 → V3 → F6, 05 §14 | 자산 결정 시도 → `E_PROTECTED`(3중) |
| T23 | 키가 든 폴더를 휴지통에 | F7 내부 검사(현재 파일 시스템) | 계획 후 폴더에 `id_rsa` 추가 → `E_PROTECTED` |
| T24 | 활성 저장소·`.git` 폴더 버림 | 02 §10.1, F7 `contains_repo` | 주입 |
| T25 | 환자 자료 휴지통 | 02 §10.1(`trash` 불허), F7 패턴 | 주입 |
| T26 | iCloud 파일을 옮겨 다른 기기에서 삭제·다운로드 유발 | dataless 항상 차단, iCloud 동기화 파일은 게이트+항목 단위 `trash`+`icloud_propagates`(해시)+`icloud_ack`(G9a)+F5 재확인 | 게이트 거짓 → V3 `E_PROTECTED`; `icloud_ack=0` → `E_APPROVAL_REQUIRED`; 실행 직전 dataless/동기화 상태 변경 → `skipped E_PROTECTED` |
| T27 | 잠금(uchg) 파일 | F5 | `E_PERMISSION` `locked` |
| T28 | 하드 링크로 공간 미확보 오해 | `details.hardlinked` | 표시 |
| T29 | 휴지통 비운 뒤 undo | §11.3 | `E_UNDO_IMPOSSIBLE`(FR-EX-006 장애 주입) |
| T30 | undo 가 남의 파일을 덮음 | `RENAME_EXCL`, `--on-conflict` | 원위치 점유 → `E_DEST_EXISTS` |
| T31 | 두 프로세스 동시 apply | `flock` | 두 번째 `E_LOCKED` |
| T32 | 엔진 버그로 연쇄 실패 | `E_INTERNAL` 시 계획 중단 | 예외 주입 → 남은 연산 미실행 |
| T33 | 승인 대화상자 문자열 주입 | argv 전달 | 파일명 `"; do shell script "…"` → 그대로 표시 |
| T34 | 보관 폴더가 스캔 루트와 겹쳐 무한 반복 | §4.4 `overlaps_scan_root` | 설정 주입 → `E_ARCHIVE_TARGET_MISSING` |
| T35 | 비밀·환자 경로가 로그·봉투로 | §14 로그 규칙, 05 §17 | 누출 스캐너 |
| T36 | Swift 앱이 파일을 직접 휴지통에 | 02 §6, 정적 검사 §15.2-6 | grep 테스트 |
| T37 | 승인 화면에 환자 파일명 노출 | §5.2 고정 문구 | 표시 확인 |
| T38 | 같은 사용자 권한의 적대적 프로세스 | 범위 밖(§0). 흔적: 감사 교차 검사 | — |
| T39 | 아무 프로세스가 `serve --stdio --channel app` 으로 앱 승인 흉내 | `app_button` = Secure Enclave 서명 검증 필수, 없으면 사람 대화상자로(§6.5) | 서명 없는/틀린 서명의 app 채널 approve → `app_button` 기록 0 |
| T40 | `PATH` 앞의 가짜 `osascript` 가 “승인” 출력 | 절대경로 `/usr/bin/osascript` + root 소유 확인 + 고정 환경(§6.4) | `PATH` 에 가짜 도구를 둔 테스트 → 호출되지 않음 |
| T41 | 승인 후 `plan_operations` 직접 수정 | 매 apply(재개 포함) 해시 재계산(G4) | 행 수정 후 apply/재개 → `E_APPROVAL_MISMATCH` |
| T42 | 다른 Mac 에서 복사한 DB·설정으로 실행 | 기기 검사(§7.11: device_id + host UUID 해시 + 계획 device_id) | `app_meta.host_uuid_sha256` 변조 → 모든 F 명령 `E_DEVICE_MISMATCH` |
| T43 | 휴지통을 외부 도구(Mole 등)가 비운 뒤 undo 가 “성공”으로 오인 | 동일성 확인 후에만 undone, 없으면 `trash_emptied` 보고 | 휴지통 파일 삭제 주입 → `E_UNDO_IMPOSSIBLE` |
| T44 | `~/.Trash` TCC 거부를 “비워짐”으로 오판 | `EPERM` → `E_TCC_DENIED`, retryable | `lstat` EPERM 주입 → `undo_failed` `E_TCC_DENIED`, 다시 시도 가능 |
| T45 | 화면 제어 도구가 대화상자 클릭 | 서명 승인(V11 통과 기기), M7 LocalAuthentication(C12, 승인마다), osascript 는 그 전까지 남은 위험(§6.8) | — |
| T46 | 검증 없이 `TRASH_UNLOCK_VERIFIED` 를 `True` 로 바꿈 | 리뷰된 변경 + CI 가 09 §12 검증 행(두 기기 `ok`) 존재 확인(§9.1) | 상수 `True` + 검증 행 비어 있음 → 테스트 실패 |
| T47 | 승인 화면에서 iCloud 경고 줄이 빠짐 | core 가 만드는 요약(`cli_tty`·`native_dialog`)에 고정 줄, 잘림 금지 위치(§6.3-3). 앱은 03 계약 + 서명이 `icloud_propagates` 포함 해시를 덮음(§6.5a). `icloud_ack` 없으면 apply 거부(G9a) | 요약 생성 함수 단위 테스트: `icloud_propagates=1` 연산 1개 → 첫 5줄 안에 문구, 1,500자 제한에서도 유지 |
| T48 | 그룹·규칙 결정이 iCloud 항목을 휴지통 대상으로 | 02 §10.1 예외 2 + `plan.create` V3 의 `actor='user' AND scope='item'` 재확인 | 그룹 결정·`actor=rule` 결정 → 계획 제외 `E_PROTECTED` |
| T49 | iCloud 휴지통을 다른 기기들이 동기화한 뒤 undo | undo 는 원래 iCloud 경로로 이름변경 → 재업로드(§9.1-1c 로 확인). 다른 기기에 같은 이름이 새로 생겼다면 원위치 점유 → `--on-conflict` 규칙(덮어쓰기 없음), iCloud 충돌 사본 가능성은 문구로 안내 | 샌드박스: 원위치 점유 → `E_DEST_EXISTS`; 실기기: §9.1-1c |
| T50 | 사용자가 동기화 루트를 `--icloud-synced no` 로 지정 | 실행 직전 실시간 신호 S1~S3 가 `no` 를 이김(§9.2), `plan.create` 도 같은 신호 사용 | 모드 `no` + S1/S2 신호 주입 → `skipped E_PROTECTED{icloud_synced, live_signal}` |
| T51 | 계획 후 루트 동기화 상태가 바뀜 | F5 의 상태 비교(§9.2-2·3) | 실효값 전환 주입 → `skipped E_PROTECTED` |

---

## 18. 소유자 첫 실사용 전 체크리스트 (12 문서 M5 종료 기준)

실제 `~` 에서 처음 `plan.apply` 를 하기 전에 소유자가 직접 확인하고 날짜와 함께 기록한다(`docs/` 밖 — 개인 기록).

1. `uv run pytest tests/safety` 녹색, 장애 주입 스위트(T16·T17·T20·T21·T29) 녹색 출력 확인.
2. Time Machine(또는 외장 백업)의 최근 백업이 24시간 이내.
3. 샌드박스 데모(`scripts/demo-m5.sh`)로 승인 → 실행 → 되돌리기를 한 번 직접 수행.
4. **실기기 검증**(자동화 불가, 결과를 09 문서에 기록):
   - `~/.Trash` 실험(09 §12 V8 — 이 절차가 그 “08 실험 절차”): 홈 아래 새 빈 폴더 `~/dayclose-trash-probe/` 에 테스트 파일 1개(`probe.txt`, 내용 `dayclose`)를 사람이 직접 만든다 → 그 폴더만 루트로 등록한 별도 `DAYCLOSE_HOME` 으로 결정·계획·승인·apply(trash) → `~/.Trash` 안 결과 `lstat`·undo → 터미널(FDA 없음)과 DayClose.app(FDA 있음) 각각에서 반복. 기록: `lstat` 결과(성공/EPERM), rename 결과, undo 결과, Finder 의 “되돌려 놓기” 가능 여부(예상: 불가). 다른 휴지통 항목은 열거하지 않는다(목록을 읽거나 출력하지 않음). 끝나면 테스트 파일과 폴더는 사람이 직접 지운다.
   - `/Volumes/External` 의 `.Trashes/<uid>` 존재·생성 여부.
   - 볼륨 간 이동 후 Finder 태그·격리 속성(`com.apple.quarantine`)이 보존되는지.
5. 첫 계획은 `--items` 로 10개 이하, 전부 같은 볼륨 `trash`. `--dry-run` 결과를 먼저 본다.
6. 실행 직후 그중 하나를 `plan.undo --op` 로 되돌려 원위치·내용을 확인.
7. 그다음에만 `move`·`archive`(외장) 를 각각 1개로 시험.

---

## 19. 결정·변경 요청·남은 위험·열린 질문

### 19.1 이 문서의 결정 요약

1. 승인 수단은 core 가 환경으로 고른다(§6.2). 사람 대기 중에는 잠금을 잡지 않는다(§6.1).
2. 에이전트 표식이 있으면 `cli_tty` 금지(§6.3). 대화상자 기본 버튼 “취소”, 텍스트는 argv(§6.4).
3. 승인 유효 24시간, 감사 교차 검사(§7.1 G5·G6). 예약 채널은 apply 불가(G10).
4. 전역 볼륨 검사로 외장 분리 시 시작 전 거부(G8).
5. 실행 연결은 `synchronous=FULL`+`fullfsync`(§7.1).
6. 한 계획 2,000 연산, 볼륨 간 200 GiB 상한(§4.1, §4.5).
7. 결정 후 수정된 파일은 계획에서 제외하되 `decided` 유지(§4.2 V2).
8. 계획 경로는 실제 경로로 해석해 저장(§4.4).
9. 보관 연·월 = 파일 mtime 의 로컬 날짜(§4.4).
10. 네트워크 볼륨은 원본·목적지 불가(§3.2). 휴지통 디렉터리는 만들지 않음(`.Trashes/<uid>` 만 예외)(§3.4). Put Back 미지원.
11. 디렉터리 연산은 지금의 파일 시스템을 걸어 보호 대상을 찾는다, 다 못 보면 보호(§7.2.1).
12. 볼륨 간 이동은 열린 파일 건너뜀(§7.2 F9). 같은 볼륨은 허용.
13. 부분 실패 시 자동 롤백 없음(§7.6.1). `E_INTERNAL` 이면 중단.
14. recover 는 자동 실행하지 않고, 원본을 지우지 않으며, 확정 전 사본은 되감는다(§10).
15. undo 는 새 계획을 만들지 않고 원 연산 행에 기록, 볼륨 간 이동 후 편집된 파일은 되돌리지 않음, 만든 디렉터리는 남김(§11).
16. 휴지통 충돌 이름에 `op_id`(§8.2).
17. 환자 항목은 승인 화면에서 이름 대신 고정 문구(§5.2).

18. `app_button` 은 Secure Enclave 서명 검증 성공일 때만, 부모 프로세스 검사는 쓰지 않음. 서명 없으면 대화상자로 저하. M7 에서 대화상자 구현을 LocalAuthentication 으로 교체(§6.5).
19. 승인 경로의 시스템 도구는 절대경로·root 소유·고정 환경(§6.4).
20. 무인 Mac mini 승인은 화면 공유 또는 ssh `cli_tty`, 기기 간 원격 승인 없음(§6.7).
21. 실행 중 중지는 SIGINT(앱은 serve 자식에 신호). 이름변경은 마치고, 복사는 임시 파일을 지워 `pending` 으로, 남은 연산은 시작하지 않음. 결과는 재개 가능한 `executing` + `E_PARTIAL`(§7.6.2, 02 §5.5).
22. 기기 검사에 host UUID 해시를 더하고, 불일치 시 모든 파일 변경 명령 거부(§7.11).
23. 휴지통 비움·TCC 거부를 undo 에서 구분해 보고(§11.2).
24. iCloud 동기화 파일 `trash`(C11): 계획 시 `icloud_propagates=1`, 승인 화면 별도 줄 + `icloud_ack`, 실행 직전 게이트·동기화 상태·dataless 재확인, 상태가 승인 때와 다르면 실행하지 않음. 해제는 §9.1 검증 후 `TRASH_UNLOCK_VERIFIED`.
25. 계획 단계에서 내용이 바뀐 결정은 `decided`+`last_error_code='E_STALE'`(재결정 필요), 실행 단계에서 바뀐 것은 `stale`+`subject_changed`(재탐지).

### 19.2 기준 문서 변경 요청 — 반영 상태 (2026-11-24 재조정 후)

| # | 요청 | 상태 |
|---|---|---|
| R1 | `plan_operations.post_dev/post_inode/post_mtime_ns` | 반영(06 §5.4). §7.3 8단계, §10.3, §11.2 |
| R2 | `src_kind`, `create_dirs_json`, `details_json` 컬럼 | 반영. `summary_json` 은 집계만(§4.7), `create_dirs` 는 `create_dirs_json` 에서 해시에 포함(§5.1) |
| R3 | `executing → cancelled/partial/failed`(cancel), `undo_state=undoing` | 반영(06 §4.4·4.5, 남은 op `E_CANCELLED`). §7.10, §10.5, §11.2 |
| R4 | `planned → failed`(비-STALE skipped) | 반영(06 §4.1) |
| R5 | `rename` 결정 동작 | 반영(06 `decision_action`, `file_decision_action`; 02 §5.3 `--dest`). §7.4.5 |
| R6 | executor 의 `file_entries` 직접 갱신, 압축 규칙 | 반영(06 §4.1 말미, §8) |
| R7 | 수정된 파일의 재질문 경로 | 반영: plan.create 단계는 `decided`+`last_error_code='E_STALE'`(§4.2 V2), 실행 단계는 `stale`+`closed_reason='subject_changed'` 후 재탐지(06 §4.1) |
| R8 | `common/fsmeta.py`, osascript `--` argv | 반영(02 §6) |
| R9 | 원본 제거 두 함수 | 반영(02 §6) |
| R10 | `plan_hash_short`, `resumable` 응답 필드 | 10 문서 소관 — 확인 필요. `stopped_by_user` 도 추가(§7.6.2) |
| R11 | `run_tool` 절대경로·고정 환경 | 반영(02 §6). 남은 세부: 승인 경로 도구의 “root 소유·그룹/기타 쓰기 불가” 검사(§6.4)를 `system_path` 의 조건으로 02 에 명시하면 좋음 |
| R12 | `app_signature`, `core.app_key`, `app_meta` 키 | 반영(02 §5.3·§10.3, 06 §5.1·`approval_method`). core 검증은 M5, 앱 서명은 V11 통과 후, 대화상자의 LocalAuthentication 교체는 M7(§6.5 표) |
| R13 | `E_DEVICE_MISMATCH`, `app_meta.host_uuid_sha256` | 반영(02 §11 종료 5, 02 §10.3 4a, 06 §5.1). §7.11 |
| R14 | iCloud 완화 조건 | 반영 — 소유자 결정 C11. §9.1 이 `TRASH_UNLOCK_VERIFIED` 를 켜는 검증 절차(M5 종료 기준) |

기준 문서와 이 문서 사이에 남은 불일치(재조정 담당에 전달):
- 02 §10.2-5 “볼륨 간 `move` 만 복사→검증(크기+SHA-256)→원본 제거” — `archive` 도 볼륨 간이면 같은 경로이고(§7.4.4, FR-AB-001), 디렉터리는 SHA-256 이 아니라 매니페스트 해시(§4.6). “볼륨 간 `move`·`archive` 만 복사→검증(크기+SHA-256 또는 매니페스트)→원본 제거” 로 고칠 것.
- 06 §4.4 의 `plan.cancel` 전이는 `executing` 경우만 `E_CANCELLED` 를 명시 — 이 문서는 `draft`/`approved` 취소의 연산 행에도 `E_CANCELLED` 를 쓴다(§7.10). 같은 문구를 06 의 `draft`,`approved` → `cancelled` 행에 넣으면 일치.
- 06 `approvals.icloud_ack` 는 “승인 화면이 경고를 보여 줬고”라고 적지만 `app_button` 의 경우 core 는 앱 화면을 볼 수 없다 — 03 이 그 줄의 표시를 계약으로 갖고, 08 은 서명이 `icloud_propagates` 를 덮는다는 점으로 보증한다(§6.5a). 03 확인 필요.

### 19.3 남은 위험 (닫지 못함)

1. **같은 사용자 권한의 적대적 프로세스**: DB 행·감사 행·해시를 함께 위조하거나, `script(1)` 로 TTY 를 흉내 내 8자를 입력할 수 있다(에이전트 표식을 지운 채). 근본적으로 그런 프로세스는 DayClose 없이도 파일을 지운다(§0).
1-1. **화면 제어**: 접근성·화면 제어 권한을 가진 도구는 osascript `native_dialog` 의 [승인] 을 누를 수 있다(§6.8). M7 전, 그리고 V11 이 통과하지 못한 Mac 에서는 앱 경로도 이 대화상자로 저하되므로 위험이 남는다. M7 의 LocalAuthentication 대화상자가 이를 닫는다.
1-2. 앱 공개키 **등록**(`core.app_key register`) 자체는 대화상자/TTY 확인이므로, 등록 순간에 화면 제어 도구가 있으면 공격자 키가 등록될 수 있다. 등록은 1회이고 지문을 사람이 앱 화면과 대조하도록 문구로 안내한다.
2. `~/.Trash` 의 TCC 동작(터미널 FDA 유무에 따른 이름변경 가능 여부)은 실기기 검증 전이다(§18-4).
3. 전원 차단 내구성(T18·T19)은 자동 테스트로 증명할 수 없다. `F_FULLFSYNC` 에 의존.
4. 디렉터리 안 파일이 다른 앱에서 열려 있는지는 검사하지 않는다(§9). 볼륨 간 디렉터리 이동 중 그 안의 파일에 쓰기가 일어나면 매니페스트 불일치로 실패(유실은 아님 — 원본 유지).
5. `archive.root` 가 암호화되지 않은 외장 볼륨이면 환자 자료가 평문 사본으로 남는다. 소유자 결정(C14)으로 차단하지 않고 `W_ARCHIVE_UNENCRYPTED` 경고만(§4.4-7). 암호화 판정이 불가능한 볼륨도 경고 쪽으로 처리한다.
6. macOS “30일 후 휴지통 자동 비우기”가 켜져 있으면 undo 가능 기간이 30일로 제한된다.
7. 볼륨 간 이동 시 원본 소유자·birthtime 은 보존되지 않을 수 있다.
8. 에이전트 표식 목록은 에이전트 제품이 바뀌면 낡는다.

### 19.4 열린 질문

소유자가 확정한 것(PRD §9.1): 승인 시 Touch ID/암호는 M7 부터 **승인할 때마다**(C12, §6.5 표), 승인 유효 24시간(C13), `archive.root` 암호화는 경고만(C14), iCloud 휴지통 허용 조건(C11, §9.1).
남은 것: 볼륨 간 이동 200 GiB·한 계획 2,000 연산 상한(이 문서의 결정 6 — 실사용 후 조정), §9.1-3 의 업로드 완료 판정 방법, §9.2 의 Desktop/Documents 동기화 실시간 신호가 실기기에서 성립하는지(09 §12).
