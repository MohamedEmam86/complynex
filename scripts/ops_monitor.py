#!/usr/bin/env python3
# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Server monitoring (P6-7). Every 5 minutes (complynex-ops-monitor.timer):

  collect   disk, RAM, CPU load, services, failed units, PostgreSQL connections,
            Elasticsearch health, queue depths, list freshness, last backup age
  judge     each check -> ok / warn / crit against the thresholds below (env-overridable)
  publish   logs/ops_status.json (read by the admin page /admin/server-status) and
            logs/ops_history.jsonl (last 2 days)
  alert     a check that turns warn/crit raises an in-app notification for the admins and
            an e-mail to OPS_ALERT_EMAIL (if set); repeated at most every OPS_REALERT_HOURS;
            a recovery is announced once. Never raises; a check that cannot run is 'unknown'.

Read-only on the server: no restarts, no writes outside logs/ and the notifications table.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, '.env'))
except ImportError:
    pass

LOG_DIR = os.path.join(BASE, 'logs')
STATUS = os.path.join(LOG_DIR, 'ops_status.json')
HISTORY = os.path.join(LOG_DIR, 'ops_history.jsonl')
STATE = os.path.join(LOG_DIR, 'ops_alert_state.json')


def _env_f(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


LIMITS = {
    'disk_warn_pct': _env_f('OPS_DISK_WARN_PCT', 80), 'disk_crit_pct': _env_f('OPS_DISK_CRIT_PCT', 90),
    'ram_warn_avail_mb': _env_f('OPS_RAM_WARN_MB', 1500), 'ram_crit_avail_mb': _env_f('OPS_RAM_CRIT_MB', 600),
    'load_warn_per_cpu': _env_f('OPS_LOAD_WARN', 1.5), 'load_crit_per_cpu': _env_f('OPS_LOAD_CRIT', 3.0),
    'pg_conn_warn_pct': _env_f('OPS_PG_WARN_PCT', 70), 'pg_conn_crit_pct': _env_f('OPS_PG_CRIT_PCT', 90),
    'backup_warn_hours': _env_f('OPS_BACKUP_WARN_H', 30), 'backup_crit_hours': _env_f('OPS_BACKUP_CRIT_H', 54),
    'queue_warn': _env_f('OPS_QUEUE_WARN', 500), 'queue_crit': _env_f('OPS_QUEUE_CRIT', 2000),
}
SERVICES = [s for s in os.getenv(
    'OPS_SERVICES',
    'complynex,postgresql,elasticsearch,redis-server,nginx,complynex-ekyc-worker,complynex-event-dispatcher'
).split(',') if s.strip()]
TIMERS = [s for s in os.getenv(
    'OPS_TIMERS',
    'complynex-sanctions-update.timer,complynex-es-sync.timer,complynex-index-health.timer,'
    'complynex-internal-list-sync.timer,complynex-backup.timer'
).split(',') if s.strip()]
BACKUP_UNITS = [s for s in os.getenv('OPS_BACKUP_UNITS', 'complynex-backup.service').split(',') if s.strip()]
REALERT_H = _env_f('OPS_REALERT_HOURS', 6)


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ''


def _lvl(value, warn, crit, higher_is_bad=True):
    if value is None:
        return 'unknown'
    if higher_is_bad:
        return 'crit' if value >= crit else 'warn' if value >= warn else 'ok'
    return 'crit' if value <= crit else 'warn' if value <= warn else 'ok'


# --------------------------------------------------------------------------- checks
def check_disk():
    out = []
    for path in sorted(set(os.getenv('OPS_DISK_PATHS', '/,/var/backups').split(','))):
        try:
            u = shutil.disk_usage(path)
            pct = round(100.0 * u.used / u.total, 1)
            out.append({'key': f'disk:{path}', 'label': f'Disk {path}', 'value': f'{pct}% used, '
                        f'{u.free // 2**30} GB free',
                        'level': _lvl(pct, LIMITS['disk_warn_pct'], LIMITS['disk_crit_pct'])})
        except Exception as e:
            out.append({'key': f'disk:{path}', 'label': f'Disk {path}', 'value': str(e)[:80], 'level': 'unknown'})
    return out


def check_ram_cpu():
    out = []
    try:
        mem = {}
        with open('/proc/meminfo') as f:
            for line in f:
                k, v = line.split(':', 1)
                mem[k] = int(v.split()[0])
        avail = mem.get('MemAvailable', 0) // 1024
        total = mem.get('MemTotal', 0) // 1024
        out.append({'key': 'ram', 'label': 'Memory available', 'value': f'{avail:,} of {total:,} MB',
                    'level': _lvl(avail, LIMITS['ram_warn_avail_mb'], LIMITS['ram_crit_avail_mb'], False)})
    except Exception as e:
        out.append({'key': 'ram', 'label': 'Memory available', 'value': str(e)[:80], 'level': 'unknown'})
    try:
        l1, l5, l15 = os.getloadavg()
        cpus = os.cpu_count() or 1
        per = round(l5 / cpus, 2)
        out.append({'key': 'load', 'label': 'CPU load (5 min, per core)', 'value': f'{per} ({l5:.1f} on {cpus} cores)',
                    'level': _lvl(per, LIMITS['load_warn_per_cpu'], LIMITS['load_crit_per_cpu'])})
    except Exception as e:
        out.append({'key': 'load', 'label': 'CPU load', 'value': str(e)[:80], 'level': 'unknown'})
    return out


def check_services():
    out = []
    for s in SERVICES:
        st = _run(['systemctl', 'is-active', s]) or 'unknown'
        out.append({'key': f'svc:{s}', 'label': f'Service {s}', 'value': st,
                    'level': 'ok' if st == 'active' else 'unknown' if st == 'unknown' else 'crit'})
    for t in TIMERS:
        st = _run(['systemctl', 'is-active', t]) or 'unknown'
        out.append({'key': f'timer:{t}', 'label': f'Timer {t}', 'value': st,
                    'level': 'ok' if st == 'active' else 'unknown' if st == 'unknown' else 'warn'})
    failed = [l.split()[0] for l in _run(['systemctl', '--failed', '--no-legend', '--plain']).splitlines()
              if l.strip() and 'complynex' in l]
    out.append({'key': 'failed_units', 'label': 'Failed ComplyNex units', 'value': ', '.join(failed) or 'none',
                'level': 'warn' if failed else 'ok'})
    return out


def check_backups():
    out = []
    for unit in BACKUP_UNITS:
        raw = _run(['systemctl', 'show', unit, '-p', 'ExecMainExitTimestamp', '-p', 'Result', '--value'])
        parts = raw.splitlines()
        result = parts[0] if parts else ''
        ts = parts[1] if len(parts) > 1 else ''
        age_h = None
        if ts and ts.strip() not in ('', 'n/a'):
            try:
                epoch = int(_run(['date', '-d', ts, '+%s']) or 0)
                age_h = round((time.time() - epoch) / 3600, 1) if epoch else None
            except Exception:
                age_h = None
        lvl = _lvl(age_h, LIMITS['backup_warn_hours'], LIMITS['backup_crit_hours'])
        if result and result != 'success':
            lvl = 'crit'
        out.append({'key': f'backup:{unit}', 'label': f'Last backup ({unit})',
                    'value': f'{age_h} h ago, result {result or "?"}' if age_h is not None else 'never ran',
                    'level': lvl if age_h is not None else 'warn'})
    return out


def check_db_and_queues():
    out = []
    try:
        import psycopg2
        from config import Config
        conn = psycopg2.connect(connect_timeout=5, **dict(Config.POSTGRES_CONFIG))
        conn.set_session(readonly=True, autocommit=True)
        c = conn.cursor()
        c.execute("SET statement_timeout = '10s'")
        c.execute("SELECT count(*), current_setting('max_connections')::int FROM pg_stat_activity")
        n, mx = c.fetchone()
        pct = round(100.0 * n / mx, 1)
        out.append({'key': 'pg_conn', 'label': 'PostgreSQL connections', 'value': f'{n} of {mx}',
                    'level': _lvl(pct, LIMITS['pg_conn_warn_pct'], LIMITS['pg_conn_crit_pct'])})
        queues = (('screening_queue', "SELECT count(*) FROM screening_queue WHERE lower(status) IN ('pending','open','in review','escalated')"),
                  ('bulk_jobs_running', "SELECT count(*) FROM screening_bulk_jobs WHERE status = 'RUNNING'"),
                  ('clearance_pending', "SELECT count(*) FROM screening_clearance_requests WHERE lower(status) = 'pending'"))
        for key, sql in queues:
            try:
                c.execute(sql)
                v = int(c.fetchone()[0])
                out.append({'key': f'queue:{key}', 'label': f'Queue {key}', 'value': f'{v:,}',
                            'level': _lvl(v, LIMITS['queue_warn'], LIMITS['queue_crit'])})
            except Exception as e:
                out.append({'key': f'queue:{key}', 'label': f'Queue {key}', 'value': str(e).split('\n')[0][:80],
                            'level': 'unknown'})
        try:
            from screening import list_versions as LV
            fr = LV.freshness(conn) or []
            bad = [f.get('source') for f in fr if (f.get('state') or f.get('status')) in ('red', 'overdue', 'failed', 'blocked')
                   or f.get('red')]
            out.append({'key': 'lists', 'label': 'List freshness', 'value': ', '.join(map(str, bad)) or 'all lists fresh',
                        'level': 'crit' if bad else 'ok'})
        except Exception as e:
            out.append({'key': 'lists', 'label': 'List freshness', 'value': str(e)[:80], 'level': 'unknown'})
        conn.close()
    except Exception as e:
        out.append({'key': 'pg', 'label': 'PostgreSQL', 'value': str(e).split('\n')[0][:100], 'level': 'crit'})
    return out


def check_es():
    try:
        from screening.es_client import get_es_client
        h = get_es_client(timeout=10).cluster.health()
        st = h.get('status')
        return [{'key': 'es', 'label': 'Elasticsearch', 'value': f"{st}, {h.get('active_shards')} shards",
                 'level': 'ok' if st in ('green', 'yellow') else 'crit'}]
    except Exception as e:
        return [{'key': 'es', 'label': 'Elasticsearch', 'value': str(e)[:100], 'level': 'crit'}]


def collect():
    checks = []
    for fn in (check_disk, check_ram_cpu, check_services, check_backups, check_db_and_queues, check_es):
        try:
            checks += fn()
        except Exception as e:
            checks.append({'key': fn.__name__, 'label': fn.__name__, 'value': str(e)[:100], 'level': 'unknown'})
    order = {'crit': 3, 'warn': 2, 'unknown': 1, 'ok': 0}
    worst = max((c['level'] for c in checks), key=lambda l: order[l], default='ok')
    return {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'overall': worst, 'checks': checks}


# --------------------------------------------------------------------------- publish / alert
def _write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def publish(status):
    os.makedirs(LOG_DIR, exist_ok=True)
    _write_json(STATUS, status)
    cutoff = time.time() - 2 * 86400
    lines = []
    try:
        with open(HISTORY) as f:
            for line in f:
                try:
                    if datetime.fromisoformat(json.loads(line)['at']).timestamp() >= cutoff:
                        lines.append(line.rstrip('\n'))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    lines.append(json.dumps({'at': status['at'], 'overall': status['overall'],
                             'bad': {c['key']: c['level'] for c in status['checks'] if c['level'] != 'ok'}}))
    with open(HISTORY + '.tmp', 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(HISTORY + '.tmp', HISTORY)


def decide_alerts(status, state, now=None):
    """Pure: (messages to send, new state). Alert on ok->warn/crit and on level change,
    repeat after REALERT_H, announce recovery once. 'unknown' never alerts."""
    now = now or time.time()
    msgs, new = [], dict(state)
    for c in status['checks']:
        k, lvl = c['key'], c['level']
        prev = state.get(k) or {}
        if lvl in ('warn', 'crit'):
            due = prev.get('level') != lvl or now - prev.get('at', 0) >= REALERT_H * 3600
            if due:
                msgs.append(f"[{lvl.upper()}] {c['label']}: {c['value']}")
                new[k] = {'level': lvl, 'at': now}
        elif lvl == 'ok' and prev.get('level') in ('warn', 'crit'):
            msgs.append(f"[RECOVERED] {c['label']}: {c['value']}")
            new.pop(k, None)
    return msgs, new


def send_alerts(msgs):
    if not msgs:
        return
    title = f"Server monitor: {len(msgs)} change(s)"
    body = '\n'.join(msgs)
    try:   # in-app notification for the admins (same table the list alerts use)
        import psycopg2
        from config import Config
        conn = psycopg2.connect(connect_timeout=5, **dict(Config.POSTGRES_CONFIG))
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE is_active = 1 AND role = 'admin'")
        now = datetime.now()
        for (uid,) in c.fetchall():
            c.execute("""INSERT INTO notifications (user_id, title, message, type, is_read, link, created_at)
                         VALUES (%s, %s, %s, 'warning', 0, %s, %s)""",
                      (uid, title[:200], body[:2000], '/admin/server-status', now))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'in-app alert failed: {e}')
    to = os.getenv('OPS_ALERT_EMAIL', '').strip()
    if not to:
        return
    try:
        import smtplib
        from email.message import EmailMessage
        from config import Config
        m = EmailMessage()
        m['Subject'] = f'[ComplyNex] {title}'
        m['From'] = Config.MAIL_DEFAULT_SENDER if isinstance(Config.MAIL_DEFAULT_SENDER, str) else Config.MAIL_USERNAME
        m['To'] = to
        m.set_content(body + '\n\nhttps://complynex.online/admin/server-status')
        cls = smtplib.SMTP_SSL if Config.MAIL_USE_SSL else smtplib.SMTP
        with cls(Config.MAIL_SERVER, Config.MAIL_PORT, timeout=20) as s:
            if not Config.MAIL_USE_SSL:
                s.starttls()
            if Config.MAIL_USERNAME:
                s.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            s.send_message(m)
    except Exception as e:
        print(f'e-mail alert failed: {e}')


def main():
    status = collect()
    publish(status)
    try:
        with open(STATE) as f:
            state = json.load(f)
    except Exception:
        state = {}
    msgs, state = decide_alerts(status, state)
    send_alerts(msgs)
    _write_json(STATE, state)
    print(f"{status['overall']}: " + ', '.join(f"{c['key']}={c['level']}" for c in status['checks'] if c['level'] != 'ok'))


if __name__ == '__main__':
    from utils.demo import skip_in_demo
    if not skip_in_demo('server monitor'):
        main()
