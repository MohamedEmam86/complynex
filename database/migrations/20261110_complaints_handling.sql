-- Consumer complaints: owner, root cause, redress, internal notes (append-only), resolution date.
BEGIN;
ALTER TABLE consumer_complaints ADD COLUMN IF NOT EXISTS root_cause_category TEXT;
ALTER TABLE consumer_complaints ADD COLUMN IF NOT EXISTS redress_type TEXT;
ALTER TABLE consumer_complaints ADD COLUMN IF NOT EXISTS redress_amount NUMERIC(14,2);
ALTER TABLE consumer_complaints ADD COLUMN IF NOT EXISTS redress_date DATE;
ALTER TABLE consumer_complaints ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;
ALTER TABLE consumer_complaints ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP;
ALTER TABLE consumer_complaints ADD COLUMN IF NOT EXISTS assigned_by INTEGER;

CREATE TABLE IF NOT EXISTS complaint_internal_notes (
    id           SERIAL PRIMARY KEY,
    complaint_id INTEGER NOT NULL,
    note         TEXT NOT NULL,
    created_by   INTEGER NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_complaint_internal_notes_c ON complaint_internal_notes (complaint_id);

-- Internal notes are a record: no edits, no deletes.
CREATE OR REPLACE FUNCTION complaint_internal_notes_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'complaint_internal_notes is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_complaint_internal_notes_ro ON complaint_internal_notes;
CREATE TRIGGER trg_complaint_internal_notes_ro BEFORE UPDATE OR DELETE ON complaint_internal_notes
    FOR EACH ROW EXECUTE FUNCTION complaint_internal_notes_append_only();

-- Backfill a resolution timestamp for already-closed complaints (best effort, from updated_at).
UPDATE consumer_complaints SET resolved_at = NULLIF(updated_at, '')::timestamp
 WHERE resolved_at IS NULL AND status IN ('RESOLVED', 'CLOSED')
   AND updated_at ~ '^\d{4}-\d{2}-\d{2}';

GRANT SELECT, INSERT ON complaint_internal_notes TO complynex;
GRANT USAGE, SELECT ON SEQUENCE complaint_internal_notes_id_seq TO complynex;
COMMIT;
