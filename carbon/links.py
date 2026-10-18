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

"""Links from Carbon results to ESG: which carbon figure feeds an ESG indicator
or a disclosure item ("auto-filled from Carbon — value, period, status").

The link is data: `carbon_metric` on esg_disclosure_items / esg_indicators.
NULL means "detect from the reference and title" (GRI 305-1…4, "Scope 1/2/3",
GHG / emissions wording, in English or Arabic); 'none' switches the link off.
Nothing is written to ESG: the value is shown next to the item, and the
person responsible still decides its status or score.
"""

import re

METRICS = ('total', 'scope1', 'scope2', 'scope3', 'intensity_employee')

_RULES = (
    ('scope1', re.compile(r'305-1\b|scope\s*1\b|النطاق\s*(?:الأول|1|١)', re.I)),
    ('scope2', re.compile(r'305-2\b|scope\s*2\b|النطاق\s*(?:الثاني|2|٢)', re.I)),
    ('scope3', re.compile(r'305-3\b|scope\s*3\b|النطاق\s*(?:الثالث|3|٣)', re.I)),
    ('intensity_employee', re.compile(r'305-4\b|emissions?\s+intensity|كثافة\s+الانبعاثات', re.I)),
    ('total', re.compile(r'\bGHG\b|greenhouse|carbon\s+footprint|\bemissions?\b|انبعاث|البصمة\s+الكربونية|غازات\s+الاحتباس', re.I)),
)


def detect(*texts):
    """Carbon metric suggested by a reference code and title, or None."""
    t = ' '.join(x for x in texts if x)
    for metric, rx in _RULES:
        if rx.search(t):
            return metric
    return None


def metric_for(row, *fields):
    """The configured metric of an ESG row (None when switched off or nothing matches)."""
    m = (row or {}).get('carbon_metric')
    if m == 'none':
        return None
    if m in METRICS:
        return m
    return detect(*[(row or {}).get(f) for f in fields])


def carbon_values(period_id):
    """{'period', 'status', 'enabled', 'values': {metric: tCO2e or ratio}} for one reporting period, or None."""
    from database.db import get_db
    from . import service as S
    try:
        inv = S.inventory(period_id)
    except Exception:
        get_db().rollback()
        return None
    if not inv.get('period'):
        return None
    t = inv['totals']
    return {'period': inv['period'], 'status': (inv.get('workflow') or {}).get('status') or 'preparing', 'enabled': inv['enabled'],
            'entries': len(inv['entries']),
            'values': {'total': t['total_location_based'], 'scope1': t['scope1'], 'scope2': t['scope2_location'],
                       'scope3': t['scope3'], 'intensity_employee': (inv.get('intensity') or {}).get('per_employee')}}


def feed(row, values, *fields):
    """What to show next to an ESG row: {metric, value, in_boundary} or None."""
    m = metric_for(row, *fields)
    if not m or not values:
        return None
    in_boundary = m not in ('scope1', 'scope2', 'scope3') or m in values['enabled']
    return {'metric': m, 'value': values['values'].get(m) if in_boundary else None, 'in_boundary': in_boundary,
            'configured': (row or {}).get('carbon_metric') in METRICS}
