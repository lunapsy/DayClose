# 04 — 파일 인텔리전스 (FILE INTELLIGENCE)

> 범위: `collect`(fs·git·apps·brew·login_items 수집기)와 `intel`(카테고리·그룹·중복·버전·프로젝트 매칭·휴리스틱 제안)의 알고리즘.
> 이름·enum·테이블·명령은 `02-ARCHITECTURE.md`, `06-DATA-MODEL.md` 를 그대로 쓴다. 보안 자산 판정은 `05-SECURE-VAULT.md`, 실행은 `08-SAFE-EXECUTION.md`, AI·학습 규칙은 `07-AI-MEMORY-POLICY.md`, macOS 시스템 소스(TCC·스크린샷 위치·앱 마지막 사용일·로그인 항목 원천)는 `09-MACOS-INTEGRATION.md`.
> **이 문서의 모든 기능은 AI 가 꺼진 상태(`ai.enabled=false`, 기본값)에서 동작해야 한다.** AI 는 이 문서가 만든 제안 위에 얹히는 선택 사항이다(07).

## 0. 파이프라인 한눈에

`scan.run` 한 번은 아래 순서로 진행한다. 각 단계는 사용자 파일을 **읽기만** 한다.

```
1. 루트 프로브      common/paths.probe — 실패 루트는 건너뜀 (W_ROOT_UNAVAILABLE / W_TCC_DENIED)
2. collect.fs       루트 순회 → 스냅샷 diff → file_entries 갱신 + file_events 기록      phase=fs
3. collect.git      projects.roots 의 저장소 상태 → projects 갱신                       phase=git
4. vault (05)       새/수정 엔트리에 대해 보안 자산 판정 → vault_assets                  phase=vault
5. collect.apps / brew / login_items (M3, 주기 조건 충족 시)                            phase=apps|brew|login_items
6. intel            카테고리 → 항목 생성 규칙 → 중복·버전·설치파일·프로젝트 매칭 → 제안  phase=review
7. policy           protection / sensitivity / allowed_actions / suppression 일치 (07·05·02 §10.1)
8. review           항목 상태 전이(detected → proposed | suppressed), 그룹 배정, 세션 지표
```

- 2~5 는 수집(사실 기록), 6~8 은 판단. 판단 단계는 같은 `scan.run` 트랜잭션 묶음 안에서 수집 결과만 보고 결정적으로 계산한다(같은 DB 상태 → 같은 결과).
- 결정: 판단 단계(6~8)는 수집 단계가 하나라도 성공하면 실행한다. 실패한 수집기는 `scan_runs.status='partial'` + 해당 경고. 이유: 외장 루트 하나 때문에 오늘의 결산 전체가 사라지면 안 된다.
- 쓰기 잠금(`state.lock`)은 `scan.run` 전체 동안 보유한다(02 §7).

---

## 1. 스캔 루트

### 1.1 기본 루트 (`core.init`, FR-CORE-002)

| 경로 | `kind` | `max_depth` | `file_level` | 비고 |
|---|---|---|---|---|
| `~/Downloads` | `downloads` | 6 | 1 | |
| `~/Desktop` | `desktop` | 6 | 1 | |
| 스크린샷 저장 위치 | `screenshots` | 2 | 1 | `defaults read com.apple.screencapture location` 결과가 Desktop 과 다를 때만(읽기 방식은 09). 경로가 다른 루트 안이면 등록하지 않고 그 루트의 하위로 취급 |
| `~/Documents` | `documents` | 8 | 1 | 기본 루트 확정(2026-11-24). dataless 규칙(§2.6) 적용 |
| `~/Library/Mobile Documents/com~apple~CloudDocs` | `icloud_drive` | 8 | 1 | 기본 루트 확정(02 §10.6). iCloud 동기화 경로 — 허용 동작은 02 §10.1 예외 2 의 표(다운로드된 파일의 `trash` 는 해제 게이트가 열렸을 때만, `move`/`archive`/`rename` 은 v1 에서 불허). `exclude_globs` 의 `**/Library/**` 는 루트 기준 상대경로로 매칭되므로 이 루트 자체를 제외하지 않는다(§2.2) |
| `config.projects.roots` 각각 (기본 `~/dev`) | `projects` | 2 | 0 | 저장소 탐지용. 파일 단위 항목 없음 |
| `~/Library/Developer/Xcode/DerivedData` (존재 시) | `custom` | 1 | 0 | 결정: 개발 캐시(§10) 전용 루트. 이유: `vault_extra` 와 달리 사용자 파일이 아니고, `file_entries.root_id NOT NULL` 이라 캐시 디렉터리 엔트리를 담을 루트가 필요(02 §9 의 `init` 규칙). M3 부터 사용 |

`vault_extra` 루트(`config.vault.extra_paths`)는 05 가 등록 규칙을 정한다. fs 수집기는 이 루트를 순회하되 **항목은 만들지 않고**(`file_level` 값과 무관) 엔트리만 vault 에 넘긴다.

중첩 루트: 루트 A 가 루트 B 안에 있으면(예: 스크린샷 폴더가 `~/Documents/Screenshots`) 각 엔트리는 **가장 깊은(가장 구체적인) 루트**에 속한다. 바깥 루트의 순회는 안쪽 루트 경로에서 가지치기한다. `root.add` 는 같은 경로 중복을 거부(06 유니크 인덱스)하고, 중첩은 허용한다.

중복 루트 제거(02 §10.6): 스캔 시작 시 각 루트 디렉터리의 `(st_dev, st_ino)` 를 구해, 같은 값을 가진 루트가 둘 이상이면(“데스크탑 및 문서 폴더” iCloud 동기화, 사용자가 같은 폴더를 다른 경로로 두 번 등록 등) **루트 ID 가 가장 작은 것 하나만** 순회하고 나머지는 이번 run 에서 건너뛴다(엔트리 유지, `stats.duplicate_roots`). 심볼릭 링크는 따라가지 않으므로 링크로 연결된 경로는 별도 트리가 되지 않는다.

iCloud 동기화 루트 판정(02 §10.1 예외 2, 06 `scan_roots`): 세 컬럼을 쓴다 — 사용자 지정 `icloud_synced_mode`(`auto`|`yes`|`no`, 기본 `auto`), 실효값 `icloud_synced`(0/1), 실효값의 근거 `icloud_synced_source`(`detected`|`user`|`assumed`). fs 수집기는 **매 scan 시작 시** 루트마다 실효값과 근거를 다시 계산하고, 둘 중 하나가 바뀌었을 때만 UPDATE 한다. 수집기는 `icloud_synced_mode` 를 절대 쓰지 않는다(사용자만 `root add … --icloud-synced`, `root set ROOT_ID --icloud-synced` 로 바꾼다 — 02 §5.3. `root.set` 은 MCP 비노출).

```
effective(root):
    live = live_signal_root(root)         # 아래 '실시간 신호' — 양성이면 사용자 'no' 보다 우선 (08 §9.2)
    if root.icloud_synced_mode == 'yes': return (1, 'user')
    if root.icloud_synced_mode == 'no':  return (1, 'detected') if live else (0, 'user')
    # auto
    if live: return (1, 'detected')
    sig = detect(root)                    # True | False | None
    if sig is True:  return (1, 'detected')
    if sig is False: return (0, 'detected')
    if root.kind in ('desktop', 'documents'): return (1, 'assumed')   # 신호 없음 → 안전 쪽
    return (0, 'detected')
```

`detect(root)` (`common/paths.is_icloud_synced(path) -> bool | None`, 테스트에서 주입):
1. `kind = 'icloud_drive'` → `True`.
2. 루트 디렉터리의 `realpath` 가 iCloud Drive 루트(`~/Library/Mobile Documents/com~apple~CloudDocs`) 아래 → `True`.
3. 루트가 `~/Desktop` 또는 `~/Documents` 이면 “데스크탑 및 문서 폴더” iCloud 동기화 여부를 09 §12(V17)가 확정한 방법으로 확인 → 켜짐 `True`, 꺼짐이 확인됨 `False`. V17 방법이 정해지기 전, 또는 확인 중 오류·시간 초과 → `None`.
4. 그 외 루트(Downloads·custom 등)는 1·2 가 아니면 `False`.

**실시간 신호**(08 §9.2, 04·07·08 공통 규칙): `lstat`·`realpath` 만 쓰고 파일 내용은 열지 않는다(다운로드 유발 없음). 하나라도 양성이면 그 대상은 iCloud 동기화로 취급한다.
- S1 경로가 `~/Library/Mobile Documents/` 또는 `~/Library/CloudStorage/` 아래(`realpath` 기준). `CloudStorage` 는 File Provider 기반 서드파티 동기화(Dropbox·Google Drive 등)도 포함하며, 같은 이유(삭제 전파·다운로드 유발)로 같은 제한을 받는다.
- S2 루트가 `desktop`/`documents` 이고 `~/Library/Mobile Documents/com~apple~CloudDocs/Desktop`(또는 `…/Documents`)이 존재(`lstat`).
- S3 파일에 `SF_DATALESS` 플래그(§2.6) — 파일 단위.
`live_signal_root(root)` 는 S1·S2 를 루트 디렉터리에 적용한 결과다.

**항목에 쓰는 실효 상태**: `allowed_actions`·`blocked_reasons`·제안(§13)·중복 keeper 선택(§12.1)에 쓰는 항목의 `icloud_synced` 는

```
item.icloud_synced = root.icloud_synced (저장된 실효값) OR S1(item.path) OR S3(item)
```

즉 사용자가 `no` 로 지정한 루트라도 실시간 신호가 양성인 항목은 iCloud 동기화로 처리한다. 결정 이유: 사용자 지정은 “판정이 실패할 때의 대체 수단”이지 실제로 동기화 중인 파일의 삭제 전파 위험을 없애지 못한다. 이 OR 계산은 intel 이 항목마다 하고, `policy`·`plan`·`executor` 는 같은 함수(`common/paths.live_icloud_signal`)를 다시 불러 재검증한다(08 §9.2).

결과: V17 이 확정되기 전에는 `~/Desktop`·`~/Documents` 가 `auto` 일 때 항상 `icloud_synced=1, source=assumed` 다. 동기화를 쓰지 않는 사용자는 `root set ROOT_ID --icloud-synced no` 로 풀고(source `user`), 이것이 V17 실패 시의 대체 수단이다. `root.list` 는 세 값을 모두 보여 준다(02 §5.3). 결정: 이전 scan 의 값을 이어받지 않는다 — 매 scan 의 결과는 그 scan 의 입력(모드·kind·판정 결과)만으로 정해진다(결정성, 테스트 재현성).

항목 단위 값: intel 은 항목마다 `icloud_synced`(루트 값)와 `is_dataless`(§2.6)를 계산해 넘기고, 항목 JSON 의 같은 이름 필드가 된다(02 §5.6). `allowed_actions`·`blocked_reasons` 는 `policy` 가 02 §10.1 예외 2 의 표로 계산한다:
- dataless → `trash`/`move`/`archive`/`rename` 모두 불가(`dataless`).
- `icloud_synced` + 다운로드됨 → `trash` 는 해제 게이트(`policy/icloud.py: TRASH_UNLOCK_VERIFIED` **그리고** `config.icloud.allow_trash`)가 참일 때만 허용, 아니면 `icloud_synced`. `move`/`archive`/`rename` 은 v1 에서 허용하지 않는다(`icloud_synced`, 해제 예정 없음 — 확정).
intel 은 이 값들을 바꾸지 않고 읽기만 한다. 이 문서에서 “trash 가능한 iCloud 항목” 은 위 조건으로 `allowed_actions` 에 `trash` 가 들어 있는 항목을 뜻한다.

### 1.2 루트 접근 실패

| 상황 | 판정 | 결과 |
|---|---|---|
| 경로 없음 | `missing` | 루트 건너뜀, `W_ROOT_UNAVAILABLE`. 기존 엔트리는 **삭제 처리하지 않는다** |
| `/Volumes/*` 프로브 시간 초과 | `timeout` | 동일. 프로브 스레드는 버림(02 §10.5) |
| EPERM (TCC) | `tcc_denied` | `W_TCC_DENIED`, 기존 엔트리 유지 |
| 하위 디렉터리 하나 EACCES/EPERM | — | 그 하위 트리만 건너뜀, `W_PERMISSION_SKIPPED`(count). **그 하위 트리에 있던 기존 엔트리는 present 유지**(§2.4 “보이지 않음 ≠ 삭제”) |

---

## 2. 증분 스캔과 스냅샷 diff (`collect/fs.py`)

### 2.1 순회

- `os.scandir` 재귀(명시적 스택, 재귀 호출 아님). `DirEntry.stat(follow_symlinks=False)` 1회로 `lstat` 결과를 얻는다. 심볼릭 링크는 따라가지 않는다(엔트리 `kind='symlink'`, 크기 = 링크 자체).
- `st_flags`(`UF_*`, `SF_*`)와 `st_birthtime` 을 함께 읽는다(macOS `os.stat_result` 제공).
- 같은 디렉터리 안에서는 이름 정렬 순서로 처리(결정성, 테스트 재현성).
- 루트의 `st_dev` 와 다른 `st_dev` 의 하위 디렉터리(마운트 경계)는 들어가지 않는다(`-xdev` 와 동일). 결정: 루트 안에 마운트된 볼륨은 별도 루트로 등록해야 한다. 이유: 볼륨 행(hang) 방지 프로브가 루트 단위로만 동작한다.
- 깊이: 루트 자신 = 0. `depth > max_depth` 인 디렉터리는 들어가지 않고 그 디렉터리 자체만 엔트리로 남긴다.

### 2.2 제외 규칙

평가 순서(먼저 일치하면 확정):

1. **내장 제외(끌 수 없음)**: `DAYCLOSE_HOME`, `~/Library/Caches/DayClose`, `~/Library/Logs/DayClose`, 모든 `.Trash`/`.Trashes`/`.DocumentRevisions-V100`/`.Spotlight-V100`/`.fseventsd`/`.TemporaryItems`, `.DS_Store`, `._*`(AppleDouble), `Icon\r`. 이유: 자기 자신·시스템 메타데이터를 변경으로 세면 매 스캔이 “변경”이 된다.
2. **설정 제외**: `config.scan.exclude_globs`(02 §9 기본값). 글롭은 **루트 기준 상대경로**(루트 자신은 빈 경로, 구분자 `/`)에 매칭하며 `**` 는 0개 이상 디렉터리, `*` 는 구분자를 넘지 않는다(02 §9). 그래서 `**/Library/**` 는 iCloud Drive 루트(`~/Library/...` 아래) 자체가 아니라 루트 **안쪽**의 `Library` 폴더만 제외한다. 디렉터리가 `<글롭>/**` 형태에 일치하면 그 디렉터리 내부만 제외하고 디렉터리 엔트리 자체는 남긴다(예: `node_modules` 디렉터리는 엔트리로 남고 내용은 순회하지 않음 → §10 개발 캐시가 크기를 따로 잰다).
3. **git 작업 트리 가지치기**: `projects` 가 아닌 루트에서 `.git`(디렉터리 또는 `gitdir:` 파일)을 가진 디렉터리를 만나면, 그 디렉터리를 `kind='dir'` 엔트리로 남기고 **내부를 순회하지 않는다**. 그 경로는 `collect.git` 의 탐지 후보로 넘긴다(§8.1). 이유: 저장소 내부 파일은 어차피 이동·휴지통 제안 대상이 아니고(FR-SO-004), 수천 개의 소스 파일이 결산을 덮는다.
4. **작성 중 파일(settle)**: 다음 중 하나면 이번 스캔에서 **엔트리를 만들지도 갱신하지도 않는다**(없는 것으로 취급하되 기존 엔트리 삭제 판정에서도 제외):
   - 확장자 `crdownload`, `download`(Safari 다운로드 패키지), `part`, `partial`, `opdownload`, `tmp`, `!ut`, `aria2`
   - `now - mtime < scan.settle_seconds`(기본 60초)
   결정: 다음 스캔에서 완성된 파일이 `created` 로 잡힌다. 이유: 다운로드 중인 파일을 “새 파일”로 두 번 세지 않기 위함(Binky 의 stable-file gate 아이디어, 13 문서).

### 2.3 패키지 디렉터리

`config.scan.package_dirs_as_files=true` 이면 아래 디렉터리는 `kind='package'` 엔트리 1개로 만들고 내부를 엔트리로 남기지 않는다.

- 확장자: `app`, `bundle`, `framework`, `plugin`, `kext`, `photoslibrary`, `musiclibrary`, `tvlibrary`, `fcpbundle`, `logicx`, `band`, `pages`, `numbers`, `key`, `rtfd`, `xcarchive`, `playground`, `scriptd`, `sparsebundle`, `pkg`(번들형 구식 pkg), `lproj` 제외.
- 또는 `NSFileWrapper` 형식 판별이 필요한 그 외 패키지는 다루지 않는다(확장자 목록이 유일한 기준, 결정: `mdls kMDItemContentTypeTree` 호출 비용 회피).

패키지 크기: 내부를 `os.scandir` 로 합산하되 **엔트리 20,000개 또는 2초**에서 중단하고 그때까지의 합계를 기록, `stats.truncated_sizes += 1`, 경고 `W_TRUNCATED`. 패키지의 `mtime_ns` 는 패키지 디렉터리 자신의 값(내부 변경은 감지하지 않음 — 결정: `.app` 자동 업데이트를 매일 “수정”으로 세지 않기 위함. 앱 버전 변화는 `collect.apps` 가 Info.plist 로 따로 본다).

디렉터리(`kind='dir'`) 크기: 이번 순회에서 본 하위 파일·패키지 크기의 합(제외된 하위 트리는 0). 추가 I/O 없음.

### 2.4 비교 키와 이벤트 판정

이전 상태 = `file_entries WHERE present=1 AND root_id IN (이번에 성공적으로 순회한 루트)`. 메모리 색인 두 개를 만든다.

- `by_path: path → row`
- `by_ident: (dev, inode) → [row]` — 하드링크(`st_nlink>1`)는 같은 키에 여러 행이 올 수 있다.

현재 관측 = 순회 결과 `obs(path, dev, inode, size, mtime_ns, ctime_ns, birthtime_ns, nlink, kind, flags)`.

판정은 **모든 루트를 다 순회한 뒤 한 번에** 한다(루트 간 이동을 잡기 위해).

```
for o in 관측:
    p = by_path.get(o.path)
    if p and (p.dev, p.inode) == (o.dev, o.inode):
        if p.kind in ('file','symlink','package') and (p.size != o.size or p.mtime_ns != o.mtime_ns):
            → modified
        else:
            → 변경 없음 (mode/flags/ctime 만 바뀐 경우 엔트리 필드만 조용히 갱신, 이벤트 없음)
        mark_seen(p); continue
    if p and (p.dev, p.inode) != (o.dev, o.inode):
        # 같은 경로, 다른 inode: 안전 저장(임시 파일 작성 후 rename)이 대표적
        if o.(dev,inode) 가 다른 경로의 이전 엔트리 q 와 일치(아래 이동 규칙 충족):
            → q 는 moved(q.path → o.path), p 는 아래 '사라짐' 처리로
        else:
            → p 의 modified (엔트리 identity 를 새 dev/inode 로 교체)
        continue
    # 경로가 처음 보임
    cand = by_ident.get((o.dev, o.inode)) 중 아직 seen 아니고, 그 경로가 이번 관측에 없는 행
    if cand 가 정확히 1개 and 이동 규칙 충족:
        → moved (old_path=cand.path, new_path=o.path, root_id 갱신)
    else:
        → 보류 목록 appeared 에 추가
seen 되지 않은 이전 엔트리 → 보류 목록 vanished
2차 매칭(볼륨 간 이동; 여기서 새로 계산한 해시는 메모리 전용 — §2.5): appeared 와 vanished 에서
    kind=='file' and 이름 동일 and size 동일 and size >= 1 MiB
    and (양쪽 sha256 가 있으면 일치, 없으면 vanished.sha256 이 있고 appeared 를 해시해서 일치)
    가 1:1 로 대응하면 → moved (cross_device). 나머지 appeared → created, vanished → deleted
```

이동 규칙(1차 identity 매칭이 유효하려면 모두 충족):
1. `kind` 동일.
2. `birthtime_ns` 가 양쪽 다 있으면 같아야 한다. 이유: APFS 는 inode 번호를 재사용할 수 있어 “삭제 후 다른 파일 생성”이 이동으로 오인될 수 있다. rename 은 birthtime 을 보존한다.
3. `nlink == 1`(하드링크면 경로 매칭만 신뢰, identity 매칭 안 함).
4. 이전 경로가 이번 관측에 **존재하지 않는다**.

추가 규칙:
- **보이지 않음 ≠ 삭제**: 이전 엔트리의 경로가 (a) 이번에 건너뛴 루트, (b) 권한 오류로 건너뛴 하위 트리, (c) settle 중 파일, (d) `max_depth` 가 줄어 이번에 들어가지 않은 깊이 아래에 있으면 vanished 에 넣지 않는다(present 유지, `last_seen_run_id` 미갱신).
- 디렉터리(`kind='dir'`)는 `created`/`deleted`/`moved` 만 기록하고 `modified` 는 기록하지 않는다. 이유: 하위 변경마다 디렉터리 mtime 이 바뀌어 잡음이 된다.
- 디렉터리가 `moved` 되면 그 하위 엔트리는 경로 접두사만 바뀐 것이므로 하위마다 `moved` 이벤트를 만들지 않고 경로만 일괄 갱신한다(이벤트는 디렉터리 1건). 결정: FR-CORE-003 “이름변경 1건 = 이벤트 1개”를 폴더에도 적용.
- 대소문자만 다른 이름변경(APFS 대소문자 무시 볼륨): 같은 inode, 다른 경로 → `moved`.
- 이벤트 행: `file_events(event, old_path, new_path, size_delta)` — `created`: new_path, `modified`: new_path + size_delta, `deleted`: old_path + `-size`, `moved`: 둘 다. `detected_at` = 이번 run 시작 시각.
- 엔트리 갱신: `created` → 새 행(`first_seen_run_id`), `deleted` → `present=0, deleted_run_id`, `moved` → 같은 행의 path/name/ext/root_id 갱신, `modified` → size/mtime/ctime(+필요 시 dev/inode) 갱신 및 **`sha256` 무효화**(`sha256_mtime_ns != mtime_ns` 이면 다음 필요 시 재계산).
- 변경 없는 재스캔 → 이벤트 0(FR-CORE-003 AC).
- 해시 저장 시점: intel 단계(§0 의 6, vault 판정 뒤)에서 계산한 중복 후보 해시만 `sha256`/`sha256_mtime_ns` 에 저장한다. vault 가 자산으로 판정한 엔트리는 vault 가 같은 트랜잭션에서 두 값을 NULL 로 지운다(06 §6, 05).

### 2.4a executor 와의 계약 (06 §4.1 “실행 결과의 스냅샷 반영”)

executor 는 연산 `done` 과 같은 트랜잭션에서 `file_entries` 를 직접 갱신한다: 새 경로·`root_id`·dev/inode, 목적지가 어느 루트에도 속하지 않으면 `present=0, deleted_run_id=NULL`. 수집기는 이를 다음과 같이 다룬다.
- 이전 상태 색인은 `present=1` 행만 읽으므로 executor 가 루트 밖으로 보낸 행은 vanished 가 되지 않는다 → `deleted` 이벤트·`stale` 전이 없음.
- executor 가 루트 안의 새 경로로 옮긴 행은 다음 scan 에서 경로·identity 가 그대로 일치 → 이벤트 없음, 새 항목 없음.
- 수집기는 `deleted_run_id IS NULL AND present=0` 행을 되살리거나 지우지 않는다(압축은 06 §8 이 그 연산의 `finished_at` 기준으로 처리). undo 가 원위치로 되돌리면 executor 가 다시 `present=1` 로 만든다.
- 휴지통(`trash`) 결과 경로는 내장 제외(§2.2-1)라 어떤 루트에도 들어오지 않는다.
- 같은 run 안에서 수집기와 executor 가 겹치지 않는다(둘 다 `state.lock` 필요, 02 §7).

### 2.5 해시 정책

SHA-256 은 **지연 계산**한다. 모든 파일을 해시하지 않는다.

| 해시하는 경우 | 조건 |
|---|---|
| 중복 후보 | 같은 `size` 를 가진 present `file` 엔트리가 2개 이상이고, 그중 하나 이상이 이번 리뷰 기간의 새 항목 후보(§4) |
| 볼륨 간 이동 2차 매칭 | §2.4 — **결과는 메모리에서만 쓰고 `file_entries.sha256` 에 저장하지 않는다**(06 §6 해시 저장 규칙: vault 판정 전에 계산한 해시). 이 해시는 vault 단계(§0 의 4)보다 먼저 계산되기 때문이다 |
| vault 지문 | 05 가 요청(`fingerprint_sha256`) |
| 계획 시점 | 08 (`pre_sha256`) — collect 가 아닌 plan 이 요청 |

제한:
- `size > config.scan.hash_max_bytes`(64MB) → 계산하지 않음, `W_HASH_SKIPPED_LARGE`(count). 중복 탐지 제외.
- dataless(§2.6) → 계산하지 않음.
- 0바이트 파일 → 해시하지 않고 중복 탐지 제외.
- 한 run 의 총 해시 바이트 예산 `scan.hash_budget_bytes`(기본 2 GiB). 초과분은 다음 run 으로 미루고 `W_TRUNCATED`. 우선순위: 새 항목 후보 → 크기가 큰 순.
- 읽기: 1 MiB 버퍼, `open(path, 'rb')` (읽기 전용 — 02 §6 변경 금지 규칙에 해당하지 않음). 읽는 중 `mtime` 이 바뀌면 결과 폐기.
- 결과 저장: `sha256`, `sha256_mtime_ns = mtime_ns`.

### 2.6 iCloud dataless 파일

FR-CORE-008, 02 §10.6. **어떤 단계도 iCloud 다운로드를 유발하지 않는다.** `config.scan.read_dataless` 는 변경 불가 고정값 `false` 다.

판정 함수 `is_dataless(entry)`(`common/paths.py`, 테스트에서 주입 가능):
- `st_flags & SF_DATALESS (0x40000000)` — `lstat` 결과의 플래그만 본다(`lstat` 은 다운로드를 유발하지 않는다).
- 또는 구형 자리표시자 이름 `.<원래 이름>.icloud`.

**모든 내용 읽기는 이 판정 뒤에만 한다.** `open()` 을 부르는 곳은 아래 목록이 전부이며, 각 호출 직전에 `is_dataless` 를 다시 확인한다(한 번 판정한 뒤 시간이 지났을 수 있으므로). dataless 이면 그 단계는 결과 없음으로 처리한다.

| 내용 읽기 지점 | dataless 일 때 |
|---|---|
| SHA-256 (§2.5, 중복·볼륨 간 이동) | 계산 안 함, `sha256` NULL. 중복·이동 2차 매칭 제외 |
| 매직바이트 16바이트 (§5) | 확장자로만 판정 |
| xar 목차 (§7.2), zip 중앙 디렉터리 (§7.3), PNG IHDR (§12.2) | 판정 안 함(제안 없음) |
| vault 내용 검사·gitleaks (05) | 05 규칙 — 이름·확장자·위치 판정만 |
| OCR·텍스트 추출 (§6.1) | 안 함 |
| `mdls` (§2.7, §6, §11.1) | 허용(Spotlight 메타데이터는 로컬) |

추가 규칙:
- **dataless 디렉터리**(플래그가 디렉터리에 붙은 경우)는 `scandir` 하지 않는다. 디렉터리 목록을 받아 오는 것 자체가 네트워크 조회를 일으킬 수 있기 때문이다. 디렉터리 엔트리만 남기고 하위는 “보이지 않음 ≠ 삭제”(§2.4)로 처리, `stats.dataless_dirs`.
- 엔트리·이벤트는 정상 기록(메타데이터는 로컬에 있음). APFS 는 dataless 파일에도 논리 크기를 보고하므로 `size_bytes` 는 그 값.
- 다운로드됨 ↔ dataless 전환(같은 inode, 플래그만 변함, size·mtime 동일)은 **이벤트가 아니다**. `flags` 만 갱신한다. 전환 후 기존 `sha256` 은 유지하되 다시 계산하지 않는다.
- 구형 자리표시자 `.<name>.icloud` 가 사라지고 같은 디렉터리에 `<name>` 이 나타나면(다운로드 완료) 같은 엔트리로 보고 경로만 갱신, 이벤트 없음. 반대 방향도 같다.
- 항목 생성은 가능(메타데이터 기반). 집계 `W_DATALESS_SKIPPED`(count). 허용 동작은 `keep`/`keep_always`/`defer` 만(02 §10.1 예외 2, 위치·게이트 무관) → 제안도 이 안에서만(§13).

### 2.7 다운로드 출처

`downloads` 루트의 새 파일에 한해 `mdls -raw -name kMDItemWhereFroms`(배치, §12) 결과를 읽어 **호스트만** `where_from_host` 에 저장(06 §6). 전체 URL 은 프로젝트 매칭(§8.3)에 그 run 메모리 안에서만 쓰고 버린다.

---

## 3. 일일 델타와 날짜 경계

### 3.1 리뷰 날짜 함수

```
review_date(t) = local_date(t - day_boundary)      # day_boundary 기본 04:00 (config.review.day_boundary)
```
예: 11-25 01:30 → `2026-11-24`. DST 전환일에도 “로컬 벽시계 시각 − 4시간”의 날짜로 계산한다(`zoneinfo`, `common/clock` 주입).

### 3.2 이벤트의 유효 시각

스캔은 “지난 스캔 이후” 변화만 안다. 이벤트가 실제로 언제 일어났는지는 파일 시각으로 추정한다.

```
effective_time(created)  = clamp(birthtime or mtime, prev_scan_started_at(root), this_scan_started_at)
effective_time(modified) = clamp(mtime,              prev_scan_started_at(root), this_scan_started_at)
effective_time(moved/deleted) = this_scan_started_at
```
`prev_scan_started_at(root)` = 이 루트를 마지막으로 성공 순회한 run 의 시작 시각. 첫 스캔이면 하한 없음.
결정: 클램프하는 이유 — 다른 기기에서 복사된 파일은 birthtime 이 과거(또는 미래)일 수 있고, 그대로 쓰면 지난달 결산에 들어간다.

### 3.3 세션 귀속

- 항목의 `review_date` = `max(review_date(effective_time), 가장 최근에 생성된 review_sessions.review_date)`.
  이유: 이미 열린 세션보다 과거 날짜로 귀속되면 이월(06 §4.2, 세션 최초 개설 시 1회)에서 빠져 다음 날까지 보이지 않는다.
- 세션 행은 `review.ensure_session(D)` 한 곳에서만 만들고, 06 §4.2 의 이월 1단계는 **그 세션을 처음 만드는 트랜잭션에서 한 번만** 실행된다. `scan.run` 의 review 단계(§0 의 8)는 그룹 행에 `session_id` 가 필요하므로 오늘 세션이 없으면 `ensure_session(오늘)` 을 먼저 부른다. 과거 날짜 세션은 만들지 않는다 — 위 `max(...)` 규칙 때문에 수집기가 과거 날짜 세션을 필요로 하는 경우는 없다(항목의 `review_date` 가 과거여도 그룹은 오늘 세션에 만든다).
- 세션 지표(`review_sessions.stats_json`)의 `new_files` / `modified_files` / `deleted_files` = 해당 `review_date(effective_time)` 를 갖는 `file_events` 중 `file_level=1` 루트의 `kind IN ('file','package')` 이벤트 수(`moved` 는 별도, 같은 엔트리의 같은 날 중복 `modified` 는 1회). `new_apps`, `new_packages` 는 §11.

### 3.4 기준선(첫 스캔)

`trigger='init'` 이거나 루트가 처음 순회되는 run 은 **기준선**이다.
- 모든 관측을 `created` 이벤트 없이 엔트리로만 저장한다(이벤트 0, `stats.baseline_entries`).
- 항목은 `review_date(birthtime) == 오늘의 리뷰 날짜` 인 파일에 대해서만 만든다(§4 규칙 적용). 결정: 설치 첫날 수천 개의 과거 파일로 결재함을 채우지 않는다. 과거 누적분 정리는 비목표(PRD §7, 청소기 영역).

---

## 4. 어떤 변경이 리뷰 항목이 되는가

06 §4.1 불변식: 파일 항목은 `created` 와 “다른 스캔 루트로의 `moved`”에서만 생긴다. `modified` 는 열린 항목의 스냅샷만 갱신한다.

| 조건 | 항목 생성 |
|---|---|
| 루트 `file_level=0` (`projects`, DerivedData `custom`) | 파일 항목 없음. 개발 캐시(§10)·저장소(§8.4) 항목만 |
| `vault_extra` 루트 | 없음(vault 인벤토리만, 05) |
| `created`, depth 1 (루트 바로 아래) `file`/`package` (`symlink` 는 엔트리만, 항목 없음) | **예** |
| `created`, depth 1 `dir` | **예**, category `folder` (하위 파일은 개별 항목 없음) |
| `created`, depth ≥ 2, 조상 depth-1 디렉터리가 이번 run 에 함께 `created` 되었거나 열린 `folder` 항목임 | 아니오 (폴더 항목에 포함) |
| `created`, depth ≥ 2, `downloads`/`desktop`/`screenshots` 루트, 기존 하위 폴더 안 | **예** |
| `created`, depth ≥ 2, `documents`·`icloud_drive` 루트 | 아니오. 결정: Documents·iCloud Drive 하위 폴더에 저장된 파일은 이미 사용자가 정리한 것. 델타 지표에는 포함. 이유 추가: 두 루트는 트리가 커서(수만~수십만 엔트리) 깊은 파일까지 항목으로 만들면 결재함이 넘친다 |
| `moved`, 다른 루트로(예: Downloads → Desktop) | **예**(새 루트 기준으로 위 규칙 재적용). 같은 subject_key 의 열린 항목이 있으면 새로 만들지 않고 그 항목의 `subject_path`·`origin_root_kind` 갱신 |
| `moved`, 같은 루트 안 | 아니오. 열린 항목이 있으면 `subject_path` 갱신 |
| `moved`, 루트 밖으로 / `deleted` | 열린 항목 → `stale` (06 §4.1) |
| `modified` | 아니오. 열린 항목의 크기·mtime 갱신, `sha256` 무효화 → 중복 그룹 재계산 |
| settle 중, dataless 라도 | dataless 는 항목 생성 가능(메타데이터 기반), settle 중은 다음 run |
| 보안 자산(05 판정) | vault 가 `security_asset` 항목을 만든다(05). intel 은 카테고리만 `security_asset` 로 확정 |
| 열린 `decided` 항목(결정 후 계획 전)의 파일이 `modified` | 새 항목 없음, 상태 유지. 스냅샷 필드만 갱신. `plan.create` 가 “결정 후 내용 변경”으로 제외하면서 `last_error_code='E_STALE'` 을 남긴다(06 §4.1, 08) — 수집기는 이 값을 지우지 않는다 |
| **재탐지 예외**: 엔트리의 마지막 항목이 `stale` + `closed_reason='subject_changed'` 이고 열린 항목이 없음 | 다음 scan 에서 엔트리가 여전히 `present=1` 이면(이벤트 종류 무관) 새 항목을 **한 번** 만든다(`review_date` = 오늘 규칙 §3.3, 이유 “실행 직전 내용이 바뀌어 건너뛴 파일 — 다시 판단해 주세요”). 그 새 항목이 다시 종결되면 일반 규칙으로 돌아간다(06 §4.1 예외, 08 R7) |

`subject_key` = `file:<dev>:<inode>` (06). 같은 subject_key 의 열린 항목이 이미 있으면 새 항목을 만들지 않는다(부분 유니크 인덱스가 최종 방어선). 종결된 항목(`keep` 등)이 있는 파일은 다른 루트로 이동하지 않는 한 다시 묻지 않는다.

---

## 5. 카테고리 판정 (`intel/category.py`)

입력: 엔트리(이름, ext, kind, 크기, 위치, 루트 kind), vault 판정 결과, 선택적으로 매직바이트 앞 16바이트(이미 해시 중이거나 확장자가 없을 때만 읽음). **첫 번째로 일치하는 행이 카테고리**다.

| 순위 | `item_category` | 규칙 |
|---|---|---|
| 1 | `security_asset` | 05 의 vault 판정이 자산(`vault_assets` 행 존재, status `active`). 이 경우 아래 규칙은 보지 않는다 |
| 2 | `dev_cache` | §10 의 개발 캐시 디렉터리 엔트리(개발 캐시 단계가 만든 항목만) |
| 3 | `installer` | ext ∈ {`dmg`, `pkg`, `mpkg`, `iso`, `xip`} 또는 `package` 엔트리 ext=`app` 이고 루트 kind ∈ {downloads, desktop, screenshots, documents} 또는 `zip` 이면서 zip 목록 최상위가 `*.app` 하나(§7.3) |
| 4 | `screenshot` | §6 스크린샷 판정 점수 ≥ 0.6 (화면 기록 포함) |
| 5 | `compressed` | ext ∈ {`zip`, `rar`, `7z`, `tar`, `gz`, `tgz`, `bz2`, `xz`, `zst`, `lz4`, `cpio`, `lzma`} 또는 매직바이트 `PK\x03\x04`, `7z\xBC\xAF\x27\x1C`, `Rar!`, `\x1F\x8B` |
| 6 | `image` | ext ∈ {`png`, `jpg`, `jpeg`, `heic`, `heif`, `gif`, `webp`, `tif`, `tiff`, `bmp`, `svg`, `raw`, `dng`, `cr2`, `cr3`, `nef`, `arw`, `psd`, `ai`, `sketch`, `fig`, `avif`, `ico`, `icns`} |
| 7 | `media` | ext ∈ {`mov`, `mp4`, `m4v`, `avi`, `mkv`, `webm`, `mp3`, `m4a`, `wav`, `aac`, `flac`, `aiff`, `aif`, `ogg`, `opus`} |
| 8 | `document` | ext ∈ {`pdf`, `doc`, `docx`, `xls`, `xlsx`, `ppt`, `pptx`, `hwp`, `hwpx`, `pages`, `numbers`, `key`, `rtf`, `rtfd`, `txt`, `md`, `markdown`, `csv`, `tsv`, `odt`, `ods`, `odp`, `epub`, `html`, `htm`, `eml`, `vcf`, `ics`} |
| 9 | `code` | ext ∈ {`py`, `js`, `ts`, `tsx`, `jsx`, `swift`, `kt`, `java`, `go`, `rs`, `c`, `cc`, `cpp`, `h`, `hpp`, `m`, `mm`, `rb`, `php`, `sh`, `zsh`, `bash`, `sql`, `json`, `yaml`, `yml`, `toml`, `xml`, `ipynb`, `dart`, `gradle`, `plist`, `css`, `scss`, `lua`, `r`, `scala`, `patch`, `diff`} |
| 10 | `folder` | `kind='dir'` |
| 11 | `misc` | 그 외(확장자 없음 포함, `package` 중 위에 해당 안 하는 것) |

`app`, `package`, `git_repo`, `login_item` 카테고리는 파일이 아니라 각 수집기가 직접 붙인다(§8.4, §11).

메모:
- ext 는 `file_entries.ext`(소문자). `tar.gz` 류는 마지막 확장자 `gz` 로 판정.
- `.key`: Keynote 패키지(`kind='package'`)는 `document`. 일반 파일 `.key` 는 개인키 후보라 05 가 먼저 본다(순위 1).
- `.json`/`.env`/`.pem` 처럼 vault 후보와 겹치는 확장자는 vault 판정이 부정일 때만 아래 순위로 내려온다.
- `ics`, `vcf`, `eml` 은 개인 정보가 많으므로 민감도 기본값을 `personal` 로 둔다(07 §3.1 표).

---

## 6. 스크린샷 판정

신호별 점수를 noisy-OR 로 합친다: `score = 1 − Π(1 − wᵢ)`. 임계값 0.6.

| 신호 | 가중치 w | 비고 |
|---|---|---|
| Spotlight `kMDItemIsScreenCapture == 1` | 0.95 | `mdls` 배치(§12). 시스템 스크린샷 도구가 붙이는 속성. 실기기에서 속성명 확인 필요(M2 첫 작업) |
| 파일명이 시스템 형식과 일치 (아래 정규식) | 0.85 | 사용자가 `com.apple.screencapture name` 을 바꿨으면 그 접두사도 포함(09 가 값 제공) |
| 위치가 `screenshots` 루트 | 0.5 | |
| 파일명이 서드파티 도구 형식(`CleanShot`, `Xnip`, `Shottr`, `Simulator Screenshot`, `Simulator Screen Recording`) | 0.8 | |
| ext=`png`, EXIF 카메라 정보 없음, `downloads`/`desktop` 루트 | 0.2 | 단독으로는 임계값 미만(Declutter 는 이 경우 “모름”으로 둔다) |

시스템 파일명 정규식(대소문자 무시, NFC 정규화 후):
```
^(스크린샷|Screenshot|Screen Shot|スクリーンショット|截屏|螢幕截圖|Bildschirmfoto|Capture d’écran) \d{4}-\d{2}-\d{2}
^(화면 기록|Screen Recording|画面収録) \d{4}-\d{2}-\d{2}
```
화면 기록(두 번째 줄 또는 신호 1 + ext ∈ {mov, mp4})은 같은 `screenshot` 카테고리로 두고 그룹 키만 다르게 한다(§9).

결과: `screenshot` 카테고리 항목의 민감도 기본값은 `personal`(06 §3.1 결정 — OCR 전까지).

### 6.1 OCR (M6, 선택)

- `dayclose-native` 의 OCR 명령(인터페이스는 09)이 로컬 Vision 으로 텍스트를 뽑는다. 대상: `screenshot` 항목, 크기 ≤ 20MB, dataless 아님, `preview_policy != metadata_only`.
- 결과는 `file_text`(`source='vision_ocr'`, 16KB 절단, `text_enc`)에만 저장. 로그·봉투·리포트 금지(02 §13).
- OCR 텍스트에 주민등록번호 패턴 → 민감도 `patient`(FR-SO-006 AC). 비밀 패턴 → 05 의 `plaintext_secret` 판정 경로로 넘김. 판정 규칙의 소유는 07(민감도)·05(비밀).
- OCR 은 분류 신호로만 쓴다: 프로젝트 이름 일치(§8.3 신호 C), 앱 이름 일치(그룹 제목 “Xcode 스크린샷” 등).
- 이름 변경 제안(M6): `rename` 은 decision action 이다(02 §5.3 — `--dest` 에 같은 디렉터리 안의 새 전체 경로). 스크린샷 OCR 결과로 `suggested_action='rename'`, `suggested_dest=<같은 디렉터리>/<YYYY-MM-DD> <주제>.<ext>` 를 제안할 수 있다. 주제 문자열 규칙: OCR 첫 줄 또는 앱 이름에서 파일명 금지 문자(`/`, `:`, 제어문자) 제거, 40자 이내, 비밀·주민등록번호·전화번호 패턴이 있으면 제안하지 않음(민감 정보가 파일명으로 새어 나가지 않게). confidence 0.5. 같은 이름이 이미 있으면 ` 2`, ` 3` … 접미사(실제 충돌 처리는 08). `sensitivity ≥ patient`, iCloud·dataless 항목에는 제안하지 않는다(어차피 허용 동작에 없음).

---

## 7. 설치 파일 ↔ 설치된 앱 매칭

목표(FR-SO-001): 이미 설치된 소프트웨어의 설치 파일만 `trash` 제안. **설치 파일을 마운트·실행·압축 해제하지 않는다**(hdiutil·installer 미사용, 허용 도구 목록 02 §6 밖).

### 7.1 설치된 앱 목록

- M3 이후: `inventory_apps`(present=1).
- M2(인벤토리 이전): `/Applications`, `/Applications/*/`(1단계 하위 폴더 안의 `.app`), `~/Applications` 의 `*.app/Contents/Info.plist` 를 `plistlib` 로 직접 읽은 임시 목록(§11.1 과 같은 함수, DB 저장 안 함).
- 각 앱: `bundle_id`, `name`(`CFBundleDisplayName` → `CFBundleName` → 파일명), `version`(`CFBundleShortVersionString` → `CFBundleVersion`), `norm = normalize(name)`.

`normalize(s)`: NFC → 소문자 → 확장자 제거 → `[-_.+()\[\]]` 와 공백 제거 → 끝의 아키텍처·플랫폼 토큰 제거(`universal`, `arm64`, `aarch64`, `x64`, `x86_64`, `intel`, `apple silicon`, `mac`, `macos`, `osx`, `darwin`, `installer`, `setup`, `install`) → 버전 토큰 제거(`v?\d+(\.\d+)+`, 단독 `\d{3,}` 빌드 번호).

### 7.2 판정

**PKG / MPKG** (정확 매칭):
1. 수신 영수증 파일명 일치: `/var/db/receipts/*.plist` 의 `PackageFileName == 파일명` → 해당 `PackageIdentifier` 설치됨. confidence 0.95.
2. 패키지 메타데이터 일치: `.pkg` 는 xar 아카이브다. 표준 라이브러리로 헤더(28바이트, `xar!`) → zlib 압축 TOC(XML)를 읽어 `Distribution`/`PackageInfo` 항목의 오프셋을 찾고, 그 항목만 읽어 `identifier`·`version` 쌍을 추출(FileMorrow 의 정규식 규칙과 동일 아이디어, 13 문서). 모든 identifier 에 대해 `/var/db/receipts/<identifier>.plist` 가 존재하고 `PackageVersion >= 패키지 version` 이면 설치됨. confidence 0.95.
   - 읽기 한도: TOC ≤ 4MB, 항목 ≤ 1MB, 전체 0.5초. 초과·파싱 실패 → 판정 불가(제안 없음).
   - 결정: `pkgutil`/`xar` CLI 를 쓰지 않는다. 이유: 허용 도구 목록 확장 없이, 임시 파일 생성 없이 읽기만 가능.
3. 영수증이 없거나 일부 identifier 만 있음 → 미설치로 판정(제안 없음).

**DMG / ISO / XIP / 설치형 ZIP** (이름 매칭):
1. `stem = normalize(파일명)`. 앱 중 `app.norm == stem` → 일치(정확).
2. 없으면 `len(app.norm) >= 4 and app.norm in stem` 인 앱 중 가장 긴 이름 → 일치(부분).
3. 파일명 버전 `installer_ver` = 첫 번째 `\d+(\.\d+)+`.
4. 판정:

| 상황 | 결과 | confidence |
|---|---|---|
| 정확 일치, 설치 버전 ≥ installer_ver | 설치 완료 → `trash` 제안, 이유 “설치 완료된 설치 파일 (Foo 1.2.3 설치됨)” | 0.85 |
| 부분 일치, 설치 버전 ≥ installer_ver | 같음 | 0.7 |
| 일치, installer_ver 없음 | 같음 | 0.6 (FR-SO-001 AC 충족: `Foo.dmg` + `Foo.app`) |
| 일치, **installer_ver > 설치 버전** | 업데이트 미적용 → 제안 `keep`, 이유 “설치된 버전보다 새 설치 파일 — 아직 업데이트하지 않았습니다” | 0.6 |
| 설치 버전이 더 높음 | `trash`, 이유 “이미 더 새 버전(…)으로 업데이트됨” | 기존 값 + 0.05 |
| 불일치 | 미설치 → 제안 없음(그룹 `installer:pending`) | — |

버전 비교: 점으로 나눈 정수 튜플 비교, 비숫자 접미사(`b2`, `rc1`)는 무시하고 숫자 부분만. 비교 불가 → “installer_ver 없음” 행으로.

**`.app` 패키지가 사용자 루트에 있음** (zip 을 풀어 생긴 앱): 같은 `bundle_id` 의 앱이 `/Applications`·`~/Applications` 에 있고 버전 ≥ → `trash` 제안 0.9. 없으면 제안 없음, 이유 “아직 응용 프로그램 폴더로 옮기지 않은 앱”.

### 7.3 압축 해제가 끝난 압축 파일 (FileMorrow 아이디어)

`compressed` 카테고리 중 ext=`zip` 이고 같은 디렉터리에 `stem` 이름의 디렉터리가 있을 때:
- `zipfile` 로 중앙 디렉터리만 읽는다(내용 압축 해제 금지, 목록 ≤ 10,000 항목, 0.5초).
- `__MACOSX/`, `.DS_Store`, `._*` 항목은 무시. `..`·절대경로 항목이 하나라도 있으면 판정 중단.
- 모든 파일 항목이 대상 디렉터리(또는 평평하게 풀린 경우 같은 디렉터리)에 같은 상대경로로 존재하고 크기(`file_size`)가 정확히 같으면 → `trash` 제안, 이유 “이미 압축을 푼 파일 (폴더 `stem/` 에 N개 일치)”, confidence 0.9.
- 하나라도 다르면 제안 없음. 압축 해제된 폴더 쪽은 절대 제안하지 않는다.

---

## 8. 프로젝트 문맥

### 8.1 프로젝트 탐지 (`collect/git.py`)

후보:
- `projects` 루트 아래 depth ≤ `max_depth`(기본 2)의 디렉터리 중 `.git` 이 있는 것 → `kind='git'`. 저장소 안의 저장소(서브모듈, 중첩)는 바깥 저장소만 등록.
- `projects` 루트 depth 1 디렉터리 중 `.git` 이 없고 프로젝트 표지 파일(`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Package.swift`, `*.xcodeproj`, `pubspec.yaml`, `build.gradle*`, `Gemfile`, `composer.json`, `CMakeLists.txt`, `Makefile`) 중 하나가 있는 것 → `kind='folder'`.
- 다른 루트의 fs 순회에서 넘어온 git 작업 트리(§2.2-3) → `kind='git'`.

`projects.name` = 디렉터리 이름. `root_path` 유니크. 사라진 후보 → `present=0`.

git 호출(`common/proc.run_tool`, `shell=False`). 모든 git 호출에 환경 `GIT_OPTIONAL_LOCKS=0`(status 가 index 를 갱신·잠그지 않게), `GIT_TERMINAL_PROMPT=0`, 인자 `-c core.fsmonitor=false -c core.untrackedCache=false`. 결정: DayClose 는 사용자 저장소에 어떤 쓰기도 유발하지 않는다.

| 값 | 명령 | 타임아웃 |
|---|---|---|
| `last_commit_at` | `git -C R log -1 --format=%ct` | 5s |
| `dirty_count` | `git -C R status --porcelain=v1 -z --untracked-files=normal` 의 항목 수 (최대 10,000 에서 중단 → 10000 기록) | 5s, 시간 초과 시 `--untracked-files=no` 로 1회 재시도, 그래도 실패 시 NULL |
| `branch_count`, `stale_branch_count` | `git -C R for-each-ref --format=%(committerdate:unix) refs/heads` — stale = 90일 이상 | 5s |
| `remote_host` | `git -C R config --get remote.origin.url` → 호스트만 파싱(`git@github.com:o/r` → `github.com`). 전체 URL 은 저장하지 않음 | 2s |
| `last_activity_at` | max(`last_commit_at`, dirty 파일들의 mtime 중 최대(최대 200개 stat), 저장소 depth-1 엔트리 mtime 최대) | — |

예산: git 단계 전체 60초. 초과 시 남은 저장소는 이전 값 유지, `W_PARTIAL_SCAN`. 저장소는 `last_activity_at` 내림차순으로 처리(활성 저장소 먼저).
`git` 미설치 → `W_TOOL_MISSING`, 모든 `kind='git'` 프로젝트는 `is_active` 이전 값 유지(새 저장소는 보수적으로 활성 취급, 아래).

### 8.2 활성 판정과 보호

```
is_active = (dirty_count > 0)
         or (now - last_commit_at   <= projects.active_days)      # 기본 30일
         or (now - last_activity_at <= projects.active_days)
```
- 값을 얻지 못한 새 저장소(타임아웃·git 없음) → `is_active=1`. 결정: 모르면 보호한다.
- `kind='folder'` 프로젝트: `last_activity_at` 만으로 판정.
- 보호: 엔트리 경로가 `is_active=1` 인 `kind='git'` 프로젝트의 `root_path` 아래 → `protection='active_repo'`(02 §10.1). 판정 자체는 `policy` 가 하고, intel 은 `file_entries.project_id` 와 프로젝트 활성 여부를 제공한다.
- 비활성 저장소 내부 파일은 보호하지 않지만(protection `none`) **파일 단위 항목은 여전히 만들지 않는다**(`projects` 루트는 `file_level=0`, 다른 루트는 §2.2-3 가지치기). 결과적으로 저장소 내부에서 리뷰 대상이 되는 것은 개발 캐시(§10)와 저장소 상태 항목(§8.4)뿐이다.

### 8.3 파일 → 프로젝트 매칭 (휴리스틱, FR-SO-003)

대상: `file_level=1` 루트의 새 항목 중 카테고리 ∈ {screenshot, image, document, code, compressed, media, misc}. 후보 프로젝트: `present=1` 인 모든 프로젝트.

신호(프로젝트 p 별 noisy-OR, 최대 0.95):

| 신호 | 조건 | w |
|---|---|---|
| A 이름 | 파일명 토큰화 결과에 `tokens(p.name)` 가 연속으로 포함. 토큰화: NFC·소문자·`[-_ .]+` 분리·camelCase 분리. 프로젝트 이름 토큰 전체 길이 ≥ 3자. 예: `PL-Agent` ↔ `pl_agent_spec.pdf`, `PLAgent-wireframe.png` | 0.6 |
| B 출처 | `kMDItemWhereFroms` URL(메모리) 의 경로가 `p` 의 remote 경로(`owner/repo`)를 포함, 또는 URL 호스트가 `localhost`/`127.0.0.1` 이고 작업 중 프로젝트(신호 D)가 하나 | 0.4 |
| C 내용 | (M6) OCR/텍스트 추출 결과에 프로젝트 이름 토큰 포함 | 0.3 |
| D 시간 | 파일 `effective_time` ± 30분 안에 `p` 의 활동(커밋 시각, dirty 파일 mtime)이 있고, 같은 창에 활동한 프로젝트가 p 하나뿐 | 0.25 |
| E 시뮬레이터 | 파일명 `Simulator Screen(shot| Recording)` 이고 D 의 프로젝트가 `*.xcodeproj`/`Package.swift` 보유 | 0.3 |

- 두 프로젝트가 같은 최고점이면(±0.05) 매칭하지 않는다.
- 최고점 ≥ 0.6 → 프로젝트 확정(`review_items.project_id`, `file_entries.project_id`), `move` 제안(§9·§13). 0.4~0.6 → `project_id` 만 기록하고 제안 없음(그룹은 카테고리 그룹). < 0.4 → 매칭 없음.
- 결정: 신호 A 하나로 0.6 에 도달하게 한 이유 — FR-SO-003 AC(“파일명에 프로젝트명 포함 시 ≥ 0.6”). 프로젝트 이름이 일반 단어(`app`, `test`, `web`, `api`, `docs`, `demo`, `tmp` 등 내장 불용어 목록)면 A 의 가중치를 0.3 으로 낮춘다.

목적지 결정:

| 카테고리 | 목적지 하위 폴더 (프로젝트 `root_path` 기준) |
|---|---|
| screenshot, image | `screenshots/` |
| document | `docs/` |
| 그 외 | `references/` |

- 해당 폴더가 이미 있으면 그대로. 없으면 같은 의미의 기존 폴더(`Screenshots`, `doc`, `documentation`, `refs`, `assets/screenshots`)를 대소문자 무시로 찾고, 없으면 기본 이름 + 이유 끝에 “(폴더 생성 필요)”(FR-SO-003 AC). 생성 자체는 08 의 plan 이 한다.
- 결정: 프로젝트가 활성 git 저장소여도 목적지로 허용한다. 저장소 안으로의 이동은 git 에 untracked 파일을 늘릴 수 있으므로 이유 문구에 “git 저장소 안으로 이동됩니다” 를 덧붙인다. 보호(`active_repo`)는 원본 위치 기준이라 이 제안을 막지 않는다.

### 8.4 저장소 상태 항목 (`git_repo`, FR-AM-003)

subject_key `repo:<project_id>`, category `git_repo`, 허용 동작 `acknowledge`/`keep_always`/`defer`(02 §10.1 결정). 항목은 **상태가 나빠질 때만** 만든다(매일 묻지 않기 위해).

- `dirty_count` 가 0 → >0 으로 바뀜, 또는
- `stale_branch_count` 가 증가, 또는
- 미커밋 변경이 지난 `git_repo` 항목 종결 이후 7일 이상 지속(“7일째 미커밋 변경”).

비활성 저장소의 dirty 는 이유 문구에 “30일 이상 활동 없는 저장소에 미커밋 변경 N개”. 그룹 `git:dirty`.

### 8.5 “다른 코드에서 참조하는 파일” (M6, FR-SO-004 비고)

저장소 밖 파일 중 `move`/`trash` 제안 후보에 대해:
- 파일명(확장자 포함, ≥ 6자, 불용어 아님) 목록을 활성 저장소마다 한 번의 `git -C R grep -F -l -I --no-color -e n1 -e n2 … -- .`(패턴 ≤ 200개, 타임아웃 10초)로 조회.
- 일치 → 해당 항목의 제안을 `keep` 으로 바꾸고 이유 “프로젝트 X 의 코드가 이 파일 이름을 참조합니다”. 보호 등급은 바꾸지 않는다(02 §10.1 의 enum 밖 개념이라서).
- 활성 저장소 전체 예산 30초, 초과 시 확인하지 못한 항목은 그대로.

---

## 9. 리뷰 그룹

그룹 = (리뷰 세션, `group_key`). 항목은 정확히 한 그룹. 그룹 키는 **첫 번째로 일치하는 규칙**으로 정한다.

| 순위 | `group_key` | 대상 | 제목 예 (title) | 그룹 `category` |
|---|---|---|---|---|
| 1 | `vault:new` | category `security_asset` (05) | “새 보안 자산 N개” | `security_asset` |
| 2 | `habit:<policy_rule_id>` | 활성 학습 규칙이 결정한 항목 (07). 키의 숫자는 `policy_rules.id`(외부 표기 `prl_`) | “습관 항목 — 설치 완료된 DMG 정리” | 한 카테고리면 그 값, 아니면 NULL |
| 3 | `duplicate:<sha256 앞 16자>` | 정확 중복 그룹 구성원(§12.1) | “같은 파일 3개” | 구성원 카테고리(확장자가 달라 섞이면 NULL) |
| 4 | `version:<family 해시 16자>` | 문서 버전 가족(§12.3) | “‘사업계획서’ 버전 4개” | `document` |
| 5 | `installer:installed` | 설치 완료 판정 | “설치가 끝난 설치 파일” | `installer` |
| 6 | `installer:extracted` | 압축 해제 완료 zip(§7.3) | “이미 압축을 푼 파일” | `compressed` |
| 7 | `installer:pending` | 그 외 installer | “아직 설치하지 않은 설치 파일” | `installer` |
| 8 | `project:<project_id>` | 프로젝트 확정(≥0.6) 항목 | “PL-Agent · 오늘의 작업 파일 7개” | 구성원이 한 카테고리면 그 값, 아니면 NULL(혼합) |
| 8a | `ai:<sha256(label+review_date) 앞 16자>` | (M6) AI 가 묶은 작업 그룹. 순위 1~8 에 해당하지 않는 항목만(07 §8.6) | AI 제안 라벨 | 한 카테고리면 그 값, 아니면 NULL |
| 9 | `screenshot:recording` | 화면 기록 | “화면 기록 N개” | `screenshot` |
| 10 | `screenshot:day` | 그 외 스크린샷 | “오늘의 스크린샷 N장” | `screenshot` |
| 11 | `devcache:inactive` / `devcache:active` | §10 | “비활성 프로젝트 개발 캐시 (4.2GB)” | `dev_cache` |
| 12 | `git:dirty` | §8.4 | “미커밋 변경이 있는 저장소” | `git_repo` |
| 13 | `app:new` / `app:unused` | §11 | “새로 설치된 앱” / “90일 이상 사용하지 않은 앱” | `app` |
| 14 | `package:new` | §11 | “새 Homebrew 패키지” | `package` |
| 15 | `login:new` | §11 | “새 백그라운드 서비스” | `login_item` |
| 16 | `<category>:<origin_root_kind>` | 나머지 | “다운로드 · 문서 12개”, “바탕화면 · 이미지 5개” | 해당 카테고리 |

규칙:
- 결정: 한 그룹에 항목이 1개뿐이면 그래도 그룹으로 둔다(FR-DR-003 “제안이 없어도 그룹은 표시”). 단 순위 16 의 그룹은 항목 수 ≥ 1 이면 생성.
- 제목은 사용자 문구. 보안 자산·환자 자료의 파일명·경로를 넣지 않는다(06 `review_groups.title`). 프로젝트 이름은 넣어도 된다(사용자 자신의 디렉터리 이름). 단 프로젝트 `root_path` 가 `patient_data`/`security_asset` 보호 규칙(`protection_rules`) 아래이거나 이름이 환자 파일명 패턴(`config.protection.patient_filename_patterns`)에 일치하면 “프로젝트 #3” 으로 표시.
- `sort_order`: vault → habit → duplicate → installer → project → screenshot → 나머지(확보 용량 내림차순) → git/app/package/login. 이유: 보안 경고 먼저, “한 번에 끝나는” 그룹 다음.
- 그룹 제안(`suggested_action/dest/source`): 구성원 중 제안이 있는 항목의 제안이 **모두 같으면** 그 값, 아니면 NULL. `rationale` = 대표 이유.
- 이월 항목(06 §4.2)은 새 세션에서 같은 규칙으로 그룹 키를 다시 계산해 재배정한다. 이월 항목만으로 이뤄진 그룹도 같은 키(제목에 “(이월 N)” 추가).
- 그룹 `category` 는 구성원 카테고리가 하나면 그 값, 둘 이상이면 NULL(06 `review_groups.category`: NULL = 혼합 그룹). 순위 16 의 그룹은 정의상 단일 카테고리.

---

## 10. 개발 캐시 (주간, FR-AM-005)

실행 조건: `app_meta.last_devcache_scan_date` 가 7일 이상 지났거나 `scan.run --collectors` 에 명시 실행(같은 `fs` 수집기의 추가 단계, phase `fs`). 결정: 새 collector 이름을 만들지 않는다(02 §5.3 목록 유지).

탐지 대상(각 프로젝트 `root_path` 아래 depth ≤ 4, DerivedData 루트는 depth 1):

| 디렉터리 이름 | 인정 조건(같은 부모에 있어야 함) | 비고 |
|---|---|---|
| `node_modules` | `package.json` | 중첩 `node_modules`(의존성 안의 것)는 바깥 것만 |
| `.build` | `Package.swift` | |
| `DerivedData/<Name>-<hash>` | DerivedData 루트의 하위 디렉터리 | `info.plist` 의 `WorkspacePath` 로 프로젝트 연결(plistlib) |
| `target` | `Cargo.toml` | |
| `build` | `build.gradle`/`build.gradle.kts`/`settings.gradle*` | 그 외 `build` 는 소스일 수 있어 제외 |
| `.gradle` | 같은 조건 | |
| `.venv`, `venv` | 내부에 `pyvenv.cfg` | |
| `.next`, `.nuxt`, `.svelte-kit`, `.turbo`, `.parcel-cache` | `package.json` | |
| `.dart_tool` | `pubspec.yaml` | |
| `Pods` | `Podfile` | git 추적 여부 검사 필수(커밋하는 팀 있음) |
| `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache` | — | 크기 합이 작아 항목화하지 않음(지표만) |

제외 조건(하나라도 해당하면 항목 없음):
- 캐시 디렉터리 안에 git 추적 파일이 있음: `git -C R ls-files -z -- <rel>` 출력이 비어 있지 않음(첫 바이트에서 중단). Mole 의 보호 규칙과 같은 취지(13 문서).
- 캐시 디렉터리 또는 부모에 `.dayclose-keep` 파일이 있음(사용자 수동 표시). 결정: 파일 하나로 보호하는 탈출구.
- 최근 7일 이내에 캐시 내부 최상위 엔트리 mtime 이 있음 → `devcache:active` 그룹(제안 없음). Mole 의 “7일 이내 활동은 기본 미선택” 규칙과 동일.

크기 측정: 내부 `os.scandir` 합산, 캐시 1개당 엔트리 200,000개 또는 5초에서 중단(`W_TRUNCATED`, 크기는 하한값, 표시 “4.2GB+”). APFS 클론 중복 계산은 감수(표시는 “추정”). 단계 전체 예산 120초, 큰 순이 아니라 프로젝트 `last_activity_at` 오름차순(오래된 것 먼저)으로 처리.

항목화: 크기 ≥ `scan.devcache_min_bytes`(기본 100MB)인 것만. 엔트리는 해당 루트(`projects` 또는 DerivedData `custom`)의 `kind='dir'` `file_entries` 행, subject_key `file:<dev>:<inode>`, subject_type `dir`, category `dev_cache`.

제안:
- 프로젝트 `is_active=0`(또는 DerivedData 의 `WorkspacePath` 가 사라짐) → `trash`, 이유 “비활성 프로젝트(마지막 활동 N일 전)의 재생성 가능한 캐시”, confidence 0.8. FR-AM-005 AC.
- 활성 프로젝트 → 제안 없음, `devcache:inactive` 가 아닌 `devcache:active` 그룹. 06 §3.1 예외에 따라 항목 단위 `trash` 는 허용.

---

## 11. 앱·Homebrew·로그인 항목 인벤토리 (M3)

공통: 인벤토리 수집기는 현재 목록을 읽어 해당 `inventory_*` 테이블과 diff 하고, `present`, `first_seen_run_id`, `last_seen_run_id` 를 갱신한다. diff 결과만 항목·지표가 된다. 첫 수집(테이블이 비어 있음)은 기준선: 항목 없음.

### 11.1 앱 (`collect/apps.py`)

- 소스: `/Applications/*.app`, `/Applications/*/*.app`(한 단계 하위 폴더), `/Applications/Utilities/*.app`, `~/Applications/*.app`, `~/Applications/*/*.app`. (`/System/Applications` 는 제외.) 소스 세부와 마지막 사용일은 09.
- 식별: `bundle_id`(없으면 `path`). 같은 `bundle_id` 가 두 경로에 있으면 행 2개.
- `version` = `CFBundleShortVersionString`(없으면 `CFBundleVersion`).
- `source`: `Contents/_MASReceipt/receipt` 존재 → `app_store`; brew cask 목록(§11.2)의 앱 아티팩트 이름과 일치 → `brew_cask`; 그 외 `manual`; Info.plist 읽기 실패 → `unknown`.
- `size_bytes`: 새 앱·버전 변경 앱만 측정(엔트리 50,000개/3초 한도, 초과 시 NULL). 결정: Xcode 같은 수십만 파일 앱을 매일 재지 않는다.
- `last_used_at`: `mdls kMDItemLastUsedDate` 배치(§12), 주 1회만 갱신.

| diff | 결과 |
|---|---|
| 새 앱 | 항목 `app`, 그룹 `app:new`, 허용 `acknowledge`/`keep_always`/`defer`, `stats.new_apps += 1` |
| 사라진 앱 | `present=0`, 항목 없음, 리포트 “삭제된 앱” 줄 |
| 버전 변경 | `version_changed_run_id`, 항목 없음, 리포트 “업데이트된 앱 N개”. 결정: 자동 업데이트를 매일 묻지 않는다 |
| 미사용(월간) | 매월 첫 리뷰 세션에서 `last_used_at` 이 90일 초과인 앱 → 항목 `app`, 그룹 `app:unused`(FR-AM-006). `last_used_at` NULL 은 제외 |

### 11.2 Homebrew (`collect/brew.py`)

- 명령: `brew info --installed --json=v2`, 환경 `HOMEBREW_NO_AUTO_UPDATE=1`, `HOMEBREW_NO_ANALYTICS=1`, `HOMEBREW_NO_ENV_HINTS=1`, 타임아웃 60초. 하루 1회(`app_meta.last_brew_scan_date`)만 실행.
- 파싱: `formulae[].name`, `formulae[].installed[0].version`, `formulae[].installed[0].installed_on_request` → `on_request`; `casks[].token`, `casks[].installed`(버전 문자열), cask 의 앱 아티팩트 이름(§11.1 source 판정용).
- `brew` 없음 → `W_TOOL_MISSING`, 단계 건너뜀(FR-AM-002). 테스트는 출력 픽스처(`run_tool` 대체).

| diff | 결과 |
|---|---|
| 새 formula, `on_request=1` | 항목 `package`, 그룹 `package:new`, `stats.new_packages += 1` |
| 새 formula, 의존성으로 설치 | 항목 없음, 지표 `new_packages` 에는 포함하지 않고 리포트에 “의존성 N개” |
| 새 cask | 항목 `package` |
| 제거 | `present=0`, 리포트 줄 |
| 버전 변경 | 항목 없음 |

### 11.3 로그인 항목 (`collect/login_items.py`, 주간)

- 실행 조건: `app_meta.last_login_items_scan_date` 로부터 7일 경과 또는 명시 실행(FR-AM-004).
- 소스는 LaunchAgent/LaunchDaemon plist **만**이다: `~/Library/LaunchAgents/*.plist` → `launch_agent_user`, `/Library/LaunchAgents/*.plist` → `launch_agent_global`, `/Library/LaunchDaemons/*.plist` → `launch_daemon`. 시스템 설정의 “로그인 항목”(BTM)은 공개 API 가 없어 수집하지 않는다(06 `login_item_kind`). plist 는 `plistlib` 로 읽기만 하고 `launchctl`·`osascript` 는 쓰지 않는다. 권한 이슈는 09.
- `label` = plist `Label`(없으면 파일명), `program_path` = `Program` 또는 `ProgramArguments[0]`.
- 식별 `(kind, label)`. DayClose 자신의 `com.dayclose.scheduler` 는 제외.
- 새 항목 → 항목 `login_item`, 그룹 `login:new`, 이유 “새 백그라운드 서비스: <label>”(label 은 표시 가능 — 비밀 아님). 사라짐 → 리포트 줄.
- plist 읽기 실패(권한) → 해당 파일 건너뜀, `W_PERMISSION_SKIPPED`.

---

## 12. 중복·유사 항목·버전 가족

### 12.1 정확 중복

1. 후보: `present=1`, `kind='file'`, `size ≥ 1 KiB`, `size ≤ hash_max_bytes`, dataless 아님, 보안 자산 아님(키 중복은 05 의 `duplicate` 발견 사항), `active_repo` 내부 아님.
2. 같은 `size` 버킷 중 이번 리뷰 날짜의 새 항목이 하나 이상 포함된 버킷만 해시(§2.5).
3. 같은 `sha256` 이 2개 이상이면 중복 그룹 `duplicate:<sha16>`.
4. 남길 사본(keeper) 선택 — 위에서부터 처음 결정되는 규칙:
   0. 사본 중 `allowed_actions` 에 `trash` 가 **없는** 것(해제 전 iCloud 동기화 사본, 보호 등급 사본 등 — dataless 사본은 해시가 없어 애초에 후보가 아님)이 있으면 그중에서 고른다(둘 이상이면 아래 1·2 를 그 안에서 적용). 이유: 정리할 수 없는 사본을 남겨야 나머지 제안이 실행 가능하다. 모든 사본이 trash 불가면 그룹만 만들고 제안 없음.
   0a. 결정: 게이트가 열려 iCloud 사본도 trash 가능하더라도, iCloud 동기화 사본과 비동기화 사본이 섞여 있으면 **iCloud 사본을 keeper 로** 둔다. 이유: 다른 기기 삭제로 전파되는 쪽을 지우는 제안을 기본으로 만들지 않는다. 모든 사본이 iCloud 동기화면 1·2 를 적용하고, 비keeper 의 `trash` 제안 이유에 “다른 기기에서도 삭제됩니다” 를 붙인다.
   1. 사본 중 정확히 하나가 `downloads`/`desktop`/`screenshots` 루트 **밖**(이미 정리된 위치)에 있으면 그것.
   2. 그 외에는 `mtime` 이 가장 최신인 사본(FR-SO-002 AC “최신 1개 keep”). 동률 → 경로 길이가 짧은 것 → 경로 사전순.
5. keeper 가 리뷰 항목이면 제안 `keep`(confidence 0.9). 나머지 항목은 `trash`, 이유 “같은 파일이 <keeper display_path> 에 있습니다”, confidence 0.9.
6. keeper 가 리뷰 항목이 아닌(이미 있던) 파일이면 그 파일은 그룹에 들어가지 않고, 새 항목만 `trash` 제안. keeper 경로가 보호 대상이면 표시 경로를 마스킹.
7. 이름 차이 표시: 비교 모드(03)용으로 그룹 rationale 에 “이름이 다른 사본 포함”.

### 12.2 유사(near-duplicate)

| 종류 | 판정 | 마일스톤 |
|---|---|---|
| 이름 변형 | 같은 디렉터리 또는 같은 루트 kind 에서 `strip_copy_suffix(name)` 가 같고 ext 같음. 접미사: ` (1)`~` (99)`, ` copy`, ` copy N`, ` 사본`, ` 사본 N`, `-1`~`-9`, `_1`~`_9`, ` 2`~` 9`, Dropbox/OneDrive 충돌 표지(Declutter 의 패턴 목록과 같은 아이디어). sha 같으면 §12.1 로, 다르면 §12.3 버전 가족 후보 | M2 |
| 연속 스크린샷 | 같은 리뷰 날짜의 스크린샷 중 생성 간격 ≤ 10초이고 픽셀 크기 같음(PNG IHDR 24바이트만 읽음) → 같은 그룹 안에서 인접 표시(별도 그룹 없음) | M2 |
| 지각 해시 | `dayclose-native` 의 이미지 dHash(64비트, 인터페이스는 09) Hamming 거리 ≤ 6 → `duplicate:` 대신 그룹 rationale 에 “비슷한 이미지 N쌍” 과 비교 모드 후보. 자동 `trash` 제안 없음(confidence 0.5 의 `trash` 제안은 1장을 제외한 나머지에, 사용자가 비교 모드에서 확인) | M6 |

### 12.3 문서 버전 가족

대상: `document` 카테고리(그리고 같은 규칙을 이미지 원본 `psd`/`sketch`/`fig` 에 적용).

`family_stem(name)` = NFC → 소문자 → 확장자 제거 → 아래 토큰 제거 → 구분자 정리:
- 버전: `v\d+(\.\d+)*`, `ver\d+`, `rev\d+`, `r\d+`
- 상태: `final`, `최종`, `최최종`, `진짜최종`, `수정`, `수정본`, `draft`, `초안`, `edited`, `확정`, `new`, `old`, `backup`, `bak`
- 날짜: `\d{8}`, `\d{6}`, `\d{4}[-_.]\d{2}[-_.]\d{2}`, `\d{2}[-_.]\d{2}`(앞 토큰 다음에만)
- 복사 접미사(§12.2)

가족 = 같은 `family_stem`(≥ 4자) + 같은 ext 그룹(`doc/docx`, `xls/xlsx`, `ppt/pptx`, `hwp/hwpx` 는 같은 그룹) + 같은 루트 또는 같은 프로젝트. 구성원 ≥ 2 이고 하나 이상이 이번 리뷰 항목일 때 그룹 `version:<sha256(family_stem+ext그룹) 앞 16자>`.

제안: 가장 최신(`mtime`) 항목은 `keep`(0.6). 나머지는 결정: **파괴적 제안 없음**(`suggested_action` NULL), 이유 “같은 문서의 이전 버전으로 보입니다 — 비교해서 남길 것을 고르세요”. 이유: 이름이 같아도 내용이 다른 버전을 잘못 버리는 비용이 크다. 바이트가 같으면 §12.1 이 먼저 잡는다. 보관 폴더(`config.archive.root`)가 설정돼 있으면 이전 버전에 `archive` 제안(0.5). 목적지는 제안하지 않는다(`decisions.dest_path` 는 archive 에서 NULL, 배치 `<root>/<YYYY>/<MM>/<원래 이름>` 는 plan 이 정함 — 06·08).

---

## 13. 휴리스틱 제안 (`intel/suggest.py`)

항목마다 제안은 최대 1개(`suggested_action`, `suggested_dest`, `suggestion_source`, `suggestion_reason`, `confidence`). 출처 우선순위: `rule`(07, 활성 학습 규칙) > `heuristic`(이 절) > `ai`(07 이 덮어쓰기 조건 정의) > `none`.

휴리스틱 규칙(위에서부터 처음 일치):

| # | 조건 | action | dest | confidence | 이유 문구(예) |
|---|---|---|---|---|---|
| H1 | protection ∈ {security_asset, patient_data} | 없음(05/07) | — | — | — (vault·정책 문구) |
| H2 | 정확 중복 비keeper(§12.1) | `trash` | — | 0.9 | “같은 파일이 ~/Documents/계약 에 있습니다” |
| H3 | 설치 완료 설치 파일(§7.2) | `trash` | — | 0.6~0.95 | “설치 완료된 설치 파일 (Foo 1.2.3 설치됨)” |
| H4 | 압축 해제 완료 zip(§7.3) | `trash` | — | 0.9 | “이미 압축을 푼 파일” |
| H5 | 업데이트 미적용 설치 파일 | `keep` | — | 0.6 | “설치된 버전보다 새 설치 파일” |
| H6 | 참조된 파일(§8.5, M6) | `keep` | — | 0.7 | “프로젝트 X 의 코드가 이 이름을 참조” |
| H7 | 프로젝트 확정(§8.3) | `move` | §8.3 목적지 | 매칭 점수 | “PL-Agent 작업 시간대에 생성된 스크린샷” / “파일명에 PL-Agent 포함” |
| H8 | 비활성 프로젝트 개발 캐시(§10) | `trash` | — | 0.8 | “비활성 프로젝트(마지막 활동 74일 전)의 재생성 가능한 캐시” |
| H9 | 버전 가족 최신본 / 이전본(§12.3) | `keep` / 없음(또는 `archive`) | — | 0.6 / 0.5 | “최신 버전” / “이전 버전으로 보임” |
| H10 | `installer` 미설치, 생성 30일 경과(이월 항목) | `trash` | — | 0.5 | “30일 동안 설치하지 않은 설치 파일” |
| H11 | `screenshot`, 이월 7회 이상(`carry_count ≥ 7`) | `archive` (`archive.root` 설정 시) / 없음 | — (NULL) | 0.4 | “일주일 넘게 결정하지 않은 스크린샷” |
| H12 | 그 외 | 없음 | — | — | — |

규칙:
- 제안 동작은 항상 `allowed_actions`(policy 계산) 안이어야 한다. 아니면 제안을 버리고 `suggestion_source='none'`.
- dataless 파일, 그리고 `trash` 가 허용되지 않은(해제 전) iCloud 동기화 항목: `trash`/`move`/`archive`/`rename` 을 내는 규칙(H2~H4·H7·H8·H10·H11, OCR `rename` §6.1)은 적용하지 않는다. 근거가 있으면 **제안 동작 없이 이유만** 남긴다(예: “같은 파일이 ~/Downloads 에도 있습니다 — iCloud 쪽은 지금 정리할 수 없습니다”). `keep` 이 근거 있는 경우(H5, H6, H9 최신본)만 그대로 제안.
- `trash` 가 허용된(게이트 열림, 다운로드됨) iCloud 동기화 항목: `trash` 를 내는 규칙(H2·H3·H4·H8·H10)은 적용할 수 있다. 단 (a) confidence 는 규칙 값에서 0.2 를 빼고 상한 0.7 — UI 일괄 기본 선택 기준(0.8)에 닿지 않게, (b) 이유 끝에 “(다른 기기에서도 삭제됩니다)”, (c) 이는 **제안일 뿐**이다 — 그룹 제안(`review_groups.suggested_action`) 계산에서 이 항목들은 제외하고, `decision.set --group` 은 이 항목을 trash 대상에서 건너뛴다(`W_PROTECTED_SKIPPED{reason:icloud_synced}`, 02 §10.1). `move`/`archive`/`rename` 을 내는 규칙(H7, H9 이전본 archive, H11, OCR rename)은 적용하지 않는다(v1 불허 확정).
- confidence 는 “이 제안을 사용자가 받아들일 가능성”의 휴리스틱 추정이다. UI 는 0.8 이상만 그룹 일괄 버튼의 기본 선택으로 쓴다(03 이 표시 규칙 확정).
- 이유 문구 규칙: 한국어 한 문장, 80자 이하, 보안 자산·환자 자료의 이름·경로 금지, 다른 파일 경로는 `display_path`(`~` 축약) 형태로만, 근거 수치 1개 포함 권장.
- 이월 항목은 새 세션에서 제안을 다시 계산한다(설치 상태 등이 바뀌었을 수 있음). 사용자가 이미 결정한 항목은 제안을 바꾸지 않는다.
- “왜 이렇게 제안됐나”(설명 가능성) 표현은 07 §6 이 정의하고, 이 절의 규칙 번호(H1~H12)를 근거 ID 로 쓴다.

---

## 14. 성능 예산과 대형 트리 제한

| 항목 | 목표 / 한도 | 근거 |
|---|---|---|
| 웜 스캔 | 기본 루트 합계 10만 엔트리, 변경 1% → ≤ 10초 (M1: 1만 엔트리 ≤ 2초) | NFR-PERF-001, 12 M1 |
| 큰 트리(Documents + iCloud Drive) | 합계 30만 엔트리 → ≤ 30초 목표(선형). 측정 결과가 넘으면 해당 루트만 `max_depth` 를 낮추라고 `doctor` 가 안내. dataless 파일은 `lstat` 만 하므로 비용이 일반 파일과 같다 | 소유자 결정(2026-11-24): 두 루트 기본 포함 |
| 순회 비용 | 파일당 `lstat` 1회(DirEntry 캐시), 디렉터리당 `scandir` 1회. 파일 내용 읽기 0회(변경 없는 파일) | |
| DB 쓰기 | 루트별 1 트랜잭션, `executemany`, 변경분만 UPDATE. 변경 없는 엔트리는 `last_seen_run_id` 일괄 UPDATE 1문(루트 단위 `WHERE root_id=? AND present=1 AND id NOT IN 변경/삭제`) | |
| 메모리 | 이전 상태 색인 ≈ 엔트리당 ~250B → 50만 엔트리 ≈ 125MB 상한. 초과 예상 시 루트별로 나눠 비교(루트 간 이동 2차 매칭은 vanished/appeared 목록만 전역 유지) | 02 §8 (DB 50만 파일 기준) |
| 루트당 엔트리 상한 | `scan.max_entries_per_root` 기본 300,000. 초과 시 순회 중단, 루트 결과는 “부분”으로 처리(§2.4 보이지 않음 ≠ 삭제 적용 — 중단 이후 경로의 기존 엔트리는 유지), `W_TRUNCATED`(02 §9) | 실수로 `~` 전체를 루트로 등록한 경우 방어 |
| 디렉터리당 엔트리 | 상한 없음, 단 50,000 초과 디렉터리는 그 디렉터리의 하위 디렉터리로 내려가지 않음 + `W_PARTIAL_SCAN` | 사진 덤프 폴더 |
| 해시 | run 당 2 GiB, 파일당 64MB | §2.5 |
| `mdls` | 파일 100개/호출, 호출당 타임아웃 10초, run 당 최대 2,000 파일(초과분 다음 run). 실패 → 해당 신호 없이 진행 | §2.7, §6 |
| git | 저장소 명령 5초, 단계 60초 | §8.1 |
| 개발 캐시 | 캐시당 5초, 단계 120초, 주 1회 | §10 |
| brew | 60초, 하루 1회 | §11.2 |
| intel 판단 단계 | 새 항목 1,000개 기준 ≤ 1초(해시·mdls 제외) | 순수 메모리 계산 |
| 진행 이벤트 | `--progress ndjson` 에서 1,000 엔트리 또는 1초마다 `phase=fs` 이벤트 | 02 §5.4 |

중단 안전: `scan.run` 이 중간에 죽으면 `scan_runs.status='running'` 이 남는다. 다음 `scan.run` 시작 시 `running` 인 이전 run 을 `interrupted` 로 바꾼다. 루트 단위 트랜잭션이라 커밋된 루트는 일관되고, 커밋 안 된 루트는 다음 run 에서 다시 diff 된다(이벤트 중복 없음: 커밋되지 않은 이벤트는 존재하지 않으므로).

---

## 14a. 이 문서가 쓰는 설정·상태 키 (02 §9 `[scan]`, 06 `app_meta` 키 목록에 반영됨)

```toml
[scan]
settle_seconds = 60                 # §2.2-4
hash_budget_bytes = 2147483648      # §2.5
max_entries_per_root = 300000       # §14
devcache_min_bytes = 104857600      # §10
```
`app_meta` 키: `last_devcache_scan_date`, `last_brew_scan_date`, `last_login_items_scan_date`, `last_app_lastused_refresh_date`.

## 15. 엣지 케이스 목록 (테스트 대상, 11 문서가 테스트로 옮김)

| # | 상황 | 기대 결과 |
|---|---|---|
| E1 | 파일 생성/수정/삭제/이름변경 각 1회 | 각각 이벤트 정확히 1개 (FR-CORE-003) |
| E2 | 편집기의 안전 저장(같은 경로, 새 inode) | `modified` 1개, `created`/`deleted` 없음 |
| E3 | 삭제 후 같은 inode 번호를 재사용한 새 파일(다른 이름) | `deleted` + `created`(birthtime 불일치로 이동 아님) |
| E4 | 하드링크 2개 중 하나 이름변경 | 경로 매칭 기반: `moved` 1개, 다른 링크 변화 없음 |
| E5 | Downloads → Desktop 이동(같은 볼륨) | `moved` 1개, 열린 항목이면 `subject_path` 갱신, 종결 항목이면 새 항목(다른 루트) — `keep_always` 면 suppression 으로 `suppressed`(FR-DR-008) |
| E6 | 외장 루트 → 내장 루트 이동(다른 볼륨, 같은 이름·크기·해시) | `moved` 1개(2차 매칭) |
| E7 | 다운로드 중 `.crdownload` | 엔트리 없음 → 완료 후 `created` 1개 |
| E8 | 폴더 이름변경(하위 1,000개) | `moved` 1개(디렉터리), 하위 경로 일괄 갱신 |
| E9 | 하위 폴더 권한 거부 | 그 하위 기존 엔트리 `present` 유지, `W_PERMISSION_SKIPPED` |
| E10 | 외장 볼륨 분리 | 루트 건너뜀, 엔트리 유지, 항목 `stale` 안 됨 |
| E11 | dataless 파일 | 해시·내용 읽기 0(open 감시 래퍼로 검증), 항목은 생성, `is_dataless=true`, `allowed_actions` = keep/keep_always/defer, `blocked_reasons` 전부 `dataless` (FR-CORE-008) |
| E11a | dataless 디렉터리 | `scandir` 0, 하위 기존 엔트리 유지 |
| E11b | 파일이 다운로드됨 → 다시 dataless 로 내려감 | 이벤트 0, `flags` 만 갱신 |
| E11c | `~/Documents` 와 iCloud 쪽 경로가 같은 (dev, inode) 디렉터리 | 한 번만 순회 |
| E11d | iCloud 항목과 Downloads 의 같은 파일(다운로드된 상태) | 게이트 열림/닫힘 모두 iCloud 사본이 keeper, Downloads 사본만 `trash` 제안 |
| E11e | 게이트 닫힘, 다운로드된 iCloud 설치 파일 | 제안 동작 없음, 이유만. `blocked_reasons.trash=icloud_synced` |
| E11g | 루트 `icloud_synced_mode=no` 인데 `~/Library/Mobile Documents/com~apple~CloudDocs/Desktop` 존재(S2) 또는 항목이 dataless(S3) | 루트 실효값 1(`detected`) 또는 항목 `icloud_synced=true` — 사용자 `no` 보다 실시간 신호 우선 |
| E11f | 게이트 열림, 다운로드된 iCloud 설치 파일 | `trash` 제안 confidence ≤ 0.7 + 전파 문구, 그룹 제안에서 제외, `--group` 결정 시 건너뜀 |
| E12 | 01:30 생성 파일, 21:00 스캔 | 전날 리뷰 날짜 귀속(FR-DR-002), 단 전날 세션 이후 세션이 이미 있으면 그 날짜 |
| E13 | 같은 파일 3개(64MB 이하) | 그룹 1, 최신 1개 `keep`, 나머지 `trash` (FR-SO-002) |
| E14 | `Foo.dmg` + `Foo.app`(가짜 Info.plist) | `trash`, “설치 완료된 설치 파일” (FR-SO-001) |
| E15 | `Foo-2.0.dmg`, 설치된 Foo 1.5 | `keep` “업데이트 미적용” |
| E16 | NFD 한글 파일명 `프로젝트.pdf` 와 NFC 프로젝트 이름 | 매칭 성공(토큰화 시 NFC), DB 경로는 원본 그대로 |
| E17 | 활성 저장소 안 `.env` | 05 판정 우선(`security_asset`) |
| E18 | 저장소를 Downloads 에 clone | 엔트리 1개(dir, 내부 미순회), `folder` 항목, 프로젝트 등록, 활성이면 `active_repo` |
| E19 | `node_modules` 가 git 추적됨 | 개발 캐시 항목 없음 |
| E20 | 첫 스캔(기준선) | 이벤트 0, 오늘 생성 파일만 항목 |
| E21 | 스캔 도중 강제 종료 후 재실행 | 이전 run `interrupted`, 이벤트 중복 없음 |
| E22 | 시계가 과거/미래인 파일(birthtime 2030년) | effective_time 클램프 → 오늘 |
| E23 | `brew`/`git` 미설치 | `W_TOOL_MISSING`, 나머지 정상 |
| E24 | 앱 자동 업데이트 | 항목 없음, 리포트 “업데이트된 앱” |
| E25 | zip 일부만 압축 해제됨 | 압축 해제 완료 제안 없음 |
