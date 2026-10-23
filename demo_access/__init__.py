"""Demo access links.

The main instance's administrator creates a time-limited invitation link
(signed with DEMO_LINK_SECRET, which both instances hold in their .env). The
link opens the demo instance, where the visitor picks a fictional persona
(administrator, MLRO, compliance officer, manager, employee) and is signed in
as that demo user without a password. Nothing is stored: the link carries its
own expiry and is checked by signature. The demo instance's own users and
passwords keep working as before.
"""
import os
import secrets
import time

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, URLSafeTimedSerializer

from utils.demo import is_demo

demo_access_bp = Blueprint('demo_access', __name__)

SALT = 'complynex-demo-access-v1'
MAX_DAYS = 30
DEMO_DOMAIN = '@nilemicro.example'
# Personas offered on the demo instance, in this order: (email, EN, AR)
PERSONAS = [
    ('mlro@nilemicro.example', 'MLRO / Compliance Manager — decisions, approvals, reports',
     'مسؤول الإبلاغ / مدير الالتزام — القرارات والاعتمادات والتقارير'),
    ('co@nilemicro.example', 'Compliance Officer — screening, alerts, eKYC review',
     'مسؤول الالتزام — الفحص والتنبيهات ومراجعة التحقق الإلكتروني'),
    ('ceo@nilemicro.example', 'CEO (manager) — approvals for the team, dashboards',
     'الرئيس التنفيذي (مدير) — اعتمادات الفريق واللوحات'),
    ('risk@nilemicro.example', 'Head of Risk (manager) — risk register and assessments',
     'رئيس المخاطر (مدير) — سجل المخاطر والتقييمات'),
    ('lo1@nilemicro.example', 'Loan officer (employee) — declarations, policies, training',
     'مسؤول ائتمان (موظف) — الإقرارات والسياسات والتدريب'),
    ('demo.admin@nilemicro.example', 'Administrator — users, roles and settings (try creating a user)',
     'مدير النظام — المستخدمون والأدوار والإعدادات (جرّب إنشاء مستخدم)'),
]


def _secret():
    return (os.environ.get('DEMO_LINK_SECRET') or '').strip()


def _serializer():
    return URLSafeTimedSerializer(_secret(), salt=SALT)


def make_token(days, label):
    days = max(1, min(int(days), MAX_DAYS))
    return _serializer().dumps({'d': days, 'l': (label or '')[:80], 'n': secrets.token_hex(4)}), days


def read_token(token):
    """(payload, expires_at_epoch) for a valid, unexpired link, else (None, None)."""
    if not _secret() or not token or len(token) > 600:
        return None, None
    try:
        data, signed_at = _serializer().loads(token, return_timestamp=True)
    except BadSignature:
        return None, None
    try:
        days = max(1, min(int(data.get('d', 1)), MAX_DAYS))
    except (TypeError, ValueError, AttributeError):
        return None, None
    expires = signed_at.timestamp() + days * 86400
    if time.time() > expires:
        return None, None
    return data, expires


def _demo_only():
    if not is_demo():
        abort(404)


@demo_access_bp.before_app_request
def _expire_demo_access():
    """A visitor who came in through a link is signed out when the link expires."""
    until = session.get('demo_access_until')
    if until and time.time() > until and is_demo():
        logout_user()
        session.clear()


# ---------------------------------------------------------------- demo instance
@demo_access_bp.route('/demo/enter/<token>')
def enter(token):
    _demo_only()
    data, expires = read_token(token)
    if not data:
        return render_template('demo_access/choose.html', invalid=True, personas=[], ar=session.get('lang') == 'ar'), 410
    session.clear()
    session['demo_access_until'] = expires
    session['demo_access_label'] = data.get('l') or ''
    return redirect(url_for('demo_access.choose'))


@demo_access_bp.route('/demo/choose')
def choose():
    _demo_only()
    until = session.get('demo_access_until')
    if not until or time.time() > until:
        return render_template('demo_access/choose.html', invalid=True, personas=[], ar=session.get('lang') == 'ar'), 410
    from models.user import User
    personas = []
    for email, en, ar in PERSONAS:
        u = User.get_by_email(email)
        if u and u.is_active:
            personas.append({'id': u.id, 'name': f'{u.first_name or ""} {u.last_name or ""}'.strip(), 'email': email, 'en': en, 'ar': ar})
    from datetime import datetime, timedelta, timezone
    until_text = (datetime.fromtimestamp(until, timezone.utc) + timedelta(hours=3)).strftime('%Y-%m-%d %H:%M') + ' (Cairo)'
    return render_template('demo_access/choose.html', invalid=False, personas=personas, until_text=until_text,
                           ar=session.get('lang') == 'ar')


@demo_access_bp.route('/demo/as/<int:user_id>', methods=['POST'])
def sign_in_as(user_id):
    _demo_only()
    until = session.get('demo_access_until')
    if not until or time.time() > until:
        flash(_('This demo link has expired. Ask for a new one.'), 'warning')
        return redirect(url_for('auth.login'))
    from models.user import User
    from models.audit import AuditLog
    u = User.get_by_id(user_id)
    allowed = {e for e, _en, _ar in PERSONAS}
    if not u or not u.is_active or (u.email or '').lower() not in allowed:
        abort(404)
    label = session.get('demo_access_label') or ''
    lang = session.get('lang')
    session.clear()
    login_user(u)
    session.permanent = True
    session['demo_access_until'] = until
    if lang:
        session['lang'] = lang
    AuditLog.log(u.id, 'Login', 'Auth', None, f'Demo access link{": " + label if label else ""}', request.remote_addr)
    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------- main instance
@demo_access_bp.route('/admin/demo-access', methods=['GET', 'POST'])
@login_required
def links():
    if is_demo() or not current_user.is_admin():
        abort(404)
    link = None
    days = 7
    label = ''
    base = (os.environ.get('DEMO_BASE_URL') or 'https://demo.complynex.online').rstrip('/')
    if request.method == 'POST' and _secret():
        label = (request.form.get('label') or '').strip()[:80]
        try:
            days = int(request.form.get('days') or 7)
        except ValueError:
            days = 7
        token, days = make_token(days, label)
        link = f'{base}/demo/enter/{token}'
        from models.audit import AuditLog
        AuditLog.log(current_user.id, 'CREATE', 'Admin', None,
                     f'Demo access link created for "{label or "-"}", valid {days} day(s)', request.remote_addr)
    return render_template('demo_access/links.html', configured=bool(_secret()), link=link, days=days, label=label,
                           max_days=MAX_DAYS, base=base, ar=session.get('lang') == 'ar')
