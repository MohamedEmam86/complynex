-- eKYC: the customer types their national ID number and Arabic name on the
-- consent page. The pipeline uses them when the card cannot be read and
-- sends any disagreement with the card read to an officer.
BEGIN;
ALTER TABLE ekyc_session ADD COLUMN IF NOT EXISTS declared_national_id VARCHAR(14);
ALTER TABLE ekyc_session ADD COLUMN IF NOT EXISTS declared_name_ar TEXT;
ALTER TABLE ekyc_session ADD COLUMN IF NOT EXISTS declared_at TIMESTAMP;
COMMIT;
