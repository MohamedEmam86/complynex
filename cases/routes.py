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
Cross-cutting case oversight, not a working queue — actual case workflow
(status changes, assignment, notes) still happens in each source module's
own UI. Gated at 'config'/admin level for the same reason the P1 event-bus
admin UI is: this is compliance-leadership oversight tooling, not a
day-to-day team workflow, so it doesn't need a new permission dimension
(perm_cases) added to the users table.
"""

from datetime import datetime

from flask import render_template, request
from flask_login import login_required

from database.db import get_db
from utils.decorators import permission_required

from . import cases_bp

# Where each source table's own record can be viewed/worked on.
_SOURCE_VIEW_ENDPOINT = {
    'tm_alerts': ('aml.view_alert', 'alert_id'),
    'whistleblowing_cases': ('whistleblowing.view_case', 'case_id'),
    'consumer_complaints': ('consumer_protection.view_complaint', 'id'),
    # cyber_incidents has no per-incident detail route yet — falls back to the module dashboard.
}


@cases_bp.route('/')
@login_required
@permission_required('config', level='admin')
def case_list():
    case_type = request.args.get('case_type') or None
    show_all = request.args.get('show_all') == '1'
    db = get_db()

    if show_all:
        rows = db.execute("""
            SELECT * FROM cases
            WHERE (%s IS NULL OR case_type = %s)
            ORDER BY due_date NULLS LAST, opened_at DESC LIMIT 300
        """, (case_type, case_type)).fetchall()
    else:
        rows = db.execute("""
            SELECT * FROM cases
            WHERE status NOT IN ('RESOLVED', 'CLOSED') AND (%s IS NULL OR case_type = %s)
            ORDER BY due_date NULLS LAST, opened_at DESC LIMIT 300
        """, (case_type, case_type)).fetchall()

    cases = [dict(r) for r in rows]
    for c in cases:
        c['is_overdue'] = bool(c['due_date']) and c['status'] not in ('RESOLVED', 'CLOSED') and \
            str(c['due_date']) < datetime.now().isoformat()

    case_types = db.execute("SELECT case_type FROM case_sla_config ORDER BY case_type").fetchall()

    return render_template('cases/list.html', cases=cases, case_types=[r['case_type'] for r in case_types],
                            selected_type=case_type, show_all=show_all)


@cases_bp.route('/<int:case_id>')
@login_required
@permission_required('config', level='admin')
def case_detail(case_id):
    db = get_db()
    row = db.execute("SELECT * FROM cases WHERE id = %s", (case_id,)).fetchone()
    if not row:
        return render_template('cases/not_found.html'), 404
    case = dict(row)

    endpoint = _SOURCE_VIEW_ENDPOINT.get(case['source_table'])
    source_url_kwargs = None
    if endpoint:
        view_endpoint, kwarg_name = endpoint
        source_url_kwargs = (view_endpoint, {kwarg_name: case['source_record_id']})

    party = None
    if case.get('party_id'):
        from models.party import Party
        party = Party.get_by_id(case['party_id'])

    return render_template('cases/view.html', case=case, source_url_kwargs=source_url_kwargs, party=party)
