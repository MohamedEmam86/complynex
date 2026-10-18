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
Regulatory parameter registry.

Every regulatory number used by a check (caps, thresholds, SLAs, ceilings)
is read from rc_parameters through get_param(). Nothing else in the code base
may hard-code such a number.

Changes go through maker-checker: propose_change() records a pending row in
rc_parameter_changes, and only approve_change() by a different user applies
it to rc_parameters. Versions are dated (effective_from / effective_to), so a
check run "as of" a past date sees the value that applied then.
"""

import re
from datetime import datetime, timedelta

from database.db import get_db

from . import logic
from .logic import ParameterNotFound, ParameterNotSet  # noqa: F401 — re-exported for callers

_MISSING = object()

VALUE_TYPES = ('number', 'integer', 'amount', 'percent', 'boolean', 'text', 'json', 'date')
CHANGE_TYPES = ('create', 'update', 'new_version', 'retire', 'review')


class ChangeError(ValueError):
    """A proposed or approved change cannot be applied (shown to the user)."""


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


# ------------------------------------------------------------------ lookup
def get_versions(key, db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM rc_parameters WHERE param_key = %s "
                     "ORDER BY licence_type, effective_from", (key,))


def get_param_record(key, licence_type='all', as_of=None, db=None):
    """The full version row that applies (value, unit, legal reference,
    needs_review …), or None."""
    return logic.select_param(get_versions(key, db), licence_type, as_of)


def get_param(key, licence_type='all', as_of=None, default=_MISSING, db=None):
    """Typed value of a regulatory parameter.

    A licence-specific version wins over the generic 'all' one. Raises
    ParameterNotFound when no version covers the date, ParameterNotSet when
    the version has no value yet — unless `default` is given.
    """
    rec = get_param_record(key, licence_type, as_of, db)
    if rec is None:
        if default is not _MISSING:
            return default
        raise ParameterNotFound(f'Regulatory parameter "{key}" ({licence_type or "all"}) is not defined '
                                f'for this date — add it under Regulatory Compliance > Parameters.')
    try:
        return logic.coerce_value(rec['value_text'], rec['value_type'])
    except ParameterNotSet:
        if default is not _MISSING:
            return default
        raise ParameterNotSet(f'Regulatory parameter "{key}" ({rec["licence_type"]}) has no value yet — '
                              f'Compliance must set and approve it.')


# ------------------------------------------------------------------ listing
def list_current(search=None, needs_review=None, licence_type=None, db=None):
    """One row per (key, licence) with the version in force today, plus the
    number of versions and of pending changes — for the admin list."""
    db = db or get_db()
    rows = _rows(db, "SELECT * FROM rc_parameters ORDER BY param_key, licence_type, effective_from")
    pending = {(r['param_key'], r['licence_type']): r['n'] for r in _rows(
        db, "SELECT param_key, licence_type, count(*) AS n FROM rc_parameter_changes "
            "WHERE status = 'pending' GROUP BY param_key, licence_type")}
    groups = {}
    for r in rows:
        groups.setdefault((r['param_key'], r['licence_type']), []).append(r)
    out = []
    for (key, lic), versions in groups.items():
        current = logic.select_param(versions, lic) or versions[-1]
        item = dict(current)
        item['versions'] = len(versions)
        item['in_force'] = logic.select_param(versions, lic) is not None
        item['pending_changes'] = pending.get((key, lic), 0)
        if search and search.lower() not in (key + ' ' + (item.get('description_en') or '') + ' ' +
                                             (item.get('description_ar') or '')).lower():
            continue
        if needs_review is not None and bool(item['needs_review']) != needs_review:
            continue
        if licence_type and lic != licence_type:
            continue
        out.append(item)
    return out


def get_parameter(param_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM rc_parameters WHERE id = %s", (param_id,)).fetchone()
    return dict(r) if r else None


def history(key, licence_type=None, db=None):
    db = db or get_db()
    sql = ("SELECT c.*, ru.first_name || ' ' || ru.last_name AS requested_by_name, "
           "       du.first_name || ' ' || du.last_name AS decided_by_name "
           "FROM rc_parameter_changes c "
           "LEFT JOIN users ru ON ru.id = c.requested_by LEFT JOIN users du ON du.id = c.decided_by "
           "WHERE c.param_key = %s")
    args = [key]
    if licence_type:
        sql += " AND c.licence_type = %s"
        args.append(licence_type)
    return _rows(db, sql + " ORDER BY c.requested_at DESC, c.id DESC", tuple(args))


def pending_changes(db=None):
    db = db or get_db()
    return _rows(db, "SELECT c.*, u.first_name || ' ' || u.last_name AS requested_by_name "
                     "FROM rc_parameter_changes c LEFT JOIN users u ON u.id = c.requested_by "
                     "WHERE c.status = 'pending' ORDER BY c.requested_at")


# ------------------------------------------------------------------ changes
def propose_change(*, key, licence_type, change_type, reason, requested_by, new_value=None,
                   value_type=None, unit=None, effective_from=None, effective_to=None,
                   legal_reference=None, description_en=None, description_ar=None,
                   needs_review=None, review_note=None, parameter_id=None, db=None):
    """Record a pending change. Returns the rc_parameter_changes id."""
    db = db or get_db()
    key = (key or '').strip()
    licence_type = licence_type or 'all'
    if change_type not in CHANGE_TYPES:
        raise ChangeError(f'unknown change type {change_type!r}')
    if not key:
        raise ChangeError('parameter key is required')
    if not re.fullmatch(r'[a-z0-9_.]+', key):
        raise ChangeError('invalid parameter key')
    if not (reason or '').strip():
        raise ChangeError('a reason is required for every parameter change')
    current = get_parameter(parameter_id, db) if parameter_id else None
    if change_type in ('update', 'retire', 'review') and not current:
        raise ChangeError('this change needs an existing parameter version')
    if current:
        key, licence_type = current['param_key'], current['licence_type']
    vt = value_type or (current or {}).get('value_type') or 'number'
    if vt not in VALUE_TYPES:
        raise ChangeError(f'unknown value type {vt!r}')
    if change_type in ('create', 'update', 'new_version'):
        err = logic.validate_value(new_value, vt)
        if err:
            raise ChangeError(f'invalid value: {err}')
    if change_type == 'update':
        effective_from = current['effective_from']
    if change_type in ('create', 'new_version') and not effective_from:
        raise ChangeError('effective from date is required')
    if effective_from and effective_to and str(effective_to) < str(effective_from):
        raise ChangeError('effective to must not be before effective from')
    old_value = current['value_text'] if current else None
    cur = db.execute("""
        INSERT INTO rc_parameter_changes
            (parameter_id, param_key, licence_type, change_type, old_value, new_value, value_type, unit,
             effective_from, effective_to, legal_reference, description_en, description_ar,
             needs_review, review_note, reason, requested_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (parameter_id, key, licence_type, change_type, old_value,
          None if new_value is None or str(new_value).strip() == '' else str(new_value).strip(),
          vt, unit, effective_from, effective_to, legal_reference, description_en, description_ar,
          needs_review, review_note, reason.strip(), requested_by))
    change_id = cur.fetchone()['id']
    db.commit()
    return change_id


def approve_change(change_id, approver_id, comment=None, db=None):
    """Apply a pending change (four-eyes: the approver must not be the requester).
    Returns the rc_parameters id that now holds the change."""
    db = db or get_db()
    ch = db.execute("SELECT * FROM rc_parameter_changes WHERE id = %s FOR UPDATE", (change_id,)).fetchone()
    if not ch:
        raise ChangeError('change not found')
    ch = dict(ch)
    if ch['status'] != 'pending':
        raise ChangeError('this change has already been decided')
    if ch['requested_by'] and ch['requested_by'] == approver_id:
        raise ChangeError('a parameter change must be approved by a different user (four-eyes rule)')
    try:
        param_id = _apply(db, ch, approver_id)
        db.execute("""UPDATE rc_parameter_changes SET status = 'approved', decided_by = %s, decided_at = %s,
                      decision_comment = %s, applied_parameter_id = %s WHERE id = %s""",
                   (approver_id, datetime.now(), comment, param_id, change_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return param_id


def reject_change(change_id, user_id, comment, db=None):
    db = db or get_db()
    if not (comment or '').strip():
        raise ChangeError('a comment is required when rejecting a change')
    n = db.execute("""UPDATE rc_parameter_changes SET status = 'rejected', decided_by = %s, decided_at = %s,
                      decision_comment = %s WHERE id = %s AND status = 'pending'""",
                   (user_id, datetime.now(), comment.strip(), change_id)).rowcount
    db.commit()
    if not n:
        raise ChangeError('change not found or already decided')


def _apply(db, ch, approver_id):
    now = datetime.now()
    if ch['change_type'] == 'retire':
        db.execute("UPDATE rc_parameters SET status = 'retired', approved_by = %s, approved_at = %s, "
                   "updated_at = %s WHERE id = %s", (approver_id, now, now, ch['parameter_id']))
        return ch['parameter_id']
    if ch['change_type'] == 'review':
        db.execute("UPDATE rc_parameters SET needs_review = %s, review_note = %s, approved_by = %s, "
                   "approved_at = %s, updated_at = %s WHERE id = %s",
                   (bool(ch['needs_review']), ch['review_note'], approver_id, now, now, ch['parameter_id']))
        return ch['parameter_id']

    versions = get_versions(ch['param_key'], db)
    mode, row_id, close_ids, next_start = logic.plan_version_change(
        versions, ch['licence_type'], ch['effective_from'])
    needs_review = bool(ch['needs_review']) if ch['needs_review'] is not None else False
    if mode == 'update':
        db.execute("""
            UPDATE rc_parameters SET value_text = %s, value_type = %s, unit = %s,
                   effective_to = COALESCE(%s, effective_to),
                   legal_reference = COALESCE(%s, legal_reference),
                   description_en = COALESCE(%s, description_en), description_ar = COALESCE(%s, description_ar),
                   needs_review = %s, review_note = %s, status = 'active',
                   approved_by = %s, approved_at = %s, updated_at = %s
            WHERE id = %s
        """, (ch['new_value'], ch['value_type'], ch['unit'], ch['effective_to'], ch['legal_reference'],
              ch['description_en'], ch['description_ar'], needs_review, ch['review_note'],
              approver_id, now, now, row_id))
        return row_id

    new_from = logic._as_date(ch['effective_from'])
    for vid in close_ids:
        db.execute("UPDATE rc_parameters SET effective_to = %s, updated_at = %s WHERE id = %s",
                   (new_from - timedelta(days=1), now, vid))
    effective_to = ch['effective_to'] or (next_start - timedelta(days=1) if next_start else None)
    prev = versions[-1] if versions else {}
    cur = db.execute("""
        INSERT INTO rc_parameters
            (param_key, licence_type, value_text, value_type, unit, effective_from, effective_to,
             legal_reference, description_en, description_ar, needs_review, review_note,
             created_by, approved_by, approved_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (ch['param_key'], ch['licence_type'], ch['new_value'], ch['value_type'],
          ch['unit'] or prev.get('unit'), new_from, effective_to,
          ch['legal_reference'] or prev.get('legal_reference'),
          ch['description_en'] or prev.get('description_en'),
          ch['description_ar'] or prev.get('description_ar'),
          needs_review, ch['review_note'], ch['requested_by'], approver_id, now))
    return cur.fetchone()['id']
