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
from functools import wraps

from flask import render_template, request, flash, redirect, url_for
from flask_babel import gettext
from flask_login import login_required, current_user

from database.db import get_db

from . import cases_bp

# Where each source table's own record can be viewed/worked on.
_SOURCE_VIEW_ENDPOINT = {
    'tm_alerts': ('aml.view_alert', 'alert_id'),
    'whistleblowing_cases': ('whistleblowing.view_case', 'case_id'),
    'consumer_complaints': ('consumer_protection.view_complaint', 'id'),
    'cyber_incidents': ('cyber.incident_detail', 'incident_id'),
    'data_subject_requests': ('dp.dsr_detail', 'id'),
    'data_breaches': ('dp.breach_detail', 'id'),
}


# Module whose view permission is needed to see a case type (compliance staff
# read access: they see only the case types of modules they may open).
CASE_TYPE_MODULE = {
    'TM_ALERT': 'aml', 'UNUSUAL_TXN': 'aml', 'SAR': 'aml', 'WHISTLEBLOWING': 'whistleblowing',
    'CONSUMER_COMPLAINT': 'consumer_protection', 'CYBER_INCIDENT': 'cyber', 'REG_CONTROL': 'regcontrols',
    'DSR': 'pdpl', 'DATA_BREACH': 'pdpl',
}


def _is_cases_admin(user):
    try:
        return user.is_admin() or user._get_perm('config') == 'admin'
    except Exception:
        return False


def visible_case_types(user, all_types):
    """None = every type (administrators); else the types the user may read."""
    if _is_cases_admin(user):
        return None
    return [t for t in all_types if t in CASE_TYPE_MODULE and user.can_view(CASE_TYPE_MODULE[t])]


def _cases_readers(f):
    """Read access: administrators, and compliance staff (read only)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not (_is_cases_admin(current_user) or current_user.is_compliance_officer()):
            flash(gettext('You do not have permission to view this page.'), 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return wrapped


@cases_bp.route('/')
@login_required
@_cases_readers
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

    case_types = db.execute("SELECT case_type FROM case_sla_config ORDER BY case_type").fetchall()
    allowed = visible_case_types(current_user, [r['case_type'] for r in case_types])
    cases = [dict(r) for r in rows if allowed is None or r['case_type'] in allowed]
    for c in cases:
        c['is_overdue'] = bool(c['due_date']) and c['status'] not in ('RESOLVED', 'CLOSED') and \
            str(c['due_date']) < datetime.now().isoformat()

    return render_template('cases/list.html', cases=cases,
                           case_types=[r['case_type'] for r in case_types
                                       if allowed is None or r['case_type'] in allowed],
                            selected_type=case_type, show_all=show_all)


@cases_bp.route('/<int:case_id>')
@login_required
@_cases_readers
def case_detail(case_id):
    db = get_db()
    row = db.execute("SELECT * FROM cases WHERE id = %s", (case_id,)).fetchone()
    allowed = visible_case_types(current_user, [row['case_type']]) if row else None
    if not row or (allowed is not None and row['case_type'] not in allowed):
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
