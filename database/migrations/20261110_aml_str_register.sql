-- =============================================================================
-- One STR register (aml module)
--  * suspicious_activities (SARs) becomes the single register of suspicion
--    cases: each case has a source (TM alert, screening hit, employee report,
--    manual entry, or another module's detection) and links to the alerts and
--    transactions behind it (aml_sar_links, soft-unlinked so the history stays).
--  * Every entry of the old unusual-transactions register is linked to a case
--    (an existing SAR raised on the same TM alert) or gets its own case.
--    Nothing is deleted; aml_unusual_transactions stays and is kept in step.
--  * Append-only activity history for TM alerts (aml_tm_alert_events).
--  * Internal suspicious-activity reports from employees to the MLRO
--    (aml_employee_reports + append-only aml_employee_report_events).
-- Idempotent.
-- =============================================================================
BEGIN;

-- ---------------------------------------------------------------- append-only guard
CREATE OR REPLACE FUNCTION aml_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- employee reports
CREATE TABLE IF NOT EXISTS aml_employee_reports (
    id                   SERIAL PRIMARY KEY,
    reference            VARCHAR(30) UNIQUE,
    reporter_id          INTEGER NOT NULL REFERENCES users(id),
    subject_type         VARCHAR(20) NOT NULL DEFAULT 'customer'
                         CHECK (subject_type IN ('customer', 'merchant', 'other')),
    subject_name         VARCHAR(255) NOT NULL,
    subject_ref          VARCHAR(80),
    customer_id          INTEGER,
    description          TEXT NOT NULL,
    related_transactions TEXT,
    activity_from        DATE,
    activity_to          DATE,
    status               VARCHAR(20) NOT NULL DEFAULT 'NEW'
                         CHECK (status IN ('NEW', 'UNDER_REVIEW', 'CONVERTED', 'CLOSED_NO_ACTION')),
    close_reason         TEXT,
    reviewed_by          INTEGER REFERENCES users(id),
    reviewed_at          TIMESTAMP,
    closed_by            INTEGER REFERENCES users(id),
    closed_at            TIMESTAMP,
    sar_id               INTEGER REFERENCES suspicious_activities(id) ON DELETE SET NULL,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_aml_emp_reports_status ON aml_employee_reports(status);
CREATE INDEX IF NOT EXISTS idx_aml_emp_reports_reporter ON aml_employee_reports(reporter_id);

CREATE TABLE IF NOT EXISTS aml_employee_report_events (
    id          SERIAL PRIMARY KEY,
    report_id   INTEGER NOT NULL REFERENCES aml_employee_reports(id),
    action      VARCHAR(30) NOT NULL,
    from_status VARCHAR(20),
    to_status   VARCHAR(20),
    note        TEXT,
    actor_id    INTEGER REFERENCES users(id),
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_aml_emp_report_events ON aml_employee_report_events(report_id);
DROP TRIGGER IF EXISTS trg_aml_emp_report_events_ro ON aml_employee_report_events;
CREATE TRIGGER trg_aml_emp_report_events_ro BEFORE UPDATE OR DELETE ON aml_employee_report_events
    FOR EACH ROW EXECUTE FUNCTION aml_append_only();

-- ---------------------------------------------------------------- SAR = master register
ALTER TABLE suspicious_activities ADD COLUMN IF NOT EXISTS source VARCHAR(20);
ALTER TABLE suspicious_activities ADD COLUMN IF NOT EXISTS unusual_txn_id INTEGER
    REFERENCES aml_unusual_transactions(id) ON DELETE SET NULL;
ALTER TABLE suspicious_activities ADD COLUMN IF NOT EXISTS employee_report_id INTEGER
    REFERENCES aml_employee_reports(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sar_unusual_txn ON suspicious_activities(unusual_txn_id)
    WHERE unusual_txn_id IS NOT NULL;

UPDATE suspicious_activities s
   SET source = CASE WHEN EXISTS (SELECT 1 FROM tm_alerts a WHERE a.sar_id = s.id) THEN 'tm_alert' ELSE 'manual' END
 WHERE s.source IS NULL;
ALTER TABLE suspicious_activities ALTER COLUMN source SET DEFAULT 'manual';
ALTER TABLE suspicious_activities ALTER COLUMN source SET NOT NULL;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'suspicious_activities_source_check') THEN
        ALTER TABLE suspicious_activities ADD CONSTRAINT suspicious_activities_source_check
            CHECK (source IN ('tm_alert', 'screening', 'employee_report', 'manual', 'system'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS aml_sar_links (
    id            SERIAL PRIMARY KEY,
    sar_id        INTEGER NOT NULL REFERENCES suspicious_activities(id),
    link_type     VARCHAR(20) NOT NULL CHECK (link_type IN ('tm_alert', 'screening_alert', 'transaction')),
    target_id     INTEGER NOT NULL,
    note          TEXT,
    linked_by     INTEGER REFERENCES users(id),
    linked_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    unlinked_by   INTEGER REFERENCES users(id),
    unlinked_at   TIMESTAMP,
    unlink_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_aml_sar_links_active ON aml_sar_links(sar_id, link_type, target_id)
    WHERE unlinked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_aml_sar_links_target ON aml_sar_links(link_type, target_id);

-- 1) an unusual-transaction entry raised on a TM alert that already has a SAR -> link to that SAR
WITH cand AS (
    SELECT DISTINCT ON (a.sar_id) a.sar_id, u.id AS uid
      FROM aml_unusual_transactions u
      JOIN tm_alerts a ON u.source_table = 'tm_alerts' AND a.id = u.source_record_id
      JOIN suspicious_activities s ON s.id = a.sar_id
     WHERE s.unusual_txn_id IS NULL
       AND NOT EXISTS (SELECT 1 FROM suspicious_activities s2 WHERE s2.unusual_txn_id = u.id)
     ORDER BY a.sar_id, u.id)
UPDATE suspicious_activities s SET unusual_txn_id = cand.uid FROM cand WHERE s.id = cand.sar_id;

-- 2) every other unusual-transaction entry -> its own case in the register
INSERT INTO suspicious_activities
    (sar_reference, activity_date, discovery_date, customer_id, customer_name, activity_description,
     amount_involved, currency, reported_by, report_date, investigation_status, investigation_notes,
     decision, decision_by, decision_date, decision_rationale, sar_filed, sar_filing_date, emlcu_reference,
     created_at, updated_at, source, unusual_txn_id)
SELECT 'SAR-' || to_char(u.detected_at, 'YYYYMM') || '-U' || lpad(u.id::text, 5, '0'),
       to_char(u.detected_at, 'YYYY-MM-DD'), to_char(u.detected_at, 'YYYY-MM-DD'),
       a.customer_id, u.subject_name,
       COALESCE(NULLIF(u.description, ''), u.detection_rule) ||
           CASE WHEN u.reference IS NOT NULL THEN E'\n[' || u.reference || ']' ELSE '' END,
       u.amount, 'EGP', u.created_by, to_char(u.detected_at, 'YYYY-MM-DD'),
       CASE u.status WHEN 'candidate' THEN 'NEW' WHEN 'under_study' THEN 'UNDER_INVESTIGATION'
                     WHEN 'str_filed' THEN 'FILED' ELSE 'NO_STR' END,
       u.analysis,
       CASE WHEN u.decision = 'str' THEN 'FILE_SAR'
            WHEN u.decision = 'no_str' OR u.status IN ('no_str', 'dismissed') THEN 'NO_STR' END,
       u.decision_by, to_char(u.decision_at, 'YYYY-MM-DD'),
       CASE WHEN u.status IN ('str_filed', 'no_str', 'dismissed') THEN u.analysis END,
       CASE WHEN u.status = 'str_filed' THEN 1 ELSE 0 END,
       CASE WHEN u.status = 'str_filed' THEN to_char(u.decision_at, 'YYYY-MM-DD') END,
       u.str_reference,
       to_char(u.detected_at, 'YYYY-MM-DD HH24:MI:SS'), to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
       CASE WHEN u.source_table = 'tm_alerts' THEN 'tm_alert'
            WHEN u.source_table IN ('aml_alerts', 'screening_results') THEN 'screening'
            WHEN u.source_table = 'aml_employee_reports' THEN 'employee_report'
            ELSE 'system' END,
       u.id
  FROM aml_unusual_transactions u
  LEFT JOIN tm_alerts a ON u.source_table = 'tm_alerts' AND a.id = u.source_record_id
 WHERE NOT EXISTS (SELECT 1 FROM suspicious_activities s WHERE s.unusual_txn_id = u.id);

-- 3) links from the existing loose references
INSERT INTO aml_sar_links (sar_id, link_type, target_id, note)
SELECT DISTINCT a.sar_id, 'tm_alert', a.id, 'migrated'
  FROM tm_alerts a JOIN suspicious_activities s ON s.id = a.sar_id
 WHERE NOT EXISTS (SELECT 1 FROM aml_sar_links l WHERE l.sar_id = a.sar_id AND l.link_type = 'tm_alert'
                     AND l.target_id = a.id AND l.unlinked_at IS NULL);
INSERT INTO aml_sar_links (sar_id, link_type, target_id, note)
SELECT DISTINCT s.id, 'tm_alert', u.source_record_id, 'migrated'
  FROM suspicious_activities s JOIN aml_unusual_transactions u ON u.id = s.unusual_txn_id
 WHERE u.source_table = 'tm_alerts' AND EXISTS (SELECT 1 FROM tm_alerts a WHERE a.id = u.source_record_id)
   AND NOT EXISTS (SELECT 1 FROM aml_sar_links l WHERE l.sar_id = s.id AND l.link_type = 'tm_alert'
                     AND l.target_id = u.source_record_id AND l.unlinked_at IS NULL);
INSERT INTO aml_sar_links (sar_id, link_type, target_id, note)
SELECT DISTINCT t.sar_id, 'transaction', t.id, 'migrated'
  FROM transactions t JOIN suspicious_activities s ON s.id = t.sar_id
 WHERE NOT EXISTS (SELECT 1 FROM aml_sar_links l WHERE l.sar_id = t.sar_id AND l.link_type = 'transaction'
                     AND l.target_id = t.id AND l.unlinked_at IS NULL);
INSERT INTO aml_sar_links (sar_id, link_type, target_id, note)
SELECT DISTINCT s.id, 'transaction', x.v::int, 'migrated'
  FROM suspicious_activities s, LATERAL json_array_elements_text(s.transaction_ids::json) AS x(v)
 WHERE s.transaction_ids ~ '^\s*\[[0-9,\s]*\]\s*$'
   AND EXISTS (SELECT 1 FROM transactions t WHERE t.id = x.v::int)
   AND NOT EXISTS (SELECT 1 FROM aml_sar_links l WHERE l.sar_id = s.id AND l.link_type = 'transaction'
                     AND l.target_id = x.v::int AND l.unlinked_at IS NULL);

-- ---------------------------------------------------------------- TM alerts
ALTER TABLE tm_alerts ADD COLUMN IF NOT EXISTS risk_score INTEGER;
UPDATE tm_alerts SET risk_score = CASE upper(COALESCE(alert_severity, ''))
        WHEN 'CRITICAL' THEN 95 WHEN 'HIGH' THEN 80 WHEN 'MEDIUM' THEN 50 WHEN 'LOW' THEN 20 ELSE 0 END
 WHERE risk_score IS NULL;

CREATE TABLE IF NOT EXISTS aml_tm_alert_events (
    id          SERIAL PRIMARY KEY,
    alert_id    INTEGER NOT NULL REFERENCES tm_alerts(id),
    action      VARCHAR(30) NOT NULL,
    from_status VARCHAR(30),
    to_status   VARCHAR(30),
    assigned_to INTEGER REFERENCES users(id),
    note        TEXT,
    actor_id    INTEGER REFERENCES users(id),
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_aml_tm_alert_events ON aml_tm_alert_events(alert_id);
DROP TRIGGER IF EXISTS trg_aml_tm_alert_events_ro ON aml_tm_alert_events;
CREATE TRIGGER trg_aml_tm_alert_events_ro BEFORE UPDATE OR DELETE ON aml_tm_alert_events
    FOR EACH ROW EXECUTE FUNCTION aml_append_only();

-- Arabic rule names (shown on Arabic pages; editable data, filled for the default rule library)
ALTER TABLE tm_rules ADD COLUMN IF NOT EXISTS rule_name_ar TEXT;
UPDATE tm_rules r SET rule_name_ar = m.ar
  FROM (VALUES ('Large Cash Transaction', 'معاملة نقدية كبيرة'),
               ('Structuring / Smurfing', 'تجزئة المعاملات'),
               ('High Velocity', 'تكرار مرتفع للمعاملات'),
               ('High Risk Country', 'دولة عالية المخاطر'),
               ('PEP Counterparty', 'طرف مقابل من الأشخاص ذوي المخاطر السياسية'),
               ('Dormant Account Activity', 'نشاط على حساب خامل'),
               ('Rapid Round Trip', 'دوران سريع للأموال'),
               ('Unusual Transaction Volume', 'حجم معاملات غير معتاد'),
               ('Multiple Currencies', 'تعدد العملات'),
               ('Frequent International Transfers', 'تحويلات دولية متكررة'),
               ('Card Used at Multiple POS Locations', 'استخدام البطاقة في نقاط بيع متعددة'),
               ('Large POS Payment', 'مدفوعات كبيرة عبر نقاط البيع'),
               ('Large Merchant Settlement', 'تسوية كبيرة لتاجر'),
               ('High Refund Velocity', 'تكرار مرتفع لعمليات الاسترداد'),
               ('Round Number POS Structuring', 'تجزئة بمبالغ صحيحة عبر نقاط البيع'),
               ('Rapid Successive Card Payments', 'مدفوعات بطاقة متتالية سريعة')) AS m(en, ar)
 WHERE r.rule_name = m.en AND r.rule_name_ar IS NULL;

GRANT SELECT, INSERT, UPDATE ON aml_employee_reports TO complynex;
GRANT SELECT, INSERT ON aml_employee_report_events TO complynex;
GRANT SELECT, INSERT, UPDATE ON aml_sar_links TO complynex;
GRANT SELECT, INSERT ON aml_tm_alert_events TO complynex;
GRANT USAGE, SELECT ON aml_employee_reports_id_seq, aml_employee_report_events_id_seq,
                       aml_sar_links_id_seq, aml_tm_alert_events_id_seq TO complynex;

COMMIT;
