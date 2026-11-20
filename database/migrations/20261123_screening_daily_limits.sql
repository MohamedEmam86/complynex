-- Daily screening limits per user (screening/limits.py).
--  * users.screening_daily_limit: per-user override (NULL = the default setting, 0 = unlimited).
--  * system setting screening.daily_limit_default: 0 = unlimited (inserted only if missing) -> nothing changes for
--    existing users until an administrator sets a limit.
--  * screening_daily_usage: screenings per user, day (Africa/Cairo) and kind (name / vessel / dualuse).
--  * screening_limit_events: every reset / change of a limit (audit trail; also written to audit_logs).
-- Idempotent; additive only.
BEGIN;
SET lock_timeout = '5s';

ALTER TABLE users ADD COLUMN IF NOT EXISTS screening_daily_limit INTEGER;

CREATE TABLE IF NOT EXISTS screening_daily_usage (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day         DATE NOT NULL,
    kind        VARCHAR(12) NOT NULL DEFAULT 'name',
    n           INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, day, kind)
);
CREATE INDEX IF NOT EXISTS idx_screening_daily_usage_day ON screening_daily_usage (day);

CREATE TABLE IF NOT EXISTS screening_limit_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,      -- NULL: the default setting
    actor_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    day         DATE NOT NULL,
    action      VARCHAR(20) NOT NULL,            -- reset | limit_set | default_set
    old_value   TEXT,
    new_value   TEXT,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_screening_limit_events_user ON screening_limit_events (user_id, created_at DESC);

-- bulk jobs: how many of a job's rows were already counted (a resumed job is never counted twice)
CREATE TABLE IF NOT EXISTS screening_job_counts (
    job_key     VARCHAR(80) PRIMARY KEY,         -- '<kind>:<job id>'
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    counted     INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO system_settings (setting_key, setting_value, description)
SELECT 'screening.daily_limit_default', '0', 'Default daily screenings per user (0 = unlimited)'
 WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE setting_key = 'screening.daily_limit_default');

GRANT SELECT, INSERT, UPDATE, DELETE ON screening_daily_usage, screening_limit_events, screening_job_counts TO complynex;
GRANT USAGE, SELECT ON SEQUENCE screening_limit_events_id_seq TO complynex;

COMMIT;
