# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

"""
Regenerate the seed block of database/migrations/20261018_regcontrols.sql from
regcontrols/library.py.

    python scripts/regcontrols_seed_sql.py           # rewrite the block in place
    python scripts/regcontrols_seed_sql.py --check   # exit 1 if the block is stale

Seed INSERTs use ON CONFLICT DO NOTHING, so re-running the migration never
overwrites a control or parameter Compliance has since edited in the UI.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from regcontrols import library  # noqa: E402

MIGRATION = os.path.join(ROOT, 'database', 'migrations', '20261018_regcontrols.sql')
BEGIN, END = '-- @@SEED-BEGIN@@', '-- @@SEED-END@@'


def q(v):
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    return "'" + str(v).replace("'", "''") + "'"


def arr(values):
    if not values:
        return "'{}'::text[]"
    return 'ARRAY[' + ', '.join(q(v) for v in values) + ']::text[]'


def build_seed():
    out = ['-- Control library (FRA control map). Generated — do not edit by hand.']
    for c in library.CONTROLS:
        out.append(
            'INSERT INTO rc_controls (control_code, area, title_en, title_ar, requirement_en, control_type, '
            'type_codes, frequency, criticality, owner_role, linked_module, linked_params, licence_types, '
            'test_procedure_en) VALUES ('
            + ', '.join([q(c['code']), q(c['area']), q(c['title_en']), q(c['title_ar']), q(c['requirement_en']),
                         q(c['control_type']), q(c['type_codes']), q(c['frequency']), q(c['criticality']),
                         q(c['owner_role']), q(c['linked_module']), arr(c['linked_params']),
                         arr(c['licence_types']), q(c['test_procedure_en'])])
            + ') ON CONFLICT (control_code) DO NOTHING;')
    out.append('')
    out.append('-- Regulatory parameters. NULL value + needs_review = waiting for Compliance to confirm.')
    for p in library.PARAMETERS:
        out.append(
            'WITH ins AS (INSERT INTO rc_parameters (param_key, licence_type, value_text, value_type, unit, '
            'legal_reference, description_en, description_ar, needs_review, review_note, approved_at) VALUES ('
            + ', '.join([q(p['key']), q(p['licence_type']), q(p['value']), q(p['value_type']), q(p['unit']),
                         q(p['legal_reference']), q(p['description_en']), q(p['description_ar']),
                         q(p['needs_review']), q(p['review_note'])])
            + ', CURRENT_TIMESTAMP) ON CONFLICT (param_key, licence_type, effective_from) DO NOTHING '
            'RETURNING id, param_key, licence_type, value_text, value_type, unit, effective_from) '
            'INSERT INTO rc_parameter_changes (parameter_id, param_key, licence_type, change_type, new_value, '
            'value_type, unit, effective_from, reason, status, decided_at, applied_parameter_id) '
            "SELECT id, param_key, licence_type, 'create', value_text, value_type, unit, effective_from, "
            "'Initial seed from the FRA control map', 'approved', CURRENT_TIMESTAMP, id FROM ins;")
    return '\n'.join(out)


def render(sql_text):
    start = sql_text.index(BEGIN) + len(BEGIN)
    end = sql_text.index(END)
    return sql_text[:start] + '\n' + build_seed() + '\n' + sql_text[end:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    with open(MIGRATION, encoding='utf-8') as fh:
        current = fh.read()
    wanted = render(current)
    if args.check:
        if wanted != current:
            print('regcontrols seed block is stale — run scripts/regcontrols_seed_sql.py')
            return 1
        print('regcontrols seed block is up to date')
        return 0
    with open(MIGRATION, 'w', encoding='utf-8') as fh:
        fh.write(wanted)
    print(f'wrote {len(library.CONTROLS)} controls and {len(library.PARAMETERS)} parameters')
    return 0


if __name__ == '__main__':
    sys.exit(main())
