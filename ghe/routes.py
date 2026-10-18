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
GHE (Gift, Hospitality & Entertainment) Routes
Handles all GHE-related views and API endpoints.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file
from werkzeug.utils import secure_filename
from datetime import datetime
import os

from models.ghe import GHEDeclaration, GHEApprovalHistory
from models.user import User
from models.audit import AuditLog

# Blueprint definition
ghe_bp = Blueprint('ghe', __name__, url_prefix='/ghe')

# File upload configuration
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx'}
UPLOAD_FOLDER = 'uploads/ghe'  # non-static — not reachable via Flask's unauthenticated /static/ route
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachment(file):
    """Save uploaded file and return relative path."""
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to avoid conflicts
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        
        # Ensure upload directory exists
        upload_path = os.path.join(current_app.root_path, UPLOAD_FOLDER)
        os.makedirs(upload_path, exist_ok=True)
        
        # Save file
        file_path = os.path.join(upload_path, filename)
        file.save(file_path)
        
        # Return relative path for storage
        return f"uploads/ghe/{filename}"
    return None


@ghe_bp.route('/')
@login_required
@permission_required('ghe', level='view')
def list_declarations():
    """
    List all declarations.
    - Admin/Compliance: See all declarations
    - Manager: See team declarations
    - Employee: Redirect to my_declarations
    """
    # Employees go to their own declarations
    if current_user.role == 'employee':
        return redirect(url_for('ghe.my_declarations'))
    
    # Get filter parameters
    filters = {
        'status': request.args.get('status'),
        'ghe_type': request.args.get('ghe_type'),
        'date_from': request.args.get('date_from'),
        'date_to': request.args.get('date_to')
    }
    # Remove empty filters
    filters = {k: v for k, v in filters.items() if v}
    
    # Get declarations based on role
    if current_user.is_compliance_officer() or current_user.is_admin():
        declarations = GHEDeclaration.get_all(filters=filters)
    elif current_user.is_manager():
        # Managers see their team's declarations
        filters['manager_id'] = current_user.id
        declarations = GHEDeclaration.get_all(filters=filters)
    else:
        declarations = []
    
    # Get statistics
    stats = GHEDeclaration.get_statistics()
    
    return render_template('ghe/list.html', 
                         declarations=declarations,
                         stats=stats)


@ghe_bp.route('/my-declarations')
@ghe_bp.route('/declarations')
@login_required
@permission_required('ghe', level='view')
def my_declarations():
    """Show current user's reviewed declarations (approved/rejected/info_requested)."""
    all_declarations = GHEDeclaration.get_by_employee(current_user.id)
    
    # Filter to only show reviewed declarations
    # pending, manager_review are NOT yet reviewed by manager/compliance
    # compliance_review IS reviewed by manager (so maybe show%s User said "reviewed by compliance analyst OR manager")
    # approved, rejected, info_requested are definitely reviewed
    visible_statuses = ['compliance_review', 'approved', 'rejected', 'requires_clarification']
    declarations = [d for d in all_declarations if d.status in visible_statuses or getattr(d, 'auto_approved', False)]
    
    my_stats = GHEDeclaration.get_employee_stats(current_user.id)
    
    return render_template('ghe/my_declarations.html',
                         declarations=declarations,
                         my_stats=my_stats)


@ghe_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('ghe', level='view')
def create_declaration():
    """Submit new GHE declaration."""
    if request.method == 'POST':
        # Get form data
        data = {
            'ghe_type': request.form.get('ghe_type'),
            'direction': request.form.get('direction'),
            'event_date': request.form.get('event_date'),
            'estimated_value_egp': request.form.get('estimated_value_egp'),
            'description': request.form.get('description'),
            'provider_recipient_name': request.form.get('provider_recipient_name'),
            'provider_recipient_company': request.form.get('provider_recipient_company'),
            'business_purpose': request.form.get('business_purpose'),
            'is_government_official': request.form.get('is_government_official'),
            'government_official_details': request.form.get('government_official_details'),
            'government_official_position': request.form.get('government_official_position')
        }
        
        # Validate required fields
        required = ['ghe_type', 'direction', 'event_date', 'estimated_value_egp', 
                   'description', 'provider_recipient_name']
        missing = [f for f in required if not data.get(f)]
        
        if missing:
            flash(f'Please fill in all required fields: {", ".join(missing)}', 'danger')
            return render_template('ghe/create.html', 
                                 today=datetime.now().strftime('%Y-%m-%d'),
                                 data=data)
        
        # Handle file upload
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file.filename:
                attachment_path = save_attachment(file)
                if attachment_path:
                    data['attachment_path'] = attachment_path
                else:
                    flash('Invalid file type. Allowed: PDF, PNG, JPG, DOC, DOCX', 'warning')
        
        try:
            # Create declaration (triggers approval workflow)
            declaration = GHEDeclaration.create(data, current_user.id)
            
            # Notify Manager and Compliance
            from models.notification import Notification
            officers = User.get_all_compliance_officers()
            notify_ids = {o.id for o in officers}
            if declaration.manager_id:
                notify_ids.add(declaration.manager_id)
            
            for uid in notify_ids:
                Notification.create(
                    user_id=uid,
                    title=f"New GHE Declaration",
                    message=f"New GHE Declaration from {current_user.get_full_name()}",
                    link=url_for('ghe.view_declaration', id=declaration.id),
                    n_type='submission'
                )
            
            if declaration.auto_approved:
                flash(f'Declaration {declaration.declaration_number} submitted and auto-approved! (Value below 500 EGP)', 'success')
            elif declaration.status == 'manager_review':
                flash(f'Declaration {declaration.declaration_number} submitted successfully! Awaiting manager approval.', 'success')
            elif declaration.status == 'compliance_review':
                flash(f'Declaration {declaration.declaration_number} submitted successfully! Awaiting compliance approval.', 'success')
            else:
                flash(f'Declaration {declaration.declaration_number} submitted successfully!', 'success')
            
            AuditLog.log(current_user.id, 'GHE Submission', 'GHE', declaration.id, f'Submitted GHE declaration {declaration.declaration_number}', request.remote_addr)
            return redirect(url_for('ghe.view_declaration', id=declaration.id))
            
        except Exception as e:
            flash(f'Error creating declaration: {str(e)}', 'danger')
            return render_template('ghe/create.html', 
                                 today=datetime.now().strftime('%Y-%m-%d'),
                                 data=data)
    
    # GET: Show empty form
    return render_template('ghe/create.html', 
                         today=datetime.now().strftime('%Y-%m-%d'),
                         data={})


@ghe_bp.route('/<int:id>')
@login_required
@permission_required('ghe', level='view')
def view_declaration(id):
    """View single declaration with approval history."""
    declaration = GHEDeclaration.get_by_id(id)
    
    if not declaration:
        flash('Declaration not found.', 'danger')
        return redirect(url_for('ghe.list_declarations'))
    
    # Check permissions
    can_view = (
        declaration.employee_id == current_user.id or
        current_user.is_compliance_officer() or
        current_user.is_admin() or
        declaration.manager_id == current_user.id
    )
    
    if not can_view:
        flash('You do not have permission to view this declaration.', 'danger')
        return redirect(url_for('ghe.my_declarations'))
    
    # Get approval history
    approval_history = GHEApprovalHistory.get_history(id)
    
    # Determine if current user can approve
    can_approve = False
    if declaration.status == 'manager_review' and current_user.is_manager():
        # Check if user is the manager or any manager when original manager not assigned
        if declaration.manager_id == current_user.id or declaration.manager_id is None:
            can_approve = True
    elif declaration.status == 'compliance_review' and current_user.is_compliance_officer():
        can_approve = True
    
    return render_template('ghe/detail.html',
                         declaration=declaration,
                         approval_history=approval_history,
                         can_approve=can_approve)


@ghe_bp.route('/<int:id>/attachment')
@login_required
@permission_required('ghe', level='view')
def download_attachment(id):
    """Serve a GHE declaration's attachment — same ownership guard as view_declaration."""
    declaration = GHEDeclaration.get_by_id(id)
    if not declaration or not declaration.attachment_path:
        flash('Attachment not found.', 'danger')
        return redirect(url_for('ghe.list_declarations'))

    can_view = (
        declaration.employee_id == current_user.id or
        current_user.is_compliance_officer() or
        current_user.is_admin() or
        declaration.manager_id == current_user.id
    )
    if not can_view:
        flash('You do not have permission to view this declaration.', 'danger')
        return redirect(url_for('ghe.my_declarations'))

    return serve_uploaded_file(declaration.attachment_path)


@ghe_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('ghe', level='view')
def edit_declaration(id):
    """Edit declaration (only if pending and user is owner)."""
    declaration = GHEDeclaration.get_by_id(id)
    
    if not declaration:
        flash('Declaration not found.', 'danger')
        return redirect(url_for('ghe.my_declarations'))
    
    # Check if user is owner and status allows editing
    if declaration.employee_id != current_user.id:
        flash('You can only edit your own declarations.', 'danger')
        return redirect(url_for('ghe.my_declarations'))
    
    if declaration.status not in ['pending', 'manager_review']:
        flash('This declaration can no longer be edited.', 'warning')
        return redirect(url_for('ghe.view_declaration', id=id))
    
    if request.method == 'POST':
        data = {
            'ghe_type': request.form.get('ghe_type'),
            'direction': request.form.get('direction'),
            'event_date': request.form.get('event_date'),
            'estimated_value_egp': request.form.get('estimated_value_egp'),
            'description': request.form.get('description'),
            'provider_recipient_name': request.form.get('provider_recipient_name'),
            'provider_recipient_company': request.form.get('provider_recipient_company'),
            'business_purpose': request.form.get('business_purpose'),
            'is_government_official': request.form.get('is_government_official'),
            'government_official_details': request.form.get('government_official_details')
        }
        
        if declaration.update(data, current_user.id):
            flash('Declaration updated successfully!', 'success')
            return redirect(url_for('ghe.view_declaration', id=id))
        else:
            flash('Error updating declaration.', 'danger')
    
    return render_template('ghe/edit.html',
                         declaration=declaration,
                         today=datetime.now().strftime('%Y-%m-%d'))


@ghe_bp.route('/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('ghe', level='view')
def approve_declaration(id):
    """Approve declaration (manager or compliance)."""
    declaration = GHEDeclaration.get_by_id(id)
    
    if not declaration:
        flash('Declaration not found.', 'danger')
        return redirect(url_for('ghe.pending_approval'))
    
    # Determine approver role and check permissions
    approver_role = None
    if declaration.status == 'manager_review' and current_user.is_manager():
        approver_role = 'manager'
    elif declaration.status == 'compliance_review' and current_user.is_compliance_officer():
        approver_role = 'compliance_officer'
    
    if not approver_role:
        flash('You do not have permission to approve this declaration.', 'danger')
        return redirect(url_for('ghe.view_declaration', id=id))
    
    comments = request.form.get('comments')
    
    if declaration.approve(current_user.id, approver_role, comments):
        AuditLog.log(current_user.id, 'GHE Approval', 'GHE', id, f'Approved GHE declaration (Role: {approver_role})', request.remote_addr)
        # Send email notification for public submissions
        if declaration.is_public_submission and declaration.submitter_email and declaration.status == 'approved':
            try:
                from services.email_service import email_service
                email_service.send_approval_notification(declaration.submitter_email, {
                    'declaration_number': declaration.declaration_number,
                    'ghe_type': declaration.ghe_type,
                    'estimated_value_egp': declaration.estimated_value_egp,
                    'submitter_name': declaration.submitter_name,
                    'compliance_comments': comments,
                    'manager_comments': declaration.manager_comments
                })
            except Exception as e:
                current_app.logger.error(f"GHE email notification failed: {e}")
        
        if declaration.status == 'approved':
            flash(f'Declaration {declaration.declaration_number} has been approved!', 'success')
        else:
            flash(f'Declaration {declaration.declaration_number} escalated to compliance review.', 'info')
    else:
        flash('Error approving declaration.', 'danger')
    
    return redirect(url_for('ghe.pending_approval'))


@ghe_bp.route('/<int:id>/reject', methods=['POST'])
@login_required
@permission_required('ghe', level='view')
def reject_declaration(id):
    """Reject declaration (manager or compliance)."""
    declaration = GHEDeclaration.get_by_id(id)
    
    if not declaration:
        flash('Declaration not found.', 'danger')
        return redirect(url_for('ghe.pending_approval'))
    
    # Determine approver role and check permissions
    approver_role = None
    if declaration.status == 'manager_review' and current_user.is_manager():
        approver_role = 'manager'
    elif declaration.status == 'compliance_review' and current_user.is_compliance_officer():
        approver_role = 'compliance_officer'
    
    if not approver_role:
        flash('You do not have permission to reject this declaration.', 'danger')
        return redirect(url_for('ghe.view_declaration', id=id))
    
    comments = request.form.get('comments')
    
    if not comments:
        flash('Rejection reason is required.', 'danger')
        return redirect(url_for('ghe.view_declaration', id=id))
    
    if declaration.reject(current_user.id, approver_role, comments):
        AuditLog.log(current_user.id, 'GHE Rejection', 'GHE', id, f'Rejected GHE declaration {declaration.declaration_number} (Role: {approver_role})', request.remote_addr)
        # Send email notification for public submissions
        if declaration.is_public_submission and declaration.submitter_email:
            try:
                from services.email_service import email_service
                email_service.send_rejection_notification(declaration.submitter_email, {
                    'declaration_number': declaration.declaration_number,
                    'ghe_type': declaration.ghe_type,
                    'estimated_value_egp': declaration.estimated_value_egp,
                    'submitter_name': declaration.submitter_name
                }, comments)
            except Exception as e:
                current_app.logger.error(f"GHE email notification failed: {e}")
        
        flash(f'Declaration {declaration.declaration_number} has been rejected.', 'warning')
    else:
        flash('Error rejecting declaration.', 'danger')
    
    return redirect(url_for('ghe.pending_approval'))


@ghe_bp.route('/pending-approval')
@login_required
@permission_required('ghe', level='view')
def pending_approval():
    """Show declarations pending current user's approval."""
    if not (current_user.is_manager() or current_user.is_compliance_officer()):
        flash('You do not have approval permissions.', 'warning')
        return redirect(url_for('ghe.my_declarations'))
    
    declarations = []
    
    # Managers see manager_review items for their team
    if current_user.is_manager():
        manager_pending = GHEDeclaration.get_pending_for_manager(current_user.id)
        declarations.extend(manager_pending)
    
    # Compliance officers see all compliance_review items
    if current_user.is_compliance_officer():
        compliance_pending = GHEDeclaration.get_pending_for_compliance()
        declarations.extend(compliance_pending)
    
    # Remove duplicates (if user is both manager and compliance)
    seen_ids = set()
    unique_declarations = []
    for d in declarations:
        if d.id not in seen_ids:
            seen_ids.add(d.id)
            unique_declarations.append(d)
    
    return render_template('ghe/pending_approval.html',
                         declarations=unique_declarations)


@ghe_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('ghe', level='view')
def delete_declaration(id):
    """Delete declaration (only if pending and user is owner)."""
    declaration = GHEDeclaration.get_by_id(id)
    
    if not declaration:
        flash('Declaration not found.', 'danger')
        return redirect(url_for('ghe.my_declarations'))
    
    if declaration.employee_id != current_user.id:
        flash('You can only delete your own declarations.', 'danger')
        return redirect(url_for('ghe.my_declarations'))
    
    if declaration.delete():
        flash('Declaration deleted successfully.', 'success')
    else:
        flash('Cannot delete this declaration. It may no longer be in pending status.', 'warning')
    
    return redirect(url_for('ghe.my_declarations'))


@ghe_bp.route('/<int:id>/request-info', methods=['POST'])
@login_required
@permission_required('ghe', level='view')
def request_more_info(id):
    """Request more information from the submitter."""
    declaration = GHEDeclaration.get_by_id(id)
    
    if not declaration:
        flash('Declaration not found.', 'danger')
        return redirect(url_for('ghe.pending_approval'))
    
    # Check permissions - only managers/compliance can request info
    if not (current_user.is_manager() or current_user.is_compliance_officer()):
        flash('You do not have permission to request information.', 'danger')
        return redirect(url_for('ghe.view_declaration', id=id))
    
    questions = request.form.get('questions', '').strip()
    
    if not questions:
        flash('Please specify what information you need.', 'danger')
        return redirect(url_for('ghe.view_declaration', id=id))
    
    try:
        # Use model method
        if declaration.request_clarification(current_user.id, 'compliance_officer' if current_user.is_compliance_officer() else 'manager', questions):
             # Send email notification for public submissions
            if declaration.is_public_submission and declaration.submitter_email:
                try:
                    from services.email_service import email_service
                    email_service.send_info_request_notification(declaration.submitter_email, {
                        'declaration_number': declaration.declaration_number,
                        'tracking_id': declaration.tracking_id,
                        'submitter_name': declaration.submitter_name
                    }, questions)
                except Exception as e:
                    current_app.logger.error(f"GHE email notification failed: {e}")
            
            flash(f'Information request sent for {declaration.declaration_number}.', 'info')
        else:
            flash(f'Error requesting information.', 'danger')

    except Exception as e:
        flash(f'Error requesting information: {str(e)}', 'danger')
    
    return redirect(url_for('ghe.pending_approval'))


@ghe_bp.route('/api/statistics')
@login_required
@permission_required('ghe', level='view')
def api_statistics():
    """API endpoint for dashboard statistics."""
    if current_user.is_compliance_officer() or current_user.is_admin():
        stats = GHEDeclaration.get_statistics()
    else:
        stats = GHEDeclaration.get_employee_stats(current_user.id)
    
    return jsonify(stats)
