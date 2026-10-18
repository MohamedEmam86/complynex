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

"""Pages of the prudential / governance / financial-reporting registers (permission: perm_prudential)."""

from datetime import date
from functools import wraps

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from attachments.service import list_attachments
from database.db import get_db
from models.audit import AuditLog

from . import logic, providers, service
from . import prudential_bp as bp

MODULE = 'prudential'

# record types that can carry files (generic_attachments module 'prudential')
FILE_TYPES = {
    'pr_capital_event': ('pr_capital_events', 'prudential.capital'),
    'pr_deadline': ('pr_deadlines', 'prudential.deadlines'),
    'pr_document': ('pr_documents', 'prudential.profile'),
    'pr_facility': ('pr_facilities', 'prudential.facilities'),
    'pr_rp_item': ('pr_rp_items', 'prudential.related_parties'),
    'pr_study': ('pr_studies', 'prudential.studies'),
}


def perm(level='view'):
    def deco(f):
        @wraps(f)
        @login_required
        def wrapped(*a, **kw):
            ok = current_user.can_edit(MODULE) if level == 'edit' else current_user.can_view(MODULE)
            if not ok:
                flash(_('You do not have permission for the prudential registers.'), 'danger')
                return redirect(request.referrer or url_for('dashboard'))
            if request.method == 'POST' and not current_user.can_edit(MODULE):
                abort(403)
            return f(*a, **kw)
        return wrapped
    return deco


def _log(action, item_id=None, details=None):
    try:
        AuditLog.log(current_user.id, action, MODULE, item_id, details, request.remote_addr)
    except Exception:
        get_db().rollback()


def _err(e):
    msg = str(e)
    flash(_(msg) if not any(c in msg for c in ':%"') else msg, 'danger')


def _done(msg=None):
    flash(msg or _('Saved.'), 'success')


def _int(v):
    try:
        return int(v) if v not in (None, '') else None
    except ValueError:
        return None


def _users():
    return [dict(r) for r in get_db().execute(
        "SELECT id, first_name, last_name FROM users WHERE is_active = 1 ORDER BY first_name").fetchall()]


def _regulators():
    return [dict(r) for r in get_db().execute(
        "SELECT id, regulator_name, regulator_code FROM regulators ORDER BY regulator_name").fetchall()]


def _controls(prefixes=('core.prudential.', 'core.governance.', 'core.finance.')):
    rows = get_db().execute("""
        SELECT c.id, c.control_code, c.title_en, c.title_ar, c.check_key,
               (SELECT r.status FROM rc_control_runs r WHERE r.control_id = c.id ORDER BY r.id DESC LIMIT 1) AS last_status
        FROM rc_controls c WHERE c.is_active AND c.check_key IS NOT NULL ORDER BY c.control_code""").fetchall()
    return [dict(r) for r in rows if any(r['check_key'].startswith(p) for p in prefixes)]


@bp.context_processor
def _ctx():
    authed = getattr(current_user, 'is_authenticated', False)
    return {'pr_can_edit': authed and current_user.can_edit(MODULE), 'today': date.today()}


@bp.app_template_global()
def corp_profile():
    """Corporate profile for letterheads and documents (single source of truth)."""
    try:
        return service.profile()
    except Exception:
        get_db().rollback()
        return {}


# ------------------------------------------------------------------ dashboard
@bp.route('/')
@perm()
def dashboard():
    db = get_db()
    cap = service.capital_position(db)
    dls = service.deadlines(db, include_closed=False)
    per = [p for p in service.periods(db) if p['status'] == 'approved']
    kf = service.key_function_matrix(db)
    br = service.branches(db)
    fac = service.facility_review(db)
    rp = service.rp_review(db)
    docs = service.documents(db)
    return render_template('prudential/dashboard.html', cap=cap, deadlines=dls, period=per[-1] if per else None,
                           kf_issues=sum(1 for m in kf if m['issues']), kf_total=len(kf),
                           branch_issues=sum(1 for b in br if logic.branch_issues(b)), branches=len(br),
                           fac_issues=sum(1 for f in fac if f['confirmation'] or f['status_issues'] or
                                          (f['accrual'] and f['accrual']['breach'])), facilities=len(fac),
                           rp_issues=sum(1 for r in rp if r['issues']), rp_items=len(rp),
                           doc_issues=sum(1 for d in docs if d['address_ok'] is False), controls=_controls(),
                           provider=providers.get().name)


# ------------------------------------------------------------------ corporate profile & documents
@bp.route('/profile', methods=['GET', 'POST'])
@perm()
def profile():
    if request.method == 'POST':
        form = request.form.get('form')
        try:
            if form == 'profile':
                service.save_profile(request.form, current_user.id)
                _log('prudential_profile_save')
            elif form == 'document':
                did = service.add_document(request.form, current_user.id)
                _log('prudential_document_add', did)
                return redirect(url_for('prudential.files', rtype='pr_document', rid=did))
            elif form == 'review':
                v = request.form.get('ok')
                service.review_document(_int(request.form.get('doc_id')), None if v == '' else v == '1',
                                        request.form.get('note'))
            _done()
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.profile'))
    return render_template('prudential/profile.html', p=service.profile(), docs=service.documents(),
                           regulators=_regulators())


# ------------------------------------------------------------------ capital
@bp.route('/capital', methods=['GET', 'POST'])
@perm()
def capital():
    if request.method == 'POST':
        try:
            eid = service.add_capital_event(request.form, current_user.id)
            _log('prudential_capital_add', eid, request.form.get('capital_type'))
            _done(_('Saved. Attach the supporting document (resolution, bank certificate, registry extract).'))
            return redirect(url_for('prudential.files', rtype='pr_capital_event', rid=eid))
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.capital'))
    events = service.capital_events()
    series = {t: [] for t in logic.CAPITAL_TYPES}
    for e in sorted(events, key=lambda e: e['effective_date']):
        series[e['capital_type']].append({'x': str(e['effective_date']), 'y': float(e['amount'])})
    return render_template('prudential/capital.html', pos=service.capital_position(), events=events, series=series,
                           types=logic.CAPITAL_TYPES)


# ------------------------------------------------------------------ deadlines
@bp.route('/deadlines', methods=['GET', 'POST'])
@perm()
def deadlines():
    if request.method == 'POST':
        try:
            did = service.save_deadline(request.form, current_user.id)
            _log('prudential_deadline_add', did)
            _done()
            return redirect(url_for('prudential.deadline', deadline_id=did))
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.deadlines'))
    return render_template('prudential/deadlines.html', rows=service.deadlines(), users=_users(),
                           regulators=_regulators(), thresholds=service.alert_thresholds())


@bp.route('/deadlines/<int:deadline_id>', methods=['GET', 'POST'])
@perm()
def deadline(deadline_id):
    db = get_db()
    d = db.execute("""SELECT d.*, r.regulator_name FROM pr_deadlines d LEFT JOIN regulators r ON r.id = d.regulator_id
                      WHERE d.id = %s""", (deadline_id,)).fetchone()
    if not d:
        abort(404)
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'extend':
                service.add_extension(deadline_id, request.form, current_user.id)
            elif action in ('met', 'missed', 'cancelled'):
                service.close_deadline(deadline_id, action, request.form.get('met_on'))
            elif action == 'edit':
                service.save_deadline(dict(request.form, due_date=str(d['due_date'])), current_user.id, deadline_id)
            else:
                abort(400)
            _log(f'prudential_deadline_{action}', deadline_id)
            _done()
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.deadline', deadline_id=deadline_id))
    d = dict(d)
    th = service.alert_thresholds()
    d['state'], d['days_left'] = logic.deadline_state(d, thresholds=th), logic.days_left(d['due_date'])
    return render_template('prudential/deadline.html', d=d, ext=service.extensions(deadline_id), users=_users(),
                           regulators=_regulators(), thresholds=th, attach_module=MODULE, attach_record_type='pr_deadline',
                           attach_record_id=deadline_id, attach_items=list_attachments(MODULE, 'pr_deadline', deadline_id),
                           attach_can_edit=current_user.can_edit(MODULE))


# ------------------------------------------------------------------ solvency
@bp.route('/solvency', methods=['GET', 'POST'])
@perm()
def solvency():
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'approve':
                service.approve_period(_int(request.form.get('period_id')), current_user.id)
                _log('prudential_period_approve', request.form.get('period_id'))
                _done(_('Period approved.'))
            elif action == 'import':
                f = request.files.get('file')
                if not f:
                    raise service.PrudentialError('choose a CSV file')
                ok, errors = service.import_periods(f.read().decode('utf-8-sig'), current_user.id)
                _log('prudential_period_import', None, f'{ok} ok, {len(errors)} errors')
                flash(_('%(n)s period(s) imported.', n=ok), 'success' if not errors else 'warning')
                for e in errors[:20]:
                    flash(e, 'danger')
            else:
                pid = service.save_period(request.form, current_user.id)
                _log('prudential_period_save', pid)
                _done(_('Saved as draft; another user must approve the figures.'))
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.solvency'))
    rows = service.periods()
    lim = service.solvency_limits()
    for p in rows:
        p['breaches'] = logic.solvency_breaches(p, lim['max_leverage'], lim['min_equity'], lim['min_capital_base'])
    chart = {'labels': [str(p['period_end']) for p in rows],
             'equity': [float(p['ratios']['equity']) if p['ratios']['equity'] is not None else None for p in rows],
             'leverage': [float(p['ratios']['leverage']) if p['ratios']['leverage'] is not None else None for p in rows]}
    return render_template('prudential/solvency.html', rows=list(reversed(rows)), limits=lim, chart=chart,
                           fields=service.PERIOD_FIELDS, provider=providers.get().name)


@bp.route('/solvency/template.csv')
@perm()
def solvency_template():
    return Response(','.join(service.PERIOD_CSV) + '\n2026-03-31,quarter,,,,,,,,\n', mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=financial_periods.csv'})


# ------------------------------------------------------------------ key functions
@bp.route('/key-functions', methods=['GET', 'POST'])
@perm()
def key_functions():
    if request.method == 'POST':
        try:
            if request.form.get('form') == 'type':
                service.save_function_type(request.form)
            else:
                kid = service.save_key_function(request.form, current_user.id, _int(request.form.get('kf_id')))
                _log('prudential_key_function_save', kid, request.form.get('function_code'))
            _done()
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.key_functions'))
    db = get_db()
    try:
        members = [dict(r) for r in db.execute(
            "SELECT id, member_name FROM board_members WHERE COALESCE(status, 'ACTIVE') = 'ACTIVE' ORDER BY member_name").fetchall()]
    except Exception:
        db.rollback()
        members = []
    all_rows = service.key_functions(db, current_only=False)
    edit = next((k for k in all_rows if str(k['id']) == request.args.get('edit')), None)
    return render_template('prudential/key_functions.html', matrix=service.key_function_matrix(db), history=all_rows,
                           types=service.function_types(db), users=_users(), members=members, edit=edit)


# ------------------------------------------------------------------ branches
@bp.route('/branches', methods=['GET', 'POST'])
@perm()
def branches():
    if request.method == 'POST':
        form = request.form.get('form')
        try:
            if form == 'role':
                service.save_branch_role(request.form)
            elif form == 'staffing':
                for b in service.branches():
                    service.set_staffing(b['id'], {r['code']: request.form.get(f"s_{b['id']}_{r['code']}")
                                                   for r in service.branch_roles()})
            else:
                bid = service.save_branch(request.form, current_user.id, _int(request.form.get('branch_id')))
                _log('prudential_branch_save', bid)
            _done()
        except (service.PrudentialError, ValueError) as e:
            _err(e)
        return redirect(url_for('prudential.branches'))
    rows = service.branches()
    roles = service.branch_roles()
    mins = service.role_minimums(roles)
    vac = service.param('branch.manager_vacancy_max_days')
    for b in rows:
        b['issues'] = logic.branch_issues(b, max_vacancy_days=vac)
    edit = next((b for b in rows if str(b['id']) == request.args.get('edit')), None)
    return render_template('prudential/branches.html', rows=rows, roles=roles, mins=mins, staffing=service.staffing(),
                           users=_users(), edit=edit, vacancy_days=vac)


# ------------------------------------------------------------------ facilities
@bp.route('/facilities', methods=['GET', 'POST'])
@perm()
def facilities():
    if request.method == 'POST':
        try:
            if request.form.get('action') == 'import':
                f = request.files.get('file')
                if not f:
                    raise service.PrudentialError('choose a CSV file')
                ok, errors = service.import_facilities(f.read().decode('utf-8-sig'), current_user.id)
                flash(_('%(n)s facility(ies) imported.', n=ok), 'success' if not errors else 'warning')
                for e in errors[:20]:
                    flash(e, 'danger')
            else:
                fid = service.save_facility(request.form, current_user.id)
                _log('prudential_facility_save', fid)
                _done()
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.facilities'))
    rows = service.facility_review()
    edit = next((r['f'] for r in rows if str(r['f']['id']) == request.args.get('edit')), None)
    return render_template('prudential/facilities.html', rows=rows, edit=edit, provider=providers.get().name,
                           max_age=service.param('finance.balance_confirmation_max_age_days'),
                           tolerance=service.param('finance.accrual_tolerance_pct'))


@bp.route('/facilities/template.csv')
@perm()
def facilities_template():
    return Response(','.join(service.FACILITY_CSV) + '\n', mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=facilities.csv'})


# ------------------------------------------------------------------ related parties
@bp.route('/related-parties', methods=['GET', 'POST'])
@perm()
def related_parties():
    if request.method == 'POST':
        try:
            if request.form.get('form') == 'item':
                iid = service.add_rp_item(_int(request.form.get('party_id')), request.form, current_user.id)
                _log('prudential_rp_item_add', iid)
                _done(_('Saved. Attach the supporting document (transfer, receipt, contract).'))
                return redirect(url_for('prudential.files', rtype='pr_rp_item', rid=iid))
            pid = service.save_related_party(request.form, current_user.id)
            _log('prudential_rp_add', pid)
            _done()
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.related_parties'))
    return render_template('prudential/related_parties.html', parties=service.related_parties(),
                           items=service.rp_review())


# ------------------------------------------------------------------ studies
@bp.route('/studies', methods=['GET', 'POST'])
@perm()
def studies():
    if request.method == 'POST':
        try:
            if request.form.get('action') == 'approve':
                sid = _int(request.form.get('study_id'))
                service.approve_study(sid, request.form.get('approved_on'), request.form.get('approved_by_body'))
                _log('prudential_study_approve', sid)
                _done(_('Study approved.'))
            else:
                sid = service.save_study(request.form, current_user.id)
                _log('prudential_study_add', sid)
                _done(_('Saved. Attach the study, then record its approval.'))
                return redirect(url_for('prudential.files', rtype='pr_study', rid=sid))
        except service.PrudentialError as e:
            _err(e)
        return redirect(url_for('prudential.studies'))
    rows = service.studies()
    by_type = {}
    for s in rows:
        by_type.setdefault(s['study_type'], []).append(s)
    return render_template('prudential/studies.html', rows=rows,
                           status={t: logic.study_issue(v) for t, v in by_type.items()})


# ------------------------------------------------------------------ files for any register row
@bp.route('/files/<rtype>/<int:rid>')
@perm()
def files(rtype, rid):
    if rtype not in FILE_TYPES:
        abort(404)
    table, back = FILE_TYPES[rtype]
    rec = get_db().execute(f"SELECT * FROM {table} WHERE id = %s", (rid,)).fetchone()
    if not rec:
        abort(404)
    rec = dict(rec)
    label = rec.get('title') or rec.get('reference') or rec.get('capital_type') or rec.get('item_type') or f'#{rid}'
    return render_template('prudential/files.html', rec=rec, label=label, back=back, attach_module=MODULE,
                           attach_record_type=rtype, attach_record_id=rid,
                           attach_items=list_attachments(MODULE, rtype, rid),
                           attach_can_edit=current_user.can_edit(MODULE))
