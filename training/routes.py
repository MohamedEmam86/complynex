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

from flask_babel import gettext
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.decorators import permission_required
from utils.file_serving import serve_uploaded_file
from flask_babel import gettext as _
import json
from datetime import datetime
from models.training import TrainingCourse, TrainingEnrollment, TrainingCertificate
from models.user import User
from models.audit import AuditLog
from utils.html_sanitizer import sanitize_html

training_bp = Blueprint('training', __name__, url_prefix='/training')

@training_bp.route('/')
@training_bp.route('/courses')
@login_required
@permission_required('training', level='view')
def list_courses():
    """List courses (and personal enrollments for all roles)"""
    # Personal data for all users
    personal_enrollments = TrainingEnrollment.get_user_enrollments(current_user.id)
    personal_certificates = TrainingCertificate.get_user_certificates(current_user.id)
    
    # Get count of available courses for the badge (for library)
    all_courses = TrainingCourse.get_all()
    enrolled_ids = [e.course_id for e in personal_enrollments]
    available_count = len([c for c in all_courses if c.id not in enrolled_ids])

    if current_user.is_compliance_officer():
        # Management view + Personal data
        courses = TrainingCourse.get_all()
        return render_template('training/admin_list.html', 
                             courses=courses,
                             personal_enrollments=personal_enrollments,
                             personal_certificates=personal_certificates,
                             available_count=available_count)
    else:
        # Employee view
        return render_template('training/employee_list.html', 
                             enrollments=personal_enrollments, 
                             certificates=personal_certificates,
                             available_count=available_count)

@training_bp.route('/report')
@login_required
@permission_required('training', level='view')
def training_report():
    """Generate a training report for compliance officers and assignment-authorized managers."""
    if not current_user.can_manage_training():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('training.list_courses'))

    filters = {
        'course_id': request.args.get('course_id'),
        'status': request.args.get('status')
    }

    courses = TrainingCourse.get_all()

    if current_user.is_compliance_officer():
        enrollments = TrainingEnrollment.get_all_enrollments(filters)
        users = User.get_all()
    else:
        # Manager with assignment authority: scope to accessible departments
        dept_ids = current_user.get_accessible_departments()
        filters['department_ids'] = dept_ids
        enrollments = TrainingEnrollment.get_all_enrollments(filters)
        users = User.get_by_departments(dept_ids)

    from database.db import get_db as _gdb
    from training import watch as W
    used = {r['enrollment_id']: r['n'] for r in _gdb().execute(
        "SELECT enrollment_id, count(*) AS n FROM training_quiz_attempts GROUP BY enrollment_id").fetchall()}
    course_by_id = {c.id: c for c in courses}
    attempts = {}
    for e in enrollments:
        c = course_by_id.get(e.course_id)
        allowed = W.max_attempts(c.max_quiz_attempts if c else None) + int(e.extra_quiz_attempts or 0)
        attempts[e.id] = {'used': used.get(e.id, 0), 'allowed': allowed,
                          'remaining': max(0, allowed - used.get(e.id, 0))}
    return render_template('training/report.html',
                         enrollments=enrollments,
                         courses=courses,
                         users=users,
                         attempts=attempts)

@training_bp.route('/api/unassigned-courses/<int:user_id>')
@login_required
@permission_required('training', level='view')
def get_unassigned_courses(user_id):
    """API for the enrollment modal to find courses a user isn't in yet"""
    if not current_user.can_manage_training():
        return {"error": "Unauthorized"}, 403

    target_user = User.get_by_id(user_id)
    if not current_user.can_assign_training_to(target_user):
        return {"error": "Unauthorized"}, 403

    all_courses = TrainingCourse.get_all()
    user_enrollments = TrainingEnrollment.get_user_enrollments(user_id)
    enrolled_ids = [e.course_id for e in user_enrollments]

    unassigned = [
        {"id": c.id, "name": c.course_name, "mandatory": c.is_mandatory}
        for c in all_courses if c.id not in enrolled_ids
    ]

    return {"courses": unassigned}

@training_bp.route('/library')
@login_required
@permission_required('training', level='view')
def course_library():
    """Browse and self-enroll in courses"""
    courses = TrainingCourse.get_all()
    enrollments = TrainingEnrollment.get_user_enrollments(current_user.id)
    enrolled_ids = [e.course_id for e in enrollments]
    
    # Enrich course objects with enrollment status
    for course in courses:
        course.is_enrolled = course.id in enrolled_ids
        if course.is_enrolled:
            course.enrollment_status = next(e.status for e in enrollments if e.course_id == course.id)
    
    return render_template('training/course_library.html', courses=courses)

@training_bp.route('/course/<int:id>')
@login_required
@permission_required('training', level='view')
def view_course(id):
    """View course content and start quiz if enrolled"""
    course = TrainingCourse.get_by_id(id)
    if not course:
        flash(gettext('Course not found.'), 'danger')
        return redirect(url_for('training.list_courses'))
        
    enrollment = next((e for e in TrainingEnrollment.get_user_enrollments(current_user.id) 
                      if e.course_id == id), None)
    
    from training import watch as W
    length = W.video_length(course.video_duration_seconds, course.duration_minutes)
    attempts_left = None
    if enrollment:
        attempts_left = W.attempts_remaining(course.max_quiz_attempts, len(enrollment.quiz_attempts()),
                                             enrollment.extra_quiz_attempts)
    return render_template('training/course_view.html',
                         course=course,
                         enrollment=enrollment,
                         watch_pct=W.watched_pct(enrollment.watched_seconds, length) if enrollment else 0,
                         watch_threshold=W.threshold_pct(course.completion_threshold_pct),
                         attempts_left=attempts_left,
                         attempts_allowed=W.max_attempts(course.max_quiz_attempts) +
                         (int(enrollment.extra_quiz_attempts or 0) if enrollment else 0))

@training_bp.route('/course/<int:id>/asset/<asset_type>')
@login_required
@permission_required('training', level='view')
def course_asset(id, asset_type):
    """Serve a course's video/presentation/document — same guard as viewing the course."""
    course = TrainingCourse.get_by_id(id)
    if not course:
        flash(gettext('Course not found.'), 'danger')
        return redirect(url_for('training.list_courses'))

    path_by_type = {
        'video': course.video_file_path,
        'presentation': course.presentation_path,
        'document': course.document_path,
    }
    relative_path = path_by_type.get(asset_type)
    if not relative_path:
        flash(gettext('File not found.'), 'danger')
        return redirect(url_for('training.view_course', id=id))

    return serve_uploaded_file(relative_path)

@training_bp.route('/course/<int:id>/quiz', methods=['GET', 'POST'])
@login_required
@permission_required('training', level='view')
def take_quiz(id):
    """Take course quiz. Eligibility, the attempt limit and grading are all
    enforced here (server side); the quiz is served in the course's language."""
    from training import watch as W
    from flask import session as _session
    course = TrainingCourse.get_by_id(id)
    if not course:
        flash(_('Course not found.'), 'danger')
        return redirect(url_for("training.course_library"))
    enrollment = next((e for e in TrainingEnrollment.get_user_enrollments(current_user.id)
                      if e.course_id == id), None)

    if not enrollment or enrollment.status == 'completed':
        flash(gettext('You are not eligible for this quiz or have already completed it.'), 'warning')
        return redirect(url_for('training.view_course', id=id))

    has_video = bool(course.video_file_path or course.video_url)
    if has_video and not enrollment.video_completed:
        flash(gettext('You must watch at least %(pct)s%% of the training video before taking the quiz.',
                      pct=W.threshold_pct(course.completion_threshold_pct)), 'warning')
        return redirect(url_for('training.view_course', id=id))

    used = len(enrollment.quiz_attempts())
    remaining = W.attempts_remaining(course.max_quiz_attempts, used, enrollment.extra_quiz_attempts)
    if remaining <= 0:
        flash(gettext('You have used all %(n)s quiz attempts for this course. Ask the training administrator for an additional attempt.',
                      n=W.max_attempts(course.max_quiz_attempts) + int(enrollment.extra_quiz_attempts or 0)), 'danger')
        return redirect(url_for('training.view_course', id=id))

    lang = W.quiz_language(getattr(course, 'language', None), _session.get('lang'))
    questions = [W.localize_question(q, lang) for q in course.get_questions()]

    if request.method == 'POST':
        score = 0
        total = len(questions)
        if total == 0:
            score_percent = 100  # Auto-pass if no questions
        else:
            for q in questions:
                answer = request.form.get(f'q_{q["id"]}')
                if answer == str(q['correct_answer']):
                    score += q['points'] or 0
            total_points = sum((q['points'] or 0) for q in questions)
            score_percent = int((score / total_points) * 100) if total_points > 0 else 100

        success, cert_num = enrollment.complete(score_percent)
        attempt_no = enrollment.record_attempt(score_percent, bool(success), lang, request.remote_addr)
        left = remaining - 1
        if success:
            AuditLog.log(current_user.id, 'Training Completion', 'Training', enrollment.id,
                         f'Passed course {course.course_code} with {score_percent}% (attempt {attempt_no})', request.remote_addr)
            flash(gettext('Congratulations! You passed with %(score)s%% and earned a certificate.', score=score_percent), 'success')
        else:
            AuditLog.log(current_user.id, 'Training Failed', 'Training', enrollment.id,
                         f'Failed course {course.course_code} with {score_percent}% (attempt {attempt_no}, {left} left)', request.remote_addr)
            if left > 0:
                flash(gettext('You scored %(score)s%%, below the passing score of %(pass)s%%. Attempts remaining: %(left)s.',
                              score=score_percent, **{'pass': course.passing_score, 'left': left}), 'warning')
            else:
                flash(gettext('You scored %(score)s%%, below the passing score of %(pass)s%%. No attempts remain; ask the training administrator for an additional attempt.',
                              score=score_percent, **{'pass': course.passing_score}), 'danger')
        return redirect(url_for('training.view_course', id=id))

    return render_template('training/quiz.html', course=course, questions=questions, quiz_lang=lang,
                           attempts_remaining=remaining, attempts_used=used)


@training_bp.route('/enrollment/<int:enrollment_id>/grant-attempt', methods=['POST'])
@login_required
@permission_required('training', level='view')
def grant_attempt(enrollment_id):
    """A training administrator grants one more quiz attempt, with a reason (tracked)."""
    from database.db import get_db as _gdb
    db = _gdb()
    row = db.execute("SELECT * FROM training_enrollments WHERE id = %s", (enrollment_id,)).fetchone()
    if not row:
        flash(gettext('Enrollment not found.'), 'danger')
        return redirect(url_for('training.training_report'))
    target = User.get_by_id(row['employee_id']) if row['employee_id'] else None
    if not (current_user.can_manage_training() and (current_user.is_compliance_officer() or
                                                     current_user.can_assign_training_to(target))):
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('training.list_courses'))
    reason = (request.form.get('reason') or '').strip()
    if not reason:
        flash(gettext('Give the reason for granting an additional attempt.'), 'danger')
        return redirect(request.referrer or url_for('training.training_report'))
    db.execute("INSERT INTO training_attempt_grants (enrollment_id, granted_by, attempts, reason) VALUES (%s,%s,1,%s)",
               (enrollment_id, current_user.id, reason))
    db.execute("UPDATE training_enrollments SET extra_quiz_attempts = COALESCE(extra_quiz_attempts, 0) + 1 WHERE id = %s",
               (enrollment_id,))
    db.commit()
    AuditLog.log(current_user.id, 'Training Attempt Granted', 'Training', enrollment_id, reason, request.remote_addr)
    flash(gettext('An additional quiz attempt was granted.'), 'success')
    return redirect(request.referrer or url_for('training.training_report'))

@training_bp.route('/certificates')
@login_required
@permission_required('training', level='view')
def my_certificates():
    """Show user's earned certificates"""
    certificates = TrainingCertificate.get_user_certificates(current_user.id)
    return render_template('training/certificates.html', certificates=certificates)

@training_bp.route('/manage/course/new')
@training_bp.route('/manage/course/<int:id>/edit')
@login_required
@permission_required('training', level='view')
def edit_course(id=None):
    if not current_user.is_compliance_officer():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('training.list_courses'))
        
    course = TrainingCourse.get_by_id(id) if id else None
    return render_template('training/course_form.html', course=course)

def _pos_int(v, lo=1, hi=None):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    if n < lo:
        return None
    return min(n, hi) if hi else n


@training_bp.route('/manage/course/<int:id>/save', methods=['POST'])
@login_required
@permission_required('training', level='view')
def save_course(id):
    if not current_user.is_compliance_officer():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('training.list_courses'))
        
    # Handle File Uploads
    from werkzeug.utils import secure_filename
    import os
    
    # non-static uploads/ dir — not reachable via Flask's unauthenticated /static/ route
    upload_dir = os.path.join('uploads', 'training')
    os.makedirs(upload_dir, exist_ok=True)
    
    video_file = request.files.get('video_file')
    document_file = request.files.get('document_file')
    presentation_file = request.files.get('presentation_file')
    
    video_path = None
    document_path = request.form.get('document_path') # Keep existing if text used
    presentation_path = None
    
    import time
    def save_file(file):
        if file and file.filename:
            filename = secure_filename(f"{int(time.time())}_{file.filename}")
            file.save(os.path.join(upload_dir, filename))
            return f"uploads/training/{filename}"
        return None

    if video_file:
        video_path = save_file(video_file)
        
    if document_file:
        # If new file uploaded, overwrite path
        document_path = save_file(document_file)
        
    if presentation_file:
        presentation_path = save_file(presentation_file)

    course_data = {
        'id': id if id != 0 else None,
        'course_code': request.form.get('course_code'),
        'course_name': request.form.get('course_name'),
        'description': request.form.get('description'),
        'category': request.form.get('category'),
        'content_type': request.form.get('content_type'),
        'duration_minutes': request.form.get('duration_minutes'),
        'passing_score': request.form.get('passing_score'),
        'video_url': request.form.get('video_url'),
        'document_path': document_path,
        # Sanitized 2026-07-24: rendered with |safe in course_view.html —
        # must never store raw attacker-controlled HTML/JS (stored-XSS
        # audit finding).
        'content': sanitize_html(request.form.get('content')),
        'is_mandatory': 1 if request.form.get('is_mandatory') == 'on' else 0,  # integer columns
        'is_active': 1 if request.form.get('is_active') == 'on' else 0,
        'created_by': current_user.id,
        'presentation_path': presentation_path,
        'video_file_path': video_path,
        'external_link': request.form.get('external_link'),
        'language': request.form.get('language') if request.form.get('language') in ('en', 'ar') else None,
        'video_duration_seconds': _pos_int(request.form.get('video_duration_seconds')),
        'completion_threshold_pct': _pos_int(request.form.get('completion_threshold_pct'), 10, 100),
        'max_quiz_attempts': _pos_int(request.form.get('max_quiz_attempts'), 1, 20),
    }
    
    # If updating, merge new paths with old if not replaced%s 
    # Current implementation replaces if new file, but if no new file, we should keep old.
    # But wait, TrainingCourse(**course_data) expects all fields.
    # If id != 0, we should fetch existing to preserve paths if not updated.
    
    if id != 0:
        existing = TrainingCourse.get_by_id(id)
        if existing:
            if not video_path: course_data['video_file_path'] = existing.video_file_path
            if not document_path and not request.form.get('document_path'): course_data['document_path'] = existing.document_path
            if not presentation_path: course_data['presentation_path'] = existing.presentation_path

    # Video length must be known to the server: entered by the administrator, or
    # read from the uploaded MP4; else the declared duration is used.
    if not course_data['video_duration_seconds'] and course_data.get('video_file_path'):
        from training.media import mp4_duration_seconds
        course_data['video_duration_seconds'] = mp4_duration_seconds(course_data['video_file_path'])
    has_video = bool(course_data.get('video_file_path') or (course_data.get('video_url') or '').strip())
    if has_video and not course_data['video_duration_seconds'] and not _pos_int(course_data.get('duration_minutes')):
        flash(gettext('Enter the video length (seconds) or the course duration (minutes): the video cannot be '
                      'marked as watched without a length known to the server.'), 'danger')
        return redirect(url_for('training.edit_course', id=id) if id else url_for('training.edit_course'))

    course = TrainingCourse(**course_data)
    course.save()
    flash(gettext('Course saved successfully.'), 'success')
    return redirect(url_for('training.list_courses'))

@training_bp.route('/manage/course/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('training', level='view')
def delete_course(id):
    if not current_user.is_compliance_officer():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('training.list_courses'))
        
    course = TrainingCourse.get_by_id(id)
    if course:
        course.delete()
        AuditLog.log(current_user.id, 'Delete Course', 'Training', id, f'Deleted course {course.course_name}', request.remote_addr)
        flash(gettext('Course deleted.'), 'success')
    else:
        flash(gettext('Course not found.'), 'danger')
        
    return redirect(url_for('training.list_courses'))

@training_bp.route('/manage/course/<int:id>/questions')
@login_required
@permission_required('training', level='view')
def manage_questions(id):
    if not current_user.is_compliance_officer():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('training.list_courses'))
        
    course = TrainingCourse.get_by_id(id)
    if not course:
        flash(gettext('Course not found.'), 'danger')
        return redirect(url_for('training.list_courses'))
    questions = course.get_questions()
    return render_template('training/manage_questions.html', course=course, questions=questions)

@training_bp.route('/manage/course/<int:course_id>/questions/save', methods=['POST'])
@login_required
@permission_required('training', level='view')
def save_question(course_id):
    if not current_user.is_compliance_officer():
        return redirect(url_for('training.list_courses'))
        
    question_text = request.form.get('question_text')
    question_text_ar = request.form.get('question_text_ar')
    
    options = [
        request.form.get('option_0'),
        request.form.get('option_1'),
        request.form.get('option_2'),
        request.form.get('option_3')
    ]
    options = [opt for opt in options if opt] # Filter empty
    
    options_ar = [
        request.form.get('option_ar_0'),
        request.form.get('option_ar_1'),
        request.form.get('option_ar_2'),
        request.form.get('option_ar_3')
    ]
    options_ar = [opt for opt in options_ar if opt] # Filter empty

    correct_answer = int(request.form.get('correct_answer'))
    points = int(request.form.get('points', 10))
    
    from models.training import TrainingQuestion
    TrainingQuestion.create(course_id, question_text, options, correct_answer, points, question_text_ar, options_ar)
    flash(gettext('Question added.'), 'success')
    return redirect(url_for('training.manage_questions', id=course_id))

@training_bp.route('/manage/course/<int:course_id>/questions/<int:question_id>/delete', methods=['POST'])
@login_required
@permission_required('training', level='view')
def delete_question(course_id, question_id):
    if not current_user.is_compliance_officer():
        return redirect(url_for('training.list_courses'))
        
    from models.training import TrainingQuestion
    TrainingQuestion.delete(question_id)
    flash(gettext('Question deleted.'), 'success')
    return redirect(url_for('training.manage_questions', id=course_id))

@training_bp.route('/report/export')
@login_required
@permission_required('training', level='view')
def training_export_report():
    if not current_user.is_compliance_officer():
        return redirect(url_for('training.list_courses'))
        
    import csv
    from io import StringIO
    from flask import Response
    
    enrollments = TrainingEnrollment.get_all_enrollments()
    
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Date', 'Employee', 'Department', 'Course Code', 'Course Name', 'Status', 'Score', 'Completion Date', 'Due Date'])
    
    for e in enrollments:
        cw.writerow([
            e.enrolled_date,
            e.employee_name,
            e.department,
            e.course_code,
            e.course_name,
            e.status,
            e.score,
            e.completion_date,
            e.due_date
        ])
        
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=training_report.csv"}
    )

@training_bp.route('/reminders/send', methods=['POST'])
@login_required
@permission_required('training', level='edit')
def send_reminders():
    if not current_user.is_compliance_officer():
        return redirect(url_for('training.list_courses'))
        
    # Logic to find overdue/pending enrollments and "send" emails
    # For now, we just log it or flash a message
    count = 0
    enrollments = TrainingEnrollment.get_all_enrollments({'status': 'enrolled'})
    # Filter for those past due or close to due if we had logic
    # checking for 'overdue' status in DB or calculating it
    
    for e in enrollments:
        # Simulate sending email
        print(f"Sending reminder to {e.employee_name} for course {e.course_code}")
        count += 1
        
    flash(gettext('Sent %(count)s reminder emails.', count=count), 'success')
    return redirect(url_for('training.training_report'))

@training_bp.route('/reminders/send/<int:enrollment_id>', methods=['POST'])
@login_required
@permission_required('training', level='view')
def send_single_reminder(enrollment_id):
    if not current_user.is_compliance_officer():
        return redirect(url_for('training.list_courses'))
    
    flash(gettext('Reminder email sent successfully.'), 'success')
    return redirect(url_for('training.training_report'))

@training_bp.route('/enroll', methods=['POST'])
@login_required
@permission_required('training', level='view')
def enroll_user():
    """Self-enroll or admin/manager enroll"""
    course_id = request.form.get('course_id')
    user_id = request.form.get('user_id', current_user.id)

    if int(user_id) != current_user.id:
        target_user = User.get_by_id(user_id)
        if not target_user or not current_user.can_assign_training_to(target_user):
            flash(gettext('Access denied.'), 'danger')
            return redirect(url_for('training.list_courses'))

    if TrainingEnrollment.enroll(course_id, user_id, current_user.id):
        AuditLog.log(current_user.id, 'Training Enrollment', 'Training', course_id, f'Enrolled user {user_id} in course {course_id}', request.remote_addr)
        flash(gettext('Enrolled successfully.'), 'success')
    else:
        flash(gettext('Already enrolled.'), 'info')

    return redirect(url_for('training.list_courses'))

@training_bp.route('/bulk-enroll', methods=['POST'])
@login_required
@permission_required('training', level='view')
def bulk_enroll_users():
    """Assign one or more courses to one or more users at once (compliance officers and
    managers with training assignment authority)."""
    if not current_user.can_manage_training():
        flash(gettext('Access denied.'), 'danger')
        return redirect(url_for('training.training_report'))

    course_ids = request.form.getlist('course_ids')
    user_ids = request.form.getlist('user_ids')
    due_days = int(request.form.get('due_days', 30))

    assigned = 0
    skipped_users = 0

    for uid in user_ids:
        target_user = User.get_by_id(uid)
        if not target_user or not current_user.can_assign_training_to(target_user):
            skipped_users += 1
            continue
        for cid in course_ids:
            if TrainingEnrollment.enroll(cid, uid, current_user.id, due_days):
                assigned += 1

    AuditLog.log(current_user.id, 'Bulk Training Enrollment', 'Training', None,
                 f'Bulk-assigned {len(course_ids)} course(s) to {len(user_ids)} user(s) '
                 f'({assigned} enrollments created, {skipped_users} users skipped)', request.remote_addr)

    if skipped_users:
        flash(f'Bulk assignment complete: {assigned} enrollment(s) created. '
              f'{skipped_users} user(s) skipped (outside your assignment scope).', 'warning')
    else:
        flash(gettext('Bulk assignment complete: %(assigned)s enrollment(s) created.', assigned=assigned), 'success')

    return redirect(url_for('training.training_report'))

@training_bp.route('/course/<int:id>/heartbeat', methods=['POST'])
@training_bp.route('/course/<int:id>/update-progress', methods=['POST'])  # older player pages
@login_required
@permission_required('training', level='view')
def heartbeat(id):
    """Player heartbeat (every few seconds while the video plays). The server
    credits watch time from its own clock; any 'completed' flag sent by the
    client is ignored."""
    from flask import jsonify
    course = TrainingCourse.get_by_id(id)
    enrollment = next((e for e in TrainingEnrollment.get_user_enrollments(current_user.id)
                      if e.course_id == id), None)
    if not course or not enrollment:
        return jsonify({'success': False, 'message': 'Enrollment not found'}), 404
    data = request.get_json(silent=True) or {}
    playing = data.get('playing', True) is not False
    result = enrollment.heartbeat(course, playing=playing)  # any length sent by the browser is ignored
    return jsonify(dict(success=True, **result))

@training_bp.route('/certificate/<int:cert_id>/download')
@login_required
def download_certificate(cert_id):
    """Generate and download a professional PDF certificate"""
    cert = TrainingCertificate.get_by_id(cert_id)
    if not cert or (not current_user.is_compliance_officer() and cert.employee_id != current_user.id):
        flash(gettext('Certificate not found or access denied.'), 'danger')
        return redirect(url_for('training.my_certificates'))

    from fpdf import FPDF
    from utils.arabic_pdf import shape, add_unicode_font, latin1_safe
    from urllib.parse import quote
    from werkzeug.utils import secure_filename
    import os

    # ComplyNex brand colors
    COMPLYNEX_NAVY  = (20, 20, 20)
    COMPLYNEX_BLUE  = (226, 9, 21)
    COMPLYNEX_GOLD  = (226, 9, 21)
    COMPLYNEX_GRAY  = (100, 100, 100)
    COMPLYNEX_LIGHT = (245, 247, 250)
    LOGO_PATH = '/opt/complynex/static/images/logo.png'

    class CertificatePDF(FPDF):
        def header(self):
            # Navy header bar
            self.set_fill_color(*COMPLYNEX_NAVY)
            self.rect(0, 0, 297, 35, 'F')
            # Gold top accent
            self.set_fill_color(*COMPLYNEX_GOLD)
            self.rect(0, 0, 297, 3, 'F')
            # Logo
            if os.path.exists('static/images/logo.png'):
                self.image('static/images/logo.png', x=12, y=7, w=28)
            # ComplyNex name
            self.set_y(10)
            self.set_x(55)
            self.set_font(FONT, 'B', 16)
            self.set_text_color(255, 255, 255)
            self.cell(0, 8, 'ComplyNex', 0, 1, 'L')
            self.set_x(55)
            self.set_font(FONT, '', 9)
            self.set_text_color(*COMPLYNEX_GOLD)
            self.cell(0, 6, 'AML COMPLIANCE PLATFORM', 0, 1, 'L')
            # Light body background
            self.set_fill_color(*COMPLYNEX_LIGHT)
            self.rect(0, 35, 297, 165, 'F')
            # Gold outer border
            self.set_draw_color(*COMPLYNEX_GOLD)
            self.set_line_width(1.0)
            self.rect(8, 38, 281, 155)
            # Navy inner border
            self.set_draw_color(*COMPLYNEX_NAVY)
            self.set_line_width(0.3)
            self.rect(11, 41, 275, 149)

        def footer(self):
            self.set_fill_color(*COMPLYNEX_NAVY)
            self.rect(0, 195, 297, 15, 'F')
            self.set_y(197)
            self.set_font(FONT, 'I', 7)
            self.set_text_color(180, 180, 180)
            self.cell(0, 5, 'Official Training Document Issued by ComplyNex', 0, 1, 'C')
            self.set_text_color(*COMPLYNEX_GOLD)
            self.set_font(FONT, 'B', 7)
            self.cell(0, 5, T(f'Verification ID: {cert.certificate_number}'), 0, 0, 'C')

    pdf = CertificatePDF(orientation='L', unit='mm', format='A4')
    # Unicode font so Arabic names / course titles render (core fonts are latin-1 only).
    FONT = add_unicode_font(pdf) or 'helvetica'
    T = shape if FONT != 'helvetica' else latin1_safe
    pdf.add_page()

    # Official document label
    pdf.set_y(50)
    pdf.set_font(FONT, 'B', 11)
    pdf.set_text_color(*COMPLYNEX_GRAY)
    pdf.cell(0, 8, '- OFFICIAL DOCUMENT -', 0, 1, 'C')

    # Main title
    pdf.ln(2)
    pdf.set_font(FONT, 'B', 34)
    pdf.set_text_color(*COMPLYNEX_NAVY)
    pdf.cell(0, 18, 'CERTIFICATE OF COMPLETION', 0, 1, 'C')

    # Gold divider
    pdf.set_draw_color(*COMPLYNEX_GOLD)
    pdf.set_line_width(0.8)
    pdf.line(80, pdf.get_y(), 217, pdf.get_y())
    pdf.ln(6)

    pdf.set_font(FONT, '', 13)
    pdf.set_text_color(*COMPLYNEX_GRAY)
    pdf.cell(0, 8, 'This certificate is proudly presented to', 0, 1, 'C')

    # Employee name
    pdf.ln(4)
    pdf.set_font(FONT, 'B', 30)
    pdf.set_text_color(*COMPLYNEX_BLUE)
    pdf.cell(0, 16, T((cert.employee_name or '').upper()), 0, 1, 'C')

    # Name underline
    pdf.set_draw_color(*COMPLYNEX_GOLD)
    pdf.set_line_width(0.5)
    pdf.line(80, pdf.get_y(), 217, pdf.get_y())
    pdf.ln(6)

    pdf.set_font(FONT, '', 13)
    pdf.set_text_color(*COMPLYNEX_GRAY)
    pdf.cell(0, 8, 'for successfully completing the compliance training course', 0, 1, 'C')

    # Course name
    pdf.ln(3)
    pdf.set_font(FONT, 'B', 20)
    pdf.set_text_color(*COMPLYNEX_NAVY)
    pdf.multi_cell(0, 12, T(cert.course_name), 0, 'C')

    # Score badge
    pdf.set_y(148)
    pdf.set_x(220)
    pdf.set_fill_color(*COMPLYNEX_NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(FONT, 'B', 10)
    pdf.cell(50, 8, f'Score: {cert.score}%', 0, 0, 'C', fill=True)

    # Bottom details
    pdf.set_y(158)
    pdf.set_x(25)
    pdf.set_font(FONT, '', 10)
    pdf.set_text_color(*COMPLYNEX_GRAY)
    pdf.cell(35, 6, 'Course Code:', 0, 0, 'L')
    pdf.set_font(FONT, 'B', 10)
    pdf.set_text_color(*COMPLYNEX_NAVY)
    pdf.cell(35, 6, T(cert.course_code), 0, 0, 'L')

    pdf.set_x(110)
    pdf.set_font(FONT, '', 10)
    pdf.set_text_color(*COMPLYNEX_GRAY)
    pdf.cell(25, 6, 'Issue Date:', 0, 0, 'L')
    pdf.set_font(FONT, 'B', 10)
    pdf.set_text_color(*COMPLYNEX_NAVY)
    pdf.cell(40, 6, (cert.issue_date.strftime('%B %d, %Y') if hasattr(cert.issue_date, 'strftime') else str(cert.issue_date).split(' ')[0]) if getattr(cert, 'issue_date', None) else __import__('datetime').datetime.now().strftime('%B %d, %Y'), 0, 0, 'L')

    # Signature
    pdf.set_y(155)
    pdf.set_x(215)
    pdf.set_draw_color(*COMPLYNEX_NAVY)
    pdf.set_line_width(0.4)
    pdf.line(215, 163, 268, 163)
    pdf.set_y(164)
    pdf.set_x(215)
    pdf.set_font(FONT, '', 9)
    pdf.set_text_color(*COMPLYNEX_GRAY)
    pdf.cell(53, 5, 'Legal and Compliance Director', 0, 1, 'C')
    pdf.set_x(215)
    pdf.set_font(FONT, 'B', 9)
    pdf.set_text_color(*COMPLYNEX_NAVY)
    pdf.cell(53, 5, 'ComplyNex', 0, 1, 'C')

    from flask import make_response
    response = make_response(bytes(pdf.output()))
    filename = f"Certificate_{cert.course_code}_{datetime.now().strftime('%Y%m%d')}.pdf"
    ascii_name = secure_filename(filename) or f'Certificate_{cert.id}.pdf'
    AuditLog.log(current_user.id, 'Certificate Download', 'Training', cert.id, f'Downloaded certificate {cert.certificate_number} for {cert.course_code}', request.remote_addr)
    response.headers['Content-Type'] = 'application/pdf'
    # RFC 5987: ASCII fallback + UTF-8 name (an Arabic course code broke the latin-1 header)
    response.headers['Content-Disposition'] = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'
    return response
