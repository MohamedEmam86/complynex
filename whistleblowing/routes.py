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
Whistleblowing Module - Enhanced Flask Routes with Public Anonymous Submission
===============================================================================
100% Free Implementation for ComplyNex CMS

New Features:
- /whistleblowing/anonymous - Information page with privacy tips
- /whistleblowing/report - Ultra-secure public submission (no login ever)
- Enhanced anonymity protection
"""

from flask_babel import gettext as _
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file, session
from flask_login import login_required, current_user
from database.db import get_db
from .models import WhistleblowingCase, WhistleblowingAttachment, WhistleblowingCategory
from utils.decorators import permission_required
from utils.email import send_confirmation_email
from extensions import csrf, limiter
from utils.file_validator import validate_file, secure_filename_strict
from flask_babel import get_locale
import logging
import io

logger = logging.getLogger(__name__)

whistleblowing_bp = Blueprint('whistleblowing', __name__, url_prefix='/whistleblowing')

# ============================================
# PUBLIC ROUTES (Anonymous Access - No Login Required)
# ============================================

@whistleblowing_bp.route('/anonymous', methods=['GET'])
def anonymous_info():
    """
    Public information page about anonymous whistleblowing.
    Accessible to anyone - no login required.
    Includes:
    - Whistleblower protection laws
    - Privacy tips
    - Anonymity guarantees
    - How the process works
    """
    categories = WhistleblowingCategory.get_all_categories()
    
    # Protection laws and policies
    protection_info = {
        'egypt_law': _('Egyptian Labor Law No. 12/2003 protects whistleblowers from retaliation'),
        'cbe_regulation': _('Central Bank of Egypt mandates confidential reporting mechanisms'),
        'company_policy': _('ComplyNex has a strict zero-tolerance policy for whistleblower retaliation'),
        'penalties': _('Retaliation against whistleblowers is grounds for immediate termination')
    }
    
    return render_template('whistleblowing/anonymous_info.html', 
                         categories=categories,
                         protection_info=protection_info)


@whistleblowing_bp.route('/report', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def public_report():
    """
    Ultra-secure public reporting page.
    
    Features:
    - Completely anonymous (no login required)
    - No cookies or tracking
    - No IP logging
    - Always anonymous regardless of user input
    - Designed for people with high fear of retaliation
    
    Can be accessed via:
    - Direct link: https://complynex.online/whistleblowing/report
    - Shared externally
    """
    if request.method == 'GET':
        categories = WhistleblowingCategory.get_all_categories()
        
        # Privacy recommendations for users
        privacy_tips = {
            'browser': {
                'title': _('Use Private Browsing'),
                'description': _('Use Incognito (Chrome) or Private (Firefox/Safari) mode'),
                'icon': 'fa-user-secret'
            },
            'network': {
                'title': _('Secure Your Connection'),
                'description': _('Consider using VPN or Tor Browser for maximum privacy'),
                'icon': 'fa-shield-alt'
            },
            'location': {
                'title': _('Submit from Public WiFi'),
                'description': _('Use cafe, library, or public WiFi instead of company network'),
                'icon': 'fa-wifi'
            },
            'device': {
                'title': _('Use Personal Device'),
                'description': _('Do not use company computer or phone'),
                'icon': 'fa-mobile-alt'
            },
            'cleanup': {
                'title': _('Clear Your Traces'),
                'description': _('Clear browser history, cookies, and cache after submission'),
                'icon': 'fa-broom'
            }
        }
        
        # What we DON'T collect
        no_collection = [
            _('IP addresses'),
            _('Browser fingerprints'),
            _('Location data'),
            _('Device information'),
            _('Cookies or tracking pixels'),
            _('Login credentials')
        ]
        
        return render_template('whistleblowing/public_report.html', 
                             categories=categories,
                             privacy_tips=privacy_tips,
                             no_collection=no_collection)
    
    # POST - Handle submission (always anonymous)
    try:
        data = request.form.to_dict()
        
        # Validate required fields
        if not data.get('title') or not data.get('description') or not data.get('incident_type'):
            return jsonify({
                'success': False,
                'error': _('Please provide title, description, and incident type')
            }), 200
        
        # Validate description length
        if len(data.get('description', '')) < 50:
            return jsonify({
                'success': False,
                'error': _('Description must be at least 50 characters')
            }), 200
        
        # FORCE anonymous submission (ignore any user data)
        # Even if somehow a logged-in user accesses this, it stays anonymous
        result = WhistleblowingCase.create(
            data=data,
            is_anonymous=True,  # ALWAYS anonymous
            submitter_id=None  # NEVER store user ID
        )
        
        # Handle file uploads (if any)
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            for file in files:
                if file and file.filename:
                    # Validate file size (10MB max)
                    file.seek(0, 2)  # Seek to end
                    file_size = file.tell()
                    file.seek(0)  # Reset to beginning
                    
                    if file_size > 10 * 1024 * 1024:  # 10MB
                        continue  # Skip files over 10MB
                    
                    WhistleblowingAttachment.save_attachment(
                        case_id=result['case_id'],
                        file=file,
                        uploaded_by=None  # ALWAYS anonymous
                    )
        
        # Log successful submission (without any identifying info)
        logger.info(f"Anonymous public report submitted: {result['case_number']}")

        # Send confirmation email if email provided (optional)
        if data.get('email'):
            template = 'emails/whistleblowing_confirmation_ar.html' if get_locale() == 'ar' else 'emails/whistleblowing_confirmation.html'
            send_confirmation_email(
                to_email=data.get('email'),
                subject=_('Whistleblowing Report Received'),
                template=template,
                case_number=result['case_number'],
                anonymous_code=result['anonymous_code']
            )
        
        return jsonify({
            'success': True,
            'message': _('Your anonymous report has been submitted securely.'),
            'case_number': result['case_number'],
            'anonymous_code': result['anonymous_code'],
            'instructions': _('Save this code to track your case. This is the only way to access your report.')
        })
            
    except Exception as e:
        logger.error(f"Public case submission failed: {e}")
        return jsonify({'success': False, 'error': _('Submission failed. Please try again.')}), 500


@whistleblowing_bp.route('/submit', methods=['GET', 'POST'])
@csrf.exempt
@limiter.limit('5 per minute', methods=['POST'])
def submit_case():
    """
    Standard whistleblowing submission form.
    Accessible without login for anonymous reporting.
    Users can choose to submit anonymously or with identity.
    """
    if request.method == 'GET':
        categories = WhistleblowingCategory.get_all_categories()
        return render_template('whistleblowing/submit.html', categories=categories)
    
    # POST - Handle submission
    try:
        data = request.form.to_dict()
        is_anonymous = data.get('is_anonymous') == 'true'
        
        # Validate required fields
        if not data.get('title') or not data.get('description') or not data.get('incident_type'):
            return jsonify({
                'success': False,
                'error': _('Please provide title, description, and incident type')
            }), 200
        
        # Create case
        result = WhistleblowingCase.create(
            data=data,
            is_anonymous=is_anonymous,
            submitter_id=current_user.id if current_user.is_authenticated and not is_anonymous else None
        )
        
        # Handle file uploads
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            for file in files:
                if file.filename:
                    is_valid, err = validate_file(file, 'document')
                    if not is_valid:
                        return jsonify({'success': False, 'error': f'Invalid file: {err}'}), 400
                    WhistleblowingAttachment.save_attachment(
                        case_id=result['case_id'],
                        file=file,
                        uploaded_by=current_user.id if current_user.is_authenticated and not is_anonymous else None
                    )
        
        # Return response
        if is_anonymous:
            # Send confirmation email if email provided
            if data.get('email'):
                template = 'emails/whistleblowing_confirmation_ar.html' if get_locale() == 'ar' else 'emails/whistleblowing_confirmation.html'
                send_confirmation_email(
                    to_email=data.get('email'),
                    subject=_('Whistleblowing Report Received'),
                    template=template,
                    case_number=result['case_number'],
                    anonymous_code=result['anonymous_code']
                )

            return jsonify({
                'success': True,
                'message': _('Your report has been submitted anonymously.'),
                'case_number': result['case_number'],
                'anonymous_code': result['anonymous_code'],
                'instructions': _('Save this code to track your case: %(code)s', code=result['anonymous_code'])
            })
        else:
            # Send confirmation email for logged in user or if email provided
            email = data.get('email') or (current_user.email if current_user.is_authenticated else None)
            if email:
                template = 'emails/whistleblowing_confirmation_ar.html' if get_locale() == 'ar' else 'emails/whistleblowing_confirmation.html'
                send_confirmation_email(
                    to_email=email,
                    subject=_('Whistleblowing Report Received'),
                    template=template,
                    case_number=result['case_number'],
                    case_id=result['case_id']
                )

            return jsonify({
                'success': True,
                'message': _('Your report has been submitted successfully.'),
                'case_number': result['case_number'],
                'case_id': result['case_id']
            })
            
    except Exception as e:
        import traceback
        logger.error(f"Case submission failed: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


@whistleblowing_bp.route('/track', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def track_case():
    """
    Track an anonymous case using access code.
    No login required.
    """
    if request.method == 'GET':
        return render_template('whistleblowing/track.html')
    
    # POST - Retrieve case
    anonymous_code = request.form.get('anonymous_code')
    
    if not anonymous_code:
        flash(_('Please enter your case tracking code.'), 'warning')
        return redirect(url_for('whistleblowing.track_case'))
    
    case = WhistleblowingCase.get_by_anonymous_code(anonymous_code)
    
    if not case:
        flash(_('Invalid or expired tracking code.'), 'error')
        return redirect(url_for('whistleblowing.track_case'))
    
    # Return case details (limited info for anonymous)
    return render_template('whistleblowing/case_status.html', case=case, is_anonymous=True)


# ============================================
# ADMIN ROUTES (Requires Login & Permissions)
# ============================================

@whistleblowing_bp.route('/')
@whistleblowing_bp.route('/dashboard')
@whistleblowing_bp.route('/cases')
@login_required
@permission_required('whistleblowing')
def dashboard():
    """
    Whistleblowing dashboard for compliance officers.
    """
    
    # Get statistics
    stats = WhistleblowingCase.get_statistics()
    
    # Get recent cases
    filters = {'status': request.args.get('status')} if request.args.get('status') else None
    cases = WhistleblowingCase.get_all_cases(filters=filters, limit=20)
    
    return render_template('whistleblowing/dashboard.html', stats=stats, cases=cases)


@whistleblowing_bp.route('/case/<int:case_id>')
@login_required
@permission_required('whistleblowing')
def view_case(case_id):
    """
    View case details (compliance officer only).
    """
    
    case = WhistleblowingCase.get_by_id(case_id, include_updates=True)
    
    if not case:
        flash(_('Case not found.'), 'error')
        return redirect(url_for('whistleblowing.dashboard'))
    
    # Get attachments
    db = get_db()
    attachments = db.execute(
        "SELECT * FROM whistleblowing_attachments WHERE case_id = %s",
        (case_id,)
    ).fetchall()
    
    # Get all users for assignment
    from models.user import User
    users = User.get_all()
    
    return render_template('whistleblowing/case_detail.html', 
                           case=case, 
                           attachments=attachments,
                           updates=case.get('updates', []),
                           users=users)

@whistleblowing_bp.route('/case/<int:case_id>/update', methods=['POST'])
@login_required
@permission_required('whistleblowing', level='edit')
def add_update(case_id):
    """
    Handle case update form submission (status change and/or comment).
    """
    
    update_text = request.form.get('update_text')
    new_status = request.form.get('new_status')
    
    if not update_text:
        flash(_('Please provide an update note.'), 'warning')
        return redirect(url_for('whistleblowing.view_case', case_id=case_id))
    
    try:
        if new_status:
            # Perform status update which also adds an update record
            WhistleblowingCase.update_status(
                case_id=case_id,
                new_status=new_status,
                updated_by=current_user.id,
                note=update_text
            )
        else:
            # Just add a comment/note
            WhistleblowingCase.add_update(
                case_id=case_id,
                update_type='INVESTIGATION_NOTE',
                update_text=update_text,
                created_by=current_user.id
            )
        
        # Handle investigator attachments
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            for file in files:
                if file and file.filename:
                    from .models import WhistleblowingAttachment
                    WhistleblowingAttachment.save_attachment(
                        case_id=case_id,
                        file=file,
                        uploaded_by=current_user.id,
                        description=f"Evidence attached to update by {current_user.username}"
                    )
        
        flash(_('Case updated successfully.'), 'success')
    except Exception as e:
        logger.error(f"Failed to update case {case_id}: {e}")
        flash(_('Failed to update case.'), 'error')
        
    return redirect(url_for('whistleblowing.view_case', case_id=case_id))


@whistleblowing_bp.route('/case/<int:case_id>/quick_status', methods=['POST'])
@login_required
@permission_required('whistleblowing', level='edit')
def quick_status(case_id):
    """Handle incredibly fast status toggles from the dashboard."""
    new_status = request.form.get('status')
    if new_status in ['UNDER_REVIEW', 'RESOLVED', 'CLOSED']:
        try:
            WhistleblowingCase.update_status(
                case_id=case_id,
                new_status=new_status,
                updated_by=current_user.id,
                note=f"Dashboard quick action: Marked as {new_status}"
            )
            flash(_('Case status updated via quick-action.'), 'success')
        except Exception as e:
            logger.error(f"Failed to quick update case {case_id}: {e}")
            flash(_('Failed to quickly update case.'), 'error')
    return redirect(url_for('whistleblowing.dashboard'))


@whistleblowing_bp.route('/api/update-status', methods=['POST'])
@login_required
@permission_required('whistleblowing', level='edit')
def update_status():
    """Update case status"""
    
    data = request.get_json()
    case_id = data.get('case_id')
    new_status = data.get('status')
    note = data.get('note')
    
    if not case_id or not new_status:
        return jsonify({'success': False, 'error': _('Missing required fields')}), 400
    
    try:
        WhistleblowingCase.update_status(
            case_id=case_id,
            new_status=new_status,
            updated_by=current_user.id,
            note=note
        )
        return jsonify({'success': True, 'message': _('Status updated successfully')})
    except Exception as e:
        logger.error(f"Status update failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@whistleblowing_bp.route('/api/assign-case', methods=['POST'])
@login_required
@permission_required('whistleblowing', level='edit')
def assign_case():
    """Assign case to investigator"""
    
    data = request.get_json()
    case_id = data.get('case_id')
    assigned_to = data.get('assigned_to')
    note = data.get('note')
    
    if not case_id or not assigned_to:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    
    try:
        WhistleblowingCase.assign_case(
            case_id=case_id,
            assigned_to=assigned_to,
            assigned_by=current_user.id,
            note=note
        )
        return jsonify({'success': True, 'message': _('Case assigned successfully')})
    except Exception as e:
        logger.error(f"Assignment failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@whistleblowing_bp.route('/api/resolve-case', methods=['POST'])
@login_required
@permission_required('whistleblowing', level='edit')
def resolve_case():
    """Resolve a case"""
    
    data = request.get_json()
    case_id = data.get('case_id')
    resolution_summary = data.get('resolution_summary')
    resolution_action = data.get('resolution_action')
    
    if not case_id or not resolution_summary:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    
    try:
        WhistleblowingCase.resolve_case(
            case_id=case_id,
            resolution_summary=resolution_summary,
            resolution_action=resolution_action,
            resolved_by=current_user.id
        )
        return jsonify({'success': True, 'message': _('Case resolved successfully')})
    except Exception as e:
        logger.error(f"Resolution failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@whistleblowing_bp.route('/api/add-comment', methods=['POST'])
@login_required
@permission_required('whistleblowing', level='edit')
def add_comment():
    """Add comment to case"""
    
    data = request.get_json()
    case_id = data.get('case_id')
    comment = data.get('comment')
    visible_to_submitter = 1 if data.get('visible_to_submitter', True) else 0
    
    if not case_id or not comment:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    
    try:
        WhistleblowingCase.add_update(
            case_id=case_id,
            update_type='COMMENT',
            update_text=comment,
            created_by=current_user.id,
            visible_to_submitter=visible_to_submitter
        )
        return jsonify({'success': True, 'message': _('Comment added successfully')})
    except Exception as e:
        logger.error(f"Comment addition failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@whistleblowing_bp.route('/api/download-attachment/<int:attachment_id>')
@login_required
@permission_required('whistleblowing')
def download_attachment(attachment_id):
    """
    Download and decrypt attachment.
    """
    
    try:
        file_content, original_filename, mime_type = WhistleblowingAttachment.decrypt_attachment(attachment_id)
        
        if not file_content:
            flash(_('Attachment not found.'), 'error')
            return redirect(request.referrer or url_for('whistleblowing.dashboard'))
        
        return send_file(
            io.BytesIO(file_content),
            mimetype=mime_type,
            as_attachment=True,
            download_name=original_filename
        )
    except Exception as e:
        logger.error(f"Attachment download failed: {e}")
        flash(_('Failed to download attachment.'), 'error')
        return redirect(request.referrer or url_for('whistleblowing.dashboard'))


@whistleblowing_bp.route('/api/statistics')
@login_required
@permission_required('whistleblowing')
def get_statistics():
    """Get statistics API"""
    
    stats = WhistleblowingCase.get_statistics()
    return jsonify({'success': True, 'stats': stats})


@whistleblowing_bp.route('/reports')
@login_required
@permission_required('whistleblowing')
def reports():
    """
    Generate whistleblowing reports for CBE.
    """
    
    stats = WhistleblowingCase.get_statistics()
    
    # Get cases for date range
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    db = get_db()
    query = "SELECT * FROM whistleblowing_cases WHERE 1=1"
    params = []
    
    if start_date:
        query += " AND date(submitted_at) >= %s"
        params.append(start_date)
    if end_date:
        query += " AND date(submitted_at) <= %s"
        params.append(end_date)
    
    query += " ORDER BY submitted_at DESC"
    
    cases = db.execute(query, params).fetchall()
    
    return render_template('whistleblowing/reports.html', stats=stats, cases=cases)


# ============================================
# MY CASES (For logged-in users)
# ============================================

@whistleblowing_bp.route('/my-cases')
@login_required
def my_cases():
    """
    Show logged-in user's own submissions.
    """
    db = get_db()
    cases = db.execute("""
        SELECT * FROM whistleblowing_cases 
        WHERE submitter_id = %s AND is_anonymous = 0
        ORDER BY submitted_at DESC
    """, (current_user.id,)).fetchall()
    
    return render_template('whistleblowing/my_cases.html', cases=cases)


# =============================================================================
# Assignment engine (Phase 4)
# =============================================================================

@whistleblowing_bp.route('/case/<int:case_id>/assign', methods=['POST'])
@login_required
def case_assignment(case_id):
    from services import whistleblowing_service as W
    ok, msg = W.assign(
        case_id,
        request.form.get('assigned_to') or None,
        current_user.id,
        action=request.form.get('action_type') or 'assign',
        reason=request.form.get('reason'),
        comments=request.form.get('comments'),
        to_org_unit_id=request.form.get('to_org_unit_id') or None,
        sla_days=int(request.form.get('sla_days') or 5))
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('whistleblowing.view_case', case_id=case_id))


@whistleblowing_bp.route('/case/<int:case_id>/remind', methods=['POST'])
@login_required
def case_remind(case_id):
    from services import whistleblowing_service as W
    sent, skipped = W.send_reminder(case_id, current_user.id,
                                    message=request.form.get('message') or None,
                                    to=request.form.get('to') or 'assignee')
    if sent:
        flash(f'Reminder sent to {sent} recipient(s).', 'success')
    else:
        flash('No reminder sent — the case has no current owner to remind.', 'warning')
    return redirect(url_for('whistleblowing.view_case', case_id=case_id))


@whistleblowing_bp.route('/tracking')
@login_required
def case_tracking():
    """One board answering "where does every case sit and who owns it".

    24 of 25 cases had no owner at all when this was built; without a view like
    this there was no way to notice.
    """
    from database.db import query_db
    from services import whistleblowing_service as W
    rows = query_db("SELECT id FROM whistleblowing_cases ORDER BY id DESC")
    cases = [W.tracking(dict(r)['id']) for r in rows]
    cases = [c for c in cases if c]
    return render_template('whistleblowing/tracking.html', cases=cases,
        summary={
            'total': len(cases),
            'unassigned': sum(1 for c in cases if c['unassigned']),
            'breached': sum(1 for c in cases if c['sla_status'] == 'breached'),
            'due_soon': sum(1 for c in cases if c['sla_status'] == 'due_soon'),
        })


@whistleblowing_bp.route('/tracking/remind-bulk', methods=['POST'])
@login_required
def bulk_remind():
    from services import whistleblowing_service as W
    ids = [int(x) for x in request.form.getlist('case_ids') if x.isdigit()]
    if not ids:
        flash('Select at least one case.', 'warning')
        return redirect(url_for('whistleblowing.case_tracking'))
    sent, skipped = W.send_reminder(ids, current_user.id,
                                    message=request.form.get('message') or None)
    msg = f'Reminders sent for {sent} case(s).'
    if skipped:
        msg += f' {len(skipped)} skipped (no current owner): {", ".join(str(x) for x in skipped[:5])}'
    flash(msg, 'success' if sent else 'warning')
    return redirect(url_for('whistleblowing.case_tracking'))
