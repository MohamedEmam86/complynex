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
Screening API v1 (P6-2 / P6-8 / G12) — one API for every client system.

  POST /api/v1/screenings                 screen a person or company (Idempotency-Key supported)
  GET  /api/v1/screenings                 the client's screenings (paginated, ?customer_ref=)
  GET  /api/v1/screenings/<id>            one screening + the analysts' decisions on its hits
  POST /api/v1/screenings/batch           up to 5,000 rows, screened in the background
  GET  /api/v1/screenings/batch/<id>      progress, then the result of every row
  GET  /api/v1/lists/status               lists, version in force, freshness
  POST /api/v1/payments/screen            real-time payment screening: PASS / HOLD / BLOCK
  GET  /api/v1/docs                       human-readable reference (signed-in users)

Auth: X-API-Key (hashed at rest, scopes, per-key rate limit, sandbox keys). Every response
carries X-Request-Id; errors use one shape: {"success": false, "error": {"code", "message"},
"request_id"}. A screening is never reported CLEAR when a source was unavailable: the status is
INCOMPLETE with the reasons.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from functools import wraps

from flask import request, jsonify, g, current_app, render_template, Response

from api import api_v1_bp
from api import v1_common as C
from api import webhooks as WH
from database.db import get_db

logger = logging.getLogger(__name__)

PAYMENT_TIMEOUT_MS = int(os.getenv('PAYMENT_SCREEN_TIMEOUT_MS', '3000'))


# --------------------------------------------------------------------------- request id / deprecation
@api_v1_bp.before_request
def _v1_request_id():
    g.request_id = C.request_id_from(request.headers.get('X-Request-Id'))


@api_v1_bp.after_request
def _v1_after(resp):
    rid = getattr(g, 'request_id', None)
    if rid:
        resp.headers['X-Request-Id'] = rid
    if request.path.rstrip('/') == '/api/v1/screening/check':
        resp.headers['Deprecation'] = 'true'
        resp.headers['Link'] = '</api/v1/screenings>; rel="successor-version"'
    return resp


def err(code, message, status, details=None, headers=None):
    r = jsonify(C.error_body(code, message, getattr(g, 'request_id', None), details))
    r.status_code = status
    for k, v in (headers or {}).items():
        r.headers[k] = v
    return r


def ok(body, status=200):
    if isinstance(body, dict):
        body.setdefault('request_id', getattr(g, 'request_id', None))
    r = jsonify(body)
    r.status_code = status
    return r


# --------------------------------------------------------------------------- auth
def v1_key(*scopes):
    """X-API-Key auth for the v1 screening endpoints (new error model; reuses the key table,
    the Redis rate limit and the audit log of api/auth.py)."""
    from api.auth import _hash_key, _check_rate_limit, _write_audit

    def deco(f):
        @wraps(f)
        def wrapped(*a, **kw):
            raw = request.headers.get('X-API-Key', '').strip()
            if not raw:
                return err('unauthenticated', 'Missing X-API-Key header', 401)
            t0 = time.monotonic()
            db = get_db()
            row = db.execute("SELECT * FROM api_keys WHERE key_hash = %s", (_hash_key(raw),)).fetchone()
            if not row:
                _write_audit(None, raw[:8], 401, 0)
                return err('unauthenticated', 'Invalid API key', 401)
            row = dict(row)
            if not row.get('is_active') or row.get('revoked_at'):
                _write_audit(row['id'], row['key_prefix'], 403, 0)
                return err('key_revoked', 'API key is revoked or disabled', 403)
            exp = row.get('expires_at')
            if exp:
                if isinstance(exp, str):
                    exp = datetime.fromisoformat(exp)
                if exp.replace(tzinfo=None) < datetime.utcnow():
                    _write_audit(row['id'], row['key_prefix'], 403, 0)
                    return err('key_expired', 'API key has expired', 403)
            granted = C.scopes_of(row)
            missing = [s for s in scopes if s not in granted]
            if missing:
                _write_audit(row['id'], row['key_prefix'], 403, 0)
                return err('insufficient_scope', f'Scope required: {", ".join(missing)}', 403)
            limit = int(row.get('rate_limit') or 100)
            if not _check_rate_limit(row['id'], limit):
                _write_audit(row['id'], row['key_prefix'], 429, 0)
                return err('rate_limited', 'Rate limit exceeded', 429,
                           headers={'Retry-After': '60', 'X-RateLimit-Limit': str(limit)})
            g.api_key = row
            g.api_client = C.client_of(row)
            g.api_sandbox = bool(row.get('sandbox'))
            resp = f(*a, **kw)
            code = resp.status_code if hasattr(resp, 'status_code') else (resp[1] if isinstance(resp, tuple) else 200)
            _write_audit(row['id'], row['key_prefix'], code, int((time.monotonic() - t0) * 1000))
            if hasattr(resp, 'headers'):
                resp.headers['X-RateLimit-Limit'] = str(limit)
                if g.api_sandbox:
                    resp.headers['X-ComplyNex-Sandbox'] = 'true'
            return resp
        return wrapped
    return deco


def idempotent(f):
    """Idempotency-Key: the same key + same body within 24 h returns the stored response
    (header Idempotent-Replayed: true); the same key with another body is refused."""
    @wraps(f)
    def wrapped(*a, **kw):
        raw = request.headers.get('Idempotency-Key')
        if raw is None:
            return f(*a, **kw)
        key = C.valid_idem_key(raw)
        if not key:
            return err('invalid_idempotency_key', 'Idempotency-Key must be 1-200 printable characters', 400)
        client = g.api_client
        h = C.request_hash(request.method, request.path, request.get_data())
        db = get_db()
        db.execute("""DELETE FROM api_idempotency WHERE client_id = %s AND idem_key = %s
                      AND created_at < now() - interval '24 hours'""", (client, key))
        ins = db.execute("""INSERT INTO api_idempotency (client_id, idem_key, request_hash)
                            VALUES (%s, %s, %s) ON CONFLICT (client_id, idem_key) DO NOTHING RETURNING id""",
                         (client, key, h)).fetchone()
        db.commit()
        if not ins:
            # a request that died mid-way (worker killed) left an in-progress row: after 5 minutes
            # the same request may take it over instead of getting 409 for 24 h
            ins = db.execute("""UPDATE api_idempotency SET created_at = now(), request_hash = %s
                                 WHERE client_id = %s AND idem_key = %s AND status_code IS NULL
                                   AND request_hash = %s AND created_at < now() - interval '5 minutes'
                                 RETURNING id""", (h, client, key, h)).fetchone()
            db.commit()
        if not ins:
            prev = dict(db.execute("""SELECT request_hash, status_code, response FROM api_idempotency
                                      WHERE client_id = %s AND idem_key = %s""", (client, key)).fetchone() or {})
            if prev.get('request_hash') != h:
                return err('idempotency_key_reused', 'This Idempotency-Key was used with a different request', 422)
            if prev.get('status_code') is None:
                return err('request_in_progress', 'A request with this Idempotency-Key is still being processed',
                           409, headers={'Retry-After': '2'})
            body = prev.get('response')
            body = body if isinstance(body, (dict, list)) else json.loads(body or '{}')
            r = jsonify(body)
            r.status_code = int(prev['status_code'])
            r.headers['Idempotent-Replayed'] = 'true'
            return r
        try:
            resp = f(*a, **kw)
        except Exception:
            db.rollback()
            db.execute("DELETE FROM api_idempotency WHERE id = %s", (ins['id'],))
            db.commit()
            raise
        code = resp.status_code
        if code >= 500:   # not stored: the caller may retry
            db.execute("DELETE FROM api_idempotency WHERE id = %s", (ins['id'],))
        else:
            db.execute("UPDATE api_idempotency SET status_code = %s, response = %s WHERE id = %s",
                       (code, resp.get_data(as_text=True), ins['id']))
        db.commit()
        return resp
    return wrapped


# --------------------------------------------------------------------------- helpers
def _acting_user():
    """The user the client's screenings are recorded under (who issued the key)."""
    k = g.api_key
    uid = k.get('owner_id') or k.get('created_by')
    if uid:
        return int(uid)
    r = get_db().execute("SELECT id FROM users WHERE role = 'admin' AND is_active = 1 ORDER BY id LIMIT 1").fetchone()
    return int(r['id']) if r else 1


def _versions_now():
    try:
        from screening import list_versions as LV
        return LV.versions_at_cached(datetime.now(timezone.utc))
    except Exception:
        return {}


def _record(kind, *, customer_ref=None, history_id=None, result_id=None, job_id=None, status=None,
            decision=None, response=None):
    db = get_db()
    row = db.execute("""INSERT INTO api_screenings (client_id, key_id, kind, sandbox, customer_ref, request_id,
                                                    history_id, result_id, job_id, status, decision, response)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                     (g.api_client, g.api_key['id'], kind, g.api_sandbox, customer_ref, g.request_id,
                      history_id, result_id, job_id, status, decision,
                      json.dumps(response, ensure_ascii=False, default=str) if response is not None else None)
                     ).fetchone()
    db.commit()
    return int(row['id'])


def _update_response(sid, response, **cols):
    db = get_db()
    sets, args = ['response = %s'], [json.dumps(response, ensure_ascii=False, default=str)]
    for k, v in cols.items():
        if k in ('history_id', 'result_id', 'status', 'decision', 'job_id'):
            sets.append(f'{k} = %s')
            args.append(v)
    db.execute(f"UPDATE api_screenings SET {', '.join(sets)} WHERE id = %s", args + [sid])
    db.commit()


def _emit(event, data, key):
    try:
        WH.enqueue_db(get_db(), event, data, g.api_client, event_key=key, sandbox=g.api_sandbox)
    except Exception as e:
        logger.warning('[API] webhook enqueue failed: %s', e)
        try:
            get_db().rollback()
        except Exception:
            pass


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- screenings
@api_v1_bp.route('/screenings', methods=['POST'])
@v1_key('screening:write')
@idempotent
def v1_create_screening():
    data = _json_body()
    if data is None:
        return err('invalid_request', 'Request body must be a JSON object', 400)
    f, errs = C.parse_screening_input(data)
    if errs:
        return err('validation_failed', 'Some fields are missing or invalid', 422, details=errs)
    query = {k: f[k] for k in ('name', 'entity_type', 'dob', 'nationality')}
    query['national_id_given'] = bool(f['national_id'])
    if g.api_sandbox:
        res = C.sandbox_result(f['name'])
        sid = _record('screening', customer_ref=f['customer_ref'], status=res['screening_result'])
        body = C.screening_view(sid, res, query, g.request_id, {}, sandbox=True, customer_ref=f['customer_ref'])
    else:
        from screening.customer_screening_service import screen_and_save
        try:
            res = screen_and_save(name=f['name'], entity_type=f['entity_type'], dob=f['dob'],
                                  nationality=f['nationality'], national_id=f['national_id'],
                                  source_module='Public API', source_record_id=None,
                                  screening_type='API', user_id=_acting_user(), results_screening_type='API')
        except Exception as e:
            logger.exception('[API] screening failed')
            return err('engine_unavailable', 'The screening engine failed; retry later', 503,
                       headers={'Retry-After': '30'})
        finally:
            try:
                from screening.routes import get_engine
                _release_engine_conn(get_engine())
            except Exception:
                pass
        sid = _record('screening', customer_ref=f['customer_ref'], history_id=res.get('history_id'),
                      result_id=res.get('results_id'), status=res.get('screening_result'))
        body = C.screening_view(sid, res, query, g.request_id, _versions_now(), customer_ref=f['customer_ref'])
    _update_response(sid, body, status=body['status'])
    _emit('screening.completed', {'screening_id': sid, 'object': 'screening', 'status': body['status'],
                                  'incomplete': body['incomplete'], 'hit_count': body['hit_count'],
                                  'requires_review': body['requires_review'], 'customer_ref': f['customer_ref']},
          f'screening.completed:{sid}')
    return ok(body, 201)


def _own(sid, kinds):
    row = get_db().execute("""SELECT * FROM api_screenings WHERE id = %s AND client_id = %s AND kind = ANY(%s)""",
                           (sid, g.api_client, list(kinds))).fetchone()
    return dict(row) if row else None


def _review_of(history_id):
    if not history_id:
        return []
    rows = get_db().execute("""SELECT match_name, list_source, match_score, status, resolution, resolved_date
                               FROM screening_queue WHERE screening_history_id = %s ORDER BY id""",
                            (history_id,)).fetchall()
    return [{'listed_name': r['match_name'], 'source': r['list_source'],
             'score': float(r['match_score'] or 0), 'status': r['status'], 'resolution': r['resolution'],
             'decided_at': r['resolved_date'] or None} for r in rows]


@api_v1_bp.route('/screenings/<int:sid>', methods=['GET'])
@v1_key('screening:read')
def v1_get_screening(sid):
    row = _own(sid, ('screening', 'payment'))
    if not row:
        return err('not_found', 'No such screening for this client', 404)
    body = row['response'] if isinstance(row['response'], dict) else json.loads(row['response'] or '{}')
    body['review'] = _review_of(row.get('history_id'))
    body['request_id'] = g.request_id
    return ok(body)


@api_v1_bp.route('/screenings', methods=['GET'])
@v1_key('screening:read')
def v1_list_screenings():
    try:
        page = max(1, int(request.args.get('page', 1)))
        per = min(100, max(1, int(request.args.get('per_page', 25))))
    except ValueError:
        return err('invalid_request', 'page and per_page must be integers', 400)
    ref = C.clean_str(request.args.get('customer_ref'), 200)
    args = [g.api_client]
    where = 'client_id = %s'
    if ref:
        where += ' AND customer_ref = %s'
        args.append(ref)
    db = get_db()
    total = db.execute(f"SELECT count(*) AS n FROM api_screenings WHERE {where}", args).fetchone()['n']
    rows = db.execute(f"""SELECT id, kind, sandbox, customer_ref, status, decision, created_at FROM api_screenings
                          WHERE {where} ORDER BY id DESC LIMIT %s OFFSET %s""", args + [per, (page - 1) * per]).fetchall()
    return ok({'object': 'list', 'page': page, 'per_page': per, 'total': int(total),
               'data': [{**dict(r), 'created_at': r['created_at'].isoformat() if r['created_at'] else None}
                        for r in rows]})


# --------------------------------------------------------------------------- batch
@api_v1_bp.route('/screenings/batch', methods=['POST'])
@v1_key('screening:write')
@idempotent
def v1_create_batch():
    data = _json_body()
    rows = (data or {}).get('rows')
    if not isinstance(rows, list) or not rows:
        return err('validation_failed', 'rows must be a non-empty list', 422)
    if len(rows) > C.MAX_BATCH_ROWS:
        return err('too_many_rows', f'At most {C.MAX_BATCH_ROWS} rows per batch', 413)
    clean, problems = [], []
    for i, r in enumerate(rows, 1):
        f, errs = C.parse_screening_input(r)
        if errs:
            problems.append({'row': i, 'errors': errs})
            continue
        clean.append({'name': f['name'], 'entity_type': 'company' if f['entity_type'] == 'ENTITY' else 'person',
                      'dob': f['dob'] or '', 'nationality': f['nationality'] or '',
                      'national_id': f['national_id'] or '', 'customer_ref': f['customer_ref'] or ''})
    if problems:
        return err('validation_failed', 'Some rows are invalid; nothing was started', 422, details=problems[:100])
    if g.api_sandbox:
        results = []
        for i, r in enumerate(clean, 1):
            res = C.sandbox_result(r['name'])
            results.append({'row': i, 'customer_ref': r['customer_ref'] or None, 'status': res['screening_result'],
                            'hit_count': len(res['matches'])})
        body = {'object': 'batch', 'sandbox': True, 'status': 'DONE', 'rows': len(clean), 'results': results}
        sid = _record('batch', status='DONE', response=body)
        body['id'] = sid
        _update_response(sid, body)
        _emit('screening.completed', {'screening_id': sid, 'object': 'batch', 'status': 'DONE', 'rows': len(clean)},
              f'batch.completed:{sid}')
        return ok(body, 201)
    from screening import bulk_jobs as BJ
    from screening import list_versions as LV
    store = BJ.SqlStore(LV.connect())
    try:
        busy = [x for x in store.running_jobs() if not BJ.is_stale(x)]
        if len(busy) >= BJ.MAX_CONCURRENT:
            return err('capacity', 'Batch capacity is in use; retry later', 503, headers={'Retry-After': '300'})
        uid = _acting_user()
        jid = store.create_job(uid, f"api:{g.api_key['key_prefix']}:{g.request_id}", list(BJ.FIELDS), clean)
        BJ.prepare(store, jid, {f: f for f in BJ.FIELDS}, 'INDIVIDUAL')
    finally:
        try:
            store.conn.close()
        except Exception:
            pass
    sid = _record('batch', job_id=jid, status='RUNNING')
    try:
        from screening.routes import _bulk_launch
        _bulk_launch(jid)
    except Exception:
        logger.exception('[API] batch launch failed')
        _update_response(sid, {'object': 'batch', 'status': 'FAILED'}, status='FAILED')
        return err('engine_unavailable', 'The batch could not be started; retry later', 503)
    body = {'id': sid, 'object': 'batch', 'sandbox': False, 'status': 'RUNNING', 'rows': len(clean),
            'status_url': f'/api/v1/screenings/batch/{sid}'}
    _update_response(sid, body)
    return ok(body, 202)


@api_v1_bp.route('/screenings/batch/<int:sid>', methods=['GET'])
@v1_key('screening:read')
def v1_get_batch(sid):
    row = _own(sid, ('batch',))
    if not row:
        return err('not_found', 'No such batch for this client', 404)
    if row['sandbox'] or not row.get('job_id'):
        body = row['response'] if isinstance(row['response'], dict) else json.loads(row['response'] or '{}')
        body['request_id'] = g.request_id
        return ok(body)
    try:
        page = max(1, int(request.args.get('page', 1)))
        per = min(1000, max(1, int(request.args.get('per_page', 500))))
    except ValueError:
        return err('invalid_request', 'page and per_page must be integers', 400)
    from screening import bulk_jobs as BJ
    from screening import list_versions as LV
    store = BJ.SqlStore(LV.connect())
    try:
        prog = BJ.progress_of(store, row['job_id'])
        out = {'id': sid, 'object': 'batch', 'sandbox': False, 'status': prog.get('status'),
               'progress': {k: prog.get(k) for k in ('total', 'finished', 'done', 'failed', 'skipped')},
               'stale_worker': bool(prog.get('stale'))}
        if prog.get('status') in ('DONE', 'DONE_WITH_GAP', 'CANCELLED', 'FAILED'):
            rows = store.rows_for_report(row['job_id'], flagged_only=False)
            part = rows[(page - 1) * per: page * per]
            out['page'], out['per_page'], out['total_rows'] = page, per, len(rows)
            out['results'] = [{'row': r['row_no'], 'customer_ref': r.get('customer_ref') or None,
                               'state': r['status'], 'status': r.get('result_status'),
                               'incomplete': r.get('result_status') == 'INCOMPLETE',
                               'hit_count': r.get('match_count'), 'highest_score': r.get('highest_score'),
                               'error': r.get('error') if r['status'] in ('FAILED', 'SKIPPED') else None}
                              for r in part]
    finally:
        try:
            store.conn.close()
        except Exception:
            pass
    return ok(out)


# --------------------------------------------------------------------------- lists
@api_v1_bp.route('/lists/status', methods=['GET'])
@v1_key('screening:read')
def v1_lists_status():
    try:
        from screening import list_versions as LV
        fr = LV.cached_freshness()
    except Exception:
        return err('unavailable', 'List status is unavailable', 503)

    def iso(v):
        return v.isoformat() if hasattr(v, 'isoformat') else v
    lists = [{'list': x['source'], 'name': x['name'], 'version': x['version_no'], 'state': x['state'],
              'problem': x['problem'], 'last_update': iso(x['last_ok']),
              'age_hours': round(x['age_hours'], 1) if x['age_hours'] is not None else None,
              'max_age_hours': x['max_age_hours'], 'records': x['records']} for x in fr]
    overall = 'red' if any(x['state'] == 'red' for x in lists) else \
        'amber' if any(x['state'] == 'amber' for x in lists) else 'green'
    return ok({'object': 'list_status', 'overall': overall, 'lists': lists})


# --------------------------------------------------------------------------- payments (G12)
def _party(p, role):
    if not isinstance(p, dict):
        return None, [{'field': role, 'message': 'an object with name (and country) is required'}]
    name = C.clean_str(p.get('name'), 300)
    if not name:
        return None, [{'field': f'{role}.name', 'message': 'required'}]
    et = C.ENTITY_TYPES.get(C.clean_str(p.get('type') or 'person', 30).lower(), 'INDIVIDUAL')
    return {'role': role, 'name': name, 'country': C.clean_str(p.get('country'), 80) or None,
            'entity_type': et, 'account': C.clean_str(p.get('account'), 80) or None}, []


def _release_engine_conn(engine):
    """The engine keeps one pooled DB connection per greenlet (threading.local under gevent)
    and never gives it back when the greenlet ends: 20 short-lived greenlets exhaust its pool
    (measured: "connection pool exhausted" after ~20 parallel screenings). Return this
    greenlet's connection when its screening is done."""
    try:
        engine.close()
    except Exception:
        pass


def _screen_parties_fast(parties, timeout_ms):
    """Name screening of the parties in parallel (no adverse media). A party not done in time
    is INCOMPLETE, never CLEAR."""
    from screening.routes import get_engine
    engine = get_engine()
    out = {}

    def one(p):
        t = time.perf_counter()
        try:
            r = engine.screen_person(name=p['name'], nationality=p['country'], entity_type=p['entity_type'],
                                     include_media=False, screening_type=('PAYMENT', 'PAYMENT'))
            out[p['role']] = (r, None, (time.perf_counter() - t) * 1000)
        except Exception as e:
            out[p['role']] = (None, e, (time.perf_counter() - t) * 1000)
        finally:
            _release_engine_conn(engine)
    try:
        import gevent
        jobs = [gevent.spawn(one, p) for p in parties]
        gevent.joinall(jobs, timeout=timeout_ms / 1000.0)
        for j in jobs:
            if not j.ready():
                j.kill(block=False)
    except ImportError:
        import threading
        ts = [threading.Thread(target=one, args=(p,), daemon=True) for p in parties]
        for t in ts:
            t.start()
        deadline = time.monotonic() + timeout_ms / 1000.0
        for t in ts:
            t.join(max(0.0, deadline - time.monotonic()))
    return out


def _persist_hits_in_background(sid, parties_to_save, user_id):
    """HOLD / BLOCK: store a full screening of the party with hits, so the analysts get queue
    items, the result page and the evidence pack; linked back to this payment screening."""
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                from screening.customer_screening_service import screen_and_save
                hist = None
                for p in parties_to_save:
                    res = screen_and_save(name=p['name'], entity_type=p['entity_type'], nationality=p['country'],
                                          source_module='Payment API', source_record_id=int(sid),
                                          screening_type='API', user_id=user_id, results_screening_type='API',
                                          screen_parties=False)
                    hist = hist or res.get('history_id')
                if hist:
                    db = get_db()
                    db.execute("UPDATE api_screenings SET history_id = %s WHERE id = %s", (hist, sid))
                    db.commit()
            except Exception:
                logger.exception('[API] payment evidence save failed for %s', sid)
            finally:
                # this greenlet's engine connection goes back to the pool (else ~20 HOLD /
                # BLOCK payments exhaust it)
                try:
                    from app import release_screening_db_conn
                    release_screening_db_conn()
                except Exception:
                    pass
    try:
        import gevent
        gevent.spawn(run)
    except ImportError:
        import threading
        threading.Thread(target=run, daemon=True).start()


@api_v1_bp.route('/payments/screen', methods=['POST'])
@v1_key('payments:screen')
@idempotent
def v1_payment_screen():
    t0 = time.perf_counter()
    data = _json_body()
    if data is None:
        return err('invalid_request', 'Request body must be a JSON object', 400)
    payer, e1 = _party(data.get('payer'), 'payer')
    payee, e2 = _party(data.get('payee'), 'payee')
    errs = e1 + e2
    amount = data.get('amount')
    if amount is not None and not isinstance(amount, (int, float)):
        errs.append({'field': 'amount', 'message': 'a number'})
    if errs:
        return err('validation_failed', 'Some fields are missing or invalid', 422, details=errs)
    parties = [payer, payee]
    out_parties = []
    if g.api_sandbox:
        for p in parties:
            res = C.sandbox_result(p['name'])
            v = C.screening_view(None, res, {}, None, {}, sandbox=True)
            out_parties.append({'role': p['role'], 'name': p['name'], 'status': v['status'],
                                'incomplete': v['incomplete'], 'incomplete_reasons': v['incomplete_reasons'],
                                'hits': v['hits'], 'latency_ms': 0})
    else:
        results = _screen_parties_fast(parties, PAYMENT_TIMEOUT_MS)
        for p in parties:
            res, exc, ms = results.get(p['role'], (None, None, None))
            if res is None:
                why = 'timeout' if exc is None else 'engine_error'
                out_parties.append({'role': p['role'], 'name': p['name'], 'status': 'INCOMPLETE', 'incomplete': True,
                                    'incomplete_reasons': [{'code': why,
                                                            'en': 'The screening did not finish in time.' if why == 'timeout'
                                                            else 'The screening engine failed.',
                                                            'ar': 'الفحص ماخلصش في الوقت.' if why == 'timeout'
                                                            else 'محرك الفحص فشل.'}],
                                    'hits': [], 'latency_ms': round(ms) if ms else None})
                continue
            v = C.screening_view(None, res, {}, None, {})
            out_parties.append({'role': p['role'], 'name': p['name'], 'status': v['status'],
                                'incomplete': v['incomplete'], 'incomplete_reasons': v['incomplete_reasons'],
                                'hits': [h for h in v['hits'] if h['tier'] in ('CONFIRMED', 'POTENTIAL', 'LOW')],
                                'latency_ms': round(ms)})
    decision, reasons = C.payment_decision(out_parties)
    body = {'object': 'payment_screening', 'sandbox': g.api_sandbox, 'decision': decision, 'reasons': reasons,
            'reference': C.clean_str(data.get('reference'), 120) or None,
            'amount': data.get('amount'), 'currency': C.clean_str(data.get('currency'), 3).upper() or None,
            'parties': out_parties,
            'list_versions': {} if g.api_sandbox else _versions_now(),
            'latency_ms': round((time.perf_counter() - t0) * 1000),
            'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    sid = _record('payment', customer_ref=body['reference'], status=decision, decision=decision)
    body['id'] = sid
    _update_response(sid, body)
    if decision in ('HOLD', 'BLOCK') and not g.api_sandbox:
        save = [p for p, op in zip(parties, out_parties) if op['hits'] or op['incomplete']]
        if save:
            _persist_hits_in_background(sid, save, _acting_user())
    _emit('screening.completed', {'screening_id': sid, 'object': 'payment_screening', 'decision': decision,
                                  'reference': body['reference']}, f'payment.completed:{sid}')
    return ok(body, 200)


# --------------------------------------------------------------------------- docs
@api_v1_bp.route('/docs', methods=['GET'])
def v1_docs():
    from flask_login import current_user
    if not current_user.is_authenticated:
        return err('unauthenticated', 'Sign in to read the API reference', 401)
    from api.routes import OPENAPI_SPEC
    return render_template('api/docs.html', spec=OPENAPI_SPEC, sandbox_help=C.SANDBOX_HELP, events=C.EVENTS)


# --------------------------------------------------------------------------- OpenAPI (added to api.routes.OPENAPI_SPEC)
def _schema_ref(name):
    return {'$ref': f'#/components/schemas/{name}'}


_JSON = 'application/json'
_ERR = {'description': 'Error', 'content': {_JSON: {'schema': _schema_ref('Error')}}}
_STD = {'401': _ERR, '403': _ERR, '422': _ERR, '429': _ERR}
_IDEM = {'name': 'Idempotency-Key', 'in': 'header', 'required': False, 'schema': {'type': 'string', 'maxLength': 200},
         'description': 'Same key + same body within 24 h returns the first response (Idempotent-Replayed: true).'}

V1_SCHEMAS = {
    'Error': {'type': 'object', 'properties': {
        'success': {'type': 'boolean', 'example': False},
        'error': {'type': 'object', 'properties': {'code': {'type': 'string'}, 'message': {'type': 'string'},
                                                   'details': {}}},
        'request_id': {'type': 'string'}}},
    'ScreeningRequest': {'type': 'object', 'required': ['name'], 'properties': {
        'name': {'type': 'string', 'maxLength': 300},
        'entity_type': {'type': 'string', 'enum': ['person', 'company'], 'default': 'person'},
        'dob': {'type': 'string', 'description': 'YYYY, YYYY-MM or YYYY-MM-DD'},
        'nationality': {'type': 'string', 'description': 'country name or ISO code'},
        'national_id': {'type': 'string'},
        'customer_ref': {'type': 'string', 'description': 'your own reference, returned as given'}}},
    'Hit': {'type': 'object', 'properties': {
        'listed_name': {'type': 'string'}, 'listed_name_ar': {'type': 'string'}, 'source': {'type': 'string'},
        'list_reference': {'type': 'string'}, 'list_type': {'type': 'string'}, 'score': {'type': 'number'},
        'tier': {'type': 'string', 'enum': ['CONFIRMED', 'POTENTIAL', 'LOW', 'BELOW']},
        'identity': {'type': 'string'}, 'identity_status': {'type': 'object'}, 'legal_status': {'type': 'string'},
        'explanation': {}, 'action': {'type': 'object'}, 'grouped_under': {'type': 'string'},
        'pep_related': {'type': 'boolean'}}},
    'Screening': {'type': 'object', 'properties': {
        'id': {'type': 'integer'}, 'object': {'type': 'string', 'example': 'screening'}, 'sandbox': {'type': 'boolean'},
        'customer_ref': {'type': 'string'},
        'status': {'type': 'string', 'enum': ['CLEAR', 'LOW_MATCH', 'POTENTIAL_MATCH', 'CONFIRMED_HIT',
                                              'WHITE_LISTED', 'INCOMPLETE']},
        'incomplete': {'type': 'boolean'}, 'incomplete_reasons': {'type': 'array', 'items': {'type': 'object'}},
        'requires_review': {'type': 'boolean'}, 'hit_count': {'type': 'integer'},
        'hits': {'type': 'array', 'items': _schema_ref('Hit')},
        'list_versions': {'type': 'object', 'additionalProperties': {'type': 'integer'}},
        'review': {'type': 'array', 'items': {'type': 'object'}, 'description': 'GET only: analyst decisions'},
        'request_id': {'type': 'string'}}},
    'Party': {'type': 'object', 'required': ['name'], 'properties': {
        'name': {'type': 'string'}, 'country': {'type': 'string'},
        'type': {'type': 'string', 'enum': ['person', 'company']}, 'account': {'type': 'string'}}},
    'PaymentRequest': {'type': 'object', 'required': ['payer', 'payee'], 'properties': {
        'payer': _schema_ref('Party'), 'payee': _schema_ref('Party'), 'amount': {'type': 'number'},
        'currency': {'type': 'string'}, 'reference': {'type': 'string'}}},
    'PaymentScreening': {'type': 'object', 'properties': {
        'id': {'type': 'integer'}, 'decision': {'type': 'string', 'enum': ['PASS', 'HOLD', 'BLOCK']},
        'reasons': {'type': 'array', 'items': {'type': 'object'}}, 'parties': {'type': 'array', 'items': {'type': 'object'}},
        'list_versions': {'type': 'object'}, 'latency_ms': {'type': 'integer'}}},
}

V1_PATHS = {
    '/screenings': {
        'post': {'summary': 'Screen a person or company', 'tags': ['Screening v1'],
                 'security': [{'ApiKeyAuth': ['screening:write']}], 'parameters': [_IDEM],
                 'requestBody': {'required': True, 'content': {_JSON: {'schema': _schema_ref('ScreeningRequest')}}},
                 'responses': {'201': {'description': 'Screening result',
                                       'content': {_JSON: {'schema': _schema_ref('Screening')}}},
                               '409': _ERR, '503': _ERR, **_STD}},
        'get': {'summary': "The client's screenings", 'tags': ['Screening v1'],
                'security': [{'ApiKeyAuth': ['screening:read']}],
                'parameters': [{'name': 'customer_ref', 'in': 'query', 'schema': {'type': 'string'}},
                               {'name': 'page', 'in': 'query', 'schema': {'type': 'integer'}},
                               {'name': 'per_page', 'in': 'query', 'schema': {'type': 'integer', 'maximum': 100}}],
                'responses': {'200': {'description': 'Page of screenings'}, **_STD}}},
    '/screenings/{id}': {
        'get': {'summary': 'One screening with the analysts\' decisions', 'tags': ['Screening v1'],
                'security': [{'ApiKeyAuth': ['screening:read']}],
                'parameters': [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}}],
                'responses': {'200': {'description': 'Screening', 'content': {_JSON: {'schema': _schema_ref('Screening')}}},
                              '404': _ERR, **_STD}}},
    '/screenings/batch': {
        'post': {'summary': 'Screen up to 5,000 rows in the background', 'tags': ['Screening v1'],
                 'security': [{'ApiKeyAuth': ['screening:write']}], 'parameters': [_IDEM],
                 'requestBody': {'required': True, 'content': {_JSON: {'schema': {
                     'type': 'object', 'required': ['rows'],
                     'properties': {'rows': {'type': 'array', 'maxItems': 5000, 'items': _schema_ref('ScreeningRequest')}}}}}},
                 'responses': {'202': {'description': 'Batch started'}, '413': _ERR, '503': _ERR, **_STD}}},
    '/screenings/batch/{id}': {
        'get': {'summary': 'Batch progress and per-row results', 'tags': ['Screening v1'],
                'security': [{'ApiKeyAuth': ['screening:read']}],
                'parameters': [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}},
                               {'name': 'page', 'in': 'query', 'schema': {'type': 'integer'}},
                               {'name': 'per_page', 'in': 'query', 'schema': {'type': 'integer', 'maximum': 1000}}],
                'responses': {'200': {'description': 'Batch'}, '404': _ERR, **_STD}}},
    '/lists/status': {
        'get': {'summary': 'Lists, version in force and freshness', 'tags': ['Screening v1'],
                'security': [{'ApiKeyAuth': ['screening:read']}],
                'responses': {'200': {'description': 'List status'}, **_STD}}},
    '/payments/screen': {
        'post': {'summary': 'Real-time payment screening (PASS / HOLD / BLOCK)', 'tags': ['Payments'],
                 'description': 'Name screening of payer and payee in parallel, no adverse media. A party not '
                                'screened in time is INCOMPLETE and the payment is held, never passed.',
                 'security': [{'ApiKeyAuth': ['payments:screen']}], 'parameters': [_IDEM],
                 'requestBody': {'required': True, 'content': {_JSON: {'schema': _schema_ref('PaymentRequest')}}},
                 'responses': {'200': {'description': 'Decision',
                                       'content': {_JSON: {'schema': _schema_ref('PaymentScreening')}}}, **_STD}}},
}


def _register_spec():
    try:
        from api.routes import OPENAPI_SPEC
        OPENAPI_SPEC['info']['version'] = '1.1.0'
        OPENAPI_SPEC['components'].setdefault('schemas', {}).update(V1_SCHEMAS)
        OPENAPI_SPEC['paths'].update(V1_PATHS)
        old = OPENAPI_SPEC['paths'].get('/screening/check', {}).get('post')
        if old is not None:
            old['deprecated'] = True
            old['description'] = 'Deprecated: use POST /screenings.'
        OPENAPI_SPEC.setdefault('x-webhooks', {e: {'signature': 'X-ComplyNex-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "t.body">'}
                                              for e in C.EVENTS})
    except Exception as e:
        logger.warning('[API] spec update failed: %s', e)


_register_spec()
