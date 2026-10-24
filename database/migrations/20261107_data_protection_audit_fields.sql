-- Data protection: record who approved a DPIA (four-eyes check, shown on the
-- DPIA page) and stop timestamps being stored as NULL ("None" on screen).
BEGIN;
ALTER TABLE dpias ADD COLUMN IF NOT EXISTS approved_by INTEGER;
ALTER TABLE dsr_timeline ALTER COLUMN action_date SET DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
ALTER TABLE dpias ALTER COLUMN created_at SET DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
ALTER TABLE data_breaches ALTER COLUMN created_at SET DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
ALTER TABLE data_subject_requests ALTER COLUMN created_at SET DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
ALTER TABLE data_processing_activities ALTER COLUMN created_at SET DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
GRANT SELECT, INSERT, UPDATE, DELETE ON dpias TO complynex;
COMMIT;
