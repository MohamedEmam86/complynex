# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Session lifetime (P6-6).

Idle timeout: Flask's PERMANENT_SESSION_LIFETIME (config SESSION_IDLE_MINUTES,
default 60) — the session cookie expires after that much inactivity.
Absolute timeout: however active the user is, a session older than
SESSION_ABSOLUTE_HOURS (default 12) ends and the user signs in again
(password + MFA). A "remember me" cookie (REMEMBER_DAYS, default 14) starts a
new session, which gets its own absolute limit.
"""
import os
import time

from flask import flash, redirect, request, session, url_for
from flask_babel import gettext as _
from flask_login import current_user, logout_user

KEY = '_cx_login_at'


def absolute_seconds():
    try:
        h = float(os.environ.get('SESSION_ABSOLUTE_HOURS', 12))
    except (TypeError, ValueError):
        h = 12
    return int(max(1, min(72, h)) * 3600)


def expired(login_at, now=None, limit=None):
    if not login_at:
        return False
    now = now or time.time()
    return (now - float(login_at)) > (limit or absolute_seconds())


def register(bp):
    @bp.before_app_request
    def _absolute_session_timeout():
        if not getattr(current_user, 'is_authenticated', False):
            return None
        ep = request.endpoint or ''
        if ep == 'static' or ep.endswith('.static') or ep in ('health', 'prometheus_metrics'):
            return None
        started = session.get(KEY)
        if not started:
            session[KEY] = time.time()
            return None
        if not expired(started):
            return None
        uid = current_user.id
        is_cms = False
        try:
            is_cms = bool(current_user.can_access_cms())
        except Exception:
            pass
        logout_user()
        session.clear()
        # logout_user() asked Flask-Login to delete the remember-me cookie, but clear() dropped
        # that request; without it the cookie would sign the user straight back in
        session['_remember'] = 'clear'
        try:
            from models.audit import AuditLog
            AuditLog.log(uid, 'Logout', 'Auth', None, 'Session ended: maximum session length reached',
                         request.remote_addr)
        except Exception:
            pass
        flash(_('Your session reached its maximum length. Please sign in again.'), 'info')
        if request.is_json or request.path.startswith('/api/'):
            return {'error': 'session expired'}, 401
        return redirect(url_for('auth.login') if is_cms else url_for('auth.portal_login'))
