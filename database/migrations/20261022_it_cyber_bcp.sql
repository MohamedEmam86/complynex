-- =============================================================================
-- IT, cybersecurity & business-continuity evidence (generic core, extends cyber/)
--
-- Registers any institution needs to evidence IT resilience: BCP / DR sites
-- and tests, backups (with an API feed for backup jobs), external
-- integrations and their health, security assessments with validity
-- (penetration, malware, CIS benchmark …), security assets and licences with
-- data-residency attestation, monitored domains with automatic TLS
-- certificate checks, and maturity self-assessments over any framework in
-- the regcontrols library. IT risks stay in the ERM risk register (risks).
--
-- Files: generic_attachments module 'cyber'. Idempotent; GRANTs at the end.
-- =============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS cy_bcp_sites (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(200) NOT NULL,
    site_type    VARCHAR(12) NOT NULL DEFAULT 'dr' CHECK (site_type IN ('primary', 'dr', 'backup', 'cloud')),
    location     VARCHAR(255),
    provider     VARCHAR(200),
    rto_hours    NUMERIC(8,2),
    rpo_hours    NUMERIC(8,2),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    note         TEXT,
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cy_dr_tests (
    id                 SERIAL PRIMARY KEY,
    site_id            INTEGER REFERENCES cy_bcp_sites(id) ON DELETE SET NULL,
    test_date          DATE NOT NULL,
    scope              TEXT,
    result             VARCHAR(10) NOT NULL CHECK (result IN ('pass', 'partial', 'fail')),
    rto_achieved_hours NUMERIC(8,2),
    rpo_achieved_hours NUMERIC(8,2),
    issues             TEXT,
    finding_id         INTEGER REFERENCES rc_findings(id) ON DELETE SET NULL,
    created_by         INTEGER REFERENCES users(id),
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cy_backups (
    id               SERIAL PRIMARY KEY,
    system_name      VARCHAR(200) NOT NULL UNIQUE,
    backup_type      VARCHAR(12) NOT NULL DEFAULT 'full' CHECK (backup_type IN ('full', 'incremental', 'snapshot', 'replication')),
    location_type    VARCHAR(10) NOT NULL DEFAULT 'offsite' CHECK (location_type IN ('onsite', 'offsite', 'cloud')),
    location_detail  VARCHAR(255),
    encrypted        BOOLEAN NOT NULL DEFAULT FALSE,
    last_success_at  TIMESTAMP,
    last_status      VARCHAR(10) CHECK (last_status IN ('success', 'failed', 'partial')),
    last_message     TEXT,
    last_restore_test DATE,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    source           VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'api')),
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cy_integrations (
    id               SERIAL PRIMARY KEY,
    code             VARCHAR(40) NOT NULL UNIQUE,
    name             VARCHAR(200) NOT NULL,
    counterparty     VARCHAR(200),
    purpose          TEXT,
    integration_type VARCHAR(10) NOT NULL DEFAULT 'api' CHECK (integration_type IN ('api', 'sftp', 'portal', 'email', 'manual')),
    status           VARCHAR(14) NOT NULL DEFAULT 'not_connected'
                     CHECK (status IN ('live', 'testing', 'down', 'not_connected')),
    last_success_at  TIMESTAMP,
    last_checked_at  TIMESTAMP,
    note             TEXT,
    pack_code        VARCHAR(40),
    updated_by       INTEGER REFERENCES users(id),
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cy_assessments (
    id                     SERIAL PRIMARY KEY,
    assessment_type        VARCHAR(30) NOT NULL,     -- pentest, malware_test, vulnerability_scan, cis_benchmark, …
    title                  VARCHAR(255) NOT NULL,
    provider               VARCHAR(200),
    provider_qualification VARCHAR(255),             -- accreditation / licence of the tester
    performed_on           DATE NOT NULL,
    valid_until            DATE,
    scope                  TEXT,
    critical_open          INTEGER NOT NULL DEFAULT 0,
    high_open              INTEGER NOT NULL DEFAULT 0,
    status                 VARCHAR(10) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'accepted')),
    accepted_by            INTEGER REFERENCES users(id),
    accepted_at            TIMESTAMP,
    created_by             INTEGER REFERENCES users(id),
    created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cy_security_assets (
    id                    SERIAL PRIMARY KEY,
    asset_type            VARCHAR(20) NOT NULL,      -- waf, epp, edr, firewall, siem, email_security, …
    product               VARCHAR(200) NOT NULL,
    vendor                VARCHAR(200),
    licence_ref           VARCHAR(200),
    licence_expiry        DATE,
    coverage_note         VARCHAR(255),
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    sends_data_abroad     BOOLEAN,                   -- NULL = not assessed
    data_location         VARCHAR(200),
    residency_attested_on DATE,
    residency_attested_by VARCHAR(200),
    updated_by            INTEGER REFERENCES users(id),
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cy_domains (
    id              SERIAL PRIMARY KEY,
    domain          VARCHAR(255) NOT NULL UNIQUE,
    port            INTEGER NOT NULL DEFAULT 443,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_checked_at TIMESTAMP,
    cert_subject    VARCHAR(500),
    cert_issuer     VARCHAR(500),
    cert_not_after  TIMESTAMP,
    last_error      TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Maturity self-assessment over the requirements of any regcontrols framework.
CREATE TABLE IF NOT EXISTS cy_maturity_assessments (
    id            SERIAL PRIMARY KEY,
    framework_id  INTEGER NOT NULL REFERENCES rc_frameworks(id) ON DELETE CASCADE,
    title         VARCHAR(255) NOT NULL,
    assessed_on   DATE NOT NULL DEFAULT CURRENT_DATE,
    status        VARCHAR(10) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'final')),
    created_by    INTEGER REFERENCES users(id),
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cy_maturity_scores (
    assessment_id  INTEGER NOT NULL REFERENCES cy_maturity_assessments(id) ON DELETE CASCADE,
    requirement_id INTEGER NOT NULL REFERENCES rc_requirements(id) ON DELETE CASCADE,
    current_level  INTEGER CHECK (current_level BETWEEN 0 AND 5),
    target_level   INTEGER CHECK (target_level BETWEEN 0 AND 5),
    note           TEXT,
    PRIMARY KEY (assessment_id, requirement_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON
    cy_bcp_sites, cy_dr_tests, cy_backups, cy_integrations, cy_assessments, cy_security_assets, cy_domains,
    cy_maturity_assessments, cy_maturity_scores
    TO complynex;
GRANT USAGE, SELECT ON
    cy_bcp_sites_id_seq, cy_dr_tests_id_seq, cy_backups_id_seq, cy_integrations_id_seq, cy_assessments_id_seq,
    cy_security_assets_id_seq, cy_domains_id_seq, cy_maturity_assessments_id_seq
    TO complynex;

COMMIT;
