"""Marker that a watchlist (sanctions list) update is running.

A list update writes hundreds of thousands of rows in long transactions.
Jobs that read the watchlist incrementally (the Elasticsearch sync, the
delta re-screening of existing customers, the semantic index) must not run
in the middle of it: rows written early but committed late fall behind
their checkpoint and are missed for good. On 2026-10-22 this left 436,306
merged OpenSanctions records in the search index.

Every update registers itself as one small file under logs/ (one file per
running update, so parallel updates are fine). A file whose process is gone
is stale and ignored.
"""
import os
import time
import uuid
import logging
from contextlib import contextmanager

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_DIR = os.path.join(_BASE, 'logs', 'watchlist_update.d')
log = logging.getLogger(__name__)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def hold(label=''):
    """Mark a watchlist update as running for the duration of the block."""
    path = None
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        path = os.path.join(LOCK_DIR, f"{os.getpid()}-{uuid.uuid4().hex[:8]}")
        with open(path, 'w') as f:
            f.write(f"{label}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    except OSError as e:  # never block an update because of the marker
        log.warning(f"could not write update marker: {e}")
        path = None
    try:
        yield
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass


def held():
    """True while any watchlist update is running."""
    try:
        names = os.listdir(LOCK_DIR)
    except OSError:
        return False
    for name in names:
        try:
            pid = int(name.split('-', 1)[0])
        except ValueError:
            continue
        if _alive(pid):
            return True
        try:
            os.remove(os.path.join(LOCK_DIR, name))
        except OSError:
            pass
    return False


def wait_until_free(max_wait_s=4 * 3600, poll_s=60, logger=None):
    """Block until no update is running. Returns False if it gave up."""
    lg = logger or log
    waited = 0
    while held():
        if waited == 0:
            lg.info("watchlist update running - waiting for it to finish")
        if waited >= max_wait_s:
            lg.error(f"watchlist update still running after {waited}s - giving up")
            return False
        time.sleep(poll_s)
        waited += poll_s
    if waited:
        lg.info(f"watchlist update finished - continuing after {waited}s")
    return True
