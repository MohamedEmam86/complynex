-- Vessel screening, round 3 (owner feedback):
--  * vessel_profile.regimes: generic regime codes of a listed ship (Russia-related, Iran-related, ...),
--    screening/vessel_regimes.py; filled by scripts/vessels_sync.py --sync from the stored rows.
--  * users.perm_vessels_db: the ComplyNex Vessels Database is a separate permission (default none; the
--    superadmin always has it). Access and exports are audited.
--  * vessel_update_runs / vessel_change_log: every refresh of the vessel tables, with the ships added,
--    removed and changed since the previous refresh (update-status page).
--  * vessel_news_cache: adverse-media results per ship (cached, refreshed after a TTL).
-- Idempotent; additive only.
BEGIN;
SET lock_timeout = '5s';

ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS regimes TEXT;            -- JSON list of regime codes

ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_vessels_db VARCHAR(10) DEFAULT 'none';   -- none | view

CREATE TABLE IF NOT EXISTS vessel_update_runs (
    id           BIGSERIAL PRIMARY KEY,
    source       VARCHAR(60),                         -- NULL = all lists
    trigger      VARCHAR(20) NOT NULL DEFAULT 'list_update',   -- list_update | manual | sync | import
    user_id      INTEGER,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       VARCHAR(12) NOT NULL DEFAULT 'running',       -- running | done | failed
    vessels      INTEGER,
    added        INTEGER NOT NULL DEFAULT 0,
    removed      INTEGER NOT NULL DEFAULT 0,
    changed      INTEGER NOT NULL DEFAULT 0,
    by_class     TEXT,                                -- JSON {SANCTION: n, BAN: n, ...}
    message      TEXT
);
CREATE INDEX IF NOT EXISTS idx_vessel_update_runs_at ON vessel_update_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS vessel_change_log (
    id            BIGSERIAL PRIMARY KEY,
    run_id        BIGINT,
    source        VARCHAR(60),
    change        VARCHAR(10) NOT NULL CHECK (change IN ('added', 'removed', 'changed')),
    watchlist_id  INTEGER,
    group_key     VARCHAR(40),
    imo           VARCHAR(10),
    name          TEXT,
    provenance    VARCHAR(10),
    detail        TEXT,                               -- JSON: the fields that changed {field: [before, after]}
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vessel_change_log_run ON vessel_change_log (run_id);
CREATE INDEX IF NOT EXISTS idx_vessel_change_log_at ON vessel_change_log (created_at DESC);

CREATE TABLE IF NOT EXISTS vessel_news_cache (
    cache_key   VARCHAR(80) PRIMARY KEY,              -- IMO:<n> or NAME:<normalised name>
    payload     JSONB NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON vessel_update_runs, vessel_change_log, vessel_news_cache TO complynex;
GRANT USAGE, SELECT ON SEQUENCE vessel_update_runs_id_seq, vessel_change_log_id_seq TO complynex;
COMMIT;
