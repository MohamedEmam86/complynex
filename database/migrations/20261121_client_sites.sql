-- Client sites: one client gets its own sub-domain served by the SAME application (client_sites/service.py).
--  * client_sites: everything client-specific is data (host, bilingual name / welcome text, logo stored under the
--    uploads folder, allowed access modes, default daily screening limit, monthly organisation cap).
--  * users.site_id: a user bound to a site signs in on that site's host only (NULL = the main hosts).
-- Idempotent; additive only. Nothing changes until the platform superadmin creates a site.
BEGIN;
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS client_sites (
    id                             SERIAL PRIMARY KEY,
    host                           VARCHAR(253) NOT NULL,
    name_en                        VARCHAR(200) NOT NULL,
    name_ar                        VARCHAR(200),
    logo_path                      VARCHAR(300),             -- relative to UPLOAD_FOLDER, never in git
    welcome_en                     TEXT,
    welcome_ar                     TEXT,
    allowed_access_modes           TEXT[] NOT NULL DEFAULT ARRAY['restricted']::TEXT[],
    default_access_mode            VARCHAR(12) NOT NULL DEFAULT 'restricted',
    contact_email                  VARCHAR(254),
    default_daily_screening_limit  INTEGER,                  -- NULL = the platform default, 0 = unlimited
    monthly_org_cap                INTEGER NOT NULL DEFAULT 0,  -- vessel + dual-use screenings per month, 0 = unlimited
    active                         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT client_sites_host_lower CHECK (host = lower(host)),
    CONSTRAINT client_sites_modes_ok CHECK (allowed_access_modes <@ ARRAY['cms', 'portal', 'restricted']::TEXT[]),
    CONSTRAINT client_sites_default_mode_ok CHECK (default_access_mode IN ('cms', 'portal', 'restricted')),
    CONSTRAINT client_sites_limits_ok CHECK (monthly_org_cap >= 0 AND COALESCE(default_daily_screening_limit, 0) >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sites_host ON client_sites (host);

ALTER TABLE users ADD COLUMN IF NOT EXISTS site_id INTEGER;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_site_id_fkey') THEN
        ALTER TABLE users ADD CONSTRAINT users_site_id_fkey FOREIGN KEY (site_id)
            REFERENCES client_sites(id) ON DELETE SET NULL;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_users_site_id ON users (site_id) WHERE site_id IS NOT NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON client_sites TO complynex;
GRANT USAGE, SELECT ON SEQUENCE client_sites_id_seq TO complynex;
COMMIT;
