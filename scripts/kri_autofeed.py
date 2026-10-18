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
Auto-feeds KRIMeasurement rows for KRIs whose value can be computed from
data this platform already has -- risk_management's KRI/KRIMeasurement
model and UI (models/risk.py, risk_management/routes.py) already exist and
are fully built; only actual_value entry was manual until now.

Deliberately NOT a generic "compute every KRI automatically" engine: each
KRI here is matched by name to one hand-written compute function, because
inventing a computation for a KRI this codebase has no real data source for
(e.g. the seeded "Critical/High Vulnerabilities Open Beyond SLA",
"CBE Regulatory Report Submission Lateness", "Settlement Liquidity Buffer
Ratio" KRIs -- there's no vulnerability scanner, regulator-report tracker,
or treasury/liquidity data anywhere in this codebase) would mean fabricating
a compliance metric, not automating one. Add a new FEEDS entry only when a
KRI has a real, confidently-mapped data source -- don't guess.

Idempotent per day: kri_measurements has UNIQUE(kri_id, measurement_date),
so a measurement already recorded today is left alone rather than erroring.

Replicates risk_management/routes.py's kris_record_measurement() RED-breach
notification (that logic lives in the route, not the model, so calling
KRIMeasurement.create() directly here skips it unless repeated).

Safe to run manually: python scripts/kri_autofeed.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tm_alert_backlog_48h(db):
    """Matches the seeded KRI 'TM Alert Backlog Aged Over 48 Hours' (unit:
    alerts) -- count of open TM_ALERT cases (P2's unified `cases` table)
    older than 48 hours."""
    row = db.execute("""
        SELECT count(*) AS c FROM cases
        WHERE case_type = 'TM_ALERT' AND status NOT IN ('RESOLVED', 'CLOSED')
          AND opened_at < NOW() - INTERVAL '48 hours'
    """).fetchone()
    return float(row['c'])


# kri_name -> compute function. Only KRIs with a confidently-real data
# source in this codebase are listed -- see module docstring.
FEEDS = {
    'TM Alert Backlog Aged Over 48 Hours': _tm_alert_backlog_48h,
}


def run_autofeed():
    from database.db import get_db
    from models.risk import KRI, KRIMeasurement
    from models.notification import Notification

    db = get_db()
    today = date.today().isoformat()
    results = {'measured': 0, 'skipped_already_measured': 0, 'skipped_no_kri': 0, 'breaches_notified': 0}

    for kri_name, compute_fn in FEEDS.items():
        kris = [k for k in KRI.get_all(active_only=True) if k.kri_name == kri_name]
        if not kris:
            results['skipped_no_kri'] += 1
            print(f"  '{kri_name}': no active KRI row found, skipping")
            continue

        for kri in kris:
            existing = db.execute(
                "SELECT 1 FROM kri_measurements WHERE kri_id = %s AND measurement_date = %s",
                (kri.id, today)
            ).fetchone()
            if existing:
                results['skipped_already_measured'] += 1
                continue

            value = compute_fn(db)
            _, status = KRIMeasurement.create(
                kri.id, measurement_date=today, actual_value=value,
                notes='Auto-computed by scripts/kri_autofeed.py', recorded_by=None,
            )
            results['measured'] += 1
            print(f"  '{kri_name}' (kri_id={kri.id}): {value} -> {status}")

            if status == 'RED' and kri.owner_id:
                Notification.create(
                    user_id=kri.owner_id, title=f'KRI breach: {kri.kri_name}',
                    message=f'Auto-computed measurement for "{kri.kri_name}" is {value} ({kri.unit_of_measure}), breaching the RED threshold.',
                    link='/risk-management/kris', n_type='kri_breach',
                )
                results['breaches_notified'] += 1

    return results


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        counts = run_autofeed()
        for key, value in counts.items():
            print(f"{key}: {value}")
