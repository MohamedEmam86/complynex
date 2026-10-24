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
from data_protection import records as R


def sync_case(case_type, source_id):
    """Push to the unified case registry (lazy import: models.case imports this package)."""
    from models.case import sync_case as _sync
    return _sync(case_type, source_id)

_ERR = {
    'name': lambda: gettext('Data subject name is required.'),
    'type': lambda: gettext('Select a valid request type.'),
    'contact': lambda: gettext("Enter the requester's email address or phone number."),
    'email': lambda: gettext('Please enter a valid email address.'),
    'phone': lambda: gettext('Please enter a valid phone number.'),
    'channel': lambda: gettext('Select the channel.'),
    'received': lambda: gettext('Invalid received date.'),
    'received_future': lambda: gettext('The received date cannot be in the future.'),
    'method': lambda: gettext('Select a valid method.'),
    'purpose': lambda: gettext('Select a purpose.'),
    'legal_basis': lambda: gettext('Select a valid legal basis.'),
    'transfer_countries': lambda: gettext('List the destination countries for the cross-border transfer.'),
    'transfer_safeguards': lambda: gettext('Describe the safeguards for the cross-border transfer.'),
    'retention': lambda: gettext('The retention period is required.'),
    'date': lambda: gettext('Invalid date.'),
    'date_future': lambda: gettext('The date cannot be in the future.'),
    'subject': lambda: gettext('The data subject is required.'),
    'evidence': lambda: gettext('Record the evidence of consent (e.g. form number, recording or log reference).'),
    'reason': lambda: gettext('A reason is required.'),
    'before_consent': lambda: gettext('The withdrawal date cannot be before the consent date.'),
    'before_discovery': lambda: gettext('A notification date cannot be before the discovery date.'),
    'reference': lambda: gettext("Enter the regulator's reference for the notification."),
    'regulator_date': lambda: gettext('Enter the date the regulator was notified.'),
    'subjects_date': lambda: gettext('Enter the date the data subjects were notified.'),
    'count': lambda: gettext('The number of notified individuals must be a whole number.'),
}


def _err(key):
    return _ERR.get(key, lambda: gettext('Invalid input.'))()


def _active_users():
    return get_db().execute("""SELECT id, COALESCE(NULLIF(TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), ''), email) AS full_name
                               FROM users WHERE is_active = 1 ORDER BY first_name, last_name""").fetchall()

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
        err, d = R.validate_dsr_intake(request.form)
        if err:
            flash(_err(err), 'danger')
            return render_template('data_protection/dsr_form.html', user=current_user, R=R, form=request.form,
                                   today=date.today().isoformat())
        request_number = f"DSR-{datetime.now().strftime('%Y%m')}-{os.urandom(2).hex().upper()}"
        due_date = (d['received_date'] + timedelta(days=30)).isoformat()  # 30 days from receipt

        new_id = db.execute("""
            INSERT INTO data_subject_requests
            (request_reference, request_date, received_date, data_subject_name, data_subject_email,
             data_subject_phone, request_channel, request_type, request_description, verification_method,
             due_date, status, identity_verified, created_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'NEW', 0, %s, %s)
            RETURNING id
        """, (request_number, d['received_date'].isoformat(), d['received_date'], d['data_subject_name'],
              d['data_subject_email'], d['data_subject_phone'], d['request_channel'], d['request_type'],
              d['request_description'], d['verification_method'], due_date, _now_text(),
              current_user.id)).fetchone()['id']
        _log_dsr(db, new_id, 'RECEIVED', f"Request received via {d['request_channel']} on {d['received_date']}")
        db.commit()
        sync_case('DSR', new_id)
        flash(gettext('Data Subject Request %(request_number)s registered.', request_number=request_number))
        return redirect(url_for('dp.dsr_detail', id=new_id))

    return render_template('data_protection/dsr_form.html', user=current_user, R=R, form={},
                           today=date.today().isoformat())

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
    
    users = _active_users()
    
    return render_template('data_protection/dsr_detail.html', R=R, 
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
    if method not in R.VERIFY_METHODS:
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
    sync_case('DSR', id)
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
    
    assigned_user = db.execute("SELECT first_name || ' ' || last_name as full_name FROM users "
                               "WHERE id = %s AND is_active = 1", (request.form.get('user_id', type=int),)).fetchone()
    if not assigned_user:
        flash(gettext('Selected user not found.'), 'danger')
        return redirect(url_for('dp.dsr_detail', id=id))
    db.execute("""
        UPDATE data_subject_requests
        SET assigned_to = %s
        WHERE id = %s
    """, (request.form.get('user_id', type=int), id))

    _log_dsr(db, id, 'ASSIGNED', f"Assigned to {assigned_user['full_name']}")
    
    db.commit()
    sync_case('DSR', id)
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
    sync_case('DSR', id)
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

        breach_id = db.execute("""
            INSERT INTO data_breaches 
            (breach_number, breach_date, discovery_date, breach_type, breach_description, 
             affected_individuals_count, includes_sensitive_data, status, created_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'NEW', %s, %s)
            RETURNING id
        """, (breach_number, breach_date, discovery_date, breach_type, description, 
              int(affected_individuals), sensitive_data, _now_text(), current_user.id)).fetchone()['id']
        db.execute("""INSERT INTO data_breach_updates (breach_id, old_status, new_status, note, created_by)
                      VALUES (%s, NULL, 'NEW', 'Breach reported', %s)""", (breach_id, current_user.id))
        db.commit()
        
        # Calculate initial severity
        from .services import calculate_breach_severity, check_pdpc_notification_requirement
        calculate_breach_severity(breach_id)
        check_pdpc_notification_requirement(breach_id)
        sync_case('DATA_BREACH', breach_id)
        
        flash(gettext('Breach %(breach_number)s reported and severity assessed.', breach_number=breach_number))
        return redirect(url_for('dp.breach_detail', id=breach_id))
        
    return render_template('data_protection/breach_form.html', user=current_user)

@dp_bp.route('/breaches/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('pdpl')
def breach_detail(id):
    db = get_db()
    
    if request.method == 'POST' and current_user.has_permission('pdpl', 'edit'):
        current = db.execute("SELECT * FROM data_breaches WHERE id = %s", (id,)).fetchone()
        if not current:
            flash(gettext('Breach not found.'))
            return redirect(url_for('dp.breach_list'))
        current = dict(current)
        if request.form.get('action') == 'notification':
            err, n = R.validate_breach_notification(request.form, current.get('discovery_date'))
            if err:
                flash(_err(err), 'danger')
                return redirect(url_for('dp.breach_detail', id=id) + '#notification')
            db.execute("""UPDATE data_breaches SET pdpc_notified = %s, pdpc_notification_date = %s, pdpc_reference = %s,
                              individuals_notified = %s, individuals_notification_date = %s,
                              individuals_notification_method = %s, individuals_notification_count = %s,
                              notification_notes = %s, notification_recorded_by = %s, updated_at = %s
                          WHERE id = %s""",
                       (n['pdpc_notified'], n['pdpc_notification_date'], n['pdpc_reference'],
                        n['individuals_notified'], n['individuals_notification_date'],
                        n['individuals_notification_method'], n['individuals_notification_count'],
                        n['notification_notes'], current_user.id, _now_text(), id))
            db.execute("""INSERT INTO data_breach_updates (breach_id, old_status, new_status, note, created_by)
                          VALUES (%s, %s, %s, %s, %s)""",
                       (id, current.get('status'), current.get('status'),
                        'Notification record updated: regulator ' + (n['pdpc_notification_date'] or '-')
                        + ' / data subjects ' + (n['individuals_notification_date'] or '-'), current_user.id))
            db.commit()
            sync_case('DATA_BREACH', id)
            flash(gettext('Notification record saved.'), 'success')
            return redirect(url_for('dp.breach_detail', id=id) + '#notification')

        # Update investigation
        status = request.form.get('status')
        findings = request.form.get('findings')
        root_cause = request.form.get('root_cause')
        note = (request.form.get('status_note') or '').strip()
        owner = request.form.get('owner_user_id', type=int)
        if status not in BREACH_STATUSES:
            flash(gettext('Invalid status.'), 'danger')
            return redirect(url_for('dp.breach_detail', id=id))
        old_status = current.get('status')
        if status != old_status and status == 'CLOSED' and not note:
            flash(gettext('A note is required to close a breach.'), 'danger')
            return redirect(url_for('dp.breach_detail', id=id))
        if owner and not db.execute("SELECT 1 FROM users WHERE id = %s AND is_active = 1", (owner,)).fetchone():
            owner = None

        db.execute("""
            UPDATE data_breaches 
            SET status = %s, investigation_findings = %s, root_cause = %s, owner_user_id = %s, updated_at = %s,
                closed_date = CASE WHEN %s = 'CLOSED' THEN COALESCE(closed_date, %s) ELSE NULL END,
                closed_by = CASE WHEN %s = 'CLOSED' THEN COALESCE(closed_by, %s) ELSE NULL END
            WHERE id = %s
        """, (status, findings, root_cause, owner, _now_text(), status, _now_text(), status, current_user.id, id))
        if status != old_status or note or owner != current.get('owner_user_id'):
            text = note or None
            if owner != current.get('owner_user_id'):
                text = ((text + ' | ') if text else '') + 'Owner changed'
            db.execute("""INSERT INTO data_breach_updates (breach_id, old_status, new_status, note, created_by)
                          VALUES (%s, %s, %s, %s, %s)""", (id, old_status, status, text, current_user.id))
        db.commit()
        sync_case('DATA_BREACH', id)
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
    
    users = _active_users()
    history = db.execute("""SELECT h.*, NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS user_name
                             FROM data_breach_updates h LEFT JOIN users u ON u.id = h.created_by
                             WHERE h.breach_id = %s ORDER BY h.created_at DESC, h.id DESC""", (id,)).fetchall()

    return render_template('data_protection/breach_detail.html', R=R, history=history, 
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

        new_id = db.execute("""
            INSERT INTO data_processing_activities 
            (activity_code, activity_name, processing_purpose, legal_basis, data_categories, data_subject_categories,
             is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
            RETURNING id
        """, (code, name, purpose, legal_basis, categories, subjects, _now_text())).fetchone()['id']
        db.execute("INSERT INTO data_processing_activity_history (activity_id, changed_by, changes) VALUES (%s, %s, %s)",
                   (new_id, current_user.id, 'Created'))
        db.commit()
        flash(gettext('Activity %(code)s registered in ROPA. Complete the remaining record fields.', code=code))
        return redirect(url_for('dp.edit_activity', id=new_id))
        
    return render_template('data_protection/activity_form.html', user=current_user)

@dp_bp.route('/activities/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('pdpl', level='edit')
def edit_activity(id):
    """ROPA record: all record-of-processing fields, with a who/when change history."""
    db = get_db()
    act = db.execute("SELECT * FROM data_processing_activities WHERE id = %s", (id,)).fetchone()
    if not act:
        flash(gettext('Activity not found.'), 'danger')
        return redirect(url_for('dp.activity_list'))
    act = dict(act)
    if request.method == 'POST':
        err, data = R.validate_ropa(request.form, LEGAL_BASES)
        if err:
            flash(_err(err), 'danger')
            act.update({k: request.form.get(k) for k in R.ROPA_FIELDS})
        else:
            changes = R.ropa_changes(act, data)
            if not changes:
                flash(gettext('No changes.'), 'info')
                return redirect(url_for('dp.edit_activity', id=id))
            cols = ', '.join(f'{k} = %s' for k in data)
            db.execute(f"UPDATE data_processing_activities SET {cols}, updated_at = %s, updated_by = %s WHERE id = %s",
                       (*data.values(), _now_text(), current_user.id, id))
            db.execute("INSERT INTO data_processing_activity_history (activity_id, changed_by, changes) VALUES (%s, %s, %s)",
                       (id, current_user.id, '\n'.join(changes)))
            db.commit()
            flash(gettext('ROPA record updated.'), 'success')
            return redirect(url_for('dp.edit_activity', id=id))
    history = db.execute("""SELECT h.*, NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS user_name
                             FROM data_processing_activity_history h LEFT JOIN users u ON u.id = h.changed_by
                             WHERE h.activity_id = %s ORDER BY h.changed_at DESC, h.id DESC""", (id,)).fetchall()
    return render_template('data_protection/activity_edit.html', act=act, history=history, users=_active_users(),
                           legal_bases=LEGAL_BASES)


def _purposes(active_only=True):
    return get_db().execute("SELECT * FROM consent_purposes" + (" WHERE COALESCE(active, 1) = 1" if active_only else "")
                            + " ORDER BY purpose_code").fetchall()


@dp_bp.route('/consents')
@login_required
@permission_required('pdpl')
def consent_log():
    """Consent register: capture, withdrawal and history."""
    db = get_db()
    q = (request.args.get('q') or '').strip()
    state = request.args.get('state') or ''
    sql = """
        SELECT c.*, p.purpose_name_en, p.purpose_name_ar, p.purpose_code
        FROM consents c
        LEFT JOIN consent_purposes p ON c.purpose_id = p.id
        WHERE 1=1"""
    args = []
    if q:
        sql += " AND (c.data_subject_id ILIKE %s OR c.data_subject_identifier ILIKE %s)"
        args += [f'%{q}%', f'%{q}%']
    if state == 'active':
        sql += " AND COALESCE(c.withdrawn, 0) = 0"
    elif state == 'withdrawn':
        sql += " AND COALESCE(c.withdrawn, 0) = 1"
    sql += " ORDER BY c.consent_date DESC, c.id DESC LIMIT 500"
    consents = db.execute(sql, args).fetchall()
    return render_template('data_protection/consent_log.html', consents=consents, user=current_user,
                           purposes=_purposes(), R=R, q=q, state=state, today=date.today().isoformat())


@dp_bp.route('/consents/new', methods=['POST'])
@login_required
@permission_required('pdpl', level='edit')
def capture_consent():
    db = get_db()
    err, d = R.validate_consent(request.form, {p['id'] for p in _purposes()})
    if err:
        flash(_err(err), 'danger')
        return redirect(url_for('dp.consent_log'))
    cid = db.execute("""INSERT INTO consents (data_subject_id, data_subject_identifier, purpose_id, consent_given,
                                              consent_date, consent_method, consent_text, evidence_ref, withdrawn,
                                              recorded_by, created_at)
                         VALUES (%s, %s, %s, 1, %s, %s, %s, %s, 0, %s, %s) RETURNING id""",
                     (d['data_subject_id'], d['data_subject_identifier'], d['purpose_id'], d['consent_date'].isoformat(),
                      d['consent_method'], d['consent_text'], d['evidence_ref'], current_user.id,
                      _now_text())).fetchone()['id']
    db.execute("""INSERT INTO consent_events (consent_id, event_type, event_date, channel, evidence_ref, created_by)
                  VALUES (%s, 'GIVEN', %s, %s, %s, %s)""",
               (cid, d['consent_date'], d['consent_method'], d['evidence_ref'], current_user.id))
    db.commit()
    flash(gettext('Consent recorded.'), 'success')
    return redirect(url_for('dp.consent_detail', id=cid))


@dp_bp.route('/consents/<int:id>')
@login_required
@permission_required('pdpl')
def consent_detail(id):
    db = get_db()
    con = db.execute("""SELECT c.*, p.purpose_name_en, p.purpose_name_ar, p.purpose_code, p.legal_basis
                         FROM consents c LEFT JOIN consent_purposes p ON p.id = c.purpose_id
                         WHERE c.id = %s""", (id,)).fetchone()
    if not con:
        flash(gettext('Consent record not found.'), 'danger')
        return redirect(url_for('dp.consent_log'))
    events = db.execute("""SELECT e.*, NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), '') AS user_name
                            FROM consent_events e LEFT JOIN users u ON u.id = e.created_by
                            WHERE e.consent_id = %s ORDER BY e.created_at, e.id""", (id,)).fetchall()
    others = db.execute("""SELECT c.id, c.consent_date, c.withdrawn, c.withdrawal_date, p.purpose_name_en, p.purpose_name_ar
                            FROM consents c LEFT JOIN consent_purposes p ON p.id = c.purpose_id
                            WHERE c.data_subject_id = %s AND c.id <> %s ORDER BY c.consent_date DESC""",
                         (con['data_subject_id'], id)).fetchall()
    return render_template('data_protection/consent_detail.html', con=con, events=events, others=others, R=R,
                           today=date.today().isoformat())


@dp_bp.route('/consents/<int:id>/withdraw', methods=['POST'])
@login_required
@permission_required('pdpl', level='edit')
def withdraw_consent(id):
    db = get_db()
    con = db.execute("SELECT * FROM consents WHERE id = %s", (id,)).fetchone()
    if not con:
        flash(gettext('Consent record not found.'), 'danger')
        return redirect(url_for('dp.consent_log'))
    if con['withdrawn']:
        flash(gettext('This consent has already been withdrawn.'), 'warning')
        return redirect(url_for('dp.consent_detail', id=id))
    err, w = R.validate_withdrawal(request.form, con['consent_date'])
    if err:
        flash(_err(err), 'danger')
        return redirect(url_for('dp.consent_detail', id=id))
    db.execute("""UPDATE consents SET withdrawn = 1, withdrawal_date = %s, withdrawal_reason = %s,
                      withdrawal_method = %s, withdrawal_recorded_by = %s WHERE id = %s""",
               (w['withdrawal_date'].isoformat(), w['withdrawal_reason'], w['withdrawal_method'], current_user.id, id))
    db.execute("""INSERT INTO consent_events (consent_id, event_type, event_date, channel, reason, created_by)
                  VALUES (%s, 'WITHDRAWN', %s, %s, %s, %s)""",
               (id, w['withdrawal_date'], w['withdrawal_method'], w['withdrawal_reason'], current_user.id))
    db.commit()
    flash(gettext('Consent withdrawal recorded.'), 'success')
    return redirect(url_for('dp.consent_detail', id=id))


@dp_bp.route('/consent-purposes/new', methods=['POST'])
@login_required
@permission_required('pdpl', level='edit')
def create_purpose():
    db = get_db()
    code = (request.form.get('purpose_code') or '').strip().upper()
    name_en = (request.form.get('purpose_name_en') or '').strip()
    name_ar = (request.form.get('purpose_name_ar') or '').strip()
    basis = request.form.get('legal_basis')
    if not code or not (name_en or name_ar):
        flash(gettext('Purpose code and name are required.'), 'danger')
        return redirect(url_for('dp.purpose_list'))
    if basis not in LEGAL_BASES:
        flash(gettext('Select a valid legal basis.'), 'danger')
        return redirect(url_for('dp.purpose_list'))
    if db.execute("SELECT 1 FROM consent_purposes WHERE UPPER(purpose_code) = %s", (code,)).fetchone():
        flash(gettext('This purpose code already exists.'), 'danger')
        return redirect(url_for('dp.purpose_list'))
    db.execute("""INSERT INTO consent_purposes (purpose_code, purpose_name_en, purpose_name_ar, legal_basis,
                                                retention_period, is_required, version, active, created_at)
                  VALUES (%s, %s, %s, %s, %s, 0, 1, 1, %s)""",
               (code, name_en or name_ar, name_ar or name_en, basis,
                (request.form.get('retention_period') or '').strip() or None, _now_text()))
    db.commit()
    flash(gettext('Consent purpose added.'), 'success')
    return redirect(url_for('dp.purpose_list'))

@dp_bp.route('/consent-purposes')
@login_required
@permission_required('pdpl')
def purpose_list():
    db = get_db()
    purposes = db.execute("SELECT * FROM consent_purposes ORDER BY purpose_code").fetchall()
    return render_template('data_protection/purpose_list.html', purposes=purposes, user=current_user,
                           legal_bases=LEGAL_BASES)
