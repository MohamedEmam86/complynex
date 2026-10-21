-- Screening quality: per-source update log (freshness / silent failures) and
-- stored results of the recurring screening-quality evaluation.
BEGIN;
CREATE TABLE IF NOT EXISTS screening_list_update_log (
    id          SERIAL PRIMARY KEY,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source      TEXT NOT NULL,
    status      TEXT NOT NULL,              -- ok | failed | skipped
    added       INTEGER DEFAULT 0,
    updated     INTEGER DEFAULT 0,
    unchanged   INTEGER DEFAULT 0,
    delisted    INTEGER DEFAULT 0,
    relisted    INTEGER DEFAULT 0,
    errors      INTEGER DEFAULT 0,
    error       TEXT,
    duration_s  NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_sclu_source_run ON screening_list_update_log (source, run_at DESC);

CREATE TABLE IF NOT EXISTS screening_quality_runs (
    id          SERIAL PRIMARY KEY,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL DEFAULT 'scheduled',
    summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    cases       JSONB NOT NULL DEFAULT '[]'::jsonb,
    duration_s  NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_sqr_run ON screening_quality_runs (run_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON screening_list_update_log, screening_quality_runs TO complynex;
GRANT USAGE, SELECT ON SEQUENCE screening_list_update_log_id_seq, screening_quality_runs_id_seq TO complynex;
COMMIT;
