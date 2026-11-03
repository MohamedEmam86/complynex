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
Reminders of customer reviews coming due (Phase 7, F2).

Does nothing unless the MLRO switched reminders on in the customer risk model
(/aml/risk-scoring). Not scheduled on any server: run it by hand, or install
a daily timer once the owner decides.

    python scripts/aml_review_reminders.py            # dry run: count only
    python scripts/aml_review_reminders.py --send
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--send', action='store_true')
    a = ap.parse_args()
    from app import app
    with app.app_context():
        from aml.periodic_review import send_reminders
        enabled, n = send_reminders(dry_run=not a.send)
        if not enabled:
            print('reminders are switched off in the customer risk model: nothing sent')
        else:
            print(f'{n} review(s) overdue or coming due' + ('' if a.send else ' (dry run, nothing sent)'))


if __name__ == '__main__':
    main()
