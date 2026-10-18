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
Carbon accounting — pure calculation and control logic (no Flask, no DB).

Extends carbon/engine.py (which keeps the one emission formula
quantity x factor / 1000) with what an auditable inventory needs:

  * organisational boundary — operational control, financial control or
    equity share (GHG Protocol Corporate Standard ch. 3);
  * versioned emission factors — the version in force on the activity date
    is selected and its value is stored with the entry, so a later factor
    update never changes a closed number;
  * PCAF financed emissions (Scope 3 Category 15) with data-quality scores;
  * data-quality controls — missing months, outliers vs the previous
    period, unit mismatches, entries without evidence;
  * preparer → reviewer → approver workflow with segregation of duties;
  * intensity metrics.

Every regulatory number (thresholds, percentages) arrives as an argument.
"""

from collections import defaultdict
from datetime import date

from .engine import compute_entry_emissions

APPROACHES = ('operational_control', 'financial_control', 'equity_share')


# --------------------------------------------------------------------------
# Organisational boundary
# --------------------------------------------------------------------------

def inclusion_share(entity, approach):
    """Fraction (0..1) of an entity's emissions consolidated under the approach."""
    if entity is None:
        return 1.0
    if not entity.get('included', True):
        return 0.0
    if approach == 'equity_share':
        return max(0.0, min(1.0, float(entity.get('ownership_pct') or 0) / 100.0))
    if approach == 'financial_control':
        return 1.0 if entity.get('financial_control') else 0.0
    return 1.0 if entity.get('operational_control', True) else 0.0


# --------------------------------------------------------------------------
# Versioned factors
# --------------------------------------------------------------------------

def select_factor_version(versions, on_date):
    """The version in force on `on_date` (effective_from <= d <= effective_to/open).
    Falls back to the latest version starting before the date; None when nothing applies."""
    on_date = on_date or date.today()
    live = [v for v in versions
            if (v.get('effective_from') or date.min) <= on_date and (v.get('effective_to') is None or v['effective_to'] >= on_date)]
    if live:
        return max(live, key=lambda v: (v.get('effective_from') or date.min, v.get('vintage_year') or 0))
    older = [v for v in versions if (v.get('effective_from') or date.min) <= on_date]
    return max(older, key=lambda v: v.get('effective_from') or date.min) if older else None


def units_match(entry_unit, factor_unit):
    norm = lambda u: (u or '').strip().lower().replace(' ', '').replace('³', '3')  # noqa: E731
    return norm(entry_unit) == norm(factor_unit)


def compute_activity(quantity, factor, share=1.0, entry_unit=None):
    """→ dict(tco2e, gross_tco2e, factor_value, unit_ok). The consolidated
    figure is the gross figure times the boundary share."""
    gross = compute_entry_emissions(quantity, factor.get('factor_kgco2e') if factor else None)
    unit_ok = entry_unit is None or (factor is not None and units_match(entry_unit, factor.get('unit')))
    return {'gross_tco2e': gross, 'tco2e': round(gross * share, 6),
            'factor_value': factor.get('factor_kgco2e') if factor else None, 'unit_ok': unit_ok}


def scope2_dual(entries):
    """GHG Protocol Scope 2 dual reporting.

    Consumption is recorded once with the grid factor (basis 'location'); where a
    contractual instrument covers it, an instrument entry (basis 'market') is
    added for the same site and month. Location-based = all location entries.
    Market-based = instrument entries + location entries of site-months that no
    instrument covers (grid factor as fallback, GHG Protocol Scope 2 Guidance).
    """
    s2 = [e for e in entries if e.get('scope') == 'scope2']
    covered = {(e.get('site_id'), e.get('activity_month')) for e in s2 if (e.get('basis') or 'location') == 'market'}
    loc = sum(float(e.get('tco2e') or 0) for e in s2 if (e.get('basis') or 'location') != 'market')
    mkt = sum(float(e.get('tco2e') or 0) for e in s2 if (e.get('basis') or 'location') == 'market')
    mkt += sum(float(e.get('tco2e') or 0) for e in s2 if (e.get('basis') or 'location') != 'market'
               and (e.get('site_id'), e.get('activity_month')) not in covered)
    return round(loc, 3), round(mkt, 3)


# --------------------------------------------------------------------------
# Scope 3 helpers (activity → quantity in the factor's unit)
# --------------------------------------------------------------------------

def commuting_quantity(employees, days_per_year, one_way_km, round_trip=True):
    """Employee commuting (Cat. 7): passenger-km = employees x days x distance (x2 for return)."""
    return float(employees or 0) * float(days_per_year or 0) * float(one_way_km or 0) * (2 if round_trip else 1)


def travel_quantity(trips, distance_km, travellers=1, round_trip=True):
    """Business travel (Cat. 6): passenger-km."""
    return float(trips or 0) * float(distance_km or 0) * float(travellers or 1) * (2 if round_trip else 1)


# --------------------------------------------------------------------------
# PCAF financed emissions (Scope 3 Category 15)
# --------------------------------------------------------------------------

PCAF_METHODS = {
    'reported_verified': 1,   # verified borrower emissions
    'reported': 2,            # unverified borrower emissions
    'physical': 3,            # activity data (energy, fuel, km) x factors
    'revenue': 4,             # borrower revenue x sector factor
    'asset': 5,               # outstanding amount x sector factor
}


def pcaf_exposure(x, sector_factor=None):
    """Financed emissions of one exposure (PCAF Global Standard, business loans /
    motor-vehicle loans).

    x: outstanding (EGP), attribution_base (borrower equity+debt, or vehicle value
       at origination, EGP), method, borrower_emissions_tco2e (methods 1-3),
       borrower_revenue_egp (method 4).
    sector_factor: tCO2e per EGP million (revenue for method 4, outstanding for method 5).
    Returns dict(attribution, financed_tco2e, score, error).
    """
    method = x.get('method')
    score = PCAF_METHODS.get(method)
    out = float(x.get('outstanding') or 0)
    if score is None:
        return {'attribution': None, 'financed_tco2e': 0.0, 'score': None, 'error': 'unknown method'}
    if out <= 0:
        return {'attribution': 0.0, 'financed_tco2e': 0.0, 'score': score, 'error': None}
    if method == 'asset':
        if sector_factor is None:
            return {'attribution': None, 'financed_tco2e': 0.0, 'score': score, 'error': 'sector factor missing'}
        return {'attribution': None, 'financed_tco2e': round(out / 1e6 * float(sector_factor), 6), 'score': score,
                'error': None}
    base = float(x.get('attribution_base') or 0)
    if base <= 0:
        return {'attribution': None, 'financed_tco2e': 0.0, 'score': score, 'error': 'attribution base missing'}
    af = min(1.0, out / base)
    if method == 'revenue':
        if sector_factor is None or not x.get('borrower_revenue_egp'):
            return {'attribution': af, 'financed_tco2e': 0.0, 'score': score, 'error': 'revenue or sector factor missing'}
        emissions = float(x['borrower_revenue_egp']) / 1e6 * float(sector_factor)
    else:
        if x.get('borrower_emissions_tco2e') is None:
            return {'attribution': af, 'financed_tco2e': 0.0, 'score': score, 'error': 'borrower emissions missing'}
        emissions = float(x['borrower_emissions_tco2e'])
    return {'attribution': round(af, 6), 'financed_tco2e': round(af * emissions, 6), 'score': score, 'error': None}


def pcaf_portfolio(results):
    """results: [(exposure, pcaf_exposure-result)] → totals and outstanding-weighted data-quality score."""
    total = sum(r['financed_tco2e'] for _, r in results)
    covered = [(x, r) for x, r in results if r['score'] is not None and not r['error']]
    w = sum(float(x.get('outstanding') or 0) for x, _ in covered)
    score = round(sum(r['score'] * float(x.get('outstanding') or 0) for x, r in covered) / w, 2) if w else None
    by_class = defaultdict(float)
    for x, r in results:
        by_class[x.get('asset_class') or 'other'] += r['financed_tco2e']
    outstanding = sum(float(x.get('outstanding') or 0) for x, _ in results)
    return {'financed_tco2e': round(total, 3), 'weighted_score': score, 'exposures': len(results),
            'errors': sum(1 for _, r in results if r['error']), 'outstanding': outstanding,
            'coverage_pct': round(100 * w / outstanding, 1) if outstanding else None,
            'by_class': {k: round(v, 3) for k, v in by_class.items()}}


# --------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------

def month_starts(start, end):
    d = date(start.year, start.month, 1)
    out = []
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def dq_issues(entries, period_start, period_end, prior_entries=(), outlier_pct=50, monthly_keys=None,
              has_evidence=None):
    """Data-quality issues for one period.

    entries: rows with id, site_id, factor_code (or activity), activity_month, quantity, unit,
             factor_unit, tco2e.
    monthly_keys: factor codes expected every month (e.g. electricity, fuel); default: every
                  factor code that appears with an activity_month.
    has_evidence: callable(entry) -> bool.
    Returns [{severity, code, message, entry_id?}] — severity 'critical' blocks approval.
    """
    out = []
    key = lambda e: (e.get('site_id'), e.get('factor_code') or e.get('activity'))  # noqa: E731
    for e in entries:
        if e.get('factor_unit') is not None and e.get('unit') is not None and not units_match(e['unit'], e['factor_unit']):
            out.append({'severity': 'critical', 'code': 'unit_mismatch', 'entry_id': e.get('id'),
                        'message': f"{e.get('activity')}: unit {e['unit']} ≠ factor unit {e['factor_unit']}"})
        if has_evidence is not None and not has_evidence(e):
            out.append({'severity': 'critical', 'code': 'unsupported', 'entry_id': e.get('id'),
                        'message': f"{e.get('activity')}: no supporting evidence"})
        if (e.get('quantity') or 0) < 0:
            out.append({'severity': 'critical', 'code': 'negative', 'entry_id': e.get('id'),
                        'message': f"{e.get('activity')}: negative quantity"})
    months = month_starts(period_start, period_end)
    seen = defaultdict(set)
    for e in entries:
        if e.get('activity_month'):
            m = e['activity_month']
            seen[key(e)].add(date(m.year, m.month, 1))
    keys = [k for k in seen if monthly_keys is None or k[1] in monthly_keys]
    for k in keys:
        missing = [m for m in months if m not in seen[k] and m <= date.today()]
        if missing:
            out.append({'severity': 'warning', 'code': 'missing_months',
                        'message': f"{k[1]} (site {k[0] or '-'}): {len(missing)} month(s) without data — "
                                   + ', '.join(m.strftime('%Y-%m') for m in missing[:6])})
    if prior_entries and outlier_pct is not None:
        cur, prev = defaultdict(float), defaultdict(float)
        for e in entries:
            cur[key(e)] += float(e.get('quantity') or 0)
        for e in prior_entries:
            prev[key(e)] += float(e.get('quantity') or 0)
        for k, q in cur.items():
            p = prev.get(k)
            if p and abs(q - p) / p * 100 > float(outlier_pct):
                out.append({'severity': 'warning', 'code': 'outlier',
                            'message': f"{k[1]} (site {k[0] or '-'}): {q:,.0f} vs {p:,.0f} in the previous period "
                                       f"({(q - p) / p * 100:+.0f}%)"})
    return out


# --------------------------------------------------------------------------
# Workflow (segregation of duties) and period lock
# --------------------------------------------------------------------------

TRANSITIONS = {
    'preparing': ('submit', 'in_review'),
    'in_review': ('review', 'reviewed'),
    'reviewed': ('approve', 'approved'),
}


def next_state(wf, action, user_id, critical_issues=0):
    """Validate a workflow action → new status, or raise ValueError with the reason."""
    status = (wf or {}).get('status') or 'preparing'
    if action == 'return':
        if status not in ('in_review', 'reviewed'):
            raise ValueError('only an inventory under review can be returned')
        return 'preparing'
    if action == 'unlock':
        if status != 'approved':
            raise ValueError('only an approved inventory can be unlocked')
        return 'preparing'
    exp = TRANSITIONS.get(status)
    if not exp or exp[0] != action:
        raise ValueError(f'cannot {action} an inventory in status {status}')
    if action == 'submit' and critical_issues:
        raise ValueError('fix the critical data-quality issues before submitting')
    if action == 'review' and wf.get('prepared_by') == user_id:
        raise ValueError('the reviewer must be different from the preparer')
    if action == 'approve' and user_id in (wf.get('prepared_by'), wf.get('reviewed_by')):
        raise ValueError('the approver must be different from the preparer and the reviewer')
    return exp[1]


def is_locked(wf):
    return bool(wf) and wf.get('status') == 'approved'


# --------------------------------------------------------------------------
# Intensity
# --------------------------------------------------------------------------

def intensities(total_tco2e, headcount=None, floor_area_m2=None, revenue_egp=None, financed_egp=None,
                financed_tco2e=None):
    """tCO2e per employee, per m², per EGP million revenue, and financed tCO2e per EGP million financed."""
    out = {}
    if headcount:
        out['per_employee'] = round(total_tco2e / float(headcount), 4)
    if floor_area_m2:
        out['per_m2'] = round(total_tco2e / float(floor_area_m2), 6)
    if revenue_egp:
        out['per_egp_m_revenue'] = round(total_tco2e / (float(revenue_egp) / 1e6), 4)
    if financed_egp and financed_tco2e is not None:
        out['per_egp_m_financed'] = round(float(financed_tco2e) / (float(financed_egp) / 1e6), 4)
    return out


def offsets_view(gross_tco2e, retired_tco2e):
    """Offsets are reported separately and never netted from gross emissions."""
    return {'gross_tco2e': round(gross_tco2e, 3), 'offsets_retired_tco2e': round(retired_tco2e or 0, 3),
            'net_shown': False}
