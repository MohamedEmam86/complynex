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
Screening limits page (administrators and the superadmin): the default daily limit, today's usage per user
(Africa/Cairo day), reset a user's usage for today and raise / lower a user's own limit. Every change is
audited (screening_limit_events + audit log). The logic is screening/limits.py.
"""
from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from access.registry import mark
from admin import admin_bp

EDITORS = ('admin', 'superadmin')


def _editor(f):
    @wraps(f)
    @login_required
    def wrapped(*a, **kw):
        if (getattr(current_user, 'role', '') or '') not in EDITORS:
            abort(403)
        return f(*a, **kw)
    return mark(('role', EDITORS))(wrapped)


@admin_bp.route('/screening-limits')
@_editor
def screening_limits():
    from screening import limits as L
    rows, day, dflt = L.usage_today()
    return render_template('admin/screening_limits.html', rows=rows, day=day, default=dflt, events=L.events(30))


@admin_bp.route('/screening-limits/default', methods=['POST'])
@_editor
def screening_limits_default():
    from screening import limits as L
    raw = (request.form.get('default') or '0').strip()
    if not raw.isdigit():
        flash(_('Enter a whole number (0 = unlimited).'), 'danger')
    else:
        L.set_default(int(raw), current_user.id, ip=request.remote_addr)
        flash(_('The default daily screening limit was saved.'), 'success')
    return redirect(url_for('admin.screening_limits'))


@admin_bp.route('/screening-limits/user/<int:user_id>', methods=['POST'])
@_editor
def screening_limit_user(user_id):
    from screening import limits as L
    note = (request.form.get('note') or '').strip()[:300] or None
    if request.form.get('action') == 'reset':
        before = L.reset_today(user_id, current_user.id, note=note, ip=request.remote_addr)
        flash(_("Today's usage was reset (%(n)s screenings were counted).", n=before), 'success')
    else:
        raw = (request.form.get('limit') or '').strip()
        if raw and not raw.isdigit():
            flash(_('Enter a whole number (0 = unlimited), or leave it empty for the default.'), 'danger')
        else:
            L.set_user_limit(user_id, int(raw) if raw else None, current_user.id, note=note, ip=request.remote_addr)
            flash(_("The user's daily screening limit was saved."), 'success')
    return redirect(url_for('admin.screening_limits'))
