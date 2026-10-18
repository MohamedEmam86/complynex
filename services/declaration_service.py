# =============================================================================
# ComplyNex — annual declaration campaigns (Phase 5): GHE / COI / COBEC
#
# Targets are resolved from the org tree, so "run COI for all of Company B" is
# one selection rather than a hand-built list that goes stale the moment
# somebody joins.
# =============================================================================
from datetime import datetime, date

from database.db import get_db
from services.notification_service import notify, delivery_status

MODULES = {
    'ghe':   {'label': 'Gifts & Hospitality', 'table': 'ghe_declarations',   'user_col': 'employee_id'},
    'coi':   {'label': 'Conflict of Interest','table': 'coi_declarations',   'user_col': 'employee_id'},
    'cobec': {'label': 'Code of Business Ethics','table': 'cobec_declarations','user_col': 'employee_id'},
}


def _unit_ids(unit_id, include_descendants=True):
    db = get_db()
    if not unit_id:
        return None
    if not include_descendants:
        return [unit_id]
    r = db.execute("SELECT path FROM org_units WHERE id=%s", (unit_id,)).fetchone()
    if not r:
        return [unit_id]
    return [dict(x)['id'] for x in db.execute(
        "SELECT id FROM org_units WHERE path LIKE %s", (dict(r)['path'] + '%',)).fetchall()]


def create_campaign(module, name, cycle_year, due_at, org_scope_unit_id=None,
                    include_descendants=True, opens_at=None, created_by=None):
    if module not in MODULES:
        return None, f'Unknown module: {module}'
    db = get_db()
    row = db.execute("""INSERT INTO declaration_campaigns
                          (module, name, cycle_year, opens_at, due_at,
                           org_scope_unit_id, include_descendants, status, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING id""",
                     (module, name, cycle_year, opens_at or date.today(), due_at,
                      org_scope_unit_id, include_descendants, created_by)).fetchone()
    db.commit()
    cid = dict(row)['id']
    n = refresh_targets(cid)
    return cid, f'Campaign created with {n} participants.'


def refresh_targets(campaign_id):
    """Recompute who is in scope. Safe to re-run — existing submissions keep
    their status, and joiners are picked up."""
    db = get_db()
    c = db.execute("SELECT * FROM declaration_campaigns WHERE id=%s", (campaign_id,)).fetchone()
    if not c:
        return 0
    c = dict(c)
    units = _unit_ids(c['org_scope_unit_id'], c['include_descendants'])

    if units:
        users = db.execute("SELECT id FROM users WHERE is_active=1 AND org_unit_id = ANY(%s)",
                           (units,)).fetchall()
    else:
        users = db.execute("SELECT id FROM users WHERE is_active=1").fetchall()

    added = 0
    for u in users:
        uid = dict(u)['id']
        exists = db.execute("SELECT 1 FROM declaration_campaign_targets "
                            "WHERE campaign_id=%s AND user_id=%s", (campaign_id, uid)).fetchone()
        if not exists:
            db.execute("INSERT INTO declaration_campaign_targets (campaign_id, user_id) "
                       "VALUES (%s,%s)", (campaign_id, uid))
            added += 1
    db.commit()
    sync_submissions(campaign_id)
    return added


def sync_submissions(campaign_id):
    """Mark who has actually declared.

    Reads the module's own table rather than trusting a flag, so the dashboard
    cannot drift away from the underlying records.
    """
    db = get_db()
    c = db.execute("SELECT * FROM declaration_campaigns WHERE id=%s", (campaign_id,)).fetchone()
    if not c:
        return 0
    c = dict(c)
    meta = MODULES[c['module']]

    try:
        rows = db.execute(
            f"SELECT {meta['user_col']} AS uid, MAX(id) AS did FROM {meta['table']} "
            f"WHERE {meta['user_col']} IS NOT NULL GROUP BY {meta['user_col']}").fetchall()
    except Exception:
        return 0

    submitted = {dict(r)['uid']: dict(r)['did'] for r in rows}
    updated = 0
    for uid, did in submitted.items():
        n = db.execute("""UPDATE declaration_campaign_targets
                             SET status='submitted', submitted_at=COALESCE(submitted_at, NOW()),
                                 declaration_id=%s
                           WHERE campaign_id=%s AND user_id=%s AND status <> 'submitted'""",
                       (did, campaign_id, uid))
        updated += 1

    # Overdue is derived, never stored ahead of time.
    if c['due_at'] and c['due_at'] < date.today():
        db.execute("""UPDATE declaration_campaign_targets SET status='overdue'
                       WHERE campaign_id=%s AND status='pending'""", (campaign_id,))
    db.commit()
    return updated


def stats(campaign_id):
    db = get_db()
    rows = db.execute("""SELECT status, count(*) AS c FROM declaration_campaign_targets
                         WHERE campaign_id=%s GROUP BY status""", (campaign_id,)).fetchall()
    d = {dict(r)['status']: dict(r)['c'] for r in rows}
    total = sum(d.values())
    submitted = d.get('submitted', 0)
    counted = total - d.get('exempt', 0)
    return {
        'total': total,
        'submitted': submitted,
        'pending': d.get('pending', 0),
        'overdue': d.get('overdue', 0),
        'exempt': d.get('exempt', 0),
        'completion_pct': round(submitted * 100.0 / counted, 1) if counted else 0.0,
    }


def participants(campaign_id, status=None):
    q = """SELECT t.*, u.first_name, u.last_name, u.email, u.employee_id, u.job_title,
                  o.name_en AS unit_name, o.code AS unit_code,
                  co.name_en AS company_name, bu.name_en AS business_unit
           FROM declaration_campaign_targets t
           JOIN users u ON u.id = t.user_id
           LEFT JOIN org_units o  ON o.id = u.org_unit_id
           LEFT JOIN org_units bu ON bu.id = o.parent_id
           LEFT JOIN org_units co ON co.id = bu.parent_id
           WHERE t.campaign_id=%s"""
    params = [campaign_id]
    if status:
        q += " AND t.status=%s"; params.append(status)
    q += " ORDER BY t.status, u.first_name"
    return [dict(r) for r in get_db().execute(q, tuple(params)).fetchall()]


def send_reminders(campaign_id, by_user_id, user_ids=None, message=None):
    """Remind non-submitters. Defaults to everyone outstanding.

    Reports what was actually delivered and by which channel — the Training
    module's version claimed to have emailed people and never did.
    """
    db = get_db()
    c = dict(db.execute("SELECT * FROM declaration_campaigns WHERE id=%s",
                        (campaign_id,)).fetchone())
    meta = MODULES[c['module']]

    if user_ids:
        targets = [t for t in participants(campaign_id) if t['user_id'] in set(user_ids)]
    else:
        targets = [t for t in participants(campaign_id)
                   if t['status'] in ('pending', 'overdue')]
    if not targets:
        return 0, 'Nobody is outstanding — no reminders sent.'

    due = c['due_at'].strftime('%d %b %Y') if c['due_at'] else 'the deadline'
    msg = message or (f"Your {meta['label']} declaration for {c['cycle_year']} "
                      f"is still outstanding. It was due by {due}.")

    ids = [t['user_id'] for t in targets]
    res = notify(ids, f"Reminder: {meta['label']} declaration {c['cycle_year']}",
                 msg, link=f"/{c['module']}/", category='warning')

    for t in targets:
        db.execute("""UPDATE declaration_campaign_targets
                         SET last_reminder_at=NOW(), reminder_count=reminder_count+1
                       WHERE id=%s""", (t['id'],))
    db.execute("""INSERT INTO reminder_log
                    (campaign_id, sent_by, recipients, channel, subject, message, target_filter)
                  VALUES (%s,%s,%s,%s,%s,%s,%s)""",
               (campaign_id, by_user_id, len(targets),
                'inapp+email' if res['email'] else 'inapp',
                f"{meta['label']} reminder", msg,
                'selected' if user_ids else 'all outstanding'))
    db.commit()

    d = delivery_status()
    note = '' if d['email'] else ' (in-app only — email is not configured)'
    return len(targets), f'Reminded {len(targets)} people{note}.'


def reminder_history(campaign_id):
    return [dict(r) for r in get_db().execute(
        """SELECT r.*, u.first_name, u.last_name FROM reminder_log r
           LEFT JOIN users u ON u.id = r.sent_by
           WHERE r.campaign_id=%s ORDER BY r.sent_at DESC""", (campaign_id,)).fetchall()]


def export_rows(campaign_id, which='all'):
    """Flat rows for Excel/CSV, with the org columns the spec asked for."""
    rows = participants(campaign_id)
    if which == 'submitted':
        rows = [r for r in rows if r['status'] == 'submitted']
    elif which == 'not_submitted':
        rows = [r for r in rows if r['status'] in ('pending', 'overdue')]
    out = []
    for r in rows:
        out.append({
            'Employee ID': r.get('employee_id') or '',
            'Name': f"{r.get('first_name') or ''} {r.get('last_name') or ''}".strip(),
            'Email': r.get('email') or '',
            'Job Title': r.get('job_title') or '',
            'Company': r.get('company_name') or '',
            'Business Unit': r.get('business_unit') or '',
            'Department': r.get('unit_name') or '',
            'Status': (r.get('status') or '').title(),
            'Submitted At': r['submitted_at'].strftime('%Y-%m-%d %H:%M') if r.get('submitted_at') else '',
            'Reminders Sent': r.get('reminder_count') or 0,
            'Last Reminder': r['last_reminder_at'].strftime('%Y-%m-%d') if r.get('last_reminder_at') else '',
        })
    return out
