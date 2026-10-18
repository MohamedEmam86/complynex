-- =============================================================================
-- regcontrols — generic compliance control framework (core)
--
-- Regulators, frameworks, requirements, controls, tests (check bindings and
-- manual test results), evidence, findings & corrective actions, alerts,
-- regulatory parameters and optional content packs. Everything regulator- or
-- sector-specific is DATA, installed by a pack (packs/<code>/) or entered in
-- the UI — nothing here is tied to one regulator, sector or company.
-- Idempotent: safe to run more than once. DDL runs as postgres; GRANTs at end.
-- =============================================================================
BEGIN;

-- ---------------------------------------------------------------- permissions
ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_regcontrols VARCHAR(10) DEFAULT 'none';

-- Generic store for module permissions declared by packs (none/view/edit/admin),
-- so core tables never need a column per optional module.
CREATE TABLE IF NOT EXISTS user_module_permissions (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module      VARCHAR(60) NOT NULL,
    level       VARCHAR(10) NOT NULL DEFAULT 'none' CHECK (level IN ('none', 'view', 'edit', 'admin')),
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, module)
);

-- ---------------------------------------------------------------- packs
CREATE TABLE IF NOT EXISTS rc_packs (
    code               VARCHAR(40) PRIMARY KEY,
    enabled            BOOLEAN NOT NULL DEFAULT FALSE,
    installed_version  VARCHAR(20),
    installed_at       TIMESTAMP,
    deactivated_controls INTEGER[] NOT NULL DEFAULT '{}',  -- controls switched off by the last disable
    updated_by         INTEGER REFERENCES users(id),
    updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------- reference data
-- Reuse the existing regulators table (Regulatory Reports module).
ALTER TABLE regulators ADD COLUMN IF NOT EXISTS name_ar VARCHAR(200);
ALTER TABLE regulators ADD COLUMN IF NOT EXISTS jurisdiction VARCHAR(10);

CREATE TABLE IF NOT EXISTS rc_licence_types (
    code          VARCHAR(40) PRIMARY KEY,
    name_en       VARCHAR(200) NOT NULL,
    name_ar       VARCHAR(200),
    regulator_id  INTEGER REFERENCES regulators(id) ON DELETE SET NULL,
    jurisdiction  VARCHAR(10),
    pack_code     VARCHAR(40),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO rc_licence_types (code, name_en, name_ar) VALUES ('all', 'All licence types', 'جميع أنواع التراخيص')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS rc_areas (
    code        VARCHAR(40) PRIMARY KEY,
    name_en     VARCHAR(200) NOT NULL,
    name_ar     VARCHAR(200),
    sort_order  INTEGER NOT NULL DEFAULT 100,
    pack_code   VARCHAR(40)
);

CREATE TABLE IF NOT EXISTS rc_owner_roles (
    code       VARCHAR(40) PRIMARY KEY,
    name_en    VARCHAR(200) NOT NULL,
    name_ar    VARCHAR(200),
    pack_code  VARCHAR(40)
);
INSERT INTO rc_owner_roles (code, name_en, name_ar) VALUES
    ('compliance_head', 'Head of Compliance', 'رئيس إدارة الالتزام'),
    ('risk_head', 'Head of Risk', 'رئيس إدارة المخاطر'),
    ('cfo', 'Chief Financial Officer', 'المدير المالي'),
    ('it_head', 'Head of IT', 'رئيس تكنولوجيا المعلومات'),
    ('ciso', 'Information Security Officer', 'مسؤول أمن المعلومات'),
    ('internal_audit_head', 'Head of Internal Audit', 'رئيس المراجعة الداخلية'),
    ('operations_head', 'Head of Operations', 'رئيس العمليات'),
    ('hr_head', 'Head of HR', 'رئيس الموارد البشرية'),
    ('board_secretary', 'Board Secretary', 'أمين سر مجلس الإدارة')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------- frameworks & requirements
CREATE TABLE IF NOT EXISTS rc_frameworks (
    id               SERIAL PRIMARY KEY,
    code             VARCHAR(40) NOT NULL UNIQUE,
    name_en          VARCHAR(300) NOT NULL,
    name_ar          VARCHAR(300),
    regulator_id     INTEGER REFERENCES regulators(id) ON DELETE SET NULL,
    jurisdiction     VARCHAR(10),
    version          VARCHAR(40),
    description      TEXT,
    source_document  TEXT,
    pack_code        VARCHAR(40),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rc_requirements (
    id               SERIAL PRIMARY KEY,
    framework_id     INTEGER NOT NULL REFERENCES rc_frameworks(id) ON DELETE CASCADE,
    ref_code         VARCHAR(40) NOT NULL,
    title_en         VARCHAR(400) NOT NULL,
    title_ar         VARCHAR(400),
    text_en          TEXT,
    text_ar          TEXT,
    legal_reference  TEXT,
    area_code        VARCHAR(40),
    sort_order       INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT rc_requirements_ref_uniq UNIQUE (framework_id, ref_code)
);

-- ---------------------------------------------------------------- parameters
CREATE TABLE IF NOT EXISTS rc_parameters (
    id              SERIAL PRIMARY KEY,
    param_key       VARCHAR(120) NOT NULL,
    licence_type    VARCHAR(40)  NOT NULL DEFAULT 'all',
    value_text      TEXT,
    value_type      VARCHAR(20)  NOT NULL DEFAULT 'number'
                    CHECK (value_type IN ('number', 'integer', 'amount', 'percent', 'boolean', 'text', 'json', 'date')),
    unit            VARCHAR(30),
    effective_from  DATE NOT NULL DEFAULT DATE '2020-01-01',
    effective_to    DATE,
    framework_id    INTEGER REFERENCES rc_frameworks(id) ON DELETE SET NULL,
    legal_reference TEXT,
    description_en  TEXT,
    description_ar  TEXT,
    needs_review    BOOLEAN NOT NULL DEFAULT FALSE,
    review_note     TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    pack_code       VARCHAR(40),
    created_by      INTEGER REFERENCES users(id),
    approved_by     INTEGER REFERENCES users(id),
    approved_at     TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT rc_parameters_version_uniq UNIQUE (param_key, licence_type, effective_from),
    CONSTRAINT rc_parameters_dates_chk CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX IF NOT EXISTS idx_rc_parameters_key ON rc_parameters(param_key);

-- Maker-checker change log. A change is applied to rc_parameters only when a
-- second user approves it; the row stays as the audit trail either way.
CREATE TABLE IF NOT EXISTS rc_parameter_changes (
    id                 SERIAL PRIMARY KEY,
    parameter_id       INTEGER REFERENCES rc_parameters(id) ON DELETE SET NULL,
    param_key          VARCHAR(120) NOT NULL,
    licence_type       VARCHAR(40)  NOT NULL DEFAULT 'all',
    change_type        VARCHAR(20)  NOT NULL CHECK (change_type IN ('create', 'update', 'new_version', 'retire', 'review')),
    old_value          TEXT,
    new_value          TEXT,
    value_type         VARCHAR(20),
    unit               VARCHAR(30),
    effective_from     DATE,
    effective_to       DATE,
    legal_reference    TEXT,
    description_en     TEXT,
    description_ar     TEXT,
    needs_review       BOOLEAN,
    review_note        TEXT,
    reason             TEXT NOT NULL,
    status             VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_by       INTEGER REFERENCES users(id),
    requested_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_by         INTEGER REFERENCES users(id),
    decided_at         TIMESTAMP,
    decision_comment   TEXT,
    applied_parameter_id INTEGER REFERENCES rc_parameters(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rc_param_changes_key ON rc_parameter_changes(param_key);
CREATE INDEX IF NOT EXISTS idx_rc_param_changes_status ON rc_parameter_changes(status);

-- ---------------------------------------------------------------- controls
-- Control library. Separate from risk_management's `controls` (an ERM
-- key-control register); erm_control_id links the two when the same control
-- is tracked in both places. A control satisfies one or more requirements
-- (possibly of different frameworks) through rc_control_requirements, and is
-- tested automatically when check_key names a registered check.
CREATE TABLE IF NOT EXISTS rc_controls (
    id                 SERIAL PRIMARY KEY,
    control_code       VARCHAR(40) NOT NULL UNIQUE,
    area               VARCHAR(40),
    title_en           VARCHAR(300) NOT NULL,
    title_ar           VARCHAR(300),
    requirement_en     TEXT,
    requirement_ar     TEXT,
    control_type       VARCHAR(20) NOT NULL CHECK (control_type IN ('automated', 'evidence', 'workflow', 'metric')),
    type_codes         VARCHAR(10),
    frequency          VARCHAR(20) NOT NULL DEFAULT 'monthly'
                       CHECK (frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'semi_annual', 'annual', 'event', 'on_demand')),
    criticality        VARCHAR(10) NOT NULL DEFAULT 'high' CHECK (criticality IN ('critical', 'high', 'medium', 'low')),
    owner_role         VARCHAR(40),
    owner_user_id      INTEGER REFERENCES users(id),
    linked_module      VARCHAR(40),
    linked_params      TEXT[] NOT NULL DEFAULT '{}',
    licence_types      TEXT[] NOT NULL DEFAULT '{all}',
    check_key          VARCHAR(120),
    test_procedure_en  TEXT,
    test_procedure_ar  TEXT,
    erm_control_id     INTEGER REFERENCES controls(id) ON DELETE SET NULL,
    auto_create_case   BOOLEAN NOT NULL DEFAULT FALSE,
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    pack_code          VARCHAR(40),
    last_run_id        INTEGER,
    last_run_at        TIMESTAMP,
    last_status        VARCHAR(20),
    next_run_due       TIMESTAMP,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rc_controls_area ON rc_controls(area);
CREATE INDEX IF NOT EXISTS idx_rc_controls_status ON rc_controls(last_status);
CREATE INDEX IF NOT EXISTS idx_rc_controls_pack ON rc_controls(pack_code);

CREATE TABLE IF NOT EXISTS rc_control_requirements (
    control_id      INTEGER NOT NULL REFERENCES rc_controls(id) ON DELETE CASCADE,
    requirement_id  INTEGER NOT NULL REFERENCES rc_requirements(id) ON DELETE CASCADE,
    PRIMARY KEY (control_id, requirement_id)
);
CREATE INDEX IF NOT EXISTS idx_rc_control_reqs_req ON rc_control_requirements(requirement_id);

-- ---------------------------------------------------------------- test runs
-- Every automated check run and every manual test result.
CREATE TABLE IF NOT EXISTS rc_control_runs (
    id               SERIAL PRIMARY KEY,
    control_id       INTEGER NOT NULL REFERENCES rc_controls(id) ON DELETE CASCADE,
    org_unit_id      INTEGER,
    status           VARCHAR(20) NOT NULL
                     CHECK (status IN ('pass', 'warning', 'fail', 'error', 'no_check', 'not_applicable')),
    summary          TEXT,
    details          JSONB NOT NULL DEFAULT '{}'::jsonb,
    affected_count   INTEGER NOT NULL DEFAULT 0,
    affected_records JSONB NOT NULL DEFAULT '[]'::jsonb,
    check_name       VARCHAR(200),
    triggered_by     VARCHAR(20) NOT NULL DEFAULT 'schedule'
                     CHECK (triggered_by IN ('schedule', 'manual', 'verification', 'api', 'event', 'manual_test')),
    run_by           INTEGER REFERENCES users(id),
    finding_id       INTEGER,
    started_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at      TIMESTAMP,
    duration_ms      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_rc_runs_control ON rc_control_runs(control_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_rc_runs_status ON rc_control_runs(status);

-- ---------------------------------------------------------------- evidence
-- Files live in generic_attachments (module 'regcontrols', record_type
-- 'rc_evidence', record_id = rc_evidence.id).
CREATE TABLE IF NOT EXISTS rc_evidence (
    id              SERIAL PRIMARY KEY,
    control_id      INTEGER NOT NULL REFERENCES rc_controls(id) ON DELETE CASCADE,
    org_unit_id     INTEGER,
    title           VARCHAR(300) NOT NULL,
    description     TEXT,
    reference_no    VARCHAR(120),
    valid_from      DATE,
    valid_to        DATE,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    source          VARCHAR(20) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'api', 'system')),
    source_module   VARCHAR(40),
    submitted_by    INTEGER REFERENCES users(id),
    submitted_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_by     INTEGER REFERENCES users(id),
    reviewed_at     TIMESTAMP,
    review_comment  TEXT,
    CONSTRAINT rc_evidence_dates_chk CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);
CREATE INDEX IF NOT EXISTS idx_rc_evidence_control ON rc_evidence(control_id);
CREATE INDEX IF NOT EXISTS idx_rc_evidence_valid_to ON rc_evidence(valid_to);

-- ---------------------------------------------------------------- findings
CREATE TABLE IF NOT EXISTS rc_findings (
    id               SERIAL PRIMARY KEY,
    reference        VARCHAR(30) UNIQUE,
    source           VARCHAR(30) NOT NULL DEFAULT 'regulator'
                     CHECK (source IN ('regulator', 'internal_audit', 'self_identified', 'external_audit', 'control_failure')),
    source_ref       VARCHAR(200),
    regulator_id     INTEGER REFERENCES regulators(id) ON DELETE SET NULL,
    framework_id     INTEGER REFERENCES rc_frameworks(id) ON DELETE SET NULL,
    title            VARCHAR(400) NOT NULL,
    description      TEXT,
    severity         VARCHAR(10) NOT NULL DEFAULT 'medium' CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    area             VARCHAR(40),
    org_unit_id      INTEGER,
    owner_user_id    INTEGER REFERENCES users(id),
    identified_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date         DATE,
    status           VARCHAR(30) NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open', 'action_plan', 'in_progress', 'pending_verification', 'closed', 'reopened')),
    closure_type     VARCHAR(20) CHECK (closure_type IN ('remediated', 'not_applicable', 'risk_accepted')),
    is_repeated      BOOLEAN NOT NULL DEFAULT FALSE,
    repeat_count     INTEGER NOT NULL DEFAULT 0,
    last_repeat_at   TIMESTAMP,
    verified_at      TIMESTAMP,
    verified_by      INTEGER REFERENCES users(id),
    verification_note TEXT,
    closed_at        TIMESTAMP,
    closed_by        INTEGER REFERENCES users(id),
    created_by       INTEGER REFERENCES users(id),
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rc_findings_status ON rc_findings(status);
CREATE INDEX IF NOT EXISTS idx_rc_findings_due ON rc_findings(due_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rc_findings_source_ref
    ON rc_findings(source, source_ref) WHERE source_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS rc_finding_controls (
    finding_id  INTEGER NOT NULL REFERENCES rc_findings(id) ON DELETE CASCADE,
    control_id  INTEGER NOT NULL REFERENCES rc_controls(id) ON DELETE CASCADE,
    PRIMARY KEY (finding_id, control_id)
);
CREATE INDEX IF NOT EXISTS idx_rc_finding_controls_control ON rc_finding_controls(control_id);

-- Corrective action plan. Evidence files: generic_attachments
-- (module 'regcontrols', record_type 'rc_action').
CREATE TABLE IF NOT EXISTS rc_corrective_actions (
    id             SERIAL PRIMARY KEY,
    finding_id     INTEGER NOT NULL REFERENCES rc_findings(id) ON DELETE CASCADE,
    description    TEXT NOT NULL,
    owner_user_id  INTEGER REFERENCES users(id),
    due_date       DATE,
    status         VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done', 'cancelled')),
    completion_note TEXT,
    completed_at   TIMESTAMP,
    completed_by   INTEGER REFERENCES users(id),
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rc_actions_finding ON rc_corrective_actions(finding_id);

CREATE TABLE IF NOT EXISTS rc_finding_events (
    id          SERIAL PRIMARY KEY,
    finding_id  INTEGER NOT NULL REFERENCES rc_findings(id) ON DELETE CASCADE,
    event_type  VARCHAR(40) NOT NULL,
    note        TEXT,
    run_id      INTEGER REFERENCES rc_control_runs(id) ON DELETE SET NULL,
    user_id     INTEGER REFERENCES users(id),
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rc_finding_events_finding ON rc_finding_events(finding_id, created_at);

-- ---------------------------------------------------------------- alerts
CREATE TABLE IF NOT EXISTS rc_alerts (
    id               SERIAL PRIMARY KEY,
    alert_type       VARCHAR(30) NOT NULL
                     CHECK (alert_type IN ('control_failed', 'evidence_expiring', 'evidence_expired',
                                           'finding_overdue', 'repeated_violation')),
    severity         VARCHAR(10) NOT NULL DEFAULT 'high' CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    control_id       INTEGER REFERENCES rc_controls(id) ON DELETE CASCADE,
    evidence_id      INTEGER REFERENCES rc_evidence(id) ON DELETE CASCADE,
    finding_id       INTEGER REFERENCES rc_findings(id) ON DELETE CASCADE,
    run_id           INTEGER REFERENCES rc_control_runs(id) ON DELETE SET NULL,
    org_unit_id      INTEGER,
    title            VARCHAR(300) NOT NULL,
    message          TEXT,
    status           VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved')),
    owner_user_id    INTEGER REFERENCES users(id),
    raised_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_notified_at TIMESTAMP,
    notify_count     INTEGER NOT NULL DEFAULT 0,
    escalated_at     TIMESTAMP,
    escalated_to     INTEGER[],
    case_id          INTEGER,
    acknowledged_by  INTEGER REFERENCES users(id),
    acknowledged_at  TIMESTAMP,
    resolved_at      TIMESTAMP,
    resolution_note  TEXT
);
CREATE INDEX IF NOT EXISTS idx_rc_alerts_status ON rc_alerts(status);
-- At most one live alert per subject; a new failure refreshes the existing one.
CREATE UNIQUE INDEX IF NOT EXISTS idx_rc_alerts_live_uniq
    ON rc_alerts(alert_type, COALESCE(control_id, 0), COALESCE(evidence_id, 0), COALESCE(finding_id, 0))
    WHERE status IN ('open', 'acknowledged');

-- Unified case list: a failed control can be worked as a case
-- (see models/case.py::_sync_reg_control).
INSERT INTO case_sla_config (case_type, sla_days, description)
VALUES ('REG_CONTROL', 10, 'Failed compliance control (regcontrols)')
ON CONFLICT (case_type) DO NOTHING;

-- ---------------------------------------------------------------- engine parameters
-- Internal-policy settings of the engine itself (not regulatory numbers).
-- Regulatory parameters arrive with a pack or are added in the UI.
WITH ins AS (
    INSERT INTO rc_parameters (param_key, value_text, value_type, unit, legal_reference, description_en, description_ar,
                               approved_at)
    VALUES
      ('rc.escalation_days', '5', 'integer', 'days', 'Internal compliance policy',
       'Days an alert may stay open before it is escalated to the Head of Compliance',
       'عدد الأيام التي يظل فيها التنبيه مفتوحًا قبل تصعيده لرئيس إدارة الالتزام', CURRENT_TIMESTAMP),
      ('rc.evidence_expiry_warning_days', '30', 'integer', 'days', 'Internal compliance policy',
       'Days before evidence expiry when the owner is warned',
       'عدد الأيام قبل انتهاء صلاحية الدليل التي يتم فيها تنبيه المسؤول', CURRENT_TIMESTAMP),
      ('rc.finding_overdue_grace_days', '0', 'integer', 'days', 'Internal compliance policy',
       'Days after a finding due date before it is reported as overdue',
       'عدد الأيام بعد تاريخ استحقاق الملاحظة قبل اعتبارها متأخرة', CURRENT_TIMESTAMP),
      ('rc.alert_renotify_days', '3', 'integer', 'days', 'Internal compliance policy',
       'Days between repeat reminders for an open alert',
       'عدد الأيام بين التذكيرات المتكررة لتنبيه مفتوح', CURRENT_TIMESTAMP),
      ('rc.auto_case_on_failure', 'false', 'boolean', NULL, 'Internal compliance policy',
       'Automatically open a case in the unified case list when a critical control fails',
       'فتح حالة تلقائيًا في قائمة الحالات الموحدة عند فشل ضابط حرج', CURRENT_TIMESTAMP)
    ON CONFLICT (param_key, licence_type, effective_from) DO NOTHING
    RETURNING id, param_key, licence_type, value_text, value_type, unit, effective_from
)
INSERT INTO rc_parameter_changes (parameter_id, param_key, licence_type, change_type, new_value, value_type, unit,
                                  effective_from, reason, status, decided_at, applied_parameter_id)
SELECT id, param_key, licence_type, 'create', value_text, value_type, unit, effective_from,
       'Engine default', 'approved', CURRENT_TIMESTAMP, id FROM ins;

-- ---------------------------------------------------------------- grants
GRANT SELECT, INSERT, UPDATE, DELETE ON
    user_module_permissions, rc_packs, rc_licence_types, rc_areas, rc_owner_roles, rc_frameworks, rc_requirements,
    rc_parameters, rc_parameter_changes, rc_controls, rc_control_requirements, rc_control_runs, rc_evidence,
    rc_findings, rc_finding_controls, rc_corrective_actions, rc_finding_events, rc_alerts
    TO complynex;
GRANT USAGE, SELECT ON
    rc_frameworks_id_seq, rc_requirements_id_seq, rc_parameters_id_seq, rc_parameter_changes_id_seq,
    rc_controls_id_seq, rc_control_runs_id_seq, rc_evidence_id_seq, rc_findings_id_seq,
    rc_corrective_actions_id_seq, rc_finding_events_id_seq, rc_alerts_id_seq
    TO complynex;

COMMIT;
