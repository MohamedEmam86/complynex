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
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Background run of one bulk screening job (P4-9).

    python scripts/bulk_screening_worker.py --job <id> [--threads 4]

Started by the web app when the analyst presses "Start" (and again by
"Resume"). One worker per job: a session advisory lock refuses a second one.
Boots the Flask app once and screens the job's PENDING rows with the same
engine and the same save path as a single screening, so every row gets its
own screening result (queue items, clearances, evidence pack).
"""
import argparse
import logging
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job', required=True)
    ap.add_argument('--threads', type=int, default=int(os.getenv('BULK_THREADS', '4')))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    log = logging.getLogger('bulk_worker')

    from screening import bulk_jobs as BJ
    from screening import list_versions as LV
    lock_conn = LV.connect()
    cur = lock_conn.cursor()
    cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", ('cx_bulk:' + a.job,))
    if not cur.fetchone()[0]:
        log.info(f'job {a.job}: another worker is already running it')
        return 0
    lock_conn.commit()

    conn = LV.connect()
    store = BJ.SqlStore(conn)
    job = store.job(a.job)
    if not job:
        log.error(f'job {a.job} not found')
        return 2
    if job['status'] not in ('READY', 'RUNNING', 'PAUSED'):
        log.info(f"job {a.job} is {job['status']}: nothing to do")
        return 0
    store.set_status(a.job, job['status'], worker_pid=os.getpid())

    from app import create_app
    app = create_app()
    with app.app_context():
        from screening.routes import get_engine, _save_screening_result
        engine = get_engine()
    user_id = job.get('started_by') or job.get('created_by') or 1

    def screen(row):
        with app.app_context():
            return engine.screen_person(
                name=row['name'], date_of_birth=row.get('dob') or None,
                nationality=row.get('nationality') or None,
                entity_type=(row.get('entity_type') or 'INDIVIDUAL').upper(),
                user_id=user_id, include_media=False,
                national_id=row.get('national_id') or None, screening_type='BULK')

    def save(row, res):
        with app.app_context():
            _hid, rid = _save_screening_result(
                name=row['name'], entity_type=row.get('entity_type') or 'INDIVIDUAL',
                dob=row.get('dob') or None, nationality=row.get('nationality') or None,
                source_module='Bulk Upload', source_record_id=None, result=res, user_id=user_id,
                screening_type='BULK', return_ids=True,
                inputs={'national_id': row.get('national_id') or None,
                        'customer_ref': row.get('customer_ref') or None,
                        'bulk_job': a.job, 'bulk_row': row['row_no']})
            return rid

    def stopped():
        j = store.job(a.job) or {}
        return j.get('status') == 'CANCELLED'

    summary = BJ.run(store, a.job, screen, save, threads=a.threads, stop=stopped,
                     progress=lambda n: log.info(f'job {a.job}: {n} rows screened in this run'))
    log.info(f'job {a.job} finished: {summary}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
