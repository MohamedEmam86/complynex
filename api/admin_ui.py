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
API clients page (admin): keys (create, rotate, revoke, sandbox), webhooks (add, disable,
test) and the delivery log. Session-authenticated and CSRF-protected (unlike /api/v1, which
is key-authenticated and CSRF-exempt). A raw key or webhook secret is shown once, on the
response to the POST that made it, and never stored.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_babel import gettext
from flask_login import login_required, current_user

from api import v1_common as C
from api import webhooks as WH
from database.db import get_db
from utils.decorators import admin_required

api_admin_bp = Blueprint('api_admin', __name__, url_prefix='/admin/api-clients')

ROTATE_GRACE_HOURS = 24


def _audit(action, item_id, details):
    try:
        from models.audit import AuditLog
        AuditLog.log(current_user.id, action, 'API', item_id, details, request.remote_addr)
    except Exception:
        pass


def _new_key():
    raw = 'cnx_' + secrets.token_hex(28)
    return raw, hashlib.sha256(raw.encode()).hexdigest(), raw[:8]


def _scopes_from_form():
    allowed = {s for s, _ in C.SCOPES}
    chosen = [s for s in request.form.getlist('scopes') if s in allowed]
    return ','.join(chosen) or 'screening:read'


def _page(new_key=None, new_secret=None):
    db = get_db()
    keys = [dict(r) for r in db.execute(
        """SELECT k.id, k.name, k.key_prefix, k.scopes, k.rate_limit, k.is_active, k.sandbox, k.last_used_at,
                  k.created_at, k.expires_at, k.revoked_at, k.rotated_from, k.description,
                  COALESCE(k.client_id, k.id) AS client,
                  NULLIF(trim(coalesce(u.first_name,'') || ' ' || coalesce(u.last_name,'')), '') AS created_by_name,
                  (SELECT count(*) FROM api_audit_log a WHERE a.key_id = k.id
                     AND a.created_at > now() - interval '24 hours') AS calls_24h
           FROM api_keys k LEFT JOIN users u ON u.id = k.created_by
           ORDER BY COALESCE(k.client_id, k.id), k.id DESC""").fetchall()]
    clients = {}
    for k in keys:
        clients.setdefault(k['client'], {'id': k['client'], 'name': k['name'], 'keys': []})['keys'].append(k)
    hooks = [dict(r) for r in db.execute(
        """SELECT id, client_id, url, events, is_active, created_at, disabled_at FROM api_webhooks
           ORDER BY client_id, id DESC""").fetchall()]
    for h in hooks:
        if h['client_id'] in clients:
            clients[h['client_id']].setdefault('hooks', []).append(h)
    deliveries = [dict(r) for r in db.execute(
        """SELECT d.id, d.webhook_id, d.event, d.status, d.attempts, d.last_status_code, d.last_error,
                  d.created_at, d.delivered_at, d.next_attempt_at, w.client_id
           FROM api_webhook_deliveries d JOIN api_webhooks w ON w.id = d.webhook_id
           ORDER BY d.id DESC LIMIT 50""").fetchall()]
    return render_template('api/clients.html', clients=list(clients.values()), deliveries=deliveries,
                           scopes=C.SCOPES, events=C.EVENTS, new_key=new_key, new_secret=new_secret,
                           grace=ROTATE_GRACE_HOURS)


@api_admin_bp.route('/', methods=['GET'])
@login_required
@admin_required
def clients():
    return _page()


@api_admin_bp.route('/keys/create', methods=['POST'])
@login_required
@admin_required
def key_create():
    name = (request.form.get('name') or '').strip()[:120]
    if not name:
        flash(gettext('Give the client a name.'), 'error')
        return redirect(url_for('api_admin.clients'))
    try:
        rate = max(1, min(10000, int(request.form.get('rate_limit') or 100)))
    except ValueError:
        rate = 100
    exp = (request.form.get('expires_at') or '').strip() or None
    if exp:
        try:
            exp = datetime.fromisoformat(exp).isoformat()
        except ValueError:
            flash(gettext('The expiry date is not valid.'), 'error')
            return redirect(url_for('api_admin.clients'))
    raw, h, prefix = _new_key()
    db = get_db()
    row = db.execute("""INSERT INTO api_keys (name, key_hash, key_prefix, scopes, rate_limit, expires_at, created_by,
                                              owner_id, sandbox, description)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                     (name, h, prefix, _scopes_from_form(), rate, exp, current_user.id, current_user.id,
                      request.form.get('sandbox') == '1', (request.form.get('description') or '')[:500] or None)
                     ).fetchone()
    db.execute("UPDATE api_keys SET client_id = id WHERE id = %s", (row['id'],))
    db.commit()
    _audit('API_KEY_CREATED', row['id'], f'{name} ({prefix}…), sandbox={request.form.get("sandbox") == "1"}')
    return _page(new_key={'id': row['id'], 'name': name, 'key': raw})


@api_admin_bp.route('/keys/<int:key_id>/rotate', methods=['POST'])
@login_required
@admin_required
def key_rotate(key_id):
    db = get_db()
    old = db.execute("SELECT * FROM api_keys WHERE id = %s", (key_id,)).fetchone()
    if not old or not old['is_active']:
        flash(gettext('Only an active key can be rotated.'), 'error')
        return redirect(url_for('api_admin.clients'))
    old = dict(old)
    raw, h, prefix = _new_key()
    now_revoke = request.form.get('revoke_now') == '1'
    row = db.execute("""INSERT INTO api_keys (name, key_hash, key_prefix, scopes, rate_limit, expires_at, created_by,
                                              owner_id, sandbox, description, client_id, rotated_from)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                     (old['name'], h, prefix, old['scopes'], old['rate_limit'], old.get('expires_at'), current_user.id,
                      old.get('owner_id') or current_user.id, old.get('sandbox') or False, old.get('description'),
                      old.get('client_id') or old['id'], old['id'])).fetchone()
    if now_revoke:
        db.execute("""UPDATE api_keys SET is_active = FALSE, revoked_at = now(), revoked_by = %s WHERE id = %s""",
                   (current_user.id, key_id))
    else:   # the old key keeps working for a short grace period so the client can switch
        grace = (datetime.utcnow() + timedelta(hours=ROTATE_GRACE_HOURS)).isoformat()
        db.execute("""UPDATE api_keys SET expires_at = CASE WHEN expires_at IS NULL OR expires_at > %s
                                                             THEN %s ELSE expires_at END WHERE id = %s""",
                   (grace, grace, key_id))
    db.commit()
    _audit('API_KEY_ROTATED', key_id, f'{old["key_prefix"]}… -> {prefix}… (old key '
           f'{"revoked now" if now_revoke else f"valid {ROTATE_GRACE_HOURS} h"})')
    return _page(new_key={'id': row['id'], 'name': old['name'], 'key': raw, 'rotated': True})


@api_admin_bp.route('/keys/<int:key_id>/revoke', methods=['POST'])
@login_required
@admin_required
def key_revoke(key_id):
    db = get_db()
    r = db.execute("""UPDATE api_keys SET is_active = FALSE, revoked_at = now(), revoked_by = %s
                      WHERE id = %s AND is_active RETURNING key_prefix""", (current_user.id, key_id)).fetchone()
    db.commit()
    if r:
        _audit('API_KEY_REVOKED', key_id, f'{r["key_prefix"]}…')
        flash(gettext('The key was revoked.'), 'success')
    return redirect(url_for('api_admin.clients'))


@api_admin_bp.route('/webhooks/create', methods=['POST'])
@login_required
@admin_required
def webhook_create():
    try:
        client = int(request.form.get('client_id') or 0)
    except ValueError:
        client = 0
    db = get_db()
    if not client or not db.execute("SELECT 1 FROM api_keys WHERE COALESCE(client_id, id) = %s", (client,)).fetchone():
        flash(gettext('Unknown client.'), 'error')
        return redirect(url_for('api_admin.clients'))
    url = (request.form.get('url') or '').strip()
    ok_, why = C.check_webhook_url(url)
    if not ok_:
        flash(gettext('The webhook URL was refused: %(why)s', why=why), 'error')
        return redirect(url_for('api_admin.clients'))
    events = [e for e in request.form.getlist('events') if e in C.EVENTS] or list(C.EVENTS)
    secret = WH.new_secret()
    row = db.execute("""INSERT INTO api_webhooks (client_id, url, secret_enc, events, created_by)
                        VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                     (client, url, WH.seal(secret), ','.join(events), current_user.id)).fetchone()
    db.commit()
    _audit('API_WEBHOOK_CREATED', row['id'], f'client {client}: {url} [{",".join(events)}]')
    return _page(new_secret={'id': row['id'], 'url': url, 'secret': secret})


@api_admin_bp.route('/webhooks/<int:hook_id>/disable', methods=['POST'])
@login_required
@admin_required
def webhook_disable(hook_id):
    db = get_db()
    r = db.execute("""UPDATE api_webhooks SET is_active = FALSE, disabled_at = now(), disabled_by = %s
                      WHERE id = %s AND is_active RETURNING url""", (current_user.id, hook_id)).fetchone()
    db.commit()
    if r:
        _audit('API_WEBHOOK_DISABLED', hook_id, r['url'])
        flash(gettext('The webhook was disabled.'), 'success')
    return redirect(url_for('api_admin.clients'))


@api_admin_bp.route('/webhooks/<int:hook_id>/test', methods=['POST'])
@login_required
@admin_required
def webhook_test(hook_id):
    db = get_db()
    h = db.execute("SELECT id, client_id, is_active FROM api_webhooks WHERE id = %s", (hook_id,)).fetchone()
    if not h or not h['is_active']:
        flash(gettext('Only an active webhook can be tested.'), 'error')
        return redirect(url_for('api_admin.clients'))
    body = WH.envelope('webhook.test', {'message': 'Test event from ComplyNex', 'webhook_id': hook_id})
    import json
    db.execute("""INSERT INTO api_webhook_deliveries (webhook_id, event, event_key, payload)
                  VALUES (%s, 'webhook.test', %s, %s)""", (hook_id, body['id'], json.dumps(body)))
    db.commit()
    _audit('API_WEBHOOK_TEST', hook_id, 'test event queued')
    flash(gettext('A test event was queued; it is delivered within a minute.'), 'success')
    return redirect(url_for('api_admin.clients'))
