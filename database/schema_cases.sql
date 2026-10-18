-- ============================================================================
-- TABLE 1: Case SLA Config (admin-editable — data, not code)
-- ============================================================================

CREATE TABLE case_sla_config (
    case_type VARCHAR(30) PRIMARY KEY,
    sla_days INTEGER NOT NULL,
    description TEXT
);

INSERT INTO case_sla_config (case_type, sla_days, description) VALUES
('TM_ALERT', 5, 'Transaction monitoring alerts should be triaged within 5 business days.'),
('WHISTLEBLOWING', 10, 'Whistleblowing reports should receive an initial review within 10 days.'),
('CONSUMER_COMPLAINT', 15, 'Statutory 15-day deadline — consumer_complaints.statutory_deadline_date is used directly instead of this when present.'),
('CYBER_INCIDENT', 1, 'Cyber incidents require same/next-day triage. The separate CBE 6-24h notification clock (cyber_incidents.cbe_notification_deadline) is unaffected by this.');


-- ============================================================================
-- TABLE 2: Unified Cases (read-through index over 7 investigation shapes —
-- currently synced from the 4 with live, centralized write paths:
-- tm_alerts, whistleblowing_cases, consumer_complaints, cyber_incidents.
-- aml_alerts and edd_cases have no live writers (schema shape only, no rows
-- being produced today); screening_queue has 5 scattered insert sites and
-- was intentionally left out of this first pass rather than risking a
-- refactor of working screening code to centralize them.
-- ============================================================================
-- Source rows remain authoritative for full case detail and workflow — this
-- table is an index/rollup for cross-module visibility and SLA tracking,
-- not a replacement for the source tables.

CREATE TABLE cases (
    id SERIAL PRIMARY KEY,

    case_type VARCHAR(30) NOT NULL REFERENCES case_sla_config(case_type),
    source_table VARCHAR(60) NOT NULL,
    source_record_id INTEGER NOT NULL,
    reference VARCHAR(60),          -- the source row's own human reference (alert_reference, case_number, ...)

    title TEXT,
    status VARCHAR(30) NOT NULL,    -- normalized: OPEN, IN_PROGRESS, RESOLVED, CLOSED
    priority VARCHAR(20),           -- normalized: LOW, MEDIUM, HIGH, CRITICAL

    party_id INTEGER REFERENCES parties(id),
    assigned_to INTEGER REFERENCES users(id),

    opened_at TIMESTAMP NOT NULL DEFAULT NOW(),
    due_date TIMESTAMP,
    resolved_at TIMESTAMP,
    last_synced_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(source_table, source_record_id)
);

CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_type ON cases(case_type);
CREATE INDEX idx_cases_party ON cases(party_id);
CREATE INDEX idx_cases_assigned ON cases(assigned_to);
CREATE INDEX idx_cases_due ON cases(due_date);
