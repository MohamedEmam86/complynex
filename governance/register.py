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

"""Board-meeting record and resolutions register on the governance blueprint.

- Meeting record: body (board / committee / OGM / EGM), sequence number, kind
  (ordinary / extraordinary / by circulation), mode, notice, chair, secretary,
  vote tellers, attendance per person (in person / remote / proxy + holder /
  excused / unexcused), quorum against the meeting's rule (first and second call),
  previous minutes, conflict declarations, minutes state, signatures and filing.
- Resolutions: never-reused numbers (body-year-meeting-item), per-member votes,
  automatic majority check, outcome, conditions, dates, follow-up, typed links.
- Search ("like sanctions screening"): governance/resolution_search.py.
- Member profile, secretary view and reports (attendance, annual board list,
  follow-up).
Pure rules live in governance/register_logic.py.
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import render_template, request, redirect, url_for, flash, abort
from flask_babel import gettext as _, get_locale
from flask_login import login_required, current_user

from database.db import get_db
from models.audit import AuditLog
from utils.decorators import permission_required
from governance.routes import governance_bp
from governance import register_logic as RL
from governance import resolution_search as RS

PAGE = 50


# ------------------------------------------------------------------ small helpers
def is_ar():
    return str(get_locale() or '').startswith('ar')


@governance_bp.app_template_global('gov_pick')
def gov_pick(en, ar=None):
    """The Arabic value on an Arabic page when there is one, else the English one."""
    return (ar if is_ar() and ar else en) or ar or ''


def _audit(action, rid, details):
    try:
        AuditLog.log(current_user.id, action, 'Governance', rid, details, request.remote_addr)
    except Exception:
        pass


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _s(name, n=2000):
    return (request.form.get(name) or '').strip()[:n] or None


def _d(name):
    return RL.as_date(request.form.get(name))


def _event(db, meeting_id, subject, subject_id, event, note=None, frm=None, to=None):
    db.execute("""INSERT INTO meeting_events (meeting_id, subject, subject_id, event, from_status, to_status, note, user_id)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
               (meeting_id, subject, subject_id, event, frm, to, note, current_user.id))


def entities(db, active_only=True, include_sample=True):
    """Boards for a choice list; sample boards are left out where a real record is being edited."""
    where = ['TRUE']
    if active_only:
        where.append('is_active')
    if not include_sample:
        where.append('NOT is_sample')
    return [dict(r) for r in db.execute(
        f"SELECT * FROM gov_entities WHERE {' AND '.join(where)} ORDER BY sort_order, id").fetchall()]


def default_entity_id(db):
    r = db.execute("SELECT id FROM gov_entities WHERE is_default ORDER BY id LIMIT 1").fetchone()
    return r['id'] if r else None


def entity_clause(alias, entity_id, default_id):
    """SQL + args selecting rows of one board (NULL entity_id = the default board)."""
    if not entity_id:
        return 'TRUE', ()
    if entity_id == default_id:
        return f'({alias}.entity_id IS NULL OR {alias}.entity_id = %s)', (entity_id,)
    return f'{alias}.entity_id = %s', (entity_id,)


def derive_body(m):
    b = (m.get('body') or '').upper()
    if b in RL.BODIES:
        return b
    if m.get('committee_id'):
        return 'COMMITTEE'
    t = (m.get('meeting_type') or '').upper()
    if t in ('AGM', 'OGM'):
        return 'OGM'
    if t == 'EGM':
        return 'EGM'
    return 'BOARD'


def derive_kind(m):
    k = (m.get('meeting_kind') or '').upper()
    if k in RL.KINDS:
        return k
    return 'EXTRAORDINARY' if (m.get('meeting_type') or '').upper() in ('EXTRAORDINARY', 'EMERGENCY') else 'ORDINARY'


def meeting_or_404(db, mid):
    row = db.execute("""SELECT m.*, c.committee_name, c.committee_name_arabic, c.res_prefix AS committee_prefix,
                               c.committee_type, c.meeting_rule_id AS committee_rule_id,
                               e.name_en AS entity_en, e.name_ar AS entity_ar, e.short_code AS entity_code,
                               e.is_default AS entity_default,
                               o.full_name AS secretary_name, o.full_name_ar AS secretary_name_ar
                        FROM board_meetings m
                        LEFT JOIN board_committees c ON c.id = m.committee_id
                        LEFT JOIN gov_entities e ON e.id = COALESCE(m.entity_id, (SELECT id FROM gov_entities WHERE is_default LIMIT 1))
                        LEFT JOIN gov_officers o ON o.id = m.secretary_officer_id
                        WHERE m.id = %s""", (mid,)).fetchone()
    if not row:
        abort(404)
    m = dict(row)
    m['body_code'] = derive_body(m)
    m['kind_code'] = derive_kind(m)
    return m


RULE_FIELDS = ('id', 'code', 'name_en', 'name_ar', 'legal_ref', 'applies_to', 'quorum_basis', 'quorum_type',
               'quorum_fraction', 'quorum_min', 'min_personal', 'second_call_type', 'second_call_fraction',
               'second_call_min', 'count_proxies', 'count_remote', 'majority_rule', 'chair_casting_vote',
               'circulation_requires_all', 'notice_days', 'filing_days', 'filing_authority')


def rule_snapshot(rule):
    """The rule values frozen on a meeting (JSON-safe)."""
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in (rule or {}).items() if k in RULE_FIELDS}


def save_rule_snapshot(db, mid, rule):
    db.execute("UPDATE board_meetings SET rule_snapshot = %s::jsonb WHERE id = %s",
               (json.dumps(rule_snapshot(rule), ensure_ascii=False, default=str), mid))


def rule_for(db, m):
    """The meeting's rule: the values frozen on the meeting when it was recorded (a later change of the
    rule in the settings does not rewrite past meetings); the configured rule only when nothing is frozen."""
    snap = m.get('rule_snapshot')
    if isinstance(snap, str):
        snap = json.loads(snap)
    if snap:
        return dict(snap)
    return live_rule(db, m)


def live_rule(db, m):
    rid = m.get('meeting_rule_id') or m.get('committee_rule_id')
    if rid:
        r = db.execute("SELECT * FROM gov_meeting_rules WHERE id = %s", (rid,)).fetchone()
        if r:
            return dict(r)
    if m.get('committee_type'):
        r = db.execute("""SELECT r.* FROM gov_committee_types t JOIN gov_meeting_rules r ON r.code = t.meeting_rule_code
                          WHERE t.code = UPPER(%s)""", (m['committee_type'],)).fetchone()
        if r:
            return dict(r)
    r = db.execute("""SELECT * FROM gov_meeting_rules WHERE is_active AND applies_to IN (%s, 'ANY')
                      ORDER BY (applies_to = 'ANY'), sort_order, id LIMIT 1""", (m['body_code'],)).fetchone()
    return dict(r) if r else {'code': 'DEFAULT', 'name_en': 'Majority of members', 'quorum_type': 'MAJORITY',
                              'quorum_fraction': 0.5, 'quorum_min': 3, 'majority_rule': 'SIMPLE_PRESENT',
                              'chair_casting_vote': True, 'count_proxies': True, 'count_remote': True}


def member_caps(db, member_ids, on=None):
    """{member_id: [capacity rows current on `on` (default today)]}"""
    ids = [i for i in set(member_ids) if i]
    if not ids:
        return {}
    on = on or date.today()
    rows = db.execute("""
        SELECT mc.*, o.code, o.name_en, o.name_ar, o.flag, o.is_voting, d.code AS dim_code, d.name_en AS dim_en,
               d.name_ar AS dim_ar, d.sort_order AS dim_order, o.sort_order AS opt_order
        FROM gov_member_capacities mc
        JOIN gov_capacity_options o ON o.id = mc.option_id
        JOIN gov_capacity_dimensions d ON d.id = o.dimension_id
        WHERE mc.member_id = ANY(%s) AND (mc.effective_from IS NULL OR mc.effective_from <= %s)
          AND (mc.effective_to IS NULL OR mc.effective_to >= %s)
        ORDER BY d.sort_order, o.sort_order, mc.id""", (ids, on, on)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r['member_id'], []).append(dict(r))
    return out


def flags_of(caps, legacy=None):
    f = {c['flag'] for c in caps or () if c.get('flag')}
    dims = {c['dim_code'] for c in caps or ()}
    if legacy is not None:   # members without capacities in a dimension keep the old flags
        if 'INDEPENDENCE' not in dims:
            f.add('independent' if legacy.get('is_independent') else 'non_independent')
        if 'EXEC_STATUS' not in dims:
            f.add('executive' if legacy.get('is_executive') else 'non_executive')
    if 'chair_md' in f:
        f.update(('chair', 'md'))
    return f


def cap_label(caps):
    return ' · '.join(gov_pick(c['name_en'], c['name_ar']) for c in caps or ())


def sync_legacy_flags(db, member_id):
    """Keep board_members.is_independent / is_executive / member_type in step with the capacities."""
    caps = member_caps(db, [member_id]).get(member_id, [])
    dims = {c['dim_code']: c for c in caps}
    sets, args = [], []
    if 'INDEPENDENCE' in dims:
        sets.append('is_independent = %s')
        args.append(1 if dims['INDEPENDENCE'].get('flag') == 'independent' else 0)
    if 'EXEC_STATUS' in dims:
        sets.append('is_executive = %s')
        args.append(1 if dims['EXEC_STATUS'].get('flag') == 'executive' else 0)
    if sets:
        db.execute(f"UPDATE board_members SET {', '.join(sets)} WHERE id = %s", tuple(args) + (member_id,))
        db.execute("""UPDATE board_members SET member_type = CASE WHEN is_independent = 1 THEN 'INDEPENDENT'
                      WHEN is_executive = 1 THEN 'EXECUTIVE' ELSE 'NON_EXECUTIVE' END WHERE id = %s""", (member_id,))


def attendance_rows(db, mid):
    rows = [dict(r) for r in db.execute("""
        SELECT ma.*, bm.member_name, bm.member_name_arabic, bm.gender, bm.is_independent, bm.is_executive,
               bm.appointment_date, bm.resignation_date, bm.is_sample AS member_sample,
               h.member_name AS holder_name, h.member_name_arabic AS holder_name_ar
        FROM meeting_attendance ma JOIN board_members bm ON bm.id = ma.member_id
        LEFT JOIN board_members h ON h.id = ma.proxy_holder_member_id
        WHERE ma.meeting_id = %s ORDER BY bm.member_name""", (mid,)).fetchall()]
    for r in rows:
        r['code'] = RL.attendance_code(r)
    return rows


def decorate_rows(db, m, rows):
    """Capacities on the meeting date, and whether each member votes at this meeting: in office on that
    date (appointed on or before it, not resigned by then) and holding a voting capacity."""
    md = RL.as_date(m.get('meeting_date')) or date.today()
    caps = member_caps(db, [r['member_id'] for r in rows], md)
    for r in rows:
        r['caps'] = caps.get(r['member_id'], [])
        r['cap_label'] = cap_label(r['caps'])
        r['flags'] = flags_of(r['caps'], r)
        appointed, resigned = RL.as_date(r.get('appointment_date')), RL.as_date(r.get('resignation_date'))
        r['in_office'] = (not appointed or appointed <= md) and (not resigned or resigned > md)
        role_votes = all(c.get('is_voting', True) for c in r['caps'] if c.get('dim_code') == 'BOARD_ROLE')
        r['voting'] = r['in_office'] and role_votes
    return rows


def committee_externals(db, m):
    """(seats, present) of external (non-board) members of the committee: active committee seats
    of key officials, present when recorded PRESENT among the meeting's external participants."""
    if not m.get('committee_id'):
        return 0, 0
    seats = {(r['full_name'] or '').strip().lower() for r in db.execute(
        """SELECT o.full_name FROM fp_official_committees oc JOIN fp_officials o ON o.id = oc.official_id
           WHERE oc.committee_id = %s AND oc.is_active AND COALESCE(o.official_type, '') <> 'board'""",
        (m['committee_id'],)).fetchall()}
    present = {(r['full_name'] or '').strip().lower() for r in db.execute(
        "SELECT full_name FROM meeting_external_attendees WHERE meeting_id = %s AND attendance_status = 'PRESENT'",
        (m['id'],)).fetchall()}
    return len(seats), len(seats & present)


def compute_quorum(db, m, rows=None, rule=None):
    """The one quorum calculation used by the page, the stored figures and the resolution checks."""
    rule = rule or rule_for(db, m)
    rows = rows if rows is not None else decorate_rows(db, m, attendance_rows(db, m['id']))
    voters = [r for r in rows if r['voting']]
    if derive_kind(m) == 'CIRCULATION':
        return dict(valid=True, basis='CIRCULATION', required=len(voters), counted=len(voters), call_no=1,
                    threshold=None, personal=None, min_personal=None), rows
    counts = RL.quorum_counts(voters, rule)
    ext_seats, ext_present = committee_externals(db, m)
    counts['IN_PERSON'] += ext_present
    q = RL.quorum(rule, len(voters) + ext_seats, counts, m.get('call_no') or 1, m.get('capital_represented_pct'))
    q['members_total'] = len(voters) + ext_seats
    return q, rows


def store_quorum(db, m):
    if not m.get('rule_snapshot'):
        rule = live_rule(db, m)
        save_rule_snapshot(db, m['id'], rule)
        m = dict(m, rule_snapshot=rule_snapshot(rule))
    q, _rows = compute_quorum(db, m)
    db.execute("""UPDATE board_meetings SET quorum_required = %s, quorum_counted = %s, members_total = %s,
                  quorum_met = %s WHERE id = %s""",
               (int(q['required']) if q['required'] is not None else None,
                int(q['counted']) if q['counted'] is not None else None,
                q.get('members_total'), 1 if q['valid'] else 0, m['id']))
    return q


def meeting_locked(db, mid):
    """True once the minutes are signed by the chair and the secretary: the record is then closed."""
    row = db.execute("SELECT minutes_state, chair_signed_at, secretary_signed_at FROM board_meetings WHERE id = %s",
                     (mid,)).fetchone()
    return bool(row) and RL.minutes_state(dict(row)) == 'SIGNED'


def guard_unlocked(db, mid, anchor=''):
    """None when the meeting record may be changed, else the redirect that refuses the change."""
    if meeting_locked(db, mid):
        flash(_('The minutes are signed; the record can no longer be changed.'), 'danger')
        return redirect(url_for('governance.meeting_record', id=mid) + (('#' + anchor) if anchor else ''))
    return None


def has_approved_version(db, mid):
    return bool(db.execute("SELECT 1 FROM meeting_minutes WHERE meeting_id = %s AND status = 'approved'",
                           (mid,)).fetchone())


def body_members(db, m):
    """Members expected at a meeting: the committee's members, or the board's active members."""
    if m.get('committee_id'):
        return [r['member_id'] for r in db.execute(
            """SELECT cm.member_id FROM committee_memberships cm JOIN board_members bm ON bm.id = cm.member_id
               WHERE cm.committee_id = %s AND COALESCE(cm.is_active, 1) = 1 AND COALESCE(bm.is_deleted, 0) = 0""",
            (m['committee_id'],)).fetchall()]
    dflt = default_entity_id(db)
    clause, args = entity_clause('bm', m.get('entity_id') or dflt, dflt)
    return [r['id'] for r in db.execute(
        f"SELECT bm.id FROM board_members bm WHERE bm.status = 'ACTIVE' AND COALESCE(bm.is_deleted, 0) = 0 AND {clause}",
        args).fetchall()]


def meeting_label(m):
    seq = m.get('sequence_no')
    return (m.get('meeting_reference') or '') + (f" (#{seq})" if seq else '')


def show_sample(db, entity_id=None):
    """Sample records are left out of lists, searches and alerts unless asked for (sample=1)
    or a sample board is selected."""
    if request.args.get('sample') == '1':
        return True
    if entity_id:
        e = db.execute("SELECT is_sample FROM gov_entities WHERE id = %s", (entity_id,)).fetchone()
        return bool(e and e['is_sample'])
    return False


# ------------------------------------------------------------------ meetings register
@governance_bp.route('/register/meetings')
@login_required
@permission_required('governance')
def register_meetings():
    db = get_db()
    dflt = default_entity_id(db)
    ent = request.args.get('entity', type=int)
    with_sample = show_sample(db, ent)
    clause, args = entity_clause('m', ent, dflt)
    if not with_sample:
        clause += ' AND NOT COALESCE(m.is_sample, FALSE)'
    rows = [dict(r) for r in db.execute(f"""
        SELECT m.*, c.committee_name, c.committee_name_arabic, e.name_en AS entity_en, e.name_ar AS entity_ar,
               (SELECT COUNT(*) FROM board_decisions d WHERE d.meeting_id = m.id) AS n_resolutions,
               (SELECT COUNT(*) FROM meeting_minutes mm WHERE mm.meeting_id = m.id AND mm.status = 'approved') AS n_approved
        FROM board_meetings m
        LEFT JOIN board_committees c ON c.id = m.committee_id
        LEFT JOIN gov_entities e ON e.id = COALESCE(m.entity_id, %s)
        WHERE {clause}
        ORDER BY m.meeting_date DESC NULLS LAST, m.id DESC""", (dflt,) + args).fetchall()]
    today = date.today()
    for r in rows:
        r['body_code'], r['kind_code'] = derive_body(r), derive_kind(r)
        r['_minutes_state'] = RL.minutes_state(r, r['n_approved'] > 0)
        r['flags'] = RL.meeting_flags(r, today)
    committees = [dict(r) for r in db.execute(
        "SELECT id, committee_name, committee_name_arabic, entity_id FROM board_committees WHERE COALESCE(is_active, 1) = 1 ORDER BY committee_name").fetchall()]
    rules = [dict(r) for r in db.execute("SELECT id, code, name_en, name_ar, applies_to FROM gov_meeting_rules WHERE is_active ORDER BY sort_order, id").fetchall()]
    return render_template('governance/register_meetings.html', rows=rows, entities=entities(db), entity=ent,
                           with_sample=with_sample,
                           committees=committees, rules=rules, default_entity=dflt, today=today)


@governance_bp.route('/register/meetings/new', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def register_meeting_new():
    db = get_db()
    body = (request.form.get('body') or 'BOARD').upper()
    kind = (request.form.get('meeting_kind') or 'ORDINARY').upper()
    d = _d('meeting_date')
    errors = []
    if body not in RL.BODIES:
        errors.append(_('Choose the body that meets.'))
    if kind not in RL.KINDS:
        errors.append(_('Choose the kind of meeting.'))
    if not d:
        errors.append(_('A valid meeting date is required.'))
    committee_id = request.form.get('committee_id', type=int) if body == 'COMMITTEE' else None
    if body == 'COMMITTEE' and not committee_id:
        errors.append(_('Choose the committee.'))
    dflt = default_entity_id(db)
    ent = request.form.get('entity_id', type=int) or dflt
    if committee_id:
        c = db.execute("SELECT entity_id FROM board_committees WHERE id = %s", (committee_id,)).fetchone()
        if not c:
            errors.append(_('Choose the committee.'))
        ent = (c and c['entity_id']) or ent
    e = db.execute("SELECT * FROM gov_entities WHERE id = %s AND is_active", (ent,)).fetchone()
    if not e:
        errors.append(_('Choose the board.'))
    elif not e['is_default'] and not (e['short_code'] or '').strip():
        errors.append(_('Give this board a short code first (Settings > Boards): it starts its resolution numbers.'))
    rule_id = request.form.get('meeting_rule_id', type=int)
    if rule_id and not db.execute("SELECT 1 FROM gov_meeting_rules WHERE id = %s AND is_active", (rule_id,)).fetchone():
        errors.append(_('Choose the quorum / majority rule from the list.'))
    if errors:
        for err in errors:
            flash(err, 'danger')
        return redirect(url_for('governance.register_meetings'))
    db.execute("SELECT pg_advisory_xact_lock(hashtext('gov_meeting_sequence'))")
    seq = next_sequence(db, ent, body, committee_id, d.year, dflt)
    mtype = {'BOARD': 'EXTRAORDINARY' if kind == 'EXTRAORDINARY' else 'BOARD', 'COMMITTEE': 'COMMITTEE',
             'OGM': 'AGM', 'EGM': 'AGM'}[body]
    ref = _s('meeting_reference', 100) or f"{RL.BODY_PREFIX.get(body, 'BOD')}-{d.year}-{seq:02d}"
    mid = db.execute("""INSERT INTO board_meetings (meeting_type, committee_id, meeting_date, meeting_time, location, status,
                            meeting_reference, entity_id, body, meeting_kind, sequence_no, mode, meeting_rule_id, call_no,
                            minutes_state, is_sample)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,'DRAFT',%s) RETURNING id""",
                     (mtype, committee_id, d.isoformat(), _s('meeting_time', 5) or '10:00', _s('location', 300),
                      'COMPLETED' if d <= date.today() else 'SCHEDULED', ref,
                      None if ent == dflt else ent, body, kind, seq,
                      (request.form.get('mode') or 'IN_PERSON').upper() if (request.form.get('mode') or '').upper() in RL.MODES else 'IN_PERSON',
                      rule_id, bool(e['is_sample']))).fetchone()['id']
    m = meeting_or_404(db, mid)
    save_rule_snapshot(db, mid, live_rule(db, m))
    for member_id in body_members(db, m):
        db.execute("INSERT INTO meeting_attendance (meeting_id, member_id, attended) VALUES (%s,%s,0) "
                   "ON CONFLICT (meeting_id, member_id) DO NOTHING", (mid, member_id))
    _event(db, mid, 'meeting', mid, 'meeting_recorded', f'{body} {kind} #{seq}')
    db.commit()
    _audit('Board Meeting Recorded', mid, f'{ref} {body} {kind}')
    flash(_('Meeting %(ref)s created. Record the formalities, attendance and resolutions below.', ref=ref), 'success')
    return redirect(url_for('governance.meeting_record', id=mid))


def next_sequence(db, entity_id, body, committee_id, year, dflt=None):
    dflt = dflt or default_entity_id(db)
    clause, args = entity_clause('m', entity_id, dflt)
    rows = db.execute(f"""SELECT m.sequence_no, m.body, m.committee_id, m.meeting_type FROM board_meetings m WHERE {clause}
                          AND m.meeting_date ~ '^[0-9]{{4}}' AND left(m.meeting_date, 4) = %s""",
                      args + (str(year),)).fetchall()
    seqs = [r['sequence_no'] for r in rows if derive_body(dict(r)) == body
            and (body != 'COMMITTEE' or r['committee_id'] == committee_id)]
    return RL.next_sequence(seqs)


# ------------------------------------------------------------------ meeting record
def record_context(db, mid):
    m = meeting_or_404(db, mid)
    rule = rule_for(db, m)
    q, rows = compute_quorum(db, m, rule=rule)
    first_call = None
    if (m.get('call_no') or 1) >= 2 and m.get('first_call_present') is not None:
        first_call = RL.quorum(rule, q.get('members_total') or 0, {'IN_PERSON': m['first_call_present']}, 1, None)
    tellers = [dict(r) for r in db.execute("""
        SELECT t.*, o.full_name, o.full_name_ar, bm.member_name, bm.member_name_arabic FROM gov_meeting_officers t
        LEFT JOIN gov_officers o ON o.id = t.officer_id LEFT JOIN board_members bm ON bm.id = t.member_id
        WHERE t.meeting_id = %s ORDER BY t.role, t.id""", (mid,)).fetchall()]
    agenda = [dict(r) for r in db.execute(
        "SELECT * FROM meeting_agenda_items WHERE meeting_id = %s ORDER BY item_number, id", (mid,)).fetchall()]
    conflicts = [dict(r) for r in db.execute("""
        SELECT c.*, bm.member_name, bm.member_name_arabic, ai.item_number, ai.item_title, d.res_no
        FROM gov_conflict_declarations c JOIN board_members bm ON bm.id = c.member_id
        LEFT JOIN meeting_agenda_items ai ON ai.id = c.agenda_item_id
        LEFT JOIN board_decisions d ON d.id = c.resolution_id
        WHERE c.meeting_id = %s ORDER BY c.id""", (mid,)).fetchall()]
    resolutions = resolutions_with_votes(db, "d.meeting_id = %s", (mid,))
    officers = [dict(r) for r in db.execute("""
        SELECT o.*, op.name_en AS role_en, op.name_ar AS role_ar, op.flag FROM gov_officers o
        LEFT JOIN gov_capacity_options op ON op.id = o.role_option_id WHERE o.is_active ORDER BY o.full_name""").fetchall()]
    dflt = default_entity_id(db)
    clause, args = entity_clause('m', m.get('entity_id') or dflt, dflt)
    others = [dict(r) for r in db.execute(f"""SELECT m.id, m.meeting_reference, m.meeting_date, m.sequence_no, m.body,
                    m.committee_id, m.meeting_type, m.meeting_kind FROM board_meetings m
                    WHERE m.id <> %s AND {clause} ORDER BY m.meeting_date DESC NULLS LAST LIMIT 60""",
                                         (mid,) + args).fetchall()]
    prev_candidates = [o for o in others if derive_body(o) == m['body_code'] and o.get('committee_id') == m.get('committee_id')
                       and (o.get('meeting_date') or '') < (m.get('meeting_date') or '9999')]
    all_res = [dict(r) for r in db.execute("""SELECT d.id, d.res_no, d.decision_number, d.decision_title, m.meeting_date
                    FROM board_decisions d JOIN board_meetings m ON m.id = d.meeting_id WHERE d.meeting_id <> %s
                    ORDER BY m.meeting_date DESC NULLS LAST, d.id DESC LIMIT 300""", (mid,)).fetchall()]
    approved = has_approved_version(db, mid)
    state = RL.minutes_state(m, approved)
    rules = [dict(r) for r in db.execute("SELECT * FROM gov_meeting_rules WHERE is_active ORDER BY sort_order, id").fetchall()]
    cats = [dict(r) for r in db.execute("SELECT * FROM gov_resolution_categories WHERE is_active ORDER BY sort_order, id").fetchall()]
    users = [dict(r) for r in db.execute("""SELECT id, NULLIF(TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')), '') AS name
                                            FROM users WHERE is_active = 1 ORDER BY first_name, last_name""").fetchall()]
    chair_row = next((r for r in rows if r['member_id'] == m.get('chair_member_id')), None)
    return dict(m=m, rule=rule, rules=rules, rows=rows, q=q, first_call=first_call, tellers=tellers, agenda=agenda,
                conflicts=conflicts, resolutions=resolutions, officers=officers, prev_candidates=prev_candidates,
                all_res=all_res, minutes_state=state, approved_version=approved, cats=cats, users=users,
                entities=entities(db, include_sample=bool(m.get('is_sample'))), chair_row=chair_row,
                flags=RL.meeting_flags(dict(m, _minutes_state=state)), locked=state == 'SIGNED',
                circulation=m['kind_code'] == 'CIRCULATION', has_resolutions=bool(resolutions),
                proxy_errors=RL.proxy_errors([dict(member_id=r['member_id'], code=r['code'],
                                                   proxy_holder_member_id=r.get('proxy_holder_member_id'),
                                                   member_name=r['member_name']) for r in rows]),
                today=date.today())


def resolutions_with_votes(db, where, args):
    res = [dict(r) for r in db.execute(f"""
        SELECT d.*, c.name_en AS cat_en, c.name_ar AS cat_ar, ai.item_number, ai.item_title AS agenda_title,
               m.meeting_date, m.meeting_reference, m.sequence_no, m.body, m.meeting_kind, m.meeting_type, m.committee_id
        FROM board_decisions d JOIN board_meetings m ON m.id = d.meeting_id
        LEFT JOIN gov_resolution_categories c ON c.code = d.category_code
        LEFT JOIN meeting_agenda_items ai ON ai.id = d.agenda_item_id
        WHERE {where} ORDER BY COALESCE(d.item_no, 0), d.id""", args).fetchall()]
    if not res:
        return res
    ids = [r['id'] for r in res]
    votes = {}
    for v in db.execute("""SELECT v.*, bm.member_name, bm.member_name_arabic FROM gov_resolution_votes v
                           JOIN board_members bm ON bm.id = v.member_id WHERE v.resolution_id = ANY(%s)
                           ORDER BY bm.member_name""", (ids,)).fetchall():
        votes.setdefault(v['resolution_id'], []).append(dict(v))
    links = {}
    for l in db.execute("""SELECT l.*, t.res_no AS to_no, t.decision_number AS to_number, t.decision_title AS to_title,
                                  f.res_no AS from_no, f.decision_number AS from_number, f.decision_title AS from_title
                           FROM gov_resolution_links l JOIN board_decisions t ON t.id = l.to_resolution_id
                           JOIN board_decisions f ON f.id = l.from_resolution_id
                           WHERE l.from_resolution_id = ANY(%s) OR l.to_resolution_id = ANY(%s)""", (ids, ids)).fetchall():
        l = dict(l)
        links.setdefault(l['from_resolution_id'], []).append(dict(l, direction='out'))
        links.setdefault(l['to_resolution_id'], []).append(dict(l, direction='in'))
    today = date.today()
    for r in res:
        r['votes'] = votes.get(r['id'], [])
        r['tally'] = RL.tally(v['vote'] for v in r['votes'])
        if not r['votes']:
            r['tally'].update(FOR=r.get('votes_for') or 0, AGAINST=r.get('votes_against') or 0, ABSTAIN=r.get('votes_abstain') or 0)
        r['links'] = links.get(r['id'], [])
        r['number'] = r.get('res_no') or r.get('decision_number') or r.get('decision_reference') or f"#{r['id']}"
        r['outcome_code'] = r.get('outcome') or {'passed': 'APPROVED', 'rejected': 'REJECTED',
                                                 'deferred': 'DEFERRED'}.get((r.get('vote_result') or '').lower())
        r['fu_state'] = RL.followup_state(r, today)
        r['body_code'], r['kind_code'] = derive_body(r), derive_kind(r)
    return res


@governance_bp.route('/register/meeting/<int:id>')
@login_required
@permission_required('governance')
def meeting_record(id):
    db = get_db()
    ctx = record_context(db, id)
    return render_template('governance/meeting_record.html', **ctx)


def _back(mid, anchor=''):
    return redirect(url_for('governance.meeting_record', id=mid) + (('#' + anchor) if anchor else ''))


@governance_bp.route('/register/meeting/<int:id>/formalities', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_formalities(id):
    db = get_db()
    m = meeting_or_404(db, id)
    refused = guard_unlocked(db, id, 'formalities')
    if refused:
        return refused
    f = request.form
    body = (f.get('body') or m['body_code']).upper()
    kind = (f.get('meeting_kind') or m['kind_code']).upper()
    mode = (f.get('mode') or '').upper() or None
    d = _d('meeting_date') or RL.as_date(m.get('meeting_date'))
    errors = []
    if body not in RL.BODIES or kind not in RL.KINDS or (mode and mode not in RL.MODES):
        errors.append(_('Choose the body, kind and mode from the lists.'))
    if not d:
        errors.append(_('A valid meeting date is required.'))
    notice = _d('notice_date')
    if notice and d and notice > d:
        errors.append(_('The notice date cannot be after the meeting date.'))
    call_no = _int(f.get('call_no')) or 1
    if call_no not in (1, 2, 3):
        errors.append(_('The call number must be 1, 2 or 3.'))
    first_present = _int(f.get('first_call_present')) if (f.get('first_call_present') or '').strip() else None
    cap = None
    if (f.get('capital_represented_pct') or '').strip():
        try:
            cap = float(f.get('capital_represented_pct').replace(',', '.'))
            if not 0 <= cap <= 100:
                raise ValueError
        except ValueError:
            errors.append(_('The capital represented must be a percentage between 0 and 100.'))
    chair_id = f.get('chair_member_id', type=int)
    if chair_id and not db.execute("SELECT 1 FROM meeting_attendance WHERE meeting_id = %s AND member_id = %s",
                                   (id, chair_id)).fetchone():
        errors.append(_('The chair of the meeting must be one of the members on the attendance list.'))
    dflt = default_entity_id(db)
    ent = f.get('entity_id', type=int) or m.get('entity_id') or dflt
    e = db.execute("SELECT * FROM gov_entities WHERE id = %s", (ent,)).fetchone()
    if not e:
        errors.append(_('Choose the board.'))
    elif not e['is_default'] and not (e['short_code'] or '').strip():
        errors.append(_('Give this board a short code first (Settings > Boards): it starts its resolution numbers.'))
    elif e['is_sample'] and not m.get('is_sample'):
        errors.append(_('A real meeting cannot be moved to the sample board.'))
    rule_id = f.get('meeting_rule_id', type=int) or None
    if rule_id and not db.execute("SELECT 1 FROM gov_meeting_rules WHERE id = %s", (rule_id,)).fetchone():
        errors.append(_('Choose the quorum / majority rule from the list.'))
    sec_id = f.get('secretary_officer_id', type=int) or None
    if sec_id and not db.execute("SELECT 1 FROM gov_officers WHERE id = %s", (sec_id,)).fetchone():
        errors.append(_('Choose the secretary from the list.'))
    prev_id = f.get('prev_minutes_meeting_id', type=int) or None
    if prev_id and (prev_id == id or not db.execute("SELECT 1 FROM board_meetings WHERE id = %s", (prev_id,)).fetchone()):
        errors.append(_('Choose the previous meeting from the list.'))
    seq = _int(f.get('sequence_no')) or m.get('sequence_no')
    new_ent = None if ent == dflt else ent
    has_res = bool(db.execute("SELECT 1 FROM board_decisions WHERE meeting_id = %s", (id,)).fetchone())
    if has_res:
        # resolution numbers are made of the body, the year and the sequence number: they stay as issued
        if body != m['body_code'] or kind != m['kind_code'] or (d and d.isoformat() != (m.get('meeting_date') or '')[:10]) \
                or seq != m.get('sequence_no') or new_ent != m.get('entity_id') or (rule_id or None) != (m.get('meeting_rule_id') or None):
            errors.append(_('Resolutions are recorded for this meeting: its board, body, kind, date, sequence number '
                            'and rule can no longer change.'))
    if seq and d and not errors:
        clause, args = entity_clause('o', ent, dflt)
        for o in db.execute(f"""SELECT o.id, o.body, o.committee_id, o.meeting_type FROM board_meetings o
                                WHERE o.id <> %s AND o.sequence_no = %s AND left(o.meeting_date, 4) = %s AND {clause}""",
                            (id, seq, str(d.year)) + args).fetchall():
            if derive_body(dict(o)) == body and (o['committee_id'] or None) == (m.get('committee_id') or None):
                errors.append(_('Sequence number %(n)s is already used by another meeting of this body in %(y)s.',
                                n=seq, y=d.year))
                break
    if errors:
        for err in errors:
            flash(err, 'danger')
        return _back(id, 'formalities')
    if rule_id:
        rule = dict(db.execute("SELECT * FROM gov_meeting_rules WHERE id = %s", (rule_id,)).fetchone())
    else:
        rule = live_rule(db, dict(m, meeting_rule_id=None))
    rule_changed = (rule_id or None) != (m.get('meeting_rule_id') or None) or not m.get('rule_snapshot')
    effective_rule = rule if rule_changed else rule_for(db, m)
    filing_due = _d('filing_due_date') or RL.filing_due(d, effective_rule.get('filing_days'))
    prev_ok = 1 if f.get('prev_minutes_approved') else 0
    db.execute("""UPDATE board_meetings SET entity_id = %s, body = %s, meeting_kind = %s, sequence_no = %s,
                  meeting_date = %s, meeting_time = %s, end_time = %s, location = %s, mode = %s, notice_date = %s,
                  notice_channel = %s, chair_member_id = %s, chair_name = %s, secretary_officer_id = %s,
                  meeting_rule_id = %s, call_no = %s, first_call_at = %s, first_call_present = %s, first_call_note = %s,
                  capital_represented_pct = %s, prev_minutes_meeting_id = %s, prev_minutes_approved = %s,
                  recording_ref = %s, filing_authority = %s, filing_due_date = %s, meeting_reference = COALESCE(%s, meeting_reference)
                  WHERE id = %s""",
               (new_ent, body, kind, seq, d.isoformat(), _s('meeting_time', 5), _s('end_time', 5),
                _s('location', 300), mode, notice, _s('notice_channel', 200), chair_id, _s('chair_name', 200),
                sec_id, rule_id, call_no, _s('first_call_at', 40),
                first_present if call_no >= 2 else None, _s('first_call_note') if call_no >= 2 else None, cap,
                prev_id, prev_ok, _s('recording_ref', 300), _s('filing_authority', 100) or effective_rule.get('filing_authority'),
                filing_due, _s('meeting_reference', 100), id))
    if rule_changed:
        save_rule_snapshot(db, id, rule)
    if prev_id and prev_ok:
        db.execute("""UPDATE board_meetings SET minutes_state = CASE WHEN COALESCE(minutes_state, 'DRAFT') = 'DRAFT'
                      THEN 'APPROVED' ELSE minutes_state END, minutes_approved_on = COALESCE(minutes_approved_on, %s)
                      WHERE id = %s""", (d, prev_id))
        _event(db, prev_id, 'minutes', prev_id, 'minutes_approved_at_meeting', m.get('meeting_reference'))
    store_quorum(db, meeting_or_404(db, id))
    _event(db, id, 'meeting', id, 'formalities_saved', f'{body} {kind} call {call_no}')
    db.commit()
    _audit('Board Meeting Formalities Saved', id, f'{body} {kind} seq {seq} call {call_no}')
    flash(_('Meeting details saved.'), 'success')
    if not chair_id and not _s('chair_name', 200):
        flash(_('No chair of the meeting is recorded: the chair\'s casting vote cannot be applied.'), 'warning')
    return _back(id, 'formalities')


@governance_bp.route('/register/meeting/<int:id>/attendance', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_record_attendance(id):
    db = get_db()
    m = meeting_or_404(db, id)
    refused = guard_unlocked(db, id, 'attendance')
    if refused:
        return refused
    rows = attendance_rows(db, id)
    add = request.form.get('add_member_id', type=int)
    if add:
        if not db.execute("SELECT 1 FROM board_members WHERE id = %s AND COALESCE(is_deleted, 0) = 0", (add,)).fetchone():
            flash(_('Choose a board member.'), 'danger')
            return _back(id, 'attendance')
        db.execute("INSERT INTO meeting_attendance (meeting_id, member_id, attended) VALUES (%s,%s,0) "
                   "ON CONFLICT (meeting_id, member_id) DO NOTHING", (id, add))
        _event(db, id, 'attendee', add, 'member_invited')
        store_quorum(db, m)
        db.commit()
        return _back(id, 'attendance')
    planned = []
    for r in rows:
        code = (request.form.get(f'att_{r["member_id"]}') or '').upper()
        if code not in RL.ATTENDANCE:
            code = r['code']
        holder = request.form.get(f'holder_{r["member_id"]}', type=int) if code == 'PROXY' else None
        doc = _s(f'proxydoc_{r["member_id"]}', 300) or (r.get('proxy_document') if code == 'PROXY' else None)
        planned.append(dict(member_id=r['member_id'], code=code, proxy_holder_member_id=holder,
                            member_name=r['member_name'], doc=doc, note=_s(f'note_{r["member_id"]}', 500), old=r))
    errs = RL.proxy_errors([p for p in planned if p['code']])
    msgs = {'proxy_holder_missing': _('%(n)s: choose the member who holds the proxy.'),
            'proxy_self': _('%(n)s cannot hold their own proxy.'),
            'proxy_holder_absent': _('%(n)s: the proxy holder must be a member who attends.'),
            'proxy_one_only': _('%(n)s holds more than one proxy; a member may hold one proxy only.')}
    errors = [msgs[code] % {'n': name} for code, name in errs]
    errors += [_('%(n)s: give the reference of the written proxy.', n=p['member_name'])
               for p in planned if p['code'] == 'PROXY' and not p['doc']]
    if errors:
        for err in errors:
            flash(err, 'danger')
        return _back(id, 'attendance')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for p in planned:
        if not p['code']:
            continue
        cols = RL.legacy_columns(p['code'])
        holder_name = None
        if p['proxy_holder_member_id']:
            h = next((r for r in rows if r['member_id'] == p['proxy_holder_member_id']), None)
            holder_name = h['member_name'] if h else None
        db.execute("""UPDATE meeting_attendance SET attended = %s, attended_remotely = %s, apology_received = %s,
                      attendance_status = %s, proxy_name = %s, proxy_holder_member_id = %s, proxy_document = %s,
                      proxy_valid = %s, absence_authorized = %s, attendance_notes = %s, recorded_at = %s, recorded_by = %s
                      WHERE meeting_id = %s AND member_id = %s""",
                   (cols['attended'], cols['attended_remotely'], cols['apology_received'], cols['attendance_status'],
                    holder_name, p['proxy_holder_member_id'], p['doc'] if p['code'] == 'PROXY' else None,
                    1 if p['code'] == 'PROXY' else None, 1 if p['code'] == 'ABSENT_EXCUSED' else 0, p['note'],
                    now, current_user.id, id, p['member_id']))
        if p['old'].get('code') != p['code']:
            _event(db, id, 'attendee', p['member_id'], 'attendance_recorded', p['member_name'], p['old'].get('code'), p['code'])
    q = store_quorum(db, m)
    db.commit()
    _audit('Board Meeting Attendance Recorded', id, f"quorum {q['counted']}/{q['required']} valid={q['valid']}")
    flash(_('Attendance saved.') + ' ' + (_('Quorum present.') if q['valid'] else _('Quorum NOT present.')),
          'success' if q['valid'] else 'warning')
    return _back(id, 'attendance')


@governance_bp.route('/register/meeting/<int:id>/tellers', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_teller_add(id):
    db = get_db()
    meeting_or_404(db, id)
    refused = guard_unlocked(db, id, 'formalities')
    if refused:
        return refused
    officer = request.form.get('officer_id', type=int)
    member = request.form.get('member_id', type=int)
    name = _s('name', 200)
    role = (request.form.get('role') or 'TELLER').upper()
    if role not in ('TELLER', 'ASSISTANT_SECRETARY', 'OBSERVER', 'AUDITOR', 'GM'):
        role = 'TELLER'
    if officer and not db.execute("SELECT 1 FROM gov_officers WHERE id = %s", (officer,)).fetchone():
        officer = None
    if member and not db.execute("SELECT 1 FROM board_members WHERE id = %s", (member,)).fetchone():
        member = None
    if not (officer or member or name):
        flash(_('Choose an officer or a member, or type a name.'), 'danger')
        return _back(id, 'formalities')
    tid = db.execute("""INSERT INTO gov_meeting_officers (meeting_id, role, officer_id, member_id, name, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (id, role, officer, member, name, current_user.id)).fetchone()['id']
    _event(db, id, 'officer', tid, 'officer_added', role)
    db.commit()
    _audit('Board Meeting Officer Added', id, role)
    flash(_('Added.'), 'success')
    return _back(id, 'formalities')


@governance_bp.route('/register/meeting/<int:id>/tellers/<int:tid>/remove', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_teller_remove(id, tid):
    db = get_db()
    refused = guard_unlocked(db, id, 'formalities')
    if refused:
        return refused
    db.execute("DELETE FROM gov_meeting_officers WHERE id = %s AND meeting_id = %s", (tid, id))
    _event(db, id, 'officer', tid, 'officer_removed')
    db.commit()
    _audit('Board Meeting Officer Removed', id, str(tid))
    flash(_('Removed.'), 'info')
    return _back(id, 'formalities')


@governance_bp.route('/register/meeting/<int:id>/agenda', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_agenda_add(id):
    db = get_db()
    meeting_or_404(db, id)
    refused = guard_unlocked(db, id, 'agenda')
    if refused:
        return refused
    title = _s('item_title', 500)
    if not title:
        flash(_('The agenda item title is required.'), 'danger')
        return _back(id, 'agenda')
    n = db.execute("SELECT COALESCE(MAX(item_number), 0) + 1 AS n FROM meeting_agenda_items WHERE meeting_id = %s",
                   (id,)).fetchone()['n']
    aid = db.execute("""INSERT INTO meeting_agenda_items (meeting_id, item_number, item_title, item_description, item_type,
                        presenter_name, display_order, objection_note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (id, n, title, _s('item_description'), (request.form.get('item_type') or 'DECISION').upper()[:20],
                      _s('presenter_name', 200), n, _s('objection_note'))).fetchone()['id']
    _event(db, id, 'agenda', aid, 'agenda_item_added', f'{n}. {title}')
    db.commit()
    flash(_('Agenda item added.'), 'success')
    return _back(id, 'agenda')


@governance_bp.route('/register/meeting/<int:id>/agenda/<int:aid>/objection', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_agenda_objection(id, aid):
    db = get_db()
    refused = guard_unlocked(db, id, 'agenda')
    if refused:
        return refused
    db.execute("UPDATE meeting_agenda_items SET objection_note = %s WHERE id = %s AND meeting_id = %s",
               (_s('objection_note'), aid, id))
    _event(db, id, 'agenda', aid, 'agenda_objection_recorded')
    db.commit()
    flash(_('Saved.'), 'success')
    return _back(id, 'agenda')


@governance_bp.route('/register/meeting/<int:id>/conflicts', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_conflict_add(id):
    db = get_db()
    refused = guard_unlocked(db, id, 'conflicts')
    if refused:
        return refused
    ctx = record_context(db, id)
    member = request.form.get('member_id', type=int)
    nature = _s('nature')
    agenda_id = request.form.get('agenda_item_id', type=int) or None
    if not member or not nature or member not in {r['member_id'] for r in ctx['rows']}:
        flash(_('Choose the member and describe the interest declared.'), 'danger')
        return _back(id, 'conflicts')
    if agenda_id and agenda_id not in {a['id'] for a in ctx['agenda']}:
        flash(_('Choose the agenda item from the list.'), 'danger')
        return _back(id, 'conflicts')
    cid = db.execute("""INSERT INTO gov_conflict_declarations (meeting_id, member_id, agenda_item_id, nature, left_room,
                        did_not_vote, ga_informed, created_by) VALUES (%s,%s,%s,%s,%s,TRUE,%s,%s) RETURNING id""",
                     (id, member, agenda_id, nature, bool(request.form.get('left_room')),
                      bool(request.form.get('ga_informed')), current_user.id)).fetchone()['id']
    # declared after the vote: the member's vote on the resolutions of that item becomes a recusal
    changed = []
    for r in ctx['resolutions']:
        if agenda_id and r.get('agenda_item_id') == agenda_id:
            db.execute("""INSERT INTO gov_resolution_votes (resolution_id, member_id, vote, created_by) VALUES (%s,%s,'RECUSED',%s)
                          ON CONFLICT (resolution_id, member_id) DO UPDATE SET vote = 'RECUSED', via_proxy = FALSE""",
                       (r['id'], member, current_user.id))
            db.execute("UPDATE gov_conflict_declarations SET resolution_id = %s WHERE id = %s", (r['id'], cid))
            recompute_resolution(db, ctx['m'], ctx['rule'], r['id'])
            changed.append(r['number'])
    _event(db, id, 'conflict', cid, 'conflict_declared', nature[:200])
    db.commit()
    _audit('Board Conflict Declared', id, f'member {member}: {nature[:100]}')
    flash(_('Declaration recorded. The member is recorded as recused on resolutions of that agenda item.'), 'success')
    if changed:
        flash(_('The vote of this member on %(r)s is now a recusal and the majority was checked again.',
                r=', '.join(changed)), 'warning')
    return _back(id, 'conflicts')


@governance_bp.route('/register/meeting/<int:id>/conflicts/<int:cid>/remove', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_conflict_remove(id, cid):
    db = get_db()
    refused = guard_unlocked(db, id, 'conflicts')
    if refused:
        return refused
    db.execute("DELETE FROM gov_conflict_declarations WHERE id = %s AND meeting_id = %s", (cid, id))
    _event(db, id, 'conflict', cid, 'conflict_removed')
    db.commit()
    _audit('Board Conflict Removed', id, str(cid))
    flash(_('Removed.'), 'info')
    return _back(id, 'conflicts')


@governance_bp.route('/register/meeting/<int:id>/minutes-state', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_minutes_state(id):
    db = get_db()
    m = meeting_or_404(db, id)
    action = request.form.get('action')
    if action not in ('approve', 'sign_chair', 'sign_secretary', 'filed'):
        abort(400)
    if action != 'filed':
        refused = guard_unlocked(db, id, 'minutes')
        if refused:
            return refused
    if action == 'approve':
        on = _d('approved_on') or date.today()
        db.execute("UPDATE board_meetings SET minutes_state = 'APPROVED', minutes_approved_on = %s WHERE id = %s", (on, id))
        _event(db, id, 'minutes', id, 'minutes_marked_approved', on.isoformat(), m.get('minutes_state'), 'APPROVED')
    elif action in ('sign_chair', 'sign_secretary'):
        who = 'chair' if action == 'sign_chair' else 'secretary'
        if m.get(f'{who}_signed_at'):
            flash(_('The minutes are already signed in this capacity.'), 'danger')
            return _back(id, 'minutes')
        if RL.minutes_state(m, has_approved_version(db, id)) == 'DRAFT':
            flash(_('Approve the minutes before they are signed.'), 'danger')
            return _back(id, 'minutes')
        default = (m.get('secretary_name') if who == 'secretary' else None)
        if who == 'chair' and m.get('chair_member_id'):
            r = db.execute("SELECT member_name FROM board_members WHERE id = %s", (m['chair_member_id'],)).fetchone()
            default = r['member_name'] if r else None
        name = _s('name', 200) or default or (m.get('chair_name') if who == 'chair' else None)
        if not name:
            flash(_('Type the name of the person signing.'), 'danger')
            return _back(id, 'minutes')
        db.execute(f"UPDATE board_meetings SET {who}_signed_at = NOW(), {who}_signed_name = %s WHERE id = %s "
                   f"AND {who}_signed_at IS NULL", (name, id))
        m2 = meeting_or_404(db, id)
        if m2.get('chair_signed_at') and m2.get('secretary_signed_at'):
            db.execute("UPDATE board_meetings SET minutes_state = 'SIGNED' WHERE id = %s", (id,))
        _event(db, id, 'minutes', id, 'minutes_signed_' + who, name)
    else:
        if m.get('filed_on'):
            flash(_('The filing is already recorded.'), 'danger')
            return _back(id, 'minutes')
        on = _d('filed_on')
        if not on:
            flash(_('A valid filing date is required.'), 'danger')
            return _back(id, 'minutes')
        db.execute("UPDATE board_meetings SET filed_on = %s, filing_reference = %s WHERE id = %s",
                   (on, _s('filing_reference', 200), id))
        _event(db, id, 'minutes', id, 'minutes_filed', f"{on} {_s('filing_reference', 200) or ''}")
    db.commit()
    _audit('Board Minutes ' + action, id, action)
    flash(_('Saved.'), 'success')
    return _back(id, 'minutes')


# ------------------------------------------------------------------ resolutions
VALID_VOTES = ('FOR', 'AGAINST', 'ABSTAIN', 'RECUSED')


def _vote_inputs(rows, conflicted, circulation):
    """Votes from the form for every member with a vote at this meeting: (votes, missing names).
    Absent members are recorded as absent; a conflicted member as recused; every other member present
    (every member, for a resolution by circulation) must have a vote chosen - nothing is assumed."""
    votes, missing = {}, []
    for r in rows:
        if not r.get('voting', True):
            continue
        mid_ = r['member_id']
        v = (request.form.get(f'vote_{mid_}') or '').upper()
        present = circulation or r['code'] in ('IN_PERSON', 'REMOTE', 'PROXY')
        if mid_ in conflicted:
            v = 'RECUSED'
        elif not present:
            v = 'ABSENT'
        elif v not in VALID_VOTES:
            missing.append(r['member_name'])
            continue
        votes[mid_] = dict(vote=v, via_proxy=(not circulation and r['code'] == 'PROXY' and v in ('FOR', 'AGAINST', 'ABSTAIN')),
                           dissent=_s(f'dissent_{mid_}'))
    return votes, missing


def decide(m, rule, codes, chair_vote, chosen=None):
    """(achieved, need, note, outcome) of a resolution from its votes and the meeting's rule."""
    eligible = sum(1 for c in codes if c in ('FOR', 'AGAINST', 'ABSTAIN'))
    if m['body_code'] in ('OGM', 'EGM') and eligible == 0:
        # a general assembly votes by shares: the tellers' count is recorded as text
        achieved, need, note = chosen in ('APPROVED', 'GA_RATIFICATION', 'RECOMMENDATION', None), 0, \
            'votes of the shares represented, counted by the tellers'
    else:
        achieved, need, note = RL.majority(rule.get('majority_rule'), codes, chair_vote,
                                           casting=bool(rule.get('chair_casting_vote', True)), eligible=eligible)
    return achieved, need, note, RL.suggested_outcome(achieved, chosen), eligible


def recompute_resolution(db, m, rule, rid):
    """Tally, majority and outcome again from the stored votes (after a late conflict declaration)."""
    r = db.execute("SELECT outcome FROM board_decisions WHERE id = %s", (rid,)).fetchone()
    votes = {v['member_id']: v['vote'] for v in db.execute(
        "SELECT member_id, vote FROM gov_resolution_votes WHERE resolution_id = %s", (rid,)).fetchall()}
    codes = list(votes.values())
    kept = r['outcome'] if r and r['outcome'] not in ('APPROVED', 'REJECTED') else None
    achieved, need, note, outcome, eligible = decide(m, rule, codes, votes.get(m.get('chair_member_id')), kept)
    t = RL.tally(codes)
    db.execute("""UPDATE board_decisions SET votes_for = %s, votes_against = %s, votes_abstain = %s, outcome = %s,
                  vote_result = %s, majority_achieved = %s, majority_note = %s WHERE id = %s""",
               (t['FOR'], t['AGAINST'], t['ABSTAIN'], outcome, RL.legacy_vote_result(outcome), 1 if achieved else 0,
                f"{t['FOR']}/{eligible} for; {need} needed ({note})", rid))


class NumberingError(ValueError):
    pass


def allocate_number(db, m, item_no):
    """Next free resolution number; serialised so that two users never get the same one."""
    db.execute("SELECT pg_advisory_xact_lock(hashtext('gov_resolution_numbers'))")
    c_prefix = None
    if m['body_code'] == 'COMMITTEE':
        c_prefix = m.get('committee_prefix')
        if not c_prefix and m.get('committee_type'):
            t = db.execute("SELECT res_prefix FROM gov_committee_types WHERE code = UPPER(%s)", (m['committee_type'],)).fetchone()
            c_prefix = t['res_prefix'] if t else None
    non_default = m.get('entity_default') is False
    if non_default and not (m.get('entity_code') or '').strip():
        raise NumberingError(_('Give this board a short code first (Settings > Boards): it starts its resolution numbers.'))
    prefix = RL.body_prefix(m['body_code'], c_prefix, m.get('entity_code') if non_default else None)
    d = RL.as_date(m.get('meeting_date')) or date.today()
    seq = m.get('sequence_no')
    if not seq:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('gov_meeting_sequence'))")
        seq = next_sequence(db, m.get('entity_id') or default_entity_id(db), m['body_code'], m.get('committee_id'), d.year)
        db.execute("UPDATE board_meetings SET sequence_no = %s WHERE id = %s", (seq, m['id']))
    base = f'{prefix}-{d.year}-{int(seq):02d}-{int(item_no):02d}'
    taken = {r['res_no'] for r in db.execute("SELECT res_no FROM gov_resolution_numbers WHERE res_no LIKE %s",
                                             (base + '%',)).fetchall()}
    taken |= {r['res_no'] for r in db.execute("SELECT res_no FROM board_decisions WHERE res_no LIKE %s",
                                              (base + '%',)).fetchall()}
    return RL.resolution_number(prefix, d.year, seq, item_no, taken)


def save_resolution(db, m, ctx, rid=None):
    """Create (rid None) or change a resolution from the submitted form. Returns (rid, errors)."""
    f = request.form
    title = _s('decision_title', 500)
    text = _s('decision_text', 20000)
    errors = []
    if not text and not title:
        errors.append(_('The resolution title or text is required.'))
    agenda_id = f.get('agenda_item_id', type=int) or None
    if agenda_id and agenda_id not in {a['id'] for a in ctx['agenda']}:
        errors.append(_('Choose the agenda item from the list.'))
    circulation = m['kind_code'] == 'CIRCULATION'
    conflicted = {c['member_id'] for c in ctx['conflicts'] if c.get('did_not_vote', True)
                  and (c.get('agenda_item_id') in (None, agenda_id) or (rid and c.get('resolution_id') == rid))}
    votes, missing = _vote_inputs(ctx['rows'], conflicted, circulation)
    if missing:
        errors.append(_('Choose the vote of: %(n)s.', n=', '.join(missing)))
    for mid_, v in votes.items():
        if v['vote'] == 'AGAINST' and not v['dissent']:
            name = next((r['member_name'] for r in ctx['rows'] if r['member_id'] == mid_), '')
            errors.append(_('%(n)s voted against: record the objection / reasons (needed to challenge a resolution).', n=name))
    codes = [v['vote'] for v in votes.values()]
    chosen = (f.get('outcome') or '').upper() or None
    if chosen and chosen not in RL.OUTCOMES:
        chosen = None
    if not circulation and not ctx['q']['valid'] and chosen != 'DEFERRED':
        errors.append(_('The meeting has no quorum: a resolution cannot be adopted (record it as deferred).'))
    if circulation and RL.circulation_error('CIRCULATION', codes + ['ABSENT'] * len(missing), ctx['rule']):
        errors.append(_('Every member must vote on a resolution by circulation.'))
    category = (f.get('category_code') or '').upper() or None
    if category and category not in {c['code'] for c in ctx['cats']}:
        category = None
    link_type = (f.get('link_type') or '').upper() or None
    link_to = f.get('link_to', type=int)
    if link_type and (link_type not in RL.LINK_TYPES or not link_to or link_to == rid or not db.execute(
            "SELECT 1 FROM board_decisions WHERE id = %s", (link_to,)).fetchone()):
        errors.append(_('Choose the type of link and the earlier resolution.'))
    owner_uid = f.get('action_owner_user_id', type=int) or None
    if owner_uid and not db.execute("SELECT 1 FROM users WHERE id = %s", (owner_uid,)).fetchone():
        owner_uid = None
    if errors:
        return None, errors
    rule = ctx['rule']
    chair_vote = votes.get(m.get('chair_member_id'), {}).get('vote')
    achieved, need, note, outcome, eligible = decide(m, rule, codes, chair_vote, chosen)
    if m['body_code'] in ('OGM', 'EGM') and eligible == 0:
        note = _s('majority_note', 300) or note
    if chosen == 'APPROVED' and not achieved:
        flash(_('The required majority was not reached; the resolution is recorded as rejected.'), 'warning')
    if not m.get('chair_member_id') and RL.tally(codes)['FOR'] == RL.tally(codes)['AGAINST'] and codes:
        flash(_('No chair of the meeting is recorded: the chair\'s casting vote cannot be applied.'), 'warning')
    t = RL.tally(codes)
    owner = _s('action_owner', 200)
    if owner_uid and not owner:
        u = db.execute("SELECT first_name, last_name FROM users WHERE id = %s", (owner_uid,)).fetchone()
        owner = f"{u['first_name'] or ''} {u['last_name'] or ''}".strip() if u else None
    due = _d('due_date')
    names = {r['member_id']: r['member_name'] for r in ctx['rows']}
    dissent_all = '; '.join(f"{names.get(k, '')}: {v['dissent']}" for k, v in votes.items() if v['dissent']) or None
    dissenters = ', '.join(names.get(k, '') for k, v in votes.items() if v['vote'] == 'AGAINST') or None
    vals = dict(decision_title=title, decision_text=text or title, decision_description=text or title,
                summary=_s('summary', 2000), category_code=category, tags=_s('tags', 500), agenda_item_id=agenda_id,
                outcome=outcome, majority_rule=rule.get('majority_rule'), majority_achieved=1 if achieved else 0,
                majority_note=f"{t['FOR']}/{eligible} for; {need} needed ({note})",
                conditions=_s('conditions'), effective_date=_d('effective_date'), expiry_date=_d('expiry_date'),
                action_owner=owner, action_owner_user_id=owner_uid, due_date=due,
                responsible_person=owner, implementation_deadline=due.isoformat() if due else None,
                deadline=due.isoformat() if due else None,
                votes_for=t['FOR'], votes_against=t['AGAINST'], votes_abstain=t['ABSTAIN'],
                vote_result=RL.legacy_vote_result(outcome),
                vote_type='UNANIMOUS' if t['AGAINST'] == 0 and t['ABSTAIN'] == 0 and t['FOR'] > 0 else 'MAJORITY',
                dissent_notes=dissent_all, dissenting_reasons=dissent_all, dissenting_members=dissenters,
                followup_status=(f.get('followup_status') or ('NOT_STARTED' if (owner or due) else None)),
                search_index=None, search_version=None)
    if vals['followup_status'] and vals['followup_status'] not in RL.FOLLOWUP:
        vals['followup_status'] = None
    if rid is None:
        item_no = RL.next_item_no([r.get('item_no') for r in ctx['resolutions']])
        try:
            res_no = allocate_number(db, m, item_no)
        except NumberingError as e:
            return None, [str(e)]
        vals.update(meeting_id=m['id'], res_no=res_no, item_no=item_no, decision_number=res_no, decision_reference=res_no,
                    decision_date=m.get('meeting_date'), status='PENDING', recorded_by=current_user.id,
                    recorded_at=datetime.now(), created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    is_sample=bool(m.get('is_sample')))
        cols = list(vals)
        rid = db.execute(f"INSERT INTO board_decisions ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
                         tuple(vals[c] for c in cols)).fetchone()['id']
        db.execute("INSERT INTO gov_resolution_numbers (res_no, resolution_id, meeting_id, is_sample) VALUES (%s,%s,%s,%s)",
                   (res_no, rid, m['id'], bool(m.get('is_sample'))))
        _event(db, m['id'], 'resolution', rid, 'resolution_recorded', res_no, None, outcome)
    else:
        cols = list(vals)
        db.execute(f"UPDATE board_decisions SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
                   tuple(vals[c] for c in cols) + (rid,))
        _event(db, m['id'], 'resolution', rid, 'resolution_changed', _s('reason', 500), None, outcome)
    db.execute("DELETE FROM gov_resolution_votes WHERE resolution_id = %s", (rid,))
    for member_id, v in votes.items():
        db.execute("""INSERT INTO gov_resolution_votes (resolution_id, member_id, vote, via_proxy, dissent_text, created_by)
                      VALUES (%s,%s,%s,%s,%s,%s)""", (rid, member_id, v['vote'], v['via_proxy'], v['dissent'], current_user.id))
    if agenda_id and conflicted:
        db.execute("""UPDATE gov_conflict_declarations SET resolution_id = %s WHERE meeting_id = %s AND agenda_item_id = %s
                      AND resolution_id IS NULL""", (rid, m['id'], agenda_id))
    if link_type and link_to and link_to != rid:
        db.execute("""INSERT INTO gov_resolution_links (from_resolution_id, to_resolution_id, link_type, note, created_by)
                      VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (rid, link_to, link_type, _s('link_note', 500), current_user.id))
    RS.reindex(db, rid)
    return rid, []


@governance_bp.route('/register/meeting/<int:id>/resolutions', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def meeting_resolution_add(id):
    db = get_db()
    refused = guard_unlocked(db, id, 'resolutions')
    if refused:
        return refused
    ctx = record_context(db, id)
    rid, errors = save_resolution(db, ctx['m'], ctx)
    if errors:
        db.rollback()
        for e in errors:
            flash(e, 'danger')
        return _back(id, 'resolutions')
    db.commit()
    r = db.execute("SELECT res_no, outcome FROM board_decisions WHERE id = %s", (rid,)).fetchone()
    _audit('Board Resolution Recorded', rid, f"{r['res_no']} {r['outcome']}")
    flash(_('Resolution %(ref)s recorded.', ref=r['res_no']), 'success')
    return _back(id, 'resolutions')


def _resolution_meeting(db, rid):
    row = db.execute("SELECT meeting_id FROM board_decisions WHERE id = %s", (rid,)).fetchone()
    if not row:
        abort(404)
    return row['meeting_id']


def _resolution_locked(db, rid):
    if meeting_locked(db, _resolution_meeting(db, rid)):
        flash(_('The minutes are signed; the record can no longer be changed.'), 'danger')
        return redirect(url_for('governance.resolution_view', rid=rid))
    return None


@governance_bp.route('/register/resolution/<int:rid>')
@login_required
@permission_required('governance')
def resolution_view(rid):
    db = get_db()
    ctx = record_context(db, _resolution_meeting(db, rid))
    res = next((r for r in ctx['resolutions'] if r['id'] == rid), None)
    vote_of = {v['member_id']: v for v in res['votes']}
    return render_template('governance/resolution_view.html', res=res, vote_of=vote_of, **ctx)


@governance_bp.route('/register/resolution/<int:rid>/update', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def resolution_update(rid):
    db = get_db()
    refused = _resolution_locked(db, rid)
    if refused:
        return refused
    ctx = record_context(db, _resolution_meeting(db, rid))
    if not _s('reason'):
        flash(_('Give the reason for changing a recorded resolution.'), 'danger')
        return redirect(url_for('governance.resolution_view', rid=rid))
    _rid, errors = save_resolution(db, ctx['m'], ctx, rid=rid)
    if errors:
        db.rollback()
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('governance.resolution_view', rid=rid))
    db.commit()
    _audit('Board Resolution Changed', rid, _s('reason', 500))
    flash(_('Resolution updated.'), 'success')
    return redirect(url_for('governance.resolution_view', rid=rid))


@governance_bp.route('/register/resolution/<int:rid>/followup', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def resolution_followup(rid):
    """Implementation follow-up stays open after the minutes are signed (secretariat duty)."""
    db = get_db()
    row = db.execute("SELECT * FROM board_decisions WHERE id = %s", (rid,)).fetchone()
    if not row:
        abort(404)
    st = (request.form.get('followup_status') or '').upper()
    if st not in RL.FOLLOWUP:
        flash(_('Choose the follow-up status.'), 'danger')
        return redirect(url_for('governance.resolution_view', rid=rid))
    ev = _s('followup_evidence')
    if st == 'DONE' and not (ev or row.get('followup_evidence')):
        flash(_('Describe the evidence that the resolution was implemented.'), 'danger')
        return redirect(url_for('governance.resolution_view', rid=rid))
    due = _d('due_date') or row.get('due_date')
    db.execute("""UPDATE board_decisions SET followup_status = %s, followup_evidence = COALESCE(%s, followup_evidence),
                  followup_updated_at = NOW(), followup_updated_by = %s, due_date = %s,
                  implemented = %s, implementation_date = CASE WHEN %s THEN %s ELSE implementation_date END,
                  status = CASE WHEN %s THEN 'COMPLETED' ELSE status END, completion_date = CASE WHEN %s THEN %s ELSE completion_date END
                  WHERE id = %s""",
               (st, ev, current_user.id, due, 1 if st == 'DONE' else 0, st == 'DONE', date.today().isoformat(),
                st == 'DONE', st == 'DONE', date.today().isoformat(), rid))
    _event(db, row['meeting_id'], 'resolution', rid, 'resolution_followup', ev, row.get('followup_status'), st)
    db.commit()
    _audit('Board Resolution Follow-up', rid, f'{st}')
    flash(_('Follow-up updated.'), 'success')
    return redirect(url_for('governance.resolution_view', rid=rid))


@governance_bp.route('/register/resolution/<int:rid>/links', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def resolution_link_add(rid):
    db = get_db()
    refused = _resolution_locked(db, rid)
    if refused:
        return refused
    lt = (request.form.get('link_type') or '').upper()
    to = request.form.get('link_to', type=int)
    if lt not in RL.LINK_TYPES or not to or to == rid or not db.execute(
            "SELECT 1 FROM board_decisions WHERE id = %s", (to,)).fetchone():
        flash(_('Choose the type of link and the earlier resolution.'), 'danger')
        return redirect(url_for('governance.resolution_view', rid=rid))
    db.execute("""INSERT INTO gov_resolution_links (from_resolution_id, to_resolution_id, link_type, note, created_by)
                  VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (rid, to, lt, _s('link_note', 500), current_user.id))
    db.commit()
    _audit('Board Resolution Linked', rid, f'{lt} -> {to}')
    flash(_('Link added.'), 'success')
    return redirect(url_for('governance.resolution_view', rid=rid))


@governance_bp.route('/register/resolution/<int:rid>/links/<int:lid>/remove', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def resolution_link_remove(rid, lid):
    db = get_db()
    link = db.execute("SELECT * FROM gov_resolution_links WHERE id = %s AND (from_resolution_id = %s OR to_resolution_id = %s)",
                      (lid, rid, rid)).fetchone()
    if not link:
        abort(404)
    # the link belongs to the record of the resolution it was recorded on
    refused = _resolution_locked(db, link['from_resolution_id'])
    if refused:
        return refused
    db.execute("DELETE FROM gov_resolution_links WHERE id = %s", (lid,))
    db.commit()
    _audit('Board Resolution Link Removed', rid, str(lid))
    flash(_('Removed.'), 'info')
    return redirect(url_for('governance.resolution_view', rid=rid))


# ------------------------------------------------------------------ register & search
def _search_filters(db):
    a = request.args
    flt = dict(q=(a.get('q') or '').strip()[:300], entity=a.get('entity', type=int), body=(a.get('body') or '').upper(),
               kind=(a.get('kind') or '').upper(), category=(a.get('category') or '').upper(),
               outcome=(a.get('outcome') or '').upper(), member=a.get('member', type=int),
               date_from=RL.as_date(a.get('date_from')), date_to=RL.as_date(a.get('date_to')),
               min=max(5, min(95, a.get('min', type=int) or 30)), page=max(1, a.get('page', type=int) or 1))
    flt['sample'] = show_sample(db, flt['entity'])
    where, args = ['TRUE' if flt['sample'] else 'NOT COALESCE(m.is_sample, FALSE)'], []
    dflt = default_entity_id(db)
    if flt['entity']:
        c, ca = entity_clause('m', flt['entity'], dflt)
        where.append(c)
        args += ca
    if flt['body'] in RL.BODIES:
        if flt['body'] == 'COMMITTEE':
            where.append("(m.body = 'COMMITTEE' OR (m.body IS NULL AND m.committee_id IS NOT NULL))")
        elif flt['body'] == 'BOARD':
            where.append("(m.body = 'BOARD' OR (m.body IS NULL AND m.committee_id IS NULL AND UPPER(COALESCE(m.meeting_type, '')) NOT IN ('AGM', 'OGM', 'EGM')))")
        else:
            where.append("m.body = %s")
            args.append(flt['body'])
    if flt['kind'] in RL.KINDS:
        if flt['kind'] == 'ORDINARY':
            where.append("(m.meeting_kind = 'ORDINARY' OR (m.meeting_kind IS NULL AND UPPER(COALESCE(m.meeting_type, '')) NOT IN ('EXTRAORDINARY', 'EMERGENCY')))")
        elif flt['kind'] == 'EXTRAORDINARY':
            where.append("(m.meeting_kind = 'EXTRAORDINARY' OR (m.meeting_kind IS NULL AND UPPER(COALESCE(m.meeting_type, '')) IN ('EXTRAORDINARY', 'EMERGENCY')))")
        else:
            where.append("m.meeting_kind = %s")
            args.append(flt['kind'])
    if flt['category']:
        where.append("d.category_code = %s")
        args.append(flt['category'])
    if flt['outcome'] in RL.OUTCOMES:
        where.append("""(d.outcome = %s OR (d.outcome IS NULL AND LOWER(COALESCE(d.vote_result, '')) = %s))""")
        args += [flt['outcome'], {'APPROVED': 'passed', 'REJECTED': 'rejected', 'DEFERRED': 'deferred'}.get(flt['outcome'], '-')]
    if flt['member']:
        where.append("""(EXISTS (SELECT 1 FROM gov_resolution_votes v WHERE v.resolution_id = d.id AND v.member_id = %s)
                         OR EXISTS (SELECT 1 FROM meeting_attendance ma WHERE ma.meeting_id = m.id AND ma.member_id = %s
                                    AND (ma.attended = 1 OR COALESCE(ma.proxy_name, '') <> '')))""")
        args += [flt['member'], flt['member']]
    if flt['date_from']:
        where.append("m.meeting_date >= %s")
        args.append(flt['date_from'].isoformat())
    if flt['date_to']:
        where.append("left(m.meeting_date, 10) <= %s")
        args.append(flt['date_to'].isoformat())
    return flt, ' AND '.join(where), tuple(args)


@governance_bp.route('/register')
@login_required
@permission_required('governance')
def register_search():
    import time
    t0 = time.time()
    db = get_db()
    flt, where, args = _search_filters(db)
    base = [dict(r) for r in db.execute(f"""SELECT d.id, m.meeting_date FROM board_decisions d
                                             JOIN board_meetings m ON m.id = d.meeting_id WHERE {where}""", args).fetchall()]
    matched = {}
    if flt['q']:
        corp = RS.corpus(db)
        ranked = RS.rank(corp, flt['q'], ids={r['id'] for r in base}, min_score=flt['min'] / 100.0, limit=2000)
        order = [(rid, s) for rid, s, _m in ranked]
        matched = {rid: mt for rid, _s, mt in ranked}
    else:
        base.sort(key=lambda r: ((r['meeting_date'] or ''), r['id']), reverse=True)
        order = [(r['id'], None) for r in base]
    total = len(order)
    page_ids = order[(flt['page'] - 1) * PAGE: flt['page'] * PAGE]
    results = []
    if page_ids:
        ids = [rid for rid, _s in page_ids]
        rows = {r['id']: r for r in resolutions_with_votes(db, "d.id = ANY(%s)", (ids,))}
        meetings = {}
        for mm in db.execute("""SELECT m.id, m.committee_id, c.committee_name, c.committee_name_arabic, o.full_name AS secretary,
                                       o.full_name_ar AS secretary_ar, e.name_en AS entity_en, e.name_ar AS entity_ar
                                FROM board_meetings m LEFT JOIN board_committees c ON c.id = m.committee_id
                                LEFT JOIN gov_officers o ON o.id = m.secretary_officer_id
                                LEFT JOIN gov_entities e ON e.id = COALESCE(m.entity_id, (SELECT id FROM gov_entities WHERE is_default LIMIT 1))
                                WHERE m.id = ANY(%s)""", ([rows[i]['meeting_id'] for i in ids if i in rows],)).fetchall():
            meetings[mm['id']] = dict(mm)
        present = {}
        for a in db.execute("""SELECT ma.meeting_id, ma.member_id, bm.member_name, bm.member_name_arabic, ma.attended,
                                      ma.attended_remotely, ma.proxy_name, ma.attendance_status, ma.apology_received, ma.recorded_at,
                                      ma.proxy_holder_member_id
                               FROM meeting_attendance ma JOIN board_members bm ON bm.id = ma.member_id
                               WHERE ma.meeting_id = ANY(%s) ORDER BY bm.member_name""",
                            (list({rows[i]['meeting_id'] for i in ids if i in rows}),)).fetchall():
            a = dict(a)
            a['code'] = RL.attendance_code(a)
            present.setdefault(a['meeting_id'], []).append(a)
        for rid, s in page_ids:
            r = rows.get(rid)
            if not r:
                continue
            mt = matched.get(rid, set())
            r['score'] = round(s * 100) if s is not None else None
            r['h_title'] = RS.highlight(r.get('decision_title') or '', mt)
            r['h_summary'] = RS.highlight(r.get('summary') or '', mt)
            r['h_text'] = RS.snippet(r.get('decision_text') or r.get('decision_description') or '', mt)
            r['h_tags'] = RS.highlight(r.get('tags') or '', mt)
            r['meeting'] = meetings.get(r['meeting_id'], {})
            r['committee_name'] = r['meeting'].get('committee_name')
            r['committee_name_arabic'] = r['meeting'].get('committee_name_arabic')
            r['attendees'] = present.get(r['meeting_id'], [])
            results.append(r)
    members = [dict(r) for r in db.execute("""SELECT bm.id, bm.member_name, bm.member_name_arabic, bm.is_sample,
        e.name_en AS entity_en FROM board_members bm LEFT JOIN gov_entities e ON e.id = bm.entity_id
        WHERE COALESCE(bm.is_deleted, 0) = 0 AND (%s OR NOT bm.is_sample) ORDER BY bm.member_name""",
                                           (flt['sample'],)).fetchall()]
    cats = [dict(r) for r in db.execute("SELECT * FROM gov_resolution_categories WHERE is_active ORDER BY sort_order, id").fetchall()]
    return render_template('governance/resolution_search.html', flt=flt, results=results, total=total, page_size=PAGE,
                           entities=entities(db), members=members, cats=cats,
                           elapsed_ms=int((time.time() - t0) * 1000))


# ------------------------------------------------------------------ member profile & capacities
@governance_bp.route('/register/member/<int:mid>')
@login_required
@permission_required('governance')
def member_profile(mid):
    db = get_db()
    mem = db.execute("""SELECT bm.*, e.name_en AS entity_en, e.name_ar AS entity_ar, e.rule_codes FROM board_members bm
                        LEFT JOIN gov_entities e ON e.id = COALESCE(bm.entity_id, (SELECT id FROM gov_entities WHERE is_default LIMIT 1))
                        WHERE bm.id = %s""", (mid,)).fetchone()
    if not mem:
        abort(404)
    mem = dict(mem)
    att = [dict(r) for r in db.execute("""
        SELECT ma.*, m.meeting_date, m.meeting_reference, m.sequence_no, m.body, m.meeting_kind, m.meeting_type, m.committee_id,
               m.status AS meeting_status, c.committee_name, c.committee_name_arabic, m.id AS mid
        FROM meeting_attendance ma JOIN board_meetings m ON m.id = ma.meeting_id
        LEFT JOIN board_committees c ON c.id = m.committee_id
        WHERE ma.member_id = %s ORDER BY m.meeting_date DESC NULLS LAST""", (mid,)).fetchall()]
    today = date.today().isoformat()
    stats_rows = []
    for a in att:
        a['code'] = RL.attendance_code(a)
        a['body_code'], a['kind_code'] = derive_body(a), derive_kind(a)
        d = RL.as_date(a.get('meeting_date'))
        if d and d.isoformat() <= today and (a.get('meeting_status') or '').upper() not in ('CANCELLED', 'CANCELED', 'POSTPONED'):
            stats_rows.append(dict(member_id=(a['body_code'], a.get('committee_id')), year=d.year, code=a['code']))
    rules = composition_rules(db, mem.get('rule_codes'))
    stats = RL.attendance_stats(stats_rows, rules)
    stat_list = sorted(({'body': k[0][0], 'committee_id': k[0][1], 'year': k[1], **v} for k, v in stats.items()),
                       key=lambda x: (-x['year'], x['body'] != 'BOARD'))
    cnames = {a['committee_id']: gov_pick(a.get('committee_name'), a.get('committee_name_arabic')) for a in att if a.get('committee_id')}
    votes = [dict(r) for r in db.execute("""
        SELECT v.*, d.res_no, d.decision_number, d.decision_title, d.outcome, d.vote_result, d.meeting_id, m.meeting_date,
               m.meeting_reference
        FROM gov_resolution_votes v JOIN board_decisions d ON d.id = v.resolution_id JOIN board_meetings m ON m.id = d.meeting_id
        WHERE v.member_id = %s ORDER BY m.meeting_date DESC NULLS LAST, d.id DESC""", (mid,)).fetchall()]
    conflicts = [dict(r) for r in db.execute("""
        SELECT c.*, m.meeting_date, m.meeting_reference, ai.item_title, d.res_no FROM gov_conflict_declarations c
        JOIN board_meetings m ON m.id = c.meeting_id LEFT JOIN meeting_agenda_items ai ON ai.id = c.agenda_item_id
        LEFT JOIN board_decisions d ON d.id = c.resolution_id WHERE c.member_id = %s ORDER BY m.meeting_date DESC""",
                                              (mid,)).fetchall()]
    history = [dict(r) for r in db.execute("""
        SELECT mc.*, o.name_en, o.name_ar, o.flag, d.name_en AS dim_en, d.name_ar AS dim_ar, d.code AS dim_code
        FROM gov_member_capacities mc JOIN gov_capacity_options o ON o.id = mc.option_id
        JOIN gov_capacity_dimensions d ON d.id = o.dimension_id
        WHERE mc.member_id = %s ORDER BY (mc.effective_to IS NULL) DESC, d.sort_order, mc.effective_from DESC NULLS LAST""",
                                            (mid,)).fetchall()]
    t = date.today()
    for h in history:
        h['current'] = (not h['effective_to'] or h['effective_to'] >= t) and (not h['effective_from'] or h['effective_from'] <= t)
    options = [dict(r) for r in db.execute("""
        SELECT o.id, o.name_en, o.name_ar, d.name_en AS dim_en, d.name_ar AS dim_ar FROM gov_capacity_options o
        JOIN gov_capacity_dimensions d ON d.id = o.dimension_id WHERE o.is_active AND d.is_active AND d.applies_to = 'MEMBER'
        ORDER BY d.sort_order, o.sort_order, o.id""").fetchall()]
    return render_template('governance/member_profile.html', mem=mem, att=att, stats=stat_list, cnames=cnames, votes=votes,
                           dissents=[v for v in votes if v['vote'] == 'AGAINST' or v.get('dissent_text')],
                           recusals=[v for v in votes if v['vote'] == 'RECUSED'], conflicts=conflicts, history=history,
                           options=options, entities=entities(db, include_sample=bool(mem.get('is_sample'))), rules=rules,
                           current=[h for h in history if h['current']])


def composition_rules(db, codes):
    codes = [c.strip() for c in (codes or '').split(',') if c.strip()]
    if not codes:
        return []
    return [dict(r) for r in db.execute("SELECT * FROM gov_composition_rules WHERE code = ANY(%s) AND is_active",
                                        (codes,)).fetchall()]


@governance_bp.route('/register/member/<int:mid>/capacities', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def member_capacity_add(mid):
    db = get_db()
    if not db.execute("SELECT 1 FROM board_members WHERE id = %s", (mid,)).fetchone():
        abort(404)
    oid = request.form.get('option_id', type=int)
    opt = db.execute("""SELECT o.*, d.multi_select, d.code AS dim_code FROM gov_capacity_options o
                        JOIN gov_capacity_dimensions d ON d.id = o.dimension_id WHERE o.id = %s""", (oid,)).fetchone() if oid else None
    if not opt:
        flash(_('Choose the capacity.'), 'danger')
        return redirect(url_for('governance.member_profile', mid=mid) + '#capacities')
    start = _d('effective_from') or date.today()
    end = _d('effective_to')
    if end and end < start:
        flash(_('The end date cannot be before the start date.'), 'danger')
        return redirect(url_for('governance.member_profile', mid=mid) + '#capacities')
    if not opt['multi_select']:
        # one current capacity per dimension: the previous one ends the day before
        db.execute("""UPDATE gov_member_capacities mc SET effective_to = %s, ended_at = NOW(), ended_by = %s
                      FROM gov_capacity_options o WHERE o.id = mc.option_id AND o.dimension_id = %s AND mc.member_id = %s
                      AND mc.option_id <> %s AND (mc.effective_to IS NULL OR mc.effective_to >= %s)
                      AND (mc.effective_from IS NULL OR mc.effective_from <= %s)""",
                   (start - timedelta(days=1), current_user.id, opt['dimension_id'], mid, oid, start, start))
    db.execute("""INSERT INTO gov_member_capacities (member_id, option_id, effective_from, effective_to, represented_entity,
                  note, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (mid, oid, start, end, _s('represented_entity', 300), _s('note', 500), current_user.id))
    sync_legacy_flags(db, mid)
    db.commit()
    _audit('Board Member Capacity Added', mid, f"{opt['code']} from {start}")
    flash(_('Capacity recorded.'), 'success')
    return redirect(url_for('governance.member_profile', mid=mid) + '#capacities')


@governance_bp.route('/register/member/<int:mid>/capacities/<int:cid>/<action>', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def member_capacity_change(mid, cid, action):
    db = get_db()
    row = db.execute("SELECT * FROM gov_member_capacities WHERE id = %s AND member_id = %s", (cid, mid)).fetchone()
    if not row or action not in ('end', 'remove'):
        abort(404)
    if action == 'end':
        on = _d('effective_to') or date.today()
        db.execute("UPDATE gov_member_capacities SET effective_to = %s, ended_at = NOW(), ended_by = %s WHERE id = %s",
                   (on, current_user.id, cid))
    else:
        db.execute("DELETE FROM gov_member_capacities WHERE id = %s", (cid,))
    sync_legacy_flags(db, mid)
    db.commit()
    _audit('Board Member Capacity ' + action.title(), mid, f'capacity {cid}')
    flash(_('Saved.'), 'success')
    return redirect(url_for('governance.member_profile', mid=mid) + '#capacities')


@governance_bp.route('/register/member/<int:mid>/facts', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def member_facts(mid):
    """Gender, nationality, board and other seats: only the fields submitted are changed."""
    db = get_db()
    mem = db.execute("SELECT * FROM board_members WHERE id = %s", (mid,)).fetchone()
    if not mem:
        abort(404)
    f = request.form
    sets, args = [], []
    if 'gender' in f:
        g = (f.get('gender') or '').upper() or None
        sets.append('gender = %s')
        args.append(g if g in ('F', 'M') else None)
    if 'nationality' in f:
        sets.append('nationality = %s')
        args.append(_s('nationality', 100))
    if 'other_board_seats' in f:
        sets.append('other_board_seats = %s')
        args.append(_int(f.get('other_board_seats')) if (f.get('other_board_seats') or '').strip() else None)
    if 'entity_id' in f:
        dflt = default_entity_id(db)
        ent = f.get('entity_id', type=int) or dflt
        e = db.execute("SELECT * FROM gov_entities WHERE id = %s AND is_active", (ent,)).fetchone()
        if not e or (e['is_sample'] and not mem['is_sample']):
            flash(_('Choose the board.'), 'danger')
            return redirect(url_for('governance.member_profile', mid=mid))
        sets.append('entity_id = %s')
        args.append(None if ent == dflt else ent)
    if sets:
        db.execute(f"UPDATE board_members SET {', '.join(sets)} WHERE id = %s", tuple(args) + (mid,))
        db.commit()
        _audit('Board Member Details Changed', mid, ', '.join(x.split(' ')[0] for x in sets))
    flash(_('Saved.'), 'success')
    return redirect(url_for('governance.member_profile', mid=mid))


# ------------------------------------------------------------------ secretary view
@governance_bp.route('/register/secretaries')
@login_required
@permission_required('governance')
def secretary_view():
    db = get_db()
    officers = [dict(r) for r in db.execute("""
        SELECT o.*, op.name_en AS role_en, op.name_ar AS role_ar, op.flag,
               (SELECT COUNT(*) FROM board_meetings m WHERE m.secretary_officer_id = o.id) AS n_meetings,
               (SELECT COUNT(*) FROM gov_meeting_officers t WHERE t.officer_id = o.id) AS n_roles
        FROM gov_officers o LEFT JOIN gov_capacity_options op ON op.id = o.role_option_id
        WHERE %s OR NOT o.is_sample OR o.id = %s
        ORDER BY (op.flag = 'secretary') DESC NULLS LAST, o.full_name""",
        (request.args.get('sample') == '1', request.args.get('officer', type=int) or 0)).fetchall()]
    sel = request.args.get('officer', type=int)
    if not sel:
        sel = next((o['id'] for o in officers if o['n_meetings']), None)
    meetings, followups, alerts = [], [], {'filing_overdue': 0, 'signature_overdue': 0, 'followup_overdue': 0}
    officer = next((o for o in officers if o['id'] == sel), None)
    if officer:
        today = date.today()
        meetings = [dict(r) for r in db.execute("""
            SELECT m.*, c.committee_name, c.committee_name_arabic,
                   (SELECT COUNT(*) FROM board_decisions d WHERE d.meeting_id = m.id) AS n_resolutions,
                   (SELECT COUNT(*) FROM meeting_minutes mm WHERE mm.meeting_id = m.id AND mm.status = 'approved') AS n_approved
            FROM board_meetings m LEFT JOIN board_committees c ON c.id = m.committee_id
            WHERE m.secretary_officer_id = %s ORDER BY m.meeting_date DESC""", (sel,)).fetchall()]
        for m in meetings:
            m['body_code'], m['kind_code'] = derive_body(m), derive_kind(m)
            m['_minutes_state'] = RL.minutes_state(m, m['n_approved'] > 0)
            m['flags'] = RL.meeting_flags(m, today)
            for f in m['flags']:
                alerts[f] += 1
        if meetings:
            followups = [r for r in resolutions_with_votes(db, "d.meeting_id = ANY(%s)", ([m['id'] for m in meetings],))
                         if r['fu_state'] in ('open', 'overdue')]
            followups.sort(key=lambda r: (r['fu_state'] != 'overdue', str(r.get('due_date') or '9999')))
            alerts['followup_overdue'] = sum(1 for r in followups if r['fu_state'] == 'overdue')
        tellers = [dict(r) for r in db.execute("""SELECT t.role, m.id, m.meeting_reference, m.meeting_date FROM gov_meeting_officers t
                    JOIN board_meetings m ON m.id = t.meeting_id WHERE t.officer_id = %s ORDER BY m.meeting_date DESC""", (sel,)).fetchall()]
    else:
        tellers = []
    return render_template('governance/secretary_view.html', officers=officers, officer=officer, meetings=meetings,
                           followups=followups, alerts=alerts, tellers=tellers)


# ------------------------------------------------------------------ reports
def _report_entity(db):
    dflt = default_entity_id(db)
    ent = request.args.get('entity', type=int) or dflt
    e = db.execute("SELECT * FROM gov_entities WHERE id = %s", (ent,)).fetchone()
    return ent, dflt, dict(e) if e else {}


@governance_bp.route('/register/reports/attendance')
@login_required
@permission_required('governance')
def report_attendance():
    db = get_db()
    ent, dflt, e = _report_entity(db)
    year = request.args.get('year', type=int) or date.today().year
    clause, args = entity_clause('m', ent, dflt)
    rows = [dict(r) for r in db.execute(f"""
        SELECT ma.*, m.meeting_date, m.body, m.committee_id, m.meeting_type, m.meeting_kind, bm.member_name,
               bm.member_name_arabic, c.committee_name, c.committee_name_arabic
        FROM meeting_attendance ma JOIN board_meetings m ON m.id = ma.meeting_id
        JOIN board_members bm ON bm.id = ma.member_id LEFT JOIN board_committees c ON c.id = m.committee_id
        WHERE {clause} AND m.meeting_date ~ '^[0-9]{{4}}' AND left(m.meeting_date, 4) = %s
          AND left(m.meeting_date, 10) <= %s
          AND UPPER(COALESCE(m.status, '')) NOT IN ('CANCELLED', 'CANCELED', 'POSTPONED')""",
                                         args + (str(year), date.today().isoformat())).fetchall()]
    rules = composition_rules(db, e.get('rule_codes'))
    groups = {}
    names = {}
    for r in rows:
        r['code'] = RL.attendance_code(r)
        b = derive_body(r)
        key = ('BOARD', None) if b == 'BOARD' else (b, r.get('committee_id'))
        groups.setdefault(key, []).append(dict(member_id=r['member_id'], year=year, code=r['code']))
        names[r['member_id']] = gov_pick(r['member_name'], r['member_name_arabic'])
        if r.get('committee_id'):
            names[('c', r['committee_id'])] = gov_pick(r.get('committee_name'), r.get('committee_name_arabic'))
    tables = []
    for key in sorted(groups, key=lambda k: (k[0] != 'BOARD', str(k))):
        st = RL.attendance_stats(groups[key], rules if key[0] == 'BOARD' else ())
        n_meetings = len({(r['meeting_id']) for r in rows if (('BOARD', None) if derive_body(r) == 'BOARD'
                                                               else (derive_body(r), r.get('committee_id'))) == key})
        tables.append(dict(key=key, title=names.get(('c', key[1])) if key[1] else None, n_meetings=n_meetings,
                           rows=sorted(({'member_id': k[0], 'name': names.get(k[0]), **v} for k, v in st.items()),
                                       key=lambda x: x['name'] or '')))
    years = [int(r['y']) for r in db.execute("""SELECT DISTINCT left(meeting_date, 4) AS y FROM board_meetings
                                               WHERE meeting_date ~ '^[0-9]{4}' ORDER BY 1 DESC""").fetchall()]
    return render_template('governance/report_attendance.html', tables=tables, rules=rules, year=year, years=years,
                           entities=entities(db), entity=ent, e=e)


@governance_bp.route('/register/reports/board-list')
@login_required
@permission_required('governance')
def report_board_list():
    db = get_db()
    ent, dflt, e = _report_entity(db)
    on = RL.as_date(request.args.get('on')) or date.today()
    clause, args = entity_clause('bm', ent, dflt)
    members = [dict(r) for r in db.execute(f"""SELECT bm.* FROM board_members bm WHERE {clause}
        AND COALESCE(bm.is_deleted, 0) = 0 AND (bm.status = 'ACTIVE' OR (bm.resignation_date ~ '^[0-9]{{4}}-' AND left(bm.resignation_date, 10) > %s))
        AND (COALESCE(bm.appointment_date, '') !~ '^[0-9]{{4}}-' OR left(bm.appointment_date, 10) <= %s)
        ORDER BY bm.member_name""", args + (on.isoformat(), on.isoformat())).fetchall()]
    caps = member_caps(db, [m['id'] for m in members], on)
    dims = [dict(r) for r in db.execute("""SELECT * FROM gov_capacity_dimensions WHERE is_active AND applies_to = 'MEMBER'
                                           ORDER BY sort_order, id""").fetchall()]
    order = {'chair': 0, 'chair_md': 0, 'vice_chair': 1, 'md': 2, 'ceo': 3}
    for m in members:
        m['caps'] = caps.get(m['id'], [])
        m['by_dim'] = {}
        for c in m['caps']:
            m['by_dim'].setdefault(c['dim_code'], []).append(c)
        fl = flags_of(m['caps'], m)
        m['rank'] = min([order.get(f, 9) for f in fl] or [9])
        m['represents'] = '; '.join(c['represented_entity'] for c in m['caps'] if c.get('represented_entity'))
    members.sort(key=lambda m: (m['rank'], m['member_name'] or ''))
    officers = [dict(r) for r in db.execute("""SELECT o.*, op.name_en AS role_en, op.name_ar AS role_ar FROM gov_officers o
        LEFT JOIN gov_capacity_options op ON op.id = o.role_option_id WHERE o.is_active AND op.flag = 'secretary'
        AND (o.entity_id IS NULL OR o.entity_id = %s)""", (ent,)).fetchall()]
    return render_template('governance/report_board_list.html', members=members, dims=dims, on=on, e=e,
                           entities=entities(db), entity=ent, officers=officers)


@governance_bp.route('/register/reports/follow-up')
@login_required
@permission_required('governance')
def report_followup():
    db = get_db()
    dflt = default_entity_id(db)
    ent = request.args.get('entity', type=int)
    show = request.args.get('show', 'open')
    clause, args = entity_clause('m', ent, dflt)
    with_sample = show_sample(db, ent)
    if not with_sample:
        clause += ' AND NOT COALESCE(m.is_sample, FALSE)'
    res = resolutions_with_votes(db, clause + " AND (d.action_owner IS NOT NULL OR d.due_date IS NOT NULL OR d.followup_status IS NOT NULL)", args)
    if show == 'overdue':
        res = [r for r in res if r['fu_state'] == 'overdue']
    elif show == 'open':
        res = [r for r in res if r['fu_state'] in ('open', 'overdue')]
    res.sort(key=lambda r: (r['fu_state'] != 'overdue', str(r.get('due_date') or '9999'), r['id']))
    legacy_actions = db.execute("""SELECT COUNT(*) AS n FROM meeting_action_items WHERE UPPER(COALESCE(status, 'PENDING'))
                                   NOT IN ('COMPLETED', 'CANCELLED') AND due_date ~ '^[0-9]{4}-' AND left(due_date, 10) < %s""",
                                (date.today().isoformat(),)).fetchone()['n']
    return render_template('governance/report_followup.html', res=res, show=show, entities=entities(db), entity=ent,
                           with_sample=with_sample,
                           overdue=sum(1 for r in res if r['fu_state'] == 'overdue'), legacy_actions=legacy_actions)
