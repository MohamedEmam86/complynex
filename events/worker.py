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
Dedicated compliance-event-dispatcher worker (see the
complynex-event-dispatcher systemd service). Separate process from the
Gunicorn web workers for the same reason as ekyc/worker.py: dispatcher
actions can call into the screening engine (1-2s+ per call), which must
never block a gevent web worker.

Unlike ekyc/worker.py this uses the default forking Worker, not
SimpleWorker — there's no warm ML model cache worth preserving across jobs
here, so per-job crash isolation is the better trade-off.
"""
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

if __name__ == '__main__':
    from rq import Worker
    from events.queue import _redis_connection, QUEUE_NAME

    worker = Worker([QUEUE_NAME], connection=_redis_connection())
    worker.work(with_scheduler=False)
