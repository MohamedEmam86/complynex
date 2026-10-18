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
COBEC (Code of Business Ethics & Conduct) Routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.decorators import permission_required
from models.cobec import COBECDeclaration
from models.audit import AuditLog
from models.user import User
from datetime import datetime

cobec_bp = Blueprint('cobec', __name__, url_prefix='/cobec')

@cobec_bp.route('/declare', methods=['GET', 'POST'])
@login_required
@permission_required('cobec', level='edit')
def declare():
    """Submit COBEC declaration"""
    year = datetime.now().year
    
    # Check if already declared this year
    existing = COBECDeclaration.get_by_employee_year(current_user.id, year)
    if existing:
        flash('You have already submitted your Code of Business Ethics & Conduct declaration for this year.', 'info')
        return redirect(url_for('cobec.view_declaration', id=existing.id))
    
    if request.method == 'POST':
        try:
            data = request.form.to_dict()
            declaration_id = COBECDeclaration.create(data, current_user.id)
            AuditLog.log(current_user.id, 'COBEC Submission', 'COBEC', declaration_id, f'Submitted annual COBEC declaration for {year}', request.remote_addr)
            
            # Notify Compliance
            from models.notification import Notification
            officers = User.get_all_compliance_officers()
            for officer in officers:
                Notification.create(
                    user_id=officer.id,
                    title=f"New COBEC Declaration",
                    message=f"New COBEC Declaration from {current_user.get_full_name()}",
                    link=url_for('cobec.view_declaration', id=declaration_id),
                    n_type='submission'
                )
            
            flash('Declaration submitted successfully. Thank you for your commitment to ethical conduct.', 'success')
            return redirect(url_for('cobec.view_declaration', id=declaration_id))
        except Exception as e:
            flash(f'Error submitting declaration: {str(e)}', 'danger')
    
    return render_template('cobec/declare.html', year=year)

@cobec_bp.route('/my-declarations')
@login_required
@permission_required('cobec', level='view')
def my_declarations():
    """View user's COBEC declarations"""
    declarations = COBECDeclaration.get_by_employee(current_user.id)
    current_year = datetime.now().year
    
    # Check if current year declaration exists
    current_declared = any(d.declaration_year == current_year for d in declarations)
    
    return render_template('cobec/my_declarations.html', 
                         declarations=declarations,
                         current_year=current_year,
                         current_declared=current_declared)

@cobec_bp.route('/declarations/<int:id>')
@login_required
@permission_required('cobec', level='view')
def view_declaration(id):
    """View a specific COBEC declaration"""
    declaration = COBECDeclaration.get_by_id(id)
    
    if not declaration:
        flash('Declaration not found.', 'danger')
        return redirect(url_for('cobec.my_declarations'))
    
    # Permission check
    is_owner = declaration.employee_id == current_user.id
    is_compliance = current_user.is_compliance_officer() if hasattr(current_user, 'is_compliance_officer') else current_user.role == 'compliance_officer'
    is_admin = current_user.role == 'admin'
    
    if not (is_owner or is_compliance or is_admin):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    return render_template('cobec/detail.html', declaration=declaration)

@cobec_bp.route('/all')
@login_required
@permission_required('cobec', level='view')
def all_declarations():
    """View all COBEC declarations (compliance/admin only)"""
    if current_user.role not in ['admin', 'compliance_officer']:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    
    year = request.args.get('year', datetime.now().year, type=int)
    
    # Use comprehensive status list instead of just declarations
    compliance_list = COBECDeclaration.get_compliance_status(year)
    stats = COBECDeclaration.get_statistics(year)
    
    return render_template('cobec/all_declarations.html', 
                         compliance_list=compliance_list,
                         stats=stats,
                         selected_year=year)

@cobec_bp.route('/pending-review')
@login_required
@permission_required('cobec', level='view')
def pending_review():
    """Declarations pending review (Manager and/or Compliance)"""
    declarations_dict = {}

    # 1. Manager: pending declarations for their direct reports
    if current_user.is_manager():
        for d in COBECDeclaration.get_pending_for_manager(current_user.id):
            declarations_dict[d.id] = d

    # 2. Compliance/Admin: pending declarations system-wide
    if current_user.is_compliance_officer() or current_user.role == 'admin':
        for d in COBECDeclaration.get_pending_for_compliance():
            declarations_dict[d.id] = d

    if not declarations_dict and not (current_user.is_manager() or current_user.is_compliance_officer() or current_user.role == 'admin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    declarations = sorted(declarations_dict.values(), key=lambda x: x.created_at if x.created_at else '', reverse=True)

    return render_template('cobec/pending_review.html', declarations=declarations)

@cobec_bp.route('/declarations/<int:id>/review', methods=['GET', 'POST'])
@login_required
@permission_required('cobec', level='edit')
def review_declaration(id):
    """Review COBEC declaration"""
    if not (current_user.is_manager() or current_user.is_compliance_officer()):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    declaration = COBECDeclaration.get_by_id(id)
    if not declaration:
        flash('Declaration not found.', 'danger')
        return redirect(url_for('cobec.pending_review'))

    if request.method == 'POST':
        action = request.form.get('action')
        comments = request.form.get('comments')

        if action == 'approve':
            declaration.approve(current_user.id, comments)
            AuditLog.log(current_user.id, 'COBEC Approval', 'COBEC', id, 'Approved COBEC declaration', request.remote_addr)
            flash('Declaration approved.', 'success')
        elif action == 'clarify':
            declaration.request_clarification(current_user.id, comments)
            AuditLog.log(current_user.id, 'COBEC Clarification', 'COBEC', id, 'Requested clarification for COBEC declaration', request.remote_addr)
            flash('Clarification requested.', 'info')
        elif action == 'escalate':
            declaration.escalate(current_user.id, comments)
            AuditLog.log(current_user.id, 'COBEC Escalation', 'COBEC', id, 'Escalated COBEC declaration to compliance', request.remote_addr)
            flash('Declaration escalated to compliance.', 'warning')

        return redirect(url_for('cobec.pending_review'))
    
    return render_template('cobec/review.html', declaration=declaration)
