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
import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from aml import tm_engine as E

log = logging.getLogger(__name__)

DEDUP_HOURS = 24          # live monitoring keeps one open alert per rule + customer for 24 hours
DUP_SECONDS = 120         # the same transaction again within 2 minutes is reported (kept); same second = duplicate
LATE_DAYS = 7             # recorded more than 7 days after the transaction date = late arrival
MAX_SAMPLE = 25
# A backtest runs inside a web request on a gevent worker (CPU work blocks the worker,
# gunicorn kills it at 120 s): cap what one run may load and how long it may compute.
MAX_ROWS = 300000
MAX_SECONDS = 60


class BacktestTooLarge(ValueError):
    def __init__(self, rows):
        super().__init__(rows)
        self.rows = rows

KNOWN_TYPES = {'CASH_DEPOSIT', 'CASH_WITHDRAWAL', 'DEPOSIT', 'WITHDRAWAL', 'TRANSFER', 'TRANSFER_IN',
               'TRANSFER_OUT', 'CREDIT', 'DEBIT', 'PAYMENT', 'REFUND', 'REMITTANCE', 'CASH_IN', 'CASH_OUT',
               'REVERSAL', 'CHARGEBACK', 'FEE'}
REVERSAL_TYPES = set(E.REVERSAL_TYPES)
ISO_RE = "'^[0-9]{4}-[0-9]{2}-[0-9]{2}'"


# --------------------------------------------------------------------------- loading
def _range(date_from, date_to, lookback_days=0):
    """WHERE clause on transaction_date as plain ISO range comparisons (index-friendly;
    the database collation is C, so text order is date order for YYYY-MM-DD...)."""
    where, args = [], []
    if date_from:
        start = (datetime.strptime(date_from, '%Y-%m-%d') - timedelta(days=int(lookback_days))).strftime('%Y-%m-%d')
        where.append("transaction_date >= %s")
        args.append(start)
    if date_to:
        end = (datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        where.append("transaction_date < %s")
        args.append(end)
    return where, args


def count_transactions(db, date_from=None, date_to=None, lookback_days=0):
    where, args = _range(date_from, date_to, lookback_days)
    sql = "SELECT COUNT(*) AS n FROM transactions" + (" WHERE " + " AND ".join(where) if where else "")
    return db.execute(sql, args).fetchone()['n']


def load_transactions(db, date_from=None, date_to=None, lookback_days=0, max_rows=None):
    """Transactions of [date_from - lookback, date_to] with the fields the rules use.
    Rows whose date is not stored as YYYY-MM-DD are outside any date range (see
    count_not_iso). Raises BacktestTooLarge above max_rows."""
    if max_rows:
        n = count_transactions(db, date_from, date_to, lookback_days)
        if n > max_rows:
            raise BacktestTooLarge(n)
    where, args = _range(date_from, date_to, lookback_days)
    sql = ("SELECT id, transaction_reference, customer_id, transaction_date, transaction_type, amount, currency, "
           "counterparty_name, counterparty_account, counterparty_country, pep_involvement, pep_name, "
           "sanctions_hit, sanctions_list, alert_raised, created_at FROM transactions")
    if where:
        sql += " WHERE " + " AND ".join(where)
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def count_not_iso(db):
    """Transactions whose date is not stored as YYYY-MM-DD...: no date range (backtest,
    live look-back) can find them."""
    try:
        return db.execute(f"SELECT COUNT(*) AS n FROM transactions WHERE transaction_date !~ {ISO_RE} "
                          "OR transaction_date IS NULL").fetchone()['n']
    except Exception:
        log.exception('TM: could not count non-ISO transaction dates')
        return None


def load_first_seen(db, customer_ids):
    """Earliest (ISO-dated) transaction of each customer, for the dormant rule's "activity
    before the quiet period" without loading a year of history."""
    ids = [i for i in customer_ids if i is not None]
    if not ids:
        return {}
    rows = db.execute(f"""SELECT customer_id, MIN(transaction_date) AS d FROM transactions
                          WHERE customer_id = ANY(%s) AND transaction_date ~ {ISO_RE}
                          GROUP BY customer_id""", (list(ids),)).fetchall()
    out = {}
    for r in rows:
        ts = E.parse_ts(r['d'])
        if ts is not None:
            out[r['customer_id']] = ts
    return out


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
        tt = (t.get('transaction_type') or '').upper()
        if amount is not None and amount < 0 and tt in REVERSAL_TYPES:
            flag('refund_stored_negative', t)           # kept: the rules use its size
        elif amount is None or amount <= 0:
            flag('amount_missing_or_not_positive', t, drop=True)
        if not (t.get('currency') or '').strip():
            flag('currency_missing', t)
        if not E.is_iso_date(t.get('transaction_date')):
            flag('date_not_iso', t)                     # kept; database look-backs cannot find it
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


def replay(rules, txs, customers, ctx, date_from=None, date_to=None, params_by_rule=None, exclude=(),
           first_seen=None, deadline=None):
    """Run the rules over the period as live monitoring would. Returns
    {rule_id: {'hits', 'alerts', 'customers', 'by_month', 'sample', 'alert_tx_ids',
    'excluded_currency', 'truncated'}}. `deadline` (time.monotonic()) stops a run that
    takes too long; the rules not finished are marked truncated."""
    params_by_rule = params_by_rule or {}
    hist = E.History([t for t in txs if t.get('id') not in exclude], first_seen=first_seen)
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
               'sample': [], 'alert_tx_ids': set(), 'excluded_currency': Counter(), 'truncated': False}
        for n, t in enumerate(period):
            if deadline is not None and n % 2000 == 0 and time.monotonic() > deadline:
                res['truncated'] = True
                break
            if E.excluded_by_currency(rule, t):
                res['excluded_currency'][(t.get('currency') or '').strip().upper()] += 1
                continue
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
        res['excluded_currency'] = dict(res['excluded_currency'])
        out[rule['id']] = res
    return out


def _prepare(db, rules, date_from, date_to):
    E.ensure_packs_loaded()
    txs = load_transactions(db, date_from, date_to, E.max_lookback_days(rules), max_rows=MAX_ROWS)
    customers = load_customers(db, {t.get('customer_id') for t in txs})
    dq = data_quality(txs, known_customers=set(customers))
    dq['not_iso_total'] = count_not_iso(db)
    first_seen = load_first_seen(db, set(customers)) if E.prior_history_rules(rules) else {}
    ctx = E.Context(E.load_high_risk(db))
    ctx.first_seen = first_seen
    ctx.deadline = time.monotonic() + MAX_SECONDS
    return txs, customers, dq, ctx


def _summary(dq, txs, date_from, date_to, res=None):
    in_period = sum(1 for t in txs if t.get('_ts') and _in_period(t, date_from, date_to))
    cur, trunc = Counter(), False
    for r in (res or {}).values():
        for k, v in (r.get('excluded_currency') or {}).items():
            cur[k] = max(cur[k], v)
        trunc = trunc or bool(r.get('truncated'))
    return {'date_from': date_from, 'date_to': date_to, 'loaded': len(txs), 'evaluated': in_period,
            'excluded': len(dq['exclude']), 'quality': {k: v for k, v in dq.items() if k != 'exclude'},
            'excluded_currency': dict(cur), 'truncated': trunc}


def _replay(rules, txs, customers, ctx, date_from, date_to, params_by_rule, dq):
    return replay(rules, txs, customers, ctx, date_from, date_to, params_by_rule, dq['exclude'],
                  first_seen=getattr(ctx, 'first_seen', None), deadline=getattr(ctx, 'deadline', None))


def backtest(db, rules, date_from=None, date_to=None, params_by_rule=None):
    txs, customers, dq, ctx = _prepare(db, rules, date_from, date_to)
    res = _replay(rules, txs, customers, ctx, date_from, date_to, params_by_rule, dq)
    for r in res.values():
        r.pop('alert_tx_ids', None)
    return {'summary': _summary(dq, txs, date_from, date_to, res), 'rules': res}


def compare(db, rule, candidate_params, date_from=None, date_to=None, current_rule=None):
    """Current (active) behaviour vs a candidate set of parameters, same data, same period.
    `rule` = the candidate version (or the rule with candidate_params); `current_rule` = the
    version in force (defaults to `rule` with its stored parameters)."""
    current_rule = current_rule or rule
    both = [current_rule] if current_rule is rule else [current_rule, rule]
    txs, customers, dq, ctx = _prepare(db, both, date_from, date_to)
    cur = _replay([current_rule], txs, customers, ctx, date_from, date_to, None, dq)[current_rule['id']]
    cand_rule = dict(rule, id=-1)
    cand = _replay([cand_rule], txs, customers, ctx, date_from, date_to,
                   {-1: candidate_params or E.rule_params(rule)}, dq)[-1]
    if not cur.get('supported') or not cand.get('supported'):
        return {'summary': _summary(dq, txs, date_from, date_to), 'supported': False}
    a, b = cur.pop('alert_tx_ids'), cand.pop('alert_tx_ids')
    return {'summary': _summary(dq, txs, date_from, date_to, {1: cur, 2: cand}), 'supported': True,
            'current': cur, 'candidate': cand,
            'only_current': len(a - b), 'only_candidate': len(b - a), 'both': len(a & b)}


def sweep(db, rule, values, date_from=None, date_to=None, param='threshold'):
    """Alert volume of one rule for several values of one parameter (the tuning curve)."""
    txs, customers, dq, ctx = _prepare(db, [rule], date_from, date_to)
    base = E.rule_params(rule)
    rows = []
    for v in values:
        p = dict(base, **{param: v})
        r = _replay([dict(rule, id=-1)], txs, customers, ctx, date_from, date_to, {-1: p}, dq)[-1]
        if not r.get('supported'):
            return {'summary': _summary(dq, txs, date_from, date_to), 'supported': False, 'rows': []}
        rows.append({'value': v, 'alerts': r['alerts'], 'customers': r['customers'], 'hits': r['hits'],
                     'current': (p.get(param) == base.get(param)), 'truncated': r.get('truncated')})
        last = r
    summary = _summary(dq, txs, date_from, date_to, {1: last} if rows else None)
    summary['truncated'] = any(x.get('truncated') for x in rows)
    return {'summary': summary, 'supported': True, 'param': param, 'rows': rows}


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
        log.exception('TM: could not record the backtest run')
        try:
            db.rollback()
        except Exception:
            pass
