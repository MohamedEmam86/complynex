-- Phase 8 AML: the freeze log becomes a HIT ESCALATION LOG (ComplyNex only alerts and escalates;
-- it never freezes), one STR case per screening hit, safe date reads for the periodic reviews.
-- Idempotent. No row is deleted and no existing value is changed except the renamed parameter keys.
BEGIN;

-- 1. Hit escalation log: steps discovered -> escalated to the MLRO -> reported to the authority.
--    The table keeps its name; the old freeze columns (frozen_at, frozen_by, freeze_scope, amount_frozen,
--    currency, released_at, release_reason) stay in place, unused.
ALTER TABLE aml_freeze_log ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMP;
ALTER TABLE aml_freeze_log ADD COLUMN IF NOT EXISTS escalated_by INTEGER;
COMMENT ON TABLE aml_freeze_log IS
    'Hit escalation log (discovered -> escalated to the MLRO -> reported). Freeze / release columns are legacy and unused.';

-- 2. Target parameters renamed (the code reads only the new names). Copied only when the new key
--    does not exist yet for the same licence type and date, so a rerun changes nothing.
DO $$
BEGIN
    IF to_regclass('public.rc_parameters') IS NOT NULL THEN
        UPDATE rc_parameters p SET param_key = 'aml.escalation_target_hours', updated_at = CURRENT_TIMESTAMP
         WHERE p.param_key = 'aml.freeze_target_hours'
           AND NOT EXISTS (SELECT 1 FROM rc_parameters n WHERE n.param_key = 'aml.escalation_target_hours'
                              AND n.licence_type = p.licence_type AND n.effective_from = p.effective_from);
        UPDATE rc_parameters p SET param_key = 'aml.report_target_hours', updated_at = CURRENT_TIMESTAMP
         WHERE p.param_key = 'aml.freeze_report_target_hours'
           AND NOT EXISTS (SELECT 1 FROM rc_parameters n WHERE n.param_key = 'aml.report_target_hours'
                              AND n.licence_type = p.licence_type AND n.effective_from = p.effective_from);
    END IF;
    IF to_regclass('public.system_settings') IS NOT NULL THEN
        UPDATE system_settings s SET setting_key = 'aml_escalation_target_hours'
         WHERE s.setting_key = 'aml_freeze_target_hours'
           AND NOT EXISTS (SELECT 1 FROM system_settings n WHERE n.setting_key = 'aml_escalation_target_hours');
        UPDATE system_settings s SET setting_key = 'aml_report_target_hours'
         WHERE s.setting_key = 'aml_freeze_report_target_hours'
           AND NOT EXISTS (SELECT 1 FROM system_settings n WHERE n.setting_key = 'aml_report_target_hours');
    END IF;
END $$;

-- 3. One active STR case link per screening hit (last guard against a double case; the page also
--    takes a lock). Created only when no hit is linked twice today; otherwise a notice is raised and
--    the duplicates must be unlinked on the case page first (nothing is changed automatically).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'uq_aml_sar_links_one_case_per_hit') THEN
        IF EXISTS (SELECT target_id FROM aml_sar_links
                    WHERE link_type = 'screening_hit' AND unlinked_at IS NULL
                    GROUP BY target_id HAVING count(*) > 1) THEN
            RAISE NOTICE 'uq_aml_sar_links_one_case_per_hit NOT created: a screening hit is linked to more than one case';
        ELSE
            CREATE UNIQUE INDEX uq_aml_sar_links_one_case_per_hit ON aml_sar_links (target_id)
                WHERE link_type = 'screening_hit' AND unlinked_at IS NULL;
        END IF;
    END IF;
END $$;

-- 4. Periodic reviews: the customers date columns are TEXT. aml_safe_date() reads one (first 10
--    characters, ISO) and returns NULL for anything that is not a valid date, so the due dates can be
--    computed, filtered and limited in SQL.
CREATE OR REPLACE FUNCTION aml_safe_date(v TEXT) RETURNS DATE
    LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF v IS NULL OR v !~ '^\s*[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN
        RETURN NULL;
    END IF;
    RETURN substr(btrim(v), 1, 10)::date;
EXCEPTION WHEN others THEN
    RETURN NULL;
END $$;

-- the columns the periodic review reads (all present in production on 2026-11-05; kept for other installs)
ALTER TABLE customers ADD COLUMN IF NOT EXISTS last_review_date TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS next_review_date TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS risk_classification_date TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS onboarding_date TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS is_high_risk_country INTEGER DEFAULT 0;

-- 5. High-risk countries page: a new row is active unless said otherwise (existing rows unchanged).
ALTER TABLE high_risk_countries ALTER COLUMN is_active SET DEFAULT 1;

GRANT SELECT, INSERT, UPDATE ON aml_freeze_log TO complynex;
GRANT SELECT, INSERT, UPDATE, DELETE ON high_risk_countries TO complynex;
GRANT USAGE, SELECT ON SEQUENCE high_risk_countries_id_seq TO complynex;
GRANT EXECUTE ON FUNCTION aml_safe_date(TEXT) TO complynex;

COMMIT;
