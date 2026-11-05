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
STR / SAR draft for the financial intelligence unit (F5).

Builds a draft report from one case of the STR register: the reporting
subject, the relationship, the grounds of suspicion, the screening hits,
alerts and transactions linked to the case, the hit escalation log and the
investigation. The analyst completes the narrative (each save is a new
version, kept); the draft never files anything: the MLRO decides on the case
page (aml.sar_detail) whether the unit is notified, and the filing is
recorded there. The unit's own form, when the sector has one, is linked from
str_report_templates.
"""
import json

from database.db import get_db
from . import escalation_log as EL
from . import str_register as SR

EDITABLE = ('grounds', 'actions_taken', 'narrative')


class DraftError(ValueError):
    pass


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def facts(sar_id, db=None):
    """Everything the draft states, read from the register (no free text added)."""
    db = db or get_db()
    case = SR.get_case(db, sar_id)
    cust = None
    if case.get('customer_id'):
        r = db.execute("SELECT * FROM customers WHERE id = %s", (case['customer_id'],)).fetchone()
        cust = dict(r) if r else None
    links = SR.case_links(db, sar_id, include_removed=False)
    tx_ids = [l['target_id'] for l in links if l['link_type'] == 'transaction']
    txs = _rows(db, """SELECT id, transaction_reference, transaction_date, amount, currency, transaction_type,
                              counterparty_name, counterparty_country FROM transactions WHERE id = ANY(%s)
                       ORDER BY transaction_date""", (tx_ids,)) if tx_ids else []
    hit_ids = [l['target_id'] for l in links if l['link_type'] == 'screening_hit']
    hits = _rows(db, """SELECT q.id, q.match_name, q.list_source, q.match_score, q.status, q.resolution,
                               h.screening_date FROM screening_queue q
                          LEFT JOIN screening_history h ON h.id = q.screening_history_id
                         WHERE q.id = ANY(%s)""", (hit_ids,)) if hit_ids else []
    alert_ids = [l['target_id'] for l in links if l['link_type'] == 'screening_alert']
    hits += [{'id': a['id'], 'match_name': a['matched_name'], 'list_source': a['source_list'],
              'match_score': a['match_score'], 'status': a['alert_status'], 'resolution': a.get('resolution_notes'),
              'screening_date': a['created_at']}
             for a in (_rows(db, "SELECT * FROM aml_alerts WHERE id = ANY(%s)", (alert_ids,)) if alert_ids else [])]
    tm_ids = [l['target_id'] for l in links if l['link_type'] == 'tm_alert']
    tms = _rows(db, """SELECT id, alert_reference, alert_severity, status, alert_date FROM tm_alerts
                        WHERE id = ANY(%s)""", (tm_ids,)) if tm_ids else []
    escalations = EL.entries(db, sar_id=sar_id)
    templates = _rows(db, """SELECT name_en, name_ar, template_url FROM str_report_templates
                              WHERE is_active ORDER BY sort_order""") if _has_templates(db) else []
    return {'case': case, 'customer': cust, 'transactions': txs, 'hits': hits, 'tm_alerts': tms,
            'escalations': escalations, 'templates': templates,
            'total_amount': sum(float(t.get('amount') or 0) for t in txs)}


def _has_templates(db):
    r = db.execute("SELECT to_regclass('public.str_report_templates') AS t").fetchone()
    return bool(r and r['t'])


def default_text(f):
    """Starting text of the editable parts, from the case itself."""
    c = f['case']
    grounds = (c.get('activity_description') or '').strip()
    if c.get('red_flags_identified'):
        grounds += '\n\n' + c['red_flags_identified'].strip()
    actions = []
    for z in f.get('escalations') or []:
        esc, rep = EL.parse_dt(z.get('escalated_at')), EL.parse_dt(z.get('reported_at'))
        if esc:
            actions.append(f"Screening hit {z.get('reference') or ''} escalated to the MLRO on {esc:%Y-%m-%d %H:%M}.")
        if rep:
            actions.append(f"Reported to {z.get('reported_to') or 'the authority'} on {rep:%Y-%m-%d %H:%M}"
                           + (f" (reference {z['report_reference']})." if z.get('report_reference') else '.'))
    return {'grounds': grounds, 'actions_taken': '\n'.join(actions),
            'narrative': (c.get('investigation_findings') or '').strip()}


def can_see(case, user, is_mlro):
    """The draft is confidential (tipping-off): the MLRO, the analyst assigned to
    the case and the person who reported it."""
    if is_mlro:
        return True
    uid = getattr(user, 'id', None)
    return uid is not None and uid in (case.get('assigned_to'), case.get('reported_by'))


def latest(sar_id, db=None):
    db = db or get_db()
    r = db.execute("""SELECT d.*, trim(coalesce(u.first_name, '') || ' ' || coalesce(u.last_name, '')) AS by_name
                        FROM aml_sar_drafts d LEFT JOIN users u ON u.id = d.created_by
                       WHERE d.sar_id = %s ORDER BY d.version DESC LIMIT 1""", (sar_id,)).fetchone()
    if not r:
        return None
    r = dict(r)
    if not isinstance(r['content'], dict):
        r['content'] = json.loads(r['content'])
    return r


def versions(sar_id, db=None):
    db = db or get_db()
    return _rows(db, """SELECT d.version, d.created_at, trim(coalesce(u.first_name, '') || ' ' || coalesce(u.last_name, ''))
                               AS by_name FROM aml_sar_drafts d LEFT JOIN users u ON u.id = d.created_by
                         WHERE d.sar_id = %s ORDER BY d.version DESC""", (sar_id,))


def save(sar_id, form, user_id, db=None):
    """Store a new version of the editable text. Returns the version number."""
    db = db or get_db()
    case = SR.get_case(db, sar_id)
    if (case.get('investigation_status') or 'NEW') in SR.CLOSED_STATUSES and case.get('investigation_status') != 'FILED':
        raise DraftError('This case is closed without a report; there is no draft to keep.')
    if case.get('investigation_status') == 'FILED':
        raise DraftError('The report is filed; the draft can no longer change.')
    content = {k: (form.get(k) or '').strip()[:20000] for k in EDITABLE}
    if len(content['grounds']) < 30:
        raise DraftError('Write the grounds of suspicion (at least 30 characters).')
    prev = latest(sar_id, db)
    if prev and prev['content'] == content:
        return prev['version']
    v = (prev['version'] if prev else 0) + 1
    try:
        db.execute("INSERT INTO aml_sar_drafts (sar_id, version, content, created_by) VALUES (%s,%s,%s,%s)",
                   (sar_id, v, json.dumps(content, ensure_ascii=False), user_id))
        db.commit()
    except Exception as ex:
        import psycopg2
        if not isinstance(ex, psycopg2.IntegrityError):
            raise
        db.rollback()          # two saves at the same moment: UNIQUE (sar_id, version)
        raise DraftError('Someone saved the draft at the same time; reload the page and try again.')
    SR._audit(user_id, sar_id, f'SAR {case["sar_reference"]}: STR draft version {v} saved')
    return v
