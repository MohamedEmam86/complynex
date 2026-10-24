"""CSRF for the customer-facing eKYC token routes (/ekyc/verify/<token>/...).

Flask-WTF's global check also enforces a strict Referer match on HTTPS. Some
customer browsers / in-app webviews send no Referer header at all, so their
consent and capture POSTs were rejected and the CSRFError handler sent the
applicant to the staff login. For these public routes only, the global check is
skipped and the CSRF *token* is validated here instead (same token, same
session, same time limit) - just without the Referer comparison. Every other
route keeps the full Flask-WTF protection."""
from functools import wraps

from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_babel import gettext
from flask_wtf.csrf import ValidationError, validate_csrf

from extensions import csrf


def _submitted_token():
    token = request.form.get('csrf_token')
    if token:
        return token
    for header in current_app.config.get('WTF_CSRF_HEADERS', ['X-CSRFToken', 'X-CSRF-Token']):
        if request.headers.get(header):
            return request.headers.get(header)
    return None


def public_token_csrf(view=None, *, json_errors=False):
    """Decorator: validate the CSRF token without the Referer check.
    json_errors=True answers a failed check with JSON (fetch() callers);
    otherwise the applicant is sent back to their verification page."""
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_app.config.get('WTF_CSRF_ENABLED', True):
                try:
                    validate_csrf(_submitted_token())
                except ValidationError as exc:
                    current_app.logger.info('eKYC public CSRF check failed on %s: %s', request.path, exc)
                    message = gettext('Your session expired. Please reload the page and try again.')
                    if json_errors:
                        return jsonify({'ok': False, 'error': message}), 400
                    flash(message, 'warning')
                    return redirect(url_for('ekyc.verify', token=kwargs.get('token')))
            return fn(*args, **kwargs)
        csrf.exempt(wrapper)  # skip only the global (Referer-strict) check for this view
        return wrapper
    return decorate(view) if view is not None else decorate
