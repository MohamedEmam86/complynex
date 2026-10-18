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

# Must patch before preload_app imports the app (and its transitive deps —
# elasticsearch client, redis, requests/urllib3) in the master. Otherwise
# those modules bind unpatched ssl/socket in the master pre-fork, and each
# gevent worker's own post-fork monkey.patch_all() (see gunicorn's
# GeventWorker.patch()) can no longer retroactively patch objects/classes
# those modules already captured — TLS I/O in those code paths would block
# the whole worker's event loop instead of yielding to other greenlets.
import gevent.monkey
gevent.monkey.patch_all()

worker_class = 'gevent'
workers = 4
bind = '127.0.0.1:8000'
timeout = 120

# Defense-in-depth memory safety net (added 2026-07-24 after a production OOM
# incident: one worker was measured at 11.4GB RSS / 26.9GB VSZ within ~7
# minutes of a fresh boot, and the OOM killer took it out, taking the whole
# service down with it). The actual root cause was a concurrency bug in
# database/db.py's connection-pool lazy-init (fixed there — see _pool_lock),
# but that fix addresses one known leak source, not every possible one.
# Recycling each worker after a bounded number of requests caps how much any
# single worker's memory can grow before it's replaced with a clean one,
# regardless of the leak's origin (this app's code, a dependency, or memory
# fragmentation in the allocator). Gunicorn replaces a worker gracefully
# (finishes in-flight requests, spawns the replacement, only then kills the
# old one) — no dropped requests. The jitter staggers the 4 workers' recycle
# points so they don't all restart in the same instant.
max_requests = 2000
max_requests_jitter = 200

# Import the app once in the master before forking, so the OS shares the
# (large, otherwise duplicated 4x) pandas/scikit-learn/elasticsearch/etc.
# import pages across workers via copy-on-write instead of each worker
# loading its own private copy.
preload_app = True


def post_fork(server, worker):
    # The Postgres connection pool is opened eagerly during create_app()
    # (database/db.py: init_pool). Under preload_app that happens once in
    # the master, pre-fork, before gevent's monkey-patching runs (gevent
    # only patches sockets inside each worker's own post-fork init). If
    # left alone, all 4 workers would inherit and share the same
    # already-open, non-greenlet-patched DB socket file descriptors,
    # corrupting concurrent query traffic. Dropping the reference here
    # forces the existing lazy-init path in db.get_db() to build a fresh,
    # worker-local, properly gevent-patched pool on first use.
    from database import db
    db._connection_pool = None
