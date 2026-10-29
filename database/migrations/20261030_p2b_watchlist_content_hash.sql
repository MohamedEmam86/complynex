-- Phase 2: fingerprint of everything stored for a list record, so changed dates of birth,
-- identifiers or aliases are picked up even when the name is unchanged.
ALTER TABLE screening_watchlist ADD COLUMN IF NOT EXISTS content_hash TEXT;
-- the EMLCU source was labelled as a PEP list in the data-source registry too (sanctions_lists is
-- rebuilt from it every night)
UPDATE screening_data_sources SET source_display_name = 'EMLCU Egyptian Terrorist Lists'
 WHERE source_name = 'emlcu' AND source_display_name = 'Egypt PEP List (Manual)';
