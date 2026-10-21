# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Integrys Academy — public learner portal (academy.integrysconsult.com).

Isolation rules enforced here and in nginx:
  * on the Academy host only /academy/* (minus /academy/admin) and /static/* answer;
  * learners authenticate by e-mail OTP into session['academy_lid'] — never Flask-Login;
  * the learner portal is closed until the 'public_enabled' flag is switched on
    (staff can preview with a signed link from the admin settings page).
"""
from functools import wraps

from flask_babel import gettext
from flask import (Blueprint, abort, flash, g, make_response, redirect, render_template,
                   request, session, url_for, current_app)
from itsdangerous import URLSafeTimedSerializer, BadSignature

from extensions import limiter
from . import service as S

academy_bp = Blueprint('academy', __name__, url_prefix='/academy')

PUBLIC_ENDPOINTS_ALWAYS_OPEN = {'academy.verify', 'academy.verify_lookup', 'academy.set_lang',
                                'academy.preview', 'academy.privacy_notice'}


# ------------------------------------------------------------- isolation
@academy_bp.record_once
def _install_host_guard(state):
    app = state.app

    @app.before_request
    def _academy_host_guard():
        host = (request.host or '').split(':')[0].lower()
        path = request.path
        if host == S.ACADEMY_HOST:
            if path.startswith('/static/'):
                return None
            if path == '/':
                return redirect('/academy/')
            if not path.startswith('/academy/') and path != '/academy' or path.startswith('/academy/admin'):
                abort(404)
        elif path.startswith('/academy') and not path.startswith('/academy/admin'):
            # learner pages live only on the Integrys host
            if app.config.get('SESSION_COOKIE_SECURE'):
                return redirect(f'{S.PUBLIC_BASE}{request.full_path.rstrip("?")}', code=302)
        return None


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='academy-preview')


@academy_bp.before_request
def _gate():
    g.ar = session.get('academy_lang') == 'ar'
    g.learner = S.learner_by_id(session.get('academy_lid'))
    if session.get('academy_lid') and not g.learner:
        session.pop('academy_lid', None)
    if request.endpoint in PUBLIC_ENDPOINTS_ALWAYS_OPEN:
        return None
    if not S.public_enabled() and not session.get('academy_preview'):
        return render_template('academy/closed.html'), 503
    return None


def t(en, ar):
    return ar if getattr(g, 'ar', False) else en


@academy_bp.app_template_filter('ia_body')
def ia_body(text):
    return S.render_body(text)


def learner_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.learner or g.learner['status'] != 'active':
            session['academy_next'] = request.path
            return redirect(url_for('academy.login'))
        return f(*a, **kw)
    return wrapper


def _L(row, field):
    """Pick the Arabic field when in Arabic mode and it is filled."""
    if g.ar and row.get(f'{field}_ar'):
        return row[f'{field}_ar']
    return row.get(f'{field}_en')


@academy_bp.context_processor
def _ctx():
    # blueprint-scoped: these names never leak into ComplyNex staff templates
    from . import media as M
    return {'t': t, 'L': _L, 'learner': getattr(g, 'learner', None), 'ar': getattr(g, 'ar', False),
            'ia_public_base': S.PUBLIC_BASE, 'embed_url': M.embed_url, 'ext_of': M.ext_of,
            'PROVIDERS': S.PROVIDERS}


# ----------------------------------------------------------------- misc
@academy_bp.route('/lang/<code>')
def set_lang(code):
    session['academy_lang'] = 'ar' if code == 'ar' else 'en'
    nxt = request.args.get('next') or url_for('academy.home')
    return redirect(nxt if nxt.startswith('/academy') else url_for('academy.home'))


@academy_bp.route('/preview/<token>')
def preview(token):
    try:
        _serializer().loads(token, max_age=14 * 86400)
    except BadSignature:
        abort(404)
    session['academy_preview'] = True
    flash(gettext('Preview mode — the Academy is not public yet.'), 'info')
    return redirect(url_for('academy.home'))


@academy_bp.route('/privacy-notice')
def privacy_notice():
    return render_template('academy/privacy_notice.html',
                           retention=S.setting('retention_months', '36'),
                           version=S.setting('privacy_version', '2026-10'))


# ----------------------------------------------------------------- home
@academy_bp.route('/')
def home():
    for k in ('utm_source', 'utm_medium', 'utm_campaign', 'src'):
        if request.args.get(k):
            session[f'ia_{k}'] = request.args[k][:80]
    if g.learner and g.learner['status'] == 'active':
        return redirect(url_for('academy.dashboard'))
    return render_template('academy/home.html', courses=S.published_courses())


# --------------------------------------------------------- registration
ERRORS = {
    'invalid':    ('Please enter a valid email address.', 'من فضلك أدخل بريدًا إلكترونيًا صحيحًا.'),
    'free':       ('Please register with your work email. Personal providers such as Gmail, Yahoo or Outlook are not accepted.',
                   'من فضلك سجّل ببريد العمل. لا نقبل البريد الشخصي مثل Gmail أو Yahoo أو Outlook.'),
    'disposable': ('Temporary email addresses are not accepted.', 'لا نقبل عناوين البريد المؤقتة.'),
    'no_mx':      ('We could not find a mail server for that domain. Please check the address.',
                   'لم نجد خادم بريد لهذا النطاق. من فضلك راجع العنوان.'),
}


def _err(key):
    en, ar = ERRORS[key]
    return ar if g.ar else en


@academy_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('10 per hour', methods=['POST'])
def register():
    form = request.form
    if request.method == 'POST':
        errors = []
        name = (form.get('full_name') or '').strip()
        cert_name = (form.get('certificate_name') or '').strip()
        if len(name) < 3:
            errors.append(t('Please enter your full name.', 'من فضلك أدخل اسمك بالكامل.'))
        if not S.LATIN_NAME_RE.match(cert_name):
            errors.append(t('Certificate name must be in English letters (as it should appear on your certificate).',
                            'الاسم على الشهادة لازم يكون بحروف إنجليزية (كما تريده أن يظهر على الشهادة).'))
        if not (form.get('company') or '').strip():
            errors.append(t('Please enter your company.', 'من فضلك أدخل اسم الشركة.'))
        if not form.get('consent_training'):
            errors.append(t('Please accept the privacy notice to register.',
                            'من فضلك وافق على إشعار الخصوصية لإتمام التسجيل.'))
        ok, email, domain, free, key = S.check_business_email(form.get('email'))
        if not ok:
            errors.append(_err(key))
        if form.get('website'):           # honeypot
            errors.append('Error.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('academy/register.html', form=form), 400
        utm = {'source': session.get('ia_src') or ('linkedin' if 'linkedin' in (request.referrer or '') else 'website'),
               'utm_source': session.get('ia_utm_source'), 'utm_medium': session.get('ia_utm_medium'),
               'utm_campaign': session.get('ia_utm_campaign')}
        learner, is_new = S.create_or_refresh_pending(form, email, domain, free, utm)
        if not is_new:
            # Already active: don't disclose that; just send a login code.
            return _start_otp(learner, 'login')
        return _start_otp(learner, 'verify')
    return render_template('academy/register.html', form={})


def _start_otp(learner, purpose):
    allowed, wait = S.otp_send_allowed(learner['id'])
    session['academy_pending'] = {'lid': learner['id'], 'purpose': purpose}
    if not allowed:
        flash(t(f'A code was sent recently. You can request a new one in {wait} seconds.',
                f'تم إرسال رمز مؤخرًا. يمكنك طلب رمز جديد بعد {wait} ثانية.'), 'warning')
    elif not S.issue_otp(learner, purpose):
        flash(t('We could not send the email right now. Please try again in a few minutes.',
                'تعذر إرسال البريد حاليًا. حاول مرة أخرى بعد دقائق.'), 'danger')
    return redirect(url_for('academy.otp'))


@academy_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('15 per hour', methods=['POST'])
def login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        learner = S.learner_by_email(email) if S.EMAIL_RE.match(email) else None
        if learner and learner['status'] in ('active', 'pending'):
            return _start_otp(learner, 'login' if learner['status'] == 'active' else 'verify')
        # Same response whether or not the address exists (no account enumeration).
        session['academy_pending'] = {'lid': None, 'purpose': 'login'}
        return redirect(url_for('academy.otp'))
    return render_template('academy/login.html')


@academy_bp.route('/verify-code', methods=['GET', 'POST'])
@limiter.limit('30 per hour', methods=['POST'])
def otp():
    pending = session.get('academy_pending')
    if not pending:
        return redirect(url_for('academy.login'))
    if request.method == 'POST':
        if request.form.get('resend'):
            learner = S.learner_by_id(pending['lid'])
            if learner:
                return _start_otp(learner, pending['purpose'])
            flash(t('If the address is registered, a new code is on its way.',
                    'إذا كان العنوان مسجلًا، فسيصلك رمز جديد.'), 'info')
            return redirect(url_for('academy.otp'))
        result = S.check_otp(pending['lid'], pending['purpose'], request.form.get('code')) if pending['lid'] else 'wrong'
        if result == 'ok':
            lid = pending['lid']
            session.pop('academy_pending', None)
            if pending['purpose'] == 'verify':
                S.activate(lid)
            session.permanent = True
            session['academy_lid'] = lid
            S.touch(lid, login=True)
            S.audit('login', lid)
            nxt = session.pop('academy_next', None)
            return redirect(nxt if nxt and nxt.startswith('/academy') else url_for('academy.dashboard'))
        msg = {'expired': t('That code has expired. Request a new one.', 'انتهت صلاحية الرمز. اطلب رمزًا جديدًا.'),
               'locked': t('Too many attempts. Request a new code.', 'محاولات كثيرة. اطلب رمزًا جديدًا.'),
               'none': t('Request a new code.', 'اطلب رمزًا جديدًا.')}.get(
            result, t('That code is not correct.', 'الرمز غير صحيح.'))
        flash(msg, 'danger')
    return render_template('academy/otp.html', purpose=pending.get('purpose'))


@academy_bp.route('/logout', methods=['POST'])
def logout():
    session.pop('academy_lid', None)
    session.pop('academy_pending', None)
    return redirect(url_for('academy.home'))


# ------------------------------------------------------------ learning
@academy_bp.route('/my')
@learner_required
def dashboard():
    from database.db import get_db
    rows = get_db().execute("""SELECT e.*, c.slug, c.title_en, c.title_ar, c.pass_mark,
                               (SELECT count(*) FROM academy_lessons l WHERE l.course_id=c.id) AS lesson_count
                               FROM academy_enrollments e JOIN academy_courses c ON c.id=e.course_id
                               WHERE e.learner_id=%s ORDER BY e.started_at DESC""", (g.learner['id'],)).fetchall()
    certs = get_db().execute("""SELECT * FROM academy_certificates WHERE learner_id=%s ORDER BY issued_at DESC""",
                             (g.learner['id'],)).fetchall()
    enrolled = {r['course_id'] for r in rows}
    available = [c for c in S.published_courses() if c['id'] not in enrolled]
    return render_template('academy/dashboard.html', enrollments=rows, certs=certs, available=available)


@academy_bp.route('/course/<slug>')
@learner_required
def course(slug):
    c = S.course_by_slug(slug, include_drafts=bool(session.get('academy_preview')))
    if not c:
        abort(404)
    enr = S.enrollment(g.learner['id'], c['id'], create=True)
    S.touch(g.learner['id'])
    ls = S.lessons(c['id'])
    pos = request.args.get('lesson', type=int)
    if pos is None:
        done = set(enr['lessons_done'] or [])
        pos = next((l['position'] for l in ls if l['position'] not in done), ls[0]['position'] if ls else None)
    current = next((l for l in ls if l['position'] == pos), None)
    vp = S.video_progress(enr['id'], current['id']) if current and current.get('video_file') else None
    return render_template('academy/course.html', c=c, enr=enr, lessons=ls, current=current, vp=vp,
                           ready=S.all_lessons_done(enr, c['id']),
                           cooldown=S.cooldown_remaining(enr, c))


@academy_bp.route('/course/<slug>/lesson/<int:pos>/done', methods=['POST'])
@learner_required
def lesson_done(slug, pos):
    c = S.course_by_slug(slug, include_drafts=bool(session.get('academy_preview')))
    if not c:
        abort(404)
    enr = S.enrollment(g.learner['id'], c['id'], create=True)
    ls = S.lessons(c['id'])
    cur = next((l for l in ls if l['position'] == pos), None)
    if cur and not S.video_ok(enr, cur):
        flash('شاهد الفيديو كاملًا قبل إكمال الدرس.' if g.ar else 'Please watch the whole video before completing this lesson.', 'warning')
        return redirect(url_for('academy.course', slug=slug, lesson=pos))
    S.mark_lesson_done(enr, pos)
    nxt = next((l['position'] for l in ls if l['position'] > pos), None)
    if nxt is None:
        return redirect(url_for('academy.course', slug=slug) + '#assessment')
    return redirect(url_for('academy.course', slug=slug, lesson=nxt))


@academy_bp.route('/course/<slug>/assessment', methods=['GET', 'POST'])
@learner_required
@limiter.limit('20 per hour', methods=['POST'])
def quiz(slug):
    c = S.course_by_slug(slug, include_drafts=bool(session.get('academy_preview')))
    if not c:
        abort(404)
    enr = S.enrollment(g.learner['id'], c['id'], create=True)
    if not S.all_lessons_done(enr, c['id']):
        flash(t('Complete all lessons before the assessment.', 'أكمل كل الدروس قبل الاختبار.'), 'warning')
        return redirect(url_for('academy.course', slug=slug))
    wait = S.cooldown_remaining(enr, c)
    if wait and request.method == 'GET':
        flash(t(f'You can retake the assessment in {wait // 60 + 1} minutes.',
                f'يمكنك إعادة الاختبار بعد {wait // 60 + 1} دقيقة.'), 'warning')
        return redirect(url_for('academy.course', slug=slug))
    if request.method == 'POST':
        from database.db import get_db
        attempt = get_db().execute("""SELECT * FROM academy_attempts WHERE id=%s AND enrollment_id=%s
                                      AND submitted_at IS NULL""",
                                   (request.form.get('attempt_id', type=int), enr['id'])).fetchone()
        if not attempt:
            flash(t('This assessment session has expired. Please start again.',
                    'انتهت جلسة الاختبار. ابدأ من جديد.'), 'warning')
            return redirect(url_for('academy.quiz', slug=slug))
        score, passed, wrong = S.grade_attempt(attempt, enr, c, request.form)
        cert = S.issue_certificate(g.learner, c, enr, attempt['id'], score) if passed else None
        return render_template('academy/result.html', c=c, score=score, passed=passed, wrong=wrong,
                               cert=cert, total=len(attempt['question_ids']))
    attempt = S.start_attempt(enr, c)
    if not attempt:
        flash(t('The assessment is not available yet.', 'الاختبار غير متاح بعد.'), 'warning')
        return redirect(url_for('academy.course', slug=slug))
    return render_template('academy/quiz.html', c=c, attempt=attempt, questions=S.attempt_questions(attempt))


@academy_bp.route('/lesson/<int:lid>/<kind>')
@learner_required
def lesson_file(lid, kind):
    from database.db import get_db
    from flask import send_file
    from . import media as M
    if kind not in M.KINDS:
        abort(404)
    row = get_db().execute("""SELECT l.*, c.status FROM academy_lessons l JOIN academy_courses c ON c.id=l.course_id
                              WHERE l.id=%s""", (lid,)).fetchone()
    if not row or (row['status'] != 'published' and not session.get('academy_preview')):
        abort(404)
    rel = row.get(f'{kind}_file')
    path = M.abs_path(rel)
    if not path:
        abort(404)
    ext = M.ext_of(rel)
    inline = kind == 'video' or ext == 'pdf'
    name = row.get(f'{kind}_name') or f'lesson-{lid}.{ext}'
    resp = send_file(path, mimetype=M.MIME.get(ext, 'application/octet-stream'), conditional=True,
                     as_attachment=not inline, download_name=name, max_age=3600)
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


# --------------------------------------------------------- certificates
@academy_bp.route('/certificate/<number>.pdf')
@learner_required
def certificate_pdf(number):
    cert = S.cert_by_number(number)
    if not cert or cert['learner_id'] != g.learner['id'] or cert['status'] != 'valid':
        abort(404)
    from .certificate import build_pdf
    resp = make_response(build_pdf(cert))
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = f'attachment; filename=Integrys-Academy-{cert["cert_number"]}.pdf'
    S.audit('certificate_downloaded', g.learner['id'], cert['cert_number'])
    return resp


@academy_bp.route('/verify', methods=['GET', 'POST'])
@limiter.limit('60 per hour')
def verify_lookup():
    if request.method == 'POST':
        return redirect(url_for('academy.verify', number=(request.form.get('number') or '').strip().upper()))
    return render_template('academy/verify.html', cert=None, looked_up=False)


@academy_bp.route('/verify/<number>')
@limiter.limit('120 per hour')
def verify(number):
    cert = S.cert_by_number(number)
    expired = bool(cert and cert['expires_at'] and cert['expires_at'] < S.now())
    return render_template('academy/verify.html', cert=cert, looked_up=True, number=number.upper(),
                           expired=expired)


# -------------------------------------------------------------- privacy
@academy_bp.route('/privacy', methods=['GET', 'POST'])
@learner_required
def privacy():
    from database.db import get_db
    if request.method == 'POST':
        action = request.form.get('action')
        lid = g.learner['id']
        if action == 'marketing_off':
            get_db().execute("UPDATE academy_learners SET consent_marketing=false, consent_marketing_at=NULL WHERE id=%s", (lid,))
            get_db().commit()
            S.audit('marketing_consent_withdrawn', lid)
            flash(t('You will no longer receive marketing emails.', 'لن تصلك رسائل تسويقية بعد الآن.'), 'success')
        elif action == 'marketing_on':
            get_db().execute("UPDATE academy_learners SET consent_marketing=true, consent_marketing_at=now() WHERE id=%s", (lid,))
            get_db().commit()
            S.audit('marketing_consent_given', lid)
            flash(t('Thank you — preference saved.', 'شكرًا — تم حفظ تفضيلك.'), 'success')
        elif action == 'erase' and request.form.get('confirm') == 'DELETE':
            S.erase_learner(lid, None, 'self-service request')
            session.pop('academy_lid', None)
            g.learner = None
            return render_template('academy/erased.html')
        else:
            flash(t('Type DELETE to confirm.', 'اكتب DELETE للتأكيد.'), 'warning')
        return redirect(url_for('academy.privacy'))
    data = get_db().execute("SELECT * FROM academy_learners WHERE id=%s", (g.learner['id'],)).fetchone()
    return render_template('academy/privacy.html', data=data)


# --------------------------------------------------------- mandatory video + ComplyNex CTA
@academy_bp.route('/course/<slug>/lesson/<int:pos>/video', methods=['POST'])
@learner_required
def lesson_video(slug, pos):
    from flask import jsonify
    c = S.course_by_slug(slug, include_drafts=bool(session.get('academy_preview')))
    if not c:
        abort(404)
    lesson = next((l for l in S.lessons(c['id']) if l['position'] == pos), None)
    if not lesson or not lesson.get('video_file'):
        abort(404)
    action = request.form.get('action', 'progress')
    if action not in ('start', 'progress', 'complete'):
        abort(400)
    try:
        t = float(request.form.get('t', 0))
    except ValueError:
        t = 0.0
    enr = S.enrollment(g.learner['id'], c['id'], create=True)
    return jsonify(S.video_event(enr, lesson, action, t))


COMPLYNEX_DEMO = ('mailto:admin@integrysconsult.com?subject=ComplyNex%20demo%20request'
                  '&body=Hello%2C%20I%20would%20like%20a%20demo%20of%20ComplyNex.')


@academy_bp.route('/complynex-demo')
@learner_required
def complynex_demo():
    """Interest signal for ComplyNex: logged against the learner, then opens an e-mail to Integrys."""
    S.audit('complynex_demo_click', g.learner['id'], request.args.get('src', '')[:60])
    return redirect(COMPLYNEX_DEMO)
