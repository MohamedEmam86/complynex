-- =============================================================================
-- Prudential, licensing, governance & financial-reporting registers (generic core)
--
-- Regulator-neutral registers that any licensed institution needs: capital,
-- regulatory deadlines and extensions, periodic solvency figures, corporate
-- profile (single source of truth for the registered address) and official
-- documents, key functions, branches and staffing, borrowing facilities,
-- related parties and approved studies (ECL, deferred tax, ...). Regulatory
-- thresholds stay in rc_parameters; content packs bind controls to the
-- core.prudential.* / core.governance.* / core.finance.* checks.
--
-- Idempotent: safe to run more than once. DDL runs as postgres; GRANTs at end.
-- =============================================================================
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_prudential VARCHAR(10) DEFAULT 'none';

-- ---------------------------------------------------------------- corporate profile
CREATE TABLE IF NOT EXISTS corp_profile (
    id                     INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    legal_name_en          VARCHAR(255),
    legal_name_ar          VARCHAR(255),
    registered_address_en  TEXT,
    registered_address_ar  TEXT,
    address_aliases        TEXT[] NOT NULL DEFAULT '{}',   -- accepted spellings of the same address
    commercial_register_no VARCHAR(100),
    tax_card_no            VARCHAR(100),
    licence_number         VARCHAR(100),
    licence_type           VARCHAR(40),
    regulator_id           INTEGER REFERENCES regulators(id),
    phone                  VARCHAR(60),
    email                  VARCHAR(200),
    website                VARCHAR(200),
    updated_by             INTEGER REFERENCES users(id),
    updated_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO corp_profile (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Official documents whose stated address must match the registered address
-- (board minutes, letters to the regulator, contracts …). File: generic_attachments
-- module 'prudential', record_type 'pr_document'.
CREATE TABLE IF NOT EXISTS pr_documents (
    id                 SERIAL PRIMARY KEY,
    doc_type           VARCHAR(30) NOT NULL DEFAULT 'letter'
                       CHECK (doc_type IN ('board_minutes', 'letter', 'contract', 'form', 'other')),
    title              VARCHAR(255) NOT NULL,
    doc_date           DATE,
    address_on_document TEXT,
    source_module      VARCHAR(40),
    source_record_id   INTEGER,
    reviewed_ok        BOOLEAN,                 -- manual override after review
    review_note        TEXT,
    created_by         INTEGER REFERENCES users(id),
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------- capital
-- Each row is the new level of one capital figure from a date (files: record_type 'pr_capital_event').
CREATE TABLE IF NOT EXISTS pr_capital_events (
    id             SERIAL PRIMARY KEY,
    capital_type   VARCHAR(12) NOT NULL CHECK (capital_type IN ('authorised', 'issued', 'paid_up', 'registered')),
    amount         NUMERIC(18,2) NOT NULL CHECK (amount >= 0),
    currency       VARCHAR(3) NOT NULL DEFAULT 'EGP',
    effective_date DATE NOT NULL,
    reference      VARCHAR(200),             -- resolution / bank certificate / registry entry
    note           TEXT,
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pr_capital_type_date ON pr_capital_events(capital_type, effective_date);

-- ---------------------------------------------------------------- regulatory deadlines
CREATE TABLE IF NOT EXISTS pr_deadlines (
    id                 SERIAL PRIMARY KEY,
    title              VARCHAR(255) NOT NULL,
    category           VARCHAR(30) NOT NULL DEFAULT 'other'
                       CHECK (category IN ('capital_increase', 'licence', 'remediation', 'submission', 'other')),
    regulator_id       INTEGER REFERENCES regulators(id),
    original_due_date  DATE NOT NULL,
    due_date           DATE NOT NULL,           -- after the latest extension
    status             VARCHAR(10) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'met', 'missed', 'cancelled')),
    met_on             DATE,
    owner_user_id      INTEGER REFERENCES users(id),
    notified_thresholds INTEGER[] NOT NULL DEFAULT '{}',   -- countdown alerts already sent (days)
    board_escalated_at TIMESTAMP,
    finding_id         INTEGER REFERENCES rc_findings(id) ON DELETE SET NULL,
    note               TEXT,
    created_by         INTEGER REFERENCES users(id),
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pr_deadline_extensions (
    id             SERIAL PRIMARY KEY,
    deadline_id    INTEGER NOT NULL REFERENCES pr_deadlines(id) ON DELETE CASCADE,
    extension_type VARCHAR(10) NOT NULL DEFAULT 'special' CHECK (extension_type IN ('general', 'special')),
    granted_on     DATE NOT NULL,
    new_due_date   DATE NOT NULL,
    letter_ref     VARCHAR(200),
    note           TEXT,
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------- periodic financial figures (solvency)
CREATE TABLE IF NOT EXISTS pr_financial_periods (
    id                 SERIAL PRIMARY KEY,
    period_end         DATE NOT NULL UNIQUE,
    period_type        VARCHAR(10) NOT NULL DEFAULT 'quarter' CHECK (period_type IN ('month', 'quarter', 'half', 'year')),
    total_assets       NUMERIC(18,2),
    total_liabilities  NUMERIC(18,2),
    equity             NUMERIC(18,2),
    paid_up_capital    NUMERIC(18,2),
    capital_base       NUMERIC(18,2),          -- regulatory capital as defined by the applicable rules
    revenue            NUMERIC(18,2),
    net_profit         NUMERIC(18,2),
    loan_portfolio     NUMERIC(18,2),
    extra              JSONB NOT NULL DEFAULT '{}'::jsonb,
    source             VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'import', 'erp')),
    status             VARCHAR(10) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
    approved_by        INTEGER REFERENCES users(id),
    approved_at        TIMESTAMP,
    created_by         INTEGER REFERENCES users(id),
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------- key functions
CREATE TABLE IF NOT EXISTS pr_key_function_types (
    code                VARCHAR(40) PRIMARY KEY,
    name_en             VARCHAR(200) NOT NULL,
    name_ar             VARCHAR(200),
    is_required         BOOLEAN NOT NULL DEFAULT TRUE,
    notify_regulator    BOOLEAN NOT NULL DEFAULT TRUE,
    needs_no_objection  BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order          INTEGER NOT NULL DEFAULT 100,
    pack_code           VARCHAR(40)
);
INSERT INTO pr_key_function_types (code, name_en, name_ar, sort_order) VALUES
  ('ceo', 'Chief executive / managing director', 'الرئيس التنفيذي / العضو المنتدب', 10),
  ('cfo', 'Chief financial officer', 'المدير المالي', 20),
  ('compliance_head', 'Head of compliance', 'رئيس الالتزام', 30),
  ('risk_head', 'Head of risk management', 'رئيس إدارة المخاطر', 40),
  ('internal_audit_head', 'Head of internal audit', 'رئيس المراجعة الداخلية', 50)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS pr_key_functions (
    id                    SERIAL PRIMARY KEY,
    function_code         VARCHAR(40) NOT NULL REFERENCES pr_key_function_types(code) ON UPDATE CASCADE,
    holder_user_id        INTEGER REFERENCES users(id),
    holder_name           VARCHAR(255),
    board_member_id       INTEGER,                 -- optional link to governance board_members (fit & proper)
    appointed_on          DATE,
    vacated_on            DATE,
    fit_proper_status     VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (fit_proper_status IN ('pending', 'passed', 'failed', 'na')),
    fit_proper_date       DATE,
    regulator_notified_on DATE,
    regulator_ref         VARCHAR(200),
    no_objection_status   VARCHAR(12) NOT NULL DEFAULT 'not_required'
                          CHECK (no_objection_status IN ('not_required', 'pending', 'granted', 'refused')),
    no_objection_on       DATE,
    note                  TEXT,
    updated_by            INTEGER REFERENCES users(id),
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pr_key_functions_code ON pr_key_functions(function_code);

-- ---------------------------------------------------------------- branches & staffing
CREATE TABLE IF NOT EXISTS pr_branches (
    id                     SERIAL PRIMARY KEY,
    code                   VARCHAR(40) NOT NULL UNIQUE,
    name_en                VARCHAR(200) NOT NULL,
    name_ar                VARCHAR(200),
    address                TEXT,
    org_unit_id            INTEGER,
    status                 VARCHAR(10) NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'active', 'closed')),
    opened_on              DATE,
    manager_name           VARCHAR(255),
    manager_user_id        INTEGER REFERENCES users(id),
    manager_no_objection   VARCHAR(12) NOT NULL DEFAULT 'pending'
                           CHECK (manager_no_objection IN ('not_required', 'pending', 'granted', 'refused')),
    manager_no_objection_ref VARCHAR(200),
    manager_no_objection_on  DATE,
    manager_vacant_since   DATE,
    updated_by             INTEGER REFERENCES users(id),
    updated_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pr_branch_roles (
    code       VARCHAR(40) PRIMARY KEY,
    name_en    VARCHAR(200) NOT NULL,
    name_ar    VARCHAR(200),
    min_count  INTEGER,                 -- fixed minimum, or …
    param_key  VARCHAR(120),            -- … a regulatory parameter holding the minimum
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    pack_code  VARCHAR(40)
);
INSERT INTO pr_branch_roles (code, name_en, name_ar, min_count) VALUES
  ('branch_manager', 'Branch manager', 'مدير الفرع', 1)
ON CONFLICT (code) DO NOTHING;
CREATE TABLE IF NOT EXISTS pr_branch_staffing (
    branch_id  INTEGER NOT NULL REFERENCES pr_branches(id) ON DELETE CASCADE,
    role_code  VARCHAR(40) NOT NULL REFERENCES pr_branch_roles(code) ON UPDATE CASCADE ON DELETE CASCADE,
    headcount  INTEGER NOT NULL DEFAULT 0 CHECK (headcount >= 0),
    as_of      DATE NOT NULL DEFAULT CURRENT_DATE,
    PRIMARY KEY (branch_id, role_code)
);

-- ---------------------------------------------------------------- borrowing facilities
CREATE TABLE IF NOT EXISTS pr_facilities (
    id                     SERIAL PRIMARY KEY,
    reference              VARCHAR(60) NOT NULL UNIQUE,
    lender_name            VARCHAR(255) NOT NULL,
    party_id               INTEGER,
    facility_type          VARCHAR(20) NOT NULL DEFAULT 'loan'
                           CHECK (facility_type IN ('loan', 'overdraft', 'bond', 'securitisation', 'related_party', 'other')),
    currency               VARCHAR(3) NOT NULL DEFAULT 'EGP',
    limit_amount           NUMERIC(18,2),
    balance                NUMERIC(18,2) NOT NULL DEFAULT 0,
    interest_rate_pct      NUMERIC(8,4),
    start_date             DATE,
    maturity_date          DATE,
    status                 VARCHAR(12) NOT NULL DEFAULT 'performing'
                           CHECK (status IN ('performing', 'default', 'rescheduled', 'closed')),
    covenant_breach        BOOLEAN NOT NULL DEFAULT FALSE,
    last_confirmation_date DATE,
    confirmation_balance   NUMERIC(18,2),
    accrual_from           DATE,                  -- last interest payment / accrual start
    accrued_booked         NUMERIC(18,2),
    booked_as_of           DATE,
    rescheduled_on         DATE,
    rescheduling_approval_ref VARCHAR(200),
    board_escalated_on     DATE,
    board_escalation_ref   VARCHAR(200),
    source                 VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'import', 'erp')),
    note                   TEXT,
    updated_by             INTEGER REFERENCES users(id),
    updated_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------- related parties
CREATE TABLE IF NOT EXISTS pr_related_parties (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    relation     VARCHAR(30) NOT NULL DEFAULT 'shareholder'
                 CHECK (relation IN ('shareholder', 'exiting_shareholder', 'director', 'affiliate', 'key_person', 'other')),
    party_id     INTEGER,
    ownership_pct NUMERIC(6,2),
    exited_on    DATE,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Contributions / balances / dues attributed to a related party (files: record_type 'pr_rp_item').
CREATE TABLE IF NOT EXISTS pr_rp_items (
    id                SERIAL PRIMARY KEY,
    related_party_id  INTEGER NOT NULL REFERENCES pr_related_parties(id) ON DELETE CASCADE,
    item_type         VARCHAR(30) NOT NULL
                      CHECK (item_type IN ('capital_contribution', 'loan_from', 'loan_to', 'current_account', 'dues', 'other')),
    amount            NUMERIC(18,2) NOT NULL,
    item_date         DATE NOT NULL,
    payer_name        VARCHAR(255),                -- who actually paid (bank transfer / receipt)
    classification    VARCHAR(20) CHECK (classification IN ('liability', 'equity', 'receivable', 'other')),
    explanation       TEXT,                        -- explains a payer ≠ party difference
    source            VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'import', 'erp')),
    created_by        INTEGER REFERENCES users(id),
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------- approved studies (ECL, deferred tax …)
CREATE TABLE IF NOT EXISTS pr_studies (
    id               SERIAL PRIMARY KEY,
    study_type       VARCHAR(30) NOT NULL,         -- ecl, deferred_tax, impairment, actuarial, other (free vocabulary)
    title            VARCHAR(255) NOT NULL,
    period_end       DATE,
    prepared_by      VARCHAR(255),
    approved_on      DATE,
    approved_by_body VARCHAR(200),                 -- board / audit committee / external auditor certificate
    next_refresh_date DATE,
    status           VARCHAR(10) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'superseded')),
    note             TEXT,
    created_by       INTEGER REFERENCES users(id),
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

GRANT SELECT, INSERT, UPDATE, DELETE ON
    corp_profile, pr_documents, pr_capital_events, pr_deadlines, pr_deadline_extensions, pr_financial_periods,
    pr_key_function_types, pr_key_functions, pr_branches, pr_branch_roles, pr_branch_staffing, pr_facilities,
    pr_related_parties, pr_rp_items, pr_studies
    TO complynex;
GRANT USAGE, SELECT ON
    pr_documents_id_seq, pr_capital_events_id_seq, pr_deadlines_id_seq, pr_deadline_extensions_id_seq,
    pr_financial_periods_id_seq, pr_key_functions_id_seq, pr_branches_id_seq, pr_facilities_id_seq,
    pr_related_parties_id_seq, pr_rp_items_id_seq, pr_studies_id_seq
    TO complynex;

COMMIT;
