# =============================================================================
# ComplyNex — document applicability and approval workflows (Phase 3)
#
# Applicability answers "who is this document FOR".
# User org scope answers "what may this person SEE".
# They are different questions and are kept in separate tables: a Compliance
# officer may need to see a document that does not apply to their own unit.
# =============================================================================
from database.db import get_db


# ------------------------------------------------------------ document types
def get_document_types(active_only=True):
    q = "SELECT * FROM document_types "
    if active_only:
        q += "WHERE is_active "
    q += "ORDER BY sort_order, name_en"
    return [dict(r) for r in get_db().execute(q).fetchall()]


# ------------------------------------------------------------- applicability
def _expand(rule):
    """One applicability row -> the set of org_unit ids it names."""
    db = get_db()
    if rule['org_unit_id']:
        if not rule['include_descendants']:
            return {rule['org_unit_id']}
        row = db.execute("SELECT path FROM org_units WHERE id=%s", (rule['org_unit_id'],)).fetchone()
        if not row:
            return set()
        return {dict(r)['id'] for r in db.execute(
            "SELECT id FROM org_units WHERE path LIKE %s", (dict(row)['path'] + '%',)).fetchall()}

    params, q = [], None
    if rule['match_code']:
        q = "SELECT id FROM org_units WHERE upper(code)=upper(%s)"; params.append(rule['match_code'])
    elif rule['match_type_id']:
        q = "SELECT id FROM org_units WHERE unit_type_id=%s"; params.append(rule['match_type_id'])
    if not q:
        return set()
    if rule['root_unit_id']:
        root = db.execute("SELECT path FROM org_units WHERE id=%s", (rule['root_unit_id'],)).fetchone()
        if root:
            q += " AND path LIKE %s"; params.append(dict(root)['path'] + '%')
    return {dict(r)['id'] for r in db.execute(q, tuple(params)).fetchall()}


def applicable_units(policy_id):
    rules = [dict(r) for r in get_db().execute(
        "SELECT * FROM policy_applicability WHERE policy_id=%s", (policy_id,)).fetchall()]
    inc, exc = set(), set()
    for r in rules:
        (exc if r['is_exclusion'] else inc).update(_expand(r))
    return inc - exc          # exclusions always win


def applies_to_user(policy_id, user_id):
    row = get_db().execute("SELECT org_unit_id, role FROM users WHERE id=%s", (user_id,)).fetchone()
    if not row:
        return False
    row = dict(row)
    if (row.get('role') or '') in ('admin', 'superadmin'):
        return True
    return row['org_unit_id'] in applicable_units(policy_id)


def describe_applicability(policy_id):
    rows = [dict(r) for r in get_db().execute(
        """SELECT a.*, o.name_en AS unit_name, ro.name_en AS root_name, t.name_en AS type_name
           FROM policy_applicability a
           LEFT JOIN org_units o  ON o.id  = a.org_unit_id
           LEFT JOIN org_units ro ON ro.id = a.root_unit_id
           LEFT JOIN org_unit_types t ON t.id = a.match_type_id
           WHERE a.policy_id=%s ORDER BY a.is_exclusion, a.id""", (policy_id,)).fetchall()]
    out = []
    for r in rows:
        if r['unit_name']:
            s = r['unit_name'] + (' and everything below it' if r['include_descendants'] else ' only')
        elif r['match_code']:
            s = f"every unit coded {r['match_code']}" + (f" within {r['root_name']}" if r['root_name'] else '')
        elif r['type_name']:
            s = f"every {r['type_name']}" + (f" within {r['root_name']}" if r['root_name'] else '')
        else:
            continue
        out.append(('Except: ' if r['is_exclusion'] else '') + s)
    return out


def set_applicability(policy_id, entries, user_id=None):
    """Replace the matrix wholesale. Editing applicability is infrequent and a
    partial update is far easier to get wrong than a replace."""
    db = get_db()
    db.execute("DELETE FROM policy_applicability WHERE policy_id=%s", (policy_id,))
    for e in entries:
        db.execute("""INSERT INTO policy_applicability
                        (policy_id, org_unit_id, include_descendants, is_exclusion,
                         match_code, match_type_id, root_unit_id, created_by)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (policy_id, e.get('org_unit_id'), e.get('include_descendants', True),
                    e.get('is_exclusion', False), e.get('match_code'),
                    e.get('match_type_id'), e.get('root_unit_id'), user_id))
    db.commit()


# ----------------------------------------------------------------- workflows
def get_workflow_for(document_type_id, org_unit_id=None):
    """A unit-specific workflow wins over the type-wide default, so one company
    can differ without forking the whole set."""
    db = get_db()
    if org_unit_id:
        r = db.execute("""SELECT * FROM approval_workflows
                          WHERE document_type_id=%s AND org_unit_id=%s AND is_active
                          ORDER BY id LIMIT 1""", (document_type_id, org_unit_id)).fetchone()
        if r:
            return dict(r)
    r = db.execute("""SELECT * FROM approval_workflows
                      WHERE document_type_id=%s AND org_unit_id IS NULL AND is_active
                      ORDER BY is_default DESC, id LIMIT 1""", (document_type_id,)).fetchone()
    return dict(r) if r else None


def get_stages(workflow_id, enabled_only=True):
    q = "SELECT * FROM approval_workflow_stages WHERE workflow_id=%s "
    if enabled_only:
        q += "AND is_enabled "
    q += "ORDER BY stage_order"
    return [dict(r) for r in get_db().execute(q, (workflow_id,)).fetchall()]


def _resolve_approver(stage, policy_org_unit_id):
    """Turn a stage definition into an actual user id at instantiation time."""
    db = get_db()
    mode = stage['approver_mode']
    if mode == 'user':
        return stage['approver_user_id']
    if mode == 'org_unit_head' and policy_org_unit_id:
        r = db.execute("SELECT head_user_id FROM org_units WHERE id=%s", (policy_org_unit_id,)).fetchone()
        if r and dict(r)['head_user_id']:
            return dict(r)['head_user_id']
        # No head set: leave unassigned rather than silently escalating to
        # someone who was never nominated. The UI shows it as unassigned.
        return None
    if mode == 'parent_unit_head' and policy_org_unit_id:
        r = db.execute("""SELECT p.head_user_id FROM org_units c
                          JOIN org_units p ON p.id = c.parent_id WHERE c.id=%s""",
                       (policy_org_unit_id,)).fetchone()
        return dict(r)['head_user_id'] if r else None
    if mode == 'role' and stage['approver_role']:
        r = db.execute("SELECT id FROM users WHERE role=%s AND is_active=1 ORDER BY id LIMIT 1",
                       (stage['approver_role'],)).fetchone()
        return dict(r)['id'] if r else None
    return None


def instantiate_workflow(policy_id, document_type_id, org_unit_id=None, force=False):
    """Snapshot the workflow onto a document.

    Snapshot, not a live reference: editing a workflow template later must not
    rewrite the approval history of documents already in flight. For a
    regulated environment an audit trail that changes retroactively is worse
    than no audit trail.
    """
    db = get_db()
    if not force:
        n = dict(db.execute("SELECT count(*) AS c FROM document_approvals WHERE policy_id=%s",
                            (policy_id,)).fetchone())['c']
        if n:
            return 0
    wf = get_workflow_for(document_type_id, org_unit_id)
    if not wf:
        return 0
    db.execute("DELETE FROM document_approvals WHERE policy_id=%s", (policy_id,))
    created = 0
    for i, st in enumerate(get_stages(wf['id']), start=1):
        db.execute("""INSERT INTO document_approvals
                        (policy_id, workflow_id, stage_order, stage_name,
                         approver_user_id, approver_role, status, sla_due_at)
                      VALUES (%s,%s,%s,%s,%s,%s,'pending',
                              NOW() + (%s || ' days')::interval)""",
                   (policy_id, wf['id'], i, st['stage_name'],
                    _resolve_approver(st, org_unit_id), st['approver_role'],
                    st['sla_days'] or 7))
        created += 1
    db.commit()
    return created


def approval_state(policy_id):
    rows = [dict(r) for r in get_db().execute(
        """SELECT a.*, u.first_name, u.last_name, u.email
           FROM document_approvals a
           LEFT JOIN users u ON u.id = a.approver_user_id
           WHERE a.policy_id=%s ORDER BY a.stage_order""", (policy_id,)).fetchall()]
    current = next((r for r in rows if r['status'] == 'pending'), None)
    return {
        'stages': rows,
        'current': current,
        'complete': bool(rows) and all(r['status'] in ('approved', 'skipped') for r in rows),
        'rejected': any(r['status'] == 'rejected' for r in rows),
    }


def decide(policy_id, stage_order, decision, user_id, comments=None):
    """Record one approval decision.

    Stages are sequential: a later stage cannot be actioned while an earlier one
    is still pending, or the chain means nothing.
    """
    db = get_db()
    earlier = dict(db.execute(
        """SELECT count(*) AS c FROM document_approvals
           WHERE policy_id=%s AND stage_order < %s AND status = 'pending'""",
        (policy_id, stage_order)).fetchone())['c']
    if earlier:
        return False, 'An earlier stage is still awaiting a decision.'

    db.execute("""UPDATE document_approvals
                     SET status=%s, decision_at=NOW(), decided_by=%s, comments=%s
                   WHERE policy_id=%s AND stage_order=%s""",
               (decision, user_id, comments, policy_id, stage_order))

    if decision == 'rejected':
        db.execute("""UPDATE document_approvals SET status='skipped'
                       WHERE policy_id=%s AND stage_order > %s AND status='pending'""",
                   (policy_id, stage_order))
        db.execute("UPDATE policies SET status='Rejected' WHERE id=%s", (policy_id,))
    else:
        st = approval_state(policy_id)
        if st['complete']:
            db.execute("UPDATE policies SET status='Approved', approval_date=%s, approved_by=%s "
                       "WHERE id=%s",
                       (__import__('datetime').date.today().isoformat(), user_id, policy_id))
    db.commit()
    return True, 'Decision recorded.'
