-- ESG / Carbon: Arabic content columns, offset-certificate details (FRA Decision 36/2026)
BEGIN;

ALTER TABLE esg_disclosure_items  ADD COLUMN IF NOT EXISTS title_ar VARCHAR(300);
ALTER TABLE esg_disclosure_items  ADD COLUMN IF NOT EXISTS requirement_ar TEXT;
ALTER TABLE esg_indicators        ADD COLUMN IF NOT EXISTS name_ar VARCHAR(300);
ALTER TABLE esg_indicators        ADD COLUMN IF NOT EXISTS description_ar TEXT;
ALTER TABLE esg_pillars           ADD COLUMN IF NOT EXISTS name_ar VARCHAR(200);
ALTER TABLE esg_materiality_topics ADD COLUMN IF NOT EXISTS name_ar VARCHAR(300);
ALTER TABLE esg_frameworks        ADD COLUMN IF NOT EXISTS name_ar VARCHAR(300);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS activity_ar VARCHAR(300);

ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS vintage_year INTEGER;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS fra_project_id VARCHAR(100);

ALTER TABLE fra_verifiers ADD COLUMN IF NOT EXISTS registration_no VARCHAR(50);
ALTER TABLE fra_verifiers ADD COLUMN IF NOT EXISTS registered_on DATE;

GRANT SELECT, INSERT, UPDATE, DELETE ON esg_disclosure_items, esg_indicators, esg_pillars, esg_materiality_topics,
      esg_frameworks, carbon_emission_factors, carbon_offset_purchases, fra_verifiers TO complynex;

COMMIT;
