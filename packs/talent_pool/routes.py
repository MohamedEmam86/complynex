# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Talent pool — staff pages (/talent/). Permission: pack module 'talent'
  view  — see applicants, open CVs
  edit  — change status, rate, add notes, export
  admin — settings, categories, erase personal data
Granted per user on the user form (Content pack modules)."""
import csv
import io
from datetime import datetime
from functools import wraps

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_login import current_user, login_required

from models.audit import AuditLog

from . import service as S

bp = Blueprint('talent', __name__, url_prefix='/talent')
MODULE = S.MODULE


def perm(level='view'):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapped(*a, **kw):
            ok = {'view': current_user.can_view, 'edit': current_user.can_edit,
                  'admin': current_user.can_admin_module}[level](MODULE)
            if not ok:
                abort(403)
            return f(*a, **kw)
        return wrapped
    return deco


def _audit(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, 'Talent pool', item_id, details, request.remote_addr)
    except Exception:
        current_app.logger.warning('talent audit failed', exc_info=True)


@bp.context_processor
def _ctx():
    if not getattr(current_user, 'is_authenticated', False):
        return {}
    return {'tp_can_edit': current_user.can_edit(MODULE), 'tp_can_admin': current_user.can_admin_module(MODULE),
            'TP': S}


@bp.route('/')
@perm('view')
def index():
    S.purge_unverified(current_app.root_path)
    rows = S.search(request.args)
    by_status, by_cat = S.counts()
    return render_template('talent_pool/list.html', rows=rows, by_status=by_status, by_cat=by_cat,
                           categories=S.categories(active_only=False), args=request.args,
                           public_enabled=S.public_enabled())


@bp.route('/<int:app_id>')
@perm('view')
def detail(app_id):
    a = S.get(app_id)
    if not a:
        abort(404)
    cats = {c['id']: c for c in S.categories(active_only=False)}
    _audit('view_applicant', app_id)
    return render_template('talent_pool/detail.html', a=a, notes=S.notes(app_id), cats=cats,
                           others=[c for i, c in cats.items() if i in (a['other_category_ids'] or [])])


@bp.route('/<int:app_id>/cv')
@perm('view')
def cv_download(app_id):
    a = S.get(app_id)
    if not a or not a['cv_path'] or a['erased_at']:
        abort(404)
    _audit('download_cv', app_id, a['ref'])
    ext = '.pdf' if a['cv_path'].endswith('.pdf') else '.docx'
    resp = send_from_directory(current_app.root_path, a['cv_path'], as_attachment=True,
                               download_name=f"CV-{a['ref']}{ext}")
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


@bp.route('/<int:app_id>/update', methods=['POST'])
@perm('edit')
def update(app_id):
    a = S.get(app_id)
    if not a or a['erased_at']:
        abort(404)
    f = request.form
    if f.get('status'):
        if S.set_status([app_id], f['status'], current_user.id):
            _audit('status', app_id, f['status'])
    if 'rating' in f:
        S.set_rating(app_id, f.get('rating'))
    if f.get('note'):
        S.add_note(app_id, current_user.id, f['note'], kind=f.get('kind') if f.get('kind') in ('note', 'call', 'email', 'meeting') else 'note')
    flash(S.label({'ok': ('Saved.', 'تم الحفظ.')}, 'ok', _is_ar()), 'success')
    return redirect(url_for('talent.detail', app_id=app_id))


@bp.route('/bulk', methods=['POST'])
@perm('edit')
def bulk():
    ids = request.form.getlist('ids')
    action = request.form.get('action')
    if action == 'export':
        return _export(ids)
    if action == 'emails':
        rows = [r for r in S.search({'status': 'all'}, limit=2000) if str(r['id']) in set(ids)]
        emails = sorted({r['email'] for r in rows if r['email'] and '@' in r['email']})
        _audit('copy_emails', None, f'{len(emails)} addresses')
        return render_template('talent_pool/emails.html', emails=emails)
    n = S.set_status(ids, action, current_user.id)
    _audit('bulk_status', None, f'{action} x{n}')
    flash(S.label({'ok': (f'{n} applicants updated.', f'تم تحديث {n} من المتقدمين.')}, 'ok', _is_ar()), 'success')
    return redirect(request.referrer or url_for('talent.index'))


@bp.route('/export')
@perm('edit')
def export():
    return _export([str(r['id']) for r in S.search(request.args, limit=5000)])


def _export(ids):
    ids = set(ids)
    rows = [r for r in S.search({'status': 'all'}, limit=5000) if str(r['id']) in ids]
    cats = {c['id']: c['name_en'] for c in S.categories(active_only=False)}
    buf = io.StringIO()
    buf.write('﻿')
    w = csv.writer(buf)
    w.writerow(['Ref', 'Full name', 'Email', 'Phone', 'WhatsApp', 'City', 'Country', 'Main area', 'Other areas',
                'Years', 'Current title', 'Seniority', 'Availability', 'Engagement', 'Work mode', 'Languages',
                'Certifications', 'LinkedIn', 'Expected rate', 'Status', 'Rating', 'Applied'])
    for r in rows:
        w.writerow([S.csv_safe(x) for x in (
            r['ref'], r['full_name'], r['email'], r['phone'], r['whatsapp'], r['city'], r['country'],
            cats.get(r['primary_category_id']), '; '.join(cats.get(i, '') for i in (r['other_category_ids'] or [])),
            r['years_experience'], r['current_title'], S.label(S.SENIORITY, r['seniority']),
            S.label(S.AVAILABILITY, r['availability']), S.label(S.ENGAGEMENT, r['engagement']),
            S.label(S.WORK_MODE, r['work_mode']), r['languages'], r['certifications'], r['linkedin_url'],
            r['expected_rate'], S.label(S.STATUS_LABELS, r['status']), r['rating'],
            r['created_at'].strftime('%Y-%m-%d') if r['created_at'] else '')])
    _audit('export', None, f'{len(rows)} rows')
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=talent-pool-{datetime.now():%Y%m%d-%H%M}.csv'})


@bp.route('/<int:app_id>/erase', methods=['POST'])
@perm('admin')
def erase(app_id):
    if request.form.get('confirm') != 'ERASE':
        flash(S.label({'x': ('Type ERASE to confirm.', 'اكتب ERASE للتأكيد.')}, 'x', _is_ar()), 'warning')
        return redirect(url_for('talent.detail', app_id=app_id))
    if S.erase(app_id, current_app.root_path, current_user.id):
        _audit('erase_personal_data', app_id)
    return redirect(url_for('talent.detail', app_id=app_id))


@bp.route('/settings', methods=['GET', 'POST'])
@perm('admin')
def settings():
    if request.method == 'POST':
        f = request.form
        if f.get('section') == 'general':
            S.set_setting('public_enabled', '1' if f.get('public_enabled') else '0', current_user.id)
            for k, n in (('org_name_en', 120), ('org_name_ar', 120), ('website', 200), ('logo', 200),
                         ('intro_en', 3000), ('intro_ar', 3000), ('terms_en', 3000), ('terms_ar', 3000),
                         ('privacy_contact', 200), ('notify_email', 200), ('sender_name', 120),
                         ('staff_base_url', 200)):
                S.set_setting(k, (f.get(k) or '').strip()[:n], current_user.id)
            _audit('settings')
        elif f.get('section') == 'category':
            S.save_category(int(f['cat_id']) if (f.get('cat_id') or '').isdigit() else None,
                            f.get('name_en'), f.get('name_ar'), f.get('is_active') == '1', f.get('sort_order'))
            _audit('category', None, f.get('name_en'))
        flash(S.label({'ok': ('Saved.', 'تم الحفظ.')}, 'ok', _is_ar()), 'success')
        return redirect(url_for('talent.settings'))
    keys = ('public_enabled', 'org_name_en', 'org_name_ar', 'website', 'logo', 'intro_en', 'intro_ar', 'terms_en',
            'terms_ar', 'privacy_contact', 'notify_email', 'sender_name', 'staff_base_url')
    return render_template('talent_pool/settings.html', s={k: S.setting(k, '') for k in keys},
                           categories=S.categories(active_only=False))


def _is_ar():
    try:
        from flask_babel import get_locale
        return str(get_locale()).startswith('ar')
    except Exception:
        return False
