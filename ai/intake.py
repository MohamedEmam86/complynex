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
"Submit to Compliance": one intake for text, documents, forwarded alerts or
e-mails and regulatory circulars. The proposal (intent, fields, routing
target, linked controls and requirements, owner role, priority, deadline)
is only a suggestion; records are created when the user confirms.
"""

import json
import logging
from datetime import datetime

from database.db import get_db

from . import audit, catalog, freeze_screening, handlers, tasks

CHANNELS = ('text', 'document', 'email', 'alert', 'circular')
PRIORITIES = ('critical', 'high', 'medium', 'low')

logger = logging.getLogger(__name__)


def create_item(channel, subject, body, user_id, db=None, received_at=None, message_id=None):
    db = db or get_db()
    if channel not in CHANNELS:
        channel = 'text'
    if not (body or '').strip() and not (subject or '').strip():
        raise ValueError('paste the text or upload a document')
    rid = db.execute("""INSERT INTO ai_intake_items (channel, subject, body, created_by, received_at, source_message_id, extraction_method)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (channel, (subject or '')[:290] or None, body, user_id, received_at, (message_id or '')[:300] or None,
                      'text' if (body or '').strip() else None)).fetchone()['id']
    db.commit()
    return rid


def set_extraction(item_id, res, use_text=True, db=None):
    """Record how the uploaded document's text was read (text | pypdf | ocr | none); optionally use it as the body."""
    db = db or get_db()
    if use_text and res.get('text'):
        db.execute("""UPDATE ai_intake_items SET body = %s, channel = CASE WHEN channel = 'text' THEN 'document' ELSE channel END,
                      extraction_method = %s, extraction_note = %s WHERE id = %s""",
                   (res['text'], res['method'], res.get('note'), item_id))
    else:
        db.execute("UPDATE ai_intake_items SET extraction_method = COALESCE(extraction_method, %s), extraction_note = %s WHERE id = %s",
                   (res['method'], res.get('note'), item_id))
    db.commit()


def visible(it, user_id, lvl):
    """Admins see all; users see their own; items from the monitored mailbox (no submitter) are the team's queue."""
    return bool(it) and (lvl >= 3 or it['created_by'] == user_id or (it['created_by'] is None and lvl >= 2))


def item(item_id, db=None):
    db = db or get_db()
    r = db.execute("SELECT * FROM ai_intake_items WHERE id = %s", (item_id,)).fetchone()
    return dict(r) if r else None


def items(db=None, limit=100, user_id=None, include_queue=False):
    db = db or get_db()
    sql = "SELECT i.*, u.first_name || ' ' || u.last_name AS created_by_name FROM ai_intake_items i LEFT JOIN users u ON u.id = i.created_by"
    args = []
    if user_id:
        sql += " WHERE (i.created_by = %s" + (" OR i.created_by IS NULL)" if include_queue else ")")
        args.append(user_id)
    return [dict(r) for r in db.execute(sql + " ORDER BY i.id DESC LIMIT %s", (*args, limit)).fetchall()]


def _requirements(control_codes, db):
    if not control_codes:
        return []
    return [dict(r) for r in db.execute("""SELECT DISTINCT q.ref_code, q.title_en, f.code AS framework FROM rc_requirements q
                                           JOIN rc_control_requirements cr ON cr.requirement_id = q.id
                                           JOIN rc_controls c ON c.id = cr.control_id JOIN rc_frameworks f ON f.id = q.framework_id
                                           WHERE c.control_code = ANY(%s) ORDER BY f.code, q.ref_code""", (list(control_codes),)).fetchall()]


def build_proposal(text, res, intents, playbook_sel=None, db=None):
    by = {i['code']: i for i in intents}
    it = by.get(res['intent'])
    if not it:
        return {'intent': None, 'confidence': res['confidence'], 'summary': res['summary'], 'fields': {},
                'handler': 'manual', 'alternatives': res.get('alternatives', []), 'why': res.get('why', {})}
    deadline = tasks.deadline_from(it, res['fields'])
    db = db or get_db()
    known = {r['control_code'] for r in db.execute("SELECT control_code FROM rc_controls WHERE is_active").fetchall()}
    codes = [c for c in it.get('control_codes') or [] if c in known]
    prop = {'intent': it['code'], 'intent_name_en': it['name_en'], 'intent_name_ar': it.get('name_ar'),
            'confidence': res['confidence'], 'summary': res['summary'], 'fields': res['fields'],
            'handler': it['handler'], 'handler_label_en': handlers.HANDLERS.get(it['handler'], {}).get('label_en'),
            'handler_label_ar': handlers.HANDLERS.get(it['handler'], {}).get('label_ar'),
            'control_codes': codes, 'requirements': _requirements(codes, db), 'owner_role': it.get('owner_role'),
            'priority': it.get('priority') or 'medium', 'deadline': deadline.isoformat() if deadline else None,
            'alternatives': res.get('alternatives', []), 'why': res.get('why', {})}
    if it['handler'] == 'playbook':
        fixed = (it.get('handler_params') or {}).get('playbook_code')
        sel = playbook_sel or {'playbooks': []}
        prop['playbooks'] = sel['playbooks'] if not fixed else [{'code': fixed, 'confidence': 1.0, 'params': {}}] + \
            [p for p in sel['playbooks'] if p['code'] != fixed]
        prop['playbook_code'] = fixed or (sel['playbooks'][0]['code'] if sel['playbooks'] else None)
        if prop['playbooks'] and prop['playbook_code']:
            first = next((p for p in prop['playbooks'] if p['code'] == prop['playbook_code']), {})
            prop['playbook_params'] = first.get('params') or {}
    return prop


def propose(item_id, user_id, gen=None, emb=None, db=None):
    db = db or get_db()
    it = item(item_id, db)
    if not it:
        raise LookupError('intake item not found')
    text = '\n'.join(x for x in (it.get('subject'), it.get('body')) if x)
    intents = catalog.intents(db)
    res, meta = tasks.classify(text, intents, gen, emb)
    sel = None
    if res['intent'] and next((i for i in intents if i['code'] == res['intent']), {}).get('handler') == 'playbook':
        sel, _m = tasks.select_playbooks(text, catalog.playbooks(db), gen, emb)
    prop = build_proposal(text, res, intents, sel, db)
    sid = audit.log('intake', text, meta['provider'], meta.get('model'), meta['prompt_version'], prop, status=meta['status'],
                    error=meta.get('error'), latency_ms=meta.get('latency_ms'), prompt_text=meta.get('prompt_text'),
                    object_type='ai_intake', object_id=item_id, user_id=user_id, db=db)
    prop.update(provider=meta['provider'], model=meta.get('model'), status=meta['status'], suggestion_id=sid)
    if prop.get('handler') == 'guidance':     # policy question: only cited library paragraphs, or "no source found"
        from . import library
        try:
            lib, lmeta = library.answer(text, gen=gen, embedder=emb, db=db)
            audit.log('guidance', text, lmeta['provider'], lmeta.get('model'), lmeta['prompt_version'],
                      {'status': lib['status'], 'cited': [c['id'] for c in lib['citations']], 'answer': lib['answer']},
                      status=lmeta['status'], error=lmeta.get('error'), latency_ms=lmeta.get('latency_ms'),
                      prompt_text=lmeta.get('prompt_text'), object_type='ai_intake', object_id=item_id, user_id=user_id, db=db)
            prop['library'] = lib
        except Exception:
            db.rollback()
            logger.exception('AI: library answer failed for intake %s', item_id)
            prop['library'] = {'status': 'no_source', 'citations': [], 'answer': None}
    db.execute("UPDATE ai_intake_items SET status = 'proposed', proposal = %s, suggestion_id = %s WHERE id = %s",
               (json.dumps(prop, ensure_ascii=False, default=str), sid, item_id))
    db.commit()
    return prop


def final_from_form(form, intent):
    fields = {f['key']: (form.get(f'f_{f["key"]}') or '').strip() for f in intent.get('fields') or []}
    pb_params = {k[3:]: v.strip() for k, v in form.items() if k.startswith('pp_') and v.strip()}
    pr = form.get('priority') if form.get('priority') in PRIORITIES else intent.get('priority') or 'medium'
    codes = [c.strip().upper() for c in (form.get('control_codes') or '').replace(';', ',').split(',') if c.strip()]
    return {'intent': intent['code'], 'summary': (form.get('summary') or '').strip(), 'fields': {k: v for k, v in fields.items() if v},
            'priority': pr, 'deadline': form.get('deadline') or None, 'control_codes': codes,
            'owner_role': form.get('owner_role') or intent.get('owner_role'),
            'playbook_code': form.get('playbook_code') or None, 'playbook_params': pb_params}


def _decision(prop, final):
    if not prop or prop.get('intent') != final['intent']:
        return 'edit'
    same = (prop.get('fields') or {}) == final['fields'] and (prop.get('priority') == final['priority']) and \
        (prop.get('deadline') or None) == (final['deadline'] or None) and (prop.get('playbook_code') or None) == final.get('playbook_code')
    return 'accept' if same else 'edit'


def confirm(item_id, form, user, db=None):
    """Create the records through the routing target. Raises handlers.HandlerError / ValueError."""
    db = db or get_db()
    it = item(item_id, db)
    if not it or it['status'] in ('confirmed', 'rejected'):
        raise ValueError('this item is already decided')
    intent = catalog.intent(form.get('intent') or '', db)
    if not intent:
        raise ValueError('choose what this is')
    final = final_from_form(form, intent)
    try:
        out = handlers.execute(intent['handler'], it, final, user, intent)
    except (handlers.HandlerError, ValueError):
        db.rollback()
        raise
    except Exception as e:  # target module failed (e.g. its table is missing): nothing half-created
        db.rollback()
        logger.exception('AI intake routing failed (%s)', intent['handler'])
        raise handlers.HandlerError(f'the target module could not create the record ({e.__class__.__name__})') from e
    decision = _decision(it.get('proposal'), final)
    if 'citations' in out:
        final['library'] = {'status': 'cited' if out['citations'] else 'no_source', 'citations': out['citations'],
                            'answer': out.get('answer')}
    db.execute("""UPDATE ai_intake_items SET status = 'confirmed', final = %s, created_refs = %s, decided_by = %s, decided_at = %s
                  WHERE id = %s""", (json.dumps(final, ensure_ascii=False, default=str), json.dumps(out['refs'], default=str),
                                     user.id, datetime.now(), item_id))
    db.commit()
    audit.decide(it.get('suggestion_id'), decision, user.id, db)
    if freeze_screening.should_screen(intent):  # freeze orders: screen every subject NOW (DB only, synchronous)
        try:
            out['screening'] = freeze_screening.run_for_item(item_id, db)
        except Exception as e:
            db.rollback()
            logger.exception('AI: freeze-order screening failed for intake %s', item_id)
            out['screening_error'] = f'screening failed ({e.__class__.__name__}): run it again from the item'
    return out, decision


def reject(item_id, user, db=None):
    db = db or get_db()
    it = item(item_id, db)
    if not it or it['status'] in ('confirmed', 'rejected'):
        raise ValueError('this item is already decided')
    db.execute("UPDATE ai_intake_items SET status = 'rejected', decided_by = %s, decided_at = %s WHERE id = %s",
               (user.id, datetime.now(), item_id))
    db.commit()
    audit.decide(it.get('suggestion_id'), 'reject', user.id, db)
