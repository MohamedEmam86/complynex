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
Transaction-monitoring tuning pages (Phase 7, TM-G1..G4):

  /aml/tm-tuning                       backtest of every rule in force + threshold sweep of one rule
  /aml/tm-rules/<id>/backtest          a pending version vs the version in force, same data and period
  /aml/tm-data-quality                 data-quality report of a period (before rules run)
  /aml/tm-rules/history/<code>         every version of a rule: who, when, why, parameters, alerts
  /aml/tm-rules/<id>/reject            reject a pending version (POST, reason)

Backtests never write alerts, cases or transaction flags; each run is kept in
tm_backtest_runs as evidence.
"""
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_babel import get_locale
from flask_babel import gettext as _
from flask_login import current_user, login_required

from database.db import get_db
from models.audit import AuditLog
from utils.decorators import permission_required

from . import aml_bp
from . import tm_backtest as B
from . import tm_engine as E
from . import tm_versions as V

MAX_PERIOD_DAYS = 400


def _is_ar():
    return str(get_locale()) == 'ar'


def _L(en, ar):
    return ar if _is_ar() else en


def _period(db):
    """date_from / date_to from the request, defaulting to the last 90 days of data."""
    df, dt = (request.values.get('date_from') or '').strip(), (request.values.get('date_to') or '').strip()
    try:
        if df:
            datetime.strptime(df, '%Y-%m-%d')
        if dt:
            datetime.strptime(dt, '%Y-%m-%d')
    except ValueError:
        flash(_L('Dates must be YYYY-MM-DD.', 'التاريخ لازم يكون بالشكل YYYY-MM-DD.'), 'danger')
        df = dt = ''
    if not dt:
        row = db.execute("SELECT MAX(substr(transaction_date, 1, 10)) AS d FROM transactions").fetchone()
        dt = (row['d'] if row and row['d'] else datetime.now().strftime('%Y-%m-%d'))[:10]
    if not df:
        df = (datetime.strptime(dt, '%Y-%m-%d') - timedelta(days=89)).strftime('%Y-%m-%d')
    if (datetime.strptime(dt, '%Y-%m-%d') - datetime.strptime(df, '%Y-%m-%d')).days > MAX_PERIOD_DAYS:
        df = (datetime.strptime(dt, '%Y-%m-%d') - timedelta(days=MAX_PERIOD_DAYS)).strftime('%Y-%m-%d')
        flash(_L(f'The period was limited to {MAX_PERIOD_DAYS} days.', f'تم تحديد الفترة بـ {MAX_PERIOD_DAYS} يوم.'),
              'info')
    if df > dt:
        df, dt = dt, df
    return df, dt


def _spec_rows(rule):
    """Parameters of a rule with unit, label and current value, for display."""
    spec = E.RULE_SPECS.get(rule.get('rule_code'), {})
    p = E.rule_params(rule)
    rows = []
    for k, d in spec.get('params', {}).items():
        rows.append({'key': k, 'label': d['label_ar'] if _is_ar() else d['label_en'], 'unit': d['unit'],
                     'value': p.get(k), 'default': d['default']})
    return rows, spec.get('op')


@aml_bp.route('/tm-tuning')
@login_required
@permission_required('aml', level='view')
def tm_tuning():
    db = get_db()
    rules = V.active_rules(db)
    E.ensure_packs_loaded()
    df, dt = _period(db)
    result, sweep, chosen = None, None, None
    if request.args.get('run'):
        result = B.backtest(db, rules, df, dt)
        B.record_run(db, 'backtest_all', None, {}, df, dt, result, current_user.id)
    rid = request.args.get('sweep_rule', type=int)
    if rid:
        chosen = next((r for r in rules if r['id'] == rid), None)
        param = request.args.get('param') or 'threshold'
        if chosen and param in E.RULE_SPECS.get(chosen['rule_code'], {}).get('params', {}):
            values = B.default_sweep_values(chosen, param)
            if values:
                sweep = B.sweep(db, chosen, values, df, dt, param=param)
                B.record_run(db, 'sweep', chosen, {param: values}, df, dt, sweep, current_user.id)
    specs = {r['id']: _spec_rows(r) for r in rules}
    return render_template('aml/tm_tuning.html', rules=rules, specs=specs, result=result, sweep=sweep,
                           chosen=chosen, date_from=df, date_to=dt, L=_L, ar=_is_ar(),
                           supported=E.supported)


@aml_bp.route('/tm-rules/<int:rule_id>/backtest')
@login_required
@permission_required('aml', level='view')
def tm_rule_backtest(rule_id):
    db = get_db()
    rule = db.execute("SELECT * FROM tm_rules WHERE id = %s", (rule_id,)).fetchone()
    if not rule:
        flash(_('Rule not found.'), 'danger')
        return redirect(url_for('aml.rules_list'))
    rule = dict(rule)
    current = next((r for r in V.active_rules(db) if r['rule_code'] == rule['rule_code']), None)
    df, dt = _period(db)
    result = None
    if request.args.get('run'):
        E.ensure_packs_loaded()
        result = B.compare(db, rule, E.rule_params(rule), df, dt, current_rule=current or rule)
        B.record_run(db, 'compare', rule, E.rule_params(rule), df, dt, result, current_user.id)
    return render_template('aml/tm_backtest.html', rule=rule, current=current, result=result,
                           changes=V.diff(current, rule) if current and current['id'] != rule['id'] else [],
                           date_from=df, date_to=dt, L=_L, ar=_is_ar())


@aml_bp.route('/tm-data-quality')
@login_required
@permission_required('aml', level='view')
def tm_data_quality():
    db = get_db()
    df, dt = _period(db)
    txs = B.load_transactions(db, df, dt)
    known = {r['id'] for r in db.execute("SELECT id FROM customers WHERE id = ANY(%s)",
                                         (list({t['customer_id'] for t in txs if t.get('customer_id')}),)).fetchall()}
    dq = B.data_quality(txs, known_customers=known)
    dq.pop('exclude', None)
    return render_template('aml/tm_data_quality.html', dq=dq, date_from=df, date_to=dt, L=_L, ar=_is_ar())


@aml_bp.route('/tm-rules/history/<code>')
@login_required
@permission_required('aml', level='view')
def tm_rule_history(code):
    db = get_db()
    versions = V.history(db, code)
    if not versions:
        flash(_('Rule not found.'), 'danger')
        return redirect(url_for('aml.rules_list'))
    diffs = {}
    by_id = {v['id']: v for v in versions}
    for v in versions:
        if v.get('previous_id') in by_id:
            diffs[v['id']] = V.diff(by_id[v['previous_id']], v)
    return render_template('aml/tm_rule_history.html', code=code, versions=versions, diffs=diffs, L=_L,
                           ar=_is_ar())


@aml_bp.route('/tm-rules/<int:rule_id>/reject', methods=['POST'])
@login_required
@permission_required('aml', level='edit')
def tm_rule_reject(rule_id):
    db = get_db()
    try:
        rule = V.reject(db, rule_id, current_user.id, request.form.get('reason'))
        AuditLog.log(current_user.id, 'Reject TM Rule Version', 'AML', rule_id,
                     f"{rule['rule_code']} v{rule.get('version')} rejected: {request.form.get('reason')}",
                     request.remote_addr)
        flash(_L('Version rejected.', 'تم رفض النسخة.'), 'info')
    except V.VersionError as e:
        flash(_(str(e)), 'danger')
    return redirect(url_for('aml.rules_list'))
