-- =============================================================================
-- Inspection readiness: score snapshots (trend), regulatory-calendar reminders
-- Generic core (regcontrols). Idempotent; GRANTs at the end.
-- =============================================================================
BEGIN;

-- One row per day x scope: overall (area_code NULL, framework_id NULL), per area, per framework.
CREATE TABLE IF NOT EXISTS rc_readiness_snapshots (
    id             SERIAL PRIMARY KEY,
    snapshot_date  DATE NOT NULL,
    framework_id   INTEGER REFERENCES rc_frameworks(id) ON DELETE CASCADE,
    area_code      VARCHAR(40),
    score          NUMERIC(5,1),
    controls       INTEGER NOT NULL DEFAULT 0,
    failing        INTEGER NOT NULL DEFAULT 0,
    open_findings  INTEGER NOT NULL DEFAULT 0,
    details        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rc_readiness_snapshot
    ON rc_readiness_snapshots (snapshot_date, COALESCE(framework_id, 0), COALESCE(area_code, ''));

-- Calendar reminders already sent (item key x days-before), so each goes out once.
CREATE TABLE IF NOT EXISTS rc_calendar_reminders (
    item_key    VARCHAR(120) NOT NULL,
    days_before INTEGER NOT NULL,
    sent_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (item_key, days_before)
);

INSERT INTO rc_parameters (param_key, value_text, value_type, unit, legal_reference, description_en, description_ar, approved_at)
SELECT 'rc.calendar_reminder_days', '[14, 3, 0]', 'json', 'days', 'Internal compliance policy',
       'Days before a regulatory deadline when owners and the Head of Compliance are reminded',
       'عدد الأيام قبل الموعد الرقابي التي يُذكَّر فيها المسؤولون ورئيس الالتزام', CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM rc_parameters WHERE param_key = 'rc.calendar_reminder_days');

GRANT SELECT, INSERT, UPDATE, DELETE ON rc_readiness_snapshots, rc_calendar_reminders TO complynex;
GRANT USAGE, SELECT ON rc_readiness_snapshots_id_seq TO complynex;

COMMIT;
