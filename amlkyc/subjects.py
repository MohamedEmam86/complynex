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
KYC subjects: the registers whose files the KYC assurance features evaluate.
The core ships two (AML customers, merchants); another module or a content
pack can add its own with register_subject() — e.g. a lending module's
clients — without the core knowing about it.
"""

from dataclasses import dataclass, field

from database.db import get_db

CLOSED_CUSTOMER_STATUSES = ('CLOSED', 'EXITED', 'REJECTED', 'TERMINATED', 'INACTIVE')


@dataclass
class Subject:
    code: str
    label_en: str
    label_ar: str
    table: str
    kind: object           # row -> 'individual' | 'entity'
    name: object           # row -> display name
    active: object         # row -> bool (relationship live)
    endpoint: str = ''     # url_for endpoint of the source record, called with id=
    risk_values: object = None   # (row, db) -> {field_key: value} extra inputs for the risk model
    extra: dict = field(default_factory=dict)


SUBJECTS = {}


def register_subject(subject):
    SUBJECTS[subject.code] = subject
    return subject


def rows(code, db=None, limit=None):
    db = db or get_db()
    s = SUBJECTS[code]
    try:
        sql = f"SELECT * FROM {s.table} ORDER BY id" + (f" LIMIT {int(limit)}" if limit else '')
        return [dict(r) for r in db.execute(sql).fetchall()]
    except Exception:
        db.rollback()
        return []


def row(code, subject_id, db=None):
    db = db or get_db()
    s = SUBJECTS[code]
    try:
        r = db.execute(f"SELECT * FROM {s.table} WHERE id = %s", (subject_id,)).fetchone()
        return dict(r) if r else None
    except Exception:
        db.rollback()
        return None


def _customer_values(r, db):
    try:
        n = db.execute("SELECT count(*) AS n FROM tm_alerts WHERE customer_id = %s", (r['id'],)).fetchone()['n']
    except Exception:
        db.rollback()
        n = 0
    return {'customer_type': r.get('customer_type'), 'residence_country': r.get('residence_country') or r.get('country'),
            'is_pep': r.get('is_pep'), 'alert_count': n}


register_subject(Subject(
    code='aml_customer', label_en='AML customers', label_ar='عملاء مكافحة غسل الأموال', table='customers',
    kind=lambda r: 'entity' if (r.get('customer_type') or '').upper() in ('CORPORATE', 'ENTITY') else 'individual',
    name=lambda r: r.get('full_name') or r.get('company_name') or r.get('customer_reference') or f"#{r['id']}",
    active=lambda r: (r.get('status') or 'ACTIVE').upper() not in CLOSED_CUSTOMER_STATUSES,
    endpoint='aml.view_customer', risk_values=_customer_values))

register_subject(Subject(
    code='merchant', label_en='Merchants', label_ar='التجار', table='merchants',
    kind=lambda r: 'entity',
    name=lambda r: r.get('merchant_name') or f"#{r['id']}",
    active=lambda r: (r.get('kyc_status') or '').upper() == 'APPROVED',
    endpoint='merchant_kyc.view_merchant',
    risk_values=lambda r, db: {'customer_type': 'CORPORATE', 'residence_country': r.get('country')}))
