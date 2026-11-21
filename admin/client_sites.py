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
Client sites (platform superadmin only): list / create / edit a client's sub-domain site (host, bilingual name
and welcome text, logo, access modes, default daily limit, monthly organisation cap), bind users to it and
see this month's screenings of its users against the cap. The logic is client_sites/service.py.
"""
from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import get_locale
from flask_login import current_user, login_required

from access.registry import mark
from admin import admin_bp

ROLES = ('superadmin',)


def _superadmin(f):
    @wraps(f)
    @login_required
    def wrapped(*a, **kw):
        if (getattr(current_user, 'role', '') or '') not in ROLES:
            abort(403)
        return f(*a, **kw)
    return mark(('role', ROLES))(wrapped)


def _lang():
    return str(get_locale() or 'en')[:2]


def _msg(pair):
    return pair[1] if _lang() == 'ar' else pair[0]


def _audit(action, site_id, detail):
    try:
        from models.audit import AuditLog
        AuditLog.log(current_user.id, action, 'Client Sites', site_id, detail[:500], request.remote_addr)
    except Exception:
        pass


def _site_or_404(site_id):
    from client_sites import service as CS
    site = CS.site_by_id(site_id)
    if not site:
        abort(404)
    return site


def _save_logo(site_id):
    """Store the uploaded logo, or remove it when asked. Returns an error message or None."""
    from client_sites import service as CS
    if request.form.get('remove_logo') in ('1', 'on'):
        CS.remove_logo(site_id)
        return None
    f = request.files.get('logo')
    if not f or not f.filename:
        return None
    raw = f.read(CS.LOGO_MAX_BYTES + 1)
    try:
        CS.store_logo(site_id, f.filename, raw)
    except ValueError as e:
        return _msg(CS.logo_error(str(e)))
    except OSError:
        return _msg(('The logo could not be saved on the server.', 'تعذّر حفظ الشعار على الخادم.'))
    return None


@admin_bp.route('/client-sites')
@_superadmin
def client_sites():
    from client_sites import service as CS
    from screening.limits import today
    sites = CS.all_sites()
    day = today()
    used = {}
    for s in sites:
        try:
            used[s['id']] = CS.month_used(s['id'], day)
        except Exception:
            used[s['id']] = 0
    return render_template('admin/client_sites/list.html', sites=sites, used=used, month=day.strftime('%Y-%m'),
                           main_hosts=sorted(CS.main_hosts()))


def _form_page(site, form_data=None, errors=None):
    from client_sites import service as CS
    return render_template('admin/client_sites/form.html', site=site, f=form_data or site or {}, errors=errors or [],
                           modes=CS.MODES, max_kb=CS.LOGO_MAX_BYTES // 1024)


@admin_bp.route('/client-sites/new', methods=['GET', 'POST'])
@_superadmin
def client_site_new():
    from client_sites import service as CS
    if request.method == 'GET':
        return _form_page(None, {'active': True, 'allowed_access_modes': ['restricted'], 'default_access_mode': 'restricted',
                                 'monthly_org_cap': 0})
    data, errs = CS.parse_form(request.form)
    if errs:
        return _form_page(None, data, [_msg(e) for e in errs]), 400
    sid = CS.save_site(data)
    _audit('Client Site Created', sid, f"host {data['host']}")
    err = _save_logo(sid)
    if err:
        flash(err, 'warning')
    flash(_msg(('Client site saved.', 'تم حفظ موقع العميل.')), 'success')
    return redirect(url_for('admin.client_site_edit', site_id=sid))


@admin_bp.route('/client-sites/<int:site_id>/edit', methods=['GET', 'POST'])
@_superadmin
def client_site_edit(site_id):
    from client_sites import service as CS
    site = _site_or_404(site_id)
    if request.method == 'GET':
        return _form_page(site)
    data, errs = CS.parse_form(request.form, existing_id=site_id)
    if errs:
        return _form_page(site, data, [_msg(e) for e in errs]), 400
    CS.save_site(data, site_id)
    changed = [k for k in data if site.get(k) != data[k]]
    _audit('Client Site Updated', site_id, 'changed: ' + (', '.join(changed) or 'nothing'))
    err = _save_logo(site_id)
    if err:
        flash(err, 'warning')
    flash(_msg(('Client site saved.', 'تم حفظ موقع العميل.')), 'success')
    return redirect(url_for('admin.client_site_edit', site_id=site_id))


@admin_bp.route('/client-sites/<int:site_id>/users')
@_superadmin
def client_site_users(site_id):
    from client_sites import service as CS
    site = _site_or_404(site_id)
    return render_template('admin/client_sites/users.html', site=site, members=CS.site_members(site_id),
                           candidates=CS.assignable_users())


@admin_bp.route('/client-sites/<int:site_id>/users/add', methods=['POST'])
@_superadmin
def client_site_user_add(site_id):
    from client_sites import service as CS
    site = _site_or_404(site_id)
    try:
        uid = int(request.form.get('user_id') or 0)
    except ValueError:
        uid = 0
    if uid and CS.assign_user(site_id, uid):
        _audit('Client Site User Added', site_id, f'user {uid} bound to {site["host"]}')
        flash(_msg(('User added to the site. They now sign in on the site\'s address only.',
                    'أضيف المستخدم إلى الموقع. يسجّل دخوله الآن من عنوان الموقع فقط.')), 'success')
    else:
        flash(_msg(('Choose a user to add.', 'اختر مستخدماً لإضافته.')), 'warning')
    return redirect(url_for('admin.client_site_users', site_id=site_id))


@admin_bp.route('/client-sites/<int:site_id>/users/<int:user_id>/remove', methods=['POST'])
@_superadmin
def client_site_user_remove(site_id, user_id):
    from client_sites import service as CS
    _site_or_404(site_id)
    CS.unassign_user(site_id, user_id)
    _audit('Client Site User Removed', site_id, f'user {user_id} unbound')
    flash(_msg(('User removed from the site. They sign in on the main address again.',
                'أزيل المستخدم من الموقع. يسجّل دخوله من العنوان الرئيسي مرة أخرى.')), 'success')
    return redirect(url_for('admin.client_site_users', site_id=site_id))


@admin_bp.route('/client-sites/<int:site_id>/usage')
@_superadmin
def client_site_usage(site_id):
    from client_sites import service as CS
    from screening.limits import today
    site = _site_or_404(site_id)
    rows, total, start = CS.usage_by_user(site_id, today())
    cap = int(site.get('monthly_org_cap') or 0)
    return render_template('admin/client_sites/usage.html', site=site, rows=rows, total=total, cap=cap,
                           left=None if not cap else max(0, cap - total), month=start.strftime('%Y-%m'))
