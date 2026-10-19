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

"""Monitored-mailbox import for the Compliance Copilot (cron, e.g. every 5 minutes):

    */5 * * * * cd /opt/complynex && venv/bin/python scripts/ai_mail_import.py

Does nothing unless AI settings > Monitored mailbox is enabled. See docs/ai/AI_ARCHITECTURE.md §7."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app  # noqa: E402
from ai import mailbox  # noqa: E402

with app.app_context():
    try:
        r = mailbox.run_import()
        print('ai mailbox:', {k: v for k, v in r.items() if k != 'items'})
    except mailbox.MailboxError as e:
        print('ai mailbox:', e)
        sys.exit(1)
