# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Security pages (Phase 6: P6-5 audit integrity, P6-6 access review / unlock).

* /admin/security/access-review  — who has what: role, CMS level, module rights,
  MFA, last login, lock state, expiry. Excel export (audited). "Record review"
  stores a signed-off review (who, when, note, sha256 of what was reviewed).
* /admin/users/<id>/unlock       — administrator unlock of a locked account.
* /admin/security/audit-chain    — integrity of the audit trail + anchors.
Viewing: administrators and compliance roles. Unlock: administrators only.
"""
import hashlib
import io
import json
from datetime import datetime

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from admin import admin_bp
from models.audit import AuditLog

SECURITY_VIEW_ROLES = ('admin', 'compliance_officer', 'compliance_manager')


def _can_view():
    return getattr(current_user, 'is_authenticated', False) and current_user.role in SECURITY_VIEW_ROLES


def _ip():
    return (request.headers.get('X-Forwarded-For', request.remote_addr or '') or '').split(',')[0].strip()[:45]


def _xl(v):
    if v is None:
        return ''
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    return "'" + s if s[:1] in ('=', '+', '-', '@', '\t', '\r') else s


def _access_rows():
    from database.db import query_db
    from models.user import User
    rows = query_db("SELECT * FROM users ORDER BY is_active DESC, role, first_name, last_name") or []
    out = []
    for r in rows:
        r = dict(r)
        perms = {k[5:]: v for k, v in r.items()
                 if k.startswith('perm_') and v not in (None, '', 'none', False, 0)}
        try:
            u = User.get_by_id(r['id'])
            mfa_req = bool(u.mfa_required()) if u else False
        except Exception:
            mfa_req = False
        locked = bool(r.get('locked_until') and r['locked_until'] > datetime.now(r['locked_until'].tzinfo))
        out.append({
            'id': r['id'], 'name': f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip() or r['email'],
            'email': r['email'], 'role': r.get('role'), 'cms_access_level': r.get('cms_access_level'),
            'active': bool(r.get('is_active')), 'temporary': bool(r.get('is_temporary')),
            'expires_at': r.get('expires_at'), 'last_login': r.get('last_login'),
            'mfa_enabled': bool(r.get('mfa_enabled')), 'mfa_required': mfa_req,
            'mfa_backup_left': _codes_left(r.get('mfa_backup_codes')),
            'locked': locked, 'locked_until': r.get('locked_until') if locked else None,
            'lock_count': r.get('lock_count') or 0,
            'perms': perms,
        })
    return out


def _codes_left(stored):
    try:
        from auth.mfa_policy import remaining
        return remaining(stored)
    except Exception:
        return 0


def _snapshot_sha(rows):
    canon = [{k: (str(v) if v is not None else None) for k, v in sorted(r.items()) if k != 'locked_until'}
             for r in rows]
    return hashlib.sha256(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@admin_bp.route('/security/access-review')
@login_required
def access_review():
    if not _can_view():
        abort(403)
    rows = _access_rows()
    if request.args.get('export') == 'xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = 'Access review'
        head = [_('Name'), _('Email'), _('Role'), _('CMS access'), _('Active'), _('Temporary'), _('Expires'),
                _('Last login'), _('MFA enabled'), _('MFA required'), _('Backup codes left'), _('Locked'),
                _('Module rights')]
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([_xl(x) for x in (
                r['name'], r['email'], r['role'], r['cms_access_level'], 'yes' if r['active'] else 'no',
                'yes' if r['temporary'] else 'no', r['expires_at'] and str(r['expires_at'])[:16],
                r['last_login'] and str(r['last_login'])[:16], 'yes' if r['mfa_enabled'] else 'no',
                'yes' if r['mfa_required'] else 'no', r['mfa_backup_left'], 'yes' if r['locked'] else 'no',
                ', '.join(f'{k}: {v}' for k, v in sorted(r['perms'].items())))])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        AuditLog.log(current_user.id, 'Export', 'Security', None,
                     f'Access review exported ({len(rows)} users)', _ip())
        return send_file(buf, as_attachment=True,
                         download_name=f'access_review_{datetime.now():%Y%m%d_%H%M}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    from database.db import query_db
    try:
        reviews = query_db("""SELECT r.*, TRIM(COALESCE(u.first_name,'')||' '||COALESCE(u.last_name,'')) AS reviewer
                                FROM access_reviews r LEFT JOIN users u ON u.id = r.reviewed_by
                               ORDER BY r.reviewed_at DESC LIMIT 12""") or []
    except Exception:
        reviews = []
    stats = {
        'active': sum(1 for r in rows if r['active']),
        'no_mfa_required': sum(1 for r in rows if r['active'] and r['mfa_required'] and not r['mfa_enabled']),
        'locked': sum(1 for r in rows if r['locked']),
        'privileged': sum(1 for r in rows if r['active'] and r['role'] in SECURITY_VIEW_ROLES),
        'never_logged_in': sum(1 for r in rows if r['active'] and not r['last_login']),
    }
    return render_template('admin/security/access_review.html', rows=rows, reviews=reviews, stats=stats,
                           can_unlock=current_user.is_admin())


@admin_bp.route('/security/access-review/record', methods=['POST'])
@login_required
def access_review_record():
    if not _can_view():
        abort(403)
    note = (request.form.get('note') or '').strip()
    if len(note) < 15:
        flash(_('Describe the review in at least 15 characters.'), 'danger')
        return redirect(url_for('admin.access_review'))
    rows = _access_rows()
    sha = _snapshot_sha(rows)
    from database.db import execute_db
    execute_db("INSERT INTO access_reviews (reviewed_by, users_count, note, snapshot_sha256) VALUES (%s,%s,%s,%s)",
               (current_user.id, len(rows), note[:2000], sha))
    AuditLog.log(current_user.id, 'Access Review', 'Security', None,
                 f'User access review recorded ({len(rows)} users, sha256 {sha[:16]}): {note[:200]}', _ip())
    flash(_('Access review recorded.'), 'success')
    return redirect(url_for('admin.access_review'))


@admin_bp.route('/users/<int:user_id>/unlock', methods=['POST'])
@login_required
def unlock_user(user_id):
    if not current_user.is_admin():
        abort(403)
    from auth import guard
    from database.db import query_db
    target = query_db("SELECT id, email FROM users WHERE id = %s", (user_id,), one=True)
    if not target:
        abort(404)
    guard.unlock(user_id)
    AuditLog.log(current_user.id, 'Account Unlocked', 'Security', user_id,
                 f"Account {target['email']} unlocked by an administrator", _ip())
    flash(_('Account unlocked.'), 'success')
    back = request.form.get('back') or ''
    return redirect(back if back.startswith('/admin/') else url_for('admin.access_review'))


@admin_bp.route('/security/audit-chain')
@login_required
def audit_chain():
    if not _can_view():
        abort(403)
    from database.db import get_db
    from utils import audit_chain as AC
    db = get_db()
    res = AC.check(db)
    try:
        anchors = AC.recent_anchors(db)
    except Exception:
        anchors = []
        try:
            db.rollback()
        except Exception:
            pass
    return render_template('admin/security/audit_chain.html', res=res, anchors=anchors)


@admin_bp.route('/security/audit-chain/anchor', methods=['POST'])
@login_required
def audit_chain_anchor():
    if not _can_view():
        abort(403)
    from database.db import get_db
    from utils import audit_chain as AC
    note = (request.form.get('note') or '').strip()[:500] or 'manual check'
    aid, res = AC.take_anchor(get_db(), current_user.id, note)
    AuditLog.log(current_user.id, 'Audit Chain Check', 'Security', aid,
                 f"Audit trail checked and anchored (anchor {aid}): {'intact' if res['ok'] else 'NOT INTACT'}", _ip())
    if aid is None:
        flash(_('The audit trail could not be checked: %(e)s', e=res.get('error') or ''), 'danger')
    elif res['ok']:
        flash(_('The audit trail is intact. Checkpoint saved.'), 'success')
    else:
        flash(_('The audit trail check found a problem. See the details below.'), 'danger')
    return redirect(url_for('admin.audit_chain'))
