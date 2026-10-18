-- =============================================================================
-- Carbon accounting: boundaries, versioned factors, PCAF financed emissions,
-- data quality, preparer -> reviewer -> approver workflow, intensity, initiatives
--
-- The carbon tables already exist on live installations (created outside the
-- migrations folder). This file therefore never re-creates them: each table is
-- created only if missing (bare id) and every column is added with
-- ADD COLUMN IF NOT EXISTS, so it is safe both on the live database and on a
-- fresh install. Existing data is never changed.
--
-- Idempotent. DDL runs as postgres; GRANTs at the end.
-- =============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS esg_reporting_periods (id SERIAL PRIMARY KEY);
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS label VARCHAR(100);
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS start_date DATE;
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS end_date DATE;
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'open';
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS fra_status VARCHAR(30) DEFAULT 'Draft';
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS verifier_name VARCHAR(255);
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS verifier_contact VARCHAR(255);
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS verification_notes TEXT;
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS sent_to_verifier_at DATE;
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS certified_at DATE;
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS submitted_to_fra_at DATE;
ALTER TABLE esg_reporting_periods ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS carbon_emission_factors (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS scope VARCHAR(10);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS category VARCHAR(100);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS ghg_category_no INTEGER;
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS activity VARCHAR(255);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS unit VARCHAR(40);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS factor_kgco2e DOUBLE PRECISION;
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS source VARCHAR(255);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS vintage_year INTEGER;
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS effective_from DATE;
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS effective_to DATE;
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS factor_code VARCHAR(60);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS version_label VARCHAR(40);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS region VARCHAR(10) DEFAULT 'EG';
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS source_url VARCHAR(500);
ALTER TABLE carbon_emission_factors ADD COLUMN IF NOT EXISTS created_by INTEGER;

CREATE TABLE IF NOT EXISTS carbon_activity_entries (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS reporting_period_id INTEGER;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS site_id INTEGER;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS scope VARCHAR(10);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS category VARCHAR(100);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS ghg_category_no INTEGER;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS activity VARCHAR(255);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS calc_method VARCHAR(30) DEFAULT 'activity_based';
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS quantity DOUBLE PRECISION;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS unit VARCHAR(40);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS factor_id INTEGER;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS tco2e DOUBLE PRECISION;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS basis VARCHAR(10) DEFAULT 'location';
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS evidence_path VARCHAR(500);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS reviewed_by INTEGER;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS created_by INTEGER;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS entity_id INTEGER;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS activity_month DATE;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS factor_code VARCHAR(60);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS factor_kgco2e_used NUMERIC(18,6);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS factor_source_used VARCHAR(255);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS factor_vintage_used INTEGER;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS gross_tco2e NUMERIC(18,6);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS boundary_share NUMERIC(6,4);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS instrument_type VARCHAR(30);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS instrument_ref VARCHAR(200);
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS helper_inputs JSONB;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;
ALTER TABLE carbon_activity_entries ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS carbon_scope_config (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS company_label VARCHAR(60);
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS scope1_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS scope2_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS scope3_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS issued_capital_egp DOUBLE PRECISION;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS net_equity_egp DOUBLE PRECISION;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS fiscal_year_end DATE;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS updated_by INTEGER;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS consolidation_approach VARCHAR(20) DEFAULT 'operational_control';
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS base_year INTEGER;
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS base_year_tco2e NUMERIC(18,3);
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS recalculation_threshold_pct NUMERIC(6,2);
ALTER TABLE carbon_scope_config ADD COLUMN IF NOT EXISTS recalculation_policy TEXT;

CREATE TABLE IF NOT EXISTS carbon_targets (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_targets ADD COLUMN IF NOT EXISTS baseline_year INTEGER;
ALTER TABLE carbon_targets ADD COLUMN IF NOT EXISTS baseline_tco2e DOUBLE PRECISION;
ALTER TABLE carbon_targets ADD COLUMN IF NOT EXISTS target_2030_pct DOUBLE PRECISION;
ALTER TABLE carbon_targets ADD COLUMN IF NOT EXISTS target_2035_pct DOUBLE PRECISION;
ALTER TABLE carbon_targets ADD COLUMN IF NOT EXISTS sbti_aligned BOOLEAN DEFAULT FALSE;
ALTER TABLE carbon_targets ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE carbon_targets ADD COLUMN IF NOT EXISTS updated_by INTEGER;
ALTER TABLE carbon_targets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS carbon_offset_obligations (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_offset_obligations ADD COLUMN IF NOT EXISTS reporting_period_id INTEGER;
ALTER TABLE carbon_offset_obligations ADD COLUMN IF NOT EXISTS total_emissions_tco2e DOUBLE PRECISION;
ALTER TABLE carbon_offset_obligations ADD COLUMN IF NOT EXISTS offset_pct DOUBLE PRECISION;
ALTER TABLE carbon_offset_obligations ADD COLUMN IF NOT EXISTS required_tco2e DOUBLE PRECISION;
ALTER TABLE carbon_offset_obligations ADD COLUMN IF NOT EXISTS report_submitted_date DATE;
ALTER TABLE carbon_offset_obligations ADD COLUMN IF NOT EXISTS deadline_date DATE;
ALTER TABLE carbon_offset_obligations ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'OPEN';
ALTER TABLE carbon_offset_obligations ADD COLUMN IF NOT EXISTS created_by INTEGER;

CREATE TABLE IF NOT EXISTS carbon_offset_purchases (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS obligation_id INTEGER;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS project_name VARCHAR(255);
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS registry_reference VARCHAR(255);
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS quantity_tco2e DOUBLE PRECISION;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS purchase_date DATE;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS cost_egp DOUBLE PRECISION;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS created_by INTEGER;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS retired_on DATE;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS serial_numbers TEXT;
ALTER TABLE carbon_offset_purchases ADD COLUMN IF NOT EXISTS standard VARCHAR(60);

CREATE TABLE IF NOT EXISTS fra_verifiers (id SERIAL PRIMARY KEY);
ALTER TABLE fra_verifiers ADD COLUMN IF NOT EXISTS name VARCHAR(255);
ALTER TABLE fra_verifiers ADD COLUMN IF NOT EXISTS contact_info VARCHAR(255);
ALTER TABLE fra_verifiers ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS carbon_entities (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_entities ADD COLUMN IF NOT EXISTS name VARCHAR(255) NOT NULL;
ALTER TABLE carbon_entities ADD COLUMN IF NOT EXISTS name_ar VARCHAR(255);
ALTER TABLE carbon_entities ADD COLUMN IF NOT EXISTS ownership_pct NUMERIC(6,2) DEFAULT 100;
ALTER TABLE carbon_entities ADD COLUMN IF NOT EXISTS operational_control BOOLEAN DEFAULT TRUE;
ALTER TABLE carbon_entities ADD COLUMN IF NOT EXISTS financial_control BOOLEAN DEFAULT TRUE;
ALTER TABLE carbon_entities ADD COLUMN IF NOT EXISTS included BOOLEAN DEFAULT TRUE;
ALTER TABLE carbon_entities ADD COLUMN IF NOT EXISTS note TEXT;

CREATE TABLE IF NOT EXISTS carbon_sites (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS entity_id INTEGER;
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS name VARCHAR(255);
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS site_type VARCHAR(20) DEFAULT 'office';
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS city VARCHAR(100);
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS floor_area_m2 NUMERIC(12,2);
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS headcount INTEGER;
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS opened_on DATE;
ALTER TABLE carbon_sites ADD COLUMN IF NOT EXISTS closed_on DATE;

CREATE TABLE IF NOT EXISTS carbon_financed_exposures (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS reporting_period_id INTEGER NOT NULL;
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS reference VARCHAR(100);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS borrower VARCHAR(255);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS asset_class VARCHAR(30) DEFAULT 'business_loans';
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS sector VARCHAR(100);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS outstanding NUMERIC(18,2) NOT NULL DEFAULT 0;
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS attribution_base NUMERIC(18,2);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS method VARCHAR(20) NOT NULL DEFAULT 'asset';
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS borrower_emissions_tco2e NUMERIC(18,6);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS borrower_revenue_egp NUMERIC(18,2);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS factor_id INTEGER;
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS factor_kgco2e_used NUMERIC(18,6);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS attribution NUMERIC(10,6);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS financed_tco2e NUMERIC(18,6);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS data_quality_score INTEGER;
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS error VARCHAR(200);
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS source VARCHAR(10) DEFAULT 'manual';
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS created_by INTEGER;
ALTER TABLE carbon_financed_exposures ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS carbon_period_metrics (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_period_metrics ADD COLUMN IF NOT EXISTS reporting_period_id INTEGER NOT NULL;
ALTER TABLE carbon_period_metrics ADD COLUMN IF NOT EXISTS revenue_egp NUMERIC(18,2);
ALTER TABLE carbon_period_metrics ADD COLUMN IF NOT EXISTS headcount INTEGER;
ALTER TABLE carbon_period_metrics ADD COLUMN IF NOT EXISTS floor_area_m2 NUMERIC(12,2);
ALTER TABLE carbon_period_metrics ADD COLUMN IF NOT EXISTS financed_portfolio_egp NUMERIC(18,2);
ALTER TABLE carbon_period_metrics ADD COLUMN IF NOT EXISTS updated_by INTEGER;
ALTER TABLE carbon_period_metrics ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS carbon_period_workflow (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS reporting_period_id INTEGER NOT NULL;
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS status VARCHAR(12) NOT NULL DEFAULT 'preparing';
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS prepared_by INTEGER;
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS prepared_at TIMESTAMP;
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS reviewed_by INTEGER;
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS approved_by INTEGER;
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;
ALTER TABLE carbon_period_workflow ADD COLUMN IF NOT EXISTS note TEXT;

CREATE TABLE IF NOT EXISTS carbon_workflow_events (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_workflow_events ADD COLUMN IF NOT EXISTS reporting_period_id INTEGER NOT NULL;
ALTER TABLE carbon_workflow_events ADD COLUMN IF NOT EXISTS action VARCHAR(20) NOT NULL;
ALTER TABLE carbon_workflow_events ADD COLUMN IF NOT EXISTS from_status VARCHAR(12);
ALTER TABLE carbon_workflow_events ADD COLUMN IF NOT EXISTS to_status VARCHAR(12);
ALTER TABLE carbon_workflow_events ADD COLUMN IF NOT EXISTS user_id INTEGER;
ALTER TABLE carbon_workflow_events ADD COLUMN IF NOT EXISTS note TEXT;
ALTER TABLE carbon_workflow_events ADD COLUMN IF NOT EXISTS at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS carbon_initiatives (id SERIAL PRIMARY KEY);
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS title VARCHAR(255) NOT NULL;
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS scope VARCHAR(10);
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS owner_user_id INTEGER;
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS start_date DATE;
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS target_date DATE;
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS expected_reduction_tco2e NUMERIC(18,3);
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS achieved_reduction_tco2e NUMERIC(18,3);
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS cost_egp NUMERIC(18,2);
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS status VARCHAR(12) DEFAULT 'planned';
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS note TEXT;
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS created_by INTEGER;
ALTER TABLE carbon_initiatives ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS uq_carbon_scope_config_label ON carbon_scope_config(company_label);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fra_verifiers_name ON fra_verifiers(name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_carbon_period_metrics ON carbon_period_metrics(reporting_period_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_carbon_period_workflow ON carbon_period_workflow(reporting_period_id);
CREATE INDEX IF NOT EXISTS idx_carbon_entries_period ON carbon_activity_entries(reporting_period_id);
CREATE INDEX IF NOT EXISTS idx_carbon_factors_code ON carbon_emission_factors(factor_code, effective_from);
CREATE INDEX IF NOT EXISTS idx_carbon_financed_period ON carbon_financed_exposures(reporting_period_id);

-- Existing factors get a stable code so later versions can be chained to them.
UPDATE carbon_emission_factors SET factor_code = 'F' || id WHERE factor_code IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    esg_reporting_periods, carbon_emission_factors, carbon_activity_entries, carbon_scope_config, carbon_targets,
    carbon_offset_obligations, carbon_offset_purchases, fra_verifiers, carbon_entities, carbon_sites,
    carbon_financed_exposures, carbon_period_metrics, carbon_period_workflow, carbon_workflow_events, carbon_initiatives
    TO complynex;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO complynex;

COMMIT;
