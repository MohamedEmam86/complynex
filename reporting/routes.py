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

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_required, current_user
from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file
from werkzeug.utils import secure_filename
import os
from datetime import datetime, date, timedelta
from database.db import get_db
from models.reporting import Regulator, RegulatoryReport, RegulatoryReportSubmission
from models.user import User
from models.policy import Policy, PolicyAcknowledgment
from models.ghe import GHEDeclaration
from models.coi import COIDeclaration
from models.cobec import COBECDeclaration
from models.audit import AuditLog
import csv
from io import StringIO
from flask import Response

reporting_bp = Blueprint('reporting', __name__, url_prefix='/reporting')
UPLOAD_FOLDER = 'uploads/reports'  # non-static — not reachable via Flask's unauthenticated /static/ route

@reporting_bp.route('/')
@login_required
@permission_required('reports')
def dashboard():
    """Reporting Dashboard / Calendar"""
        
    upcoming = RegulatoryReportSubmission.get_upcoming(days=30)
    all_submissions = RegulatoryReportSubmission.get_all()
    regulators = Regulator.get_all()
    reports = RegulatoryReport.get_all()
    today = datetime.now().date()
    overdue_count = len([
        s for s in all_submissions
        if s.status in ('pending', 'in_progress') and s.due_date and str(s.due_date) < today.isoformat()
    ])

    return render_template('reporting/dashboard.html',
                         upcoming=upcoming,
                         all_submissions=all_submissions,
                         regulators=regulators,
                         reports=reports,
                         overdue_count=overdue_count,
                         now=datetime.now())

@reporting_bp.route('/submission/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('reports')
def view_submission(id):
    """View and update a specific report submission"""
        
    submission = RegulatoryReportSubmission.get_by_id(id)
    
    if not submission:
        flash('Submission not found.', 'danger')
        return redirect(url_for('reporting.dashboard'))
        
    if request.method == 'POST':
        if not current_user.can_edit('reports'):
            flash('You do not have permission to update this submission.', 'danger')
            return redirect(url_for('reporting.view_submission', id=id))

        # Handle file upload
        attachment = request.files.get('attachment')
        attachment_path = submission.attachment_path
        if attachment and attachment.filename != '':
            save_dir = os.path.join(current_app.root_path, UPLOAD_FOLDER)
            os.makedirs(save_dir, exist_ok=True)
            filename = secure_filename(attachment.filename)
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            full_path = os.path.join(save_dir, filename)
            attachment.save(full_path)
            # Stored relative to the static/ folder so url_for('static', ...) resolves it directly
            attachment_path = os.path.join('uploads/reports', filename)
            submission.attachment_path = attachment_path
            
        status = request.form.get('status')
        notes = request.form.get('notes')
        reference = request.form.get('submission_reference')
        
        submission.update_status(status, current_user.id, 
                               submission_date=datetime.now().date(),
                               reference=reference,
                               notes=notes)
        AuditLog.log(current_user.id, 'Report Submission Update', 'Reporting', id, f'Updated status to {status} for {submission.report_name}', request.remote_addr)
        flash('Submission updated.', 'success')
        return redirect(url_for('reporting.view_submission', id=id))
        
    return render_template('reporting/detail.html', submission=submission)


@reporting_bp.route('/submission/<int:id>/attachment')
@login_required
@permission_required('reports')
def download_attachment(id):
    """Serve a submission's attachment — same module guard as viewing the submission."""
    submission = RegulatoryReportSubmission.get_by_id(id)
    if not submission or not submission.attachment_path:
        flash('Attachment not found.', 'danger')
        return redirect(url_for('reporting.dashboard'))
    return serve_uploaded_file(submission.attachment_path)

@reporting_bp.route('/generate-calendar', methods=['POST'])
@login_required
@permission_required('reports', level='edit')
def generate_calendar():
    """Auto-generate submissions for the year based on templates"""
        
    # Logic to generate based on frequency
    reports = RegulatoryReport.get_all()
    count = 0
    today = datetime.now().date()
    
    for report in reports:
        if report.frequency.lower() == 'adhoc':
            continue
            
        # Check if a submission already exists for the "current" period
        # For simplicity, we'll just check if there's any pending submission for this report
        db = get_db()
        existing = db.execute('''
            SELECT COUNT(*) as count FROM regulatory_report_submissions 
            WHERE report_id = %s AND status = 'pending'
            AND due_date::date >= %s
        ''', (report.id, today)).fetchone()['count']
        
        if existing == 0:
            # Calculate next due date
            next_due = None
            freq = report.frequency.lower()
            if freq == 'daily':
                next_due = today + timedelta(days=1)
            elif freq == 'monthly':
                # Next month, day X
                next_month = today.month + 1 if today.month < 12 else 1
                next_year = today.year if today.month < 12 else today.year + 1
                next_due = date(next_year, next_month, report.due_day or 1)
            elif freq == 'quarterly':
                # Next quarter end
                curr_q = (today.month - 1) // 3 + 1
                next_q_month = (curr_q * 3) + 1
                if next_q_month > 12:
                    next_year = today.year + 1
                    next_q_month = 1
                else:
                    next_year = today.year
                next_due = date(next_year, next_q_month, 1) - timedelta(days=1)
            elif freq == 'annual':
                next_due = date(today.year, report.due_month or 12, report.due_day or 31)
                if next_due < today:
                    next_due = date(today.year + 1, report.due_month or 12, report.due_day or 31)
            elif freq == 'weekly':
                # Next Sunday, matching the weekly convention already used by
                # RegulatoryReport.generate_upcoming_submissions().
                days_ahead = (6 - today.weekday()) % 7
                next_due = today + timedelta(days=days_ahead or 7)
            elif freq == 'semi_annual':
                # Two due dates a year, six months apart, anchored on due_month/due_day.
                first_month = report.due_month or 6
                second_month = first_month + 6 if first_month <= 6 else first_month - 6
                day = report.due_day or 28
                candidates = sorted([
                    date(today.year, first_month, min(day, 28)),
                    date(today.year, second_month, min(day, 28)),
                ])
                next_due = next((d for d in candidates if d >= today), None)
                if next_due is None:
                    next_due = date(today.year + 1, min(candidates).month, min(day, 28))

            if next_due:
                RegulatoryReportSubmission.create({
                    'report_id': report.id,
                    'due_date': next_due.isoformat(),
                    'status': 'pending',
                    'notes': f'Auto-generated submission for {report.frequency} cycle.'
                })
                count += 1
                
    AuditLog.log(current_user.id, 'Generate Calendar', 'Reporting', None, f'Generated {count} new submissions.', request.remote_addr)
    flash(f'Reporting calendar updated. {count} new submissions generated.', 'info')
    return redirect(url_for('reporting.dashboard'))

@reporting_bp.route('/create-submission', methods=['POST'])
@login_required
@permission_required('reports', level='edit')
def create_submission():
    """Manually create a report submission"""
        
    report_id = request.form.get('report_id')
    
    # Handle on-the-fly report creation
    if report_id == 'new':
        new_report_name = request.form.get('new_report_name')
        new_regulator_name = request.form.get('new_regulator_name') 
        new_frequency = request.form.get('new_frequency')
        
        if not new_report_name:
             flash('Report Name is required for new reports.', 'danger')
             return redirect(url_for('reporting.dashboard'))

        # Check for regulator or create simplified logic
        regulator_id = request.form.get('new_regulator_id')
        if not regulator_id:
            # Fallback: try to find 'Central Bank of Egypt' or first active
            regs = Regulator.get_all()
            if regs: regulator_id = regs[0].id
        
        try:
            # Create the new Report Definition
             report_id = RegulatoryReport.create({
                 'report_code': f"REP-{datetime.now().strftime('%y%m%d')}", # Auto-gen code
                 'report_name': new_report_name,
                 'regulator_id': regulator_id,
                 'frequency': new_frequency,
                 'submission_method': 'Portal',
                 'is_active': 1
             })
        except Exception as e:
             flash(f'Error creating new report definition: {str(e)}', 'danger')
             return redirect(url_for('reporting.dashboard'))

    reporting_period_start = request.form.get('reporting_period_start')
    reporting_period_end = request.form.get('reporting_period_end')
    due_date = request.form.get('due_date')
    notes = request.form.get('notes')
    
    if not report_id or not due_date:
        flash('Report and Due Date are required.', 'danger')
        return redirect(url_for('reporting.dashboard'))
        
    try:
        submission_id = RegulatoryReportSubmission.create({
            'report_id': report_id,
            'reporting_period_start': reporting_period_start or None,
            'reporting_period_end': reporting_period_end or None,
            'due_date': due_date,
            'status': 'pending',
            'notes': notes,
            'prepared_by': current_user.id
        })
        AuditLog.log(current_user.id, 'Manual Report Submission', 'Reporting', submission_id, f'Created manual submission for report {report_id}', request.remote_addr)
        flash('New submission created successfully.', 'success')
        return redirect(url_for('reporting.view_submission', id=submission_id))
    except Exception as e:
        flash(f'Error creating submission: {str(e)}', 'danger')
        return redirect(url_for('reporting.dashboard'))

@reporting_bp.route('/extended')
@login_required
@permission_required('reports')
def extended_reports():
    """Access advanced compliance reports (Admin/Compliance only)."""
        
    from models.audit import AuditLog
    from models.policy import Policy
    from models.training import TrainingEnrollment, TrainingCourse
    
    # Audit Logs
    audit_logs = AuditLog.get_all()
    
    # Policy Status Report
    all_policies = Policy.get_all()
    policy_stats = []
    for p in all_policies:
        policy_stats.append({
            'id': p.id,
            'name': p.policy_name,
            'number': p.policy_number,
            'status': p.status,
            'ack_count': p.get_acknowledgment_count(),
            'ack_rate': p.get_acknowledgment_rate()
        })
        
    # Training Progress Report
    all_courses = TrainingCourse.get_all()
    training_stats = []
    for c in all_courses:
        enrollments = TrainingEnrollment.get_all_enrollments({'course_id': c.id})
        total = len(enrollments)
        completed = len([e for e in enrollments if e.status == 'completed'])
        training_stats.append({
            'name': c.course_name,
            'code': c.course_code,
            'total_enrolled': total,
            'completed': completed,
            'progress': (completed / total * 100) if total > 0 else 0
        })
        
    return render_template('reporting/reports_extended.html',
                           audit_logs=audit_logs,
                           policy_stats=policy_stats,
                           training_stats=training_stats)

@reporting_bp.route('/policy/<int:id>/acknowledgments')
@login_required
@permission_required('reports')
def policy_acknowledgments(id):
    """View details of who acknowledged a policy"""

    policy = Policy.get_by_id(id)
    if not policy:
        flash('Policy not found.', 'danger')
        return redirect(url_for('reporting.extended_reports'))

    acks = PolicyAcknowledgment.get_acknowledgments(id)
    return render_template('reporting/policy_records.html', policy=policy, acknowledgments=acks)

@reporting_bp.route('/export/approvals')
@login_required
@permission_required('reports')
def export_pending_approvals():
    """Export pending approvals to CSV"""

    # Fetch data
    ghe = GHEDeclaration.get_pending_for_compliance()
    coi = COIDeclaration.get_pending_for_compliance()
    # Filter COBEC for pending status
    all_cobec = COBECDeclaration.get_all()
    cobec = [d for d in all_cobec if d.status in ['under_review', 'submitted']]

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Type', 'Details', 'Employee', 'Date', 'Status'])

    for item in ghe:
        cw.writerow(['GHE', f"{item.ghe_type} - {item.description[:50]}", item.employee_name, item.declaration_date, item.status])
    
    for item in coi:
        has_conflict = item.has_conflicts()
        cw.writerow(['COI', f"{item.campaign_name} - Conflict: {has_conflict}", item.employee_name, item.declaration_date, item.status])

    for item in cobec:
        cw.writerow(['COBEC', 'Annual Declaration', item.employee_name, item.declaration_date, item.status])

    output = si.getvalue()
    return Response(output, mimetype='text/csv', 
                    headers={"Content-Disposition": "attachment;filename=pending_approvals.csv"})

@reporting_bp.route('/export/ics')
@login_required
@permission_required('reports')
def export_calendar():
    """Export upcoming submissions to ICS calendar format"""
    upcoming = RegulatoryReportSubmission.get_upcoming(days=90)
    
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ComplyNex CMS//Regulatory Reporting//EN",
        "CALSCALE:GREGORIAN"
    ]
    
    for sub in upcoming:
        uid = f"report-{sub.id}@complynex.online"
        dtstart = sub.due_date.replace('-', '') + "T090000Z"
        dtend = sub.due_date.replace('-', '') + "T100000Z"
        dtstamp = datetime.now().strftime('%Y%m%dT%H%M%SZ')
        
        ics_lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:DUE: {sub.report_name} ({sub.regulator_name})",
            f"DESCRIPTION:Regulatory deadline for {sub.report_name}. Reference: {sub.report_code}.",
            "END:VEVENT"
        ])
        
    ics_lines.append("END:VCALENDAR")
    
    output = "\\r\\n".join(ics_lines)
    return Response(output, mimetype='text/calendar', headers={"Content-Disposition": "attachment;filename=regulatory_calendar.ics"})

@reporting_bp.route('/report/manage', defaults={'id': None}, methods=['GET', 'POST'])
@reporting_bp.route('/report/manage/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('reports', level='edit')
def manage_report(id):
    """Create or Edit a Regulatory Report Template"""

    report = None
    if id:
        report = RegulatoryReport.get_by_id(id)
        if not report:
            flash('Report not found.', 'danger')
            return redirect(url_for('reporting.dashboard'))

    if request.method == 'POST':
        data = {
            'report_name': request.form.get('report_name'),
            'report_code': request.form.get('report_code'),
            'regulator_id': request.form.get('regulator_id') or None,
            'frequency': request.form.get('frequency'),
            'description': request.form.get('description'),
            'due_day': request.form.get('due_day') or None,
            'due_month': request.form.get('due_month') or None,
            'responsible_department': request.form.get('responsible_department'),
            'regulatory_reference': request.form.get('regulatory_reference')
        }
        
        if id:
             report.update(data)
             AuditLog.log(current_user.id, 'Update Report Template', 'Reporting', id, f'Updated report template {data["report_name"]}', request.remote_addr)
             flash('Report updated successfully.', 'success')
        else:
             new_id = RegulatoryReport.create(data)
             AuditLog.log(current_user.id, 'Create Report Template', 'Reporting', new_id, f'Created report template {data["report_name"]}', request.remote_addr)
             flash('New report template created.', 'success')
        
        return redirect(url_for('reporting.dashboard'))

    regulators = Regulator.get_all()
    return render_template('reporting/manage_report.html', report=report, regulators=regulators)

@reporting_bp.route('/reports')
@login_required
@permission_required('reports')
def list_reports():
    """List all regulatory report templates"""
        
    reports = RegulatoryReport.get_all()
    regulators = Regulator.get_all()
    return render_template('reporting/report_list.html', reports=reports, regulators=regulators)

@reporting_bp.route('/regulators')
@login_required
@permission_required('reports')
def list_regulators():
    """List all regulators"""

    show_inactive = request.args.get('include_inactive') == '1'
    regulators = Regulator.get_all(include_inactive=show_inactive)
    return render_template('reporting/regulator_list.html', regulators=regulators, show_inactive=show_inactive)

@reporting_bp.route('/regulator/manage', defaults={'id': None}, methods=['GET', 'POST'])
@reporting_bp.route('/regulator/manage/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('reports', level='edit')
def manage_regulator(id):
    """Create or Edit a Regulator"""

    regulator = None
    if id:
        regulator = Regulator.get_by_id(id)
        if not regulator:
            flash('Regulator not found.', 'danger')
            return redirect(url_for('reporting.list_regulators'))

    if request.method == 'POST':
        data = {
            'regulator_name': request.form.get('regulator_name'),
            'regulator_code': request.form.get('regulator_code'),
            'contact_email': request.form.get('contact_email'),
            'contact_phone': request.form.get('contact_phone'),
            'website': request.form.get('website'),
            'description': request.form.get('description'),
            'is_active': request.form.get('is_active') == 'on'
        }
        
        if id:
             regulator.update(data)
             AuditLog.log(current_user.id, 'Update Regulator', 'Reporting', id, f'Updated regulator {data["regulator_name"]}', request.remote_addr)
             flash('Regulator updated successfully.', 'success')
        else:
             new_id = Regulator.create(data)
             AuditLog.log(current_user.id, 'Create Regulator', 'Reporting', new_id, f'Created regulator {data["regulator_name"]}', request.remote_addr)
             flash('New regulator created.', 'success')
        
        return redirect(url_for('reporting.list_regulators'))

    return render_template('reporting/manage_regulator.html', regulator=regulator)
