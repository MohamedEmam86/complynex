-- Unified case registry: data protection requests and breaches become case sources.
BEGIN;
INSERT INTO case_sla_config (case_type, sla_days, description) VALUES
 ('DSR', 30, 'Data subject request — the request''s own due_date is used when present.'),
 ('DATA_BREACH', 3, 'Personal-data breach — regulator notification clock (72 hours from discovery) unless a notification deadline is recorded.')
ON CONFLICT (case_type) DO NOTHING;
COMMIT;
