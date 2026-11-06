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

"""Pure rules of the board-meeting record and the resolutions register
(no database): quorum, majority, resolution numbers, follow-up status,
attendance statistics and attendance alerts. Every number (fractions, minimums,
majority type, filing days, alert thresholds) comes from configuration rows
(gov_meeting_rules, gov_composition_rules) passed in as dicts.
"""
import math
from datetime import date, datetime, timedelta

BODIES = ('BOARD', 'COMMITTEE', 'OGM', 'EGM')
KINDS = ('ORDINARY', 'EXTRAORDINARY', 'CIRCULATION')
MODES = ('IN_PERSON', 'REMOTE', 'HYBRID')
# attendance codes stored in meeting_attendance.attendance_status (legacy-compatible) + mode flag
ATTENDANCE = ('IN_PERSON', 'REMOTE', 'PROXY', 'ABSENT_EXCUSED', 'ABSENT_UNEXCUSED')
VOTES = ('FOR', 'AGAINST', 'ABSTAIN', 'RECUSED', 'ABSENT')
OUTCOMES = ('APPROVED', 'REJECTED', 'DEFERRED', 'GA_RATIFICATION', 'RECOMMENDATION')
MAJORITY_RULES = ('SIMPLE_CAST', 'SIMPLE_PRESENT', 'TWO_THIRDS', 'THREE_QUARTERS', 'UNANIMOUS')
LINK_TYPES = ('AMENDS', 'SUPERSEDES', 'REVOKES', 'IMPLEMENTS', 'RATIFIES')
FOLLOWUP = ('NOT_STARTED', 'IN_PROGRESS', 'DONE', 'NOT_REQUIRED', 'CANCELLED')
FOLLOWUP_CLOSED = ('DONE', 'NOT_REQUIRED', 'CANCELLED')
MINUTES_STATES = ('DRAFT', 'APPROVED', 'SIGNED')
BODY_PREFIX = {'BOARD': 'BOD', 'OGM': 'OGM', 'EGM': 'EGM', 'COMMITTEE': 'COM'}


def as_date(v):
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


def _num(v, default=None):
    if v in (None, ''):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _yes(v):
    return v is True or str(v).strip().lower() in ('1', 'true', 't', 'yes', 'y', 'on')


# ------------------------------------------------------------------ attendance
def attendance_code(row):
    """Attendance code of a meeting_attendance row (legacy columns included)."""
    st = str(row.get('attendance_status') or '').upper()
    if st in ATTENDANCE:
        return st
    if _yes(row.get('attended')):
        return 'REMOTE' if _yes(row.get('attended_remotely')) else 'IN_PERSON'
    if (row.get('proxy_name') or '').strip() or row.get('proxy_holder_member_id') or st == 'REPRESENTED_BY_PROXY':
        return 'PROXY'
    if not st and not row.get('recorded_at'):
        return None   # invited, not recorded yet
    return 'ABSENT_EXCUSED' if (_yes(row.get('apology_received')) or st == 'ABSENT_WITH_APOLOGY') else 'ABSENT_UNEXCUSED'


def legacy_columns(code):
    """Columns written for an attendance code so the older pages keep reading it."""
    return {
        'IN_PERSON': dict(attended=1, attended_remotely=0, apology_received=0, attendance_status='PRESENT'),
        'REMOTE': dict(attended=1, attended_remotely=1, apology_received=0, attendance_status='PRESENT'),
        'PROXY': dict(attended=0, attended_remotely=0, apology_received=0, attendance_status='REPRESENTED_BY_PROXY'),
        'ABSENT_EXCUSED': dict(attended=0, attended_remotely=0, apology_received=1, attendance_status='ABSENT_WITH_APOLOGY'),
        'ABSENT_UNEXCUSED': dict(attended=0, attended_remotely=0, apology_received=0, attendance_status='ABSENT'),
    }[code]


def proxy_errors(rows):
    """rows: [{member_id, code, proxy_holder_member_id, member_name}] for one meeting.
    A proxy must be held by another member who is present; one member holds one proxy at most."""
    errors = []
    by_id = {r['member_id']: r for r in rows}
    held = {}
    for r in rows:
        if r.get('code') != 'PROXY':
            continue
        h = r.get('proxy_holder_member_id')
        if not h:
            errors.append(('proxy_holder_missing', r.get('member_name')))
            continue
        if h == r['member_id']:
            errors.append(('proxy_self', r.get('member_name')))
            continue
        holder = by_id.get(h)
        if not holder or holder.get('code') not in ('IN_PERSON', 'REMOTE'):
            errors.append(('proxy_holder_absent', r.get('member_name')))
        held[h] = held.get(h, 0) + 1
    for h, n in held.items():
        if n > 1:
            errors.append(('proxy_one_only', (by_id.get(h) or {}).get('member_name')))
    return errors


# ------------------------------------------------------------------ quorum
def required_count(total, qtype, fraction, minimum=None):
    """Head count needed: MAJORITY = more than fraction x total; AT_LEAST = fraction x total or more."""
    total = int(total or 0)
    f = _num(fraction, 0.5)
    if qtype == 'AT_LEAST':
        need = math.ceil(round(total * f, 6))
    else:
        need = int(math.floor(round(total * f, 6))) + 1
    if minimum:
        need = max(need, int(minimum))
    return need


def _flag(rule, key, default=True):
    v = (rule or {}).get(key)
    return default if v is None else _yes(v)


def quorum_counts(rows, rule=None):
    """{'IN_PERSON', 'REMOTE', 'PROXY'} counted for the quorum from attendance rows
    [{member_id, code, proxy_holder_member_id, voting}]: only members with a vote; a proxy
    counts only when its holder is counted himself (present, or remote when remote counts)."""
    voters = [r for r in rows if r.get('voting', True)]
    by_id = {r['member_id']: r for r in voters}
    remote_ok = _flag(rule, 'count_remote')
    c = {'IN_PERSON': 0, 'REMOTE': 0, 'PROXY': 0}
    for r in voters:
        if r.get('code') in ('IN_PERSON', 'REMOTE'):
            c[r['code']] += 1
    for r in voters:
        if r.get('code') == 'PROXY':
            h = by_id.get(r.get('proxy_holder_member_id'))
            if h and (h.get('code') == 'IN_PERSON' or (h.get('code') == 'REMOTE' and remote_ok)):
                c['PROXY'] += 1
    return c


def quorum(rule, total_members, counts, call_no=1, capital_pct=None):
    """rule: gov_meeting_rules row (or the meeting's snapshot of it);
    counts: {'IN_PERSON': n, 'REMOTE': n, 'PROXY': n} (see quorum_counts);
    returns {valid, required, counted, basis, call_no, threshold, personal, min_personal}."""
    rule = rule or {}
    call_no = int(call_no or 1)
    qtype, frac, mn = rule.get('quorum_type') or 'MAJORITY', rule.get('quorum_fraction'), rule.get('quorum_min')
    if call_no >= 2 and rule.get('second_call_type'):
        qtype, frac = rule['second_call_type'], rule.get('second_call_fraction')
        if rule.get('second_call_min') not in (None, ''):
            mn = rule.get('second_call_min')
    if frac in (None, ''):
        frac = 0.5
    if (rule.get('quorum_basis') or 'MEMBERS') == 'CAPITAL':
        pct = _num(capital_pct)
        thr = round(_num(frac, 0) * 100, 3)
        if pct is None:
            return dict(valid=None, required=thr, counted=None, basis='CAPITAL', call_no=call_no, threshold=thr)
        ok = pct > thr if qtype == 'MAJORITY' else pct >= thr
        return dict(valid=ok, required=thr, counted=pct, basis='CAPITAL', call_no=call_no, threshold=thr)
    personal = int(counts.get('IN_PERSON', 0))
    if _flag(rule, 'count_remote'):
        personal += int(counts.get('REMOTE', 0))
    counted = personal + (int(counts.get('PROXY', 0)) if _flag(rule, 'count_proxies') else 0)
    need = required_count(total_members, qtype, frac, mn)
    min_personal = int(rule['min_personal']) if rule.get('min_personal') not in (None, '') else None
    valid = bool(total_members) and counted >= need and (min_personal is None or personal >= min_personal)
    return dict(valid=valid, required=need, counted=counted, basis='MEMBERS', call_no=call_no, threshold=None,
                personal=personal, min_personal=min_personal)


# ------------------------------------------------------------------ majority
def tally(votes):
    t = {v: 0 for v in VOTES}
    for v in votes:
        v = str(v or '').upper()
        if v in t:
            t[v] += 1
    return t


def majority(rule_code, votes, chair_vote=None, casting=True, eligible=None):
    """votes: list of vote codes of the members on the body (FOR/AGAINST/ABSTAIN/RECUSED/ABSENT).
    eligible = members present and entitled to vote (recused and absent excluded).
    Returns (achieved, required, note) — required is the FOR votes needed."""
    t = tally(votes)
    f, a, ab = t['FOR'], t['AGAINST'], t['ABSTAIN']
    if eligible is None:
        eligible = f + a + ab
    rule_code = rule_code if rule_code in MAJORITY_RULES else 'SIMPLE_PRESENT'
    if eligible <= 0:
        return False, 0, 'no eligible votes'
    if rule_code == 'SIMPLE_CAST':
        need = a + 1
        ok = f > a
        if f == a and f > 0 and casting and str(chair_vote or '').upper() == 'FOR':
            return True, need, 'tie broken by the chair\'s casting vote'
        return ok, need, 'more votes for than against'
    if rule_code == 'SIMPLE_PRESENT':
        need = eligible // 2 + 1
        ok = f >= need
        if not ok and casting and f == a and f > 0 and str(chair_vote or '').upper() == 'FOR':
            return True, need, 'tie broken by the chair\'s casting vote'
        return ok, need, 'more than half of the members present and voting'
    if rule_code == 'TWO_THIRDS':
        need = math.ceil(round(eligible * 2 / 3, 6))
        return f >= need, need, 'two thirds of the members present'
    if rule_code == 'THREE_QUARTERS':
        need = math.ceil(round(eligible * 3 / 4, 6))
        return f >= need, need, 'three quarters of the members present'
    need = eligible
    return f == eligible, need, 'all members present'


def suggested_outcome(achieved, chosen=None):
    """Outcome to store: a chosen DEFERRED / GA_RATIFICATION / RECOMMENDATION is kept;
    APPROVED is kept only when the majority was achieved."""
    if chosen in ('DEFERRED', 'GA_RATIFICATION', 'RECOMMENDATION'):
        return chosen
    if chosen == 'REJECTED':
        return 'REJECTED'
    return 'APPROVED' if achieved else 'REJECTED'


def legacy_vote_result(outcome):
    return {'APPROVED': 'passed', 'REJECTED': 'rejected', 'DEFERRED': 'deferred',
            'GA_RATIFICATION': 'passed', 'RECOMMENDATION': 'passed'}.get(outcome, 'deferred')


def circulation_error(kind, votes, rule=None):
    """Written resolutions by circulation: every member must vote (Code 2016 / AoA)."""
    if kind != 'CIRCULATION':
        return None
    if rule is not None and not _yes(rule.get('circulation_requires_all', True)):
        return None
    if any(str(v).upper() == 'ABSENT' for v in votes):
        return 'every member must vote on a resolution by circulation'
    return None


# ------------------------------------------------------------------ numbering
def body_prefix(body, committee_prefix=None, entity_code=None):
    p = (committee_prefix or '').strip().upper() if body == 'COMMITTEE' else ''
    p = p or BODY_PREFIX.get(body or 'BOARD', 'BOD')
    return f'{entity_code.strip().upper()}-{p}' if entity_code and entity_code.strip() else p


def resolution_number(prefix, year, meeting_seq, item_no, taken=()):
    """'BOD-2026-05-03' (body-year-meeting-item). If that number was ever issued,
    a letter is appended (BOD-2026-05-03A) so a number is never reused."""
    base = f'{prefix}-{int(year)}-{int(meeting_seq or 0):02d}-{int(item_no):02d}'
    taken = set(taken or ())
    if base not in taken:
        return base
    for suffix in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        if base + suffix not in taken:
            return base + suffix
    raise ValueError('no free resolution number')


def next_item_no(existing_item_numbers):
    return max([int(x) for x in existing_item_numbers if x is not None] or [0]) + 1


def next_sequence(existing_sequences):
    return max([int(x) for x in existing_sequences if x is not None] or [0]) + 1


# ------------------------------------------------------------------ follow-up / filing / signatures
def followup_state(res, today=None):
    """'overdue' / 'open' / 'closed' / 'none' for a resolution's follow-up."""
    today = today or date.today()
    st = (res.get('followup_status') or '').upper()
    if st in FOLLOWUP_CLOSED:
        return 'closed'
    due = as_date(res.get('due_date'))
    if not (res.get('action_owner') or due or st):
        return 'none'
    if due and due < today:
        return 'overdue'
    return 'open'


def filing_due(meeting_date, filing_days):
    d = as_date(meeting_date)
    if not d or filing_days in (None, ''):
        return None
    return d + timedelta(days=int(filing_days))


def minutes_state(m, has_approved_version=False):
    if m.get('chair_signed_at') and m.get('secretary_signed_at'):
        return 'SIGNED'
    st = (m.get('minutes_state') or '').upper()
    if st == 'SIGNED':
        return 'APPROVED'   # a signature is missing
    if st == 'APPROVED' or has_approved_version or m.get('minutes_approved_on'):
        return 'APPROVED'
    return 'DRAFT'


def meeting_flags(m, today=None, signature_grace_days=30):
    """Secretariat alerts for one meeting dict (meeting_date, minutes state, filing)."""
    today = today or date.today()
    out = []
    d = as_date(m.get('meeting_date'))
    if not d or d > today:
        return out
    if (m.get('status') or '').upper() in ('CANCELLED', 'CANCELED', 'POSTPONED'):
        return out
    state = m.get('_minutes_state') or minutes_state(m)
    due = as_date(m.get('filing_due_date'))
    if due and not m.get('filed_on') and due < today:
        out.append('filing_overdue')
    grace = due or (d + timedelta(days=signature_grace_days))
    if state != 'SIGNED' and grace < today:
        out.append('signature_overdue')
    return out


# ------------------------------------------------------------------ attendance statistics
def attendance_stats(rows, rules=()):
    """rows: [{member_id, year, code}] (one per member per meeting of the body).
    rules: composition rule dicts (max_absence_pct, max_missed_meetings).
    Returns {(member_id, year): {...counts, rate, alerts}}."""
    out = {}
    for r in rows:
        key = (r['member_id'], r['year'])
        s = out.setdefault(key, dict(meetings=0, present=0, remote=0, proxy=0, excused=0, unexcused=0, unknown=0))
        s['meetings'] += 1
        c = r.get('code')
        if c == 'IN_PERSON':
            s['present'] += 1
        elif c == 'REMOTE':
            s['present'] += 1
            s['remote'] += 1
        elif c == 'PROXY':
            s['proxy'] += 1
        elif c == 'ABSENT_EXCUSED':
            s['excused'] += 1
        elif c == 'ABSENT_UNEXCUSED':
            s['unexcused'] += 1
        else:
            s['unknown'] += 1
    for s in out.values():
        recorded = s['meetings'] - s['unknown']
        absent = s['excused'] + s['unexcused'] + s['proxy']   # a proxy is not personal attendance
        s['absent'] = absent
        s['rate'] = round(100.0 * s['present'] / recorded, 1) if recorded else None
        s['absence_pct'] = round(100.0 * absent / recorded, 1) if recorded else None
        alerts = []
        for rule in rules or ():
            mx = _num(rule.get('max_absence_pct'))
            if mx is not None and s['absence_pct'] is not None and s['absence_pct'] > mx:
                alerts.append(dict(code='absence_pct', limit=mx, rule=rule.get('name_en'), rule_ar=rule.get('name_ar'),
                                   legal_ref=rule.get('legal_ref')))
            mm = rule.get('max_missed_meetings')
            if mm not in (None, '') and absent >= int(mm):
                alerts.append(dict(code='missed_meetings', limit=int(mm), rule=rule.get('name_en'),
                                   rule_ar=rule.get('name_ar'), legal_ref=rule.get('legal_ref')))
        s['alerts'] = alerts
    return out
