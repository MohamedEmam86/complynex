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
Demo data for carbon accounting — FICTIONAL company "Nile Microfinance S.A.E.".
All factors are DEMO values (illustrative, NOT official emission factors);
names, sites and figures are invented. Use only on demo / test installations.

    python packs/fra_nbfi/scripts/seed_demo_carbon.py [--no-demo-parameters]

Creates a closed 2025 period (not yet approved or verified) and an open 2026
period with monthly electricity and fuel data (one month missing, one unit
mismatch, one entry without evidence), a versioned grid factor, commuting via
the helper, three PCAF exposures (scores 2, 4, 5), intensity denominators,
an offset obligation past its deadline, and two reduction initiatives.
"""
import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

DEMO_SRC = 'DEMO factor — illustrative only, not an official value'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-demo-parameters', action='store_true')
    args = ap.parse_args()
    from app import create_app
    from database.db import get_db
    from regcontrols import packs
    app = create_app()
    with app.app_context():
        db = get_db()
        prof = db.execute("SELECT legal_name_en FROM corp_profile WHERE id = 1").fetchone()
        if prof and prof['legal_name_en'] and prof['legal_name_en'] != 'Nile Microfinance S.A.E.':
            print('A real corporate profile exists — refusing to add demo data to this installation.')
            return 1
        if db.execute("SELECT count(*) AS n FROM carbon_activity_entries").fetchone()['n']:
            print('Carbon data already present — not adding demo data.')
            return 0
        if not packs.is_enabled('fra_nbfi'):
            print('enabling the fra_nbfi pack:', packs.enable('fra_nbfi'))
        from packs.fra_nbfi import demo
        demo.mark_demo_tenant()
        if not args.no_demo_parameters:
            demo.apply_demo_parameters(db)
        from carbon import service as S
        uid = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()['id']
        y = date.today().year
        for label, s, e, st in [(f'FY{y - 1} (demo)', date(y - 1, 1, 1), date(y - 1, 12, 31), 'closed'),
                                (f'FY{y} (demo)', date(y, 1, 1), date(y, 12, 31), 'open')]:
            db.execute("INSERT INTO esg_reporting_periods (label, start_date, end_date, status) VALUES (%s,%s,%s,%s)",
                       (label, s, e, st))
        db.commit()
        p_prev = db.execute("SELECT id FROM esg_reporting_periods WHERE start_date = %s", (date(y - 1, 1, 1),)).fetchone()['id']
        p_cur = db.execute("SELECT id FROM esg_reporting_periods WHERE start_date = %s", (date(y, 1, 1),)).fetchone()['id']
        S.save_boundary({'consolidation_approach': 'equity_share', 'base_year': str(y - 1),
                         'recalculation_threshold_pct': '5',
                         'recalculation_policy': 'Recalculate the base year when structural or methodology changes move it '
                                                 'by more than 5 percent (demo policy).'}, uid, db)
        db.execute("UPDATE carbon_scope_config SET scope3_enabled = TRUE WHERE company_label = 'default'")
        db.commit()
        hq = S.save_entity({'name': 'Nile Microfinance S.A.E. (demo)', 'ownership_pct': '100', 'operational_control': '1',
                            'financial_control': '1', 'included': '1'}, db=db)
        jv = S.save_entity({'name': 'Delta Demo Collections JV', 'ownership_pct': '40', 'operational_control': '',
                            'financial_control': '', 'included': '1'}, db=db)
        s1 = S.save_site({'entity_id': hq, 'name': 'Head office — Nasr City (demo)', 'site_type': 'office', 'city': 'Cairo',
                          'floor_area_m2': '1200', 'headcount': '85'}, db=db)
        s2 = S.save_site({'entity_id': hq, 'name': 'Giza branch (demo)', 'site_type': 'branch', 'city': 'Giza',
                          'floor_area_m2': '300', 'headcount': '22'}, db=db)
        S.save_site({'entity_id': jv, 'name': 'Collections centre — JV (demo)', 'site_type': 'office', 'city': 'Alexandria',
                     'floor_area_m2': '400', 'headcount': '30'}, db=db)
        f = lambda code, data: S.publish_factor_version(code, dict(data, source=DEMO_SRC), uid, db)  # noqa: E731
        f('DEMO_GRID_ELEC', {'scope': 'scope2', 'category': 'Purchased electricity', 'activity': 'Grid electricity (demo)',
                             'unit': 'kWh', 'factor_kgco2e': '0.50', 'effective_from': str(date(y - 1, 1, 1)),
                             'vintage_year': str(y - 1)})
        f('DEMO_GRID_ELEC', {'factor_kgco2e': '0.47', 'effective_from': str(date(y, 1, 1)), 'vintage_year': str(y)})
        f('DEMO_DIESEL', {'scope': 'scope1', 'category': 'Stationary combustion', 'activity': 'Diesel — generators (demo)',
                          'unit': 'litre', 'factor_kgco2e': '2.7', 'effective_from': str(date(y - 1, 1, 1))})
        f('DEMO_COMMUTE', {'scope': 'scope3', 'category': 'Employee commuting', 'ghg_category_no': '7',
                           'activity': 'Commuting — mixed modes (demo)', 'unit': 'passenger-km', 'factor_kgco2e': '0.12',
                           'effective_from': str(date(y - 1, 1, 1))})
        f('DEMO_PCAF_MICRO', {'scope': 'scope3', 'category': 'Financed emissions', 'ghg_category_no': '15',
                              'activity': 'Micro-enterprise loans — per EGP m outstanding (demo)', 'unit': 'EGP m',
                              'factor_kgco2e': '12000', 'effective_from': str(date(y - 1, 1, 1))})
        f('DEMO_PCAF_TRADE', {'scope': 'scope3', 'category': 'Financed emissions', 'ghg_category_no': '15',
                              'activity': 'Retail trade — per EGP m revenue (demo)', 'unit': 'EGP m',
                              'factor_kgco2e': '30000', 'effective_from': str(date(y - 1, 1, 1))})
        last_month = date.today().replace(day=1) - timedelta(days=1)
        for pid, yr, months in [(p_prev, y - 1, range(1, 13)), (p_cur, y, range(1, last_month.month + 1 if last_month.year == y else 1))]:
            for m in months:
                if pid == p_cur and m == 2:
                    continue        # planted gap: February missing at the head office
                q = 18000 if pid == p_prev else (21000 if m != 3 else 52000)   # planted outlier in March
                S.add_entry(pid, {'factor_code': 'DEMO_GRID_ELEC', 'activity_month': f'{yr}-{m:02d}', 'site_id': s1,
                                  'quantity': str(q)}, uid, db)
                S.add_entry(pid, {'factor_code': 'DEMO_GRID_ELEC', 'activity_month': f'{yr}-{m:02d}', 'site_id': s2,
                                  'quantity': '5200'}, uid, db)
            S.add_entry(pid, {'factor_code': 'DEMO_DIESEL', 'activity_month': f'{yr}-06', 'site_id': s1, 'quantity': '900'},
                        uid, db)
            S.add_entry(pid, {'factor_code': 'DEMO_COMMUTE', 'activity_month': f'{yr}-12' if pid == p_prev else f'{yr}-01',
                              'helper': 'commuting', 'employees': '107', 'days_per_year': '220', 'one_way_km': '14'}, uid, db)
        S.add_entry(p_cur, {'factor_code': 'DEMO_DIESEL', 'activity_month': f'{y}-01', 'site_id': s2, 'quantity': '50',
                            'unit': 'kWh'}, uid, db)      # planted unit mismatch
        db.execute("""INSERT INTO generic_attachments (module, record_type, record_id, filename, file_path, uploaded_by, is_deleted)
                      SELECT 'carbon', 'carbon_entry', id, 'invoice-demo.pdf', 'demo/none', %s, 0
                      FROM carbon_activity_entries WHERE unit = 'kWh' AND scope = 'scope2'""", (uid,))
        db.commit()
        for pid in (p_prev, p_cur):
            S.save_exposure(pid, {'reference': 'PCAF-MICRO', 'borrower': 'Micro-enterprise book (demo)', 'asset_class': 'business_loans',
                                  'sector': 'mixed', 'method': 'asset', 'outstanding': '180000000', 'factor_code': 'DEMO_PCAF_MICRO'}, uid, db)
            S.save_exposure(pid, {'reference': 'PCAF-SME-01', 'borrower': 'Example Agro Trading (demo)', 'method': 'reported',
                                  'outstanding': '6000000', 'attribution_base': '40000000', 'borrower_emissions_tco2e': '850'}, uid, db)
            S.save_exposure(pid, {'reference': 'PCAF-SME-02', 'borrower': 'Example Retail Co. (demo)', 'method': 'revenue',
                                  'outstanding': '3000000', 'attribution_base': '12000000', 'borrower_revenue_egp': '25000000',
                                  'factor_code': 'DEMO_PCAF_TRADE'}, uid, db)
            S.save_metrics(pid, {'revenue_egp': '95000000', 'financed_portfolio_egp': '189000000'}, uid, db)
        S.save_initiative({'title': 'LED retrofit in all branches (demo)', 'scope': 'scope2', 'target_date': str(date(y, 12, 31)),
                           'expected_reduction_tco2e': '18', 'status': 'in_progress'}, uid, db)
        S.save_initiative({'title': 'Solar PV on head-office roof (demo)', 'scope': 'scope2', 'target_date': str(date(y + 1, 6, 30)),
                           'expected_reduction_tco2e': '40'}, uid, db)
        db.execute("""INSERT INTO carbon_targets (baseline_year, baseline_tco2e, target_2030_pct, target_2035_pct, notes, updated_by)
                      SELECT %s, 145, 30, 50, 'Demo target', %s WHERE NOT EXISTS (SELECT 1 FROM carbon_targets)""", (y - 1, uid))
        db.execute("""INSERT INTO carbon_offset_obligations (reporting_period_id, total_emissions_tco2e, offset_pct, required_tco2e,
                      report_submitted_date, deadline_date, status, created_by) VALUES (%s, 140, 20, 28, %s, %s, 'OPEN', %s)""",
                   (p_prev, date.today() - timedelta(days=120), date.today() - timedelta(days=30), uid))
        db.commit()
        print('carbon demo data loaded:', {k: v for k, v in S.inventory(p_cur, db)['totals'].items()})
    return 0


if __name__ == '__main__':
    sys.exit(main())
