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

import os
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from utils.decorators import permission_required
from database.db import get_db
from . import dp_bp
from datetime import datetime, timedelta

@dp_bp.route('/')
@login_required
@permission_required('pdpl')
def dashboard():
    db = get_db()
    open_dsrs = db.execute("SELECT COUNT(*) as count FROM data_subject_requests WHERE status NOT IN ('COMPLETED', 'REJECTED')").fetchone()['count']
    pending_dpias = db.execute("SELECT COUNT(*) as count FROM dpias WHERE status = 'PENDING_APPROVAL'").fetchone()['count']
    active_consents = db.execute("SELECT COUNT(*) as count FROM consents WHERE withdrawn = 0").fetchone()['count']
    
    active_breaches = db.execute("""
        SELECT * FROM data_breaches 
        WHERE status != 'CLOSED' 
        ORDER BY discovery_date DESC
    """).fetchall()
    
    return render_template('data_protection/dashboard.html', 
                          user=current_user,
                          open_dsrs=open_dsrs,
                          pending_dpias=pending_dpias,
                          active_consents=active_consents,
                          active_breaches=active_breaches)

@dp_bp.route('/dsrs')
@login_required
@permission_required('pdpl', level='view')
def dsr_list():
    db = get_db()
    dsrs = db.execute("SELECT * FROM data_subject_requests ORDER BY due_date ASC").fetchall()
    return render_template('data_protection/dsr_list.html', dsrs=dsrs, user=current_user)

@dp_bp.route('/dsrs/new', methods=['GET', 'POST'])
@login_required
@permission_required('pdpl', level='edit')
@permission_required('pdpl', level='view')
def create_dsr():
    if request.method == 'POST':
        db = get_db()
        request_number = f"DSR-{datetime.now().strftime('%Y%m')}-{os.urandom(2).hex().upper()}"
        subject_name = request.form.get('subject_name')
        req_type = request.form.get('request_type')
        due_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d') # PDPL standard is 30 days
        
        db.execute("""
            INSERT INTO data_subject_requests
            (request_reference, request_date, data_subject_name, request_type, due_date, status, created_by)
            VALUES (%s, CURRENT_DATE, %s, %s, %s, 'NEW', %s)
        """, (request_number, subject_name, req_type, due_date, current_user.id))
        
        db.commit()
        flash(f'Data Subject Request {request_number} registered.')
        return redirect(url_for('dp.dsr_list'))
        
    return render_template('data_protection/dsr_form.html', user=current_user)

@dp_bp.route('/dsrs/<int:id>')
@login_required
@permission_required('pdpl')
def dsr_detail(id):
    db = get_db()
    dsr = db.execute("SELECT * FROM data_subject_requests WHERE id = %s", (id,)).fetchone()
    if not dsr:
        flash('Request not found.')
        return redirect(url_for('dp.dsr_list'))
    
    timeline = db.execute("""
        SELECT t.*, u.first_name || ' ' || u.last_name as user_name 
        FROM dsr_timeline t 
        LEFT JOIN users u ON t.action_by = u.id 
        WHERE t.request_id = %s 
        ORDER BY t.action_date DESC
    """, (id,)).fetchall()
    
    users = db.execute("SELECT id, first_name || ' ' || last_name as full_name FROM users WHERE is_active = 1").fetchall()
    
    return render_template('data_protection/dsr_detail.html', 
                          dsr=dsr, 
                          timeline=timeline, 
                          users=users,
                          user=current_user)

@dp_bp.route('/dsrs/<int:id>/verify', methods=['POST'])
@login_required
@permission_required('pdpl', level='edit')
@permission_required('pdpl', level='view')
def verify_identity(id):
    db = get_db()
    method = request.form.get('method')
    
    db.execute("""
        UPDATE data_subject_requests
        SET identity_verified = 1,
            verified_by = %s,
            verification_date = CURRENT_DATE,
            verification_method = %s,
            status = 'IN_PROGRESS'
        WHERE id = %s
    """, (current_user.id, method, id))
    
    db.execute("""
        INSERT INTO dsr_timeline (request_id, action_type, action_description, action_by)
        VALUES (%s, 'IDENTITY_VERIFIED', %s, %s)
    """, (id, f"Identity verified via {method}", current_user.id))
    
    db.commit()
    flash('Identity verified. Request moved to IN_PROGRESS.')
    return redirect(url_for('dp.dsr_detail', id=id))

@dp_bp.route('/dsrs/<int:id>/assign', methods=['POST'])
@login_required
@permission_required('pdpl', level='edit')
def assign_dsr(id):
    db = get_db()
    user_id = request.form.get('user_id')
    
    db.execute("""
        UPDATE data_subject_requests
        SET assigned_to = %s
        WHERE id = %s
    """, (user_id, id))

    assigned_user = db.execute("SELECT first_name || ' ' || last_name as full_name FROM users WHERE id = %s", (user_id,)).fetchone()
    if not assigned_user:
        flash('Selected user not found.', 'danger')
        return redirect(url_for('dp.dsr_detail', id=id))

    db.execute("""
        INSERT INTO dsr_timeline (request_id, action_type, action_description, action_by)
        VALUES (%s, 'ASSIGNED', %s, %s)
    """, (id, f"Assigned to {assigned_user['full_name']}", current_user.id))
    
    db.commit()
    flash(f'Request assigned to {assigned_user["full_name"]}.')
    return redirect(url_for('dp.dsr_detail', id=id))

@dp_bp.route('/dsrs/<int:id>/complete', methods=['POST'])
@login_required
@permission_required('pdpl', level='edit')
def complete_dsr(id):
    db = get_db()
    status = request.form.get('status')
    notes = request.form.get('notes')
    rejection_reason = request.form.get('rejection_reason') if status == 'REJECTED' else None
    # response_notes/rejection_reason aren't real columns on data_subject_requests
    # (that was the bug — this crashed on every completion); decision_rationale
    # is the closest existing column for "why this decision was made", so both
    # go there instead of inventing a schema change for a bug fix.
    rationale = notes or ''
    if rejection_reason:
        rationale = f"{rationale} | Rejection reason: {rejection_reason}".strip(' |')

    db.execute("""
        UPDATE data_subject_requests
        SET status = %s,
            response_date = CURRENT_DATE,
            decision = %s,
            decision_date = CURRENT_DATE,
            decision_rationale = %s
        WHERE id = %s
    """, (status, status, rationale, id))
    
    db.execute("""
        INSERT INTO dsr_timeline (request_id, action_type, action_description, action_by)
        VALUES (%s, %s, %s, %s)
    """, (id, status, f"Request {status.lower()}. Notes: {notes}", current_user.id))
    
    db.commit()
    flash(f'Request {status.lower()}.')
    return redirect(url_for('dp.dsr_detail', id=id))

@dp_bp.route('/breaches')
@login_required
@permission_required('pdpl')
def breach_list():
    db = get_db()
    breaches = db.execute("SELECT * FROM data_breaches ORDER BY discovery_date DESC").fetchall()
    return render_template('data_protection/breach_list.html', breaches=breaches, user=current_user)

@dp_bp.route('/breaches/new', methods=['GET', 'POST'])
@login_required
@permission_required('pdpl', level='edit')
@permission_required('pdpl', level='view')
def report_breach():
    if request.method == 'POST':
        db = get_db()
        breach_number = f"BRC-{datetime.now().strftime('%Y%m')}-{os.urandom(2).hex().upper()}"
        breach_date = request.form.get('breach_date')
        discovery_date = request.form.get('discovery_date')
        breach_type = request.form.get('breach_type')
        description = request.form.get('description')
        affected_individuals = request.form.get('affected_individuals') or 0
        sensitive_data = 1 if request.form.get('includes_sensitive_data') else 0
        
        db.execute("""
            INSERT INTO data_breaches 
            (breach_number, breach_date, discovery_date, breach_type, breach_description, 
             affected_individuals_count, includes_sensitive_data, status, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'NEW', %s)
        """, (breach_number, breach_date, discovery_date, breach_type, description, 
              affected_individuals, sensitive_data, current_user.id))
        
        db.commit()
        
        # Calculate initial severity
        breach_id = db.execute("SELECT LASTVAL() as id").fetchone()['id']
        from .services import calculate_breach_severity, check_pdpc_notification_requirement
        calculate_breach_severity(breach_id)
        check_pdpc_notification_requirement(breach_id)
        
        flash(f'Breach {breach_number} reported and severity assessed.')
        return redirect(url_for('dp.breach_list'))
        
    return render_template('data_protection/breach_form.html', user=current_user)

@dp_bp.route('/breaches/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('pdpl')
def breach_detail(id):
    db = get_db()
    
    if request.method == 'POST' and current_user.has_permission('pdpl', 'edit'):
        # Update investigation
        status = request.form.get('status')
        findings = request.form.get('findings')
        root_cause = request.form.get('root_cause')
        
        db.execute("""
            UPDATE data_breaches 
            SET status = %s, investigation_findings = %s, root_cause = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (status, findings, root_cause, id))
        db.commit()
        flash('Breach investigation updated.')
        return redirect(url_for('dp.breach_detail', id=id))

    breach = db.execute("SELECT * FROM data_breaches WHERE id = %s", (id,)).fetchone()
    if not breach:
        flash('Breach not found.')
        return redirect(url_for('dp.breach_list'))
        
    remediations = db.execute("""
        SELECT r.*, u.first_name || ' ' || u.last_name as owner_name 
        FROM breach_remediation_actions r
        LEFT JOIN users u ON r.action_owner = u.id
        WHERE r.breach_id = %s
    """, (id,)).fetchall()
    
    users = db.execute("SELECT id, first_name || ' ' || last_name as full_name FROM users WHERE is_active = 1").fetchall()
    
    return render_template('data_protection/breach_detail.html', 
                          breach=breach, 
                          remediations=remediations,
                          users=users,
                          user=current_user)

@dp_bp.route('/dpias')
@login_required
@permission_required('pdpl')
def dpia_list():
    db = get_db()
    dpias = db.execute("SELECT * FROM dpias ORDER BY created_at DESC").fetchall()
    return render_template('data_protection/dpia_list.html', dpias=dpias, user=current_user)

@dp_bp.route('/dpias/new', methods=['GET', 'POST'])
@login_required
@permission_required('pdpl', level='edit')
@permission_required('pdpl', level='view')
def create_dpia():
    if request.method == 'POST':
        db = get_db()
        dpia_number = f"DPIA-{datetime.now().strftime('%Y%m')}-{os.urandom(2).hex().upper()}"
        project_name = request.form.get('project_name')
        description = request.form.get('description')
        risk_level = request.form.get('risk_level')
        
        db.execute("""
            INSERT INTO dpias
            (assessment_reference, system_name, processing_description, risk_level, status, created_by)
            VALUES (%s, %s, %s, %s, 'DRAFT', %s)
        """, (dpia_number, project_name, description, risk_level, current_user.id))
        
        db.commit()
        flash(f'DPIA {dpia_number} created as draft.')
        return redirect(url_for('dp.dpia_list'))
        
    return render_template('data_protection/dpia_form.html', user=current_user)

@dp_bp.route('/dpias/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('pdpl')
def dpia_detail(id):
    db = get_db()
    
    if request.method == 'POST' and current_user.has_permission('pdpl', 'edit'):
        # Update assessments
        processing = request.form.get('processing')
        risks = request.form.get('risks')
        mitigations = request.form.get('mitigations')
        status = request.form.get('status')

        # risks_identified and updated_at aren't real columns on dpias (that
        # was the bug — this crashed on every save). There's no existing
        # free-text column for "risks identified" (dpias only has structured
        # risk_likelihood/risk_impact/risk_level scoring fields, not a risks
        # narrative) — folding the officer's risks text into
        # mitigation_measures is a stopgap, not a real fix; flagged in the
        # audit report as needing an actual schema decision.
        combined_mitigations = f"Risks identified: {risks}\n\nMitigation measures: {mitigations}" if risks else mitigations
        db.execute("""
            UPDATE dpias
            SET processing_description = %s,
                mitigation_measures = %s, status = %s
            WHERE id = %s
        """, (processing, combined_mitigations, status, id))
        db.commit()
        flash('DPIA assessment updated.')
        return redirect(url_for('dp.dpia_detail', id=id))

    dpia = db.execute("SELECT * FROM dpias WHERE id = %s", (id,)).fetchone()
    if not dpia:
        flash('DPIA not found.')
        return redirect(url_for('dp.dpia_list'))
        
    users = db.execute("SELECT id, first_name || ' ' || last_name as full_name FROM users WHERE is_active = 1").fetchall()
    
    return render_template('data_protection/dpia_detail.html', 
                          dpia=dpia, 
                          users=users,
                          user=current_user)

@dp_bp.route('/dpias/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('pdpl', level='approve')
@permission_required('pdpl', level='edit')
def approve_dpia(id):
    db = get_db()
    decision = request.form.get('decision')
    conditions = request.form.get('conditions')
    
    status = 'APPROVED' if decision == 'approve' else 'REJECTED'

    # approved/approved_by/approval_conditions aren't real columns on dpias
    # (that was the bug). senior_management_approval (integer 0/1) and
    # approval_date are the columns that actually exist; conditions text has
    # nowhere to persist, folded into dpo_advice as the closest existing
    # free-text field rather than dropped silently.
    db.execute("""
        UPDATE dpias
        SET status = %s, senior_management_approval = %s,
            approval_date = CURRENT_DATE, dpo_advice = %s
        WHERE id = %s
    """, (status, 1 if status == 'APPROVED' else 0, conditions, id))
    
    db.commit()
    flash(f'DPIA {status.lower()}.')
    return redirect(url_for('dp.dpia_detail', id=id))

@dp_bp.route('/activities')
@login_required
@permission_required('pdpl')
def activity_list():
    db = get_db()
    activities = db.execute("SELECT * FROM data_processing_activities ORDER BY activity_code ASC").fetchall()
    return render_template('data_protection/activity_list.html', activities=activities, user=current_user)

@dp_bp.route('/activities/new', methods=['GET', 'POST'])
@login_required
@permission_required('pdpl', level='edit')
@permission_required('pdpl', level='view')
def create_activity():
    if request.method == 'POST':
        db = get_db()
        code = request.form.get('code')
        name = request.form.get('name')
        purpose = request.form.get('purpose')
        legal_basis = request.form.get('legal_basis')
        categories = request.form.get('categories')
        subjects = request.form.get('subjects')
        
        db.execute("""
            INSERT INTO data_processing_activities 
            (activity_code, activity_name, processing_purpose, legal_basis, data_categories, data_subject_categories, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
        """, (code, name, purpose, legal_basis, categories, subjects))
        
        db.commit()
        flash(f'Activity {code} registered in ROPA.')
        return redirect(url_for('dp.activity_list'))
        
    return render_template('data_protection/activity_form.html', user=current_user)

@dp_bp.route('/consents')
@login_required
@permission_required('pdpl')
def consent_log():
    db = get_db()
    consents = db.execute("""
        SELECT c.*, p.purpose_name_en AS purpose_name
        FROM consents c
        JOIN consent_purposes p ON c.purpose_id = p.id
        ORDER BY c.consent_date DESC
    """).fetchall()
    return render_template('data_protection/consent_log.html', consents=consents, user=current_user)

@dp_bp.route('/consent-purposes')
@login_required
@permission_required('pdpl')
def purpose_list():
    db = get_db()
    purposes = db.execute("SELECT * FROM consent_purposes").fetchall()
    return render_template('data_protection/purpose_list.html', purposes=purposes, user=current_user)
