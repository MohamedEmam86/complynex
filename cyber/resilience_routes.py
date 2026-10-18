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

"""IT resilience pages of the cyber module: BCP/DR, backups, integrations,
security assessments, security assets & licences, domains (TLS), maturity
self-assessment and the IT view of the ERM risk register."""

from datetime import date, datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from attachments.service import list_attachments
from database.db import get_db
from models.audit import AuditLog
from utils.decorators import permission_required

from . import cyber_bp as bp
from . import resilience as svc
from . import resilience_logic as logic

MODULE = 'cyber'
FILE_TYPES = {
    'cy_dr_test': ('cy_dr_tests', 'cyber.res_bcp'),
    'cy_backup': ('cy_backups', 'cyber.res_backups'),
    'cy_assessment': ('cy_assessments', 'cyber.res_assessments'),
    'cy_security_asset': ('cy_security_assets', 'cyber.res_assets'),
    'cy_integration': ('cy_integrations', 'cyber.res_integrations'),
}


def _log(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, MODULE, item_id, details, request.remote_addr)
    except Exception:
        get_db().rollback()


def _err(e):
    msg = str(e)
    flash(_(msg) if not any(c in msg for c in ':%"') else msg, 'danger')


def _edit_guard():
    if request.method == 'POST' and not current_user.can_edit(MODULE):
        abort(403)


def _int(v):
    try:
        return int(v) if v not in (None, '') else None
    except ValueError:
        return None


def _controls():
    rows = get_db().execute("""
        SELECT c.id, c.control_code, c.title_en, c.title_ar, c.check_key,
               (SELECT r.status FROM rc_control_runs r WHERE r.control_id = c.id ORDER BY r.id DESC LIMIT 1) AS last_status
        FROM rc_controls c WHERE c.is_active AND c.check_key IS NOT NULL
          AND (c.check_key LIKE 'core.cyber.%%' OR c.check_key = 'core.risk.register_fresh')
        ORDER BY c.control_code""").fetchall()
    return [dict(r) for r in rows]


@bp.context_processor
def _ctx():
    authed = getattr(current_user, 'is_authenticated', False)
    return {'cy_can_edit': authed and current_user.can_edit(MODULE), 'today': date.today(), 'now': datetime.now()}


@bp.route('/resilience/')
@login_required
@permission_required(MODULE)
def res_dashboard():
    db = get_db()
    warn = svc.param('it.ssl_expiry_warning_days', default=30)
    lic_warn = svc.param('it.licence_expiry_warning_days', default=30)
    doms = svc.domains(db)
    assets = svc.assets(db)
    return render_template('cyber/resilience/dashboard.html',
                           dr=logic.dr_issues(svc.sites(db), svc.dr_tests(db), None,
                                              svc.param('it.dr_test_max_age_months')),
                           backups_bad=sum(1 for b in svc.backups(db) if logic.backup_issues(
                               b, None, svc.param('it.offsite_backup_max_age_days'))),
                           backups=len(svc.backups(db)),
                           integ_bad=sum(1 for i in svc.integrations(db) if logic.integration_issue(i)),
                           integ=len(svc.integrations(db)),
                           certs_bad=sum(1 for d in doms if d['is_active'] and logic.cert_state(d, None, warn) != 'ok'),
                           certs=len(doms),
                           assets_bad=sum(1 for a in assets if logic.asset_state(a, None, lic_warn) in
                                          ('expired', 'expiring', 'no_licence')),
                           assets=len(assets), controls=_controls(), maturity=svc.maturity_assessments(db)[:3],
                           risks_stale=sum(1 for r in svc.it_risks(db=db) if logic.risk_stale(
                               r, None, svc.param('it.risk_register_max_age_days'))))


@bp.route('/resilience/bcp', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def res_bcp():
    _edit_guard()
    if request.method == 'POST':
        try:
            if request.form.get('form') == 'site':
                svc.save_site(request.form, current_user.id)
            else:
                tid = svc.add_dr_test(request.form, current_user.id)
                _log('cyber_dr_test_add', tid, request.form.get('result'))
                flash(_('DR test recorded. Attach the test report.'), 'success')
                return redirect(url_for('cyber.res_files', rtype='cy_dr_test', rid=tid))
            flash(_('Saved.'), 'success')
        except svc.ResilienceError as e:
            _err(e)
        return redirect(url_for('cyber.res_bcp'))
    return render_template('cyber/resilience/bcp.html', sites=svc.sites(), tests=svc.dr_tests(),
                           max_months=svc.param('it.dr_test_max_age_months'))


@bp.route('/resilience/backups', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def res_backups():
    _edit_guard()
    if request.method == 'POST':
        try:
            bid = svc.save_backup(request.form)
            _log('cyber_backup_save', bid)
            flash(_('Saved.'), 'success')
        except svc.ResilienceError as e:
            _err(e)
        return redirect(url_for('cyber.res_backups'))
    days = svc.param('it.offsite_backup_max_age_days')
    rows = [dict(b, issues=logic.backup_issues(b, None, days)) for b in svc.backups()]
    edit = next((b for b in rows if str(b['id']) == request.args.get('edit')), None)
    return render_template('cyber/resilience/backups.html', rows=rows, days=days, edit=edit)


@bp.route('/resilience/integrations', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def res_integrations():
    _edit_guard()
    if request.method == 'POST':
        try:
            if request.form.get('action') == 'exchange':
                svc.record_integration_exchange(request.form.get('code'), request.form.get('ok') == '1')
            else:
                svc.save_integration(request.form, current_user.id)
            _log('cyber_integration_save', None, request.form.get('code'))
            flash(_('Saved.'), 'success')
        except svc.ResilienceError as e:
            _err(e)
        return redirect(url_for('cyber.res_integrations'))
    rows = [dict(i, issue=logic.integration_issue(i)) for i in svc.integrations()]
    edit = next((i for i in rows if i['code'] == request.args.get('edit')), None)
    return render_template('cyber/resilience/integrations.html', rows=rows, edit=edit)


@bp.route('/resilience/assessments', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def res_assessments():
    _edit_guard()
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'accept':
                svc.accept_assessment(_int(request.form.get('assessment_id')), current_user.id)
                flash(_('Assessment accepted.'), 'success')
            elif action == 'open':
                svc.update_open_findings(_int(request.form.get('assessment_id')), request.form.get('critical_open'),
                                         request.form.get('high_open'))
                flash(_('Saved.'), 'success')
            else:
                aid = svc.add_assessment(request.form, current_user.id)
                _log('cyber_assessment_add', aid)
                flash(_('Saved. Attach the report, then accept it.'), 'success')
                return redirect(url_for('cyber.res_files', rtype='cy_assessment', rid=aid))
        except (svc.ResilienceError, ValueError) as e:
            _err(e)
        return redirect(url_for('cyber.res_assessments'))
    rows = svc.assessments()
    status = {}
    for t in sorted({r['assessment_type'] for r in rows}):
        status[t] = logic.assessment_issue([r for r in rows if r['assessment_type'] == t])
    return render_template('cyber/resilience/assessments.html', rows=rows, status=status)


@bp.route('/resilience/assets', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def res_assets():
    _edit_guard()
    if request.method == 'POST':
        try:
            aid = svc.save_asset(request.form, current_user.id, _int(request.form.get('asset_id')))
            _log('cyber_asset_save', aid)
            flash(_('Saved.'), 'success')
        except svc.ResilienceError as e:
            _err(e)
        return redirect(url_for('cyber.res_assets'))
    warn = svc.param('it.licence_expiry_warning_days', default=30)
    rows = [dict(a, state=logic.asset_state(a, None, warn), residency=logic.residency_issue(a)) for a in svc.assets()]
    edit = next((a for a in rows if str(a['id']) == request.args.get('edit')), None)
    return render_template('cyber/resilience/assets.html', rows=rows, warn=warn, edit=edit)


@bp.route('/resilience/domains', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def res_domains():
    _edit_guard()
    if request.method == 'POST':
        try:
            if request.form.get('action') == 'check':
                res = svc.check_domain(_int(request.form.get('domain_id')))
                flash(res['error'] or _('Certificate valid until %(d)s.', d=res['not_after']),
                      'danger' if res['error'] else 'success')
            elif request.form.get('action') == 'toggle':
                db = get_db()
                db.execute("UPDATE cy_domains SET is_active = NOT is_active WHERE id = %s", (_int(request.form.get('domain_id')),))
                db.commit()
            else:
                did = svc.add_domain(request.form.get('domain'), current_user.id, request.form.get('port') or 443)
                svc.check_domain(did)
                _log('cyber_domain_add', did, request.form.get('domain'))
                flash(_('Domain added and checked.'), 'success')
        except svc.ResilienceError as e:
            _err(e)
        return redirect(url_for('cyber.res_domains'))
    warn = svc.param('it.ssl_expiry_warning_days', default=30)
    rows = [dict(d, state=logic.cert_state(d, None, warn)) for d in svc.domains()]
    return render_template('cyber/resilience/domains.html', rows=rows, warn=warn)


@bp.route('/resilience/maturity', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def res_maturity():
    _edit_guard()
    db = get_db()
    if request.method == 'POST':
        try:
            aid = svc.start_maturity(_int(request.form.get('framework_id')), request.form.get('title'), current_user.id)
            return redirect(url_for('cyber.res_maturity_detail', assessment_id=aid))
        except svc.ResilienceError as e:
            _err(e)
        return redirect(url_for('cyber.res_maturity'))
    fws = [dict(r) for r in db.execute("""SELECT f.id, f.code, f.name_en, f.name_ar,
                                          (SELECT count(*) FROM rc_requirements q WHERE q.framework_id = f.id) AS n
                                          FROM rc_frameworks f WHERE f.is_active ORDER BY f.code""").fetchall()]
    return render_template('cyber/resilience/maturity.html', rows=svc.maturity_assessments(db), frameworks=fws)


@bp.route('/resilience/maturity/<int:assessment_id>', methods=['GET', 'POST'])
@login_required
@permission_required(MODULE)
def res_maturity_detail(assessment_id):
    _edit_guard()
    db = get_db()
    a = next((x for x in svc.maturity_assessments(db) if x['id'] == assessment_id), None)
    if not a:
        abort(404)
    scores = svc.maturity_scores(assessment_id, db)
    if request.method == 'POST':
        levels = {s['requirement_id']: (request.form.get(f"c_{s['requirement_id']}"), request.form.get(f"t_{s['requirement_id']}"),
                                        request.form.get(f"n_{s['requirement_id']}")) for s in scores}
        try:
            svc.save_maturity(assessment_id, levels, request.form.get('finalise') == '1', db)
            _log('cyber_maturity_save', assessment_id, request.form.get('finalise'))
            flash(_('Saved.'), 'success')
        except svc.ResilienceError as e:
            _err(e)
        return redirect(url_for('cyber.res_maturity_detail', assessment_id=assessment_id))
    return render_template('cyber/resilience/maturity_detail.html', a=a, scores=scores,
                           summary=logic.maturity_summary(scores))


@bp.route('/resilience/it-risks')
@login_required
@permission_required(MODULE)
def res_it_risks():
    cats = [c.strip().upper() for c in (request.args.get('categories') or 'TEC').split(',') if c.strip()]
    days = svc.param('it.risk_register_max_age_days')
    rows = [dict(r, stale=logic.risk_stale(r, None, days)) for r in svc.it_risks(cats)]
    return render_template('cyber/resilience/it_risks.html', rows=rows, days=days, cats=cats)


@bp.route('/resilience/files/<rtype>/<int:rid>')
@login_required
@permission_required(MODULE)
def res_files(rtype, rid):
    if rtype not in FILE_TYPES:
        abort(404)
    table, back = FILE_TYPES[rtype]
    rec = get_db().execute(f"SELECT * FROM {table} WHERE id = %s", (rid,)).fetchone()
    if not rec:
        abort(404)
    rec = dict(rec)
    label = rec.get('title') or rec.get('system_name') or rec.get('product') or rec.get('name') or f'#{rid}'
    return render_template('cyber/resilience/files.html', rec=rec, label=label, back=back, attach_module=MODULE,
                           attach_record_type=rtype, attach_record_id=rid,
                           attach_items=list_attachments(MODULE, rtype, rid),
                           attach_can_edit=current_user.can_edit(MODULE))
