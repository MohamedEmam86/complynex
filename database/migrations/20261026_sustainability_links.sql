-- =============================================================================
-- Sustainability: link ESG indicators and disclosure items to Carbon results
--
-- carbon_metric = which carbon figure feeds the row (total, scope1, scope2,
-- scope3, intensity_employee); NULL = detected from the reference and title;
-- 'none' = no link. Display only: ESG statuses and scores are never changed.
-- The ESG tables exist on live installations (created outside this folder), so
-- they are only created bare if missing; existing data is untouched.
--
-- Idempotent. DDL runs as postgres; GRANTs at the end.
-- =============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS esg_disclosure_items (id SERIAL PRIMARY KEY);
ALTER TABLE esg_disclosure_items ADD COLUMN IF NOT EXISTS carbon_metric VARCHAR(30);

CREATE TABLE IF NOT EXISTS esg_indicators (id SERIAL PRIMARY KEY);
ALTER TABLE esg_indicators ADD COLUMN IF NOT EXISTS carbon_metric VARCHAR(30);

GRANT SELECT, INSERT, UPDATE, DELETE ON esg_disclosure_items, esg_indicators TO complynex;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO complynex;

COMMIT;
