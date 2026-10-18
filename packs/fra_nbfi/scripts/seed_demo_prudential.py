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
Demo data for the prudential, governance & financial-reporting registers —
FICTIONAL company "Nile Microfinance S.A.E.". Every name, address, lender and
figure is invented. Use only on demo / test installations. Enables the
fra_nbfi pack if it is not enabled yet.

    python packs/fra_nbfi/scripts/seed_demo_prudential.py                        # data only
    python packs/fra_nbfi/scripts/seed_demo_prudential.py --with-demo-parameters # --no-demo-parameters keeps parameters empty

It flags the installation as the fictional demo tenant and fills every empty
pack parameter with an ILLUSTRATIVE value (packs/fra_nbfi/demo.py, marked
"DEMO VALUE"); --no-demo-parameters skips that. Never run it on a production
installation: those numbers are not regulatory values.

Deliberate gaps so every check has something to find: paid-up capital below
the minimum and not yet registered, an extended capital-increase deadline
inside the alert window and an overdue licence renewal, leverage above the
ceiling, a letter with an old address, a vacant and an un-notified key
function, a branch manager without no-objection and a long vacancy, a branch
below the loan-officer minimum, a stale balance confirmation, under-booked
accrued interest, an unescalated default, a rescheduling without approval, a
capital contribution paid by someone else, exiting-shareholder dues booked as
equity, an ECL study due for refresh and no deferred-tax study.
"""
import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

COMPANY = 'Nile Microfinance S.A.E.'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--with-demo-parameters', action='store_true', help='(default; kept for compatibility)')
    ap.add_argument('--no-demo-parameters', action='store_true', help='leave the regulatory parameters empty')
    args = ap.parse_args()
    from app import create_app
    from database.db import get_db
    from regcontrols import packs
    app = create_app()
    with app.app_context():
        db = get_db()
        from prudential import service as S
        prof = S.profile(db)
        if prof.get('legal_name_en') and prof['legal_name_en'] != COMPANY:
            print('A real corporate profile exists — refusing to add demo data to this installation.')
            return 1
        if not packs.is_enabled('fra_nbfi'):
            print('enabling the fra_nbfi pack:', packs.enable('fra_nbfi'))
        from packs.fra_nbfi import demo
        demo.mark_demo_tenant()
        if not args.no_demo_parameters:
            filled = demo.apply_demo_parameters(db)
            print(f"  demo parameter values: {sum(v == 'set' for v in filled.values())} set (marked 'DEMO VALUE')")
        uid = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()['id']
        t = date.today()
        d = lambda days: t + timedelta(days=days)  # noqa: E731
        if db.execute("SELECT count(*) AS n FROM pr_capital_events").fetchone()['n']:
            print('Demo data already present.')
            return 0
        S.save_profile({'legal_name_en': COMPANY, 'legal_name_ar': 'النيل للتمويل متناهي الصغر ش.م.م (شركة وهمية)',
                        'registered_address_en': '12 Example Street, Nasr City, Cairo',
                        'registered_address_ar': '12 شارع المثال، مدينة نصر، القاهرة',
                        'commercial_register_no': 'CR-DEMO-0001', 'tax_card_no': 'TX-DEMO-0001',
                        'licence_number': 'DEMO-LIC-01', 'licence_type': 'microfinance',
                        'address_aliases': '12 Example St., Nasr City, Cairo'}, uid, db)
        S.add_document({'doc_type': 'board_minutes', 'title': 'Board minutes Q1 (demo)', 'doc_date': str(d(-120)),
                        'address_on_document': '12 Example St, Nasr City, Cairo'}, uid, db)
        S.add_document({'doc_type': 'letter', 'title': 'Letter to the regulator — branch opening (demo)',
                        'doc_date': str(d(-40)), 'address_on_document': '5 Old Demo Road, Dokki, Giza'}, uid, db)
        for ct, amt, days, ref in [('authorised', 50_000_000, -900, 'EGM 2024 (demo)'),
                                   ('issued', 20_000_000, -900, 'EGM 2024 (demo)'),
                                   ('paid_up', 10_000_000, -900, 'Bank certificate (demo)'),
                                   ('registered', 10_000_000, -880, 'Registry extract (demo)'),
                                   ('paid_up', 15_000_000, -30, 'Bank certificate 2 (demo)')]:
            S.add_capital_event({'capital_type': ct, 'amount': amt, 'effective_date': str(d(days)), 'reference': ref},
                                uid, db)
        reg = db.execute("SELECT id FROM regulators WHERE regulator_code = 'FRA'").fetchone()
        rid = reg['id'] if reg else None
        cap = S.save_deadline({'title': 'Complete the capital increase to the licence minimum (demo)',
                               'category': 'capital_increase', 'regulator_id': rid, 'due_date': str(d(-60)),
                               'owner_user_id': uid}, uid, db=db)
        S.add_extension(cap, {'extension_type': 'special', 'granted_on': str(d(-70)), 'new_due_date': str(d(25)),
                              'letter_ref': 'REG-EXT-001 (demo)'}, uid, db)
        S.save_deadline({'title': 'Licence renewal file (demo)', 'category': 'licence', 'regulator_id': rid,
                         'due_date': str(d(-3)), 'owner_user_id': uid}, uid, db=db)
        for q, (a, l, e) in enumerate([(120e6, 95e6, 25e6), (135e6, 112e6, 23e6), (150e6, 128e6, 22e6),
                                       (170e6, 152e6, 18e6)]):
            pe = [date(t.year - 1, 3, 31), date(t.year - 1, 6, 30), date(t.year - 1, 9, 30), date(t.year - 1, 12, 31)][q]
            pid = S.save_period({'period_end': str(pe), 'period_type': 'quarter', 'total_assets': a,
                                 'total_liabilities': l, 'equity': e, 'paid_up_capital': 15e6, 'capital_base': e * 0.9,
                                 'loan_portfolio': a * 0.8}, uid, db=db)
            db.execute("UPDATE pr_financial_periods SET status = 'approved', approved_at = now() WHERE id = %s", (pid,))
        db.commit()
        for code, holder, notified, fp, no in [('ceo', 'Hany Demo-Mansour', d(-400), 'passed', 'not_required'),
                                               ('cfo', 'Rasha Demo-Kamal', None, 'passed', 'not_required'),
                                               ('risk_head', 'Ali Demo-Fawzy', d(-200), 'passed', 'not_required'),
                                               ('internal_audit_head', 'Mai Demo-Lotfy', d(-150), 'pending', 'not_required'),
                                               ('mlro', 'Samir Demo-Adel', d(-20), 'passed', 'pending')]:
            S.save_key_function({'function_code': code, 'holder_name': holder, 'appointed_on': str(d(-500)),
                                 'regulator_notified_on': str(notified) if notified else '', 'fit_proper_status': fp,
                                 'no_objection_status': no}, uid, db=db)
        # compliance_head stays vacant
        for code, name, mgr, no, vacant in [('NM-CAI-01', 'Cairo branch (demo)', 'Tamer Demo-Hosny', 'granted', None),
                                            ('NM-GIZ-01', 'Giza branch (demo)', 'Nadia Demo-Samy', 'pending', None),
                                            ('NM-ALX-01', 'Alexandria branch (demo)', None, 'pending', d(-75))]:
            bid = S.save_branch({'code': code, 'name_en': name, 'status': 'planned', 'manager_name': mgr or '',
                                 'manager_no_objection': no, 'manager_vacant_since': str(vacant) if vacant else ''},
                                uid, db=db)
            db.execute("UPDATE pr_branches SET status = 'active', opened_on = %s WHERE id = %s", (d(-700), bid))
            S.set_staffing(bid, {'branch_manager': 1 if mgr else 0,
                                 'loan_officer': {'NM-CAI-01': 4, 'NM-GIZ-01': 2, 'NM-ALX-01': 3}[code]}, db)
        db.commit()
        for f in [
            {'reference': 'FAC-001', 'lender_name': 'Example Bank One (demo)', 'balance': 40e6, 'interest_rate_pct': 18,
             'last_confirmation_date': str(d(-200)), 'confirmation_balance': 40e6, 'accrual_from': str(d(-90)),
             'booked_as_of': str(d(-1)), 'accrued_booked': 1_750_000},
            {'reference': 'FAC-002', 'lender_name': 'Example Development Fund (demo)', 'balance': 30e6,
             'interest_rate_pct': 12, 'last_confirmation_date': str(d(-20)), 'confirmation_balance': 30e6,
             'accrual_from': str(d(-60)), 'booked_as_of': str(d(-1)), 'accrued_booked': 200_000},
            {'reference': 'FAC-003', 'lender_name': 'Example Bank Two (demo)', 'balance': 12e6, 'interest_rate_pct': 20,
             'status': 'default', 'last_confirmation_date': str(d(-30)), 'confirmation_balance': 12e6,
             'accrual_from': str(d(-30)), 'booked_as_of': str(d(-1)), 'accrued_booked': 190_000},
            {'reference': 'FAC-004', 'lender_name': 'Example Leasing Partner (demo)', 'balance': 8e6,
             'interest_rate_pct': 16, 'status': 'rescheduled', 'rescheduled_on': str(d(-45)),
             'last_confirmation_date': str(d(-15)), 'confirmation_balance': 8e6, 'accrual_from': str(d(-30)),
             'booked_as_of': str(d(-1)), 'accrued_booked': 102_000},
        ]:
            S.save_facility(f, uid, db=db)
        sh = S.save_related_party({'name': 'Delta Demo Holdings', 'relation': 'shareholder', 'ownership_pct': 60}, uid, db)
        ex = S.save_related_party({'name': 'Karim Demo-Wahba', 'relation': 'exiting_shareholder', 'ownership_pct': 0,
                                   'exited_on': str(d(-100))}, uid, db)
        S.add_rp_item(sh, {'item_type': 'capital_contribution', 'amount': 5e6, 'item_date': str(d(-30)),
                           'payer_name': 'Omar Demo-Saleh'}, uid, db)
        S.add_rp_item(ex, {'item_type': 'dues', 'amount': 1.2e6, 'item_date': str(d(-90)), 'classification': 'equity',
                           'payer_name': ''}, uid, db)
        sid = S.save_study({'study_type': 'ecl', 'title': 'ECL model and study (demo)', 'period_end': str(d(-430)),
                            'prepared_by': 'Example Advisory (demo)'}, uid, db)
        db.execute("""UPDATE pr_studies SET status = 'approved', approved_on = %s, approved_by_body = 'Board (demo)',
                      next_refresh_date = %s WHERE id = %s""", (d(-420), d(-55), sid))
        db.commit()
        print('prudential demo data loaded for', COMPANY)
        print('deadline sweep:', S.deadline_sweep(db))
    return 0


if __name__ == '__main__':
    sys.exit(main())
