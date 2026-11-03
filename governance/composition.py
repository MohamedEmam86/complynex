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

"""Board and committee composition checks (Phase 7, H3).

Each committee already carries its own requirements as data (board_committees:
minimum / maximum members, minimum independent members, a financial expert,
meetings per year, quorum, charter review date). This module turns those
requirements into findings, plus member-level findings for the whole board
(term ended, fit & proper review overdue, independence declaration older than a
year). Nothing here hard-codes a regulator's numbers: a committee with no
minimum set is simply not checked for it.

`check_committee()` / `check_members()` are pure so they can be tested without a database.
"""
from datetime import date, datetime, timedelta

SEVERITY_ORDER = {'high': 0, 'medium': 1, 'low': 2}


def _d(v):
    if v in (None, ''):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _yes(v):
    return str(v).strip().lower() in ('1', 'true', 't', 'yes', 'y')


def _f(code, severity, message, message_ar, **kw):
    """A finding; the message is rendered with its parameters (en / ar) by the page."""
    return dict({'code': code, 'severity': severity, 'message': message, 'message_ar': message_ar, 'params': kw})


def check_committee(c, members, meetings_last_12m, today=None):
    """c: board_committees row; members: active memberships joined with board_members
    (is_independent, status, skills_financial, has_required_expertise, member_id, role);
    meetings_last_12m: meetings held in the last 12 months. Returns findings."""
    today = today or date.today()
    out = []
    active = [m for m in members if str(m.get('status') or 'ACTIVE').upper() == 'ACTIVE']
    n = len(active)
    independent = [m for m in active if _yes(m.get('is_independent'))]
    if c.get('min_members') and n < int(c['min_members']):
        out.append(_f('min_members', 'high', 'Has %(n)s active members; the minimum is %(m)s.',
                      'عدد الأعضاء النشطين %(n)s والحد الأدنى %(m)s.', n=n, m=c['min_members']))
    if c.get('max_members') and n > int(c['max_members']):
        out.append(_f('max_members', 'medium', 'Has %(n)s active members; the maximum is %(m)s.',
                      'عدد الأعضاء النشطين %(n)s والحد الأقصى %(m)s.', n=n, m=c['max_members']))
    if c.get('min_independent_members') and len(independent) < int(c['min_independent_members']):
        out.append(_f('independence', 'high', '%(n)s independent members; at least %(m)s are required.',
                      'عدد الأعضاء المستقلين %(n)s والمطلوب %(m)s على الأقل.', n=len(independent), m=c['min_independent_members']))
    if _yes(c.get('requires_financial_expert')):
        expert = [m for m in active if _yes(m.get('has_required_expertise')) or (m.get('skills_financial') or 0) >= 4]
        if not expert:
            out.append(_f('financial_expert', 'high', 'No member with recognised financial expertise.',
                          'لا يوجد عضو لديه خبرة مالية معتمدة.'))
    chair = c.get('chairman_id')
    if not chair:
        out.append(_f('no_chair', 'medium', 'No chair is appointed.', 'لم يتم تعيين رئيس للجنة.'))
    elif chair not in {m.get('member_id') for m in active}:
        out.append(_f('chair_not_member', 'medium', 'The chair is not an active member of the committee.',
                      'رئيس اللجنة ليس عضواً نشطاً فيها.'))
    if c.get('min_meetings_per_year') and meetings_last_12m < int(c['min_meetings_per_year']):
        out.append(_f('meetings', 'medium', '%(n)s meetings in the last 12 months; the minimum is %(m)s.',
                      'عدد الاجتماعات في آخر 12 شهراً %(n)s والحد الأدنى %(m)s.', n=meetings_last_12m, m=c['min_meetings_per_year']))
    if c.get('quorum_number') and n < int(c['quorum_number']):
        out.append(_f('quorum', 'high', 'Fewer active members (%(n)s) than the quorum (%(m)s): it cannot meet validly.',
                      'عدد الأعضاء النشطين (%(n)s) أقل من النصاب (%(m)s): لا يمكن انعقادها صحيحاً.', n=n, m=c['quorum_number']))
    review = _d(c.get('charter_next_review'))
    if review and review < today:
        out.append(_f('charter', 'low', 'Charter review was due on %(d)s.', 'موعد مراجعة الميثاق كان %(d)s.', d=review.isoformat()))
    elif not c.get('charter_file') and not review:
        out.append(_f('charter_missing', 'low', 'No charter or charter review date is recorded.',
                      'لا يوجد ميثاق أو موعد مراجعة مسجل.'))
    return sorted(out, key=lambda f: SEVERITY_ORDER[f['severity']])


def check_members(members, today=None):
    """Board-level findings per active member."""
    today = today or date.today()
    out = []
    for m in members:
        if str(m.get('status') or '').upper() != 'ACTIVE':
            continue
        name = m.get('member_name') or ''
        end = _d(m.get('term_end_date'))
        if end and end < today:
            out.append(_f('term_ended', 'high', 'Term ended on %(d)s but the member is still active.',
                          'انتهت مدة العضوية في %(d)s والعضو ما زال نشطاً.', d=end.isoformat(),
                          member=name, member_id=m.get('id')))
        fp = _d(m.get('fit_proper_next_review'))
        if fp and fp < today:
            out.append(_f('fit_proper', 'high', 'Fit and proper review overdue since %(d)s.',
                          'تقييم الملاءمة متأخر منذ %(d)s.', d=fp.isoformat(),
                          member=name, member_id=m.get('id')))
        if _yes(m.get('is_independent')):
            dec = _d(m.get('independence_declaration_date'))
            if not dec:
                out.append(_f('independence_declaration', 'medium', 'Counted as independent without an independence declaration.',
                              'مسجل كمستقل بدون إقرار استقلالية.',
                              member=name, member_id=m.get('id')))
            elif dec < today - timedelta(days=365):
                out.append(_f('independence_declaration', 'medium', 'Independence declaration older than a year (%(d)s).',
                              'إقرار الاستقلالية أقدم من سنة (%(d)s).',
                              d=dec.isoformat(), member=name, member_id=m.get('id')))
    return sorted(out, key=lambda f: (SEVERITY_ORDER[f['severity']], f['params'].get('member') or ''))


def build():
    """Findings for every active committee and the board (database)."""
    from database.db import query_db
    from models.governance import SAFE_MEETING_DATE
    committees = query_db("SELECT * FROM board_committees WHERE COALESCE(is_active, 1) = 1 ORDER BY committee_name") or []
    members = query_db("SELECT * FROM board_members WHERE COALESCE(is_deleted, 0) = 0 ORDER BY member_name") or []
    out = []
    for c in committees:
        mem = query_db("""SELECT cm.member_id, cm.role, cm.has_required_expertise, bm.member_name, bm.is_independent,
                                 bm.status, bm.skills_financial
                          FROM committee_memberships cm JOIN board_members bm ON bm.id = cm.member_id
                          WHERE cm.committee_id = %s AND COALESCE(cm.is_active, 1) = 1
                            AND COALESCE(bm.is_deleted, 0) = 0""", (c['id'],)) or []
        held = query_db(f"""SELECT COUNT(*) AS n FROM board_meetings WHERE committee_id = %s
                            AND UPPER(COALESCE(status, '')) NOT IN ('CANCELLED', 'CANCELED', 'POSTPONED')
                            AND {SAFE_MEETING_DATE} BETWEEN CURRENT_DATE - INTERVAL '12 months' AND CURRENT_DATE""",
                        (c['id'],), one=True)
        n_held = int((held or {}).get('n') or 0)
        mem = [dict(m) for m in mem]
        out.append({'committee': c, 'members': mem, 'meetings_12m': n_held,
                    'independent': len([m for m in mem if _yes(m.get('is_independent'))]),
                    'findings': check_committee(dict(c), mem, n_held)})
    return {'committees': out, 'board': check_members([dict(m) for m in members]),
            'active_members': len([m for m in members if str(m.get('status') or '').upper() == 'ACTIVE'])}
