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
Inspection readiness: scores per area / framework, gaps, evidence and
findings status, trend snapshots, the unified regulatory calendar with
reminders, and the per-area inspection evidence pack (ZIP).
"""

import csv
import io
import json
import os
import zipfile
from datetime import date, datetime, timedelta

from flask import current_app

from database.db import get_db

from . import catalog
from . import evidence as evidence_svc
from . import findings as findings_svc
from . import readiness_logic as RL


def _rows(db, sql, args=()):
    try:
        return [dict(r) for r in db.execute(sql, args).fetchall()]
    except Exception:
        db.rollback()
        return []


def controls(db=None, framework_id=None, area=None):
    db = db or get_db()
    sql = "SELECT c.* FROM rc_controls c WHERE c.is_active"
    args = []
    if framework_id:
        sql += """ AND c.id IN (SELECT cr.control_id FROM rc_control_requirements cr JOIN rc_requirements q
                   ON q.id = cr.requirement_id WHERE q.framework_id = %s)"""
        args.append(framework_id)
    if area:
        sql += " AND c.area = %s"
        args.append(area)
    return _rows(db, sql + " ORDER BY c.control_code", tuple(args))


def area_labels(db=None):
    try:
        return catalog.ref_labels('areas', db=db)
    except Exception:
        return {}


def overview(framework_id=None, db=None):
    db = db or get_db()
    cs = controls(db, framework_id)
    overall = RL.score(cs)
    areas = RL.by_area(cs)
    open_f = findings_svc.list_findings(status='open', db=db)
    ev = evidence_svc.list_all(db=db)
    risks = _rows(db, """SELECT r.id, r.risk_id, r.risk_title, r.residual_risk_score, r.inherent_risk_score, c.category_code
                         FROM risks r LEFT JOIN risk_categories c ON c.id = r.category_id WHERE r.status = 'ACTIVE'
                         ORDER BY COALESCE(r.residual_risk_score, r.inherent_risk_score) DESC NULLS LAST LIMIT 5""")
    area_list = sorted(areas.items(), key=lambda kv: (kv[1]['score'] is None, kv[1]['score'] or 0))
    return {'overall': overall, 'band': RL.band(overall['score']), 'areas': areas, 'area_list': area_list, 'labels': area_labels(db),
            'gaps': RL.top_gaps(cs, 12), 'controls': cs,
            'expiring': [e for e in ev if e['state'] in ('expiring', 'expired')][:12],
            'open_findings': open_f, 'ageing': findings_svc.ageing_summary(open_f),
            'repeated': [f for f in open_f if f.get('is_repeated')], 'risks': risks,
            'trend': trend(framework_id, db=db),
            'frameworks': [dict(fw, s=RL.score(controls(db, fw['id']))) for fw in catalog.frameworks(active_only=True, db=db)]}


def trend(framework_id=None, area=None, days=180, db=None):
    db = db or get_db()
    return _rows(db, """SELECT snapshot_date, score, failing, open_findings FROM rc_readiness_snapshots
                        WHERE COALESCE(framework_id, 0) = %s AND COALESCE(area_code, '') = %s AND snapshot_date >= %s
                        ORDER BY snapshot_date""", (framework_id or 0, area or '', date.today() - timedelta(days=days)))


def snapshot(db=None, on=None):
    """Store today's scores (overall, per area, per framework). Idempotent per day."""
    db = db or get_db()
    on = on or date.today()
    open_n = len(findings_svc.list_findings(status='open', db=db))
    rows = []
    cs = controls(db)
    rows.append((None, None, RL.score(cs)))
    for a, s in RL.by_area(cs).items():
        rows.append((None, a, s))
    for fw in catalog.frameworks(active_only=True, db=db):
        rows.append((fw['id'], None, RL.score(controls(db, fw['id']))))
    for fw_id, area, s in rows:
        db.execute("""INSERT INTO rc_readiness_snapshots (snapshot_date, framework_id, area_code, score, controls, failing,
                      open_findings, details) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (snapshot_date, COALESCE(framework_id, 0), COALESCE(area_code, ''))
                      DO UPDATE SET score = EXCLUDED.score, controls = EXCLUDED.controls, failing = EXCLUDED.failing,
                      open_findings = EXCLUDED.open_findings, details = EXCLUDED.details""",
                   (on, fw_id, area, s['score'], s['controls'], s['failing'], open_n, json.dumps(s['by_status'])))
    db.commit()
    return len(rows)


# ------------------------------------------------------------------ regulatory calendar
def calendar_items(start=None, end=None, db=None):
    """Every dated obligation from the modules that hold them, newest data wins:
    report submissions (or projected from the report schedule), regulatory
    deadlines, offset deadlines, evidence expiry, findings and action plans."""
    db = db or get_db()
    start = start or date.today() - timedelta(days=30)
    end = end or date.today() + timedelta(days=180)
    items = []
    subs = _rows(db, """SELECT s.id, s.due_date, s.status, r.id AS report_id, r.report_code, r.report_name
                        FROM regulatory_report_submissions s JOIN regulatory_reports r ON r.id = s.report_id
                        WHERE s.due_date BETWEEN %s AND %s AND COALESCE(s.status, 'pending') NOT IN ('submitted', 'approved')""",
                     (start, end))
    have = {(s['report_id'], s['due_date']) for s in subs}
    for s in subs:
        items.append({'key': f"sub:{s['id']}", 'date': s['due_date'], 'kind': 'submission', 'title': f"{s['report_code']} — {s['report_name']}",
                      'status': s['status'] or 'pending', 'link': f"/reporting/submission/{s['id']}", 'owner': None})
    for r in _rows(db, "SELECT * FROM regulatory_reports WHERE CAST(is_active AS INTEGER) = 1"):
        for d in RL.occurrences(r.get('frequency'), r.get('due_day'), r.get('due_month'), max(start, date.today()), end):
            if (r['id'], d) not in have:
                items.append({'key': f"rep:{r['id']}:{d}", 'date': d, 'kind': 'submission',
                              'title': f"{r['report_code']} — {r['report_name']}", 'status': 'scheduled',
                              'link': '/reporting/', 'owner': None})
    for d in _rows(db, "SELECT * FROM pr_deadlines WHERE status = 'open' AND due_date <= %s", (end,)):
        items.append({'key': f"dl:{d['id']}", 'date': d['due_date'], 'kind': 'deadline', 'title': d['title'],
                      'status': 'overdue' if d['due_date'] < date.today() else 'open',
                      'link': f"/prudential/deadlines/{d['id']}", 'owner': d.get('owner_user_id')})
    for o in _rows(db, "SELECT * FROM carbon_offset_obligations WHERE status <> 'FULFILLED' AND deadline_date <= %s", (end,)):
        items.append({'key': f"off:{o['id']}", 'date': o['deadline_date'], 'kind': 'offsets',
                      'title': f"Carbon offsets: {o['required_tco2e']} tCO2e", 'status': o['status'],
                      'link': '/carbon/fra', 'owner': o.get('created_by')})
    for e in _rows(db, """SELECT e.id, e.title, e.valid_to, c.control_code, c.owner_user_id FROM rc_evidence e
                          JOIN rc_controls c ON c.id = e.control_id
                          WHERE e.valid_to BETWEEN %s AND %s AND e.status = 'approved'""", (start, end)):
        items.append({'key': f"ev:{e['id']}", 'date': e['valid_to'], 'kind': 'evidence', 'title': f"{e['control_code']}: {e['title']} expires",
                      'status': 'expired' if e['valid_to'] < date.today() else 'valid',
                      'link': f"/regcontrols/evidence/{e['id']}", 'owner': e.get('owner_user_id')})
    for f in _rows(db, """SELECT id, reference, title, due_date, owner_user_id FROM rc_findings
                          WHERE status <> 'closed' AND due_date IS NOT NULL AND due_date <= %s""", (end,)):
        items.append({'key': f"fd:{f['id']}", 'date': f['due_date'], 'kind': 'finding', 'title': f"{f['reference']}: {f['title']}",
                      'status': 'overdue' if f['due_date'] < date.today() else 'open',
                      'link': f"/regcontrols/findings/{f['id']}", 'owner': f.get('owner_user_id')})
    for a in _rows(db, """SELECT a.id, a.description, a.due_date, a.owner_user_id, f.reference, f.id AS finding_id
                          FROM rc_corrective_actions a JOIN rc_findings f ON f.id = a.finding_id
                          WHERE a.status NOT IN ('done', 'cancelled') AND a.due_date IS NOT NULL AND a.due_date <= %s""", (end,)):
        items.append({'key': f"ca:{a['id']}", 'date': a['due_date'], 'kind': 'action', 'title': f"{a['reference']}: {a['description']}",
                      'status': 'overdue' if a['due_date'] < date.today() else 'open',
                      'link': f"/regcontrols/findings/{a['finding_id']}", 'owner': a.get('owner_user_id')})
    return sorted(items, key=lambda i: (i['date'], i['kind']))


def calendar_sweep(db=None, today=None):
    """Reminders N days before each dated obligation (rc.calendar_reminder_days)."""
    db = db or get_db()
    today = today or date.today()
    from .alerts import compliance_heads
    from .params import get_param
    try:
        days = [int(x) for x in (get_param('rc.calendar_reminder_days', default=[14, 3, 0]) or [])]
    except Exception:
        days = [14, 3, 0]
    from services.notification_service import notify
    sent = 0
    heads = compliance_heads(db)
    for it in calendar_items(today - timedelta(days=1), today + timedelta(days=max(days or [0]) + 1), db):
        done = {r['days_before'] for r in _rows(db, "SELECT days_before FROM rc_calendar_reminders WHERE item_key = %s",
                                                (it['key'],))}
        due = RL.reminders_due(it['date'], today, days, done)
        if not due:
            continue
        left = (it['date'] - today).days
        notify([it['owner'], *heads], 'Regulatory calendar',
               f"{it['title']} — due {it['date']} ({left} day(s))", link=it['link'], category='warning',
               channels=('inapp', 'email'))
        for d in due:
            db.execute("INSERT INTO rc_calendar_reminders (item_key, days_before) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                       (it['key'], d))
        db.commit()
        sent += 1
    return {'reminders': sent}


# ------------------------------------------------------------------ evidence pack
def runs_csv(control_ids, db=None):
    db = db or get_db()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['control', 'started_at', 'triggered_by', 'status', 'affected', 'summary'])
    for r in _rows(db, """SELECT c.control_code, r.started_at, r.triggered_by, r.status, r.affected_count, r.summary
                          FROM rc_control_runs r JOIN rc_controls c ON c.id = r.control_id
                          WHERE r.control_id = ANY(%s) ORDER BY c.control_code, r.started_at DESC""", (list(control_ids),)):
        w.writerow([r['control_code'], r['started_at'], r['triggered_by'], r['status'], r['affected_count'], r['summary']])
    return buf.getvalue()


def evidence_pack(area=None, framework_id=None, index_pdf=None, db=None):
    """ZIP: index.pdf (passed in, rendered by the caller), controls.csv, run_history.csv,
    evidence/<control>/<file>. Missing files are listed in missing_files.txt."""
    db = db or get_db()
    cs = controls(db, framework_id, area)
    ids = [c['id'] for c in cs]
    buf = io.BytesIO()
    missing = []
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        if index_pdf:
            z.writestr('index.pdf', index_pdf)
        cbuf = io.StringIO()
        w = csv.writer(cbuf)
        w.writerow(['control', 'title', 'area', 'criticality', 'last_status', 'last_run_at', 'check_key'])
        for c in cs:
            w.writerow([c['control_code'], c['title_en'], c['area'], c['criticality'], c.get('last_status'),
                        c.get('last_run_at'), c.get('check_key')])
        z.writestr('controls.csv', cbuf.getvalue())
        z.writestr('run_history.csv', runs_csv(ids, db) if ids else '')
        files = _rows(db, """SELECT g.filename, g.file_path, c.control_code, e.title FROM generic_attachments g
                             JOIN rc_evidence e ON e.id = g.record_id JOIN rc_controls c ON c.id = e.control_id
                             WHERE g.module = 'regcontrols' AND g.record_type = 'rc_evidence'
                               AND COALESCE(g.is_deleted, 0) = 0 AND e.control_id = ANY(%s)""", (ids,)) if ids else []
        root = current_app.root_path
        for f in files:
            src = os.path.realpath(os.path.join(root, f['file_path'] or ''))
            if src.startswith(os.path.realpath(root) + os.sep) and os.path.isfile(src):
                z.write(src, f"evidence/{f['control_code']}/{os.path.basename(f['filename'] or src)}")
            else:
                missing.append(f"{f['control_code']}: {f['filename']}")
        if missing:
            z.writestr('missing_files.txt', '\n'.join(missing))
    return buf.getvalue(), cs, len(files) - len(missing), missing
