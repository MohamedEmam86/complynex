# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Integrys Academy — staff console on ComplyNex: learner database, courses,
certificate register, settings. Gated by perm_academy (view / edit)."""
import csv
import io
from datetime import datetime

from flask_babel import gettext
from flask import (Blueprint, Response, abort, flash, redirect, render_template, request,
                   url_for, current_app)
from flask_login import current_user, login_required

from database.db import get_db
from utils.decorators import permission_required
from . import service as S

academy_admin_bp = Blueprint('academy_admin', __name__, url_prefix='/academy/admin')

SORTS = {
    'name': 'l.full_name', 'company': 'l.company', 'domain': 'l.email_domain',
    'registered': 'l.created_at', 'activity': 'l.last_activity_at', 'status': 'l.status',
    'courses': 'courses', 'certs': 'certs', 'best': 'best_score',
}


def _uname(uid):
    if not uid:
        return ''
    r = get_db().execute("SELECT first_name, last_name, email FROM users WHERE id=%s", (uid,)).fetchone()
    if not r:
        return f'user {uid}'
    return (f"{r['first_name'] or ''} {r['last_name'] or ''}".strip() or r['email'])


@academy_admin_bp.app_template_global('academy_uname')
def academy_uname(uid):
    return _uname(uid)


@academy_admin_bp.route('/')
@login_required
@permission_required('academy', 'view')
def index():
    db = get_db()
    k = db.execute("""SELECT
        count(*) FILTER (WHERE status<>'erased')                             AS registered,
        count(*) FILTER (WHERE status='active')                              AS verified,
        count(*) FILTER (WHERE status='pending')                             AS pending,
        count(*) FILTER (WHERE status='active' AND consent_marketing)        AS marketing,
        count(*) FILTER (WHERE status<>'erased' AND created_at > now()-interval '30 days') AS last30,
        count(*) FILTER (WHERE status='erased')                              AS erased
        FROM academy_learners""").fetchone()
    e = db.execute("""SELECT count(DISTINCT learner_id) AS enrolled,
                             count(DISTINCT learner_id) FILTER (WHERE status='passed') AS passed
                      FROM academy_enrollments""").fetchone()
    certs = db.execute("SELECT count(*) AS n FROM academy_certificates WHERE status='valid'").fetchone()['n']
    companies = db.execute("""SELECT company, count(*) n FROM academy_learners WHERE status='active'
                              AND company IS NOT NULL GROUP BY company ORDER BY n DESC LIMIT 10""").fetchall()
    sources = db.execute("""SELECT COALESCE(utm_source, source, 'direct') AS s, count(*) n FROM academy_learners
                            WHERE status<>'erased' GROUP BY 1 ORDER BY n DESC LIMIT 8""").fetchall()
    rejected = db.execute("""SELECT * FROM academy_rejected_domains ORDER BY hits DESC, last_seen DESC LIMIT 15""").fetchall()
    courses = db.execute("""SELECT c.id, c.title_en, c.status, c.provider,
        (SELECT count(*) FROM academy_enrollments e WHERE e.course_id=c.id) enrolled,
        (SELECT count(*) FROM academy_enrollments e WHERE e.course_id=c.id AND e.status='passed') passed,
        (SELECT round(avg(best_score)) FROM academy_enrollments e WHERE e.course_id=c.id AND best_score IS NOT NULL) avg_score
        FROM academy_courses c ORDER BY c.id""").fetchall()
    return render_template('academy/admin/index.html', k=k, e=e, certs=certs, companies=companies,
                           sources=sources, rejected=rejected, courses=courses,
                           public_enabled=S.public_enabled())


def _learner_query(args):
    where, params = ["l.status <> 'erased'"], []
    q = (args.get('q') or '').strip()
    if q:
        where.append("(l.full_name ILIKE %s OR l.email ILIKE %s OR l.company ILIKE %s OR l.job_title ILIKE %s)")
        params += [f'%{q}%'] * 4
    if args.get('status') in ('active', 'pending', 'suspended'):
        where.append('l.status = %s'); params.append(args['status'])
    if args.get('marketing') == '1':
        where.append('l.consent_marketing')
    if args.get('free') == '1':
        where.append('l.free_provider')
    if args.get('course', type=int):
        where.append('EXISTS (SELECT 1 FROM academy_enrollments x WHERE x.learner_id=l.id AND x.course_id=%s)')
        params.append(args.get('course', type=int))
    if args.get('outcome') == 'passed':
        where.append("EXISTS (SELECT 1 FROM academy_enrollments x WHERE x.learner_id=l.id AND x.status='passed')")
    elif args.get('outcome') == 'not_passed':
        where.append("NOT EXISTS (SELECT 1 FROM academy_enrollments x WHERE x.learner_id=l.id AND x.status='passed')")
    for key, op in (('from', '>='), ('to', '<')):
        v = args.get(key)
        if v:
            try:
                datetime.strptime(v, '%Y-%m-%d')
                where.append(f"l.created_at {op} %s::date" + (" + 1" if key == 'to' else ''))
                params.append(v)
            except ValueError:
                pass
    sort = args.get('sort', 'registered')
    col = SORTS.get(sort, 'l.created_at')
    direction = 'ASC' if args.get('dir') == 'asc' else 'DESC'
    sql = f"""SELECT l.*,
        (SELECT count(*) FROM academy_enrollments x WHERE x.learner_id=l.id) AS courses,
        (SELECT count(*) FROM academy_certificates c WHERE c.learner_id=l.id AND c.status='valid') AS certs,
        (SELECT max(best_score) FROM academy_enrollments x WHERE x.learner_id=l.id) AS best_score,
        (SELECT string_agg(ac.title_en, '; ' ORDER BY ac.id) FROM academy_enrollments x
            JOIN academy_courses ac ON ac.id=x.course_id WHERE x.learner_id=l.id AND x.status='passed') AS passed_courses
        FROM academy_learners l WHERE {' AND '.join(where)}
        ORDER BY {col} {direction} NULLS LAST, l.id DESC"""
    return sql, params


@academy_admin_bp.route('/learners')
@login_required
@permission_required('academy', 'view')
def learners():
    sql, params = _learner_query(request.args)
    db = get_db()
    export = request.args.get('export')
    if export in ('all', 'marketing'):
        if export == 'marketing':
            sql = sql.replace("WHERE l.status <> 'erased'",
                              "WHERE l.status = 'active' AND l.consent_marketing AND l.status <> 'erased'", 1)
        rows = db.execute(sql, params).fetchall()
        return _csv(rows, export)
    page = max(1, request.args.get('page', 1, type=int))
    total = db.execute(f"SELECT count(*) AS n FROM ({sql}) s", params).fetchone()['n']
    rows = db.execute(sql + ' LIMIT 50 OFFSET %s', params + [(page - 1) * 50]).fetchall()
    courses = db.execute("SELECT id, title_en FROM academy_courses ORDER BY id").fetchall()
    return render_template('academy/admin/learners.html', rows=rows, total=total, page=page,
                           pages=max(1, (total + 49) // 50), courses=courses, args=request.args)


def _csv(rows, kind):
    buf = io.StringIO()
    buf.write('﻿')  # Excel opens UTF-8 Arabic correctly
    w = csv.writer(buf)
    if kind == 'marketing':
        head = ['Full name', 'Email', 'Company', 'Job title', 'Country', 'Marketing consent at', 'Passed courses']
        w.writerow(head)
        for r in rows:
            w.writerow([S.csv_safe(x) for x in (r['full_name'], r['email'], r['company'], r['job_title'],
                        r['country'], r['consent_marketing_at'], r['passed_courses'])])
    else:
        head = ['ID', 'Full name', 'Certificate name', 'Email', 'Domain', 'Company', 'Job title', 'Country',
                'Status', 'Free-mail flag', 'Source', 'UTM source', 'UTM campaign', 'Marketing consent',
                'Registered', 'Verified', 'Last activity', 'Courses', 'Certificates', 'Best score', 'Passed courses']
        w.writerow(head)
        for r in rows:
            w.writerow([S.csv_safe(x) for x in (r['id'], r['full_name'], r['certificate_name'], r['email'],
                        r['email_domain'], r['company'], r['job_title'], r['country'], r['status'],
                        'yes' if r['free_provider'] else '', r['source'], r['utm_source'], r['utm_campaign'],
                        'yes' if r['consent_marketing'] else 'no', r['created_at'], r['email_verified_at'],
                        r['last_activity_at'], r['courses'], r['certs'], r['best_score'], r['passed_courses'])])
    S.audit(f'export_{kind}', None, f'{len(rows)} rows', actor_user_id=current_user.id)
    name = f'integrys-academy-{kind}-{datetime.now():%Y%m%d-%H%M}.csv'
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={name}'})


@academy_admin_bp.route('/learners/<int:lid>')
@login_required
@permission_required('academy', 'view')
def learner(lid):
    db = get_db()
    l = db.execute("SELECT * FROM academy_learners WHERE id=%s", (lid,)).fetchone()
    if not l:
        abort(404)
    enrs = db.execute("""SELECT e.*, c.title_en, c.pass_mark,
                         (SELECT count(*) FROM academy_lessons x WHERE x.course_id=c.id) lesson_count
                         FROM academy_enrollments e JOIN academy_courses c ON c.id=e.course_id
                         WHERE e.learner_id=%s ORDER BY e.started_at""", (lid,)).fetchall()
    attempts = db.execute("""SELECT a.*, c.title_en FROM academy_attempts a
                             JOIN academy_enrollments e ON e.id=a.enrollment_id
                             JOIN academy_courses c ON c.id=e.course_id
                             WHERE e.learner_id=%s AND a.submitted_at IS NOT NULL ORDER BY a.submitted_at DESC""",
                          (lid,)).fetchall()
    certs = db.execute("SELECT * FROM academy_certificates WHERE learner_id=%s ORDER BY issued_at DESC", (lid,)).fetchall()
    log = db.execute("SELECT * FROM academy_audit WHERE learner_id=%s ORDER BY created_at DESC LIMIT 100", (lid,)).fetchall()
    return render_template('academy/admin/learner.html', l=l, enrs=enrs, attempts=attempts, certs=certs, log=log)


@academy_admin_bp.route('/learners/<int:lid>/action', methods=['POST'])
@login_required
@permission_required('academy', 'edit')
def learner_action(lid):
    db = get_db()
    l = db.execute("SELECT * FROM academy_learners WHERE id=%s", (lid,)).fetchone()
    if not l or l['status'] == 'erased':
        abort(404)
    action = request.form.get('action')
    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash(gettext('A reason is required for this action.'), 'danger')
        return redirect(url_for('academy_admin.learner', lid=lid))
    if action == 'suspend' and l['status'] == 'active':
        db.execute("UPDATE academy_learners SET status='suspended' WHERE id=%s", (lid,))
        db.commit()
        S.audit('suspended', lid, reason, actor_user_id=current_user.id)
    elif action == 'reactivate' and l['status'] == 'suspended':
        db.execute("UPDATE academy_learners SET status='active' WHERE id=%s", (lid,))
        db.commit()
        S.audit('reactivated', lid, reason, actor_user_id=current_user.id)
    elif action == 'erase' and request.form.get('confirm') == 'ERASE':
        S.erase_learner(lid, current_user.id, reason)
        flash(gettext('Personal data erased. Certificate numbers remain in the register as redacted.'), 'success')
        return redirect(url_for('academy_admin.learners'))
    else:
        flash(gettext('Action not applied.'), 'warning')
        return redirect(url_for('academy_admin.learner', lid=lid))
    flash(gettext('Done.'), 'success')
    return redirect(url_for('academy_admin.learner', lid=lid))


# ---------------------------------------------------------------- courses
@academy_admin_bp.route('/courses')
@login_required
@permission_required('academy', 'view')
def courses():
    rows = get_db().execute("""SELECT c.*,
        (SELECT count(*) FROM academy_lessons l WHERE l.course_id=c.id) lessons,
        (SELECT count(*) FROM academy_questions q WHERE q.course_id=c.id AND q.is_active) questions,
        (SELECT count(*) FROM academy_enrollments e WHERE e.course_id=c.id) enrolled
        FROM academy_courses c ORDER BY c.id""").fetchall()
    return render_template('academy/admin/courses.html', rows=rows)


@academy_admin_bp.route('/courses/<int:cid>')
@login_required
@permission_required('academy', 'view')
def course(cid):
    db = get_db()
    c = db.execute("SELECT * FROM academy_courses WHERE id=%s", (cid,)).fetchone()
    if not c:
        abort(404)
    ls = db.execute("SELECT * FROM academy_lessons WHERE course_id=%s ORDER BY position", (cid,)).fetchall()
    qs = db.execute("SELECT * FROM academy_questions WHERE course_id=%s ORDER BY id", (cid,)).fetchall()
    log = db.execute("""SELECT * FROM academy_audit WHERE learner_id IS NULL AND detail LIKE %s
                        ORDER BY created_at DESC LIMIT 30""", (f'course={cid}%',)).fetchall()
    return render_template('academy/admin/course.html', c=c, lessons=ls, questions=qs, log=log)


@academy_admin_bp.route('/courses/<int:cid>/status', methods=['POST'])
@login_required
@permission_required('academy', 'edit')
def course_status(cid):
    db = get_db()
    c = db.execute("SELECT * FROM academy_courses WHERE id=%s", (cid,)).fetchone()
    if not c:
        abort(404)
    new = request.form.get('status')
    note = (request.form.get('note') or '').strip()
    if new not in ('published', 'draft', 'retired') or not note:
        flash(gettext('Choose a status and record the approval note.'), 'danger')
        return redirect(url_for('academy_admin.course', cid=cid))
    if new == 'published':
        nq = db.execute("SELECT count(*) n FROM academy_questions WHERE course_id=%s AND is_active", (cid,)).fetchone()['n']
        if nq < c['questions_per_attempt']:
            flash(gettext('Cannot publish: %(nq)s active questions, %(questions_per_attempt)s needed per attempt.', nq=nq, questions_per_attempt=c["questions_per_attempt"]), 'danger')
            return redirect(url_for('academy_admin.course', cid=cid))
        db.execute("""UPDATE academy_courses SET status='published', approved_by=%s, approved_at=now(),
                      approval_note=%s, updated_at=now() WHERE id=%s""", (current_user.id, note, cid))
    else:
        db.execute("UPDATE academy_courses SET status=%s, updated_at=now() WHERE id=%s", (new, cid))
    db.commit()
    S.audit(f'course_{new}', None, f'course={cid} {note}', actor_user_id=current_user.id)
    flash(gettext('Course set to %(new)s.', new=new), 'success')
    return redirect(url_for('academy_admin.course', cid=cid))


@academy_admin_bp.route('/courses/<int:cid>/question/<int:qid>/toggle', methods=['POST'])
@login_required
@permission_required('academy', 'edit')
def question_toggle(cid, qid):
    db = get_db()
    db.execute("UPDATE academy_questions SET is_active = NOT is_active WHERE id=%s AND course_id=%s", (qid, cid))
    db.commit()
    S.audit('question_toggled', None, f'course={cid} question={qid}', actor_user_id=current_user.id)
    return redirect(url_for('academy_admin.course', cid=cid) + '#questions')


# ----------------------------------------------------------- certificates
@academy_admin_bp.route('/certificates')
@login_required
@permission_required('academy', 'view')
def certificates():
    q = (request.args.get('q') or '').strip()
    sql = """SELECT c.*, l.email, l.company FROM academy_certificates c
             LEFT JOIN academy_learners l ON l.id=c.learner_id"""
    params = []
    if q:
        sql += " WHERE c.cert_number ILIKE %s OR c.holder_name ILIKE %s OR l.company ILIKE %s"
        params = [f'%{q}%'] * 3
    rows = get_db().execute(sql + " ORDER BY c.issued_at DESC LIMIT 500", params).fetchall()
    return render_template('academy/admin/certificates.html', rows=rows, q=q, now=S.now())


@academy_admin_bp.route('/certificates/<int:cert_id>/revoke', methods=['POST'])
@login_required
@permission_required('academy', 'edit')
def certificate_revoke(cert_id):
    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash(gettext('A reason is required to revoke a certificate.'), 'danger')
        return redirect(url_for('academy_admin.certificates'))
    db = get_db()
    row = db.execute("""UPDATE academy_certificates SET status='revoked', status_reason=%s,
                        status_changed_by=%s, status_changed_at=now() WHERE id=%s AND status='valid'
                        RETURNING learner_id, cert_number""", (reason, current_user.id, cert_id)).fetchone()
    db.commit()
    if row:
        S.audit('certificate_revoked', row['learner_id'], f"{row['cert_number']}: {reason}", actor_user_id=current_user.id)
        flash(gettext("Certificate %(cert_number)s revoked.", cert_number=row['cert_number']), 'success')
    return redirect(url_for('academy_admin.certificates'))


@academy_admin_bp.route('/certificates/<int:cert_id>/pdf')
@login_required
@permission_required('academy', 'view')
def certificate_pdf(cert_id):
    cert = get_db().execute("SELECT * FROM academy_certificates WHERE id=%s", (cert_id,)).fetchone()
    if not cert:
        abort(404)
    from .certificate import build_pdf
    return Response(build_pdf(cert), mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename={cert["cert_number"]}.pdf'})


# ---------------------------------------------------------------- settings
@academy_admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@permission_required('academy', 'view')
def settings():
    if request.method == 'POST':
        if not current_user.can_edit('academy'):
            abort(403)
        changes = []
        for key, allowed in (('public_enabled', ('true', 'false')), ('free_email_policy', ('reject', 'flag'))):
            v = request.form.get(key)
            if v in allowed and v != S.setting(key):
                S.set_setting(key, v, current_user.id)
                changes.append(f'{key}={v}')
        rm = request.form.get('retention_months', type=int)
        if rm and 6 <= rm <= 120 and str(rm) != S.setting('retention_months'):
            S.set_setting('retention_months', rm, current_user.id)
            changes.append(f'retention_months={rm}')
        if changes:
            S.audit('settings_changed', None, ', '.join(changes), actor_user_id=current_user.id)
            flash('Settings saved: ' + ', '.join(changes), 'success')
        return redirect(url_for('academy_admin.settings'))
    from .routes import _serializer
    token = _serializer().dumps('preview')
    log = get_db().execute("""SELECT * FROM academy_audit WHERE learner_id IS NULL ORDER BY created_at DESC LIMIT 40""").fetchall()
    return render_template('academy/admin/settings.html',
                           s={k: S.setting(k) for k in ('public_enabled', 'free_email_policy', 'retention_months',
                                                       'privacy_version', 'sender_name')},
                           preview_url=f'{S.PUBLIC_BASE}/academy/preview/{token}', log=log,
                           mail_live=not current_app.config.get('EMAIL_MOCK_MODE', True))
