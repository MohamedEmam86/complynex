-- Dual-use goods (optional pack 'trade_control'): a threshold read from an exclusion clause of a control entry
-- ("except ... dry fertilizers containing less than 15 %") is stored with role = 'exclusion', so the
-- screening answers it as "excluded from this entry" instead of "meets the entry". Idempotent.
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE dualuse_parameters ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'control';
GRANT SELECT, INSERT, UPDATE, DELETE ON dualuse_parameters TO complynex;
COMMIT;
