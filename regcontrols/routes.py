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
UI for regcontrols: dashboard, control library, control runs, evidence,
findings & corrective actions, alerts, regulatory parameters.

Permission perm_regcontrols:
  view  — see everything in scope
  edit  — run controls, submit/review evidence, manage findings and actions
  admin — approve parameter changes, edit the control library, close a
          finding without remediation, settings
Records with an org_unit_id are filtered with services.org_service scoping.
"""

import json
from datetime import date, datetime
from functools import wraps

from flask import (abort, flash, redirect, render_template, request, url_for, Response)
from flask_babel import gettext as _
from flask_login import current_user, login_required

from database.db import get_db
from models.audit import AuditLog
from attachments.service import list_attachments

from . import regcontrols_bp as bp
from . import alerts as alerts_svc
from . import catalog, engine, evidence as evidence_svc, findings as findings_svc, logic, packs, params, vocab


MODULE = 'regcontrols'


# ------------------------------------------------------------------ helpers
def rc_required(level='view'):
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            ok = {'view': current_user.can_view, 'edit': current_user.can_edit,
                  'admin': current_user.can_admin_module}[level](MODULE)
            if not ok:
                flash(_('You do not have permission for this Regulatory Compliance action.'), 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def _scope(column):
    try:
        from services import org_service
        return org_service.scope_filter(column)
    except Exception:
        return '', ()


def _check_unit(row):
    if row and row.get('org_unit_id'):
        try:
            from services import org_service
            if not org_service.can_see_unit(row['org_unit_id']):
                abort(404)
        except ImportError:
            pass


def _units():
    try:
        from services import org_service
        return org_service.visible_units()
    except Exception:
        return []


def _users():
    return [dict(r) for r in get_db().execute(
        "SELECT id, first_name, last_name, email FROM users WHERE is_active = 1 "
        "ORDER BY first_name, last_name").fetchall()]


def _int(v):
    try:
        return int(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _date(v):
    try:
        return logic._as_date(v) if v else None
    except ValueError:
        return None


def _flash_error(e):
    flash(_(str(e)), 'danger')


def _log(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, MODULE, item_id, details, request.remote_addr)
    except Exception:
        get_db().rollback()


class _Vocab:
    """Vocabularies for templates: fixed ones from vocab.py, regulator/sector
    specific ones (areas, licence types, owner roles) from the database,
    loaded once per request."""
    CONTROL_TYPES = vocab.CONTROL_TYPES
    FREQUENCIES = vocab.FREQUENCIES
    CRITICALITY = vocab.CRITICALITY

    def _db(self, kind):
        from flask import g
        cache = g.setdefault('_rc_vocab', {})
        if kind not in cache:
            try:
                cache[kind] = catalog.ref_labels(kind)
            except Exception:
                get_db().rollback()
                cache[kind] = {}
        return cache[kind]

    @property
    def AREAS(self):
        return self._db('areas')

    @property
    def LICENCE_TYPES(self):
        return self._db('licence_types')

    @property
    def OWNER_ROLES(self):
        return self._db('owner_roles')


VOCAB = _Vocab()


@bp.app_template_global('rc_label')
def rc_label(vocab_name, code):
    """Localised label from a vocabulary, e.g. rc_label('AREAS', c.area)."""
    from flask_babel import get_locale
    pair = getattr(VOCAB, vocab_name, {}).get(code)
    if not pair:
        return (code or '').replace('_', ' ')
    return pair[1] if str(get_locale()).startswith('ar') else pair[0]


@bp.app_template_global('rc_loc')
def rc_loc(en, ar):
    from flask_babel import get_locale
    return (ar or en) if str(get_locale()).startswith('ar') else (en or ar)


@bp.app_template_global('rc_evidence_state')
def rc_evidence_state(item, warn_days=30):
    return logic.evidence_state(item, date.today(), warn_days)


@bp.app_template_global('rc_pack_menus')
def rc_pack_menus():
    """Sidebar groups of enabled content packs for the current user."""
    try:
        return packs.menus(current_user) if getattr(current_user, 'is_authenticated', False) else []
    except Exception:
        get_db().rollback()
        return []


@bp.app_template_global('rc_pack_permission_modules')
def rc_pack_permission_modules():
    try:
        return packs.permission_modules()
    except Exception:
        return []


@bp.app_template_global('rc_user_module_perm')
def rc_user_module_perm(user, module):
    try:
        return packs.get_module_perms(user.id).get(module, 'none')
    except Exception:
        return 'none'


@bp.context_processor
def _inject():
    if not getattr(current_user, 'is_authenticated', False):
        return {'rc_vocab': VOCAB, 'rc_can_edit': False, 'rc_can_admin': False, 'today': date.today()}
    return {'rc_vocab': VOCAB, 'rc_can_edit': current_user.can_edit(MODULE),
            'rc_can_admin': current_user.can_admin_module(MODULE), 'today': date.today()}


# ------------------------------------------------------------------ dashboard
@bp.route('/')
@rc_required('view')
def dashboard():
    db = get_db()
    controls = [dict(r) for r in db.execute(
        "SELECT * FROM rc_controls WHERE is_active ORDER BY control_code").fetchall()]
    status_counts = {}
    for c in controls:
        key = c['last_status'] or 'not_run'
        status_counts[key] = status_counts.get(key, 0) + 1
    by_area = {}
    for c in controls:
        a = by_area.setdefault(c['area'], {'total': 0, 'pass': 0, 'fail': 0, 'warning': 0, 'other': 0})
        a['total'] += 1
        s = c['last_status']
        a[s if s in ('pass', 'fail', 'warning') else 'other'] += 1
    failing = [c for c in controls if c['last_status'] in ('fail', 'error')]
    sql, args = _scope('f.org_unit_id')
    open_findings = findings_svc.list_findings(status='open', scope_sql=sql, scope_args=args)
    ev_sql, ev_args = _scope('e.org_unit_id')
    evidence_rows = evidence_svc.list_all(scope_sql=ev_sql, scope_args=ev_args)
    expiring = [e for e in evidence_rows if e['state'] in ('expiring', 'expired')][:10]
    pending_review = [e for e in evidence_rows if e['state'] == 'pending']
    al_sql, al_args = _scope('a.org_unit_id')
    open_alerts = db.execute(f"SELECT count(*) AS n FROM rc_alerts a WHERE a.status IN ('open', 'acknowledged') {al_sql}",
                             al_args).fetchone()['n']
    pending_params = db.execute("SELECT count(*) AS n FROM rc_parameter_changes WHERE status = 'pending'").fetchone()['n']
    review_params = db.execute("SELECT count(*) AS n FROM rc_parameters WHERE needs_review AND status = 'active'"
                               ).fetchone()['n']
    fw_rows = []
    for fw in catalog.frameworks(active_only=True, db=db):
        st = [r['last_status'] for r in db.execute("""
            SELECT DISTINCT c.id, c.last_status FROM rc_controls c JOIN rc_control_requirements cr ON cr.control_id = c.id
            JOIN rc_requirements q ON q.id = cr.requirement_id WHERE q.framework_id = %s AND c.is_active""",
                                                           (fw['id'],)).fetchall()]
        fw_rows.append(dict(fw, passing=st.count('pass'), failing=sum(1 for x in st if x in ('fail', 'error')),
                            not_run=st.count(None)))
    return render_template(
        'regcontrols/dashboard.html', frameworks=fw_rows, controls=controls, status_counts=status_counts, by_area=by_area,
        failing=failing, open_findings=open_findings, ageing=findings_svc.ageing_summary(open_findings),
        repeated=[f for f in open_findings if f['is_repeated']],
        overdue=[f for f in open_findings if f['overdue']],
        expiring=expiring, pending_review=pending_review, open_alerts=open_alerts,
        pending_params=pending_params, review_params=review_params,
        licence_type=engine.company_licence_type())


@bp.route('/run-due', methods=['POST'])
@rc_required('admin')
def run_due():
    job = engine.enqueue_due()
    if job:
        flash(_('Scheduled run queued. Results appear as each control finishes.'), 'info')
    else:
        engine.run_sweeps()
        counts = engine.run_due()
        evidence_svc.sweep_expiry()
        findings_svc.sweep_overdue()
        alerts_svc.sweep_escalations()
        flash(_('Due controls run: %(n)s.', n=sum(counts.values())), 'success')
    _log('regcontrols_run_due')
    return redirect(url_for('regcontrols.dashboard'))


# ------------------------------------------------------------------ controls
@bp.route('/controls')
@rc_required('view')
def controls():
    db = get_db()
    area, status, ctype, q = (request.args.get(k) or '' for k in ('area', 'status', 'type', 'q'))
    fw = request.args.get('framework') or ''
    clauses, args = ['1=1'], []
    if fw:
        clauses.append('''EXISTS (SELECT 1 FROM rc_control_requirements cr JOIN rc_requirements q
                                  ON q.id = cr.requirement_id WHERE cr.control_id = c.id AND q.framework_id = %s)''')
        args.append(int(fw) if fw.isdigit() else 0)
    if area:
        clauses.append('c.area = %s')
        args.append(area)
    if ctype:
        clauses.append('c.control_type = %s')
        args.append(ctype)
    if status == 'not_run':
        clauses.append('c.last_status IS NULL')
    elif status:
        clauses.append('c.last_status = %s')
        args.append(status)
    if q:
        clauses.append("(c.control_code ILIKE %s OR c.title_en ILIKE %s OR c.title_ar ILIKE %s)")
        args += [f'%{q}%'] * 3
    rows = [dict(r) for r in db.execute(f"""
        SELECT c.*, u.first_name || ' ' || u.last_name AS owner_name,
               (SELECT count(*) FROM rc_finding_controls fc JOIN rc_findings f ON f.id = fc.finding_id
                 WHERE fc.control_id = c.id AND f.status <> 'closed') AS open_findings
        FROM rc_controls c LEFT JOIN users u ON u.id = c.owner_user_id
        WHERE {' AND '.join(clauses)} ORDER BY c.control_code
    """, tuple(args)).fetchall()]
    engine.load_checks()
    return render_template('regcontrols/controls.html', controls=rows, checks=engine.CHECKS,
                           f_area=area, f_status=status, f_type=ctype, q=q, f_framework=fw,
                           frameworks=catalog.frameworks())


@bp.route('/controls/<int:control_id>')
@rc_required('view')
def control_detail(control_id):
    db = get_db()
    control = engine.get_control(control_id, db)
    if not control:
        abort(404)
    lic = engine.company_licence_type()
    linked_params = []
    for key in control['linked_params'] or []:
        rec = params.get_param_record(key, lic)
        linked_params.append({'key': key, 'rec': rec})
    engine.load_checks()
    owner = db.execute("SELECT first_name, last_name FROM users WHERE id = %s",
                       (control['owner_user_id'],)).fetchone() if control['owner_user_id'] else None
    al_sql, al_args = _scope('a.org_unit_id')
    alerts = [dict(r) for r in db.execute(
        f"SELECT a.* FROM rc_alerts a WHERE a.control_id = %s {al_sql} ORDER BY a.raised_at DESC LIMIT 20",
        (control_id, *al_args)).fetchall()]
    sql, args = _scope('f.org_unit_id')
    erm = None
    if control['erm_control_id']:
        erm = db.execute("SELECT id, control_code, control_name FROM controls WHERE id = %s",
                         (control['erm_control_id'],)).fetchone()
    return render_template(
        'regcontrols/control_detail.html', control=control, owner=owner, linked_params=linked_params,
        check=engine.CHECKS.get(control['check_key']) if control['check_key'] else None,
        runs=engine.latest_runs(control_id), requirements=catalog.control_requirements(control_id),
        all_requirements=([(fw, catalog.requirements(fw['id'])) for fw in catalog.frameworks(active_only=True)]
                          if current_user.can_admin_module(MODULE) else []),
        evidence=evidence_svc.list_for_control(control_id), warn_days=params.get_param(
            'rc.evidence_expiry_warning_days', default=30),
        findings=findings_svc.list_findings(control_id=control_id, scope_sql=sql, scope_args=args),
        alerts=alerts, erm=erm, licence_type=lic)


@bp.route('/controls/<int:control_id>/run', methods=['POST'])
@rc_required('edit')
def control_run(control_id):
    control = engine.get_control(control_id)
    if not control:
        abort(404)
    if request.form.get('inline') or not engine.enqueue_run(control['control_code'], current_user.id):
        run = engine.run_control(control, triggered_by='manual', user_id=current_user.id)
        flash(_('Control run finished: %(status)s', status=run['status']),
              'success' if run['status'] == 'pass' else 'warning')
    else:
        flash(_('Control run queued. Refresh in a moment to see the result.'), 'info')
    _log('regcontrols_run_control', control_id, control['control_code'])
    return redirect(url_for('regcontrols.control_detail', control_id=control_id))


@bp.route('/controls/<int:control_id>/edit', methods=['GET', 'POST'])
@rc_required('admin')
def control_edit(control_id):
    db = get_db()
    control = engine.get_control(control_id, db)
    if not control:
        abort(404)
    if request.method == 'POST':
        f = request.form
        freq = f.get('frequency')
        crit = f.get('criticality')
        if freq not in vocab.FREQUENCIES or crit not in vocab.CRITICALITY:
            flash(_('Invalid frequency or criticality.'), 'danger')
            return redirect(request.url)
        lics = [x for x in f.getlist('licence_types') if x in VOCAB.LICENCE_TYPES] or ['all']
        check_key = f.get('check_key') or None
        if check_key and check_key not in engine.CHECKS:
            flash(_('Unknown check.'), 'danger')
            return redirect(request.url)
        try:
            check_config = json.loads(f.get('check_config') or '{}')
            if not isinstance(check_config, dict):
                raise ValueError
        except ValueError:
            flash(_('Check settings must be a JSON object, e.g. {"fields": ["gender"]}.'), 'danger')
            return redirect(request.url)
        keys = [k.strip() for k in (f.get('linked_params') or '').replace(';', ',').split(',') if k.strip()]
        db.execute("""
            UPDATE rc_controls SET check_key = %s, check_config = %s, area = %s, control_type = %s,
                   title_en = %s, title_ar = %s, requirement_en = %s, requirement_ar = %s,
                   frequency = %s, criticality = %s, owner_role = %s, owner_user_id = %s, linked_module = %s,
                   linked_params = %s, licence_types = %s, test_procedure_en = %s, test_procedure_ar = %s,
                   erm_control_id = %s, auto_create_case = %s, is_active = %s, updated_at = %s,
                   next_run_due = CASE WHEN frequency = %s THEN next_run_due ELSE NULL END
            WHERE id = %s
        """, (check_key, json.dumps(check_config), f.get('area') or None,
              f.get('control_type') if f.get('control_type') in vocab.CONTROL_TYPES else control['control_type'],
              f.get('title_en', '').strip() or control['title_en'], f.get('title_ar', '').strip() or None,
              f.get('requirement_en') or None, f.get('requirement_ar') or None, freq, crit,
              f.get('owner_role') or None, _int(f.get('owner_user_id')), f.get('linked_module') or None,
              keys, lics, f.get('test_procedure_en') or None, f.get('test_procedure_ar') or None,
              _int(f.get('erm_control_id')), bool(f.get('auto_create_case')), bool(f.get('is_active')),
              datetime.now(), freq, control_id))
        db.commit()
        _log('regcontrols_control_edit', control_id, control['control_code'])
        flash(_('Control updated.'), 'success')
        return redirect(url_for('regcontrols.control_detail', control_id=control_id))
    erm_controls = [dict(r) for r in db.execute(
        "SELECT id, control_code, control_name FROM controls WHERE status = 'ACTIVE' ORDER BY control_code"
    ).fetchall()]
    return render_template('regcontrols/control_form.html', control=control, users=_users(),
                           erm_controls=erm_controls, checks=engine.check_catalogue())


@bp.route('/runs/<int:run_id>')
@rc_required('view')
def run_detail(run_id):
    db = get_db()
    run = db.execute("""
        SELECT r.*, c.control_code, c.title_en, c.title_ar, u.first_name || ' ' || u.last_name AS run_by_name
        FROM rc_control_runs r JOIN rc_controls c ON c.id = r.control_id LEFT JOIN users u ON u.id = r.run_by
        WHERE r.id = %s""", (run_id,)).fetchone()
    if not run:
        abort(404)
    run = dict(run)
    _check_unit(run)
    return render_template('regcontrols/run_detail.html', run=run)


# ------------------------------------------------------------------ evidence
@bp.route('/evidence')
@rc_required('view')
def evidence_list():
    sql, args = _scope('e.org_unit_id')
    state = request.args.get('state') or None
    return render_template('regcontrols/evidence_list.html',
                           items=evidence_svc.list_all(state, sql, args), f_state=state or '')


@bp.route('/controls/<int:control_id>/evidence/new', methods=['GET', 'POST'])
@rc_required('edit')
def evidence_new(control_id):
    control = engine.get_control(control_id)
    if not control:
        abort(404)
    if request.method == 'POST':
        f = request.form
        try:
            ev_id = evidence_svc.record_evidence(
                control, f.get('title'), valid_from=_date(f.get('valid_from')), valid_to=_date(f.get('valid_to')),
                description=f.get('description') or None, reference_no=f.get('reference_no') or None,
                submitted_by=current_user.id, org_unit_id=_int(f.get('org_unit_id')))
        except evidence_svc.EvidenceError as e:
            _flash_error(e)
            return redirect(request.url)
        _log('regcontrols_evidence_add', ev_id, control['control_code'])
        flash(_('Evidence recorded. Attach the supporting file below, then ask a reviewer to approve it.'),
              'success')
        return redirect(url_for('regcontrols.evidence_detail', evidence_id=ev_id))
    return render_template('regcontrols/evidence_form.html', control=control, units=_units())


@bp.route('/evidence/<int:evidence_id>')
@rc_required('view')
def evidence_detail(evidence_id):
    item = evidence_svc.get(evidence_id)
    if not item:
        abort(404)
    _check_unit(item)
    item['state'] = logic.evidence_state(item, date.today(),
                                         params.get_param('rc.evidence_expiry_warning_days', default=30))
    can_edit = current_user.can_edit(MODULE)
    return render_template(
        'regcontrols/evidence_detail.html', item=item,
        attach_module='regcontrols', attach_record_type=evidence_svc.ATTACH_TYPE, attach_record_id=item['id'],
        attach_items=list_attachments('regcontrols', evidence_svc.ATTACH_TYPE, item['id']),
        attach_can_edit=can_edit and item['status'] == 'pending')


@bp.route('/evidence/<int:evidence_id>/review', methods=['POST'])
@rc_required('edit')
def evidence_review(evidence_id):
    item = evidence_svc.get(evidence_id)
    if not item:
        abort(404)
    _check_unit(item)
    decision = request.form.get('decision')
    if decision == 'approved' and not list_attachments('regcontrols', evidence_svc.ATTACH_TYPE, evidence_id) \
            and not request.form.get('no_file_ok'):
        flash(_('No file is attached. Attach the evidence file, or tick the box to confirm it is held elsewhere.'),
              'warning')
        return redirect(url_for('regcontrols.evidence_detail', evidence_id=evidence_id))
    try:
        evidence_svc.review(evidence_id, current_user.id, decision, request.form.get('comment'))
    except evidence_svc.EvidenceError as e:
        _flash_error(e)
    else:
        _log('regcontrols_evidence_review', evidence_id, decision)
        flash(_('Evidence review saved.'), 'success')
    return redirect(url_for('regcontrols.evidence_detail', evidence_id=evidence_id))


# ------------------------------------------------------------------ findings
@bp.route('/findings')
@rc_required('view')
def findings():
    sql, args = _scope('f.org_unit_id')
    status, source, severity = (request.args.get(k) or '' for k in ('status', 'source', 'severity'))
    repeated = bool(request.args.get('repeated'))
    rows = findings_svc.list_findings(status=status or None, source=source or None, severity=severity or None,
                                      repeated=repeated, scope_sql=sql, scope_args=args)
    all_open = findings_svc.list_findings(status='open', scope_sql=sql, scope_args=args)
    return render_template('regcontrols/findings.html', findings=rows, ageing=findings_svc.ageing_summary(all_open),
                           f_status=status, f_source=source, f_severity=severity, f_repeated=repeated,
                           sources=logic.FINDING_SOURCES, severities=logic.SEVERITIES)


@bp.route('/findings/new', methods=['GET', 'POST'])
@rc_required('edit')
def finding_new():
    db = get_db()
    if request.method == 'POST':
        f = request.form
        codes = [c for c in (f.get('control_codes') or '').replace(',', ';').split(';') if c.strip()]
        try:
            fid = findings_svc.raise_finding(
                f.get('title'), source=f.get('source') or 'self_identified', severity=f.get('severity') or 'medium',
                description=f.get('description') or None, source_ref=f.get('source_ref') or None,
                area=f.get('area') or None, control_codes=codes, owner_user_id=_int(f.get('owner_user_id')),
                due_date=_date(f.get('due_date')), identified_date=_date(f.get('identified_date')),
                org_unit_id=_int(f.get('org_unit_id')), created_by=current_user.id)
        except findings_svc.FindingError as e:
            _flash_error(e)
            return render_template('regcontrols/finding_form.html', form=f, users=_users(), units=_units(),
                                   sources=logic.FINDING_SOURCES, severities=logic.SEVERITIES)
        _log('regcontrols_finding_add', fid)
        flash(_('Finding recorded. Add the corrective action plan next.'), 'success')
        return redirect(url_for('regcontrols.finding_detail', finding_id=fid))
    pre = {}
    if request.args.get('control'):
        c = engine.get_control(request.args['control'], db)
        if c:
            pre = {'control_codes': c['control_code'], 'area': c['area'], 'severity': c['criticality'],
                   'title': c['title_en']}
    return render_template('regcontrols/finding_form.html', form=pre, users=_users(), units=_units(),
                           sources=logic.FINDING_SOURCES, severities=logic.SEVERITIES)


@bp.route('/findings/<int:finding_id>')
@rc_required('view')
def finding_detail(finding_id):
    f = findings_svc.get_finding(finding_id)
    if not f:
        abort(404)
    _check_unit(f)
    action_files = {a['id']: list_attachments('regcontrols', 'rc_action', a['id']) for a in f['actions']}
    return render_template('regcontrols/finding_detail.html', f=f, users=_users(), action_files=action_files,
                           attach_module='regcontrols', attach_record_type='rc_finding', attach_record_id=f['id'],
                           attach_items=list_attachments('regcontrols', 'rc_finding', f['id']),
                           attach_can_edit=current_user.can_edit(MODULE))


def _finding_or_404(finding_id):
    f = get_db().execute("SELECT * FROM rc_findings WHERE id = %s", (finding_id,)).fetchone()
    if not f:
        abort(404)
    f = dict(f)
    _check_unit(f)
    return f


@bp.route('/findings/<int:finding_id>/edit', methods=['POST'])
@rc_required('edit')
def finding_edit(finding_id):
    _finding_or_404(finding_id)
    f = request.form
    sev = f.get('severity')
    if sev not in logic.SEVERITIES:
        flash(_('Invalid severity.'), 'danger')
        return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))
    findings_svc.update_finding(finding_id, current_user.id, title=f.get('title') or None,
                                description=f.get('description') or None, severity=sev,
                                owner_user_id=_int(f.get('owner_user_id')), due_date=_date(f.get('due_date')),
                                source_ref=f.get('source_ref') or None)
    _log('regcontrols_finding_edit', finding_id)
    flash(_('Finding updated.'), 'success')
    return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))


@bp.route('/findings/<int:finding_id>/controls', methods=['POST'])
@rc_required('edit')
def finding_link(finding_id):
    _finding_or_404(finding_id)
    codes = [c for c in (request.form.get('control_codes') or '').replace(',', ';').split(';') if c.strip()]
    try:
        findings_svc.link_controls(finding_id, control_codes=codes)
        findings_svc.add_event(finding_id, 'controls_linked', ', '.join(c.strip().upper() for c in codes),
                               current_user.id)
        get_db().commit()
        flash(_('Controls linked.'), 'success')
    except findings_svc.FindingError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))


@bp.route('/findings/<int:finding_id>/controls/<int:control_id>/unlink', methods=['POST'])
@rc_required('edit')
def finding_unlink(finding_id, control_id):
    _finding_or_404(finding_id)
    findings_svc.unlink_control(finding_id, control_id)
    findings_svc.add_event(finding_id, 'control_unlinked', str(control_id), current_user.id)
    get_db().commit()
    return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))


@bp.route('/findings/<int:finding_id>/actions', methods=['POST'])
@rc_required('edit')
def action_add(finding_id):
    _finding_or_404(finding_id)
    f = request.form
    try:
        findings_svc.add_action(finding_id, f.get('description'), owner_user_id=_int(f.get('owner_user_id')),
                                due_date=_date(f.get('due_date')), created_by=current_user.id)
        flash(_('Corrective action added.'), 'success')
    except findings_svc.FindingError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))


@bp.route('/actions/<int:action_id>/status', methods=['POST'])
@rc_required('edit')
def action_status(action_id):
    row = get_db().execute("SELECT finding_id FROM rc_corrective_actions WHERE id = %s", (action_id,)).fetchone()
    if not row:
        abort(404)
    _finding_or_404(row['finding_id'])
    try:
        findings_svc.set_action_status(action_id, request.form.get('status'), current_user.id,
                                       request.form.get('note') or None)
        flash(_('Action updated.'), 'success')
    except findings_svc.FindingError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.finding_detail', finding_id=row['finding_id']))


@bp.route('/findings/<int:finding_id>/request-verification', methods=['POST'])
@rc_required('edit')
def finding_request_verification(finding_id):
    _finding_or_404(finding_id)
    try:
        findings_svc.request_verification(finding_id, current_user.id)
        flash(_('Sent for verification.'), 'success')
    except findings_svc.FindingError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))


@bp.route('/findings/<int:finding_id>/verify', methods=['POST'])
@rc_required('edit')
def finding_verify(finding_id):
    _finding_or_404(finding_id)
    try:
        outcome, runs = findings_svc.verify(finding_id, current_user.id, request.form.get('manual_note'))
    except findings_svc.FindingError as e:
        _flash_error(e)
        return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))
    messages = {
        'verified': (_('All linked controls passed. The finding is closed.'), 'success'),
        'manual_closed': (_('Closed on manual verification.'), 'success'),
        'manual': (_('The linked controls have no automated or evidence check. Enter how you verified the fix '
                     'and verify again.'), 'warning'),
        'failed': (_('A linked control still fails. The finding stays open.'), 'danger'),
        'inconclusive': (_('Re-test inconclusive (warnings). Resolve them and verify again.'), 'warning'),
    }
    msg, cat = messages.get(outcome, (outcome, 'info'))
    flash(msg, cat)
    _log('regcontrols_finding_verify', finding_id, outcome)
    return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))


@bp.route('/findings/<int:finding_id>/close', methods=['POST'])
@rc_required('admin')
def finding_close(finding_id):
    _finding_or_404(finding_id)
    try:
        findings_svc.close_without_remediation(finding_id, current_user.id, request.form.get('closure_type'),
                                               request.form.get('note'))
        _log('regcontrols_finding_close', finding_id, request.form.get('closure_type'))
        flash(_('Finding closed.'), 'success')
    except findings_svc.FindingError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.finding_detail', finding_id=finding_id))


@bp.route('/findings/import', methods=['GET', 'POST'])
@rc_required('edit')
def findings_import():
    errors, preview = [], None
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash(_('Choose a CSV file.'), 'warning')
            return redirect(request.url)
        raw = file.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            flash(_('The file is larger than 2 MB.'), 'danger')
            return redirect(request.url)
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            flash(_('The file must be UTF-8 encoded CSV.'), 'danger')
            return redirect(request.url)
        known = [r['control_code'] for r in get_db().execute("SELECT control_code FROM rc_controls").fetchall()]
        rows, errors = logic.parse_findings_csv(text, known)
        if not errors and rows:
            created, skipped = findings_svc.import_rows(rows, current_user.id)
            _log('regcontrols_findings_import', None, f'created={created} skipped={skipped}')
            flash(_('%(c)s finding(s) imported, %(s)s already existed.', c=created, s=skipped), 'success')
            return redirect(url_for('regcontrols.findings'))
        if not rows and not errors:
            errors = [(0, 'the file has no data rows')]
        preview = rows
    return render_template('regcontrols/findings_import.html', errors=errors, preview=preview,
                           columns=logic.FINDING_CSV_COLUMNS)


@bp.route('/findings/import/template.csv')
@rc_required('view')
def findings_import_template():
    return Response('﻿' + logic.findings_csv_template(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=regcontrols_findings_template.csv'})


@bp.route('/findings/import-internal-audit', methods=['POST'])
@rc_required('edit')
def findings_import_ia():
    n = findings_svc.import_from_internal_audit(current_user.id)
    _log('regcontrols_findings_import_ia', None, f'created={n}')
    flash(_('%(n)s internal-audit finding(s) imported.', n=n), 'success')
    return redirect(url_for('regcontrols.findings'))


# ------------------------------------------------------------------ alerts
@bp.route('/alerts')
@rc_required('view')
def alerts():
    db = get_db()
    status = request.args.get('status') or 'live'
    sql, args = _scope('a.org_unit_id')
    where = "a.status IN ('open', 'acknowledged')" if status == 'live' else 'a.status = %s'
    q_args = () if status == 'live' else (status,)
    rows = [dict(r) for r in db.execute(f"""
        SELECT a.*, c.control_code, f.reference AS finding_ref, u.first_name || ' ' || u.last_name AS owner_name
        FROM rc_alerts a LEFT JOIN rc_controls c ON c.id = a.control_id
        LEFT JOIN rc_findings f ON f.id = a.finding_id LEFT JOIN users u ON u.id = a.owner_user_id
        WHERE {where} {sql} ORDER BY a.raised_at DESC LIMIT 500
    """, q_args + tuple(args)).fetchall()]
    return render_template('regcontrols/alerts.html', alerts=rows, f_status=status)


def _alert_or_404(alert_id):
    a = get_db().execute("SELECT * FROM rc_alerts WHERE id = %s", (alert_id,)).fetchone()
    if not a:
        abort(404)
    a = dict(a)
    _check_unit(a)
    return a


@bp.route('/alerts/<int:alert_id>/ack', methods=['POST'])
@rc_required('edit')
def alert_ack(alert_id):
    _alert_or_404(alert_id)
    alerts_svc.acknowledge(alert_id, current_user.id)
    return redirect(request.referrer or url_for('regcontrols.alerts'))


@bp.route('/alerts/<int:alert_id>/resolve', methods=['POST'])
@rc_required('edit')
def alert_resolve(alert_id):
    _alert_or_404(alert_id)
    note = (request.form.get('note') or '').strip()
    if not note:
        flash(_('Enter a short resolution note.'), 'warning')
    else:
        alerts_svc.resolve(alert_id, current_user.id, note)
        _log('regcontrols_alert_resolve', alert_id)
    return redirect(request.referrer or url_for('regcontrols.alerts'))


# ------------------------------------------------------------------ parameters
@bp.route('/parameters')
@rc_required('view')
def parameters():
    q = request.args.get('q') or ''
    review = request.args.get('review')
    lic = request.args.get('licence') or ''
    rows = params.list_current(q or None, True if review == '1' else None, lic or None)
    from models.settings import Settings
    return render_template('regcontrols/parameters.html', params=rows, q=q, f_review=review or '', f_licence=lic,
                           pending=params.pending_changes(), licence_type=engine.company_licence_type(),
                           heads=Settings.get('regcontrols_compliance_head_ids', '') or '', users=_users())


@bp.route('/parameters/<int:param_id>')
@rc_required('view')
def parameter_detail(param_id):
    p = params.get_parameter(param_id)
    if not p:
        abort(404)
    versions = [v for v in params.get_versions(p['param_key']) if v['licence_type'] == p['licence_type']]
    current = logic.select_param(versions, p['licence_type'])
    return render_template('regcontrols/parameter_detail.html', p=p, versions=versions, current=current,
                           history=params.history(p['param_key'], p['licence_type']),
                           used_by=[dict(r) for r in get_db().execute(
                               "SELECT id, control_code, title_en, title_ar FROM rc_controls "
                               "WHERE %s = ANY(linked_params) ORDER BY control_code", (p['param_key'],)).fetchall()])


@bp.route('/parameters/new', methods=['GET', 'POST'])
@bp.route('/parameters/<int:param_id>/change', methods=['GET', 'POST'])
@rc_required('admin')
def parameter_change(param_id=None):
    p = params.get_parameter(param_id) if param_id else None
    if param_id and not p:
        abort(404)
    if request.method == 'POST':
        f = request.form
        change_type = f.get('change_type') or ('update' if p else 'create')
        try:
            cid = params.propose_change(
                key=f.get('param_key') or (p or {}).get('param_key'),
                licence_type=f.get('licence_type') or (p or {}).get('licence_type') or 'all',
                change_type=change_type, reason=f.get('reason'), requested_by=current_user.id,
                new_value=f.get('value_text'), value_type=f.get('value_type') or None, unit=f.get('unit') or None,
                effective_from=_date(f.get('effective_from')), effective_to=_date(f.get('effective_to')),
                legal_reference=f.get('legal_reference') or None, description_en=f.get('description_en') or None,
                description_ar=f.get('description_ar') or None, needs_review=bool(f.get('needs_review')),
                review_note=f.get('review_note') or None, parameter_id=param_id)
        except params.ChangeError as e:
            _flash_error(e)
            return render_template('regcontrols/parameter_form.html', p=p, form=f, value_types=params.VALUE_TYPES)
        _log('regcontrols_param_propose', cid, f'{change_type} {(p or {}).get("param_key") or f.get("param_key")}')
        flash(_('Change submitted. A second administrator must approve it before it takes effect.'), 'success')
        return redirect(url_for('regcontrols.parameters'))
    return render_template('regcontrols/parameter_form.html', p=p, form=(p or {}), value_types=params.VALUE_TYPES)


@bp.route('/parameters/changes/<int:change_id>/<decision>', methods=['POST'])
@rc_required('admin')
def parameter_decide(change_id, decision):
    try:
        if decision == 'approve':
            params.approve_change(change_id, current_user.id, request.form.get('comment') or None)
            flash(_('Change approved and applied.'), 'success')
        elif decision == 'reject':
            params.reject_change(change_id, current_user.id, request.form.get('comment'))
            flash(_('Change rejected.'), 'info')
        else:
            abort(400)
    except params.ChangeError as e:
        _flash_error(e)
    else:
        _log(f'regcontrols_param_{decision}', change_id)
    return redirect(request.referrer or url_for('regcontrols.parameters'))


@bp.route('/settings', methods=['POST'])
@rc_required('admin')
def settings_save():
    from models.settings import Settings
    lic = request.form.get('rc_licence_type')
    if lic in VOCAB.LICENCE_TYPES:
        Settings.set('rc_licence_type', lic, 'Licence type used to select regulatory parameter values')
    heads = ','.join(str(int(x)) for x in request.form.getlist('compliance_heads') if str(x).isdigit())
    Settings.set('regcontrols_compliance_head_ids', heads, 'Users who receive regcontrols escalations')
    _log('regcontrols_settings', None, f'licence={lic} heads={heads}')
    flash(_('Settings saved.'), 'success')
    return redirect(url_for('regcontrols.parameters'))


# ------------------------------------------------------------------ manual tests & new controls
@bp.route('/controls/<int:control_id>/test', methods=['POST'])
@rc_required('edit')
def control_test(control_id):
    try:
        engine.record_manual_test(control_id, request.form.get('status'), request.form.get('note'), current_user.id)
        _log('regcontrols_manual_test', control_id, request.form.get('status'))
        flash(_('Test result recorded.'), 'success')
    except ValueError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.control_detail', control_id=control_id))


@bp.route('/controls/new', methods=['GET', 'POST'])
@rc_required('admin')
def control_new():
    if request.method == 'POST':
        try:
            cid = catalog.create_control(request.form)
            req_id = _int(request.form.get('requirement_id'))
            if req_id:
                catalog.map_control(cid, req_id)
            _log('regcontrols_control_new', cid, request.form.get('control_code'))
            flash(_('Control created. Complete its settings below.'), 'success')
            return redirect(url_for('regcontrols.control_edit', control_id=cid))
        except catalog.CatalogError as e:
            _flash_error(e)
    req = None
    if request.args.get('requirement'):
        req = get_db().execute("SELECT q.*, f.code AS framework_code FROM rc_requirements q JOIN rc_frameworks f "
                               "ON f.id = q.framework_id WHERE q.id = %s", (_int(request.args['requirement']),)).fetchone()
    return render_template('regcontrols/control_new.html', form=request.form, req=dict(req) if req else None)


@bp.route('/controls/<int:control_id>/requirements', methods=['POST'])
@rc_required('admin')
def control_map(control_id):
    req_id = _int(request.form.get('requirement_id'))
    if req_id:
        catalog.map_control(control_id, req_id, linked=request.form.get('action') != 'unlink')
        _log('regcontrols_control_map', control_id, f"{request.form.get('action') or 'link'} {req_id}")
    return redirect(url_for('regcontrols.control_detail', control_id=control_id))


@bp.route('/requirements.json')
@rc_required('view')
def requirements_json():
    from flask import jsonify
    fid = _int(request.args.get('framework'))
    return jsonify([{'id': r['id'], 'ref': r['ref_code'], 'title': rc_loc(r['title_en'], r['title_ar'])}
                    for r in (catalog.requirements(fid) if fid else [])])


# ------------------------------------------------------------------ library: frameworks & requirements
@bp.route('/library')
@rc_required('view')
def library_home():
    return render_template('regcontrols/library.html', frameworks=catalog.frameworks(),
                           regulators=catalog.regulators(),
                           refs={k: catalog.ref_list(k) for k in catalog.REF_TABLES})


@bp.route('/library/frameworks/new', methods=['GET', 'POST'])
@bp.route('/library/frameworks/<int:framework_id>/edit', methods=['GET', 'POST'])
@rc_required('admin')
def framework_edit(framework_id=None):
    fw = catalog.framework(framework_id) if framework_id else None
    if framework_id and not fw:
        abort(404)
    if request.method == 'POST':
        data = request.form.to_dict()
        data['regulator_id'] = _int(data.get('regulator_id'))
        data['is_active'] = bool(request.form.get('is_active'))
        try:
            fid = catalog.save_framework(data, framework_id)
            _log('regcontrols_framework_save', fid, data.get('code'))
            flash(_('Framework saved.'), 'success')
            return redirect(url_for('regcontrols.framework_detail', framework_id=fid))
        except catalog.CatalogError as e:
            _flash_error(e)
            fw = data
    return render_template('regcontrols/framework_form.html', fw=fw or {'is_active': True},
                           regulators=catalog.regulators(), framework_id=framework_id)


@bp.route('/library/frameworks/<int:framework_id>')
@rc_required('view')
def framework_detail(framework_id):
    fw = catalog.framework(framework_id)
    if not fw:
        abort(404)
    reqs = catalog.requirements(framework_id)
    status = {}
    for r in get_db().execute("""
            SELECT cr.requirement_id, c.last_status FROM rc_control_requirements cr
            JOIN rc_controls c ON c.id = cr.control_id JOIN rc_requirements q ON q.id = cr.requirement_id
            WHERE q.framework_id = %s AND c.is_active""", (framework_id,)).fetchall():
        status.setdefault(r['requirement_id'], []).append(r['last_status'])
    for q in reqs:
        q['status'] = logic.worst_status(status.get(q['id'], [])) if status.get(q['id']) else None
    covered = sum(1 for q in reqs if q['control_codes'])
    return render_template('regcontrols/framework_detail.html', fw=fw, reqs=reqs, covered=covered)


@bp.route('/library/frameworks/<int:framework_id>/requirements', methods=['POST'])
@rc_required('admin')
def requirement_save(framework_id):
    if not catalog.framework(framework_id):
        abort(404)
    try:
        catalog.save_requirement(framework_id, request.form.to_dict(), _int(request.form.get('requirement_id')))
        _log('regcontrols_requirement_save', framework_id, request.form.get('ref_code'))
        flash(_('Requirement saved.'), 'success')
    except catalog.CatalogError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.framework_detail', framework_id=framework_id))


@bp.route('/library/reference/<kind>', methods=['POST'])
@rc_required('admin')
def reference_save(kind):
    try:
        if kind == 'regulators':
            catalog.save_regulator(request.form.get('name_en'), request.form.get('code'), request.form.get('name_ar'),
                                   request.form.get('jurisdiction'), request.form.get('website'),
                                   _int(request.form.get('regulator_id')))
        elif kind in catalog.REF_TABLES:
            extra = {}
            if kind == 'licence_types':
                extra = {'regulator_id': _int(request.form.get('regulator_id')),
                         'jurisdiction': (request.form.get('jurisdiction') or '').upper() or None}
            if kind == 'areas' and _int(request.form.get('sort_order')) is not None:
                extra = {'sort_order': _int(request.form.get('sort_order'))}
            catalog.save_ref(kind, request.form.get('code'), request.form.get('name_en'), request.form.get('name_ar'),
                             extra)
        else:
            abort(404)
        _log('regcontrols_reference_save', None, f"{kind} {request.form.get('code') or request.form.get('name_en')}")
        flash(_('Saved.'), 'success')
    except catalog.CatalogError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.library_home') + '#' + kind)


# ------------------------------------------------------------------ content packs
@bp.route('/packs')
@rc_required('view')
def packs_list():
    return render_template('regcontrols/packs.html', packs=packs.listing())


@bp.route('/packs/<code>/<action>', methods=['POST'])
@rc_required('admin')
def pack_action(code, action):
    try:
        if action == 'enable':
            summary = packs.enable(code, current_user.id)
            flash(_('Pack enabled.') + (f' {summary}' if summary else ''), 'success')
        elif action == 'disable':
            packs.disable(code, current_user.id)
            flash(_('Pack disabled. Its controls are inactive and its pages hidden; its data is kept.'), 'info')
        else:
            abort(400)
        _log(f'regcontrols_pack_{action}', None, code)
    except ValueError as e:
        _flash_error(e)
    return redirect(url_for('regcontrols.packs_list'))

from . import readiness_routes  # noqa: E402,F401 — inspection readiness pages
