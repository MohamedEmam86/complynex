-- =============================================================================
-- AML & KYC assurance (core, regulator-neutral)
--
-- Key AML roles & independence, role-conflict rules, annual MLRO report with
-- board approval, policy board approvals, AML monitoring programme, screening
-- QA harness, employee screening, KYC field rules / supplementary profile /
-- beneficial owners / declarations, configurable risk model, onboarding gate
-- with EDD, internal-audit coverage of the control library.
-- Plus rc_controls.check_config so one check can serve several frameworks
-- with different settings.
-- Idempotent. Requires 20261018_regcontrols.sql and 20261019_aml_unusual_register.sql.
-- =============================================================================
BEGIN;

-- ---------------------------------------------------------------- engine
ALTER TABLE rc_controls ADD COLUMN IF NOT EXISTS check_config JSONB NOT NULL DEFAULT '{}'::jsonb;

-- ---------------------------------------------------------------- governance
CREATE TABLE IF NOT EXISTS aml_key_roles (
    id                        SERIAL PRIMARY KEY,
    role_code                 VARCHAR(40) NOT NULL,          -- e.g. mlro, deputy_mlro
    title                     VARCHAR(200),
    holder_user_id            INTEGER REFERENCES users(id) ON DELETE SET NULL,
    holder_name               VARCHAR(200),
    reports_to_title          VARCHAR(200),
    reports_to_user_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reports_to_board          BOOLEAN NOT NULL DEFAULT FALSE,  -- direct line to the board / its committee
    other_positions           TEXT,                            -- other roles held, incl. at group companies
    combined_role_approval_ref VARCHAR(120),                   -- regulator approval for combined roles
    combined_role_approved_on DATE,
    appointed_on              DATE,
    regulator_notified_on     DATE,
    regulator_ref             VARCHAR(120),
    org_unit_id               INTEGER,
    is_active                 BOOLEAN NOT NULL DEFAULT TRUE,
    notes                     TEXT,
    updated_by                INTEGER REFERENCES users(id),
    updated_at                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Positions a role must not hold or report to (data, editable).
CREATE TABLE IF NOT EXISTS aml_role_conflict_rules (
    id           SERIAL PRIMARY KEY,
    role_code    VARCHAR(40) NOT NULL,
    rule_type    VARCHAR(20) NOT NULL CHECK (rule_type IN ('holds', 'reports_to')),
    keyword      VARCHAR(120) NOT NULL,          -- matched case-insensitively in titles / positions
    reason_en    TEXT,
    reason_ar    TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT aml_role_conflict_uniq UNIQUE (role_code, rule_type, keyword)
);
INSERT INTO aml_role_conflict_rules (role_code, rule_type, keyword, reason_en, reason_ar) VALUES
  ('mlro', 'reports_to', 'risk', 'The MLRO must be independent of risk management', 'يجب أن يكون مسؤول الإبلاغ مستقلًا عن إدارة المخاطر'),
  ('mlro', 'reports_to', 'business', 'The MLRO must not report to business lines', 'لا يجوز أن يتبع مسؤول الإبلاغ خطوط الأعمال'),
  ('mlro', 'reports_to', 'sales', 'The MLRO must not report to sales', 'لا يجوز أن يتبع مسؤول الإبلاغ إدارة المبيعات'),
  ('mlro', 'reports_to', 'operations', 'The MLRO must not report to operations', 'لا يجوز أن يتبع مسؤول الإبلاغ إدارة العمليات'),
  ('mlro', 'holds', 'internal control', 'Internal-control duties conflict with the MLRO role', 'تتعارض مهام الرقابة الداخلية مع دور مسؤول الإبلاغ'),
  ('mlro', 'holds', 'internal audit', 'Internal-audit duties conflict with the MLRO role', 'تتعارض مهام المراجعة الداخلية مع دور مسؤول الإبلاغ'),
  ('mlro', 'holds', 'risk', 'Risk-management duties conflict with the MLRO role', 'تتعارض مهام إدارة المخاطر مع دور مسؤول الإبلاغ')
ON CONFLICT (role_code, rule_type, keyword) DO NOTHING;

CREATE TABLE IF NOT EXISTS aml_annual_reports (
    id                SERIAL PRIMARY KEY,
    report_year       INTEGER NOT NULL,
    role_code         VARCHAR(40) NOT NULL DEFAULT 'mlro',
    status            VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved')),
    data              JSONB NOT NULL DEFAULT '{}'::jsonb,
    narrative         TEXT,
    generated_at      TIMESTAMP,
    generated_by      INTEGER REFERENCES users(id),
    submitted_at      TIMESTAMP,
    board_meeting_ref VARCHAR(200),
    board_approved_on DATE,
    approval_recorded_by INTEGER REFERENCES users(id),
    CONSTRAINT aml_annual_reports_uniq UNIQUE (report_year, role_code)
);

-- Policies that need board approval, and the approvals given.
ALTER TABLE policies ADD COLUMN IF NOT EXISTS requires_board_approval BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS policy_board_approvals (
    id              SERIAL PRIMARY KEY,
    policy_id       INTEGER NOT NULL,
    policy_version  VARCHAR(40),
    approved_on     DATE NOT NULL,
    board_ref       VARCHAR(200),
    notes           TEXT,
    recorded_by     INTEGER REFERENCES users(id),
    recorded_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_policy_board_approvals_policy ON policy_board_approvals(policy_id);

-- ---------------------------------------------------------------- monitoring programme
CREATE TABLE IF NOT EXISTS aml_monitoring_plans (
    id           SERIAL PRIMARY KEY,
    plan_year    INTEGER NOT NULL UNIQUE,
    title        VARCHAR(300),
    approved_on  DATE,
    notes        TEXT,
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS aml_monitoring_reviews (
    id              SERIAL PRIMARY KEY,
    plan_id         INTEGER NOT NULL REFERENCES aml_monitoring_plans(id) ON DELETE CASCADE,
    unit_label      VARCHAR(200) NOT NULL,          -- branch / department reviewed
    org_unit_id     INTEGER,
    review_type     VARCHAR(10) NOT NULL DEFAULT 'offsite' CHECK (review_type IN ('offsite', 'onsite')),
    planned_date    DATE NOT NULL,
    performed_date  DATE,
    reviewer_id     INTEGER REFERENCES users(id),
    checklist       JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{item, result: ok|issue|na, note}]
    conclusion      TEXT,
    status          VARCHAR(12) NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'done', 'cancelled')),
    finding_id      INTEGER REFERENCES rc_findings(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_aml_mon_reviews_plan ON aml_monitoring_reviews(plan_id);

-- ---------------------------------------------------------------- screening assurance
-- QA cases are built in the UI from the installation's own watchlist entries
-- (no list data in the repository) plus synthetic negatives.
CREATE TABLE IF NOT EXISTS screening_qa_cases (
    id             SERIAL PRIMARY KEY,
    query_name     VARCHAR(300) NOT NULL,
    expected_name  VARCHAR(300),                  -- watchlist name that must be found (NULL = must NOT match)
    variant_type   VARCHAR(40) NOT NULL DEFAULT 'exact',
    expect_match   BOOLEAN NOT NULL DEFAULT TRUE,
    list_label     VARCHAR(120),                  -- e.g. UN, local terrorist list, freeze orders
    entity_type    VARCHAR(20) NOT NULL DEFAULT 'INDIVIDUAL',
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT screening_qa_cases_uniq UNIQUE (query_name, expected_name)
);
CREATE TABLE IF NOT EXISTS screening_qa_runs (
    id               SERIAL PRIMARY KEY,
    run_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    run_by           INTEGER REFERENCES users(id),
    cases            INTEGER NOT NULL DEFAULT 0,
    positives        INTEGER NOT NULL DEFAULT 0,
    hits             INTEGER NOT NULL DEFAULT 0,
    misses           INTEGER NOT NULL DEFAULT 0,
    false_positives  INTEGER NOT NULL DEFAULT 0,
    recall_pct       NUMERIC(6,2),
    precision_pct    NUMERIC(6,2),
    details          JSONB NOT NULL DEFAULT '[]'::jsonb,
    error            TEXT
);

CREATE TABLE IF NOT EXISTS employee_screenings (
    id                 SERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    screened_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    trigger            VARCHAR(20) NOT NULL DEFAULT 'periodic' CHECK (trigger IN ('hiring', 'periodic', 'manual')),
    history_id         INTEGER,
    status             VARCHAR(30),
    high_risk_matches  INTEGER NOT NULL DEFAULT 0,
    screened_by        INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_employee_screenings_user ON employee_screenings(user_id, screened_at DESC);

-- Internal-audit findings flagged as AML red flags are routed to the
-- unusual-transactions register for study.
ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS aml_red_flag BOOLEAN NOT NULL DEFAULT FALSE;

INSERT INTO case_sla_config (case_type, sla_days, description)
VALUES ('UNUSUAL_TXN', 15, 'Unusual transaction / AML red flag to study (aml_unusual_transactions)')
ON CONFLICT (case_type) DO NOTHING;

-- ---------------------------------------------------------------- KYC / KYB
-- Field catalogue: which fields a complete file needs. source 'column' reads
-- the subject's own table; 'profile' reads kyc_profile_values (for fields the
-- source table does not capture).
CREATE TABLE IF NOT EXISTS kyc_fields (
    field_key    VARCHAR(60) NOT NULL,
    subject      VARCHAR(30) NOT NULL,            -- aml_customer, merchant, …
    label_en     VARCHAR(200) NOT NULL,
    label_ar     VARCHAR(200),
    source       VARCHAR(10) NOT NULL DEFAULT 'column' CHECK (source IN ('column', 'profile')),
    column_names TEXT[] NOT NULL DEFAULT '{}',     -- first non-empty column wins
    applies_to   VARCHAR(12) NOT NULL DEFAULT 'all' CHECK (applies_to IN ('individual', 'entity', 'all')),
    is_required  BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order   INTEGER NOT NULL DEFAULT 100,
    pack_code    VARCHAR(40),
    PRIMARY KEY (subject, field_key)
);
INSERT INTO kyc_fields (subject, field_key, label_en, label_ar, source, column_names, applies_to, sort_order) VALUES
  ('aml_customer', 'full_name', 'Full name', 'الاسم الكامل', 'column', '{full_name}', 'individual', 10),
  ('aml_customer', 'date_of_birth', 'Date of birth', 'تاريخ الميلاد', 'column', '{date_of_birth}', 'individual', 20),
  ('aml_customer', 'gender', 'Gender', 'النوع', 'column', '{gender}', 'individual', 30),
  ('aml_customer', 'nationality', 'Nationality / nationalities', 'الجنسية / الجنسيات', 'column', '{nationality}', 'individual', 40),
  ('aml_customer', 'residence_country', 'Country of residence', 'بلد الإقامة', 'column', '{residence_country,country}', 'all', 50),
  ('aml_customer', 'address', 'Address', 'العنوان', 'column', '{address_line1,address}', 'all', 60),
  ('aml_customer', 'id_type', 'Identity document type', 'نوع مستند الهوية', 'column', '{id_type}', 'individual', 70),
  ('aml_customer', 'company_name', 'Legal name', 'الاسم القانوني', 'column', '{company_name}', 'entity', 10),
  ('aml_customer', 'registration_number', 'Commercial registration number', 'رقم السجل التجاري', 'column', '{registration_number}', 'entity', 20),
  ('aml_customer', 'tax_card_number', 'Tax card number', 'رقم البطاقة الضريبية', 'column', '{tax_card_number,tax_id}', 'entity', 30),
  ('aml_customer', 'tax_card_issuer', 'Tax card issuing office', 'جهة إصدار البطاقة الضريبية', 'profile', '{}', 'entity', 40),
  ('aml_customer', 'senior_management', 'Senior management names', 'أسماء الإدارة العليا', 'profile', '{}', 'entity', 50),
  ('merchant', 'merchant_name', 'Merchant legal name', 'الاسم القانوني للتاجر', 'column', '{merchant_name}', 'entity', 10),
  ('merchant', 'tax_card_number', 'Tax card number', 'رقم البطاقة الضريبية', 'column', '{tax_id}', 'entity', 20),
  ('merchant', 'tax_card_issuer', 'Tax card issuing office', 'جهة إصدار البطاقة الضريبية', 'profile', '{}', 'entity', 30),
  ('merchant', 'senior_management', 'Senior management names', 'أسماء الإدارة العليا', 'profile', '{}', 'entity', 40)
ON CONFLICT (subject, field_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS kyc_profile_values (
    subject     VARCHAR(30) NOT NULL,
    subject_id  INTEGER NOT NULL,
    field_key   VARCHAR(60) NOT NULL,
    value       TEXT,
    updated_by  INTEGER REFERENCES users(id),
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (subject, subject_id, field_key)
);

CREATE TABLE IF NOT EXISTS kyc_beneficial_owners (
    id             SERIAL PRIMARY KEY,
    subject        VARCHAR(30) NOT NULL,
    subject_id     INTEGER NOT NULL,
    full_name      VARCHAR(255) NOT NULL,
    nationality    VARCHAR(100),
    ownership_pct  NUMERIC(6,2),
    control_type   VARCHAR(30) NOT NULL DEFAULT 'ownership' CHECK (control_type IN ('ownership', 'control', 'senior_manager')),
    is_pep         BOOLEAN NOT NULL DEFAULT FALSE,
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kyc_bo_subject ON kyc_beneficial_owners(subject, subject_id);

-- Signed beneficial-owner declaration (file: generic_attachments, module 'aml',
-- record_type 'kyc_bo_declaration').
CREATE TABLE IF NOT EXISTS kyc_bo_declarations (
    id               SERIAL PRIMARY KEY,
    subject          VARCHAR(30) NOT NULL,
    subject_id       INTEGER NOT NULL,
    declaration_type VARCHAR(10) NOT NULL CHECK (declaration_type IN ('self', 'other')),
    bo_name          VARCHAR(255),
    signed_on        DATE NOT NULL,
    recorded_by      INTEGER REFERENCES users(id),
    recorded_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kyc_bo_decl_subject ON kyc_bo_declarations(subject, subject_id);

-- Configurable multi-factor risk model.
CREATE TABLE IF NOT EXISTS kyc_risk_factors (
    id          SERIAL PRIMARY KEY,
    factor_key  VARCHAR(60) NOT NULL UNIQUE,
    category    VARCHAR(20) NOT NULL CHECK (category IN ('customer', 'geography', 'product', 'channel', 'pep', 'behaviour')),
    label_en    VARCHAR(200) NOT NULL,
    label_ar    VARCHAR(200),
    field_key   VARCHAR(60) NOT NULL,         -- kyc field / record column / profile value it reads
    weight      NUMERIC(6,2) NOT NULL DEFAULT 1,
    scoring     JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {"value": score 0-100, "*": default}
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    pack_code   VARCHAR(40)
);
INSERT INTO kyc_risk_factors (factor_key, category, label_en, label_ar, field_key, weight, scoring) VALUES
  ('customer_type', 'customer', 'Customer type', 'نوع العميل', 'customer_type', 1, '{"INDIVIDUAL": 20, "CORPORATE": 50, "*": 30}'),
  ('residence', 'geography', 'Country of residence', 'بلد الإقامة', 'residence_country', 1.5, '{"*": 30}'),
  ('product', 'product', 'Product / service', 'المنتج / الخدمة', 'product', 1, '{"*": 30}'),
  ('channel', 'channel', 'Onboarding channel', 'قناة بدء العلاقة', 'channel', 1, '{"branch": 20, "digital": 50, "agent": 60, "*": 40}'),
  ('pep', 'pep', 'Politically exposed person', 'شخص معرض سياسيًا', 'is_pep', 2, '{"1": 100, "true": 100, "True": 100, "*": 0}'),
  ('behaviour', 'behaviour', 'Transaction behaviour (alerts)', 'السلوك (التنبيهات)', 'alert_count', 1.5, '{"0": 0, "*": 70}')
ON CONFLICT (factor_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS kyc_risk_bands (
    band              VARCHAR(10) PRIMARY KEY CHECK (band IN ('low', 'medium', 'high')),
    min_score         NUMERIC(6,2) NOT NULL,
    refresh_param_key VARCHAR(120),          -- regulatory parameter holding the KYC refresh cycle (months)
    label_en          VARCHAR(40),
    label_ar          VARCHAR(40)
);
INSERT INTO kyc_risk_bands (band, min_score, refresh_param_key, label_en, label_ar) VALUES
  ('low', 0, 'kyc.refresh_months_low', 'Low', 'منخفض'),
  ('medium', 40, 'kyc.refresh_months_medium', 'Medium', 'متوسط'),
  ('high', 70, 'kyc.refresh_months_high', 'High', 'مرتفع')
ON CONFLICT (band) DO NOTHING;

CREATE TABLE IF NOT EXISTS kyc_risk_ratings (
    id                SERIAL PRIMARY KEY,
    subject           VARCHAR(30) NOT NULL,
    subject_id        INTEGER NOT NULL,
    score             NUMERIC(6,2) NOT NULL,
    band              VARCHAR(10) NOT NULL,
    factors           JSONB NOT NULL DEFAULT '[]'::jsonb,
    trigger           VARCHAR(30) NOT NULL DEFAULT 'manual',     -- onboarding, periodic, pep_change, alerts, manual
    rated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rated_by          INTEGER REFERENCES users(id),
    next_review_date  DATE,
    is_current        BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_kyc_ratings_subject ON kyc_risk_ratings(subject, subject_id, is_current);

-- Onboarding gate: completeness + rating + EDD (+ senior approval for high risk).
CREATE TABLE IF NOT EXISTS kyc_onboarding (
    subject            VARCHAR(30) NOT NULL,
    subject_id         INTEGER NOT NULL,
    status             VARCHAR(12) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    edd_checklist      JSONB NOT NULL DEFAULT '[]'::jsonb,       -- [{item, done, note}]
    edd_completed      BOOLEAN NOT NULL DEFAULT FALSE,
    senior_approved_by INTEGER REFERENCES users(id),
    senior_approved_at TIMESTAMP,
    approved_by        INTEGER REFERENCES users(id),
    approved_at        TIMESTAMP,
    note               TEXT,
    PRIMARY KEY (subject, subject_id)
);

-- ---------------------------------------------------------------- internal-audit coverage
CREATE TABLE IF NOT EXISTS ia_area_controls (
    universe_id  INTEGER NOT NULL REFERENCES audit_universe(id) ON DELETE CASCADE,
    control_id   INTEGER NOT NULL REFERENCES rc_controls(id) ON DELETE CASCADE,
    PRIMARY KEY (universe_id, control_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON
    aml_key_roles, aml_role_conflict_rules, aml_annual_reports, policy_board_approvals, aml_monitoring_plans,
    aml_monitoring_reviews, screening_qa_cases, screening_qa_runs, employee_screenings, kyc_fields,
    kyc_profile_values, kyc_beneficial_owners, kyc_bo_declarations, kyc_risk_factors, kyc_risk_bands,
    kyc_risk_ratings, kyc_onboarding, ia_area_controls
    TO complynex;
GRANT USAGE, SELECT ON
    aml_key_roles_id_seq, aml_role_conflict_rules_id_seq, aml_annual_reports_id_seq, policy_board_approvals_id_seq,
    aml_monitoring_plans_id_seq, aml_monitoring_reviews_id_seq, screening_qa_cases_id_seq, screening_qa_runs_id_seq,
    employee_screenings_id_seq, kyc_beneficial_owners_id_seq, kyc_bo_declarations_id_seq, kyc_risk_factors_id_seq,
    kyc_risk_ratings_id_seq
    TO complynex;

COMMIT;
