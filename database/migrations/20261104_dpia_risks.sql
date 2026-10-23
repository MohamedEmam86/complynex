-- DPIA review saves its own "risks identified" text (it was folded into
-- mitigation_measures because the column did not exist) and a change time.
BEGIN;
ALTER TABLE dpias ADD COLUMN IF NOT EXISTS risks_identified TEXT;
ALTER TABLE dpias ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;
COMMIT;
