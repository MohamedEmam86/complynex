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

"""Routes: customer EDD record, customer activation gate, corporate KYB page,
and the configurable high-risk country list."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from attachments.service import list_attachments
from database.db import get_db
from models.audit import AuditLog
from utils.decorators import permission_required
from utils.kyc_labels import tr
from . import aml_bp, edd, edd_logic as L


def _customer(cid):
    r = get_db().execute("SELECT * FROM customers WHERE id = %s", (cid,)).fetchone()
    return dict(r) if r else None


def _flash_error(e):
    msgs = e.args[0] if e.args else ''
    for m in (msgs if isinstance(msgs, list) else [msgs]):
        flash(tr(m), 'danger')


@aml_bp.route('/customers/<int:id>/edd', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def customer_edd(id):
    c = _customer(id)
    if not c:
        flash(tr('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
    here = url_for('aml.customer_edd', id=id)
    case = edd.latest_case(id)

    if request.method == 'POST':
        action = request.form.get('action', '')
        cname = c.get('company_name') or c.get('full_name')
        try:
            if action == 'start':
                if not current_user.can_edit('aml'):
                    raise edd.EddError('You do not have permission to prepare EDD.')
                if case and L.edd_status(case) != L.EDD_APPROVED:
                    raise edd.EddError('An EDD record is already in progress for this customer.')
                case = edd.new_review(id, current_user.id) if case else \
                    edd.open_case(id, edd.forced_reasons(c), current_user.id)
                msg = 'EDD record opened.'
            else:
                if not case or str(case['id']) != request.form.get('case_id'):
                    raise edd.EddError('The EDD record changed; reload the page.')
                if action in ('save', 'submit'):
                    if not current_user.can_edit('aml'):
                        raise edd.EddError('You do not have permission to prepare EDD.')
                    edd.save_case(case, request.form, current_user.id)
                    msg = 'EDD saved.'
                    if action == 'submit':
                        edd.submit(edd.get_case(case['id']), current_user.id)
                        msg = 'EDD submitted for approval.'
                elif action == 'approve':
                    edd.approve(case, current_user, request.form.get('notes'))
                    msg = 'EDD approved.'
                elif action == 'return':
                    edd.return_case(case, current_user, request.form.get('notes'))
                    msg = 'EDD returned to the preparer.'
                else:
                    raise edd.EddError('Unknown action.')
        except edd.EddError as e:
            _flash_error(e)
            return redirect(here)
        AuditLog.log(current_user.id, 'EDD', 'AML', id, f'{msg} for customer {c.get("customer_reference")} ({cname})',
                     request.remote_addr)
        flash(tr(msg), 'success')
        return redirect(here)

    ev = edd.evidence_count(case['id']) if case else 0
    reasons = edd.forced_reasons(c)
    return render_template(
        'aml/customer_edd.html', customer=c, case=case, status=L.edd_status(case),
        display=L.display_status(c.get('requires_edd'), case),
        checklist=L.checklist(case, ev) if case else [], evidence_count=ev, reasons=reasons,
        history=edd.history(case['id']) if case else [],
        preparer=edd.user_name(case.get('prepared_by')) if case else None,
        approver=edd.user_name(case.get('approved_by')) if case else None,
        can_prepare=current_user.can_edit('aml') and (not case or L.can_edit(case)),
        can_decide=bool(case) and L.edd_status(case) == L.EDD_SUBMITTED
        and L.approver_role_ok(current_user.role, current_user.can_view('aml'))
        and not L.four_eyes_error(current_user.id, case.get('prepared_by')),
        is_preparer=bool(case) and case.get('prepared_by') == current_user.id,
        frequencies=L.MONITORING_FREQUENCIES,
        attach_module='aml', attach_record_type=edd.ATTACH_TYPE, attach_record_id=case['id'] if case else 0,
        attach_items=list_attachments('aml', edd.ATTACH_TYPE, case['id']) if case else [],
        attach_can_edit=current_user.can_edit('aml') and bool(case) and L.can_edit(case))


@aml_bp.route('/customers/<int:id>/activate', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def activate_customer(id):
    c = _customer(id)
    if not c:
        flash(tr('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
    try:
        old = edd.activate(id, current_user, request.form.get('note'))
    except edd.EddError as e:
        _flash_error(e)
        return redirect(url_for('aml.view_customer', id=id))
    AuditLog.log(current_user.id, 'Customer Activated', 'AML', id,
                 f'Customer {c.get("customer_reference")} status {old} -> ACTIVE', request.remote_addr)
    flash(tr('Customer approved and activated.'), 'success')
    return redirect(url_for('aml.view_customer', id=id))


@aml_bp.route('/customers/<int:id>/kyb', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def customer_kyb(id):
    from kyb import views
    c = _customer(id)
    if not c or (c.get('customer_type') or '').upper() not in ('CORPORATE', 'ENTITY'):
        flash(tr('Corporate KYB applies to corporate customers only.'), 'warning')
        return redirect(url_for('aml.view_customer', id=id) if c else url_for('aml.customer_list'))
    return views.handle('aml_customer', id, self_endpoint='aml.customer_kyb',
                        back_url=url_for('aml.view_customer', id=id), can_edit=current_user.can_edit('aml'),
                        title_prefix=c.get('company_name') or c.get('full_name') or tr('Customer'),
                        after_change=lambda cid: edd.reassess(cid, current_user.id))


@aml_bp.route('/high-risk-countries', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def high_risk_countries():
    db = get_db()
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            flash(tr('You do not have permission to change the high-risk country list.'), 'danger')
            return redirect(url_for('aml.high_risk_countries'))
        action = request.form.get('action')
        now = datetime.now()
        if action == 'add':
            code = (request.form.get('country_code') or '').strip().upper()[:3]
            name = (request.form.get('country_name') or '').strip()[:100]
            cat = request.form.get('risk_category') or 'INTERNAL'
            if not code or not name or cat not in ('CALL_FOR_ACTION', 'INCREASED_MONITORING', 'INTERNAL'):
                flash(tr('Enter the country code, name and category.'), 'danger')
                return redirect(url_for('aml.high_risk_countries'))
            if db.execute("SELECT 1 FROM high_risk_countries WHERE upper(country_code) = %s OR upper(country_name) = upper(%s)",
                          (code, name)).fetchone():
                flash(tr('This country is already on the list; reactivate it instead.'), 'warning')
                return redirect(url_for('aml.high_risk_countries'))
            db.execute("""INSERT INTO high_risk_countries (country_code, country_name, name_ar, aliases, risk_category,
                          source, effective_date, is_active, notes, updated_by, updated_at)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)""",
                       (code, name, (request.form.get('name_ar') or '').strip() or None,
                        (request.form.get('aliases') or '').strip() or None, cat,
                        (request.form.get('source') or '').strip() or 'Internal decision',
                        now.strftime('%Y-%m-%d'), (request.form.get('notes') or '').strip() or None,
                        current_user.id, now))
            detail = f'added {code} {name} ({cat})'
        elif action in ('activate', 'deactivate', 'update'):
            rid = request.form.get('id', type=int)
            row = db.execute("SELECT * FROM high_risk_countries WHERE id = %s", (rid,)).fetchone()
            if not row:
                flash(tr('Country not found.'), 'danger')
                return redirect(url_for('aml.high_risk_countries'))
            reason = (request.form.get('notes') or '').strip()
            if action == 'deactivate' and len(reason) < 5:
                flash(tr('Give the reason for removing the country from the active list.'), 'danger')
                return redirect(url_for('aml.high_risk_countries'))
            if action == 'update':
                db.execute("UPDATE high_risk_countries SET aliases = %s, name_ar = %s, updated_by = %s, updated_at = %s "
                           "WHERE id = %s", ((request.form.get('aliases') or '').strip() or None,
                                             (request.form.get('name_ar') or '').strip() or None,
                                             current_user.id, now, rid))
            else:
                db.execute("UPDATE high_risk_countries SET is_active = %s, notes = COALESCE(NULLIF(%s, ''), notes), "
                           "updated_by = %s, updated_at = %s WHERE id = %s",
                           (1 if action == 'activate' else 0, reason, current_user.id, now, rid))
            detail = f'{action} {row["country_code"]} {row["country_name"]}' + (f': {reason}' if reason else '')
        elif action == 'reassess':
            n = 0
            for r in db.execute("SELECT id FROM customers WHERE COALESCE(status, '') NOT IN ('CLOSED')").fetchall():
                edd.reassess(r['id'], current_user.id, db=db)
                n += 1
            detail = f're-assessed {n} customers against the list'
            flash(tr(('%(n)s customers re-assessed.', {'n': n})), 'info')
        else:
            flash(tr('Unknown action.'), 'danger')
            return redirect(url_for('aml.high_risk_countries'))
        db.commit()
        AuditLog.log(current_user.id, 'High-risk Countries', 'AML', None, detail, request.remote_addr)
        if action != 'reassess':
            flash(tr('High-risk country list updated.'), 'success')
        return redirect(url_for('aml.high_risk_countries'))
    rows = db.execute("""SELECT h.*, TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS updated_by_name
                         FROM high_risk_countries h LEFT JOIN users u ON u.id = h.updated_by
                         ORDER BY h.is_active DESC, h.risk_category, h.country_name""").fetchall()
    return render_template('aml/high_risk_countries.html', rows=rows, can_edit=current_user.can_edit('aml'))
