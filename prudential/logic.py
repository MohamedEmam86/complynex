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
Pure decision logic for the prudential / governance / financial-reporting
registers — no Flask, no database, no regulator-specific values. Every
threshold (minimum capital, leverage ceiling, confirmation age, vacancy days,
tolerance …) arrives as an argument read by the caller from the regcontrols
parameter registry.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal


def _t(msg, **kw):
    """Translated issue text when a request is active (pages), plain English otherwise (tests, jobs)."""
    try:
        from flask import has_request_context
        if has_request_context():
            from flask_babel import gettext
            return gettext(msg, **kw)
    except Exception:
        pass
    return msg % kw if kw else msg

CAPITAL_TYPES = ('authorised', 'issued', 'paid_up', 'registered')


def _d(v):
    return None if v is None else Decimal(str(v))


# --------------------------------------------------------------------------
# Capital
# --------------------------------------------------------------------------

def capital_levels(events, as_of=None):
    """Latest level of each capital figure on `as_of`: {type: {'amount', 'date', 'id'}}."""
    as_of = as_of or date.today()
    out = {}
    for e in sorted(events, key=lambda e: (e['effective_date'], e.get('id') or 0)):
        if e['effective_date'] <= as_of:
            out[e['capital_type']] = {'amount': _d(e['amount']), 'date': e['effective_date'], 'id': e.get('id')}
    return out


def capital_issues(levels, minimum=None):
    """Problems with the capital position. minimum: required paid-up capital (or None if not set)."""
    out = []
    paid = (levels.get('paid_up') or {}).get('amount')
    if paid is None:
        out.append(('no_paid_up', _t('no paid-up capital recorded')))
        return out
    if minimum is not None and paid < _d(minimum):
        out.append(('below_minimum', _t('paid-up capital %(paid)s below the minimum %(minimum)s', paid=f'{paid:,.0f}', minimum=f'{_d(minimum):,.0f}')))
    reg = (levels.get('registered') or {}).get('amount')
    if reg is not None and reg < paid:
        out.append(('not_registered', _t('paid-up %(paid)s not yet registered (registered %(reg)s)', paid=f'{paid:,.0f}', reg=f'{reg:,.0f}')))
    issued = (levels.get('issued') or {}).get('amount')
    if issued is not None and paid > issued:
        out.append(('paid_above_issued', _t('paid-up capital exceeds issued capital')))
    auth = (levels.get('authorised') or {}).get('amount')
    if auth is not None and issued is not None and issued > auth:
        out.append(('issued_above_authorised', _t('issued capital exceeds authorised capital')))
    return out


# --------------------------------------------------------------------------
# Regulatory deadlines
# --------------------------------------------------------------------------

def days_left(due, today=None):
    return (due - (today or date.today())).days


def deadline_state(dl, today=None, thresholds=(60, 30, 7)):
    """'met' | 'overdue' | 'due_soon' | 'ok' for one deadline row (status/due_date)."""
    if dl['status'] in ('met', 'cancelled'):
        return dl['status']
    left = days_left(dl['due_date'], today)
    if left < 0:
        return 'overdue'
    if thresholds and left <= max(thresholds):
        return 'due_soon'
    return 'ok'


def thresholds_to_send(left, thresholds, already):
    """Countdown thresholds (days) newly crossed and not yet notified."""
    return sorted((t for t in thresholds or [] if left <= t and t not in (already or [])), reverse=True)


def needs_board_escalation(dl, today=None, thresholds=(60, 30, 7)):
    """Escalate to the board when overdue or inside the last countdown threshold."""
    if dl['status'] in ('met', 'cancelled') or dl.get('board_escalated_at'):
        return False
    left = days_left(dl['due_date'], today)
    return left < 0 or (bool(thresholds) and left <= min(thresholds))


# --------------------------------------------------------------------------
# Solvency
# --------------------------------------------------------------------------

def ratios(p):
    """Derived figures for one financial period."""
    eq, liab, assets = _d(p.get('equity')), _d(p.get('total_liabilities')), _d(p.get('total_assets'))
    if eq is None and assets is not None and liab is not None:
        eq = assets - liab
    lev = (liab / eq).quantize(Decimal('0.01')) if (liab is not None and eq and eq > 0) else None
    eq_assets = (100 * eq / assets).quantize(Decimal('0.01')) if (eq is not None and assets) else None
    return {'equity': eq, 'leverage': lev, 'equity_to_assets_pct': eq_assets,
            'capital_base': _d(p.get('capital_base')), 'negative_equity': eq is not None and eq < 0}


def solvency_breaches(p, max_leverage=None, min_equity=None, min_capital_base=None):
    """[(metric, value, limit, severity)] for one period."""
    r = ratios(p)
    out = []
    if r['equity'] is None:
        return [('equity', None, None, 'high')]
    if r['negative_equity']:
        out.append(('equity', r['equity'], Decimal(0), 'critical'))
    elif min_equity is not None and r['equity'] < _d(min_equity):
        out.append(('equity', r['equity'], _d(min_equity), 'high'))
    if max_leverage is not None:
        if r['leverage'] is None and not r['negative_equity'] and r['equity'] == 0:
            out.append(('leverage', None, _d(max_leverage), 'critical'))
        elif r['leverage'] is not None and r['leverage'] > _d(max_leverage):
            out.append(('leverage', r['leverage'], _d(max_leverage), 'high'))
    if min_capital_base is not None and r['capital_base'] is not None and r['capital_base'] < _d(min_capital_base):
        out.append(('capital_base', r['capital_base'], _d(min_capital_base), 'high'))
    return out


# --------------------------------------------------------------------------
# Addresses and names
# --------------------------------------------------------------------------

_AR = [('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ة', 'ه'), ('ى', 'ي'), ('ؤ', 'و'), ('ئ', 'ي')]
_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
_STOP = {'st', 'street', 'rd', 'road', 'the', 'of', 'no', 'floor', 'fl', 'bldg', 'building', 'ش', 'شارع', 'عمارة',
         'الدور', 'رقم', 'apt', 'flat', 'شقة', 'egypt', 'مصر', 'arab', 'republic'}


def normalise(s):
    s = unicodedata.normalize('NFKC', s or '').lower().translate(_DIGITS)
    for a, b in _AR:
        s = s.replace(a, b)
    s = re.sub(r'[ً-ْ]', '', s)
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s)).strip()


def _tokens(s):
    return {t for t in normalise(s).split() if t not in _STOP}


def address_matches(text, registered, aliases=(), threshold=0.75):
    """True when the address on a document is the registered address (or an accepted alias).
    Token overlap ignores punctuation, Arabic letter forms, Arabic-Indic digits and filler words."""
    doc = _tokens(text)
    if not doc:
        return False
    for ref in [registered, *(aliases or [])]:
        r = _tokens(ref)
        if not r:
            continue
        overlap = len(doc & r) / len(doc | r)
        if overlap >= threshold or r <= doc:
            return True
    return False


def same_party(a, b):
    """Loose equality of two party names (payer vs related party)."""
    ta, tb = set(normalise(a).split()), set(normalise(b).split())
    if not ta or not tb:
        return False
    return ta == tb or ta <= tb or tb <= ta


# --------------------------------------------------------------------------
# Key functions, branches, staffing
# --------------------------------------------------------------------------

def key_function_issues(ftype, holder, today=None):
    """Issues for one key-function type given its current holder row (or None)."""
    out = []
    if not holder or holder.get('vacated_on'):
        if ftype.get('is_required', True):
            out.append(('vacant', _t('function is vacant')))
        return out
    if holder.get('fit_proper_status') == 'failed':
        out.append(('fit_proper_failed', _t('fit & proper assessment failed')))
    elif holder.get('fit_proper_status') == 'pending':
        out.append(('fit_proper_pending', _t('fit & proper assessment not completed')))
    if ftype.get('notify_regulator', True) and not holder.get('regulator_notified_on'):
        out.append(('not_notified', _t('filled but not notified to the regulator')))
    if ftype.get('needs_no_objection'):
        st = holder.get('no_objection_status')
        if st == 'refused':
            out.append(('no_objection_refused', _t('regulator refused the appointment')))
        elif st != 'granted':
            out.append(('no_objection_pending', _t('regulator no-objection not granted')))
    return out


def branch_issues(b, today=None, max_vacancy_days=None):
    today = today or date.today()
    out = []
    if b['status'] != 'active':
        return out
    vacant = not (b.get('manager_name') or b.get('manager_user_id'))
    if vacant:
        since = b.get('manager_vacant_since')
        days = (today - since).days if since else None
        if max_vacancy_days is not None and days is not None and days <= int(max_vacancy_days):
            out.append(('vacancy_within_limit', _t('manager post vacant for %(days)s day(s)', days=days)))
        else:
            out.append(('no_manager', (_t('no branch manager for %(days)s day(s)', days=days) if days is not None else _t('no branch manager'))))
    elif b.get('manager_no_objection') not in ('granted', 'not_required'):
        out.append(('no_objection_missing', _t('branch manager without regulator no-objection')))
    return out


def staffing_gaps(branches, roles, staffing, minimums):
    """branches: active rows; roles: role rows; staffing: {(branch_id, role_code): headcount};
    minimums: {role_code: int|None}. Returns [(branch, role, have, need)]."""
    out = []
    for b in branches:
        if b['status'] != 'active':
            continue
        for r in roles:
            need = minimums.get(r['code'])
            if need is None or not r.get('is_active', True):
                continue
            have = staffing.get((b['id'], r['code']), 0)
            if have < int(need):
                out.append((b, r, have, int(need)))
    return out


# --------------------------------------------------------------------------
# Facilities
# --------------------------------------------------------------------------

def expected_accrual(balance, rate_pct, start, end, basis=365):
    """Simple-interest accrual between two dates (actual/basis)."""
    if balance is None or rate_pct is None or not start or not end or end <= start:
        return Decimal(0)
    return (_d(balance) * _d(rate_pct) / 100 * (end - start).days / basis).quantize(Decimal('0.01'))


def accrual_gap(f, tolerance_pct=0):
    """(expected, booked, diff, breach) for one facility, or None when not measurable."""
    if f.get('status') == 'closed' or not f.get('interest_rate_pct') or not f.get('accrual_from'):
        return None
    end = f.get('booked_as_of')
    if not end:
        return None
    exp = expected_accrual(f.get('balance'), f.get('interest_rate_pct'), f['accrual_from'], end)
    booked = _d(f.get('accrued_booked')) or Decimal(0)
    diff = exp - booked
    tol = exp * _d(tolerance_pct or 0) / 100
    return {'expected': exp, 'booked': booked, 'diff': diff, 'breach': exp > 0 and abs(diff) > tol}


def confirmation_issue(f, today=None, max_age_days=None):
    today = today or date.today()
    if f.get('status') == 'closed':
        return None
    d = f.get('last_confirmation_date')
    if not d:
        return 'no balance confirmation on file'
    if max_age_days is not None and (today - d).days > int(max_age_days):
        return f'confirmation {(today - d).days} day(s) old'
    cb, bal = f.get('confirmation_balance'), f.get('balance')
    if cb is not None and bal is not None and _d(cb) != _d(bal) and not f.get('booked_as_of'):
        return 'confirmed balance differs from the books'
    return None


def facility_status_issues(f):
    out = []
    if f.get('status') == 'closed':
        return out
    if (f.get('status') == 'default' or f.get('covenant_breach')) and not f.get('board_escalated_on'):
        out.append(_t('default / covenant breach not escalated to the board'))
    if f.get('status') == 'rescheduled' and not (f.get('rescheduling_approval_ref') or '').strip():
        out.append(_t('rescheduled without an approval reference'))
    return out


# --------------------------------------------------------------------------
# Related parties & studies
# --------------------------------------------------------------------------

def rp_item_issues(item, party, has_documents):
    out = []
    if item['item_type'] == 'capital_contribution' and not has_documents:
        out.append(_t('capital contribution without supporting document'))
    payer = (item.get('payer_name') or '').strip()
    if payer and not same_party(payer, party['name']) and not (item.get('explanation') or '').strip():
        out.append(_t('paid by "%(payer)s", not by the related party', payer=payer))
    if party.get('relation') == 'exiting_shareholder' and item['item_type'] in ('dues', 'current_account') \
            and item.get('classification') != 'liability':
        out.append(_t('dues to an exiting shareholder not classified as a liability'))
    return out


def study_issue(studies, today=None):
    """Issue for one study type given its rows, or None when an approved, current study exists."""
    today = today or date.today()
    approved = [s for s in studies if s['status'] == 'approved' and s.get('approved_on')]
    if not approved:
        return 'no approved study'
    cur = max(approved, key=lambda s: s['approved_on'])
    if cur.get('next_refresh_date') and cur['next_refresh_date'] < today:
        return f"study approved {cur['approved_on']} is due for refresh since {cur['next_refresh_date']}"
    return None
