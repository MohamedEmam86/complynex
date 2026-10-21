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
import secrets
from datetime import datetime, timedelta
# import qrcode
from io import BytesIO
from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file

# Create Blueprint
consumer_bp = Blueprint('consumer_protection', __name__, 
                        url_prefix='/consumer-protection')

# Helper: Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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
    complaints = ConsumerComplaint.get_all(status=status)
    return render_template('consumer_protection/list.html', complaints=complaints)

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
        try:
            action = request.form.get('action')
            
            if action == 'update_status':
                new_status = request.form['status']
                old_status = complaint['status']
                
                ConsumerComplaint.update_status(id, new_status, current_user.id)
                
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
            
    return render_template('consumer_protection/view.html', complaint=complaint, logs=logs, documents=documents)


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
