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
Superadmin page of the local negative-lists workbook import (in the list sources / versions area):
upload -> preview (counts only) -> apply. The work runs in a background thread; its state is a small JSON file
next to the upload (works across workers) and the page refreshes itself while it runs. The workbook's sheet
names are shown on this page only (superadmin); every other user sees the generic categories on hits.
Registered on the screening blueprint (imported at the end of screening/routes.py).
"""
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_babel import gettext
from flask_login import current_user, login_required

from screening.routes import screening_bp, BASE_DIR, _audit
from utils.decorators import permission_required

logger = logging.getLogger(__name__)

LL_DIR = os.path.join(BASE_DIR, 'uploads', 'local_lists')
_TOKEN = re.compile(r'^[0-9a-f]{32}$')
KEEP_DAYS = 2


def is_superadmin():
    return getattr(current_user, 'role', '') == 'superadmin'


def _job_path(token):
    return os.path.join(LL_DIR, f'{token}.json')


def load_job(token):
    if not token or not _TOKEN.match(token):
        return None
    try:
        with open(_job_path(token), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_job(token, job):
    tmp = _job_path(token) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(job, fh, ensure_ascii=False, default=str)
    os.replace(tmp, _job_path(token))


def cleanup(days=KEEP_DAYS):
    """Uploaded workbooks hold personal data: anything older than `days` is removed."""
    try:
        limit = time.time() - days * 86400
        for f in os.listdir(LL_DIR):
            p = os.path.join(LL_DIR, f)
            if os.path.isfile(p) and os.path.getmtime(p) < limit:
                os.remove(p)
    except OSError:
        pass


def start(token, job, do_apply, db_config=None):
    """Run the preview or the import of the uploaded workbook in a thread; the job file follows it."""
    if db_config is None:
        from config import get_config
        db_config = dict(get_config().POSTGRES_CONFIG)
    xlsx = os.path.join(LL_DIR, f'{token}.xlsx')
    job.update({'state': 'running', 'mode': 'apply' if do_apply else 'preview',
                'started': datetime.now().isoformat(timespec='seconds'), 'error': None})
    save_job(token, job)

    def _run():
        import psycopg2
        from screening.local_lists import importer as LLI
        conn = None
        try:
            conn = psycopg2.connect(**db_config)
            opts = job.get('options') or {}
            out = LLI.run(conn, xlsx, do_apply=do_apply, user_id=job.get('user_id'), trigger='upload',
                          allow_shrink=bool(opts.get('allow_shrink')), allow_unknown=bool(opts.get('allow_unknown')),
                          lifted_mode=opts.get('lifted') or 'history', retire_legacy=bool(opts.get('retire_legacy')),
                          file_name=job.get('file_name'))
            job.update({'state': 'done', 'result': out, 'finished': datetime.now().isoformat(timespec='seconds')})
            if do_apply and out.get('result') == 'APPLIED':
                try:
                    os.remove(xlsx)          # personal data: the file is not kept once imported (its hash is)
                except OSError:
                    pass
        except LLI.ImportBusy:
            job.update({'state': 'error', 'error': 'busy'})
        except Exception as e:
            logger.exception('local lists import job failed')
            job.update({'state': 'error', 'error': e.__class__.__name__})
        finally:
            if conn is not None:
                conn.close()
            save_job(token, job)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def _refuse():
    flash(gettext('Only the platform superadmin imports the local lists workbook.'), 'error')
    return redirect(url_for('screening.list_versions'))


@screening_bp.route('/lists/local-import')
@login_required
@permission_required('screening', level='view')
def list_local_import():
    if not is_superadmin():
        return _refuse()
    from screening.local_lists import importer as LLI
    from screening.local_lists.categories import label as ll_label
    from screening.local_lists.workbook import KIND_LABEL
    conn = None
    try:
        from screening import list_versions as LV
        conn = LV.connect()
        hist, force = LLI.history(conn), LLI.in_force(conn)
    except Exception as e:
        logger.error('local lists page: %s', e)
        hist, force = [], []
    finally:
        if conn is not None:
            conn.close()
    token = request.args.get('job') or ''
    job = load_job(token)
    return render_template('screening/local_lists_import.html', history=hist, in_force=force, job=job,
                           token=token if job else '', ll_label=ll_label, kind_label=KIND_LABEL)


@screening_bp.route('/lists/local-import/upload', methods=['POST'])
@login_required
@permission_required('screening', level='view')
def list_local_import_upload():
    if not is_superadmin():
        return _refuse()
    f = request.files.get('file')
    if not f or not f.filename or not f.filename.lower().endswith(('.xlsx', '.xlsm')):
        flash(gettext('Choose the workbook (.xlsx).'), 'error')
        return redirect(url_for('screening.list_local_import'))
    os.makedirs(LL_DIR, exist_ok=True)
    cleanup()
    token = uuid.uuid4().hex
    f.save(os.path.join(LL_DIR, f'{token}.xlsx'))
    job = {'user_id': current_user.id, 'file_name': os.path.basename(f.filename)[:200],
           'options': {'allow_unknown': bool(request.form.get('allow_unknown'))}}
    start(token, job, do_apply=False)
    _audit('Local lists workbook uploaded for preview', None, f'job {token}')
    return redirect(url_for('screening.list_local_import', job=token))


@screening_bp.route('/lists/local-import/<token>/apply', methods=['POST'])
@login_required
@permission_required('screening', level='view')
def list_local_import_apply(token):
    if not is_superadmin():
        return _refuse()
    job = load_job(token)
    if not job or job.get('state') != 'done' or (job.get('result') or {}).get('result') != 'DRY_RUN' or \
            not os.path.isfile(os.path.join(LL_DIR, f'{token}.xlsx')):
        flash(gettext('Preview the workbook first.'), 'error')
        return redirect(url_for('screening.list_local_import'))
    allow_shrink = bool(request.form.get('allow_shrink'))
    reason = (request.form.get('reason') or '').strip()
    if allow_shrink and len(reason) < 10:
        flash(gettext('Write why the shrink of a list is accepted (at least 10 characters).'), 'error')
        return redirect(url_for('screening.list_local_import', job=token))
    lifted = request.form.get('lifted') if request.form.get('lifted') in ('history', 'inactive') else 'history'
    retire = bool(request.form.get('retire_legacy'))
    job['options'] = dict(job.get('options') or {}, allow_shrink=allow_shrink, lifted=lifted, retire_legacy=retire)
    job['user_id'] = current_user.id
    start(token, job, do_apply=True)
    _audit('Local lists workbook import started', None,
           f'job {token}; shrink allowed: {allow_shrink}' + (f'; reason: {reason}' if reason else '') +
           f'; lifted: {lifted}; retire older rows: {retire}')
    return redirect(url_for('screening.list_local_import', job=token))
