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

import os, re, subprocess
from datetime import datetime
from functools import wraps

from flask_babel import gettext
from flask import render_template, request, redirect, url_for, flash, jsonify, abort, current_app
from flask_login import login_required, current_user
from utils.decorators import permission_required, admin_required
from admin import admin_bp
from models.user import User
from models.department import Department
from models.audit import AuditLog
import csv
import io

ALLOWED_ROLES = {'employee', 'viewer', 'analyst', 'compliance_officer',
                 'compliance_manager', 'manager', 'admin'}

EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]{1,64}@([A-Za-z0-9\-]+\.)+[A-Za-z]{2,24}$')


def validate_new_user(email, password, role):
    """Checks shared by single add and bulk upload. Returns an untranslated
    error message, or None when the values are acceptable. An empty password
    is left to the caller (both then issue a random one-time password)."""
    email = (email or '').strip()
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        return 'Enter a valid email address.'
    if role not in ALLOWED_ROLES:
        return 'Invalid role selected.'
    if password:
        ok, msg = User.validate_password_strength(password)
        if not ok:
            return msg
    return None

@admin_bp.route('/')
@admin_bp.route('')
@login_required
@permission_required('config')
def admin_index():
    """Administration landing page.

    39 routes existed under /admin/... but nothing answered /admin itself, so
    the obvious URL — the one people type and the one links get truncated to —
    returned 404. Both the bare path and the trailing-slash form are registered
    because Flask treats them as distinct rules here.
    """
    from database.db import query_db

    sections = [
        {'title': 'Users & Access', 'icon': 'bi bi-people', 'items': [
            ('Users', 'admin.list_users', 'Accounts, roles and module permissions'),
            ('Organisation', 'admin.org_tree', 'Group, companies, business units, departments'),
            ('Departments', 'admin.list_departments', 'Legacy department list'),
            ('Multi-Factor Auth', 'admin.mfa_overview', 'Require, lift or reset second factors'),
        ]},
        {'title': 'Documents', 'icon': 'bi bi-files', 'items': [
            ('Document Types', 'admin.document_types', 'Types and their approval workflows'),
        ]},
        {'title': 'Platform', 'icon': 'bi bi-hdd-network', 'items': [
            ('Settings', 'admin.settings', 'General configuration'),
            ('API Keys', 'admin.settings_api_keys', 'Programmatic access for integrations'),
            ('Integrations', 'admin.settings_integrations', 'Health of connected services'),
            ('Backup', 'admin.settings_backup', 'Backup status'),
        ]},
        {'title': 'Oversight', 'icon': 'bi bi-clipboard-data', 'items': [
            ('Approvals', 'admin.approvals', 'Items awaiting a decision'),
            ('Audit Logs', 'admin.view_audit_logs', 'Who did what, and when'),
            ('Reports', 'admin.reports', 'Regulatory reporting calendar'),
        ]},
    ]

    # Drop anything whose endpoint is not registered, so a renamed route leaves
    # a gap rather than a 500 on the landing page itself.
    live = {r.endpoint for r in current_app.url_map.iter_rules()}
    for sec in sections:
        sec['items'] = [i for i in sec['items'] if i[1] in live]
    sections = [s_ for s_ in sections if s_['items']]

    stats = query_db("""SELECT
            (SELECT count(*) FROM users WHERE is_active = 1)              AS users,
            (SELECT count(*) FROM users WHERE mfa_enabled)                AS mfa,
            (SELECT count(*) FROM org_units WHERE is_active)              AS units,
            (SELECT count(*) FROM document_types WHERE is_active)         AS doc_types""",
        one=True)
    return render_template('admin/index.html', sections=sections, stats=stats)


@admin_bp.route('/users')
@login_required
@admin_required
def list_users():
    """List users (administrators only — user management can grant any role),
    with search and filters: name/email, role, department, active, MFA and
    last login."""
    from database.db import get_db
    db = get_db()
    f = {k: (request.args.get(k) or '').strip() for k in ('q', 'role', 'department', 'active', 'mfa', 'last_login')}
    where, params = [], []
    if f['q']:
        like = '%' + f['q'].replace('%', '').replace('_', '') + '%'
        where.append("(u.first_name ILIKE %s OR u.last_name ILIKE %s OR u.email ILIKE %s"
                     " OR (COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) ILIKE %s OR u.job_title ILIKE %s)")
        params += [like] * 5
    if f['role'] in ALLOWED_ROLES:
        where.append('u.role = %s'); params.append(f['role'])
    if f['department'].isdigit():
        where.append('(u.department_id = %s OR EXISTS (SELECT 1 FROM user_departments ud2 '
                     'WHERE ud2.user_id = u.id AND ud2.department_id = %s))')
        params += [int(f['department'])] * 2
    if f['active'] == '1':
        where.append('u.is_active = 1 AND (u.expires_at IS NULL OR u.expires_at > NOW())')
    elif f['active'] == '0':
        where.append('u.is_active <> 1')
    elif f['active'] == 'expired':
        where.append('u.is_active = 1 AND u.expires_at IS NOT NULL AND u.expires_at <= NOW()')
    if f['mfa'] == '1':
        where.append('u.mfa_enabled IS TRUE')
    elif f['mfa'] == '0':
        where.append('u.mfa_enabled IS NOT TRUE')
    if f['last_login'] == 'never':
        where.append('u.last_login IS NULL')
    elif f['last_login'] in ('7', '30', '90'):
        where.append("u.last_login >= NOW() - (%s || ' days')::interval"); params.append(f['last_login'])
    elif f['last_login'] == 'stale':
        where.append("(u.last_login IS NULL OR u.last_login < NOW() - interval '90 days')")
    users = db.execute('''
        SELECT u.*, d.name AS primary_dept_name,
               (SELECT string_agg(d2.name, ', ' ORDER BY d2.name) FROM user_departments ud
                  JOIN departments d2 ON d2.id = ud.department_id WHERE ud.user_id = u.id) AS extra_depts
        FROM users u
        LEFT JOIN departments d ON u.department_id = d.id
        ''' + ('WHERE ' + ' AND '.join(where) if where else '') + '''
        ORDER BY u.first_name, u.last_name
    ''', tuple(params)).fetchall()
    total = db.execute('SELECT count(*) AS n FROM users').fetchone()['n']

    enriched_users = []
    for user_row in users:
        user_dict = dict(user_row)
        # Display department: primary > legacy text > additional departments > '-'
        user_dict['display_department'] = (user_dict.get('primary_dept_name') or user_dict.get('department')
                                           or user_dict.get('extra_depts') or '-')
        _exp = user_dict.get('expires_at')
        try:
            from datetime import timezone as _tz
            user_dict['is_expired'] = bool(_exp) and _exp <= (datetime.now(_tz.utc) if getattr(_exp, 'tzinfo', None) else datetime.now())
        except TypeError:
            user_dict['is_expired'] = False
        enriched_users.append(user_dict)

    departments = db.execute('SELECT id, name FROM departments ORDER BY name').fetchall()
    return render_template('admin/users/list.html', users=enriched_users, filters=f, total=total,
                           roles=sorted(ALLOWED_ROLES), departments=departments)

def _authority_context(user_id=None):
    """Everything the can-see / cannot-see picker needs.

    The unit list is passed as JSON rather than rendered as <option> tags,
    because the picker rebuilds both boxes client-side whenever a preset
    changes — it needs the whole tree, not just one side of it.
    """
    import json
    from services import org_service as _O
    units = _O.get_tree(active_only=True)
    payload = [{'id': u['id'], 'name': u['name_en'], 'code': u['code'],
                'depth': u['depth'], 'path': u['path']} for u in units]
    if user_id:
        can, _cannot = _O.can_cannot_lists(user_id)
        visible = [u['id'] for u in can]
    else:
        visible = [u['id'] for u in units]   # new users default to full visibility
    return {'org_units': units,
            'all_units_json': json.dumps(payload),
            'visible_ids_json': json.dumps(visible),
            'authority_levels': _O.AUTHORITY_LEVELS}


@admin_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    """Add a single user"""

    departments = Department.get_all()
    from database.db import get_db as _get_db_managers
    managers = _get_db_managers().execute(
        "SELECT id, first_name, last_name, role FROM users WHERE role IN ('manager','compliance_manager','admin') AND is_active = 1 ORDER BY first_name, last_name"
    ).fetchall()

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password')
        # No password typed: issue a random one-time password, shown once below.
        issued_password = None
        if not password:
            from utils.temp_password import generate as _gen_pw
            password = issued_password = _gen_pw()
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role = request.form.get('role', 'employee')
        _err = validate_new_user(email, password, role)
        if _err:
            flash(gettext(_err), 'danger')
            return redirect(request.url)
        is_active = 1 if request.form.get('is_active') else 0
        employee_id = request.form.get('employee_id')
        department_id = request.form.get('department_id')
        manager_id = request.form.get('manager_id') or None
        # Resolve department name for legacy field from department_id
        dept_obj = Department.get_by_id(department_id) if department_id else None
        department = dept_obj.name if dept_obj else request.form.get('department', '')
        job_title = request.form.get('job_title')
        
        # Granular permissions
        perms = {
            'perm_governance': request.form.get('perm_governance', 'none'),
            'perm_aml': request.form.get('perm_aml', 'none'),
            'perm_policies': request.form.get('perm_policies', 'none'),
            'perm_reports': request.form.get('perm_reports', 'none'),
            'perm_pdpl': request.form.get('perm_pdpl', 'none'),
            'perm_training': request.form.get('perm_training', 'none'),
            'perm_screening': request.form.get('perm_screening', 'none'),
            'perm_config': request.form.get('perm_config', 'none'),
            'perm_cyber': request.form.get('perm_cyber', 'none'),
            'perm_ghe': request.form.get('perm_ghe', 'none'),
            'perm_coi': request.form.get('perm_coi', 'none'),
            'perm_cobec': request.form.get('perm_cobec', 'none'),
            'perm_merchant_kyc': request.form.get('perm_merchant_kyc', 'none'),
            'perm_tm': request.form.get('perm_tm', 'none'),
            'perm_whistleblowing': request.form.get('perm_whistleblowing', 'none'),
            # perm_phishing existed in the schema and was enforced by the
            # sidebar, but was never offered in the form nor saved here, so it
            # could never be granted to a non-admin.
            'perm_phishing': request.form.get('perm_phishing', 'none'),
            'perm_consumer_protection': request.form.get('perm_consumer_protection', 'none'),
            'perm_ekyc': request.form.get('perm_ekyc', 'none'),
            'perm_risk_management': request.form.get('perm_risk_management', 'none'),
            'perm_internal_audit': request.form.get('perm_internal_audit', 'none'),
            'perm_esg': request.form.get('perm_esg', 'none'),
            'perm_carbon': request.form.get('perm_carbon', 'none'),
            # Running a re-screen and adjudicating its findings is a
            # separate duty from clearing a match, so it is granted
            # separately rather than riding on perm_screening.
            'perm_ongoing_screening': request.form.get('perm_ongoing_screening', 'none'),
            'perm_academy': request.form.get('perm_academy', 'none'),
            'perm_regcontrols': request.form.get('perm_regcontrols', 'none'),
            'perm_prudential': request.form.get('perm_prudential', 'none'),
            'perm_ai': request.form.get('perm_ai', 'none'),
        }
        
        # Handle temporary user
        is_temporary = 1 if request.form.get('is_temporary') else 0
        expires_at = None
        if is_temporary:
            from datetime import datetime, timedelta
            duration = request.form.get('temp_duration', '7')
            custom_date = request.form.get('expires_at_custom', '')
            if custom_date:
                try:
                    expires_at = datetime.strptime(custom_date, '%Y-%m-%d').isoformat()
                except Exception:
                    expires_at = (datetime.now() + timedelta(days=7)).isoformat()
            else:
                expires_at = (datetime.now() + timedelta(days=int(duration))).isoformat()

        try:
            new_user = User.create_user(email, password, first_name, last_name, role, employee_id, department, job_title,
                                        manager_id=manager_id, is_active=is_active, **perms)
            # Permissions for modules added by optional content packs.
            from regcontrols.packs import save_module_perms
            save_module_perms(new_user.id, request.form)

            # Authority level: which parts of the organisation this user may
            # see. Set here rather than only on the separate visibility screen,
            # so a user is never created with the wrong default and then
            # forgotten about.
            from services import org_service as _O
            # The picker posts the CAN SEE side. It wins over the preset
            # dropdown, because the boxes are what the administrator was
            # actually looking at when they pressed save.
            chosen = request.form.getlist('can_see_units')
            if chosen:
                _O.apply_explicit_scope(new_user.id, chosen, granted_by=current_user.id)
            else:
                _O.apply_authority(new_user.id,
                                   request.form.get('authority_level') or 'group',
                                   request.form.get('authority_unit_id') or None,
                                   request.form.getlist('authority_exclude'),
                                   granted_by=current_user.id)
            from database.db import execute_db as _ex
            # Organisation unit: the one chosen, otherwise the company's root unit.
            _ex("UPDATE users SET org_unit_id=%s, must_change_password=TRUE WHERE id=%s",
                (request.form.get('org_unit_id') or _O.root_unit_id(), new_user.id))
            
            # Set the primary department_id on the new user
            if department_id:
                from database.db import get_db
                db = get_db()
                db.execute('UPDATE users SET department_id = %s WHERE id = %s', (department_id, new_user.id))
                db.commit()

            # Training assignment authority (independent of role/perm_training)
            can_assign_training = bool(request.form.get('can_assign_training'))
            from database.db import get_db
            db = get_db()
            db.execute('UPDATE users SET can_assign_training = %s WHERE id = %s', (can_assign_training, new_user.id))
            db.commit()

            # Set temporary user fields
            if is_temporary:
                from database.db import get_db
                db = get_db()
                db.execute('UPDATE users SET is_temporary = %s, expires_at = %s WHERE id = %s',
                           (is_temporary, expires_at, new_user.id))
                db.commit()

            # Handle Additional Access departments
            accessible_departments = request.form.getlist('accessible_departments')
            if accessible_departments:
                from database.db import get_db
                db = get_db()
                for dept_id in accessible_departments:
                    db.execute('INSERT INTO user_departments (user_id, department_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                              (new_user.id, dept_id))
                db.commit()

            # Auto-assign training/policies
            from models.training import TrainingRequirement
            assigned = TrainingRequirement.assign_requirements(new_user.id, role, department, current_user.id)
            
            flash(gettext('User created successfully. %(assigned)s training items assigned.', assigned=assigned), 'success')
            AuditLog.log(current_user.id, 'Create User', 'Admin', new_user.id,
                         f'Created user {email} ({role}); ' + ('one-time password issued' if issued_password
                                                               else 'password set by administrator') +
                         '; password change required at first login', request.remote_addr)
            if issued_password:
                return _credentials_page([{'email': email, 'first_name': first_name, 'last_name': last_name,
                                           'password': issued_password}])
            return redirect(url_for('admin.list_users'))
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            flash(f'Error creating user: {str(e)}', 'danger')
            
    return render_template('admin/users/add.html', departments=departments,
                           managers=managers, **_authority_context())

@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash(gettext('You cannot delete your own account.'), 'danger')
        return redirect(url_for('admin.list_users'))
    try:
        from database.db import get_db
        db = get_db()
        user = db.execute('SELECT first_name, last_name, email, role FROM users WHERE id = %s', (user_id,)).fetchone()
        if not user:
            flash(gettext('User not found.'), 'danger')
            return redirect(url_for('admin.list_users'))
        if user['role'] == 'admin':
            admin_count = db.execute("SELECT COUNT(*) as c FROM users WHERE role = 'admin'").fetchone()['c']
            if admin_count <= 1:
                flash(gettext('Cannot delete the last remaining admin account.'), 'danger')
                return redirect(url_for('admin.list_users'))
        db.execute('DELETE FROM users WHERE id = %s', (user_id,))
        db.commit()
        AuditLog.log(current_user.id, 'Delete User', 'Admin', user_id,
                     f'Deleted user: {user["first_name"]} {user["last_name"]} ({user["email"]})')
        flash(gettext('User %(first_name)s %(last_name)s deleted successfully.', first_name=user["first_name"], last_name=user["last_name"]), 'success')
    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'danger')
    return redirect(url_for('admin.list_users'))


@admin_bp.route('/users/upload', methods=['POST'])
@login_required
@admin_required
def upload_users():
    """Upload users from CSV"""

    if 'file' not in request.files:
        flash(gettext('No file part'), 'danger')
        return redirect(url_for('admin.list_users'))
        
    file = request.files['file']
    if file.filename == '':
        flash(gettext('No selected file'), 'danger')
        return redirect(url_for('admin.list_users'))
        
    if file and file.filename.endswith('.csv'):
        try:
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_input = csv.DictReader(stream)
            
            count = 0
            errors = 0
            failed = []   # (line number, reason) — reported back so nothing fails silently
            issued = []   # one-time credentials, shown once to the administrator
            from utils.temp_password import generate as _gen_pw
            from services import org_service as _O
            from database.db import execute_db as _ex
            root_unit = _O.root_unit_id()
            dept_names = {(d.name or '').strip().lower(): d.name for d in Department.get_all()}

            for line_no, row in enumerate(csv_input, start=2):   # line 1 is the header
                try:
                    # Basic mapping check
                    email = (row.get('Email') or row.get('email') or '').strip()
                    first_name = row.get('First Name') or row.get('first_name')
                    last_name = row.get('Last Name') or row.get('last_name')
                    # A password column is still accepted; otherwise every user gets their own random one.
                    given_pw = (row.get('Password') or row.get('password') or '').strip()
                    password = given_pw or _gen_pw()
                    department = (row.get('Department') or row.get('department') or '').strip()
                    job_title = row.get('Job Title') or row.get('job_title')
                    role = (row.get('Role') or row.get('role') or 'employee').strip().lower()

                    if not (email and first_name and last_name):
                        reason = gettext('Email, first name and last name are required.')
                    elif department and department.lower() not in dept_names:
                        reason = gettext('Unknown department: %(name)s', name=department)
                    else:
                        _err = validate_new_user(email, password, role)
                        reason = gettext(_err) if _err else None
                    if reason:
                        errors += 1
                        failed.append((line_no, reason))
                        continue
                    department = dept_names.get(department.lower()) if department else None
                    new_u = User.create_user(email, password, first_name, last_name, role, None, department, job_title)
                    _ex("UPDATE users SET org_unit_id = COALESCE(org_unit_id, %s), must_change_password = TRUE "
                        "WHERE id = %s", (root_unit, new_u.id))
                    _O.apply_authority(new_u.id, 'group', None, [], granted_by=current_user.id)
                    issued.append({'email': email, 'first_name': first_name, 'last_name': last_name,
                                   'password': '' if given_pw else password})
                    count += 1
                except Exception as e:
                    errors += 1
                    failed.append((line_no, str(e)[:120]))

            flash(gettext('Successfully imported %(count)s users. %(errors)s failed.', count=count, errors=errors), 'success' if errors == 0 else 'warning')
            if failed:
                detail = '; '.join(gettext('Row %(row)s: %(reason)s', row=n, reason=r) for n, r in failed[:20])
                if len(failed) > 20:
                    detail += ' …'
                flash(detail, 'danger')
            if issued:
                AuditLog.log(current_user.id, 'Bulk Upload Users', 'Admin', None,
                             f'{len(issued)} users imported with one-time passwords; change required at first login',
                             request.remote_addr)
                return _credentials_page(issued)
            
        except Exception as e:
            flash(f'Error processing file: {str(e)}', 'danger')
            
    return redirect(url_for('admin.list_users'))

def _credentials_page(rows):
    """Show newly issued one-time passwords once, with a CSV download built in
    the page itself (nothing is stored in clear on the server)."""
    from flask import make_response
    from utils.temp_password import credentials_csv
    resp = make_response(render_template('admin/users/credentials.html', rows=rows,
                                         csv_text=credentials_csv(rows)))
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


def _excluded_unit_ids(user_id):
    """Units explicitly excluded for a user, for pre-selecting the form field.

    A helper rather than an inline query because admin/routes.py imports the db
    helpers per-function, and the inline version referenced query_db in a scope
    that never imported it — which 500'd the whole edit-user page.
    """
    from database.db import query_db
    rows = query_db("SELECT org_unit_id FROM user_org_scope_rules "
                    "WHERE user_id=%s AND is_exclusion", (user_id,)) or []
    return [dict(r)['org_unit_id'] for r in rows if dict(r)['org_unit_id']]


@admin_bp.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id):
    """Edit an existing user"""

    user = User.get_by_id(id)
    if not user:
        flash(gettext('User not found.'), 'danger')
        return redirect(url_for('admin.list_users'))
        
    departments = Department.get_all()
    user_accessible_depts = user.get_accessible_departments()
    from database.db import get_db as _get_db_managers
    managers = _get_db_managers().execute(
        "SELECT id, first_name, last_name, role FROM users WHERE role IN ('manager','compliance_manager','admin') AND is_active = 1 AND id != %s ORDER BY first_name, last_name",
        (id,)
    ).fetchall()


    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        department = request.form.get('department')
        job_title = request.form.get('job_title')
        _role_raw = request.form.get('role', '')
        role = _role_raw if _role_raw in ALLOWED_ROLES else 'viewer'
        if id == current_user.id and role != user.role:
            flash(gettext('You cannot change your own role.'), 'danger')
            return redirect(request.url)
        cms_access_level = request.form.get('cms_access_level')
        is_active = 1 if request.form.get('is_active') else False
        new_password = request.form.get('new_password')
        
        try:
            # Handle M2M Departments
            accessible_departments = request.form.getlist('accessible_departments')
            
            # Ensure primary department is included in accessible list logic (though stored separately)
            # The UI will handle the selection, but we pass the list to update_user
            
            update_data = {
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
                'department_id': request.form.get('department_id') or None, # New Primary Dept ID
                'manager_id': request.form.get('manager_id') or None,
                'job_title': job_title,
                'role': role,
                'cms_access_level': cms_access_level,
                'is_active': 1 if is_active else 0,
                'accessible_departments': accessible_departments, # New list
                'perm_governance': request.form.get('perm_governance', 'none'),
                'perm_aml': request.form.get('perm_aml', 'none'),
                'perm_policies': request.form.get('perm_policies', 'none'),
                'perm_reports': request.form.get('perm_reports', 'none'),
                'perm_pdpl': request.form.get('perm_pdpl', 'none'),
                'perm_training': request.form.get('perm_training', 'none'),
                'perm_screening': request.form.get('perm_screening', 'none'),
                'perm_config': request.form.get('perm_config', 'none'),
                'perm_cyber': request.form.get('perm_cyber', 'none'),
                'perm_consumer_protection': request.form.get('perm_consumer_protection', 'none'),
                'perm_whistleblowing': request.form.get('perm_whistleblowing', 'none'),
                'perm_phishing': request.form.get('perm_phishing', 'none'),
                'perm_ghe': request.form.get('perm_ghe', 'none'),
                'perm_coi': request.form.get('perm_coi', 'none'),
                'perm_cobec': request.form.get('perm_cobec', 'none'),
                'perm_merchant_kyc': request.form.get('perm_merchant_kyc', 'none'),
                'perm_tm': request.form.get('perm_tm', 'none'),
                'perm_ekyc': request.form.get('perm_ekyc', 'none'),
                'perm_risk_management': request.form.get('perm_risk_management', 'none'),
                'perm_internal_audit': request.form.get('perm_internal_audit', 'none'),
                'perm_esg': request.form.get('perm_esg', 'none'),
                'perm_carbon': request.form.get('perm_carbon', 'none'),
            # Running a re-screen and adjudicating its findings is a
            # separate duty from clearing a match, so it is granted
            # separately rather than riding on perm_screening.
            'perm_ongoing_screening': request.form.get('perm_ongoing_screening', 'none'),
            'perm_academy': request.form.get('perm_academy', 'none'),
            'perm_regcontrols': request.form.get('perm_regcontrols', 'none'),
            'perm_prudential': request.form.get('perm_prudential', 'none'),
            'perm_ai': request.form.get('perm_ai', 'none'),
                'can_assign_training': bool(request.form.get('can_assign_training'))
            }

            if new_password:
                _ok, _msg = User.validate_password_strength(new_password)
                if not _ok:
                    from flask_babel import gettext as _t
                    flash(_t(_msg), 'danger')
                    return redirect(request.url)
                update_data['password_hash'] = User.hash_password(new_password)

            # Handle temporary access
            is_temporary = 1 if request.form.get('is_temporary') else 0
            update_data['is_temporary'] = is_temporary
            if is_temporary:
                from datetime import datetime, timedelta
                duration = request.form.get('temp_duration', '7')
                custom_date = request.form.get('expires_at_custom', '')
                if custom_date:
                    try:
                        expires_at = datetime.strptime(custom_date, '%Y-%m-%d').isoformat()
                    except Exception:
                        expires_at = (datetime.now() + timedelta(days=7)).isoformat()
                else:
                    expires_at = (datetime.now() + timedelta(days=int(duration))).isoformat()
                update_data['expires_at'] = expires_at
            else:
                update_data['expires_at'] = None

            # Track changes before update
            old_role = user.role
            old_cms = user.cms_access_level
            old_screening = getattr(user, 'perm_screening', 'none')

            User.update_user(id, **update_data)
            if new_password or not update_data.get('is_active'):
                # a new password or a deactivation ends every open session of that user
                from database.db import get_db as _gdb
                _db = _gdb()
                _db.execute('UPDATE users SET auth_version = COALESCE(auth_version, 0) + 1, '
                            'failed_login_count = 0, locked_until = NULL WHERE id = %s', (id,))
                _db.commit()
            # Permissions for modules added by optional content packs.
            from regcontrols.packs import save_module_perms
            save_module_perms(id, request.form)

            from services import org_service as _O
            from database.db import execute_db as _ex
            chosen = request.form.getlist('can_see_units')
            if chosen:
                _O.apply_explicit_scope(id, chosen, granted_by=current_user.id)
            else:
                _O.apply_authority(id,
                                   request.form.get('authority_level') or 'group',
                                   request.form.get('authority_unit_id') or None,
                                   request.form.getlist('authority_exclude'),
                                   granted_by=current_user.id)
            if request.form.get('org_unit_id'):
                _ex("UPDATE users SET org_unit_id=%s WHERE id=%s",
                    (request.form.get('org_unit_id'), id))
            elif not getattr(user, 'org_unit_id', None):
                _ex("UPDATE users SET org_unit_id=%s WHERE id=%s AND org_unit_id IS NULL", (_O.root_unit_id(), id))
            if new_password:
                # an administrator-set password is temporary: the user replaces it at the next login
                _ex("UPDATE users SET must_change_password=TRUE WHERE id=%s", (id,))

            # Audit log: track what changed
            changes = []
            if role != old_role:
                changes.append(f"Role: {old_role}→{role}")
            if cms_access_level != old_cms:
                changes.append(f"CMS Access: {old_cms}→{cms_access_level}")
            perm_screening_new = update_data.get('perm_screening', 'none')
            if perm_screening_new != old_screening:
                changes.append(f"Screening Permission: {old_screening}→{perm_screening_new}")
            change_detail = '; '.join(changes) if changes else 'User details updated'
            from models.audit import AuditLog as _AL
            _AL.log(current_user.id, 'Update User', 'Admin', id,
                    f'Updated user {first_name} {last_name}: {change_detail}',
                    request.remote_addr)

            # Auto-assign training/policies based on new Role/Department
            from models.training import TrainingRequirement
            assigned = TrainingRequirement.assign_requirements(id, role, department, current_user.id)
            
            flash(gettext('User updated successfully. %(assigned)s new training items assigned.', assigned=assigned), 'success')
            return redirect(url_for('admin.list_users'))
        except Exception as e:
            flash(f'Error updating user: {str(e)}', 'danger')
            
    return render_template('admin/users/edit.html', user=user, departments=departments,
                           user_accessible_depts=user_accessible_depts, managers=managers,
                           excluded_ids=_excluded_unit_ids(user.id),
                           **_authority_context(user.id))

@admin_bp.route('/audit-logs')
@login_required
def view_audit_logs():
    """View system audit logs (Compliance/Admin only)"""
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))
    
    filters = {
        'search': request.args.get('search'),
        'module': request.args.get('module'),
        'action': request.args.get('action'),
        'date_from': request.args.get('date_from'),
        'date_to': request.args.get('date_to')
    }
    # Filter out None/empty
    active_filters = {k: v for k, v in filters.items() if v}
    
    logs = AuditLog.get_all(filters=active_filters)
    
    # Get unique modules and actions for filter dropdowns
    from database.db import get_db
    db = get_db()
    modules = [row['module'] for row in db.execute('SELECT DISTINCT module FROM audit_logs WHERE module IS NOT NULL ORDER BY module').fetchall()]
    actions = [row['action'] for row in db.execute('SELECT DISTINCT action FROM audit_logs ORDER BY action').fetchall()]

    return render_template('admin/audit_logs.html', 
                         logs=logs, 
                         filters=filters,
                         modules=modules,
                         actions=actions)

@admin_bp.route('/approvals')
@login_required
def approvals():
    """Centralized approvals dashboard"""
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))
        
    from models.ghe import GHEDeclaration
    from models.coi import COIDeclaration
    from database.db import get_db
    
    # Get pending GHE
    ghe_pending = GHEDeclaration.get_pending_for_compliance()
    
    # Get pending COI
    coi_pending = COIDeclaration.get_pending_for_compliance()
    
    # Get pending COBEC
    db = get_db()
    cobec_pending = db.execute(
        "SELECT * FROM cobec_declarations WHERE status IN ('under_review', 'escalated', 'submitted')"
    ).fetchall()
    
    return render_template('admin/approvals.html', 
                         ghe_pending=ghe_pending,
                         coi_pending=coi_pending,
                         cobec_pending=cobec_pending)

@admin_bp.route('/reports')
@login_required
def reports():
    """System Reports Hub"""
    if not current_user.is_admin() and not current_user.is_compliance_officer():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))
    return render_template('admin/reports.html')

@admin_bp.route('/settings')
@login_required
@permission_required('config')
def settings():
    """Settings Hub — enterprise admin configuration landing page."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    backup_info = _backup_status()
    return render_template('admin/settings/hub.html', backup_info=backup_info)


@admin_bp.route('/settings/general', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def settings_general():
    """General Settings: Organization Info + Workflow (GHE) thresholds."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    from database.db import get_db
    from models.settings import Settings as Cfg
    db = get_db()

    ORG_FIELDS = ['company_name', 'registration_number', 'regulator_name',
                  'contact_email', 'contact_phone', 'address',
                  'governance_independence_tenure_years', 'governance_independence_shareholding_pct']

    if request.method == 'POST':
        # Organization Info
        for field in ORG_FIELDS:
            value = request.form.get(field)
            if value is not None:
                old = Cfg.get(field, '')
                if old != value:
                    Cfg.set(field, value)
                    AuditLog.log(current_user.id, 'Update Setting', 'Settings', None,
                                 f'Organization field "{field}" changed')

        # GHE Thresholds
        ghe_auto = request.form.get('ghe_auto_approve_threshold')
        ghe_manager = request.form.get('ghe_manager_approval_threshold')

        old_auto = db.execute('SELECT setting_value FROM system_settings WHERE setting_key = %s', ('ghe_auto_approve_threshold',)).fetchone()
        old_manager = db.execute('SELECT setting_value FROM system_settings WHERE setting_key = %s', ('ghe_manager_approval_threshold',)).fetchone()

        if ghe_auto:
            db.execute('UPDATE system_settings SET setting_value = %s WHERE setting_key = %s', (ghe_auto, 'ghe_auto_approve_threshold'))
            if old_auto and old_auto['setting_value'] != ghe_auto:
                AuditLog.log(current_user.id, 'Update Setting', 'Settings', None,
                             f'GHE Auto-approve threshold changed from {old_auto["setting_value"]} to {ghe_auto}')

        if ghe_manager:
            db.execute('UPDATE system_settings SET setting_value = %s WHERE setting_key = %s', (ghe_manager, 'ghe_manager_approval_threshold'))
            if old_manager and old_manager['setting_value'] != ghe_manager:
                AuditLog.log(current_user.id, 'Update Setting', 'Settings', None,
                             f'GHE Manager approval threshold changed from {old_manager["setting_value"]} to {ghe_manager}')

        db.commit()
        flash(gettext('Settings updated successfully.'), 'success')
        return redirect(url_for('admin.settings_general'))

    rows = db.execute('SELECT setting_key, setting_value FROM system_settings').fetchall()
    settings_dict = {row['setting_key']: row['setting_value'] for row in rows}

    return render_template('admin/settings/general.html', settings=settings_dict)


@admin_bp.route('/settings/security', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def settings_security():
    """Security Settings: session timeout, password policy, MFA overview."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    from models.settings import Settings as Cfg
    from database.db import get_db

    if request.method == 'POST':
        session_timeout = request.form.get('session_timeout_minutes')
        min_length = request.form.get('password_min_length')
        require_complexity = 'password_require_complexity' in request.form

        if session_timeout and session_timeout.isdigit():
            Cfg.set('session_timeout_minutes', session_timeout)
        if min_length and min_length.isdigit():
            Cfg.set('password_min_length', min_length)
        Cfg.set('password_require_complexity', 'true' if require_complexity else 'false')

        AuditLog.log(current_user.id, 'Update Setting', 'Settings', None, 'Security policy updated')
        flash(gettext('Security settings updated. Session timeout applies to new logins.'), 'success')
        return redirect(url_for('admin.settings_security'))

    db = get_db()
    mfa_stats = db.execute(
        "SELECT COUNT(*) FILTER (WHERE mfa_enabled) AS enabled, COUNT(*) AS total FROM users"
    ).fetchone()

    return render_template('admin/settings/security.html',
                            session_timeout_minutes=Cfg.get_int('session_timeout_minutes', 30),
                            password_min_length=Cfg.get_int('password_min_length', 8),
                            password_require_complexity=Cfg.get_bool('password_require_complexity', True),
                            mfa_stats=mfa_stats)


@admin_bp.route('/settings/numbering', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def settings_numbering():
    """Numbering Sequences: configurable prefix/padding for document IDs."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    from database.db import get_db
    db = get_db()

    if request.method == 'POST':
        seq_id = request.form.get('id')
        prefix = (request.form.get('prefix') or '').strip().upper()
        padding = request.form.get('padding')
        if seq_id and prefix and padding and padding.isdigit():
            db.execute(
                'UPDATE numbering_sequences SET prefix = %s, padding = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                (prefix, int(padding), seq_id)
            )
            db.commit()
            AuditLog.log(current_user.id, 'Update Setting', 'Settings', seq_id, f'Numbering sequence updated: prefix={prefix}')
            flash(gettext('Numbering sequence updated.'), 'success')
        return redirect(url_for('admin.settings_numbering'))

    sequences = db.execute('SELECT * FROM numbering_sequences ORDER BY sequence_key').fetchall()
    return render_template('admin/settings/numbering.html', sequences=sequences)


@admin_bp.route('/settings/email-templates')
@login_required
@permission_required('config')
def settings_email_templates():
    """Email Templates list."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    from database.db import get_db
    db = get_db()
    templates = db.execute('SELECT * FROM email_templates ORDER BY template_key').fetchall()
    return render_template('admin/settings/email_templates.html', templates=templates)


@admin_bp.route('/settings/email-templates/new', methods=['POST'])
@login_required
@permission_required('config')
def create_email_template():
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    from database.db import get_db
    db = get_db()
    key = (request.form.get('template_key') or '').strip()
    subject = request.form.get('subject', '')
    if not key:
        flash(gettext('Template key is required.'), 'danger')
        return redirect(url_for('admin.settings_email_templates'))
    try:
        db.execute(
            'INSERT INTO email_templates (template_key, subject, body_html, body_text, updated_by) VALUES (%s, %s, %s, %s, %s)',
            (key, subject, request.form.get('body_html', ''), request.form.get('body_text', ''), current_user.id)
        )
        db.commit()
        AuditLog.log(current_user.id, 'Create Email Template', 'Settings', None, f'Created email template {key}')
        flash(gettext('Email template created.'), 'success')
    except Exception as e:
        flash(f'Error creating template: {str(e)}', 'danger')
    return redirect(url_for('admin.settings_email_templates'))


@admin_bp.route('/settings/email-templates/<int:template_id>/edit', methods=['POST'])
@login_required
@permission_required('config')
def edit_email_template(template_id):
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    from database.db import get_db
    db = get_db()
    is_active = 'is_active' in request.form
    db.execute(
        '''UPDATE email_templates
           SET subject = %s, body_html = %s, body_text = %s, is_active = %s,
               updated_at = CURRENT_TIMESTAMP, updated_by = %s
           WHERE id = %s''',
        (request.form.get('subject', ''), request.form.get('body_html', ''),
         request.form.get('body_text', ''), is_active, current_user.id, template_id)
    )
    db.commit()
    AuditLog.log(current_user.id, 'Update Email Template', 'Settings', template_id, 'Email template updated')
    flash(gettext('Email template updated.'), 'success')
    return redirect(url_for('admin.settings_email_templates'))


APPROVER_ROLES = ('compliance_officer', 'compliance_manager')
PERM_LEVELS = ('none', 'view', 'edit', 'approve')


def effective_level(user, module):
    """What a user can do in a module, for the permissions matrix:
    'approve' — site administrator, the module's 'admin' level, or edit rights
    held by a compliance officer/manager (the roles the approval and four-eyes
    steps accept); 'edit'; 'view'; or 'none'."""
    if user.is_admin() or user.can_admin_module(module):
        return 'approve'
    if user.can_edit(module):
        return 'approve' if user.role in APPROVER_ROLES else 'edit'
    if user.can_view(module):
        return 'view'
    return 'none'


@admin_bp.route('/settings/permissions-matrix')
@login_required
@admin_required
def settings_permissions_matrix():
    """Roles x modules x view/edit/approve, plus the per-user grid; CSV export."""
    from utils.labels import MODULES, label as _label, module_label
    view = request.args.get('view', 'roles')
    role_f = request.args.get('role', '')
    module_f = request.args.get('module', '')
    show_inactive = request.args.get('inactive') == '1'
    modules = [m for m, _l in MODULES]
    shown_modules = [m for m in modules if not module_f or m == module_f]
    users = [u for u in User.get_all() if (show_inactive or u.is_active)]
    if role_f:
        users = [u for u in users if u.role == role_f]
    levels = {u.id: {m: effective_level(u, m) for m in shown_modules} for u in users}
    roles = [r for r in ['admin', 'compliance_manager', 'compliance_officer', 'manager', 'analyst', 'viewer', 'employee']
             if any(u.role == r for u in users)]
    roles += sorted({u.role for u in users if u.role and u.role not in roles})
    role_users = {r: [u for u in users if u.role == r] for r in roles}
    # role_matrix[module][role] = {'view': n, 'edit': n, 'approve': n, 'total': n}
    role_matrix = {m: {r: {lv: sum(1 for u in role_users[r] if levels[u.id][m] == lv) for lv in PERM_LEVELS}
                       for r in roles} for m in shown_modules}

    if request.args.get('format') == 'csv':
        buf = io.StringIO()
        w = csv.writer(buf)
        lv_name = {lv: gettext({'none': 'No access', 'view': 'View', 'edit': 'Edit', 'approve': 'Approve'}[lv]) for lv in PERM_LEVELS}
        if view == 'users':
            w.writerow([gettext('User'), gettext('Email'), gettext('Role'), gettext('Active')] + [module_label(m) for m in shown_modules])
            for u in users:
                w.writerow([u.get_full_name(), u.email, _label(u.role), gettext('Yes') if u.is_active else gettext('No')]
                           + [lv_name[levels[u.id][m]] for m in shown_modules])
        else:
            w.writerow([gettext('Module'), gettext('Role'), gettext('Users'), lv_name['view'], lv_name['edit'], lv_name['approve'], lv_name['none']])
            for m in shown_modules:
                for r in roles:
                    c = role_matrix[m][r]
                    w.writerow([module_label(m), _label(r), len(role_users[r]), c['view'], c['edit'], c['approve'], c['none']])
        AuditLog.log(current_user.id, 'Export Permissions Matrix', 'Settings', None, f'view={view}')
        from flask import Response
        return Response('\ufeff' + buf.getvalue(), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename=permissions_matrix_{view}.csv'})

    return render_template('admin/settings/permissions_matrix.html', users=users, modules=modules,
                           shown_modules=shown_modules, levels=levels, roles=roles, role_users=role_users,
                           role_matrix=role_matrix, view=view, role_f=role_f, module_f=module_f,
                           show_inactive=show_inactive, all_roles=sorted(ALLOWED_ROLES))


@admin_bp.route('/settings/localization', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def settings_localization():
    """Platform default language."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    from models.settings import Settings as Cfg

    if request.method == 'POST':
        locale = request.form.get('default_locale')
        if locale in ('ar', 'en'):
            Cfg.set('default_locale', locale)
            AuditLog.log(current_user.id, 'Update Setting', 'Settings', None, f'Default locale set to {locale}')
            flash(gettext('Default language updated. Takes effect for new sessions.'), 'success')
        return redirect(url_for('admin.settings_localization'))

    return render_template('admin/settings/localization.html',
                            default_locale=Cfg.get('default_locale', 'ar'))


def _backup_status():
    """Read-only real backup directory status (no fake config, just facts)."""
    import glob
    backup_dir = '/var/www/complynex/backups'
    files = sorted(glob.glob(os.path.join(backup_dir, '*.tar.gz.gpg')), reverse=True)
    latest = None
    if files:
        stat = os.stat(files[0])
        latest = {
            'name': os.path.basename(files[0]),
            'size_mb': round(stat.st_size / (1024 * 1024), 1),
            'mtime': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        }
    return {'count': len(files), 'latest': latest, 'directory': backup_dir}


@admin_bp.route('/settings/backup')
@login_required
@permission_required('config')
def settings_backup():
    """Read-only backup status (real daily cron-driven backups, no fake schedule UI)."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))
    return render_template('admin/settings/backup.html', backup_info=_backup_status())


@admin_bp.route('/settings/api-keys')
@login_required
@permission_required('config')
def settings_api_keys():
    """API Keys management UI — calls the existing /api/v1/keys JSON endpoints."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))
    return render_template('admin/settings/api_keys.html')


@admin_bp.route('/settings/integrations')
@login_required
@permission_required('config')
def settings_integrations():
    """Read-only health status of external integrations (ES, Redis, Postgres, gdrive)."""
    if not current_user.is_admin():
        flash(gettext('Access denied. Admin only.'), 'danger')
        return redirect(url_for('dashboard'))

    integrations = []

    try:
        from elasticsearch import Elasticsearch
        from screening.es_client import get_es_client
        ok = get_es_client(timeout=3).ping()
        integrations.append({'name': 'Elasticsearch', 'status': 'ok' if ok else 'error',
                              'detail': 'Connected' if ok else 'Ping failed'})
    except Exception as e:
        integrations.append({'name': 'Elasticsearch', 'status': 'error', 'detail': str(e)[:150]})

    try:
        import redis as redis_lib
        ok = redis_lib.Redis(host='localhost', port=6379, db=0).ping()
        integrations.append({'name': 'Redis', 'status': 'ok' if ok else 'error',
                              'detail': 'Connected' if ok else 'Ping failed'})
    except Exception as e:
        integrations.append({'name': 'Redis', 'status': 'error', 'detail': str(e)[:150]})

    try:
        from database.db import get_db
        get_db().execute('SELECT 1')
        integrations.append({'name': 'PostgreSQL', 'status': 'ok', 'detail': 'Connected'})
    except Exception as e:
        integrations.append({'name': 'PostgreSQL', 'status': 'error', 'detail': str(e)[:150]})

    gdrive_log = '/var/www/complynex/logs/complynex_gdrive_upload.log'
    if os.path.exists(gdrive_log):
        mtime = datetime.fromtimestamp(os.stat(gdrive_log).st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        integrations.append({'name': 'Google Drive Backup Sync', 'status': 'ok', 'detail': f'Last activity: {mtime}'})
    else:
        integrations.append({'name': 'Google Drive Backup Sync', 'status': 'unknown', 'detail': 'No log file found'})

    return render_template('admin/settings/integrations.html', integrations=integrations)


@admin_bp.route('/reports/generate-calendar', methods=['POST'])
@login_required
def generate_calendar():
    """Trigger generation of upcoming regulatory report submissions."""
    if not current_user.can_manage_users(): # Using generic admin permission
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('admin.reports'))
        
    from models.reporting import RegulatoryReport
    reports = RegulatoryReport.get_all()
    total_generated = 0
    
    for report in reports:
        total_generated += report.generate_upcoming_submissions()
        
    flash(gettext('Calendar updated. Generated %(total_generated)s upcoming submissions.', total_generated=total_generated), 'success')
    return redirect(url_for('admin.reports'))

@admin_bp.route('/training/requirements', methods=['GET', 'POST'])
@login_required
def training_requirements():
    """Manage Training Requirements (Auto-assignment rules)"""
    if not current_user.can_manage_users():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))

    from models.training import TrainingRequirement, TrainingCourse
    from models.policy import Policy
    
    if request.method == 'POST':
        if 'delete' in request.form:
            TrainingRequirement.delete(request.form.get('id'))
            flash(gettext('Requirement deleted.'), 'success')
        elif 'update' in request.form:
            req_id = request.form.get('id')
            data = {
                'role': request.form.get('role'),
                'department': request.form.get('department'),
                'course_id': request.form.get('course_id') or None,
                'policy_id': request.form.get('policy_id') or None,
                'is_mandatory': 1 if request.form.get('is_mandatory') else 0,
                'deadline_days': request.form.get('deadline_days')
            }
            try:
                TrainingRequirement.update(req_id, data)
                flash(gettext('Requirement updated successfully.'), 'success')
            except Exception as e:
                flash(f'Error updating requirement: {str(e)}', 'danger')
        else:
            data = {
                'role': request.form.get('role'),
                'department': request.form.get('department'),
                'course_id': request.form.get('course_id') or None,
                'policy_id': request.form.get('policy_id') or None,
                'is_mandatory': request.form.get('is_mandatory'),
                'deadline_days': request.form.get('deadline_days')
            }
            if not data['course_id'] and not data['policy_id']:
                flash(gettext('Please select either a course or a policy.'), 'warning')
            else:
                try:
                    TrainingRequirement.create(data)
                    flash(gettext('Requirement added successfully.'), 'success')
                except Exception as e:
                    flash(f'Error adding requirement: {str(e)}', 'danger')
        
        return redirect(url_for('admin.training_requirements'))
        
    requirements = TrainingRequirement.get_all()
    courses = TrainingCourse.get_all()
    policies = Policy.get_published()
    
    return render_template('admin/training/requirements.html', 
                         requirements=requirements,
                         courses=courses,
                         policies=policies)

@admin_bp.route('/departments')
@login_required
def list_departments():
    """Manage Departments / Business Units / Branches"""
    if not current_user.is_admin():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))

    from models.department import Department
    unit_type = request.args.get('unit_type') or None
    departments = Department.get_all(unit_type=unit_type)
    all_units = Department.get_all()
    return render_template('admin/departments.html', departments=departments,
                            all_units=all_units, active_unit_type=unit_type)

@admin_bp.route('/departments/create', methods=['POST'])
@login_required
def create_department():
    """Create a new department / business unit / branch"""
    if not current_user.is_admin():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))

    name = request.form.get('name')
    code = request.form.get('code')
    description = request.form.get('description')
    unit_type = request.form.get('unit_type', 'department')
    parent_id = request.form.get('parent_id') or None

    from models.department import Department
    try:
        Department.create(name, code, description, unit_type=unit_type, parent_id=parent_id)
        flash(gettext('Department created successfully.'), 'success')
        AuditLog.log(current_user.id, 'Create Department', 'Admin', None, f'Created department {name} ({code})')
    except Exception as e:
        flash(f'Error creating department: {str(e)}', 'danger')

    return redirect(url_for('admin.list_departments'))

@admin_bp.route('/departments/toggle-active/<int:id>', methods=['POST'])
@login_required
def toggle_department_active(id):
    """Archive/reactivate a department/business unit/branch (soft, preserves FK history)"""
    if not current_user.is_admin():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))

    from models.department import Department
    dept = Department.get_by_id(id)
    if not dept:
        flash(gettext('Not found.'), 'danger')
        return redirect(url_for('admin.list_departments'))
    new_state = not dept.is_active
    Department.set_active(id, new_state)
    AuditLog.log(current_user.id, 'Update Department', 'Admin', id,
                 f'{"Reactivated" if new_state else "Archived"} {dept.name}')
    flash(f'{dept.name} {"reactivated" if new_state else "archived"}.', 'success')
    return redirect(url_for('admin.list_departments'))

@admin_bp.route('/departments/edit/<int:id>', methods=['POST'])
@login_required
def edit_department(id):
    """Edit department"""
    if not current_user.is_admin():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))

    name = request.form.get('name')
    code = request.form.get('code')
    description = request.form.get('description')
    unit_type = request.form.get('unit_type', 'department')
    parent_id = request.form.get('parent_id') or None
    
    from models.department import Department
    try:
        Department.update(id, name, code, description, unit_type=unit_type, parent_id=parent_id)
        flash(gettext('Department updated successfully.'), 'success')
        AuditLog.log(current_user.id, 'Update Department', 'Admin', id, f'Updated department {name}')
    except Exception as e:
        flash(f'Error updating department: {str(e)}', 'danger')
        
    return redirect(url_for('admin.list_departments'))

@admin_bp.route('/departments/delete/<int:id>', methods=['POST'])
@login_required
def delete_department(id):
    """Delete department"""
    if not current_user.is_admin():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('dashboard'))
        
    from models.department import Department
    try:
        # Check if used by users or policies
        # TODO: Implement strict dependency check
        Department.delete(id)
        flash(gettext('Department deleted successfully.'), 'success')
        AuditLog.log(current_user.id, 'Delete Department', 'Admin', id, 'Deleted department')
    except Exception as e:
        flash(f'Error deleting department: {str(e)}', 'danger')
        
    return redirect(url_for('admin.list_departments'))

@admin_bp.route('/departments/create-ajax', methods=['POST'])
@login_required
def create_department_ajax():
    """AJAX endpoint to create a department inline from user forms"""
    if not current_user.can_manage_users():
        return jsonify({'error': 'Access denied'}), 403

    name = request.json.get('name') if request.is_json else request.form.get('name')
    code = request.json.get('code') if request.is_json else request.form.get('code')
    description = request.json.get('description') if request.is_json else request.form.get('description')

    if not name or not code:
        return jsonify({'error': 'Name and code are required'}), 400

    try:
        dept = Department.create(name, code, description)
        AuditLog.log(current_user.id, 'Create Department', 'Admin', dept.id, f'Created department {name} ({code})')
        return jsonify({'id': dept.id, 'name': dept.name, 'code': dept.code})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Superadmin guard ──────────────────────────────────────────────────
def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        role = getattr(current_user, 'role', '')
        if role not in ('superadmin', 'admin', 'it_admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated

# ── Safe Audited Dispatcher (replaces free-text terminal) ─────────────────────
#
# Each DISPATCH_OPS entry is a named operation with a fixed argv list.
# No free-text command input; no shell=True.  Every invocation is written to
# the audit_logs table so compliance staff can see who ran what and when.
#
DISPATCH_OPS = {
    # Service control
    'service_status':   (['systemctl', 'status',  'complynex', '--no-pager'],  'Service status'),
    'service_restart':  (['systemctl', 'restart', 'complynex'],                'Restart service'),
    'service_start':    (['systemctl', 'start',   'complynex'],                'Start service'),
    'service_stop':     (['systemctl', 'stop',    'complynex'],                'Stop service'),
    # Nginx
    'nginx_test':       (['nginx', '-t'],                                       'Nginx config test'),
    'nginx_reload':     (['systemctl', 'reload',  'nginx'],                    'Reload nginx'),
    'nginx_restart':    (['systemctl', 'restart', 'nginx'],                    'Restart nginx'),
    # Logs (read-only, fixed paths, no user-supplied args)
    'tail_app_log':     (['tail', '-n', '100', '/var/www/complynex/logs/complynex.log'], 'Last 100 app log lines'),
    'tail_error_log':   (['tail', '-n', '100', '/var/www/complynex/logs/error.log'],     'Last 100 error log lines'),
    'tail_nginx_access':(['tail', '-n',  '50', '/var/log/nginx/access.log'],             'Last 50 nginx access lines'),
    'journal':          (['journalctl', '-u', 'complynex', '-n', '50', '--no-pager'],    'Last 50 journal entries'),
    # System info (read-only)
    'disk_usage':       (['df', '-h'],                                          'Disk usage'),
    'memory':           (['free', '-h'],                                        'Memory usage'),
    'uptime':           (['uptime'],                                            'System uptime'),
    'processes':        (['ps', 'aux', '--no-headers'],                        'Running processes'),
}


def _audit_dispatch(op_key, label, output, success):
    """Write dispatcher invocation to audit_logs."""
    try:
        from database.db import get_db
        db = get_db()
        db.execute(
            """INSERT INTO audit_logs (user_id, action, module, details, ip_address, created_at)
               VALUES (%s, %s, %s, %s, %s, NOW())""",
            (
                current_user.id,
                f'admin_dispatch:{op_key}',
                'admin',
                f'{label} — {"OK" if success else "FAIL"} — {output[:300]}',
                request.headers.get('X-Forwarded-For', request.remote_addr or ''),
            )
        )
        db.commit()
    except Exception:
        pass  # audit failure must never block the response


@admin_bp.route('/terminal')
@login_required
@superadmin_required
def terminal():
    return redirect(url_for('admin.ops_panel'))


@admin_bp.route('/ops')
@login_required
@superadmin_required
def ops_panel():
    """Safe operations panel — replaces the free-text terminal."""
    ops = [{'key': k, 'label': v[1]} for k, v in DISPATCH_OPS.items()]
    return render_template('admin/ops.html', ops=ops)


@admin_bp.route('/ops/run', methods=['POST'])
@login_required
@superadmin_required
def run_op():
    """Execute a single predefined operation; no free-text input accepted."""
    data = request.get_json(silent=True) or {}
    op_key = data.get('op', '').strip()

    if op_key not in DISPATCH_OPS:
        return jsonify({'output': f'Unknown operation: {op_key!r}', 'success': False}), 400

    argv, label = DISPATCH_OPS[op_key]
    try:
        result = subprocess.run(
            argv,
            capture_output=True, text=True,
            timeout=30,
            env={
                **os.environ,
                'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            }
        )
        output = result.stdout
        if result.stderr:
            output += ('\n' if output else '') + result.stderr
        success = result.returncode == 0
        _audit_dispatch(op_key, label, output, success)
        return jsonify({'output': output or '(no output)', 'success': success, 'label': label})
    except subprocess.TimeoutExpired:
        _audit_dispatch(op_key, label, 'TIMEOUT', False)
        return jsonify({'output': '⚠ Operation timed out after 30 seconds.', 'success': False})
    except Exception as e:
        _audit_dispatch(op_key, label, str(e), False)
        return jsonify({'output': f'Error: {e}', 'success': False})


# =============================================================================
# Organisational hierarchy (Phase 2)
# =============================================================================

@admin_bp.route('/organisation')
@login_required
@permission_required('config')
def org_tree():
    """The org chart. Rendered from a path-ordered flat list rather than a
    recursive macro — depth is already on every row."""
    from services import org_service
    return render_template('admin/organisation/tree.html',
                           units=org_service.get_tree(active_only=False),
                           unit_types=org_service.get_unit_types())


@admin_bp.route('/organisation/unit', methods=['POST'])
@login_required
@permission_required('config')
def org_unit_create():
    from database.db import execute_db
    code = (request.form.get('code') or '').strip().upper()
    name = (request.form.get('name_en') or '').strip()
    if not code or not name:
        flash(gettext('Code and name are both required.'), 'danger')
        return redirect(url_for('admin.org_tree'))
    try:
        execute_db("""INSERT INTO org_units
                        (parent_id, unit_type_id, code, name_en, name_ar,
                         is_legal_entity, country, created_by)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (request.form.get('parent_id') or None,
                    request.form.get('unit_type_id'),
                    code, name,
                    (request.form.get('name_ar') or '').strip() or None,
                    bool(request.form.get('is_legal_entity')),
                    (request.form.get('country') or '').strip() or None,
                    current_user.id))
        flash(gettext('Unit "%(name)s" created.', name=name), 'success')
    except Exception as e:
        msg = str(e)
        if 'org_units_code_uniq' in msg:
            flash(gettext('Code "%(code)s" is already in use.', code=code), 'danger')
        else:
            flash(f'Could not create unit: {msg[:160]}', 'danger')
    return redirect(url_for('admin.org_tree'))


@admin_bp.route('/organisation/unit/<int:unit_id>', methods=['POST'])
@login_required
@permission_required('config')
def org_unit_update(unit_id):
    from database.db import execute_db, query_db
    action = request.form.get('action')

    if action == 'deactivate':
        kids = query_db("SELECT count(*) AS c FROM org_units WHERE parent_id=%s AND is_active",
                        (unit_id,), one=True)
        if dict(kids)['c']:
            flash(gettext('Deactivate or move the child units first.'), 'danger')
            return redirect(url_for('admin.org_tree'))
        staff = query_db("SELECT count(*) AS c FROM users WHERE org_unit_id=%s", (unit_id,), one=True)
        if dict(staff)['c']:
            flash(f'{dict(staff)["c"]} user(s) are still posted to this unit. Move them first.', 'danger')
            return redirect(url_for('admin.org_tree'))
        execute_db("UPDATE org_units SET is_active=FALSE WHERE id=%s", (unit_id,))
        flash(gettext('Unit deactivated. Its history is kept.'), 'info')

    elif action == 'reactivate':
        execute_db("UPDATE org_units SET is_active=TRUE WHERE id=%s", (unit_id,))
        flash(gettext('Unit reactivated.'), 'success')

    else:
        new_parent = request.form.get('parent_id') or None
        if new_parent and int(new_parent) == unit_id:
            flash(gettext('A unit cannot be its own parent.'), 'danger')
            return redirect(url_for('admin.org_tree'))
        try:
            execute_db("""UPDATE org_units SET name_en=%s, name_ar=%s, code=%s,
                                 unit_type_id=%s, parent_id=%s, is_legal_entity=%s,
                                 country=%s, head_user_id=%s, updated_at=NOW()
                           WHERE id=%s""",
                       ((request.form.get('name_en') or '').strip(),
                        (request.form.get('name_ar') or '').strip() or None,
                        (request.form.get('code') or '').strip().upper(),
                        request.form.get('unit_type_id'),
                        new_parent,
                        bool(request.form.get('is_legal_entity')),
                        (request.form.get('country') or '').strip() or None,
                        request.form.get('head_user_id') or None,
                        unit_id))
            flash(gettext('Unit updated.'), 'success')
        except Exception as e:
            # the trigger raises on cycles, which is the case worth naming
            flash('Could not update: ' + ('that move would create a loop in the tree.'
                  if 'cycle' in str(e).lower() else str(e)[:160]), 'danger')
    return redirect(url_for('admin.org_tree'))


@admin_bp.route('/organisation/scope/<int:user_id>', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def org_user_scope(user_id):
    """Grant a user visibility over parts of the tree.

    Deliberately separate from the module permission screen: perm_* decides
    which modules exist for a user, this decides which records inside them.
    Mixing the two on one screen is how people grant more than they meant to.
    """
    from database.db import execute_db, query_db
    from services import org_service

    if request.method == 'POST':
        if request.form.get('action') == 'delete':
            execute_db("DELETE FROM user_org_scope_rules WHERE id=%s AND user_id=%s",
                       (request.form.get('rule_id'), user_id))
            flash(gettext('Scope rule removed.'), 'info')
        else:
            rt = request.form.get('rule_type')
            execute_db("""INSERT INTO user_org_scope_rules
                            (user_id, rule_type, org_unit_id, root_unit_id,
                             match_code, match_type_id, is_exclusion, granted_by)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                       (user_id, rt,
                        request.form.get('org_unit_id') or None,
                        request.form.get('root_unit_id') or None,
                        (request.form.get('match_code') or '').strip().upper() or None,
                        request.form.get('match_type_id') or None,
                        bool(request.form.get('is_exclusion')),
                        current_user.id))
            flash(gettext('Scope rule added.'), 'success')
        return redirect(url_for('admin.org_user_scope', user_id=user_id))

    user = query_db("SELECT * FROM users WHERE id=%s", (user_id,), one=True)
    if not user:
        flash(gettext('User not found.'), 'danger')
        return redirect(url_for('admin.list_users'))

    rules = query_db("""SELECT r.*, o.name_en AS unit_name, ro.name_en AS root_name,
                               t.name_en AS type_name
                        FROM user_org_scope_rules r
                        LEFT JOIN org_units o  ON o.id  = r.org_unit_id
                        LEFT JOIN org_units ro ON ro.id = r.root_unit_id
                        LEFT JOIN org_unit_types t ON t.id = r.match_type_id
                        WHERE r.user_id=%s ORDER BY r.is_exclusion, r.id""", (user_id,))
    resolved = org_service.resolve_scope(user_id, use_cache=False)
    return render_template('admin/organisation/scope.html',
                           user=user, rules=rules,
                           units=org_service.get_tree(),
                           unit_types=org_service.get_unit_types(),
                           summary=org_service.describe_scope(user_id),
                           resolved_count=('all' if resolved is None else len(resolved)))


# =============================================================================
# Document types and approval workflows (Phase 3)
# =============================================================================

@admin_bp.route('/document-types', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def document_types():
    from database.db import execute_db, query_db
    from services import document_service as D

    if request.method == 'POST':
        act = request.form.get('action')
        if act == 'create':
            try:
                execute_db("""INSERT INTO document_types
                                (code, name_en, name_ar, description, icon, numbering_prefix,
                                 requires_approval, default_review_months, sort_order, created_by)
                              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                           ((request.form.get('code') or '').strip().upper(),
                            (request.form.get('name_en') or '').strip(),
                            (request.form.get('name_ar') or '').strip() or None,
                            (request.form.get('description') or '').strip() or None,
                            request.form.get('icon') or 'bi bi-file-earmark-text',
                            (request.form.get('numbering_prefix') or '').strip().upper() or None,
                            bool(request.form.get('requires_approval')),
                            int(request.form.get('default_review_months') or 12),
                            int(request.form.get('sort_order') or 999),
                            current_user.id))
                flash(gettext('Document type created.'), 'success')
            except Exception as e:
                flash('Could not create: ' + ('that code already exists.'
                      if 'document_types_code_key' in str(e) else str(e)[:150]), 'danger')

        elif act == 'update':
            execute_db("""UPDATE document_types SET name_en=%s, name_ar=%s, description=%s,
                                 icon=%s, numbering_prefix=%s, requires_approval=%s,
                                 default_review_months=%s, sort_order=%s
                           WHERE id=%s""",
                       ((request.form.get('name_en') or '').strip(),
                        (request.form.get('name_ar') or '').strip() or None,
                        (request.form.get('description') or '').strip() or None,
                        request.form.get('icon'),
                        (request.form.get('numbering_prefix') or '').strip().upper() or None,
                        bool(request.form.get('requires_approval')),
                        int(request.form.get('default_review_months') or 12),
                        int(request.form.get('sort_order') or 999),
                        request.form.get('type_id')))
            flash(gettext('Document type updated.'), 'success')

        elif act == 'toggle':
            execute_db("UPDATE document_types SET is_active = NOT is_active WHERE id=%s",
                       (request.form.get('type_id'),))
            flash(gettext('Document type status changed.'), 'info')

        elif act == 'delete':
            tid = request.form.get('type_id')
            used = dict(query_db("SELECT count(*) AS c FROM policies WHERE document_type_id=%s",
                                 (tid,), one=True))['c']
            if used:
                # Deleting a type in use would orphan its documents and, worse,
                # detach them from their approval history.
                flash(f'{used} document(s) use this type. Deactivate it instead — '
                      f'it will disappear from the picker but existing documents keep working.',
                      'danger')
            else:
                execute_db("DELETE FROM document_types WHERE id=%s", (tid,))
                flash(gettext('Document type deleted.'), 'success')

        return redirect(url_for('admin.document_types'))

    types = query_db("""SELECT dt.*,
                          (SELECT count(*) FROM policies p WHERE p.document_type_id=dt.id) AS doc_count,
                          (SELECT count(*) FROM approval_workflows w WHERE w.document_type_id=dt.id) AS wf_count
                        FROM document_types dt ORDER BY dt.sort_order, dt.name_en""")
    return render_template('admin/documents/types.html', types=types)


@admin_bp.route('/document-types/<int:type_id>/workflow', methods=['GET', 'POST'])
@login_required
@permission_required('config')
def document_workflow(type_id):
    """Edit the approval chain for one document type.

    Stages can be reordered, disabled or made optional. Disabling is preferred
    over deleting: a stage that has been used sits in the history of every
    document that passed through it.
    """
    from database.db import execute_db, query_db
    from services import document_service as D

    dt = query_db("SELECT * FROM document_types WHERE id=%s", (type_id,), one=True)
    if not dt:
        flash(gettext('Document type not found.'), 'danger')
        return redirect(url_for('admin.document_types'))

    wf = D.get_workflow_for(type_id)
    if not wf:
        execute_db("""INSERT INTO approval_workflows (document_type_id, name, is_default)
                      VALUES (%s,%s,TRUE)""", (type_id, dict(dt)['name_en'] + ' — approval'))
        wf = D.get_workflow_for(type_id)

    if request.method == 'POST':
        act = request.form.get('action')
        if act == 'add_stage':
            nxt = dict(query_db("SELECT COALESCE(MAX(stage_order),0)+1 AS n "
                                "FROM approval_workflow_stages WHERE workflow_id=%s",
                                (wf['id'],), one=True))['n']
            execute_db("""INSERT INTO approval_workflow_stages
                            (workflow_id, stage_order, stage_name, approver_mode,
                             approver_user_id, approver_role, is_mandatory, sla_days)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                       (wf['id'], nxt, (request.form.get('stage_name') or 'Stage').strip(),
                        request.form.get('approver_mode') or 'role',
                        request.form.get('approver_user_id') or None,
                        (request.form.get('approver_role') or '').strip() or None,
                        bool(request.form.get('is_mandatory')),
                        int(request.form.get('sla_days') or 7)))
            flash(gettext('Stage added.'), 'success')

        elif act == 'update_stage':
            execute_db("""UPDATE approval_workflow_stages
                             SET stage_name=%s, approver_mode=%s, approver_user_id=%s,
                                 approver_role=%s, is_mandatory=%s, sla_days=%s
                           WHERE id=%s AND workflow_id=%s""",
                       ((request.form.get('stage_name') or '').strip(),
                        request.form.get('approver_mode'),
                        request.form.get('approver_user_id') or None,
                        (request.form.get('approver_role') or '').strip() or None,
                        bool(request.form.get('is_mandatory')),
                        int(request.form.get('sla_days') or 7),
                        request.form.get('stage_id'), wf['id']))
            flash(gettext('Stage updated.'), 'success')

        elif act == 'toggle_stage':
            execute_db("UPDATE approval_workflow_stages SET is_enabled = NOT is_enabled "
                       "WHERE id=%s AND workflow_id=%s", (request.form.get('stage_id'), wf['id']))
            flash(gettext('Stage enabled/disabled.'), 'info')

        elif act == 'delete_stage':
            execute_db("DELETE FROM approval_workflow_stages WHERE id=%s AND workflow_id=%s",
                       (request.form.get('stage_id'), wf['id']))
            # close the gap so ordering stays 1..n
            rows = query_db("SELECT id FROM approval_workflow_stages WHERE workflow_id=%s "
                            "ORDER BY stage_order", (wf['id'],))
            for i, r in enumerate(rows, start=1):
                execute_db("UPDATE approval_workflow_stages SET stage_order=%s WHERE id=%s",
                           (i, dict(r)['id']))
            flash(gettext('Stage removed.'), 'info')

        elif act in ('move_up', 'move_down'):
            sid = request.form.get('stage_id')
            cur = query_db("SELECT stage_order FROM approval_workflow_stages WHERE id=%s",
                           (sid,), one=True)
            if cur:
                o = dict(cur)['stage_order']
                other_o = o - 1 if act == 'move_up' else o + 1
                other = query_db("SELECT id FROM approval_workflow_stages "
                                 "WHERE workflow_id=%s AND stage_order=%s",
                                 (wf['id'], other_o), one=True)
                if other:
                    execute_db("UPDATE approval_workflow_stages SET stage_order=%s WHERE id=%s",
                               (other_o, sid))
                    execute_db("UPDATE approval_workflow_stages SET stage_order=%s WHERE id=%s",
                               (o, dict(other)['id']))
        return redirect(url_for('admin.document_workflow', type_id=type_id))

    return render_template('admin/documents/workflow.html',
                           dt=dt, wf=wf,
                           stages=D.get_stages(wf['id'], enabled_only=False),
                           users=query_db("SELECT id, first_name, last_name, email, role "
                                          "FROM users WHERE is_active=1 ORDER BY first_name"),
                           roles=['admin', 'compliance_manager', 'manager', 'employee'])


# =============================================================================
# MFA administration
#
# Self-service enrolment already existed; an administrator could not require it
# of a given person, lift it, or clear a lost enrolment. Every action here is
# recorded — resetting somebody's second factor is a security event.
# =============================================================================

@admin_bp.route('/users/<int:user_id>/mfa', methods=['POST'])
@login_required
@admin_required
def user_mfa(user_id):
    from database.db import execute_db, query_db

    target = query_db("SELECT id, email, first_name, last_name, role, mfa_enabled "
                      "FROM users WHERE id=%s", (user_id,), one=True)
    if not target:
        flash(gettext('User not found.'), 'danger')
        return redirect(url_for('admin.list_users'))
    target = dict(target)
    name = f"{target['first_name']} {target['last_name']}".strip() or target['email']
    action = request.form.get('mfa_action')
    reason = (request.form.get('reason') or '').strip()

    if action == 'reset':
        # Clear the enrolment entirely so the person re-enrols from scratch:
        # a lost or compromised authenticator must not stay valid.
        execute_db("""UPDATE users
                         SET mfa_enabled=FALSE, mfa_secret=NULL, mfa_backup_codes=NULL,
                             mfa_enrolled_at=NULL, mfa_last_reset_at=NOW(), mfa_last_reset_by=%s
                       WHERE id=%s""", (current_user.id, user_id))
        flash(f'MFA reset for {name}. They will be asked to enrol again at next login '
              f'if it is required for them.', 'warning')

    elif action == 'require':
        execute_db("UPDATE users SET mfa_required_override=TRUE WHERE id=%s", (user_id,))
        flash(gettext('MFA is now required for %(name)s.', name=name), 'success')

    elif action == 'not_required':
        if target['role'] in ('admin', 'compliance_officer', 'compliance_manager'):
            flash(f'{name} holds a privileged role. Lifting MFA for them is possible, '
                  f'but weakens a control an auditor will look for.', 'warning')
        execute_db("UPDATE users SET mfa_required_override=FALSE WHERE id=%s", (user_id,))
        flash(gettext('MFA is no longer required for %(name)s. They may still enable it themselves.', name=name),
              'info')

    elif action == 'follow_role':
        execute_db("UPDATE users SET mfa_required_override=NULL WHERE id=%s", (user_id,))
        flash(gettext('%(name)s now follows the default rule for their role.', name=name), 'info')

    elif action == 'disable':
        if not reason:
            flash(gettext('Turning off an active second factor needs a reason.'), 'danger')
            return redirect(request.referrer or url_for('admin.list_users'))
        execute_db("UPDATE users SET mfa_enabled=FALSE WHERE id=%s", (user_id,))
        flash(gettext('MFA disabled for %(name)s.', name=name), 'warning')

    else:
        flash(gettext('Unknown MFA action.'), 'danger')
        return redirect(request.referrer or url_for('admin.list_users'))

    execute_db("""INSERT INTO mfa_audit (user_id, action, performed_by, reason, ip_address)
                  VALUES (%s,%s,%s,%s,%s)""",
               (user_id, action, current_user.id, reason or None,
                request.headers.get('X-Forwarded-For', request.remote_addr or '')[:45]))
    return redirect(request.referrer or url_for('admin.edit_user', id=user_id))


@admin_bp.route('/security/mfa')
@login_required
@admin_required
def mfa_overview():
    """Who has a second factor, who is required to, and who is outstanding."""
    from database.db import query_db
    return render_template(
        'admin/security/mfa.html',
        users=query_db("""SELECT id, email, first_name, last_name, role, is_active,
                                 mfa_enabled, mfa_required_override, mfa_enrolled_at,
                                 mfa_last_reset_at
                          FROM users ORDER BY mfa_enabled, role, first_name"""),
        history=query_db("""SELECT m.*,
                                   TRIM(COALESCE(t.first_name,'')||' '||COALESCE(t.last_name,'')) AS target_name,
                                   TRIM(COALESCE(p.first_name,'')||' '||COALESCE(p.last_name,'')) AS actor_name
                            FROM mfa_audit m
                            LEFT JOIN users t ON t.id = m.user_id
                            LEFT JOIN users p ON p.id = m.performed_by
                            ORDER BY m.performed_at DESC LIMIT 30"""))
