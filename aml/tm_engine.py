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
Transaction-monitoring rule engine (Phase 7, TM-G2 / G3).

One definition of every rule, used by live monitoring (aml/tm_service.py), the
backtest / simulation (aml/tm_backtest.py) and the scenario simulator, so a rule
behaves the same in all three.

Design
- Every window is anchored on the transaction's OWN date, never on "now": a
  file of past transactions uploaded today is judged as of when each one
  happened, and a backtest over last year gives what the rule would have done
  then. (Before this, an uploaded history fired the dormant-account rule on
  almost every customer because "90 days before now" contained nothing.)
- Only transactions up to the evaluated one count (no look-ahead).
- Parameters are data: the rule row's threshold_value / time_period_days plus a
  `parameters` JSON for the rest (counts, bands, tolerances, transaction types).
  RULE_SPECS documents each parameter with its unit and the comparison used, so
  the tuning page and the boundary tests read the same definition.
- Content packs add rules with register_rule(); the core imports no pack.

evaluate(rule, tx, history, customer, ctx) -> Hit | None   (pure, no database)
"""
import bisect
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CASH_TYPES = ('CASH_DEPOSIT', 'CASH_WITHDRAWAL')
IN_TYPES = ('TRANSFER_IN', 'CREDIT')
OUT_TYPES = ('TRANSFER_OUT', 'DEBIT')
INCOME_MONTHLY = {'<50K': 50000, '50K-100K': 100000, '100K-500K': 500000, '>500K': 2000000, 'UNDECLARED': 50000}

# Used only when the high_risk_countries table cannot be read.
FALLBACK_HIGH_RISK = {'Iran', 'North Korea', 'Myanmar'}


def N_(s):
    return s


@dataclass
class Hit:
    code: str
    description: str
    related_ids: list = field(default_factory=list)   # other transactions that make up the pattern
    value: float = None                               # the measured value compared with the threshold


# --------------------------------------------------------------------------- dates
_DATE_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d')


def parse_ts(v):
    """transactions.transaction_date is TEXT in several shapes -> naive datetime (None if unreadable)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    s = str(v).strip().replace('Z', '')
    s = re.sub(r'[+-]\d{2}:?\d{2}$', '', s) if len(s) > 19 else s
    s = s.split('.')[0]
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- history
class History:
    """Transactions in memory, indexed by customer and by card / counterparty account,
    each list sorted by (time, id). Built once for a backtest, or for one customer's
    look-back in live monitoring. Windows end AT the evaluated transaction (its
    position in the list), so later transactions are never seen."""

    def __init__(self, txs):
        by_customer, by_card = {}, {}
        for t in txs:
            ts = t.get('_ts') or parse_ts(t.get('transaction_date'))
            if ts is None:
                continue
            t['_ts'] = ts
            by_customer.setdefault(t.get('customer_id'), []).append(t)
            card = (t.get('counterparty_account') or '').strip()
            if len(card) >= 6:
                by_card.setdefault(card, []).append(t)
        self.by_customer = self._index(by_customer, '_ci')
        self.by_card = self._index(by_card, '_ki')

    @staticmethod
    def _index(groups, pos_key):
        out = {}
        for k, lst in groups.items():
            lst.sort(key=lambda x: (x['_ts'], x.get('id') or 0))
            keys, sums, run = [], [0.0], 0.0
            for i, x in enumerate(lst):
                x[pos_key] = i
                keys.append(x['_ts'])
                run += _num(x.get('amount'), 0.0) or 0.0
                sums.append(run)
            out[k] = (lst, keys, sums)
        return out

    @staticmethod
    def _bounds(entry, tx, pos_key, start):
        lst, keys, _ = entry
        hi = tx.get(pos_key)
        if hi is None or hi >= len(lst) or lst[hi] is not tx:
            hi = bisect.bisect_right(keys, tx['_ts']) - 1
        return bisect.bisect_left(keys, start), hi

    def customer_window(self, tx, start):
        entry = self.by_customer.get(tx.get('customer_id'))
        if not entry:
            return []
        lo, hi = self._bounds(entry, tx, '_ci', start)
        return entry[0][lo:hi + 1] if hi >= lo else []

    def customer_count(self, tx, start):
        entry = self.by_customer.get(tx.get('customer_id'))
        if not entry:
            return 0
        lo, hi = self._bounds(entry, tx, '_ci', start)
        return max(0, hi - lo + 1)

    def customer_sum(self, tx, start):
        entry = self.by_customer.get(tx.get('customer_id'))
        if not entry:
            return 0.0
        lo, hi = self._bounds(entry, tx, '_ci', start)
        return entry[2][hi + 1] - entry[2][lo] if hi >= lo else 0.0

    def customer_before(self, tx, before):
        """Any transaction of the customer strictly before `before`?"""
        entry = self.by_customer.get(tx.get('customer_id'))
        return bool(entry) and bisect.bisect_left(entry[1], before) > 0

    def card_window(self, tx, start):
        entry = self.by_card.get((tx.get('counterparty_account') or '').strip())
        if not entry:
            return []
        lo, hi = self._bounds(entry, tx, '_ki', start)
        return entry[0][lo:hi + 1] if hi >= lo else []


# --------------------------------------------------------------------------- parameters
def _num(v, default=None):
    try:
        return float(v) if v is not None and v != '' else default
    except (TypeError, ValueError):
        return default


def rule_params(rule):
    """Effective parameters of a rule row: spec defaults < `parameters` JSON < the
    threshold / period columns (the columns stay the main, visible knobs)."""
    spec = RULE_SPECS.get(rule.get('rule_code'), {})
    p = {k: d['default'] for k, d in spec.get('params', {}).items()}
    extra = rule.get('parameters')
    if isinstance(extra, str):
        try:
            extra = json.loads(extra or '{}')
        except ValueError:
            extra = {}
    if isinstance(extra, dict):
        p.update({k: v for k, v in extra.items() if v is not None})
    if rule.get('threshold_value') not in (None, ''):
        p['threshold'] = _num(rule['threshold_value'], p.get('threshold'))
    if rule.get('time_period_days') not in (None, '') and 'days' in spec.get('params', {}):
        p['days'] = int(rule['time_period_days'])
    return p


def _types(v, default):
    if isinstance(v, (list, tuple, set)):
        return tuple(str(x).upper() for x in v)
    if isinstance(v, str) and v.strip():
        return tuple(x.strip().upper() for x in v.split(',') if x.strip())
    return default


def _amt(t):
    return _num(t.get('amount'), 0.0) or 0.0


def _cmp(value, op, threshold):
    return value >= threshold if op == '>=' else value > threshold


# --------------------------------------------------------------------------- rules
# Each spec: params {name: {default, unit, label_en, label_ar}}, op = comparison of
# the measured value with `threshold`.  unit codes: amount (in the rule currency),
# count, ratio, days, hours, percent.
def _p(default, unit, en, ar):
    return {'default': default, 'unit': unit, 'label_en': en, 'label_ar': ar}


RULE_SPECS = {
    'TM001': {'op': '>=', 'measure': 'amount', 'params': {
        'threshold': _p(10000, 'amount', 'Cash amount', 'مبلغ النقدية'),
        'cash_types': _p(list(CASH_TYPES), 'types', 'Cash transaction types', 'أنواع العمليات النقدية')}},
    'TM002': {'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(9000, 'amount', 'Reporting threshold being avoided', 'الحد الذي يتم تجنبه'),
        'days': _p(3, 'days', 'Window', 'الفترة'),
        'min_count': _p(3, 'count', 'Cash transactions just below the threshold', 'عدد العمليات تحت الحد مباشرة'),
        'band_low': _p(0.7, 'ratio', 'Lower edge of the band (x threshold)', 'بداية النطاق (× الحد)'),
        'band_high': _p(1.0, 'ratio', 'Upper edge of the band (x threshold, excluded)', 'نهاية النطاق (× الحد، غير شاملة)'),
        'cash_types': _p(list(CASH_TYPES), 'types', 'Cash transaction types', 'أنواع العمليات النقدية')}},
    'TM003': {'op': '>', 'measure': 'count', 'params': {
        'threshold': _p(5, 'count', 'Transactions in the window', 'عدد العمليات في الفترة'),
        'hours': _p(24, 'hours', 'Window', 'الفترة')}},
    'TM004': {'op': 'in', 'measure': 'country', 'params': {}},
    'TM005': {'op': 'flag', 'measure': 'flag', 'params': {}},
    'TM006': {'op': '>=', 'measure': 'amount', 'params': {
        'threshold': _p(5000, 'amount', 'Amount after the quiet period', 'المبلغ بعد فترة الخمول'),
        'days': _p(90, 'days', 'Quiet period with no activity', 'فترة بدون أي حركة'),
        'require_prior_history': _p(True, 'bool', 'Customer had activity before the quiet period',
                                    'وجود حركة قبل فترة الخمول')}},
    'TM007': {'op': 'match', 'measure': 'amount', 'params': {
        'hours': _p(24, 'hours', 'Window between in and out', 'الفترة بين الوارد والصادر'),
        'tolerance_pct': _p(5, 'percent', 'Amount tolerance', 'هامش اختلاف المبلغ'),
        'in_types': _p(list(IN_TYPES), 'types', 'Incoming types', 'أنواع الوارد'),
        'out_types': _p(list(OUT_TYPES), 'types', 'Outgoing types', 'أنواع الصادر')}},
    'TM008': {'op': '>', 'measure': 'ratio', 'params': {
        'threshold': _p(3, 'ratio', 'Multiple of the expected monthly volume', 'مضاعف الحجم الشهري المتوقع'),
        'days': _p(30, 'days', 'Window', 'الفترة')}},
    'TM009': {'op': '>', 'measure': 'count', 'params': {
        'threshold': _p(3, 'count', 'Distinct currencies', 'عدد العملات المختلفة'),
        'days': _p(7, 'days', 'Window', 'الفترة')}},
    'TM010': {'op': '>', 'measure': 'count', 'params': {
        'threshold': _p(5, 'count', 'International transfers', 'عدد التحويلات الدولية'),
        'days': _p(7, 'days', 'Window', 'الفترة'),
        'home_countries': _p(['Egypt', 'EG', 'EGY', 'مصر'], 'types', 'Domestic country names (not counted)',
                             'أسماء الدولة المحلية (لا تُحسب)'),
        'transfer_types': _p(['TRANSFER_OUT', 'TRANSFER_IN', 'REMITTANCE'], 'types', 'Transfer types', 'أنواع التحويل')}},
    'TM011': {'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(3, 'count', 'Distinct merchants for one card', 'عدد التجار المختلفين للكارت'),
        'hours': _p(24, 'hours', 'Window', 'الفترة')}},
    'TM012': {'op': '>=', 'measure': 'amount', 'params': {
        'threshold': _p(50000, 'amount', 'Payment amount', 'مبلغ الدفع')}},
    'TM013': {'op': '>=', 'measure': 'amount', 'params': {
        'threshold': _p(100000, 'amount', 'Settlement amount', 'مبلغ التسوية')}},
    'TM014': {'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(3, 'count', 'Refunds in the window', 'عدد المرتجعات في الفترة'),
        'hours': _p(24, 'hours', 'Window', 'الفترة')}},
    'TM015': {'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(3, 'count', 'Round-number payments the same day', 'عدد المدفوعات بأرقام صحيحة في اليوم'),
        'round_unit': _p(1000, 'amount', 'Round unit', 'وحدة الرقم الصحيح')}},
    'TM016': {'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(5, 'count', 'Payments with one card in the window', 'عدد مدفوعات الكارت في الفترة'),
        'minutes': _p(60, 'minutes', 'Window', 'الفترة')}},
}

_EVALUATORS = {}


def register_rule(code, spec, fn):
    """Add a rule (used by content packs). fn(tx, hist, customer, p, ctx) -> Hit | None."""
    RULE_SPECS[code] = spec
    _EVALUATORS[code] = fn


def _rule(code):
    def deco(fn):
        _EVALUATORS[code] = fn
        return fn
    return deco


def _cur(tx):
    return tx.get('currency') or ''


@_rule('TM001')
def _tm001(tx, h, cust, p, ctx):
    if (tx.get('transaction_type') or '').upper() in _types(p.get('cash_types'), CASH_TYPES) and \
            _cmp(_amt(tx), '>=', p['threshold']):
        return Hit('TM001', f"Cash transaction of {_amt(tx):,.2f} {_cur(tx)} at or above the threshold of "
                            f"{p['threshold']:,.0f}", value=_amt(tx))


@_rule('TM002')
def _tm002(tx, h, cust, p, ctx):
    cash = _types(p.get('cash_types'), CASH_TYPES)
    if (tx.get('transaction_type') or '').upper() not in cash:
        return None
    lo, hi = float(p['band_low']) * p['threshold'], float(p['band_high']) * p['threshold']
    win = [t for t in h.customer_window(tx, tx['_ts'] - timedelta(days=int(p['days'])))
           if (t.get('transaction_type') or '').upper() in cash and lo <= _amt(t) < hi]
    if any(t is tx for t in win) and _cmp(len(win), '>=', int(p['min_count'])):
        total = sum(_amt(t) for t in win)
        return Hit('TM002', f"Possible structuring: {len(win)} cash transactions between {lo:,.0f} and {hi:,.0f} "
                            f"(total {total:,.2f}) within {int(p['days'])} days",
                   related_ids=[t.get('id') for t in win if t is not tx], value=len(win))


@_rule('TM003')
def _tm003(tx, h, cust, p, ctx):
    n = h.customer_count(tx, tx['_ts'] - timedelta(hours=float(p['hours'])))
    if _cmp(n, '>', p['threshold']):
        win = h.customer_window(tx, tx['_ts'] - timedelta(hours=float(p['hours'])))
        return Hit('TM003', f"High velocity: {n} transactions in {float(p['hours']):g} hours "
                            f"(threshold: more than {p['threshold']:g})",
                   related_ids=[t.get('id') for t in win if t is not tx][-50:], value=n)


@_rule('TM004')
def _tm004(tx, h, cust, p, ctx):
    country = (tx.get('counterparty_country') or '').strip()
    if country and country.lower() in ctx.high_risk:
        return Hit('TM004', f"Transaction with a high-risk country: {country}")


@_rule('TM005')
def _tm005(tx, h, cust, p, ctx):
    if tx.get('pep_involvement') or tx.get('sanctions_hit'):
        return Hit('TM005', f"Counterparty flagged: PEP={tx.get('pep_name') or ''}, "
                            f"Sanctions={tx.get('sanctions_list') or ''}")


@_rule('TM006')
def _tm006(tx, h, cust, p, ctx):
    if not _cmp(_amt(tx), '>=', p['threshold']):
        return None
    quiet_from = tx['_ts'] - timedelta(days=int(p['days']))
    if h.customer_count(tx, quiet_from) > 1:      # anything besides this transaction in the quiet period
        return None
    if p.get('require_prior_history', True) and not h.customer_before(tx, quiet_from):
        return None          # a new customer is not a dormant one
    return Hit('TM006', f"Dormant account: no activity for {int(p['days'])} days, then {_amt(tx):,.2f} {_cur(tx)}",
               value=_amt(tx))


@_rule('TM007')
def _tm007(tx, h, cust, p, ctx):
    t_type = (tx.get('transaction_type') or '').upper()
    ins, outs = _types(p.get('in_types'), IN_TYPES), _types(p.get('out_types'), OUT_TYPES)
    if t_type in ins:
        other = outs
    elif t_type in outs:
        other = ins
    else:
        return None
    tol = _amt(tx) * float(p['tolerance_pct']) / 100.0
    win = [t for t in h.customer_window(tx, tx['_ts'] - timedelta(hours=float(p['hours'])))
           if t is not tx and (t.get('transaction_type') or '').upper() in other and abs(_amt(t) - _amt(tx)) <= tol]
    if win and _amt(tx) > 0:
        return Hit('TM007', f"Rapid round trip: {_amt(tx):,.2f} {_cur(tx)} in and out within "
                            f"{float(p['hours']):g} hours", related_ids=[t.get('id') for t in win])


@_rule('TM008')
def _tm008(tx, h, cust, p, ctx):
    total = h.customer_sum(tx, tx['_ts'] - timedelta(days=int(p['days'])))
    expected = INCOME_MONTHLY.get((cust or {}).get('annual_income_range') or 'UNDECLARED', 50000) / 12.0
    expected *= int(p['days']) / 30.0
    ratio = total / expected if expected else 0
    if _cmp(ratio, '>', p['threshold']):
        return Hit('TM008', f"Volume of {total:,.2f} in {int(p['days'])} days is {ratio:.1f}x the expected "
                            f"{expected:,.2f} (threshold: more than {p['threshold']:g}x)", value=round(ratio, 2))


@_rule('TM009')
def _tm009(tx, h, cust, p, ctx):
    win = h.customer_window(tx, tx['_ts'] - timedelta(days=int(p['days'])))
    n = len({(t.get('currency') or '').upper() for t in win if t.get('currency')})
    if _cmp(n, '>', p['threshold']):
        return Hit('TM009', f"{n} different currencies in {int(p['days'])} days", value=n)


@_rule('TM010')
def _tm010(tx, h, cust, p, ctx):
    home = {str(c).strip().lower() for c in (p.get('home_countries') or [])}
    kinds = _types(p.get('transfer_types'), ('TRANSFER_OUT', 'TRANSFER_IN'))

    def intl(t):
        c = (t.get('counterparty_country') or '').strip().lower()
        return (t.get('transaction_type') or '').upper() in kinds and c and c not in home
    if not intl(tx):
        return None
    win = [t for t in h.customer_window(tx, tx['_ts'] - timedelta(days=int(p['days']))) if intl(t)]
    if _cmp(len(win), '>', p['threshold']):
        return Hit('TM010', f"{len(win)} international transfers in {int(p['days'])} days",
                   related_ids=[t.get('id') for t in win if t is not tx][-50:], value=len(win))


def _mask(pan):
    return pan[:6] + '***' + pan[-4:] if len(pan) > 10 else pan


@_rule('TM011')
def _tm011(tx, h, cust, p, ctx):
    pan = (tx.get('counterparty_account') or '').strip()
    if len(pan) < 6:
        return None
    win = h.card_window(tx, tx['_ts'] - timedelta(hours=float(p['hours'])))
    merchants = {(t.get('counterparty_name') or '').strip().lower() for t in win if (t.get('counterparty_name') or '').strip()}
    if _cmp(len(merchants), '>=', p['threshold']):
        return Hit('TM011', f"Card {_mask(pan)} used at {len(merchants)} different merchants within "
                            f"{float(p['hours']):g} hours", related_ids=[t.get('id') for t in win if t is not tx][-50:],
                   value=len(merchants))


@_rule('TM012')
def _tm012(tx, h, cust, p, ctx):
    if (tx.get('transaction_type') or '').upper() == 'PAYMENT' and _cmp(_amt(tx), '>=', p['threshold']):
        return Hit('TM012', f"Large payment of {_amt(tx):,.2f} {_cur(tx)} at "
                            f"{tx.get('counterparty_name') or 'unknown merchant'}", value=_amt(tx))


@_rule('TM013')
def _tm013(tx, h, cust, p, ctx):
    if (tx.get('transaction_type') or '').upper() == 'TRANSFER_IN' and _cmp(_amt(tx), '>=', p['threshold']):
        return Hit('TM013', f"Large settlement of {_amt(tx):,.2f} {_cur(tx)}", value=_amt(tx))


@_rule('TM014')
def _tm014(tx, h, cust, p, ctx):
    if (tx.get('transaction_type') or '').upper() != 'REFUND':
        return None
    win = [t for t in h.customer_window(tx, tx['_ts'] - timedelta(hours=float(p['hours'])))
           if (t.get('transaction_type') or '').upper() == 'REFUND']
    if _cmp(len(win), '>=', p['threshold']):
        return Hit('TM014', f"{len(win)} refunds within {float(p['hours']):g} hours",
                   related_ids=[t.get('id') for t in win if t is not tx], value=len(win))


@_rule('TM015')
def _tm015(tx, h, cust, p, ctx):
    unit = float(p['round_unit'])

    def rnd(t):
        a = _amt(t)
        return (t.get('transaction_type') or '').upper() == 'PAYMENT' and a >= unit and a % unit == 0
    if not rnd(tx):
        return None
    day = tx['_ts'].replace(hour=0, minute=0, second=0, microsecond=0)
    win = [t for t in h.customer_window(tx, day) if rnd(t)]
    if _cmp(len(win), '>=', p['threshold']):
        return Hit('TM015', f"{len(win)} round-number payments (multiples of {unit:,.0f}) the same day",
                   related_ids=[t.get('id') for t in win if t is not tx], value=len(win))


@_rule('TM016')
def _tm016(tx, h, cust, p, ctx):
    pan = (tx.get('counterparty_account') or '').strip()
    if len(pan) < 6 or (tx.get('transaction_type') or '').upper() != 'PAYMENT':
        return None
    win = [t for t in h.card_window(tx, tx['_ts'] - timedelta(minutes=float(p['minutes'])))
           if (t.get('transaction_type') or '').upper() == 'PAYMENT']
    if _cmp(len(win), '>=', p['threshold']):
        return Hit('TM016', f"Card {_mask(pan)} used {len(win)} times within {float(p['minutes']):g} minutes",
                   related_ids=[t.get('id') for t in win if t is not tx], value=len(win))


# --------------------------------------------------------------------------- context + entry points
class Context:
    """Lookups shared by all rules for one run (no per-transaction queries)."""

    def __init__(self, high_risk=None):
        self.high_risk = {c.lower() for c in (high_risk if high_risk is not None else FALLBACK_HIGH_RISK)}


def load_high_risk(db):
    """Active countries of the high_risk_countries table, by name, code and alias."""
    try:
        rows = db.execute("SELECT country_code, country_name, name_ar, aliases FROM high_risk_countries "
                          "WHERE COALESCE(is_active, 1) = 1").fetchall()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return set(FALLBACK_HIGH_RISK)
    out = set()
    for r in rows:
        for v in (r['country_code'], r['country_name'], r['name_ar']):
            if v:
                out.add(str(v).strip())
        for a in str(r['aliases'] or '').split('|'):
            if a.strip():
                out.add(a.strip())
    return out or set(FALLBACK_HIGH_RISK)


def ensure_packs_loaded():
    """Content packs register their rules on import; the core never names one."""
    try:
        from regcontrols.packs import discover
        discover()
    except Exception:
        pass


def supported(code):
    return code in _EVALUATORS


def evaluate(rule, tx, history, customer, ctx, params=None):
    """Evaluate one rule on one transaction. `tx` must be in `history`. Returns Hit or None."""
    fn = _EVALUATORS.get(rule.get('rule_code'))
    if fn is None:
        return None
    if tx.get('_ts') is None:
        tx['_ts'] = parse_ts(tx.get('transaction_date'))
        if tx['_ts'] is None:
            return None
    return fn(tx, history, customer, params if params is not None else rule_params(rule), ctx)


def max_lookback_days(rules):
    """Longest window any of these rules looks back (days), for loading history."""
    days = 1.0
    for r in rules:
        p = rule_params(r)
        days = max(days, float(p.get('days') or 0), float(p.get('hours') or 0) / 24.0,
                   float(p.get('minutes') or 0) / 1440.0)
        if r.get('rule_code') == 'TM006':
            days = max(days, float(p.get('days') or 90) + 365)   # prior history before the quiet period
    return days
