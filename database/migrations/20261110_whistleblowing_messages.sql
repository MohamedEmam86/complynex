-- Whistleblowing: two-way messaging with the (anonymous) reporter.
BEGIN;
CREATE TABLE IF NOT EXISTS whistleblowing_messages (
    id              SERIAL PRIMARY KEY,
    case_id         INTEGER NOT NULL,
    sender          TEXT NOT NULL CHECK (sender IN ('REPORTER', 'STAFF')),
    body            TEXT NOT NULL,
    staff_user_id   INTEGER,          -- internal only; never shown to the reporter
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    read_by_staff_at TIMESTAMP,
    read_by_staff   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_wb_messages_case ON whistleblowing_messages (case_id, created_at);
GRANT SELECT, INSERT, UPDATE ON whistleblowing_messages TO complynex;
GRANT USAGE, SELECT ON SEQUENCE whistleblowing_messages_id_seq TO complynex;
COMMIT;
