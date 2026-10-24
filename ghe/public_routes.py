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
Public GHE Routes - No Authentication Required
Allows external users to submit GHE declarations via public link
"""
from flask_babel import gettext
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from datetime import datetime
import uuid

public_ghe_bp = Blueprint('public_ghe', __name__, url_prefix='/ghe/public')


def get_db():
    """Get database connection."""
    from database.db import get_db as db_get
    return db_get()


def generate_tracking_id():
    """Generate a unique tracking ID for public submissions."""
    return str(uuid.uuid4())[:8].upper()


def generate_declaration_number():
    """Generate a unique declaration number."""
    db = get_db()
    today = datetime.now().strftime('%Y%m%d')
    
    # Get the count of declarations today
    result = db.execute(
        "SELECT COUNT(*) as count FROM ghe_declarations WHERE declaration_number LIKE %s",
        (f'GHE-{today}%',)
    ).fetchone()
    
    count = (result['count'] if result else 0) + 1
    return f"GHE-{today}-{count:04d}"


def determine_initial_status(value, is_govt_official):
    """
    Determine initial status based on value and government official flag.
    """
    if is_govt_official:
        return 'manager_review'
    
    if value < 500:
        return 'approved'  # Auto-approve
    elif value <= 2000:
        return 'manager_review'
    else:
        return 'compliance_review'


@public_ghe_bp.route('/submit', methods=['GET', 'POST'])
def public_submit():
    """Public GHE submission form - no login required."""
    if request.method == 'POST':
        # Get form data
        submitter_email = request.form.get('submitter_email', '').strip()
        submitter_name = request.form.get('submitter_name', '').strip()
        submitter_department = request.form.get('submitter_department', '').strip()
        ghe_type = request.form.get('ghe_type')
        direction = request.form.get('direction')
        event_date = request.form.get('event_date')
        estimated_value = request.form.get('estimated_value_egp', 0)
        description = request.form.get('description', '').strip()
        provider_name = request.form.get('provider_recipient_name', '').strip()
        provider_company = request.form.get('provider_recipient_company', '').strip()
        business_purpose = request.form.get('business_purpose', '').strip()
        is_govt_official = request.form.get('is_government_official') == 'on'
        govt_details = request.form.get('government_official_details', '').strip()
        govt_position = request.form.get('government_official_position', '').strip()
        
        # Validation
        errors = []
        if not submitter_email:
            errors.append('Email address is required')
        if not submitter_name:
            errors.append('Your name is required')
        if not ghe_type:
            errors.append('GHE type is required')
        if not direction:
            errors.append('Direction is required')
        if not event_date:
            errors.append('Event date is required')
        if not description:
            errors.append('Description is required')
        if not provider_name:
            errors.append('Provider/Recipient name is required')
        
        if is_govt_official and not govt_position:
            errors.append('Government Official Position is required')
        
        try:
            estimated_value = float(estimated_value)
            if estimated_value <= 0:
                errors.append('Estimated value must be greater than 0')
        except ValueError:
            errors.append('Invalid estimated value')
        try:
            if datetime.strptime((event_date or '')[:10], '%Y-%m-%d').date() > datetime.now().date():
                errors.append('Event date cannot be in the future')
        except ValueError:
            errors.append('Invalid event date')
        if is_govt_official and not govt_details:
            errors.append('Government entity is required')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('ghe/public_submit.html')
        
        # Generate IDs
        tracking_id = generate_tracking_id()
        declaration_number = generate_declaration_number()
        
        # Determine status
        status = determine_initial_status(estimated_value, is_govt_official)
        auto_approved = (status == 'approved' and not is_govt_official)
        
        # Link to existing employee if email matches
        db = get_db()
        user = db.execute('SELECT id, manager_id FROM users WHERE email = %s', (submitter_email,)).fetchone()
        employee_id = user['id'] if user else None
        # If user exists, use their manager. If not, manager_id is None (will need manual assignment by Compliance)
        manager_id = user['manager_id'] if user else None
        
        # Insert into database
        try:
            db.execute('''
                INSERT INTO ghe_declarations (
                    declaration_number, tracking_id, submitter_email, submitter_name,
                    submitter_department, ghe_type, direction, event_date,
                    estimated_value_egp, description, provider_recipient_name,
                    provider_recipient_company, business_purpose, is_government_official,
                    government_official_details, government_official_position, status, auto_approved, is_public_submission,
                    employee_id, manager_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
            ''', (
                declaration_number, tracking_id, submitter_email, submitter_name,
                submitter_department, ghe_type, direction, event_date,
                estimated_value, description, provider_name, provider_company,
                business_purpose, 1 if is_govt_official else 0, govt_details, govt_position,
                status, 1 if auto_approved else 0,
                employee_id, manager_id
            ))
            db.commit()
            
            # Log creation in history
            declaration_id = db.execute(
                'SELECT id FROM ghe_declarations WHERE tracking_id = %s',
                (tracking_id,)
            ).fetchone()['id']
            
            action = 'Created (Public Submission)'
            if auto_approved:
                action += ' - Auto-Approved'
            
            db.execute('''
                INSERT INTO ghe_approval_history (
                    ghe_declaration_id, action, action_by, old_status, new_status, comments
                ) VALUES (%s, %s, %s, 'new', %s, 'Public submission via online form')
            ''', (declaration_id, action, employee_id if employee_id else 0, status))
            db.commit()
            
            # Send confirmation email
            try:
                from services.email_service import email_service
                email_service.send_submission_confirmation(submitter_email, {
                    'declaration_number': declaration_number,
                    'tracking_id': tracking_id,
                    'ghe_type': ghe_type,
                    'estimated_value_egp': estimated_value,
                    'submitter_name': submitter_name
                })
            except Exception as e:
                current_app.logger.error(f"GHE email notification failed: {e}")
            
            flash(gettext('Your declaration has been submitted successfully!'), 'success')
            return redirect(url_for('public_ghe.thank_you', tracking_id=tracking_id))
            
        except Exception as e:
            flash(f'Error submitting declaration: {str(e)}', 'danger')
            return render_template('ghe/public_submit.html')
    
    return render_template('ghe/public_submit.html')


@public_ghe_bp.route('/thank-you/<tracking_id>')
def thank_you(tracking_id):
    """Thank you page after successful submission."""
    db = get_db()
    declaration = db.execute(
        'SELECT * FROM ghe_declarations WHERE tracking_id = %s',
        (tracking_id,)
    ).fetchone()
    
    if not declaration:
        flash(gettext('Declaration not found'), 'danger')
        return redirect(url_for('public_ghe.public_submit'))
    
    return render_template('ghe/public_thank_you.html', declaration=declaration)


@public_ghe_bp.route('/status/<tracking_id>')
def check_status(tracking_id):
    """Check declaration status using tracking ID."""
    tracking_id = tracking_id.upper()
    
    db = get_db()
    declaration = db.execute(
        'SELECT * FROM ghe_declarations WHERE tracking_id = %s',
        (tracking_id,)
    ).fetchone()
    
    if not declaration:
        flash(gettext('Declaration not found. Please check your tracking ID.'), 'danger')
        return render_template('ghe/public_status.html', declaration=None, tracking_id=tracking_id)
    
    # Get approval history
    history = db.execute('''
        SELECT h.*, 
               COALESCE(u.first_name || ' ' || u.last_name, 'System') as action_by_name
        FROM ghe_approval_history h
        LEFT JOIN users u ON h.action_by = u.id
        WHERE h.ghe_declaration_id = %s
        ORDER BY h.action_date DESC
    ''', (declaration['id'],)).fetchall()
    
    return render_template('ghe/public_status.html', 
                          declaration=declaration, 
                          history=history,
                          tracking_id=tracking_id)


@public_ghe_bp.route('/status/<tracking_id>/respond', methods=['POST'])
def respond_to_info_request(tracking_id):
    """Submit response to information request."""
    tracking_id = tracking_id.upper()
    response = request.form.get('response', '').strip()
    
    if not response:
        flash(gettext('Please provide a response'), 'danger')
        return redirect(url_for('public_ghe.check_status', tracking_id=tracking_id))
    
    db = get_db()
    declaration = db.execute(
        'SELECT * FROM ghe_declarations WHERE tracking_id = %s AND needs_more_info = 1',
        (tracking_id,)
    ).fetchone()
    
    if not declaration:
        flash(gettext('Declaration not found or no information was requested'), 'danger')
        return redirect(url_for('public_ghe.check_status', tracking_id=tracking_id))
    
    # Update declaration with response
    db.execute('''
        UPDATE ghe_declarations SET 
            info_response = %s,
            info_response_date = CURRENT_TIMESTAMP,
            needs_more_info = 0,
            status = 'manager_review'
        WHERE tracking_id = %s
    ''', (response, tracking_id))
    db.commit()
    
    # Log in history
    db.execute('''
        INSERT INTO ghe_approval_history (
            ghe_declaration_id, action, action_by, old_status, new_status, comments
        ) VALUES (%s, 'Information Provided', 0, 'info_requested', 'manager_review', %s)
    ''', (declaration['id'], response))
    db.commit()
    
    flash(gettext('Thank you! Your response has been submitted and your declaration is back under review.'), 'success')
    return redirect(url_for('public_ghe.check_status', tracking_id=tracking_id))


@public_ghe_bp.route('/status', methods=['GET', 'POST'])
def status_lookup():
    """Status lookup page."""
    if request.method == 'POST':
        tracking_id = request.form.get('tracking_id', '').strip().upper()
        if tracking_id:
            return redirect(url_for('public_ghe.check_status', tracking_id=tracking_id))
        flash(gettext('Please enter a tracking ID'), 'danger')
    
    return render_template('ghe/public_status_lookup.html')
