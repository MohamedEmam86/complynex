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
Admin UI over the compliance event bus: a read-only recent-events log, and
enable/disable toggling of event_routing_rules (the rules themselves stay
data — no code change needed to turn a routing action on or off).
Gated at 'config'/admin level since this is system configuration, not a
day-to-day compliance workflow.
"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required

from database.db import get_db
from utils.decorators import permission_required

from . import events_bp


@events_bp.route('/')
@login_required
@permission_required('config', level='admin')
def event_log():
    db = get_db()
    events = db.execute("""
        SELECT * FROM compliance_events ORDER BY created_at DESC LIMIT 200
    """).fetchall()
    return render_template('events/log.html', events=events)


@events_bp.route('/rules')
@login_required
@permission_required('config', level='admin')
def rules_list():
    db = get_db()
    rules = db.execute("""
        SELECT * FROM event_routing_rules ORDER BY event_type_pattern, priority
    """).fetchall()
    return render_template('events/rules.html', rules=rules)


@events_bp.route('/rules/<int:rule_id>/toggle', methods=['POST'])
@login_required
@permission_required('config', level='admin')
def toggle_rule(rule_id):
    db = get_db()
    db.execute(
        "UPDATE event_routing_rules SET enabled = NOT enabled, updated_at = NOW() WHERE id = %s",
        (rule_id,),
    )
    db.commit()
    flash('Routing rule updated.', 'success')
    return redirect(url_for('events.rules_list'))
