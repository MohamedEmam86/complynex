-- P5-5: monthly screening drift reports (one row per month). Idempotent; no own transaction.
CREATE TABLE IF NOT EXISTS screening_drift_reports (
    id          SERIAL PRIMARY KEY,
    month       DATE NOT NULL UNIQUE,
    metrics     JSONB NOT NULL,
    alerts      JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON screening_drift_reports TO complynex;
GRANT USAGE, SELECT ON SEQUENCE screening_drift_reports_id_seq TO complynex;
