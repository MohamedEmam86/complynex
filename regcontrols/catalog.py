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
Catalog of regulator- and sector-specific reference data, stored as rows:
regulators, licence types, areas, owner roles, frameworks, requirements and
the controls that satisfy them. Editable in the UI (Compliance Controls >
Library) and installable by content packs through the install_* helpers.

install_* helpers are idempotent and never overwrite what a user has since
changed in the UI: they insert missing rows and only fill a pack_code.
"""

from datetime import datetime

from database.db import get_db

from . import vocab

REF_TABLES = {
    'licence_types': 'rc_licence_types',
    'areas': 'rc_areas',
    'owner_roles': 'rc_owner_roles',
}


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


# ------------------------------------------------------------------ lookups
def ref_list(kind, db=None):
    db = db or get_db()
    table = REF_TABLES[kind]
    order = 'sort_order, code' if kind == 'areas' else 'code'
    return _rows(db, f"SELECT * FROM {table} ORDER BY {order}")


def ref_labels(kind, db=None):
    """{code: (name_en, name_ar)} for a reference table."""
    return {r['code']: (r['name_en'], r['name_ar'] or r['name_en']) for r in ref_list(kind, db)}


def regulators(db=None):
    db = db or get_db()
    return _rows(db, "SELECT * FROM regulators ORDER BY regulator_name")


def frameworks(active_only=False, db=None):
    db = db or get_db()
    return _rows(db, f"""
        SELECT f.*, r.regulator_name, r.name_ar AS regulator_name_ar,
               (SELECT count(*) FROM rc_requirements q WHERE q.framework_id = f.id) AS requirement_count,
               (SELECT count(DISTINCT cr.control_id) FROM rc_requirements q
                  JOIN rc_control_requirements cr ON cr.requirement_id = q.id WHERE q.framework_id = f.id) AS control_count
        FROM rc_frameworks f LEFT JOIN regulators r ON r.id = f.regulator_id
        {'WHERE f.is_active' if active_only else ''} ORDER BY f.code""")


def framework(framework_id, db=None):
    db = db or get_db()
    r = db.execute("""SELECT f.*, r.regulator_name, r.name_ar AS regulator_name_ar FROM rc_frameworks f
                      LEFT JOIN regulators r ON r.id = f.regulator_id WHERE f.id = %s""", (framework_id,)).fetchone()
    return dict(r) if r else None


def requirements(framework_id, db=None):
    db = db or get_db()
    return _rows(db, """
        SELECT q.*, (SELECT string_agg(c.control_code, ', ' ORDER BY c.control_code)
                     FROM rc_control_requirements cr JOIN rc_controls c ON c.id = cr.control_id
                     WHERE cr.requirement_id = q.id) AS control_codes
        FROM rc_requirements q WHERE q.framework_id = %s ORDER BY q.sort_order, q.ref_code""", (framework_id,))


def control_requirements(control_id, db=None):
    db = db or get_db()
    return _rows(db, """
        SELECT q.*, f.code AS framework_code, f.name_en AS framework_name_en, f.name_ar AS framework_name_ar
        FROM rc_control_requirements cr JOIN rc_requirements q ON q.id = cr.requirement_id
        JOIN rc_frameworks f ON f.id = q.framework_id WHERE cr.control_id = %s ORDER BY f.code, q.ref_code""",
                 (control_id,))


# ------------------------------------------------------------------ edits (UI)
class CatalogError(ValueError):
    pass


def save_ref(kind, code, name_en, name_ar=None, extra=None, db=None):
    db = db or get_db()
    code = (code or '').strip().lower()
    if not code or not (name_en or '').strip():
        raise CatalogError('code and English name are required')
    table = REF_TABLES[kind]
    cols = {'code': code, 'name_en': name_en.strip(), 'name_ar': (name_ar or '').strip() or None}
    cols.update({k: v for k, v in (extra or {}).items() if v not in (None, '')})
    keys = list(cols)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))}) "
               f"ON CONFLICT (code) DO UPDATE SET " + ', '.join(f'{k} = EXCLUDED.{k}' for k in keys if k != 'code'),
               tuple(cols.values()))
    db.commit()


def save_regulator(name_en, code=None, name_ar=None, jurisdiction=None, website=None, regulator_id=None, db=None):
    db = db or get_db()
    if not (name_en or '').strip():
        raise CatalogError('regulator name is required')
    if regulator_id:
        db.execute("UPDATE regulators SET regulator_name = %s, regulator_code = %s, name_ar = %s, jurisdiction = %s, "
                   "website = %s WHERE id = %s",
                   (name_en.strip(), code or None, name_ar or None, (jurisdiction or '').upper() or None, website or None,
                    regulator_id))
        db.commit()
        return regulator_id
    rid = db.execute("INSERT INTO regulators (regulator_name, regulator_code, name_ar, jurisdiction, website) "
                     "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                     (name_en.strip(), code or None, name_ar or None, (jurisdiction or '').upper() or None,
                      website or None)).fetchone()['id']
    db.commit()
    return rid


def save_framework(data, framework_id=None, db=None):
    db = db or get_db()
    code = (data.get('code') or '').strip().upper()
    if not code or not (data.get('name_en') or '').strip():
        raise CatalogError('framework code and English name are required')
    vals = (code, data['name_en'].strip(), data.get('name_ar') or None, data.get('regulator_id') or None,
            (data.get('jurisdiction') or '').upper() or None, data.get('version') or None,
            data.get('description') or None, data.get('source_document') or None, bool(data.get('is_active', True)))
    if framework_id:
        db.execute("""UPDATE rc_frameworks SET code = %s, name_en = %s, name_ar = %s, regulator_id = %s, jurisdiction = %s,
                      version = %s, description = %s, source_document = %s, is_active = %s WHERE id = %s""",
                   vals + (framework_id,))
        db.commit()
        return framework_id
    fid = db.execute("""INSERT INTO rc_frameworks (code, name_en, name_ar, regulator_id, jurisdiction, version,
                        description, source_document, is_active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     vals).fetchone()['id']
    db.commit()
    return fid


def save_requirement(framework_id, data, requirement_id=None, db=None):
    db = db or get_db()
    ref = (data.get('ref_code') or '').strip()
    if not ref or not (data.get('title_en') or '').strip():
        raise CatalogError('requirement reference and English title are required')
    vals = (ref, data['title_en'].strip(), data.get('title_ar') or None, data.get('text_en') or None,
            data.get('text_ar') or None, data.get('legal_reference') or None, data.get('area_code') or None)
    if requirement_id:
        db.execute("""UPDATE rc_requirements SET ref_code = %s, title_en = %s, title_ar = %s, text_en = %s, text_ar = %s,
                      legal_reference = %s, area_code = %s WHERE id = %s AND framework_id = %s""",
                   vals + (requirement_id, framework_id))
        db.commit()
        return requirement_id
    rid = db.execute("""INSERT INTO rc_requirements (ref_code, title_en, title_ar, text_en, text_ar, legal_reference,
                        area_code, framework_id, sort_order)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                                (SELECT COALESCE(max(sort_order), 0) + 1 FROM rc_requirements WHERE framework_id = %s))
                        RETURNING id""", vals + (framework_id, framework_id)).fetchone()['id']
    db.commit()
    return rid


def map_control(control_id, requirement_id, linked=True, db=None):
    db = db or get_db()
    if linked:
        db.execute("INSERT INTO rc_control_requirements (control_id, requirement_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", (control_id, requirement_id))
    else:
        db.execute("DELETE FROM rc_control_requirements WHERE control_id = %s AND requirement_id = %s",
                   (control_id, requirement_id))
    db.commit()


def create_control(data, db=None):
    db = db or get_db()
    code = (data.get('control_code') or '').strip().upper()
    if not code or not (data.get('title_en') or '').strip():
        raise CatalogError('control code and English title are required')
    ctype = data.get('control_type') or 'evidence'
    if ctype not in vocab.CONTROL_TYPES:
        raise CatalogError('unknown control type')
    if db.execute("SELECT 1 FROM rc_controls WHERE control_code = %s", (code,)).fetchone():
        raise CatalogError('a control with this code already exists')
    cid = db.execute("""INSERT INTO rc_controls (control_code, title_en, title_ar, area, control_type, frequency,
                        criticality, owner_role, requirement_en) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (code, data['title_en'].strip(), data.get('title_ar') or None, data.get('area') or None, ctype,
                      data.get('frequency') if data.get('frequency') in vocab.FREQUENCIES else 'monthly',
                      data.get('criticality') if data.get('criticality') in vocab.CRITICALITY else 'high',
                      data.get('owner_role') or None, data.get('requirement_en') or None)).fetchone()['id']
    db.commit()
    return cid


# ------------------------------------------------------------------ pack installers
def install_ref(kind, code, name_en, name_ar=None, pack_code=None, db=None, **extra):
    db = db or get_db()
    table = REF_TABLES[kind]
    cols = dict({'code': code, 'name_en': name_en, 'name_ar': name_ar, 'pack_code': pack_code}, **extra)
    db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
               f"ON CONFLICT (code) DO NOTHING", tuple(cols.values()))


def install_regulator(code, name_en, name_ar=None, jurisdiction=None, website=None, db=None):
    db = db or get_db()
    r = db.execute("SELECT id FROM regulators WHERE regulator_code = %s", (code,)).fetchone()
    if r:
        db.execute("UPDATE regulators SET name_ar = COALESCE(name_ar, %s), jurisdiction = COALESCE(jurisdiction, %s) "
                   "WHERE id = %s", (name_ar, jurisdiction, r['id']))
        return r['id']
    return db.execute("INSERT INTO regulators (regulator_name, regulator_code, name_ar, jurisdiction, website) "
                      "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                      (name_en, code, name_ar, jurisdiction, website)).fetchone()['id']


def install_framework(code, name_en, name_ar=None, regulator_id=None, jurisdiction=None, version=None,
                      description=None, source_document=None, pack_code=None, db=None):
    db = db or get_db()
    r = db.execute("SELECT id FROM rc_frameworks WHERE code = %s", (code,)).fetchone()
    if r:
        return r['id']
    return db.execute("""INSERT INTO rc_frameworks (code, name_en, name_ar, regulator_id, jurisdiction, version,
                         description, source_document, pack_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                      (code, name_en, name_ar, regulator_id, jurisdiction, version, description, source_document,
                       pack_code)).fetchone()['id']


def install_requirement(framework_id, ref_code, title_en, title_ar=None, text_en=None, text_ar=None,
                        legal_reference=None, area_code=None, sort_order=0, db=None):
    db = db or get_db()
    r = db.execute("SELECT id FROM rc_requirements WHERE framework_id = %s AND ref_code = %s",
                   (framework_id, ref_code)).fetchone()
    if r:
        return r['id']
    return db.execute("""INSERT INTO rc_requirements (framework_id, ref_code, title_en, title_ar, text_en, text_ar,
                         legal_reference, area_code, sort_order) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                      (framework_id, ref_code, title_en, title_ar, text_en, text_ar, legal_reference, area_code,
                       sort_order)).fetchone()['id']


def install_control(c, pack_code=None, requirement_ids=(), db=None):
    """c: dict with code, area, type_codes, control_type, title_en/ar, requirement_en, test_procedure_en,
    linked_module, owner_role, frequency, criticality, linked_params, licence_types, check_key."""
    db = db or get_db()
    r = db.execute("SELECT id, check_key FROM rc_controls WHERE control_code = %s", (c['code'],)).fetchone()
    if r:
        cid = r['id']
        # A newer pack version may add a check to a control installed earlier.
        if not r['check_key'] and c.get('check_key'):
            db.execute("UPDATE rc_controls SET check_key = %s WHERE id = %s", (c['check_key'], cid))
    else:
        cid = db.execute("""
            INSERT INTO rc_controls (control_code, area, title_en, title_ar, requirement_en, control_type, type_codes,
                                     frequency, criticality, owner_role, linked_module, linked_params, licence_types,
                                     test_procedure_en, check_key, pack_code)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                         (c['code'], c.get('area'), c['title_en'], c.get('title_ar'), c.get('requirement_en'),
                          c['control_type'], c.get('type_codes'), c.get('frequency', 'monthly'),
                          c.get('criticality', 'high'), c.get('owner_role'), c.get('linked_module'),
                          list(c.get('linked_params') or []), list(c.get('licence_types') or ['all']),
                          c.get('test_procedure_en'), c.get('check_key'), pack_code)).fetchone()['id']
    for rid in requirement_ids:
        db.execute("INSERT INTO rc_control_requirements (control_id, requirement_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", (cid, rid))
    return cid


def install_parameter(p, pack_code=None, framework_id=None, db=None):
    """p: dict with key, licence_type, value, value_type, unit, description_en/ar, legal_reference,
    needs_review, review_note. Inserted once, with an approved history row."""
    db = db or get_db()
    r = db.execute("""INSERT INTO rc_parameters (param_key, licence_type, value_text, value_type, unit, legal_reference,
                      description_en, description_ar, needs_review, review_note, approved_at, framework_id, pack_code)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (param_key, licence_type, effective_from) DO NOTHING
                      RETURNING id, effective_from""",
                   (p['key'], p.get('licence_type', 'all'), p.get('value'), p['value_type'], p.get('unit'),
                    p.get('legal_reference'), p.get('description_en'), p.get('description_ar'),
                    bool(p.get('needs_review')), p.get('review_note'), datetime.now(), framework_id,
                    pack_code)).fetchone()
    if r:
        db.execute("""INSERT INTO rc_parameter_changes (parameter_id, param_key, licence_type, change_type, new_value,
                      value_type, unit, effective_from, reason, status, decided_at, applied_parameter_id)
                      VALUES (%s,%s,%s,'create',%s,%s,%s,%s,%s,'approved',%s,%s)""",
                   (r['id'], p['key'], p.get('licence_type', 'all'), p.get('value'), p['value_type'], p.get('unit'),
                    r['effective_from'], f'Installed by pack {pack_code}' if pack_code else 'Installed',
                    datetime.now(), r['id']))
    return r['id'] if r else None


def install_regulatory_report(code, name, frequency, *, due_day=None, due_month=None, description=None,
                              regulator_id=None, submission_method=None, responsible_department=None, db=None):
    """Add a periodic submission to the existing regulatory calendar (Regulatory
    Reports module) unless a report with this code exists. Returns its id."""
    db = db or get_db()
    r = db.execute("SELECT id FROM regulatory_reports WHERE report_code = %s", (code,)).fetchone()
    if r:
        return r['id']
    # '1' (a quoted literal, not TRUE or a bound int): the legacy is_active column is INTEGER on
    # migrated installations and BOOLEAN on others; PostgreSQL casts '1' to either.
    return db.execute("""INSERT INTO regulatory_reports (report_code, report_name, regulator_id, frequency, due_day,
                         due_month, description, submission_method, responsible_department, is_active)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'1') RETURNING id""",
                      (code, name, regulator_id, frequency, due_day, due_month, description, submission_method,
                       responsible_department)).fetchone()['id']
