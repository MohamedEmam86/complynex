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
API webhooks dispatcher (P6-8) — run every minute by complynex-api-webhooks.timer.

  1. emits list.updated (new list versions), hit.decided (analyst decisions on hits of API
     screenings) and screening.completed for finished API batches;
  2. delivers the due events (signed, retried with back-off, then DEAD);
  3. drops idempotency records older than 24 hours.
"""
import logging
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, '.env'))
except ImportError:
    pass

log = logging.getLogger('api_webhooks')


def main():
    from utils.demo import skip_in_demo
    if skip_in_demo('API webhooks', log):
        return 0
    import psycopg2
    from config import Config
    from api import webhooks as WH
    conn = psycopg2.connect(**dict(Config.POSTGRES_CONFIG))
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(hashtext('cx_api_webhooks'))")
        if not cur.fetchone()[0]:
            log.info('another dispatcher is running')
            return 0
        conn.commit()
        stats = {}
        for name, fn in (('list.updated', WH.emit_list_updates), ('hit.decided', WH.emit_hit_decisions),
                         ('batch', WH.emit_batch_completions)):
            try:
                stats[name] = fn(conn)
            except Exception as e:
                conn.rollback()
                log.error('emit %s failed: %s', name, e)
        total = {'delivered': 0, 'retry': 0, 'dead': 0}
        for _ in range(10):   # at most 1,000 deliveries per run
            r = WH.deliver_due(conn)
            for k in total:
                total[k] += r[k]
            if sum(r.values()) < 100:
                break
        stats['deliveries'] = total
        stats['idempotency_purged'] = WH.purge_idempotency(conn)
        if any(v for k, v in stats.items() if k != 'deliveries') or any(total.values()):
            log.info('%s', stats)
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    sys.exit(main())
