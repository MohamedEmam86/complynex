-- =============================================================================
-- Screening: four-eyes on sanctions clearance + whitelist governance
--
-- 1. clearance_approval_threshold (screening_config): clearing a hit at or
--    above this score, or any hit from a sanctions list, needs a second person
--    with approval authority (MLRO) before it takes effect.
-- 2. screening_clearance_requests: one row per clearance waiting for / given
--    a second decision (maker = requested_by, checker = decided_by).
-- 3. screening_hit_decisions: who did what on a hit, when and why.
-- 4. screening_whitelist governance: reason, review date (default +12 months,
--    max 24), creator, MLRO approval before an entry suppresses anything.
--    Existing entries keep working: review date = created + 12 months, active
--    entries are recorded as approved on a "legacy" basis.
-- =============================================================================
BEGIN;

INSERT INTO screening_config (config_key, config_value, category, description, updated_at)
VALUES ('clearance_approval_threshold', '85', 'governance',
        'Clearing a hit with a score at or above this value (or any hit from a sanctions list) needs MLRO approval (four-eyes)',
        CURRENT_TIMESTAMP)
ON CONFLICT (config_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS screening_clearance_requests (
    id                SERIAL PRIMARY KEY,
    target_type       TEXT NOT NULL CHECK (target_type IN ('queue', 'result')),
    target_id         INTEGER NOT NULL,
    entity_name       TEXT,
    match_name        TEXT,
    match_score       DOUBLE PRECISION,
    list_source       TEXT,
    is_sanctions      BOOLEAN NOT NULL DEFAULT FALSE,
    proposed_decision TEXT NOT NULL,
    reason            TEXT NOT NULL,
    previous_status   TEXT,
    requested_by      INTEGER REFERENCES users(id),
    requested_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_by        INTEGER REFERENCES users(id),
    decided_at        TIMESTAMP,
    decision_comment  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_scr_clearance_pending
    ON screening_clearance_requests (target_type, target_id) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_scr_clearance_status
    ON screening_clearance_requests (status, requested_at DESC);

CREATE TABLE IF NOT EXISTS screening_hit_decisions (
    id          SERIAL PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    action      TEXT NOT NULL,
    decision    TEXT,
    reason      TEXT,
    actor_id    INTEGER REFERENCES users(id),
    request_id  INTEGER REFERENCES screening_clearance_requests(id),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scr_hit_decisions_target
    ON screening_hit_decisions (target_type, target_id, created_at);

ALTER TABLE screening_whitelist ADD COLUMN IF NOT EXISTS approval_basis   TEXT;
ALTER TABLE screening_whitelist ADD COLUMN IF NOT EXISTS approval_comment TEXT;
ALTER TABLE screening_whitelist ADD COLUMN IF NOT EXISTS requested_by     INTEGER;
ALTER TABLE screening_whitelist ADD COLUMN IF NOT EXISTS requested_at     TIMESTAMP;
ALTER TABLE screening_whitelist ADD COLUMN IF NOT EXISTS request_reason   TEXT;
ALTER TABLE screening_whitelist ADD COLUMN IF NOT EXISTS rejected_by      INTEGER;
ALTER TABLE screening_whitelist ADD COLUMN IF NOT EXISTS rejected_at      TIMESTAMP;

-- review date: ISO YYYY-MM-DD so it compares as text; created + 12 months
UPDATE screening_whitelist
   SET review_date = substr(review_date, 1, 10)
 WHERE review_date ~ '^\d{4}-\d{2}-\d{2}' AND length(review_date) > 10;
UPDATE screening_whitelist
   SET review_date = to_char(
         (CASE WHEN added_at ~ '^\d{4}-\d{2}-\d{2}' THEN substr(added_at, 1, 10)::date
               ELSE CURRENT_DATE END) + INTERVAL '12 months', 'YYYY-MM-DD')
 WHERE review_date IS NULL OR review_date !~ '^\d{4}-\d{2}-\d{2}$';

-- existing active entries: approved on a legacy basis, nothing stops working
UPDATE screening_whitelist
   SET status = 'Active'
 WHERE status IS NULL OR status = '';
UPDATE screening_whitelist
   SET approval_basis = 'legacy'
 WHERE approval_basis IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON screening_clearance_requests, screening_hit_decisions TO complynex;
GRANT USAGE, SELECT ON SEQUENCE screening_clearance_requests_id_seq, screening_hit_decisions_id_seq TO complynex;
COMMIT;
