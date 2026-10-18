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

"""UI for AML & KYC assurance. Permission perm_aml (view / edit); internal-audit
coverage uses perm_internal_audit."""

from datetime import date, datetime
from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from attachments.service import list_attachments
from database.db import get_db
from models.audit import AuditLog

from . import amlkyc_bp as bp
from . import logic, service, subjects


def perm(level='view', module='aml'):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapped(*a, **kw):
            ok = current_user.can_edit(module) if level == 'edit' else current_user.can_view(module)
            if not ok:
                flash(_('You do not have permission for this AML assurance action.'), 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            return f(*a, **kw)
        return wrapped
    return deco


def _log(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, 'aml', item_id, details, request.remote_addr)
    except Exception:
        get_db().rollback()


def _err(e):
    msg = str(e)
    flash(_(msg) if ':' not in msg else msg, 'danger')


def _date(v):
    try:
        return datetime.strptime(v, '%Y-%m-%d').date() if v else None
    except ValueError:
        return None


def _int(v):
    try:
        return int(v) if v not in (None, '') else None
    except ValueError:
        return None


def _users():
    return [dict(r) for r in get_db().execute(
        "SELECT id, first_name, last_name, job_title FROM users WHERE is_active = 1 ORDER BY first_name").fetchall()]


def _controls_with(check_key):
    return [dict(r) for r in get_db().execute(
        "SELECT * FROM rc_controls WHERE check_key = %s AND is_active ORDER BY control_code", (check_key,)).fetchall()]


@bp.context_processor
def _ctx():
    authed = getattr(current_user, 'is_authenticated', False)
    return {'aa_can_edit': authed and current_user.can_edit('aml'), 'today': date.today(),
            'aa_subjects': subjects.SUBJECTS}


# ------------------------------------------------------------------ dashboard
@bp.route('/')
@perm()
def dashboard():
    db = get_db()
    rules = service.conflict_rules(db)
    roles = [dict(service.effective_role(r), conflicts=logic.role_conflicts(service.effective_role(r), rules))
             for r in service.key_roles(db)]
    unusual = service.unusual_list(db=db)
    kyc = {}
    for code in subjects.SUBJECTS:
        p = service.portfolio(code, db)
        active = [x for x in p if x['active']]
        kyc[code] = {'active': len(active), 'incomplete': sum(1 for x in active if x['missing']),
                     'unrated': sum(1 for x in active if not x['rating']),
                     'high': sum(1 for x in active if x['rating'] and x['rating']['band'] == 'high')}
    months = service.param('aml.employee_rescreen_months')
    emp_due = sum(1 for r in service.employees_due(months, db) if r['due']) if months is not None else None
    plan = db.execute("SELECT * FROM aml_monitoring_plans WHERE plan_year = %s", (date.today().year,)).fetchone()
    return render_template('amlkyc/dashboard.html', roles=roles, qa=service.last_qa_run(db),
                           unusual_open=sum(1 for u in unusual if u['status'] in ('candidate', 'under_study')),
                           unusual_late=sum(1 for u in unusual if logic.study_overdue(u)), kyc=kyc, emp_due=emp_due,
                           months=months, plan=dict(plan) if plan else None, model_gaps=logic.model_gaps(
                               service.risk_factors(db)), sources=service.screening_sources(db))


# ------------------------------------------------------------------ key roles
@bp.route('/roles', methods=['GET', 'POST'])
@perm()
def roles():
    db = get_db()
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        try:
            if request.form.get('form') == 'rule':
                service.save_conflict_rule(request.form.get('role_code'), request.form.get('rule_type'),
                                           request.form.get('keyword'), request.form.get('reason_en'),
                                           request.form.get('reason_ar'))
            else:
                data = request.form.to_dict()
                for k in ('holder_user_id', 'reports_to_user_id'):
                    data[k] = _int(data.get(k))
                for k in ('combined_role_approved_on', 'appointed_on', 'regulator_notified_on'):
                    data[k] = _date(data.get(k))
                data['is_active'] = bool(request.form.get('is_active'))
                service.save_key_role(data, current_user.id, _int(request.form.get('role_id')))
            _log('amlkyc_roles_save')
            flash(_('Saved.'), 'success')
        except service.AssuranceError as e:
            _err(e)
        return redirect(url_for('amlkyc.roles'))
    rules = service.conflict_rules(db)
    items = []
    for r in service.key_roles(db, active_only=False):
        er = service.effective_role(r)
        items.append(dict(er, conflicts=logic.role_conflicts(er, rules), combined_unapproved=logic.combined_role_unapproved(er)))
    edit = next((x for x in items if str(x['id']) == request.args.get('edit')), None)
    return render_template('amlkyc/roles.html', roles=items, rules=rules, users=_users(), edit=edit)


# ------------------------------------------------------------------ annual report
@bp.route('/annual-report', methods=['GET', 'POST'])
@perm()
def annual_reports():
    db = get_db()
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        try:
            rid = service.generate_annual_report(_int(request.form.get('year')) or date.today().year - 1, current_user.id)
            _log('amlkyc_annual_report_generate', rid)
            return redirect(url_for('amlkyc.annual_report', report_id=rid))
        except service.AssuranceError as e:
            _err(e)
    rows = [dict(r) for r in db.execute("SELECT * FROM aml_annual_reports ORDER BY report_year DESC").fetchall()]
    return render_template('amlkyc/annual_reports.html', reports=rows)


@bp.route('/annual-report/<int:report_id>', methods=['GET', 'POST'])
@perm()
def annual_report(report_id):
    db = get_db()
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        try:
            service.annual_report_action(report_id, request.form.get('action'), current_user.id,
                                         request.form.get('narrative'), request.form.get('board_meeting_ref'),
                                         _date(request.form.get('board_approved_on')))
            _log(f"amlkyc_annual_report_{request.form.get('action')}", report_id)
            flash(_('Saved.'), 'success')
        except service.AssuranceError as e:
            _err(e)
        return redirect(url_for('amlkyc.annual_report', report_id=report_id))
    r = db.execute("SELECT * FROM aml_annual_reports WHERE id = %s", (report_id,)).fetchone()
    if not r:
        abort(404)
    tpl = 'amlkyc/annual_report_print.html' if request.args.get('print') else 'amlkyc/annual_report.html'
    return render_template(tpl, r=dict(r), roles=service.key_roles(db))


# ------------------------------------------------------------------ board approvals
@bp.route('/board-approvals', methods=['GET', 'POST'])
@perm()
def board_approvals():
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        pid = _int(request.form.get('policy_id'))
        try:
            if request.form.get('action') == 'toggle':
                service.set_board_required(pid, request.form.get('required') == '1')
            else:
                service.record_board_approval(pid, _date(request.form.get('approved_on')), request.form.get('board_ref'),
                                              current_user.id, request.form.get('notes'))
            _log('amlkyc_board_approval', pid, request.form.get('action'))
            flash(_('Saved.'), 'success')
        except service.AssuranceError as e:
            _err(e)
        return redirect(url_for('amlkyc.board_approvals'))
    return render_template('amlkyc/board_approvals.html', policies=service.board_policies())


# ------------------------------------------------------------------ monitoring programme
@bp.route('/monitoring', methods=['GET', 'POST'])
@perm()
def monitoring():
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        pid = service.save_plan(_int(request.form.get('plan_year')) or date.today().year, request.form.get('title'),
                                _date(request.form.get('approved_on')), current_user.id)
        return redirect(url_for('amlkyc.monitoring_plan', plan_id=pid))
    return render_template('amlkyc/monitoring.html', plans=service.plans())


@bp.route('/monitoring/<int:plan_id>', methods=['GET', 'POST'])
@perm()
def monitoring_plan(plan_id):
    db = get_db()
    plan = db.execute("SELECT * FROM aml_monitoring_plans WHERE id = %s", (plan_id,)).fetchone()
    if not plan:
        abort(404)
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        try:
            service.add_review(plan_id, request.form.get('unit_label'), request.form.get('review_type'),
                               _date(request.form.get('planned_date')), _int(request.form.get('reviewer_id')))
            flash(_('Saved.'), 'success')
        except service.AssuranceError as e:
            _err(e)
        return redirect(url_for('amlkyc.monitoring_plan', plan_id=plan_id))
    return render_template('amlkyc/monitoring_plan.html', plan=dict(plan), reviews=service.reviews(plan_id),
                           users=_users())


@bp.route('/monitoring/review/<int:review_id>', methods=['GET', 'POST'])
@perm()
def monitoring_review(review_id):
    db = get_db()
    r = db.execute("SELECT * FROM aml_monitoring_reviews WHERE id = %s", (review_id,)).fetchone()
    if not r:
        abort(404)
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        results = [(request.form.get(f'result_{i}'), request.form.get(f'note_{i}') or '') for i in range(len(r['checklist']))]
        try:
            fid = service.complete_review(review_id, results, request.form.get('conclusion'), current_user.id,
                                          _date(request.form.get('performed_date')))
            _log('amlkyc_monitoring_review', review_id)
            flash(_('Review recorded.') + (' ' + _('A finding was opened for the issues.') if fid else ''), 'success')
        except service.AssuranceError as e:
            _err(e)
        return redirect(url_for('amlkyc.monitoring_review', review_id=review_id))
    return render_template('amlkyc/monitoring_review.html', r=dict(r))


# ------------------------------------------------------------------ screening assurance
@bp.route('/screening', methods=['GET', 'POST'])
@perm()
def screening():
    db = get_db()
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        action = request.form.get('action')
        try:
            if action == 'entry':
                n = service.add_cases_from_entry(request.form.get('name') or '', request.form.get('list_label'),
                                                 current_user.id)
                flash(_('%(n)s test case(s) added.', n=n), 'success')
            elif action == 'negatives':
                service.add_synthetic_negatives(current_user.id)
                flash(_('Synthetic negative cases added.'), 'success')
            elif action == 'case':
                service.add_qa_case(request.form.get('query_name'), request.form.get('expected_name'),
                                    request.form.get('variant_type') or 'manual', bool(request.form.get('expected_name')),
                                    request.form.get('list_label'), current_user.id)
                flash(_('Saved.'), 'success')
            elif action == 'toggle':
                db.execute("UPDATE screening_qa_cases SET is_active = NOT is_active WHERE id = %s",
                           (_int(request.form.get('case_id')),))
                db.commit()
            elif action == 'run':
                run = service.run_qa(current_user.id)
                _log('amlkyc_screening_qa_run', run['id'])
                flash(_('QA run finished: recall %(r)s, misses %(m)s.', r=run['recall_pct'], m=run['misses']),
                      'success' if not run['misses'] and not run['error'] else 'warning')
        except service.AssuranceError as e:
            _err(e)
        return redirect(url_for('amlkyc.screening'))
    hours = service.param('aml.watchlist_freshness_max_hours')
    required = []
    for c in _controls_with('core.screening.required_sources'):
        required += (c.get('check_config') or {}).get('required') or []
    sources = service.screening_sources(db)
    return render_template('amlkyc/screening.html', sources=sources, hours=hours,
                           required=service.source_status(sources, required, hours) if required else [],
                           cases=service.qa_cases(db), run=service.last_qa_run(db))


@bp.route('/employees', methods=['GET', 'POST'])
@perm()
def employees():
    months = service.param('aml.employee_rescreen_months')
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        ids = [_int(request.form.get('user_id'))] if request.form.get('user_id') else \
            [r['id'] for r in service.employees_due(months or 0) if r['due']]
        n = hits = 0
        for uid in ids[:200]:
            try:
                res = service.screen_employee(uid, current_user.id, request.form.get('trigger') or 'periodic')
                n += 1
                hits += int(res.get('high_risk_matches') or 0)
            except Exception as e:
                get_db().rollback()
                flash(_('Screening failed:') + f' {e}', 'danger')
                break
        _log('amlkyc_employee_screening', None, f'screened={n} hits={hits}')
        flash(_('%(n)s employee(s) screened, %(h)s potential match(es).', n=n, h=hits), 'success' if not hits else 'warning')
        return redirect(url_for('amlkyc.employees'))
    return render_template('amlkyc/employees.html', rows=service.employees_due(months or 0), months=months)


# ------------------------------------------------------------------ unusual transactions
@bp.route('/unusual')
@perm()
def unusual():
    return render_template('amlkyc/unusual.html', rows=service.unusual_list(request.args.get('status') or None),
                           f_status=request.args.get('status') or '', missing=service.reconcile_register())


@bp.route('/unusual/<int:item_id>', methods=['GET', 'POST'])
@perm()
def unusual_item(item_id):
    db = get_db()
    u = db.execute("SELECT * FROM aml_unusual_transactions WHERE id = %s", (item_id,)).fetchone()
    if not u:
        abort(404)
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        try:
            service.unusual_study(item_id, current_user.id, request.form.get('analysis'),
                                  request.form.get('decision') or None, request.form.get('str_reference'))
            _log('amlkyc_unusual_study', item_id, request.form.get('decision'))
            flash(_('Saved.'), 'success')
        except service.AssuranceError as e:
            _err(e)
        return redirect(url_for('amlkyc.unusual_item', item_id=item_id))
    return render_template('amlkyc/unusual_item.html', u=dict(u),
                           attach_module='aml', attach_record_type='aml_unusual', attach_record_id=item_id,
                           attach_items=list_attachments('aml', 'aml_unusual', item_id),
                           attach_can_edit=current_user.can_edit('aml') and u['status'] in ('candidate', 'under_study'))


# ------------------------------------------------------------------ KYC
@bp.route('/kyc')
@perm()
def kyc_home():
    code = request.args.get('subject') or next(iter(subjects.SUBJECTS))
    if code not in subjects.SUBJECTS:
        abort(404)
    rows = service.portfolio(code)
    f = request.args.get('filter') or ''
    if f == 'incomplete':
        rows = [r for r in rows if r['active'] and r['missing']]
    elif f == 'unrated':
        rows = [r for r in rows if r['active'] and not r['rating']]
    elif f == 'high':
        rows = [r for r in rows if r['rating'] and r['rating']['band'] == 'high']
    return render_template('amlkyc/kyc.html', code=code, subject=subjects.SUBJECTS[code], rows=rows[:2000],
                           f_filter=f, fields=service.fields(code))


@bp.route('/kyc/<code>/<int:subject_id>', methods=['GET', 'POST'])
@perm()
def kyc_file(code, subject_id):
    if code not in subjects.SUBJECTS:
        abort(404)
    s = subjects.SUBJECTS[code]
    rec = subjects.row(code, subject_id)
    if not rec:
        abort(404)
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        action = request.form.get('action')
        try:
            if action == 'profile':
                service.save_profile(code, subject_id, {k[3:]: v for k, v in request.form.items() if k.startswith('pf_')},
                                     current_user.id)
            elif action == 'bo':
                service.add_bo(code, subject_id, request.form.to_dict(), current_user.id)
            elif action == 'declaration':
                service.add_declaration(code, subject_id, request.form.get('declaration_type'), request.form.get('bo_name'),
                                        _date(request.form.get('signed_on')), current_user.id)
            elif action == 'rate':
                score, band, nr = service.rate_subject(code, subject_id, current_user.id,
                                                       request.form.get('trigger') or 'manual')
                flash(_('Rated %(score)s (%(band)s).', score=score, band=band), 'info')
            elif action == 'edd':
                service.save_edd(code, subject_id, request.form.getlist('edd_item'), request.form.get('note'),
                                 current_user.id)
            elif action == 'senior':
                service.senior_approve(code, subject_id, current_user.id)
            elif action == 'approve':
                service.approve_onboarding(code, subject_id, current_user.id)
                flash(_('Onboarding approved.'), 'success')
            else:
                abort(400)
            _log(f'amlkyc_kyc_{action}', subject_id, code)
            if action not in ('rate', 'approve'):
                flash(_('Saved.'), 'success')
        except service.AssuranceError as e:
            _err(e)
        return redirect(url_for('amlkyc.kyc_file', code=code, subject_id=subject_id))
    db = get_db()
    flds = service.fields(code, db)
    prof = service.profile(code, subject_id, db)
    st = service.file_status(code, rec, prof, flds)
    field_rows = []
    for fdef in flds:
        if not logic.applies(fdef, st['kind']):
            continue
        v, captured = logic.field_value(rec, prof, fdef)
        field_rows.append({'f': fdef, 'value': v, 'captured': captured, 'profile': prof.get(fdef['field_key'])})
    ratings = [dict(r) for r in db.execute("""SELECT * FROM kyc_risk_ratings WHERE subject = %s AND subject_id = %s
                                              ORDER BY rated_at DESC LIMIT 10""", (code, subject_id)).fetchall()]
    decls = service.declarations(code, subject_id, db)
    decl_files = {d['id']: list_attachments('aml', 'kyc_bo_declaration', d['id']) for d in decls}
    try:
        source_link = url_for(s.endpoint, id=subject_id) if s.endpoint else None
    except Exception:
        source_link = None
    return render_template('amlkyc/kyc_file.html', code=code, s=s, rec=rec, name=s.name(rec), st=st,
                           field_rows=field_rows, bos=service.bos(code, subject_id, db), decls=decls, decl_files=decl_files,
                           ratings=ratings, onb=service.onboarding(code, subject_id, db) or {},
                           blockers=service.onboarding_blockers(code, subject_id, db), edd_items=service.EDD_ITEMS,
                           source_link=source_link)


@bp.route('/kyc/fields', methods=['POST'])
@perm('edit')
def kyc_fields_save():
    db = get_db()
    code = request.form.get('subject')
    if code not in subjects.SUBJECTS:
        abort(400)
    key = (request.form.get('field_key') or '').strip().lower()
    if not key or not request.form.get('label_en'):
        flash(_('Field key and English label are required.'), 'danger')
    else:
        cols = [c.strip() for c in (request.form.get('column_names') or '').split(',') if c.strip()]
        db.execute("""INSERT INTO kyc_fields (subject, field_key, label_en, label_ar, source, column_names, applies_to, is_required)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (subject, field_key) DO UPDATE SET
                      label_en = EXCLUDED.label_en, label_ar = EXCLUDED.label_ar, source = EXCLUDED.source,
                      column_names = EXCLUDED.column_names, applies_to = EXCLUDED.applies_to, is_required = EXCLUDED.is_required""",
                   (code, key, request.form['label_en'], request.form.get('label_ar') or None,
                    'column' if cols else 'profile', cols,
                    request.form.get('applies_to') if request.form.get('applies_to') in ('individual', 'entity', 'all') else 'all',
                    bool(request.form.get('is_required'))))
        db.commit()
        _log('amlkyc_kyc_field_save', None, f'{code}.{key}')
        flash(_('Saved.'), 'success')
    return redirect(url_for('amlkyc.kyc_home', subject=code))


@bp.route('/risk-model', methods=['GET', 'POST'])
@perm()
def risk_model():
    import json as _json
    db = get_db()
    if request.method == 'POST':
        if not current_user.can_edit('aml'):
            abort(403)
        try:
            if request.form.get('form') == 'band':
                for b in service.risk_bands(db):
                    v = request.form.get(f"min_{b['band']}")
                    if v not in (None, ''):
                        db.execute("UPDATE kyc_risk_bands SET min_score = %s, refresh_param_key = %s WHERE band = %s",
                                   (float(v), request.form.get(f"param_{b['band']}") or None, b['band']))
            else:
                scoring = _json.loads(request.form.get('scoring') or '{}')
                if not isinstance(scoring, dict):
                    raise ValueError
                if request.form.get('category') not in logic.CATEGORIES:
                    raise ValueError
                db.execute("""INSERT INTO kyc_risk_factors (factor_key, category, label_en, label_ar, field_key, weight, scoring, is_active)
                              VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (factor_key) DO UPDATE SET category = EXCLUDED.category,
                              label_en = EXCLUDED.label_en, label_ar = EXCLUDED.label_ar, field_key = EXCLUDED.field_key,
                              weight = EXCLUDED.weight, scoring = EXCLUDED.scoring, is_active = EXCLUDED.is_active""",
                           ((request.form.get('factor_key') or '').strip().lower(), request.form['category'],
                            request.form.get('label_en'), request.form.get('label_ar') or None,
                            (request.form.get('field_key') or '').strip(), float(request.form.get('weight') or 1),
                            _json.dumps(scoring), bool(request.form.get('is_active'))))
            db.commit()
            _log('amlkyc_risk_model_save')
            flash(_('Saved.'), 'success')
        except (ValueError, KeyError):
            db.rollback()
            flash(_('Check the values: category, weight and scoring JSON (e.g. {"HIGH": 80, "*": 20}).'), 'danger')
        return redirect(url_for('amlkyc.risk_model'))
    factors = service.risk_factors(db)
    return render_template('amlkyc/risk_model.html', factors=factors, bands=service.risk_bands(db),
                           gaps=logic.model_gaps(factors), categories=logic.CATEGORIES)


# ------------------------------------------------------------------ training & audit coverage
@bp.route('/training-coverage')
@perm()
def training_coverage():
    cfg = {}
    for c in _controls_with('core.training.coverage'):
        cfg = c.get('check_config') or {}
        break
    category = request.args.get('category') or cfg.get('category')
    cov, people, done = service.training_coverage(cfg.get('course_ids'), category, cfg.get('window_months'))
    target = service.param(cfg.get('target_param') or 'training.aml_coverage_target_pct')
    return render_template('amlkyc/training_coverage.html', cov=sorted(cov.items()), target=target, category=category,
                           overall=round(100 * len(done & {p['id'] for p in people}) / len(people), 1) if people else 0)


@bp.route('/audit-coverage', methods=['GET', 'POST'])
@perm(module='internal_audit')
def audit_coverage():
    if request.method == 'POST':
        if not current_user.can_edit('internal_audit'):
            abort(403)
        service.map_area_control(_int(request.form.get('universe_id')), _int(request.form.get('control_id')),
                                 request.form.get('action') != 'unlink')
        return redirect(url_for('amlkyc.audit_coverage', year=request.args.get('year')))
    return render_template('amlkyc/audit_coverage.html', cov=service.audit_coverage(_int(request.args.get('year'))))


@bp.route('/audit-red-flag/<int:finding_id>', methods=['POST'])
@perm('edit', module='internal_audit')
def audit_red_flag(finding_id):
    db = get_db()
    db.execute("UPDATE audit_findings SET aml_red_flag = %s WHERE id = %s",
               (request.form.get('flag') == '1', finding_id))
    db.commit()
    n = service.route_audit_red_flags(db) if request.form.get('flag') == '1' else 0
    _log('amlkyc_audit_red_flag', finding_id, request.form.get('flag'))
    flash(_('AML red flag updated.') + (' ' + _('Sent to the unusual-transactions register.') if n else ''), 'success')
    return redirect(request.referrer or url_for('internal_audit.findings'))
