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
Evidence items per control: what proves a control that cannot (yet) be
checked automatically — a board approval, a pen-test report, a DR test, an
auditor certificate. Each item has a validity period, needs approval by a
reviewer other than the submitter, and is swept daily for expiry.

Files are stored through the shared attachments module
(generic_attachments, module 'regcontrols', record_type 'rc_evidence').
"""

import logging
import os
import shutil
from datetime import date, datetime

from database.db import get_db

from . import logic, params

logger = logging.getLogger(__name__)

ATTACH_MODULE = 'regcontrols'
ATTACH_TYPE = 'rc_evidence'


class EvidenceError(ValueError):
    pass


def _warn_days(db):
    try:
        return params.get_param('rc.evidence_expiry_warning_days', default=30, db=db)
    except Exception:
        return 30


def list_for_control(control_id, db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute("""
        SELECT e.*, su.first_name || ' ' || su.last_name AS submitted_by_name,
               ru.first_name || ' ' || ru.last_name AS reviewed_by_name
        FROM rc_evidence e
        LEFT JOIN users su ON su.id = e.submitted_by LEFT JOIN users ru ON ru.id = e.reviewed_by
        WHERE e.control_id = %s ORDER BY e.submitted_at DESC
    """, (control_id,)).fetchall()]


def get(evidence_id, db=None):
    db = db or get_db()
    r = db.execute("""
        SELECT e.*, c.control_code, c.title_en AS control_title_en, c.title_ar AS control_title_ar,
               su.first_name || ' ' || su.last_name AS submitted_by_name,
               ru.first_name || ' ' || ru.last_name AS reviewed_by_name
        FROM rc_evidence e JOIN rc_controls c ON c.id = e.control_id
        LEFT JOIN users su ON su.id = e.submitted_by LEFT JOIN users ru ON ru.id = e.reviewed_by
        WHERE e.id = %s
    """, (evidence_id,)).fetchone()
    return dict(r) if r else None


def list_all(state=None, scope_sql='', scope_args=(), db=None):
    db = db or get_db()
    rows = [dict(r) for r in db.execute(f"""
        SELECT e.*, c.control_code, c.title_en AS control_title_en, c.title_ar AS control_title_ar
        FROM rc_evidence e JOIN rc_controls c ON c.id = e.control_id
        WHERE 1=1 {scope_sql} ORDER BY e.valid_to NULLS LAST, e.submitted_at DESC
    """, tuple(scope_args)).fetchall()]
    warn = _warn_days(db)
    for r in rows:
        r['state'] = logic.evidence_state(r, date.today(), warn)
    if state:
        rows = [r for r in rows if r['state'] == state]
    return rows


def record_evidence(control, title, *, valid_from=None, valid_to=None, description=None, reference_no=None,
                    submitted_by=None, org_unit_id=None, source='manual', source_module=None,
                    file_path=None, file_name=None, db=None):
    """Create an evidence item (status 'pending', waiting for review).

    Items recorded by the system itself (source='system', e.g. an automatic
    SSL check) are stored as approved — there is no human submitter to
    separate from the reviewer. Optionally copies a file into the shared
    attachments store. Returns the rc_evidence id.
    """
    from .engine import get_control
    db = db or get_db()
    ctrl = get_control(control, db)
    if not ctrl:
        raise EvidenceError('control not found')
    if not (title or '').strip():
        raise EvidenceError('title is required')
    vf, vt = logic._as_date(valid_from), logic._as_date(valid_to)
    if vf and vt and vt < vf:
        raise EvidenceError('valid to must not be before valid from')
    status = 'approved' if source == 'system' else 'pending'
    now = datetime.now()
    ev_id = db.execute("""
        INSERT INTO rc_evidence (control_id, org_unit_id, title, description, reference_no, valid_from, valid_to,
                                 status, source, source_module, submitted_by, submitted_at, reviewed_at,
                                 review_comment)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (ctrl['id'], org_unit_id, title.strip()[:300], description, reference_no, vf, vt, status, source,
          source_module, submitted_by, now, now if status == 'approved' else None,
          'Recorded automatically by the system' if status == 'approved' else None)).fetchone()['id']
    db.commit()
    if file_path:
        attach_file(ev_id, file_path, file_name, submitted_by, db=db)
    if status == 'approved':
        _after_approval(ctrl['id'], db)
    else:
        from .notify import evidence_submitted
        evidence_submitted(ev_id, db=db)  # reviewers: in-app + background email; never raises
    return ev_id


def attach_file(evidence_id, file_path, file_name=None, user_id=None, db=None):
    """Copy a file from disk into the attachments store for an evidence item."""
    from flask import current_app
    from utils.file_validator import secure_filename_strict
    db = db or get_db()
    name = secure_filename_strict(file_name or os.path.basename(file_path))
    rel_dir = os.path.join('uploads', 'attachments', ATTACH_MODULE, ATTACH_TYPE, str(evidence_id))
    full_dir = os.path.join(current_app.root_path, rel_dir)
    os.makedirs(full_dir, exist_ok=True)
    dest = os.path.join(full_dir, name)
    shutil.copyfile(file_path, dest)
    db.execute("""
        INSERT INTO generic_attachments (module, record_type, record_id, filename, file_path, file_size,
                                         description, uploaded_by, uploaded_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (ATTACH_MODULE, ATTACH_TYPE, evidence_id, (file_name or name)[:255],
          os.path.join(rel_dir, name).replace('\\', '/'), os.path.getsize(dest), None, user_id,
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()


def review(evidence_id, reviewer_id, decision, comment=None, db=None):
    """Approve or reject a pending item. The reviewer must not be the submitter."""
    db = db or get_db()
    item = get(evidence_id, db)
    if not item:
        raise EvidenceError('evidence not found')
    if item['status'] != 'pending':
        raise EvidenceError('only pending evidence can be reviewed')
    if item['submitted_by'] and item['submitted_by'] == reviewer_id:
        raise EvidenceError('evidence must be reviewed by someone other than the person who submitted it')
    if decision not in ('approved', 'rejected'):
        raise EvidenceError('decision must be approved or rejected')
    if decision == 'rejected' and not (comment or '').strip():
        raise EvidenceError('a comment is required when rejecting evidence')
    db.execute("UPDATE rc_evidence SET status = %s, reviewed_by = %s, reviewed_at = %s, review_comment = %s "
               "WHERE id = %s", (decision, reviewer_id, datetime.now(), comment, evidence_id))
    db.commit()
    if decision == 'approved':
        _after_approval(item['control_id'], db)


def _after_approval(control_id, db):
    """New valid evidence clears expiry alerts for the control's older items."""
    from . import alerts
    old = [r['id'] for r in db.execute(
        "SELECT id FROM rc_evidence WHERE control_id = %s AND status IN ('approved', 'expired')",
        (control_id,)).fetchall()]
    for ev_id in old:
        alerts.resolve_alerts(['evidence_expiring', 'evidence_expired'], evidence_id=ev_id,
                              note='Newer evidence approved', db=db)


def sweep_expiry(today=None, db=None):
    """Mark expired items and alert owners about items expiring soon.
    Returns (expired, expiring)."""
    from . import alerts
    db = db or get_db()
    today = logic._as_date(today) or date.today()
    warn = _warn_days(db)
    rows = [dict(r) for r in db.execute("""
        SELECT e.*, c.control_code, c.title_en AS control_title, c.owner_user_id, c.criticality,
               EXISTS (SELECT 1 FROM rc_evidence n WHERE n.control_id = e.control_id AND n.id <> e.id
                       AND n.status = 'approved' AND (n.valid_to IS NULL OR n.valid_to > e.valid_to)) AS superseded
        FROM rc_evidence e JOIN rc_controls c ON c.id = e.control_id
        WHERE e.status = 'approved' AND e.valid_to IS NOT NULL
    """).fetchall()]
    expired = expiring = 0
    for e in rows:
        state = logic.evidence_state(e, today, warn)
        link = alerts.LINKS['evidence'].format(id=e['id'])
        if state == 'expired':
            db.execute("UPDATE rc_evidence SET status = 'expired' WHERE id = %s", (e['id'],))
            db.commit()
            alerts.resolve_alerts('evidence_expiring', evidence_id=e['id'], note='Expired', db=db)
            if not e['superseded']:
                alerts.raise_alert(
                    'evidence_expired', f"{e['control_code']}: evidence expired — {e['title']}",
                    f"Evidence for {e['control_code']} ({e['control_title']}) expired on {e['valid_to']}. "
                    f"Upload and approve new evidence.",
                    severity=e['criticality'] or 'high', control_id=e['control_id'], evidence_id=e['id'],
                    owner_user_id=e['owner_user_id'] or e['submitted_by'], org_unit_id=e['org_unit_id'],
                    link=link, db=db)
            expired += 1
        elif state == 'expiring' and not e['superseded']:
            alerts.raise_alert(
                'evidence_expiring', f"{e['control_code']}: evidence expires on {e['valid_to']}",
                f"Evidence \"{e['title']}\" for {e['control_code']} expires on {e['valid_to']}. "
                f"Prepare the renewal now.",
                severity='medium', control_id=e['control_id'], evidence_id=e['id'],
                owner_user_id=e['owner_user_id'] or e['submitted_by'], org_unit_id=e['org_unit_id'],
                link=link, db=db)
            expiring += 1
    return expired, expiring
