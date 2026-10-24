-- Data protection: DSR intake, ROPA/PDPL record fields, consent register history,
-- breach notification record, breach status history and owner.
BEGIN;
ALTER TABLE data_subject_requests ADD COLUMN IF NOT EXISTS received_date DATE;

ALTER TABLE data_processing_activities ADD COLUMN IF NOT EXISTS dpo_review_date DATE;
ALTER TABLE data_processing_activities ADD COLUMN IF NOT EXISTS updated_by INTEGER;

CREATE TABLE IF NOT EXISTS data_processing_activity_history (
    id          SERIAL PRIMARY KEY,
    activity_id INTEGER NOT NULL,
    changed_by  INTEGER,
    changed_at  TIMESTAMP NOT NULL DEFAULT now(),
    changes     TEXT
);
CREATE INDEX IF NOT EXISTS idx_dpa_history_activity ON data_processing_activity_history (activity_id);

ALTER TABLE consents ADD COLUMN IF NOT EXISTS evidence_ref TEXT;
ALTER TABLE consents ADD COLUMN IF NOT EXISTS recorded_by INTEGER;
ALTER TABLE consents ADD COLUMN IF NOT EXISTS withdrawal_recorded_by INTEGER;
CREATE TABLE IF NOT EXISTS consent_events (
    id          SERIAL PRIMARY KEY,
    consent_id  INTEGER NOT NULL,
    event_type  TEXT NOT NULL,       -- GIVEN / WITHDRAWN
    event_date  DATE,
    channel     TEXT,
    reason      TEXT,
    evidence_ref TEXT,
    created_by  INTEGER,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_consent_events_consent ON consent_events (consent_id);

ALTER TABLE data_breaches ADD COLUMN IF NOT EXISTS notification_notes TEXT;
ALTER TABLE data_breaches ADD COLUMN IF NOT EXISTS owner_user_id INTEGER;
ALTER TABLE data_breaches ADD COLUMN IF NOT EXISTS notification_recorded_by INTEGER;
CREATE TABLE IF NOT EXISTS data_breach_updates (
    id          SERIAL PRIMARY KEY,
    breach_id   INTEGER NOT NULL,
    old_status  TEXT,
    new_status  TEXT,
    note        TEXT,
    created_by  INTEGER,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_data_breach_updates_b ON data_breach_updates (breach_id);

GRANT SELECT, INSERT, UPDATE ON data_processing_activity_history, consent_events, data_breach_updates TO complynex;
GRANT SELECT, INSERT, UPDATE ON consents, consent_purposes TO complynex;
GRANT USAGE, SELECT ON SEQUENCE data_processing_activity_history_id_seq, consent_events_id_seq,
      data_breach_updates_id_seq TO complynex;
COMMIT;
