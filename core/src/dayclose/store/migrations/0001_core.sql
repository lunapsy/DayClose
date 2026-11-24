CREATE TABLE app_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
) STRICT;
-- 키 목록(값은 TEXT): device_id, created_at, contract_version, last_compaction_date, last_devcache_scan_date,
--   last_brew_scan_date, last_login_items_scan_date, last_app_lastused_refresh_date (04 §14a),
--   vault.backlog_entry_ids (JSON 배열, 05 §2.4),
--   host_uuid_sha256 (SHA-256("dayclose.host.v1"+gethostuuid()), 원 UUID 저장 금지, 08 §7.11),
--   approval.app_pubkey_spki_b64, approval.app_pubkey_registered_at (core.app_key, 08 §6.5). 새 키는 이 목록에 먼저 추가.

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
  max_depth   INTEGER,                 -- root.add 가 --max-depth 생략 시 04 의 kind 별 기본값 표로 채움(예 projects 2, DerivedData 1). NULL = 무제한(사용자가 명시했을 때만)
  file_level  INTEGER NOT NULL DEFAULT 1 CHECK (file_level IN (0,1)), -- 0 = 파일 단위 항목 생성 안 함 (projects, DerivedData)
  icloud_synced_mode TEXT NOT NULL DEFAULT 'auto' CHECK (icloud_synced_mode IN ('auto','yes','no')), -- 사용자 지정(root add/set --icloud-synced)
  icloud_synced INTEGER NOT NULL DEFAULT 0 CHECK (icloud_synced IN (0,1)), -- 실효값(02 §10.1 예외 2). yes→1, no→0, auto→04 §1 판정; auto 인데 판정 신호가 없으면 desktop/documents 루트는 1(안전 쪽, 09 §12 V17). scan 마다 재계산. 정책 판단에 쓰는 값은 이 값 OR 양성 실시간 신호(02 §10.1 예외 2, 08 §9.2) — 사용자 'no' 는 양성 신호를 이기지 못함
  icloud_synced_source TEXT NOT NULL DEFAULT 'detected' CHECK (icloud_synced_source IN ('detected','user','assumed')), -- 실효값의 근거
  created_at  INTEGER NOT NULL,
  removed_at  INTEGER
) STRICT;
CREATE UNIQUE INDEX ux_scan_roots_path_active ON scan_roots(path) WHERE removed_at IS NULL;

CREATE TABLE scan_runs (
  id           INTEGER PRIMARY KEY,
  started_at   INTEGER NOT NULL,
  finished_at  INTEGER,
  status       TEXT NOT NULL CHECK (status IN ('running','completed','partial','failed','interrupted')),
  trigger      TEXT NOT NULL CHECK (trigger IN ('manual','app','schedule','agent')),
  collectors_json TEXT NOT NULL CHECK (json_valid(collectors_json)),  -- ["fs","git",...]
  stats_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats_json)),  -- 키: 04 §0 통계 + warning_codes(그 run 의 경고 코드 배열)
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
