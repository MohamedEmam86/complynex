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

from flask_babel import gettext
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_babel import gettext as _
from models.user import User
from utils.file_serving import serve_uploaded_file
from werkzeug.security import generate_password_hash

users_bp = Blueprint('users', __name__, url_prefix='/users')

# Endpoints a user holding an administrator-issued password may still reach.
_PW_CHANGE_ALLOWED = {'static', 'users.password_change_required', 'users.change_password',
                      'auth.logout', 'auth.logout_everywhere', 'auth.login', 'auth.portal_login'}


@users_bp.before_app_request
def _force_password_change():
    """A temporary (administrator-issued) password must be replaced before anything else."""
    if not getattr(current_user, 'is_authenticated', False) or not getattr(current_user, 'must_change_password', False):
        return None
    ep = request.endpoint or ''
    if ep in _PW_CHANGE_ALLOWED or ep.endswith('.static'):
        return None
    return redirect(url_for('users.password_change_required'))


def _store_new_password(user_id, new_password):
    from database.db import get_db
    db = get_db()
    db.execute('UPDATE users SET password_hash = %s, auth_version = COALESCE(auth_version, 0) + 1, '
               'must_change_password = FALSE WHERE id = %s', (User.hash_password(new_password), user_id))
    db.commit()
    # keep THIS browser signed in under the new auth_version; all others are signed out
    from flask_login import login_user
    login_user(User.get_by_id(user_id), remember=bool(request.cookies.get('remember_token')))


@users_bp.route('/password/change-required', methods=['GET', 'POST'])
@login_required
def password_change_required():
    """First login with a temporary password: choose a personal one."""
    if not getattr(current_user, 'must_change_password', False):
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        new_password = request.form.get('new_password') or ''
        if not current_user.check_password(request.form.get('current_password') or ''):
            flash(gettext('Current password is incorrect.'), 'danger')
        elif new_password != request.form.get('confirm_password'):
            flash(gettext('New passwords do not match.'), 'danger')
        elif current_user.check_password(new_password):
            flash(_('Choose a password different from the temporary one.'), 'danger')
        else:
            ok, msg = User.validate_password_strength(new_password)
            if not ok:
                flash(_(msg), 'danger')
            else:
                uid = current_user.id
                _store_new_password(uid, new_password)
                from models.audit import AuditLog
                AuditLog.log(uid, 'Password Changed', 'Auth', None, 'Temporary password replaced at first login',
                             request.remote_addr)
                flash(_('Password updated. Welcome.'), 'success')
                return redirect(url_for('dashboard'))
    return render_template('users/password_change_required.html')

@users_bp.route('/')
@login_required
def list_users():
    """List all users for admin management."""
    if not current_user.is_admin():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))
        
    users = User.get_all()
    return render_template('users/list.html', users=users)

@users_bp.route('/profile')
@login_required
def profile():
    """View user profile settings."""
    return render_template('users/profile.html')

@users_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    """Update user personal information."""
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    
    if not first_name or not last_name:
        flash(gettext('All fields are required.'), 'danger')
        return redirect(url_for('users.profile'))
        
    User.update_user(current_user.id, first_name=first_name, last_name=last_name)
    
    # Trigger auto-assignment in case department/role changed (though this route only updates names currently)
    # Keeping it simple for now, but if department was editable here, we'd need it.
    # Actually, let's skip it here since only names change. 
    # But admin update is where it matters.
    
    flash(gettext('Profile updated successfully.'), 'success')
    return redirect(url_for('users.profile'))

@users_bp.route('/profile/password', methods=['POST'])
@login_required
def change_password():
    """Change user password."""
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not current_user.check_password(current_password):
        flash(gettext('Current password is incorrect.'), 'danger')
        return redirect(url_for('users.profile'))
        
    if new_password != confirm_password:
        flash(gettext('New passwords do not match.'), 'danger')
        return redirect(url_for('users.profile'))
        
    ok, msg = User.validate_password_strength(new_password or '')
    if not ok:
        flash(_(msg), 'danger')
        return redirect(url_for('users.profile'))

    _store_new_password(current_user.id, new_password)

    flash(_('Password updated successfully. Other devices have been signed out.'), 'success')
    return redirect(url_for('users.profile'))

@users_bp.route('/profile/avatar', methods=['POST'])
@login_required
def upload_avatar():
    """Upload profile picture."""
    if 'avatar' not in request.files:
        flash(gettext('No file uploaded.'), 'danger')
        return redirect(url_for('users.profile'))
        
    file = request.files['avatar']
    if file.filename == '':
        flash(gettext('No file selected.'), 'danger')
        return redirect(url_for('users.profile'))
        
    if file:
        import os
        from werkzeug.utils import secure_filename

        # Non-static uploads/ dir — not reachable via Flask's unauthenticated /static/ route
        upload_dir = os.path.join('uploads', 'profiles')
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)

        filename = secure_filename(f"user_{current_user.id}_{file.filename}")
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        # Save relative path in DB
        relative_path = f"uploads/profiles/{filename}"
        User.update_user(current_user.id, profile_picture=relative_path)
        
        flash(gettext('Profile picture updated.'), 'success')

    return redirect(url_for('users.profile'))


@users_bp.route('/<int:user_id>/avatar')
@login_required
def download_avatar(user_id):
    """Serve a user's profile picture — viewable by the user themselves or an admin."""
    if user_id != current_user.id and not current_user.is_admin():
        flash(gettext('You do not have permission to view this.'), 'danger')
        return redirect(url_for('users.profile'))

    user = User.get_by_id(user_id)
    if not user or not user.profile_picture:
        flash(gettext('No profile picture found.'), 'danger')
        return redirect(url_for('users.profile'))

    return serve_uploaded_file(user.profile_picture)

@users_bp.route('/<int:user_id>/progress')
@login_required
def user_progress(user_id):
    """View detailed progress for a user (Admin view)."""
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        # Managers might need this too, but restricting for now
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))
        
    user = User.get_by_id(user_id)
    if not user:
        flash(gettext('User not found.'), 'danger')
        return redirect(url_for('dashboard'))

    # Reuse status logic from portal but for specific user
    from database.db import get_db
    db = get_db()
    
    # Get COI submissions
    coi_submissions = db.execute('''
        SELECT d.*, c.campaign_name, c.campaign_year
        FROM coi_declarations d
        JOIN coi_campaigns c ON d.campaign_id = c.id
        WHERE d.employee_id = %s
        ORDER BY d.created_at DESC
    ''', (user.id,)).fetchall()
    
    # Get COBEC submissions
    cobec_submissions = db.execute('''
        SELECT * FROM cobec_declarations
        WHERE employee_id = %s
        ORDER BY created_at DESC
    ''', (user.id,)).fetchall()
    
    # Get Policy acknowledgments
    policy_acknowledgments = db.execute('''
        SELECT a.*, p.policy_name, p.policy_number
        FROM policy_acknowledgments a
        JOIN policies p ON a.policy_id = p.id
        WHERE a.employee_id = %s
        ORDER BY a.acknowledgment_date DESC
    ''', (user.id,)).fetchall()

    # Get Training enrollments
    training_enrollments = db.execute('''
        SELECT e.*, c.course_name, c.passing_score
        FROM training_enrollments e
        JOIN training_courses c ON e.course_id = c.id
        WHERE e.employee_id = %s
        ORDER BY e.enrolled_date DESC
    ''', (user.id,)).fetchall()
    
    return render_template('users/progress.html',
                         user=user,
                         coi_submissions=coi_submissions,
                         cobec_submissions=cobec_submissions,
                         policy_acknowledgments=policy_acknowledgments,
                         training_enrollments=training_enrollments)
    

@users_bp.route('/<int:user_id>/reset-password', methods=['POST'])
@login_required
def reset_password(user_id):
    """Reset a user's password (Admin only)."""
    if not current_user.is_admin():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))
        
    new_password = request.form.get('new_password')
    ok, msg = User.validate_password_strength(new_password or '')
    if not ok:
        flash(_(msg), 'danger')
        return redirect(url_for('users.list_users'))

    password_hash = User.hash_password(new_password)
    from database.db import get_db
    db = get_db()
    db.execute('UPDATE users SET password_hash = %s, auth_version = COALESCE(auth_version, 0) + 1, '
               'failed_login_count = 0, locked_until = NULL, must_change_password = TRUE WHERE id = %s',
               (password_hash, user_id))
    db.commit()

    flash(_('Password reset successfully.'), 'success')
    return redirect(url_for('users.list_users'))

@users_bp.route('/<int:user_id>/update-role', methods=['POST'])
@login_required
def update_role(user_id):
    """Inline update a user's role (Admin only)."""
    if not current_user.is_admin():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))
        
    if user_id == current_user.id:
        flash(gettext('Cannot change your own role.'), 'warning')
        return redirect(url_for('users.list_users'))
        
    new_role = request.form.get('role')
    if new_role not in ['admin', 'compliance_officer', 'manager', 'employee']:
        flash(gettext('Invalid role selected.'), 'danger')
        return redirect(url_for('users.list_users'))
        
    User.update_user(user_id, role=new_role)
    flash(gettext('User role updated successfully.'), 'success')
    return redirect(url_for('users.list_users'))
