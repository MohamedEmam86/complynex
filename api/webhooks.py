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
Signed webhooks for the API clients (P6-8): screening.completed, hit.decided, list.updated.

Events are written to api_webhook_deliveries (one row per subscribed webhook, de-duplicated by
event_key) and delivered by scripts/api_webhook_dispatch.py (systemd timer, every minute):
HTTPS POST, header X-ComplyNex-Signature: t=<unix>,v1=<HMAC-SHA256 of '<t>.<body>'>, retries
with back-off, then DEAD. Works with a plain psycopg2 connection (no Flask needed).
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta

from api import v1_common as C

logger = logging.getLogger(__name__)

BACKOFF = (60, 300, 900, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 24 * 3600)   # seconds after attempt n
MAX_ATTEMPTS = len(BACKOFF) + 1
TIMEOUT = 10
USER_AGENT = 'ComplyNex-Webhooks/1'


# --------------------------------------------------------------------------- secrets at rest
def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get('ENCRYPTION_KEY')
    if not key:   # same derivation as data_protection.encryption_service
        from config import Config
        key = base64.urlsafe_b64encode(hashlib.sha256(Config.SECRET_KEY.encode()).digest())
    return Fernet(key)


def new_secret():
    return 'whsec_' + secrets.token_hex(24)


def seal(secret):
    return _fernet().encrypt(secret.encode()).decode()


def unseal(token):
    return _fernet().decrypt(token.encode()).decode()


# --------------------------------------------------------------------------- emitting
def _cur(conn):
    from psycopg2.extras import RealDictCursor
    return conn.cursor(cursor_factory=RealDictCursor)


def envelope(event, data, sandbox=False, event_id=None):
    return {'id': event_id or 'evt_' + uuid.uuid4().hex[:24], 'type': event, 'api_version': C.API_VERSION,
            'created': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'sandbox': bool(sandbox),
            'data': data}


def enqueue(conn, event, data, client_id=None, event_key=None, sandbox=False):
    """Queue an event for the client's active webhooks subscribed to it (client_id None = all
    clients, e.g. list.updated). Returns the number of deliveries queued. Commits."""
    c = _cur(conn)
    if client_id is None:
        c.execute("SELECT id, events FROM api_webhooks WHERE is_active")
    else:
        c.execute("SELECT id, events FROM api_webhooks WHERE is_active AND client_id = %s", (client_id,))
    hooks = [h for h in c.fetchall() if event in [e.strip() for e in (h['events'] or '').split(',')]
             or event == 'webhook.test']
    n = 0
    for h in hooks:
        body = envelope(event, data, sandbox)
        c.execute("""INSERT INTO api_webhook_deliveries (webhook_id, event, event_key, payload)
                     VALUES (%s, %s, %s, %s) ON CONFLICT (webhook_id, event_key) DO NOTHING""",
                  (h['id'], event, event_key or body['id'], json.dumps(body, ensure_ascii=False, default=str)))
        n += c.rowcount
    conn.commit()
    return n


def enqueue_db(db, event, data, client_id, event_key=None, sandbox=False):
    """Same as enqueue() through the app's get_db() wrapper (request context)."""
    rows = db.execute("SELECT id, events FROM api_webhooks WHERE is_active AND client_id = %s",
                      (client_id,)).fetchall()
    n = 0
    for h in rows:
        h = dict(h)
        if event not in [e.strip() for e in (h['events'] or '').split(',')] and event != 'webhook.test':
            continue
        body = envelope(event, data, sandbox)
        db.execute("""INSERT INTO api_webhook_deliveries (webhook_id, event, event_key, payload)
                      VALUES (%s, %s, %s, %s) ON CONFLICT (webhook_id, event_key) DO NOTHING""",
                   (h['id'], event, event_key or body['id'], json.dumps(body, ensure_ascii=False, default=str)))
        n += 1
    db.commit()
    return n


def _cursor_get(c, name):
    c.execute("SELECT value FROM api_event_cursors WHERE name = %s", (name,))
    r = c.fetchone()
    return r['value'] if r else None


def _cursor_set(c, name, value):
    c.execute("""INSERT INTO api_event_cursors (name, value, updated_at) VALUES (%s, %s, now())
                 ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""", (name, str(value)))


def emit_list_updates(conn):
    """list.updated for every list version applied / restored since the last run."""
    c = _cur(conn)
    last = _cursor_get(c, 'list_versions')
    if last is None:   # first run: start from now, do not replay history
        c.execute("SELECT COALESCE(max(id), 0) AS m FROM screening_list_versions")
        _cursor_set(c, 'list_versions', c.fetchone()['m'])
        conn.commit()
        return 0
    c.execute("""SELECT id, source, version_no, status, trigger, finished_at, added, updated, delisted, relisted,
                        active_after
                 FROM screening_list_versions
                 WHERE id > %s AND status IN ('APPLIED', 'RESTORED') AND trigger <> 'baseline'
                 ORDER BY id LIMIT 200""", (int(last),))
    rows = c.fetchall()
    n = 0
    for r in rows:
        data = {'list': r['source'], 'version': r['version_no'], 'status': r['status'],
                'kind': 'rollback' if r['status'] == 'RESTORED' else (r['trigger'] or 'update'),
                'applied_at': r['finished_at'].isoformat() if r['finished_at'] else None,
                'added': r['added'], 'updated': r['updated'], 'delisted': r['delisted'],
                'relisted': r['relisted'], 'active_records': r['active_after']}
        n += enqueue(conn, 'list.updated', data, None, event_key=f"list.updated:{r['id']}")
    if rows:
        _cursor_set(c, 'list_versions', rows[-1]['id'])
        conn.commit()
    return n


def emit_hit_decisions(conn):
    """hit.decided for queue items of API screenings resolved since the last run."""
    c = _cur(conn)
    last = _cursor_get(c, 'queue_resolved')
    if last is None:
        _cursor_set(c, 'queue_resolved', datetime.now(timezone.utc).isoformat(timespec='seconds'))
        conn.commit()
        return 0
    c.execute("""SELECT q.id, q.status, q.resolution, q.resolved_date, q.match_name, q.match_score,
                        q.list_source, s.id AS screening_id, s.client_id, s.sandbox, s.customer_ref
                 FROM screening_queue q JOIN api_screenings s ON s.history_id = q.screening_history_id
                 WHERE q.resolved_date ~ '^\\d{4}-\\d{2}-\\d{2}'
                   AND q.resolved_date::timestamptz >= %s::timestamptz
                 ORDER BY q.resolved_date::timestamptz LIMIT 500""", (last,))
    rows = c.fetchall()
    n = 0
    for r in rows:
        data = {'screening_id': r['screening_id'], 'customer_ref': r['customer_ref'],
                'hit': {'listed_name': r['match_name'], 'source': r['list_source'],
                        'score': float(r['match_score'] or 0)},
                'decision': {'status': r['status'], 'resolution': r['resolution'],
                             'decided_at': r['resolved_date']}}
        n += enqueue(conn, 'hit.decided', data, r['client_id'],
                     event_key=f"hit.decided:{r['id']}:{r['status']}:{r['resolution']}", sandbox=r['sandbox'])
    if rows:
        _cursor_set(c, 'queue_resolved', rows[-1]['resolved_date'])
        conn.commit()
    return n


def emit_batch_completions(conn, store_factory=None):
    """screening.completed for API batch jobs that have finished."""
    c = _cur(conn)
    c.execute("""SELECT s.id, s.client_id, s.job_id, s.sandbox, s.customer_ref, j.status AS job_status,
                        j.total_rows, j.finished_at
                 FROM api_screenings s JOIN screening_bulk_jobs j ON j.id = s.job_id
                 WHERE s.kind = 'batch' AND s.status NOT IN ('DONE', 'DONE_WITH_GAP', 'CANCELLED', 'FAILED')
                   AND j.status IN ('DONE', 'DONE_WITH_GAP', 'CANCELLED', 'FAILED')""")
    rows = c.fetchall()
    n = 0
    for r in rows:
        c.execute("""SELECT status, count(*) AS n FROM screening_bulk_rows WHERE job_id = %s GROUP BY status""",
                  (r['job_id'],))
        counts = {x['status']: x['n'] for x in c.fetchall()}
        c.execute("""SELECT result_status, count(*) AS n FROM screening_bulk_rows WHERE job_id = %s
                     AND result_status IS NOT NULL GROUP BY result_status""", (r['job_id'],))
        results = {x['result_status']: x['n'] for x in c.fetchall()}
        data = {'screening_id': r['id'], 'object': 'batch', 'status': r['job_status'],
                'rows': r['total_rows'], 'row_states': counts, 'results': results}
        n += enqueue(conn, 'screening.completed', data, r['client_id'],
                     event_key=f"batch.completed:{r['id']}", sandbox=r['sandbox'])
        c.execute("UPDATE api_screenings SET status = %s WHERE id = %s", (r['job_status'], r['id']))
        conn.commit()
    return n


# --------------------------------------------------------------------------- delivering
class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def _post(url, body_bytes, headers):
    """POST pinned to the address that was checked: the name is resolved once, every address
    must be public, and the TLS connection goes to that IP with the real host name for SNI,
    certificate check and the Host header (no second lookup that DNS rebinding could change)."""
    import certifi
    import urllib3
    from urllib.parse import urlparse
    u = urlparse(url)
    host, port = u.hostname, u.port or 443
    ip = C.resolve_public_ip(host, port)
    path = (u.path or '/') + (('?' + u.query) if u.query else '')
    pool = urllib3.HTTPSConnectionPool(ip, port=port, server_hostname=host, assert_hostname=host,
                                       cert_reqs='CERT_REQUIRED', ca_certs=certifi.where(),
                                       timeout=urllib3.Timeout(total=TIMEOUT), retries=False, maxsize=1)
    h = dict(headers)
    h['Host'] = host if port == 443 else f'{host}:{port}'
    try:
        r = pool.urlopen('POST', path, body=body_bytes, headers=h, redirect=False,
                         assert_same_host=False, preload_content=True)
        return _Resp(r.status)
    finally:
        pool.close()


def deliver_due(conn, limit=100, post=None, check_url=None):
    """Deliver due events once. Returns {'delivered', 'retry', 'dead'}."""
    post = post or _post
    check_url = check_url or C.check_webhook_url
    c = _cur(conn)
    c.execute("""SELECT d.id, d.webhook_id, d.event, d.payload, d.attempts, w.url, w.secret_enc, w.is_active
                 FROM api_webhook_deliveries d JOIN api_webhooks w ON w.id = d.webhook_id
                 WHERE d.status = 'PENDING' AND d.next_attempt_at <= now()
                 ORDER BY d.next_attempt_at LIMIT %s FOR UPDATE OF d SKIP LOCKED""", (limit,))
    rows = c.fetchall()
    out = {'delivered': 0, 'retry': 0, 'dead': 0}
    for r in rows:
        attempt = int(r['attempts']) + 1
        code, err = None, None
        if not r['is_active']:
            err = 'webhook disabled'
            attempt = MAX_ATTEMPTS
        else:
            ok, why = check_url(r['url'])
            if not ok:
                err = f'URL refused: {why}'
            else:
                payload = r['payload'] if isinstance(r['payload'], dict) else json.loads(r['payload'])
                body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
                try:
                    secret = unseal(r['secret_enc'])
                    headers = {'Content-Type': 'application/json', 'User-Agent': USER_AGENT,
                               'X-ComplyNex-Event': r['event'], 'X-ComplyNex-Delivery': str(r['id']),
                               'X-ComplyNex-Signature': C.sign(secret, body)}
                    resp = post(r['url'], body, headers)
                    code = resp.status_code
                    if not 200 <= code < 300:
                        err = f'HTTP {code}'
                except Exception as e:
                    err = f'{type(e).__name__}: {str(e)[:300]}'
        if err is None:
            c.execute("""UPDATE api_webhook_deliveries SET status = 'DELIVERED', attempts = %s, delivered_at = now(),
                            last_status_code = %s, last_error = NULL WHERE id = %s""", (attempt, code, r['id']))
            out['delivered'] += 1
        elif attempt >= MAX_ATTEMPTS:
            c.execute("""UPDATE api_webhook_deliveries SET status = 'DEAD', attempts = %s, last_status_code = %s,
                            last_error = %s WHERE id = %s""", (attempt, code, err, r['id']))
            out['dead'] += 1
        else:
            delay = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            c.execute("""UPDATE api_webhook_deliveries SET attempts = %s, last_status_code = %s, last_error = %s,
                            next_attempt_at = now() + (%s || ' seconds')::interval WHERE id = %s""",
                      (attempt, code, err, str(delay), r['id']))
            out['retry'] += 1
    conn.commit()
    return out


def purge_idempotency(conn, hours=C.IDEM_TTL_HOURS):
    """Idempotency records only matter for 24 hours (a cache of responses, not a record)."""
    c = _cur(conn)
    c.execute("DELETE FROM api_idempotency WHERE created_at < now() - (%s || ' hours')::interval", (str(hours),))
    n = c.rowcount
    conn.commit()
    return n
