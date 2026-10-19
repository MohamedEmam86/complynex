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
Runs AI features with governance: builds the configured local providers,
calls the task (model with schema validation, or rules), logs the
suggestion, and executes long model calls as RQ jobs that the page polls.
Without Redis / a worker the job runs inline; rules_only always runs inline.
"""

import logging
import uuid
from datetime import datetime

from database.db import get_db

from . import audit, catalog, settings, tasks

logger = logging.getLogger(__name__)
_SEEDED = False


def seeded(db=None):
    global _SEEDED
    if not _SEEDED:
        catalog.ensure_seeded(db)
        _SEEDED = True


def providers():
    cfg = settings.get_config()
    return cfg, settings.generator(cfg), settings.embedder(cfg)


def _log(feature, payload, res, meta, user_id, obj_type=None, obj_id=None):
    return audit.log(feature, payload, meta['provider'], meta.get('model'), meta['prompt_version'], res, status=meta['status'],
                     error=meta.get('error'), latency_ms=meta.get('latency_ms'), prompt_text=meta.get('prompt_text'),
                     object_type=obj_type, object_id=obj_id, user_id=user_id)


# ------------------------------------------------------------------ feature runners (sync)
def run_feature(feature, payload, user_id):
    cfg, gen, emb = providers()
    if not cfg['ai.enabled']:
        raise RuntimeError('AI features are disabled for this installation')
    seeded()
    db = get_db()
    if feature == 'intake':
        from . import intake
        return intake.propose(payload['item_id'], user_id, gen, emb)
    if feature == 'playbook':
        res, meta = tasks.select_playbooks(payload['text'], catalog.playbooks(db), gen, emb)
        sid = _log('playbook', payload['text'], res, meta, user_id)
        return dict(res, suggestion_id=sid, provider=meta['provider'], status=meta['status'])
    if feature == 'nba':
        from . import nba
        gaps, ctx = nba.gaps_for(payload['obj_type'], int(payload['obj_id']), db)
        res, meta = tasks.phrase(gaps, payload.get('lang', 'en'), gen, ctx)
        sid = _log('nba', {'gaps': gaps, 'lang': payload.get('lang')}, res, meta, user_id, payload['obj_type'], int(payload['obj_id']))
        return dict(res, gaps=gaps, suggestion_id=sid, provider=meta['provider'], status=meta['status'])
    if feature == 'draft':
        from . import nba
        kind = payload['kind']
        if kind == 'board_summary':
            from regcontrols import readiness
            o = readiness.overview(db=db)
            ctx = {'score': o['overall']['score'], 'failing': o['overall']['failing'], 'open_findings': len(o['open_findings']),
                   'gaps': [f"{c['control_code']} {c['title_en']}" for c in o['gaps'][:5]]}
        else:
            gaps, ctx = nba.gaps_for(payload['obj_type'], int(payload['obj_id']), db)
            ctx = dict(ctx, gaps=gaps)
        res, meta = tasks.draft(kind, ctx, payload.get('lang', 'en'), gen)
        sid = _log('draft', {'kind': kind, 'ctx': ctx}, res, meta, user_id, payload.get('obj_type'), payload.get('obj_id'))
        return dict(res, suggestion_id=sid, provider=meta['provider'], status=meta['status'])
    if feature == 'library_index':
        from . import library
        return library.rebuild(db, emb)
    if feature == 'mail_import':
        from . import mailbox
        return mailbox.run_import(db=db)
    raise ValueError('unknown feature')


BACKGROUND = ('library_index', 'mail_import')     # may be slow without any model (embeddings, mail server)


# ------------------------------------------------------------------ jobs
def start_job(feature, payload, user_id):
    """Create a job row; run it on the RQ worker when a local model is configured, else inline. Returns the job id."""
    db = get_db()
    jid = str(uuid.uuid4())
    import json
    db.execute("INSERT INTO ai_jobs (id, feature, payload, created_by) VALUES (%s,%s,%s,%s)",
               (jid, feature, json.dumps(payload, default=str), user_id))
    db.commit()
    cfg, gen, _ = providers()
    if cfg['ai.async'] and (gen.can_generate or feature in BACKGROUND):
        try:
            from events.queue import get_queue
            get_queue().enqueue('ai.service.job_entry', jid, job_timeout=int(cfg['ai.timeout_s']) * 3 + 60)
            return jid
        except Exception:
            logger.warning('AI: RQ unavailable, running job %s inline', jid, exc_info=True)
    execute_job(jid)
    return jid


def execute_job(jid):
    import json
    db = get_db()
    j = db.execute("SELECT * FROM ai_jobs WHERE id = %s", (jid,)).fetchone()
    if not j or j['status'] in ('done', 'failed'):
        return
    db.execute("UPDATE ai_jobs SET status = 'running' WHERE id = %s", (jid,))
    db.commit()
    try:
        res = run_feature(j['feature'], j['payload'], j['created_by'])
        db.execute("UPDATE ai_jobs SET status = 'done', result = %s, suggestion_id = %s, finished_at = %s WHERE id = %s",
                   (json.dumps(res, ensure_ascii=False, default=str), res.get('suggestion_id'), datetime.now(), jid))
    except Exception as e:
        db.rollback()
        logger.exception('AI job %s failed', jid)
        db.execute("UPDATE ai_jobs SET status = 'failed', error = %s, finished_at = %s WHERE id = %s",
                   (str(e)[:500], datetime.now(), jid))
    db.commit()


def job_entry(jid):
    """RQ entry point (runs in the event-dispatcher worker)."""
    from events.dispatcher import _get_app
    with _get_app().app_context():
        execute_job(jid)


def job(jid, user_id=None):
    r = get_db().execute("SELECT * FROM ai_jobs WHERE id = %s", (jid,)).fetchone()
    if not r or (user_id and r['created_by'] and r['created_by'] != user_id):
        return None
    return dict(r)


def health():
    cfg, gen, emb = providers()
    out = {'enabled': cfg['ai.enabled'], 'provider': gen.name, 'model': gen.model, 'generator': gen.health(),
           'embeddings': emb.health() if emb else {'ok': None, 'detail': 'off'}, 'config': cfg}
    try:
        from events.queue import get_queue
        q = get_queue()
        q.connection.ping()
        out['queue'] = {'ok': True, 'detail': f'{q.name}: {len(q)} waiting'}
    except Exception as e:
        out['queue'] = {'ok': False, 'detail': f'not available ({e.__class__.__name__}) — jobs run inline'}
    db = get_db()
    out['jobs'] = [dict(r) for r in db.execute("""SELECT status, count(*) AS n FROM ai_jobs WHERE created_at > now() - interval '1 day'
                                                  GROUP BY status""").fetchall()]
    return out


def purge():
    cfg = settings.get_config()
    return audit.purge(cfg['ai.log_retention_days'])
