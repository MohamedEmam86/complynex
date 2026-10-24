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
Database-backed queue of control runs.

"Queue run" on a control and "Run scheduled controls" add a row to
rc_run_queue; the rows are processed by

  * scripts/regcontrols_process_queue.py (systemd timer, see
    deploy/systemd/complynex-regcontrols-queue.*), or
  * an administrator's "Process queue now" / "Run now" on /regcontrols/run-queue.

Each instance processes its own database's queue, so the demo instance never
hands work to the main instance's workers (the previous RQ hand-off used the
shared 'events' queue).
"""

import logging
from datetime import datetime

from database.db import get_db

logger = logging.getLogger(__name__)


def enqueue(control_id=None, user_id=None, kind='control', db=None):
    """Queue a run; an identical item still waiting is reused. Returns the queue id."""
    db = db or get_db()
    row = db.execute("""SELECT id FROM rc_run_queue WHERE status = 'queued' AND kind = %s
                        AND COALESCE(control_id, 0) = %s ORDER BY id LIMIT 1""",
                     (kind, control_id or 0)).fetchone()
    if row:
        return row['id']
    qid = db.execute("""INSERT INTO rc_run_queue (kind, control_id, requested_by) VALUES (%s,%s,%s) RETURNING id""",
                     (kind, control_id, user_id)).fetchone()['id']
    db.commit()
    return qid


def items(status=None, limit=100, db=None):
    db = db or get_db()
    clause, args = ('WHERE q.status = %s', (status,)) if status else ('', ())
    return [dict(r) for r in db.execute(f"""
        SELECT q.*, c.control_code, c.title_en AS control_title,
               NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS requested_by_name,
               NULLIF(TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, '')), '') AS processed_by_name,
               r.status AS run_status
        FROM rc_run_queue q
        LEFT JOIN rc_controls c ON c.id = q.control_id
        LEFT JOIN users u ON u.id = q.requested_by
        LEFT JOIN users p ON p.id = q.processed_by
        LEFT JOIN rc_control_runs r ON r.id = q.run_id
        {clause}
        ORDER BY (q.status = 'queued') DESC, q.requested_at DESC LIMIT %s""", args + (limit,)).fetchall()]


def queued_count(db=None):
    db = db or get_db()
    return db.execute("SELECT count(*) AS n FROM rc_run_queue WHERE status = 'queued'").fetchone()['n']


def _claim(db, queue_id=None):
    """Take the next queued item (or the given one) so two processors never run it twice."""
    clause, args = ('AND id = %s', (queue_id,)) if queue_id else ('', ())
    row = db.execute(f"""UPDATE rc_run_queue SET status = 'running', started_at = NOW()
                         WHERE id = (SELECT id FROM rc_run_queue WHERE status = 'queued' {clause}
                                     ORDER BY requested_at, id LIMIT 1 FOR UPDATE SKIP LOCKED)
                         RETURNING *""", args).fetchone()
    db.commit()
    return dict(row) if row else None


def _run_item(item, user_id, db):
    from . import engine
    if item['kind'] == 'due':
        from . import alerts, evidence, findings
        engine.run_sweeps()
        counts = engine.run_due(db=db)
        evidence.sweep_expiry(db=db)
        findings.sweep_overdue(db=db)
        alerts.sweep_escalations(db=db)
        return None, ', '.join(f'{k}: {v}' for k, v in sorted(counts.items())) or 'no controls due'
    run = engine.run_control(item['control_id'], triggered_by='manual',
                             user_id=item.get('requested_by') or user_id, db=db)
    return run['id'], run['status']


def process(limit=50, user_id=None, queue_id=None, db=None):
    """Run queued items (oldest first). Returns {'done': n, 'failed': n}."""
    db = db or get_db()
    out = {'done': 0, 'failed': 0}
    for _ in range(1 if queue_id else limit):
        item = _claim(db, queue_id)
        if not item:
            break
        try:
            run_id, result = _run_item(item, user_id, db)
            db.execute("""UPDATE rc_run_queue SET status = 'done', finished_at = %s, run_id = %s, result = %s,
                          processed_by = %s WHERE id = %s""",
                       (datetime.now(), run_id, (result or '')[:500], user_id, item['id']))
            db.commit()
            out['done'] += 1
        except Exception as e:
            logger.exception('regcontrols: queued run %s failed', item['id'])
            db.rollback()
            db.execute("""UPDATE rc_run_queue SET status = 'failed', finished_at = %s, error = %s, processed_by = %s
                          WHERE id = %s""", (datetime.now(), str(e)[:1000], user_id, item['id']))
            db.commit()
            out['failed'] += 1
    return out


def requeue_stale(minutes=60, db=None):
    """Items left 'running' by a crashed processor go back to the queue."""
    db = db or get_db()
    n = db.execute("""UPDATE rc_run_queue SET status = 'queued', started_at = NULL
                      WHERE status = 'running' AND started_at < NOW() - make_interval(mins => %s)""",
                   (minutes,)).rowcount
    db.commit()
    return n
