#!/usr/bin/env python3
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
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Standalone entry point for complynex-pep-scheduler.service — runs the
screening/pep_management/ subsystem's background sync scheduler as its own
persistent process, matching every other recurring job on this box
(complynex-ekyc-worker.service, complynex-es-sync.timer, etc.) rather than as
a thread inside gunicorn's gevent workers, which would run 4 duplicate
schedulers (one per worker) firing the same external syncs simultaneously.

init_pep_module() starts the scheduler's own background daemon thread and
returns immediately, so this script just blocks the main thread afterward to
keep that daemon thread (and the process) alive under systemd.
"""

import os
import sys
import signal
import time
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

from config import Config
from screening.pep_management.api import init_pep_module

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('pep_scheduler_main')

_stop = False


def _handle_signal(signum, frame):
    global _stop
    logger.info(f"Received signal {signum}, shutting down.")
    _stop = True


def main():
    # OPENCORPORATES_API_KEY is not currently configured — the scheduled
    # OpenCorporates sync (scheduler.py's _sync_opencorporates) is a no-op
    # stub today regardless, so this resolves to None without breaking
    # anything; wire up a real key here if that sync is ever implemented.
    oc_api_key = os.environ.get('OPENCORPORATES_API_KEY')

    init_pep_module(dict(Config.POSTGRES_CONFIG), oc_api_key=oc_api_key)
    logger.info("PEP scheduler initialized and running.")

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not _stop:
        time.sleep(5)


if __name__ == '__main__':
    main()
