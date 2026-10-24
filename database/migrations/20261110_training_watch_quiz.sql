-- Training: server-side watch time (heartbeats), completion threshold,
-- quiz attempt limit and course language.
BEGIN;
ALTER TABLE training_courses ADD COLUMN IF NOT EXISTS language VARCHAR(5);            -- en / ar / NULL = both
ALTER TABLE training_courses ADD COLUMN IF NOT EXISTS video_duration_seconds INTEGER;
ALTER TABLE training_courses ADD COLUMN IF NOT EXISTS completion_threshold_pct INTEGER;  -- NULL = 90
ALTER TABLE training_courses ADD COLUMN IF NOT EXISTS max_quiz_attempts INTEGER;        -- NULL = 3

ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS watched_seconds INTEGER NOT NULL DEFAULT 0;
ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMP;
ALTER TABLE training_enrollments ADD COLUMN IF NOT EXISTS extra_quiz_attempts INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS training_quiz_attempts (
    id            SERIAL PRIMARY KEY,
    enrollment_id INTEGER NOT NULL,
    employee_id   INTEGER NOT NULL,
    course_id     INTEGER NOT NULL,
    attempt_no    INTEGER NOT NULL,
    score         INTEGER,
    passed        BOOLEAN NOT NULL DEFAULT FALSE,
    language      VARCHAR(5),
    submitted_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address    VARCHAR(64),
    UNIQUE (enrollment_id, attempt_no)
);
CREATE INDEX IF NOT EXISTS idx_tqa_enrollment ON training_quiz_attempts(enrollment_id);

-- Extra attempts granted by a training administrator (who / when / why).
CREATE TABLE IF NOT EXISTS training_attempt_grants (
    id            SERIAL PRIMARY KEY,
    enrollment_id INTEGER NOT NULL,
    granted_by    INTEGER NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 1,
    reason        TEXT NOT NULL,
    granted_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON training_courses, training_enrollments, training_quiz_attempts,
      training_attempt_grants TO complynex;
GRANT USAGE, SELECT ON SEQUENCE training_quiz_attempts_id_seq, training_attempt_grants_id_seq TO complynex;
COMMIT;
