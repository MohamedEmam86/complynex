# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Social and governance figures that other ComplyNex modules already hold, shown next
to the ESG indicators and disclosure items they answer (like the Carbon feed).

Nothing is written to ESG: the figure is evidence for the person who scores or
completes the item. A row is matched by its reference and wording (English or
Arabic); each metric degrades to "no data" when its module is not in use.
"""
import re
from datetime import date

from flask_babel import gettext as _

from database.db import get_db

RULES = (
    ('training', re.compile(r'404-1|training hours|hours of training|training\s*&\s*development|employee development|'
                            r'ساعات التدريب|تدريب العاملين|تطوير العاملين', re.I)),
    ('data_protection', re.compile(r'418-1|privacy|data protection|خصوصية|حماية البيانات', re.I)),
    ('whistleblowing', re.compile(r'whistleblow|speak-up|grievance|الإبلاغ عن المخالفات|التظلمات', re.I)),
    ('complaints', re.compile(r'consumer protection|customer protection|complaint volume|حماية العملاء|شكاوى العملاء', re.I)),
    ('coi', re.compile(r'conflicts? of interest|تعارض المصالح', re.I)),
    ('ethics', re.compile(r'code of (business )?(ethics|conduct)|ethical conduct|ميثاق|السلوك الأخلاقي|أخلاقيات', re.I)),
    ('board', re.compile(r'\b2-9\b|board (composition|structure)|independence|تشكيل مجلس|استقلالية|هيكل مجلس', re.I)),
    ('policies', re.compile(r'policy governance|review cadence|حوكمة السياسات', re.I)),
)
MODULES = {'training': ('bi-mortarboard', 'Training'), 'data_protection': ('bi-shield-lock', 'Data protection'),
           'whistleblowing': ('bi-megaphone', 'Whistleblowing'), 'complaints': ('bi-chat-left-text', 'Consumer protection'),
           'coi': ('bi-person-exclamation', 'Conflicts of interest'), 'ethics': ('bi-patch-check', 'Code of conduct'),
           'board': ('bi-people', 'Governance'), 'policies': ('bi-journal-text', 'Policies')}


def detect(*texts):
    t = ' '.join(x for x in texts if x)
    for metric, rx in RULES:
        if rx.search(t):
            return metric
    return None


def _one(sql, params=()):
    db = get_db()
    try:
        r = db.execute(sql, params).fetchone()
        return dict(r) if r else {}
    except Exception:
        db.rollback()
        return None


def _pct(a, b):
    return round(100.0 * a / b) if b else None


def values(period):
    """{metric: text} for one reporting period (dates from esg_reporting_periods)."""
    if not period:
        return {}
    s, e = period['start_date'], period['end_date']
    out = {}
    staff = (_one("SELECT COUNT(*) AS n FROM users WHERE is_active::int = 1") or {}).get('n') or 0

    t = _one("""SELECT COUNT(*) FILTER (WHERE en.status = 'completed' AND en.completion_date::date BETWEEN %s AND %s) AS done,
                       COUNT(*) FILTER (WHERE en.due_date::date BETWEEN %s AND %s) AS due,
                       COUNT(*) FILTER (WHERE en.due_date::date BETWEEN %s AND %s AND en.status = 'completed') AS due_done,
                       COALESCE(SUM(c.duration_minutes) FILTER (WHERE en.status = 'completed'
                                AND en.completion_date::date BETWEEN %s AND %s), 0) AS minutes
                FROM training_enrollments en LEFT JOIN training_courses c ON c.id = en.course_id""", (s, e) * 4)
    if t and (t['done'] or t['due']):
        hours = round(float(t['minutes'] or 0) / 60.0 / staff, 1) if staff else None
        out['training'] = _('%(h)s training hours per employee · %(n)s courses completed · %(p)s%% of due courses on time',
                            h=hours if hours is not None else '-', n=t['done'], p=_pct(t['due_done'], t['due']) or 0)

    w = _one("""SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE status = 'RESOLVED') AS resolved
                FROM whistleblowing_cases WHERE submitted_at::date BETWEEN %s AND %s""", (s, e))
    if w and w['n']:
        out['whistleblowing'] = _('%(n)s reports received · %(r)s resolved', n=w['n'], r=w['resolved'])

    c = _one("""SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE status IN ('RESOLVED', 'CLOSED')) AS closed
                FROM consumer_complaints WHERE created_at::date BETWEEN %s AND %s""", (s, e))
    if c and c['n']:
        out['complaints'] = _('%(n)s customer complaints · %(p)s%% resolved or closed', n=c['n'], p=_pct(c['closed'], c['n']) or 0)

    b = _one("""SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE pdpc_notified::text IN ('1', 'true', 't')) AS notified
                FROM data_breaches WHERE breach_date::date BETWEEN %s AND %s""", (s, e))
    if b is not None:
        out['data_protection'] = _('%(n)s personal-data breaches recorded in the period · %(m)s notified to the regulator',
                                   n=b.get('n') or 0, m=b.get('notified') or 0)

    k = _one("""SELECT COUNT(DISTINCT employee_id) AS n, COUNT(*) FILTER (WHERE has_conflict::text IN ('1', 'true', 't')) AS conflicts
                FROM coi_declarations WHERE declaration_date::date BETWEEN %s AND %s""", (s, e))
    if k and k['n']:
        out['coi'] = _('%(n)s staff declared (%(p)s%% of active users) · %(c)s conflicts declared', n=k['n'],
                       p=_pct(k['n'], staff) or 0, c=k['conflicts'])

    y = e.year if isinstance(e, date) else int(str(e)[:4])
    x = _one("""SELECT COUNT(DISTINCT employee_id) AS n FROM cobec_declarations WHERE declaration_year::text = %s""", (str(y),))
    if x and x['n']:
        out['ethics'] = _('%(n)s staff attested the code of conduct for %(y)s (%(p)s%% of active users)', n=x['n'], y=y,
                          p=_pct(x['n'], staff) or 0)

    bd = _one("""SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE is_independent::text IN ('1', 'true', 't')) AS ind
                 FROM board_members WHERE UPPER(status) = 'ACTIVE'""")
    if bd and bd['n']:
        out['board'] = _('%(n)s active board members · %(p)s%% independent', n=bd['n'], p=_pct(bd['ind'], bd['n']) or 0)

    p = _one("""SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE next_review_date::date < CURRENT_DATE) AS overdue
                FROM policies WHERE LOWER(status) IN ('active', 'approved', 'published')""")
    if p and p['n']:
        out['policies'] = _('%(n)s active policies · %(o)s past their review date', n=p['n'], o=p['overdue'])
    return out


def feed(row, vals, *fields):
    """{'metric', 'text', 'icon', 'module'} for an ESG row, or None."""
    if not vals:
        return None
    m = detect(*[(row or {}).get(f) for f in fields])
    if not m or m not in vals:
        return None
    icon, module = MODULES[m]
    return {'metric': m, 'text': vals[m], 'icon': icon, 'module': _(module)}
