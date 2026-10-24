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
Employee Portal Routes - Public Access for All Employees
Unified submission portal for annual declarations and incident reports
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_babel import gettext as _
from flask_login import login_required, current_user
from datetime import datetime
import uuid

portal_bp = Blueprint('portal', __name__, url_prefix='/portal')

@portal_bp.before_request
def before_request():
    """Ensure all portal routes require login and redirect to portal login specifically."""
    if not current_user.is_authenticated:
        return redirect(url_for('auth.portal_login'))


def get_db():
    """Get database connection."""
    from database.db import get_db as db_get
    return db_get()


def generate_tracking_id():
    """Generate a unique tracking ID for submissions."""
    return str(uuid.uuid4())[:8].upper()


def check_annual_coi_submission(email, year=None):
    """Check if employee has submitted annual COI for the year."""
    db = get_db()
    current_year = year or datetime.now().year
    
    # First find the user by email
    user = db.execute('SELECT id FROM users WHERE email = %s', (email,)).fetchone()
    if not user:
        return {'exists': False, 'submitted': False, 'user_id': None}
    
    # Check for COI declaration in active campaigns for this year
    result = db.execute('''
        SELECT d.id, d.created_at, d.status 
        FROM coi_declarations d
        JOIN coi_campaigns c ON d.campaign_id = c.id
        WHERE d.employee_id = %s AND c.campaign_year = %s
        ORDER BY d.created_at DESC
        LIMIT 1
    ''', (user['id'], current_year)).fetchone()
    
    return {
        'exists': True,
        'submitted': result is not None,
        'user_id': user['id'],
        'submission_date': result['created_at'] if result else None,
        'status': result['status'] if result else None,
        'id': result['id'] if result else None
    }


def check_annual_cobec_submission(email, year=None):
    """Check if employee has submitted annual COBEC for the year."""
    db = get_db()
    current_year = year or datetime.now().year
    
    # First find the user by email
    user = db.execute('SELECT id FROM users WHERE email = %s', (email,)).fetchone()
    if not user:
        return {'exists': False, 'submitted': False, 'user_id': None}
    
    # Check for COBEC declaration for this year
    result = db.execute('''
        SELECT id, created_at, status 
        FROM cobec_declarations
        WHERE employee_id = %s AND declaration_year = %s
        ORDER BY created_at DESC
        LIMIT 1
    ''', (user['id'], current_year)).fetchone()
    
    return {
        'exists': True,
        'submitted': result is not None,
        'user_id': user['id'],
        'submission_date': result['created_at'] if result else None,
        'status': result['status'] if result else None
    }


# ============================================
# Main Landing Page / Dashboard
# ============================================
@portal_bp.route('/')
@portal_bp.route('/dashboard')
@login_required
def dashboard():
    """Main Employee Portal Dashboard."""
    if not current_user.role == 'employee':
         # If admin/manager accesses portal, let them see it but maybe warn%s
         # For now, allow access.
         pass

    db = get_db()
    current_year = datetime.now().year
    
    # Check COI Status
    coi_status = check_annual_coi_submission(current_user.email, current_year)
    
    # Check COBEC Status
    cobec_status = check_annual_cobec_submission(current_user.email, current_year)
    
    # Check Pending Policies
    pending_policies_count = 0
    from models.policy import Policy
    all_policies = Policy.get_published(only_public=True)
    
    acknowledged = db.execute(
        'SELECT policy_id FROM policy_acknowledgments WHERE employee_id = %s', 
        (current_user.id,)
    ).fetchall()
    ack_ids = [r['policy_id'] for r in acknowledged]
    
    pending_policies_count = sum(1 for p in all_policies if p.id not in ack_ids)
    
    # Check Training Due
    training_due_count = 0 
    from models.training import TrainingCourse, TrainingEnrollment
    enrollments = TrainingEnrollment.get_user_enrollments(current_user.id)
    # Count Enrolled/In Progress
    training_due_count = sum(1 for e in enrollments if e.status in ['enrolled', 'in_progress'])
    
    # Check Whistleblowing Cases
    whistleblowing_count = db.execute(
        'SELECT COUNT(*) as count FROM whistleblowing_cases WHERE submitter_id = %s OR submitter_email = %s',
        (current_user.id, current_user.email)
    ).fetchone()['count']
    
    # CMS Access Link
    can_access_cms = current_user.can_access_cms()
    
    return render_template('portal/dashboard.html', 
                           current_year=current_year,
                           coi_status=coi_status,
                           cobec_status=cobec_status,
                           pending_policies_count=pending_policies_count,
                           training_due_count=training_due_count,
                           whistleblowing_count=whistleblowing_count,
                           can_access_cms=can_access_cms,
                           recent_activities=[]) # Placeholder for activity log


@portal_bp.route('/training')
@login_required
def training_list():
    """List training courses for the logged-in employee."""
    user_id = current_user.id
    
    # Get mandatory and optional courses they aren't enrolled in yet
    from models.training import TrainingCourse, TrainingEnrollment
    all_courses = TrainingCourse.get_all()
    
    # Get existing enrollments
    enrollments = TrainingEnrollment.get_user_enrollments(user_id)
    enrolled_course_ids = [e.course_id for e in enrollments]
    
    # Filter courses not yet enrolled
    available_mandatory = [c for c in all_courses if c.is_mandatory and c.id not in enrolled_course_ids]
    available_optional = [c for c in all_courses if not c.is_mandatory and c.id not in enrolled_course_ids]
    
    return render_template('portal/training_list.html', 
                           user=current_user, 
                           enrollments=enrollments,
                           available_mandatory=available_mandatory,
                           available_optional=available_optional,
                           email=current_user.email,
                           now=datetime.now())


@portal_bp.route('/policies')
@login_required
def policy_list():
    """List policies for the logged-in employee."""
    from models.policy import Policy
    from database.db import get_db as _gdb

    # Get all published policies
    all_policies = Policy.get_published(only_public=False)

    # Get user dept codes for owner_function matching
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

    def can_see(p):
        if p.is_public:
            return True
        if p.department_id and current_user.has_department_access(p.department_id):
            return True
        if not p.department_id and p.owner_function:
            of = p.owner_function.upper()
            for code in user_dept_codes:
                if code in of:
                    return True
        return False

    policies = [p for p in all_policies if can_see(p)]
    
    db = get_db()
    # Get acknowledgment status for each policy
    ack_ids = db.execute(
        'SELECT policy_id FROM policy_acknowledgments WHERE employee_id = %s', 
        (current_user.id,)
    ).fetchall()
    ack_ids = [r['policy_id'] for r in ack_ids]
    
    # Attach status to each policy object
    for p in policies:
        p.is_signed = p.id in ack_ids
        # FORCE: All policies in portal are mandatory for employees
        p.is_mandatory = True
        # Priority for mandatory policies
        p.sort_key = 0 if (not p.is_signed) else 1
    
    # Sort: Mandatory unsigned first
    policies.sort(key=lambda x: (x.sort_key, x.created_at or ''), reverse=False)
    
    return render_template('portal/policy_list.html', 
                          user=current_user, 
                          policies=policies,
                          email=current_user.email,
                          now=datetime.now())


@portal_bp.route('/policies/acknowledge/<int:id>', methods=['POST'])
@login_required
def acknowledge_policy(id):
    """Acknowledge a specific policy from the portal."""
    from models.policy import Policy
    policy = Policy.get_by_id(id)
    
    if not policy:
        return jsonify({'success': False, 'error': 'Policy not found'}), 404
        
    try:
        signature = request.form.get('signature', f"Signed by {current_user.get_full_name()} via Portal")
        policy.acknowledge(current_user.id, request.remote_addr, signature)
        
        # Log audit
        from models.audit import AuditLog
        AuditLog.log(current_user.id, 'Policy Acknowledgment', 'Policy', id, 
                    f'Acknowledged policy {policy.policy_number} via Portal', request.remote_addr)
        
        flash(_('Policy "%(name)s" has been acknowledged.', name=policy.policy_name), 'success')
        return redirect(url_for('portal.policy_list'))
    except Exception as e:
        flash(_('Error acknowledging policy: %(error)s', error=str(e)), 'danger')
        return redirect(url_for('portal.policy_list'))


# ============================================
# Annual COI Declaration
# ============================================
@portal_bp.route('/annual/coi', methods=['GET', 'POST'])
@login_required
def annual_coi():
    """Annual COI declaration form."""
    email = current_user.email
    year = datetime.now().year

    if request.method == 'POST':
        # Check if already submitted
        check = check_annual_coi_submission(email, year)
        if check['submitted']:
            flash(_('You have already submitted your COI declaration for %(year)s.', year=year), 'warning')
            return redirect(url_for('portal.dashboard'))
        
        db = get_db()
        # Find or create annual campaign
        annual_campaign_name = f"Annual Declaration {year}"
        campaign = db.execute('SELECT * FROM coi_campaigns WHERE campaign_name = %s', (annual_campaign_name,)).fetchone()
        
        if not campaign:
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO coi_campaigns (campaign_name, campaign_year, start_date, end_date, description, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (annual_campaign_name, year, f"{year}-01-01", f"{year}-12-31",
                  "Annual conflict of interest declarations via Employee Portal.", 'active', 1))
            campaign_id = cursor.fetchone()['id']
            db.commit()
        else:
            campaign_id = campaign['id']
        
        # Create declaration using COIDeclaration model
        try:
            from models.coi import COIDeclaration
            data = request.form.to_dict()
            data['campaign_id'] = campaign_id
            
            if not data.get('digital_signature'):
                flash(_('Digital signature is required.'), 'danger')
                return render_template('portal/annual_coi.html', email=email, year=year)
            
            status_code, pin_code = COIDeclaration.create(data, current_user.id)
            
            flash(_('Your COI declaration has been submitted successfully!'), 'success')
            return redirect(url_for('portal.thank_you', tracking_id=pin_code, type='coi'))
            
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                flash(_('You have already submitted a COI declaration for this year.'), 'warning')
                return redirect(url_for('portal.dashboard'))
            else:
                flash(_('Error submitting declaration: %(error)s', error=str(e)), 'danger')
    
    return render_template('portal/annual_coi.html', email=email, year=year)


# ============================================
# Annual COBEC Declaration
# ============================================
@portal_bp.route('/annual/cobec', methods=['GET', 'POST'])
@login_required
def annual_cobec():
    """Annual COBEC declaration form."""
    email = current_user.email
    year = datetime.now().year
    
    if request.method == 'POST':
        # Check if already submitted
        check = check_annual_cobec_submission(email, year)
        if check['submitted']:
            flash(_('You have already submitted your COBEC declaration for %(year)s.', year=year), 'warning')
            return redirect(url_for('portal.dashboard'))
        
        # Create declaration using COBECDeclaration model
        try:
            from models.cobec import COBECDeclaration
            data = request.form.to_dict()
            
            if not data.get('digital_signature'):
                flash(_('Digital signature is required.'), 'danger')
                return render_template('portal/annual_cobec.html', email=email, year=year)
            
            COBECDeclaration.create(data, current_user.id, year)
            
            tracking_id = generate_tracking_id()
            flash(_('Your COBEC declaration has been submitted successfully!'), 'success')
            return redirect(url_for('portal.thank_you', tracking_id=tracking_id, type='cobec'))
            
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                flash(_('You have already submitted a COBEC declaration for this year.'), 'warning')
                return redirect(url_for('portal.dashboard'))
            else:
                flash(_('Error submitting declaration: %(error)s', error=str(e)), 'danger')
    
    return render_template('portal/annual_cobec.html', email=email, year=year)


# ============================================
# GHE Incident Submission
# ============================================
@portal_bp.route('/incident/ghe', methods=['GET', 'POST'])
@login_required
def incident_ghe():
    """GHE incident submission form."""
    from models.ghe import GHEDeclaration
    from models.audit import AuditLog
    from models.notification import Notification
    from models.user import User
    from werkzeug.utils import secure_filename
    import os
    from flask import current_app

    # File upload config (same as GHE module) — non-static uploads/ dir, not
    # reachable via Flask's unauthenticated /static/ route
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx'}
    UPLOAD_FOLDER = 'uploads/ghe'
    
    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    def save_attachment(file):
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{filename}"
            upload_path = os.path.join(current_app.root_path, UPLOAD_FOLDER)
            os.makedirs(upload_path, exist_ok=True)
            file_path = os.path.join(upload_path, filename)
            file.save(file_path)
            return f"uploads/ghe/{filename}"
        return None

    if request.method == 'POST':
        # Get form data - match CMS fields
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
        errors = GHEDeclaration.validation_errors(data)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('portal/incident_ghe.html', email=current_user.email, today=datetime.now().strftime('%Y-%m-%d'))

        try:
            # Handle file upload
            if 'attachment' in request.files:
                file = request.files['attachment']
                if file.filename:
                    attachment_path = save_attachment(file)
                    if attachment_path:
                        data['attachment_path'] = attachment_path
                    else:
                        flash(_('Invalid file type. Allowed: PDF, PNG, JPG, DOC, DOCX'), 'warning')

            # Create declaration
            declaration = GHEDeclaration.create(data, current_user.id)
            
            # Notifications
            officers = User.get_all_compliance_officers()
            notify_ids = {o.id for o in officers}
            if declaration.manager_id:
                notify_ids.add(declaration.manager_id)
            
            for uid in notify_ids:
                Notification.create(
                    user_id=uid,
                    title="New GHE Incident Report",
                    message=f"New GHE Declaration from {current_user.get_full_name()}",
                    link=url_for('ghe.view_declaration', id=declaration.id),
                    n_type='submission'
                )
            
            AuditLog.log(current_user.id, 'GHE Submission', 'GHE', declaration.id, 
                        f'Submitted GHE declaration {declaration.declaration_number}', request.remote_addr)
            
            flash(_('Your GHE declaration has been submitted successfully!'), 'success')
            return redirect(url_for('portal.thank_you', tracking_id=declaration.tracking_id, type='ghe'))
            
        except Exception as e:
            flash(_('Error submitting declaration: %(error)s', error=str(e)), 'danger')
            return render_template('portal/incident_ghe.html', email=current_user.email, today=datetime.now().strftime('%Y-%m-%d'))
    
    return render_template('portal/incident_ghe.html', email=current_user.email, today=datetime.now().strftime('%Y-%m-%d'))


# ============================================
# Ad-hoc COI Submission
# ============================================
# Ad-hoc COI form "type of conflict" -> declaration area (flag, details column).
ADHOC_COI_AREAS = {
    'financial': ('has_financial_interests', 'financial_interests_details'),
    'employment': ('has_outside_employment', 'outside_employment_details'),
    'gifts': ('has_received_gifts', 'gifts_details'),
    'family': ('has_other_conflicts', 'other_conflicts_details'),
    'other': ('has_other_conflicts', 'other_conflicts_details'),
}


@portal_bp.route('/incident/coi', methods=['GET', 'POST'])
@login_required
def incident_coi():
    """Ad-hoc COI incident submission form."""
    email = current_user.email
    
    if request.method == 'POST':
        db = get_db()
        year = datetime.now().year
        adhoc_campaign_name = f"Ad-hoc Disclosures {year}"
        
        # Find or create ad-hoc campaign
        campaign = db.execute('SELECT * FROM coi_campaigns WHERE campaign_name = %s', (adhoc_campaign_name,)).fetchone()
        
        if not campaign:
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO coi_campaigns (campaign_name, campaign_year, start_date, end_date, description, status, created_by, campaign_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (adhoc_campaign_name, year, f"{year}-01-01", f"{year}-12-31",
                  "Ad-hoc conflict of interest disclosures via Employee Portal.", 'active', 1, 'adhoc'))
            campaign_id = cursor.fetchone()['id']
            db.commit()
        else:
            campaign_id = campaign['id']
        
        # Create declaration
        try:
            from models.coi import COIDeclaration
            form = request.form
            conflict_type = (form.get('conflict_type') or '').strip()
            description = (form.get('conflict_description') or '').strip()
            parties = (form.get('parties_involved') or '').strip()
            mitigation = (form.get('mitigation') or '').strip()
            signature = (form.get('digital_signature') or '').strip()
            if not signature:
                flash(_('Digital signature is required.'), 'danger')
                return render_template('portal/incident_coi.html', email=email)
            if conflict_type not in ADHOC_COI_AREAS or not description:
                flash(_('Please select the type of conflict and describe it.'), 'danger')
                return render_template('portal/incident_coi.html', email=email)
            # Build the declaration server-side (not from the page script): the
            # disclosed area is answered "Yes" with the description as details.
            flag, details_field = ADHOC_COI_AREAS[conflict_type]
            summary = description + (('\n' + _('Parties involved') + ': ' + parties) if parties else '')
            data = {
                'campaign_id': campaign_id,
                'digital_signature': signature,
                flag: 1,
                details_field: summary,
                'conflict_type': conflict_type,
                'details': description,
                'parties_involved': parties or None,
                'mitigation_plan': mitigation or None,
            }
            
            status_code_adhoc, pin_code = COIDeclaration.create(data, current_user.id)
            
            flash(_('Your ad-hoc COI disclosure has been submitted successfully!'), 'success')
            return redirect(url_for('portal.thank_you', tracking_id=pin_code, type='coi-adhoc'))
            
        except Exception as e:
            flash(_('Error submitting disclosure: %(error)s', error=str(e)), 'danger')
    
    return render_template('portal/incident_coi.html', email=email)


# ============================================
# Thank You Page
# ============================================
@portal_bp.route('/thank-you/<tracking_id>')
@login_required
def thank_you(tracking_id):
    """Thank you page after submission."""
    declaration_type = request.args.get('type', 'general')
    return render_template('portal/thank_you.html', 
                           tracking_id=tracking_id, 
                           declaration_type=declaration_type)


# ============================================
# Status Check
# ============================================
@portal_bp.route('/status', methods=['GET', 'POST'])
@login_required
def status():
    """Check submission status."""
    email = current_user.email
    db = get_db()
    user_id = current_user.id
    
    # Get COI submissions
    coi_submissions = db.execute('''
        SELECT d.*, c.campaign_name, c.campaign_year
        FROM coi_declarations d
        JOIN coi_campaigns c ON d.campaign_id = c.id
        WHERE d.employee_id = %s
        ORDER BY d.created_at DESC
    ''', (user_id,)).fetchall()
    
    # Get COBEC submissions
    cobec_submissions = db.execute('''
        SELECT * FROM cobec_declarations
        WHERE employee_id = %s
        ORDER BY created_at DESC
    ''', (user_id,)).fetchall()
    
    # Get GHE submissions
    ghe_submissions = db.execute('''
        SELECT * FROM ghe_declarations
        WHERE submitter_email = %s OR employee_id = %s
        ORDER BY created_at DESC
    ''', (email, user_id)).fetchall()
    
    # Get Policy acknowledgments
    policy_acknowledgments = db.execute('''
        SELECT a.*, p.policy_name, p.policy_number
        FROM policy_acknowledgments a
        JOIN policies p ON a.policy_id = p.id
        WHERE a.employee_id = %s
        ORDER BY a.acknowledgment_date DESC
    ''', (user_id,)).fetchall()

    # Get Training enrollments
    training_enrollments = db.execute('''
        SELECT e.*, c.course_name, c.passing_score, cert.id as cert_id
        FROM training_enrollments e
        JOIN training_courses c ON e.course_id = c.id
        LEFT JOIN training_certificates cert ON e.id = cert.enrollment_id
        WHERE e.employee_id = %s
        ORDER BY e.enrolled_date DESC
    ''', (user_id,)).fetchall()
    
    return render_template('portal/status.html', 
                           email=email,
                           coi_submissions=coi_submissions,
                           cobec_submissions=cobec_submissions,
                           ghe_submissions=ghe_submissions,
                           policy_acknowledgments=policy_acknowledgments,
                           training_enrollments=training_enrollments,
                           user=current_user)


# ============================================
# Secure Clarification Response (COI)
# ============================================
@portal_bp.route('/coi/verify-pin/<int:id>', methods=['GET', 'POST'])
@login_required
def verify_coi_pin(id):
    """Verify 4-digit PIN for COI clarification."""
    db = get_db()
    # Check if this declaration belongs to the current user
    declaration = db.execute('''
        SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.email
        FROM coi_declarations d
        JOIN users u ON d.employee_id = u.id
        WHERE d.id = %s AND d.employee_id = %s
    ''', (id, current_user.id)).fetchone()
    
    if not declaration:
        flash(_('Declaration not found or access denied.'), 'danger')
        return redirect(url_for('portal.dashboard'))
        
    if declaration['status'] != 'requires_clarification':
        flash(_('This declaration does not require clarification at this time.'), 'info')
        return redirect(url_for('portal.dashboard'))

    if request.method == 'POST':
        entered_pin = request.form.get('pin', '').strip()
        if entered_pin == declaration['pin_code']:
            from flask import session
            session[f'verified_coi_{id}'] = True
            return redirect(url_for('portal.respond_coi_clarification', id=id))
        else:
            flash(_('Invalid PIN code. Please try again.'), 'danger')
            
    return render_template('portal/coi_pin_verify.html', 
                           id=id, 
                           employee_name=declaration['employee_name'],
                           email=declaration['email'])


@portal_bp.route('/coi/respond/<int:id>', methods=['GET', 'POST'])
@login_required
def respond_coi_clarification(id):
    """View and respond to COI clarification request."""
    from flask import session
    if not session.get(f'verified_coi_{id}'):
        flash(_('Please verify your identity with the Case PIN first.'), 'warning')
        return redirect(url_for('portal.verify_coi_pin', id=id))
        
    db = get_db()
    
    sql = '''
        SELECT d.*, u.first_name || ' ' || u.last_name as employee_name, u.department, c.campaign_name
        FROM coi_declarations d
        JOIN users u ON d.employee_id = u.id
        JOIN coi_campaigns c ON d.campaign_id = c.id
        WHERE d.id = %s AND d.employee_id = %s
    '''
    row = db.execute(sql, (id, current_user.id)).fetchone()
    
    if not row:
        flash(_('Declaration not found.'), 'danger')
        return redirect(url_for('portal.dashboard'))

    if request.method == 'POST':
        response_text = request.form.get('response_text', '').strip()
        if not response_text:
            flash(_('Please provide a response.'), 'danger')
        else:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            new_comments = f"{row['review_comments']}\n\n--- Employee Response ({timestamp}) ---\n{response_text}"
            
            db.execute('''
                UPDATE coi_declarations 
                SET status = 'under_review', review_comments = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (new_comments, id))
            
            db.execute('''
                UPDATE coi_campaign_employees 
                SET status = 'submitted'
                WHERE campaign_id = %s AND employee_id = %s
            ''', (row['campaign_id'], row['employee_id']))
            
            db.commit()
            
            session.pop(f'verified_coi_{id}', None)
            
            flash(_('Your response has been submitted to compliance.'), 'success')
            return render_template('portal/thank_you.html', tracking_id='Updated', declaration_type='coi-clarification')

    return render_template('portal/coi_respond.html', declaration=row)
