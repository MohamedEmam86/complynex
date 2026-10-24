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
Process the regcontrols run queue (rc_run_queue): control runs queued from the
UI ("Queue run") and scheduled sweeps queued by an administrator.

    python scripts/regcontrols_process_queue.py            # process up to 50 queued items
    python scripts/regcontrols_process_queue.py --limit 5
    python scripts/regcontrols_process_queue.py --list     # show what is waiting

Each instance runs it against its own database (its own .env), e.g. from
deploy/systemd/complynex-regcontrols-queue.timer (every 5 minutes).
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('regcontrols_queue')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=50)
    ap.add_argument('--list', action='store_true', help='list queued items and exit')
    args = ap.parse_args()

    from app import create_app
    from regcontrols import run_queue

    app = create_app()
    with app.app_context():
        if args.list:
            for q in run_queue.items(status='queued'):
                log.info('#%s %s %s requested %s', q['id'], q['kind'], q.get('control_code') or '', q['requested_at'])
            return 0
        stale = run_queue.requeue_stale()
        if stale:
            log.info('re-queued %s stale item(s)', stale)
        out = run_queue.process(limit=args.limit)
        log.info('processed: %s done, %s failed', out['done'], out['failed'])
    return 0 if not out['failed'] else 1


if __name__ == '__main__':
    sys.exit(main())
