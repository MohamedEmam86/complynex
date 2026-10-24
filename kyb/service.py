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

"""KYB data access: entity fields, beneficial owners, signatories, screening."""

import logging
from datetime import date, datetime

from database.db import get_db
from . import logic
from .logic import M

log = logging.getLogger(__name__)


class KybError(Exception):
    """Carries a list of untranslated messages ((msgid, params) or str)."""

    def __init__(self, messages):
        self.messages = messages if isinstance(messages, list) else [messages]
        super().__init__(str(self.messages))


# Each register maps the canonical KYB entity fields onto its own columns.
SUBJECTS = {
    'merchant': {
        'table': 'merchants',
        'name': lambda r: r.get('merchant_name') or f"#{r['id']}",
        'fields': {'cr_number': 'cr_number', 'tax_card_number': 'tax_id', 'legal_form': 'business_type',
                   'incorporation_date': 'incorporation_date', 'incorporation_country': 'incorporation_country',
                   'licence_number': 'licence_number', 'licence_regulator': 'licence_regulator'},
        # older code reads one UBO from these columns: keep them on the main owner
        'main_owner_columns': {'ubo_name': 'full_name', 'ubo_nationality': 'nationality', 'ubo_id_type': 'id_type',
                               'ubo_id_number': 'id_number', 'ubo_dob': 'date_of_birth',
                               'ownership_percentage': 'ownership_pct'},
    },
    'aml_customer': {
        'table': 'customers',
        'name': lambda r: r.get('company_name') or r.get('full_name') or f"#{r['id']}",
        'fields': {'cr_number': 'registration_number', 'tax_card_number': 'tax_card_number',
                   'legal_form': 'legal_form', 'incorporation_date': 'incorporation_date',
                   'incorporation_country': 'registration_country', 'licence_number': 'licence_number',
                   'licence_regulator': 'licence_regulator'},
        'main_owner_columns': {},
    },
}

SCREEN_MODULE = {'ubo': 'KYB Beneficial Owner', 'signatory': 'KYB Signatory'}
TABLE = {'ubo': 'kyc_beneficial_owners', 'signatory': 'kyb_signatories'}


def register_subject(code, table, name, fields, main_owner_columns=None):
    """Let another module or a pack run KYB on its own register of entities."""
    SUBJECTS[code] = {'table': table, 'name': name, 'fields': fields, 'main_owner_columns': main_owner_columns or {}}


def _cfg(subject):
    if subject not in SUBJECTS:
        raise KybError(M('Unknown register.'))
    return SUBJECTS[subject]


def record(subject, subject_id, db=None):
    db = db or get_db()
    r = db.execute(f"SELECT * FROM {_cfg(subject)['table']} WHERE id = %s", (subject_id,)).fetchone()
    return dict(r) if r else None


def entity(subject, subject_id, db=None):
    """Canonical KYB entity fields of one record (None when the record is missing)."""
    r = record(subject, subject_id, db)
    if not r:
        return None
    cfg = _cfg(subject)
    out = {k: r.get(col) for k, col in cfg['fields'].items()}
    out['id'] = r['id']
    out['name'] = cfg['name'](r)
    return out


def _clean(v, n=255):
    v = (v or '').strip() if isinstance(v, str) else v
    return (v[:n] if isinstance(v, str) else v) or None


def _date(v, field_label):
    v = (v or '').strip() if isinstance(v, str) else v
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        raise KybError(M('%(field)s is not a valid date.', field=field_label))
    if d > date.today():
        raise KybError(M('%(field)s cannot be in the future.', field=field_label))
    return d


def save_entity(subject, subject_id, form, user_id, db=None):
    db = db or get_db()
    cfg = _cfg(subject)
    vals = {}
    for k in cfg['fields']:
        if k not in form:
            continue
        v = _clean(form.get(k))
        if k == 'legal_form' and v and v not in logic.LEGAL_FORMS:
            raise KybError(M('Choose a legal form from the list.'))
        if k == 'incorporation_date' and v:
            v = _date(v, 'Incorporation date').isoformat()
        vals[cfg['fields'][k]] = v
    if not vals:
        return
    sets = ', '.join(f"{c} = %s" for c in vals)
    extra = ', updated_at = CURRENT_TIMESTAMP, updated_by = %s'
    db.execute(f"UPDATE {cfg['table']} SET {sets}{extra} WHERE id = %s", (*vals.values(), user_id, subject_id))
    db.commit()


# ----------------------------------------------------------------------------- people

def people(kind, subject, subject_id, db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute(
        f"SELECT * FROM {TABLE[kind]} WHERE subject = %s AND subject_id = %s ORDER BY id",
        (subject, subject_id)).fetchall()]


def _person_data(kind, form):
    d = {
        'full_name': _clean(form.get('full_name')),
        'nationality': _clean(form.get('nationality'), 100),
        'id_type': _clean(form.get('id_type'), 30),
        'id_number': _clean(form.get('id_number'), 100),
        'date_of_birth': _date(form.get('date_of_birth'), 'Date of birth'),
    }
    if not d['full_name']:
        raise KybError(M('Name is required.'))
    if d['id_type'] and d['id_type'] not in logic.ID_TYPES:
        raise KybError(M('Choose an ID type from the list.'))
    if kind == 'ubo':
        d['ownership_pct'] = form.get('ownership_pct')
        try:
            p = logic.pct(d['ownership_pct'])
        except ValueError:
            raise KybError(M('Ownership of %(name)s is not a number.', name=d['full_name']))
        d['ownership_pct'] = p
        ct = form.get('control_type') or 'ownership'
        if ct not in logic.CONTROL_TYPES:
            raise KybError(M('Invalid control type for %(name)s.', name=d['full_name']))
        d['control_type'] = ct
        d['is_pep'] = form.get('is_pep') in ('on', '1', 'true', True)
    else:
        d['position'] = _clean(form.get('position'), 150)
        sa = form.get('signing_authority') or 'sole'
        if sa not in logic.SIGNING_AUTHORITIES:
            raise KybError(M('Choose sole or joint signing authority.'))
        d['signing_authority'] = sa
    return d


def save_person(kind, subject, subject_id, form, user_id, person_id=None, screen=True, db=None):
    """Add or update one owner / signatory, validate the whole owner set, then
    screen the person when their identity data is new or changed.
    Returns (person_id, warnings)."""
    db = db or get_db()
    if not record(subject, subject_id, db):
        raise KybError(M('Record not found.'))
    d = _person_data(kind, form)
    warnings = []
    if kind == 'ubo':
        current = [u for u in people('ubo', subject, subject_id, db) if u['id'] != person_id]
        errors, warnings = logic.validate_ubos(current + [d])
        if errors:
            raise KybError(errors)
    cols = list(d.keys())
    if person_id:
        row = db.execute(f"SELECT id FROM {TABLE[kind]} WHERE id = %s AND subject = %s AND subject_id = %s",
                         (person_id, subject, subject_id)).fetchone()
        if not row:
            raise KybError(M('Record not found.'))
        sets = ', '.join(f"{c} = %s" for c in cols)
        db.execute(f"UPDATE {TABLE[kind]} SET {sets}, updated_by = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                   (*d.values(), user_id, person_id))
    else:
        ph = ', '.join(['%s'] * len(cols))
        person_id = db.execute(
            f"INSERT INTO {TABLE[kind]} (subject, subject_id, {', '.join(cols)}, created_by) "
            f"VALUES (%s, %s, {ph}, %s) RETURNING id", (subject, subject_id, *d.values(), user_id)).fetchone()['id']
    db.commit()
    if kind == 'ubo':
        sync_main_owner(subject, subject_id, db)
    if screen:
        row = dict(db.execute(f"SELECT * FROM {TABLE[kind]} WHERE id = %s", (person_id,)).fetchone())
        if row.get('screened_key') != logic.screen_key(row) or not row.get('screening_history_id'):
            screen_person(kind, row, user_id, db)
    return person_id, warnings


def delete_person(kind, subject, subject_id, person_id, db=None):
    """Remove one owner / signatory. Returns the removed row (for the audit log) or None."""
    db = db or get_db()
    row = db.execute(f"SELECT * FROM {TABLE[kind]} WHERE id = %s AND subject = %s AND subject_id = %s",
                     (person_id, subject, subject_id)).fetchone()
    if not row:
        return None
    db.execute(f"DELETE FROM {TABLE[kind]} WHERE id = %s", (person_id,))
    db.commit()
    if kind == 'ubo':
        sync_main_owner(subject, subject_id, db)
    return dict(row)


def sync_main_owner(subject, subject_id, db=None):
    db = db or get_db()
    cols = _cfg(subject)['main_owner_columns']
    if not cols:
        return
    main = logic.main_owner(people('ubo', subject, subject_id, db))
    if not main:
        return     # keep what the record holds; nothing is cleared
    vals = []
    for col, key in cols.items():
        v = main.get(key)
        if isinstance(v, date):
            v = v.isoformat()
        elif v is not None and key == 'ownership_pct':
            v = float(v)
        vals.append(v)
    db.execute(f"UPDATE {_cfg(subject)['table']} SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
               (*vals, subject_id))
    db.commit()


def screen_person(kind, row, user_id, db=None):
    """Screen one person through the public screening service and link the result."""
    db = db or get_db()
    try:
        from screening.customer_screening_service import screen_and_save
        res = screen_and_save(
            name=row['full_name'], entity_type='INDIVIDUAL',
            dob=row['date_of_birth'].isoformat() if isinstance(row.get('date_of_birth'), date) else row.get('date_of_birth'),
            nationality=row.get('nationality'), national_id=row.get('id_number'),
            source_module=SCREEN_MODULE[kind], source_record_id=row['id'],
            screening_type='KYB', user_id=user_id, results_screening_type='KYB')
        db.execute(f"""UPDATE {TABLE[kind]} SET screening_history_id = %s, screening_error = NULL,
                       screened_key = %s, screened_at = CURRENT_TIMESTAMP WHERE id = %s""",
                   (res['history_id'], logic.screen_key(row), row['id']))
        db.commit()
        return res
    except Exception as e:     # engine unavailable: record it, the person stays a blocker
        log.exception('KYB screening failed for %s %s', kind, row.get('id'))
        db.rollback()
        db.execute(f"UPDATE {TABLE[kind]} SET screening_history_id = NULL, screening_error = %s, "
                   f"screened_at = CURRENT_TIMESTAMP WHERE id = %s", (str(e)[:300], row['id']))
        db.commit()
        return None


def screen_all(subject, subject_id, user_id, only_needed=True, db=None):
    """Screen every owner and signatory that has not been screened on its current data."""
    db = db or get_db()
    n = 0
    for kind in ('ubo', 'signatory'):
        for p in people(kind, subject, subject_id, db):
            if only_needed and p.get('screening_history_id') and p.get('screened_key') == logic.screen_key(p):
                continue
            screen_person(kind, p, user_id, db)
            n += 1
    return n


def with_states(subject, subject_id, db=None):
    """(ubos, signatories, states) with each person's current screening state."""
    db = db or get_db()
    ubos = people('ubo', subject, subject_id, db)
    sigs = people('signatory', subject, subject_id, db)
    hids = [p['screening_history_id'] for p in ubos + sigs if p.get('screening_history_id')]
    hist, queue = {}, {}
    if hids:
        for h in db.execute("SELECT id, screening_result, screening_date, highest_score FROM screening_history "
                            "WHERE id = ANY(%s)", (hids,)).fetchall():
            hist[h['id']] = dict(h)
        for q in db.execute("SELECT id, screening_history_id, status, resolution, match_name, list_source "
                            "FROM screening_queue WHERE screening_history_id = ANY(%s)", (hids,)).fetchall():
            queue.setdefault(q['screening_history_id'], []).append(dict(q))
    states = {}
    for kind, rows in (('ubo', ubos), ('signatory', sigs)):
        for p in rows:
            h = hist.get(p.get('screening_history_id'))
            st = logic.screening_state(p, h, queue.get(p.get('screening_history_id'), []))
            p['screening_state'] = st
            p['screening_queue'] = queue.get(p.get('screening_history_id'), [])
            p['screening'] = h
            states[(kind, p['id'])] = st
    return ubos, sigs, states


def blockers(subject, subject_id, db=None):
    db = db or get_db()
    ent = entity(subject, subject_id, db)
    if not ent:
        return [M('Record not found.')]
    ubos, sigs, states = with_states(subject, subject_id, db)
    return logic.approval_blockers(ent, ubos, sigs, states)


def risk_people(subject, subject_id, db=None):
    """Owners and signatories with their screening state, for the customer risk floor."""
    try:
        ubos, sigs, _s = with_states(subject, subject_id, db)
    except Exception:
        (db or get_db()).rollback()
        return []
    return ubos + sigs
