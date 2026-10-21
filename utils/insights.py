# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Insight charts for the module dashboards (drawn by static/js/ecx-charts.js).

`module_insights(name)` returns a list of cards {title, spec | heat, note}; every
query is guarded, so a module that is not in use simply shows fewer cards.
Read-only aggregates: no row-level data leaves the database.
"""
import logging
from datetime import date

from flask_babel import gettext as _

from database.db import get_db

logger = logging.getLogger(__name__)
SEV = {'LOW': '#20c997', 'MEDIUM': '#ffc107', 'HIGH': '#fd7e14', 'CRITICAL': '#dc3545'}
SEV_ORDER = ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')


def _rows(sql, params=()):
    db = get_db()
    try:
        return [dict(r) for r in db.execute(sql, params).fetchall()]
    except Exception:
        db.rollback()
        logger.debug('insight query failed', exc_info=True)
        return []


def _months(n=12):
    t = date.today()
    out = []
    y, m = t.year, t.month
    for _i in range(n):
        out.append(f'{y:04d}-{m:02d}')
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _sev_label(s):
    return {'LOW': _('Low'), 'MEDIUM': _('Medium'), 'HIGH': _('High'), 'CRITICAL': _('Critical')}.get(s, s)


def _status_label(s):
    s = (s or '').upper()
    return {'NEW': _('New'), 'OPEN': _('Open'), 'ASSIGNED': _('Assigned'), 'IN_PROGRESS': _('In progress'),
            'UNDER_REVIEW': _('Under review'), 'INVESTIGATING': _('Investigating'), 'SUBMITTED': _('Submitted'),
            'RESOLVED': _('Resolved'), 'CLOSED': _('Closed'), 'FALSE_POSITIVE': _('False positive'),
            'PENDING': _('Pending'), 'TRUE_HIT': _('True match')}.get(s, s.replace('_', ' ').title())


def _monthly_stacked(rows, key, value_order, colors, label_fn, title, note=None):
    months = _months()
    if not rows:
        return None
    series = []
    for v in value_order:
        data = [sum(r['n'] for r in rows if r['m'] == mo and (r[key] or '').upper() == v) for mo in months]
        if any(data):
            series.append({'name': label_fn(v), 'data': data, 'color': colors.get(v, '#6c757d'), 'stack': 's', 'barMax': 26})
    if not series:
        return None
    return {'title': title, 'note': note, 'height': 260,
            'spec': {'kind': 'bar', 'stacked': True, 'labels': months, 'series': series}}


def _doughnut(rows, title, label_fn=_status_label, palette=None):
    rows = [r for r in rows if r['n']]
    if not rows:
        return None
    pal = palette or ['#0d6efd', '#20c997', '#ffc107', '#fd7e14', '#dc3545', '#6f42c1', '#6c757d', '#198754']
    total = sum(r['n'] for r in rows)
    return {'title': title, 'height': 240,
            'spec': {'kind': 'doughnut', 'labels': [label_fn(r['k']) for r in rows],
                     'series': [{'name': title, 'data': [r['n'] for r in rows], 'color': pal[:len(rows)]}],
                     'centre': [f'{total:,}', _('total')]}}


def _hbar(rows, title, color='#0d6efd', label_fn=lambda k: k, note=None):
    rows = [r for r in rows if r['n']]
    if not rows:
        return None
    return {'title': title, 'note': note, 'height': 70 + 30 * len(rows),
            'spec': {'kind': 'hbar', 'legend': False, 'labels': [label_fn(r['k']) for r in rows],
                     'series': [{'name': title, 'data': [r['n'] for r in rows], 'color': color, 'barMax': 22}]}}


START = "date_trunc('month', CURRENT_DATE) - INTERVAL '11 months'"


def _risk():
    cards = []
    rows = _rows("""SELECT COALESCE(residual_likelihood, likelihood) AS l, COALESCE(residual_impact, impact) AS i, COUNT(*) AS n
                    FROM risks WHERE COALESCE(LOWER(status), 'active') NOT IN ('closed', 'archived', 'retired') GROUP BY 1, 2""")
    if rows:
        grid = {(int(r['l'] or 0), int(r['i'] or 0)): r['n'] for r in rows}
        cards.append({'title': _('Residual risk heat map'), 'heat': grid,
                      'note': _('Rows: likelihood (5 = almost certain). Columns: impact (5 = severe). Each cell shows how many risks sit there.')})
    cat = _rows("""SELECT COALESCE(c.category_name, '—') AS k, COUNT(*) AS n FROM risks r LEFT JOIN risk_categories c ON c.id = r.category_id
                   GROUP BY 1 ORDER BY 2 DESC LIMIT 10""")
    cards.append(_hbar(cat, _('Risks by category'), '#6f42c1'))
    return cards


def _aml():
    rows = _rows(f"""SELECT to_char(alert_date::date, 'YYYY-MM') AS m, UPPER(alert_severity) AS sev, COUNT(*) AS n
                     FROM tm_alerts WHERE alert_date::date >= {START} GROUP BY 1, 2""")
    st = _rows("SELECT UPPER(status) AS k, COUNT(*) AS n FROM tm_alerts GROUP BY 1 ORDER BY 2 DESC")
    return [_monthly_stacked(rows, 'sev', SEV_ORDER, SEV, _sev_label, _('Transaction-monitoring alerts per month')),
            _doughnut(st, _('Alert status'))]


def _screening():
    res = {'CONFIRMED_HIT': '#dc3545', 'POTENTIAL_MATCH': '#fd7e14', 'REVIEW_REQUIRED': '#ffc107', 'LOW_MATCH': '#0dcaf0',
           'CLEAR': '#20c997'}
    lab = {'CONFIRMED_HIT': _('Confirmed hit'), 'POTENTIAL_MATCH': _('Potential match'), 'REVIEW_REQUIRED': _('Review required'),
           'LOW_MATCH': _('Low match'), 'CLEAR': _('Clear')}
    rows = _rows(f"""SELECT to_char(created_at::timestamp, 'YYYY-MM') AS m, UPPER(screening_result) AS r, COUNT(*) AS n
                     FROM screening_results WHERE created_at::timestamp >= {START} GROUP BY 1, 2""")
    q = _rows("SELECT INITCAP(status) AS k, COUNT(*) AS n FROM screening_queue GROUP BY 1 ORDER BY 2 DESC")
    return [_monthly_stacked(rows, 'r', tuple(res), res, lambda v: lab.get(v, v), _('Screenings per month by result')),
            _doughnut(q, _('Review queue'), label_fn=lambda k: _status_label(k))]


def _cases():
    rows = _rows("""SELECT case_type AS t,
                           CASE WHEN now() - opened_at::timestamp <= INTERVAL '7 days' THEN 'a'
                                WHEN now() - opened_at::timestamp <= INTERVAL '30 days' THEN 'b'
                                WHEN now() - opened_at::timestamp <= INTERVAL '90 days' THEN 'c' ELSE 'd' END AS b,
                           COUNT(*) AS n
                    FROM cases WHERE UPPER(status) NOT IN ('RESOLVED', 'CLOSED') GROUP BY 1, 2""")
    if not rows:
        return []
    buckets = [('a', _('0–7 days')), ('b', _('8–30 days')), ('c', _('31–90 days')), ('d', _('Over 90 days'))]
    types = sorted({r['t'] for r in rows})
    pal = ['#0d6efd', '#fd7e14', '#6f42c1', '#20c997', '#dc3545', '#6c757d']
    series = [{'name': (t or '').replace('_', ' ').title(), 'stack': 's', 'color': pal[i % len(pal)], 'barMax': 40,
               'data': [sum(r['n'] for r in rows if r['t'] == t and r['b'] == b) for b, _l in buckets]}
              for i, t in enumerate(types)]
    return [{'title': _('Open cases by age'), 'height': 260,
             'note': _('Cases still open, by how long ago they were opened. The right-hand bars need attention first.'),
             'spec': {'kind': 'bar', 'stacked': True, 'labels': [l for _b, l in buckets], 'series': series}}]


def _whistleblowing():
    rows = _rows(f"""SELECT to_char(submitted_at::timestamp, 'YYYY-MM') AS m, 'ALL' AS x, COUNT(*) AS n
                     FROM whistleblowing_cases WHERE submitted_at::timestamp >= {START} GROUP BY 1""")
    st = _rows("SELECT UPPER(status) AS k, COUNT(*) AS n FROM whistleblowing_cases GROUP BY 1 ORDER BY 2 DESC")
    return [_monthly_stacked(rows, 'x', ('ALL',), {'ALL': '#6f42c1'}, lambda v: _('Reports'), _('Reports received per month')),
            _doughnut(st, _('Report status'))]


def _consumer():
    rows = _rows(f"""SELECT to_char(created_at::timestamp, 'YYYY-MM') AS m, 'ALL' AS x, COUNT(*) AS n
                     FROM consumer_complaints WHERE created_at::timestamp >= {START} GROUP BY 1""")
    cat = _rows("""SELECT COALESCE(complaint_category, '—') AS k, COUNT(*) AS n FROM consumer_complaints
                   GROUP BY 1 ORDER BY 2 DESC LIMIT 10""")
    return [_monthly_stacked(rows, 'x', ('ALL',), {'ALL': '#0d6efd'}, lambda v: _('Complaints'), _('Complaints received per month')),
            _hbar(cat, _('Complaints by category'), '#fd7e14', lambda k: (k or '').replace('_', ' ').title())]


def _audit():
    rows = _rows("""SELECT UPPER(severity) AS sev, CASE WHEN UPPER(status) LIKE '%%CLOSED%%' THEN 'closed' ELSE 'open' END AS s,
                           COUNT(*) AS n FROM audit_findings GROUP BY 1, 2""")
    if not rows:
        return []
    sevs = [s for s in SEV_ORDER if any(r['sev'] == s for r in rows)]
    return [{'title': _('Audit findings by severity'), 'height': 240,
             'spec': {'kind': 'bar', 'stacked': True, 'labels': [_sev_label(s) for s in sevs],
                      'series': [{'name': _('Open'), 'stack': 's', 'color': '#dc3545', 'barMax': 40,
                                  'data': [sum(r['n'] for r in rows if r['sev'] == s and r['s'] == 'open') for s in sevs]},
                                 {'name': _('Closed'), 'stack': 's', 'color': '#20c997', 'barMax': 40,
                                  'data': [sum(r['n'] for r in rows if r['sev'] == s and r['s'] == 'closed') for s in sevs]}]}}]


def _data_protection():
    dsr = _rows("SELECT UPPER(status) AS k, COUNT(*) AS n FROM data_subject_requests GROUP BY 1 ORDER BY 2 DESC")
    br = _rows("SELECT UPPER(severity) AS k, COUNT(*) AS n FROM data_breaches GROUP BY 1 ORDER BY 2 DESC")
    return [_doughnut(dsr, _('Data-subject requests by status')),
            _hbar(br, _('Personal-data breaches by severity'), '#dc3545', _sev_label)]


def _overview():
    q = """SELECT k, n FROM (
             SELECT 'tm' AS k, COUNT(*) AS n FROM tm_alerts WHERE UPPER(status) IN ('NEW', 'ASSIGNED', 'IN_PROGRESS')
             UNION ALL SELECT 'queue', COUNT(*) FROM screening_queue WHERE status = 'Pending'
             UNION ALL SELECT 'cases', COUNT(*) FROM cases WHERE UPPER(status) NOT IN ('RESOLVED', 'CLOSED')
             UNION ALL SELECT 'wb', COUNT(*) FROM whistleblowing_cases WHERE UPPER(status) NOT IN ('RESOLVED', 'CLOSED')
             UNION ALL SELECT 'cc', COUNT(*) FROM consumer_complaints WHERE UPPER(status) NOT IN ('RESOLVED', 'CLOSED')
             UNION ALL SELECT 'af', COUNT(*) FROM audit_findings WHERE UPPER(status) NOT LIKE '%%CLOSED%%'
           ) x"""
    lab = {'tm': _('Open monitoring alerts'), 'queue': _('Screening matches to review'), 'cases': _('Open cases'),
           'wb': _('Open whistleblowing reports'), 'cc': _('Open customer complaints'), 'af': _('Open audit findings')}
    rows = sorted(_rows(q), key=lambda r: -r['n'])
    cards = [_hbar(rows, _('Open work across modules'), '#0d6efd', lambda k: lab.get(k, k),
                   note=_('Items still waiting for action. Open the module to work on them.'))]
    cards += _screening()[:1]
    return cards


BUILDERS = {'risk': _risk, 'aml': _aml, 'screening': _screening, 'cases': _cases, 'whistleblowing': _whistleblowing,
            'consumer_protection': _consumer, 'internal_audit': _audit, 'data_protection': _data_protection,
            'overview': _overview}


def module_insights(name):
    fn = BUILDERS.get(name)
    if not fn:
        return []
    try:
        return [c for c in fn() if c]
    except Exception:
        logger.warning('insights for %s failed', name, exc_info=True)
        get_db().rollback()
        return []
