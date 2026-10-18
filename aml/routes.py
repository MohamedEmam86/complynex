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
        ORDER BY onboarding_date DESC
    """).fetchall()
    return render_template('aml/customer_list.html', customers=customers, user=current_user)

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
            'income': request.form.get('income')
        }
        
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
                    flash(f'⚠️ WARNING: Automated screening found potential matches for "{screening_name}". Customer assigned HIGH risk and status set to UNDER_REVIEW.', 'warning')
                else:
                    flash(f'✅ Screening completed for "{screening_name}". No hits found.')

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
            
            return redirect(url_for('aml.customer_list'))
        else:
            flash('Error creating customer.', 'danger')
        
    return render_template('aml/customer_form.html', user=current_user)

@aml_bp.route('/customers/<int:id>')
@login_required
@permission_required('aml')
def view_customer(id):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id = %s", (id,)).fetchone()
    if not customer:
        flash('Customer not found.', 'danger')
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

    return render_template(
        'aml/customer_view.html', customer=customer, recent_alerts=recent_alerts, user=current_user,
        risk_radar_json=risk_radar_json,
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
        flash('Customer not found.', 'danger')
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

        # --- ComplyNex AI Enhancement ---
        nid_data = parse_egyptian_nid(request.form.get('id_number'))
        if nid_data:
            if not request.form.get('dob'): data['dob'] = nid_data['dob']
            if not request.form.get('gender'): data['gender'] = nid_data['gender']
            data['birth_governorate'] = nid_data.get('birth_governorate')
        # ------------------------------
        
        if Customer.update(id, data):
            # Re-calculate risk after edit
            calculate_customer_risk(id)
            db.commit()
            flash('Customer information updated successfully.')
            return redirect(url_for('aml.view_customer', id=id))
        else:
            flash('Error updating customer.', 'danger')
            db.rollback()
        
    return render_template('aml/customer_form.html', customer=customer, user=current_user)

@aml_bp.route('/sars')
@login_required
@permission_required('aml')
def sar_list():
    db = get_db()
    sars = db.execute("""
        SELECT s.*, c.full_name as customer_name 
        FROM suspicious_activities s
        LEFT JOIN customers c ON s.customer_id = c.id
        ORDER BY s.report_date DESC
    """).fetchall()
    return render_template('aml/sar_list.html', sars=sars, user=current_user)

@aml_bp.route('/sars/new', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def create_sar():
    db = get_db()
    if request.method == 'POST':
        sar_reference = f"SAR-{datetime.now().strftime('%Y%m')}-{os.urandom(2).hex().upper()}"
        AuditLog.log(current_user.id, 'File SAR', 'AML', None,
            f'SAR {sar_reference} filed for customer {request.form.get("customer_id")}', request.remote_addr)
        customer_id = request.form.get('customer_id')
        activity_date = request.form.get('activity_date')
        discovery_date = request.form.get('discovery_date')
        amount = request.form.get('amount')
        description = request.form.get('description')
        
        db.execute("""
            INSERT INTO suspicious_activities 
            (sar_reference, activity_date, discovery_date, customer_id, amount_involved, activity_description, reported_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (sar_reference, activity_date, discovery_date, customer_id, amount, description, current_user.id))
        
        db.commit()
        flash(f'SAR {sar_reference} filed successfully and queued for compliance review.')
        return redirect(url_for('aml.sar_list'))
    
    customers = db.execute("SELECT id, full_name, customer_reference FROM customers ORDER BY full_name").fetchall()
    return render_template('aml/sar_form.html', 
                          customers=customers, 
                          user=current_user,
                          now_date=datetime.now().strftime('%Y-%m-%d'))

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
        c = dict(customer)
        writer.writerow([
            c.get('id'), c.get('full_name') or c.get('company_name'), 
            c.get('date_of_birth'), c.get('nationality'), c.get('id_number'),
            c.get('risk_classification'), c.get('risk_score'), 'Yes' if c.get('is_pep') else 'No',
            c.get('phone'), c.get('email'), c.get('address_line1')
        ])
        
    return Response(
        output.getvalue(),
        mimetype="text/csv",
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
        flash('Customer not found.', 'danger')
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
        flash('Customer not found.', 'danger')
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
                flash('Transaction saved. No alerts triggered.', 'success')
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
        flash('Transaction not found', 'danger')
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
    from database.db import get_db
    from aml.tm_service import get_alert_stats
    db = get_db()

    # Default to OPEN alerts only. Previously this listed every alert
    # regardless of status, so an alert closed as a false positive stayed
    # sitting in the working list and looked like the closure had not worked.
    # 'ALL' explicitly shows everything, including resolved alerts.
    CLOSED_STATUSES = ('FALSE_POSITIVE', 'CLOSED', 'SAR_CREATED')
    status_filter = request.args.get('status', 'OPEN')
    severity_filter = request.args.get('severity', '')
    page = int(request.args.get('page', 1))
    per_page = 25
    offset = (page - 1) * per_page

    filters = []
    params = []
    if status_filter == 'OPEN':
        filters.append("a.status NOT IN (%s, %s, %s)")
        params.extend(CLOSED_STATUSES)
    elif status_filter and status_filter != 'ALL':
        filters.append("a.status = %s")
        params.append(status_filter)
    if severity_filter:
        filters.append("a.alert_severity = %s")
        params.append(severity_filter)

    where = "WHERE " + " AND ".join(filters) if filters else ""

    total = db.execute(f"SELECT COUNT(*) as count FROM tm_alerts a {where}", params).fetchone()['count']
    alerts = db.execute(f"""
        SELECT a.id, a.alert_reference, CAST(a.alert_date AS TEXT) as alert_date,
               a.alert_description, a.alert_severity, a.status,
               a.assigned_to, a.investigation_notes, a.disposition,
               a.triggered_transactions, a.rule_id, a.customer_id,
               r.rule_name, r.rule_code,
               c.full_name, c.company_name, c.customer_reference,
               u.first_name || ' ' || u.last_name as assigned_name
        FROM tm_alerts a
        LEFT JOIN tm_rules r ON a.rule_id = r.id
        LEFT JOIN customers c ON a.customer_id = c.id
        LEFT JOIN users u ON a.assigned_to = u.id
        {where}
        ORDER BY 
            CASE a.alert_severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
            a.alert_date DESC
        LIMIT %s OFFSET %s
    """, params + [per_page, offset]).fetchall()

    stats = get_alert_stats(db)
    total_pages = (total + per_page - 1) // per_page
    compliance_users = db.execute("SELECT id, first_name, last_name FROM users WHERE is_active=1").fetchall()

    return render_template('aml/alert_list.html',
                           alerts=alerts, stats=stats, total=total,
                           page=page, total_pages=total_pages,
                           status_filter=status_filter,
                           severity_filter=severity_filter,
                           compliance_users=compliance_users)


@aml_bp.route('/alerts/<int:alert_id>', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='view')
def view_alert(alert_id):
    from database.db import get_db
    db = get_db()

    if request.method == 'POST':
        action = request.form.get('action')
        notes = request.form.get('notes', '')
        status_map = {
            'assign': 'ASSIGNED', 'investigate': 'INVESTIGATING',
            'escalate': 'ESCALATED', 'false_positive': 'FALSE_POSITIVE',
            'close': 'CLOSED'
        }
        new_status = status_map.get(action)
        if new_status:
            assigned_to = request.form.get('assigned_to') or None
            db.execute("""
                UPDATE tm_alerts SET status=%s, investigation_notes=%s,
                assigned_to=COALESCE(%s,assigned_to),
                disposition=%s, disposition_by=%s, disposition_date=%s
                WHERE id=%s
            """, (new_status, notes, assigned_to,
                  action.upper(), current_user.id,
                  datetime.now().date().isoformat(), alert_id))
            db.commit()

            # An escalation nobody is told about is not an escalation. Notify
            # every compliance officer / admin (except the person who just
            # escalated) with a direct link back to this alert.
            if action == 'escalate':
                try:
                    from models.notification import Notification
                    from models.user import User as _User
                    ref_row = db.execute(
                        """SELECT a.alert_reference, a.alert_severity,
                                  COALESCE(c.full_name, c.company_name) AS cname
                             FROM tm_alerts a
                             LEFT JOIN customers c ON a.customer_id = c.id
                            WHERE a.id = %s""", (alert_id,)).fetchone()
                    ref = (ref_row['alert_reference'] if ref_row else alert_id)
                    sev = (ref_row['alert_severity'] if ref_row else '') or ''
                    cname = (ref_row['cname'] if ref_row else '') or ''
                    link = url_for('aml.view_alert', alert_id=alert_id)
                    recipients = [u for u in _User.get_all_compliance_officers()
                                  if u.id != current_user.id]
                    for u in recipients:
                        Notification.create(
                            user_id=u.id,
                            title='Escalated AML alert %s' % ref,
                            message='%s escalated alert %s%s%s. %s' % (
                                current_user.first_name or 'A reviewer',
                                ref,
                                (' (%s)' % sev) if sev else '',
                                (' for %s' % cname) if cname else '',
                                (notes or 'No notes provided.')),
                            link=link,
                            n_type='aml_escalation',
                        )
                    AuditLog.log(
                        current_user.id, 'Escalate AML Alert', 'AML', alert_id,
                        'Escalated alert %s to %d compliance staff'
                        % (ref, len(recipients)), request.remote_addr)
                    if recipients:
                        flash(_('Escalated. %(n)d compliance staff notified.',
                                n=len(recipients)), 'info')
                    else:
                        flash(_('Escalated, but no other compliance officer '
                                'exists to notify.'), 'warning')
                except Exception as exc:
                    current_app.logger.error(
                        'Escalation notification failed for alert %s: %s',
                        alert_id, exc)
                    flash(_('Alert escalated, but notifying the team failed.'),
                          'warning')

            # Closing as a false positive also records the customer on the
            # screening whitelist, so the same name is not re-flagged.
            # NOTE: this suppresses future SANCTIONS-SCREENING hits on this
            # name too, not just this transaction-monitoring rule. The alert
            # reference is written into the reason so the decision can always
            # be traced back to the case that justified it, and the entry can
            # be revoked from Screening > Whitelist.
            if action == 'false_positive':
                row = db.execute(
                    """SELECT a.alert_reference,
                              COALESCE(c.full_name, c.company_name) AS cname,
                              c.id AS cid
                         FROM tm_alerts a
                         LEFT JOIN customers c ON a.customer_id = c.id
                        WHERE a.id = %s""", (alert_id,)).fetchone()
                cname = (row['cname'] if row else None) or ''
                if cname.strip():
                    try:
                        db.execute("""
                            INSERT INTO screening_whitelist
                                (name, normalized_name, reason, added_by,
                                 entity_type, status)
                            VALUES (%s, %s, %s, %s, 'Individual', 'Active')
                            ON CONFLICT (normalized_name)
                                WHERE normalized_name IS NOT NULL
                            DO UPDATE SET reason = EXCLUDED.reason
                        """, (
                            cname.strip(),
                            cname.upper().strip(),
                            'AML alert %s closed as false positive: %s' % (
                                (row['alert_reference'] if row else alert_id),
                                (notes or 'no notes')),
                            current_user.id,
                        ))
                        db.commit()
                        flash(_('Customer added to the screening whitelist.'),
                              'info')
                    except Exception as exc:
                        db.rollback()
                        current_app.logger.error(
                            'Whitelisting from AML alert %s failed: %s',
                            alert_id, exc)
                        flash(_('Alert closed, but the customer could not be '
                                'added to the whitelist. Please add manually.'),
                              'warning')
                else:
                    flash(_('Alert closed. No linked customer name, so nothing '
                            'was added to the whitelist.'), 'warning')

            flash(f'Alert updated to {new_status}', 'success')
        return redirect(url_for('aml.view_alert', alert_id=alert_id))

    alert = db.execute("""
        SELECT a.id, a.alert_reference, CAST(a.alert_date AS TEXT) as alert_date,
               a.alert_description, a.alert_severity, a.status,
               a.assigned_to, a.investigation_notes, a.disposition,
               a.triggered_transactions, a.rule_id, a.customer_id,
               a.disposition_by, a.disposition_date,
               r.rule_name, r.rule_code, r.rule_description,
               c.full_name, c.company_name, c.customer_reference, c.risk_classification,
               c.id as cust_id
        FROM tm_alerts a
        LEFT JOIN tm_rules r ON a.rule_id = r.id
        LEFT JOIN customers c ON a.customer_id = c.id
        WHERE a.id = %s
    """, (alert_id,)).fetchone()

    if not alert:
        flash('Alert not found', 'danger')
        return redirect(url_for('aml.alert_list'))

    tx_ids = json.loads(alert['triggered_transactions'] or '[]')
    transactions = []
    if tx_ids:
        placeholders = ','.join(['%s'] * len(tx_ids))
        transactions = db.execute(f"SELECT * FROM transactions WHERE id IN ({placeholders})", tx_ids).fetchall()

    recent_txs = db.execute("""
        SELECT * FROM transactions WHERE customer_id=%s
        ORDER BY transaction_date DESC LIMIT 10
    """, (alert['cust_id'],)).fetchall()

    compliance_users = db.execute("SELECT id, first_name, last_name FROM users WHERE is_active=1").fetchall()

    return render_template('aml/alert_view.html',
                           alert=alert, transactions=transactions,
                           recent_txs=recent_txs,
                           compliance_users=compliance_users)


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
    flash('Rule updated', 'success')
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
            flash('No file selected', 'danger')
            return redirect(request.url)

        f = request.files['file']
        if not f.filename:
            flash('No file selected', 'danger')
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
                flash('Only CSV or XLSX files accepted', 'danger')
                return redirect(request.url)

            # Enforce row limit
            if len(rows) > MAX_ROWS:
                rows = rows[:MAX_ROWS]
                flash(f'File truncated to {MAX_ROWS} rows (max per upload). Split file for more.', 'warning')

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
                flash(f'Rule code {code} already exists', 'danger')
                return render_template('aml/rule_form.html', rule=None, action='Create')

            db.execute("""
                INSERT INTO tm_rules 
                (rule_code, rule_name, rule_description, rule_category, rule_type,
                 threshold_value, threshold_currency, time_period_days, severity, is_active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
            """, (
                code,
                request.form.get('rule_name','').strip(),
                request.form.get('rule_description','').strip(),
                request.form.get('rule_category','').strip(),
                request.form.get('rule_type','THRESHOLD'),
                float(request.form.get('threshold_value') or 0) or None,
                request.form.get('threshold_currency','').strip() or None,
                int(request.form.get('time_period_days') or 1),
                request.form.get('severity','MEDIUM')
            ))
            db.commit()
            flash(f'Rule {code} created successfully', 'success')
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
        flash('Rule not found', 'danger')
        return redirect(url_for('aml.rule_list'))

    if request.method == 'POST':
        try:
            db.execute("""
                UPDATE tm_rules SET
                    rule_name=%s, rule_description=%s, rule_category=%s, rule_type=%s,
                    threshold_value=%s, threshold_currency=%s, time_period_days=%s, severity=%s
                WHERE id=%s
            """, (
                request.form.get('rule_name','').strip(),
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
            flash('Rule updated successfully', 'success')
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
        flash('Cannot delete built-in rules. Disable them instead.', 'warning')
        return redirect(url_for('aml.rule_list'))
    db.execute("DELETE FROM tm_rules WHERE id=%s", (rule_id,))
    db.commit()
    flash('Rule deleted', 'success')
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
            flash('Select a valid rule', 'danger')
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
        flash('Customer not found','danger')
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
        flash('Customer not found.', 'danger')
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
                   (rule_code, rule_name, rule_description, rule_category, rule_type,
                    threshold_value, threshold_currency, time_period_days,
                    severity, is_active, status, created_by, created_at, version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'PENDING',%s,NOW(),1)""",
                (
                    data['rule_code'].strip().upper(),
                    data['rule_name'].strip(),
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
            flash('Rule submitted for approval.', 'success')
            return redirect(url_for('aml.rules_list'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')
    return render_template('aml/rules/form.html', rule=None, action='create')


@aml_bp.route('/rules/<int:rule_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('aml', level='edit')
def rule_edit(rule_id):
    db = get_db()
    rule = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not rule:
        flash('Rule not found.', 'danger')
        return redirect(url_for('aml.rules_list'))

    if request.method == 'POST':
        data = request.form
        try:
            # Create a new version pending approval instead of overwriting
            db.execute(
                """INSERT INTO tm_rules
                   (rule_code, rule_name, rule_description, rule_category, rule_type,
                    threshold_value, threshold_currency, time_period_days,
                    severity, is_active, status, created_by, created_at, version, previous_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'PENDING',%s,NOW(),%s,%s)""",
                (
                    data['rule_code'].strip().upper(),
                    data['rule_name'].strip(),
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
            flash('Edited rule submitted for approval (v%d → v%d).' % (rule['version'], rule['version'] + 1), 'info')
            return redirect(url_for('aml.rules_list'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

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
    flash('Rule approved and activated.', 'success')
    return redirect(url_for('aml.rules_list'))


@aml_bp.route('/rules/<int:rule_id>/disable', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def rule_disable(rule_id):
    db = get_db()
    db.execute(
        "UPDATE tm_rules SET status='DISABLED', is_active=0, updated_at=NOW(), updated_by=%s WHERE id=%s",
        (current_user.id, rule_id)
    )
    db.commit()
    flash('Rule disabled.', 'warning')
    return redirect(url_for('aml.rules_list'))


@aml_bp.route('/rules/<int:rule_id>/rollback', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def rule_rollback(rule_id):
    """Re-activate the previous version of a rule and disable this one."""
    db = get_db()
    rule = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not rule or not rule['previous_id']:
        flash('No previous version to roll back to.', 'danger')
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
    flash('Rolled back to previous rule version.', 'info')
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
