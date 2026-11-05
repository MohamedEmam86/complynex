-- Phase 8 TM review fixes (B1, should-fix 2, B2):
-- * every rule row gets an explicit status: legacy rows with status NULL take it from is_active;
-- * legacy_baseline marks the rule versions that were in force before four-eyes versioning
--   (Phase 7) and so carry no approval: they may be re-enabled / rolled back to, while any other
--   version needs a recorded approval first;
-- * the status CHECK constraint accepts REJECTED (reject() failed before);
-- * tm_monitoring_issues keeps what live monitoring could not judge (unreadable date, other currency).
BEGIN;

ALTER TABLE tm_rules ADD COLUMN IF NOT EXISTS legacy_baseline BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE tm_rules SET legacy_baseline = TRUE
 WHERE NOT legacy_baseline AND approved_at IS NULL AND previous_id IS NULL AND COALESCE(version, 1) = 1
   AND is_active = 1 AND COALESCE(status, 'ACTIVE') = 'ACTIVE';

UPDATE tm_rules SET status = CASE WHEN is_active = 1 THEN 'ACTIVE' ELSE 'DISABLED' END
 WHERE status IS NULL;

-- REJECTED was never allowed by the original CHECK constraint, so rejecting a pending version
-- failed with a constraint violation (tm_versions.reject, /aml/tm-rules/<id>/reject).
ALTER TABLE tm_rules DROP CONSTRAINT IF EXISTS tm_rules_status_check;
ALTER TABLE tm_rules ADD CONSTRAINT tm_rules_status_check
    CHECK (status IS NULL OR status IN ('PENDING', 'ACTIVE', 'DISABLED', 'REJECTED'));

CREATE INDEX IF NOT EXISTS ix_tm_alerts_customer_code ON tm_alerts (customer_id, rule_code);

CREATE TABLE IF NOT EXISTS tm_monitoring_issues (
    id              SERIAL PRIMARY KEY,
    transaction_id  INTEGER,
    issue           TEXT NOT NULL,          -- date_unreadable | currency_excluded | amount_unusable
    detail          TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_tm_monitoring_issues_at ON tm_monitoring_issues (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_tm_monitoring_issues_tx ON tm_monitoring_issues (transaction_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON tm_monitoring_issues TO complynex;
GRANT USAGE, SELECT ON SEQUENCE tm_monitoring_issues_id_seq TO complynex;

COMMIT;
