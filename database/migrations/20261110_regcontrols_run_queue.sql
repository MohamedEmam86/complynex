-- Regulatory controls: database-backed run queue. "Queue run" and the
-- scheduled sweep add rows here; scripts/regcontrols_process_queue.py (timer)
-- or an administrator's "Process queue now" runs them. Replaces handing runs
-- to the shared RQ 'events' queue, which the demo instance has no worker for.
BEGIN;
CREATE TABLE IF NOT EXISTS rc_run_queue (
    id            SERIAL PRIMARY KEY,
    kind          VARCHAR(10) NOT NULL DEFAULT 'control' CHECK (kind IN ('control', 'due')),
    control_id    INTEGER REFERENCES rc_controls(id) ON DELETE CASCADE,
    status        VARCHAR(10) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    requested_by  INTEGER REFERENCES users(id),
    requested_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at    TIMESTAMP,
    finished_at   TIMESTAMP,
    processed_by  INTEGER REFERENCES users(id),
    run_id        INTEGER,
    result        TEXT,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_rc_run_queue_status ON rc_run_queue(status, requested_at);
GRANT SELECT, INSERT, UPDATE, DELETE ON rc_run_queue TO complynex;
GRANT USAGE, SELECT ON SEQUENCE rc_run_queue_id_seq TO complynex;
COMMIT;
