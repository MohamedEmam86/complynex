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

"""Compliance Copilot pages (permission perm_ai: none / view / use / admin)."""

import json
import os
from datetime import datetime
from functools import wraps

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import get_locale
from flask_babel import gettext as _
from flask_login import current_user, login_required

from attachments.service import list_attachments
from database.db import get_db
from models.audit import AuditLog

from . import ai_bp as bp
from . import audit, catalog, extract, handlers, intake, nba, playbooks, service, settings, tasks
from .netguard import NotLocalError

RANK = {'none': 0, 'view': 1, 'use': 2, 'edit': 2, 'admin': 3}


def level(user=None):
    u = user or current_user
    if not getattr(u, 'is_authenticated', False):
        return 0
    if u.is_admin():
        return 3
    return RANK.get(getattr(u, 'perm_ai', None) or u._get_perm('ai'), 0)


def need(lvl):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapped(*a, **kw):
            if level() < RANK[lvl]:
                if request.accept_mimetypes.best == 'application/json' or request.path.startswith('/ai/api/'):
                    return jsonify({'error': 'forbidden'}), 403
                flash(_('You do not have permission for the Compliance Copilot.'), 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            return f(*a, **kw)
        return wrapped
    return deco


def _log(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, 'ai', item_id, details, request.remote_addr)
    except Exception:
        get_db().rollback()


def _err(e):
    msg = str(e)
    flash(_(msg) if not any(c in msg for c in ':%"') else msg, 'danger')


def _lang():
    return 'ar' if str(get_locale()).startswith('ar') else 'en'


@bp.app_template_global('ai_level')
def ai_level():
    try:
        return level()
    except Exception:
        return 0


@bp.app_template_global('ai_enabled')
def ai_enabled():
    try:
        return bool(settings.get_config()['ai.enabled'])
    except Exception:
        return False


@bp.context_processor
def _ctx():
    return {'ai_cfg': settings.get_config()}


# ------------------------------------------------------------------ intake
def _save_upload(item_id, f):
    from utils.file_validator import secure_filename_strict, validate_file
    ok, err = validate_file(f, upload_type='document')
    if not ok:
        raise ValueError(f'file not accepted: {err}')
    name = secure_filename_strict(f.filename)
    rel_dir = os.path.join('uploads', 'attachments', 'ai', 'ai_intake', str(item_id))
    full_dir = os.path.join(current_app.root_path, rel_dir)
    os.makedirs(full_dir, exist_ok=True)
    full = os.path.join(full_dir, name)
    f.save(full)
    db = get_db()
    db.execute("""INSERT INTO generic_attachments (module, record_type, record_id, filename, file_path, file_size, uploaded_by,
                  uploaded_at) VALUES ('ai', 'ai_intake', %s, %s, %s, %s, %s, %s)""",
               (item_id, f.filename[:255], os.path.join(rel_dir, name).replace('\\', '/'), os.path.getsize(full), current_user.id,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()
    with open(full, 'rb') as fh:
        return extract.text_from_bytes(f.filename, fh.read())


@bp.route('/', methods=['GET', 'POST'])
@need('view')
def home():
    service.seeded()
    if request.method == 'POST':
        if level() < 2:
            abort(403)
        f = request.files.get('file')
        body = request.form.get('body') or ''
        try:
            if not settings.get_config()['ai.enabled']:
                raise ValueError('AI features are disabled for this installation')
            iid = intake.create_item(request.form.get('channel'), request.form.get('subject'),
                                     body or ('(document)' if f and f.filename else ''), current_user.id)
            if f and f.filename:
                text, note = _save_upload(iid, f)
                if text and not body.strip():
                    get_db().execute("UPDATE ai_intake_items SET body = %s, channel = 'document' WHERE id = %s", (text, iid))
                    get_db().commit()
                if note:
                    flash(_(note) if ':' not in note else note, 'warning')
            jid = service.start_job('intake', {'item_id': iid}, current_user.id)
            _log('ai_intake_submit', iid)
            return redirect(url_for('ai.intake_review', item_id=iid, job=jid))
        except ValueError as e:
            _err(e)
        return redirect(url_for('ai.home'))
    return render_template('ai/home.html', items=intake.items(limit=30, user_id=None if level() >= 3 else current_user.id),
                           channels=intake.CHANNELS)


@bp.route('/intake/<int:item_id>', methods=['GET', 'POST'])
@need('view')
def intake_review(item_id):
    it = intake.item(item_id)
    if not it or (level() < 3 and it['created_by'] != current_user.id):
        abort(404)
    if request.method == 'POST':
        if level() < 2:
            abort(403)
        try:
            if request.form.get('action') == 'reject':
                intake.reject(item_id, current_user)
                flash(_('Proposal rejected; nothing was created.'), 'info')
            elif request.form.get('action') == 'repropose':
                jid = service.start_job('intake', {'item_id': item_id}, current_user.id)
                return redirect(url_for('ai.intake_review', item_id=item_id, job=jid))
            else:
                out, decision = intake.confirm(item_id, request.form, current_user)
                _log('ai_intake_confirm', item_id, f"{request.form.get('intent')} ({decision})")
                msg = out['message']
                flash(_(msg), 'success')
        except (ValueError, handlers.HandlerError) as e:
            _err(e)
        return redirect(url_for('ai.intake_review', item_id=item_id))
    service.seeded()
    intents = catalog.intents()
    prop = it.get('proposal') or {}
    sel = request.args.get('intent') or prop.get('intent')
    chosen = next((i for i in intents if i['code'] == sel), None)
    pf = {}
    if chosen:   # fields for the chosen intent: the proposal's, or extracted again when the user picked another intent
        pf = prop.get('fields') or {} if prop.get('intent') == chosen['code'] else \
            tasks.extract_fields(it.get('body') or '', chosen.get('fields'))
    return render_template('ai/intake_review.html', it=it, prop=prop, intents=intents, chosen=chosen, pf=pf,
                           playbooks=catalog.playbooks(), handlers=handlers.HANDLERS, job_id=request.args.get('job'),
                           files=list_attachments('ai', 'ai_intake', item_id), lang=_lang())


# ------------------------------------------------------------------ jobs / cards (JSON, polled by static/js/ai_copilot.js)
@bp.route('/api/jobs/<jid>')
@need('view')
def api_job(jid):
    j = service.job(jid, None if level() >= 3 else current_user.id)
    if not j:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'status': j['status'], 'result': j['result'], 'error': j['error']})


@bp.route('/api/nba/<obj_type>/<int:obj_id>', methods=['POST'])
@need('use')
def api_nba(obj_type, obj_id):
    if obj_type not in nba.OBJECTS:
        return jsonify({'error': 'unknown object'}), 404
    try:
        gaps, _ctx2 = nba.gaps_for(obj_type, obj_id)
    except LookupError:
        return jsonify({'error': 'not found'}), 404
    jid = service.start_job('nba', {'obj_type': obj_type, 'obj_id': obj_id, 'lang': _lang()}, current_user.id)
    return jsonify({'job_id': jid, 'gaps': gaps, 'deterministic': tasks.phrase_rules(gaps, _lang())})


@bp.route('/api/draft', methods=['POST'])
@need('use')
def api_draft():
    d = request.get_json(silent=True) or request.form
    if d.get('kind') not in tasks.DRAFT_KINDS:
        return jsonify({'error': 'unknown draft'}), 400
    payload = {'kind': d['kind'], 'obj_type': d.get('obj_type'), 'obj_id': d.get('obj_id'), 'lang': _lang()}
    if d['kind'] != 'board_summary' and payload['obj_type'] not in nba.OBJECTS:
        return jsonify({'error': 'unknown object'}), 400
    return jsonify({'job_id': service.start_job('draft', payload, current_user.id)})


@bp.route('/api/suggestions/<int:sid>/decision', methods=['POST'])
@need('use')
def api_decision(sid):
    d = request.get_json(silent=True) or request.form
    audit.decide(sid, d.get('decision'), current_user.id)
    return jsonify({'ok': True})


# ------------------------------------------------------------------ playbooks
@bp.route('/playbooks', methods=['GET', 'POST'])
@need('view')
def playbooks_home():
    service.seeded()
    if request.method == 'POST':
        if level() < 2:
            abort(403)
        if request.form.get('action') == 'run':
            code = request.form.get('playbook_code')
            pb = catalog.playbook(code)
            if not pb:
                abort(404)
            params = {p['key']: (request.form.get(f"p_{p['key']}") or '').strip() for p in pb.get('parameters') or []}
            try:
                r = playbooks.instantiate(code, {k: v for k, v in params.items() if v}, current_user.id,
                                          suggestion_id=request.form.get('suggestion_id', type=int))
                sid = request.form.get('suggestion_id', type=int)
                audit.decide(sid, 'accept' if request.form.get('proposed') == code else 'edit', current_user.id)
                _log('ai_playbook_run', r['run_id'], code)
                flash(_('Playbook started: %(n)s task(s) created.', n=r['actions']), 'success')
                return redirect(url_for('regcontrols.finding_detail', finding_id=r['finding_id']))
            except ValueError as e:
                _err(e)
            return redirect(url_for('ai.playbooks_home'))
        text = (request.form.get('situation') or '').strip()
        if not text:
            flash(_('Describe the situation.'), 'danger')
            return redirect(url_for('ai.playbooks_home'))
        jid = service.start_job('playbook', {'text': text}, current_user.id)
        return redirect(url_for('ai.playbooks_home', job=jid))
    jid = request.args.get('job')
    j = service.job(jid, None if level() >= 3 else current_user.id) if jid else None
    return render_template('ai/playbooks.html', playbooks=catalog.playbooks(), runs=playbooks.runs(limit=20),
                           job_id=jid, job=j, lang=_lang())


@bp.route('/playbooks/<code>', methods=['GET', 'POST'])
@need('view')
def playbook_edit(code):
    service.seeded()
    pb = catalog.playbook(code) if code != 'new' else None
    if request.method == 'POST':
        if level() < 3:
            abort(403)
        new_code = (request.form.get('code') or code).strip().lower()
        if not new_code or new_code == 'new' or not request.form.get('name_en'):
            flash(_('Code and English name are required.'), 'danger')
            return redirect(url_for('ai.playbook_edit', code=code))
        try:
            data = {'name_en': request.form['name_en'], 'name_ar': request.form.get('name_ar') or None,
                    'description': request.form.get('description') or None,
                    'keywords': [k.strip() for k in (request.form.get('keywords') or '').splitlines() if k.strip()],
                    'examples': [k.strip() for k in (request.form.get('examples') or '').splitlines() if k.strip()],
                    'parameters': json.loads(request.form.get('parameters') or '[]'),
                    'severity': request.form.get('severity') or 'medium', 'is_active': bool(request.form.get('is_active'))}
            steps = []
            for i in range(int(request.form.get('n_steps') or 0) + 1):
                key = (request.form.get(f's{i}_key') or '').strip()
                if not key:
                    continue
                steps.append({'step_key': key, 'seq': int(request.form.get(f's{i}_seq') or (i + 1) * 10),
                              'step_type': request.form.get(f's{i}_type') or 'task', 'title_en': request.form.get(f's{i}_title_en') or key,
                              'title_ar': request.form.get(f's{i}_title_ar'), 'control_code': (request.form.get(f's{i}_control') or '').upper(),
                              'owner_role': request.form.get(f's{i}_owner'), 'due_days': request.form.get(f's{i}_due') or 14,
                              'is_active': bool(request.form.get(f's{i}_active'))})
            catalog.save_playbook(new_code, data, steps, current_user.id)
            _log('ai_playbook_save', None, new_code)
            flash(_('Saved.'), 'success')
            return redirect(url_for('ai.playbook_edit', code=new_code))
        except (ValueError, KeyError) as e:
            get_db().rollback()
            _err(e)
            return redirect(url_for('ai.playbook_edit', code=code))
    if code != 'new' and not pb:
        abort(404)
    steps = []
    if pb:
        steps = [dict(s) for s in get_db().execute("SELECT * FROM ai_playbook_steps WHERE playbook_code = %s ORDER BY seq, id",
                                                   (code,)).fetchall()]
    return render_template('ai/playbook_form.html', pb=pb, steps=steps, code=code, lang=_lang())


# ------------------------------------------------------------------ intent catalog
@bp.route('/intents')
@need('view')
def intents():
    service.seeded()
    return render_template('ai/intents.html', rows=catalog.intents(active_only=False), handlers=handlers.HANDLERS, lang=_lang())


@bp.route('/intents/<code>', methods=['GET', 'POST'])
@need('view')
def intent_edit(code):
    service.seeded()
    row = catalog.intent(code) if code != 'new' else None
    if request.method == 'POST':
        if level() < 3:
            abort(403)
        new_code = (request.form.get('code') or code).strip().lower()
        if not new_code or new_code == 'new' or not request.form.get('name_en'):
            flash(_('Code and English name are required.'), 'danger')
            return redirect(url_for('ai.intent_edit', code=code))
        if request.form.get('handler') not in handlers.HANDLERS:
            flash(_('Choose a routing target.'), 'danger')
            return redirect(url_for('ai.intent_edit', code=code))
        try:
            data = {'name_en': request.form['name_en'], 'name_ar': request.form.get('name_ar') or None,
                    'description': request.form.get('description') or None,
                    'keywords': [k.strip() for k in (request.form.get('keywords') or '').splitlines() if k.strip()],
                    'examples': [k.strip() for k in (request.form.get('examples') or '').splitlines() if k.strip()],
                    'fields': json.loads(request.form.get('fields') or '[]'),
                    'handler': request.form['handler'], 'handler_params': json.loads(request.form.get('handler_params') or '{}'),
                    'control_codes': [c.strip().upper() for c in (request.form.get('control_codes') or '').split(',') if c.strip()],
                    'owner_role': request.form.get('owner_role') or None,
                    'priority': request.form.get('priority') if request.form.get('priority') in intake.PRIORITIES else 'medium',
                    'deadline_hours': request.form.get('deadline_hours', type=int), 'is_active': bool(request.form.get('is_active'))}
            if not isinstance(data['fields'], list) or not isinstance(data['handler_params'], dict):
                raise ValueError('fields must be a JSON list and routing parameters a JSON object')
            catalog.save_intent(new_code, data, current_user.id)
            _log('ai_intent_save', None, new_code)
            flash(_('Saved.'), 'success')
            return redirect(url_for('ai.intent_edit', code=new_code))
        except ValueError as e:
            get_db().rollback()
            _err(e)
            return redirect(url_for('ai.intent_edit', code=code))
    if code != 'new' and not row:
        abort(404)
    return render_template('ai/intent_form.html', row=row, code=code, handlers=handlers.HANDLERS, priorities=intake.PRIORITIES,
                           lang=_lang())


# ------------------------------------------------------------------ settings, health, log
@bp.route('/settings', methods=['GET', 'POST'])
@need('admin')
def settings_page():
    if request.method == 'POST':
        data = {k: (request.form.get(k) or '').strip() for k in settings.DEFAULTS}
        data['ai.enabled'] = 'true' if request.form.get('ai.enabled') else 'false'
        data['ai.async'] = 'true' if request.form.get('ai.async') else 'false'
        try:
            settings.save_config(data)
            _log('ai_settings_save', None, f"{data['ai.provider']} {data.get('ai.model')}")
            flash(_('Saved.'), 'success')
        except (NotLocalError, ValueError) as e:
            _err(e)
        return redirect(url_for('ai.settings_page'))
    return render_template('ai/settings.html', cfg=settings.get_config(), health=service.health())


@bp.route('/log', methods=['GET', 'POST'])
@need('view')
def log_page():
    if request.method == 'POST':
        if level() < 3:
            abort(403)
        r = service.purge()
        flash(_('Retention applied: %(n)s prompt(s) purged.', n=r['suggestions']), 'success')
        return redirect(url_for('ai.log_page'))
    db = get_db()
    rows = [dict(r) for r in db.execute("""SELECT s.id, s.feature, s.object_type, s.object_id, s.provider, s.model, s.prompt_version,
                                           s.status, s.latency_ms, s.decision, s.created_at, s.purged_at, s.input_hash,
                                           u.first_name || ' ' || u.last_name AS user_name
                                           FROM ai_suggestions s LEFT JOIN users u ON u.id = s.user_id
                                           ORDER BY s.id DESC LIMIT 200""").fetchall()]
    return render_template('ai/log.html', rows=rows, stats=audit.stats())


@bp.route('/log/<int:sid>')
@need('admin')
def log_detail(sid):
    r = get_db().execute("SELECT * FROM ai_suggestions WHERE id = %s", (sid,)).fetchone()
    if not r:
        abort(404)
    return render_template('ai/log_detail.html', s=dict(r))
