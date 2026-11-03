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
"""PSP typologies, registered with the core engine (aml/tm_engine.py) on import."""
from datetime import timedelta

from aml import tm_engine as E

CASH_IN = ['CASH_IN', 'CASH_DEPOSIT', 'DEPOSIT']
CASH_OUT = ['CASH_OUT', 'CASH_WITHDRAWAL', 'WITHDRAWAL']
FUNDS_IN = ['TRANSFER_IN', 'CREDIT', 'CASH_IN', 'CASH_DEPOSIT', 'DEPOSIT']
FUNDS_OUT = ['TRANSFER_OUT', 'DEBIT', 'CASH_OUT', 'CASH_WITHDRAWAL', 'WITHDRAWAL', 'TRANSFER', 'REMITTANCE']
_p = E._p


def _t(t):
    return (t.get('transaction_type') or '').upper()


def _party(t):
    return ((t.get('counterparty_account') or '').strip() or (t.get('counterparty_name') or '').strip().lower())


def psp01(tx, h, cust, p, ctx):
    """Cash-in structuring: several cash-ins just below the limit in a short period."""
    types = E._types(p.get('types'), tuple(CASH_IN))
    if _t(tx) not in types:
        return None
    lo, hi = float(p['band_low']) * p['threshold'], p['threshold']
    win = [t for t in h.customer_window(tx, tx['_ts'] - timedelta(days=int(p['days'])))
           if _t(t) in types and lo <= E._amt(t) < hi]
    if any(t is tx for t in win) and len(win) >= int(p['min_count']):
        return E.Hit('PSP01', f"{len(win)} cash-ins between {lo:,.0f} and {hi:,.0f} within {int(p['days'])} days "
                              f"(total {sum(E._amt(t) for t in win):,.2f})",
                     related_ids=[t.get('id') for t in win if t is not tx], value=len(win))


def psp02(tx, h, cust, p, ctx):
    """Pass-through wallet: money in and most of it out again within hours."""
    outs = E._types(p.get('out_types'), tuple(FUNDS_OUT))
    if _t(tx) not in outs:
        return None
    ins = E._types(p.get('in_types'), tuple(FUNDS_IN))
    win = h.customer_window(tx, tx['_ts'] - timedelta(hours=float(p['hours'])))
    tin = sum(E._amt(t) for t in win if _t(t) in ins)
    tout = sum(E._amt(t) for t in win if _t(t) in outs)
    if tin >= p['threshold'] and tout >= tin * float(p['out_pct']) / 100.0:
        return E.Hit('PSP02', f"{tin:,.2f} received and {tout:,.2f} sent out within {float(p['hours']):g} hours",
                     related_ids=[t.get('id') for t in win if t is not tx][-50:], value=round(tout / tin * 100, 1))


def _distinct(tx, h, p, types):
    win = [t for t in h.customer_window(tx, tx['_ts'] - timedelta(days=int(p['days']))) if _t(t) in types]
    return win, {_party(t) for t in win if _party(t)}


def psp03(tx, h, cust, p, ctx):
    """Many-to-one: funds from many different senders (collection / mule account)."""
    types = E._types(p.get('types'), tuple(FUNDS_IN))
    if _t(tx) not in types:
        return None
    win, parties = _distinct(tx, h, p, types)
    if len(parties) >= p['threshold']:
        return E.Hit('PSP03', f"Funds from {len(parties)} different senders within {int(p['days'])} days",
                     related_ids=[t.get('id') for t in win if t is not tx][-50:], value=len(parties))


def psp04(tx, h, cust, p, ctx):
    """One-to-many: funds sent to many different beneficiaries (distribution)."""
    types = E._types(p.get('types'), tuple(FUNDS_OUT))
    if _t(tx) not in types:
        return None
    win, parties = _distinct(tx, h, p, types)
    if len(parties) >= p['threshold']:
        return E.Hit('PSP04', f"Funds sent to {len(parties)} different beneficiaries within {int(p['days'])} days",
                     related_ids=[t.get('id') for t in win if t is not tx][-50:], value=len(parties))


def psp05(tx, h, cust, p, ctx):
    """Agent cash velocity: unusual number of cash operations at one agent / point in a day."""
    types = E._types(p.get('types'), tuple(CASH_IN + CASH_OUT))
    if _t(tx) not in types:
        return None
    win = [t for t in h.customer_window(tx, tx['_ts'] - timedelta(hours=float(p['hours']))) if _t(t) in types]
    if len(win) >= p['threshold']:
        return E.Hit('PSP05', f"{len(win)} cash operations within {float(p['hours']):g} hours "
                              f"(total {sum(E._amt(t) for t in win):,.2f})",
                     related_ids=[t.get('id') for t in win if t is not tx][-50:], value=len(win))


SPECS = {
    'PSP01': ({'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(10000, 'amount', 'Cash-in limit being avoided', 'حد الإيداع اللي بيتم تجنبه'),
        'days': _p(3, 'days', 'Window', 'الفترة'),
        'min_count': _p(3, 'count', 'Cash-ins just below the limit', 'عدد الإيداعات تحت الحد مباشرة'),
        'band_low': _p(0.7, 'ratio', 'Lower edge of the band (x limit)', 'بداية النطاق (× الحد)'),
        'types': _p(CASH_IN, 'types', 'Cash-in types', 'أنواع الإيداع النقدي')}}, psp01),
    'PSP02': ({'op': '>=', 'measure': 'percent', 'params': {
        'threshold': _p(20000, 'amount', 'Minimum amount received', 'أقل مبلغ وارد'),
        'hours': _p(48, 'hours', 'Window', 'الفترة'),
        'out_pct': _p(80, 'percent', 'Share sent out again', 'نسبة اللي خرج تاني'),
        'in_types': _p(FUNDS_IN, 'types', 'Incoming types', 'أنواع الوارد'),
        'out_types': _p(FUNDS_OUT, 'types', 'Outgoing types', 'أنواع الصادر')}}, psp02),
    'PSP03': ({'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(10, 'count', 'Different senders', 'عدد المرسلين المختلفين'),
        'days': _p(7, 'days', 'Window', 'الفترة'),
        'types': _p(FUNDS_IN, 'types', 'Incoming types', 'أنواع الوارد')}}, psp03),
    'PSP04': ({'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(10, 'count', 'Different beneficiaries', 'عدد المستفيدين المختلفين'),
        'days': _p(7, 'days', 'Window', 'الفترة'),
        'types': _p(FUNDS_OUT, 'types', 'Outgoing types', 'أنواع الصادر')}}, psp04),
    'PSP05': ({'op': '>=', 'measure': 'count', 'params': {
        'threshold': _p(50, 'count', 'Cash operations', 'عدد عمليات الكاش'),
        'hours': _p(24, 'hours', 'Window', 'الفترة'),
        'types': _p(CASH_IN + CASH_OUT, 'types', 'Cash types', 'أنواع الكاش')}}, psp05),
}

for _code, (_spec, _fn) in SPECS.items():
    E.register_rule(_code, _spec, _fn)

RULES = [
    {'rule_code': 'PSP01', 'rule_name': 'Cash-in structuring below the limit', 'rule_name_ar': 'تجزئة الإيداع النقدي تحت الحد',
     'rule_description': 'Several cash-ins just below the cash-in limit within a few days.',
     'rule_category': 'Cash', 'rule_type': 'PATTERN', 'threshold_value': 10000, 'threshold_currency': 'EGP',
     'time_period_days': 3, 'severity': 'HIGH', 'parameters': {'min_count': 3, 'band_low': 0.7}},
    {'rule_code': 'PSP02', 'rule_name': 'Pass-through wallet (rapid in and out)', 'rule_name_ar': 'محفظة تمرير (دخول وخروج سريع)',
     'rule_description': 'Funds received and most of them sent out again within hours.',
     'rule_category': 'Pattern', 'rule_type': 'PATTERN', 'threshold_value': 20000, 'threshold_currency': 'EGP',
     'time_period_days': 2, 'severity': 'HIGH', 'parameters': {'hours': 48, 'out_pct': 80}},
    {'rule_code': 'PSP03', 'rule_name': 'Many senders to one account', 'rule_name_ar': 'مرسلين كتير لحساب واحد',
     'rule_description': 'Funds from many different senders within a week (collection or mule account).',
     'rule_category': 'Transfer', 'rule_type': 'PATTERN', 'threshold_value': 10, 'time_period_days': 7,
     'severity': 'MEDIUM'},
    {'rule_code': 'PSP04', 'rule_name': 'One account to many beneficiaries', 'rule_name_ar': 'حساب واحد لمستفيدين كتير',
     'rule_description': 'Funds sent to many different beneficiaries within a week.',
     'rule_category': 'Transfer', 'rule_type': 'PATTERN', 'threshold_value': 10, 'time_period_days': 7,
     'severity': 'MEDIUM'},
    {'rule_code': 'PSP05', 'rule_name': 'Agent cash velocity', 'rule_name_ar': 'سرعة عمليات الكاش عند الوكيل',
     'rule_description': 'Unusual number of cash operations at one agent or point within a day.',
     'rule_category': 'Cash', 'rule_type': 'VELOCITY', 'threshold_value': 50, 'time_period_days': 1,
     'severity': 'MEDIUM', 'parameters': {'hours': 24}},
]
