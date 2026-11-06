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
    if _yes(c.get('independent_majority')) and n and len(independent) * 2 <= n:
        out.append(_f('independent_majority', 'high', 'Independent members are not a majority (%(n)s of %(m)s).',
                      'الأعضاء المستقلون ليسوا أغلبية (%(n)s من %(m)s).', n=len(independent), m=n))
    chair = c.get('chairman_id')
    chair_row = next((m for m in active if m.get('member_id') == chair), None) if chair else None
    if chair_row and _yes(c.get('independent_chair')) and not _yes(chair_row.get('is_independent')):
        out.append(_f('independent_chair', 'high', 'The chair is not independent.', 'رئيس اللجنة غير مستقل.'))
    if chair_row and _yes(c.get('non_executive_chair')) and _yes(chair_row.get('is_executive')):
        out.append(_f('non_executive_chair', 'high', 'The chair is an executive member.', 'رئيس اللجنة عضو تنفيذي.'))
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


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def check_board(members, rules, meetings_12m=None, today=None):
    """Board-level composition findings for one board.
    members: active members as dicts {id, member_name, gender ('F'/'M'/None), flags (set of capacity
    flags: chair, md, ceo, chair_md, executive, non_executive, independent ...), independent_since (date)};
    rules: gov_composition_rules rows chosen for the board (an empty value is not checked);
    meetings_12m: board meetings held in the last 12 months."""
    today = today or date.today()
    out = []
    n = len(members)
    execs = [m for m in members if 'executive' in m['flags']]
    non_exec = [m for m in members if 'executive' not in m['flags']]
    indep = [m for m in members if 'independent' in m['flags']]
    women = [m for m in members if (m.get('gender') or '').upper() == 'F']
    unknown_gender = [m for m in members if not m.get('gender')]
    chairs = [m for m in members if m['flags'] & {'chair', 'chair_md'}]
    for r in rules or ():
        ref = dict(rule=r.get('name_en'), rule_ar=r.get('name_ar') or r.get('name_en'), legal_ref=r.get('legal_ref') or '')

        def add(code, sev, en, ar, **kw):
            out.append(_f(code, sev, en, ar, **dict(ref, **kw)))
        if r.get('min_board_size') and n < int(r['min_board_size']):
            add('board_size', 'high', 'The board has %(n)s members; at least %(m)s are required.',
                'عدد أعضاء المجلس %(n)s والمطلوب %(m)s على الأقل.', n=n, m=r['min_board_size'])
        if r.get('max_board_size') and n > int(r['max_board_size']):
            add('board_size_max', 'medium', 'The board has %(n)s members; the maximum is %(m)s.',
                'عدد أعضاء المجلس %(n)s والحد الأقصى %(m)s.', n=n, m=r['max_board_size'])
        if _yes(r.get('non_exec_majority')) and n and len(non_exec) * 2 <= n:
            add('non_exec_majority', 'high', 'Non-executive members are not a majority (%(n)s of %(m)s).',
                'الأعضاء غير التنفيذيين ليسوا أغلبية (%(n)s من %(m)s).', n=len(non_exec), m=n)
        if r.get('min_indep_share_of_non_exec') not in (None, '') and non_exec and \
                _pct(len(indep), len(non_exec)) < float(r['min_indep_share_of_non_exec']):
            add('indep_of_non_exec', 'high', 'Independent members are %(p)s%% of the non-executives; at least %(m)s%% are required.',
                'المستقلون %(p)s%% من غير التنفيذيين والمطلوب %(m)s%% على الأقل.',
                p=_pct(len(indep), len(non_exec)), m=float(r['min_indep_share_of_non_exec']))
        if r.get('min_indep_share_of_board') not in (None, '') and n and _pct(len(indep), n) < float(r['min_indep_share_of_board']):
            add('indep_of_board', 'high', 'Independent members are %(p)s%% of the board; at least %(m)s%% are required.',
                'المستقلون %(p)s%% من المجلس والمطلوب %(m)s%% على الأقل.', p=_pct(len(indep), n), m=float(r['min_indep_share_of_board']))
        if r.get('min_independent_count') and len(indep) < int(r['min_independent_count']):
            add('indep_count', 'high', '%(n)s independent members; at least %(m)s are required.',
                'عدد المستقلين %(n)s والمطلوب %(m)s على الأقل.', n=len(indep), m=r['min_independent_count'])
        if r.get('max_executives') not in (None, '') and len(execs) > int(r['max_executives']):
            add('max_execs', 'high', '%(n)s executive members; at most %(m)s are allowed.',
                'عدد التنفيذيين %(n)s والحد الأقصى %(m)s.', n=len(execs), m=r['max_executives'])
        if r.get('min_executives') and len(execs) < int(r['min_executives']):
            add('min_execs', 'medium', '%(n)s executive members; at least %(m)s are required.',
                'عدد التنفيذيين %(n)s والمطلوب %(m)s على الأقل.', n=len(execs), m=r['min_executives'])
        if r.get('min_women_share') not in (None, '') and n and _pct(len(women), n) < float(r['min_women_share']):
            add('women_share', 'high', 'Women are %(p)s%% of the board; at least %(m)s%% are required.',
                'نسبة السيدات %(p)s%% من المجلس والمطلوب %(m)s%% على الأقل.', p=_pct(len(women), n), m=float(r['min_women_share']))
        if r.get('min_women_count') and len(women) < int(r['min_women_count']):
            add('women_count', 'high', '%(n)s women on the board; at least %(m)s are required.',
                'عدد السيدات في المجلس %(n)s والمطلوب %(m)s على الأقل.', n=len(women), m=r['min_women_count'])
        if (r.get('min_women_share') not in (None, '') or r.get('min_women_count')) and unknown_gender:
            add('gender_unknown', 'low', 'Gender is not recorded for %(n)s members, so the women share may be understated.',
                'لم يُسجل النوع لـ %(n)s أعضاء، لذا قد تكون نسبة السيدات أقل من الحقيقية.', n=len(unknown_gender))
        if _yes(r.get('chair_ceo_separate')):
            for c in chairs:
                if c['flags'] & {'ceo', 'md', 'chair_md'}:
                    add('chair_ceo', 'medium', 'The chair is also the managing director / CEO: record the justification.',
                        'رئيس المجلس هو العضو المنتدب / الرئيس التنفيذي: يجب تسجيل المبرر.', member=c.get('member_name'),
                        member_id=c.get('id'))
        yrs = r.get('independence_max_years')
        if yrs:
            for m in indep:
                since = _d(m.get('independent_since'))
                if since and (today - since).days >= int(yrs) * 365.25:
                    add('independence_clock', 'high', 'Counted as independent since %(d)s: more than %(m)s consecutive years.',
                        'مستقل منذ %(d)s: أكثر من %(m)s سنوات متتالية.', d=since.isoformat(), m=yrs,
                        member=m.get('member_name'), member_id=m.get('id'))
                elif since and (today - since).days >= (int(yrs) - 1) * 365.25:
                    add('independence_clock_soon', 'low', 'Independent since %(d)s: the %(m)s-year limit is reached within a year.',
                        'مستقل منذ %(d)s: يكتمل حد %(m)s سنوات خلال سنة.', d=since.isoformat(), m=yrs,
                        member=m.get('member_name'), member_id=m.get('id'))
        if r.get('min_board_meetings_per_year') and meetings_12m is not None and meetings_12m < int(r['min_board_meetings_per_year']):
            add('board_meetings', 'medium', '%(n)s board meetings in the last 12 months; at least %(m)s are required.',
                'عدد اجتماعات المجلس في آخر 12 شهراً %(n)s والمطلوب %(m)s على الأقل.', n=meetings_12m,
                m=r['min_board_meetings_per_year'])
    if len(chairs) > 1:
        out.append(_f('two_chairs', 'medium', '%(n)s members hold the chair role at the same time.',
                      'يشغل %(n)s أعضاء منصب الرئيس في نفس الوقت.', n=len(chairs)))
    stats = dict(n=n, executives=len(execs), non_executives=len(non_exec), independent=len(indep), women=len(women),
                 independent_pct=_pct(len(indep), n), non_exec_pct=_pct(len(non_exec), n), women_pct=_pct(len(women), n),
                 gender_unknown=len(unknown_gender))
    return sorted(out, key=lambda f: SEVERITY_ORDER[f['severity']]), stats


def build_boards(db=None):
    """Board-level findings per board (gov_entities)."""
    from database.db import get_db
    from models.governance import SAFE_MEETING_DATE
    from governance.register import member_caps, flags_of, composition_rules, default_entity_id, entity_clause
    db = db or get_db()
    dflt = default_entity_id(db)
    out = []
    for e in db.execute("SELECT * FROM gov_entities WHERE is_active ORDER BY sort_order, id").fetchall():
        e = dict(e)
        clause, args = entity_clause('bm', e['id'], dflt)
        mem = [dict(r) for r in db.execute(f"""SELECT bm.* FROM board_members bm WHERE {clause}
                 AND bm.status = 'ACTIVE' AND COALESCE(bm.is_deleted, 0) = 0 ORDER BY bm.member_name""", args).fetchall()]
        if not mem and not e.get('is_default'):
            continue
        caps = member_caps(db, [m['id'] for m in mem])
        for m in mem:
            mc = caps.get(m['id'], [])
            m['flags'] = flags_of(mc, m)
            ind = [c for c in mc if c.get('flag') == 'independent']
            m['independent_since'] = min((c['effective_from'] for c in ind if c.get('effective_from')), default=None)
        mclause, margs = entity_clause('m', e['id'], dflt)
        held = db.execute(f"""SELECT COUNT(*) AS n FROM board_meetings m WHERE {mclause} AND m.committee_id IS NULL
                  AND COALESCE(m.body, 'BOARD') = 'BOARD' AND UPPER(COALESCE(m.status, '')) NOT IN ('CANCELLED', 'CANCELED', 'POSTPONED')
                  AND {SAFE_MEETING_DATE.replace('meeting_date', 'm.meeting_date')} BETWEEN CURRENT_DATE - INTERVAL '12 months' AND CURRENT_DATE""",
                          margs).fetchone()['n']
        rules = composition_rules(db, e.get('rule_codes'))
        findings, stats = check_board(mem, rules, int(held or 0))
        out.append(dict(entity=e, rules=rules, findings=findings, stats=stats, meetings_12m=int(held or 0)))
    return out


def build():
    """Findings for every active committee and the board (database)."""
    from database.db import query_db
    from models.governance import SAFE_MEETING_DATE
    committees = query_db("SELECT * FROM board_committees WHERE COALESCE(is_active, 1) = 1 ORDER BY committee_name") or []
    members = query_db("SELECT * FROM board_members WHERE COALESCE(is_deleted, 0) = 0 ORDER BY member_name") or []
    out = []
    for c in committees:
        mem = query_db("""SELECT cm.member_id, cm.role, cm.has_required_expertise, bm.member_name, bm.is_independent,
                                 bm.is_executive, bm.status, bm.skills_financial
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
    try:
        boards = build_boards()
    except Exception:   # the board tables of this release are not migrated yet
        from database.db import get_db
        get_db().rollback()
        boards = []
    return {'committees': out, 'board': check_members([dict(m) for m in members]), 'boards': boards,
            'active_members': len([m for m in members if str(m.get('status') or '').upper() == 'ACTIVE'])}
