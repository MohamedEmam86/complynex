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
Playbook instantiation: a confirmed playbook becomes a finding (source
self_identified, titled "[Playbook] …") with one corrective action per step
(evidence, approvals, tasks) due relative to the start date, linked to the
steps' controls — all through the regcontrols API. Nothing is created
before the user confirms.
"""

import json
from datetime import date, timedelta

from database.db import get_db

from . import catalog

STEP_PREFIX = {'evidence': ('Evidence', 'دليل'), 'approval': ('Approval', 'اعتماد'), 'task': ('Task', 'مهمة'),
               'control': ('Control test', 'اختبار ضابط')}


def missing_params(pb, params):
    return [p['key'] for p in pb.get('parameters') or [] if p.get('required') and not (params.get(p['key']) or '').strip()]


def preview(pb, params, start=None):
    start = start or date.today()
    out = []
    for s in pb['steps']:
        out.append({'step_key': s['step_key'], 'type': s['step_type'], 'title_en': s['title_en'], 'title_ar': s.get('title_ar'),
                    'control_code': s.get('control_code'), 'owner_role': s.get('owner_role'),
                    'due_date': (start + timedelta(days=int(s['due_days']))).isoformat()})
    return out


def title_for(pb, params):
    label = next((params.get(p['key']) for p in pb.get('parameters') or [] if params.get(p['key'])), '')
    return f"[Playbook] {pb['name_en']}" + (f" — {label}" if label else '')


def instantiate(code, params, user_id, start=None, suggestion_id=None, source_ref=None, db=None):
    """Create the finding + actions. Returns {'run_id', 'finding_id', 'actions'}. Raises ValueError."""
    from regcontrols.api import raise_finding
    from regcontrols.findings import add_action
    db = db or get_db()
    pb = catalog.playbook(code, db)
    if not pb or not pb['is_active']:
        raise ValueError('unknown playbook')
    miss = missing_params(pb, params)
    if miss:
        raise ValueError('missing: ' + ', '.join(miss))
    start = start or date.today()
    steps = preview(pb, params, start)
    known = {r['control_code'] for r in db.execute("SELECT control_code FROM rc_controls WHERE is_active").fetchall()}
    codes = sorted({s['control_code'] for s in steps if s['control_code'] and s['control_code'] in known})
    desc = '\n'.join([pb.get('description') or '', ''] + [f"{p['label_en']}: {params.get(p['key'])}" for p in pb.get('parameters') or []
                                                           if params.get(p['key'])])
    last = max([s['due_date'] for s in steps] or [start.isoformat()])
    fid = raise_finding(title_for(pb, params)[:390], source='self_identified', severity=pb.get('severity') or 'medium',
                        description=desc, source_ref=source_ref or f"playbook:{code}:{json.dumps(params, sort_keys=True)}"[:190],
                        control_codes=codes or None, owner_user_id=user_id, due_date=date.fromisoformat(last),
                        created_by=user_id, dedupe=True, db=db)
    existing = {r['description'] for r in db.execute("SELECT description FROM rc_corrective_actions WHERE finding_id = %s",
                                                      (fid,)).fetchall()}
    n = 0
    for s in steps:
        en, _ar = STEP_PREFIX.get(s['type'], ('Task', ''))
        text = f"{en}: {s['title_en']}" + (f" [{s['control_code']}]" if s['control_code'] else '') + \
            (f" — owner: {s['owner_role']}" if s['owner_role'] else '')
        if text in existing:
            continue
        add_action(fid, text, due_date=date.fromisoformat(s['due_date']), created_by=user_id, db=db)
        n += 1
    rid = db.execute("""INSERT INTO ai_playbook_runs (playbook_code, title, params, start_date, finding_id, suggestion_id, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (code, title_for(pb, params)[:290], json.dumps(params, ensure_ascii=False), start, fid, suggestion_id,
                      user_id)).fetchone()['id']
    db.commit()
    return {'run_id': rid, 'finding_id': fid, 'actions': n, 'controls': codes}


def runs(db=None, limit=50):
    db = db or get_db()
    return [dict(r) for r in db.execute("""SELECT r.*, f.reference, f.status AS finding_status FROM ai_playbook_runs r
                                           LEFT JOIN rc_findings f ON f.id = r.finding_id ORDER BY r.id DESC LIMIT %s""",
                                        (limit,)).fetchall()]
