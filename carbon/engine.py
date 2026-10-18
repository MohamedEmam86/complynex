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
Carbon Footprint & Climate — calculation engine.

Pure functions only: nothing here touches the database or Flask. Every
number this module produces can be traced back to `quantity x factor`,
with the factor's source/vintage/citation carried alongside the result so
the UI can show "why is this the number" next to every figure — that
transparency was the single biggest gap found in the two Integrys Excel
workbooks reviewed for this project (hardcoded cell references, silent
off-by-one row shifts, and no visible link between a total and the factor
that produced it).

GHG Protocol basics this module encodes:
  - Scope 1: direct emissions (owned/controlled combustion, fugitive refrigerant losses).
  - Scope 2: indirect emissions from purchased electricity/heat/steam/cooling.
      Reported on BOTH a location-based basis (grid average factor) and a
      market-based basis (contractual instruments e.g. PPAs/RECs), per the
      GHG Protocol Scope 2 Guidance dual-reporting requirement.
  - Scope 3: all other value-chain emissions, split across the 15 standard
      categories (8 upstream, 7 downstream) defined in the GHG Protocol
      Corporate Value Chain (Scope 3) Standard.
"""
from collections import defaultdict

SCOPE3_CATEGORIES = {
    1: "Purchased Goods & Services",
    2: "Capital Goods",
    3: "Fuel- and Energy-Related Activities",
    4: "Upstream Transportation & Distribution",
    5: "Waste Generated in Operations",
    6: "Business Travel",
    7: "Employee Commuting",
    8: "Upstream Leased Assets",
    9: "Downstream Transportation & Distribution",
    10: "Processing of Sold Products",
    11: "Use of Sold Products",
    12: "End-of-Life Treatment of Sold Products",
    13: "Downstream Leased Assets",
    14: "Franchises",
    15: "Investments",
}

SCOPE_LABELS = {
    'scope1': 'Scope 1 — Direct Emissions',
    'scope2': 'Scope 2 — Purchased Energy',
    'scope3': 'Scope 3 — Value Chain',
}


def compute_entry_emissions(quantity, factor_kgco2e):
    """value (tCO2e) = quantity x factor(kgCO2e/unit) / 1000.

    This is the ONE formula every activity entry in this module runs
    through. It is intentionally this simple and intentionally the only
    place it is implemented — every dashboard total, scope subtotal, and
    intensity metric downstream is a sum or ratio built on top of this,
    never a re-derivation of it. That is the fix for the row-shift and
    formula-drift bugs found in the reviewed Excel workbooks.
    """
    if quantity is None or factor_kgco2e is None:
        return 0.0
    return round((float(quantity) * float(factor_kgco2e)) / 1000.0, 6)


def compute_scope_totals(entries):
    """entries: iterable of dict-like rows with 'scope' and 'tco2e'.
    Returns {'scope1': x, 'scope2': y, 'scope3': z, 'total': x+y+z}, plus a
    scope2 location/market split when a 'basis' key is present."""
    totals = defaultdict(float)
    scope2_location = 0.0
    scope2_market = 0.0
    for e in entries:
        scope = e['scope']
        tco2e = float(e['tco2e'] or 0.0)   # NUMERIC or float column
        totals[scope] += tco2e
        if scope == 'scope2':
            if (e.get('basis') or 'location') == 'market':
                scope2_market += tco2e
            else:
                scope2_location += tco2e

    scope1 = round(totals.get('scope1', 0.0), 3)
    scope2_loc = round(scope2_location, 3)
    scope2_mkt = round(scope2_market, 3)
    scope3 = round(totals.get('scope3', 0.0), 3)

    return {
        'scope1': scope1,
        'scope2_location': scope2_loc,
        'scope2_market': scope2_mkt,
        'scope3': scope3,
        'total_location_based': round(scope1 + scope2_loc + scope3, 3),
        'total_market_based': round(scope1 + scope2_mkt + scope3, 3),
    }


def compute_scope3_breakdown(entries):
    """Returns {category_no: tco2e} for scope3 entries, plus category labels."""
    breakdown = defaultdict(float)
    for e in entries:
        if e['scope'] != 'scope3':
            continue
        cat_no = e.get('ghg_category_no')
        if cat_no is None:
            continue
        breakdown[cat_no] += float(e['tco2e'] or 0.0)
    return {
        cat_no: {
            'label': SCOPE3_CATEGORIES.get(cat_no, f'Category {cat_no}'),
            'tco2e': round(val, 3),
        }
        for cat_no, val in sorted(breakdown.items())
    }


def compute_intensity_metrics(total_tco2e, headcount=None, revenue_egp_000=None):
    """Carbon intensity per FTE and per EGP '000 revenue — the two metrics
    CBE/EGX-listed peers and most GRI 305-4 disclosures expect alongside
    the absolute total, since absolute totals alone don't show whether a
    company is decarbonizing or just shrinking/growing."""
    out = {}
    if headcount:
        out['tco2e_per_fte'] = round(total_tco2e / headcount, 4)
    if revenue_egp_000:
        out['tco2e_per_egp_000_revenue'] = round(total_tco2e / revenue_egp_000, 6)
    return out


def compute_yoy_comparison(current_total, prior_total):
    """Returns absolute + percentage change. Prior-year figure must come
    from a CLOSED reporting period's stored total, never a live recompute
    against a possibly-still-open period — this is what caused one of the
    wrong-YoY-reference bugs found in the Integrys workbook review."""
    if prior_total is None:
        return {'available': False}
    delta = round(current_total - prior_total, 3)
    pct = round((delta / prior_total) * 100, 2) if prior_total else None
    return {
        'available': True,
        'prior_total': round(prior_total, 3),
        'current_total': round(current_total, 3),
        'delta_tco2e': delta,
        'pct_change': pct,
        'direction': 'down' if delta < 0 else ('up' if delta > 0 else 'flat'),
    }


def compute_target_progress(baseline_year, baseline_tco2e, current_tco2e, target_pct, target_year):
    """% progress toward a reduction target, e.g. 'reduce 50% by 2030 vs.
    2026 baseline'. Returns None if there's no usable baseline yet (a
    fresh deployment before the first inventory closes)."""
    if not baseline_tco2e:
        return None
    target_tco2e = baseline_tco2e * (1 - (target_pct / 100.0))
    reduction_so_far = baseline_tco2e - current_tco2e
    reduction_needed = baseline_tco2e - target_tco2e
    pct_of_path_walked = round((reduction_so_far / reduction_needed) * 100, 1) if reduction_needed else None
    return {
        'baseline_year': baseline_year,
        'baseline_tco2e': round(baseline_tco2e, 3),
        'target_year': target_year,
        'target_pct': target_pct,
        'target_tco2e': round(target_tco2e, 3),
        'current_tco2e': round(current_tco2e, 3),
        'pct_of_path_walked': pct_of_path_walked,
        'on_track': pct_of_path_walked is not None and pct_of_path_walked >= 0,
    }
