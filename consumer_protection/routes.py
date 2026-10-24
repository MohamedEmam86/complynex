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
Consumer Protection Module - Routes
===================================
ComplyNex CMS - 100% Free Implementation
Compliant with Banking Law No. 194 of 2020

Features:
- Public Complaint Submission (Bilingual)
- Complaint Tracking
- QR Code Generation
- Admin Dashboard
- CBE Reporting
"""

from flask_babel import gettext
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, send_file, current_app, session
from flask_login import login_required, current_user
from flask_babel import gettext as _, get_locale
from utils.email import send_confirmation_email
from database.db import get_db
from models import ConsumerComplaint, ComplaintDocument, ComplaintActivityLog, ComplaintCategory
from werkzeug.utils import secure_filename
import os
import re
import secrets
from datetime import datetime, timedelta
# import qrcode
from io import BytesIO
from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file
from models.consumer_protection import ComplaintInternalNote
from consumer_protection import handling as H

# Create Blueprint
consumer_bp = Blueprint('consumer_protection', __name__, 
                        url_prefix='/consumer-protection')

# Helper: Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ESCALATED is set by scripts/escalate_complaints.py when the statutory deadline passes.
COMPLAINT_STATUSES = ('NEW', 'IN_PROGRESS', 'ESCALATED', 'RESOLVED', 'CLOSED')
MIN_COMPLAINT_DESCRIPTION = 20
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_PHONE_RE = re.compile(r'^\+?[0-9 ()\-]{7,20}$')


def validate_public_complaint(data, category_codes):
    """Server-side validation of the public form. Returns a list of error messages."""
    errors = []
    if not (data.get('customer_name') or '').strip():
        errors.append(_('Full name is required.'))
    email = (data.get('customer_email') or '').strip()
    if email and not _EMAIL_RE.match(email):
        errors.append(_('Please enter a valid email address.'))
    phone = (data.get('customer_phone') or '').strip()
    digits = sum(ch.isdigit() for ch in phone)
    if not _PHONE_RE.match(phone) or not 7 <= digits <= 15:
        errors.append(_('Please enter a valid phone number.'))
    if data.get('complaint_category') not in category_codes:
        errors.append(_('Please select a valid category.'))
    if not (data.get('complaint_subject') or '').strip():
        errors.append(_('Subject is required.'))
    if len((data.get('complaint_description') or '').strip()) < MIN_COMPLAINT_DESCRIPTION:
        errors.append(_('Please describe the complaint in at least 20 characters.'))
    return errors


# ==============================================================================
# PUBLIC ROUTES
# ==============================================================================

@consumer_bp.route('/', methods=['GET'])
def public_form():
    """Public complaint submission form"""
    session['lang'] = 'ar'
    session['dir'] = 'rtl'
    # Get categories for dropdown
    categories = ComplaintCategory.get_all()
    return render_template('consumer_protection/public_form.html', categories=categories)

@consumer_bp.route('/submit', methods=['POST'])
def submit_complaint():
    """Handle public complaint submission"""
    try:
        # Extract form data
        data = {
            'customer_name': request.form.get('full_name'),
            'customer_email': request.form.get('email'),
            'customer_phone': request.form.get('phone'),
            'customer_id_number': request.form.get('national_id'),
            'complaint_category': request.form.get('category_id'),
            'complaint_subject': request.form.get('subject'),
            'complaint_description': request.form.get('description'),
            'customer_type': 'INDIVIDUAL', # Default
            'complaint_channel': 'PUBLIC_FORM'
        }
        for k in ('customer_name', 'customer_email', 'customer_phone', 'customer_id_number',
                  'complaint_category', 'complaint_subject', 'complaint_description'):
            data[k] = (data[k] or '').strip() or None
        errors = validate_public_complaint(
            data, {c['category_code'] for c in ComplaintCategory.get_all()})
        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('consumer_protection.public_form'))
        
        # Handle file uploads
        files = request.files.getlist('attachments')
        attachments = []
        
        # Create Complaint
        complaint = ConsumerComplaint.create(data)
        
        # Save attachments
        if complaint and files:
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Create directory if it doesn't exist — non-static uploads/ dir,
                    # not reachable via Flask's unauthenticated /static/ route
                    upload_dir = os.path.join(current_app.root_path, 'uploads', 'complaints', str(complaint['id']))
                    os.makedirs(upload_dir, exist_ok=True)

                    file_path = os.path.join(upload_dir, filename)
                    file.save(file_path)

                    # Record in DB
                    doc_data = {
                        'complaint_id': complaint['id'],
                        'file_name': filename,
                        'file_path': f"uploads/complaints/{complaint['id']}/{filename}",
                        'uploaded_by': None # Public
                    }
                    ComplaintDocument.create(doc_data)
        
        if complaint:
            # Send confirmation email
            if data.get('customer_email'):
                template = 'emails/consumer_protection_confirmation_ar.html' if get_locale() == 'ar' else 'emails/consumer_protection_confirmation.html'
                send_confirmation_email(
                    to_email=data.get('customer_email'),
                    subject=_('Consumer Complaint Received'),
                    template=template,
                    complaint_ref=complaint['id'],
                    pin=complaint['complaint_pin']
                )

            return render_template('consumer_protection/success.html', 
                                   complaint_ref=complaint['id'], 
                                   pin=complaint['complaint_pin'])
        else:
            flash(_('Error submitting complaint. Please try again.'), 'danger')
            return redirect(url_for('consumer_protection.public_form'))
            
    except Exception as e:
        current_app.logger.error(f"Complaint Submission Error: {e}")
        flash(_('An unexpected error occurred: %(error)s', error=str(e)), 'danger')
        return redirect(url_for('consumer_protection.public_form'))

@consumer_bp.route('/track', methods=['GET', 'POST'])
def track_case():
    """Track complaint status"""
    session['lang'] = 'ar'
    session['dir'] = 'rtl'
    if request.method == 'POST':
        ref_number = request.form.get('reference_number')
        pin = request.form.get('pin')
        
        # Try finding by reference number (cleaned of CP- prefix if present)
        complaint = ConsumerComplaint.get_by_ref_and_pin(ref_number, pin)
        
        # If not found, try finding by email
        if not complaint and '@' in ref_number:
            complaint = ConsumerComplaint.get_by_email_and_pin(ref_number, pin)
            
        if complaint:
            return render_template('consumer_protection/track.html', 
                                   complaint=complaint, 
                                   show_result=True)
        else:
            flash(_('Invalid Reference Number, Email or PIN.'), 'danger')
    
    return render_template('consumer_protection/track.html', show_result=False)

# ==============================================================================
# INTERNAL ROUTES (Login Required)
# ==============================================================================

@consumer_bp.route('/dashboard')
@login_required
@permission_required('consumer_protection')
def dashboard():
    """Consumer Protection Dashboard"""
    stats = ConsumerComplaint.get_stats()
    # Recent Complaints
    recent_complaints = ConsumerComplaint.get_all(limit=10)
    
    return render_template('consumer_protection/dashboard.html', 
                           total_open=stats['total_open'], 
                           overdue=stats['overdue'],
                           recent_complaints=recent_complaints)

@consumer_bp.route('/complaints')
@login_required
@permission_required('consumer_protection')
def complaints_list():
    """List all complaints with filtering"""
    status = request.args.get('status')
    if status not in COMPLAINT_STATUSES:
        status = None
    q = (request.args.get('q') or '').strip()
    complaints = ConsumerComplaint.get_all(status=status, q=q or None)
    ar = str(get_locale()) == 'ar'
    cats = {c['category_code']: (c['category_name_ar'] if ar else c['category_name_en']) or c['category_code']
            for c in ComplaintCategory.get_all()}
    return render_template('consumer_protection/list.html', complaints=complaints, q=q, cats=cats)

def _complaint_staff():
    """Active users who can work complaints (owner / assignee candidates)."""
    rows = get_db().execute(
        """SELECT id, NULLIF(TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), '') AS name, email
           FROM users WHERE is_active = 1
             AND (role = 'admin' OR perm_consumer_protection IN ('view', 'use', 'edit', 'admin'))
           ORDER BY first_name, last_name""").fetchall()
    return [{'id': r['id'], 'name': r['name'] or r['email']} for r in rows]


_RES_ERRORS = {
    'root_cause': lambda: _('Select a root cause category.'),
    'redress_type': lambda: _('Select a redress type.'),
    'amount': lambda: _('The redress amount must be a positive number.'),
    'amount_required': lambda: _('Enter the redress amount for a refund, fee waiver or compensation.'),
    'date': lambda: _('Invalid redress date.'),
    'date_future': lambda: _('The redress date cannot be in the future.'),
    'date_required': lambda: _('Enter the date the redress was provided.'),
}


def _staff_action(id, complaint):
    """Owner / internal note / root cause & redress. Returns a redirect, or None if not handled."""
    action = request.form.get('action')
    if action not in ('assign', 'add_note', 'resolution_details'):
        return None
    back = redirect(url_for('consumer_protection.view_complaint', id=id))
    if not current_user.can_edit('consumer_protection'):
        flash(_('You do not have permission to change complaints.'), 'danger')
        return back
    if action == 'assign':
        uid = request.form.get('assigned_to', type=int)
        staff = {u['id']: u['name'] for u in _complaint_staff()}
        if uid not in staff:
            flash(_('Select a staff member who handles complaints.'), 'danger')
            return back
        if uid == complaint.get('assigned_to_user_id'):
            flash(_('The complaint is already assigned to this person.'), 'info')
            return back
        reason = (request.form.get('reason') or '').strip()
        if complaint.get('assigned_to_user_id') and not reason:
            flash(_('A reason is required when reassigning a complaint.'), 'danger')
            return back
        ConsumerComplaint.assign(id, uid, current_user.id, reason)
        ComplaintActivityLog.create({'complaint_id': id, 'activity_type': 'ASSIGNMENT',
                                     'activity_description': f"Assigned to {staff[uid]}" + (f" — {reason}" if reason else ''),
                                     'performed_by': current_user.id})
        try:
            from services.notification_service import notify
            if uid != current_user.id:
                notify(uid, f'Complaint CP-{id} assigned to you', complaint.get('complaint_subject') or '',
                       link=url_for('consumer_protection.view_complaint', id=id), category='warning')
        except Exception:
            current_app.logger.exception('complaint assignment notification failed')
        flash(_('Owner updated.'), 'success')
    elif action == 'add_note':
        note = (request.form.get('note') or '').strip()
        if not note:
            flash(_('The note is empty.'), 'warning')
            return back
        ComplaintInternalNote.add(id, note[:4000], current_user.id)
        ComplaintActivityLog.create({'complaint_id': id, 'activity_type': 'INTERNAL_NOTE',
                                     'activity_description': 'Internal note added', 'performed_by': current_user.id})
        flash(_('Internal note added.'), 'success')
    else:
        err, clean = H.validate_resolution_details(
            request.form.get('root_cause_category'), request.form.get('redress_type'),
            request.form.get('redress_amount'), request.form.get('redress_date'))
        if err:
            flash(_RES_ERRORS[err](), 'danger')
            return back
        ConsumerComplaint.set_resolution_details(id, **clean)
        desc = f"Root cause: {clean['root_cause_category']}; redress: {clean['redress_type']}"
        if clean['redress_amount']:
            desc += f" {clean['redress_amount']:.2f}"
        if clean['redress_date']:
            desc += f" on {clean['redress_date']}"
        ComplaintActivityLog.create({'complaint_id': id, 'activity_type': 'RESOLUTION_DETAILS',
                                     'activity_description': desc, 'performed_by': current_user.id})
        flash(_('Root cause and redress recorded.'), 'success')
    return back


@consumer_bp.route('/complaint/<int:id>', methods=['GET', 'POST'])
@login_required
@permission_required('consumer_protection')
def view_complaint(id):
    """View and manage a specific complaint"""
    complaint = ConsumerComplaint.get_by_id(id)
    if not complaint:
        return render_template('errors/404.html'), 404
        
    logs = ComplaintActivityLog.get_logs(id)
    # Fetch attachments
    documents = ComplaintDocument.get_by_complaint_id(id)
    
    if request.method == 'POST':
        handled = _staff_action(id, complaint)
        if handled is not None:
            return handled
        try:
            action = request.form.get('action')
            
            if action == 'update_status':
                new_status = (request.form.get('status') or '').strip().upper()
                old_status = complaint['status']
                resolution = (request.form.get('resolution_summary') or '').strip()
                if new_status not in COMPLAINT_STATUSES:
                    flash(_('Invalid status.'), 'danger')
                    return redirect(url_for('consumer_protection.view_complaint', id=id))
                if new_status in ('RESOLVED', 'CLOSED') and not (resolution or complaint.get('resolution_summary')):
                    flash(_('A resolution is required to resolve or close a complaint. The customer sees it when tracking the complaint.'), 'danger')
                    return redirect(url_for('consumer_protection.view_complaint', id=id))
                if new_status in ('RESOLVED', 'CLOSED') and not complaint.get('root_cause_category'):
                    flash(_('Record the root cause and redress before resolving or closing the complaint.'), 'danger')
                    return redirect(url_for('consumer_protection.view_complaint', id=id))

                ConsumerComplaint.update_status(id, new_status, current_user.id,
                                                resolution_summary=resolution or None)
                
                # Handle file uploads
                if 'attachments' in request.files:
                    files = request.files.getlist('attachments')
                    for file in files:
                        if file and allowed_file(file.filename):
                            filename = secure_filename(file.filename)
                            upload_dir = os.path.join(current_app.root_path, 'uploads', 'complaints', str(id))
                            os.makedirs(upload_dir, exist_ok=True)
                            
                            file_path = os.path.join(upload_dir, filename)
                            file.save(file_path)
                            
                            # Record in DB
                            doc_data = {
                                'complaint_id': id,
                                'file_name': filename,
                                'file_path': f"uploads/complaints/{id}/{filename}",
                                'uploaded_by': current_user.id
                            }
                            ComplaintDocument.create(doc_data)
                
                # Log
                log_data = {
                    'complaint_id': id,
                    'activity_type': 'STATUS_CHANGE',
                    'activity_description': f"Status changed from {old_status} to {new_status}",
                    'old_status': old_status,
                    'new_status': new_status,
                    'performed_by': current_user.id
                }
                ComplaintActivityLog.create(log_data)
                
                flash(_('Complaint updated successfully'), 'success')
                return redirect(url_for('consumer_protection.view_complaint', id=id))

        except Exception as e:
            current_app.logger.error(f"Error updating complaint: {e}")
            flash(_('Error updating complaint'), 'danger')
            
    category = get_db().execute("SELECT category_name_en, category_name_ar FROM complaint_categories "
                                "WHERE category_code = %s", (complaint.get('complaint_category'),)).fetchone()
    return render_template('consumer_protection/view.html', complaint=complaint, logs=logs, documents=documents,
                           notes=ComplaintInternalNote.list(id), staff=_complaint_staff(),
                           category=dict(category) if category else None,
                           root_causes=H.ROOT_CAUSES, redress_types=H.REDRESS_TYPES,
                           can_edit=current_user.can_edit('consumer_protection'))


@consumer_bp.route('/complaint/<int:id>/letter')
@login_required
@permission_required('consumer_protection')
def response_letter(id):
    """Printable customer response letter (Arabic or English) generated from the recorded resolution."""
    from flask_babel import force_locale
    complaint = ConsumerComplaint.get_by_id(id)
    if not complaint:
        return render_template('errors/404.html'), 404
    lang = request.args.get('lang') if request.args.get('lang') in ('ar', 'en') else 'ar'
    cat = get_db().execute("SELECT category_name_en, category_name_ar FROM complaint_categories "
                           "WHERE category_code = %s", (complaint.get('complaint_category'),)).fetchone()
    category = (cat['category_name_ar'] if lang == 'ar' else cat['category_name_en']) if cat else complaint.get('complaint_category')
    with force_locale(lang):
        return render_template('consumer_protection/letter.html', c=complaint, lang=lang, category=category,
                               is_final=complaint.get('status') in H.DONE and bool(complaint.get('resolution_summary')),
                               today=datetime.now().strftime('%Y-%m-%d'))


@consumer_bp.route('/reports/periodic')
@login_required
@permission_required('consumer_protection')
def periodic_report():
    """Periodic complaints report for submission to the regulator: received in the period, by
    category / status / channel, average resolution days, overdue, full list. CSV / Excel export."""
    period = request.args.get('period') or 'month'
    start, end = H.period_bounds(period, request.args.get('start'), request.args.get('end'))
    db = get_db()
    report = H.summarize(H.fetch(db, start, end))
    cats = {r['category_code']: (r['category_name_ar'] if str(get_locale()) == 'ar' else r['category_name_en'])
            for r in db.execute("SELECT category_code, category_name_en, category_name_ar FROM complaint_categories").fetchall()}
    fmt = request.args.get('format')
    if fmt in ('csv', 'xlsx'):
        return _export_periodic(report, cats, start, end, fmt)
    return render_template('consumer_protection/periodic_report.html', r=report, cats=cats, period=period,
                           start=start, end=end)


def _export_periodic(report, cats, start, end, fmt):
    from cases.labels import label
    from flask import Response
    head = [_('Reference'), _('Received'), _('Category'), _('Channel'), _('Status'), _('Owner'),
            _('Statutory Deadline'), _('Resolution days'), _('Overdue'), _('Root cause'), _('Redress'),
            _('Redress amount'), _('Redress date')]
    lines = []
    for c in report['rows']:
        lines.append([f"CP-{c['id']}", (c.get('created_at') or '')[:10], cats.get(c.get('complaint_category'), c.get('complaint_category')),
                      label(c.get('complaint_channel')), label(c.get('status')), c.get('owner_name') or '',
                      c.get('statutory_deadline_date') or '', c.get('resolution_days') if c.get('resolution_days') is not None else '',
                      _('Yes') if c.get('overdue') else _('No'), label(c.get('root_cause_category')) if c.get('root_cause_category') else '',
                      label(c.get('redress_type')) if c.get('redress_type') else '',
                      float(c['redress_amount']) if c.get('redress_amount') is not None else '',
                      str(c.get('redress_date') or '')])
    summary = [[_('Period'), f"{start} — {end}"], [_('Complaints received'), report['total']],
               [_('Resolved / closed'), report['resolved']], [_('Open'), report['open']],
               [_('Average resolution days'), report['avg_resolution_days'] if report['avg_resolution_days'] is not None else '-'],
               [_('Open past deadline'), report['overdue_open']], [_('Resolved after deadline'), report['resolved_late']]]
    breakdowns = [(_('By category'), {cats.get(k, k): v for k, v in report['by_category'].items()}),
                  (_('By status'), {label(k): v for k, v in report['by_status'].items()}),
                  (_('By channel'), {label(k): v for k, v in report['by_channel'].items()})]
    fname = f"complaints_report_{start}_{end}"
    if fmt == 'csv':
        import csv, io as _io
        out = _io.StringIO()
        w = csv.writer(out)
        for row in summary:
            w.writerow(row)
        for title, data in breakdowns:
            w.writerow([])
            w.writerow([title])
            for k, v in data.items():
                w.writerow([k, v])
        w.writerow([])
        w.writerow(head)
        w.writerows(lines)
        return Response(out.getvalue().encode('utf-8-sig'), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename={fname}.csv'})
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = 'Summary'
    for row in summary:
        ws.append([str(x) if not isinstance(x, (int, float)) else x for x in row])
    for title, data in breakdowns:
        ws.append([])
        ws.append([str(title)])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        for k, v in data.items():
            ws.append([str(k), v])
    ws2 = wb.create_sheet('Complaints')
    ws2.append([str(h) for h in head])
    for cell in ws2[1]:
        cell.font = Font(bold=True)
    for ln in lines:
        ws2.append([x if isinstance(x, (int, float)) else str(x) for x in ln])
    if str(get_locale()) == 'ar':
        ws.sheet_view.rightToLeft = True
        ws2.sheet_view.rightToLeft = True
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f'{fname}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@consumer_bp.route('/document/<int:doc_id>/download')
@login_required
@permission_required('consumer_protection')
def download_document(doc_id):
    """Serve a complaint attachment — same authorization guard as viewing the complaint."""
    doc = ComplaintDocument.get_by_id(doc_id)
    if not doc:
        flash(_('Document not found.'), 'danger')
        return redirect(url_for('consumer_protection.complaints_list'))
    return serve_uploaded_file(doc['file_path'], download_name=doc['file_name'])


@consumer_bp.route('/complaint/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_complaint(id):
    flash(gettext('Edit functionality is merged with the View screen.'), 'info')
    return redirect(url_for('consumer_protection.view_complaint', id=id))
