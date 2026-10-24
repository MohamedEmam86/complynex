-- Screening history rows were inserted without screening_date / created_at
-- (no column default), so History showed "None" and sorted them below older
-- rows. The app now sets both on insert; this adds defaults for every other
-- insert path and backfills existing rows. Idempotent.
BEGIN;

DO $$
DECLARE
    sd_type text;
BEGIN
    SELECT data_type INTO sd_type
      FROM information_schema.columns
     WHERE table_name = 'screening_history' AND column_name = 'screening_date';

    IF sd_type = 'text' OR sd_type = 'character varying' THEN
        ALTER TABLE screening_history
            ALTER COLUMN screening_date SET DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS');
    ELSIF sd_type IS NOT NULL THEN
        ALTER TABLE screening_history ALTER COLUMN screening_date SET DEFAULT CURRENT_TIMESTAMP;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'screening_history' AND column_name = 'created_at') THEN
        ALTER TABLE screening_history ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
    END IF;

    -- Backfill: the row's own created_at, else its linked screening_results row.
    IF sd_type = 'text' OR sd_type = 'character varying' THEN
        UPDATE screening_history h
           SET screening_date = COALESCE(to_char(h.created_at, 'YYYY-MM-DD HH24:MI:SS'),
                                         (SELECT r.created_at::text FROM screening_results r
                                           WHERE r.id = h.screening_result_id))
         WHERE h.screening_date IS NULL;
    END IF;
    UPDATE screening_history h
       SET created_at = (SELECT r.created_at::timestamp FROM screening_results r
                          WHERE r.id = h.screening_result_id)
     WHERE h.created_at IS NULL AND h.screening_result_id IS NOT NULL;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON screening_history TO complynex;

COMMIT;
