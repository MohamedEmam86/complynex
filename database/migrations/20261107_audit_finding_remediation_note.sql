-- Internal audit: "Mark remediation complete" now records what was done and
-- the evidence for it, and when.
BEGIN;
ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS remediation_note TEXT;
ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS remediated_at TIMESTAMP;
GRANT SELECT, INSERT, UPDATE, DELETE ON audit_findings TO complynex;
COMMIT;
