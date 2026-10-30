-- Phase 2 (P2-1, P2-7): numbered list versions with an update guard and rollback,
-- list alerts, and the per-list settings (guard limits, allowed age).
CREATE TABLE IF NOT EXISTS screening_list_versions (
    id               SERIAL PRIMARY KEY,
    source           TEXT NOT NULL,
    version_no       INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('RUNNING','APPLIED','BLOCKED','FAILED','ROLLED_BACK','RESTORED')),
    trigger          TEXT,                      -- scheduled / manual / import / rollback / baseline
    triggered_by     INTEGER,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    file_sha256      TEXT,
    hash_kind        TEXT,                      -- file (raw download) / content (parsed list, streamed feeds)
    fetched_count    INTEGER,
    active_before    INTEGER,
    active_after     INTEGER,
    added            INTEGER DEFAULT 0,
    updated          INTEGER DEFAULT 0,
    unchanged        INTEGER DEFAULT 0,
    delisted         INTEGER DEFAULT 0,
    relisted         INTEGER DEFAULT 0,
    reason           TEXT,
    guard            JSONB,
    snapshot         BYTEA,                     -- gzip of the sorted active source_ids (last 10 per list kept)
    snapshot_count   INTEGER,
    approved_by      INTEGER,
    approved_at      TIMESTAMPTZ,
    approval_reason  TEXT,
    approval_used_by INTEGER,
    rolled_back_by   INTEGER,
    rolled_back_at   TIMESTAMPTZ,
    rollback_reason  TEXT,
    restored_from    INTEGER REFERENCES screening_list_versions(id),
    UNIQUE (source, version_no)
);
-- the parsed-list fingerprint: approvals are matched on it (a re-download often has another file hash)
ALTER TABLE screening_list_versions ADD COLUMN IF NOT EXISTS content_sha256 TEXT;
CREATE INDEX IF NOT EXISTS idx_slv_source_status ON screening_list_versions (source, status, version_no DESC);
CREATE INDEX IF NOT EXISTS idx_slv_finished ON screening_list_versions (finished_at);

CREATE TABLE IF NOT EXISTS screening_list_alerts (
    id          SERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,                  -- blocked / failed / overdue
    title       TEXT,
    recipients  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sla_source_kind ON screening_list_alerts (source, kind, created_at DESC);

INSERT INTO screening_config (config_key, config_value, category, description, updated_at)
SELECT 'list_update_guard', '{"default": {"max_drop_pct": 10, "max_delist_pct": 10, "min_abs": 25}}', 'lists',
       'List update guard: block an update when the record count falls, or deactivations exceed, these limits', CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM screening_config WHERE config_key = 'list_update_guard');
INSERT INTO screening_config (config_key, config_value, category, description, updated_at)
SELECT 'list_four_eyes', 'true', 'lists',
       'A blocked list update must be approved by an MLRO other than the one who started it (false = off)', CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM screening_config WHERE config_key = 'list_four_eyes');
INSERT INTO screening_config (config_key, config_value, category, description, updated_at)
SELECT 'list_max_age_hours', '{"default": 48, "pma_ps": 1080}', 'lists',
       'Allowed age of each list (hours) before it is shown red and the MLRO is alerted', CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM screening_config WHERE config_key = 'list_max_age_hours');

GRANT SELECT, INSERT, UPDATE ON screening_list_versions, screening_list_alerts TO complynex;
GRANT USAGE, SELECT ON SEQUENCE screening_list_versions_id_seq, screening_list_alerts_id_seq TO complynex;
