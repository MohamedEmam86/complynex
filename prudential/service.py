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

"""
Service layer for the prudential / governance / financial-reporting registers.
Pages, checks and imports go through here; finance figures come through the
provider interface (providers.py) so an ERP can feed them later.
"""

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from database.db import get_db

from . import logic, providers


def N_(s):
    """Mark a message for translation (shown translated by the page)."""
    return s


class PrudentialError(ValueError):
    pass


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def _safe_rows(db, sql, args=()):
    try:
        return _rows(db, sql, args)
    except Exception:
        db.rollback()
        return []


def param(key, default=None):
    if not key:
        return default
    from regcontrols.api import get_param
    from regcontrols.engine import company_licence_type
    return get_param(key, company_licence_type(), default=default)


def _num(v):
    if v in (None, ''):
        return None
    try:
        return Decimal(str(v).replace(',', '').strip())
    except InvalidOperation:
        raise PrudentialError(f'not a number: {v}')


def _date(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        raise PrudentialError(f'not a date (YYYY-MM-DD): {v}')


def has_files(record_type, record_id, db=None):
    db = db or get_db()
    r = _safe_rows(db, """SELECT 1 FROM generic_attachments WHERE module = 'prudential' AND record_type = %s
                          AND record_id = %s AND COALESCE(is_deleted, 0) = 0 LIMIT 1""", (record_type, record_id))
    return bool(r)


# ------------------------------------------------------------------ corporate profile & documents
PROFILE_FIELDS = ('legal_name_en', 'legal_name_ar', 'registered_address_en', 'registered_address_ar',
                  'commercial_register_no', 'tax_card_no', 'licence_number', 'licence_type', 'phone', 'email', 'website')


def profile(db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM corp_profile WHERE id = 1").fetchone()
    return dict(r) if r else {}


def save_profile(data, user_id, db=None):
    db = db or get_db()
    vals = [(data.get(k) or '').strip() or None for k in PROFILE_FIELDS]
    aliases = [a.strip() for a in (data.get('address_aliases') or '').splitlines() if a.strip()]
    db.execute("INSERT INTO corp_profile (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    db.execute(f"""UPDATE corp_profile SET {', '.join(f'{k} = %s' for k in PROFILE_FIELDS)}, address_aliases = %s,
                   regulator_id = %s, updated_by = %s, updated_at = %s WHERE id = 1""",
               (*vals, aliases, data.get('regulator_id') or None, user_id, datetime.now()))
    db.commit()


def registered_addresses(prof):
    return [a for a in (prof.get('registered_address_en'), prof.get('registered_address_ar')) if a]


def document_ok(doc, prof):
    """True / False / None (no address stated)."""
    if doc.get('reviewed_ok') is not None:
        return doc['reviewed_ok']
    if not (doc.get('address_on_document') or '').strip():
        return None
    regs = registered_addresses(prof)
    return any(logic.address_matches(doc['address_on_document'], r, prof.get('address_aliases') or []) for r in regs) \
        if regs else False


def documents(db=None):
    db = db or get_db()
    prof = profile(db)
    rows = _rows(db, "SELECT * FROM pr_documents ORDER BY COALESCE(doc_date, created_at::date) DESC, id DESC")
    for d in rows:
        d['address_ok'] = document_ok(d, prof)
    return rows


def add_document(data, user_id, db=None):
    db = db or get_db()
    if not (data.get('title') or '').strip():
        raise PrudentialError(N_('title is required'))
    rid = db.execute("""INSERT INTO pr_documents (doc_type, title, doc_date, address_on_document, source_module,
                        source_record_id, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (data.get('doc_type') or 'letter', data['title'].strip(), _date(data.get('doc_date')),
                      (data.get('address_on_document') or '').strip() or None, data.get('source_module') or None,
                      data.get('source_record_id') or None, user_id)).fetchone()['id']
    db.commit()
    return rid


def review_document(doc_id, ok, note, db=None):
    db = db or get_db()
    db.execute("UPDATE pr_documents SET reviewed_ok = %s, review_note = %s WHERE id = %s", (ok, note, doc_id))
    db.commit()


# ------------------------------------------------------------------ capital
def capital_events(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM pr_capital_events ORDER BY effective_date DESC, id DESC")


def add_capital_event(data, user_id, db=None):
    db = db or get_db()
    if data.get('capital_type') not in logic.CAPITAL_TYPES:
        raise PrudentialError(N_('choose a capital type'))
    amount, eff = _num(data.get('amount')), _date(data.get('effective_date'))
    if amount is None or not eff:
        raise PrudentialError(N_('amount and date are required'))
    rid = db.execute("""INSERT INTO pr_capital_events (capital_type, amount, currency, effective_date, reference, note,
                        created_by) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (data['capital_type'], amount, data.get('currency') or 'EGP', eff, data.get('reference') or None,
                      data.get('note') or None, user_id)).fetchone()['id']
    db.commit()
    return rid


def capital_position(db=None, as_of=None, min_param='capital.min_paid_up'):
    db = db or get_db()
    levels = logic.capital_levels(capital_events(db), as_of)
    minimum = param(min_param)
    return {'levels': levels, 'minimum': minimum, 'issues': logic.capital_issues(levels, minimum)}


# ------------------------------------------------------------------ deadlines
def deadlines(db=None, include_closed=True):
    db = db or get_db()
    rows = _rows(db, """SELECT d.*, r.regulator_name, (SELECT count(*) FROM pr_deadline_extensions e WHERE e.deadline_id = d.id)
                        AS extensions FROM pr_deadlines d LEFT JOIN regulators r ON r.id = d.regulator_id
                        ORDER BY (d.status = 'open') DESC, d.due_date""")
    th = alert_thresholds()
    for d in rows:
        d['state'] = logic.deadline_state(d, thresholds=th)
        d['days_left'] = logic.days_left(d['due_date'])
    return rows if include_closed else [d for d in rows if d['status'] == 'open']


def alert_thresholds():
    v = param('capital.deadline_alert_days', default=None)
    try:
        return sorted({int(x) for x in (v or [60, 30, 7])}, reverse=True)
    except (TypeError, ValueError):
        return [60, 30, 7]


def save_deadline(data, user_id, deadline_id=None, db=None):
    db = db or get_db()
    due = _date(data.get('due_date'))
    if not (data.get('title') or '').strip() or not due:
        raise PrudentialError(N_('title and due date are required'))
    cat = data.get('category') if data.get('category') in ('capital_increase', 'licence', 'remediation', 'submission',
                                                             'other') else 'other'
    if deadline_id:
        db.execute("""UPDATE pr_deadlines SET title = %s, category = %s, regulator_id = %s, owner_user_id = %s, note = %s
                      WHERE id = %s""", (data['title'].strip(), cat, data.get('regulator_id') or None,
                                         data.get('owner_user_id') or None, data.get('note') or None, deadline_id))
    else:
        deadline_id = db.execute("""INSERT INTO pr_deadlines (title, category, regulator_id, original_due_date, due_date,
                                    owner_user_id, note, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                                 (data['title'].strip(), cat, data.get('regulator_id') or None, due, due,
                                  data.get('owner_user_id') or None, data.get('note') or None, user_id)).fetchone()['id']
    db.commit()
    return deadline_id


def add_extension(deadline_id, data, user_id, db=None):
    db = db or get_db()
    d = db.execute("SELECT * FROM pr_deadlines WHERE id = %s", (deadline_id,)).fetchone()
    if not d:
        raise PrudentialError(N_('deadline not found'))
    new_due, granted = _date(data.get('new_due_date')), _date(data.get('granted_on'))
    if not new_due or not granted:
        raise PrudentialError(N_('grant date and new due date are required'))
    if new_due <= d['due_date']:
        raise PrudentialError(N_('an extension must move the due date later'))
    db.execute("""INSERT INTO pr_deadline_extensions (deadline_id, extension_type, granted_on, new_due_date, letter_ref, note,
                  created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (deadline_id, 'general' if data.get('extension_type') == 'general' else 'special', granted, new_due,
                data.get('letter_ref') or None, data.get('note') or None, user_id))
    db.execute("""UPDATE pr_deadlines SET due_date = %s, notified_thresholds = '{}', board_escalated_at = NULL,
                  status = 'open' WHERE id = %s""", (new_due, deadline_id))
    db.commit()


def extensions(deadline_id, db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM pr_deadline_extensions WHERE deadline_id = %s ORDER BY granted_on", (deadline_id,))


def close_deadline(deadline_id, status, met_on=None, db=None):
    db = db or get_db()
    if status not in ('met', 'missed', 'cancelled'):
        raise PrudentialError(N_('invalid status'))
    db.execute("UPDATE pr_deadlines SET status = %s, met_on = %s WHERE id = %s",
               (status, _date(met_on) or date.today() if status == 'met' else None, deadline_id))
    db.commit()


def deadline_sweep(db=None, today=None):
    """Countdown notifications (owner + compliance heads) and board escalation
    (a critical finding) for open deadlines. Returns counts."""
    db = db or get_db()
    today = today or date.today()
    th = alert_thresholds()
    from regcontrols.alerts import compliance_heads
    from regcontrols.api import raise_finding
    from services.notification_service import notify
    sent = escalated = 0
    for d in _rows(db, "SELECT * FROM pr_deadlines WHERE status = 'open'"):
        left = logic.days_left(d['due_date'], today)
        new = logic.thresholds_to_send(left, th, d['notified_thresholds'])
        if new or (left < 0 and -1 not in (d['notified_thresholds'] or [])):
            msg = (f"{d['title']}: due {d['due_date']} ({left} day(s) left)" if left >= 0
                   else f"{d['title']}: OVERDUE since {d['due_date']}")
            notify([d['owner_user_id'], *compliance_heads(db)], 'Regulatory deadline', msg,
                   link=f"/prudential/deadlines/{d['id']}", category='warning', channels=('inapp', 'email'))
            marks = list(d['notified_thresholds'] or []) + new + ([-1] if left < 0 else [])
            db.execute("UPDATE pr_deadlines SET notified_thresholds = %s WHERE id = %s", (sorted(set(marks)), d['id']))
            sent += 1
        if logic.needs_board_escalation(d, today, th):
            fid = raise_finding(f"Regulatory deadline at risk — {d['title']}", source='self_identified',
                                source_ref=f"pr_deadline:{d['id']}", severity='critical', due_date=d['due_date'],
                                description=f"Due {d['due_date']} ({left} day(s)). Escalated to the board of directors.",
                                dedupe=True, db=db)
            db.execute("UPDATE pr_deadlines SET board_escalated_at = %s, finding_id = %s WHERE id = %s",
                       (datetime.now(), fid, d['id']))
            escalated += 1
        db.commit()
    return {'notified': sent, 'escalated': escalated}


# ------------------------------------------------------------------ financial periods (solvency)
PERIOD_FIELDS = ('total_assets', 'total_liabilities', 'equity', 'paid_up_capital', 'capital_base', 'revenue',
                 'net_profit', 'loan_portfolio')


def periods(db=None):
    db = db or get_db()
    rows = providers.get().financial_periods(db)
    for p in rows:
        p['ratios'] = logic.ratios(p)
    return rows


def solvency_limits(cfg=None):
    cfg = cfg or {}
    return {'max_leverage': param(cfg.get('max_leverage_param') or 'solvency.max_leverage_ratio'),
            'min_equity': param(cfg.get('min_equity_param') or 'solvency.min_equity'),
            'min_capital_base': param(cfg.get('min_capital_base_param') or 'solvency.min_capital_base')}


def save_period(data, user_id, source='manual', db=None):
    db = db or get_db()
    pe = _date(data.get('period_end'))
    if not pe:
        raise PrudentialError(N_('period end is required'))
    vals = [_num(data.get(k)) for k in PERIOD_FIELDS]
    ptype = data.get('period_type') if data.get('period_type') in ('month', 'quarter', 'half', 'year') else 'quarter'
    ex = db.execute("SELECT id, status FROM pr_financial_periods WHERE period_end = %s", (pe,)).fetchone()
    if ex and ex['status'] == 'approved':
        raise PrudentialError(f'{pe} is approved; it cannot be changed')
    if ex:
        db.execute(f"""UPDATE pr_financial_periods SET period_type = %s, {', '.join(f'{k} = %s' for k in PERIOD_FIELDS)},
                       source = %s WHERE id = %s""", (ptype, *vals, source, ex['id']))
        pid = ex['id']
    else:
        pid = db.execute(f"""INSERT INTO pr_financial_periods (period_end, period_type, {', '.join(PERIOD_FIELDS)}, source,
                             created_by) VALUES (%s,%s,{', '.join(['%s'] * len(PERIOD_FIELDS))},%s,%s) RETURNING id""",
                         (pe, ptype, *vals, source, user_id)).fetchone()['id']
    db.commit()
    return pid


def approve_period(period_id, user_id, db=None):
    db = db or get_db()
    p = db.execute("SELECT * FROM pr_financial_periods WHERE id = %s", (period_id,)).fetchone()
    if not p:
        raise PrudentialError(N_('period not found'))
    if p['created_by'] == user_id:
        raise PrudentialError(N_('figures must be approved by someone other than the person who entered them'))
    db.execute("UPDATE pr_financial_periods SET status = 'approved', approved_by = %s, approved_at = %s WHERE id = %s",
               (user_id, datetime.now(), period_id))
    db.commit()


PERIOD_CSV = ['period_end', 'period_type', *PERIOD_FIELDS]


def import_periods(text, user_id, db=None):
    """CSV with header PERIOD_CSV. Returns (ok, errors)."""
    ok, errors = 0, []
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            save_period(row, user_id, source='import', db=db)
            ok += 1
        except PrudentialError as e:
            errors.append(f'line {i}: {e}')
    return ok, errors


# ------------------------------------------------------------------ key functions
def function_types(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM pr_key_function_types ORDER BY sort_order, code")


def key_functions(db=None, current_only=True):
    db = db or get_db()
    sql = """SELECT k.*, t.name_en, t.name_ar, COALESCE(u.first_name || ' ' || u.last_name, k.holder_name) AS holder
             FROM pr_key_functions k JOIN pr_key_function_types t ON t.code = k.function_code
             LEFT JOIN users u ON u.id = k.holder_user_id"""
    if current_only:
        sql += " WHERE k.vacated_on IS NULL"
    return _rows(db, sql + " ORDER BY t.sort_order, k.id")


def key_function_matrix(db=None):
    db = db or get_db()
    cur = {}
    for k in key_functions(db):
        cur.setdefault(k['function_code'], k)
    out = []
    for t in function_types(db):
        h = cur.get(t['code'])
        out.append({'type': t, 'holder': h, 'issues': logic.key_function_issues(t, h)})
    return out


def _fit_proper_from_governance(board_member_id, db):
    if not board_member_id:
        return None, None
    r = _safe_rows(db, """SELECT assessment_result, assessment_date FROM fit_proper_assessments WHERE member_id = %s
                          ORDER BY assessment_date DESC LIMIT 1""", (board_member_id,))
    if not r:
        return None, None
    res = (r[0]['assessment_result'] or '').upper()
    return ('passed' if res in ('APPROVED', 'CONDITIONAL') else 'failed' if res == 'REJECTED' else 'pending'), \
        r[0]['assessment_date']


def save_key_function(data, user_id, kf_id=None, db=None):
    db = db or get_db()
    if not db.execute("SELECT 1 FROM pr_key_function_types WHERE code = %s", (data.get('function_code'),)).fetchone():
        raise PrudentialError(N_('choose a key function'))
    if not (data.get('holder_user_id') or (data.get('holder_name') or '').strip()):
        raise PrudentialError(N_('name the holder'))
    fp, fp_date = _fit_proper_from_governance(data.get('board_member_id') or None, db)
    fp = fp or (data.get('fit_proper_status') if data.get('fit_proper_status') in ('pending', 'passed', 'failed', 'na')
                else 'pending')
    fp_date = fp_date or _date(data.get('fit_proper_date'))
    no = data.get('no_objection_status') if data.get('no_objection_status') in (
        'not_required', 'pending', 'granted', 'refused') else 'not_required'
    vals = (data['function_code'], data.get('holder_user_id') or None, (data.get('holder_name') or '').strip() or None,
            data.get('board_member_id') or None, _date(data.get('appointed_on')), _date(data.get('vacated_on')), fp,
            fp_date, _date(data.get('regulator_notified_on')), data.get('regulator_ref') or None, no,
            _date(data.get('no_objection_on')), data.get('note') or None, user_id, datetime.now())
    cols = ('function_code, holder_user_id, holder_name, board_member_id, appointed_on, vacated_on, fit_proper_status, '
            'fit_proper_date, regulator_notified_on, regulator_ref, no_objection_status, no_objection_on, note, '
            'updated_by, updated_at')
    if kf_id:
        db.execute(f"UPDATE pr_key_functions SET ({cols}) = ({', '.join(['%s'] * 15)}) WHERE id = %s", (*vals, kf_id))
    else:
        kf_id = db.execute(f"INSERT INTO pr_key_functions ({cols}) VALUES ({', '.join(['%s'] * 15)}) RETURNING id",
                           vals).fetchone()['id']
    db.commit()
    return kf_id


def save_function_type(data, db=None):
    db = db or get_db()
    code = (data.get('code') or '').strip().lower()
    if not code or not data.get('name_en'):
        raise PrudentialError(N_('code and English name are required'))
    db.execute("""INSERT INTO pr_key_function_types (code, name_en, name_ar, is_required, notify_regulator, needs_no_objection)
                  VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (code) DO UPDATE SET name_en = EXCLUDED.name_en,
                  name_ar = EXCLUDED.name_ar, is_required = EXCLUDED.is_required,
                  notify_regulator = EXCLUDED.notify_regulator, needs_no_objection = EXCLUDED.needs_no_objection""",
               (code, data['name_en'], data.get('name_ar') or None, bool(data.get('is_required')),
                bool(data.get('notify_regulator')), bool(data.get('needs_no_objection'))))
    db.commit()


# ------------------------------------------------------------------ branches & staffing
def branches(db=None):
    db = db or get_db()
    return _rows(db, """SELECT b.*, COALESCE(u.first_name || ' ' || u.last_name, b.manager_name) AS manager
                        FROM pr_branches b LEFT JOIN users u ON u.id = b.manager_user_id ORDER BY b.code""")


def save_branch(data, user_id, branch_id=None, db=None):
    db = db or get_db()
    code = (data.get('code') or '').strip()
    if not code or not (data.get('name_en') or '').strip():
        raise PrudentialError(N_('code and name are required'))
    status = data.get('status') if data.get('status') in ('planned', 'active', 'closed') else 'planned'
    no = data.get('manager_no_objection') if data.get('manager_no_objection') in (
        'not_required', 'pending', 'granted', 'refused') else 'pending'
    mgr = (data.get('manager_name') or '').strip() or None
    mgr_uid = data.get('manager_user_id') or None
    vacant_since = _date(data.get('manager_vacant_since'))
    if not (mgr or mgr_uid) and not vacant_since:
        vacant_since = date.today()
    if mgr or mgr_uid:
        vacant_since = None
    if status == 'active' and (mgr or mgr_uid) and no not in ('granted', 'not_required'):
        raise PrudentialError(N_('a branch can be active only with a manager who has the regulator no-objection'))
    vals = (code, data['name_en'].strip(), data.get('name_ar') or None, data.get('address') or None,
            data.get('org_unit_id') or None, status, _date(data.get('opened_on')), mgr, mgr_uid, no,
            data.get('manager_no_objection_ref') or None, _date(data.get('manager_no_objection_on')), vacant_since,
            user_id, datetime.now())
    cols = ('code, name_en, name_ar, address, org_unit_id, status, opened_on, manager_name, manager_user_id, '
            'manager_no_objection, manager_no_objection_ref, manager_no_objection_on, manager_vacant_since, '
            'updated_by, updated_at')
    if branch_id:
        db.execute(f"UPDATE pr_branches SET ({cols}) = ({', '.join(['%s'] * 15)}) WHERE id = %s", (*vals, branch_id))
    else:
        branch_id = db.execute(f"INSERT INTO pr_branches ({cols}) VALUES ({', '.join(['%s'] * 15)}) RETURNING id",
                               vals).fetchone()['id']
    db.commit()
    return branch_id


def branch_roles(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM pr_branch_roles ORDER BY code")


def role_minimums(roles):
    out = {}
    for r in roles:
        if r.get('param_key'):
            out[r['code']] = param(r['param_key'])
        else:
            out[r['code']] = r.get('min_count')
    return out


def save_branch_role(data, db=None):
    db = db or get_db()
    code = (data.get('code') or '').strip().lower()
    if not code or not data.get('name_en'):
        raise PrudentialError(N_('code and English name are required'))
    db.execute("""INSERT INTO pr_branch_roles (code, name_en, name_ar, min_count, param_key, is_active)
                  VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (code) DO UPDATE SET name_en = EXCLUDED.name_en,
                  name_ar = EXCLUDED.name_ar, min_count = EXCLUDED.min_count, param_key = EXCLUDED.param_key,
                  is_active = EXCLUDED.is_active""",
               (code, data['name_en'], data.get('name_ar') or None, int(data['min_count']) if data.get('min_count') else None,
                data.get('param_key') or None, bool(data.get('is_active'))))
    db.commit()


def staffing(db=None):
    db = db or get_db()
    return {(r['branch_id'], r['role_code']): r['headcount'] for r in _rows(db, "SELECT * FROM pr_branch_staffing")}


def set_staffing(branch_id, counts, db=None):
    db = db or get_db()
    for role, n in counts.items():
        if n in (None, ''):
            continue
        db.execute("""INSERT INTO pr_branch_staffing (branch_id, role_code, headcount, as_of) VALUES (%s,%s,%s,%s)
                      ON CONFLICT (branch_id, role_code) DO UPDATE SET headcount = EXCLUDED.headcount, as_of = EXCLUDED.as_of""",
                   (branch_id, role, max(0, int(n)), date.today()))
    db.commit()


# ------------------------------------------------------------------ facilities
FACILITY_FIELDS = ('lender_name', 'facility_type', 'currency', 'limit_amount', 'balance', 'interest_rate_pct',
                   'start_date', 'maturity_date', 'status', 'covenant_breach', 'last_confirmation_date',
                   'confirmation_balance', 'accrual_from', 'accrued_booked', 'booked_as_of', 'rescheduled_on',
                   'rescheduling_approval_ref', 'board_escalated_on', 'board_escalation_ref', 'note')
_F_NUM = {'limit_amount', 'balance', 'interest_rate_pct', 'confirmation_balance', 'accrued_booked'}
_F_DATE = {'start_date', 'maturity_date', 'last_confirmation_date', 'accrual_from', 'booked_as_of', 'rescheduled_on',
           'board_escalated_on'}


def facilities(db=None):
    db = db or get_db()
    return providers.get().facilities(db)


def _facility_values(data):
    out = []
    for k in FACILITY_FIELDS:
        v = data.get(k)
        if k in _F_NUM:
            v = _num(v)
        elif k in _F_DATE:
            v = _date(v)
        elif k == 'covenant_breach':
            v = str(v).lower() in ('1', 'true', 'yes', 'on')
        elif k == 'status':
            v = v if v in ('performing', 'default', 'rescheduled', 'closed') else 'performing'
        elif k == 'facility_type':
            v = v if v in ('loan', 'overdraft', 'bond', 'securitisation', 'related_party', 'other') else 'loan'
        elif k == 'currency':
            v = (v or 'EGP').upper()[:3]
        else:
            v = (v or '').strip() or None
        out.append(v)
    return out


def save_facility(data, user_id, source='manual', db=None):
    db = db or get_db()
    ref = (data.get('reference') or '').strip()
    if not ref or not (data.get('lender_name') or '').strip():
        raise PrudentialError(N_('reference and lender are required'))
    vals = _facility_values(data)
    cols = ', '.join(FACILITY_FIELDS)
    fid = db.execute(f"""INSERT INTO pr_facilities (reference, {cols}, source, updated_by, updated_at)
                         VALUES (%s, {', '.join(['%s'] * len(FACILITY_FIELDS))}, %s, %s, %s)
                         ON CONFLICT (reference) DO UPDATE SET {', '.join(f'{k} = EXCLUDED.{k}' for k in FACILITY_FIELDS)},
                         source = EXCLUDED.source, updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at
                         RETURNING id""", (ref, *vals, source, user_id, datetime.now())).fetchone()['id']
    db.commit()
    return fid


FACILITY_CSV = ['reference', *[f for f in FACILITY_FIELDS if f != 'note']]


def import_facilities(text, user_id, db=None):
    ok, errors = 0, []
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            save_facility(row, user_id, source='import', db=db)
            ok += 1
        except PrudentialError as e:
            errors.append(f'line {i}: {e}')
    return ok, errors


def facility_review(db=None, today=None):
    db = db or get_db()
    max_age = param('finance.balance_confirmation_max_age_days')
    tol = param('finance.accrual_tolerance_pct', default=0)
    out = []
    for f in facilities(db):
        out.append({'f': f, 'confirmation': logic.confirmation_issue(f, today, max_age),
                    'accrual': logic.accrual_gap(f, tol), 'status_issues': logic.facility_status_issues(f)})
    return out


# ------------------------------------------------------------------ related parties
def related_parties(db=None):
    db = db or get_db()
    return _rows(db, """SELECT p.*, (SELECT count(*) FROM pr_rp_items i WHERE i.related_party_id = p.id) AS items
                        FROM pr_related_parties p ORDER BY p.is_active DESC, p.name""")


def save_related_party(data, user_id, db=None):
    db = db or get_db()
    if not (data.get('name') or '').strip():
        raise PrudentialError(N_('name is required'))
    rel = data.get('relation') if data.get('relation') in (
        'shareholder', 'exiting_shareholder', 'director', 'affiliate', 'key_person', 'other') else 'other'
    rid = db.execute("""INSERT INTO pr_related_parties (name, relation, ownership_pct, exited_on, created_by)
                        VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                     (data['name'].strip(), rel, _num(data.get('ownership_pct')), _date(data.get('exited_on')),
                      user_id)).fetchone()['id']
    db.commit()
    return rid


def add_rp_item(party_id, data, user_id, db=None):
    db = db or get_db()
    if data.get('item_type') not in ('capital_contribution', 'loan_from', 'loan_to', 'current_account', 'dues', 'other'):
        raise PrudentialError(N_('choose an item type'))
    amount, d = _num(data.get('amount')), _date(data.get('item_date'))
    if amount is None or not d:
        raise PrudentialError(N_('amount and date are required'))
    cls = data.get('classification') if data.get('classification') in ('liability', 'equity', 'receivable', 'other') else None
    rid = db.execute("""INSERT INTO pr_rp_items (related_party_id, item_type, amount, item_date, payer_name, classification,
                        explanation, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (party_id, data['item_type'], amount, d, (data.get('payer_name') or '').strip() or None, cls,
                      (data.get('explanation') or '').strip() or None, user_id)).fetchone()['id']
    db.commit()
    return rid


def rp_review(db=None, party_id=None):
    db = db or get_db()
    out = []
    for it in providers.get().related_party_items(db):
        if party_id and it['related_party_id'] != party_id:
            continue
        party = {'name': it['party_name'], 'relation': it['relation']}
        docs = has_files('pr_rp_item', it['id'], db)
        out.append({'item': it, 'has_docs': docs, 'issues': logic.rp_item_issues(it, party, docs)})
    return out


# ------------------------------------------------------------------ studies
def studies(db=None, study_type=None):
    db = db or get_db()
    if study_type:
        return _rows(db, "SELECT * FROM pr_studies WHERE study_type = %s ORDER BY COALESCE(approved_on, created_at::date) DESC",
                     (study_type,))
    return _rows(db, "SELECT * FROM pr_studies ORDER BY study_type, COALESCE(approved_on, created_at::date) DESC")


STUDY_REFRESH_PARAMS = {'ecl': 'finance.ecl_refresh_months'}


def save_study(data, user_id, db=None):
    db = db or get_db()
    st = (data.get('study_type') or '').strip().lower()
    if not st or not (data.get('title') or '').strip():
        raise PrudentialError(N_('type and title are required'))
    rid = db.execute("""INSERT INTO pr_studies (study_type, title, period_end, prepared_by, note, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (st, data['title'].strip(), _date(data.get('period_end')), data.get('prepared_by') or None,
                      data.get('note') or None, user_id)).fetchone()['id']
    db.commit()
    return rid


def approve_study(study_id, approved_on, body, refresh_months=None, db=None):
    db = db or get_db()
    s = db.execute("SELECT * FROM pr_studies WHERE id = %s", (study_id,)).fetchone()
    if not s:
        raise PrudentialError(N_('study not found'))
    approved_on = _date(approved_on)
    if not approved_on or not (body or '').strip():
        raise PrudentialError(N_('approval date and approving body are required'))
    if not has_files('pr_study', study_id, db):
        raise PrudentialError(N_('attach the approved study (or certificate) first'))
    months = refresh_months if refresh_months is not None else param(STUDY_REFRESH_PARAMS.get(s['study_type']))
    from dateutil.relativedelta import relativedelta
    nxt = approved_on + relativedelta(months=int(months)) if months else None
    db.execute("UPDATE pr_studies SET status = 'superseded' WHERE study_type = %s AND status = 'approved' AND id <> %s",
               (s['study_type'], study_id))
    db.execute("""UPDATE pr_studies SET status = 'approved', approved_on = %s, approved_by_body = %s, next_refresh_date = %s
                  WHERE id = %s""", (approved_on, body.strip(), nxt, study_id))
    db.commit()


# ------------------------------------------------------------------ installers for content packs
def install_function_type(code, name_en, name_ar=None, *, is_required=True, notify_regulator=True,
                          needs_no_objection=False, sort_order=100, pack_code=None, db=None):
    """Add a key-function type if it does not exist yet (never overwrites UI edits)."""
    db = db or get_db()
    db.execute("""INSERT INTO pr_key_function_types (code, name_en, name_ar, is_required, notify_regulator,
                  needs_no_objection, sort_order, pack_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT (code) DO NOTHING""",
               (code, name_en, name_ar, is_required, notify_regulator, needs_no_objection, sort_order, pack_code))


def install_branch_role(code, name_en, name_ar=None, *, min_count=None, param_key=None, pack_code=None, db=None):
    """Add a required branch role if it does not exist yet (never overwrites UI edits)."""
    db = db or get_db()
    db.execute("""INSERT INTO pr_branch_roles (code, name_en, name_ar, min_count, param_key, pack_code)
                  VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (code) DO NOTHING""",
               (code, name_en, name_ar, min_count, param_key, pack_code))
