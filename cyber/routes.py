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
from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from utils.decorators import permission_required
from database.db import get_db
from . import cyber_bp
from datetime import datetime, timedelta
import os

@cyber_bp.route('/')
@login_required
@permission_required('cyber')
def dashboard():
    db = get_db()
    # Cyber stats
    active_incidents = db.execute("SELECT * FROM cyber_incidents WHERE status != 'CLOSED' ORDER BY severity DESC").fetchall()
    total_active = len(active_incidents)
    high_critical = db.execute("SELECT COUNT(*) as count FROM cyber_incidents WHERE status != 'CLOSED' AND severity IN ('HIGH', 'CRITICAL')").fetchone()['count']
    
    return render_template('cyber/dashboard.html', 
                          user=current_user,
                          active_incidents=active_incidents,
                          total_active=total_active,
                          high_critical=high_critical)

@cyber_bp.route('/incidents/new', methods=['GET', 'POST'])
@login_required
@permission_required('cyber', level='edit')
@permission_required('cyber', level='view')
def report_incident():
    if request.method == 'POST':
        db = get_db()
        inc_number = f"INC-{datetime.now().strftime('%Y%m%d')}-{os.urandom(2).hex().upper()}"
        inc_type = request.form.get('incident_type')
        severity = request.form.get('severity')
        description = request.form.get('description')
        
        # CBE Notification Logic (CBE Circular Dec 2023)
        # High/Critical incidents MUST be reported within 6-24 hours
        cbe_notif_req = 1 if severity in ['HIGH', 'CRITICAL'] else 0
        
        cursor = db.execute("""
            INSERT INTO cyber_incidents
            (incident_number, incident_date, discovery_date, incident_type, severity, incident_description, cbe_notification_required, status, created_by)
            VALUES (%s, NOW(), NOW(), %s, %s, %s, %s, 'NEW', %s)
            RETURNING id
        """, (inc_number, inc_type, severity, description, cbe_notif_req, current_user.id))
        incident_id = cursor.fetchone()['id']

        db.commit()

        try:
            from models.case import Case
            Case.sync_from_source('CYBER_INCIDENT', incident_id)
        except Exception:
            current_app.logger.exception('Failed to sync case registry for cyber_incidents %s', incident_id)

        flash(gettext('Incident %(inc_number)s reported. Compliance and SOC teams notified.', inc_number=inc_number))
        return redirect(url_for('cyber.dashboard'))
        
    return render_template('cyber/incident_form.html', user=current_user)
