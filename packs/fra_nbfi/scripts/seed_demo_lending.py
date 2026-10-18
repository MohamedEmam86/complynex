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
FRA NBFI pack — demo data for Lending Conduct & Portfolio: a FICTIONAL
microfinance company ("Nile Microfinance S.A.E."). Every name, reference and
figure is invented. Use only on demo / test installations. Enables the
fra_nbfi pack if it is not enabled yet.

    python packs/fra_nbfi/scripts/seed_demo_lending.py                        # data only
    python packs/fra_nbfi/scripts/seed_demo_lending.py --with-demo-parameters # also fill unset lending parameters

--with-demo-parameters writes ILLUSTRATIVE values into lending parameters that
are still empty, marked needs_review with the note "DEMO VALUE". Never run it
on a production installation: those numbers are not regulatory values.

The data contains deliberate breaches so every lending check has something
to find: unsigned contracts, missing GPS / receipt / credit study, copied
credit-study figures, fees above the caps, an early repayment without consent
followed by a costlier loan, a client above the revenue ceiling, a branch with
high PAR, and loans without follow-up visits.
"""
import argparse
import json
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

DEMO_PARAMS = {
    'lending.max_client_monthly_revenue': '50000', 'lending.max_project_size': '500000',
    'lending.gps_mandatory_min_amount': '30000', 'lending.followup_visit_days': '30',
    'portfolio.par30_threshold_pct': '5', 'lending.min_cost_lines': '3', 'lending.max_dsr_pct': '50',
    'lending.admin_fee_cap_pct': '3', 'lending.admin_fee_tiers': '[{"max_amount": 20000, "cap_pct": 3}, {"max_amount": null, "cap_pct": 2}]',
    'lending.late_penalty_rate_pct': '2', 'lending.late_penalty_cap_pct': '10', 'lending.transfer_fee_cap': '100',
    'lending.rescheduling_fee_cap': '250', 'lending.prepay_new_loan_window_days': '30',
    'aml.unusual_txn_study_sla_days': '15',
}

FIRST = ['Ahmed', 'Mona', 'Karim', 'Sara', 'Hassan', 'Nour', 'Omar', 'Laila', 'Youssef', 'Heba', 'Tarek', 'Dina',
         'Mahmoud', 'Rania', 'Sherif', 'Yasmin', 'Adel', 'Salma', 'Walid', 'Hala']
LAST = ['Demo-Farouk', 'Demo-Saleh', 'Demo-Nabil', 'Demo-Fathy', 'Demo-Rashad', 'Demo-Zaki']


def build(today):
    rnd = random.Random(2026)
    branches = ['NM-CAI-01', 'NM-GIZ-02', 'NM-ASY-03']
    officers = {'NM-CAI-01': ['OF-11', 'OF-12'], 'NM-GIZ-02': ['OF-21', 'OF-22'], 'NM-ASY-03': ['OF-31']}
    clients, loans, contracts, docs, studies, inst, visits, ers, resched, transfers = ([] for _ in range(10))
    for n in range(1, 37):
        cref = f'NMF-C{n:04d}'
        clients.append({'client_ref': cref, 'full_name': f'{rnd.choice(FIRST)} {rnd.choice(LAST)} (demo)',
                        'national_id': f'DEMO{n:010d}', 'gender': rnd.choice(['male', 'female']),
                        'governorate': rnd.choice(['Cairo', 'Giza', 'Assiut']), 'business_activity': 'Retail (demo)',
                        'monthly_revenue': str(rnd.randrange(8000, 40000, 500)), 'project_size': str(rnd.randrange(50000, 300000, 5000))})
        branch = branches[n % 3]
        officer = rnd.choice(officers[branch])
        amount = rnd.choice([10000, 15000, 25000, 40000, 60000])
        disb = today - timedelta(days=rnd.randrange(60, 330))
        lref = f'NMF-L{n:05d}'
        loans.append({'loan_ref': lref, 'client_ref': cref, 'product_code': 'NM-MICRO', 'amount': str(amount),
                      'tenor_months': '12', 'interest_rate_pct': '24', 'apr_pct': '32',
                      'admin_fee_amount': str(round(amount * 0.018, 2)), 'branch_code': branch, 'officer_code': officer,
                      'status': 'disbursed', 'application_date': str(disb - timedelta(days=10)),
                      'approval_date': str(disb - timedelta(days=3)), 'disbursement_date': str(disb),
                      'outstanding_principal': str(round(amount * 0.6, 2)),
                      'gps_lat': '30.0444' if amount > 30000 else '', 'gps_lng': '31.2357' if amount > 30000 else ''})
        contracts.append({'loan_ref': lref, 'contract_no': f'CT-{n:05d}', 'contract_date': str(disb),
                          'signed_by_lender': 'yes', 'lender_signed_at': str(disb), 'signed_by_client': 'yes',
                          'client_signed_at': str(disb), 'penalty_clause_rate_pct': '2', 'penalty_clause_cap_pct': '10'})
        for dt in ('national_id', 'contract', 'receipt_acknowledgement', 'credit_study'):
            docs.append({'loan_ref': lref, 'doc_type': dt, 'received_date': str(disb)})
        rev = rnd.randrange(9000, 30000, 250)
        studies.append({'loan_ref': lref, 'study_date': str(disb - timedelta(days=7)), 'officer_code': officer,
                        'monthly_revenue': str(rev), 'monthly_costs_total': str(int(rev * 0.55)),
                        'household_expenses': str(rnd.randrange(2000, 5000, 50)), 'other_debt_service': '0',
                        'net_income': str(int(rev * 0.3)), 'dsr_pct': '25',
                        'cost_lines': json.dumps([{'label': 'stock', 'amount': int(rev * 0.35)},
                                                  {'label': 'rent', 'amount': int(rev * 0.12)},
                                                  {'label': 'transport', 'amount': int(rev * 0.08)}])})
        for k in range(1, 13):
            due = disb + timedelta(days=30 * k)
            paid = due <= today
            inst.append({'loan_ref': lref, 'seq': str(k), 'due_date': str(due), 'principal_due': str(round(amount / 12, 2)),
                         'interest_due': str(round(amount * 0.02, 2)),
                         'paid_amount': str(round(amount / 12 + amount * 0.02, 2)) if paid else '0',
                         'paid_date': str(due) if paid else '', 'status': 'paid' if paid else 'due'})
        visits.append({'loan_ref': lref, 'planned_date': str(disb + timedelta(days=20)),
                       'visit_date': str(disb + timedelta(days=21)), 'officer_code': officer, 'outcome': 'ok'})

    def L(n):
        return next(l for l in loans if l['loan_ref'] == f'NMF-L{n:05d}')

    # --- deliberate breaches -------------------------------------------------
    next(c for c in contracts if c['loan_ref'] == 'NMF-L00002').update(signed_by_client='no', client_signed_at='')   # FRA-009
    L(3).update(amount='60000', gps_lat='', gps_lng='')                                                               # FRA-013
    docs[:] = [d for d in docs if not (d['loan_ref'] == 'NMF-L00004' and d['doc_type'] == 'receipt_acknowledgement')]  # FRA-014
    studies[:] = [s for s in studies if s['loan_ref'] != 'NMF-L00005']                                               # FRA-015
    for n in (6, 9, 12):                                                                                            # FRA-016 copied figures
        s = next(s for s in studies if s['loan_ref'] == f'NMF-L{n:05d}')
        s.update(officer_code='OF-11', monthly_revenue='20000', monthly_costs_total='11000', household_expenses='3000',
                 cost_lines=json.dumps([{'label': 'stock', 'amount': 11000}]))
    L(7).update(admin_fee_amount='1500')                                                                              # FRA-017/018 (10,000 x 15%)
    L(8).update(amount='40000', admin_fee_amount='1000', gps_lat='30.1', gps_lng='31.3')                               # FRA-018 tier only (2.5% > 2%)
    clients[9].update(monthly_revenue='85000')                                                                        # FRA-004
    late = next(i for i in inst if i['loan_ref'] == 'NMF-L00011' and i['seq'] == '2')                                 # FRA-020
    late.update(penalty_charged='900', paid_date=str(date.fromisoformat(late['due_date']) + timedelta(days=20)))
    resched.append({'loan_ref': 'NMF-L00013', 'resched_date': str(today - timedelta(days=40)), 'fee_amount': '600',
                    'old_tenor': '12', 'new_tenor': '18', 'reason': 'demo'})                                         # FRA-026
    transfers.append({'loan_ref': 'NMF-L00014', 'transfer_date': str(today - timedelta(days=35)), 'instalments_moved': '1',
                      'fee_amount': '300'})                                                                          # FRA-025
    # FRA-021–024: early repayment without consent, then a costlier loan 12 days later
    er_day = today - timedelta(days=50)
    L(15).update(status='closed', outstanding_principal='0')
    ers.append({'loan_ref': 'NMF-L00015', 'settlement_amount': '9000', 'prepayment_fee': '200',
                'request_date': str(er_day), 'executed_date': str(er_day), 'disclosure_given': 'no',
                'consent_signed': 'no', 'cost_acknowledged': 'no'})
    loans.append(dict(L(15), loan_ref='NMF-L00915', status='disbursed', apr_pct='41', amount='20000',
                      admin_fee_amount='500', application_date=str(er_day + timedelta(days=10)),
                      disbursement_date=str(er_day + timedelta(days=12)), outstanding_principal='18000', gps_lat='', gps_lng=''))
    for dt in ('national_id', 'contract', 'receipt_acknowledgement', 'credit_study'):
        docs.append({'loan_ref': 'NMF-L00915', 'doc_type': dt, 'received_date': str(er_day + timedelta(days=12))})
    contracts.append(dict(next(c for c in contracts if c['loan_ref'] == 'NMF-L00015'), loan_ref='NMF-L00915'))
    studies.append(dict(next(s for s in studies if s['loan_ref'] == 'NMF-L00016'), loan_ref='NMF-L00915'))
    # FRA-011/012: Assiut branch arrears — unpaid instalments for several loans
    for l in loans:
        if l['loan_ref'] in ('NMF-L00021', 'NMF-L00024', 'NMF-L00027', 'NMF-L00030'):
            for i in inst:
                if i['loan_ref'] == l['loan_ref'] and date.fromisoformat(i['due_date']) > today - timedelta(days=95):
                    i.update(paid_amount='0', paid_date='', status='due')
    # FRA-010: no follow-up visit for two loans
    visits[:] = [v for v in visits if v['loan_ref'] not in ('NMF-L00017', 'NMF-L00018')]
    return {'clients': clients, 'loans': loans, 'contracts': contracts, 'documents': docs, 'credit_studies': studies,
            'instalments': inst, 'visits': visits, 'early_repayments': ers, 'reschedulings': resched,
            'transfers': transfers}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--with-demo-parameters', action='store_true')
    args = ap.parse_args()
    from app import create_app
    from database.db import get_db
    from packs.fra_nbfi.lending import importer
    from regcontrols import packs
    app = create_app()
    with app.app_context():
        db = get_db()
        if not packs.is_enabled('fra_nbfi'):
            print('enabling the fra_nbfi pack:', packs.enable('fra_nbfi'))
        if db.execute("SELECT EXISTS (SELECT 1 FROM ln_loans WHERE source <> 'demo') AS x").fetchone()['x']:
            print('Real lending data exists — refusing to add demo data to this installation.')
            return 1
        db.execute("""INSERT INTO ln_products (code, name_en, name_ar, licence_type, required_docs)
                      VALUES ('NM-MICRO', 'Micro-enterprise loan (demo)', 'تمويل مشروع متناهي الصغر (تجريبي)',
                              'microfinance', '{national_id}') ON CONFLICT (code) DO NOTHING""")
        db.commit()
        if args.with_demo_parameters:
            from models.settings import Settings
            if (Settings.get('rc_licence_type', 'all') or 'all') == 'all':
                Settings.set('rc_licence_type', 'microfinance', 'Licence type used to select regulatory parameter values')
                print('  licence type set to microfinance (demo)')
            for key, value in DEMO_PARAMS.items():
                n = db.execute("""UPDATE rc_parameters SET value_text = %s, needs_review = TRUE,
                                  review_note = 'DEMO VALUE — illustrative only, not a regulatory value'
                                  WHERE param_key = %s AND value_text IS NULL AND status = 'active'""",
                               (value, key)).rowcount
                print(f'  {key}: {"set" if n else "kept existing value"}')
            db.commit()
        for kind, rows in build(date.today()).items():
            b = importer.import_rows(kind, rows, source='demo')
            print(f'{kind}: {b["rows_ok"]} ok, {b["rows_failed"]} failed {b["errors"][:3] if b["errors"] else ""}')
        from packs.fra_nbfi.lending.checks import lending_sweep
        print('sweep:', lending_sweep())
    return 0


if __name__ == '__main__':
    sys.exit(main())
