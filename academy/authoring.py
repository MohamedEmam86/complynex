# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Integrys Academy — course authoring (courses, lessons + media, question bank)
and the results report. Staff-only, on the ComplyNex host, perm_academy."""
import csv
import io
import json
from datetime import datetime

from flask import Response, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from database.db import get_db
from utils.decorators import permission_required
from . import media as M
from . import service as S
from .admin_routes import academy_admin_bp as bp

COURSE_INT_FIELDS = {  # field: (min, max, default)
    'duration_minutes': (5, 600, 45), 'pass_mark': (40, 100, 70), 'questions_per_attempt': (3, 50, 10),
    'retry_cooldown_minutes': (0, 1440, 30), 'validity_months': (0, 120, 24),
}


@bp.before_request
def _allow_large_lesson_uploads():
    # App-wide limit is 50 MB; a lesson form may carry a video + presentation + handout.
    if request.endpoint == 'academy_admin.lesson_form':
        request.max_content_length = 430 * 1024 * 1024


def _course(cid):
    c = get_db().execute("SELECT * FROM academy_courses WHERE id=%s", (cid,)).fetchone()
    if not c:
        abort(404)
    return c


def _log(cid, action, detail=''):
    S.audit(action, None, f'course={cid} {detail}'.strip(), actor_user_id=current_user.id)


# ================================================================ courses
@bp.route('/courses/new', methods=['GET', 'POST'])
@bp.route('/courses/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('academy', 'edit')
def course_form(cid=None):
    c = _course(cid) if cid else None
    if request.method == 'POST':
        f = request.form
        errors = []
        data = {
            'provider': f.get('provider') if f.get('provider') in S.PROVIDERS else 'integrys',
            'title_en': (f.get('title_en') or '').strip()[:200],
            'title_ar': (f.get('title_ar') or '').strip()[:200] or None,
            'summary_en': (f.get('summary_en') or '').strip()[:1000] or None,
            'summary_ar': (f.get('summary_ar') or '').strip()[:1000] or None,
            'level': (f.get('level') or 'Foundation')[:40],
        }
        if not data['title_en']:
            errors.append('English title is required (it is printed on the certificate).')
        for k, (lo, hi, dflt) in COURSE_INT_FIELDS.items():
            v = f.get(k, type=int)
            if v is None or not lo <= v <= hi:
                errors.append(f'{k.replace("_", " ")} must be between {lo} and {hi}.')
                v = dflt
            data[k] = v
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('academy/admin/course_form.html', c={**(c or {}), **data}, is_new=not c)
        db = get_db()
        if c:
            changed = [k for k in data if str(data[k]) != str(c.get(k))]
            sets = ', '.join(f'{k}=%s' for k in data)
            db.execute(f"UPDATE academy_courses SET {sets}, updated_at=now() WHERE id=%s", [*data.values(), cid])
            db.commit()
            _log(cid, 'course_edited', 'changed: ' + (', '.join(changed) or 'nothing'))
            if c['status'] == 'published' and {'pass_mark', 'questions_per_attempt'} & set(changed):
                flash('This course is live — the new assessment settings apply to attempts started from now on.', 'warning')
            flash('Course saved.', 'success')
        else:
            slug = S.slugify(data['title_en'])
            while db.execute("SELECT 1 FROM academy_courses WHERE slug=%s", (slug,)).fetchone():
                slug = f'{slug[:60]}-{datetime.now():%H%M%S}'
            cols = ['slug', 'created_by', *data]
            row = db.execute(f"INSERT INTO academy_courses ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))}) RETURNING id",
                             [slug, current_user.id, *data.values()]).fetchone()
            db.commit()
            cid = row['id']
            _log(cid, 'course_created', data['title_en'])
            flash('Course created as DRAFT. Now add lessons and questions.', 'success')
        return redirect(url_for('academy_admin.course', cid=cid))
    return render_template('academy/admin/course_form.html', c=c or {'provider': 'integrys', 'level': 'Foundation',
                           **{k: v[2] for k, v in COURSE_INT_FIELDS.items()}}, is_new=not c)


# ================================================================ lessons
def _store_media(f_files, lesson, course_id):
    """Apply uploads/removals from the form. Returns dict of column updates."""
    upd = {}
    for kind in ('video', 'presentation', 'material'):
        if request.form.get(f'remove_{kind}') and lesson and lesson.get(f'{kind}_file'):
            M.remove(lesson[f'{kind}_file'])
            upd[f'{kind}_file'], upd[f'{kind}_name'] = None, None
        fs = f_files.get(f'{kind}_upload')
        if fs and fs.filename:
            rel, original = M.save_upload(fs, kind, course_id)   # raises ValueError
            if lesson and lesson.get(f'{kind}_file'):
                M.remove(lesson[f'{kind}_file'])
            upd[f'{kind}_file'], upd[f'{kind}_name'] = rel, original
    return upd


@bp.route('/courses/<int:cid>/lessons/new', methods=['GET', 'POST'])
@bp.route('/courses/<int:cid>/lessons/<int:lid>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('academy', 'edit')
def lesson_form(cid, lid=None):
    c = _course(cid)
    db = get_db()
    lesson = None
    if lid:
        lesson = db.execute("SELECT * FROM academy_lessons WHERE id=%s AND course_id=%s", (lid, cid)).fetchone()
        if not lesson:
            abort(404)
    if request.method == 'POST':
        f = request.form
        data = {'title_en': (f.get('title_en') or '').strip()[:200],
                'title_ar': (f.get('title_ar') or '').strip()[:200] or None,
                'body_en': (f.get('body_en') or '').strip() or None,
                'body_ar': (f.get('body_ar') or '').strip() or None,
                'video_url': (f.get('video_url') or '').strip()[:500] or None}
        if not data['title_en']:
            flash('English lesson title is required.', 'danger')
            return render_template('academy/admin/lesson_form.html', c=c, l={**(lesson or {}), **data})
        if data['video_url'] and not data['video_url'].startswith('https://'):
            flash('Video link must start with https://', 'danger')
            return render_template('academy/admin/lesson_form.html', c=c, l={**(lesson or {}), **data})
        try:
            data.update(_store_media(request.files, lesson, cid))
        except ValueError as e:
            flash(str(e), 'danger')
            return render_template('academy/admin/lesson_form.html', c=c, l={**(lesson or {}), **data})
        if lesson:
            sets = ', '.join(f'{k}=%s' for k in data)
            db.execute(f"UPDATE academy_lessons SET {sets} WHERE id=%s", [*data.values(), lid])
            _log(cid, 'lesson_edited', f'lesson={lesson["position"]} {data["title_en"]}')
        else:
            pos = db.execute("SELECT COALESCE(max(position),0)+1 AS p FROM academy_lessons WHERE course_id=%s", (cid,)).fetchone()['p']
            cols = ['course_id', 'position', *data]
            db.execute(f"INSERT INTO academy_lessons ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})",
                       [cid, pos, *data.values()])
            _log(cid, 'lesson_added', f'lesson={pos} {data["title_en"]}')
        db.commit()
        flash('Lesson saved.', 'success')
        return redirect(url_for('academy_admin.course', cid=cid) + '#lessons')
    return render_template('academy/admin/lesson_form.html', c=c, l=lesson or {})


@bp.route('/courses/<int:cid>/lessons/<int:lid>/delete', methods=['POST'])
@login_required
@permission_required('academy', 'edit')
def lesson_delete(cid, lid):
    db = get_db()
    l = db.execute("SELECT * FROM academy_lessons WHERE id=%s AND course_id=%s", (lid, cid)).fetchone()
    if not l:
        abort(404)
    for kind in ('video', 'presentation', 'material'):
        M.remove(l.get(f'{kind}_file'))
    db.execute("DELETE FROM academy_lessons WHERE id=%s", (lid,))
    # close the gap so positions stay 1..n
    rows = db.execute("SELECT id FROM academy_lessons WHERE course_id=%s ORDER BY position", (cid,)).fetchall()
    db.execute("UPDATE academy_lessons SET position = position + 1000 WHERE course_id=%s", (cid,))
    for i, r in enumerate(rows, 1):
        db.execute("UPDATE academy_lessons SET position=%s WHERE id=%s", (i, r['id']))
    db.commit()
    _log(cid, 'lesson_deleted', l['title_en'])
    flash('Lesson deleted.', 'success')
    return redirect(url_for('academy_admin.course', cid=cid) + '#lessons')


@bp.route('/courses/<int:cid>/lessons/<int:lid>/move/<direction>', methods=['POST'])
@login_required
@permission_required('academy', 'edit')
def lesson_move(cid, lid, direction):
    db = get_db()
    rows = [r['id'] for r in db.execute("SELECT id FROM academy_lessons WHERE course_id=%s ORDER BY position", (cid,)).fetchall()]
    if lid not in rows:
        abort(404)
    i = rows.index(lid)
    j = i - 1 if direction == 'up' else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        db.execute("UPDATE academy_lessons SET position = position + 1000 WHERE course_id=%s", (cid,))
        for k, rid in enumerate(rows, 1):
            db.execute("UPDATE academy_lessons SET position=%s WHERE id=%s", (k, rid))
        db.commit()
        _log(cid, 'lessons_reordered')
    return redirect(url_for('academy_admin.course', cid=cid) + '#lessons')


@bp.route('/lessons/<int:lid>/file/<kind>')
@login_required
@permission_required('academy', 'view')
def lesson_file(lid, kind):
    if kind not in M.KINDS:
        abort(404)
    l = get_db().execute("SELECT * FROM academy_lessons WHERE id=%s", (lid,)).fetchone()
    path = M.abs_path(l.get(f'{kind}_file')) if l else None
    if not path:
        abort(404)
    ext = M.ext_of(path)
    return send_file(path, mimetype=M.MIME.get(ext, 'application/octet-stream'), conditional=True,
                     as_attachment=not (kind == 'video' or ext == 'pdf'),
                     download_name=l.get(f'{kind}_name') or f'lesson-{lid}.{ext}')


# ============================================================== questions
def _parse_question(f):
    opts_en = [o.strip() for o in (f.get('options_en') or '').splitlines() if o.strip()]
    opts_ar = [o.strip() for o in (f.get('options_ar') or '').splitlines() if o.strip()]
    correct = f.get('correct', type=int)
    errors = []
    if not (f.get('text_en') or '').strip():
        errors.append('English question text is required.')
    if not 2 <= len(opts_en) <= 6:
        errors.append('Give between 2 and 6 answer options (one per line).')
    if opts_ar and len(opts_ar) != len(opts_en):
        errors.append(f'Arabic options ({len(opts_ar)}) must match English options ({len(opts_en)}) line by line.')
    if not correct or not 1 <= correct <= len(opts_en):
        errors.append('Choose which option is the correct answer.')
    data = {'text_en': (f.get('text_en') or '').strip(), 'text_ar': (f.get('text_ar') or '').strip() or None,
            'options_en': json.dumps(opts_en), 'options_ar': json.dumps(opts_ar, ensure_ascii=False) if opts_ar else None,
            'correct_index': (correct or 1) - 1,
            'explanation_en': (f.get('explanation_en') or '').strip() or None,
            'explanation_ar': (f.get('explanation_ar') or '').strip() or None}
    return data, errors


@bp.route('/courses/<int:cid>/questions/new', methods=['GET', 'POST'])
@bp.route('/courses/<int:cid>/questions/<int:qid>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('academy', 'edit')
def question_form(cid, qid=None):
    c = _course(cid)
    db = get_db()
    q = None
    if qid:
        q = db.execute("SELECT * FROM academy_questions WHERE id=%s AND course_id=%s", (qid, cid)).fetchone()
        if not q:
            abort(404)
    if request.method == 'POST':
        data, errors = _parse_question(request.form)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('academy/admin/question_form.html', c=c, q=request.form, editing=bool(q))
        if q:
            sets = ', '.join(f'{k}=%s' for k in data)
            db.execute(f"UPDATE academy_questions SET {sets} WHERE id=%s", [*data.values(), qid])
            _log(cid, 'question_edited', f'question={qid}')
        else:
            cols = ['course_id', *data]
            db.execute(f"INSERT INTO academy_questions ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})",
                       [cid, *data.values()])
            _log(cid, 'question_added')
        db.commit()
        flash('Question saved.', 'success')
        if request.form.get('save_and_new'):
            return redirect(url_for('academy_admin.question_form', cid=cid))
        return redirect(url_for('academy_admin.course', cid=cid) + '#questions')
    form = None
    if q:
        form = {'text_en': q['text_en'], 'text_ar': q['text_ar'] or '',
                'options_en': '\n'.join(q['options_en'] or []), 'options_ar': '\n'.join(q['options_ar'] or []),
                'correct': str(q['correct_index'] + 1), 'explanation_en': q['explanation_en'] or '',
                'explanation_ar': q['explanation_ar'] or ''}
    return render_template('academy/admin/question_form.html', c=c, q=form or {}, editing=bool(q))


@bp.route('/courses/<int:cid>/questions/<int:qid>/delete', methods=['POST'])
@login_required
@permission_required('academy', 'edit')
def question_delete(cid, qid):
    db = get_db()
    used = db.execute("""SELECT 1 FROM academy_attempts a JOIN academy_enrollments e ON e.id=a.enrollment_id
                         WHERE e.course_id=%s AND a.question_ids @> %s::jsonb LIMIT 1""",
                      (cid, json.dumps([qid]))).fetchone()
    if used:
        db.execute("UPDATE academy_questions SET is_active=false WHERE id=%s AND course_id=%s", (qid, cid))
        flash('This question already appeared in learners\' assessments, so it was DISABLED (kept for the record) instead of deleted.', 'warning')
        _log(cid, 'question_disabled', f'question={qid} (in use)')
    else:
        db.execute("DELETE FROM academy_questions WHERE id=%s AND course_id=%s", (qid, cid))
        flash('Question deleted.', 'success')
        _log(cid, 'question_deleted', f'question={qid}')
    db.commit()
    return redirect(url_for('academy_admin.course', cid=cid) + '#questions')


CSV_HEAD = ['question_en', 'question_ar', 'option1_en', 'option2_en', 'option3_en', 'option4_en', 'option5_en', 'option6_en',
            'option1_ar', 'option2_ar', 'option3_ar', 'option4_ar', 'option5_ar', 'option6_ar',
            'correct_option_number', 'explanation_en', 'explanation_ar']


@bp.route('/courses/questions-template.csv')
@login_required
@permission_required('academy', 'view')
def questions_template():
    buf = io.StringIO()
    buf.write('﻿')
    w = csv.writer(buf)
    w.writerow(CSV_HEAD)
    w.writerow(['Which body is Egypt\'s Financial Intelligence Unit?', 'ما الجهة التي تمثل وحدة التحريات المالية في مصر؟',
                'The Egyptian Exchange', 'EMLCU', 'The Tax Authority', '', '', '',
                'البورصة المصرية', 'وحدة مكافحة غسل الأموال وتمويل الإرهاب', 'مصلحة الضرائب', '', '', '',
                '2', 'EMLCU receives STRs.', 'الوحدة تتلقى إخطارات الاشتباه.'])
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=academy-questions-template.csv'})


@bp.route('/courses/<int:cid>/questions/import', methods=['POST'])
@login_required
@permission_required('academy', 'edit')
def questions_import(cid):
    _course(cid)
    fs = request.files.get('csv_file')
    if not fs or not fs.filename.lower().endswith('.csv'):
        flash('Upload the CSV template (save from Excel as "CSV UTF-8").', 'danger')
        return redirect(url_for('academy_admin.course', cid=cid) + '#questions')
    text = fs.stream.read().decode('utf-8-sig', errors='replace')
    rows = list(csv.DictReader(io.StringIO(text)))
    good, bad = [], []
    for n, r in enumerate(rows, 2):
        f = {'text_en': r.get('question_en'), 'text_ar': r.get('question_ar'),
             'options_en': '\n'.join(r.get(f'option{i}_en') or '' for i in range(1, 7)),
             'options_ar': '\n'.join(r.get(f'option{i}_ar') or '' for i in range(1, 7)),
             'explanation_en': r.get('explanation_en'), 'explanation_ar': r.get('explanation_ar')}

        class _F(dict):
            def get(self, k, default=None, type=None):
                v = dict.get(self, k, default)
                if type is not None:
                    try:
                        return type(v)
                    except (TypeError, ValueError):
                        return None
                return v
        data, errors = _parse_question(_F(f, correct=(r.get('correct_option_number') or '').strip()))
        (bad if errors else good).append((n, data, errors))
    if bad:
        for n, _, errs in bad[:10]:
            flash(f'Row {n}: ' + ' '.join(errs), 'danger')
        flash(f'Nothing imported — fix the {len(bad)} row(s) above and upload again.', 'warning')
        return redirect(url_for('academy_admin.course', cid=cid) + '#questions')
    db = get_db()
    for _, data, _ in good:
        cols = ['course_id', *data]
        db.execute(f"INSERT INTO academy_questions ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})",
                   [cid, *data.values()])
    db.commit()
    _log(cid, 'questions_imported', f'{len(good)} from {fs.filename}')
    flash(f'{len(good)} questions imported.', 'success')
    return redirect(url_for('academy_admin.course', cid=cid) + '#questions')


# ================================================================ results
RESULT_SORTS = {'learner': 'l.full_name', 'company': 'l.company', 'course': 'c.title_en', 'provider': 'c.provider',
                'status': 'e.status', 'best': 'e.best_score', 'attempts': 'e.attempts_count',
                'started': 'e.started_at', 'completed': 'e.completed_at'}


@bp.route('/results')
@login_required
@permission_required('academy', 'view')
def results():
    a = request.args
    where, params = ["l.status <> 'erased'"], []
    if a.get('q'):
        where.append("(l.full_name ILIKE %s OR l.email ILIKE %s OR l.company ILIKE %s)")
        params += [f"%{a['q'].strip()}%"] * 3
    if a.get('course', type=int):
        where.append('e.course_id=%s'); params.append(a.get('course', type=int))
    if a.get('provider') in S.PROVIDERS:
        where.append('c.provider=%s'); params.append(a['provider'])
    if a.get('status') in ('passed', 'in_progress'):
        where.append('e.status=%s'); params.append(a['status'])
    if a.get('min_score', type=int) is not None:
        where.append('e.best_score >= %s'); params.append(a.get('min_score', type=int))
    for key, op in (('from', '>='), ('to', '<')):
        if a.get(key):
            try:
                datetime.strptime(a[key], '%Y-%m-%d')
                where.append(f"e.started_at {op} %s::date" + (' + 1' if key == 'to' else ''))
                params.append(a[key])
            except ValueError:
                pass
    col = RESULT_SORTS.get(a.get('sort'), 'e.started_at')
    direction = 'ASC' if a.get('dir') == 'asc' else 'DESC'
    sql = f"""SELECT e.*, l.full_name, l.email, l.company, l.job_title, l.id AS learner_id,
              c.title_en, c.provider, c.pass_mark,
              (SELECT count(*) FROM academy_lessons x WHERE x.course_id=c.id) AS lesson_count,
              (SELECT score FROM academy_attempts t WHERE t.enrollment_id=e.id AND t.submitted_at IS NOT NULL
                 ORDER BY t.submitted_at DESC LIMIT 1) AS last_score,
              (SELECT cert_number FROM academy_certificates z WHERE z.enrollment_id=e.id ORDER BY z.issued_at DESC LIMIT 1) AS cert_number,
              (SELECT status FROM academy_certificates z WHERE z.enrollment_id=e.id ORDER BY z.issued_at DESC LIMIT 1) AS cert_status
              FROM academy_enrollments e JOIN academy_learners l ON l.id=e.learner_id
              JOIN academy_courses c ON c.id=e.course_id
              WHERE {' AND '.join(where)} ORDER BY {col} {direction} NULLS LAST, e.id DESC"""
    db = get_db()
    if a.get('export') == 'csv':
        rows = db.execute(sql, params).fetchall()
        buf = io.StringIO(); buf.write('﻿')
        w = csv.writer(buf)
        w.writerow(['Learner', 'Email', 'Company', 'Job title', 'Course', 'Provider', 'Status', 'Lessons done',
                    'Lessons total', 'Attempts', 'Best score %', 'Last score %', 'Pass mark %', 'Started', 'Completed',
                    'Certificate', 'Certificate status'])
        for r in rows:
            w.writerow([S.csv_safe(x) for x in (r['full_name'], r['email'], r['company'], r['job_title'], r['title_en'],
                        S.PROVIDERS[r['provider']]['label'], r['status'], len(r['lessons_done'] or []), r['lesson_count'],
                        r['attempts_count'], r['best_score'], r['last_score'], r['pass_mark'],
                        r['started_at'].strftime('%Y-%m-%d'), r['completed_at'].strftime('%Y-%m-%d') if r['completed_at'] else '',
                        r['cert_number'], r['cert_status'])])
        S.audit('export_results', None, f'{len(rows)} rows', actor_user_id=current_user.id)
        return Response(buf.getvalue(), mimetype='text/csv', headers={
            'Content-Disposition': f'attachment; filename=integrys-academy-results-{datetime.now():%Y%m%d-%H%M}.csv'})
    rows = db.execute(sql + ' LIMIT 500', params).fetchall()
    summary = db.execute(f"""SELECT count(*) n, count(*) FILTER (WHERE e.status='passed') passed,
                             round(avg(e.best_score)) avg_best FROM academy_enrollments e
                             JOIN academy_learners l ON l.id=e.learner_id JOIN academy_courses c ON c.id=e.course_id
                             WHERE {' AND '.join(where)}""", params).fetchone()
    courses = db.execute("SELECT id, title_en, provider FROM academy_courses ORDER BY id").fetchall()
    return render_template('academy/admin/results.html', rows=rows, summary=summary, courses=courses, args=a)
