-- Phase 8 TM review fixes (B1, should-fix 2, B2):
-- * every rule row gets an explicit status: legacy rows with status NULL take it from is_active;
-- * legacy_baseline marks the rule versions created before four-eyes versioning (Phase 7):
--   they carry no approval, yet may be re-enabled / rolled back to, while any other version
--   needs a recorded approval first. "Before Phase 7" is read from the data: version 1, no
--   previous version, no approval, no change reason (Phase 7 always records one) and no pack;
-- * the status CHECK constraint accepts REJECTED (reject() failed before);
-- * tm_monitoring_issues keeps what live monitoring could not fully judge, one row per issue,
--   detail and day with an occurrence count.
-- Indexes on large tables are in 20261105_p8tm_tx_date_indexes.sql (CONCURRENTLY).
BEGIN;
SET LOCAL lock_timeout = '10s';

ALTER TABLE tm_rules ADD COLUMN IF NOT EXISTS legacy_baseline BOOLEAN NOT NULL DEFAULT FALSE;

-- REJECTED was never allowed by the original CHECK constraint: drop every CHECK on tm_rules
-- that constrains status, whatever its name, and add the full one.
DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'tm_rules'::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) ILIKE '%status%'
  LOOP
    EXECUTE format('ALTER TABLE tm_rules DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
ALTER TABLE tm_rules ADD CONSTRAINT tm_rules_status_check
    CHECK (status IS NULL OR status IN ('PENDING', 'ACTIVE', 'DISABLED', 'REJECTED'));

UPDATE tm_rules SET status = CASE WHEN is_active = 1 THEN 'ACTIVE' ELSE 'DISABLED' END
 WHERE status IS NULL;

UPDATE tm_rules SET legacy_baseline = TRUE
 WHERE NOT legacy_baseline AND approved_at IS NULL AND previous_id IS NULL AND COALESCE(version, 1) = 1
   AND change_reason IS NULL AND pack_code IS NULL AND status IN ('ACTIVE', 'DISABLED');

CREATE TABLE IF NOT EXISTS tm_monitoring_issues (
    id                  SERIAL PRIMARY KEY,
    transaction_id      INTEGER,                -- first transaction of the day with this issue
    issue               TEXT NOT NULL,          -- date_unreadable | amount_unusable | currency_unconverted
    detail              TEXT,
    occurrences         INTEGER NOT NULL DEFAULT 1,
    last_transaction_id INTEGER,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    last_at             TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_tm_monitoring_issues_at ON tm_monitoring_issues (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_tm_monitoring_issues_key ON tm_monitoring_issues (issue, detail, created_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON tm_monitoring_issues TO complynex;
GRANT USAGE, SELECT ON SEQUENCE tm_monitoring_issues_id_seq TO complynex;

COMMIT;
