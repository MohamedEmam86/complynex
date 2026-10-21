# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Chart specifications for the ESG pages (drawn by static/js/ecx-charts.js)."""
from flask_babel import gettext as _, get_locale


def _ar():
    return str(get_locale() or '') == 'ar'


def loc(row, field):
    """Arabic text when the user reads Arabic and a translation exists."""
    if _ar() and row.get(field + '_ar'):
        return row[field + '_ar']
    return row.get(field)


def pillar_radar(summary, prior=None, prior_label=None):
    pillars = (summary or {}).get('pillars') or []
    if len(pillars) < 3 or not any(p.get('score') is not None for p in pillars):
        return None
    series = [{'name': _('This period'), 'data': [p['score'] or 0 for p in pillars], 'color': 'rgba(91,75,196,.18)', 'border': '#5b4bc4'}]
    if prior and any(p.get('score') is not None for p in prior.get('pillars') or []):
        by = {p['code']: p['score'] for p in prior['pillars']}
        series.append({'name': prior_label or _('Previous period'), 'data': [by.get(p['code']) or 0 for p in pillars],
                       'color': 'rgba(108,117,125,.08)', 'border': '#adb5bd'})
    return {'kind': 'radar', 'max': 5, 'labels': [loc(p, 'name') for p in pillars], 'series': series, 'unit': '/5'}


STATUS_ORDER = ('complete', 'partial', 'not_started', 'not_applicable')


def coverage_rows(rows):
    """rows: framework, status, n -> [{framework, counts{status: n}, total, pct_done}] for the heat table."""
    out = {}
    for r in rows:
        d = out.setdefault(r['framework'], {'framework': r['framework'], 'counts': {s: 0 for s in STATUS_ORDER}, 'total': 0})
        d['counts'][r['status'] if r['status'] in STATUS_ORDER else 'not_started'] += r['n']
        d['total'] += r['n']
    res = []
    for fw in sorted(out):
        d = out[fw]
        applicable = d['total'] - d['counts']['not_applicable']
        d['pct_done'] = round(100.0 * (d['counts']['complete'] + 0.5 * d['counts']['partial']) / applicable) if applicable else 0
        res.append(d)
    return res


def materiality_scatter(plotted):
    pts = []
    for p in plotted or []:
        t = p['topic']
        name = loc(t, 'name') or ''
        pts.append({'x': float(p['impact']), 'y': float(p['importance']), 'label': name if len(name) <= 28 else name[:26] + '…'})
    if not pts:
        return None
    return {'kind': 'scatter', 'xMin': 1, 'xMax': 5, 'min': 1, 'max': 5, 'pointLabels': True,
            'quadrants': {'x': 3, 'y': 3}, 'xTitle': _('Business Impact'), 'yTitle': _('Stakeholder Importance'),
            'series': [{'name': _('Topics'), 'data': pts, 'color': '#5b4bc4'}]}
