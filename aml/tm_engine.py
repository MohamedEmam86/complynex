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
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

CASH_TYPES = ('CASH_DEPOSIT', 'CASH_WITHDRAWAL')
IN_TYPES = ('TRANSFER_IN', 'CREDIT')
OUT_TYPES = ('TRANSFER_OUT', 'DEBIT')
INCOME_MONTHLY = {'<50K': 50000, '50K-100K': 100000, '100K-500K': 500000, '>500K': 2000000, 'UNDECLARED': 50000}

# Refunds / reversals may be stored signed (negative): their size is what the rules use.
REVERSAL_TYPES = ('REFUND', 'REVERSAL', 'CHARGEBACK')


def _fallback_high_risk():
    """The built-in country list of the customer risk model (utils/aml_risk.py), used
    only when the high_risk_countries table cannot be read."""
    try:
        from utils.aml_risk import DEFAULT_MODEL
        return {str(c).strip() for c in DEFAULT_MODEL['country']['builtin_list'] if str(c).strip()}
    except Exception:          # pragma: no cover - the module is part of the core
        return {'IRAN', 'NORTH KOREA', 'SYRIA', 'RUSSIA', 'MYANMAR'}


FALLBACK_HIGH_RISK = _fallback_high_risk()


def N_(s):
    return s


@dataclass
class Hit:
    code: str
    description: str
    related_ids: list = field(default_factory=list)   # other transactions that make up the pattern
    value: float = None                               # the measured value compared with the threshold


# --------------------------------------------------------------------------- dates
# Day-first for the slash / dash forms (DD/MM/YYYY, DD-MM-YYYY), as written in Egypt and
# most of the world; uploads are normalised to ISO by the upload screen, these cover
# the API and other feeds that store the text they receive.
_DATE_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d',
                 '%Y/%m/%d %H:%M:%S', '%Y/%m/%d %H:%M', '%Y/%m/%d',
                 '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y',
                 '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M', '%d-%m-%Y')
_TZ_SUFFIX = re.compile(r'(?<=\d{2}:\d{2})(?::\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})$')
_ISO_PREFIX = re.compile(r'^\d{4}-\d{2}-\d{2}')
_LOCAL_TZ = None


def _local_tz():
    """Zone that naive transaction dates are in (TM_LOCAL_TZ, default Africa/Cairo).
    A date sent with an offset is converted to it, so '10:00Z' and '12:00+02:00'
    land on the same moment as a naive local '12:00'."""
    global _LOCAL_TZ
    if _LOCAL_TZ is None:
        try:
            from zoneinfo import ZoneInfo
            _LOCAL_TZ = ZoneInfo(os.environ.get('TM_LOCAL_TZ') or 'Africa/Cairo')
        except Exception:
            from datetime import timezone as _tz
            _LOCAL_TZ = _tz(timedelta(hours=2))
    return _LOCAL_TZ


def _to_local_naive(dt):
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(_local_tz()).replace(tzinfo=None)


def parse_ts(v):
    """transactions.transaction_date is TEXT in several shapes -> naive local datetime (None if unreadable)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return _to_local_naive(v)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip()
    if not s:
        return None
    m = _TZ_SUFFIX.search(s)
    if m:
        off = m.group(1)
        base = s[:m.start(1)].split('.')[0]
        try:
            iso = base.replace(' ', 'T') + ('+00:00' if off == 'Z' else
                                             (off if ':' in off else off[:3] + ':' + off[3:]))
            return _to_local_naive(datetime.fromisoformat(iso))
        except ValueError:
            s = base
    s = s.split('.')[0] if re.match(r'^\d{4}-', s) else s
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def is_iso_date(v):
    """Stored as YYYY-MM-DD...: the database date-range queries (look-back) can find it."""
    return bool(v) and bool(_ISO_PREFIX.match(str(v).strip()))


# --------------------------------------------------------------------------- history
class History:
    """Transactions in memory, indexed by customer and by card / counterparty account,
    each list sorted by (time, id). Built once for a backtest, or for one customer's
    look-back in live monitoring. Windows end AT the evaluated transaction (its
    position in the list), so later transactions are never seen.

    first_seen {customer_id: datetime} = the customer's earliest transaction known to
    the caller (the database), for "had activity before X" checks that reach further
    back than the loaded look-back (the dormant-account rule).
    prior {(customer_id, date): bool} = "any transaction on a day before `date`",
    already asked of the database (live monitoring: one EXISTS query); the loaded
    look-back covers that day itself."""

    def __init__(self, txs, first_seen=None, prior=None, parent=None):
        by_customer, by_card = {}, {}
        self.txs = []
        for t in txs:
            ts = t.get('_ts') or parse_ts(t.get('transaction_date'))
            if ts is None:
                continue
            t['_ts'] = ts
            self.txs.append(t)
            by_customer.setdefault(t.get('customer_id'), []).append(t)
            card = (t.get('counterparty_account') or '').strip()
            if len(card) >= 6:
                by_card.setdefault(card, []).append(t)
        self._pos = {}                       # (index name, id(tx)) -> position; never written on the tx
        self.by_customer = self._index(by_customer, 'c')
        self.by_card = self._index(by_card, 'k')
        self.first_seen = dict(first_seen or {})
        self.prior = dict(prior or {})
        self.parent = parent                 # the all-currencies history of a currency view
        self._views, self._sliding, self._sums = {}, {}, {}

    @property
    def all(self):
        """The history with every currency (activity checks are not per currency)."""
        return self.parent or self

    def _index(self, groups, name):
        out = {}
        for k, lst in groups.items():
            lst.sort(key=lambda x: (x['_ts'], x.get('id') or 0))
            keys, sums, run = [], [0.0], 0.0
            for i, x in enumerate(lst):
                self._pos[(name, id(x))] = i
                keys.append(x['_ts'])
                run += _amt(x)
                sums.append(run)
            out[k] = (lst, keys, sums)
        return out

    def _bounds(self, entry, tx, name, start):
        lst, keys, _ = entry
        hi = self._pos.get((name, id(tx)))
        if hi is None or hi >= len(lst) or lst[hi] is not tx:
            hi = bisect.bisect_right(keys, tx['_ts']) - 1
        return bisect.bisect_left(keys, start), hi

    def customer_window(self, tx, start):
        entry = self.by_customer.get(tx.get('customer_id'))
        if not entry:
            return []
        lo, hi = self._bounds(entry, tx, 'c', start)
        return entry[0][lo:hi + 1] if hi >= lo else []

    def customer_count(self, tx, start):
        entry = self.by_customer.get(tx.get('customer_id'))
        if not entry:
            return 0
        lo, hi = self._bounds(entry, tx, 'c', start)
        return max(0, hi - lo + 1)

    def customer_sum(self, tx, start):
        entry = self.by_customer.get(tx.get('customer_id'))
        if not entry:
            return 0.0
        lo, hi = self._bounds(entry, tx, 'c', start)
        return entry[2][hi + 1] - entry[2][lo] if hi >= lo else 0.0

    def customer_before(self, tx, before):
        """Any transaction of the customer strictly before `before`?"""
        cust = tx.get('customer_id')
        entry = self.by_customer.get(cust)
        if entry and bisect.bisect_left(entry[1], before) > 0:
            return True
        fs = self.first_seen.get(cust)
        if fs is not None and fs < before:
            return True
        return bool(self.prior.get((cust, before.date())))

    def card_window(self, tx, start):
        entry = self.by_card.get((tx.get('counterparty_account') or '').strip())
        if not entry:
            return []
        lo, hi = self._bounds(entry, tx, 'k', start)
        return entry[0][lo:hi + 1] if hi >= lo else []

    # ---- running aggregates (no per-transaction copy of the window) -----------------
    def filtered_sum(self, tx, start, key, pred):
        """Sum of the amounts of the customer's window transactions matching pred.
        Prefix sums are built once per (key, customer); `key` identifies pred."""
        cust = tx.get('customer_id')
        entry = self.by_customer.get(cust)
        if not entry:
            return 0.0
        pre = self._sums.get((key, cust))
        if pre is None:
            pre, run = [0.0], 0.0
            for x in entry[0]:
                run += _amt(x) if pred(x) else 0.0
                pre.append(run)
            self._sums[(key, cust)] = pre
        lo, hi = self._bounds(entry, tx, 'c', start)
        return pre[hi + 1] - pre[lo] if hi >= lo else 0.0

    def distinct_count(self, tx, start, key, item):
        """Number of distinct item(t) (None = not counted) in the customer's window.
        A sliding window per (key, customer): transactions evaluated in time order (a
        backtest) cost O(1) each; any other order resets the window."""
        cust = tx.get('customer_id')
        entry = self.by_customer.get(cust)
        if not entry:
            return 0
        lst = entry[0]
        lo, hi = self._bounds(entry, tx, 'c', start)
        st = self._sliding.get((key, cust))
        if st is None or hi < st[1] or lo < st[0]:
            st = [lo, lo - 1, Counter()]
        a, b, cnt = st
        for i in range(b + 1, hi + 1):
            v = item(lst[i])
            if v is not None:
                cnt[v] += 1
        for i in range(a, min(lo, hi + 1)):        # every index a..hi is counted at this point
            v = item(lst[i])
            if v is not None:
                cnt[v] -= 1
                if cnt[v] <= 0:
                    del cnt[v]
        st[0], st[1] = lo, max(hi, lo - 1)
        self._sliding[(key, cust)] = st
        return len(cnt)

    # ---- currency views ------------------------------------------------------------
    def for_currency(self, currency):
        """The same history limited to one currency (rows without a currency are kept:
        they are assumed to be in it, and reported by the data-quality check)."""
        cur = (currency or '').strip().upper()
        if not cur or self.parent is not None:
            return self
        v = self._views.get(cur)
        if v is None:
            v = History([t for t in self.txs if (t.get('currency') or '').strip().upper() in ('', cur)],
                        first_seen=self.first_seen, prior=self.prior, parent=self)
            self._views[cur] = v
        return v


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
    """Amount the rules use: refunds / reversals stored signed (negative) count by size."""
    a = _num(t.get('amount'), 0.0) or 0.0
    if a < 0 and (t.get('transaction_type') or '').upper() in REVERSAL_TYPES:
        return -a
    return a


def _fmt(v):
    """A parameter for a message: 2000000 -> '2,000,000', 1.5 -> '1.5' (never 2e+06)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f'{f:,.0f}' if f == int(f) else f'{f:,.2f}'.rstrip('0').rstrip('.')


def _cmp(value, op, threshold):
    return value >= threshold if op == '>=' else value > threshold


# --------------------------------------------------------------------------- rules
# Each spec: params {name: {default, unit, label_en, label_ar}}, op = comparison of
# the measured value with `threshold`.  unit codes: amount (in the rule currency),
# count, ratio, days, hours, percent.
# Optional keys (defaults in brackets):
#   needs    what the rule needs on the evaluated transaction: 'date' (a time window)
#            and/or 'amount' [('date', 'amount')]. A rule that needs no date still runs
#            on a transaction whose date cannot be read.
#   scope    'card' when the windows follow the card / counterparty account ['customer']
#   currency True when amounts are compared, so only transactions in the rule's
#            threshold_currency count [True when a parameter is an amount, or the
#            measure is an amount or a ratio of amounts]
#   prior_history  True when the rule asks "any activity before the window" [False]
def _p(default, unit, en, ar):
    return {'default': default, 'unit': unit, 'label_en': en, 'label_ar': ar}


RULE_SPECS = {
    'TM001': {'op': '>=', 'measure': 'amount', 'needs': ('amount',), 'params': {
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
    'TM004': {'op': 'in', 'measure': 'country', 'needs': (), 'params': {}},
    'TM005': {'op': 'flag', 'measure': 'flag', 'needs': (), 'params': {}},
    'TM006': {'op': '>=', 'measure': 'amount', 'prior_history': True, 'params': {
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
    'TM011': {'op': '>=', 'measure': 'count', 'scope': 'card', 'params': {
        'threshold': _p(3, 'count', 'Distinct merchants for one card', 'عدد التجار المختلفين للكارت'),
        'hours': _p(24, 'hours', 'Window', 'الفترة')}},
    'TM012': {'op': '>=', 'measure': 'amount', 'needs': ('amount',), 'params': {
        'threshold': _p(50000, 'amount', 'Payment amount', 'مبلغ الدفع')}},
    'TM013': {'op': '>=', 'measure': 'amount', 'needs': ('amount',), 'params': {
        'threshold': _p(100000, 'amount', 'Settlement amount', 'مبلغ التسوية')}},
    'TM014': {'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(3, 'count', 'Refunds in the window', 'عدد المرتجعات في الفترة'),
        'hours': _p(24, 'hours', 'Window', 'الفترة')}},
    'TM015': {'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(3, 'count', 'Round-number payments the same day', 'عدد المدفوعات بأرقام صحيحة في اليوم'),
        'round_unit': _p(1000, 'amount', 'Round unit', 'وحدة الرقم الصحيح')}},
    'TM016': {'op': '>=', 'measure': 'count', 'scope': 'card', 'params': {
        'threshold': _p(5, 'count', 'Payments with one card in the window', 'عدد مدفوعات الكارت في الفترة'),
        'minutes': _p(60, 'minutes', 'Window', 'الفترة')}},
}

_EVALUATORS = {}


def spec_of(code):
    return RULE_SPECS.get(code) or {}


def needs(code):
    """What the rule needs on the evaluated transaction: subset of {'date', 'amount'}."""
    n = spec_of(code).get('needs')
    return set(n) if n is not None else {'date', 'amount'}


def is_card_rule(code):
    return spec_of(code).get('scope') == 'card'


def is_currency_rule(code):
    """Amounts are compared: only transactions in the rule currency count."""
    spec = spec_of(code)
    if 'currency' in spec:
        return bool(spec['currency'])
    return (spec.get('measure') in ('amount', 'ratio') or
            any(d.get('unit') == 'amount' for d in spec.get('params', {}).values()))


def rule_currency(rule):
    """Currency a rule's amounts are in (None = no filter)."""
    if not is_currency_rule(rule.get('rule_code')):
        return None
    return (rule.get('threshold_currency') or '').strip().upper() or None


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
                            f"{_fmt(p['threshold'])}", value=_amt(tx))


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
        return Hit('TM003', f"High velocity: {n} transactions in {_fmt(p['hours'])} hours "
                            f"(threshold: more than {_fmt(p['threshold'])})",
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


def quiet_start(ts, p):
    """Start of the dormant rule's quiet period."""
    return ts - timedelta(days=int(p['days']))


@_rule('TM006')
def _tm006(tx, h, cust, p, ctx):
    if not _cmp(_amt(tx), '>=', p['threshold']):
        return None
    quiet_from = quiet_start(tx['_ts'], p)
    act = h.all                                    # activity in any currency breaks the quiet period
    if act.customer_count(tx, quiet_from) > 1:     # anything besides this transaction in the quiet period
        return None
    if p.get('require_prior_history', True) and not act.customer_before(tx, quiet_from):
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
                            f"{_fmt(p['hours'])} hours", related_ids=[t.get('id') for t in win])


@_rule('TM008')
def _tm008(tx, h, cust, p, ctx):
    total = h.customer_sum(tx, tx['_ts'] - timedelta(days=int(p['days'])))
    expected = INCOME_MONTHLY.get((cust or {}).get('annual_income_range') or 'UNDECLARED', 50000) / 12.0
    expected *= int(p['days']) / 30.0
    ratio = total / expected if expected else 0
    if _cmp(ratio, '>', p['threshold']):
        return Hit('TM008', f"Volume of {total:,.2f} in {int(p['days'])} days is {ratio:.1f}x the expected "
                            f"{expected:,.2f} (threshold: more than {_fmt(p['threshold'])}x)", value=round(ratio, 2))


@_rule('TM009')
def _tm009(tx, h, cust, p, ctx):
    n = h.distinct_count(tx, tx['_ts'] - timedelta(days=int(p['days'])), ('TM009', int(p['days'])),
                         lambda t: (t.get('currency') or '').strip().upper() or None)
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
                            f"{_fmt(p['hours'])} hours", related_ids=[t.get('id') for t in win if t is not tx][-50:],
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
        return Hit('TM014', f"{len(win)} refunds within {_fmt(p['hours'])} hours",
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
        return Hit('TM016', f"Card {_mask(pan)} used {len(win)} times within {_fmt(p['minutes'])} minutes",
                   related_ids=[t.get('id') for t in win if t is not tx], value=len(win))


# --------------------------------------------------------------------------- context + entry points
class Context:
    """Lookups shared by all rules for one run (no per-transaction queries)."""

    def __init__(self, high_risk=None):
        self.high_risk = {c.lower() for c in (high_risk if high_risk is not None else FALLBACK_HIGH_RISK)}
        self.first_seen = None       # backtest: earliest transaction per customer (dormant rule)
        self.deadline = None         # backtest: time.monotonic() after which a run stops


_HR_CACHE = {'at': 0.0, 'value': None}
HIGH_RISK_TTL = 300          # seconds a process keeps the list (one query per batch, not per transaction)


def load_high_risk(db, fresh=False):
    """Active countries of the high_risk_countries table, by name, code and alias.
    Cached per process for HIGH_RISK_TTL seconds. Read inside a SAVEPOINT so a failure
    never aborts the caller's transaction; on failure the built-in list of the risk
    model is used and the failure is logged as an error (TM004 runs on less)."""
    now = time.monotonic()
    if not fresh and _HR_CACHE['value'] is not None and now - _HR_CACHE['at'] < HIGH_RISK_TTL:
        return set(_HR_CACHE['value'])
    try:
        db.execute("SAVEPOINT tm_high_risk")
    except Exception:
        log.exception('TM: could not open a savepoint to read high_risk_countries')
        return set(FALLBACK_HIGH_RISK)
    try:
        rows = db.execute("SELECT country_code, country_name, name_ar, aliases FROM high_risk_countries "
                          "WHERE COALESCE(is_active, 1) = 1").fetchall()
        db.execute("RELEASE SAVEPOINT tm_high_risk")
    except Exception:
        log.exception('TM: high_risk_countries cannot be read; the built-in list of %d countries is used',
                      len(FALLBACK_HIGH_RISK))
        try:
            db.execute("ROLLBACK TO SAVEPOINT tm_high_risk")
            db.execute("RELEASE SAVEPOINT tm_high_risk")
        except Exception:
            log.exception('TM: could not roll back to the savepoint')
        return set(FALLBACK_HIGH_RISK)
    out = set()
    for r in rows:
        for v in (r['country_code'], r['country_name'], r['name_ar']):
            if v:
                out.add(str(v).strip())
        for a in str(r['aliases'] or '').split('|'):
            if a.strip():
                out.add(a.strip())
    if not out:
        log.error('TM: high_risk_countries has no active country; the built-in list is used')
        out = set(FALLBACK_HIGH_RISK)
    _HR_CACHE.update(at=now, value=frozenset(out))
    return set(out)


PACK_LOAD_ERRORS = []        # names of content packs that failed to load (shown on the rule list)
_PACKS = {'ok': False, 'tried': None}
PACK_RETRY_SECONDS = 300


def ensure_packs_loaded():
    """Content packs register their rules on import; the core never names one.
    A pack that fails to load is logged and listed in PACK_LOAD_ERRORS."""
    now = time.monotonic()
    if _PACKS['ok'] or (_PACKS['tried'] is not None and now - _PACKS['tried'] < PACK_RETRY_SECONDS):
        return PACK_LOAD_ERRORS
    _PACKS['tried'] = now
    errors = []
    try:
        from regcontrols.packs import discover
        discover()
    except Exception as e:
        log.exception('TM: content packs could not be discovered')
        errors.append(f'discovery: {e.__class__.__name__}')
    try:
        import pkgutil
        import sys
        import packs as packs_pkg
        for mod in pkgutil.iter_modules(packs_pkg.__path__):
            if mod.ispkg and f'packs.{mod.name}' not in sys.modules:
                log.error('TM: content pack %s is not loaded (import failed); its rules will not run', mod.name)
                errors.append(mod.name)
    except ImportError:
        pass
    except Exception:
        log.exception('TM: could not list content packs')
    PACK_LOAD_ERRORS[:] = errors
    _PACKS['ok'] = not errors
    return PACK_LOAD_ERRORS


def supported(code):
    return code in _EVALUATORS


class _Empty(History):
    def __init__(self):
        super().__init__([])


def evaluate(rule, tx, history, customer, ctx, params=None):
    """Evaluate one rule on one transaction. `tx` must be in `history` (unless its date
    cannot be read: then only rules that need no date run). Returns Hit or None.
    Amount rules only see transactions in the rule currency (rule_currency)."""
    code = rule.get('rule_code')
    fn = _EVALUATORS.get(code)
    if fn is None:
        return None
    need = needs(code)
    if tx.get('_ts') is None:
        tx['_ts'] = parse_ts(tx.get('transaction_date'))
    if tx['_ts'] is None:
        if 'date' in need:
            return None
        history = _Empty()
    cur = rule_currency(rule)
    if cur:
        tc = (tx.get('currency') or '').strip().upper()
        if tc and tc != cur:
            return None                     # reported as excluded by currency, never compared
        if history is not None:
            history = history.for_currency(cur)
    return fn(tx, history, customer, params if params is not None else rule_params(rule), ctx)


def excluded_by_currency(rule, tx):
    cur = rule_currency(rule)
    tc = (tx.get('currency') or '').strip().upper()
    return bool(cur and tc and tc != cur)


def _rule_days(r):
    p = rule_params(r)
    return max(float(p.get('days') or 0), float(p.get('hours') or 0) / 24.0, float(p.get('minutes') or 0) / 1440.0)


def max_lookback_days(rules):
    """Longest window any of these rules looks back (days), for loading history.
    The dormant rule's "activity before the quiet period" is NOT loaded: it is one
    question to the database (History.first_seen / prior)."""
    days = 1.0
    for r in rules:
        days = max(days, _rule_days(r))
    return days


def card_lookback_days(rules):
    """Longest window of the card rules among these (0 = no card rule)."""
    return max([_rule_days(r) for r in rules if is_card_rule(r.get('rule_code'))] or [0.0])


def prior_history_rules(rules):
    return [r for r in rules if spec_of(r.get('rule_code')).get('prior_history')]
