-- Board & committee meetings: minutes workflow with versions, resolution votes,
-- tracked action items, external (non-user) committee members and their attendance.
BEGIN;

-- Minutes: one row per version. draft -> circulated -> approved (by chair or secretary).
-- A new draft after circulation/approval supersedes the earlier version (kept read-only).
CREATE TABLE IF NOT EXISTS meeting_minutes (
    id              SERIAL PRIMARY KEY,
    meeting_id      INTEGER NOT NULL REFERENCES board_meetings(id) ON DELETE CASCADE,
    version_no      INTEGER NOT NULL,
    body            TEXT NOT NULL,
    change_note     TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'circulated', 'approved', 'superseded')),
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP,
    circulated_by   INTEGER REFERENCES users(id),
    circulated_at   TIMESTAMP,
    approved_by     INTEGER REFERENCES users(id),
    approved_at     TIMESTAMP,
    approver_capacity VARCHAR(20) CHECK (approver_capacity IN ('chair', 'secretary')),
    UNIQUE (meeting_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_meeting_minutes_meeting ON meeting_minutes(meeting_id);

-- Status history of a meeting's minutes, resolutions and actions (who / when / why).
CREATE TABLE IF NOT EXISTS meeting_events (
    id          SERIAL PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES board_meetings(id) ON DELETE CASCADE,
    subject     VARCHAR(20) NOT NULL,          -- minutes / resolution / action / attendee / meeting
    subject_id  INTEGER,
    event       VARCHAR(40) NOT NULL,
    from_status VARCHAR(30),
    to_status   VARCHAR(30),
    note        TEXT,
    user_id     INTEGER REFERENCES users(id),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_meeting_events_meeting ON meeting_events(meeting_id);

-- Resolutions use board_decisions (votes for/against/abstain and dissent already exist).
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS vote_result VARCHAR(20);   -- passed / rejected / deferred
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS dissent_notes TEXT;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS recorded_by INTEGER;
ALTER TABLE board_decisions ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMP;

-- Action items: owner (user or free-text), tracking and carry-forward to a later meeting.
ALTER TABLE meeting_action_items ADD COLUMN IF NOT EXISTS owner_user_id INTEGER;
ALTER TABLE meeting_action_items ADD COLUMN IF NOT EXISTS resolution_id INTEGER;
ALTER TABLE meeting_action_items ADD COLUMN IF NOT EXISTS carried_to_meeting_id INTEGER;
ALTER TABLE meeting_action_items ADD COLUMN IF NOT EXISTS created_by INTEGER;
ALTER TABLE meeting_action_items ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE meeting_action_items ADD COLUMN IF NOT EXISTS updated_by INTEGER;
ALTER TABLE meeting_action_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- External committee members / invitees who are not system users.
CREATE TABLE IF NOT EXISTS meeting_external_attendees (
    id                SERIAL PRIMARY KEY,
    meeting_id        INTEGER NOT NULL REFERENCES board_meetings(id) ON DELETE CASCADE,
    full_name         VARCHAR(200) NOT NULL,
    email             VARCHAR(200),
    role              VARCHAR(200),
    organisation      VARCHAR(200),
    attendance_status VARCHAR(30) NOT NULL DEFAULT 'INVITED',
    attendance_notes  TEXT,
    invited_by        INTEGER REFERENCES users(id),
    invited_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    recorded_by       INTEGER REFERENCES users(id),
    recorded_at       TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_meeting_ext_meeting ON meeting_external_attendees(meeting_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON meeting_minutes, meeting_events, meeting_external_attendees,
      board_decisions, meeting_action_items TO complynex;
GRANT USAGE, SELECT ON SEQUENCE meeting_minutes_id_seq, meeting_events_id_seq, meeting_external_attendees_id_seq TO complynex;
COMMIT;
