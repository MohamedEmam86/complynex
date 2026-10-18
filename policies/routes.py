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

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app, abort
from flask_login import login_required, current_user
from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file
from flask_babel import gettext as _
from werkzeug.utils import secure_filename
import os
from models.policy import Policy, PolicyCategory, PolicyAcknowledgment, PolicyAttachment, PolicyReviewWorkflow
from models.user import User
from models.audit import AuditLog
from datetime import datetime
from database.db import get_db
import csv
import io
from flask import Response
from utils.html_sanitizer import sanitize_html

policies_bp = Blueprint('policies', __name__, url_prefix='/policies')
UPLOAD_FOLDER = 'uploads/policies'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _policy_document_accessible(user, policy):
    """Whether `user` may view/download `policy`'s attachment(s). Compliance
    staff use the normal module permission; portal employees have no
    'policies' module permission at all, so this also mirrors the visibility
    rule portal.policy_list's can_see() uses to decide what to show them in
    the first place — keep both in sync if that rule ever changes."""
    if user.is_admin() or user.can_view('policies'):
        return True
    if policy.is_public:
        return True
    if policy.department_id and user.has_department_access(policy.department_id):
        return True
    if not policy.department_id and policy.owner_function:
        of = policy.owner_function.upper()
        try:
            from models.department import Department
            for dept_id in user.get_accessible_departments():
                d = Department.get_by_id(dept_id)
                if d and d.code.upper() in of:
                    return True
        except Exception:
            pass
    return False

@policies_bp.route('/')
@policies_bp.route('/list')
@login_required
@permission_required('policies')
def list_policies():
    """List policies - different views for different roles"""
    categories = PolicyCategory.get_all()
    
    # Get pending count for current user
    pending_policies = Policy.get_pending_acknowledgment(current_user.id)
    pending_count = len(pending_policies)
    # RBAC: Filter policies
    db_policies = Policy.get_all()
    
    # 1. Admin: See ALL
    # 2. Manager: See Global + Their Department (Internal & Public)
    # 3. Employee: See Global Public + Their Department (Internal & Public)
    
    if current_user.is_admin():
        filtered_policies = db_policies
    else:
        # Get user's accessible department codes e.g. "Operations (OPS)" -> "OPS"
        user_dept_codes = []
        user_dept_names = []
        try:
            from models.department import Department
            for dept_id in current_user.get_accessible_departments():
                d = Department.get_by_id(dept_id)
                if d:
                    user_dept_codes.append(d.code.upper())
                    user_dept_names.append(d.name.lower())
        except Exception:
            pass

        def owner_function_matches(p):
            """Check if policy owner_function matches user dept"""
            if not p.owner_function:
                return False
            of = p.owner_function.upper()
            for code in user_dept_codes:
                if code in of:
                    return True
            for name in user_dept_names:
                if name in p.owner_function.lower():
                    return True
            return False

        filtered_policies = []
        for p in db_policies:
            # Public policy: everyone can see
            if p.is_public:
                filtered_policies.append(p)
                continue
            # Internal with department_id: check dept access
            if p.department_id:
                if current_user.has_department_access(p.department_id):
                    filtered_policies.append(p)
                continue
            # Internal with no department_id: check owner_function or compliance role
            if current_user.is_compliance_officer():
                filtered_policies.append(p)
                continue
            if owner_function_matches(p):
                filtered_policies.append(p)
        
    policies = filtered_policies
    
    return render_template('policies/list.html', 
                         policies=policies, 
                         categories=categories,
                         pending_count=pending_count)

@policies_bp.route('/categories')
@login_required
@permission_required('policies')
def categories():
    """List policy categories with policy counts"""
    # Admin sees all, Manager/Employee sees Global + Own Depts
    # Pass None to get_all to get potentially everything, then filter in memory
    # This is less efficient but cleaner than modifying get_all signature for now
    all_categories = PolicyCategory.get_all(department_id=None, include_global=True)
    
    if current_user.is_admin():
        categories = all_categories
    else:
        # Filter: Global (dept_id is None) OR User has access to dept
        categories = [
            c for c in all_categories
            if (c.department_id is None) or current_user.has_department_access(c.department_id)
        ]
    
    # Add policy counts
    db = get_db()
    for cat in categories:
        row = db.execute('SELECT COUNT(*) as count FROM policies WHERE category_id = %s', (cat.id,)).fetchone()
        cat.policy_count = row['count']
    
    return render_template('policies/categories.html', categories=categories)

@policies_bp.route('/category/create', methods=['GET', 'POST'])
@login_required
@permission_required('policies', level='edit')
def create_category():
    """Create a new policy category"""
    
    if request.method == 'POST':
        name_en = request.form.get('name_en')
        name_ar = request.form.get('name_ar')
        icon = request.form.get('icon', 'bi-folder')
        description_en = request.form.get('description_en')
        description_ar = request.form.get('description_ar')
        
        # Determine department (Manager -> Own Dept, Admin -> Optional/None for Global)
        department_id = None
        if current_user.is_manager() and not current_user.is_admin():
            department_id = current_user.department_id
        
        if not name_en:
            flash('English name is required.', 'warning')
            return redirect(url_for('policies.categories'))
            
        PolicyCategory.create(name_en, name_ar, description_en, description_ar, icon, department_id=department_id)
        flash(f'Category "{name_en}" created successfully.', 'success')
        AuditLog.log(current_user.id, f'Created policy category: {name_en}', module='Policies')
        return redirect(url_for('policies.categories'))
        
    return render_template('policies/category_form.html', category=None)

@policies_bp.route('/category/edit/<int:category_id>', methods=['GET', 'POST'])
@login_required
@permission_required('policies', level='edit')
def edit_category(category_id):
    """Edit an existing policy category"""
    
    category = PolicyCategory.get_by_id(category_id)
    if not category:
        flash('Category not found.', 'danger')
        return redirect(url_for('policies.categories'))
        
    if request.method == 'POST':
        name_en = request.form.get('name_en')
        name_ar = request.form.get('name_ar')
        icon = request.form.get('icon', 'bi-folder')
        description_en = request.form.get('description_en')
        description_ar = request.form.get('description_ar')
        
        if not name_en:
            flash('English name is required.', 'warning')
            return redirect(url_for('policies.categories'))
            
        PolicyCategory.update(category_id, name_en, name_ar, description_en, description_ar, icon)
        flash(f'Category "{name_en}" updated successfully.', 'success')
        AuditLog.log(current_user.id, f'Updated policy category: {name_en}', module='Policies')
        return redirect(url_for('policies.categories'))
        
    return render_template('policies/category_form.html', category=category)

@policies_bp.route('/category/delete/<int:category_id>')
@login_required
@permission_required('policies', level='edit')
def delete_category(category_id):
    """Delete a policy category"""
        
    category = PolicyCategory.get_by_id(category_id)
    if not category:
        flash('Category not found.', 'danger')
        return redirect(url_for('policies.categories'))
        
    success, message = PolicyCategory.delete(category_id)
    if success:
        flash(message, 'success')
        AuditLog.log(current_user.id, f'Deleted policy category: {category.name_en}', module='Policies')
    else:
        flash(message, 'danger')
        
    return redirect(url_for('policies.categories'))

@policies_bp.route('/category/<int:category_id>')
@login_required
@permission_required('policies')
def view_category(category_id):
    """View policies in a specific category"""
    category = PolicyCategory.get_by_id(category_id)
    if not category:
        flash('Category not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    
    policies = Policy.get_all(category_id=category_id)
    return render_template('policies/category_detail.html', category=category, policies=policies)

def _render_create_form(categories, departments):
    """Single place that builds the create-form context.

    There were three separate render_template calls for this one form; adding
    the new pickers to only the happy path would have silently dropped them on
    every validation failure.
    """
    from services import document_service as _D, org_service as _O
    return render_template('policies/create.html',
                           categories=categories, users=User.get_all(),
                           departments=departments,
                           document_types=_D.get_document_types(),
                           org_units=_O.get_tree(),
                           org_unit_types=_O.get_unit_types())


@policies_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('policies', level='edit')
def create_policy():
    """Create new policy (compliance only)"""
    # Computed up front (not just at the bottom for the GET path) — the POST
    # validation-failure paths below re-render this same form and need these
    # before request.method == 'POST' even starts, not after it.
    from models.department import Department

    if current_user.is_admin():
        departments = Department.get_all()
        categories = PolicyCategory.get_all()
    else:
        all_depts = Department.get_all()
        departments = [d for d in all_depts if current_user.has_department_access(d.id)]
        all_cats = PolicyCategory.get_all(include_global=True)
        categories = [c for c in all_cats if (c.department_id is None) or current_user.has_department_access(c.department_id)]

    if request.method == 'POST':
        # RBAC Check: Managers can only create for their department
        department_id = request.form.get('department_id')
        
        if not current_user.is_admin():
             # Check if user has access to this department
             if not department_id or not current_user.has_department_access(department_id):
                 flash('You do not have permission to create policies for this department.', 'danger')
                 return redirect(url_for('policies.list_policies'))
        
        is_internal = request.form.get('is_internal') == 'on'
        
        # Handle file upload
        attachment = request.files.get('attachment')
        attachment_path = None
        if attachment and allowed_file(attachment.filename):
            filename = secure_filename(attachment.filename)
            # Add timestamp to avoid collisions
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            
            # Full path for saving
            full_path = os.path.join(current_app.root_path, UPLOAD_FOLDER, filename)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            attachment.save(full_path)
            
            # DB Path: relative to static folder
            attachment_path = f"uploads/policies/{filename}"
        
        # Handle Category (Text Input)
        category_id = request.form.get('category_id')
        if not category_id:
            category_name = request.form.get('category_name')
            if category_name:
                cat = PolicyCategory.get_by_name(category_name)
                if cat:
                    category_id = cat.id
                else:
                    cat = PolicyCategory.create(category_name)
                    category_id = cat.id

        # Extract all form data into variables
        policy_number = request.form.get('policy_number')
        policy_name = request.form.get('policy_name')
        version = request.form.get('version', '1.0')
        effective_date = request.form.get('effective_date')
        review_date = request.form.get('review_date')
        next_review_date = request.form.get('next_review_date')
        owner_function = request.form.get('owner_function')
        owner_id = request.form.get('owner_id')
        description = request.form.get('description')
        # Sanitized 2026-07-24: this rich-text field is rendered with |safe
        # in detail.html/review_policy.html — must never store raw
        # attacker-controlled HTML/JS (stored-XSS audit finding).
        content = sanitize_html(request.form.get('content'))
        regulatory_reference = request.form.get('regulatory_reference')
        cbe_requirement = request.form.get('cbe_requirement')
        status = request.form.get('status', 'draft')
        
        # Handle boolean flags (Radio buttons return '1' or '0', Checkboxes return 'on' or None)
        is_public_val = request.form.get('is_public')
        if is_public_val == '1':
            is_public = 1
        elif is_public_val == '0':
            is_public = 0
        else:
            is_public = 1 if is_public_val == 'on' else 0 # Fallback for checkboxes if any

        is_mandatory = 1 if request.form.get('is_mandatory') == 'on' else 0 # Checkbox still used here
        issuing_date = request.form.get('issuing_date') or datetime.now().date().isoformat()

        # Create policy
        data = {
            'policy_number': policy_number,
            'policy_name': policy_name,
            'category_id': category_id,
            'version': version,
            'effective_date': effective_date,
            'review_date': review_date,
            'next_review_date': next_review_date,
            'owner_function': owner_function,
            'owner_id': owner_id,
            'description': description,
            'content': content,
            'attachment_path': attachment_path,
            'regulatory_reference': regulatory_reference,
            'cbe_requirement': cbe_requirement,
            'status': status,
            'is_public': is_public,
            'is_mandatory': is_mandatory,
            'department_id': department_id,
            'is_internal': 1 if not is_public else 0, # Logic: Public=0 means Internal=1
            'issuing_date': issuing_date,
            'document_type_id': request.form.get('document_type_id') or None,
            'org_unit_id': request.form.get('org_unit_id') or None
        }
        
        # Validate required fields
        if not data.get('policy_name', '').strip():
            flash('Policy Name is required.', 'danger')
            return _render_create_form(categories, departments)
        if not data.get('category_id'):
            flash('Category is required.', 'danger')
            return _render_create_form(categories, departments)

        try:
            policy = Policy.create(data, current_user.id)

            # Policy.create() writes the legacy column set; the Phase 3 columns
            # are applied here so the model does not have to change and older
            # callers keep working unchanged.
            from database.db import execute_db
            from services import document_service as _D
            doc_type_id = data.get('document_type_id')
            org_unit_id = data.get('org_unit_id')
            execute_db("UPDATE policies SET document_type_id=%s, org_unit_id=%s WHERE id=%s",
                       (doc_type_id, org_unit_id, policy.id))

            # Applicability. Falls back to the owning unit rather than to
            # group-wide: defaulting a document to "applies to everyone" when
            # the author simply did not choose is the wrong way to be wrong.
            entries = []
            for raw in request.form.getlist('applicability'):
                if not raw:
                    continue
                kind, _, val = raw.partition(':')
                if kind == 'unit':
                    entries.append({'org_unit_id': int(val), 'include_descendants': True})
                elif kind == 'unit_only':
                    entries.append({'org_unit_id': int(val), 'include_descendants': False})
                elif kind == 'code':
                    entries.append({'match_code': val})
                elif kind == 'type':
                    entries.append({'match_type_id': int(val)})
            for raw in request.form.getlist('applicability_exclude'):
                if raw:
                    entries.append({'org_unit_id': int(raw), 'include_descendants': True,
                                    'is_exclusion': True})
            if not entries and org_unit_id:
                entries = [{'org_unit_id': int(org_unit_id), 'include_descendants': True}]
            if entries:
                _D.set_applicability(policy.id, entries, current_user.id)

            # Approval chain for the chosen type, snapshotted now.
            stages = 0
            if doc_type_id:
                stages = _D.instantiate_workflow(policy.id, int(doc_type_id),
                                                 int(org_unit_id) if org_unit_id else None)

            AuditLog.log(current_user.id, 'Create Policy', 'Policies', policy.id, f'Created policy {policy.policy_name} ({policy.policy_number})', request.remote_addr)
            if stages:
                flash(f'Document created and sent for approval ({stages} stages).', 'success')
            else:
                flash('Policy created successfully.', 'success')
            return redirect(url_for('policies.view_policy', id=policy.id))
        except Exception as e:
            flash(f'Error creating policy: {str(e)}', 'danger')

    from services import document_service as _D, org_service as _O
    return render_template('policies/create.html', categories=categories,
                           users=User.get_all(), departments=departments,
                           document_types=_D.get_document_types(),
                           org_units=_O.get_tree(),
                           org_unit_types=_O.get_unit_types())


@policies_bp.route('/<int:id>/versions')
@login_required
@permission_required('policies')
def version_history(id):
    """View version history of a policy"""
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    
    versions = policy.get_versions()
    return render_template('policies/versions.html', policy=policy, versions=versions)

@policies_bp.route('/compare-versions/<int:v1_id>/<int:v2_id>')
@login_required
@permission_required('policies')
def compare_versions(v1_id, v2_id):
    """Compare two versions of a policy"""
    db = get_db()
    v1 = db.execute('SELECT * FROM policy_versions WHERE id = %s', (v1_id,)).fetchone()
    v2 = db.execute('SELECT * FROM policy_versions WHERE id = %s', (v2_id,)).fetchone()
    
    if not v1 or not v2:
        flash('One or both versions not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    
    return render_template('policies/compare.html', v1=v1, v2=v2)

@policies_bp.route('/<int:id>/submit-approval', methods=['POST'])
@login_required
@permission_required('policies', level='edit')
def submit_for_approval(id):
    """Submit policy for formal approval workflow"""
    
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    
    # Get reviewer from form or fall back to compliance officers / admins
    reviewer_id = request.form.get('reviewer_id')
    if reviewer_id:
        reviewer_id = int(reviewer_id)
        reviewer_user = User.get_by_id(reviewer_id)
    else:
        officers = User.get_all_compliance_officers()
        if not officers:
            # Fall back to admins/managers
            from database.db import get_db as _get_db
            _db = _get_db()
            _row = _db.execute(
                "SELECT id FROM users WHERE role IN ('admin','manager') ORDER BY id LIMIT 1"
            ).fetchone()
            if not _row:
                flash('No approver found. Please assign a user first.', 'danger')
                return redirect(url_for('policies.view_policy', id=id))
            reviewer_id = _row['id']
        else:
            reviewer_id = officers[0].id
        reviewer_user = User.get_by_id(reviewer_id)
    
    # Update status to pending_approval
    policy.update({'status': 'pending_approval'}, current_user.id)
    
    # Create workflow entry (Compliance Review)
    db = get_db()
    db.execute('''
        INSERT INTO policy_review_workflow (policy_id, reviewer_id, stage_name, status)
        VALUES (%s, %s, 'Compliance Review', 'pending')
    ''', (policy.id, reviewer_id)) 
    db.commit()
    
    reviewer_name = reviewer_user.get_full_name() if reviewer_user else f'User #{reviewer_id}'
    flash(f'Policy submitted for approval. Assigned to: {reviewer_name}', 'success')
    return redirect(url_for('policies.view_policy', id=id))

@policies_bp.route('/gap-analysis/export')
@login_required
@permission_required('policies')
def export_gap_analysis():
    """Export gap analysis to CSV"""
    gaps = Policy.get_gap_analysis()
    
    output = io.StringIO()
    # Add BOM for Excel compatibility with Arabic characters
    output.write('\ufeff')
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        _('Required Policy Name'), 
        _('Regulatory Reference'), 
        _('Priority'), 
        _('Status'), 
        _('Implemented Policy')
    ])
    
    for gap in gaps:
        status = _('Missing')
        if gap['policy']:
            status = _('Compliant') if gap['policy'].status == 'published' else _('Draft/Pending')
            
        writer.writerow([
            gap['required'].policy_name_en,
            gap['required'].regulatory_reference or 'CBE Circular 2023',
            _('Mandatory') if gap['required'].is_mandatory else _('Recommended'),
            status,
            gap['policy'].policy_name if gap['policy'] else ''
        ])
        
    output.seek(0)
    
    filename = f"Compliance_Gap_Analysis_{datetime.now().strftime('%Y%m%d')}.csv"
    
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )
@policies_bp.route('/gap-analysis')
@login_required
@permission_required('policies')
def gap_analysis():
    """View policies gap analysis against CBE requirements"""
    
    gaps = Policy.get_gap_analysis()
    return render_template('policies/gap_analysis.html', gaps=gaps)

@policies_bp.route('/gap-analysis/manage', methods=['GET', 'POST'])
@login_required
@permission_required('policies', level='edit')
def manage_gap_requirements():
    """Manage the list of required policies for gap analysis"""
    
    from models.policy import RequiredPolicy
    from models.audit import AuditLog
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            data = {
                'policy_name_en': request.form.get('policy_name_en'),
                'policy_name_ar': request.form.get('policy_name_ar'),
                'regulatory_reference': request.form.get('regulatory_reference'),
                'is_mandatory': request.form.get('is_mandatory') == 'on',
                'description_en': request.form.get('description_en'),
                'description_ar': request.form.get('description_ar')
            }
            new_id = RequiredPolicy.create(data)
            AuditLog.log(current_user.id, 'create', 'policies', new_id, 
                        f"Added required policy: {data['policy_name_en']}", request.remote_addr)
            flash('Required policy added successfully.', 'success')
        elif action == 'delete':
            policy_id = request.form.get('id')
            RequiredPolicy.delete(policy_id)
            AuditLog.log(current_user.id, 'delete', 'policies', policy_id, 
                        "Deleted required policy", request.remote_addr)
            flash('Required policy removed.', 'success')
        elif action == 'update':
            policy_id = request.form.get('id')
            data = {
                'policy_name_en': request.form.get('policy_name_en'),
                'policy_name_ar': request.form.get('policy_name_ar'),
                'regulatory_reference': request.form.get('regulatory_reference'),
                'is_mandatory': request.form.get('is_mandatory') == 'on',
                'description_en': request.form.get('description_en'),
                'description_ar': request.form.get('description_ar')
            }
            RequiredPolicy.update(policy_id, data)
            AuditLog.log(current_user.id, 'update', 'policies', policy_id, 
                        f"Updated required policy: {data['policy_name_en']}", request.remote_addr)
            flash('Required policy updated.', 'success')
            
        return redirect(url_for('policies.manage_gap_requirements'))
    
    requirements = RequiredPolicy.get_all()
    return render_template('policies/manage_gap_requirements.html', requirements=requirements)

@policies_bp.route('/<int:id>')
@login_required
@permission_required('policies')
def view_policy(id):
    """View policy"""
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
        
    # Check if user has acknowledged
    has_acknowledged = PolicyAcknowledgment.has_acknowledged(id, current_user.id)
    
    # Get acknowledgment stats (for compliance)
    acknowledgment_count = policy.get_acknowledgment_count()
    acknowledgment_rate = policy.get_acknowledgment_rate()
    
    # Get all attachments for this policy
    attachments = PolicyAttachment.get_all_for_policy(id)
    
    # Get review workflow history
    from database.db import get_db
    db = get_db()
    reviews = []
    try:
        reviews = db.execute('''
            SELECT rw.*, u.first_name || ' ' || u.last_name as reviewer_name
            FROM policy_review_workflow rw
            LEFT JOIN users u ON rw.reviewer_id = u.id
            WHERE rw.policy_id = %s
            ORDER BY rw.created_at ASC
        ''', (id,)).fetchall()
        reviews = [dict(r) for r in reviews]
    except Exception:
        pass  # Table may not exist yet
    
    # Get approvers list for submit-approval form
    from database.db import get_db as _gdb
    _db = _gdb()
    approvers = _db.execute(
        "SELECT id, first_name, last_name, role FROM users WHERE role IN ('admin','manager','compliance_officer') ORDER BY role, first_name"
    ).fetchall()
    approvers = [dict(a) for a in approvers]

    return render_template('policies/detail.html',
                         policy=policy,
                         has_acknowledged=has_acknowledged,
                         acknowledgment_count=acknowledgment_count,
                         acknowledgment_rate=acknowledgment_rate,
                         attachments=attachments,
                         reviews=reviews,
                         approvers=approvers)

@policies_bp.route('/<int:id>/document')
@login_required
def download_policy_document(id):
    """Serve a policy's main attachment — authenticated + authorized."""
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    if not _policy_document_accessible(current_user, policy):
        abort(403)
    if not policy.attachment_path:
        flash('No document attached to this policy.', 'warning')
        return redirect(url_for('policies.view_policy', id=id))
    return serve_uploaded_file(policy.attachment_path)


@policies_bp.route('/attachment/<int:attachment_id>/download')
@login_required
def download_policy_attachment(attachment_id):
    """Serve one of a policy's additional attachments — same authorization
    as the main document, resolved via the attachment's parent policy."""
    attachment = PolicyAttachment.get_by_id(attachment_id)
    if not attachment:
        abort(404)
    policy = Policy.get_by_id(attachment.policy_id)
    if not policy or not _policy_document_accessible(current_user, policy):
        abort(403)
    return serve_uploaded_file(attachment.file_path, download_name=attachment.filename)


@policies_bp.route('/<int:id>/acknowledge', methods=['POST'])
@login_required
def acknowledge_policy(id):
    """Acknowledge policy"""
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
        
    if policy.status != 'published':
        flash('This policy is not available for acknowledgment.', 'warning')
        return redirect(url_for('policies.list_policies'))
    
    signature = request.form.get('digital_signature')
    if not signature:
        flash('Digital signature is required.', 'danger')
        return redirect(url_for('policies.view_policy', id=id))
        
    ip_address = request.remote_addr
    
    PolicyAcknowledgment.acknowledge(id, current_user.id, ip_address, signature)
    AuditLog.log(current_user.id, 'Policy Acknowledgment', 'Policies', id, f'Acknowledged policy {policy.policy_name}', request.remote_addr)
    
    # Notify Compliance
    from models.notification import Notification
    officers = User.get_all_compliance_officers()
    for officer in officers:
        Notification.create(
            user_id=officer.id,
            title="Policy Acknowledgment",
            message=f"{current_user.get_full_name()} acknowledged policy: {policy.policy_name}",
            link=url_for('policies.view_policy', id=id),
            n_type='policy'
        )
    
    flash('Policy acknowledged successfully.', 'success')
    return redirect(url_for('policies.list_policies'))

@policies_bp.route('/acknowledge-all', methods=['POST'])
@login_required
def acknowledge_all():
    """Acknowledge all pending policies for the current user"""
    pending_policies = Policy.get_pending_acknowledgment(current_user.id)
    policy_ids = [p.id for p in pending_policies]
    
    if not policy_ids:
        flash(_('No pending policies to acknowledge.'), 'info')
        return redirect(url_for('policies.pending_acknowledgment'))
        
    PolicyAcknowledgment.acknowledge_all(policy_ids, current_user.id, request.remote_addr)
    # Log audit for all
    for pid in policy_ids:
        AuditLog.log(current_user.id, 'Policy Acknowledgment', 'Policies', pid, f'Acknowledged policy {pid} (Batch)', request.remote_addr)
        
    flash(_('All pending policies have been acknowledged.'), 'success')
    return redirect(url_for('policies.list_policies'))

@policies_bp.route('/acknowledgment-dashboard')
@login_required
@permission_required('policies')
def acknowledgment_dashboard():
    """Admin dashboard for tracking policy acknowledgments"""
    stats = Policy.get_overall_stats()
    
    # Get stats per mandatory policy
    db = get_db()
    policies = db.execute('''
        SELECT p.*, c.name_en as category_name_en,
               (SELECT COUNT(*) FROM policy_acknowledgments WHERE policy_id = p.id) as ack_count
        FROM policies p
        LEFT JOIN policy_categories c ON p.category_id = c.id
        WHERE p.status = 'published'
        ORDER BY p.is_mandatory DESC, ack_count ASC
    ''').fetchall()
    
    # Get departments stats
    dept_stats = db.execute('''
        SELECT u.department, COUNT(a.id) as ack_count, COUNT(DISTINCT u.id) as user_count
        FROM users u
        LEFT JOIN policy_acknowledgments a ON u.id = a.employee_id
        WHERE u.role != 'admin' AND u.is_active = 1
        GROUP BY u.department
    ''').fetchall()
    
    return render_template('policies/ack_dashboard.html',
                         stats=stats,
                         policies=policies,
                         dept_stats=dept_stats)

@policies_bp.route('/<int:id>/acknowledgments')
@login_required
@permission_required('policies')
def policy_acknowledgments(id):
    """Who has (and hasn't) acknowledged a specific policy — compliance-officer view."""
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.acknowledgment_dashboard'))

    acknowledged = PolicyAcknowledgment.get_acknowledgments(id)
    pending = policy.get_pending_employees()

    return render_template('policies/policy_acknowledgments.html',
                         policy=policy,
                         acknowledged=acknowledged,
                         pending=pending)

@policies_bp.route('/pending-acknowledgment')
@login_required
@permission_required('policies')
def pending_acknowledgment():
    """Show policies pending employee acknowledgment"""
    policies = Policy.get_pending_acknowledgment(current_user.id)
    return render_template('policies/pending.html', policies=policies)



@policies_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('policies', level='edit')
def edit_policy(id):
    """Edit policy (compliance only)"""
    
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    
    if request.method == 'POST':
        # Handle file upload
        attachment = request.files.get('attachment')
        attachment_path = policy.attachment_path
        if attachment and allowed_file(attachment.filename):
            filename = secure_filename(attachment.filename)
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            
            # Full path for saving
            full_path = os.path.join(current_app.root_path, UPLOAD_FOLDER, filename)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            attachment.save(full_path)
            
            # DB Path: relative to static folder
            attachment_path = f"uploads/policies/{filename}"
            
        # Update policy
        # Update policy
        data = {
            'policy_number': request.form.get('policy_number'),
            'policy_name': request.form.get('policy_name'),
            'category_id': request.form.get('category_id'),
            'version': request.form.get('version_number', policy.version),
            'effective_date': request.form.get('effective_date'),
            'review_date': request.form.get('review_date'),
            'next_review_date': request.form.get('next_review_date'),
            'department_id': request.form.get('department_id') if (current_user.is_admin() or current_user.has_department_access(request.form.get('department_id'))) else policy.department_id,
            'is_internal': 0 if request.form.get('is_public') == '1' else 1, # Radio returns '1' or '0'
            'is_public': 1 if request.form.get('is_public') == '1' else 0,   # Redundant with is_internal but safe to keep
            'is_mandatory': 1 if request.form.get('is_mandatory') == 'on' else 0,
            'owner_function': request.form.get('owner_function') or policy.owner_function,
            'description': request.form.get('description'),
            # Sanitized 2026-07-24 — see the matching comment in create_policy() above.
            'content': sanitize_html(request.form.get('content')),
            'attachment_path': attachment_path,
            'regulatory_reference': request.form.get('regulatory_reference'),
            'cbe_requirement': request.form.get('cbe_requirement'),
            'status': request.form.get('status', policy.status),

            'issuing_date': request.form.get('issuing_date') or policy.issuing_date,
            'approval_cycle': request.form.get('approval_cycle')
        }
        
        # If status changed to published, we might want to do something, but the publish method also exists
        
        # Track changes for audit log
        changes = []
        if data.get('policy_name') and data['policy_name'] != policy.policy_name:
            changes.append(f"Name: '{policy.policy_name}'→'{data['policy_name']}'")
        if data.get('status') and data['status'] != policy.status:
            changes.append(f"Status: {policy.status}→{data['status']}")
        if data.get('owner_function') and data['owner_function'] != policy.owner_function:
            changes.append(f"Owner: {policy.owner_function}→{data['owner_function']}")
        change_detail = '; '.join(changes) if changes else 'Metadata updated'

        policy.update(data, current_user.id)
        AuditLog.log(current_user.id, 'Update Policy', 'Policies', id, f'Updated policy {policy.policy_name}: {change_detail}', request.remote_addr)
        flash('Policy updated successfully.', 'success')
        return redirect(url_for('policies.view_policy', id=id))

    # Filter categories for dropdown
    from models.department import Department
    all_departments = Department.get_all()
    dept_id = current_user.department_id if current_user.is_manager() and not current_user.is_admin() else None
    categories = PolicyCategory.get_all(department_id=dept_id)
    
    from models.department import Department
    if current_user.is_admin():
        departments = Department.get_all()
    else:
        all_depts = Department.get_all()
        departments = [d for d in all_depts if current_user.has_department_access(d.id)]

    return render_template('policies/edit.html', policy=policy, categories=categories, users=User.get_all(), departments=departments, attachments=PolicyAttachment.get_all_for_policy(id))

@policies_bp.route('/<int:id>/upload-attachment', methods=['POST'])
@login_required
@permission_required('policies', level='edit')
def upload_attachment(id):
    """Upload additional attachments to a policy"""
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    
    files = request.files.getlist('attachments')
    if not files:
        flash('No files selected.', 'warning')
        return redirect(url_for('policies.edit_policy', id=id))
    
    uploaded = 0
    for f in files:
        if f and f.filename and allowed_file(f.filename):
            filename = secure_filename(f.filename)
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            full_path = os.path.join(current_app.root_path, UPLOAD_FOLDER, filename)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            f.save(full_path)
            file_size = os.path.getsize(full_path)
            file_path = f"uploads/policies/{filename}"
            PolicyAttachment.create(id, f.filename, file_path, file_size, current_user.id)
            uploaded += 1
    
    if uploaded:
        AuditLog.log(current_user.id, 'Upload Attachments', 'Policies', id, f'Uploaded {uploaded} attachment(s)', request.remote_addr)
        flash(f'{uploaded} attachment(s) uploaded successfully.', 'success')
    else:
        flash('No valid files were uploaded. Allowed types: PDF, DOC, DOCX.', 'warning')
    
    return redirect(url_for('policies.edit_policy', id=id))

@policies_bp.route('/attachment/<int:attachment_id>/delete', methods=['POST'])
@login_required
@permission_required('policies', level='edit')
def delete_attachment(attachment_id):
    """Delete a policy attachment"""
    attachment = PolicyAttachment.get_by_id(attachment_id)
    if not attachment:
        flash('Attachment not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    
    policy_id = attachment.policy_id
    result = PolicyAttachment.delete(attachment_id)
    
    # Try to delete the file from disk
    if result and result.get('file_path'):
        try:
            full_path = os.path.join('static', result['file_path'])
            if os.path.exists(full_path):
                os.remove(full_path)
        except Exception:
            pass
    
    AuditLog.log(current_user.id, 'Delete Attachment', 'Policies', policy_id, f'Deleted attachment {attachment.filename}', request.remote_addr)
    flash('Attachment deleted successfully.', 'success')
    return redirect(url_for('policies.edit_policy', id=policy_id))

@policies_bp.route('/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('policies', level='edit')
def approve_policy(id):
    """Approve policy (compliance only)"""
    
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
        
    policy.approve(current_user.id)
    AuditLog.log(current_user.id, 'Approve Policy', 'Policies', id, f'Approved policy {policy.policy_name}', request.remote_addr)
    
    flash('Policy approved successfully.', 'success')
    return redirect(url_for('policies.view_policy', id=id))

@policies_bp.route('/<int:id>/publish', methods=['POST'])
@login_required
@permission_required('policies', level='edit')
def publish_policy(id):
    """Publish policy (compliance only)"""
    
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
        
    policy.publish()
    AuditLog.log(current_user.id, 'Publish Policy', 'Policies', id, f'Published policy {policy.policy_name}', request.remote_addr)
    
    flash('Policy published. Employees will be notified.', 'success')
    return redirect(url_for('policies.list_policies'))

@policies_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@permission_required('policies', level='edit')
def archive_policy(id):
    """Archive policy (compliance only)"""
    
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
        
    policy.archive()
    AuditLog.log(current_user.id, 'Archive Policy', 'Policies', id, f'Archived policy {policy.policy_name}', request.remote_addr)
    
    flash('Policy archived successfully.', 'success')
    return redirect(url_for('policies.list_policies'))

@policies_bp.route('/review/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('policies')
def review_policy(id):
    """Review policy and submit decision"""
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
    
    if request.method == 'POST':
        status = request.form.get('status')
        comments = request.form.get('comments')
        
        policy.submit_review(current_user.id, status, comments)
        AuditLog.log(current_user.id, 'Policy Review Decision', 'Policies', id, f'Submitted {status} for policy {policy.policy_name}', request.remote_addr)
        
        flash(f'Review submitted: {status}', 'success')
        return redirect(url_for('policies.my_reviews'))
        
    reviews = policy.get_reviews()
    return render_template('policies/review_policy.html', policy=policy, reviews=reviews)

@policies_bp.route('/workflow/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('policies', level='edit')
def workflow_management(id):
    """Manage the review stages for a policy (Compliance Officer only)"""
        
    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('policies.list_policies'))
        
    if request.method == 'POST':
        reviewer_id = request.form.get('reviewer_id')
        stage_name = request.form.get('stage_name')
        
        policy.add_review_stage(reviewer_id, stage_name)
        flash('Review stage added successfully.', 'success')
        return redirect(url_for('policies.workflow_management', id=id))
        
    reviews = policy.get_reviews()
    users = User.get_all()
    return render_template('policies/workflow_management.html', policy=policy, reviews=reviews, users=users)

@policies_bp.route('/my-reviews')
@login_required
@permission_required('policies')
def my_reviews():
    """List pending reviews for the current user"""
    pending_reviews = PolicyReviewWorkflow.get_pending_for_user(current_user.id)
    return render_template('policies/my_reviews.html', reviews=pending_reviews)
