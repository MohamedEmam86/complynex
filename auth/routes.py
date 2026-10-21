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
Authentication routes for ComplyNex CMS
Handles login, logout, and user registration
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_babel import gettext as _
from flask_login import login_user, logout_user, login_required, current_user
from extensions import limiter
from models.user import User
from models.audit import AuditLog
from auth import guard


auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/portal/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def portal_login():
    """
    Handle Employee Portal login.
    """
    if current_user.is_authenticated:
        return render_template('auth/switch_user.html', user=current_user)
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False) == 'on'
        
        user = User.get_by_email(email)

        if user and guard.is_locked(user.id):
            AuditLog.log(user.id, 'Failed Login', 'Auth', None, 'Portal Login: account locked', request.remote_addr)
            flash(_('This account is temporarily locked after several failed attempts. Try again in %(m)s minutes.', m=guard.LOCK_MINUTES), 'danger')
            return render_template('auth/login_portal.html')

        if user and user.check_password(password):
            # Session fixation prevention - regenerate session on login
            session.clear()
            guard.reset_failures(user.id)

            if not user.is_active:
                AuditLog.log(user.id, 'Failed Login', 'Auth', None, 'Account expired' if user.is_expired() else 'Account deactivated', request.remote_addr)
                flash(_('Your account has expired. Contact your administrator.') if user.is_expired() else _('Your account has been deactivated.'), 'danger')
            elif user.mfa_enabled:
                # Password correct but MFA required — store pending user id and redirect to verify
                session['mfa_pending_user_id'] = user.id
                session['mfa_remember'] = remember
                session['mfa_next'] = 'portal.dashboard'
                return redirect(url_for('auth.mfa_verify'))
            else:
                # MFA not yet set up: enforce it for privileged roles before granting access
                if user.mfa_required() and not user.mfa_enabled:
                    session['mfa_setup_user_id'] = user.id
                    session['mfa_remember'] = remember
                    session['mfa_next'] = 'portal.dashboard'
                    return redirect(url_for('auth.mfa_setup'))
                login_user(user, remember=remember)
                session.permanent = True
                User.update_last_login(user.id)
                AuditLog.log(user.id, 'Login', 'Auth', None, 'Employee Portal Login', request.remote_addr)
                return redirect(url_for('portal.dashboard'))
        else:
            # For failed login attempt, we don't have a reliable user_id if email is wrong
            # but we can try to find it for the log if it exists
            failed_user = User.get_by_email(email)
            AuditLog.log(failed_user.id if failed_user else None, 'Failed Login', 'Auth', None, f'Invalid password for {email}' if failed_user else f'Invalid email: {email}', request.remote_addr)
            if failed_user and guard.register_failure(failed_user.id):
                AuditLog.log(failed_user.id, 'Account Locked', 'Auth', None, f'Locked for {guard.LOCK_MINUTES} min after {guard.LOCK_AFTER} failed attempts', request.remote_addr)
            flash(_('Invalid email or password.'), 'danger')
            
    return render_template('auth/login_portal.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    """
    Handle CMS (Admin/Officer) login.
    """
    if current_user.is_authenticated:
        if current_user.can_access_cms():
             return redirect(url_for('dashboard'))
        flash(_('You are logged in but do not have CMS access.'), 'warning')
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False) == 'on'
        
        user = User.get_by_email(email)

        if user and guard.is_locked(user.id):
            AuditLog.log(user.id, 'Failed Login', 'Auth', None, 'CMS Login: account locked', request.remote_addr)
            flash(_('This account is temporarily locked after several failed attempts. Try again in %(m)s minutes.', m=guard.LOCK_MINUTES), 'danger')
            return render_template('auth/login.html')

        if user and user.check_password(password):
            # Session fixation prevention - regenerate session on login
            session.clear()
            guard.reset_failures(user.id)
            # Upgrade legacy hash to bcrypt if needed
            if not user.password_hash.startswith('$2b$'):
                new_hash = User.hash_password(password)
                User.update_user(user.id, password_hash=new_hash)

            if not user.is_active:
                AuditLog.log(user.id, 'Failed Login', 'Auth', None, 'CMS Login: Account expired' if user.is_expired() else 'CMS Login: Account deactivated', request.remote_addr)
                flash(_('Your account has expired. Contact your administrator.') if user.is_expired() else _('Account deactivated.'), 'danger')
            elif not user.can_access_cms():
                AuditLog.log(user.id, 'Failed Login', 'Auth', None, 'CMS Login: Access Denied (Role Insufficient)', request.remote_addr)
                flash(_('Access Denied. You do not have permission to access the CMS.'), 'danger')
            elif user.mfa_enabled:
                # Password correct but MFA required — store pending user id and redirect to verify
                session['mfa_pending_user_id'] = user.id
                session['mfa_remember'] = remember
                return redirect(url_for('auth.mfa_verify'))
            else:
                # MFA not yet set up: enforce it for privileged roles before granting access
                if user.mfa_required() and not user.mfa_enabled:
                    session['mfa_setup_user_id'] = user.id
                    session['mfa_remember'] = remember
                    return redirect(url_for('auth.mfa_setup'))
                login_user(user, remember=remember)
                session.permanent = True
                User.update_last_login(user.id)
                AuditLog.log(user.id, 'Login', 'Auth', None, 'CMS Login Successful', request.remote_addr)
                return redirect(url_for('dashboard'))
        else:
            failed_user = User.get_by_email(email)
            AuditLog.log(failed_user.id if failed_user else None, 'Failed Login', 'Auth', None, f'CMS Login: Invalid password for {email}' if failed_user else f'CMS Login: Invalid email: {email}', request.remote_addr)
            if failed_user and guard.register_failure(failed_user.id):
                AuditLog.log(failed_user.id, 'Account Locked', 'Auth', None, f'Locked for {guard.LOCK_MINUTES} min after {guard.LOCK_AFTER} failed attempts', request.remote_addr)
            flash(_('Invalid email or password.'), 'danger')
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Log out current user."""
    # Determine where to redirect based on role before logging out
    is_cms_user = current_user.can_access_cms()
    user_id = current_user.id
    logout_user()
    AuditLog.log(user_id, 'Logout', 'Auth', None, 'User logged out', request.remote_addr)
    flash(_('You have been logged out successfully.'), 'info')
    
    if is_cms_user:
        return redirect(url_for('auth.login'))
    return redirect(url_for('auth.portal_login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    flash('Self-registration is disabled. Contact your administrator.', 'warning')
    return redirect(url_for('auth.login'))


# ── MFA Setup ────────────────────────────────────────────────────────────────

@auth_bp.route('/mfa/setup', methods=['GET', 'POST'])
def mfa_setup():
    """Force-MFA setup for privileged roles who haven't enrolled yet."""
    user_id = session.get('mfa_setup_user_id')
    if not user_id:
        return redirect(url_for('auth.login'))

    import pyotp, qrcode, io, base64, json as _json
    user = User.get_by_id(user_id)
    if not user:
        session.pop('mfa_setup_user_id', None)
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'verify':
            secret = session.get('mfa_tmp_secret')
            code   = request.form.get('code', '').strip()
            if not secret:
                flash('Session expired. Please start again.', 'danger')
                return redirect(url_for('auth.mfa_setup'))
            totp = pyotp.TOTP(secret)
            if totp.verify(code, valid_window=1):
                codes, codes_json = User.generate_backup_codes()
                User.enable_mfa(user_id, secret, codes_json)
                session.pop('mfa_tmp_secret', None)
                session.pop('mfa_setup_user_id', None)
                remember = session.pop('mfa_remember', False)
                next_endpoint = session.pop('mfa_next', 'dashboard')
                login_user(user, remember=remember)
                session.permanent = True
                User.update_last_login(user_id)
                AuditLog.log(user_id, 'MFA Enabled', 'Auth', None, 'TOTP MFA configured successfully', request.remote_addr)
                flash('Two-factor authentication enabled. Save your backup codes — they are shown once only.', 'success')
                return render_template('auth/mfa_backup_codes.html', codes=codes, next_endpoint=next_endpoint)
            else:
                flash('Invalid code. Please try again.', 'danger')

    # GET: generate a fresh secret and QR code
    secret = User.generate_mfa_secret()
    session['mfa_tmp_secret'] = secret
    totp = pyotp.TOTP(secret)
    otp_uri = totp.provisioning_uri(name=user.email, issuer_name='ComplyNex CMS')
    img = qrcode.make(otp_uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return render_template('auth/mfa_setup.html', qr_b64=qr_b64, secret=secret, user=user)


@auth_bp.route('/mfa/verify', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def mfa_verify():
    """Second-factor verification after password check."""
    user_id = session.get('mfa_pending_user_id')
    if not user_id:
        return redirect(url_for('auth.login'))

    user = User.get_by_id(user_id)
    if not user or not user.is_active:
        session.pop('mfa_pending_user_id', None)
        return redirect(url_for('auth.login'))

    if guard.is_locked(user.id):
        session.pop('mfa_pending_user_id', None)
        flash(_('This account is temporarily locked after several failed attempts. Try again in %(m)s minutes.', m=guard.LOCK_MINUTES), 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        code     = request.form.get('code', '').strip()
        use_backup = request.form.get('use_backup') == '1'
        valid = user.verify_backup_code(code) if use_backup else user.verify_totp(code)
        if valid:
            guard.reset_failures(user_id)
            session.pop('mfa_pending_user_id', None)
            remember = session.pop('mfa_remember', False)
            next_endpoint = session.pop('mfa_next', 'dashboard')
            login_user(user, remember=remember)
            session.permanent = True
            User.update_last_login(user_id)
            method = 'backup code' if use_backup else 'TOTP'
            AuditLog.log(user_id, 'Login', 'Auth', None, f'CMS Login with MFA ({method})', request.remote_addr)
            return redirect(url_for(next_endpoint))
        else:
            AuditLog.log(user_id, 'Failed MFA', 'Auth', None, 'Invalid MFA code', request.remote_addr)
            if guard.register_failure(user_id):
                AuditLog.log(user_id, 'Account Locked', 'Auth', None, f'Locked for {guard.LOCK_MINUTES} min after {guard.LOCK_AFTER} failed MFA codes', request.remote_addr)
                session.pop('mfa_pending_user_id', None)
                flash(_('This account is temporarily locked after several failed attempts. Try again in %(m)s minutes.', m=guard.LOCK_MINUTES), 'danger')
                return redirect(url_for('auth.login'))
            flash(_('Invalid code. Please try again.'), 'danger')

    return render_template('auth/mfa_verify.html')


@auth_bp.route('/mfa/disable', methods=['POST'])
@login_required
def mfa_disable():
    """Allow admin to disable MFA for their own account (re-enroll)."""
    if not current_user.is_admin():
        flash(_('Only administrators can disable MFA directly.'), 'danger')
        return redirect(url_for('dashboard'))
    if not current_user.verify_totp(request.form.get('code', '')):
        AuditLog.log(current_user.id, 'Failed MFA', 'Auth', None, 'MFA disable refused: invalid code', request.remote_addr)
        flash(_('Enter a valid code from your authenticator app to disable MFA.'), 'danger')
        return redirect(url_for('dashboard'))
    User.disable_mfa(current_user.id)
    AuditLog.log(current_user.id, 'MFA Disabled', 'Auth', None, 'TOTP MFA removed by admin', request.remote_addr)
    flash(_('MFA has been disabled. You will be prompted to re-enroll on next login.'), 'warning')
    return redirect(url_for('dashboard'))


@auth_bp.route('/logout-everywhere', methods=['POST'])
@login_required
def logout_everywhere():
    """Invalidate every session and remember-me cookie of the current user."""
    is_cms_user = current_user.can_access_cms()
    user_id = current_user.id
    User.bump_auth_version(user_id)
    logout_user()
    AuditLog.log(user_id, 'Logout', 'Auth', None, 'Signed out on all devices', request.remote_addr)
    flash(_('You have been signed out on all devices.'), 'info')
    return redirect(url_for('auth.login') if is_cms_user else url_for('auth.portal_login'))
