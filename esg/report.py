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

"""ESG period report (Phase 7, H1).

One reporting period, one document: the weighted pillar and indicator scores,
how complete the period is (indicators answered, disclosures done per
framework, materiality topics scored), the materiality matrix with each
topic's quadrant, the disclosure index of every framework tracked for the
period, and the figures other modules contribute (training, whistleblowing,
board, carbon ...).

Everything comes from the ESG data (frameworks, pillars, indicators, responses,
materiality, disclosure items) - no framework, regulator or weight is written
here, so a CBE sustainable-finance or FRA ESG disclosure set is simply the data
loaded into the disclosure tracker. Pure helpers are separate from the queries
so they can be tested without a database.
"""
from datetime import datetime

from database.db import query_db
from esg.engine import build_pillar_summary, MATURITY_LABELS

# materiality scores are on a 1-5 scale; the matrix splits at the midpoint
MATERIALITY_SPLIT = 3.0
QUADRANTS = {
    'priority': ('Priority - report and manage', 'أولوية - يتم الإفصاح عنها وإدارتها'),
    'stakeholder': ('Stakeholder focus', 'اهتمام أصحاب المصلحة'),
    'business': ('Business focus', 'أثر على الأعمال'),
    'monitor': ('Monitor', 'متابعة'),
}
STATUS_LABELS = {
    'complete': ('Complete', 'مكتمل'),
    'partial': ('Partial', 'جزئي'),
    'not_started': ('Not started', 'لم يبدأ'),
    'not_applicable': ('Not applicable', 'لا ينطبق'),
}


# --------------------------------------------------------------------------- pure helpers
def quadrant(importance, impact, split=MATERIALITY_SPLIT):
    """Quadrant code of one materiality topic, or None when it is not scored on both axes."""
    if importance is None or impact is None:
        return None
    hi_i, hi_b = float(importance) >= split, float(impact) >= split
    if hi_i and hi_b:
        return 'priority'
    if hi_i:
        return 'stakeholder'
    if hi_b:
        return 'business'
    return 'monitor'


def materiality_rows(topics, scores_by_topic):
    """topics + {topic_id: score row} -> rows sorted priority first, then by combined score."""
    order = {'priority': 0, 'stakeholder': 1, 'business': 2, 'monitor': 3, None: 4}
    rows = []
    for t in topics:
        s = scores_by_topic.get(t['id']) or {}
        imp, bus = s.get('stakeholder_importance'), s.get('business_impact')
        q = quadrant(imp, bus)
        rows.append({'id': t['id'], 'name': t.get('name'), 'name_ar': t.get('name_ar'),
                     'category': t.get('category'), 'gri_reference': t.get('gri_reference'),
                     'importance': imp, 'impact': bus, 'quadrant': q, 'notes': s.get('notes'),
                     'combined': (float(imp) + float(bus)) if q else None})
    rows.sort(key=lambda r: (order[r['quadrant']], -(r['combined'] or 0), r['name'] or ''))
    return rows


def disclosure_index(items):
    """Disclosure items -> [{framework, rows[], counts{status: n}, applicable, done_pct}] by framework.
    Not-applicable items leave the denominator; a partial item counts half (same rule as the tracker)."""
    out = {}
    for it in items:
        fw = it.get('framework') or '-'
        d = out.setdefault(fw, {'framework': fw, 'rows': [], 'counts': {k: 0 for k in STATUS_LABELS}})
        st = it.get('status') if it.get('status') in STATUS_LABELS else 'not_started'
        d['counts'][st] += 1
        d['rows'].append(dict(it, status=st))
    res = []
    for fw in sorted(out):
        d = out[fw]
        c = d['counts']
        d['total'] = sum(c.values())
        d['applicable'] = d['total'] - c['not_applicable']
        d['done_pct'] = round(100.0 * (c['complete'] + 0.5 * c['partial']) / d['applicable'], 1) if d['applicable'] else None
        d['rows'].sort(key=lambda i: str(i.get('ref_code') or ''))
        res.append(d)
    return res


def gaps(pillars, materiality, index):
    """What still stands between the period and a complete report."""
    out = []
    for p in pillars:
        for i in p['indicators']:
            if i.get('score') is None:
                out.append({'kind': 'indicator', 'ref': i.get('code'), 'name': i.get('name'), 'name_ar': i.get('name_ar'),
                            'where': p.get('name')})
    for m in materiality:
        if not m['quadrant']:
            out.append({'kind': 'materiality', 'ref': m.get('gri_reference'), 'name': m.get('name'),
                        'name_ar': m.get('name_ar'), 'where': m.get('category')})
    for fw in index:
        for it in fw['rows']:
            if it['status'] in ('not_started', 'partial'):
                out.append({'kind': 'disclosure_' + it['status'], 'ref': it.get('ref_code'), 'name': it.get('title'),
                            'name_ar': it.get('title_ar'), 'where': fw['framework']})
    return out


def completeness(summary, materiality, index):
    ind_total = sum(p['indicator_count'] for p in summary['pillars'])
    ind_done = sum(p['answered_count'] for p in summary['pillars'])
    mat_total = len(materiality)
    mat_done = len([m for m in materiality if m['quadrant']])
    applicable = sum(f['applicable'] for f in index)
    done = sum(f['counts']['complete'] + 0.5 * f['counts']['partial'] for f in index)

    def pct(a, b):
        return round(100.0 * a / b, 1) if b else None
    return {'indicators_total': ind_total, 'indicators_answered': ind_done, 'indicators_pct': pct(ind_done, ind_total),
            'materiality_total': mat_total, 'materiality_scored': mat_done, 'materiality_pct': pct(mat_done, mat_total),
            'disclosures_applicable': applicable, 'disclosures_pct': pct(done, applicable)}


# --------------------------------------------------------------------------- the report
def periods():
    return query_db("SELECT * FROM esg_reporting_periods ORDER BY start_date DESC") or []


def build(period_id, framework=None, include_carbon=False):
    """Everything the period report shows, for one reporting period (None if the period does not exist)."""
    from esg import routes as R            # shared helpers (lazy: routes imports this module lazily too)
    from esg import feeds as module_feeds
    period = query_db("SELECT * FROM esg_reporting_periods WHERE id = %s", (period_id,), one=True)
    if not period:
        return None
    framework = framework or R._default_framework()
    pillars = R._pillars_with_indicators(framework['id'], period['id']) if framework else []
    summary = build_pillar_summary(pillars)
    topics = query_db("SELECT * FROM esg_materiality_topics WHERE is_active = TRUE ORDER BY display_order") or []
    scores = query_db("SELECT * FROM esg_materiality_scores WHERE reporting_period_id = %s", (period['id'],)) or []
    materiality = materiality_rows(topics, {s['topic_id']: s for s in scores})
    items = query_db(
        "SELECT d.*, (u.first_name || ' ' || u.last_name) AS owner_name FROM esg_disclosure_items d "
        "LEFT JOIN users u ON d.owner_id = u.id WHERE d.reporting_period_id = %s ORDER BY d.framework, d.ref_code",
        (period['id'],)) or []
    index = disclosure_index([dict(i) for i in items])
    feeds = module_feeds.values(period) or {}
    carbon = None
    if include_carbon:
        try:
            from carbon import links as carbon_links
            carbon = carbon_links.carbon_values(period['id'])
        except Exception:
            carbon = None
    return {
        'period': period, 'framework': framework, 'pillars': pillars, 'summary': summary,
        'materiality': materiality, 'index': index, 'feeds': feeds, 'carbon': carbon,
        'completeness': completeness(summary, materiality, index), 'gaps': gaps(pillars, materiality, index),
        'maturity_labels': MATURITY_LABELS, 'quadrants': QUADRANTS, 'status_labels': STATUS_LABELS,
        'generated_at': datetime.now(),
    }


# --------------------------------------------------------------------------- Excel
def workbook(rep):
    """Bilingual Excel workbook of the period report (one sheet per section)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    # Excel/CSV formula injection: a string a user controls (an evidence note, a
    # topic name …) that starts with one of these is run as a formula when the
    # workbook is opened. Any such string is stored as literal text instead.
    _FORMULA_LEAD = ('=', '+', '-', '@', '\t', '\r')

    def _clean(v):
        if isinstance(v, str):
            # drop control characters openpyxl would otherwise reject outright
            v = ILLEGAL_CHARACTERS_RE.sub('', v)
        return '' if v is None else v

    def sheet(wb, title, header, rows):
        ws = wb.create_sheet(title)
        ws.append([_clean(h) for h in header])
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([_clean(v) for v in r])
            for cell in ws[ws.max_row]:
                if isinstance(cell.value, str) and cell.value[:1] in _FORMULA_LEAD:
                    cell.data_type = 's'   # force literal text, never a formula
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = max(
                12, min(60, max(len(str(c.value or '')) for c in col) + 2))
        return ws

    # scores are shown to 2 decimals, the same precision the printable (PDF)
    # report uses, so the two never disagree on a figure.
    def _r2(v):
        return round(float(v), 2) if v is not None else None

    wb = Workbook()
    wb.remove(wb.active)
    p, s, c = rep['period'], rep['summary'], rep['completeness']
    fw = rep['framework'] or {}
    sheet(wb, 'Summary', ['Item / البند', 'Value / القيمة'], [
        ('Framework / الإطار', fw.get('name')),
        ('Reporting period / فترة التقرير', f"{p['label']} ({p['start_date']} - {p['end_date']})"),
        ('Period status / حالة الفترة', p.get('status')),
        ('Overall score (1-5) / الدرجة الكلية', _r2(s.get('overall_score'))),
        ('Overall score (out of 100) / الدرجة من 100', s.get('overall_pct_100')),
        ('Rating / التقييم', (s.get('overall_rating') or (None,))[0]),
        ('Indicators answered / المؤشرات المجاب عنها', f"{c['indicators_answered']} / {c['indicators_total']}"),
        ('Disclosures done % / نسبة الإفصاحات المكتملة', c['disclosures_pct']),
        ('Materiality topics scored / موضوعات الأهمية النسبية المقيمة', f"{c['materiality_scored']} / {c['materiality_total']}"),
        ('Open gaps / الفجوات المفتوحة', len(rep['gaps'])),
        ('Generated / تاريخ الإعداد', rep['generated_at'].strftime('%Y-%m-%d %H:%M')),
    ])
    sheet(wb, 'Pillars', ['Pillar / الركيزة', 'Pillar (AR)', 'Weight / الوزن', 'Score (1-5) / الدرجة', 'Rating / التقييم',
                          'Answered / المجاب', 'Indicators / المؤشرات', 'Completeness % / الاكتمال'],
          [(x['name'], x.get('name_ar'), x['weight'], _r2(x['score']), (x['rating'] or (None,))[0], x['answered_count'],
            x['indicator_count'], x['completeness_pct']) for x in s['pillars']])
    sheet(wb, 'Indicators', ['Pillar / الركيزة', 'Code / الرمز', 'Indicator / المؤشر', 'Indicator (AR)', 'Weight / الوزن',
                             'Score (1-5) / الدرجة', 'Maturity / مستوى النضج', 'Evidence notes / ملاحظات الدليل'],
          [(pl['name'], i['code'], i['name'], i.get('name_ar'), i['weight'], _r2(i['score']),
            rep['maturity_labels'].get(int(round(i['score']))) if i['score'] is not None else None, i.get('evidence_notes'))
           for pl in rep['pillars'] for i in pl['indicators']])
    sheet(wb, 'Materiality', ['Topic / الموضوع', 'Topic (AR)', 'Category / الفئة', 'GRI ref.', 'Stakeholder importance / أهمية أصحاب المصلحة',
                              'Business impact / الأثر على الأعمال', 'Quadrant / الربع', 'Notes / ملاحظات'],
          [(m['name'], m.get('name_ar'), m.get('category'), m.get('gri_reference'), m['importance'], m['impact'],
            ' / '.join(QUADRANTS[m['quadrant']]) if m['quadrant'] else 'Not scored / غير مقيم', m.get('notes'))
           for m in rep['materiality']])
    sheet(wb, 'Disclosure index', ['Framework / الإطار', 'Ref. / المرجع', 'Disclosure / الإفصاح', 'Disclosure (AR)',
                                   'Status / الحالة', 'Owner / المسؤول', 'Evidence notes / ملاحظات الدليل'],
          [(f['framework'], i.get('ref_code'), i.get('title'), i.get('title_ar'), ' / '.join(STATUS_LABELS[i['status']]),
            i.get('owner_name'), i.get('evidence_notes')) for f in rep['index'] for i in f['rows']])
    sheet(wb, 'Framework coverage', ['Framework / الإطار', 'Items / البنود', 'Applicable / المنطبقة', 'Complete / مكتمل',
                                     'Partial / جزئي', 'Not started / لم يبدأ', 'N/A', 'Done % / الإنجاز'],
          [(f['framework'], f['total'], f['applicable'], f['counts']['complete'], f['counts']['partial'],
            f['counts']['not_started'], f['counts']['not_applicable'], f['done_pct']) for f in rep['index']])
    sheet(wb, 'Gaps', ['Type / النوع', 'Ref. / المرجع', 'Item / البند', 'Item (AR)', 'Where / الموضع'],
          [(g['kind'], g.get('ref'), g.get('name'), g.get('name_ar'), g.get('where')) for g in rep['gaps']])
    rows = [(k, v) for k, v in sorted((rep['feeds'] or {}).items())]
    if rep.get('carbon'):
        rows += [('carbon.' + str(k), v) for k, v in sorted(rep['carbon'].items()) if not isinstance(v, (dict, list))]
    sheet(wb, 'From other modules', ['Metric / المؤشر', 'Value / القيمة'], rows)
    return wb
