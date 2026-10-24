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
Unusual-transactions register (aml_unusual_transactions).

Any module that detects a pattern worth an AML study calls
register_candidate(); the AML team then studies it and decides STR / no STR.
Registration is idempotent per (source_table, source_record_id, detection_rule),
so a scheduled check can call it on every run. Each entry also has its case in the
one STR register (suspicious_activities) — see aml/str_register.py.
"""

from datetime import date, datetime, timedelta

from database.db import get_db


def register_candidate(*, source_module, detection_rule, description, source_table=None, source_record_id=None,
                       party_id=None, subject_name=None, subject_ref=None, amount=None, org_unit_id=None,
                       created_by=None, study_sla_days=None, db=None):
    """Add a candidate to the register (or return the existing one). Returns (id, created)."""
    db = db or get_db()
    if source_table and source_record_id is not None:
        row = db.execute("""SELECT id FROM aml_unusual_transactions WHERE source_table = %s
                            AND source_record_id = %s AND detection_rule = %s""",
                         (source_table, source_record_id, detection_rule)).fetchone()
        if row:
            _ensure_case(row['id'], db)
            return row['id'], False
    due = date.today() + timedelta(days=int(study_sla_days)) if study_sla_days else None
    uid = db.execute("""
        INSERT INTO aml_unusual_transactions
            (source_module, source_table, source_record_id, detection_rule, party_id, subject_name, subject_ref,
             amount, description, study_due_date, org_unit_id, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (source_module, source_table, source_record_id, detection_rule, party_id, subject_name, subject_ref,
          amount, description, due, org_unit_id, created_by)).fetchone()['id']
    db.execute("UPDATE aml_unusual_transactions SET reference = %s WHERE id = %s",
               (f'UTR-{datetime.now().year}-{uid:05d}', uid))
    db.commit()
    try:
        from models.case import Case
        Case.sync_from_source('UNUSUAL_TXN', uid)
    except Exception:
        db.rollback()
    _ensure_case(uid, db)
    return uid, True


def _ensure_case(uid, db):
    """Every entry has its case in the one STR register (aml/str_register.py)."""
    try:
        from aml.str_register import ensure_case_for_unusual
        ensure_case_for_unusual(uid, db=db)
    except Exception:
        db.rollback()
        import logging
        logging.getLogger(__name__).exception('Could not open the STR register case for unusual entry %s', uid)


def list_register(status=None, db=None):
    db = db or get_db()
    sql = "SELECT * FROM aml_unusual_transactions"
    args = ()
    if status:
        sql += " WHERE status = %s"
        args = (status,)
    return [dict(r) for r in db.execute(sql + " ORDER BY detected_at DESC", args).fetchall()]
