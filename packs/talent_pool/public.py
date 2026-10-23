# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Public careers pages (/careers/): landing, application form, e-mail
confirmation code, privacy notice. No staff login; anonymous visitors.

Defences: CSRF token, honeypot field, minimum fill time (signed timestamp),
per-IP rate limits, server-side validation of every field, length caps,
CV checks (cv.py), parameterised SQL only, the applicant's e-mail proven
by a one-time code before the application reaches staff."""
import re
from datetime import datetime, timezone

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, session,
                   url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from extensions import limiter
from utils import public_paths

from . import cv, service as S

PREFIX = public_paths.register('/careers')
public_bp = Blueprint('talent_public', __name__, url_prefix='/careers')

MIN_FILL_SECONDS = 8
MAX_REQUEST_BYTES = cv.MAX_BYTES + 512 * 1024


def t(en, ar):
    return ar if getattr(g, 'tp_ar', False) else en


def L(row_or_pair, field=None):
    if field is None:                       # (en, ar) tuple
        return row_or_pair[1] if g.tp_ar and row_or_pair[1] else row_or_pair[0]
    if g.tp_ar and row_or_pair.get(f'{field}_ar'):
        return row_or_pair[f'{field}_ar']
    return row_or_pair.get(f'{field}_en')


@public_bp.before_request
def _gate():
    g.tp_ar = session.get('academy_lang') == 'ar'
    if request.endpoint in ('talent_public.set_lang', 'talent_public.privacy'):
        return None
    if not S.public_enabled():
        return render_template('talent_pool/public/closed.html'), 503
    if request.method == 'POST' and (request.content_length or 0) > MAX_REQUEST_BYTES:
        abort(413)
    return None


@public_bp.after_request
def _headers(resp):
    resp.headers['X-Robots-Tag'] = 'noindex' if request.endpoint != 'talent_public.landing' else 'index, follow'
    resp.headers['Cache-Control'] = 'no-store' if request.method == 'POST' or request.endpoint in (
        'talent_public.apply', 'talent_public.verify') else resp.headers.get('Cache-Control', 'no-cache')
    return resp


@public_bp.context_processor
def _ctx():
    return {'t': t, 'L': L, 'ar': getattr(g, 'tp_ar', False), 'brand': S.branding(), 'TPS': S}


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='talent-form')


@public_bp.route('/lang/<code>')
def set_lang(code):
    session['academy_lang'] = 'ar' if code == 'ar' else 'en'
    nxt = request.args.get('next') or ''
    return redirect(nxt if nxt.startswith(PREFIX) and '//' not in nxt else url_for('talent_public.landing'))


@public_bp.route('/')
def landing():
    if request.args.get('src'):
        session['tp_src'] = re.sub(r'[^a-z0-9_\-]', '', request.args['src'].lower())[:30]
    return render_template('talent_pool/public/landing.html', categories=S.categories())


@public_bp.route('/privacy')
def privacy():
    return render_template('talent_pool/public/privacy.html')


def _int(v, lo, hi):
    try:
        v = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def _txt(form, key, n):
    v = (form.get(key) or '').strip()
    v = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', v)
    return v[:n] or None


def _validate(form, cats):
    errors, d = [], {}
    d['full_name'] = _txt(form, 'full_name', 120)
    if not d['full_name'] or len(d['full_name']) < 5 or len(d['full_name'].split()) < 2:
        errors.append(t('Please enter your full name (at least two names).', 'يُرجى كتابة اسمك بالكامل (اسمان على الأقل).'))
    email = (form.get('email') or '').strip().lower()[:254]
    if not S.EMAIL_RE.match(email):
        errors.append(t('Please enter a valid e-mail address.', 'يُرجى كتابة بريد إلكتروني صحيح.'))
    d['email'] = email
    phone = S.clean_phone(form.get('phone'))
    if not S.PHONE_RE.match(phone):
        errors.append(t('Please enter a valid mobile number (with country code if outside Egypt).',
                        'يُرجى كتابة رقم هاتف محمول صحيح (مع كود الدولة إن كنت خارج مصر).'))
    d['phone'] = phone
    wa = S.clean_phone(form.get('whatsapp'))
    d['whatsapp'] = wa if wa and S.PHONE_RE.match(wa) else None
    d['city'] = _txt(form, 'city', 80)
    d['country'] = _txt(form, 'country', 60)
    ids = {c['id'] for c in cats}
    pc = _int(form.get('primary_category'), 1, 10 ** 9)
    if pc not in ids:
        errors.append(t('Please choose your main area of expertise.', 'يُرجى اختيار مجال خبرتك الأساسي.'))
    d['primary_category_id'] = pc
    d['other_category_ids'] = [i for i in (_int(x, 1, 10 ** 9) for x in form.getlist('other_categories')[:12])
                               if i in ids and i != pc]
    d['years_experience'] = _int(form.get('years_experience'), 0, 60)
    if d['years_experience'] is None:
        errors.append(t('Please enter your years of experience.', 'يُرجى كتابة عدد سنوات الخبرة.'))
    d['current_title'] = _txt(form, 'current_title', 120)
    d['seniority'] = form.get('seniority') if form.get('seniority') in S.SENIORITY else None
    d['availability'] = form.get('availability') if form.get('availability') in S.AVAILABILITY else None
    if not d['availability']:
        errors.append(t('Please choose your availability.', 'يُرجى اختيار الوقت المتاح لك.'))
    d['engagement'] = form.get('engagement') if form.get('engagement') in S.ENGAGEMENT else None
    d['work_mode'] = form.get('work_mode') if form.get('work_mode') in S.WORK_MODE else None
    d['languages'] = _txt(form, 'languages', 120)
    d['certifications'] = _txt(form, 'certifications', 400)
    li = S.clean_linkedin(form.get('linkedin_url'))
    if li is False:
        errors.append(t('The LinkedIn link should look like https://www.linkedin.com/in/your-name',
                        'يجب أن يكون رابط لينكدإن بالشكل https://www.linkedin.com/in/your-name'))
    d['linkedin_url'] = li or None
    d['expected_rate'] = _txt(form, 'expected_rate', 80)
    d['summary'] = _txt(form, 'summary', 2000)
    if not d['summary'] or len(d['summary']) < 40:
        errors.append(t('Please describe your experience in a few lines (at least 40 characters).',
                        'يُرجى كتابة نبذة عن خبرتك في سطور قليلة (40 حرفًا على الأقل).'))
    if not form.get('consent_privacy'):
        errors.append(t('Please accept the privacy notice.', 'يُرجى الموافقة على إشعار الخصوصية.'))
    if not form.get('ack_terms'):
        errors.append(t('Please confirm you understand that engagements are under an NDA and a consulting contract.',
                        'يُرجى تأكيد علمك بأن أي تعاون يتم بموجب اتفاقية سرية (NDA) وعقد استشارات.'))
    src = (session.get('tp_src') or ('linkedin' if 'linkedin' in (request.referrer or '') else 'website'))
    d['source'] = re.sub(r'[^a-z0-9_\-]', '', src.lower())[:30]
    return errors, d


@public_bp.route('/apply', methods=['GET', 'POST'])
@limiter.limit('6 per hour; 20 per day', methods=['POST'])
def apply():
    cats = S.categories()
    if request.method == 'GET':
        if request.args.get('src'):
            session['tp_src'] = re.sub(r'[^a-z0-9_\-]', '', request.args['src'].lower())[:30]
        return render_template('talent_pool/public/apply.html', form={}, categories=cats,
                               stamp=_serializer().dumps('f'))
    form = request.form
    bot = bool(form.get('website'))
    try:
        _, issued = _serializer().loads(form.get('stamp') or '', max_age=6 * 3600, return_timestamp=True)
        age_ok = (datetime.now(timezone.utc) - issued).total_seconds() >= MIN_FILL_SECONDS
    except (BadSignature, SignatureExpired):
        age_ok = False
    errors, d = _validate(form, cats)
    f = request.files.get('cv')
    cv_meta, cv_data = {}, None
    if f and f.filename:
        try:
            cv_data, ext, original = cv.check(f)
            cv_meta = {'original': original, 'ext': ext}
        except cv.CVError as e:
            errors.append(L(cv.MESSAGES.get(str(e), cv.MESSAGES['signature'])))
    if bot or not age_ok:
        # Same neutral message a person would get after a long pause — no hint to a bot.
        errors.append(t('Please review the form and submit it again.', 'يُرجى مراجعة البيانات وإرسال النموذج مرة أخرى.'))
    if errors:
        for e in errors:
            flash(e, 'danger')
        return render_template('talent_pool/public/apply.html', form=form, categories=cats,
                               stamp=_serializer().dumps('f')), 400
    S.purge_unverified(current_app.root_path)
    # A double click or a second try before confirming: replace the earlier
    # unconfirmed submission of this e-mail instead of keeping two copies.
    S.drop_unverified_for(d['email'], current_app.root_path)
    if cv_data:
        path, sha, size = cv.store(current_app.root_path, cv_data, cv_meta['ext'])
        cv_meta.update(path=path, sha256=sha, size=size)
    row = S.create_application(d, cv_meta)
    session['tp_pending'] = row['id']
    app_row = S.get(row['id'])
    if not S.issue_otp(app_row):
        flash(t('We could not send the confirmation e-mail right now. Use "send a new code" in a few minutes.',
                'تعذر إرسال رسالة التأكيد حاليًا. اضغط «أرسل رمزًا جديدًا» بعد دقائق.'), 'warning')
    return redirect(url_for('talent_public.verify'))


@public_bp.route('/verify', methods=['GET', 'POST'])
@limiter.limit('30 per hour', methods=['POST'])
def verify():
    app_id = session.get('tp_pending')
    app_row = S.get(app_id) if app_id else None
    if not app_row or app_row['status'] != 'unverified':
        session.pop('tp_pending', None)
        return redirect(url_for('talent_public.apply'))
    if request.method == 'POST':
        if request.form.get('resend'):
            ok, wait = S.otp_send_allowed(app_id)
            if not ok:
                flash(t(f'A code was sent recently. You can request a new one in {wait} seconds.',
                        f'تم إرسال رمز مؤخرًا. يمكنك طلب رمز جديد بعد {wait} ثانية.'), 'warning')
            elif S.issue_otp(app_row):
                flash(t('A new code is on its way.', 'تم إرسال رمز جديد.'), 'info')
            return redirect(url_for('talent_public.verify'))
        result = S.check_otp(app_id, request.form.get('code'))
        if result == 'ok':
            S.verify(app_id)
            session.pop('tp_pending', None)
            session['tp_done'] = app_row['ref']
            try:
                done = S.get(app_id)
                S.send_received_email(done, getattr(g, 'tp_ar', False))
                base = (S.setting('staff_base_url') or request.url_root).rstrip('/')
                S.notify_staff(done, base + url_for('talent.detail', app_id=app_id))
            except Exception:
                current_app.logger.warning('talent: confirmation / staff notification failed', exc_info=True)
            return redirect(url_for('talent_public.thanks'))
        flash({'expired': t('That code has expired. Request a new one.', 'انتهت صلاحية الرمز. اطلب رمزًا جديدًا.'),
               'locked': t('Too many attempts. Request a new code.', 'تجاوزت عدد المحاولات. اطلب رمزًا جديدًا.'),
               'none': t('Request a new code.', 'اطلب رمزًا جديدًا.')}.get(
            result, t('That code is not correct.', 'الرمز غير صحيح.')), 'danger')
    masked = re.sub(r'(^.).*(@.*$)', r'\1•••\2', app_row['email'])
    return render_template('talent_pool/public/verify.html', masked=masked)


@public_bp.route('/thanks')
def thanks():
    ref = session.get('tp_done')
    if not ref:
        return redirect(url_for('talent_public.landing'))
    return render_template('talent_pool/public/thanks.html', ref=ref)
