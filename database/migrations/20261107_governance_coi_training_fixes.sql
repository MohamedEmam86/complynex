-- Governance / COI / training fixes.
-- 1) Meetings saved with a blank or non-date meeting_date broke every page that
--    casts it (governance dashboard, meetings list, annual reports). Clear them
--    so they show as "no date" and can be edited.
-- 2) Ad-hoc COI disclosures from the employee portal: keep the disclosed
--    conflict type and parties (description -> details, mitigation -> mitigation_plan).
-- 3) Training certificates issued without an issue date: backfill from the
--    enrollment completion date, else from the date in the certificate number.
BEGIN;

UPDATE board_meetings SET meeting_date = NULL
 WHERE meeting_date IS NOT NULL AND meeting_date !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}';

ALTER TABLE coi_declarations ADD COLUMN IF NOT EXISTS conflict_type TEXT;
ALTER TABLE coi_declarations ADD COLUMN IF NOT EXISTS parties_involved TEXT;

UPDATE training_certificates c
   SET issue_date = COALESCE(
         (SELECT left(e.completion_date, 10) FROM training_enrollments e
           WHERE e.id = c.enrollment_id AND e.completion_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'),
         CASE WHEN c.certificate_number ~ '-[0-9]{8}$'
              THEN to_char(to_date(right(c.certificate_number, 8), 'YYYYMMDD'), 'YYYY-MM-DD') END)
 WHERE c.issue_date IS NULL OR c.issue_date = '' OR c.issue_date = 'None';

GRANT SELECT, INSERT, UPDATE, DELETE ON board_meetings, coi_declarations, training_certificates TO complynex;
COMMIT;
