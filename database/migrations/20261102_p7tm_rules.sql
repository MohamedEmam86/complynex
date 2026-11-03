-- Phase 7 transaction monitoring (TM-G2 / G3 / G4): rule parameters with units and references,
-- the reason for every version, the version on every alert, and the evidence of backtests.
BEGIN;

ALTER TABLE tm_rules ADD COLUMN IF NOT EXISTS parameters JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE tm_rules ADD COLUMN IF NOT EXISTS threshold_unit TEXT;
ALTER TABLE tm_rules ADD COLUMN IF NOT EXISTS reference TEXT;
ALTER TABLE tm_rules ADD COLUMN IF NOT EXISTS change_reason TEXT;
ALTER TABLE tm_rules ADD COLUMN IF NOT EXISTS pack_code TEXT;
CREATE INDEX IF NOT EXISTS ix_tm_rules_code_status ON tm_rules (rule_code, status);

ALTER TABLE tm_alerts ADD COLUMN IF NOT EXISTS rule_code TEXT;
ALTER TABLE tm_alerts ADD COLUMN IF NOT EXISTS rule_version INTEGER;
-- existing alerts: the version row they point at
UPDATE tm_alerts a SET rule_code = r.rule_code, rule_version = COALESCE(r.version, 1)
  FROM tm_rules r WHERE r.id = a.rule_id AND a.rule_code IS NULL;

CREATE TABLE IF NOT EXISTS tm_backtest_runs (
    id          SERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,              -- backtest_all | compare | sweep
    rule_id     INTEGER,
    rule_code   TEXT,
    rule_version INTEGER,
    parameters  JSONB,
    date_from   DATE,
    date_to     DATE,
    result      JSONB,
    run_by      INTEGER,
    run_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_tm_backtest_runs_rule ON tm_backtest_runs (rule_code, run_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON tm_backtest_runs TO complynex;
GRANT USAGE, SELECT ON SEQUENCE tm_backtest_runs_id_seq TO complynex;

COMMIT;
