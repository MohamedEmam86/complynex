-- P4-9 bulk screening: jobs and rows live in the database (any web worker shows
-- progress, a restart loses nothing, every row ends DONE / FAILED / SKIPPED).
CREATE TABLE IF NOT EXISTS screening_bulk_jobs (
    id            TEXT PRIMARY KEY,
    created_by    INTEGER,
    started_by    INTEGER,
    filename      TEXT,
    headers       JSONB,
    column_map    JSONB,
    default_type  TEXT DEFAULT 'INDIVIDUAL',
    status        TEXT NOT NULL DEFAULT 'MAPPING',   -- MAPPING READY RUNNING PAUSED DONE DONE_WITH_GAP CANCELLED
    total_rows    INTEGER NOT NULL DEFAULT 0,
    summary       JSONB,
    error         TEXT,
    worker_pid    INTEGER,
    heartbeat     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sbj_created ON screening_bulk_jobs (created_at DESC);

CREATE TABLE IF NOT EXISTS screening_bulk_rows (
    job_id              TEXT NOT NULL REFERENCES screening_bulk_jobs(id) ON DELETE CASCADE,
    row_no              INTEGER NOT NULL,
    raw                 JSONB,
    name                TEXT,
    entity_type         TEXT,
    dob                 TEXT,
    nationality         TEXT,
    national_id         TEXT,
    customer_ref        TEXT,
    input_warnings      JSONB,
    status              TEXT NOT NULL DEFAULT 'NEW',  -- NEW PENDING RUNNING DONE FAILED SKIPPED
    attempts            INTEGER NOT NULL DEFAULT 0,
    result_status       TEXT,
    highest_score       DOUBLE PRECISION,
    match_count         INTEGER,
    screening_result_id INTEGER,
    error               TEXT,
    finished_at         TIMESTAMPTZ,
    PRIMARY KEY (job_id, row_no)
);
CREATE INDEX IF NOT EXISTS idx_sbr_job_status ON screening_bulk_rows (job_id, status);

GRANT SELECT, INSERT, UPDATE, DELETE ON screening_bulk_jobs, screening_bulk_rows TO complynex;
