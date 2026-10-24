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
from flask_babel import gettext
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from utils.decorators import permission_required
from database.db import get_db
from . import dp_bp
from datetime import datetime, timedelta, date

DSR_FINAL_STATES = ('COMPLETED', 'REJECTED')
# Request types that disclose or destroy personal data: never complete them for an
# unverified requester.
DSR_VERIFY_FIRST = ('ACCESS', 'ERASURE', 'PORTABILITY')
LEGAL_BASES = ('CONSENT', 'CONTRACT', 'LEGAL_OBLIGATION', 'VITAL_INTERESTS',
               'PUBLIC_INTEREST', 'LEGITIMATE_INTERESTS')
DPIA_EDIT_STATUSES = ('DRAFT', 'IN_PROGRESS', 'PENDING_APPROVAL')
BREACH_STATUSES = ('NEW', 'INVESTIGATING', 'CONTAINED', 'REMEDIATING', 'CLOSED')


def _now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _log_dsr(db, request_id, action_type, description):
    db.execute("""
        INSERT INTO dsr_timeline (request_id, action_date, action_type, action_description, action_by)
        VALUES (%s, %s, %s, %s, %s)
    """, (request_id, _now_text(), action_type, description, current_user.id))


def _parse_day(value):
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def breach_notification_overdue(breach, now=None):
    """True when the regulator had to be notified, 72 hours have passed since
    discovery, and no notification is recorded."""
    b = dict(breach)
    if not b.get('pdpc_notification_required') or b.get('pdpc_notified'):
        return False
    disc = _parse_day(b.get('discovery_date'))
    if not disc:
        return False
    now = now or datetime.now()
    return now >= datetime.combine(disc, datetime.min.time()) + timedelta(hours=72)


def validate_breach_report(breach_date, discovery_date, affected, today=None):
    """Returns an error message or None."""
    today = today or date.today()
    b, d = _parse_day(breach_date), _parse_day(discovery_date)
    if not b or not d:
        return gettext('Breach date and discovery date are required.')
    if b > d:
        return gettext('The breach date cannot be after the discovery date.')
    if d > today:
        return gettext('The discovery date cannot be in the future.')
    try:
        if int(affected or 0) < 0:
            return gettext('Affected individuals cannot be negative.')
    except (TypeError, ValueError):
        return gettext('Affected individuals must be a whole number.')
    return None

@dp_bp.route('/')
@login_required
@permission_required('pdpl')
def dashboard():
    db = get_db()
    open_dsrs = db.execute("SELECT COUNT(*) as count FROM data_subject_requests WHERE status NOT IN ('COMPLETED', 'REJECTED')").fetchone()['count']
    pending_dpias = db.execute("SELECT COUNT(*) as count FROM dpias WHERE status = 'PENDING_APPROVAL'").fetchone()['count']
    active_consents = db.execute("SELECT COUNT(*) as count FROM consents WHERE withdrawn = 0").fetchone()['count']
    activities_count = db.execute("SELECT COUNT(*) as count FROM data_processing_activities").fetchone()['count']
    
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
                          activities_count=activities_count,
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
            (request_reference, request_date, data_subject_name, request_type, due_date, status,
             identity_verified, created_at, created_by)
            VALUES (%s, CURRENT_DATE, %s, %s, %s, 'NEW', 0, %s, %s)
        """, (request_number, subject_name, req_type, due_date, _now_text(), current_user.id))
        
        db.commit()
        flash(gettext('Data Subject Request %(request_number)s registered.', request_number=request_number))
        return redirect(url_for('dp.dsr_list'))
        
    return render_template('data_protection/dsr_form.html', user=current_user)

@dp_bp.route('/dsrs/<int:id>')
@login_required
@permission_required('pdpl')
def dsr_detail(id):
    db = get_db()
    dsr = db.execute("SELECT * FROM data_subject_requests WHERE id = %s", (id,)).fetchone()
    if not dsr:
        flash(gettext('Request not found.'))
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
    method = (request.form.get('method') or '').strip()
    dsr = db.execute("SELECT status FROM data_subject_requests WHERE id = %s", (id,)).fetchone()
    if not dsr:
        flash(gettext('Request not found.'))
        return redirect(url_for('dp.dsr_list'))
    if dsr['status'] in DSR_FINAL_STATES:
        flash(gettext('This request is closed and can no longer be changed.'), 'warning')
        return redirect(url_for('dp.dsr_detail', id=id))
    if not method:
        flash(gettext('Select how the identity was verified.'), 'warning')
        return redirect(url_for('dp.dsr_detail', id=id))

    db.execute("""
        UPDATE data_subject_requests
        SET identity_verified = 1,
            verified_by = %s,
            verification_date = CURRENT_DATE,
            verification_method = %s,
            status = 'IN_PROGRESS'
        WHERE id = %s
    """, (current_user.id, method, id))
    
    _log_dsr(db, id, 'IDENTITY_VERIFIED', f"Identity verified via {method}")
    
    db.commit()
    flash(gettext('Identity verified. Request moved to IN_PROGRESS.'))
    return redirect(url_for('dp.dsr_detail', id=id))

@dp_bp.route('/dsrs/<int:id>/assign', methods=['POST'])
@login_required
@permission_required('pdpl', level='edit')
def assign_dsr(id):
    db = get_db()
    user_id = request.form.get('user_id')
    dsr = db.execute("SELECT status FROM data_subject_requests WHERE id = %s", (id,)).fetchone()
    if not dsr:
        flash(gettext('Request not found.'))
        return redirect(url_for('dp.dsr_list'))
    if dsr['status'] in DSR_FINAL_STATES:
        flash(gettext('This request is closed and can no longer be changed.'), 'warning')
        return redirect(url_for('dp.dsr_detail', id=id))
    
    db.execute("""
        UPDATE data_subject_requests
        SET assigned_to = %s
        WHERE id = %s
    """, (user_id, id))

    assigned_user = db.execute("SELECT first_name || ' ' || last_name as full_name FROM users WHERE id = %s", (user_id,)).fetchone()
    if not assigned_user:
        flash(gettext('Selected user not found.'), 'danger')
        return redirect(url_for('dp.dsr_detail', id=id))

    _log_dsr(db, id, 'ASSIGNED', f"Assigned to {assigned_user['full_name']}")
    
    db.commit()
    flash(gettext('Request assigned to %(full_name)s.', full_name=assigned_user["full_name"]))
    return redirect(url_for('dp.dsr_detail', id=id))

@dp_bp.route('/dsrs/<int:id>/complete', methods=['POST'])
@login_required
@permission_required('pdpl', level='edit')
def complete_dsr(id):
    db = get_db()
    status = (request.form.get('status') or '').strip().upper()
    notes = (request.form.get('notes') or '').strip()
    rejection_reason = (request.form.get('rejection_reason') or '').strip() if status == 'REJECTED' else None
    dsr = db.execute("SELECT * FROM data_subject_requests WHERE id = %s", (id,)).fetchone()
    if not dsr:
        flash(gettext('Request not found.'))
        return redirect(url_for('dp.dsr_list'))
    if dsr['status'] in DSR_FINAL_STATES:
        flash(gettext('This request is closed and can no longer be changed.'), 'warning')
        return redirect(url_for('dp.dsr_detail', id=id))
    if status not in DSR_FINAL_STATES:
        flash(gettext('Invalid status.'), 'danger')
        return redirect(url_for('dp.dsr_detail', id=id))
    if status == 'REJECTED' and not rejection_reason:
        flash(gettext('A rejection reason is required.'), 'danger')
        return redirect(url_for('dp.dsr_detail', id=id))
    if (status == 'COMPLETED' and (dsr['request_type'] or '').upper() in DSR_VERIFY_FIRST
            and not dsr['identity_verified']):
        flash(gettext("Verify the data subject's identity before completing an access or erasure request."), 'danger')
        return redirect(url_for('dp.dsr_detail', id=id))
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
            decision_by = %s,
            decision_rationale = %s,
            closed = 1,
            closed_date = CURRENT_DATE
        WHERE id = %s
    """, (status, status, current_user.id, rationale, id))

    _log_dsr(db, id, status, f"Request {status.lower()}. Notes: {rationale}")

    db.commit()
    flash(gettext('Request completed.') if status == 'COMPLETED' else gettext('Request rejected.'))
    return redirect(url_for('dp.dsr_detail', id=id))

@dp_bp.route('/breaches')
@login_required
@permission_required('pdpl')
def breach_list():
    db = get_db()
    breaches = [dict(b) for b in db.execute("SELECT * FROM data_breaches ORDER BY discovery_date DESC").fetchall()]
    for b in breaches:
        b['notification_overdue'] = breach_notification_overdue(b)
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
        err = validate_breach_report(breach_date, discovery_date, affected_individuals)
        if err:
            flash(err, 'danger')
            return render_template('data_protection/breach_form.html', user=current_user)

        db.execute("""
            INSERT INTO data_breaches 
            (breach_number, breach_date, discovery_date, breach_type, breach_description, 
             affected_individuals_count, includes_sensitive_data, status, created_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'NEW', %s, %s)
        """, (breach_number, breach_date, discovery_date, breach_type, description, 
              int(affected_individuals), sensitive_data, _now_text(), current_user.id))
        
        db.commit()
        
        # Calculate initial severity
        breach_id = db.execute("SELECT LASTVAL() as id").fetchone()['id']
        from .services import calculate_breach_severity, check_pdpc_notification_requirement
        calculate_breach_severity(breach_id)
        check_pdpc_notification_requirement(breach_id)
        
        flash(gettext('Breach %(breach_number)s reported and severity assessed.', breach_number=breach_number))
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
        if status not in BREACH_STATUSES:
            flash(gettext('Invalid status.'), 'danger')
            return redirect(url_for('dp.breach_detail', id=id))

        db.execute("""
            UPDATE data_breaches 
            SET status = %s, investigation_findings = %s, root_cause = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (status, findings, root_cause, id))
        db.commit()
        flash(gettext('Breach investigation updated.'))
        return redirect(url_for('dp.breach_detail', id=id))

    breach = db.execute("SELECT * FROM data_breaches WHERE id = %s", (id,)).fetchone()
    if not breach:
        flash(gettext('Breach not found.'))
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
                          notification_overdue=breach_notification_overdue(breach),
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
            (assessment_reference, system_name, processing_description, risk_level, status, created_at, created_by)
            VALUES (%s, %s, %s, %s, 'DRAFT', %s, %s)
        """, (dpia_number, project_name, description, risk_level, _now_text(), current_user.id))
        
        db.commit()
        flash(gettext('DPIA %(dpia_number)s created as draft.', dpia_number=dpia_number))
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
        # Approval only happens through approve_dpia (four-eyes check there).
        if status not in DPIA_EDIT_STATUSES:
            flash(gettext('Invalid status.'), 'danger')
            return redirect(url_for('dp.dpia_detail', id=id))

        # dpias.risks_identified / updated_at added by migration 20261104
        # (risks used to be folded into mitigation_measures as a stopgap).
        db.execute("""
            UPDATE dpias
            SET processing_description = %s, risks_identified = %s,
                mitigation_measures = %s, status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (processing, risks, mitigations, status, id))
        db.commit()
        flash(gettext('DPIA assessment updated.'))
        return redirect(url_for('dp.dpia_detail', id=id))

    dpia = db.execute("""
        SELECT d.*, NULLIF(TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')), '') AS approved_by_name,
               NULLIF(TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')), '') AS created_by_name
        FROM dpias d
        LEFT JOIN users a ON a.id = d.approved_by
        LEFT JOIN users c ON c.id = d.created_by
        WHERE d.id = %s""", (id,)).fetchone()
    if not dpia:
        flash(gettext('DPIA not found.'))
        return redirect(url_for('dp.dpia_list'))

    users =db.execute("SELECT id, first_name || ' ' || last_name as full_name FROM users WHERE is_active = 1").fetchall()
    
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
    dpia = db.execute("SELECT created_by, status FROM dpias WHERE id = %s", (id,)).fetchone()
    if not dpia:
        flash(gettext('DPIA not found.'))
        return redirect(url_for('dp.dpia_list'))
    if dpia['created_by'] is not None and int(dpia['created_by']) == int(current_user.id):
        flash(gettext('The approver must be a different person from the DPIA author.'), 'danger')
        return redirect(url_for('dp.dpia_detail', id=id))
    if dpia['status'] != 'PENDING_APPROVAL':
        flash(gettext('Only a DPIA pending approval can be approved or rejected.'), 'warning')
        return redirect(url_for('dp.dpia_detail', id=id))

    status = 'APPROVED' if decision == 'approve' else 'REJECTED'

    # approved/approved_by/approval_conditions aren't real columns on dpias
    # (that was the bug). senior_management_approval (integer 0/1) and
    # approval_date are the columns that actually exist; conditions text has
    # nowhere to persist, folded into dpo_advice as the closest existing
    # free-text field rather than dropped silently.
    db.execute("""
        UPDATE dpias
        SET status = %s, senior_management_approval = %s,
            approval_date = CURRENT_DATE, dpo_advice = %s, approved_by = %s
        WHERE id = %s
    """, (status, 1 if status == 'APPROVED' else 0, conditions, current_user.id, id))
    
    db.commit()
    flash(gettext('DPIA approved.') if status == 'APPROVED' else gettext('DPIA rejected.'))
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
        code = (code or '').strip().upper()
        if not code:
            flash(gettext('Activity code is required.'), 'danger')
            return render_template('data_protection/activity_form.html', user=current_user)
        if legal_basis not in LEGAL_BASES:
            flash(gettext('Select a valid legal basis.'), 'danger')
            return render_template('data_protection/activity_form.html', user=current_user)
        if db.execute("SELECT 1 FROM data_processing_activities WHERE UPPER(TRIM(activity_code)) = %s",
                      (code,)).fetchone():
            flash(gettext('Activity code %(code)s already exists in the ROPA.', code=code), 'danger')
            return render_template('data_protection/activity_form.html', user=current_user)

        db.execute("""
            INSERT INTO data_processing_activities 
            (activity_code, activity_name, processing_purpose, legal_basis, data_categories, data_subject_categories,
             is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
        """, (code, name, purpose, legal_basis, categories, subjects, _now_text()))
        
        db.commit()
        flash(gettext('Activity %(code)s registered in ROPA.', code=code))
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
