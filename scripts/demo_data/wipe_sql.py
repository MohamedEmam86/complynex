#!/usr/bin/env python3
"""Print the SQL that empties a DEMO database back to reference data only.

Run by scripts/demo_data/reset.sh (piped into psql as the database owner).
Reference tables (regulatory library, frameworks, list sources, emission
factors, categories, settings...) are kept; everything a company records is
emptied, then dangling references from kept tables are cleared.
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))
from utils.demo import is_demo  # noqa: E402

KEEP = {
    # academy course content (learners are wiped)
    'academy_courses', 'academy_lessons', 'academy_questions', 'academy_settings', 'academy_rejected_domains',
    # assistant configuration
    'ai_intents', 'ai_playbook_steps', 'ai_playbooks',
    # workflow and module configuration
    'aml_role_conflict_rules', 'approval_workflow_stages', 'approval_workflows', 'case_escalation_settings',
    'case_sla_config', 'complaint_categories', 'consent_purposes', 'document_types', 'ekyc_config',
    'email_templates', 'event_routing_rules', 'high_risk_countries', 'kyc_fields', 'kyc_risk_bands',
    'kyc_risk_factors', 'numbering_sequences', 'ongoing_screening_config', 'org_unit_types',
    'policy_categories', 'red_flags', 'required_policies', 'risk_categories', 'risk_scoring_bands',
    'str_report_templates', 'system_settings', 'tm_rules', 'whistleblowing_categories', 'board_roles',
    'training_courses', 'training_questions', 'training_requirements', 'pr_key_function_types', 'pr_branch_roles',
    # ESG / carbon reference content
    'carbon_emission_factors', 'esg_frameworks', 'esg_indicators', 'esg_pillars',
    'esg_materiality_topics', 'fra_verifiers',
    # regulatory library and packs
    'rc_areas', 'rc_calendar_reminders', 'rc_control_requirements', 'rc_controls', 'rc_frameworks',
    'rc_licence_types', 'rc_owner_roles', 'rc_packs', 'rc_parameters', 'rc_requirements',
    'regulators', 'regulatory_reports',
    # sanctions list sources and engine quality (public lists, not company data)
    'sanctions_lists', 'screening_config', 'screening_data_sources', 'screening_settings',
    'screening_list_update_log', 'screening_update_logs', 'screening_update_log', 'screening_risk_criteria',
    'data_source_urls', 'data_update_audit_log', 'screening_quality_runs', 'screening_qa_cases',
    'screening_qa_runs', 'screening_watchlist',
}
INTERNAL_SOURCES = ('internal_blacklist', 'internal_pep')


def _meta():
    import psycopg2
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute("""SELECT tablename FROM pg_tables WHERE schemaname = 'public'
                   AND tablename NOT LIKE 'pg\\_%' ORDER BY 1""")
    tables = [r[0] for r in cur.fetchall()]
    cur.execute("""SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, a.attnotnull
                   FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                   WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace""")
    fks = cur.fetchall()
    cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                   WHERE table_schema = 'public' AND column_default LIKE 'nextval(%%'""")
    seqs = cur.fetchall()
    conn.close()
    return tables, fks, seqs


def main(mode):
    """wipe: empty every table (reference tables are re-copied from the main
    instance right after); keep: list the reference tables to copy; fix: clear
    references from reference rows to removed rows and reset id sequences."""
    if not is_demo():
        sys.exit('refused: not a demo instance (no .demo_instance file)')
    tables, fks, seqs = _meta()
    keep = [t for t in tables if t in KEEP and t != 'screening_watchlist']
    if mode == 'keep':
        print('\n'.join(keep))
        return
    if mode == 'wipe':
        out = ["BEGIN;"]
        out += [f'DELETE FROM "{t}";' for t in tables if t != 'screening_watchlist']
        out.append("DELETE FROM screening_watchlist WHERE source IN ('internal_blacklist', 'internal_pep');")
        out.append("COMMIT;")
    else:
        out = ["BEGIN;"]
        for t, col, ref, notnull in fks:
            if t in KEEP and ref not in KEEP and not notnull:
                out.append(f'UPDATE "{t}" SET "{col}" = NULL WHERE "{col}" IS NOT NULL;')
        for t, c in seqs:
            out.append(f"SELECT setval(pg_get_serial_sequence('\"{t}\"', '{c}'), "
                       f"COALESCE((SELECT max(\"{c}\") FROM \"{t}\"), 0) + 1, false);")
        out.append("COMMIT;")
    print("\n".join(out))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'wipe')
