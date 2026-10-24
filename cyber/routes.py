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
from flask import abort
import os

# NEW is the state a fresh report starts in; the response hub moves it on.
INCIDENT_STATUSES = ('NEW', 'OPEN', 'CONTAINED', 'RESOLVED', 'CLOSED')
INCIDENT_DONE = ('RESOLVED', 'CLOSED')

@cyber_bp.route('/')
@login_required
@permission_required('cyber')
def dashboard():
    db = get_db()
    # Cyber stats
    active_incidents = db.execute(
        "SELECT * FROM cyber_incidents WHERE COALESCE(UPPER(status), 'NEW') NOT IN ('RESOLVED', 'CLOSED') "
        "ORDER BY severity DESC").fetchall()
    total_active = len(active_incidents)
    high_critical = db.execute(
        "SELECT COUNT(*) as count FROM cyber_incidents WHERE COALESCE(UPPER(status), 'NEW') NOT IN ('RESOLVED', 'CLOSED') "
        "AND severity IN ('HIGH', 'CRITICAL')").fetchone()['count']
    
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
        return redirect(url_for('cyber.incident_detail', incident_id=incident_id))
        
    return render_template('cyber/incident_form.html', user=current_user)


@cyber_bp.route('/incidents/<int:incident_id>', methods=['GET', 'POST'])
@login_required
@permission_required('cyber')
def incident_detail(incident_id):
    """Response hub for one incident: status (Open / Contained / Resolved / Closed) and notes."""
    db = get_db()
    inc = db.execute("SELECT * FROM cyber_incidents WHERE id = %s", (incident_id,)).fetchone()
    if not inc:
        abort(404)
    inc = dict(inc)

    if request.method == 'POST':
        if not current_user.can_edit('cyber'):
            abort(403)
        new_status = (request.form.get('status') or '').strip().upper()
        note = (request.form.get('note') or '').strip()
        old_status = (inc.get('status') or 'NEW').upper()
        if new_status not in INCIDENT_STATUSES:
            flash(gettext('Invalid status.'), 'danger')
            return redirect(url_for('cyber.incident_detail', incident_id=incident_id))
        if new_status == old_status and not note:
            flash(gettext('Change the status or add a note.'), 'warning')
            return redirect(url_for('cyber.incident_detail', incident_id=incident_id))
        if new_status != old_status and new_status in INCIDENT_DONE and not note:
            flash(gettext('A note is required to resolve or close an incident.'), 'danger')
            return redirect(url_for('cyber.incident_detail', incident_id=incident_id))

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sets, args = ['status = %s'], [new_status]
        if new_status == 'CONTAINED' and not inc.get('containment_date'):
            sets.append('containment_date = %s'); args.append(now)
        if new_status == 'RESOLVED' and not inc.get('recovery_date'):
            sets.append('recovery_date = %s'); args.append(now)
        if new_status == 'CLOSED':
            sets += ['closed_date = %s', 'closed_by = %s']; args += [now, current_user.id]
        db.execute(f"UPDATE cyber_incidents SET {', '.join(sets)} WHERE id = %s", (*args, incident_id))
        db.execute("""INSERT INTO cyber_incident_updates (incident_id, old_status, new_status, note, created_by)
                      VALUES (%s, %s, %s, %s, %s)""",
                   (incident_id, old_status, new_status, note or None, current_user.id))
        db.commit()
        try:
            from models.case import Case
            Case.sync_from_source('CYBER_INCIDENT', incident_id)
        except Exception:
            current_app.logger.exception('Failed to sync case registry for cyber_incidents %s', incident_id)
        flash(gettext('Incident updated.'), 'success')
        return redirect(url_for('cyber.incident_detail', incident_id=incident_id))

    try:
        updates = db.execute("""
            SELECT u.*, NULLIF(TRIM(COALESCE(us.first_name, '') || ' ' || COALESCE(us.last_name, '')), '') AS user_name
            FROM cyber_incident_updates u LEFT JOIN users us ON us.id = u.created_by
            WHERE u.incident_id = %s ORDER BY u.created_at DESC, u.id DESC""", (incident_id,)).fetchall()
    except Exception:
        # Table arrives with migration 20261107_cyber_incident_updates.
        db.rollback()
        updates = []
    return render_template('cyber/incident_detail.html', inc=inc, updates=updates,
                           statuses=INCIDENT_STATUSES,
                           can_edit=current_user.can_edit('cyber'))
