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
Redis-backed job queue for compliance event dispatch. Mirrors
ekyc/queue.py's rationale: routing-rule actions (screening calls, DB writes)
must not run inline in the gevent web workers, so the web process only
enqueues here and a dedicated `complynex-event-dispatcher` process (see
events/worker.py) consumes it.

Uses Redis db 3 — db 0 is the dashboard cache, db 1 the rate limiter, db 2
the eKYC pipeline queue (see ekyc/queue.py).
"""
import os
from urllib.parse import urlparse

from redis import Redis
from rq import Queue

QUEUE_NAME = 'events'


def _redis_connection():
    base_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    parsed = urlparse(base_url)
    return Redis(host=parsed.hostname or 'localhost', port=parsed.port or 6379, db=3)


def get_queue():
    return Queue(QUEUE_NAME, connection=_redis_connection())


def enqueue_event(event_id):
    """Submit a compliance_events row for routing/dispatch. Returns the RQ job id."""
    queue = get_queue()
    job = queue.enqueue('events.dispatcher.process_event', event_id, job_timeout=120)
    return job.id
