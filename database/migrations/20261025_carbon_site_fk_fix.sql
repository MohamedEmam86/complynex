-- Fix: carbon_activity_entries.site_id must reference carbon_sites (not the legacy esg_sites)
BEGIN;

-- Production schemas created site_id with a FK to esg_sites; sites now live in carbon_sites.
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'carbon_activity_entries'::regclass AND contype = 'f'
             AND pg_get_constraintdef(oid) LIKE '%(site_id)%' AND pg_get_constraintdef(oid) NOT LIKE '%carbon_sites%'
  LOOP
    EXECUTE format('ALTER TABLE carbon_activity_entries DROP CONSTRAINT %I', c.conname);
  END LOOP;
  UPDATE carbon_activity_entries SET site_id = NULL
   WHERE site_id IS NOT NULL AND site_id NOT IN (SELECT id FROM carbon_sites);
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'carbon_activity_entries'::regclass
                 AND conname = 'carbon_activity_entries_carbon_site_fkey') THEN
    ALTER TABLE carbon_activity_entries ADD CONSTRAINT carbon_activity_entries_carbon_site_fkey
      FOREIGN KEY (site_id) REFERENCES carbon_sites(id);
  END IF;
END $$;
COMMIT;
