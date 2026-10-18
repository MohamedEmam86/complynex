-- =============================================================================
-- FRA NBFI pack — Lending Conduct & Portfolio module schema (ln_* tables).
-- Used only while the fra_nbfi pack is enabled; harmless otherwise.
-- Permission: module 'lending' in user_module_permissions (no users column).
-- Idempotent. Requires 20261018_regcontrols.sql.
-- =============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS ln_products (
    id               SERIAL PRIMARY KEY,
    code             VARCHAR(40) NOT NULL UNIQUE,
    name_en          VARCHAR(200) NOT NULL,
    name_ar          VARCHAR(200),
    licence_type     VARCHAR(40) NOT NULL DEFAULT 'all',      -- code from rc_licence_types
    required_docs    TEXT[] NOT NULL DEFAULT '{national_id}',
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ln_import_batches (
    id           SERIAL PRIMARY KEY,
    kind         VARCHAR(30) NOT NULL,
    source       VARCHAR(10) NOT NULL DEFAULT 'file' CHECK (source IN ('file', 'api', 'manual', 'demo')),
    filename     VARCHAR(255),
    rows_total   INTEGER NOT NULL DEFAULT 0,
    rows_ok      INTEGER NOT NULL DEFAULT 0,
    rows_failed  INTEGER NOT NULL DEFAULT 0,
    errors       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Clients link to the party registry (parties / party_links, role LENDING_CLIENT).
CREATE TABLE IF NOT EXISTS ln_clients (
    id               SERIAL PRIMARY KEY,
    client_ref       VARCHAR(60) NOT NULL UNIQUE,
    party_id         INTEGER REFERENCES parties(id) ON DELETE SET NULL,
    client_type      VARCHAR(12) NOT NULL DEFAULT 'individual' CHECK (client_type IN ('individual', 'entity')),
    full_name        VARCHAR(255) NOT NULL,
    national_id_hash TEXT,
    gender           VARCHAR(10),
    phone            VARCHAR(40),
    address          TEXT,
    governorate      VARCHAR(80),
    business_activity VARCHAR(200),
    monthly_revenue  NUMERIC(16,2),
    project_size     NUMERIC(16,2),
    org_unit_id      INTEGER,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ln_loans (
    id                  SERIAL PRIMARY KEY,
    loan_ref            VARCHAR(60) NOT NULL UNIQUE,
    client_id           INTEGER NOT NULL REFERENCES ln_clients(id) ON DELETE CASCADE,
    product_code        VARCHAR(40),
    amount              NUMERIC(16,2) NOT NULL,
    tenor_months        INTEGER,
    interest_rate_pct   NUMERIC(8,4),
    apr_pct             NUMERIC(8,4),
    admin_fee_amount    NUMERIC(16,2) NOT NULL DEFAULT 0,
    other_fees_amount   NUMERIC(16,2) NOT NULL DEFAULT 0,
    branch_code         VARCHAR(40),
    officer_code        VARCHAR(40),
    status              VARCHAR(20) NOT NULL DEFAULT 'application'
                        CHECK (status IN ('application', 'approved', 'disbursed', 'closed', 'written_off', 'rejected')),
    application_date    DATE,
    approval_date       DATE,
    disbursement_date   DATE,
    maturity_date       DATE,
    outstanding_principal NUMERIC(16,2) NOT NULL DEFAULT 0,
    days_past_due       INTEGER NOT NULL DEFAULT 0,
    gps_lat             NUMERIC(10,7),
    gps_lng             NUMERIC(10,7),
    purpose             TEXT,
    file_complete       BOOLEAN NOT NULL DEFAULT FALSE,
    file_gaps           JSONB NOT NULL DEFAULT '[]'::jsonb,
    source              VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (source IN ('file', 'api', 'manual', 'demo')),
    import_batch_id     INTEGER REFERENCES ln_import_batches(id) ON DELETE SET NULL,
    org_unit_id         INTEGER,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ln_loans_client ON ln_loans(client_id);
CREATE INDEX IF NOT EXISTS idx_ln_loans_status ON ln_loans(status);
CREATE INDEX IF NOT EXISTS idx_ln_loans_branch ON ln_loans(branch_code);

CREATE TABLE IF NOT EXISTS ln_contracts (
    id                SERIAL PRIMARY KEY,
    loan_id           INTEGER NOT NULL UNIQUE REFERENCES ln_loans(id) ON DELETE CASCADE,
    contract_no       VARCHAR(60),
    contract_date     DATE,
    signed_by_lender  BOOLEAN NOT NULL DEFAULT FALSE,
    lender_signed_at  DATE,
    signed_by_client  BOOLEAN NOT NULL DEFAULT FALSE,
    client_signed_at  DATE,
    penalty_clause_rate_pct NUMERIC(8,4),
    penalty_clause_cap_pct  NUMERIC(8,4)
);

-- Files: generic_attachments (module 'lending', record_type 'ln_document').
CREATE TABLE IF NOT EXISTS ln_documents (
    id             SERIAL PRIMARY KEY,
    loan_id        INTEGER REFERENCES ln_loans(id) ON DELETE CASCADE,
    client_id      INTEGER REFERENCES ln_clients(id) ON DELETE CASCADE,
    doc_type       VARCHAR(40) NOT NULL,
    received_date  DATE,
    reference_no   VARCHAR(120),
    notes          TEXT,
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ln_documents_loan ON ln_documents(loan_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ln_documents_uniq ON ln_documents(loan_id, doc_type) WHERE loan_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ln_credit_studies (
    id                  SERIAL PRIMARY KEY,
    loan_id             INTEGER NOT NULL UNIQUE REFERENCES ln_loans(id) ON DELETE CASCADE,
    study_date          DATE,
    officer_code        VARCHAR(40),
    monthly_revenue     NUMERIC(16,2),
    monthly_costs_total NUMERIC(16,2),
    cost_lines          JSONB NOT NULL DEFAULT '[]'::jsonb,
    household_expenses  NUMERIC(16,2),
    other_debt_service  NUMERIC(16,2),
    net_income          NUMERIC(16,2),
    dsr_pct             NUMERIC(8,2)
);

CREATE TABLE IF NOT EXISTS ln_instalments (
    id              SERIAL PRIMARY KEY,
    loan_id         INTEGER NOT NULL REFERENCES ln_loans(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    due_date        DATE NOT NULL,
    principal_due   NUMERIC(16,2) NOT NULL DEFAULT 0,
    interest_due    NUMERIC(16,2) NOT NULL DEFAULT 0,
    fees_due        NUMERIC(16,2) NOT NULL DEFAULT 0,
    paid_amount     NUMERIC(16,2) NOT NULL DEFAULT 0,
    paid_date       DATE,
    penalty_charged NUMERIC(16,2) NOT NULL DEFAULT 0,
    status          VARCHAR(12) NOT NULL DEFAULT 'due' CHECK (status IN ('due', 'partial', 'paid', 'waived')),
    UNIQUE (loan_id, seq)
);

CREATE TABLE IF NOT EXISTS ln_visits (
    id            SERIAL PRIMARY KEY,
    loan_id       INTEGER NOT NULL REFERENCES ln_loans(id) ON DELETE CASCADE,
    planned_date  DATE,
    visit_date    DATE,
    officer_code  VARCHAR(40),
    outcome       VARCHAR(40),
    notes         TEXT
);
CREATE INDEX IF NOT EXISTS idx_ln_visits_loan ON ln_visits(loan_id);

-- Early repayment flow: request -> disclosure -> signed consent + acknowledgement -> execute.
-- Signed consent file: generic_attachments (module 'lending', record_type 'ln_early_repayment').
CREATE TABLE IF NOT EXISTS ln_early_repayments (
    id                      SERIAL PRIMARY KEY,
    loan_id                 INTEGER NOT NULL REFERENCES ln_loans(id) ON DELETE CASCADE,
    request_date            DATE NOT NULL DEFAULT CURRENT_DATE,
    settlement_amount       NUMERIC(16,2),
    prepayment_fee          NUMERIC(16,2) NOT NULL DEFAULT 0,
    original_remaining_cost NUMERIC(16,2),
    new_total_cost          NUMERIC(16,2),
    disclosure_text_en      TEXT,
    disclosure_text_ar      TEXT,
    disclosed_at            TIMESTAMP,
    consent_signed          BOOLEAN NOT NULL DEFAULT FALSE,
    consent_date            DATE,
    cost_acknowledged       BOOLEAN NOT NULL DEFAULT FALSE,
    status                  VARCHAR(12) NOT NULL DEFAULT 'requested'
                            CHECK (status IN ('requested', 'disclosed', 'consented', 'executed', 'cancelled')),
    executed_at             TIMESTAMP,
    executed_by             INTEGER REFERENCES users(id),
    source                  VARCHAR(10) NOT NULL DEFAULT 'manual',
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ln_er_loan ON ln_early_repayments(loan_id);

CREATE TABLE IF NOT EXISTS ln_reschedulings (
    id           SERIAL PRIMARY KEY,
    loan_id      INTEGER NOT NULL REFERENCES ln_loans(id) ON DELETE CASCADE,
    resched_date DATE NOT NULL,
    fee_amount   NUMERIC(16,2) NOT NULL DEFAULT 0,
    old_tenor    INTEGER,
    new_tenor    INTEGER,
    reason       TEXT
);

CREATE TABLE IF NOT EXISTS ln_transfers (
    id                SERIAL PRIMARY KEY,
    loan_id           INTEGER NOT NULL REFERENCES ln_loans(id) ON DELETE CASCADE,
    transfer_date     DATE NOT NULL,
    instalments_moved INTEGER,
    fee_amount        NUMERIC(16,2) NOT NULL DEFAULT 0
);

-- Exceptions: eligibility breach or incomplete file approved by a second person.
CREATE TABLE IF NOT EXISTS ln_exceptions (
    id              SERIAL PRIMARY KEY,
    loan_id         INTEGER NOT NULL REFERENCES ln_loans(id) ON DELETE CASCADE,
    exception_type  VARCHAR(20) NOT NULL CHECK (exception_type IN ('eligibility', 'file_incomplete')),
    reason          TEXT NOT NULL,
    status          VARCHAR(12) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    requested_by    INTEGER REFERENCES users(id),
    requested_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_by      INTEGER REFERENCES users(id),
    decided_at      TIMESTAMP,
    decision_comment TEXT
);

-- Credit-study QA queue (FRA-016).
CREATE TABLE IF NOT EXISTS ln_qa_flags (
    id           SERIAL PRIMARY KEY,
    loan_id      INTEGER NOT NULL REFERENCES ln_loans(id) ON DELETE CASCADE,
    flag_type    VARCHAR(30) NOT NULL,
    detail       TEXT,
    status       VARCHAR(12) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'cleared', 'confirmed')),
    reviewed_by  INTEGER REFERENCES users(id),
    reviewed_at  TIMESTAMP,
    review_note  TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (loan_id, flag_type)
);

-- Monthly PAR snapshots (FRA-011/012 trend and re-measurement).
CREATE TABLE IF NOT EXISTS ln_par_snapshots (
    id           SERIAL PRIMARY KEY,
    period       DATE NOT NULL,
    dimension    VARCHAR(12) NOT NULL CHECK (dimension IN ('company', 'branch', 'officer', 'product')),
    dim_value    VARCHAR(60) NOT NULL,
    loans        INTEGER NOT NULL,
    outstanding  NUMERIC(18,2) NOT NULL,
    par30        NUMERIC(8,2) NOT NULL,
    par60        NUMERIC(8,2) NOT NULL,
    par90        NUMERIC(8,2) NOT NULL,
    par120       NUMERIC(8,2) NOT NULL,
    computed_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (period, dimension, dim_value)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON
    ln_products, ln_import_batches, ln_clients, ln_loans, ln_contracts, ln_documents, ln_credit_studies,
    ln_instalments, ln_visits, ln_early_repayments, ln_reschedulings, ln_transfers, ln_exceptions,
    ln_qa_flags, ln_par_snapshots
    TO complynex;
GRANT USAGE, SELECT ON
    ln_products_id_seq, ln_import_batches_id_seq, ln_clients_id_seq, ln_loans_id_seq, ln_contracts_id_seq,
    ln_documents_id_seq, ln_credit_studies_id_seq, ln_instalments_id_seq, ln_visits_id_seq,
    ln_early_repayments_id_seq, ln_reschedulings_id_seq, ln_transfers_id_seq, ln_exceptions_id_seq,
    ln_qa_flags_id_seq, ln_par_snapshots_id_seq
    TO complynex;

COMMIT;
