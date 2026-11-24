# 06 — 데이터 모델 (DATA MODEL)

> 상태: 기준 문서(contract). 테이블·컬럼·enum 값·상태 이름은 여기 정의된 것만 쓴다.
> DB 파일: `$DAYCLOSE_HOME/dayclose.db` (02 문서 §8). 접근은 `dayclose/store` 모듈만.

## 1. 공통 규칙

- SQLite ≥ 3.45 (Python 3.14 번들). 모든 테이블은 `STRICT`.
- 연결 시 PRAGMA: `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`, `busy_timeout=5000`, `trusted_schema=OFF`.
- PK 는 `INTEGER PRIMARY KEY`. 외부 노출 ID 는 접두사 문자열(02 §5.1)로 변환.
- 시각: `*_at` 컬럼은 **UTC epoch milliseconds INTEGER**. 파일 시각은 `*_ns`(epoch nanoseconds). 리뷰 날짜는 `review_date TEXT 'YYYY-MM-DD'`(로컬 시간 + `review.day_boundary` 적용).
- 불리언: `INTEGER NOT NULL CHECK (x IN (0,1))`.
- enum: `TEXT` + `CHECK (x IN (...))`. 값 추가는 마이그레이션으로(테이블 재작성 필요 → §7).
- JSON 컬럼은 이름이 `*_json`, `CHECK (json_valid(x))`.
- 민감 필드는 이름이 `*_enc`, `BLOB`(§6). 평문 컬럼에 같은 내용 저장 금지.
- 기기당 DB 하나: MacBook·Mac mini 는 각자 독립 DB(02 §8.1). `app_meta.device_id` 가 기기를 식별하며 행 단위 `device_id` 컬럼은 두지 않는다(한 DB 에 한 기기만 존재). 기기 간 병합·동기화 구조 없음. `protection_rules`·`suppressions`·`policy_rules`·`decisions` 도 기기별이다.
- 경로는 `os.fsdecode()` 결과 그대로(정규화하지 않음). 파일 동일성 판단은 경로가 아니라 `(dev, inode)` 가 1순위.

## 2. 엔티티 개요

```
scan_roots ─< file_entries ─< file_events >─ scan_runs
                  │
                  ├──── vault_assets ─< vault_findings
                  │
projects ─────────┤                    inventory_apps / inventory_packages / inventory_login_items
                  ▼                                   │
review_sessions ─< review_groups ─< review_items >────┘
                                      │  ├─< decisions
                                      │  └── suppressions (keep_always)
                                      ▼
                         plans ─< plan_operations, approvals
protection_rules, policy_rules(M6), file_text(M6), ai_requests(M6), audit_log, app_meta
(archive_targets/archive_records 는 2026-11-24 삭제 — 보관 폴더는 config `archive.root` 하나)
```

## 3. Enum 정의

| enum | 값 (순서 의미 있음 표시 ★) |
|---|---|
| `scan_root_kind` | `downloads`, `desktop`, `screenshots`, `documents`, `icloud_drive`, `projects`, `vault_extra`, `custom` |
| `run_status` | `running`, `completed`, `partial`, `failed`, `interrupted` |
| `run_trigger` | `init`, `manual`, `app`, `schedule`, `agent` |
| `entry_kind` | `file`, `dir`, `symlink`, `package` (`.app` 등 번들 디렉터리를 한 항목으로) |
| `file_event_type` | `created`, `modified`, `deleted`, `moved` |
| `subject_type` | `file`, `dir`, `app`, `package`, `git_repo`, `login_item` |
| `item_category` | `screenshot`, `image`, `document`, `installer`, `compressed`, `media`, `code`, `folder`, `misc`, `dev_cache`, `security_asset`, `app`, `package`, `git_repo`, `login_item` |
| `item_state` | `detected`, `proposed`, `decided`, `planned`, `executed`, `undone`, `failed`, `stale`, `suppressed` |
| `decision_action` | `keep`, `keep_always`, `trash`, `move`, `archive`, `defer`, `acknowledge` |
| `decision_actor` | `user`, `rule` |
| `channel` | `cli`, `app`, `skill`, `mcp`, `schedule`, `test` |
| `suggestion_source` | `none`, `heuristic`, `rule`, `ai` |
| `protection_class` ★ | `none` < `user_rule` < `system` < `active_repo` < `patient_data` < `security_asset` |
| `sensitivity` ★ | `normal` < `personal` < `patient` < `secret` |
| `preview_policy` (파생) | `full`, `ephemeral`, `metadata_only` |
| `ai_policy` (파생) | `external_ok`, `local_only`, `none` |
| `plan_state` | `draft`, `approved`, `executing`, `completed`, `partial`, `failed`, `cancelled`, `undone`, `partially_undone` |
| `op_type` | `trash`, `move`, `archive`, `rename`(M6), `restore` |
| `op_state` | `pending`, `running`, `done`, `failed`, `skipped` |
| `undo_state` | `not_applicable`, `undoable`, `undone`, `undo_failed`, `not_undoable` |
| `approval_method` | `app_button`, `cli_tty`, `native_dialog`, `test` |
| `vault_asset_kind` | `certificate`, `pkcs12`, `private_key`, `ssh_private_key`, `ssh_config`, `env_file`, `api_credential`, `cloud_credential`, `apple_signing`, `android_keystore`, `vpn_config`, `crypto_wallet`, `crypto_seed_suspected`, `db_credential`, `recovery_codes`, `npki_cert`, `unknown_secret` |
| `vault_detect_method` | `extension`, `filename`, `location`, `magic`, `content_pattern`, `gitleaks` |
| `vault_asset_status` | `active`, `missing`, `retired` |
| `backup_status` | `unknown`, `none`, `verified`, `stale` |
| `vault_finding_type` | `expiring_soon`, `expired`, `tracked_in_git`, `duplicate`, `bad_permissions`, `no_backup`, `exposed_location`, `plaintext_secret`, `seed_phrase_suspected` |
| `finding_severity` ★ | `info` < `warn` < `high` < `critical` |
| `finding_state` | `open`, `acknowledged`, `resolved` |
| `protection_rule_kind` | `path_prefix`, `glob`, `extension`, `project` |
| `suppression_match` | `entry_identity`, `path`, `path_glob`, `sha256`, `bundle_id`, `package`, `repo` |
| `policy_rule_state` | `suggested`, `active`, `rejected`, `disabled` |
| `project_kind` | `git`, `folder` |
| `package_manager` | `brew_formula`, `brew_cask` |
| `app_source` | `app_store`, `brew_cask`, `manual`, `unknown` |
| `login_item_kind` | `launch_agent_user`, `launch_agent_global`, `launch_daemon`, `login_item` |

`vault_asset_kind` 대응(05 문서가 탐지 규칙 확정): `.pem/.cer/.crt/.der/.p7b` → `certificate`; `.p12/.pfx` → `pkcs12`; `.key/.pkcs8` → `private_key`; `id_rsa/id_ed25519` → `ssh_private_key`; `~/.ssh/config` → `ssh_config`; `.env*` → `env_file`; AWS/GCP/Azure/Firebase → `cloud_credential`; `.p8`/`.mobileprovision`/개발자 인증서 → `apple_signing`; `.jks/.keystore/key.properties` → `android_keystore`; `.ovpn`/WireGuard → `vpn_config`; 지갑 JSON/Keystore → `crypto_wallet`; 복구 구문 의심 → `crypto_seed_suspected`; DB 접속 정보 → `db_credential`; 복구 키·백업 코드 → `recovery_codes`; NPKI `signCert.der/signPri.key` → `npki_cert`.

### 3.1 파생 값

`sensitivity` → `preview_policy`, `ai_policy` (저장하지 않고 읽을 때 계산, `policy/sensitivity.py`):

| sensitivity | preview_policy | ai_policy | 판정 근거(04/05/07 문서가 세부 확정) |
|---|---|---|---|
| `normal` | `full` | `external_ok` (단 `ai.allow_external=false` 면 `local_only`. 외부 공급자는 소유자 허용, 옵트인) | 기본값 |
| `personal` | `full` | `local_only` | 개인 문서·사진, 스크린샷(OCR 전 기본값) |
| `patient` | `ephemeral` | `none` | `patient_data` 보호 판정 |
| `secret` | `metadata_only` | `none` | `security_asset` 판정, gitleaks 적중 |

결정: 스크린샷은 OCR 결과가 나오기 전까지 `personal` 로 둔다. 이유: 화면에 비밀번호·환자 정보가 찍혀 있을 수 있음.
결정: `patient`·`secret` 는 로컬 모델에도 보내지 않는다(`none`). 이유: 결정론적 규칙으로 충분하고, 모델 입력이 로그·캐시로 새는 경로를 원천 차단.

`protection_class` → `allowed_actions`: 02 문서 §10.1 표가 기준.
추가 규칙: `protection=active_repo` 라도 `category=dev_cache` 이고 결정이 항목 단위면 `trash` 허용(재생성 가능한 산출물: `node_modules`, `.build`, `DerivedData` 등, 04 문서가 목록 확정).

## 4. 상태 기계

### 4.1 리뷰 항목 (`review_items.state`)

```
          (collector)
              │
              ▼
          detected ──(intel/policy: 제안 부착)──▶ proposed ◀──────────────┐
           │   │                                  │  │  ▲                │
           │   └──────────(suppression 일치)────▶ suppressed            │ decision.undo
           │                                      │  │                   │
           └──(대상 소멸)──▶ stale ◀──(대상 소멸)──┘  │ decision.set      │
                              ▲                      ▼ (defer 제외)      │
                              │                   decided ───────────────┤
                              │  (사전조건 불일치)   │ plan.create         │
                              ├──────────────────  ▼ (trash/move/archive)│
                              │                   planned ──plan.cancel──▶ decided
                              │                   │      │
                              │            op done│      │op failed
                              │                   ▼      ▼
                              │               executed  failed ──decision.undo──▶ proposed
                              │                   │       └──plan.create──▶ planned
                              │         plan.undo ▼
                              │                 undone
```

전이 표(이 외의 전이는 `E_INVALID_STATE`):

| from | to | 트리거 | 부수 효과 |
|---|---|---|---|
| — | `detected` | collector 가 항목 생성 규칙(04 문서) 충족 | `review_date`=탐지 시점의 리뷰 날짜 |
| `detected` | `proposed` | 같은 scan 내 `intel`+`policy` 처리 완료 | `suggestion_*`, `protection`, `sensitivity`, `group_id` 설정. 제안이 없으면 `suggestion_source='none'` |
| `detected`,`proposed` | `suppressed` | 활성 suppression 일치 | `closed_reason='suppressed'`, `suppression_id` |
| `detected`,`proposed`,`decided` | `stale` | 대상 삭제됨/루트 밖으로 이동/식별자 변경 | `closed_reason='subject_gone'` |
| `proposed` | `proposed` | `decision.set --action defer` | decisions 행 추가, `deferred_until`(기본 다음 리뷰 날짜) |
| `proposed` | `decided` | `decision.set` (defer 외, `allowed_actions` 안) | `decision_id`, `decided_action`, `decided_at`. `keep_always` 면 suppression 생성 |
| `decided` | `proposed` | `decision.undo` | 현재 decision `revoked_at` 기록. `keep_always` 로 생긴 suppression 제거 |
| `decided` | `planned` | `plan.create` (`decided_action ∈ {trash,move,archive}`) | `plan_op_id` |
| `planned` | `decided` | `plan.cancel` / draft plan 폐기 | `plan_op_id=NULL` |
| `planned` | `executed` | 해당 op `done` | `executed_at` |
| `planned` | `failed` | 해당 op `failed` | `last_error_code` |
| `planned` | `stale` | 해당 op `skipped`(`E_STALE`) | |
| `failed` | `planned` | 새 `plan.create` 에 포함 | |
| `failed` | `proposed` | `decision.undo` | |
| `executed` | `undone` | `plan.undo` 의 해당 op `undone` | `undone_at`. 자동으로 재질문하지 않음(결정: 사용자가 되돌렸다는 사실 자체가 판단) |

종결 상태: `executed`(undo 전), `undone`, `stale`, `suppressed`, 그리고 `decided` 중 `decided_action ∈ {keep, keep_always, acknowledge}`.

재탐지 규칙(04 문서가 세부 확정, 여기서는 불변식만): 파일 항목은 `created` 이벤트와 “다른 스캔 루트로의 `moved`” 이벤트에서만 새로 생긴다. `modified` 는 열린 항목의 스냅샷 필드만 갱신하고 종결 항목을 다시 열지 않는다. 따라서 `keep` 으로 종결된 파일은 내용이 바뀌어도 다시 묻지 않는다.

**열린 항목(`is_open=1`)**: `state ∈ {detected, proposed, planned, failed}` 또는 (`state=decided` 이고 `decided_action ∈ {trash, move, archive}`). 같은 `subject_key` 의 열린 항목은 최대 1개(부분 유니크 인덱스).

### 4.2 이월(carry-over)과 보류

`review.summary --review-date D` 가 D 의 세션을 처음 열 때(트랜잭션 1개):
1. `is_open=1 AND state IN ('detected','proposed') AND review_date < D AND last_carried_date IS NOT D` 인 항목:
   - `deferred_until IS NULL OR deferred_until <= D` → `carry_count += 1`, `last_carried_date = D`, D 의 그룹으로 재배정.
   - `deferred_until > D` → 이월하지 않고 “보류 중” 수만 집계.
2. `state='decided' AND is_open=1`(계획 대기) 항목은 “실행 대기” 영역에 표시(그룹 재배정 없음).
3. 세션 지표 `stats_json` 계산.

같은 날짜로 다시 열면 1단계는 일어나지 않는다(`last_carried_date` 로 멱등). `config.review.carryover=false` 면 1단계 생략(항목은 여전히 `item.list --open` 으로 조회 가능).

### 4.3 “유지하고 다시 묻지 않기” (`keep_always`)

`decision.set --action keep_always` 는 항목을 `decided` 로 만들고 `suppressions` 행을 만든다.

| subject_type | 기본 `match_type` / `match_value` |
|---|---|
| `file`,`dir` | `entry_identity` / `"<dev>:<inode>"` (+ 보조로 `path` 저장) |
| `app` | `bundle_id` / 번들 ID |
| `package` | `package` / `"<manager>:<name>"` |
| `git_repo` | `repo` / `project_id` |
| `login_item` | `path` / plist 경로 |

향후 collector 가 만든 항목이 활성 suppression(`removed_at IS NULL AND (expires_at IS NULL OR expires_at > now)`)과 일치하면 `detected → suppressed` 로 곧장 간다(사용자에게 보이지 않음, 리포트에 “조용히 유지 N개” 집계).
`path_glob`·`sha256` 매칭은 사용자가 규칙으로 명시한 경우(07 문서)만. 해제는 `suppression.remove`.

### 4.4 계획 (`plans.state`)

```
draft ──plan.approve──▶ approved ──plan.apply──▶ executing ──▶ completed
  │                        │                        ├────────▶ partial   (일부 op failed/skipped)
  │                        │                        └────────▶ failed    (done 0개)
  └──plan.cancel──▶ cancelled ◀──plan.cancel──┘
completed|partial ──plan.undo(전체)──▶ undone
completed|partial ──plan.undo(일부 또는 일부 실패)──▶ partially_undone ──plan.undo──▶ undone
```

| from | to | 조건 |
|---|---|---|
| `draft` | `approved` | approval 행 생성, `approvals.plan_hash == plans.plan_hash` |
| `draft`,`approved` | `cancelled` | `plan.cancel`. 항목 `planned → decided` |
| `approved` | `executing` | `plan.apply` 시작(잠금 보유) |
| `executing` | `completed` / `partial` / `failed` | 모든 op 가 `done` / 혼합 / `done` 0개 |
| `executing` | `executing` | 크래시 후 재시작: `plan.recover` 가 op 정합화 후 남은 op 계속 또는 종료 상태 결정 |
| `completed`,`partial`,`partially_undone` | `undone`,`partially_undone` | `plan.undo` 결과 |

draft 는 내용이 바뀌지 않는다(불변). 항목을 더하거나 빼려면 cancel 후 새 plan. 결정: 승인 대상이 바뀌는 경로를 없애기 위함.

### 4.5 연산 (`plan_operations`)

`op_state`: `pending → running → done | failed`, `pending → skipped`(사전조건/정책 불일치), `running → done|failed`(recover 판정).
`undo_state`: 생성 시 `not_applicable`; `done` 이 되면 `undoable`(trash/move/archive/rename) 또는 `not_undoable`(아직 없음); undo 성공 `undone`, 실패 `undo_failed`(예: 휴지통 비워짐 → `E_UNDO_IMPOSSIBLE`).

### 4.6 보안 자산·발견 사항

`vault_assets.status`: `active`(현재 존재) ↔ `missing`(마지막 스캔에서 없음; 경로 이동이면 동일 지문으로 재연결 후 `active`), `retired`(사용자가 폐기 표시, M3 의 `vault.annotate`).
`vault_findings.state`: `open → acknowledged`(사용자 확인) `→ resolved`(조건 해소 시 스캔이 자동 설정, 예: 권한 수정됨). `acknowledged` 도 조건 해소 시 `resolved`.

## 5. DDL

마이그레이션 번호별로 나뉜다(§7). 아래가 각 마이그레이션 파일의 내용이다.

### 5.1 `0001_core.sql` (M1)

```sql
CREATE TABLE app_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
) STRICT;
-- 예: ('device_id','dev_5f2c9a1e'), ('created_at','1764000000000'), ('contract_version','1')

CREATE TABLE schema_migrations (
  version    INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  checksum   TEXT NOT NULL,            -- 마이그레이션 SQL 파일의 sha256
  applied_at INTEGER NOT NULL
) STRICT;

CREATE TABLE scan_roots (
  id          INTEGER PRIMARY KEY,
  path        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('downloads','desktop','screenshots','documents','icloud_drive','projects','vault_extra','custom')),
  enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  max_depth   INTEGER,                 -- NULL = 무제한. projects 기본 2 (저장소 탐지용)
  file_level  INTEGER NOT NULL DEFAULT 1 CHECK (file_level IN (0,1)), -- 0 = 파일 단위 항목 생성 안 함 (projects)
  created_at  INTEGER NOT NULL,
  removed_at  INTEGER
) STRICT;
CREATE UNIQUE INDEX ux_scan_roots_path_active ON scan_roots(path) WHERE removed_at IS NULL;

CREATE TABLE scan_runs (
  id           INTEGER PRIMARY KEY,
  started_at   INTEGER NOT NULL,
  finished_at  INTEGER,
  status       TEXT NOT NULL CHECK (status IN ('running','completed','partial','failed','interrupted')),
  trigger      TEXT NOT NULL CHECK (trigger IN ('init','manual','app','schedule','agent')),
  collectors_json TEXT NOT NULL CHECK (json_valid(collectors_json)),  -- ["fs","git",...]
  stats_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),
  error_code   TEXT,
  request_id   TEXT
) STRICT;
CREATE INDEX ix_scan_runs_started ON scan_runs(started_at);

CREATE TABLE file_entries (
  id              INTEGER PRIMARY KEY,
  root_id         INTEGER NOT NULL REFERENCES scan_roots(id),
  path            TEXT NOT NULL,
  name            TEXT NOT NULL,
  ext             TEXT,                -- 소문자, 점 제외. 없으면 NULL
  kind            TEXT NOT NULL CHECK (kind IN ('file','dir','symlink','package')),
  size_bytes      INTEGER NOT NULL,    -- package/dir 는 하위 합계(04 문서의 상한 규칙)
  mtime_ns        INTEGER NOT NULL,
  ctime_ns        INTEGER NOT NULL,
  birthtime_ns    INTEGER,
  dev             INTEGER NOT NULL,
  inode           INTEGER NOT NULL,
  mode            INTEGER NOT NULL,    -- st_mode
  flags           INTEGER NOT NULL DEFAULT 0, -- st_flags. SF_DATALESS(0x40000000) = iCloud 미다운로드 → 내용 접근 금지 (02 §10.6)
  sha256          TEXT,                -- 지연 계산. hash_max_bytes 초과/dataless 는 NULL
  sha256_mtime_ns INTEGER,             -- sha256 계산 당시 mtime (무효화 판단)
  where_from_host TEXT,                -- kMDItemWhereFroms 의 호스트만 (전체 URL 저장 금지)
  sensitivity     TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN ('normal','personal','patient','secret')),
  protection      TEXT NOT NULL DEFAULT 'none' CHECK (protection IN ('none','user_rule','system','active_repo','patient_data','security_asset')),
  project_id      INTEGER,             -- projects.id (0002 에서 생기는 테이블). FK 제약 없음, 앱 로직으로 보장
  present         INTEGER NOT NULL DEFAULT 1 CHECK (present IN (0,1)),
  first_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
  last_seen_run_id  INTEGER NOT NULL REFERENCES scan_runs(id),
  deleted_run_id    INTEGER REFERENCES scan_runs(id)
) STRICT;
CREATE UNIQUE INDEX ux_file_entries_path_present ON file_entries(path) WHERE present = 1;
CREATE INDEX ix_file_entries_identity ON file_entries(dev, inode);
CREATE INDEX ix_file_entries_root ON file_entries(root_id, present);
CREATE INDEX ix_file_entries_sha ON file_entries(sha256) WHERE sha256 IS NOT NULL;
CREATE INDEX ix_file_entries_project ON file_entries(project_id) WHERE project_id IS NOT NULL;

CREATE TABLE file_events (
  id          INTEGER PRIMARY KEY,
  run_id      INTEGER NOT NULL REFERENCES scan_runs(id),
  entry_id    INTEGER NOT NULL REFERENCES file_entries(id),
  event       TEXT NOT NULL CHECK (event IN ('created','modified','deleted','moved')),
  old_path    TEXT,                    -- moved/deleted
  new_path    TEXT,                    -- created/modified/moved
  size_delta  INTEGER NOT NULL DEFAULT 0,
  detected_at INTEGER NOT NULL
) STRICT;
CREATE INDEX ix_file_events_run ON file_events(run_id);
CREATE INDEX ix_file_events_entry ON file_events(entry_id, detected_at);
CREATE INDEX ix_file_events_time ON file_events(detected_at);

CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY,
  ts          INTEGER NOT NULL,
  request_id  TEXT NOT NULL,
  command     TEXT NOT NULL,           -- 명령 ID (02 §5.3)
  channel     TEXT NOT NULL CHECK (channel IN ('cli','app','skill','mcp','schedule','test')),
  ok          INTEGER NOT NULL CHECK (ok IN (0,1)),
  error_code  TEXT,
  target_type TEXT,                    -- 'item','plan','asset','root',...
  target_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(target_ids_json)), -- 외부 ID 문자열 배열
  summary     TEXT NOT NULL DEFAULT '' -- 경로·비밀·메모 금지. 예: "decision.set trash ×3"
) STRICT;
CREATE INDEX ix_audit_ts ON audit_log(ts);
```

`audit_log` 에는 쓰기 명령(W)만 기록한다. 읽기 명령은 기록하지 않는다(용량).

### 5.2 `0002_review.sql` (M2)

```sql
CREATE TABLE projects (
  id               INTEGER PRIMARY KEY,
  root_path        TEXT NOT NULL UNIQUE,
  name             TEXT NOT NULL,
  kind             TEXT NOT NULL CHECK (kind IN ('git','folder')),
  is_active        INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1)),
  last_commit_at   INTEGER,
  last_activity_at INTEGER,            -- 저장소 내 최신 mtime (얕은 샘플링, 04 문서)
  dirty_count      INTEGER,            -- git status --porcelain 줄 수
  branch_count     INTEGER,
  stale_branch_count INTEGER,          -- 90일 이상 커밋 없는 로컬 브랜치
  remote_host      TEXT,               -- 'github.com' 등 호스트만
  present          INTEGER NOT NULL DEFAULT 1 CHECK (present IN (0,1)),
  first_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
  last_seen_run_id  INTEGER NOT NULL REFERENCES scan_runs(id),
  updated_at       INTEGER NOT NULL
) STRICT;
CREATE INDEX ix_projects_active ON projects(is_active) WHERE present = 1;

CREATE TABLE review_sessions (
  id           INTEGER PRIMARY KEY,
  review_date  TEXT NOT NULL UNIQUE,   -- 'YYYY-MM-DD'
  opened_at    INTEGER NOT NULL,
  closed_at    INTEGER,
  opened_channel TEXT NOT NULL CHECK (opened_channel IN ('cli','app','skill','mcp','schedule','test')),
  stats_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json))
  -- stats_json 키: new_files, modified_files, deleted_files, new_apps, new_packages,
  --   items_total, items_open, items_decided, carried_over, deferred, pending_plan_bytes,
  --   trash_planned, suppressed_today, vault_new, vault_findings_open
) STRICT;

CREATE TABLE review_groups (
  id               INTEGER PRIMARY KEY,
  session_id       INTEGER NOT NULL REFERENCES review_sessions(id),
  group_key        TEXT NOT NULL,      -- 04 문서 규칙. 예 'installer:installed', 'screenshot:day', 'project:3', 'duplicate:<sha256 앞 16자>', 'vault:new'
  category         TEXT NOT NULL CHECK (category IN ('screenshot','image','document','installer','compressed','media','code','folder','misc','dev_cache','security_asset','app','package','git_repo','login_item')),
  title            TEXT NOT NULL,      -- 사용자 표시 문구. 비밀/환자 정보 금지
  rationale        TEXT,
  suggested_action TEXT CHECK (suggested_action IN ('keep','keep_always','trash','move','archive','defer','acknowledge')),
  suggested_dest   TEXT,
  suggestion_source TEXT NOT NULL DEFAULT 'none' CHECK (suggestion_source IN ('none','heuristic','rule','ai')),
  sort_order       INTEGER NOT NULL DEFAULT 0,
  created_at       INTEGER NOT NULL,
  UNIQUE (session_id, group_key)
) STRICT;

CREATE TABLE review_items (
  id                 INTEGER PRIMARY KEY,
  subject_type       TEXT NOT NULL CHECK (subject_type IN ('file','dir','app','package','git_repo','login_item')),
  subject_key        TEXT NOT NULL,    -- 'file:<dev>:<inode>' | 'app:<bundle_id>' | 'pkg:<manager>:<name>' | 'repo:<project_id>' | 'login:<plist_path>'
  entry_id           INTEGER REFERENCES file_entries(id),
  project_id         INTEGER REFERENCES projects(id),
  app_id             INTEGER,          -- 0003 inventory_apps.id
  package_id         INTEGER,          -- 0003 inventory_packages.id
  login_item_id      INTEGER,          -- 0003 inventory_login_items.id
  vault_asset_id     INTEGER,          -- 0003 vault_assets.id
  subject_path       TEXT,             -- 탐지/최근 이동 시점 경로 스냅샷 (표시·stale 판단용)
  origin_root_kind   TEXT CHECK (origin_root_kind IN ('downloads','desktop','screenshots','documents','icloud_drive','projects','vault_extra','custom')),
  category           TEXT NOT NULL CHECK (category IN ('screenshot','image','document','installer','compressed','media','code','folder','misc','dev_cache','security_asset','app','package','git_repo','login_item')),
  state              TEXT NOT NULL CHECK (state IN ('detected','proposed','decided','planned','executed','undone','failed','stale','suppressed')),
  protection         TEXT NOT NULL DEFAULT 'none' CHECK (protection IN ('none','user_rule','system','active_repo','patient_data','security_asset')),
  sensitivity        TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN ('normal','personal','patient','secret')),
  suggested_action   TEXT CHECK (suggested_action IN ('keep','keep_always','trash','move','archive','defer','acknowledge')),
  suggested_dest     TEXT,
  suggestion_source  TEXT NOT NULL DEFAULT 'none' CHECK (suggestion_source IN ('none','heuristic','rule','ai')),
  suggestion_reason  TEXT,             -- 사용자 표시 문구. 비밀/환자 정보 금지
  confidence         REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  group_id           INTEGER REFERENCES review_groups(id),
  review_date        TEXT NOT NULL,    -- 최초 탐지 리뷰 날짜
  last_carried_date  TEXT,
  carry_count        INTEGER NOT NULL DEFAULT 0,
  deferred_until     TEXT,             -- 'YYYY-MM-DD'
  decision_id        INTEGER,          -- 현재 유효 결정 (decisions.id)
  decided_action     TEXT CHECK (decided_action IN ('keep','keep_always','trash','move','archive','defer','acknowledge')),
  plan_op_id         INTEGER,          -- 0004 plan_operations.id
  suppression_id     INTEGER,
  closed_reason      TEXT CHECK (closed_reason IN ('suppressed','subject_gone','executed','undone')),
  last_error_code    TEXT,
  first_detected_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
  last_detected_run_id  INTEGER NOT NULL REFERENCES scan_runs(id),
  detected_at        INTEGER NOT NULL,
  proposed_at        INTEGER,
  decided_at         INTEGER,
  executed_at        INTEGER,
  undone_at          INTEGER,
  state_changed_at   INTEGER NOT NULL,
  is_open            INTEGER GENERATED ALWAYS AS (
                       CASE WHEN state IN ('detected','proposed','planned','failed') THEN 1
                            WHEN state = 'decided' AND decided_action IN ('trash','move','archive') THEN 1
                            ELSE 0 END) STORED,
  CHECK (state <> 'decided' OR decided_action IS NOT NULL),
  CHECK (decided_action IS NULL OR decided_action <> 'defer')   -- defer 는 상태를 바꾸지 않음
) STRICT;
CREATE UNIQUE INDEX ux_review_items_open_subject ON review_items(subject_key) WHERE is_open = 1;
CREATE INDEX ix_review_items_state ON review_items(state, review_date);
CREATE INDEX ix_review_items_open ON review_items(is_open, review_date) WHERE is_open = 1;
CREATE INDEX ix_review_items_group ON review_items(group_id);
CREATE INDEX ix_review_items_entry ON review_items(entry_id);
CREATE INDEX ix_review_items_category ON review_items(category, state);

CREATE TABLE decisions (
  id           INTEGER PRIMARY KEY,
  item_id      INTEGER NOT NULL REFERENCES review_items(id),
  action       TEXT NOT NULL CHECK (action IN ('keep','keep_always','trash','move','archive','defer','acknowledge')),
  dest_path    TEXT,                   -- move 필수. archive 는 NULL (plan.create 가 config archive.root 기준으로 목적지 결정)
  defer_until  TEXT,
  note_enc     BLOB,                   -- 사용자 메모 (암호화, §6)
  actor        TEXT NOT NULL DEFAULT 'user' CHECK (actor IN ('user','rule')),
  rule_id      INTEGER,                -- actor='rule' 일 때 policy_rules.id (M6)
  scope        TEXT NOT NULL CHECK (scope IN ('item','group')),
  group_id     INTEGER REFERENCES review_groups(id),
  channel      TEXT NOT NULL CHECK (channel IN ('cli','app','skill','mcp','schedule','test')),
  request_id   TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  revoked_at   INTEGER,
  CHECK (action <> 'move' OR dest_path IS NOT NULL),
  CHECK (action <> 'defer' OR defer_until IS NOT NULL)
) STRICT;
CREATE INDEX ix_decisions_item ON decisions(item_id, created_at);
CREATE INDEX ix_decisions_created ON decisions(created_at);
-- 학습(M6)용: 최근 결정을 카테고리·동작별로 집계
CREATE INDEX ix_decisions_action ON decisions(action, created_at) WHERE revoked_at IS NULL;

CREATE TABLE protection_rules (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('path_prefix','glob','extension','project')),
  pattern     TEXT NOT NULL,
  protection  TEXT NOT NULL CHECK (protection IN ('user_rule','system','active_repo','patient_data','security_asset')),
  sensitivity TEXT CHECK (sensitivity IN ('normal','personal','patient','secret')),
  source      TEXT NOT NULL CHECK (source IN ('builtin','user','config')),
  enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  created_at  INTEGER NOT NULL,
  UNIQUE (kind, pattern, protection)
) STRICT;
-- builtin 시드: ('path_prefix','/System','system'), ('path_prefix','/Library','system'),
--   ('glob','/Applications/*.app/**','system'), ('path_prefix','~/.ssh','security_asset') 등 — 04/05 문서가 확정.
-- config 소스: config.toml [protection].patient_filename_patterns 를 로드 시 glob/patient_data 규칙으로 동기화. (환자 폴더 설정은 없음 — 2026-11-24)
-- builtin 규칙은 비활성화할 수 없다(enabled 변경 시 E_PROTECTED).

CREATE TABLE suppressions (
  id            INTEGER PRIMARY KEY,
  match_type    TEXT NOT NULL CHECK (match_type IN ('entry_identity','path','path_glob','sha256','bundle_id','package','repo')),
  match_value   TEXT NOT NULL,
  aux_path      TEXT,                  -- entry_identity 일 때 참고 경로
  category      TEXT,                  -- NULL = 모든 카테고리
  created_from_decision_id INTEGER REFERENCES decisions(id),
  created_at    INTEGER NOT NULL,
  expires_at    INTEGER,
  removed_at    INTEGER
) STRICT;
CREATE INDEX ix_suppressions_match ON suppressions(match_type, match_value) WHERE removed_at IS NULL;
```

### 5.3 `0003_vault_inventory.sql` (M3)

```sql
CREATE TABLE vault_assets (
  id                 INTEGER PRIMARY KEY,
  entry_id           INTEGER REFERENCES file_entries(id),
  path               TEXT NOT NULL,
  kind               TEXT NOT NULL CHECK (kind IN ('certificate','pkcs12','private_key','ssh_private_key','ssh_config','env_file','api_credential','cloud_credential','apple_signing','android_keystore','vpn_config','crypto_wallet','crypto_seed_suspected','db_credential','recovery_codes','npki_cert','unknown_secret')),
  detect_methods_json TEXT NOT NULL CHECK (json_valid(detect_methods_json)), -- ["extension","magic",...]
  confidence         REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  masked_name        TEXT NOT NULL,    -- 표시용 마스킹 이름 (05 문서 규칙)
  fingerprint_sha256 TEXT,             -- 파일 SHA-256. crypto_seed_suspected 는 항상 NULL
  key_fingerprint    TEXT,             -- 공개키 SHA-256 지문 (인증서·키 쌍 연결/중복 판정)
  cert_subject_enc   BLOB,             -- 인증서 subject (실명 포함 가능 → 암호화)
  cert_issuer        TEXT,
  cert_not_before    INTEGER,
  cert_not_after     INTEGER,
  expiry_source      TEXT NOT NULL DEFAULT 'unknown' CHECK (expiry_source IN ('file','user','unknown')),
  needs_password     INTEGER NOT NULL DEFAULT 0 CHECK (needs_password IN (0,1)), -- 암호 걸린 p12 등: 메타데이터 미확인
  permissions_mode   INTEGER,
  in_git_repo        INTEGER NOT NULL DEFAULT 0 CHECK (in_git_repo IN (0,1)),
  git_tracked        INTEGER NOT NULL DEFAULT 0 CHECK (git_tracked IN (0,1)),
  git_ignored        INTEGER NOT NULL DEFAULT 0 CHECK (git_ignored IN (0,1)),
  project_id         INTEGER REFERENCES projects(id),
  backup_status      TEXT NOT NULL DEFAULT 'unknown' CHECK (backup_status IN ('unknown','none','verified','stale')),
  status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','missing','retired')),
  user_label_enc     BLOB,
  user_note_enc      BLOB,
  user_expires_on    TEXT,             -- 'YYYY-MM-DD' (파일로 알 수 없는 API 키 만료일)
  first_seen_run_id  INTEGER NOT NULL REFERENCES scan_runs(id),
  last_seen_run_id   INTEGER NOT NULL REFERENCES scan_runs(id),
  updated_at         INTEGER NOT NULL
) STRICT;
CREATE UNIQUE INDEX ux_vault_assets_entry ON vault_assets(entry_id) WHERE entry_id IS NOT NULL AND status <> 'retired';
CREATE INDEX ix_vault_assets_kind ON vault_assets(kind, status);
CREATE INDEX ix_vault_assets_fp ON vault_assets(fingerprint_sha256) WHERE fingerprint_sha256 IS NOT NULL;
CREATE INDEX ix_vault_assets_keyfp ON vault_assets(key_fingerprint) WHERE key_fingerprint IS NOT NULL;
CREATE INDEX ix_vault_assets_expiry ON vault_assets(cert_not_after) WHERE cert_not_after IS NOT NULL;

CREATE TABLE vault_findings (
  id          INTEGER PRIMARY KEY,
  asset_id    INTEGER REFERENCES vault_assets(id),
  entry_id    INTEGER REFERENCES file_entries(id),  -- 자산이 아닌 일반 파일 내 비밀(plaintext_secret)
  finding     TEXT NOT NULL CHECK (finding IN ('expiring_soon','expired','tracked_in_git','duplicate','bad_permissions','no_backup','exposed_location','plaintext_secret','seed_phrase_suspected')),
  severity    TEXT NOT NULL CHECK (severity IN ('info','warn','high','critical')),
  rule_id     TEXT,                    -- gitleaks RuleID 또는 내부 패턴 ID. 매치 문자열 저장 금지
  line_no     INTEGER,
  state       TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open','acknowledged','resolved')),
  detected_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
  last_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
  acknowledged_at INTEGER,
  resolved_at INTEGER,
  CHECK (asset_id IS NOT NULL OR entry_id IS NOT NULL)
) STRICT;
CREATE UNIQUE INDEX ux_vault_findings_open ON vault_findings(COALESCE(asset_id,0), COALESCE(entry_id,0), finding, COALESCE(rule_id,''), COALESCE(line_no,0)) WHERE state <> 'resolved';
CREATE INDEX ix_vault_findings_state ON vault_findings(state, severity);

CREATE TABLE inventory_apps (
  id            INTEGER PRIMARY KEY,
  bundle_id     TEXT,                  -- 없으면 path 로 식별
  name          TEXT NOT NULL,
  path          TEXT NOT NULL,
  version       TEXT,
  size_bytes    INTEGER,
  source        TEXT NOT NULL DEFAULT 'unknown' CHECK (source IN ('app_store','brew_cask','manual','unknown')),
  last_used_at  INTEGER,               -- mdls kMDItemLastUsedDate
  present       INTEGER NOT NULL DEFAULT 1 CHECK (present IN (0,1)),
  first_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
  last_seen_run_id  INTEGER NOT NULL REFERENCES scan_runs(id),
  version_changed_run_id INTEGER REFERENCES scan_runs(id),
  updated_at    INTEGER NOT NULL
) STRICT;
CREATE UNIQUE INDEX ux_inventory_apps_path ON inventory_apps(path) WHERE present = 1;
CREATE INDEX ix_inventory_apps_bundle ON inventory_apps(bundle_id);

CREATE TABLE inventory_packages (
  id            INTEGER PRIMARY KEY,
  manager       TEXT NOT NULL CHECK (manager IN ('brew_formula','brew_cask')),
  name          TEXT NOT NULL,
  version       TEXT,
  on_request    INTEGER CHECK (on_request IN (0,1)), -- 직접 설치 여부 (의존성 설치 구분)
  present       INTEGER NOT NULL DEFAULT 1 CHECK (present IN (0,1)),
  first_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
  last_seen_run_id  INTEGER NOT NULL REFERENCES scan_runs(id),
  updated_at    INTEGER NOT NULL,
  UNIQUE (manager, name)
) STRICT;

CREATE TABLE inventory_login_items (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('launch_agent_user','launch_agent_global','launch_daemon','login_item')),
  label         TEXT NOT NULL,
  plist_path    TEXT,
  program_path  TEXT,
  present       INTEGER NOT NULL DEFAULT 1 CHECK (present IN (0,1)),
  first_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
  last_seen_run_id  INTEGER NOT NULL REFERENCES scan_runs(id),
  updated_at    INTEGER NOT NULL,
  UNIQUE (kind, label)
) STRICT;
```

### 5.4 `0004_execution.sql` (M5)

```sql
CREATE TABLE plans (
  id             INTEGER PRIMARY KEY,
  state          TEXT NOT NULL CHECK (state IN ('draft','approved','executing','completed','partial','failed','cancelled','undone','partially_undone')),
  plan_hash      TEXT NOT NULL,        -- 08 문서의 정규화 규칙으로 계산한 sha256 hex
  op_count       INTEGER NOT NULL,
  total_bytes    INTEGER NOT NULL,
  created_channel TEXT NOT NULL CHECK (created_channel IN ('cli','app','skill','mcp','schedule','test')),
  created_request_id TEXT NOT NULL,
  created_at     INTEGER NOT NULL,
  approval_id    INTEGER,
  started_at     INTEGER,
  finished_at    INTEGER,
  undone_at      INTEGER,
  summary_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(summary_json)) -- {"trash":12,"move":3,"bytes_by_op":{...}}
) STRICT;
CREATE INDEX ix_plans_state ON plans(state, created_at);

CREATE TABLE plan_operations (
  id             INTEGER PRIMARY KEY,
  plan_id        INTEGER NOT NULL REFERENCES plans(id),
  seq            INTEGER NOT NULL,
  item_id        INTEGER NOT NULL REFERENCES review_items(id),
  op             TEXT NOT NULL CHECK (op IN ('trash','move','archive','rename','restore')),
  src_path       TEXT NOT NULL,
  dst_path       TEXT,                 -- trash 는 실행 시 결정되어 actual_dst_path 에 기록
  pre_dev        INTEGER NOT NULL,
  pre_inode      INTEGER NOT NULL,
  pre_size       INTEGER NOT NULL,
  pre_mtime_ns   INTEGER NOT NULL,
  pre_sha256     TEXT,                 -- 볼륨 간 이동/보관 시 필수
  state          TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','running','done','failed','skipped')),
  error_code     TEXT,
  actual_dst_path TEXT,
  cross_device   INTEGER NOT NULL DEFAULT 0 CHECK (cross_device IN (0,1)),
  started_at     INTEGER,
  finished_at    INTEGER,
  undo_state     TEXT NOT NULL DEFAULT 'not_applicable' CHECK (undo_state IN ('not_applicable','undoable','undone','undo_failed','not_undoable')),
  undo_error_code TEXT,
  undone_at      INTEGER,
  UNIQUE (plan_id, seq)
) STRICT;
CREATE INDEX ix_plan_ops_plan ON plan_operations(plan_id, state);
CREATE INDEX ix_plan_ops_running ON plan_operations(state) WHERE state = 'running';
CREATE INDEX ix_plan_ops_item ON plan_operations(item_id);

CREATE TABLE approvals (
  id          INTEGER PRIMARY KEY,
  plan_id     INTEGER NOT NULL REFERENCES plans(id),
  plan_hash   TEXT NOT NULL,
  method      TEXT NOT NULL CHECK (method IN ('app_button','cli_tty','native_dialog','test')),
  channel     TEXT NOT NULL CHECK (channel IN ('cli','app','skill','mcp','schedule','test')),
  request_id  TEXT NOT NULL,
  approved_at INTEGER NOT NULL,
  UNIQUE (plan_id)
) STRICT;
```

`review_items.plan_op_id` 는 0002 에서 이미 INTEGER 컬럼으로 존재(FK 제약 없음, 앱 로직으로 보장). 결정: STRICT 테이블 재작성을 피하기 위함.

### 5.5 `0005_ai_memory.sql` (M6)

```sql
CREATE TABLE policy_rules (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  condition_json TEXT NOT NULL CHECK (json_valid(condition_json)), -- 07 문서의 조건 DSL (예 {"category":"installer","installed":true,"origin_root_kind":"downloads"})
  action         TEXT NOT NULL CHECK (action IN ('keep','keep_always','trash','move','archive','acknowledge')),
  dest_template  TEXT,
  state          TEXT NOT NULL CHECK (state IN ('suggested','active','rejected','disabled')),
  source         TEXT NOT NULL CHECK (source IN ('user','learned')),
  evidence_count INTEGER NOT NULL DEFAULT 0,  -- 근거가 된 일치 결정 수
  evidence_json  TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_json)), -- 최근 decision id 목록 (최대 20)
  created_at     INTEGER NOT NULL,
  decided_at     INTEGER,
  last_applied_at INTEGER
) STRICT;
CREATE INDEX ix_policy_rules_state ON policy_rules(state);

CREATE TABLE file_text (
  entry_id     INTEGER PRIMARY KEY REFERENCES file_entries(id),
  source       TEXT NOT NULL CHECK (source IN ('vision_ocr','pdf_text','plain_text')),
  sha256       TEXT NOT NULL,          -- 추출 당시 파일 해시 (무효화)
  text_enc     BLOB NOT NULL,          -- 추출 텍스트 (암호화, 최대 16KB 로 절단)
  lang         TEXT,
  extracted_at INTEGER NOT NULL
) STRICT;

CREATE TABLE ai_requests (
  id            INTEGER PRIMARY KEY,
  ts            INTEGER NOT NULL,
  provider      TEXT NOT NULL CHECK (provider IN ('ollama','anthropic','openai')),
  model         TEXT NOT NULL,
  external      INTEGER NOT NULL CHECK (external IN (0,1)),
  purpose       TEXT NOT NULL,         -- 'classify_group','suggest_dest' 등 07 문서
  item_count    INTEGER NOT NULL,
  blocked_count INTEGER NOT NULL DEFAULT 0, -- 게이트가 제외한 항목 수
  payload_sha256 TEXT NOT NULL,        -- 본문은 저장하지 않음
  status        TEXT NOT NULL CHECK (status IN ('ok','error','timeout','rejected_output')),
  latency_ms    INTEGER,
  request_id    TEXT NOT NULL
) STRICT;
CREATE INDEX ix_ai_requests_ts ON ai_requests(ts);
```

## 6. 민감 필드와 보호

| 컬럼 | 내용 | 보호 |
|---|---|---|
| `decisions.note_enc` | 사용자 메모 | AES-256-GCM |
| `vault_assets.cert_subject_enc` | 인증서 subject (NPKI 는 실명 포함) | AES-256-GCM |
| `vault_assets.user_label_enc`, `user_note_enc` | 사용자 입력 | AES-256-GCM |
| `file_text.text_enc` | OCR/문서 텍스트 (환자 정보·비밀 포함 가능). dataless 파일은 추출하지 않음 | AES-256-GCM |
| `vault_findings.rule_id/line_no` | 위치 정보만 | 평문 허용 (매치 문자열 저장 금지) |
| `file_entries.where_from_host` | 다운로드 출처 호스트 | 평문 허용 (전체 URL·쿼리 저장 금지) |
| 경로 컬럼 전반 | 파일 경로 | 평문 (DB 파일 0600 + FileVault 전제). 로그에는 보안/환자 항목 경로 금지 |

**절대 저장하지 않는 것**: 비밀값·개인키 본문·토큰, 시드/복구 구문(해시 포함), gitleaks `Match`/`Secret`, AI 요청/응답 본문, 썸네일 이미지, 환자 자료 내용.

암호화 형식(`common/crypto.py`):
- 키: 32바이트 랜덤, Keychain `service="com.dayclose.db"`, `account="field-key-v1"`. `core.init` 이 생성.
- 값: `b"\x01" + nonce(12) + ciphertext||tag`. 첫 바이트 = 키 버전.
- AAD: `"<table>.<column>"` UTF-8 (컬럼 간 바꿔치기 방지).
- 테스트: `DAYCLOSE_SANDBOX` 가 설정되면 키 백엔드는 `$DAYCLOSE_HOME/test-field-key`(파일)로 대체. 실제 Keychain 접근 금지.
- 키 분실 시: 암호화 필드만 읽을 수 없고(`null` 로 표시 + 경고 `W_FIELD_KEY_UNAVAILABLE`), 나머지 기능은 동작.
- 키 교체: 새 버전 키 생성 → 전 `*_enc` 재암호화 마이그레이션(별도 명령, M8 이후).

DB 파일 보호: `DAYCLOSE_HOME` 0700, DB·WAL 0600. `core.doctor` 가 권한을 검사. 결정: SQLCipher 전체 암호화는 쓰지 않는다. 이유: 의존성·디버깅 비용 대비, 위협 대부분(외부 모델 전송·로그 유출)은 필드 정책으로 막히고 디스크 도난은 FileVault 가 담당.

## 7. 마이그레이션 전략

- 파일: `core/src/dayclose/store/migrations/NNNN_<name>.sql`. 번호 = `db_schema_version`.
- 적용: 연결 시 `schema_migrations` 와 비교 → 미적용분을 번호순으로 각각 트랜잭션(`BEGIN IMMEDIATE`) 실행 → `schema_migrations` 행 + `PRAGMA user_version=N`.
- 데이터가 있는 DB 에 적용하기 전 SQLite backup API 로 `backups/dayclose-<ts>-pre-v<N>.db` 생성(최근 3개 유지).
- 전진 전용(forward-only). down 마이그레이션 없음. 되돌리기 = 백업 복원(`E_DB_MIGRATION` 메시지에 백업 경로 안내).
- 체크섬 불일치(적용된 파일이 수정됨) → `E_DB_MIGRATION`. 이미 적용된 마이그레이션 파일은 절대 수정하지 않는다.
- DB 버전 > 코드가 아는 최대 버전 → `E_DB_MIGRATION`(“core 가 DB 보다 오래됨”), 읽기·쓰기 모두 거부.
- CHECK 제약 enum 값 추가 = 테이블 재작성(SQLite 공식 12단계 절차: 새 테이블 생성 → 복사 → 삭제 → 이름변경 → 인덱스 재생성, `foreign_keys=OFF` 구간 내 `foreign_key_check`). 결정: enum 을 CHECK 로 두는 대가로 감수. 이유: 잘못된 상태 값이 DB 에 들어가는 것을 원천 차단.
- 마이그레이션 테스트: 각 버전의 픽스처 DB(`core/tests/fixtures/db/v<N>.db`)에서 최신까지 올리는 테스트 필수(11 문서).

## 8. 보존·압축 (용량 예산)

`scan.run` 끝에 하루 1회 실행(`app_meta.last_compaction_date`):

| 대상 | 규칙 |
|---|---|
| `file_events` | `detected_at` 90일 경과 삭제 |
| `file_entries` (`present=0`) | `deleted_run_id` 의 시작 시각 180일 경과 + 열린/계획 중 항목·vault 자산이 참조하지 않으면 삭제 |
| `review_items` 종결 상태 | 180일 경과 시 유지(결정 이력이 학습 근거). 단 `subject_path` 외 세부(suggestion_reason) NULL 처리 |
| `scan_runs` | 365일 경과 + 참조 없음 → 삭제 |
| `audit_log` | 365일 |
| `ai_requests` | 90일 |
| `decisions` | 삭제 안 함(학습·감사 근거, 행당 작음) |

압축 후 `PRAGMA incremental_vacuum`, 주 1회 `PRAGMA optimize`. `auto_vacuum=INCREMENTAL` 은 `store` 가 새 DB 파일을 만든 직후, 첫 마이그레이션 전에 설정한다(테이블이 생긴 뒤에는 바꿀 수 없음).

## 9. 대표 쿼리 (인덱스 근거)

```sql
-- 오늘의 리뷰 그룹별 열린 항목 수 (review.summary)
SELECT g.id, g.group_key, g.title, COUNT(i.id) AS n, SUM(COALESCE(e.size_bytes,0)) AS bytes
FROM review_groups g
JOIN review_items i ON i.group_id = g.id AND i.is_open = 1
LEFT JOIN file_entries e ON e.id = i.entry_id
WHERE g.session_id = :session_id
GROUP BY g.id ORDER BY g.sort_order;

-- 이월 대상 (§4.2)
SELECT id FROM review_items
WHERE is_open = 1 AND state IN ('detected','proposed')
  AND review_date < :d AND (last_carried_date IS NULL OR last_carried_date <> :d);

-- 증분 스캔: 루트별 현재 항목 로드 (dict 로 메모리 비교)
SELECT id, path, dev, inode, size_bytes, mtime_ns FROM file_entries WHERE root_id = :root AND present = 1;

-- 중복 후보
SELECT sha256, COUNT(*) FROM file_entries WHERE present = 1 AND sha256 IS NOT NULL GROUP BY sha256 HAVING COUNT(*) > 1;

-- 만료 임박 인증서
SELECT id FROM vault_assets WHERE status='active' AND cert_not_after < :now_plus_warn;

-- 크래시 복구 대상
SELECT * FROM plan_operations WHERE state = 'running';
```

## 10. 다른 문서와의 경계

- 어떤 변경이 항목이 되는지, 카테고리·그룹 키 판정 → 04.
- vault 탐지·마스킹·발견 사항 판정 → 05.
- `policy_rules.condition_json` DSL, 학습 임계값 → 07.
- `plan_hash` 정규화, 휴지통 경로, recover 판정표 → 08.
- 각 명령의 `data` 가 이 테이블들을 어떻게 투영하는지 → 10.
