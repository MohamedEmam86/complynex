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
Intent and playbook catalogs (DATA). Installers are idempotent and never
overwrite UI edits; `extend_*` lets a content pack add keywords, examples,
controls or steps to a generic entry.
"""

import json
from datetime import datetime

from database.db import get_db

from . import seed

INTENT_COLS = ('name_en', 'name_ar', 'description', 'keywords', 'examples', 'fields', 'handler', 'handler_params',
               'control_codes', 'owner_role', 'priority', 'deadline_hours', 'is_active')
PLAYBOOK_COLS = ('name_en', 'name_ar', 'description', 'keywords', 'examples', 'parameters', 'severity', 'is_active')
_JSON = ('fields', 'handler_params', 'parameters')


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def _val(col, v):
    if col in _JSON:
        return json.dumps(v if v is not None else ([] if col != 'handler_params' else {}), ensure_ascii=False)
    if col in ('keywords', 'examples', 'control_codes'):
        return list(v or [])
    return v


# ------------------------------------------------------------------ intents
def intents(db=None, active_only=True):
    db = db or get_db()
    return _rows(db, "SELECT * FROM ai_intents" + (" WHERE is_active" if active_only else "") + " ORDER BY code")


def intent(code, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM ai_intents WHERE code = %s", (code,)).fetchone()
    return dict(r) if r else None


def install_intent(d, pack_code=None, db=None):
    db = db or get_db()
    vals = [_val(c, d.get(c, True if c == 'is_active' else ('medium' if c == 'priority' else None)))
            for c in INTENT_COLS]
    vals[INTENT_COLS.index('handler')] = d.get('handler') or 'manual'
    db.execute(f"""INSERT INTO ai_intents (code, {', '.join(INTENT_COLS)}, pack_code)
                   VALUES (%s, {', '.join(['%s'] * len(INTENT_COLS))}, %s) ON CONFLICT (code) DO NOTHING""",
               (d['code'], *vals, pack_code))


def extend_intent(code, keywords=(), examples=(), control_codes=(), db=None):
    """Union-merge pack additions into an existing intent (keeps UI edits)."""
    db = db or get_db()
    db.execute("""UPDATE ai_intents SET
                    keywords = ARRAY(SELECT DISTINCT unnest(keywords || %s::text[])),
                    examples = ARRAY(SELECT DISTINCT unnest(examples || %s::text[])),
                    control_codes = ARRAY(SELECT DISTINCT unnest(control_codes || %s::text[]))
                  WHERE code = %s""", (list(keywords), list(examples), list(control_codes), code))


def save_intent(code, data, user_id, db=None):
    db = db or get_db()
    vals = [_val(c, data.get(c)) for c in INTENT_COLS]
    db.execute(f"""INSERT INTO ai_intents (code, {', '.join(INTENT_COLS)}, updated_by, updated_at)
                   VALUES (%s, {', '.join(['%s'] * len(INTENT_COLS))}, %s, %s)
                   ON CONFLICT (code) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in INTENT_COLS)},
                   updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at""",
               (code, *vals, user_id, datetime.now()))
    db.commit()


# ------------------------------------------------------------------ playbooks
def playbooks(db=None, active_only=True):
    db = db or get_db()
    rows = _rows(db, "SELECT * FROM ai_playbooks" + (" WHERE is_active" if active_only else "") + " ORDER BY code")
    steps = {}
    for s in _rows(db, "SELECT * FROM ai_playbook_steps WHERE is_active ORDER BY seq, id"):
        steps.setdefault(s['playbook_code'], []).append(s)
    for p in rows:
        p['steps'] = steps.get(p['code'], [])
    return rows


def playbook(code, db=None):
    return next((p for p in playbooks(db, active_only=False) if p['code'] == code), None)


def install_playbook(d, pack_code=None, db=None):
    db = db or get_db()
    vals = [_val(c, d.get(c, True if c == 'is_active' else ('medium' if c == 'severity' else None))) for c in PLAYBOOK_COLS]
    db.execute(f"""INSERT INTO ai_playbooks (code, {', '.join(PLAYBOOK_COLS)}, pack_code)
                   VALUES (%s, {', '.join(['%s'] * len(PLAYBOOK_COLS))}, %s) ON CONFLICT (code) DO NOTHING""",
               (d['code'], *vals, pack_code))
    for n, s in enumerate(d.get('steps') or [], start=1):
        install_step(d['code'], s, seq=n * 10, pack_code=pack_code, db=db)


def install_step(playbook_code, s, seq=None, pack_code=None, db=None):
    db = db or get_db()
    db.execute("""INSERT INTO ai_playbook_steps (playbook_code, step_key, seq, step_type, title_en, title_ar, control_code,
                  owner_role, due_days, pack_code) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT (playbook_code, step_key) DO NOTHING""",
               (playbook_code, s['step_key'], s.get('seq', seq or 100), s.get('step_type', 'task'), s['title_en'],
                s.get('title_ar'), s.get('control_code'), s.get('owner_role'), int(s.get('due_days') or 14), pack_code))


def extend_playbook(code, keywords=(), examples=(), db=None):
    db = db or get_db()
    db.execute("""UPDATE ai_playbooks SET keywords = ARRAY(SELECT DISTINCT unnest(keywords || %s::text[])),
                  examples = ARRAY(SELECT DISTINCT unnest(examples || %s::text[])) WHERE code = %s""",
               (list(keywords), list(examples), code))


def save_playbook(code, data, steps, user_id, db=None):
    db = db or get_db()
    vals = [_val(c, data.get(c)) for c in PLAYBOOK_COLS]
    db.execute(f"""INSERT INTO ai_playbooks (code, {', '.join(PLAYBOOK_COLS)}, updated_by, updated_at)
                   VALUES (%s, {', '.join(['%s'] * len(PLAYBOOK_COLS))}, %s, %s)
                   ON CONFLICT (code) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in PLAYBOOK_COLS)},
                   updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at""",
               (code, *vals, user_id, datetime.now()))
    for s in steps:
        db.execute("""INSERT INTO ai_playbook_steps (playbook_code, step_key, seq, step_type, title_en, title_ar, control_code,
                      owner_role, due_days, is_active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (playbook_code, step_key) DO UPDATE SET seq = EXCLUDED.seq, step_type = EXCLUDED.step_type,
                      title_en = EXCLUDED.title_en, title_ar = EXCLUDED.title_ar, control_code = EXCLUDED.control_code,
                      owner_role = EXCLUDED.owner_role, due_days = EXCLUDED.due_days, is_active = EXCLUDED.is_active""",
                   (code, s['step_key'], s['seq'], s['step_type'], s['title_en'], s.get('title_ar'), s.get('control_code') or None,
                    s.get('owner_role') or None, int(s.get('due_days') or 14), s.get('is_active', True)))
    db.commit()


# ------------------------------------------------------------------ seeding
def ensure_seeded(db=None, commit=True):
    """Install the generic catalog the first time the AI layer is used (idempotent)."""
    db = db or get_db()
    for d in seed.INTENTS:
        install_intent(d, db=db)
    for p in seed.PLAYBOOKS:
        install_playbook(p, db=db)
    if commit:
        db.commit()
