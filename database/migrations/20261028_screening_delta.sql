-- Re-screening of existing customers / merchants / parties against names newly
-- added to any list (asset-freeze orders, terrorist lists, sanctions, PEPs).
BEGIN;
CREATE TABLE IF NOT EXISTS screening_delta_runs (
    id            SERIAL PRIMARY KEY,
    run_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_bl_id    BIGINT, to_bl_id BIGINT,
    from_pep_id   BIGINT, to_pep_id BIGINT,
    from_wl_id    BIGINT, to_wl_id BIGINT,
    new_names     INTEGER DEFAULT 0,
    subjects      INTEGER DEFAULT 0,
    hits          INTEGER DEFAULT 0,
    duration_s    NUMERIC,
    note          TEXT
);
CREATE TABLE IF NOT EXISTS screening_delta_hits (
    id             SERIAL PRIMARY KEY,
    run_id         INTEGER REFERENCES screening_delta_runs(id) ON DELETE CASCADE,
    found_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    subject_table  TEXT NOT NULL,
    subject_id     INTEGER NOT NULL,
    subject_name   TEXT,
    list_table     TEXT NOT NULL,
    list_record_id BIGINT NOT NULL,
    listed_name    TEXT,
    list_source    TEXT,
    category       TEXT,
    score          NUMERIC,
    tier           TEXT,
    decision       JSONB,
    status         TEXT NOT NULL DEFAULT 'open',      -- open | true_match | false_positive
    reviewed_by    INTEGER,
    reviewed_at    TIMESTAMPTZ,
    review_note    TEXT,
    UNIQUE (subject_table, subject_id, list_table, list_record_id)
);
CREATE INDEX IF NOT EXISTS idx_sdh_status ON screening_delta_hits (status, found_at DESC);
GRANT SELECT, INSERT, UPDATE, DELETE ON screening_delta_runs, screening_delta_hits TO complynex;
GRANT USAGE, SELECT ON SEQUENCE screening_delta_runs_id_seq, screening_delta_hits_id_seq TO complynex;
COMMIT;
