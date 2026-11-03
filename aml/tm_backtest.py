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
Backtest, simulation and tuning for transaction-monitoring rules (Phase 7, TM-G1/G2/G3).

Nothing here writes alerts, cases or transaction flags. A run reads the
transactions of a period (plus the look-back the rules need), checks their
quality first (TM-G1), then replays every rule the way live monitoring would
(aml/tm_engine.py), with the same "one open alert per rule and customer per
24 hours" grouping, and reports what would have fired.

  data_quality(txs)                  -> issues found before rules run
  backtest(db, rules, date_from, date_to, overrides=None) -> per-rule results
  compare(db, rule, candidate_params, date_from, date_to) -> current vs candidate
  sweep(db, rule, values, date_from, date_to)             -> alerts per threshold value
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from aml import tm_engine as E

DEDUP_HOURS = 24          # live monitoring keeps one open alert per rule + customer for 24 hours
DUP_SECONDS = 120         # the same transaction again within 2 minutes is reported (kept); same second = duplicate
LATE_DAYS = 7             # recorded more than 7 days after the transaction date = late arrival
MAX_SAMPLE = 25

KNOWN_TYPES = {'CASH_DEPOSIT', 'CASH_WITHDRAWAL', 'DEPOSIT', 'WITHDRAWAL', 'TRANSFER', 'TRANSFER_IN',
               'TRANSFER_OUT', 'CREDIT', 'DEBIT', 'PAYMENT', 'REFUND', 'REMITTANCE', 'CASH_IN', 'CASH_OUT',
               'REVERSAL', 'CHARGEBACK', 'FEE'}
REVERSAL_TYPES = {'REFUND', 'REVERSAL', 'CHARGEBACK'}


# --------------------------------------------------------------------------- loading
def load_transactions(db, date_from=None, date_to=None, lookback_days=0):
    """Transactions of [date_from - lookback, date_to] with the fields the rules use."""
    where, args = [], []
    if date_from:
        start = (datetime.strptime(date_from, '%Y-%m-%d') - timedelta(days=int(lookback_days))).strftime('%Y-%m-%d')
        where.append("substr(transaction_date, 1, 10) >= %s")
        args.append(start)
    if date_to:
        where.append("substr(transaction_date, 1, 10) <= %s")
        args.append(date_to)
    sql = ("SELECT id, transaction_reference, customer_id, transaction_date, transaction_type, amount, currency, "
           "counterparty_name, counterparty_account, counterparty_country, pep_involvement, pep_name, "
           "sanctions_hit, sanctions_list, alert_raised, created_at FROM transactions")
    if where:
        sql += " WHERE " + " AND ".join(where)
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def load_customers(db, ids):
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    rows = db.execute("SELECT id, annual_income_range, risk_classification FROM customers WHERE id = ANY(%s)",
                      (list(ids),)).fetchall()
    return {r['id']: dict(r) for r in rows}


# --------------------------------------------------------------------------- TM-G1 data quality
def data_quality(txs, known_customers=None, now=None):
    """Issues that make monitoring unreliable, found before the rules run.
    Returns {'total', 'issues': {code: count}, 'samples': {code: [ids]}, 'exclude': set(ids)}.
    Excluded from monitoring: likely duplicates (all but the first), and rows with no
    usable date, customer or amount."""
    now = now or datetime.now()
    issues, samples, exclude = Counter(), defaultdict(list), set()

    def flag(code, t, drop=False):
        issues[code] += 1
        if len(samples[code]) < MAX_SAMPLE:
            samples[code].append(t.get('id'))
        if drop:
            exclude.add(t.get('id'))

    seen_ref, last_seen = {}, {}
    ordered = sorted(txs, key=lambda t: (E.parse_ts(t.get('transaction_date')) or datetime.min, t.get('id') or 0))
    for t in ordered:
        ts = E.parse_ts(t.get('transaction_date'))
        amount = E._num(t.get('amount'))
        if ts is None:
            flag('date_unreadable', t, drop=True)
            continue
        if ts > now + timedelta(days=1):
            flag('date_in_future', t)
        if t.get('customer_id') is None:
            flag('customer_missing', t, drop=True)
        elif known_customers is not None and t['customer_id'] not in known_customers:
            flag('customer_unknown', t, drop=True)
        if amount is None or amount <= 0:
            flag('amount_missing_or_not_positive', t, drop=True)
        if not (t.get('currency') or '').strip():
            flag('currency_missing', t)
        tt = (t.get('transaction_type') or '').upper()
        if tt not in KNOWN_TYPES:
            flag('type_unknown', t)
        if tt in ('TRANSFER_IN', 'TRANSFER_OUT', 'REMITTANCE') and not (t.get('counterparty_country') or '').strip():
            flag('transfer_without_country', t)
        created = E.parse_ts(t.get('created_at'))
        if created and (created - ts).days > LATE_DAYS:
            flag('late_arrival', t)
        ref = (t.get('transaction_reference') or '').strip()
        if ref:
            if ref in seen_ref:
                flag('duplicate_reference', t, drop=True)
                continue
            seen_ref[ref] = t.get('id')
        key = (t.get('customer_id'), tt, round(amount or 0, 2), (t.get('currency') or '').upper(),
               (t.get('counterparty_account') or '').strip())
        prev = last_seen.get(key)
        if prev is not None and ts == prev:
            flag('duplicate_likely', t, drop=True)      # same customer, type, amount, account, same second
        elif prev is not None and (ts - prev).total_seconds() <= DUP_SECONDS:
            flag('repeat_within_2_minutes', t)          # kept: repeated small payments are what card testing looks like
        last_seen[key] = ts
        if tt in REVERSAL_TYPES:
            flag('reversal_or_refund', t)
    measurable = sum(1 for t in txs if t.get('created_at'))
    return {'total': len(txs), 'issues': dict(issues), 'samples': {k: v for k, v in samples.items()},
            'exclude': exclude, 'late_measurable': measurable}


# --------------------------------------------------------------------------- replay
def _in_period(t, date_from, date_to):
    d = t['_ts'].strftime('%Y-%m-%d')
    return (not date_from or d >= date_from) and (not date_to or d <= date_to)


def replay(rules, txs, customers, ctx, date_from=None, date_to=None, params_by_rule=None, exclude=()):
    """Run the rules over the period as live monitoring would. Returns
    {rule_id: {'hits', 'alerts', 'customers', 'by_month', 'sample', 'alert_tx_ids'}}."""
    params_by_rule = params_by_rule or {}
    hist = E.History([t for t in txs if t.get('id') not in exclude])
    period = sorted((t for lst, _k, _s in hist.by_customer.values() for t in lst if _in_period(t, date_from, date_to)),
                    key=lambda t: (t['_ts'], t.get('id') or 0))
    out = {}
    for rule in rules:
        if not E.supported(rule.get('rule_code')):
            out[rule['id']] = {'supported': False}
            continue
        p = params_by_rule.get(rule['id']) or E.rule_params(rule)
        last_alert = {}
        res = {'supported': True, 'hits': 0, 'alerts': 0, 'customers': set(), 'by_month': Counter(),
               'sample': [], 'alert_tx_ids': set()}
        for t in period:
            hit = E.evaluate(rule, t, hist, customers.get(t.get('customer_id')), ctx, params=p)
            if not hit:
                continue
            res['hits'] += 1
            cust = t.get('customer_id')
            prev = last_alert.get(cust)
            if prev and (t['_ts'] - prev).total_seconds() < DEDUP_HOURS * 3600:
                continue                           # joins the open alert, as live monitoring does
            last_alert[cust] = t['_ts']
            res['alerts'] += 1
            res['customers'].add(cust)
            res['by_month'][t['_ts'].strftime('%Y-%m')] += 1
            res['alert_tx_ids'].add(t.get('id'))
            if len(res['sample']) < MAX_SAMPLE:
                res['sample'].append({'tx_id': t.get('id'), 'customer_id': cust,
                                      'date': t['_ts'].strftime('%Y-%m-%d %H:%M'), 'amount': E._amt(t),
                                      'type': t.get('transaction_type'), 'reason': hit.description,
                                      'already_flagged': bool(t.get('alert_raised'))})
        res['customers'] = len(res['customers'])
        res['by_month'] = dict(sorted(res['by_month'].items()))
        out[rule['id']] = res
    return out


def _prepare(db, rules, date_from, date_to):
    E.ensure_packs_loaded()
    txs = load_transactions(db, date_from, date_to, E.max_lookback_days(rules))
    customers = load_customers(db, {t.get('customer_id') for t in txs})
    dq = data_quality(txs, known_customers=set(customers))
    ctx = E.Context(E.load_high_risk(db))
    return txs, customers, dq, ctx


def _summary(dq, txs, date_from, date_to):
    in_period = sum(1 for t in txs if t.get('_ts') and _in_period(t, date_from, date_to))
    return {'date_from': date_from, 'date_to': date_to, 'loaded': len(txs), 'evaluated': in_period,
            'excluded': len(dq['exclude']), 'quality': {k: v for k, v in dq.items() if k != 'exclude'}}


def backtest(db, rules, date_from=None, date_to=None, params_by_rule=None):
    txs, customers, dq, ctx = _prepare(db, rules, date_from, date_to)
    res = replay(rules, txs, customers, ctx, date_from, date_to, params_by_rule, dq['exclude'])
    for r in res.values():
        r.pop('alert_tx_ids', None)
    return {'summary': _summary(dq, txs, date_from, date_to), 'rules': res}


def compare(db, rule, candidate_params, date_from=None, date_to=None, current_rule=None):
    """Current (active) behaviour vs a candidate set of parameters, same data, same period.
    `rule` = the candidate version (or the rule with candidate_params); `current_rule` = the
    version in force (defaults to `rule` with its stored parameters)."""
    current_rule = current_rule or rule
    both = [current_rule] if current_rule is rule else [current_rule, rule]
    txs, customers, dq, ctx = _prepare(db, both, date_from, date_to)
    cur = replay([current_rule], txs, customers, ctx, date_from, date_to, None, dq['exclude'])[current_rule['id']]
    cand_rule = dict(rule, id=-1)
    cand = replay([cand_rule], txs, customers, ctx, date_from, date_to,
                  {-1: candidate_params or E.rule_params(rule)}, dq['exclude'])[-1]
    if not cur.get('supported') or not cand.get('supported'):
        return {'summary': _summary(dq, txs, date_from, date_to), 'supported': False}
    a, b = cur.pop('alert_tx_ids'), cand.pop('alert_tx_ids')
    return {'summary': _summary(dq, txs, date_from, date_to), 'supported': True,
            'current': cur, 'candidate': cand,
            'only_current': len(a - b), 'only_candidate': len(b - a), 'both': len(a & b)}


def sweep(db, rule, values, date_from=None, date_to=None, param='threshold'):
    """Alert volume of one rule for several values of one parameter (the tuning curve)."""
    txs, customers, dq, ctx = _prepare(db, [rule], date_from, date_to)
    base = E.rule_params(rule)
    rows = []
    for v in values:
        p = dict(base, **{param: v})
        r = replay([dict(rule, id=-1)], txs, customers, ctx, date_from, date_to, {-1: p}, dq['exclude'])[-1]
        if not r.get('supported'):
            return {'summary': _summary(dq, txs, date_from, date_to), 'supported': False, 'rows': []}
        rows.append({'value': v, 'alerts': r['alerts'], 'customers': r['customers'], 'hits': r['hits'],
                     'current': (p.get(param) == base.get(param))})
    return {'summary': _summary(dq, txs, date_from, date_to), 'supported': True, 'param': param, 'rows': rows}


def default_sweep_values(rule, param='threshold'):
    """A spread of values around the current one (x0.5 .. x2), for amounts and counts alike."""
    cur = E.rule_params(rule).get(param)
    if cur in (None, ''):
        return []
    cur = float(cur)
    unit = E.RULE_SPECS.get(rule.get('rule_code'), {}).get('params', {}).get(param, {}).get('unit')
    if unit in ('count', 'days', 'hours', 'minutes'):
        vals = sorted({max(1, int(round(cur * f))) for f in (0.5, 0.75, 1, 1.25, 1.5, 2)} | {int(cur) - 1, int(cur) + 1})
        return [v for v in vals if v >= 1]
    return sorted({round(cur * f, 2) for f in (0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 2)})


def record_run(db, kind, rule, params, date_from, date_to, result, user_id):
    """Keep the evidence of a backtest (who ran what, on which period, with which outcome)."""
    try:
        summary = {k: v for k, v in result.items() if k in ('summary', 'only_current', 'only_candidate', 'both')}
        for k in ('current', 'candidate'):
            if k in result:
                summary[k] = {x: result[k].get(x) for x in ('alerts', 'customers', 'hits')}
        if 'rows' in result:
            summary['rows'] = result['rows']
        if 'rules' in result:
            summary['rules'] = {str(i): {x: r.get(x) for x in ('alerts', 'customers', 'hits', 'supported')}
                                for i, r in result['rules'].items()}
        db.execute("""INSERT INTO tm_backtest_runs (kind, rule_id, rule_code, rule_version, parameters,
                          date_from, date_to, result, run_by)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (kind, rule.get('id') if rule else None, rule.get('rule_code') if rule else None,
                    rule.get('version') if rule else None, json.dumps(params or {}, default=str),
                    date_from or None, date_to or None, json.dumps(summary, default=str), user_id))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
