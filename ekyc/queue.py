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
Redis-backed job queue for the eKYC verification pipeline.

The pipeline (OCR, face matching, liveness, document-PAD) is CPU-bound and
loads several hundred MB of ML models. It must NOT run inline in the
Gunicorn gevent web workers: gevent is built for I/O concurrency, so a
blocking inference call would stall every other request on that worker,
and each of the 2 web workers would otherwise load its own copy of every
model. Instead, the web process enqueues a job here and a single dedicated
`ekyc-worker` process (loads models once, see worker.py) consumes it.

Uses Redis db 2 to stay isolated from the dashboard cache (db 0) and the
rate-limiter storage (db 1).
"""
import os
from urllib.parse import urlparse

from redis import Redis
from rq import Queue

QUEUE_NAME = 'ekyc'


def _redis_connection():
    base_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    parsed = urlparse(base_url)
    return Redis(host=parsed.hostname or 'localhost', port=parsed.port or 6379, db=2)


def get_queue():
    return Queue(QUEUE_NAME, connection=_redis_connection())


def enqueue_session(session_id):
    """Submit a session for pipeline processing. Returns the RQ job id."""
    queue = get_queue()
    job = queue.enqueue('ekyc.worker.process_session', session_id, job_timeout=300)
    return job.id
