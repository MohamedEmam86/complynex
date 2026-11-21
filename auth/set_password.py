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
One-time set-password links.

A link carries a signed token (itsdangerous, the application's SECRET_KEY, its own salt) naming the user, the
user's auth_version and a fingerprint of the current password hash. Setting the password changes both, so a
link works once; it also expires after the hours it was issued for (default 24, at most 7 days). Used for the first superadmin of a new
instance (scripts/instance/create_superadmin.py), whose random password nobody ever sees.
"""

import hashlib
import time

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from auth.routes import auth_bp
from extensions import limiter
from models.audit import AuditLog
from models.user import User

SALT = 'cx-set-password'
HOURS = 24                 # default validity of a link
MAX_HOURS = 7 * 24         # hard cap, whatever a link says


def _serializer(secret_key=None):
    return URLSafeTimedSerializer(secret_key or current_app.config['SECRET_KEY'], salt=SALT)


def _fp(password_hash):
    return hashlib.sha256((password_hash or '').encode('utf-8')).hexdigest()[:16]


def make_token(user, secret_key=None, hours=HOURS):
    hours = max(0.01, min(float(hours), MAX_HOURS))
    return _serializer(secret_key).dumps({'u': int(user.id), 'v': int(getattr(user, 'auth_version', 0) or 0),
                                          'h': _fp(getattr(user, 'password_hash', '')),
                                          'x': int(time.time() + hours * 3600)})


def user_for_token(token, secret_key=None, now=None):
    """The active user a valid, unused, unexpired token names, else None."""
    try:
        data = _serializer(secret_key).loads(token, max_age=MAX_HOURS * 3600)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
    try:
        if (now or time.time()) > int(data.get('x', 0)):
            return None
    except (TypeError, ValueError, AttributeError):
        return None
    try:
        user = User.get_by_id(int(data['u']))
    except (KeyError, TypeError, ValueError):
        return None
    if not user or not user.is_active:
        return None
    if int(getattr(user, 'auth_version', 0) or 0) != int(data.get('v', -1)):
        return None
    if _fp(getattr(user, 'password_hash', '')) != data.get('h'):
        return None
    return user


def set_password_url(user, base_url=None, hours=HOURS):
    """Absolute one-time link for this user (inside an app context; base_url overrides the request host)."""
    token = make_token(user, hours=hours)
    if base_url:
        return base_url.rstrip('/') + url_for('auth.set_password', token=token)
    return url_for('auth.set_password', token=token, _external=True)


@auth_bp.route('/set-password/<token>', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def set_password(token):
    user = user_for_token(token)
    if user is None:
        return render_template('auth/set_password.html', invalid=True), 400
    if request.method == 'POST':
        pw = request.form.get('password') or ''
        if pw != (request.form.get('confirm') or ''):
            flash(_('The two passwords do not match.'), 'danger')
            return render_template('auth/set_password.html', invalid=False, email=user.email)
        ok, msg = User.validate_password_strength(pw)
        if not ok:
            flash(_(msg), 'danger')
            return render_template('auth/set_password.html', invalid=False, email=user.email)
        from database.db import get_db
        db = get_db()
        db.execute('UPDATE users SET password_hash = %s, auth_version = COALESCE(auth_version, 0) + 1, '
                   'failed_login_count = 0, locked_until = NULL, must_change_password = FALSE WHERE id = %s',
                   (User.hash_password(pw), user.id))
        db.commit()
        AuditLog.log(user.id, 'Password Set', 'Auth', None, 'Password set with a one-time link', request.remote_addr)
        flash(_('Your password has been set. Please sign in.'), 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/set_password.html', invalid=False, email=user.email)
