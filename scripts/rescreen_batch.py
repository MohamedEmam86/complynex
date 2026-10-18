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
Ongoing re-screening: there is no existing scheduled re-screen anywhere in
this codebase (the only re-screening today is the manual "Run Screening"
button per customer/merchant), and as of 2026-07-14, 1688 of 1689 customers
have never been screened via this flow at all (last_screening_date is
NULL/blank) -- this is a backlog to clear, not routine staleness to refresh.

Each run screens up to BATCH_SIZE customers+merchants, prioritized
never-screened first, then oldest-screened first, and skips anything
screened within RESCREEN_AFTER_DAYS (steady-state throttle once the
backlog clears -- otherwise this would re-screen the entire base on every
run forever). BATCH_SIZE is deliberately conservative: this is a 2-core
box already showing ~1.9GB swap in use, and each screen_person() call costs
roughly 1.5-2.5s (see the P1/P2 investigation notes) even though the FAISS
index itself is offloaded to complynex-semantic.service over HTTP, not
reloaded per call.

Boots the Flask app once and loops in-process (not one job/process per
record, unlike the P1 event-dispatcher's forking RQ worker) -- that
dispatcher path was measured at ~10s of pure app/pool/ES/Redis boot
overhead per job, which would dominate a 1700-record batch.

Publishes 'screening.hit' via the P1 event bus on a high-risk match (the
onboarding screening path does this; the existing manual re-screen buttons
in aml/routes.py and merchant_kyc/routes.py do not -- this batch matches
the onboarding path's behavior since silent re-screening hits would
otherwise never reach a compliance officer).

Only the primary name (full_name/company_name/merchant_name) is screened,
not the Arabic-name variant the manual customer re-screen button also
screens -- a deliberate scope cut trading per-record thoroughness for
breadth given the box's resource constraints; the manual button remains
available for a more thorough one-off screen.

Safe to run manually: python scripts/rescreen_batch.py
"""
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BATCH_SIZE = int(os.environ.get('RESCREEN_BATCH_SIZE', '15'))
RESCREEN_AFTER_DAYS = int(os.environ.get('RESCREEN_AFTER_DAYS', '30'))
SLEEP_BETWEEN_SEC = float(os.environ.get('RESCREEN_SLEEP_SEC', '0.5'))


def _parse_dt(value):
    """Returns a naive datetime (tzinfo stripped) -- these date-as-text
    columns mix naive and offset-aware formats (e.g. one merchant row has a
    '+00' suffix, most don't; see P2's models/case.py for the same
    inconsistency in other tables), and comparing a naive cutoff against an
    aware value raises TypeError. Only relative ordering/age matters here,
    not timezone-correct absolute time, so stripping tzinfo is safe."""
    if not value:
        return None
    try:
        from dateutil import parser as dateutil_parser
        parsed = dateutil_parser.parse(str(value))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, TypeError):
        return None


def _select_batch(db):
    """Returns up to BATCH_SIZE (kind, id, name, entity_type, dob, nationality)
    tuples, never-screened first, then oldest-screened first, excluding
    anything screened within RESCREEN_AFTER_DAYS."""
    cutoff = datetime.now() - timedelta(days=RESCREEN_AFTER_DAYS)
    candidates = []

    for row in db.execute("""
        SELECT id, full_name, company_name, customer_type, date_of_birth, nationality, last_screening_date
        FROM customers
    """).fetchall():
        c = dict(row)
        name = c['full_name'] if c.get('customer_type') == 'INDIVIDUAL' else (c.get('company_name') or c['full_name'])
        if not name:
            continue
        last = _parse_dt(c.get('last_screening_date'))
        if last and last >= cutoff:
            continue
        candidates.append((
            last or datetime.min, 'customer', c['id'], name,
            'INDIVIDUAL' if c.get('customer_type') == 'INDIVIDUAL' else 'ENTITY',
            c.get('date_of_birth'), c.get('nationality'),
        ))

    for row in db.execute("SELECT id, merchant_name, country, last_screening_date FROM merchants").fetchall():
        m = dict(row)
        if not m.get('merchant_name'):
            continue
        last = _parse_dt(m.get('last_screening_date'))
        if last and last >= cutoff:
            continue
        candidates.append((
            last or datetime.min, 'merchant', m['id'], m['merchant_name'],
            'ENTITY', None, m.get('country'),
        ))

    candidates.sort(key=lambda c: c[0])
    return candidates[:BATCH_SIZE]


def run_batch():
    from database.db import get_db
    from screening.customer_screening_service import screen_and_save
    from events.publisher import publish_event

    db = get_db()
    batch = _select_batch(db)
    results = {'screened': 0, 'high_risk': 0, 'errors': 0}

    for last, kind, record_id, name, entity_type, dob, nationality in batch:
        source_module = 'Customer KYC' if kind == 'customer' else 'Merchant KYC'
        source_table = 'customers' if kind == 'customer' else 'merchants'
        try:
            res = screen_and_save(
                name=name, entity_type=entity_type, dob=dob, nationality=nationality,
                source_module=source_module, source_record_id=record_id,
                screening_type='Scheduled Re-screening',
                results_screening_type='CUSTOMER' if kind == 'customer' else 'MERCHANT_KYC',
                write_results_table=False,
            )
            results['screened'] += 1
            if res['high_risk_matches'] > 0:
                results['high_risk'] += 1
                publish_event(
                    event_type='screening.hit',
                    source_module=source_module,
                    source_table=source_table,
                    source_record_id=record_id,
                    entity_type=kind.upper(),
                    entity_id=record_id,
                    payload={
                        'entity_name': name,
                        'high_risk_matches': res['high_risk_matches'],
                        'highest_score': res['highest_score'],
                    },
                )
        except Exception as exc:
            results['errors'] += 1
            print(f"  {kind} {record_id} ({name}): FAILED - {exc}")

        if SLEEP_BETWEEN_SEC:
            time.sleep(SLEEP_BETWEEN_SEC)

    return results


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        start = time.time()
        counts = run_batch()
        elapsed = time.time() - start
        for key, value in counts.items():
            print(f"{key}: {value}")
        print(f"elapsed: {elapsed:.1f}s")
