-- Per-user access control (owner requirement: every module and every feature is granted per user).
--  * users.access_mode: where the user works — 'cms' (back-office), 'portal' (employee portal) or
--    'restricted' (a clean workspace with only the granted modules: no CMS, no portal, every other URL refused).
--    NULL = not yet migrated: the application derives it from the old rule (can_access_cms), so a database
--    where this migration ran but the backfill did not still behaves exactly as before.
--  * user_access_grants: one row per (user, feature) the administrator decided; granted = TRUE/FALSE.
--    Features without a row follow the old role/perm_* rules for 'cms'/'portal' users and are refused for
--    'restricted' users. The feature catalogue itself is code (access/catalog.py + each pack's manifest).
--  * user_access_audit: every change (who, whom, what before/after) for the audit trail.
-- The backfill that writes today's effective access as explicit grants is scripts/access_backfill.py
-- (idempotent; it uses the same rules as the application). This file only sets access_mode.
-- Idempotent; additive only.
BEGIN;
SET lock_timeout = '5s';

ALTER TABLE users ADD COLUMN IF NOT EXISTS access_mode VARCHAR(12);

DO $$ BEGIN
    ALTER TABLE users ADD CONSTRAINT users_access_mode_check
        CHECK (access_mode IS NULL OR access_mode IN ('cms', 'portal', 'restricted'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS user_access_grants (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feature     VARCHAR(80) NOT NULL,
    granted     BOOLEAN NOT NULL DEFAULT TRUE,
    source      VARCHAR(20) NOT NULL DEFAULT 'admin',       -- admin | backfill | copy
    updated_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, feature)
);
CREATE INDEX IF NOT EXISTS idx_user_access_grants_feature ON user_access_grants (feature);

CREATE TABLE IF NOT EXISTS user_access_audit (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- whose access changed
    actor_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,           -- who changed it (NULL = migration)
    action      VARCHAR(30) NOT NULL,           -- save | copy | backfill | mode
    mode_before VARCHAR(12),
    mode_after  VARCHAR(12),
    added       TEXT,                           -- JSON list of features granted by this change
    removed     TEXT,                           -- JSON list of features taken away by this change
    note        TEXT,
    ip_address  VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_access_audit_user ON user_access_audit (user_id, created_at DESC);

-- The platform superadmin is unrestricted and works in the CMS (an earlier draft of this file gave a superadmin
-- without a CMS level 'portal'; corrected here, idempotently).
UPDATE users SET access_mode = 'cms' WHERE role = 'superadmin' AND access_mode IS DISTINCT FROM 'cms';

-- Today's rule, made explicit: CMS for the compliance roles and for users with a CMS access level,
-- the employee portal for everyone else. Only rows never set are touched.
UPDATE users SET access_mode = CASE
        WHEN role IN ('superadmin', 'admin', 'compliance_officer', 'compliance_manager') THEN 'cms'
        WHEN COALESCE(cms_access_level, 'none') IN ('view', 'edit') THEN 'cms'
        ELSE 'portal' END
 WHERE access_mode IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON user_access_grants, user_access_audit TO complynex;
GRANT USAGE, SELECT ON SEQUENCE user_access_audit_id_seq TO complynex;

COMMIT;
