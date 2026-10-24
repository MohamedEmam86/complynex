-- COI: remember who a declaration was escalated to, so that person (even
-- without the COI module permission) can open and decide that declaration only.
BEGIN;
ALTER TABLE coi_declarations ADD COLUMN IF NOT EXISTS escalated_to INTEGER;
ALTER TABLE coi_declarations ADD COLUMN IF NOT EXISTS escalated_by INTEGER;
ALTER TABLE coi_declarations ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMP;
GRANT SELECT, INSERT, UPDATE, DELETE ON coi_declarations TO complynex;
COMMIT;
