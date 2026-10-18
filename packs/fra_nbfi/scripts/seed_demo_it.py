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
Demo data for IT / cyber / business-continuity evidence — FICTIONAL company
"Nile Microfinance S.A.E.". Every name, domain and figure is invented. Use
only on demo / test installations. Enables the fra_nbfi pack if needed.

    python packs/fra_nbfi/scripts/seed_demo_it.py [--with-demo-parameters]

Deliberate gaps: last DR test older than the limit and partial, one system
backed up on-site only and one stale backup, the freeze-order integration not
connected, an expired penetration test and no malware test, a WAF licence
expiring soon, an EDR without a data-residency attestation, an unreachable
demo domain (TLS check error), a maturity self-assessment below target and an
IT risk not reviewed. Domains use the reserved ".example" names, so the TLS
check reports them as unreachable — add a real domain to see a valid check.
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

DEMO_PARAMS = {'it.dr_test_max_age_months': '12', 'it.offsite_backup_max_age_days': '7',
               'it.risk_register_max_age_days': '180'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--with-demo-parameters', action='store_true')
    args = ap.parse_args()
    from app import create_app
    from database.db import get_db
    from regcontrols import packs
    app = create_app()
    with app.app_context():
        db = get_db()
        from cyber import resilience as R
        if db.execute("SELECT count(*) AS n FROM cy_bcp_sites").fetchone()['n']:
            print('IT resilience data already present — not adding demo data.')
            return 0
        if not packs.is_enabled('fra_nbfi'):
            print('enabling the fra_nbfi pack:', packs.enable('fra_nbfi'))
        if args.with_demo_parameters:
            for key, value in DEMO_PARAMS.items():
                db.execute("""UPDATE rc_parameters SET value_text = %s, needs_review = TRUE,
                              review_note = 'DEMO VALUE — illustrative only, not a regulatory value'
                              WHERE param_key = %s AND value_text IS NULL AND status = 'active'""", (value, key))
            db.commit()
        uid = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()['id']
        t, now = date.today(), datetime.now()
        R.save_site({'name': 'Head office data room (demo)', 'site_type': 'primary', 'location': 'Cairo'}, uid, db)
        dr = R.save_site({'name': 'DR site — Example Hosting (demo)', 'site_type': 'dr', 'location': '6th of October',
                          'provider': 'Example Hosting Co. (demo)', 'rto_hours': 8, 'rpo_hours': 4}, uid, db)
        R.add_dr_test({'site_id': dr, 'test_date': str(t - timedelta(days=430)), 'result': 'partial',
                       'scope': 'Core lending system switch-over', 'issues': 'Collections module not restored within RTO'},
                      uid, db)
        R.save_backup({'system_name': 'Core lending system (demo)', 'location_type': 'offsite', 'encrypted': '1',
                       'location_detail': 'DR site', 'last_success_at': now - timedelta(hours=20), 'last_status': 'success',
                       'last_restore_test': str(t - timedelta(days=90))}, db)
        R.save_backup({'system_name': 'Accounting system (demo)', 'location_type': 'onsite', 'encrypted': '0',
                       'last_success_at': now - timedelta(days=1), 'last_status': 'success'}, db)
        R.save_backup({'system_name': 'Document archive (demo)', 'location_type': 'cloud', 'encrypted': '1',
                       'last_success_at': now - timedelta(days=16), 'last_status': 'failed'}, db)
        R.save_integration({'code': 'sms_gateway', 'name': 'SMS gateway (demo)', 'counterparty': 'Example Telecom (demo)',
                            'status': 'live'}, uid, db)
        R.record_integration_exchange('sms_gateway', True, db)
        R.add_assessment({'assessment_type': 'pentest', 'title': 'External penetration test (demo)',
                          'provider': 'Example Security Labs (demo)', 'performed_on': str(t - timedelta(days=420)),
                          'valid_until': str(t - timedelta(days=55)), 'critical_open': 1}, uid, db)
        db.execute("UPDATE cy_assessments SET status = 'accepted' WHERE assessment_type = 'pentest'")
        R.add_assessment({'assessment_type': 'cis_benchmark', 'title': 'CIS benchmark — servers (demo)',
                          'provider': 'Internal IT', 'performed_on': str(t - timedelta(days=60)),
                          'valid_until': str(t + timedelta(days=300))}, uid, db)
        db.execute("UPDATE cy_assessments SET status = 'accepted' WHERE assessment_type = 'cis_benchmark'")
        db.commit()
        R.save_asset({'asset_type': 'waf', 'product': 'Example WAF (demo)', 'vendor': 'Example Vendor',
                      'licence_ref': 'WAF-DEMO-1', 'licence_expiry': str(t + timedelta(days=12))}, uid, db=db)
        R.save_asset({'asset_type': 'epp', 'product': 'Example Endpoint Protection (demo)', 'licence_ref': 'EPP-DEMO-1',
                      'licence_expiry': str(t + timedelta(days=200)), 'sends_data_abroad': '0', 'data_location': 'Egypt',
                      'residency_attested_on': str(t - timedelta(days=30)), 'residency_attested_by': 'Vendor letter'},
                     uid, db=db)
        R.save_asset({'asset_type': 'edr', 'product': 'Example EDR (demo)', 'licence_ref': 'EDR-DEMO-1',
                      'licence_expiry': str(t + timedelta(days=200))}, uid, db=db)
        R.add_domain('portal.nile-microfinance.example', uid, db=db)
        fw = db.execute("SELECT id FROM rc_frameworks WHERE code = 'FRA-ITGOV'").fetchone()
        if fw:
            aid = R.start_maturity(fw['id'], 'IT self-assessment 2026 (demo)', uid, db)
            levels = {s['requirement_id']: (2 if i % 3 else 3, 3, 'demo') for i, s in enumerate(R.maturity_scores(aid, db))}
            R.save_maturity(aid, levels, finalise=True, db=db)
        cat = db.execute("SELECT id FROM risk_categories WHERE category_code = 'TEC'").fetchone()
        if cat:
            for rid, title, last in [('RSK-IT-DEMO-1', 'Ransomware on core systems (demo)', t - timedelta(days=60)),
                                     ('RSK-IT-DEMO-2', 'Vendor lock-in of the core system (demo)', t - timedelta(days=400))]:
                db.execute("""INSERT INTO risks (risk_id, risk_title, category_id, likelihood, impact, inherent_risk_score,
                              last_review_date, next_review_date, status) VALUES (%s,%s,%s,3,4,12,%s,%s,'ACTIVE')
                              ON CONFLICT (risk_id) DO NOTHING""", (rid, title, cat['id'], last, last + timedelta(days=90)))
            db.commit()
        try:
            db.execute("""INSERT INTO policies (policy_number, policy_name, effective_date, status)
                          VALUES ('POL-IS-DEMO', 'Information security policy (demo)', %s, 'draft')
                          ON CONFLICT (policy_number) DO NOTHING""", (t - timedelta(days=200),))
            db.commit()
        except Exception:
            db.rollback()
        print('IT resilience demo data loaded. TLS sweep:', R.tls_sweep(db))
    return 0


if __name__ == '__main__':
    sys.exit(main())
