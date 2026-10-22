"""Fit & proper routes (registered on the governance blueprint)."""
import io
import os
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, send_file, abort, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _

from database.db import get_db
from utils.decorators import permission_required
from utils.file_validator import validate_file, secure_filename_strict
from attachments.service import list_attachments
from models.audit import AuditLog
from governance.routes import governance_bp
from . import service as S
from . import forms as F


def _lang():
    from flask import session
    return 'ar' if session.get('lang') == 'ar' else 'en'


def _form_or_404(fid):
    f = S.get(fid)
    if not f:
        abort(404)
    defn = F.get_form(f['template_code'])
    if not defn:
        abort(404)
    return f, defn


def hub():
    d = S.dashboard()
    db = get_db()
    legacy = db.execute("""SELECT a.id, a.assessment_date, a.assessment_result, a.total_score, m.member_name
                           FROM fit_proper_assessments a JOIN board_members m ON m.id = a.member_id
                           ORDER BY a.id DESC LIMIT 20""").fetchall()
    return render_template('governance/fp/hub.html', d=d, forms=F.all_forms(), S=S, legacy=legacy, lang=_lang())


@governance_bp.route('/fit-proper/officials/new', methods=['GET', 'POST'])
@governance_bp.route('/fit-proper/officials/<int:oid>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def fp_official_edit(oid=None):
    db = get_db()
    o = db.execute("SELECT * FROM fp_officials WHERE id = %s", (oid,)).fetchone() if oid else None
    if oid and not o:
        abort(404)
    if request.method == 'POST':
        f = request.form
        name = (f.get('full_name') or '').strip()
        if not name:
            flash(_('Name is required.'), 'danger')
            return redirect(request.url)
        vals = (name, (f.get('full_name_ar') or '').strip() or None, f.get('official_type') or 'executive',
                f.get('board_member_id') or None, f.get('user_id') or None, f.get('key_function') or None,
                (f.get('position_title') or '').strip() or None, (f.get('email') or '').strip() or None,
                (f.get('phone') or '').strip() or None, (f.get('nationality') or '').strip() or None,
                'is_active' in f if oid else True, (f.get('notes') or '').strip() or None)
        if oid:
            db.execute("""UPDATE fp_officials SET full_name=%s, full_name_ar=%s, official_type=%s, board_member_id=%s,
                          user_id=%s, key_function=%s, position_title=%s, email=%s, phone=%s, nationality=%s,
                          is_active=%s, notes=%s, updated_at=now() WHERE id=%s""", (*vals, oid))
        else:
            oid = db.execute("""INSERT INTO fp_officials (full_name, full_name_ar, official_type, board_member_id, user_id,
                                key_function, position_title, email, phone, nationality, is_active, notes, created_by)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                             (*vals, current_user.id)).fetchone()['id']
        db.commit()
        AuditLog.log(current_user.id, 'Save key official', 'Governance', oid, name, request.remote_addr)
        flash(_('Saved.'), 'success')
        return redirect(url_for('governance.fit_proper_dashboard'))
    members = db.execute("SELECT id, member_name FROM board_members WHERE COALESCE(is_deleted,0)=0 ORDER BY member_name").fetchall()
    users = db.execute("SELECT id, first_name, last_name, job_title FROM users WHERE is_active = 1 ORDER BY first_name").fetchall()
    seats = S.committee_seats(db).get(oid, []) if oid else []
    committees = db.execute("SELECT id, committee_name FROM board_committees WHERE COALESCE(is_active,1)=1 ORDER BY committee_name").fetchall()
    return render_template('governance/fp/official_form.html', o=o, members=members, users=users, KF=S.KEY_FUNCTIONS,
                           seats=seats, committees=committees, lang=_lang())


@governance_bp.route('/fit-proper/officials/import-board', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def fp_import_board():
    n = S.import_board_members(current_user.id)
    flash(_('%(n)s board member(s) added to the key officials list.', n=n), 'success')
    return redirect(url_for('governance.fit_proper_dashboard'))


@governance_bp.route('/fit-proper/officials/<int:oid>/committee', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def fp_official_committee(oid):
    db = get_db()
    cid = request.form.get('committee_id')
    if request.form.get('remove'):
        db.execute("UPDATE fp_official_committees SET is_active = FALSE, left_on = CURRENT_DATE WHERE official_id = %s AND committee_id = %s",
                   (oid, cid))
        flash(_('Committee seat removed.'), 'info')
    elif cid:
        db.execute("""INSERT INTO fp_official_committees (official_id, committee_id, role, joined_on)
                      VALUES (%s,%s,%s,CURRENT_DATE)
                      ON CONFLICT (official_id, committee_id) DO UPDATE SET is_active = TRUE, role = EXCLUDED.role, left_on = NULL""",
                   (oid, cid, request.form.get('role') or 'MEMBER'))
        flash(_('Committee seat added.'), 'success')
    db.commit()
    return redirect(url_for('governance.fp_official_edit', oid=oid))


@governance_bp.route('/fit-proper/forms/new', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def fp_form_new():
    try:
        fid = S.create_form(int(request.form['official_id']), request.form['template_code'],
                            request.form.get('purpose') or 'new_nomination', current_user.id,
                            committee_id=request.form.get('committee_id') or None)
    except (KeyError, ValueError) as e:
        flash(_('Could not create the form: %(e)s', e=str(e)), 'danger')
        return redirect(url_for('governance.fit_proper_dashboard'))
    AuditLog.log(current_user.id, 'Create fit & proper form', 'Governance', fid, request.form.get('template_code'), request.remote_addr)
    return redirect(url_for('governance.fp_form_edit', fid=fid))


@governance_bp.route('/fit-proper/forms/<int:fid>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('governance', level='edit')
def fp_form_edit(fid):
    f, defn = _form_or_404(fid)
    if f['status'] not in ('draft', 'candidate_completed', 'under_review'):
        flash(_('This form is locked (status: %(s)s). Return it to draft to change answers.', s=f['status']), 'warning')
        return redirect(url_for('governance.fp_form_view', fid=fid))
    if request.method == 'POST':
        answers = S.parse_answers(defn, request.form)
        S.save_answers(fid, answers, current_user.id)
        if request.form.get('complete') and f['status'] == 'draft':
            issues = S.validate(defn, answers)
            if issues:
                flash(_('Saved, but %(n)s item(s) still need an answer (write N/A where not applicable).', n=len(issues)), 'warning')
                return redirect(url_for('governance.fp_form_edit', fid=fid, check=1))
            S.transition(fid, 'complete', current_user.id)
            flash(_('Form completed and sent for compliance review.'), 'success')
            return redirect(url_for('governance.fp_form_view', fid=fid))
        flash(_('Answers saved.'), 'success')
        return redirect(url_for('governance.fp_form_edit', fid=fid))
    issues = S.validate(defn, f['answers']) if request.args.get('check') else []
    return render_template('governance/fp/form_edit.html', f=f, defn=defn, a=f['answers'], issues=issues,
                           issue_nos={i[0] for i in issues}, lang=_lang(), S=S)


@governance_bp.route('/fit-proper/forms/<int:fid>')
@login_required
@permission_required('governance')
def fp_form_view(fid):
    f, defn = _form_or_404(fid)
    flags = S.adverse_flags(defn, f['answers'])
    caps = S.suggest_caps(defn, f['answers'])
    issues = S.validate(defn, f['answers'])
    from utils.rating_guides import guide
    return render_template('governance/fp/form_view.html', f=f, defn=defn, a=f['answers'], flags=flags, caps=caps,
                           issues=issues, events=S.events(fid), CRITERIA=S.CRITERIA, guide=guide, S=S, lang=_lang(),
                           signed=list_attachments('governance', 'fp_form', fid),
                           has_docx=bool(F.docx_path(defn)))


@governance_bp.route('/fit-proper/forms/<int:fid>/assess', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def fp_form_assess(fid):
    f, defn = _form_or_404(fid)
    a = {}
    for crit in S.CRITERIA:
        key = crit[0]
        sc = request.form.get(f'score_{key}') or ''
        just = (request.form.get(f'just_{key}') or '').strip()
        if sc and not just:
            flash(_('Every score needs a justification (why this level and not the one above or below).'), 'danger')
            return redirect(url_for('governance.fp_form_view', fid=fid) + '#assessment')
        a[key] = {'score': sc, 'justification': just}
    score, result = S.save_assessment(fid, a, (request.form.get('conditions') or '').strip() or None, current_user.id)
    flash(_('Assessment saved.') + (f' {score} / 5' if score else ''), 'success')
    return redirect(url_for('governance.fp_form_view', fid=fid) + '#assessment')


@governance_bp.route('/fit-proper/forms/<int:fid>/status', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def fp_form_status(fid):
    action = request.form.get('action')
    try:
        S.transition(fid, action, current_user.id, note=(request.form.get('note') or '').strip() or None,
                     extra={'regulator_reference': (request.form.get('regulator_reference') or '').strip() or None,
                            'decision_on': request.form.get('decision_on') or None})
        AuditLog.log(current_user.id, f'Fit & proper form: {action}', 'Governance', fid, None, request.remote_addr)
        flash(_('Status updated.'), 'success')
    except ValueError as e:
        flash(_('Not possible: %(e)s', e=str(e)), 'danger')
    return redirect(url_for('governance.fp_form_view', fid=fid))


@governance_bp.route('/fit-proper/forms/<int:fid>/signed', methods=['POST'])
@login_required
@permission_required('governance', level='edit')
def fp_form_signed(fid):
    f, _defn = _form_or_404(fid)
    file = request.files.get('file')
    if not file or not file.filename:
        flash(_('Choose the scanned signed form (PDF).'), 'warning')
        return redirect(url_for('governance.fp_form_view', fid=fid))
    ok, err = validate_file(file, upload_type='document')
    if not ok:
        flash(_('File not accepted: %(error)s', error=err), 'danger')
        return redirect(url_for('governance.fp_form_view', fid=fid))
    name = secure_filename_strict(file.filename)
    rel_dir = os.path.join('uploads', 'attachments', 'governance', 'fp_form', str(fid))
    os.makedirs(os.path.join(current_app.root_path, rel_dir), exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    rel = os.path.join(rel_dir, f'signed_{stamp}_{name}').replace('\\', '/')
    file.save(os.path.join(current_app.root_path, rel))
    db = get_db()
    aid = db.execute("""INSERT INTO generic_attachments (module, record_type, record_id, filename, file_path, file_size,
                        description, uploaded_by, uploaded_at) VALUES ('governance','fp_form',%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (fid, file.filename[:255], rel, os.path.getsize(os.path.join(current_app.root_path, rel)),
                      'Signed fit & proper form (candidate and institution)', current_user.id,
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchone()['id']
    db.commit()
    S.attach_signed(fid, aid, current_user.id)
    flash(_('Signed copy attached.'), 'success')
    return redirect(url_for('governance.fp_form_view', fid=fid))


def _print_html(f, defn, blank=False, pdf=False):
    return render_template('governance/fp/form_print.html', f=f, defn=defn, a={} if blank else f['answers'],
                           blank=blank, pdf=pdf, now=datetime.now(), S=S)


@governance_bp.route('/fit-proper/forms/<int:fid>/print')
@login_required
@permission_required('governance')
def fp_form_print(fid):
    f, defn = _form_or_404(fid)
    return _print_html(f, defn)


@governance_bp.route('/fit-proper/forms/<int:fid>/pdf')
@login_required
@permission_required('governance')
def fp_form_pdf(fid):
    f, defn = _form_or_404(fid)
    from weasyprint import HTML
    pdf = HTML(string=_print_html(f, defn, pdf=True), base_url=current_app.root_path + '/').write_pdf()
    return send_file(io.BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
                     download_name=f"{f['reference']}_{defn['code']}.pdf")


@governance_bp.route('/fit-proper/forms/<int:fid>/docx')
@login_required
@permission_required('governance')
def fp_form_docx(fid):
    f, defn = _form_or_404(fid)
    path = F.docx_path(defn)
    if not path:
        abort(404)
    from .docx_fill import fill
    data = fill(path, defn, f['answers'])
    AuditLog.log(current_user.id, 'Export regulator form (Word)', 'Governance', fid, defn['code'], request.remote_addr)
    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{f['reference']}_{defn['code']}.docx",
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')


@governance_bp.route('/fit-proper/templates/<code>/blank')
@login_required
@permission_required('governance')
def fp_template_blank(code):
    defn = F.get_form(code)
    if not defn:
        abort(404)
    if request.args.get('original') and F.docx_path(defn):
        return send_file(F.docx_path(defn), as_attachment=True, download_name=f'{code}_original.docx')
    return _print_html({'reference': '', 'full_name': '', 'status': ''}, defn, blank=True)
