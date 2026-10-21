# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Chart specifications for the Carbon pages (drawn by static/js/ecx-charts.js).

Pure functions over the same entry rows and totals the pages already show, so a
chart can never disagree with the figures next to it. Labels are translated here.
"""
from datetime import date

from flask_babel import gettext as _

SCOPE_COLORS = {'scope1': '#E67E22', 'scope2': '#0D6EFD', 'scope3': '#198754'}


def scope_label(sc):
    return {'scope1': _('Scope 1'), 'scope2': _('Scope 2'), 'scope3': _('Scope 3')}.get(sc, sc)


def category_label(c):
    return {'stationary_combustion': _('Stationary combustion'), 'mobile_combustion': _('Mobile combustion'),
            'fugitive_emissions': _('Fugitive emissions (refrigerants)'), 'purchased_electricity': _('Purchased electricity'),
            'business_travel': _('Business travel'), 'employee_commuting': _('Employee commuting'),
            'purchased_goods_services': _('Purchased goods and services'), 'waste_operations': _('Waste from operations'),
            'upstream_transport': _('Upstream transportation'), 'fuel_energy_related': _('Fuel- and energy-related activities'),
            'investments': _('Investments (financed emissions)')}.get(c, (c or '').replace('_', ' '))


def _t(e):
    try:
        return float(e.get('tco2e') or 0)
    except (TypeError, ValueError):
        return 0.0


def _month(v):
    if not v:
        return None
    if isinstance(v, date):
        return v.strftime('%Y-%m')
    return str(v)[:7]


def monthly_by_scope(entries, enabled):
    """Stacked monthly bars per scope; None when fewer than two months carry data."""
    months = sorted({m for m in (_month(e.get('activity_month')) for e in entries) if m})
    if len(months) < 2:
        return None
    series = []
    for sc in ('scope1', 'scope2', 'scope3'):
        if sc not in enabled:
            continue
        vals = [round(sum(_t(e) for e in entries if e['scope'] == sc and _month(e.get('activity_month')) == m), 3) for m in months]
        if any(vals):
            series.append({'name': scope_label(sc), 'data': vals, 'color': SCOPE_COLORS[sc], 'stack': 's', 'barMax': 38})
    no_month = sum(1 for e in entries if not e.get('activity_month'))
    return {'kind': 'bar', 'stacked': True, 'labels': months, 'series': series, 'unit': 'tCO2e',
            'yTitle': 'tCO2e', 'no_month': no_month}


def by_category(entries):
    """Horizontal bars, largest source first: where to start reducing."""
    agg = {}
    for e in entries:
        k = (e['scope'], e.get('category'))
        agg[k] = agg.get(k, 0.0) + _t(e)
    rows = sorted(((v, sc, c) for (sc, c), v in agg.items() if v > 0), reverse=True)[:12]
    if not rows:
        return None
    return {'kind': 'hbar', 'labels': [category_label(c) for _v, _sc, c in rows], 'legend': False, 'unit': 'tCO2e',
            'series': [{'name': 'tCO2e', 'data': [round(v, 3) for v, _sc, _c in rows],
                        'color': [SCOPE_COLORS.get(sc, '#6c757d') for _v, sc, _c in rows], 'barMax': 22}],
            'height': 60 + 30 * len(rows)}


def by_site(entries, site_names):
    agg = {}
    for e in entries:
        sid = e.get('site_id')
        agg[sid] = agg.get(sid, 0.0) + _t(e)
    if len([k for k in agg if k]) < 2:
        return None
    rows = sorted(agg.items(), key=lambda kv: -kv[1])
    return {'kind': 'hbar', 'legend': False, 'unit': 'tCO2e',
            'labels': [site_names.get(k) or _('No site') for k, _v in rows],
            'series': [{'name': 'tCO2e', 'data': [round(v, 3) for _k, v in rows], 'color': '#20c997', 'barMax': 22}],
            'height': 60 + 30 * len(rows)}


def pathway(target, progress, total, period):
    """Base year -> 2030 required path (dashed) against the actual inventory of the period."""
    if not target or not progress or not target.get('baseline_year'):
        return None
    by = int(target['baseline_year'])
    end = 2030
    if end <= by:
        return None
    base = float(progress['baseline_tco2e'])
    tgt = float(progress['target_tco2e'])
    years = list(range(by, end + 1))
    path = [round(base + (tgt - base) * (y - by) / (end - by), 3) for y in years]
    actual = [None] * len(years)
    actual[0] = round(base, 3)
    py = None
    try:
        py = (period or {}).get('end_date').year
    except Exception:
        py = date.today().year
    if py in years:
        actual[years.index(py)] = round(float(total or 0), 3)
    return {'kind': 'line', 'labels': [str(y) for y in years], 'unit': 'tCO2e', 'yTitle': 'tCO2e',
            'series': [{'name': _('Required path to the 2030 target'), 'data': path, 'color': '#6c757d', 'dashed': True, 'pointRadius': 0},
                       {'name': _('Actual inventory'), 'data': actual, 'color': '#198754', 'pointRadius': 5}]}


def offset_doughnut(purchased, required):
    if not required:
        return None
    required = float(required)
    purchased = float(purchased or 0)
    rem = max(0.0, required - purchased)
    pct = min(100, round(100.0 * purchased / required)) if required else 0
    return {'kind': 'doughnut', 'labels': [_('Certificates bought'), _('Still to buy')], 'unit': 'tCO2e',
            'series': [{'name': 'tCO2e', 'data': [round(min(purchased, required), 3), round(rem, 3)], 'color': ['#198754', '#e9ecef']}],
            'centre': [f'{pct}%', _('of the obligation')]}
