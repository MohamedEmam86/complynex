-- Unified case registry: STR cases opened outside the old unusual-transactions register.
BEGIN;
INSERT INTO case_sla_config (case_type, sla_days, description) VALUES
 ('SAR', 15, 'STR case — the case''s own statutory deadline is used when one is recorded.')
ON CONFLICT (case_type) DO NOTHING;
COMMIT;
