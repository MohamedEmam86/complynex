-- Phase 7 (H2): written client authorisation required before a phishing simulation is sent.
BEGIN;
CREATE TABLE IF NOT EXISTS phishing_authorisations (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL UNIQUE REFERENCES phishing_campaigns(id) ON DELETE CASCADE,
    organisation VARCHAR(255),
    authorised_by_name VARCHAR(255),
    authorised_by_title VARCHAR(255),
    authorised_on DATE,
    scope TEXT,
    allowed_domains TEXT,
    valid_from DATE,
    valid_to DATE,
    notes TEXT,
    recorded_by INTEGER,
    recorded_at TIMESTAMP DEFAULT NOW(),
    updated_by INTEGER,
    updated_at TIMESTAMP,
    revoked_at TIMESTAMP,
    revoked_by INTEGER,
    revoke_reason TEXT
);
ALTER TABLE phishing_campaigns ADD COLUMN IF NOT EXISTS authorised_send_check TEXT;
GRANT SELECT, INSERT, UPDATE, DELETE ON phishing_authorisations TO complynex;
GRANT USAGE, SELECT ON SEQUENCE phishing_authorisations_id_seq TO complynex;
COMMIT;
