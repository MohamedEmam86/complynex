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
Freeze log (F6): for every listed-person hit that requires a freeze, when it
was discovered, when the funds / accounts were frozen and when it was reported
(to the FIU / supervisor), with the time elapsed between the steps.

Targets ("freeze within N hours of discovery", "report within N hours of the
freeze") are regulator values, so they are DATA: the regcontrols parameters
aml.freeze_target_hours / aml.freeze_report_target_hours for the company's
licence type, else the settings aml_freeze_target_hours /
aml_freeze_report_target_hours. With neither, only the elapsed time is shown.
"""
import os
from datetime import datetime

from database.db import get_db

STATUSES = [  # code, EN, AR
    ('DISCOVERED', 'Discovered — not frozen yet', 'تم الاكتشاف — لم يتم التجميد بعد'),
    ('FROZEN', 'Frozen — not reported yet', 'تم التجميد — لم يتم الإخطار بعد'),
    ('REPORTED', 'Frozen and reported', 'تم التجميد والإخطار'),
    ('RELEASED', 'Released', 'تم رفع التجميد'),
]
STATUS_CODES = tuple(c for c, _e, _a in STATUSES)
TARGET_PARAMS = {'freeze': ('aml.freeze_target_hours', 'aml_freeze_target_hours'),
                 'report': ('aml.freeze_report_target_hours', 'aml_freeze_report_target_hours')}


class FreezeError(ValueError):
    pass


def parse_dt(v):
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    s = str(v or '').strip().replace('T', ' ')
    for part in (s[:19], s[:16], s[:10]):
        try:
            return datetime.fromisoformat(part) if part else None
        except ValueError:
            continue
    return None


def hours_between(a, b):
    a, b = parse_dt(a), parse_dt(b)
    if not a or not b:
        return None
    return round((b - a).total_seconds() / 3600.0, 2)


def duration_text(hours):
    if hours is None:
        return '—'
    if hours < 0:
        return '—'
    m = int(round(hours * 60))
    d, rem = divmod(m, 24 * 60)
    h, mi = divmod(rem, 60)
    return (f'{d}d ' if d else '') + f'{h}h {mi:02d}m'


def status_of(entry):
    if entry.get('released_at'):
        return 'RELEASED'
    if entry.get('reported_at'):
        return 'REPORTED'
    if entry.get('frozen_at'):
        return 'FROZEN'
    return 'DISCOVERED'


def timeline(entry, targets, now=None):
    """Elapsed times and whether each step met its target.
    targets: {'freeze': hours|None, 'report': hours|None}."""
    now = now or datetime.now()
    disc, frz, rep = parse_dt(entry.get('discovered_at')), parse_dt(entry.get('frozen_at')), parse_dt(entry.get('reported_at'))
    to_freeze = hours_between(disc, frz or now)
    to_report = hours_between(frz, rep or now) if frz else None

    def check(elapsed, target, done):
        if target in (None, '') or elapsed is None:
            return None
        return {'met': elapsed <= float(target), 'done': done}

    return {
        'to_freeze_h': to_freeze, 'freeze_done': bool(frz), 'freeze_check': check(to_freeze, targets.get('freeze'), bool(frz)),
        'to_report_h': to_report, 'report_done': bool(rep), 'report_check': check(to_report, targets.get('report'), bool(rep)),
        'discovery_to_report_h': hours_between(disc, rep) if rep else None,
    }


def validate_step(entry, step, when):
    """Order of the steps: discovered <= frozen <= reported; nothing in the future."""
    w = parse_dt(when)
    if not w:
        raise FreezeError('Enter the date and time.')
    if w > datetime.now():
        raise FreezeError('The time cannot be in the future.')
    disc = parse_dt(entry.get('discovered_at'))
    if step in ('frozen', 'reported') and disc and w < disc:
        raise FreezeError('This step cannot be before the discovery time.')
    if step == 'reported':
        frz = parse_dt(entry.get('frozen_at'))
        if not frz:
            raise FreezeError('Record the freeze before the report.')
        if w < frz:
            raise FreezeError('The report cannot be before the freeze.')
    if step == 'released':
        frz = parse_dt(entry.get('frozen_at'))
        if not frz or w < frz:
            raise FreezeError('A release must come after the freeze.')
    return w


# ----------------------------------------------------------------------------- database side

def targets(db=None):
    out = {}
    for key, (param, setting) in TARGET_PARAMS.items():
        v = None
        try:
            from regcontrols.api import get_param
            from regcontrols.engine import company_licence_type
            v = get_param(param, company_licence_type(), default=None)
        except Exception:
            try:
                (db or get_db()).rollback()
            except Exception:
                pass
        if v in (None, ''):
            try:
                from models.settings import Settings
                v = Settings.get(setting)
            except Exception:
                v = None
        try:
            out[key] = float(v) if v not in (None, '') and float(v) > 0 else None
        except (TypeError, ValueError):
            out[key] = None
    return out


def _audit(actor_id, entry_id, details):
    try:
        from flask import request
        ip = request.remote_addr
    except Exception:
        ip = None
    from models.audit import AuditLog
    AuditLog.log(actor_id, 'Freeze log', 'AML', entry_id, details, ip)


def new_reference(when=None):
    when = when or datetime.now()
    return f"FRZ-{when.strftime('%Y%m')}-{os.urandom(2).hex().upper()}"


def get(entry_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM aml_freeze_log WHERE id = %s", (entry_id,)).fetchone()
    if not r:
        raise FreezeError('Freeze log entry not found.')
    return dict(r)


def from_hit(queue_id, db=None):
    """Prefill (subject, list, customer, discovery time) from a screening queue item."""
    db = db or get_db()
    q = db.execute("""SELECT q.id, q.match_name, q.entity_name, q.list_source, q.created_at, q.source_module,
                             q.source_record_id, h.screening_date
                        FROM screening_queue q LEFT JOIN screening_history h ON h.id = q.screening_history_id
                       WHERE q.id = %s""", (queue_id,)).fetchone()
    if not q:
        return None
    q = dict(q)
    return {'screening_queue_id': q['id'], 'subject_name': q.get('entity_name') or q.get('match_name'),
            'list_name': q.get('list_source'), 'listed_name': q.get('match_name'),
            'customer_id': q['source_record_id'] if q.get('source_module') == 'Customer KYC' else None,
            'discovered_at': parse_dt(q.get('screening_date')) or parse_dt(q.get('created_at'))}


def create(data, user_id, db=None):
    db = db or get_db()
    name = (data.get('subject_name') or '').strip()
    if len(name) < 2:
        raise FreezeError('Enter the name of the listed person or entity.')
    disc = parse_dt(data.get('discovered_at'))
    if not disc or disc > datetime.now():
        raise FreezeError('Enter when the match was discovered (not in the future).')
    cid = data.get('customer_id')
    cid = int(cid) if str(cid or '').isdigit() else None
    if cid and not db.execute("SELECT 1 FROM customers WHERE id = %s", (cid,)).fetchone():
        raise FreezeError('Customer not found.')
    qid = data.get('screening_queue_id')
    qid = int(qid) if str(qid or '').isdigit() else None
    sid = data.get('sar_id')
    sid = int(sid) if str(sid or '').isdigit() else None
    ref = new_reference()
    eid = db.execute("""INSERT INTO aml_freeze_log (reference, customer_id, subject_name, list_name, listed_name,
                        screening_queue_id, sar_id, discovered_at, status, notes, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'DISCOVERED',%s,%s) RETURNING id""",
                     (ref, cid, name[:300], (data.get('list_name') or '').strip()[:200] or None,
                      (data.get('listed_name') or '').strip()[:300] or None, qid, sid, disc,
                      (data.get('notes') or '').strip() or None, user_id)).fetchone()['id']
    db.commit()
    _audit(user_id, eid, f'{ref} opened: {name} ({data.get("list_name") or "-"}), discovered {disc}')
    return eid, ref


def record_freeze(entry_id, when, scope, amount, user_id, db=None):
    db = db or get_db()
    e = get(entry_id, db)
    if e.get('frozen_at'):
        raise FreezeError('The freeze is already recorded.')
    w = validate_step(e, 'frozen', when)
    scope = (scope or '').strip()
    if len(scope) < 5:
        raise FreezeError('Describe what was frozen (accounts, wallets, funds).')
    try:
        amt = float(amount) if str(amount or '').strip() else None
        if amt is not None and amt < 0:
            raise ValueError
    except ValueError:
        raise FreezeError('The amount must be a positive number.')
    db.execute("""UPDATE aml_freeze_log SET frozen_at = %s, frozen_by = %s, freeze_scope = %s, amount_frozen = %s,
                  status = 'FROZEN', updated_at = now() WHERE id = %s""", (w, user_id, scope, amt, entry_id))
    db.commit()
    _audit(user_id, entry_id, f'{e["reference"]}: frozen at {w} ({scope})')


def record_report(entry_id, when, reported_to, reference, user_id, db=None):
    db = db or get_db()
    e = get(entry_id, db)
    if e.get('reported_at'):
        raise FreezeError('The report is already recorded.')
    w = validate_step(e, 'reported', when)
    to = (reported_to or '').strip()
    if len(to) < 2:
        raise FreezeError('Name the authority the freeze was reported to.')
    db.execute("""UPDATE aml_freeze_log SET reported_at = %s, reported_by = %s, reported_to = %s, report_reference = %s,
                  status = 'REPORTED', updated_at = now() WHERE id = %s""",
               (w, user_id, to[:200], (reference or '').strip()[:120] or None, entry_id))
    db.commit()
    _audit(user_id, entry_id, f'{e["reference"]}: reported to {to} at {w}')


def record_release(entry_id, when, reason, user_id, is_mlro, db=None):
    db = db or get_db()
    if not is_mlro:
        raise FreezeError('Only the MLRO records the release of a freeze.')
    e = get(entry_id, db)
    if e.get('released_at'):
        raise FreezeError('The release is already recorded.')
    w = validate_step(e, 'released', when)
    reason = (reason or '').strip()
    if len(reason) < 20:
        raise FreezeError('Give the legal basis of the release (at least 20 characters).')
    db.execute("""UPDATE aml_freeze_log SET released_at = %s, release_reason = %s, status = 'RELEASED',
                  updated_at = now() WHERE id = %s""", (w, reason, entry_id))
    db.commit()
    _audit(user_id, entry_id, f'{e["reference"]}: released at {w}: {reason}')


def link_case(entry_id, sar_id, user_id, db=None):
    db = db or get_db()
    e = get(entry_id, db)
    if not db.execute("SELECT 1 FROM suspicious_activities WHERE id = %s", (sar_id,)).fetchone():
        raise FreezeError('STR case not found.')
    db.execute("UPDATE aml_freeze_log SET sar_id = %s, updated_at = now() WHERE id = %s", (sar_id, entry_id))
    db.commit()
    _audit(user_id, entry_id, f'{e["reference"]}: linked to STR case #{sar_id}')


def entries(db=None, status=None, customer_id=None, sar_id=None):
    db = db or get_db()
    where, args = [], []
    if status in STATUS_CODES:
        where.append('f.status = %s')
        args.append(status)
    if customer_id:
        where.append('f.customer_id = %s')
        args.append(customer_id)
    if sar_id:
        where.append('f.sar_id = %s')
        args.append(sar_id)
    rows = db.execute(f"""SELECT f.*, c.customer_reference, s.sar_reference
                            FROM aml_freeze_log f LEFT JOIN customers c ON c.id = f.customer_id
                            LEFT JOIN suspicious_activities s ON s.id = f.sar_id
                           {('WHERE ' + ' AND '.join(where)) if where else ''}
                           ORDER BY (f.status = 'DISCOVERED') DESC, (f.status = 'FROZEN') DESC, f.discovered_at DESC
                           LIMIT 500""", tuple(args)).fetchall()
    return [dict(r) for r in rows]
