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


from flask_babel import gettext
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database.db import get_db
from models.coi import COICampaign, COIDeclaration
from models.user import User
from datetime import datetime

public_coi_bp = Blueprint('public_coi', __name__, url_prefix='/coi/public')

@public_coi_bp.route('/declare', methods=['GET', 'POST'])
def public_declare():
    """Public COI Declaration (Email Lookup)"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        
        # 1. Verify Employee
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = %s', (email,)).fetchone()
        
        if not user:
            flash(gettext('Email not found in our employee database. Please contact HR.'), 'danger')
            return render_template('coi/public_declare.html')
            
        # 2. Find Ad-hoc Campaign
        year = datetime.now().year
        adhoc_campaign_name = f"Ad-hoc Disclosures {year}"
        
        # Helper logic to find/create ad-hoc campaign (duplicated from routes.py for now, can be refactored)
        # We need raw SQL here since we don't have the full model methods easily available/trusted without context
        campaign = db.execute('SELECT * FROM coi_campaigns WHERE campaign_name = %s', (adhoc_campaign_name,)).fetchone()
        
        if not campaign:
            # Auto-create by system
            cursor = db.cursor()
            cursor.execute('''
                INSERT INTO coi_campaigns (campaign_name, campaign_year, start_date, end_date, description, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            ''', (adhoc_campaign_name, year, f"{year}-01-01", f"{year}-12-31", 
                  "Container for ad-hoc conflict of interest disclosures reported outside of annual campaigns.", 'active', 1))
            campaign_id = cursor.fetchone()[0]
            db.commit()
            campaign = db.execute('SELECT * FROM coi_campaigns WHERE id = %s', (campaign_id,)).fetchone()
        
        # 3. Create Declaration
        try:
            # Construct data dict from form
            data = request.form.to_dict()
            data['campaign_id'] = campaign['id']
            # Digital signature is required
            if not data.get('digital_signature'):
                 flash(gettext('Digital signature is required.'), 'danger')
                 return render_template('coi/public_declare.html', email=email)

            # Check existing%s
            # COIDeclaration.create logic handles "already exists" uniqueness%s 
            # The schema is UNIQUE(campaign_id, employee_id).
            # If they already submitted 1 ad-hoc this year, they can't submit another via this simple logic.
            # We catch IntegrityError
            
            try:
                COIDeclaration.create(data, user['id'])
                flash(gettext('Declaration submitted successfully! A manager will review your submission.'), 'success')
                return redirect(url_for('public_coi.thank_you'))
            except Exception as e:
                import sqlite3
                if "UNIQUE constraint failed" in str(e):
                    flash(gettext('You have already submitted an ad-hoc declaration for this year. Please contact compliance to edit.'), 'warning')
                else:
                    flash(f'Error submitting declaration: {str(e)}', 'danger')
                    
        except Exception as e:
            flash(f'System Error: {str(e)}', 'danger')
            
    return render_template('coi/public_declare.html')

@public_coi_bp.route('/thank-you')
def thank_you():
    return render_template('coi/public_thank_you.html')
