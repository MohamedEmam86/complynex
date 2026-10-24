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
Scheduled entry point for the regcontrols control engine.

    python scripts/regcontrols_run.py            # due controls + all sweeps (cron, e.g. hourly)
    python scripts/regcontrols_run.py --sweeps   # only evidence expiry, overdue findings, escalations
    python scripts/regcontrols_run.py --control FRA-079   # run one control now
    python scripts/regcontrols_run.py --enqueue  # add the sweep to the run queue (rc_run_queue) instead

Suggested crontab (server time Africa/Cairo):
    15 * * * *  cd /var/www/complynex && venv/bin/python scripts/regcontrols_run.py >> logs/regcontrols.log 2>&1
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('regcontrols_run')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sweeps', action='store_true', help='only run the sweeps')
    ap.add_argument('--control', help='run a single control code now')
    ap.add_argument('--enqueue', action='store_true', help='enqueue on RQ instead of running here')
    args = ap.parse_args()

    from app import create_app
    from regcontrols import alerts, engine, evidence, findings

    app = create_app()
    with app.app_context():
        if args.enqueue:
            job = engine.enqueue_due()
            log.info('queued sweep %s (processed by scripts/regcontrols_process_queue.py)', job)
            return 0 if job else 1
        if args.control:
            run = engine.run_control(args.control, triggered_by='schedule')
            log.info('%s: %s — %s', args.control, run['status'], run['summary'])
            return 0
        log.info('data sweeps: %s', engine.run_sweeps())
        if not args.sweeps:
            log.info('due controls: %s', engine.run_due())
        log.info('evidence (expired, expiring): %s', evidence.sweep_expiry())
        log.info('overdue findings alerted: %s', findings.sweep_overdue())
        log.info('alerts (escalated, reminded): %s', alerts.sweep_escalations())
    return 0


if __name__ == '__main__':
    sys.exit(main())
