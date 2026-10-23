-- Talent pool (optional pack 'talent_pool'): a public application form for
-- part-time / freelance consultants and the staff register that reviews them.
-- Personal data: name, contact details, CV. Access is granted per user
-- (user_module_permissions, module 'talent').
BEGIN;

CREATE TABLE IF NOT EXISTS talent_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_by  INTEGER,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS talent_categories (
    id          SERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name_en     TEXT NOT NULL,
    name_ar     TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INTEGER NOT NULL DEFAULT 100,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS talent_applications (
    id                  SERIAL PRIMARY KEY,
    ref                 TEXT UNIQUE NOT NULL,
    full_name           TEXT NOT NULL,
    email               TEXT NOT NULL,
    phone               TEXT NOT NULL,
    whatsapp            TEXT,
    city                TEXT,
    country             TEXT,
    primary_category_id INTEGER REFERENCES talent_categories(id),
    other_category_ids  INTEGER[] NOT NULL DEFAULT '{}',
    years_experience    INTEGER,
    current_title       TEXT,
    seniority           TEXT,
    availability        TEXT,
    engagement          TEXT,
    work_mode           TEXT,
    languages           TEXT,
    certifications      TEXT,
    linkedin_url        TEXT,
    expected_rate       TEXT,
    summary             TEXT,
    cv_path             TEXT,
    cv_original_name    TEXT,
    cv_size             INTEGER,
    cv_sha256           TEXT,
    consent_privacy_at  TIMESTAMPTZ,
    ack_terms_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'unverified',
    email_verified_at   TIMESTAMPTZ,
    rating              SMALLINT,
    source              TEXT,
    ip_address          TEXT,
    user_agent          TEXT,
    status_changed_by   INTEGER,
    status_changed_at   TIMESTAMPTZ,
    erased_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT talent_status_chk CHECK (status IN ('unverified','new','shortlisted','contacted','interview','engaged','on_hold','rejected','withdrawn')),
    CONSTRAINT talent_rating_chk CHECK (rating IS NULL OR rating BETWEEN 1 AND 5)
);
CREATE INDEX IF NOT EXISTS idx_talent_app_status   ON talent_applications(status);
CREATE INDEX IF NOT EXISTS idx_talent_app_category ON talent_applications(primary_category_id);
CREATE INDEX IF NOT EXISTS idx_talent_app_email    ON talent_applications(lower(email));
CREATE INDEX IF NOT EXISTS idx_talent_app_created  ON talent_applications(created_at DESC);

CREATE TABLE IF NOT EXISTS talent_notes (
    id              SERIAL PRIMARY KEY,
    application_id  INTEGER NOT NULL REFERENCES talent_applications(id) ON DELETE CASCADE,
    user_id         INTEGER,
    kind            TEXT NOT NULL DEFAULT 'note',
    body            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_talent_notes_app ON talent_notes(application_id);

-- e-mail ownership check: a 6-digit code (stored as an HMAC, never in clear)
CREATE TABLE IF NOT EXISTS talent_otp (
    id              SERIAL PRIMARY KEY,
    application_id  INTEGER NOT NULL REFERENCES talent_applications(id) ON DELETE CASCADE,
    code_hash       TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    consumed_at     TIMESTAMPTZ,
    request_ip      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_talent_otp_app ON talent_otp(application_id, created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON talent_settings, talent_categories, talent_applications, talent_notes, talent_otp TO complynex;
GRANT USAGE, SELECT ON SEQUENCE talent_categories_id_seq, talent_applications_id_seq, talent_notes_id_seq, talent_otp_id_seq TO complynex;
COMMIT;
