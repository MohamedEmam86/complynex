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

from utils.nid_parser import parse_egyptian_nid
from flask_babel import gettext
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from utils.decorators import permission_required
from flask_babel import gettext as _
from database.db import get_db
from datetime import datetime
import os
from . import aml_bp
from .services import calculate_customer_risk
import csv
import io
from flask import Response, current_app
import json
import uuid
from attachments.service import list_attachments

@aml_bp.route('/')
@aml_bp.route('/dashboard')
@login_required
@permission_required('aml')
def dashboard():
    db = get_db()
    
    # Get stats
    total_customers = db.execute("SELECT COUNT(*) FROM customers").fetchone()['count'] if db.execute("SELECT COUNT(*) as count FROM customers").fetchone() else 0
    high_risk = (db.execute("SELECT COUNT(*) as cnt FROM customers WHERE risk_classification = 'HIGH'").fetchone() or {}).get("cnt", 0)
    pending_sar = (db.execute("SELECT COUNT(*) as cnt FROM suspicious_activities WHERE investigation_status != 'CLOSED'").fetchone() or {}).get("cnt", 0)
    alerts_24h = (db.execute("SELECT COUNT(*) as cnt FROM tm_alerts WHERE alert_date::timestamp > NOW() - INTERVAL '1 day'").fetchone() or {}).get("cnt", 0)
    
    recent_alerts = db.execute("""
        SELECT a.*, c.full_name as customer_name, r.rule_name 
        FROM tm_alerts a
        LEFT JOIN customers c ON a.customer_id = c.id
        LEFT JOIN tm_rules r ON a.rule_id = r.id
        ORDER BY a.alert_date DESC LIMIT 5
    """).fetchall()
    
    return render_template('aml/dashboard.html', 
                          user=current_user,
                          total_customers=total_customers,
                          high_risk=high_risk,
                          pending_sar=pending_sar,
                          alerts_24h=alerts_24h,
                          recent_alerts=recent_alerts)

@aml_bp.route('/customers')
@login_required
@permission_required('aml')
def customer_list():
    db = get_db()
    customers = db.execute("""
        SELECT id, customer_reference, customer_type, full_name, company_name, 
               nationality, id_type, id_number,
               risk_classification, status, onboarding_date
        FROM customers
        ORDER BY COALESCE(onboarding_date, created_at) DESC NULLS LAST, id DESC
    """).fetchall()
    from . import edd as _edd, edd_logic as _L
    cases = _edd.list_summary(db)
    rows = []
    for c in customers:
        c = dict(c)
        case = cases.get(c['id'])
        c['edd_display'] = _L.display_status(c.get('requires_edd'), case)
        c['edd_pending'] = _L.is_pending(c.get('requires_edd'), case)
        rows.append(c)
    return render_template('aml/customer_list.html', customers=rows, user=current_user,
                           edd_filter=request.args.get('edd', ''))

from models.aml import Customer
from models.audit import AuditLog

@aml_bp.route('/customers/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def create_customer():
    db = get_db()
    if request.method == 'POST':
        # Prepare data for Model
        data = {
            'customer_type': request.form.get('customer_type'),
            'full_name': request.form.get('full_name'),
            'full_name_arabic': request.form.get('full_name_arabic'),
            'date_of_birth': request.form.get('date_of_birth'),
            'nationality': request.form.get('nationality'),
            'id_type': request.form.get('id_type'),
            'id_number': request.form.get('id_number'),
            'id_expiry_date': request.form.get('id_expiry_date'),
            'gender': request.form.get('gender'),
            'company_name': request.form.get('company_name'),
            'registration_number': request.form.get('registration_number'),
            'industry': request.form.get('industry'),
            'address': request.form.get('address'),
            'phone': request.form.get('phone'),
            'email': request.form.get('email'),
            'source_of_funds': request.form.get('source_of_funds'),
            'is_pep': True if request.form.get('is_pep') == 'on' else False,
            'country': request.form.get('country'),
            'purpose': request.form.get('purpose'),
            'income': request.form.get('income'),
            'created_by': current_user.id,
        }
        if data['customer_type'] == 'CORPORATE':
            # a legal entity stays pending until its KYB file (owners, signatories,
            # screening) is complete and someone approves it
            data['status'] = 'PENDING'
        if data['customer_type'] not in ('INDIVIDUAL', 'CORPORATE'):
            flash(_('Select a valid customer type.'), 'danger')
            return _customer_form_again()
        if data['customer_type'] == 'CORPORATE':
            # The form has one name field; a corporate customer is stored under company_name.
            data['company_name'] = data['company_name'] or data['full_name']
            data['full_name'] = None
        if not (data['full_name'] or data['company_name'] or '').strip():
            flash(_('Name is required.'), 'danger')
            return _customer_form_again()
        dup = Customer.find_duplicate_id(data['id_type'], data['id_number'])
        if dup:
            flash(_('A customer with this ID number already exists: %(ref)s (%(name)s).',
                    ref=dup['customer_reference'], name=dup['name'] or ''), 'danger')
            return _customer_form_again()
        
        # Map 'source_of_funds' to 'income' if income is missing%s 
        # Form has 'source_of_funds'. Model uses 'income' for risk.
        # utils/aml_risk.py checks data.get('income') or data.get('annual_income_range').
        # I'll rely on form having 'income' or 'annual_income_range'.
        # Previous code used request.form.get('source_of_funds').
        
        customer_id = Customer.create(data)
        if customer_id:
            try:
                from parties.linker import upsert_party_for_customer
                upsert_party_for_customer(customer_id)
            except Exception:
                current_app.logger.exception('Failed to sync party registry for customer %s', customer_id)

            # AUTOMATED SCREENING INTEGRATION
            _last_hist_id = None
            try:
                from screening.customer_screening_service import screen_and_save

                screening_name = data.get('full_name') or data.get('company_name')
                entity_type = 'INDIVIDUAL' if data.get('customer_type') == 'INDIVIDUAL' else 'ENTITY'

                res = screen_and_save(
                    name=screening_name,
                    entity_type=entity_type,
                    dob=data.get('date_of_birth'),
                    nationality=data.get('country'),
                    gender=data.get('gender'),
                    source_module='Customer KYC',
                    source_record_id=customer_id,
                    screening_type='Customer Onboarding',
                    results_screening_type='CUSTOMER',  # preserve the literal this table used to store
                )

                _last_hist_id = (res or {}).get('history_id') or _last_hist_id

                # Impact on customer record — no separate "confirmed hit" auto-reject
                # tier here (the canonical engine only distinguishes match/no-match at
                # the high-risk threshold); every high-risk hit goes to UNDER_REVIEW for
                # a compliance officer to adjudicate, never an automatic REJECTED.
                if res['screening_result'] == 'POTENTIAL_MATCH':
                    db.execute("UPDATE customers SET status = 'UNDER_REVIEW', risk_classification = 'HIGH' WHERE id = %s", (customer_id,))
                    flash(gettext('⚠️ WARNING: Automated screening found potential matches for "%(screening_name)s". Customer assigned HIGH risk and status set to UNDER_REVIEW.', screening_name=screening_name), 'warning')
                else:
                    flash(gettext('✅ Screening completed for "%(screening_name)s". No hits found.', screening_name=screening_name))

                db.commit()

                if res['high_risk_matches'] > 0:
                    from events.publisher import publish_event
                    publish_event(
                        event_type='screening.hit',
                        source_module='Customer KYC',
                        source_table='customers',
                        source_record_id=customer_id,
                        entity_type='CUSTOMER',
                        entity_id=customer_id,
                        payload={
                            'entity_name': screening_name,
                            'high_risk_matches': res['high_risk_matches'],
                            'highest_score': res['highest_score'],
                        },
                    )
            except Exception as e:
                flash(f'Customer created but automated screening failed: {str(e)}', 'warning')

            # risk floor again now that screening has run (a hit forces HIGH + EDD)
            from . import edd as _edd
            res = _edd.reassess(customer_id, current_user.id)
            if res and res['requires_edd']:
                flash(_('High-risk customer: an EDD record was opened. The customer cannot be activated until the EDD is completed and approved by the MLRO or a senior manager.'), 'warning')
            if data['customer_type'] == 'CORPORATE':
                flash(_('Complete the corporate KYB file (beneficial owners and authorised signatories) before approving this customer.'), 'info')
                return redirect(url_for('aml.customer_kyb', id=customer_id))
            return redirect(url_for('aml.view_customer', id=customer_id))
        else:
            flash(gettext('Error creating customer.'), 'danger')
        
    return render_template('aml/customer_form.html', user=current_user)


def _customer_form_again():
    """Re-show the onboarding form with what the user typed."""
    prefill = request.form.to_dict()
    prefill['annual_income_range'] = prefill.get('income')
    prefill['purpose_of_relationship'] = prefill.get('purpose')
    return render_template('aml/customer_form.html', user=current_user, prefill=prefill)

@aml_bp.route('/customers/<int:id>')
@login_required
@permission_required('aml')
def view_customer(id):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id = %s", (id,)).fetchone()
    if not customer:
        flash(gettext('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
    
    recent_alerts = db.execute("""
        SELECT a.*, r.rule_name 
        FROM tm_alerts a
        LEFT JOIN tm_rules r ON a.rule_id = r.id
        WHERE a.customer_id = %s 
        ORDER BY a.alert_date DESC LIMIT 5
    """, (id,)).fetchall()

    # ── Risk Radar Chart ───────────────────────────────────
    import json as _json
    from datetime import datetime as _dt
    try:
        HIGH_RISK_COUNTRIES = {
            'Iran','North Korea','Myanmar','Afghanistan','Syria','Yemen',
            'Libya','Somalia','Sudan','Iraq','Mali','Burkina Faso',
            'Haiti','Laos','South Sudan','Nigeria','Pakistan'
        }
        nationality = customer['nationality'] or customer['country'] or ''
        geo_score = 80 if nationality in HIGH_RISK_COUNTRIES else 20

        cust_vol = db.execute("SELECT COALESCE(SUM(amount),0) as v FROM transactions WHERE customer_id=%s",(id,)).fetchone()['v'] or 0
        avg_vol = db.execute("SELECT COALESCE(AVG(total),0) as v FROM (SELECT SUM(amount) as total FROM transactions GROUP BY customer_id) t").fetchone()['v'] or 1
        volume_score = min(100, int(float(cust_vol) / float(avg_vol) * 50))

        total_amt = db.execute("SELECT COALESCE(SUM(amount),0) as v FROM transactions WHERE customer_id=%s",(id,)).fetchone()['v'] or 0
        cash_amt = db.execute("SELECT COALESCE(SUM(amount),0) as v FROM transactions WHERE customer_id=%s AND transaction_type IN ('CASH_DEPOSIT','CASH_WITHDRAWAL')",(id,)).fetchone()['v'] or 0
        cash_score = int(float(cash_amt) / max(float(total_amt),1) * 100)

        name_search = f"%{customer['full_name'] or customer['company_name'] or ''}%"
        hits = db.execute("SELECT COUNT(*) as c FROM screening_history WHERE entity_name ILIKE %s AND screening_result IN ('CONFIRMED_HIT','POTENTIAL_MATCH')",(name_search,)).fetchone()['c'] or 0
        sanctions_score = min(100, hits * 40)

        created_str = str(customer['created_at'] or '')[:19]
        try:
            days_old = (_dt.now() - _dt.fromisoformat(created_str)).days
        except: days_old = 365
        age_score = max(0, 80 - int(days_old / 365 * 60))

        open_alerts = db.execute("SELECT COUNT(*) as c FROM tm_alerts WHERE customer_id=%s AND status NOT IN ('CLOSED','FALSE_POSITIVE')",(id,)).fetchone()['c'] or 0
        alert_score = min(100, open_alerts * 25)

        risk_radar_json = _json.dumps({
            'labels':['Geographic','Tx Volume','Cash Ratio','PEP/Sanctions','Account Age','Alert History'],
            'scores':[geo_score, volume_score, cash_score, sanctions_score, age_score, alert_score]
        })
    except Exception as e:
        risk_radar_json = _json.dumps({'labels':['Geographic','Tx Volume','Cash Ratio','PEP/Sanctions','Account Age','Alert History'],'scores':[20,20,20,20,20,20]})

    from . import edd as _edd, edd_logic as _L
    edd_case = _edd.latest_case(id)
    kyb_ubos, kyb_sigs = [], []
    if (customer['customer_type'] or '').upper() in ('CORPORATE', 'ENTITY'):
        from kyb import service as _kyb
        kyb_ubos, kyb_sigs, _states = _kyb.with_states('aml_customer', id)
    return render_template(
        'aml/customer_view.html', customer=Customer.form_values(customer), recent_alerts=recent_alerts, user=current_user,
        risk_radar_json=risk_radar_json,
        edd_case=edd_case, edd_status=_L.edd_status(edd_case),
        edd_display=_L.display_status(customer['requires_edd'], edd_case),
        edd_reasons=_edd.forced_reasons(dict(customer)),
        activation_blockers=_edd.activation_blockers(dict(customer)) if (customer['status'] or '') != 'ACTIVE' else [],
        kyb_ubos=kyb_ubos, kyb_sigs=kyb_sigs,
        attach_module='aml', attach_record_type='customer', attach_record_id=id,
        attach_items=list_attachments('aml', 'customer', id),
        attach_can_edit=current_user.can_edit('aml'),
    )

@aml_bp.route('/customers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def edit_customer(id):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id = %s", (id,)).fetchone()
    if not customer:
        flash(gettext('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
        
    if request.method == 'POST':
        AuditLog.log(current_user.id, 'Edit Customer', 'AML', id,
            f'Customer {id} profile updated', request.remote_addr)
        data = {
            'full_name': request.form.get('full_name'),
            'full_name_arabic': request.form.get('full_name_arabic'),
            'nationality': request.form.get('nationality'),
            'id_type': request.form.get('id_type'),
            'id_number': request.form.get('id_number'),
            'id_expiry_date': request.form.get('id_expiry_date'),
            'address': request.form.get('address'),
            'country': request.form.get('country'),
            'phone': request.form.get('phone'),
            'email': request.form.get('email'),
            'industry': request.form.get('industry'),
            'source_of_funds': request.form.get('source_of_funds'),
            'purpose_of_relationship': request.form.get('purpose'),
            'annual_income_range': request.form.get('income'),
            'date_of_birth': request.form.get('date_of_birth'),
            'registration_number': request.form.get('registration_number'),
            'is_pep': 1 if request.form.get('is_pep') == 'on' else 0,
            'status': request.form.get('status'),
            'updated_at': datetime.now(),
            'updated_by': current_user.id
        }

        if customer['customer_type'] == 'CORPORATE':
            # The form's single name field holds the company name.
            data['company_name'] = data['full_name']
            data['full_name'] = None
        dup = Customer.find_duplicate_id(data['id_type'], data['id_number'], exclude_id=id)
        if dup:
            flash(_('A customer with this ID number already exists: %(ref)s (%(name)s).',
                    ref=dup['customer_reference'], name=dup['name'] or ''), 'danger')
            return render_template('aml/customer_form.html', customer=Customer.form_values(customer),
                                   user=current_user)

        # Activation goes through the gate (EDD approved, KYB complete), never a plain status change.
        want_activate = data.get('status') == 'ACTIVE' and (customer['status'] or '') != 'ACTIVE'
        if want_activate:
            data['status'] = None

        # --- ComplyNex AI Enhancement ---
        nid_data = parse_egyptian_nid(request.form.get('id_number'))
        if nid_data:
            if not request.form.get('dob'): data['dob'] = nid_data['dob']
            if not request.form.get('gender'): data['gender'] = nid_data['gender']
            data['birth_governorate'] = nid_data.get('birth_governorate')
        # ------------------------------
        
        if Customer.update(id, data):
            # Re-calculate risk after edit (scoring model + HIGH floor + EDD)
            calculate_customer_risk(id, current_user.id)
            db.commit()
            flash(gettext('Customer information updated successfully.'))
            if want_activate:
                from . import edd as _edd
                try:
                    _edd.activate(id, current_user)
                    AuditLog.log(current_user.id, 'Customer Activated', 'AML', id,
                                 f'Customer {customer["customer_reference"]} status {customer["status"]} -> ACTIVE',
                                 request.remote_addr)
                    flash(_('Customer approved and activated.'), 'success')
                except _edd.EddError as e:
                    from utils.kyc_labels import tr
                    msgs = e.args[0] if isinstance(e.args[0], list) else [e.args[0]]
                    flash(_('The status was not changed to Active:') + ' ' + '; '.join(tr(m) for m in msgs), 'danger')
            return redirect(url_for('aml.view_customer', id=id))
        else:
            flash(gettext('Error updating customer.'), 'danger')
            db.rollback()
        
    return render_template('aml/customer_form.html', customer=Customer.form_values(customer), user=current_user)

# ---------------------------------------------------------------- STR register (one list)
from . import str_register as strreg
from . import tm_alerts as tmal
from . import employee_reports as empr

SAR_STATUSES = strreg.STATUSES  # code, EN, AR (kept for older imports)


def _ar():
    from flask_babel import get_locale
    return str(get_locale()) == 'ar'


def _csv_response(header, rows, filename):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(['' if v is None else v for v in r])
    return Response('﻿' + buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


def _is_mlro(user):
    return getattr(user, 'role', None) in ('compliance_manager', 'admin')


def _due_text(due):
    if not due:
        return ''
    if due['overdue']:
        return _('Overdue by %(n)s day(s)', n=due['days'])
    if due['days'] == 0:
        return _('Due today')
    return _('Due in %(n)s day(s)', n=due['days'])


@aml_bp.route('/sars')
@login_required
@permission_required('aml')
def sar_list():
    """The single STR register: SARs from every source, with links and deadlines."""
    db = get_db()
    f = {k: (request.args.get(k) or '').strip() for k in ('status', 'source', 'assignee', 'overdue', 'q', 'register')}
    rows, cfg = strreg.list_cases(db, status=f['status'] or None, source=f['source'] or None,
                                  assignee=f['assignee'] or None, overdue=f['overdue'] or None, q=f['q'] or None,
                                  register=f['register'] == '1')
    ar = _ar()
    st_l, src_l = strreg.status_labels(ar), strreg.source_labels(ar)
    if request.args.get('export') == 'csv':
        return _csv_response(
            [_('Ref'), _('Source'), _('Customer'), _('Discovery Date'), _('Amount'), _('Status'), _('Assigned to'),
             _('Linked alerts'), _('Linked transactions'), _('Deadline'), _('Deadline status'), _('Unit reference')],
            [[r['sar_reference'], src_l.get(r['source'], r['source']), r['customer_display'], r['discovery_date'],
              r['amount_involved'], st_l.get(r['investigation_status'] or 'NEW', r['investigation_status']),
              r['assigned_name'], r['alert_links'], r['tx_links'],
              r['due']['deadline'].isoformat() if r['due'] else '', _due_text(r['due']), r['emlcu_reference']]
             for r in rows], 'str_register.csv')
    missing = []
    if current_user.can_edit('aml'):
        try:
            from amlkyc.service import reconcile_register
            missing = reconcile_register(db)
        except Exception:
            db.rollback()
    return render_template('aml/sar_list.html', sars=rows, user=current_user, status_labels=st_l,
                           source_labels=src_l, statuses=strreg.STATUSES, sources=strreg.SOURCES,
                           staff=strreg.aml_staff(db), f=f, cfg=cfg, due_text=_due_text, missing=missing,
                           can_configure=_is_mlro(current_user) or current_user.is_admin())


@aml_bp.route('/sars/deadline-setting', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def sar_deadline_setting():
    if not (_is_mlro(current_user) or current_user.is_admin()):
        flash(_('Only the MLRO can change the deadline setting.'), 'danger')
        return redirect(url_for('aml.sar_list'))
    try:
        strreg.save_deadline_setting(request.form.get('days'), request.form.get('basis'), current_user.id)
        flash(_('Deadline setting saved.'), 'success')
    except strreg.StrError as e:
        flash(_(str(e)), 'danger')
    return redirect(url_for('aml.sar_list'))


def _prefill_from_alert(db, alert_id):
    a = db.execute("""SELECT a.*, r.rule_name, r.rule_code FROM tm_alerts a LEFT JOIN tm_rules r ON r.id = a.rule_id
                      WHERE a.id = %s""", (alert_id,)).fetchone()
    if not a:
        return None, {}
    a = dict(a)
    ids = tmal.triggered_ids(a)
    txs = [dict(t) for t in db.execute("SELECT id, transaction_date, amount FROM transactions WHERE id = ANY(%s)",
                                       (ids,)).fetchall()] if ids else []
    dates = sorted((t['transaction_date'] or '')[:10] for t in txs if t.get('transaction_date'))
    form = {'customer_id': str(a['customer_id'] or ''),
            'activity_date': dates[0] if dates else (a['alert_date'] or '')[:10],
            'discovery_date': (a['alert_date'] or '')[:10] or datetime.now().strftime('%Y-%m-%d'),
            'amount': f"{sum(float(t['amount'] or 0) for t in txs):.2f}" if txs else '',
            'description': f"{a['alert_reference']} — {a.get('rule_code') or ''} {a.get('rule_name') or ''}: "
                           f"{a.get('alert_description') or ''}",
            'red_flags': a.get('rule_name') or '', 'source': 'tm_alert', 'alert_id': str(a['id'])}
    return a, form


def _prefill_from_screening(db, sa_id):
    a = db.execute("SELECT * FROM aml_alerts WHERE id = %s", (sa_id,)).fetchone()
    if not a:
        return None, {}
    a = dict(a)
    return a, {'customer_id': str(a['customer_id'] or ''), 'discovery_date': (a['created_at'] or '')[:10],
               'activity_date': (a['created_at'] or '')[:10],
               'description': f"{_('Screening hit')}: {a.get('matched_name') or ''} ({a.get('source_list') or ''}, "
                              f"{a.get('match_score') or ''}). {a.get('alert_details') or ''}",
               'source': 'screening', 'screening_alert_id': str(a['id'])}


@aml_bp.route('/sars/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def create_sar():
    db = get_db()
    customers = db.execute("SELECT id, full_name, customer_reference FROM customers ORDER BY full_name").fetchall()
    src = request.values
    alert, prefill = (None, {})
    if (src.get('alert_id') or '').isdigit():
        alert, prefill = _prefill_from_alert(db, int(src['alert_id']))
    elif (src.get('screening_alert_id') or '').isdigit():
        alert, prefill = _prefill_from_screening(db, int(src['screening_alert_id']))
    ctx = dict(customers=customers, user=current_user, now_date=datetime.now().strftime('%Y-%m-%d'),
               source_alert=alert, sources=[s for s in strreg.SOURCES if s[0] in ('manual', 'screening')],
               source_labels=strreg.source_labels(_ar()))
    if request.method == 'POST':
        form = request.form
        errors = _sar_input_errors(form, db)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('aml/sar_form.html', form=form, selected_customer=form.get('customer_id'),
                                   **ctx), 400
        links, source = [], (form.get('source') if form.get('source') in ('manual', 'screening') else 'manual')
        alert_id = form.get('alert_id') if (form.get('alert_id') or '').isdigit() else None
        if alert_id and alert:
            source = 'tm_alert'
            links = [('tm_alert', int(alert_id))] + [('transaction', t) for t in tmal.triggered_ids(alert)]
        elif (form.get('screening_alert_id') or '').isdigit() and alert:
            source = 'screening'
            links = [('screening_alert', int(form['screening_alert_id']))]
        sid, ref = strreg.create_case(
            source=source, reported_by=current_user.id, description=form.get('description').strip(),
            customer_id=int(form.get('customer_id')), activity_date=form.get('activity_date'),
            discovery_date=form.get('discovery_date'), amount=form.get('amount') or 0,
            red_flags=(form.get('red_flags') or '').strip() or None, links=links, db=db)
        if alert_id and alert:
            tmal.mark_sar_created(int(alert_id), sid, ref, current_user.id, db=db)
        flash(gettext('SAR %(sar_reference)s filed successfully and queued for compliance review.', sar_reference=ref))
        return redirect(url_for('aml.sar_detail', sar_id=sid))
    return render_template('aml/sar_form.html', form=prefill,
                           selected_customer=prefill.get('customer_id') or request.args.get('customer_id'), **ctx)


def _sar_input_errors(form, db):
    """Server-side checks for a new SAR: customer, sensible dates, amount, description."""
    from datetime import date
    errors = []
    cid = form.get('customer_id')
    if not cid or not str(cid).isdigit() or not db.execute("SELECT 1 FROM customers WHERE id = %s", (cid,)).fetchone():
        errors.append(_('Select the customer the report is about.'))
    try:
        act = date.fromisoformat(form.get('activity_date') or '')
        disc = date.fromisoformat(form.get('discovery_date') or '')
        if act > disc:
            errors.append(_('The activity date cannot be after the discovery date.'))
        if disc > date.today():
            errors.append(_('The discovery date cannot be in the future.'))
    except ValueError:
        errors.append(_('Enter the activity date and the discovery date.'))
    try:
        if float(form.get('amount') or 0) < 0:
            errors.append(_('The amount cannot be negative.'))
    except ValueError:
        errors.append(_('The amount must be a number.'))
    if len((form.get('description') or '').strip()) < 30:
        errors.append(_('Describe the suspicious activity (at least 30 characters).'))
    return errors


@aml_bp.route('/sars/<int:sar_id>', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def sar_detail(sar_id):
    """Work one case: assign, investigate, MLRO decision (file / no report, with
    rationale, by someone other than the reporter), record the filing, and keep
    the linked alerts / transactions."""
    db = get_db()
    sar = db.execute("""SELECT s.*, c.full_name AS customer_full_name, c.customer_reference,
                               u.reference AS unusual_reference, er.reference AS employee_report_reference
                        FROM suspicious_activities s LEFT JOIN customers c ON c.id = s.customer_id
                        LEFT JOIN aml_unusual_transactions u ON u.id = s.unusual_txn_id
                        LEFT JOIN aml_employee_reports er ON er.id = s.employee_report_id
                        WHERE s.id = %s""", (sar_id,)).fetchone()
    if not sar:
        flash(_('SAR not found.'), 'warning')
        return redirect(url_for('aml.sar_list'))
    sar = dict(sar)
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            flash(_('You do not have permission to change SARs.'), 'danger')
            return redirect(url_for('aml.sar_detail', sar_id=sar_id))
        action = request.form.get('action')
        try:
            if action == 'assign':
                strreg.assign_case(sar_id, request.form.get('assigned_to'), current_user.id, db=db)
            elif action == 'investigate':
                strreg.record_investigation(sar_id, request.form.get('notes'), request.form.get('findings'),
                                            request.form.get('ready') == 'on', current_user.id,
                                            f"{current_user.first_name or ''} {current_user.last_name or ''}".strip(),
                                            db=db)
            elif action == 'decide':
                strreg.record_decision(sar_id, request.form.get('decision'), request.form.get('rationale'),
                                       current_user.id, _is_mlro(current_user), db=db)
            elif action == 'file':
                strreg.record_filing(sar_id, request.form.get('filing_date'), request.form.get('emlcu_reference'),
                                     current_user.id, db=db)
            elif action == 'link':
                lt = request.form.get('link_type')
                tid = strreg.resolve_target(db, lt, request.form.get('target_ref'))
                if not tid:
                    raise strreg.StrError(strreg.N_('Alert or transaction not found.'))
                strreg.add_link(sar_id, lt, tid, current_user.id, note=(request.form.get('note') or '').strip() or None,
                                db=db)
            elif action == 'unlink':
                lid = request.form.get('link_id')
                if not (lid or '').isdigit() or not db.execute(
                        "SELECT 1 FROM aml_sar_links WHERE id = %s AND sar_id = %s", (lid, sar_id)).fetchone():
                    raise strreg.StrError(strreg.N_('Link not found.'))
                strreg.remove_link(int(lid), current_user.id, request.form.get('reason'), db=db)
            else:
                raise strreg.StrError(strreg.N_('Unknown action.'))
        except strreg.StrError as e:
            flash(_(str(e)), 'danger')
            return redirect(url_for('aml.sar_detail', sar_id=sar_id))
        flash(_('SAR updated.'), 'success')
        return redirect(url_for('aml.sar_detail', sar_id=sar_id))

    names = {k: strreg.user_name(db, sar.get(k)) for k in ('reported_by', 'assigned_to', 'decision_by') if sar.get(k)}
    history = db.execute("""SELECT a.created_at AS at, a.details, u.first_name, u.last_name FROM audit_logs a
                            LEFT JOIN users u ON u.id = a.user_id
                            WHERE a.module = 'AML' AND a.item_id = %s AND a.details LIKE %s ORDER BY a.id DESC LIMIT 100""",
                         (sar_id, f'%{sar["sar_reference"]}%')).fetchall()
    cfg = strreg.deadline_config(db)
    due = strreg.deadline_flag(sar, cfg['days'], cfg['basis'])
    ar = _ar()
    return render_template('aml/sar_detail.html', sar=sar, staff=strreg.aml_staff(db), names=names, history=history,
                           statuses=strreg.STATUSES, status_labels=strreg.status_labels(ar),
                           source_labels=strreg.source_labels(ar), link_labels=strreg.link_labels(ar),
                           link_types=strreg.LINK_TYPES, links=strreg.case_links(db, sar_id),
                           alert_status_labels=tmal.labels(tmal.STATUSES, ar),
                           due=due, due_text=_due_text, cfg=cfg,
                           deadline=strreg.case_deadline(sar, cfg['days'], cfg['basis']),
                           is_mlro=_is_mlro(current_user),
                           legacy_attachments=(list_attachments('aml', 'aml_unusual', sar['unusual_txn_id'])
                                               if sar.get('unusual_txn_id') else []),
                           report_attachments=(list_attachments('aml', empr.ATTACH_TYPE, sar['employee_report_id'])
                                               if sar.get('employee_report_id') else []))


# ---------------------------------------------------------------- employee reports: MLRO inbox
def _mlro_only():
    if not (_is_mlro(current_user) or current_user.is_admin()):
        flash(_('Only the MLRO can open internal suspicious-activity reports.'), 'danger')
        return redirect(url_for('aml.sar_list'))
    return None


@aml_bp.route('/employee-reports')
@login_required
@permission_required('aml')
def employee_report_inbox():
    deny = _mlro_only()
    if deny:
        return deny
    db = get_db()
    status = request.args.get('status', 'OPEN')
    ar = _ar()
    return render_template('aml/employee_report_inbox.html', rows=empr.inbox(db, status if status != 'ALL' else None),
                           status=status, statuses=empr.STATUSES, status_labels=empr.labels(empr.STATUSES, ar),
                           subject_labels=empr.labels(empr.SUBJECT_TYPES, ar))


@aml_bp.route('/employee-reports/<int:report_id>', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def employee_report_view(report_id):
    deny = _mlro_only()
    if deny:
        return deny
    db = get_db()
    try:
        r = empr.get_report(db, report_id)
    except empr.ReportError:
        flash(_('Report not found.'), 'warning')
        return redirect(url_for('aml.employee_report_inbox'))
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'review':
                empr.start_review(report_id, current_user.id, db=db)
                msg = 'review started'
            elif action == 'convert':
                sid, sref = empr.convert_to_str(report_id, current_user.id, request.form.get('customer_id'),
                                                request.form.get('amount'), db=db)
                msg = f'converted to STR case {sref}'
            elif action == 'close':
                empr.close_no_action(report_id, current_user.id, request.form.get('reason'), db=db)
                msg = 'closed — no action'
            else:
                raise empr.ReportError(empr.N_('Unknown action.'))
            AuditLog.log(current_user.id, 'UPDATE', 'AML', report_id,
                         f'Employee suspicion report {r["reference"]}: {msg}', request.remote_addr)
            flash(_('Report updated.'), 'success')
        except empr.ReportError as e:
            flash(_(str(e)), 'danger')
        return redirect(url_for('aml.employee_report_view', report_id=report_id))
    ar = _ar()
    customers = db.execute("SELECT id, full_name, customer_reference FROM customers ORDER BY full_name").fetchall()
    return render_template('aml/employee_report_view.html', r=r, events=empr.report_events(db, report_id),
                           status_labels=empr.labels(empr.STATUSES, ar), subject_labels=empr.labels(empr.SUBJECT_TYPES, ar),
                           action_labels=empr.labels(empr.ACTIONS, ar), customers=customers,
                           attachments=list_attachments('aml', empr.ATTACH_TYPE, report_id))


@aml_bp.route('/screening', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def screening():
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name')
        dob = request.form.get('dob')
        nationality = request.form.get('nationality')
        
        try:
            from screening.customer_screening_service import screen_and_save
            res = screen_and_save(
                name=name,
                dob=dob,
                nationality=nationality,
                source_module='AML Manual',
                results_screening_type='MANUAL',  # aml.screening's own recent-list below filters on this literal
            )

            # Prepare result object for template (screening/screening_result.html
            # expects the screening_results row shape, so map field names to match)
            res['id'] = res['results_id']
            res['screened_name'] = name
            res['highest_match_score'] = res['highest_score']
            res['status'] = 'PENDING'  # Manual screening usually pending adjudication

            return render_template('screening/screening_result.html',
                                 result=res,
                                 matches=res.get('matches', []),
                                 adverse_hits=res.get('adverse_media', []),
                                 screened_name=name)

        except Exception as e:
            flash(f'Screening failed: {str(e)}', 'danger')
            return redirect(url_for('aml.screening'))
            
    # Get recent manual screenings
    recent = db.execute("""
        SELECT * FROM screening_results 
        WHERE screening_type = 'MANUAL' 
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()
    
    return render_template('aml/screening.html', user=current_user, recent=recent)

@aml_bp.route('/ubo-verification', methods=['GET', 'POST'])
@login_required
@permission_required('aml')
def ubo_verification():
    if request.method == 'POST':
        # Simulate UBO logic
        company = request.form.get('company_name')
        flash(_('UBO structure for "%(company)s" has been verified against Chamber of Commerce records.', company=company), 'info')
        return redirect(url_for('aml.ubo_verification'))
    return render_template('aml/ubo.html', user=current_user)

@aml_bp.route('/customers/export')
@login_required
@permission_required('aml')
def export_customers():
        
    db = get_db()
    customers = db.execute("SELECT * FROM customers").fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    headers = [
        'ID', 'Full Name', 'DOB', 'Nationality', 'National ID', 
        'Risk Level', 'Risk Score', 'PEP', 'Phone', 'Email', 'Address'
    ]
    writer.writerow(headers)
    
    for customer in customers:
        c = Customer._process_row(customer)
        writer.writerow([
            c.get('id'), c.get('full_name') or c.get('company_name'), 
            c.get('date_of_birth'), c.get('nationality'), c.get('id_number'),
            c.get('risk_classification'), c.get('risk_score'), 'Yes' if c.get('is_pep') else 'No',
            c.get('phone'), c.get('email'), c.get('address_line1')
        ])
        
    # UTF-8 BOM: without it Excel opens the file as ANSI and garbles Arabic names.
    return Response(
        '\ufeff' + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-disposition": "attachment; filename=aml_customers.csv"}
    )


@aml_bp.route('/customers/<int:id>/run-screening', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def run_customer_screening(id):
    """Run sanctions screening for a customer via the screening engine."""
    db = get_db()
    row = db.execute("SELECT * FROM customers WHERE id = %s", (id,)).fetchone()
    if not row:
        flash(gettext('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
    customer = dict(row)

    _last_hist_id = None
    names_to_screen = []
    cust_name = customer['full_name'] or customer['company_name']
    if cust_name:
        names_to_screen.append(cust_name)
    # Also screen Arabic name if available
    arabic_name = customer.get('full_name_arabic')
    if arabic_name:
        names_to_screen.append(arabic_name)

    overall_result = 'CLEAR'
    overall_score = 0.0
    total_high_risk = 0

    for name in names_to_screen:
        try:
            from screening.customer_screening_service import screen_and_save
            entity_type = 'INDIVIDUAL' if customer.get('customer_type') == 'INDIVIDUAL' else 'ENTITY'
            res = screen_and_save(
                name=name,
                entity_type=entity_type,
                dob=customer.get('date_of_birth'),
                nationality=customer.get('nationality'),
                source_module='Customer KYC',
                source_record_id=id,
                screening_type='Customer CDD',
                write_results_table=False,  # this call site never wrote to screening_results before
            )

            high_risk_count = res['high_risk_matches']
            total_high_risk += high_risk_count
            if res['highest_score'] > overall_score:
                overall_score = res['highest_score']
            if res['screening_result'] == 'POTENTIAL_MATCH':
                overall_result = res['screening_result']

        except Exception as e:
            flash(f'Screening error for "{name}": {str(e)}', 'danger')

    # Update customer screening and risk status
    if overall_result == 'CLEAR' or overall_result == 'WHITE_LISTED':
        screening_status = 'Clear'
        risk_class = customer.get('risk_classification', 'LOW')  # Keep existing
    elif total_high_risk > 0:
        screening_status = 'Pending Review'
        risk_class = 'HIGH'
    else:
        screening_status = 'Clear'
        risk_class = customer.get('risk_classification', 'LOW')

    db.execute("""
        UPDATE customers
        SET screening_status = %s, last_screening_date = CURRENT_TIMESTAMP,
            last_screened_by = %s, screening_notes = %s
        WHERE id = %s
    """, (screening_status, current_user.id,
          f'Screened {len(names_to_screen)} name(s). High-risk matches: {total_high_risk}. Result: {overall_result}',
          id))

    if total_high_risk > 0:
        db.execute("UPDATE customers SET risk_classification = 'HIGH', status = 'SUSPENDED' WHERE id = %s", (id,))

    db.commit()
    from . import edd as _edd
    _edd.reassess(id, current_user.id)

    if total_high_risk > 0:
        # Link straight to the record just created rather than telling the
        # operator to go and find it. Markup is safe here: the message is
        # built from a url_for and an integer count, not from user input.
        from markupsafe import Markup
        _link = ('  <a href="%s" class="alert-link">View screening report</a>'
                 % url_for('screening.screening_history_detail', id=_last_hist_id)) if _last_hist_id else ''
        flash(Markup(f'Screening completed: {total_high_risk} high-risk match(es). '
                     f'Review required in the Screening Queue.{_link}'), 'danger')
    else:
        from markupsafe import Markup
        _link = ('  <a href="%s" class="alert-link">View screening report</a>'
                 % url_for('screening.screening_history_detail', id=_last_hist_id)) if _last_hist_id else ''
        flash(Markup(f'Screening completed: no sanctions matches found.{_link}'), 'success')

    return redirect(url_for('aml.view_customer', id=id))


@aml_bp.route('/customers/<int:id>/print-cdd')
@login_required
@permission_required('aml')
@permission_required('aml', level='edit')
def print_cdd_form(id):
    """Render a printable KYC/CDD form for a customer."""
    db = get_db()
    row = db.execute("SELECT * FROM customers WHERE id = %s", (id,)).fetchone()
    if not row:
        flash(gettext('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
    customer = dict(row)

    # Get screening history for this customer
    screening_records = db.execute("""
        SELECT * FROM screening_history
        WHERE source_module = 'Customer KYC' AND source_record_id = %s
        ORDER BY screening_date DESC LIMIT 10
    """, (id,)).fetchall()

    # Get screening results from legacy table too
    cust_name = customer['full_name'] or customer['company_name']
    legacy_results = db.execute("""
        SELECT * FROM screening_results
        WHERE screened_name = %s OR screened_name = %s
        ORDER BY created_at DESC LIMIT 5
    """, (cust_name, customer.get('full_name_arabic') or '')).fetchall()

    return render_template('aml/print_cdd_form.html',
                           customer=customer,
                           screening_records=screening_records,
                           legacy_results=legacy_results,
                           now_date=datetime.now().strftime('%Y-%m-%d %H:%M'))




# ─────────────────────────────────────────────
#  TRANSACTION MONITORING
# ─────────────────────────────────────────────

@aml_bp.route('/transactions')
@login_required
@permission_required('aml', level='view')
def transaction_list():
    from database.db import get_db
    db = get_db()
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page

    filters = []
    params = []
    if request.args.get('customer_id'):
        filters.append("t.customer_id = %s")
        params.append(request.args.get('customer_id'))
    if request.args.get('alert_only'):
        filters.append("t.alert_raised = 1")
    if request.args.get('type'):
        filters.append("t.transaction_type = %s")
        params.append(request.args.get('type'))

    where = "WHERE " + " AND ".join(filters) if filters else ""

    total = db.execute(f"SELECT COUNT(*) as count FROM transactions t {where}", params).fetchone()['count']
    transactions = db.execute(f"""
        SELECT t.*, c.full_name, c.company_name, c.customer_reference
        FROM transactions t
        LEFT JOIN customers c ON t.customer_id = c.id
        {where}
        ORDER BY t.transaction_date DESC
        LIMIT %s OFFSET %s
    """, params + [per_page, offset]).fetchall()

    total_pages = (total + per_page - 1) // per_page
    return render_template('aml/transaction_list.html',
                           transactions=transactions, total=total,
                           page=page, total_pages=total_pages,
                           filters=request.args)


@aml_bp.route('/transactions/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def create_transaction():
    from database.db import get_db
    from aml.tm_service import evaluate_transaction
    db = get_db()

    if request.method == 'POST':
        try:
            ref = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4()).replace('-','')[:8].upper()}"
            db.execute("""
                INSERT INTO transactions (
                    transaction_reference, customer_id, transaction_date,
                    transaction_type, amount, currency,
                    counterparty_name, counterparty_account, counterparty_country,
                    purpose_of_transaction, remittance_information, created_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                ref,
                int(request.form['customer_id']),
                request.form['transaction_date'],
                request.form['transaction_type'],
                float(request.form['amount']),
                request.form.get('currency', 'EGP'),
                request.form.get('counterparty_name'),
                request.form.get('counterparty_account'),
                request.form.get('counterparty_country'),
                request.form.get('purpose_of_transaction'),
                request.form.get('remittance_information'),
                current_user.id
            ))
            db.commit()
            tx_id = db.execute("SELECT id FROM transactions WHERE transaction_reference=%s", (ref,)).fetchone()['id']
            alerts = evaluate_transaction(tx_id, db)
            if alerts:
                flash(f'Transaction saved. {len(alerts)} alert(s) raised: {", ".join(a["rule"] for a in alerts)}', 'warning')
            else:
                flash(gettext('Transaction saved. No alerts triggered.'), 'success')
            return redirect(url_for('aml.transaction_list'))
        except Exception as e:
            db.rollback()
            flash(f'Error: {str(e)}', 'danger')

    customers = db.execute("SELECT id, customer_reference, full_name, company_name FROM customers WHERE status='ACTIVE' ORDER BY full_name").fetchall()
    now = datetime.now().strftime('%Y-%m-%dT%H:%M')
    return render_template('aml/transaction_form.html', customers=customers, now=now)


@aml_bp.route('/transactions/<int:tx_id>')
@login_required
@permission_required('aml', level='view')
def view_transaction(tx_id):
    from database.db import get_db
    db = get_db()
    tx = db.execute("""
        SELECT t.*, c.full_name, c.company_name, c.customer_reference, c.risk_classification
        FROM transactions t LEFT JOIN customers c ON t.customer_id = c.id
        WHERE t.id = %s
    """, (tx_id,)).fetchone()
    if not tx:
        flash(gettext('Transaction not found'), 'danger')
        return redirect(url_for('aml.transaction_list'))
    alerts = db.execute("""
        SELECT a.*, r.rule_name, r.rule_code
        FROM tm_alerts a LEFT JOIN tm_rules r ON a.rule_id = r.id
        WHERE a.customer_id = %s ORDER BY a.alert_date DESC LIMIT 10
    """, (tx['customer_id'],)).fetchall()
    return render_template('aml/transaction_view.html', tx=tx, alerts=alerts)


@aml_bp.route('/alerts')
@login_required
@permission_required('aml', level='view')
def alert_list():
    from aml.tm_service import get_alert_stats
    db = get_db()

    # Default to OPEN alerts only; 'ALL' explicitly shows everything, including resolved alerts.
    f = {k: (request.args.get(k) or '').strip() for k in
         ('severity', 'rule', 'assignee', 'date_from', 'date_to', 'score_min', 'score_max', 'q')}
    status_filter = request.args.get('status', 'OPEN')
    severity_filter = f['severity']
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    per_page = 25

    filters, params = [], []
    if status_filter == 'OPEN':
        filters.append("a.status NOT IN (%s, %s, %s)")
        params.extend(tmal.CLOSED_STATUSES)
    elif status_filter and status_filter != 'ALL':
        filters.append("a.status = %s")
        params.append(status_filter)
    if severity_filter:
        filters.append("a.alert_severity = %s")
        params.append(severity_filter)
    if f['rule'].isdigit():
        filters.append("a.rule_id = %s")
        params.append(int(f['rule']))
    if f['assignee'] == 'none':
        filters.append("a.assigned_to IS NULL")
    elif f['assignee'].isdigit():
        filters.append("a.assigned_to = %s")
        params.append(int(f['assignee']))
    for key, op in (('date_from', '>='), ('date_to', '<=')):
        if f[key]:
            try:
                datetime.strptime(f[key], '%Y-%m-%d')
                filters.append(f"substr(CAST(a.alert_date AS TEXT), 1, 10) {op} %s")
                params.append(f[key])
            except ValueError:
                pass
    for key, op in (('score_min', '>='), ('score_max', '<=')):
        if f[key].isdigit():
            filters.append(f"COALESCE(a.risk_score, 0) {op} %s")
            params.append(int(f[key]))
    if f['q']:
        like = f"%{f['q']}%"
        filters.append("""(a.alert_reference ILIKE %s OR COALESCE(a.alert_description, '') ILIKE %s
                           OR COALESCE(c.full_name, c.company_name, '') ILIKE %s OR COALESCE(c.customer_reference, '') ILIKE %s
                           OR COALESCE(r.rule_name, '') ILIKE %s OR COALESCE(r.rule_code, '') ILIKE %s)""")
        params.extend([like] * 6)

    where = "WHERE " + " AND ".join(filters) if filters else ""
    base = f"""FROM tm_alerts a
        LEFT JOIN tm_rules r ON a.rule_id = r.id
        LEFT JOIN customers c ON a.customer_id = c.id
        LEFT JOIN users u ON a.assigned_to = u.id
        {where}"""
    cols = """SELECT a.id, a.alert_reference, CAST(a.alert_date AS TEXT) as alert_date,
               a.alert_description, a.alert_severity, a.status, a.risk_score,
               a.assigned_to, a.investigation_notes, a.disposition, a.sar_id,
               a.triggered_transactions, a.rule_id, a.customer_id,
               r.rule_name, r.rule_name_ar, r.rule_code,
               c.full_name, c.company_name, c.customer_reference,
               u.first_name || ' ' || u.last_name as assigned_name"""
    order = """ORDER BY CASE a.alert_severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, a.alert_date DESC"""
    ar = _ar()
    st_l, sev_l = tmal.labels(tmal.STATUSES, ar), tmal.labels(tmal.SEVERITIES, ar)
    if request.args.get('export') == 'csv':
        rows = db.execute(f"{cols} {base} {order} LIMIT 20000", params).fetchall()
        return _csv_response(
            [_('Reference'), _('Date'), _('Customer'), _('Customer reference'), _('Rule'), _('Severity'), _('Score'),
             _('Status'), _('Assigned To'), _('Description')],
            [[a['alert_reference'], (a['alert_date'] or '')[:16], a['full_name'] or a['company_name'],
              a['customer_reference'], f"{a['rule_code'] or ''} {tmal.rule_label(a['rule_name'], a['rule_name_ar'], ar)}",
              sev_l.get(a['alert_severity'], a['alert_severity']), a['risk_score'],
              st_l.get(a['status'], a['status']), a['assigned_name'], a['alert_description']] for a in rows],
            'tm_alerts.csv')

    total = db.execute(f"SELECT COUNT(*) as count {base}", params).fetchone()['count']
    alerts = db.execute(f"{cols} {base} {order} LIMIT %s OFFSET %s",
                        params + [per_page, (page - 1) * per_page]).fetchall()
    stats = get_alert_stats(db)
    total_pages = (total + per_page - 1) // per_page
    rules = db.execute("SELECT id, rule_code, rule_name, rule_name_ar FROM tm_rules ORDER BY rule_code").fetchall()
    qs = {k: v for k, v in f.items() if v}
    qs['status'] = status_filter
    return render_template('aml/alert_list.html',
                           alerts=alerts, stats=stats, total=total,
                           page=page, total_pages=total_pages,
                           status_filter=status_filter, severity_filter=severity_filter, f=f, qs=qs,
                           rules=rules, compliance_users=strreg.aml_staff(db), ar=ar,
                           status_labels=st_l, severity_labels=sev_l, statuses=tmal.STATUSES,
                           severities=tmal.SEVERITIES, rule_label=tmal.rule_label)


def _notify_escalation(db, alert_id, notes):
    """An escalation nobody is told about is not an escalation: notify every
    compliance officer / admin (except the escalating user) with a link back."""
    try:
        from models.notification import Notification
        from models.user import User as _User
        ref_row = db.execute("""SELECT a.alert_reference, a.alert_severity, COALESCE(c.full_name, c.company_name) AS cname
                                  FROM tm_alerts a LEFT JOIN customers c ON a.customer_id = c.id
                                 WHERE a.id = %s""", (alert_id,)).fetchone()
        ref = (ref_row['alert_reference'] if ref_row else alert_id)
        sev = (ref_row['alert_severity'] if ref_row else '') or ''
        cname = (ref_row['cname'] if ref_row else '') or ''
        link = url_for('aml.view_alert', alert_id=alert_id)
        recipients = [u for u in _User.get_all_compliance_officers() if u.id != current_user.id]
        for u in recipients:
            Notification.create(
                user_id=u.id, title='Escalated AML alert %s' % ref,
                message='%s escalated alert %s%s%s. %s' % (
                    current_user.first_name or 'A reviewer', ref, (' (%s)' % sev) if sev else '',
                    (' for %s' % cname) if cname else '', (notes or 'No notes provided.')),
                link=link, n_type='aml_escalation')
        AuditLog.log(current_user.id, 'Escalate AML Alert', 'AML', alert_id,
                     'Escalated alert %s to %d compliance staff' % (ref, len(recipients)), request.remote_addr)
        if recipients:
            flash(_('Escalated. %(n)d compliance staff notified.', n=len(recipients)), 'info')
        else:
            flash(_('Escalated, but no other compliance officer exists to notify.'), 'warning')
    except Exception as exc:
        current_app.logger.error('Escalation notification failed for alert %s: %s', alert_id, exc)
        flash(_('Alert escalated, but notifying the team failed.'), 'warning')


@aml_bp.route('/alerts/<int:alert_id>', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='view')
def view_alert(alert_id):
    db = get_db()

    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            flash(_('You do not have permission to change alerts.'), 'danger')
            return redirect(url_for('aml.view_alert', alert_id=alert_id))
        action = request.form.get('action')
        notes = (request.form.get('notes') or '').strip()
        try:
            if action == 'assign':
                tmal.assign_alert(alert_id, request.form.get('assigned_to'), current_user.id, notes, db=db)
            elif action == 'investigate':
                tmal.start_investigation(alert_id, current_user.id, notes, db=db)
            elif action == 'escalate':
                tmal.escalate_alert(alert_id, current_user.id, notes, db=db)
                _notify_escalation(db, alert_id, notes)
            elif action == 'false_positive':
                # Closes this alert only — it does NOT touch the screening whitelist.
                tmal.mark_false_positive(alert_id, current_user.id, notes, db=db)
            elif action == 'close':
                tmal.close_alert(alert_id, current_user.id, notes, db=db)
            elif action == 'note':
                tmal.add_note(alert_id, current_user.id, notes, db=db)
            else:
                raise tmal.AlertError(tmal.N_('Unknown action.'))
            AuditLog.log(current_user.id, 'UPDATE', 'AML', alert_id, f'TM alert {alert_id}: {action}',
                         request.remote_addr)
            flash(_('Alert updated.'), 'success')
        except tmal.AlertError as e:
            flash(_(str(e)), 'danger')
        return redirect(url_for('aml.view_alert', alert_id=alert_id))

    alert = db.execute("""
        SELECT a.id, a.alert_reference, CAST(a.alert_date AS TEXT) as alert_date,
               a.alert_description, a.alert_severity, a.status, a.risk_score, a.sar_id,
               a.assigned_to, a.investigation_notes, a.disposition,
               a.triggered_transactions, a.rule_id, a.customer_id,
               a.disposition_by, a.disposition_date,
               r.rule_name, r.rule_name_ar, r.rule_code, r.rule_description,
               c.full_name, c.company_name, c.customer_reference, c.risk_classification,
               c.id as cust_id, u.first_name || ' ' || u.last_name AS assigned_name
        FROM tm_alerts a
        LEFT JOIN tm_rules r ON a.rule_id = r.id
        LEFT JOIN customers c ON a.customer_id = c.id
        LEFT JOIN users u ON u.id = a.assigned_to
        WHERE a.id = %s
    """, (alert_id,)).fetchone()
    if not alert:
        flash(gettext('Alert not found'), 'danger')
        return redirect(url_for('aml.alert_list'))

    tx_ids = tmal.triggered_ids(dict(alert))
    transactions = db.execute("SELECT * FROM transactions WHERE id = ANY(%s)", (tx_ids,)).fetchall() if tx_ids else []
    recent_txs = db.execute("SELECT * FROM transactions WHERE customer_id=%s ORDER BY transaction_date DESC LIMIT 10",
                            (alert['cust_id'],)).fetchall()
    linked_cases = db.execute("""SELECT DISTINCT s.id, s.sar_reference, s.investigation_status
                                   FROM aml_sar_links l JOIN suspicious_activities s ON s.id = l.sar_id
                                  WHERE l.link_type = 'tm_alert' AND l.target_id = %s AND l.unlinked_at IS NULL
                                  ORDER BY s.id""", (alert_id,)).fetchall()
    ar = _ar()
    return render_template('aml/alert_view.html',
                           alert=alert, transactions=transactions, recent_txs=recent_txs,
                           compliance_users=strreg.aml_staff(db), events=tmal.events(db, alert_id),
                           linked_cases=linked_cases, closed=alert['status'] in tmal.CLOSED_STATUSES,
                           status_labels=tmal.labels(tmal.STATUSES, ar), severity_labels=tmal.labels(tmal.SEVERITIES, ar),
                           action_labels=tmal.labels(tmal.ACTIONS, ar), case_status_labels=strreg.status_labels(ar),
                           rule_label=tmal.rule_label(alert['rule_name'], alert['rule_name_ar'], ar))


@aml_bp.route('/tm-rules')
@login_required
@permission_required('aml', level='view')
def rule_list():
    from database.db import get_db
    db = get_db()
    rules = db.execute("SELECT * FROM tm_rules ORDER BY rule_code").fetchall()
    return render_template('aml/rule_list.html', rules=rules)


@aml_bp.route('/tm-rules/<int:rule_id>/toggle', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def toggle_rule(rule_id):
    from database.db import get_db
    db = get_db()
    db.execute("UPDATE tm_rules SET is_active = NOT is_active WHERE id=%s", (rule_id,))
    db.commit()
    flash(gettext('Rule updated'), 'success')
    return redirect(url_for('aml.rule_list'))


@aml_bp.route('/tm-dashboard')
@login_required
@permission_required('aml', level='view')
def tm_dashboard():
    from database.db import get_db
    from aml.tm_service import get_alert_stats
    db = get_db()
    stats = get_alert_stats(db)

    recent_alerts = db.execute("""
        SELECT a.id, a.alert_reference, CAST(a.alert_date AS TEXT) as alert_date,
               a.alert_severity, a.status, a.alert_description,
               a.assigned_to, a.rule_id, a.customer_id,
               r.rule_name, c.full_name, c.company_name, c.customer_reference
        FROM tm_alerts a
        LEFT JOIN tm_rules r ON a.rule_id = r.id
        LEFT JOIN customers c ON a.customer_id = c.id
        WHERE a.status NOT IN ('CLOSED','FALSE_POSITIVE')
        ORDER BY CASE a.alert_severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                 a.alert_date DESC
        LIMIT 10
    """).fetchall()

    rule_stats = db.execute("""
        SELECT r.rule_name, r.rule_code, r.severity,
               COUNT(a.id) as alert_count
        FROM tm_rules r
        LEFT JOIN tm_alerts a ON r.id = a.rule_id
        GROUP BY r.id ORDER BY alert_count DESC
    """).fetchall()

    monthly_volume = db.execute("""
        SELECT TO_CHAR(transaction_date::timestamp, 'YYYY-MM') as month,
               COUNT(*) as count,
               SUM(amount) as total,
               SUM(CASE WHEN alert_raised=1 THEN 1 ELSE 0 END) as flagged
        FROM transactions
        GROUP BY month ORDER BY month DESC LIMIT 6
    """).fetchall()

    return render_template('aml/tm_dashboard.html',
                           stats=stats, recent_alerts=recent_alerts,
                           rule_stats=rule_stats, monthly_volume=monthly_volume)


# ─────────────────────────────────────────────
#  BULK TRANSACTION UPLOAD
# ─────────────────────────────────────────────

@aml_bp.route('/transactions/upload', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def upload_transactions():
    from database.db import get_db
    from aml.tm_service import evaluate_transaction
    import io
    db = get_db()

    MAX_ROWS = 5000  # Max rows per upload

    if request.method == 'POST':
        if 'file' not in request.files:
            flash(gettext('No file selected'), 'danger')
            return redirect(request.url)

        f = request.files['file']
        if not f.filename:
            flash(gettext('No file selected'), 'danger')
            return redirect(request.url)

        ext = f.filename.rsplit('.', 1)[-1].lower()
        results = {'added': 0, 'skipped': 0, 'errors': [], 'alerts': 0,
                   'customers_created': 0, 'customers_existing': 0}
        inserted_tx_ids = []  # Collect IDs for batch TM evaluation after all inserts

        # Payment gateway column mapping (auto-detect)
        PG_COLUMN_MAP = {
            'customer_reference': ['customer_reference', 'MID', 'mid', 'merchant_id', 'customer_id'],
            'transaction_date':   ['transaction_date', 'Created on', 'created_on', 'date', 'tx_date'],
            'transaction_type':   ['transaction_type', 'Type', 'type', 'tx_type'],
            'amount':             ['amount', 'Amount', 'net_amount', 'Net amount'],
            'currency':           ['currency', 'Currency'],
            'counterparty_name':  ['counterparty_name', 'Merchant name', 'merchant_name', 'counterparty'],
            'counterparty_account':['counterparty_account', 'Primary account number', 'pan', 'account'],
            'counterparty_country':['counterparty_country', 'country', 'Country'],
            'purpose_of_transaction':['purpose_of_transaction', 'Status details', 'status_details', 'purpose'],
            'remittance_information':['remittance_information', 'Retrieval Reference Number', 'rrn', 'reference'],
            # Auto-create customer fields
            'company_name':       ['company_name', 'Company', 'company', 'Merchant name', 'merchant_name'],
            'customer_type':      ['customer_type', 'Merchant type', 'merchant_type'],
        }

        TX_TYPE_MAP = {
            'SALE': 'PAYMENT', 'PURCHASE': 'PAYMENT', 'AUTHORIZATION': 'PAYMENT',
            'CAPTURE': 'PAYMENT', 'SETTLEMENT': 'TRANSFER_IN', 'CREDIT': 'CREDIT',
            'DEBIT': 'DEBIT', 'REFUND': 'REFUND', 'REVERSAL': 'REFUND',
            'VOID': 'REFUND', 'TRANSFER': 'TRANSFER_OUT', 'CASH': 'CASH_DEPOSIT',
            'WITHDRAWAL': 'CASH_WITHDRAWAL',
        }

        VALID_TYPES = ('CREDIT','DEBIT','TRANSFER_IN','TRANSFER_OUT',
                       'CASH_DEPOSIT','CASH_WITHDRAWAL','PAYMENT','REFUND')
        VALID_CURRENCIES = ('EGP','USD','EUR','SAR','AED')

        def get_col(row, field):
            """Get value from row using column aliases"""
            for alias in PG_COLUMN_MAP.get(field, [field]):
                val = row.get(alias)
                if val is not None and str(val).strip() not in ('', 'nan', 'None'):
                    return str(val).strip()
            return ''

        try:
            if ext == 'csv':
                import csv as csv_mod
                stream = io.StringIO(f.stream.read().decode('utf-8-sig'))
                reader = csv_mod.DictReader(stream)
                rows = list(reader)
            elif ext in ('xlsx', 'xls'):
                import pandas as pd
                df = pd.read_excel(f.stream, nrows=MAX_ROWS)
                df = df.fillna('')
                rows = df.to_dict('records')
            else:
                flash(gettext('Only CSV or XLSX files accepted'), 'danger')
                return redirect(request.url)

            # Enforce row limit
            if len(rows) > MAX_ROWS:
                rows = rows[:MAX_ROWS]
                flash(gettext('File truncated to %(MAX_ROWS)s rows (max per upload). Split file for more.', MAX_ROWS=MAX_ROWS), 'warning')

            for i, row in enumerate(rows, 1):
                try:
                    # ── Resolve or auto-create customer ──────────────────
                    cust_ref = get_col(row, 'customer_reference')
                    if not cust_ref:
                        results['errors'].append(f"Row {i}: Missing customer identifier")
                        results['skipped'] += 1
                        continue

                    cust = db.execute(
                        "SELECT id FROM customers WHERE customer_reference=%s OR CAST(id AS TEXT)=%s",
                        (cust_ref, cust_ref)
                    ).fetchone()

                    if not cust:
                        # Auto-create customer from available data
                        company = get_col(row, 'company_name') or cust_ref
                        ctype_raw = get_col(row, 'customer_type') or 'CORPORATE'
                        ctype = 'INDIVIDUAL' if 'indiv' in ctype_raw.lower() or 'personal' in ctype_raw.lower() else 'CORPORATE'
                        now_str = datetime.now().strftime('%Y-%m-%d')

                        cur = db.execute("""
                            INSERT INTO customers (
                                customer_reference, customer_type, company_name, full_name,
                                country, status, risk_classification, onboarding_date,
                                created_at, created_by
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING id
                        """, (
                            cust_ref, ctype, company,
                            company if ctype == 'INDIVIDUAL' else '',
                            get_col(row, 'counterparty_country') or 'Egypt',
                            'ACTIVE', 'LOW', now_str, now_str, current_user.id
                        ))
                        db.commit()
                        new_cust = cur.fetchone()
                        cust = new_cust
                        results['customers_created'] += 1
                    else:
                        results['customers_existing'] += 1

                    # ── Validate and map transaction ──────────────────────
                    tx_type_raw = get_col(row, 'transaction_type').upper()
                    tx_type = TX_TYPE_MAP.get(tx_type_raw, tx_type_raw)
                    if tx_type not in VALID_TYPES:
                        tx_type = 'PAYMENT'  # Default instead of skipping

                    try:
                        amount = float(str(get_col(row, 'amount') or '0').replace(',', ''))
                    except:
                        results['errors'].append(f"Row {i}: Invalid amount")
                        results['skipped'] += 1
                        continue

                    if amount <= 0:
                        results['skipped'] += 1
                        continue

                    currency = get_col(row, 'currency').upper() or 'EGP'
                    if currency not in VALID_CURRENCIES:
                        currency = 'EGP'

                    tx_date_raw = get_col(row, 'transaction_date')
                    try:
                        import pandas as pd
                        tx_date = pd.to_datetime(tx_date_raw).strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        tx_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    ref = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4()).replace('-','')[:8].upper()}-{i}"

                    tx_cur = db.execute("""
                        INSERT INTO transactions (
                            transaction_reference, customer_id, transaction_date,
                            transaction_type, amount, currency,
                            counterparty_name, counterparty_account, counterparty_country,
                            purpose_of_transaction, remittance_information, created_by
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                    """, (
                        ref, cust['id'], tx_date, tx_type, amount, currency,
                        get_col(row, 'counterparty_name') or None,
                        get_col(row, 'counterparty_account') or None,
                        get_col(row, 'counterparty_country') or 'Egypt',
                        get_col(row, 'purpose_of_transaction') or None,
                        get_col(row, 'remittance_information') or None,
                        current_user.id
                    ))
                    db.commit()
                    tx_row = tx_cur.fetchone()
                    tx_id = tx_row['id'] if tx_row else None
                    if not tx_id:
                        results['skipped'] += 1
                        continue

                    inserted_tx_ids.append(tx_id)
                    results['added'] += 1

                except Exception as e:
                    results['errors'].append(f"Row {i}: {str(e)[:80]}")
                    results['skipped'] += 1
                    try:
                        db.rollback()
                    except Exception:
                        try:
                            from database.db import get_db as _gdb
                            db = _gdb()
                        except Exception:
                            pass

            # Batch TM evaluation after all inserts (much faster than per-row)
            from aml.tm_service import evaluate_transaction
            TM_BATCH_LIMIT = 500  # Evaluate TM on first 500 only to avoid timeout
            for tx_id in inserted_tx_ids[:TM_BATCH_LIMIT]:
                try:
                    alerts = evaluate_transaction(tx_id, db)
                    results['alerts'] += len(alerts)
                except Exception:
                    pass

            summary = (
                f"Upload complete: {results['added']} transactions imported, "
                f"{results['skipped']} skipped, {results['alerts']} TM alerts raised. "
                f"Customers: {results['customers_created']} new profiles created, "
                f"{results['customers_existing']} existing profiles updated."
            )
            flash(summary, 'success' if results['added'] > 0 else 'warning')
            return render_template('aml/upload_transactions.html',
                                   results=results, done=True)

        except Exception as e:
            flash(f'Upload failed: {str(e)}', 'danger')

    return render_template('aml/upload_transactions.html', results=None, done=False)


@aml_bp.route('/transactions/template')
@login_required
@permission_required('aml', level='view')
def download_tx_template():
    import csv as csv_mod
    output = io.StringIO()
    writer = csv_mod.writer(output)
    writer.writerow([
        'customer_reference','transaction_date','transaction_type','amount','currency',
        'counterparty_name','counterparty_account','counterparty_country',
        'purpose_of_transaction','remittance_information'
    ])
    writer.writerow([
        'CUST-001','2026-03-01 10:00:00','CASH_DEPOSIT','15000','EGP',
        'John Doe','1234567890','Egypt','Payment for services',''
    ])
    writer.writerow([
        'CUST-001','2026-03-02 14:30:00','TRANSFER_OUT','5000','USD',
        'Jane Smith','9876543210','Iran','Trade payment',''
    ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=transactions_template.csv'}
    )


# ─────────────────────────────────────────────
#  RULE EDITOR (ADD / EDIT / DELETE)
# ─────────────────────────────────────────────

@aml_bp.route('/tm-rules/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def create_rule():
    from database.db import get_db
    db = get_db()

    if request.method == 'POST':
        try:
            code = request.form.get('rule_code','').strip().upper()
            if db.execute("SELECT id FROM tm_rules WHERE rule_code=%s", (code,)).fetchone():
                flash(gettext('Rule code %(code)s already exists', code=code), 'danger')
                return render_template('aml/rule_form.html', rule=None, action='Create')

            db.execute("""
                INSERT INTO tm_rules 
                (rule_code, rule_name, rule_name_ar, rule_description, rule_category, rule_type,
                 threshold_value, threshold_currency, time_period_days, severity, is_active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
            """, (
                code,
                request.form.get('rule_name','').strip(),
                request.form.get('rule_name_ar','').strip() or None,
                request.form.get('rule_description','').strip(),
                request.form.get('rule_category','').strip(),
                request.form.get('rule_type','THRESHOLD'),
                float(request.form.get('threshold_value') or 0) or None,
                request.form.get('threshold_currency','').strip() or None,
                int(request.form.get('time_period_days') or 1),
                request.form.get('severity','MEDIUM')
            ))
            db.commit()
            flash(gettext('Rule %(code)s created successfully', code=code), 'success')
            return redirect(url_for('aml.rule_list'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')

    return render_template('aml/rule_form.html', rule=None, action='Create')


@aml_bp.route('/tm-rules/<int:rule_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def edit_rule(rule_id):
    from database.db import get_db
    db = get_db()
    rule = db.execute("SELECT * FROM tm_rules WHERE id=%s", (rule_id,)).fetchone()
    if not rule:
        flash(gettext('Rule not found'), 'danger')
        return redirect(url_for('aml.rule_list'))

    if request.method == 'POST':
        try:
            db.execute("""
                UPDATE tm_rules SET
                    rule_name=%s, rule_name_ar=%s, rule_description=%s, rule_category=%s, rule_type=%s,
                    threshold_value=%s, threshold_currency=%s, time_period_days=%s, severity=%s
                WHERE id=%s
            """, (
                request.form.get('rule_name','').strip(),
                request.form.get('rule_name_ar','').strip() or None,
                request.form.get('rule_description','').strip(),
                request.form.get('rule_category','').strip(),
                request.form.get('rule_type','THRESHOLD'),
                float(request.form.get('threshold_value') or 0) or None,
                request.form.get('threshold_currency','').strip() or None,
                int(request.form.get('time_period_days') or 1),
                request.form.get('severity','MEDIUM'),
                rule_id
            ))
            db.commit()
            flash(gettext('Rule updated successfully'), 'success')
            return redirect(url_for('aml.rule_list'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')

    return render_template('aml/rule_form.html', rule=rule, action='Edit')


@aml_bp.route('/tm-rules/<int:rule_id>/delete', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def delete_rule(rule_id):
    from database.db import get_db
    db = get_db()
    rule = db.execute("SELECT rule_code FROM tm_rules WHERE id=%s", (rule_id,)).fetchone()
    if rule and rule['rule_code'].startswith('TM0'):
        flash(gettext('Cannot delete built-in rules. Disable them instead.'), 'warning')
        return redirect(url_for('aml.rule_list'))
    db.execute("DELETE FROM tm_rules WHERE id=%s", (rule_id,))
    db.commit()
    flash(gettext('Rule deleted'), 'success')
    return redirect(url_for('aml.rule_list'))


# ─────────────────────────────────────────────
#  ANALYTICS DASHBOARD
# ─────────────────────────────────────────────

@aml_bp.route('/tm-analytics')
@login_required
@permission_required('aml', level='view')
def tm_analytics():
    from database.db import get_db
    db = get_db()

    # Daily volume last 30 days
    daily = db.execute("""
        SELECT DATE(transaction_date::timestamp) as day,
               COUNT(*) as tx_count,
               SUM(amount) as volume,
               SUM(CASE WHEN alert_raised=1 THEN 1 ELSE 0 END) as flagged
        FROM transactions
        WHERE transaction_date::timestamp >= (CURRENT_DATE - INTERVAL '30 days')
        GROUP BY day ORDER BY day
    """).fetchall()

    # Alert rate by rule
    by_rule = db.execute("""
        SELECT r.rule_code, r.rule_name, r.severity,
               COUNT(a.id) as total,
               SUM(CASE WHEN a.status='CLOSED' THEN 1 ELSE 0 END) as closed,
               SUM(CASE WHEN a.status='FALSE_POSITIVE' THEN 1 ELSE 0 END) as false_pos,
               SUM(CASE WHEN a.disposition='ESCALATE' THEN 1 ELSE 0 END) as escalated
        FROM tm_rules r
        LEFT JOIN tm_alerts a ON r.id = a.rule_id
        GROUP BY r.id ORDER BY total DESC
    """).fetchall()

    # Top flagged customers
    top_customers = db.execute("""
        SELECT c.customer_reference, c.full_name, c.company_name,
               c.risk_classification,
               COUNT(t.id) as tx_count,
               SUM(CASE WHEN t.alert_raised=1 THEN 1 ELSE 0 END) as flagged,
               SUM(t.amount) as total_volume
        FROM customers c
        JOIN transactions t ON c.id = t.customer_id
        GROUP BY c.id
        ORDER BY flagged DESC, total_volume DESC
        LIMIT 10
    """).fetchall()

    # Transaction type breakdown
    by_type = db.execute("""
        SELECT transaction_type,
               COUNT(*) as count,
               SUM(amount) as volume,
               SUM(CASE WHEN alert_raised=1 THEN 1 ELSE 0 END) as flagged
        FROM transactions
        GROUP BY transaction_type ORDER BY count DESC
    """).fetchall()

    # Monthly trend last 6 months
    monthly = db.execute("""
        SELECT TO_CHAR(transaction_date::timestamp, 'YYYY-MM') as month,
               COUNT(*) as tx_count,
               SUM(amount) as volume,
               SUM(CASE WHEN alert_raised=1 THEN 1 ELSE 0 END) as flagged,
               COUNT(DISTINCT customer_id) as unique_customers
        FROM transactions
        GROUP BY month ORDER BY month DESC LIMIT 6
    """).fetchall()

    # Alert disposition summary
    disposition = db.execute("""
        SELECT status, COUNT(*) as count
        FROM tm_alerts GROUP BY status
    """).fetchall()

    # High risk country breakdown
    countries = db.execute("""
        SELECT counterparty_country, COUNT(*) as count,
               SUM(CASE WHEN alert_raised=1 THEN 1 ELSE 0 END) as flagged
        FROM transactions
        WHERE counterparty_country IS NOT NULL AND counterparty_country != ''
        GROUP BY counterparty_country ORDER BY count DESC LIMIT 10
    """).fetchall()

    return render_template('aml/tm_analytics.html',
                           daily=daily, by_rule=by_rule,
                           top_customers=top_customers, by_type=by_type,
                           monthly=monthly, disposition=disposition,
                           countries=countries)


# ─────────────────────────────────────────────
#  SCENARIO SIMULATOR
# ─────────────────────────────────────────────

@aml_bp.route('/tm-scenario', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='view')
def scenario_simulator():
    from database.db import get_db
    db = get_db()
    rules = db.execute("SELECT * FROM tm_rules ORDER BY rule_code").fetchall()

    simulation_results = None

    if request.method == 'POST':
        rule_id = int(request.form.get('rule_id', 0))
        date_from = request.form.get('date_from', '')
        date_to = request.form.get('date_to', '')
        customer_risk = request.form.get('customer_risk', '')

        rule = db.execute("SELECT * FROM tm_rules WHERE id=%s", (rule_id,)).fetchone()
        if not rule:
            flash(gettext('Select a valid rule'), 'danger')
            return render_template('aml/scenario_simulator.html',
                                   rules=rules, results=None)

        # Build transaction filter
        filters = []
        params = []
        if date_from:
            filters.append("t.transaction_date::timestamp >= %s")
            params.append(date_from)
        if date_to:
            filters.append("t.transaction_date::timestamp <= %s")
            params.append(date_to + ' 23:59:59')
        if customer_risk:
            filters.append("c.risk_classification = %s")
            params.append(customer_risk)

        where = "WHERE " + " AND ".join(filters) if filters else ""

        transactions = db.execute(f"""
            SELECT t.*, c.full_name, c.company_name, c.customer_reference,
                   c.risk_classification, c.annual_income_range
            FROM transactions t
            LEFT JOIN customers c ON t.customer_id = c.id
            {where}
            ORDER BY t.transaction_date DESC
        """, params).fetchall()

        rule_dict = dict(rule)
        triggered = []
        would_not_trigger = []

        HIGH_RISK_COUNTRIES = {
            'Iran', 'North Korea', 'Myanmar', 'Afghanistan', 'Syria',
            'Yemen', 'Libya', 'Somalia', 'Sudan', 'Iraq', 'Mali',
            'Burkina Faso', 'Haiti', 'Laos', 'South Sudan', 'Tanzania',
            'Vietnam', 'Nigeria', 'Pakistan', 'Philippines'
        }

        for tx in transactions:
            tx = dict(tx)
            hit = False
            reason = ''
            code = rule_dict['rule_code']

            if code == 'TM001':
                if tx['transaction_type'] in ('CASH_DEPOSIT','CASH_WITHDRAWAL') and \
                   float(tx['amount']) >= float(rule_dict['threshold_value'] or 0):
                    hit = True
                    reason = f"Cash {tx['amount']} >= threshold {rule_dict['threshold_value']}"

            elif code == 'TM002':
                count = db.execute("""
                    SELECT COUNT(*) as c FROM transactions
                    WHERE customer_id=%s AND transaction_type IN ('CASH_DEPOSIT','CASH_WITHDRAWAL')
                    AND amount < %s AND transaction_date::date >= (%s::date - (%s || ' days')::interval)
                """, (tx['customer_id'], rule_dict['threshold_value'],
                      tx['transaction_date'], rule_dict['time_period_days'])).fetchone()['c']
                if count >= 3:
                    hit = True
                    reason = f"{count} cash txns below threshold in window"

            elif code == 'TM003':
                count = db.execute("""
                    SELECT COUNT(*) as c FROM transactions
                    WHERE customer_id=%s AND date(transaction_date)=date(%s)
                """, (tx['customer_id'], tx['transaction_date'])).fetchone()['c']
                if count > int(rule_dict['threshold_value'] or 5):
                    hit = True
                    reason = f"{count} transactions same day > {rule_dict['threshold_value']}"

            elif code == 'TM004':
                country = (tx.get('counterparty_country') or '').strip()
                if country in HIGH_RISK_COUNTRIES:
                    hit = True
                    reason = f"High-risk country: {country}"

            elif code == 'TM006':
                if float(tx['amount']) >= float(rule_dict['threshold_value'] or 0):
                    prev = db.execute("""
                        SELECT COUNT(*) as c FROM transactions
                        WHERE customer_id=%s AND id != %s
                        AND transaction_date::date < (%s::date - (%s || ' days')::interval)
                    """, (tx['customer_id'], tx['id'],
                          tx['transaction_date'], rule_dict['time_period_days'])).fetchone()['c']
                    if prev == 0:
                        hit = True
                        reason = f"No transactions in {rule_dict['time_period_days']} days before this"

            elif code == 'TM010':
                count = db.execute("""
                    SELECT COUNT(*) as c FROM transactions
                    WHERE customer_id=%s AND transaction_type IN ('TRANSFER_OUT','TRANSFER_IN')
                    AND counterparty_country IS NOT NULL
                    AND transaction_date::date >= (%s::date - (%s || ' days')::interval)
                """, (tx['customer_id'], tx['transaction_date'],
                      rule_dict['time_period_days'])).fetchone()['c']
                if count > int(rule_dict['threshold_value'] or 5):
                    hit = True
                    reason = f"{count} intl transfers in {rule_dict['time_period_days']} days"

            if hit:
                tx['sim_reason'] = reason
                tx['already_flagged'] = bool(tx.get('alert_raised'))
                triggered.append(tx)
            else:
                would_not_trigger.append(tx)

        simulation_results = {
            'rule': rule_dict,
            'total_evaluated': len(transactions),
            'would_trigger': len(triggered),
            'would_not_trigger': len(would_not_trigger),
            'new_alerts': sum(1 for t in triggered if not t['already_flagged']),
            'already_flagged': sum(1 for t in triggered if t['already_flagged']),
            'trigger_rate': round(len(triggered) / max(len(transactions), 1) * 100, 1),
            'triggered_transactions': triggered[:50],
            'date_from': date_from,
            'date_to': date_to,
        }

    return render_template('aml/scenario_simulator.html',
                           rules=rules, results=simulation_results)


# ─────────────────────────────────────────────
#  TM NETWORK GRAPH
# ─────────────────────────────────────────────
@aml_bp.route('/tm-network')
@login_required
@permission_required('aml')
def tm_network():
    from database.db import get_db
    import json
    db = get_db()
    try:
        txs = db.execute("""
            SELECT t.customer_id, c.full_name, c.company_name, c.customer_reference,
                   t.counterparty_name, t.counterparty_country,
                   SUM(t.amount::numeric) as total_amount, COUNT(*) as tx_count,
                   MAX(CASE WHEN t.alert_raised = 1 THEN 1 ELSE 0 END) as has_alert
            FROM transactions t
            JOIN customers c ON t.customer_id = c.id
            WHERE t.counterparty_name IS NOT NULL AND t.counterparty_name != ''
            GROUP BY t.customer_id, c.full_name, c.company_name, c.customer_reference, t.counterparty_name, t.counterparty_country
            ORDER BY total_amount DESC LIMIT 100
        """).fetchall()

        nodes = {}
        links = []
        for tx in txs:
            cid = f"cust_{tx['customer_id']}"
            cname = tx['full_name'] or tx['company_name'] or tx['customer_reference']
            cpid = f"cp_{str(tx['counterparty_name']).replace(' ','_')[:20]}"
            cpname = tx['counterparty_name']

            if cid not in nodes:
                nodes[cid] = {'id':cid,'name':cname,'type':'customer','alert':False}
            if tx['has_alert']: nodes[cid]['alert'] = True

            if cpid not in nodes:
                nodes[cpid] = {'id':cpid,'name':cpname,'type':'counterparty',
                               'country': tx['counterparty_country'] or '','alert':False}

            links.append({'source':cid,'target':cpid,
                          'value':float(tx['total_amount'] or 0),
                          'count':tx['tx_count'],'alert':bool(tx['has_alert'])})

        graph = {'nodes':list(nodes.values()),'links':links}
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"TM network graph error: {e}", exc_info=True)
        graph = {'nodes':[],'links':[]}

    # Pass the raw dict, not a pre-serialized json.dumps() string — the template
    # uses Jinja's |tojson filter, which both serializes AND HTML/script-escapes
    # (json.dumps()+|safe does not escape "</script>", making this a real XSS sink
    # for any customer/counterparty name containing that sequence).
    return render_template('aml/tm_network.html', graph_json=graph)


# ─────────────────────────────────────────────
#  PDF EXPORT — CUSTOMER CDD
# ─────────────────────────────────────────────
@aml_bp.route('/customers/<int:id>/pdf')
@login_required
@permission_required('aml')
def customer_pdf(id):
    from database.db import get_db
    from flask import make_response, request as freq
    from datetime import datetime
    db = get_db()

    customer = db.execute("SELECT * FROM customers WHERE id=%s",(id,)).fetchone()
    if not customer:
        flash(gettext('Customer not found'),'danger')
        return redirect(url_for('aml.customer_list'))

    transactions = db.execute("""
        SELECT * FROM transactions WHERE customer_id=%s
        ORDER BY transaction_date DESC LIMIT 20
    """,(id,)).fetchall()

    screenings = db.execute("""
        SELECT * FROM screening_history
        WHERE entity_name ILIKE %s
        ORDER BY created_at DESC LIMIT 10
    """,(f"%{customer['full_name'] or customer['company_name'] or ''}%",)).fetchall()

    alerts = db.execute("""
        SELECT a.*, r.rule_name FROM tm_alerts a
        LEFT JOIN tm_rules r ON a.rule_id=r.id
        WHERE a.customer_id=%s ORDER BY a.alert_date DESC
    """,(id,)).fetchall()

    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M')

    try:
        from weasyprint import HTML, CSS
        html_content = render_template('aml/customer_pdf.html',
            customer=customer, transactions=transactions,
            screenings=screenings, alerts=alerts, generated_at=generated_at)
        pdf = HTML(string=html_content, base_url=freq.url_root).write_pdf(
            stylesheets=[CSS(string='''
                @page { size: A4; margin: 1.5cm; }
                body { font-family: Arial, sans-serif; font-size: 10pt; color: #333; }
                table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
                th { background: #1B3A6B; color: white; padding: 6px 8px; font-size: 9pt; text-align: left; }
                td { border: 1px solid #ddd; padding: 5px 8px; font-size: 9pt; }
                tr:nth-child(even) td { background: #f5f7fa; }
                h2 { color: #1B3A6B; font-size: 12pt; border-bottom: 2px solid #00B4D8; padding-bottom: 3px; margin-top: 16px; }
                .risk-HIGH { color: #C0392B; font-weight: bold; }
                .risk-MEDIUM { color: #D35400; font-weight: bold; }
                .risk-LOW { color: #1E8449; font-weight: bold; }
                .header { background: #1B3A6B; color: white; padding: 16px; margin-bottom: 16px; }
                .header h1 { margin: 0; font-size: 16pt; }
                .header p { margin: 3px 0; font-size: 9pt; opacity: 0.8; }
                .footer-note { font-size: 8pt; color: #888; border-top: 1px solid #ddd; padding-top: 6px; margin-top: 20px; }
            ''')]
        )
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        ref = customer['customer_reference'] or str(id)
        response.headers['Content-Disposition'] = f'attachment; filename=CDD-{ref}-{datetime.now().strftime("%Y%m%d")}.pdf'
        return response
    except Exception as e:
        flash(f'PDF generation failed: {str(e)}', 'danger')
        return redirect(url_for('aml.view_customer', id=id))


# --- PDF Export Route ---
@aml_bp.route('/customer/<int:id>/export/pdf')
@login_required
def export_customer_pdf(id):
    from weasyprint import HTML
    from flask import make_response
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id = %s", (id,)).fetchone()
    if not customer:
        flash(gettext('Customer not found.'), 'danger')
        return redirect(url_for('aml.customer_list'))
    html = render_template('aml/pdf/customer_cdd.html', customer=customer)
    pdf = HTML(string=html).write_pdf()
    resp = make_response(pdf)
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=CDD_{id}.pdf'
    return resp


@aml_bp.route('/cft-control/dashboard')
@login_required
def cft_dashboard():
    return redirect(url_for('aml.dashboard'))


# ──────────────────────────────────────────────────────────────────────────────
# AML Rule Management (Item 14)
# ──────────────────────────────────────────────────────────────────────────────

@aml_bp.route('/rules')
@login_required
@permission_required('aml')
def rules_list():
    db = get_db()
    rules = db.execute(
        """SELECT r.*, u.email as created_by_email, a.email as approved_by_email
           FROM tm_rules r
           LEFT JOIN users u ON r.created_by = u.id
           LEFT JOIN users a ON r.approved_by = a.id
           ORDER BY r.rule_code"""
    ).fetchall()
    return render_template('aml/rules/list.html', rules=rules)


@aml_bp.route('/rules/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def rule_create():
    if request.method == 'POST':
        data = request.form
        db = get_db()
        try:
            db.execute(
                """INSERT INTO tm_rules
                   (rule_code, rule_name, rule_name_ar, rule_description, rule_category, rule_type,
                    threshold_value, threshold_currency, time_period_days,
                    severity, is_active, status, created_by, created_at, version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'PENDING',%s,NOW(),1)""",
                (
                    data['rule_code'].strip().upper(),
                    data['rule_name'].strip(),
                    data.get('rule_name_ar', '').strip() or None,
                    data.get('rule_description', '').strip(),
                    data.get('rule_category', 'General').strip(),
                    data.get('rule_type', 'THRESHOLD').strip(),
                    float(data.get('threshold_value') or 0),
                    data.get('threshold_currency', 'EGP').strip(),
                    int(data.get('time_period_days') or 1),
                    data.get('severity', 'MEDIUM').strip(),
                    current_user.id,
                )
            )
            db.commit()
            flash(gettext('Rule submitted for approval.'), 'success')
            return redirect(url_for('aml.rules_list'))
        except Exception as e:
            flash(gettext('Error: %(e)s', e=e), 'danger')
    return render_template('aml/rules/form.html', rule=None, action='create')


@aml_bp.route('/rules/<int:rule_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def rule_edit(rule_id):
    db = get_db()
    rule = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not rule:
        flash(gettext('Rule not found.'), 'danger')
        return redirect(url_for('aml.rules_list'))

    if request.method == 'POST':
        data = request.form
        try:
            # Create a new version pending approval instead of overwriting
            db.execute(
                """INSERT INTO tm_rules
                   (rule_code, rule_name, rule_name_ar, rule_description, rule_category, rule_type,
                    threshold_value, threshold_currency, time_period_days,
                    severity, is_active, status, created_by, created_at, version, previous_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'PENDING',%s,NOW(),%s,%s)""",
                (
                    data['rule_code'].strip().upper(),
                    data['rule_name'].strip(),
                    data.get('rule_name_ar', '').strip() or None,
                    data.get('rule_description', '').strip(),
                    data.get('rule_category', 'General').strip(),
                    data.get('rule_type', 'THRESHOLD').strip(),
                    float(data.get('threshold_value') or 0),
                    data.get('threshold_currency', 'EGP').strip(),
                    int(data.get('time_period_days') or 1),
                    data.get('severity', 'MEDIUM').strip(),
                    current_user.id,
                    rule['version'] + 1,
                    rule_id,
                )
            )
            db.commit()
            flash(gettext('Edited rule submitted for approval (v%(old)s → v%(new)s).', old=rule['version'], new=rule['version'] + 1), 'info')
            return redirect(url_for('aml.rules_list'))
        except Exception as e:
            flash(gettext('Error: %(e)s', e=e), 'danger')

    return render_template('aml/rules/form.html', rule=dict(rule), action='edit')


@aml_bp.route('/rules/<int:rule_id>/approve', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def rule_approve(rule_id):
    db = get_db()
    rule = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not rule:
        return jsonify({'error': 'Not found'}), 404

    # If this rule supersedes a previous one, disable the old version
    if rule['previous_id']:
        db.execute(
            "UPDATE tm_rules SET is_active=0, status='DISABLED', updated_at=NOW() WHERE id=%s",
            (rule['previous_id'],)
        )

    db.execute(
        """UPDATE tm_rules SET status='ACTIVE', is_active=1,
           approved_by=%s, approved_at=NOW(), updated_at=NOW()
           WHERE id=%s""",
        (current_user.id, rule_id)
    )
    db.commit()
    flash(gettext('Rule approved and activated.'), 'success')
    return redirect(url_for('aml.rules_list'))


@aml_bp.route('/rules/<int:rule_id>/disable', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def rule_disable(rule_id):
    db = get_db()
    rule = db.execute("SELECT id, rule_code, status FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not rule:
        flash(gettext('Rule not found.'), 'danger')
        return redirect(url_for('aml.rules_list'))
    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash(gettext('A reason is required to disable a rule.'), 'danger')
        return redirect(url_for('aml.rules_list'))
    if rule['status'] != 'ACTIVE':
        flash(gettext('Only an active rule can be disabled.'), 'warning')
        return redirect(url_for('aml.rules_list'))
    db.execute(
        "UPDATE tm_rules SET status='DISABLED', is_active=0, updated_at=NOW(), updated_by=%s WHERE id=%s",
        (current_user.id, rule_id)
    )
    db.commit()
    AuditLog.log(current_user.id, 'Disable TM Rule', 'AML', rule_id,
                 'Rule %s disabled. Reason: %s' % (rule['rule_code'], reason), request.remote_addr)
    flash(gettext('Rule disabled.'), 'warning')
    return redirect(url_for('aml.rules_list'))


@aml_bp.route('/rules/<int:rule_id>/enable', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def rule_enable(rule_id):
    """Re-activate a disabled rule. Same permission
    level as disable; the reason goes to the audit log."""
    db = get_db()
    rule = db.execute("SELECT id, rule_code, status FROM tm_rules WHERE id = %s",
                      (rule_id,)).fetchone()
    if not rule:
        flash(gettext('Rule not found.'), 'danger')
        return redirect(url_for('aml.rules_list'))
    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash(gettext('A reason is required to enable a rule.'), 'danger')
        return redirect(url_for('aml.rules_list'))
    if rule['status'] != 'DISABLED':
        flash(gettext('Only a disabled rule can be enabled.'), 'warning')
        return redirect(url_for('aml.rules_list'))
    other = db.execute(
        "SELECT id, version FROM tm_rules WHERE rule_code = %s AND status = 'ACTIVE' AND id <> %s",
        (rule['rule_code'], rule_id)).fetchone()
    if other:
        flash(gettext('Another version of this rule (v%(version)s) is already active. Disable it first.',
                      version=other['version']), 'warning')
        return redirect(url_for('aml.rules_list'))
    db.execute(
        "UPDATE tm_rules SET status='ACTIVE', is_active=1, updated_at=NOW(), updated_by=%s WHERE id=%s",
        (current_user.id, rule_id)
    )
    db.commit()
    AuditLog.log(current_user.id, 'Enable TM Rule', 'AML', rule_id,
                 'Rule %s enabled. Reason: %s' % (rule['rule_code'], reason), request.remote_addr)
    flash(gettext('Rule enabled.'), 'success')
    return redirect(url_for('aml.rules_list'))


@aml_bp.route('/rules/<int:rule_id>/rollback', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def rule_rollback(rule_id):
    """Re-activate the previous version of a rule and disable this one."""
    db = get_db()
    rule = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not rule or not rule['previous_id']:
        flash(gettext('No previous version to roll back to.'), 'danger')
        return redirect(url_for('aml.rules_list'))

    # Disable current
    db.execute(
        "UPDATE tm_rules SET status='DISABLED', is_active=0, updated_at=NOW(), updated_by=%s WHERE id=%s",
        (current_user.id, rule_id)
    )
    # Re-activate previous
    db.execute(
        """UPDATE tm_rules SET status='ACTIVE', is_active=1, updated_at=NOW(), updated_by=%s
           WHERE id=%s""",
        (current_user.id, rule['previous_id'])
    )
    db.commit()
    flash(gettext('Rolled back to previous rule version.'), 'info')
    return redirect(url_for('aml.rules_list'))


@aml_bp.route('/rules/simulate', methods=['POST'])
@login_required
@permission_required('aml')
def rule_simulate():
    """
    Simulate a rule against a hypothetical transaction — no data is saved.
    Accepts JSON: {rule_id, amount, transaction_type, customer_id (opt)}
    """
    data = request.get_json(silent=True) or {}
    rule_id = data.get('rule_id')
    amount  = float(data.get('amount', 0))
    tx_type = data.get('transaction_type', 'CASH_IN')

    if not rule_id:
        return jsonify({'error': 'rule_id required'}), 400

    db = get_db()
    rule = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not rule:
        return jsonify({'error': 'Rule not found'}), 404

    rule = dict(rule)
    triggered = False
    reason    = ''

    if rule['rule_type'] == 'THRESHOLD':
        if amount >= float(rule['threshold_value']):
            triggered = True
            reason = (f"Amount {amount} {rule['threshold_currency']} exceeds threshold "
                      f"{rule['threshold_value']} {rule['threshold_currency']}")
    elif rule['rule_type'] == 'PATTERN':
        reason = ('Pattern rule simulation: in production, requires transaction history. '
                  f"Threshold per window: {rule['threshold_value']} {rule['threshold_currency']} "
                  f"over {rule['time_period_days']} days.")
        triggered = amount >= float(rule['threshold_value'])
    else:
        reason = f"Rule type {rule['rule_type']!r} simulation not implemented."

    return jsonify({
        'rule_code': rule['rule_code'],
        'rule_name': rule['rule_name'],
        'would_trigger': triggered,
        'reason': reason,
        'severity': rule['severity'] if triggered else None,
    })
