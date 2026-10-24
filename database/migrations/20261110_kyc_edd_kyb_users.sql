-- =============================================================================
-- KYC / KYB / EDD and user-administration fixes (2026-11-10)
--   1. Configurable high-risk country list (seeded, editable in the UI)
--   2. EDD record on edd_cases: checklist fields, preparer / approver (four-eyes), history
--   3. Corporate KYB: entity fields, multiple UBOs (screened), authorised signatories;
--      merchants' single UBO copied into the multi-UBO table (nothing removed)
--   4. Merchant approval: submitter + status history
--   5. Users: must_change_password; organisation scope backfill (empty / NULL only)
-- Idempotent. Run as postgres.
-- =============================================================================
BEGIN;

-- ---------------------------------------------------------------- 1. high-risk countries
ALTER TABLE high_risk_countries ADD COLUMN IF NOT EXISTS name_ar    TEXT;
ALTER TABLE high_risk_countries ADD COLUMN IF NOT EXISTS aliases    TEXT;      -- '|' separated spellings / adjectives
ALTER TABLE high_risk_countries ADD COLUMN IF NOT EXISTS notes      TEXT;
ALTER TABLE high_risk_countries ADD COLUMN IF NOT EXISTS updated_by INTEGER;
ALTER TABLE high_risk_countries ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- Default list in the style of the FATF public statements (call for action + increased
-- monitoring). It is a starting point only: compliance must review it against the latest
-- publication and edit it on /aml/high-risk-countries. A country already present (by code),
-- including one deactivated by an administrator, is never re-added.
INSERT INTO high_risk_countries (country_code, country_name, name_ar, aliases, risk_category, source, effective_date, is_active)
SELECT v.code, v.name, v.name_ar, v.aliases, v.cat, 'Default seed list (FATF style) - review against the latest publication',
       '2026-11-10', 1
  FROM (VALUES
    ('KP', 'North Korea', 'كوريا الشمالية', 'DPRK|Korea, North|Democratic People''s Republic of Korea|North Korean|PRK', 'CALL_FOR_ACTION'),
    ('IR', 'Iran', 'إيران', 'Islamic Republic of Iran|Iranian|IRN', 'CALL_FOR_ACTION'),
    ('MM', 'Myanmar', 'ميانمار', 'Burma|Burmese|MMR', 'CALL_FOR_ACTION'),
    ('DZ', 'Algeria', 'الجزائر', 'Algerian|DZA', 'INCREASED_MONITORING'),
    ('AO', 'Angola', 'أنغولا', 'Angolan|AGO', 'INCREASED_MONITORING'),
    ('BO', 'Bolivia', 'بوليفيا', 'Bolivian|BOL', 'INCREASED_MONITORING'),
    ('BG', 'Bulgaria', 'بلغاريا', 'Bulgarian|BGR', 'INCREASED_MONITORING'),
    ('CM', 'Cameroon', 'الكاميرون', 'Cameroonian|CMR', 'INCREASED_MONITORING'),
    ('CI', 'Cote d''Ivoire', 'كوت ديفوار', 'Côte d''Ivoire|Ivory Coast|Ivorian|CIV', 'INCREASED_MONITORING'),
    ('CD', 'Democratic Republic of the Congo', 'جمهورية الكونغو الديمقراطية', 'DRC|DR Congo|Congo, Democratic Republic|COD', 'INCREASED_MONITORING'),
    ('HT', 'Haiti', 'هايتي', 'Haitian|HTI', 'INCREASED_MONITORING'),
    ('KE', 'Kenya', 'كينيا', 'Kenyan|KEN', 'INCREASED_MONITORING'),
    ('LA', 'Laos', 'لاوس', 'Lao PDR|Lao People''s Democratic Republic|Lao|LAO', 'INCREASED_MONITORING'),
    ('LB', 'Lebanon', 'لبنان', 'Lebanese|LBN', 'INCREASED_MONITORING'),
    ('MC', 'Monaco', 'موناكو', 'Monegasque|MCO', 'INCREASED_MONITORING'),
    ('NA', 'Namibia', 'ناميبيا', 'Namibian|NAM', 'INCREASED_MONITORING'),
    ('NP', 'Nepal', 'نيبال', 'Nepali|Nepalese|NPL', 'INCREASED_MONITORING'),
    ('SS', 'South Sudan', 'جنوب السودان', 'South Sudanese|SSD', 'INCREASED_MONITORING'),
    ('SY', 'Syria', 'سوريا', 'Syrian Arab Republic|Syrian|SYR', 'INCREASED_MONITORING'),
    ('VE', 'Venezuela', 'فنزويلا', 'Venezuelan|VEN', 'INCREASED_MONITORING'),
    ('VN', 'Vietnam', 'فيتنام', 'Viet Nam|Vietnamese|VNM', 'INCREASED_MONITORING'),
    ('YE', 'Yemen', 'اليمن', 'Yemeni|YEM', 'INCREASED_MONITORING'),
    ('VG', 'British Virgin Islands', 'جزر فيرجن البريطانية', 'BVI|Virgin Islands (British)|VGB', 'INCREASED_MONITORING')
  ) AS v(code, name, name_ar, aliases, cat)
 WHERE NOT EXISTS (SELECT 1 FROM high_risk_countries h WHERE upper(h.country_code) = v.code
                                                        OR upper(h.country_name) = upper(v.name));

-- ---------------------------------------------------------------- 2. EDD record
ALTER TABLE edd_cases ADD COLUMN IF NOT EXISTS source_of_wealth TEXT;
ALTER TABLE edd_cases ADD COLUMN IF NOT EXISTS source_of_funds  TEXT;
ALTER TABLE edd_cases ADD COLUMN IF NOT EXISTS sof_evidence     TEXT;      -- description of the evidence held
ALTER TABLE edd_cases ADD COLUMN IF NOT EXISTS purpose_nature   TEXT;      -- purpose and intended nature of the relationship
ALTER TABLE edd_cases ADD COLUMN IF NOT EXISTS next_review_date DATE;
ALTER TABLE edd_cases ADD COLUMN IF NOT EXISTS prepared_by      INTEGER;
ALTER TABLE edd_cases ADD COLUMN IF NOT EXISTS submitted_at     TIMESTAMP;
ALTER TABLE edd_cases ADD COLUMN IF NOT EXISTS returned_reason  TEXT;
CREATE INDEX IF NOT EXISTS idx_edd_cases_customer ON edd_cases(customer_id);

CREATE TABLE IF NOT EXISTS edd_case_history (
    id           SERIAL PRIMARY KEY,
    edd_case_id  INTEGER NOT NULL,
    action       VARCHAR(30) NOT NULL,
    from_status  VARCHAR(20),
    to_status    VARCHAR(20),
    reason       TEXT,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_edd_case_history_case ON edd_case_history(edd_case_id);

-- ---------------------------------------------------------------- 3. corporate KYB
ALTER TABLE customers ADD COLUMN IF NOT EXISTS tax_card_number   TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS legal_form        TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS licence_number    TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS licence_regulator TEXT;

ALTER TABLE merchants ADD COLUMN IF NOT EXISTS incorporation_date    TEXT;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS incorporation_country TEXT;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS licence_number        TEXT;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS licence_regulator     TEXT;

ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS id_type              VARCHAR(30);
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS id_number            VARCHAR(100);
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS date_of_birth        DATE;
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS screening_history_id INTEGER;
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS screening_error      TEXT;
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS screened_key         TEXT;
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS screened_at          TIMESTAMP;
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS source               VARCHAR(30);
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS updated_by           INTEGER;
ALTER TABLE kyc_beneficial_owners ADD COLUMN IF NOT EXISTS updated_at           TIMESTAMP;

CREATE TABLE IF NOT EXISTS kyb_signatories (
    id                   SERIAL PRIMARY KEY,
    subject              VARCHAR(30) NOT NULL,
    subject_id           INTEGER NOT NULL,
    full_name            VARCHAR(255) NOT NULL,
    position             VARCHAR(150),
    signing_authority    VARCHAR(20) NOT NULL DEFAULT 'sole' CHECK (signing_authority IN ('sole', 'joint')),
    nationality          VARCHAR(100),
    id_type              VARCHAR(30),
    id_number            VARCHAR(100),
    date_of_birth        DATE,
    screening_history_id INTEGER,
    screening_error      TEXT,
    screened_key         TEXT,
    screened_at          TIMESTAMP,
    created_by           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by           INTEGER,
    updated_at           TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kyb_signatories_subject ON kyb_signatories(subject, subject_id);

-- Merchants held one UBO in columns; copy it into the multi-UBO table when the merchant
-- has none yet. The merchant columns stay (they are kept in sync with the main owner).
INSERT INTO kyc_beneficial_owners (subject, subject_id, full_name, nationality, ownership_pct, control_type,
                                   is_pep, id_type, id_number, date_of_birth, source, created_by, created_at)
SELECT 'merchant', m.id, left(trim(m.ubo_name), 255), m.ubo_nationality,
       CASE WHEN m.ownership_percentage BETWEEN 0 AND 100 THEN m.ownership_percentage END,
       'ownership', COALESCE(m.pep_status, 0) = 1, m.ubo_id_type, m.ubo_id_number,
       CASE WHEN m.ubo_dob ~ '^\d{4}-\d{2}-\d{2}' THEN substr(m.ubo_dob, 1, 10)::date END,
       'migrated', m.created_by, CURRENT_TIMESTAMP
  FROM merchants m
 WHERE COALESCE(lower(trim(m.ubo_name)), '') NOT IN ('', 'none', 'null')
   AND NOT EXISTS (SELECT 1 FROM kyc_beneficial_owners b WHERE b.subject = 'merchant' AND b.subject_id = m.id);

-- Owner rows recorded earlier without identity details: take them from the merchant columns.
UPDATE kyc_beneficial_owners b
   SET id_type = COALESCE(b.id_type, m.ubo_id_type),
       id_number = COALESCE(b.id_number, m.ubo_id_number),
       date_of_birth = COALESCE(b.date_of_birth,
                                CASE WHEN m.ubo_dob ~ '^\d{4}-\d{2}-\d{2}' THEN substr(m.ubo_dob, 1, 10)::date END)
  FROM merchants m
 WHERE b.subject = 'merchant' AND b.subject_id = m.id
   AND lower(trim(b.full_name)) = lower(trim(m.ubo_name))
   AND (b.id_number IS NULL OR b.date_of_birth IS NULL);

-- Corporate customers: owners recorded in the older beneficial_owners register.
INSERT INTO kyc_beneficial_owners (subject, subject_id, full_name, nationality, ownership_pct, control_type,
                                   is_pep, id_type, id_number, date_of_birth, source, created_by, created_at)
SELECT 'aml_customer', o.customer_id, left(trim(o.full_name), 255), o.nationality,
       CASE WHEN o.ownership_percentage BETWEEN 0 AND 100 THEN o.ownership_percentage END,
       'ownership', COALESCE(o.is_pep, 0) = 1, o.id_type, o.id_number,
       CASE WHEN o.date_of_birth ~ '^\d{4}-\d{2}-\d{2}' THEN substr(o.date_of_birth, 1, 10)::date END,
       'migrated', o.created_by, CURRENT_TIMESTAMP
  FROM beneficial_owners o
 WHERE o.customer_id IS NOT NULL AND COALESCE(trim(o.full_name), '') <> ''
   AND NOT EXISTS (SELECT 1 FROM kyc_beneficial_owners b WHERE b.subject = 'aml_customer' AND b.subject_id = o.customer_id);

UPDATE kyc_beneficial_owners b
   SET id_type = COALESCE(b.id_type, o.id_type),
       id_number = COALESCE(b.id_number, o.id_number),
       date_of_birth = COALESCE(b.date_of_birth,
                                CASE WHEN o.date_of_birth ~ '^\d{4}-\d{2}-\d{2}' THEN substr(o.date_of_birth, 1, 10)::date END)
  FROM beneficial_owners o
 WHERE b.subject = 'aml_customer' AND b.subject_id = o.customer_id
   AND lower(trim(b.full_name)) = lower(trim(o.full_name))
   AND (b.id_number IS NULL OR b.date_of_birth IS NULL);

-- ---------------------------------------------------------------- 4. merchant approval
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS submitted_by INTEGER;
ALTER TABLE merchants ADD COLUMN IF NOT EXISTS submitted_at TEXT;

CREATE TABLE IF NOT EXISTS merchant_status_history (
    id           SERIAL PRIMARY KEY,
    merchant_id  INTEGER NOT NULL,
    from_status  VARCHAR(20),
    to_status    VARCHAR(20) NOT NULL,
    action       VARCHAR(30) NOT NULL,
    reason       TEXT,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_label  VARCHAR(60),           -- e.g. 'merchant (public link)' when no user is involved
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_merchant_status_history_m ON merchant_status_history(merchant_id);

-- ---------------------------------------------------------------- 5. users
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

-- Organisation scope: only users with nothing set get the company's root unit.
UPDATE users
   SET org_unit_id = (SELECT id FROM org_units WHERE parent_id IS NULL ORDER BY id LIMIT 1)
 WHERE org_unit_id IS NULL
   AND EXISTS (SELECT 1 FROM org_units WHERE parent_id IS NULL);

UPDATE users SET authority_level = 'group' WHERE authority_level IS NULL OR authority_level = '';

-- 'group' means the whole organisation; such a user with no scope rule saw nothing.
INSERT INTO user_org_scope_rules (user_id, rule_type, org_unit_id)
SELECT u.id, 'subtree', r.id
  FROM users u
 CROSS JOIN (SELECT id FROM org_units WHERE parent_id IS NULL ORDER BY id LIMIT 1) r
 WHERE u.authority_level = 'group'
   AND NOT EXISTS (SELECT 1 FROM user_org_scope_rules s WHERE s.user_id = u.id);

GRANT SELECT, INSERT, UPDATE, DELETE ON edd_case_history, kyb_signatories, merchant_status_history TO complynex;
GRANT USAGE, SELECT ON edd_case_history_id_seq, kyb_signatories_id_seq, merchant_status_history_id_seq TO complynex;

COMMIT;
