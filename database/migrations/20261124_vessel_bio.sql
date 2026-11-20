-- Vessel BIO (round 5): the particulars the lists carry beyond identity - deadweight, full build date,
-- registration number, the date a list first published the ship, its topics (shadow fleet, detained ...),
-- the list's own description and source links (superadmin only), and for each linked party its role as the
-- list words it, the period and the party's country. Filled by the list importers / vessel_store.sync.
BEGIN;

ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS deadweight          VARCHAR(40);
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS build_date          VARCHAR(20);
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS registration_number VARCHAR(60);
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS listed_on           VARCHAR(20);
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS topics              TEXT;      -- JSON list
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS description         TEXT;
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS source_urls         TEXT;      -- JSON list

ALTER TABLE vessel_party_link ADD COLUMN IF NOT EXISTS role_label    TEXT;
ALTER TABLE vessel_party_link ADD COLUMN IF NOT EXISTS start_date    VARCHAR(20);
ALTER TABLE vessel_party_link ADD COLUMN IF NOT EXISTS end_date      VARCHAR(20);
ALTER TABLE vessel_party_link ADD COLUMN IF NOT EXISTS party_country TEXT;
ALTER TABLE vessel_party_link ADD COLUMN IF NOT EXISTS party_target  BOOLEAN;   -- FALSE: only related to a listing
ALTER TABLE vessel_party_link ADD COLUMN IF NOT EXISTS as_of         VARCHAR(20); -- date the link was reported

GRANT SELECT, INSERT, UPDATE, DELETE ON vessel_profile, vessel_party_link TO complynex;
COMMIT;
