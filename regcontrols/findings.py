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
Findings & corrective actions (inspection / audit / self-identified findings).

A finding comes from the regulator, internal / external audit, self-
identification or a failing control. It is linked to one or more controls,
gets a corrective action plan (actions with owner, due date, status and
evidence), and is closed only by VERIFICATION: every linked control is
re-run and must pass. When a linked control fails again after the finding
was closed, the finding reopens and is flagged as a repeated violation.
"""

import logging
from datetime import date, datetime, timedelta

from database.db import get_db

from . import logic, params

logger = logging.getLogger(__name__)

ACTION_STATUSES = ('open', 'in_progress', 'done', 'cancelled')


class FindingError(ValueError):
    pass


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def add_event(finding_id, event_type, note=None, user_id=None, run_id=None, db=None):
    db = db or get_db()
    db.execute("INSERT INTO rc_finding_events (finding_id, event_type, note, run_id, user_id) "
               "VALUES (%s,%s,%s,%s,%s)", (finding_id, event_type, note, run_id, user_id))


def _control_ids(codes, db):
    codes = [c.strip().upper() for c in (codes or []) if c and c.strip()]
    if not codes:
        return []
    rows = _rows(db, "SELECT id, control_code FROM rc_controls WHERE control_code = ANY(%s)", (codes,))
    found = {r['control_code'] for r in rows}
    missing = [c for c in codes if c not in found]
    if missing:
        raise FindingError('unknown control code(s): ' + ', '.join(missing))
    return [r['id'] for r in rows]


def link_controls(finding_id, control_codes=None, control_ids=None, db=None):
    db = db or get_db()
    ids = list(control_ids or []) + _control_ids(control_codes, db)
    for cid in dict.fromkeys(ids):
        db.execute("INSERT INTO rc_finding_controls (finding_id, control_id) VALUES (%s, %s) "
                   "ON CONFLICT DO NOTHING", (finding_id, cid))
    db.commit()


def unlink_control(finding_id, control_id, db=None):
    db = db or get_db()
    db.execute("DELETE FROM rc_finding_controls WHERE finding_id = %s AND control_id = %s", (finding_id, control_id))
    db.commit()


def raise_finding(title, *, source='self_identified', severity='medium', description=None, source_ref=None,
                  area=None, control_codes=None, control_ids=None, owner_user_id=None, due_date=None,
                  identified_date=None, org_unit_id=None, created_by=None, dedupe=True, db=None):
    """Create a finding (or return the existing one) and link it to controls.

    dedupe=True returns the existing finding when (source, source_ref) was
    already imported, or — for source 'control_failure' — when an open
    control-failure finding already exists for the same first control. That
    lets a check call raise_finding() on every failing run without piling up
    duplicates. Returns the rc_findings id.
    """
    db = db or get_db()
    if not (title or '').strip():
        raise FindingError('title is required')
    if source not in logic.FINDING_SOURCES:
        raise FindingError(f'unknown source {source!r}')
    if severity not in logic.SEVERITIES:
        raise FindingError(f'unknown severity {severity!r}')
    ids = list(control_ids or []) + _control_ids(control_codes, db)
    if dedupe:
        existing = None
        if source_ref:
            existing = db.execute("SELECT id FROM rc_findings WHERE source = %s AND source_ref = %s",
                                  (source, source_ref)).fetchone()
        elif source == 'control_failure' and ids:
            existing = db.execute("""
                SELECT f.id FROM rc_findings f JOIN rc_finding_controls fc ON fc.finding_id = f.id
                WHERE f.source = 'control_failure' AND fc.control_id = %s AND f.status <> 'closed'
                ORDER BY f.id DESC LIMIT 1""", (ids[0],)).fetchone()
        if existing:
            link_controls(existing['id'], control_ids=ids, db=db)
            return existing['id']
    fid = db.execute("""
        INSERT INTO rc_findings (source, source_ref, title, description, severity, area, org_unit_id,
                                 owner_user_id, identified_date, due_date, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (source, source_ref, title.strip()[:400], description, severity, area, org_unit_id, owner_user_id,
          logic._as_date(identified_date) or date.today(), logic._as_date(due_date), created_by)).fetchone()['id']
    db.execute("UPDATE rc_findings SET reference = %s WHERE id = %s",
               (f'RCF-{date.today().year}-{fid:05d}', fid))
    add_event(fid, 'created', f'Source: {source}' + (f' ({source_ref})' if source_ref else ''), created_by, db=db)
    db.commit()
    link_controls(fid, control_ids=ids, db=db)
    return fid


def get_finding(finding_id, db=None):
    db = db or get_db()
    r = db.execute("""
        SELECT f.*, ou.first_name || ' ' || ou.last_name AS owner_name
        FROM rc_findings f LEFT JOIN users ou ON ou.id = f.owner_user_id WHERE f.id = %s
    """, (finding_id,)).fetchone()
    if not r:
        return None
    f = dict(r)
    f['controls'] = _rows(db, """
        SELECT c.* FROM rc_controls c JOIN rc_finding_controls fc ON fc.control_id = c.id
        WHERE fc.finding_id = %s ORDER BY c.control_code""", (finding_id,))
    f['actions'] = _rows(db, """
        SELECT a.*, u.first_name || ' ' || u.last_name AS owner_name
        FROM rc_corrective_actions a LEFT JOIN users u ON u.id = a.owner_user_id
        WHERE a.finding_id = %s ORDER BY a.due_date NULLS LAST, a.id""", (finding_id,))
    f['events'] = _rows(db, """
        SELECT e.*, u.first_name || ' ' || u.last_name AS user_name
        FROM rc_finding_events e LEFT JOIN users u ON u.id = e.user_id
        WHERE e.finding_id = %s ORDER BY e.created_at DESC, e.id DESC""", (finding_id,))
    f['age_bucket'] = logic.age_bucket(f['identified_date'])
    f['overdue'] = logic.is_overdue(f['due_date'], f['status'], grace_days=_grace(db))
    return f


def _grace(db):
    try:
        return params.get_param('rc.finding_overdue_grace_days', default=0, db=db)
    except Exception:
        return 0


def list_findings(status=None, source=None, severity=None, repeated=None, control_id=None,
                  scope_sql='', scope_args=(), db=None):
    db = db or get_db()
    clauses, args = ['1=1'], []
    if status == 'open':
        clauses.append("f.status <> 'closed'")
    elif status:
        clauses.append('f.status = %s')
        args.append(status)
    if source:
        clauses.append('f.source = %s')
        args.append(source)
    if severity:
        clauses.append('f.severity = %s')
        args.append(severity)
    if repeated:
        clauses.append('f.is_repeated')
    if control_id:
        clauses.append('EXISTS (SELECT 1 FROM rc_finding_controls fc WHERE fc.finding_id = f.id AND fc.control_id = %s)')
        args.append(control_id)
    rows = _rows(db, f"""
        SELECT f.*, ou.first_name || ' ' || ou.last_name AS owner_name,
               (SELECT string_agg(c.control_code, ', ' ORDER BY c.control_code) FROM rc_finding_controls fc
                  JOIN rc_controls c ON c.id = fc.control_id WHERE fc.finding_id = f.id) AS control_codes,
               (SELECT count(*) FROM rc_corrective_actions a WHERE a.finding_id = f.id) AS action_count,
               (SELECT count(*) FROM rc_corrective_actions a WHERE a.finding_id = f.id
                  AND a.status IN ('done', 'cancelled')) AS actions_done
        FROM rc_findings f LEFT JOIN users ou ON ou.id = f.owner_user_id
        WHERE {' AND '.join(clauses)} {scope_sql}
        ORDER BY (f.status = 'closed'), f.is_repeated DESC, f.due_date NULLS LAST, f.id DESC
    """, tuple(args) + tuple(scope_args))
    grace = _grace(db)
    for f in rows:
        f['age_bucket'] = logic.age_bucket(f['identified_date'])
        f['overdue'] = logic.is_overdue(f['due_date'], f['status'], grace_days=grace)
    return rows


def ageing_summary(rows):
    out = {label: 0 for label, _, _ in logic.AGE_BUCKETS}
    for f in rows:
        if f['status'] != 'closed':
            out[f['age_bucket']] += 1
    return out


def update_finding(finding_id, user_id, db=None, **fields):
    allowed = {'title', 'description', 'severity', 'area', 'owner_user_id', 'due_date', 'source_ref', 'org_unit_id'}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    db = db or get_db()
    sets = ', '.join(f'{k} = %s' for k in fields)
    db.execute(f"UPDATE rc_findings SET {sets}, updated_at = %s WHERE id = %s",
               (*fields.values(), datetime.now(), finding_id))
    add_event(finding_id, 'updated', ', '.join(sorted(fields)), user_id, db=db)
    db.commit()


# ------------------------------------------------------------------ actions
def _refresh_status(finding_id, db):
    """Keep the finding's status in step with its action plan (never closes —
    only verification closes)."""
    f = db.execute("SELECT status FROM rc_findings WHERE id = %s", (finding_id,)).fetchone()
    if not f or f['status'] in ('closed', 'pending_verification'):
        return
    acts = [r['status'] for r in db.execute(
        "SELECT status FROM rc_corrective_actions WHERE finding_id = %s", (finding_id,)).fetchall()]
    if not acts:
        new = f['status']
    elif any(s in ('in_progress', 'done') for s in acts):
        new = 'in_progress'
    else:
        new = 'action_plan'
    if f['status'] == 'reopened' and new == 'action_plan':
        new = 'reopened'
    if new != f['status']:
        db.execute("UPDATE rc_findings SET status = %s, updated_at = %s WHERE id = %s",
                   (new, datetime.now(), finding_id))


def add_action(finding_id, description, *, owner_user_id=None, due_date=None, created_by=None, db=None):
    db = db or get_db()
    if not (description or '').strip():
        raise FindingError('action description is required')
    aid = db.execute("""
        INSERT INTO rc_corrective_actions (finding_id, description, owner_user_id, due_date, created_by)
        VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                     (finding_id, description.strip(), owner_user_id, logic._as_date(due_date), created_by)
                     ).fetchone()['id']
    add_event(finding_id, 'action_added', description.strip()[:300], created_by, db=db)
    _refresh_status(finding_id, db)
    db.commit()
    return aid


def set_action_status(action_id, status, user_id, note=None, db=None):
    db = db or get_db()
    if status not in ACTION_STATUSES:
        raise FindingError('unknown action status')
    a = db.execute("SELECT * FROM rc_corrective_actions WHERE id = %s", (action_id,)).fetchone()
    if not a:
        raise FindingError('action not found')
    done = status in ('done', 'cancelled')
    db.execute("""UPDATE rc_corrective_actions SET status = %s, completion_note = COALESCE(%s, completion_note),
                  completed_at = %s, completed_by = %s WHERE id = %s""",
               (status, note, datetime.now() if done else None, user_id if done else None, action_id))
    add_event(a['finding_id'], f'action_{status}', (note or a['description'])[:300], user_id, db=db)
    _refresh_status(a['finding_id'], db)
    db.commit()
    return a['finding_id']


def request_verification(finding_id, user_id, db=None):
    db = db or get_db()
    acts = _rows(db, "SELECT status FROM rc_corrective_actions WHERE finding_id = %s", (finding_id,))
    if not acts:
        raise FindingError('add at least one corrective action before asking for verification')
    if any(a['status'] not in ('done', 'cancelled') for a in acts):
        raise FindingError('all corrective actions must be done (or cancelled) first')
    db.execute("UPDATE rc_findings SET status = 'pending_verification', updated_at = %s WHERE id = %s",
               (datetime.now(), finding_id))
    add_event(finding_id, 'verification_requested', None, user_id, db=db)
    db.commit()
    from .notify import verification_requested
    verification_requested(finding_id, user_id, db=db)


def verify(finding_id, user_id, manual_note=None, db=None):
    """Re-run every linked control; close the finding only if they all pass.

    Returns (outcome, runs). Controls with no automated or evidence check
    give outcome 'manual': the finding is closed only when manual_note
    explains how the fix was verified, and the verifier must not be the
    finding owner.
    """
    from .engine import run_control
    db = db or get_db()
    f = get_finding(finding_id, db)
    if not f:
        raise FindingError('finding not found')
    if f['status'] == 'closed':
        raise FindingError('finding is already closed')
    req = db.execute("""SELECT user_id FROM rc_finding_events
                         WHERE finding_id = %s AND event_type = 'verification_requested'
                         ORDER BY created_at DESC, id DESC LIMIT 1""", (finding_id,)).fetchone()
    done_by = [r['completed_by'] for r in _rows(
        db, "SELECT completed_by FROM rc_corrective_actions WHERE finding_id = %s AND status = 'done'",
        (finding_id,))]
    err = logic.four_eyes_error(user_id, dict(req)['user_id'] if req else None, done_by)
    if err:
        raise FindingError(err)
    runs = [run_control(c, triggered_by='verification', user_id=user_id, finding_id=finding_id, db=db)
            for c in f['controls'] if c['is_active']]
    outcome = logic.verification_outcome([r['status'] for r in runs])
    summary = '; '.join(f"{c['control_code']}: {r['status']}" for c, r in zip(
        [c for c in f['controls'] if c['is_active']], runs)) or 'no linked controls'
    now = datetime.now()
    if outcome == 'manual':
        if not (manual_note or '').strip():
            add_event(finding_id, 'verification_manual_needed', summary, user_id, db=db)
            db.commit()
            return outcome, runs
        if f['owner_user_id'] and f['owner_user_id'] == user_id:
            raise FindingError('the finding owner cannot verify their own remediation')
        note = 'Manual verification: ' + manual_note.strip()
    elif outcome == 'verified':
        note = 'Verified by re-test — ' + summary
    else:
        db.execute("UPDATE rc_findings SET status = 'in_progress', updated_at = %s WHERE id = %s", (now, finding_id))
        add_event(finding_id, f'verification_{outcome}', summary, user_id,
                  run_id=runs[0]['id'] if runs else None, db=db)
        db.commit()
        return outcome, runs
    db.execute("""UPDATE rc_findings SET status = 'closed', closure_type = 'remediated', verified_at = %s,
                  verified_by = %s, verification_note = %s, closed_at = %s, closed_by = %s, updated_at = %s
                  WHERE id = %s""", (now, user_id, note, now, user_id, now, finding_id))
    add_event(finding_id, 'closed', note, user_id, run_id=runs[0]['id'] if runs else None, db=db)
    db.commit()
    from . import alerts
    alerts.resolve_alerts(['finding_overdue', 'repeated_violation'], finding_id=finding_id,
                          note='Finding verified and closed', db=db)
    return 'verified' if outcome == 'verified' else 'manual_closed', runs


def close_without_remediation(finding_id, user_id, closure_type, note, db=None):
    """Close as not applicable / risk accepted (admin only — enforced by the route)."""
    db = db or get_db()
    if closure_type not in ('not_applicable', 'risk_accepted'):
        raise FindingError('unknown closure type')
    if not (note or '').strip():
        raise FindingError('a justification is required')
    now = datetime.now()
    db.execute("""UPDATE rc_findings SET status = 'closed', closure_type = %s, verification_note = %s,
                  closed_at = %s, closed_by = %s, updated_at = %s WHERE id = %s""",
               (closure_type, note.strip(), now, user_id, now, finding_id))
    add_event(finding_id, 'closed', f'{closure_type}: {note.strip()}', user_id, db=db)
    db.commit()


# ------------------------------------------------------------------ engine hook
def handle_run(control, run, db=None):
    """Engine post-run hook: recurrence detection for findings linked to the control."""
    db = db or get_db()
    if run.get('triggered_by') == 'verification':
        return
    linked = _rows(db, """
        SELECT f.* FROM rc_findings f JOIN rc_finding_controls fc ON fc.finding_id = f.id
        WHERE fc.control_id = %s""", (control['id'],))
    from . import alerts
    now = datetime.now()
    for fid, action in logic.recurrence_actions(linked, run['status']):
        if action == 'reopen_repeat':
            db.execute("""UPDATE rc_findings SET status = 'reopened', is_repeated = TRUE,
                          repeat_count = repeat_count + 1, last_repeat_at = %s, closed_at = NULL,
                          closed_by = NULL, closure_type = NULL, updated_at = %s WHERE id = %s""",
                       (now, now, fid))
            add_event(fid, 'repeated_violation',
                      f"{control['control_code']} failed again after closure: {run.get('summary') or ''}".strip(),
                      run_id=run['id'], db=db)
            db.commit()
            f = next(x for x in linked if x['id'] == fid)
            alerts.raise_alert(
                'repeated_violation', f"Repeated violation: {f['reference']} — {f['title']}"[:300],
                f"{control['control_code']} failed again after the finding was closed. "
                f"The finding has been reopened.",
                severity='critical', control_id=control['id'], finding_id=fid, run_id=run['id'],
                owner_user_id=f['owner_user_id'] or control.get('owner_user_id'),
                org_unit_id=f['org_unit_id'], link=alerts.LINKS['finding'].format(id=fid), db=db)
        elif action == 'still_failing':
            last = db.execute("SELECT event_type, created_at FROM rc_finding_events WHERE finding_id = %s "
                              "ORDER BY created_at DESC, id DESC LIMIT 1", (fid,)).fetchone()
            if not last or last['event_type'] != 'control_still_failing' \
                    or now - last['created_at'] > timedelta(days=7):
                add_event(fid, 'control_still_failing', f"{control['control_code']}: {run.get('summary') or ''}",
                          run_id=run['id'], db=db)
                db.commit()


def sweep_overdue(today=None, db=None):
    """Alert owners of overdue findings. Returns the number alerted."""
    from . import alerts
    db = db or get_db()
    today = logic._as_date(today) or date.today()
    grace = _grace(db)
    n = 0
    for f in _rows(db, "SELECT * FROM rc_findings WHERE status <> 'closed' AND due_date IS NOT NULL"):
        if logic.is_overdue(f['due_date'], f['status'], today, grace):
            alerts.raise_alert(
                'finding_overdue', f"Overdue finding {f['reference']}: {f['title']}"[:300],
                f"Due on {f['due_date']} ({(today - f['due_date']).days} day(s) ago). Status: {f['status']}.",
                severity=f['severity'], finding_id=f['id'], owner_user_id=f['owner_user_id'],
                org_unit_id=f['org_unit_id'], link=alerts.LINKS['finding'].format(id=f['id']), db=db)
            n += 1
    return n


# ------------------------------------------------------------------ imports
def import_rows(rows, created_by, db=None):
    """Import parsed CSV rows (see logic.parse_findings_csv). Returns (created, skipped)."""
    db = db or get_db()
    created = skipped = 0
    emails = {r['owner_email'] for r in rows if r.get('owner_email')}
    owners = {}
    if emails:
        owners = {r['email'].lower(): r['id'] for r in _rows(
            db, "SELECT id, email FROM users WHERE lower(email) = ANY(%s)", (list(emails),))}
    for r in rows:
        before = db.execute("SELECT count(*) AS n FROM rc_findings").fetchone()['n']
        raise_finding(r['title'], source=r['source'], severity=r['severity'], description=r['description'],
                      source_ref=r['source_ref'], area=r['area'], control_codes=r['control_codes'],
                      owner_user_id=owners.get(r.get('owner_email') or ''), due_date=r['due_date'],
                      identified_date=r['identified_date'], created_by=created_by, db=db)
        after = db.execute("SELECT count(*) AS n FROM rc_findings").fetchone()['n']
        if after > before:
            created += 1
        else:
            skipped += 1
    return created, skipped


_IA_SEVERITY = {'CRITICAL': 'critical', 'HIGH': 'high', 'MEDIUM': 'medium', 'LOW': 'low'}


def import_from_internal_audit(created_by, db=None):
    """Bring open internal-audit findings into the tracker (once each).
    A finding whose linked ERM control is mapped to a compliance control
    (rc_controls.erm_control_id) is linked to that control."""
    db = db or get_db()
    rows = _rows(db, """
        SELECT af.*, ap.audit_number FROM audit_findings af
        LEFT JOIN audit_projects ap ON ap.id = af.project_id
        WHERE af.status <> 'VERIFIED_CLOSED'
          AND NOT EXISTS (SELECT 1 FROM rc_findings f WHERE f.source = 'internal_audit'
                          AND f.source_ref = 'IA-' || af.id::text)
    """)
    n = 0
    for af in rows:
        ctrl_ids = []
        if af.get('linked_control_id'):
            ctrl_ids = [r['id'] for r in db.execute(
                "SELECT id FROM rc_controls WHERE erm_control_id = %s", (af['linked_control_id'],)).fetchall()]
        raise_finding(
            f"{af['finding_number']}: {af['finding_title']}", source='internal_audit',
            severity=_IA_SEVERITY.get(af['severity'], 'medium'),
            description='\n\n'.join(x for x in (af.get('finding_description'), af.get('recommendation')) if x)
            or None,
            source_ref=f"IA-{af['id']}", control_ids=ctrl_ids, owner_user_id=af.get('responsible_person_id'),
            due_date=af.get('target_date'), created_by=created_by, db=db)
        n += 1
    return n
