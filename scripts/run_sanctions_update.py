#!/usr/bin/env python3
# =============================================================================
# ComplyNex - scheduled sanctions/watchlist refresh (screening Rec #1, 2026-07-21)
#
# Why this exists: list updates were previously manual-only (an admin clicking
# "sync"), which left OFAC 3 weeks stale and EU a month stale in production.
# For a CBE-licensed PSP, timely list updates are a core AML/CFT control -
# this script is executed daily by complynex-sanctions-update.timer.
#
# What it does:
#   1. Runs the existing EnhancedDataUpdater across all active sources
#      (same code path as the manual sync button - nothing bespoke).
#   2. Upserts the sanctions_lists registry table so "which lists do we
#      screen against and when was each updated" is answerable from one
#      screen (screening Rec #4).
#   3. Logs to logs/sanctions_update.log and exits non-zero on any source
#      failure so the systemd unit shows failed state (visible in
#      systemctl/journal, and consecutive_failures surfaces on the
#      screening dashboard freshness panel).
#
# Usage:
#   run_sanctions_update.py                  # update all active sources
#   run_sanctions_update.py --source ofac    # update one source by name
#   run_sanctions_update.py --registry-only  # only refresh the registry table
# =============================================================================
import sys, os, argparse, logging
from datetime import datetime

sys.path.insert(0, '/var/www/complynex')
os.chdir('/var/www/complynex')

from dotenv import load_dotenv
load_dotenv('/var/www/complynex/.env')
os.environ.setdefault('DB_TYPE', 'postgresql')

LOG_PATH = '/var/www/complynex/logs/sanctions_update.log'
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
)
log = logging.getLogger('sanctions_update')


def refresh_registry(conn):
    """Upsert sanctions_lists from screening_data_sources so the registry is
    a single, always-current source of truth for list coverage + freshness."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, source_name, source_display_name, source_url,
               last_successful_update, total_records, is_active
        FROM screening_data_sources
    """)
    rows = cur.fetchall()
    for r in rows:
        sid, name, display, url, last_ok, total, active = r
        cur.execute("SELECT id FROM sanctions_lists WHERE list_code = %s", (name,))
        hit = cur.fetchone()
        if hit:
            cur.execute("""
                UPDATE sanctions_lists
                SET list_name=%s, source_url=%s, last_download_date=%s,
                    record_count=%s, is_active=%s
                WHERE list_code=%s
            """, (display or name, url, str(last_ok or ''), total or 0, active or 0, name))
        else:
            cur.execute("""
                INSERT INTO sanctions_lists
                    (list_code, list_name, source_url, last_download_date, record_count, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (name, display or name, url, str(last_ok or ''), total or 0, active or 0))
    conn.commit()
    log.info(f"registry refreshed: {len(rows)} sources")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', help='update a single source by source_name')
    ap.add_argument('--registry-only', action='store_true')
    args = ap.parse_args()

    from utils.demo import skip_in_demo
    if skip_in_demo("list update", log):
        return

    from config import get_config
    cfg = get_config()
    db_config = dict(cfg.POSTGRES_CONFIG)

    import psycopg2
    conn = psycopg2.connect(**db_config)

    failures = []
    from screening.update_lock import hold
    marker = hold('scheduled run')
    marker.__enter__()
    if not args.registry_only:
        from screening.data_updater_enhanced import EnhancedDataUpdater
        cur = conn.cursor()
        if args.source:
            cur.execute("SELECT id, source_name FROM screening_data_sources WHERE source_name=%s AND is_active=1", (args.source,))
        else:
            cur.execute("SELECT id, source_name FROM screening_data_sources WHERE is_active=1 ORDER BY id")
        sources = cur.fetchall()
        log.info(f"=== scheduled update run: {len(sources)} source(s) ===")

        cur.execute("SELECT source_name FROM screening_data_sources WHERE source_url = 'internal' OR source_url IS NULL")
        internal = {r[0] for r in cur.fetchall()}

        def _log_run(sname, status, st, err, secs):
            try:
                c = conn.cursor()
                c.execute("""INSERT INTO screening_list_update_log
                    (source, status, added, updated, unchanged, delisted, relisted, errors, error, duration_s)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (sname, status, st.get('added', 0), st.get('updated', 0), st.get('unchanged', 0),
                     st.get('delisted', 0), st.get('relisted', 0), st.get('errors', 0), err, round(secs, 1)))
                conn.commit()
            except Exception as le:
                conn.rollback()
                log.warning(f"could not write screening_list_update_log: {le}")

        for sid, sname in sources:
            if sname in internal:
                # internal lists are maintained in the app, not downloaded
                _log_run(sname, 'skipped', {}, 'internal list (maintained in the app)', 0)
                continue
            t0 = datetime.now()
            try:
                updater = EnhancedDataUpdater(db_config)
                updater.version_trigger = 'scheduled'     # recorded in the list version (P2-1)
                stats = updater.update_watchlist(source_id=sid, user_id=1)
                updater.close_db()
                secs = (datetime.now() - t0).total_seconds()
                # update_watchlist never raises for a bad source: it counts
                # errors. Those used to be logged as [OK] — OFAC, HMT and EU
                # silently stopped updating for months.
                per = (stats or {}).get('sources', {}).get(sname) if isinstance(stats, dict) else None
                st = per or stats or {}
                if st.get('errors'):
                    err = st.get('error') or 'processing error (see log)'
                    blocked = bool(st.get('blocked'))
                    log.error(f"[{'BLOCKED' if blocked else 'FAIL'}] {sname} (id={sid}) in {secs:.0f}s stats={stats}")
                    failures.append(sname)
                    _log_run(sname, 'blocked' if blocked else 'failed', st, err, secs)
                else:
                    log.info(f"[OK] {sname} (id={sid}) in {secs:.0f}s stats={stats}")
                    _log_run(sname, 'ok', st, None, secs)
            except Exception as e:
                secs = (datetime.now() - t0).total_seconds()
                log.error(f"[FAIL] {sname} (id={sid}) after {secs:.0f}s: {e}", exc_info=True)
                failures.append(sname)
                _log_run(sname, 'failed', {}, str(e)[:500], secs)

    refresh_registry(conn)
    if not args.registry_only:
        # P2-7: one MLRO alert per failed / blocked / overdue list (de-duplicated per day)
        try:
            from screening import list_versions as LV
            red = LV.check_and_alert(conn)
            log.info(f"list freshness: {len(red)} list(s) need attention" + (f": {[r['source'] for r in red]}" if red else ''))
        except Exception as e:
            log.warning(f"list freshness check failed: {e}")
    conn.close()
    if not args.registry_only:
        try:
            import subprocess
            r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'link_emlcu_internal.py'), '--apply'], capture_output=True, text=True, timeout=900)
            log.info(f"EMLCU <-> Public Prosecution link: {(r.stdout or r.stderr).strip().splitlines()[-2:]}")
        except Exception as e:
            log.warning(f"EMLCU link step failed: {e}")
    marker.__exit__(None, None, None)

    if not args.registry_only:
        # Full id-by-id check of the search index against the watchlist
        # (removes delisted / merged records, adds anything missing).
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import es_reconcile
            log.info(f"search index check: {es_reconcile.run()}")
        except Exception as e:
            log.error(f"search index check failed: {e}", exc_info=True)
            failures.append('es_reconcile')

    # P2-6: rebuild the links between records of the same person on several lists, after the
    # update marker is released (the search-index sync is not held up) and only when something
    # changed (new tables only; never changes a watchlist row). ENTITY_LINKS_AUTO=0 turns it off.
    if not args.registry_only and os.getenv('ENTITY_LINKS_AUTO', '1') != '0':
        try:
            import subprocess
            r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'build_entity_links.py'), '--apply', '--if-changed'],
                               capture_output=True, text=True, timeout=1800)
            log.info(f"entity links: {(r.stdout or r.stderr).strip().splitlines()[-1:]}")
        except Exception as e:
            log.warning(f"entity link step failed: {e}")

    if failures:
        log.error(f"=== run finished WITH FAILURES: {failures} ===")
        sys.exit(1)
    log.info("=== run finished OK ===")


if __name__ == '__main__':
    main()
