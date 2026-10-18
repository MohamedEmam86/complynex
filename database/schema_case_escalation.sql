-- ============================================================================
-- Case Escalation Settings (single-row config)
-- ============================================================================
-- SLA escalation (scripts/sync_cases.py::escalate_overdue_cases) only fires
-- for cases opened on or after `cutover_at`. Without this, backfilled
-- historical cases (which can be months old against a freshly-applied SLA
-- clock) would all read as instantly overdue and fire one large burst of
-- notifications the first time escalation runs — not a useful signal, just
-- noise from retroactively applying a live clock to historical data.
-- `cutover_at` defaults to the moment this migration runs (go-live for
-- escalation), so only genuinely new cases get escalated.

CREATE TABLE case_escalation_settings (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    cutover_at TIMESTAMP NOT NULL DEFAULT NOW()
);

INSERT INTO case_escalation_settings (id) VALUES (1);
