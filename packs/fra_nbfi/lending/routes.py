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

"""FRA NBFI pack — UI for Lending Conduct & Portfolio. Permission: pack module
'lending' (view / edit), stored in user_module_permissions."""

import csv
import io
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from attachments.service import list_attachments
from database.db import get_db
from models.audit import AuditLog

from . import lending_bp as bp  # noqa: F401 — also exported as `bp` for the pack manifest
from . import importer, logic, service

MODULE = 'lending'
DOC_TYPES = ('national_id', 'contract', 'receipt_acknowledgement', 'credit_study', 'guarantor_id', 'project_photo',
             'commercial_register', 'tax_card', 'utility_bill', 'resignation_letter', 'other')


def perm(level='view'):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapped(*a, **kw):
            ok = current_user.can_edit(MODULE) if level == 'edit' else current_user.can_view(MODULE)
            if not ok:
                flash(_('You do not have permission for this Lending action.'), 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            return f(*a, **kw)
        return wrapped
    return deco


def _scope(col):
    try:
        from services import org_service
        return org_service.scope_filter(col)
    except Exception:
        return '', ()


def _log(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, MODULE, item_id, details, request.remote_addr)
    except Exception:
        get_db().rollback()


def _err(e):
    flash(_(str(e)) if ':' not in str(e) else str(e), 'danger')


def _date(v):
    try:
        return datetime.strptime(v, '%Y-%m-%d').date() if v else None
    except ValueError:
        return None


def _loan_or_404(loan_id):
    b = service.bundle(loan_id)
    if not b:
        abort(404)
    if b['loan'].get('org_unit_id'):
        from services import org_service
        if not org_service.can_see_unit(b['loan']['org_unit_id']):
            abort(404)
    return b


@bp.context_processor
def _ctx():
    authed = getattr(current_user, 'is_authenticated', False)
    return {'ln_can_edit': authed and current_user.can_edit(MODULE), 'today': date.today(), 'DOC_TYPES': DOC_TYPES}


# ------------------------------------------------------------------ dashboard
@bp.route('/')
@perm('view')
def dashboard():
    db = get_db()
    sql, args = _scope('l.org_unit_id')
    loans = service.active_portfolio(sql, args)
    company = logic.portfolio_metrics(loans)
    prev = service.previous_snapshot('company', 'ALL', date(date.today().year, date.today().month, 1))
    by = {dim: logic.par_by(loans, key) for dim, key in (('branch', 'branch_code'), ('officer', 'officer_code'),
                                                          ('product', 'product_code'))}
    threshold = service.param('portfolio.par30_threshold_pct')
    breaches = service.fee_breaches()
    counts = {
        'incomplete': db.execute(f"SELECT count(*) AS n FROM ln_loans l WHERE l.status = 'disbursed' "
                                 f"AND NOT l.file_complete {sql}", args).fetchone()['n'],
        'qa_open': db.execute("SELECT count(*) AS n FROM ln_qa_flags WHERE status = 'open'").fetchone()['n'],
        'exceptions': db.execute("SELECT count(*) AS n FROM ln_exceptions WHERE status = 'pending'").fetchone()['n'],
        'er_pending': db.execute("SELECT count(*) AS n FROM ln_early_repayments WHERE status IN "
                                 "('requested', 'disclosed', 'consented')").fetchone()['n'],
        'aml_candidates': db.execute("SELECT count(*) AS n FROM aml_unusual_transactions WHERE source_module = 'lending' "
                                     "AND status = 'candidate'").fetchone()['n'],
    }
    days = service.param('lending.followup_visit_days')
    missing_visits = []
    if days is not None:
        dl = [dict(r) for r in db.execute(f"SELECT l.* FROM ln_loans l WHERE l.status = 'disbursed' {sql}", args).fetchall()]
        visits = [dict(r) for r in db.execute("SELECT * FROM ln_visits").fetchall()]
        missing_visits, _overdue = logic.visit_gaps(dl, visits, days)
        counts['visits_overdue'] = len(missing_visits) + len(_overdue)
    from regcontrols.engine import get_control
    controls = {code: get_control(code) for code in ('FRA-004', 'FRA-009', 'FRA-010', 'FRA-011', 'FRA-012', 'FRA-013',
                                                     'FRA-014', 'FRA-015', 'FRA-016', 'FRA-017', 'FRA-018', 'FRA-019',
                                                     'FRA-020', 'FRA-021', 'FRA-022', 'FRA-023', 'FRA-024', 'FRA-025',
                                                     'FRA-026')}
    return render_template('fra_nbfi/lending/dashboard.html', company=company, prev=prev, by=by, threshold=threshold,
                           breaches=breaches, counts=counts, controls=controls, buckets=logic.BUCKETS,
                           missing_visits=missing_visits[:20], visits_param=days,
                           trend=logic.trend(company['par'][30], prev['par30']) if prev else None)


@bp.route('/refresh', methods=['POST'])
@perm('edit')
def refresh():
    from .checks import lending_sweep
    res = lending_sweep()
    flash(_('Portfolio data refreshed.') + f' {res}', 'success')
    return redirect(url_for('lending.dashboard'))


# ------------------------------------------------------------------ loans
@bp.route('/loans')
@perm('view')
def loans():
    db = get_db()
    sql, args = _scope('l.org_unit_id')
    clauses, q_args = [], []
    for key, col in (('status', 'l.status'), ('branch', 'l.branch_code'), ('officer', 'l.officer_code'),
                     ('product', 'l.product_code')):
        if request.args.get(key):
            clauses.append(f'{col} = %s')
            q_args.append(request.args[key])
    if request.args.get('incomplete'):
        clauses.append("NOT l.file_complete AND l.status IN ('approved', 'disbursed')")
    if request.args.get('q'):
        clauses.append('(l.loan_ref ILIKE %s OR c.client_ref ILIKE %s OR c.full_name ILIKE %s)')
        q_args += [f"%{request.args['q']}%"] * 3
    where = ' AND '.join(clauses) or '1=1'
    rows = [dict(r) for r in db.execute(f"""
        SELECT l.*, c.client_ref, c.full_name AS client_name FROM ln_loans l JOIN ln_clients c ON c.id = l.client_id
        WHERE {where} {sql} ORDER BY l.loan_ref LIMIT 1000""", tuple(q_args) + tuple(args)).fetchall()]
    branches = [r['b'] for r in db.execute("SELECT DISTINCT branch_code AS b FROM ln_loans WHERE branch_code IS NOT NULL "
                                           "ORDER BY 1").fetchall()]
    return render_template('fra_nbfi/lending/loans.html', loans=rows, branches=branches, f=request.args)


@bp.route('/loans/<int:loan_id>')
@perm('view')
def loan_detail(loan_id):
    b = _loan_or_404(loan_id)
    gaps = service.file_gaps(b)
    elig = service.eligibility(b['client'])
    doc_files = {d['id']: list_attachments(MODULE, 'ln_document', d['id']) for d in b['documents']}
    fees = {}
    cap, tiers = service.param('lending.admin_fee_cap_pct'), service.param('lending.admin_fee_tiers')
    if cap is not None or tiers:
        fees['admin'] = logic.admin_fee_breach(b['loan'], cap_pct=cap, tiers=tiers)
    return render_template('fra_nbfi/lending/loan_detail.html', b=b, gaps=gaps, elig=elig, doc_files=doc_files, fees=fees,
                           blockers=service.disbursement_blockers(b), cap=cap,
                           gps_min=service.param('lending.gps_mandatory_min_amount'))


@bp.route('/loans/<int:loan_id>/disburse', methods=['POST'])
@perm('edit')
def loan_disburse(loan_id):
    _loan_or_404(loan_id)
    try:
        service.mark_disbursed(loan_id, current_user.id, _date(request.form.get('disbursement_date')))
        _log('lending_disburse', loan_id)
        flash(_('Loan marked as disbursed.'), 'success')
    except service.LendingError as e:
        _err(e)
    return redirect(url_for('lending.loan_detail', loan_id=loan_id))


@bp.route('/loans/<int:loan_id>/exception', methods=['POST'])
@perm('edit')
def loan_exception(loan_id):
    _loan_or_404(loan_id)
    try:
        service.request_exception(loan_id, request.form.get('exception_type'), request.form.get('reason'),
                                  current_user.id)
        _log('lending_exception_request', loan_id, request.form.get('exception_type'))
        flash(_('Exception requested. Another user must approve it.'), 'success')
    except service.LendingError as e:
        _err(e)
    return redirect(url_for('lending.loan_detail', loan_id=loan_id))


@bp.route('/exceptions/<int:exception_id>/<decision>', methods=['POST'])
@perm('edit')
def exception_decide(exception_id, decision):
    if decision not in ('approve', 'reject'):
        abort(400)
    try:
        loan_id = service.decide_exception(exception_id, current_user.id, decision == 'approve',
                                           request.form.get('comment'))
        _log(f'lending_exception_{decision}', exception_id)
        flash(_('Exception decision saved.'), 'success')
        return redirect(url_for('lending.loan_detail', loan_id=loan_id))
    except service.LendingError as e:
        _err(e)
        return redirect(request.referrer or url_for('lending.dashboard'))


@bp.route('/loans/<int:loan_id>/record', methods=['POST'])
@perm('edit')
def loan_record(loan_id):
    """Manual entry on the loan file: contract, document, credit study, visit."""
    b = _loan_or_404(loan_id)
    kind = request.form.get('kind')
    f = request.form
    rows = []
    ref = b['loan']['loan_ref']
    if kind == 'contracts':
        rows = [{'loan_ref': ref, 'contract_no': f.get('contract_no'), 'contract_date': f.get('contract_date'),
                 'signed_by_lender': 'yes' if f.get('signed_by_lender') else 'no', 'lender_signed_at': f.get('lender_signed_at'),
                 'signed_by_client': 'yes' if f.get('signed_by_client') else 'no', 'client_signed_at': f.get('client_signed_at'),
                 'penalty_clause_rate_pct': f.get('penalty_clause_rate_pct'),
                 'penalty_clause_cap_pct': f.get('penalty_clause_cap_pct')}]
    elif kind == 'documents':
        if f.get('doc_type') not in DOC_TYPES:
            abort(400)
        rows = [{'loan_ref': ref, 'doc_type': f.get('doc_type'), 'received_date': f.get('received_date'),
                 'reference_no': f.get('reference_no')}]
    elif kind == 'credit_studies':
        lines = []
        for line in (f.get('cost_lines') or '').splitlines():
            if ':' in line:
                label, amt = line.rsplit(':', 1)
                if logic.D(amt.strip() or None) is not None:
                    lines.append({'label': label.strip(), 'amount': str(logic.D(amt.strip()))})
        import json as _json
        rows = [{'loan_ref': ref, 'study_date': f.get('study_date'), 'officer_code': f.get('officer_code'),
                 'monthly_revenue': f.get('monthly_revenue'), 'monthly_costs_total': f.get('monthly_costs_total'),
                 'household_expenses': f.get('household_expenses'), 'other_debt_service': f.get('other_debt_service'),
                 'net_income': f.get('net_income'), 'dsr_pct': f.get('dsr_pct'), 'cost_lines': _json.dumps(lines)}]
    elif kind == 'visits':
        rows = [{'loan_ref': ref, 'planned_date': f.get('planned_date'), 'visit_date': f.get('visit_date'),
                 'officer_code': f.get('officer_code'), 'outcome': f.get('outcome'), 'notes': f.get('notes')}]
    else:
        abort(400)
    batch = importer.import_rows(kind, rows, source='manual', user_id=current_user.id)
    if batch['rows_failed']:
        flash('; '.join(e['error'] for e in batch['errors']), 'danger')
    else:
        flash(_('Saved.'), 'success')
    return redirect(url_for('lending.loan_detail', loan_id=loan_id))


@bp.route('/clients/new', methods=['GET', 'POST'])
@perm('edit')
def client_new():
    return _manual_new('clients')


@bp.route('/loans/new', methods=['GET', 'POST'])
@perm('edit')
def loan_new():
    return _manual_new('loans')


def _manual_new(kind):
    if request.method == 'POST':
        row = {k: v for k, v in request.form.items() if k in importer.KINDS[kind][0] + importer.KINDS[kind][1]}
        batch = importer.import_rows(kind, [row], source='manual', user_id=current_user.id)
        if batch['rows_failed']:
            flash('; '.join(e['error'] for e in batch['errors']), 'danger')
            return render_template('fra_nbfi/lending/manual_form.html', kind=kind, form=request.form,
                                   cols=importer.KINDS[kind], products=_products())
        _log(f'lending_manual_{kind}')
        flash(_('Saved.'), 'success')
        if kind == 'loans':
            lid = get_db().execute("SELECT id FROM ln_loans WHERE loan_ref = %s", (row.get('loan_ref'),)).fetchone()['id']
            return redirect(url_for('lending.loan_detail', loan_id=lid))
        return redirect(url_for('lending.loans'))
    return render_template('fra_nbfi/lending/manual_form.html', kind=kind, form={}, cols=importer.KINDS[kind],
                           products=_products())


def _products():
    return [dict(r) for r in get_db().execute("SELECT * FROM ln_products WHERE is_active ORDER BY code").fetchall()]


@bp.route('/products', methods=['GET', 'POST'])
@perm('view')
def products():
    db = get_db()
    if request.method == 'POST':
        if not current_user.can_edit(MODULE):
            abort(403)
        code = (request.form.get('code') or '').strip().upper()
        docs = [d for d in request.form.getlist('required_docs') if d in DOC_TYPES]
        if not code or not request.form.get('name_en'):
            flash(_('Code and name are required.'), 'danger')
        else:
            db.execute("""INSERT INTO ln_products (code, name_en, name_ar, licence_type, required_docs)
                          VALUES (%s,%s,%s,%s,%s) ON CONFLICT (code) DO UPDATE SET name_en = EXCLUDED.name_en,
                          name_ar = EXCLUDED.name_ar, licence_type = EXCLUDED.licence_type,
                          required_docs = EXCLUDED.required_docs""",
                       (code, request.form['name_en'], request.form.get('name_ar') or None,
                        request.form.get('licence_type') or 'microfinance', docs or ['national_id']))
            db.commit()
            _log('lending_product_save', None, code)
            flash(_('Product saved.'), 'success')
        return redirect(url_for('lending.products'))
    return render_template('fra_nbfi/lending/products.html', products=[dict(r) for r in db.execute(
        "SELECT * FROM ln_products ORDER BY code").fetchall()])


# ------------------------------------------------------------------ QA queue
@bp.route('/qa')
@perm('view')
def qa():
    rows = [dict(r) for r in get_db().execute("""
        SELECT f.*, l.loan_ref, l.officer_code, l.branch_code, c.client_ref FROM ln_qa_flags f
        JOIN ln_loans l ON l.id = f.loan_id JOIN ln_clients c ON c.id = l.client_id
        ORDER BY (f.status = 'open') DESC, f.created_at DESC LIMIT 1000""").fetchall()]
    return render_template('fra_nbfi/lending/qa.html', flags=rows)


@bp.route('/qa/<int:flag_id>', methods=['POST'])
@perm('edit')
def qa_review(flag_id):
    try:
        service.review_qa(flag_id, current_user.id, request.form.get('status'), request.form.get('note'))
        flash(_('QA decision saved.'), 'success')
    except service.LendingError as e:
        _err(e)
    return redirect(url_for('lending.qa'))


# ------------------------------------------------------------------ fees
@bp.route('/fees')
@perm('view')
def fees():
    br = service.fee_breaches()
    if request.args.get('export') == 'csv':
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['control', 'loan_ref', 'client_ref', 'client_name', 'branch', 'detail', 'charged', 'allowed',
                    'overcharge'])
        for code in ('FRA-017', 'FRA-018', 'FRA-020', 'FRA-025', 'FRA-026'):
            for b in br[code]:
                w.writerow([code, b['loan_ref'], b['client_ref'], b['client_name'], b['branch'],
                            b.get('instalment') or b.get('date') or '', b['charged'], b['allowed'], b['overcharge']])
        return Response('﻿' + out.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename=fee_breaches.csv'})
    return render_template('fra_nbfi/lending/fees.html', br=br, by_client=service.overcharge_by_client(br))


# ------------------------------------------------------------------ early repayment
@bp.route('/loans/<int:loan_id>/early-repayment', methods=['POST'])
@perm('edit')
def er_new(loan_id):
    _loan_or_404(loan_id)
    try:
        er_id = service.er_request(loan_id, request.form.get('settlement_amount'), request.form.get('prepayment_fee'),
                                   current_user.id)
        _log('lending_er_request', er_id)
        return redirect(url_for('lending.er_detail', er_id=er_id))
    except (service.LendingError, ArithmeticError, ValueError) as e:
        _err(e)
        return redirect(url_for('lending.loan_detail', loan_id=loan_id))


@bp.route('/early-repayments/<int:er_id>')
@perm('view')
def er_detail(er_id):
    er = get_db().execute("SELECT * FROM ln_early_repayments WHERE id = %s", (er_id,)).fetchone()
    if not er:
        abort(404)
    er = dict(er)
    b = _loan_or_404(er['loan_id'])
    return render_template('fra_nbfi/lending/er_detail.html', er=er, b=b,
                           attach_module=MODULE, attach_record_type='ln_early_repayment', attach_record_id=er_id,
                           attach_items=list_attachments(MODULE, 'ln_early_repayment', er_id),
                           attach_can_edit=current_user.can_edit(MODULE) and er['status'] != 'executed')


@bp.route('/early-repayments/<int:er_id>/<action>', methods=['POST'])
@perm('edit')
def er_action(er_id, action):
    try:
        if action == 'disclose':
            service.er_disclose(er_id)
        elif action == 'consent':
            service.er_consent(er_id, bool(request.form.get('consent_signed')),
                               bool(request.form.get('cost_acknowledged')), _date(request.form.get('consent_date')))
        elif action == 'execute':
            service.er_execute(er_id, current_user.id)
        else:
            abort(400)
        _log(f'lending_er_{action}', er_id)
        flash(_('Saved.'), 'success')
    except service.LendingError as e:
        _err(e)
    return redirect(url_for('lending.er_detail', er_id=er_id))


@bp.route('/early-repayments/<int:er_id>/print')
@perm('view')
def er_print(er_id):
    er = get_db().execute("SELECT * FROM ln_early_repayments WHERE id = %s", (er_id,)).fetchone()
    if not er:
        abort(404)
    return render_template('fra_nbfi/lending/er_print.html', er=dict(er), b=_loan_or_404(er['loan_id']))


# ------------------------------------------------------------------ disclosure (FRA-019)
@bp.route('/disclosure')
@perm('view')
def disclosure():
    today = date.today()
    q_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    prev_end = q_start - timedelta(days=1)
    prev_start = date(prev_end.year, 3 * ((prev_end.month - 1) // 3) + 1, 1)
    start = _date(request.args.get('start')) or prev_start
    end = _date(request.args.get('end')) or prev_end
    rows = service.pricing_disclosure(start, end)
    if request.args.get('export') == 'csv':
        out = io.StringIO()
        w = csv.writer(out)
        cols = ['product_code', 'name_en', 'loans', 'total_amount', 'avg_rate', 'min_rate', 'max_rate', 'avg_apr',
                'max_apr', 'avg_admin_fee_pct', 'max_admin_fee_pct', 'penalty_rate', 'penalty_cap']
        w.writerow(['period_start', 'period_end'] + cols)
        for r in rows:
            w.writerow([start, end] + [r.get(c) for c in cols])
        return Response('﻿' + out.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename=pricing_disclosure_{start}_{end}.csv'})
    report = get_db().execute("SELECT id FROM regulatory_reports WHERE report_code = 'FRA-RPD'").fetchone()
    return render_template('fra_nbfi/lending/disclosure.html', rows=rows, start=start, end=end,
                           submissions=service.disclosure_submissions(), report=report)


# ------------------------------------------------------------------ import
@bp.route('/import', methods=['GET', 'POST'])
@perm('view')
def import_data():
    db = get_db()
    if request.method == 'POST':
        if not current_user.can_edit(MODULE):
            abort(403)
        kind = request.form.get('kind')
        file = request.files.get('file')
        if kind not in importer.KINDS or not file or not file.filename:
            flash(_('Choose the data type and a CSV or Excel file.'), 'warning')
            return redirect(url_for('lending.import_data'))
        data = file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            flash(_('The file is larger than 20 MB.'), 'danger')
            return redirect(url_for('lending.import_data'))
        try:
            rows = importer.read_table(file.filename, data)
        except Exception as e:
            flash(_('The file could not be read:') + f' {e}', 'danger')
            return redirect(url_for('lending.import_data'))
        batch = importer.import_rows(kind, rows, filename=file.filename, user_id=current_user.id)
        _log('lending_import', batch['id'], f"{kind} ok={batch['rows_ok']} failed={batch['rows_failed']}")
        flash(_('Import finished: %(ok)s row(s) saved, %(bad)s with errors.', ok=batch['rows_ok'],
                bad=batch['rows_failed']), 'success' if not batch['rows_failed'] else 'warning')
        return redirect(url_for('lending.import_data', batch=batch['id']))
    batches = [dict(r) for r in db.execute("SELECT * FROM ln_import_batches ORDER BY id DESC LIMIT 30").fetchall()]
    sel = None
    if request.args.get('batch'):
        sel = next((x for x in batches if str(x['id']) == request.args['batch']), None)
    return render_template('fra_nbfi/lending/import.html', kinds=importer.KINDS, batches=batches, sel=sel)


@bp.route('/import/template/<kind>.csv')
@perm('view')
def import_template(kind):
    if kind not in importer.KINDS:
        abort(404)
    return Response('﻿' + importer.template_csv(kind), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=lending_{kind}_template.csv'})
