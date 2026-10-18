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

"""Carbon accounting pages: boundary, versioned factors, detailed activity
data with evidence, PCAF financed emissions, data quality, review workflow,
intensity & initiatives, and the bilingual disclosure (page / PDF / Excel)."""

import io
from datetime import datetime

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from attachments.service import list_attachments
from database.db import get_db
from models.audit import AuditLog
from utils.decorators import permission_required

from . import accounting as A
from . import service as S
from .engine import SCOPE3_CATEGORIES
from .routes import carbon_bp as bp

MODULE = 'carbon'


def _log(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, MODULE, item_id, details, request.remote_addr)
    except Exception:
        get_db().rollback()


def _err(e):
    msg = str(e)
    flash(_(msg) if not any(c in msg for c in ':%"') else msg, 'danger')


def _guard():
    if request.method == 'POST' and not current_user.can_edit(MODULE):
        abort(403)


def _period():
    pid = request.values.get('period', type=int)
    p = S.period(pid)
    if pid and not p:
        abort(404)
    return p


@bp.context_processor
def _ctx():
    authed = getattr(current_user, 'is_authenticated', False)
    return {'cb_can_edit': authed and current_user.can_edit(MODULE), 'cb_periods': (S.periods() if authed else []),
            'scope3_labels': SCOPE3_CATEGORIES}


@bp.route('/boundary', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def boundary():
    _guard()
    if request.method == 'POST':
        f = request.form.get('form')
        try:
            if f == 'entity':
                S.save_entity(request.form, request.form.get('entity_id', type=int))
            elif f == 'site':
                S.save_site(request.form, request.form.get('site_id', type=int))
            else:
                S.save_boundary(request.form, current_user.id)
            _log(f'carbon_boundary_{f or "approach"}')
            flash(_('Saved.'), 'success')
        except S.CarbonError as e:
            _err(e)
        return redirect(url_for('carbon.boundary'))
    return render_template('carbon/acc/boundary.html', cfg=S.config(), entities=S.entities(), sites=S.sites(),
                           approaches=A.APPROACHES)


@bp.route('/factor-versions', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def factor_versions():
    _guard()
    if request.method == 'POST':
        code = (request.form.get('factor_code') or '').strip().upper()
        try:
            if not code:
                raise S.CarbonError(S.N_('factor code is required'))
            fid = S.publish_factor_version(code, request.form, current_user.id)
            _log('carbon_factor_version', fid, code)
            flash(_('New factor version published; earlier entries keep the version they used.'), 'success')
        except S.CarbonError as e:
            _err(e)
        return redirect(url_for('carbon.factor_versions', code=code or None))
    codes = S.factor_codes()
    sel = request.args.get('code')
    return render_template('carbon/acc/factor_versions.html', codes=codes, sel=sel, versions=codes.get(sel, []))


@bp.route('/activity', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def activity():
    _guard()
    p = _period()
    if not p:
        flash(_('No reporting period exists yet.'), 'warning')
        return redirect(url_for('carbon.dashboard'))
    if request.method == 'POST':
        try:
            if request.form.get('action') == 'delete':
                S.delete_entry(request.form.get('entry_id', type=int))
                flash(_('Entry deleted.'), 'info')
            else:
                eid, res = S.add_entry(p['id'], request.form, current_user.id)
                _log('carbon_activity_add', eid, f"{res['tco2e']} tCO2e")
                flash(_('Recorded %(t)s tCO2e. Attach the evidence (invoice, meter reading, ticket).', t=res['tco2e']),
                      'success' if res['unit_ok'] else 'warning')
                return redirect(url_for('carbon.activity_files', entry_id=eid))
        except S.CarbonError as e:
            _err(e)
        return redirect(url_for('carbon.activity', period=p['id']))
    cfg = S.config()
    en = S.enabled_scopes(cfg)
    codes = {c: v for c, v in S.factor_codes().items() if v and v[-1]['scope'] in en}
    rows = S.entries(p['id'])
    for e in rows:
        e['evidence'] = S.has_evidence(e)
    return render_template('carbon/acc/activity.html', p=p, rows=rows, codes=codes, sites=S.sites(),
                           wf=S.workflow(p['id']), locked=A.is_locked(S.workflow(p['id'])))


@bp.route('/activity/<int:entry_id>/files')
@login_required
@permission_required(MODULE)
def activity_files(entry_id):
    e = get_db().execute("SELECT * FROM carbon_activity_entries WHERE id = %s", (entry_id,)).fetchone()
    if not e:
        abort(404)
    e = dict(e)
    locked = A.is_locked(S.workflow(e['reporting_period_id']))
    return render_template('carbon/acc/files.html', e=e, attach_module=MODULE, attach_record_type='carbon_entry',
                           attach_record_id=entry_id, attach_items=list_attachments(MODULE, 'carbon_entry', entry_id),
                           attach_can_edit=current_user.can_edit(MODULE) and not locked)


@bp.route('/financed', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def financed():
    _guard()
    p = _period()
    if not p:
        return redirect(url_for('carbon.dashboard'))
    if request.method == 'POST':
        try:
            rid, r = S.save_exposure(p['id'], request.form, current_user.id)
            _log('carbon_pcaf_add', rid)
            flash(_('Exposure saved: %(t)s tCO2e financed (PCAF score %(s)s).', t=r['financed_tco2e'], s=r['score'])
                  if not r['error'] else r['error'], 'success' if not r['error'] else 'warning')
        except S.CarbonError as e:
            _err(e)
        return redirect(url_for('carbon.financed', period=p['id']))
    codes = {c: v for c, v in S.factor_codes().items() if v and v[-1].get('ghg_category_no') == 15}
    return render_template('carbon/acc/financed.html', p=p, rows=S.exposures(p['id']), summary=S.financed_summary(p['id']),
                           codes=codes, methods=A.PCAF_METHODS, locked=A.is_locked(S.workflow(p['id'])))


@bp.route('/quality')
@login_required
@permission_required(MODULE)
def quality():
    p = _period()
    if not p:
        return redirect(url_for('carbon.dashboard'))
    return render_template('carbon/acc/quality.html', p=p, dq=S.data_quality(p['id']))


@bp.route('/workflow', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def workflow():
    _guard()
    p = _period()
    if not p:
        return redirect(url_for('carbon.dashboard'))
    if request.method == 'POST':
        try:
            new = S.workflow_action(p['id'], request.form.get('action'), current_user, request.form.get('note'))
            _log('carbon_workflow_' + (request.form.get('action') or ''), p['id'], new)
            flash(_('Inventory status: %(s)s.', s=new), 'success')
        except S.CarbonError as e:
            _err(e)
        return redirect(url_for('carbon.workflow', period=p['id']))
    dq = S.data_quality(p['id'])
    return render_template('carbon/acc/workflow.html', p=p, wf=S.workflow(p['id']), events=S.workflow_events(p['id']),
                           critical=sum(1 for i in dq['issues'] if i['severity'] == 'critical'), dq=dq)


@bp.route('/intensity', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def intensity():
    _guard()
    p = _period()
    if not p:
        return redirect(url_for('carbon.dashboard'))
    if request.method == 'POST':
        try:
            if request.form.get('form') == 'initiative':
                S.save_initiative(request.form, current_user.id)
            else:
                S.save_metrics(p['id'], request.form, current_user.id)
            flash(_('Saved.'), 'success')
        except S.CarbonError as e:
            _err(e)
        return redirect(url_for('carbon.intensity', period=p['id']))
    inv = S.inventory(p['id'])
    target = get_db().execute("SELECT * FROM carbon_targets ORDER BY id DESC LIMIT 1").fetchone()
    from .engine import compute_target_progress
    prog = None
    if target and target['baseline_tco2e']:
        prog = compute_target_progress(target['baseline_year'], float(target['baseline_tco2e']),
                                       inv['operational_tco2e'], float(target['target_2030_pct'] or 0), 2030)
    ini = S.initiatives()
    return render_template('carbon/acc/intensity.html', p=p, inv=inv, target=target, progress=prog, initiatives=ini,
                           planned_reduction=sum(float(i['expected_reduction_tco2e'] or 0) for i in ini
                                                 if i['status'] in ('planned', 'in_progress')))


# ------------------------------------------------------------------ disclosure
@bp.route('/disclosure')
@login_required
@permission_required(MODULE)
def disclosure():
    p = _period()
    if not p:
        return redirect(url_for('carbon.dashboard'))
    inv = S.inventory(p['id'])
    html = render_template('carbon/acc/disclosure.html', inv=inv, p=p, generated_at=datetime.now(),
                           pdf=request.args.get('format') == 'pdf')
    if request.args.get('format') == 'pdf':
        from weasyprint import HTML
        pdf = HTML(string=html, base_url=request.url_root).write_pdf()
        _log('carbon_disclosure_pdf', p['id'])
        return Response(pdf, mimetype='application/pdf',
                        headers={'Content-Disposition': f"attachment; filename=carbon_disclosure_{p['id']}.pdf"})
    return html


@bp.route('/disclosure.xlsx')
@login_required
@permission_required(MODULE)
def disclosure_xlsx():
    p = _period()
    if not p:
        return redirect(url_for('carbon.dashboard'))
    from .export import workbook
    buf = io.BytesIO()
    workbook(S.inventory(p['id'])).save(buf)
    _log('carbon_disclosure_xlsx', p['id'])
    return Response(buf.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f"attachment; filename=carbon_disclosure_{p['id']}.xlsx"})
