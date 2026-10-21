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

from functools import wraps
from flask_babel import gettext
from flask import flash, redirect, url_for, request, abort
from flask_login import current_user

def permission_required(module, level='view'):
    """
    Decorator to check if a user has the required permission for a module.

    Args:
        module: The module name (governance, aml, policies, reports, pdpl, training, screening, config, cyber)
        level: The required level ('view', 'edit', or 'admin' — 'admin' restricts the route to
               site administrators only, regardless of the caller's granular module permission)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))

            # Admins have full access
            if current_user.is_admin():
                return f(*args, **kwargs)

            # Check specific permission
            if level == 'edit':
                if not current_user.can_edit(module):
                    flash(gettext('You do not have permission to edit %(module)s.', module=module), 'danger')
                    return redirect(request.referrer or url_for('dashboard'))
            elif level == 'admin':
                # is_admin() only matches role == 'admin' exactly, but this codebase
                # also treats 'superadmin'/'it_admin' as admin-equivalent elsewhere
                # (see admin/routes.py::superadmin_required) — match that same set so
                # this doesn't lock out those accounts.
                if getattr(current_user, 'role', '') not in ('admin', 'superadmin', 'it_admin'):
                    flash(gettext('This action requires administrator privileges.'), 'danger')
                    return redirect(request.referrer or url_for('dashboard'))
            else:
                if not current_user.can_view(module):
                    flash(gettext('You do not have permission to access %(module)s.', module=module), 'danger')
                    return redirect(request.referrer or url_for('dashboard'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """Decorator to require admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.url))
        if not current_user.is_admin():
            flash(gettext('This action requires administrator privileges.'), 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function
