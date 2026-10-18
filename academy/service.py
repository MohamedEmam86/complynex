# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Integrys Academy — domain logic.

External learners live in academy_* tables only. Nothing here reads or writes
`users`, the org hierarchy or the permission model.
"""
import hashlib
import hmac
import json
import os
import random
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, request
from markupsafe import Markup, escape

from database.db import get_db
from .free_domains import FREE_PROVIDERS, DISPOSABLE

ACADEMY_HOST = 'academy.integrysconsult.com'
PUBLIC_BASE = f'https://{ACADEMY_HOST}'
OTP_TTL_MIN = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60
OTP_MAX_PER_15MIN = 3

EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+\.)+[A-Za-z]{2,}$')
LATIN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{1,78}[A-Za-z.]$")


def now():
    return datetime.now(timezone.utc)


def client_ip():
    return (request.headers.get('X-Real-IP') or request.remote_addr or '')[:64]


# ---------------------------------------------------------------- settings
def setting(key, default=None):
    row = get_db().execute("SELECT value FROM academy_settings WHERE key=%s", (key,)).fetchone()
    return row['value'] if row and row['value'] is not None else default


def set_setting(key, value, user_id=None):
    db = get_db()
    db.execute("""INSERT INTO academy_settings (key, value, updated_by, updated_at)
                  VALUES (%s,%s,%s,now())
                  ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value,
                  updated_by=EXCLUDED.updated_by, updated_at=now()""", (key, str(value), user_id))
    db.commit()


def public_enabled():
    return setting('public_enabled', 'false') == 'true'


def audit(action, learner_id=None, detail=None, actor_user_id=None, commit=True):
    db = get_db()
    db.execute("INSERT INTO academy_audit (learner_id, actor_user_id, action, detail, ip) "
               "VALUES (%s,%s,%s,%s,%s)",
               (learner_id, actor_user_id, action, (detail or '')[:2000], client_ip()))
    if commit:
        db.commit()


# ---------------------------------------------------------- email checks
def _record_rejection(domain, reason):
    db = get_db()
    db.execute("""INSERT INTO academy_rejected_domains (domain, reason) VALUES (%s,%s)
                  ON CONFLICT (domain, reason) DO UPDATE SET hits = academy_rejected_domains.hits + 1,
                  last_seen = now()""", (domain[:255], reason))
    db.commit()


def _has_mx(domain):
    try:
        import dns.resolver
        r = dns.resolver.Resolver()
        r.lifetime = 4.0
        try:
            return len(r.resolve(domain, 'MX')) > 0
        except dns.resolver.NoAnswer:
            # RFC 5321 implicit MX: an A record can receive mail
            return len(r.resolve(domain, 'A')) > 0
    except Exception:
        return False


def check_business_email(email):
    """Returns (ok, normalised_email, domain, free_flag, error_key)."""
    email = (email or '').strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        return False, email, '', False, 'invalid'
    domain = email.rsplit('@', 1)[1]
    if domain in DISPOSABLE:
        _record_rejection(domain, 'disposable')
        return False, email, domain, False, 'disposable'
    free = domain in FREE_PROVIDERS
    if free and setting('free_email_policy', 'reject') == 'reject':
        _record_rejection(domain, 'free_provider')
        return False, email, domain, True, 'free'
    if not _has_mx(domain):
        _record_rejection(domain, 'no_mx')
        return False, email, domain, free, 'no_mx'
    return True, email, domain, free, None


# --------------------------------------------------------------- learners
def learner_by_email(email):
    return get_db().execute(
        "SELECT * FROM academy_learners WHERE lower(email)=lower(%s) AND status <> 'erased'",
        (email,)).fetchone()


def learner_by_id(lid):
    if not lid:
        return None
    return get_db().execute("SELECT * FROM academy_learners WHERE id=%s AND status <> 'erased'",
                            (lid,)).fetchone()


def create_or_refresh_pending(form, email, domain, free_flag, utm):
    """New registration, or re-registration of an address that never verified."""
    db = get_db()
    existing = learner_by_email(email)
    marketing = bool(form.get('consent_marketing'))
    vals = (form['full_name'].strip()[:120], form['certificate_name'].strip()[:80],
            (form.get('company') or '').strip()[:160], (form.get('job_title') or '').strip()[:120],
            (form.get('country') or '').strip()[:60], marketing,
            setting('privacy_version', '2026-10'))
    if existing:
        if existing['status'] != 'pending':
            return existing, False
        db.execute("""UPDATE academy_learners SET full_name=%s, certificate_name=%s, company=%s,
                      job_title=%s, country=%s, consent_marketing=%s, privacy_version=%s,
                      consent_training_at=now(),
                      consent_marketing_at = CASE WHEN %s THEN now() ELSE NULL END
                      WHERE id=%s""", vals + (marketing, existing['id']))
        db.commit()
        return learner_by_id(existing['id']), True
    row = db.execute("""INSERT INTO academy_learners
        (full_name, certificate_name, company, job_title, country, consent_marketing, privacy_version,
         email, email_domain, free_provider, consent_training_at, consent_marketing_at,
         source, utm_source, utm_medium, utm_campaign, registered_ip)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(), CASE WHEN %s THEN now() ELSE NULL END,
                %s,%s,%s,%s,%s) RETURNING id""",
        vals + (email, domain, free_flag, marketing,
                utm.get('source'), utm.get('utm_source'), utm.get('utm_medium'),
                utm.get('utm_campaign'), client_ip())).fetchone()
    db.commit()
    audit('registered', row['id'], f'domain={domain} marketing={marketing} free={free_flag}')
    return learner_by_id(row['id']), True


def touch(learner_id, login=False):
    db = get_db()
    if login:
        db.execute("UPDATE academy_learners SET last_login_at=now(), last_activity_at=now() WHERE id=%s",
                   (learner_id,))
    else:
        db.execute("UPDATE academy_learners SET last_activity_at=now() WHERE id=%s", (learner_id,))
    db.commit()


# -------------------------------------------------------------------- OTP
def _otp_hash(learner_id, purpose, code):
    key = current_app.config['SECRET_KEY'].encode()
    return hmac.new(key, f'{learner_id}:{purpose}:{code}'.encode(), hashlib.sha256).hexdigest()


def otp_send_allowed(learner_id):
    """(allowed, seconds_to_wait)"""
    db = get_db()
    rows = db.execute("""SELECT created_at FROM academy_otp WHERE learner_id=%s
                         AND created_at > now() - interval '15 minutes' ORDER BY created_at DESC""",
                      (learner_id,)).fetchall()
    if rows:
        since = (now() - rows[0]['created_at']).total_seconds()
        if since < OTP_RESEND_SECONDS:
            return False, int(OTP_RESEND_SECONDS - since)
        if len(rows) >= OTP_MAX_PER_15MIN:
            oldest = rows[-1]['created_at']
            return False, int(900 - (now() - oldest).total_seconds())
    return True, 0


def issue_otp(learner, purpose):
    code = f'{secrets.randbelow(1_000_000):06d}'
    db = get_db()
    # one live code per learner+purpose
    db.execute("UPDATE academy_otp SET consumed_at=now() WHERE learner_id=%s AND purpose=%s "
               "AND consumed_at IS NULL", (learner['id'], purpose))
    db.execute("""INSERT INTO academy_otp (learner_id, purpose, code_hash, expires_at, request_ip)
                  VALUES (%s,%s,%s,%s,%s)""",
               (learner['id'], purpose, _otp_hash(learner['id'], purpose, code),
                now() + timedelta(minutes=OTP_TTL_MIN), client_ip()))
    db.commit()
    sent = send_otp_email(learner, code, purpose)
    audit('otp_sent' if sent else 'otp_send_failed', learner['id'], purpose)
    return sent


def check_otp(learner_id, purpose, code):
    """Returns 'ok' | 'expired' | 'locked' | 'wrong' | 'none'."""
    db = get_db()
    row = db.execute("""SELECT * FROM academy_otp WHERE learner_id=%s AND purpose=%s
                        AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1""",
                     (learner_id, purpose)).fetchone()
    if not row:
        return 'none'
    if row['expires_at'] < now():
        return 'expired'
    if row['attempts'] >= OTP_MAX_ATTEMPTS:
        return 'locked'
    code = re.sub(r'\D', '', code or '')
    if hmac.compare_digest(row['code_hash'], _otp_hash(learner_id, purpose, code)):
        db.execute("UPDATE academy_otp SET consumed_at=now() WHERE id=%s", (row['id'],))
        db.commit()
        return 'ok'
    db.execute("UPDATE academy_otp SET attempts = attempts + 1 WHERE id=%s", (row['id'],))
    db.commit()
    return 'locked' if row['attempts'] + 1 >= OTP_MAX_ATTEMPTS else 'wrong'


def activate(learner_id):
    db = get_db()
    db.execute("""UPDATE academy_learners SET status='active',
                  email_verified_at=COALESCE(email_verified_at, now()) WHERE id=%s""", (learner_id,))
    db.commit()
    audit('email_verified', learner_id)


def send_otp_email(learner, code, purpose):
    from flask_mail import Message
    from extensions import mail
    cfg = current_app.config
    sender_addr = cfg.get('MAIL_DEFAULT_SENDER') or cfg.get('MAIL_USERNAME')
    if isinstance(sender_addr, (tuple, list)):
        sender_addr = sender_addr[-1]
    sender = (setting('sender_name', 'Integrys Academy'), sender_addr)
    first = (learner['full_name'] or '').split(' ')[0]
    subject = f'{code} is your Integrys Academy code'
    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:auto;color:#0e2340">
<div style="border-top:4px solid #006B75;padding:24px 8px">
<p style="font-size:13px;color:#006B75;font-weight:700;letter-spacing:1px;margin:0">INTEGRYS ACADEMY</p>
<p>Hello {escape(first)},</p>
<p>Your verification code is:</p>
<p style="font-size:32px;font-weight:700;letter-spacing:8px;margin:12px 0">{code}</p>
<p style="color:#555">It expires in {OTP_TTL_MIN} minutes. If you did not request it, ignore this email.</p>
<hr style="border:none;border-top:1px solid #e5e7eb">
<p dir="rtl" style="color:#555">رمز التحقق الخاص بك: <b>{code}</b> — صالح لمدة {OTP_TTL_MIN} دقائق.</p>
<p style="font-size:11px;color:#888">Integrys Consulting · Cairo · {PUBLIC_BASE}<br>
Training delivered on the ComplyNex platform.</p></div></div>"""
    text = (f'Your Integrys Academy verification code is {code}. It expires in {OTP_TTL_MIN} minutes.\n'
            f'رمز التحقق: {code}')
    if cfg.get('EMAIL_MOCK_MODE', True):
        current_app.logger.info(f'[ACADEMY MOCK OTP] learner={learner["id"]} purpose={purpose}')
        return True
    try:
        mail.send(Message(subject=subject, recipients=[learner['email']], html=html, body=text,
                          sender=sender))
        return True
    except Exception as e:  # never leak SMTP detail to the learner
        current_app.logger.error(f'academy OTP mail failed for learner {learner["id"]}: {e}')
        return False


# ---------------------------------------------------------------- courses
PROVIDERS = {
    'integrys':  {'label': 'Integrys Consulting', 'label_ar': 'إنتيجريس للاستشارات'},
    'complynex': {'label': 'ComplyNex', 'label_ar': 'كومبلاي‑نكس'},
}


def slugify(text):
    s = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')[:70]
    return s or f'course-{secrets.token_hex(3)}'


def published_courses():
    return get_db().execute("""SELECT c.*, (SELECT count(*) FROM academy_lessons l WHERE l.course_id=c.id) AS lesson_count
                               FROM academy_courses c WHERE status='published' ORDER BY id""").fetchall()


def course_by_slug(slug, include_drafts=False):
    sql = "SELECT * FROM academy_courses WHERE slug=%s"
    if not include_drafts:
        sql += " AND status='published'"
    return get_db().execute(sql, (slug,)).fetchone()


def lessons(course_id):
    return get_db().execute("SELECT * FROM academy_lessons WHERE course_id=%s ORDER BY position",
                            (course_id,)).fetchall()


def enrollment(learner_id, course_id, create=False):
    db = get_db()
    row = db.execute("SELECT * FROM academy_enrollments WHERE learner_id=%s AND course_id=%s",
                     (learner_id, course_id)).fetchone()
    if not row and create:
        db.execute("INSERT INTO academy_enrollments (learner_id, course_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", (learner_id, course_id))
        db.commit()
        audit('enrolled', learner_id, f'course={course_id}')
        row = db.execute("SELECT * FROM academy_enrollments WHERE learner_id=%s AND course_id=%s",
                         (learner_id, course_id)).fetchone()
    return row


def mark_lesson_done(enr, position):
    done = set(enr['lessons_done'] or [])
    done.add(int(position))
    db = get_db()
    db.execute("UPDATE academy_enrollments SET lessons_done=%s WHERE id=%s",
               (json.dumps(sorted(done)), enr['id']))
    db.commit()


def all_lessons_done(enr, course_id):
    positions = {l['position'] for l in lessons(course_id)}
    return positions.issubset(set(enr['lessons_done'] or []))


def cooldown_remaining(enr, course):
    row = get_db().execute("""SELECT submitted_at FROM academy_attempts WHERE enrollment_id=%s
                              AND submitted_at IS NOT NULL AND passed = false
                              ORDER BY submitted_at DESC LIMIT 1""", (enr['id'],)).fetchone()
    if not row:
        return 0
    wait = timedelta(minutes=course['retry_cooldown_minutes']) - (now() - row['submitted_at'])
    return max(0, int(wait.total_seconds()))


def start_attempt(enr, course):
    db = get_db()
    open_row = db.execute("""SELECT * FROM academy_attempts WHERE enrollment_id=%s AND submitted_at IS NULL
                             AND started_at > now() - interval '2 hours' ORDER BY id DESC LIMIT 1""",
                          (enr['id'],)).fetchone()
    if open_row:
        return open_row
    ids = [r['id'] for r in db.execute(
        "SELECT id FROM academy_questions WHERE course_id=%s AND is_active", (course['id'],)).fetchall()]
    if not ids:
        return None
    pick = random.SystemRandom().sample(ids, min(course['questions_per_attempt'], len(ids)))
    row = db.execute("""INSERT INTO academy_attempts (enrollment_id, question_ids, request_ip)
                        VALUES (%s,%s,%s) RETURNING *""",
                     (enr['id'], json.dumps(pick), client_ip())).fetchone()
    db.commit()
    return row


def attempt_questions(attempt):
    ids = attempt['question_ids']
    rows = {r['id']: r for r in get_db().execute(
        "SELECT * FROM academy_questions WHERE id = ANY(%s)", (ids,)).fetchall()}
    return [rows[i] for i in ids if i in rows]


def grade_attempt(attempt, enr, course, form):
    qs = attempt_questions(attempt)
    answers, correct = {}, 0
    for q in qs:
        raw = form.get(f'q{q["id"]}')
        try:
            choice = int(raw)
        except (TypeError, ValueError):
            choice = None
        answers[str(q['id'])] = choice
        if choice == q['correct_index']:
            correct += 1
    score = round(100 * correct / len(qs)) if qs else 0
    passed = score >= course['pass_mark']
    db = get_db()
    db.execute("""UPDATE academy_attempts SET answers=%s, score=%s, passed=%s, submitted_at=now()
                  WHERE id=%s AND submitted_at IS NULL""",
               (json.dumps(answers), score, passed, attempt['id']))
    db.execute("""UPDATE academy_enrollments SET attempts_count = attempts_count + 1,
                  best_score = GREATEST(COALESCE(best_score,0), %s),
                  status = CASE WHEN %s THEN 'passed' ELSE status END,
                  completed_at = CASE WHEN %s AND completed_at IS NULL THEN now() ELSE completed_at END
                  WHERE id=%s""", (score, passed, passed, enr['id']))
    db.commit()
    audit('quiz_submitted', enr['learner_id'], f'course={course["id"]} score={score} passed={passed}')
    wrong = [i + 1 for i, q in enumerate(qs) if answers[str(q['id'])] != q['correct_index']]
    return score, passed, wrong


# ------------------------------------------------------------ certificates
def _cert_number():
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return f'IA-{now():%Y}-' + ''.join(secrets.choice(alphabet) for _ in range(6))


def cert_hash(number, name, course_title, score, issued_at):
    payload = f'{number}|{name}|{course_title}|{score}|{issued_at.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}'
    return hashlib.sha256(payload.encode()).hexdigest()


def issue_certificate(learner, course, enr, attempt_id, score):
    db = get_db()
    existing = db.execute("""SELECT * FROM academy_certificates WHERE learner_id=%s AND course_id=%s
                             AND status='valid' ORDER BY issued_at DESC LIMIT 1""",
                          (learner['id'], course['id'])).fetchone()
    if existing and (existing['expires_at'] is None or existing['expires_at'] > now()):
        return existing
    issued = now().replace(microsecond=0)
    expires = issued + timedelta(days=round(course['validity_months'] * 30.44)) if course['validity_months'] else None
    name = learner['certificate_name'] or learner['full_name']
    for _ in range(5):
        number = _cert_number()
        if not db.execute("SELECT 1 FROM academy_certificates WHERE cert_number=%s", (number,)).fetchone():
            break
    digest = cert_hash(number, name, course['title_en'], score, issued)
    row = db.execute("""INSERT INTO academy_certificates (cert_number, learner_id, course_id, enrollment_id,
                        attempt_id, holder_name, course_title, score, issued_at, expires_at, sha256, provider)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                     (number, learner['id'], course['id'], enr['id'], attempt_id, name,
                      course['title_en'], score, issued, expires, digest,
                      course.get('provider') or 'integrys')).fetchone()
    db.commit()
    audit('certificate_issued', learner['id'], number)
    return row


def cert_by_number(number):
    return get_db().execute("SELECT * FROM academy_certificates WHERE cert_number=%s",
                            ((number or '').strip().upper(),)).fetchone()


# ------------------------------------------------------------- erasure
def erase_learner(learner_id, actor_user_id=None, reason=''):
    """PDPL erasure: personal data removed; certificate register keeps number + status only."""
    db = get_db()
    db.execute("""UPDATE academy_learners SET full_name='[erased]', certificate_name=NULL,
                  email = 'erased-' || id || '@invalid.local', email_domain='[erased]', company=NULL,
                  job_title=NULL, country=NULL, utm_source=NULL, utm_medium=NULL, utm_campaign=NULL,
                  registered_ip=NULL, consent_marketing=false, status='erased', erased_at=now(),
                  erased_by=%s WHERE id=%s""", (actor_user_id, learner_id))
    db.execute("""UPDATE academy_certificates SET holder_name=NULL, status='redacted',
                  status_reason='Holder exercised data-erasure right', status_changed_at=now(),
                  status_changed_by=%s WHERE learner_id=%s AND status <> 'revoked'""",
               (actor_user_id, learner_id))
    db.execute("DELETE FROM academy_otp WHERE learner_id=%s", (learner_id,))
    db.execute("UPDATE academy_attempts SET request_ip=NULL WHERE enrollment_id IN "
               "(SELECT id FROM academy_enrollments WHERE learner_id=%s)", (learner_id,))
    db.execute("UPDATE academy_audit SET ip=NULL WHERE learner_id=%s", (learner_id,))
    db.commit()
    audit('erased', learner_id, reason or ('self-service' if actor_user_id is None else 'by staff'),
          actor_user_id=actor_user_id)


def purge_inactive(months=None):
    months = int(months or setting('retention_months', '36'))
    db = get_db()
    ids = [r['id'] for r in db.execute(
        """SELECT id FROM academy_learners WHERE status <> 'erased'
           AND COALESCE(last_activity_at, created_at) < now() - (%s || ' months')::interval""",
        (str(months),)).fetchall()]
    # unverified sign-ups older than 30 days are noise, not leads
    ids += [r['id'] for r in db.execute(
        """SELECT id FROM academy_learners WHERE status='pending'
           AND created_at < now() - interval '30 days'""").fetchall()]
    for lid in sorted(set(ids)):
        erase_learner(lid, None, f'retention policy ({months} months inactivity / unverified 30 days)')
    return len(set(ids))


# --------------------------------------------------------------- render
def render_body(text):
    """Tiny, safe markup: '## ' headings, '- ' bullets, '> ' callouts, blank-line paragraphs."""
    out, bullets = [], []

    def flush():
        if bullets:
            out.append('<ul>' + ''.join(f'<li>{b}</li>' for b in bullets) + '</ul>')
            bullets.clear()

    for block in (text or '').replace('\r', '').split('\n'):
        line = block.strip()
        if not line:
            flush()
            continue
        inline = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', str(escape(line)))
        if line.startswith('- '):
            bullets.append(inline[2:])
            continue
        flush()
        if line.startswith('## '):
            out.append(f'<h3>{inline[3:]}</h3>')
        elif line.startswith('> '):
            out.append(f'<div class="ia-callout">{inline[5:]}</div>')
        else:
            out.append(f'<p>{inline}</p>')
    flush()
    return Markup('\n'.join(out))


def csv_safe(v):
    s = '' if v is None else str(v)
    return "'" + s if s[:1] in ('=', '+', '-', '@', '\t', '\r') else s


# --------------------------------------------------------- mandatory video viewing
VIDEO_DONE_RATIO = 0.95      # share of the video that must have been played
VIDEO_WALLCLOCK_RATIO = 0.9  # real time that must have passed since the first play


def video_seconds(lesson):
    """Duration of an uploaded lesson video (cached on the lesson row; probed once with ffprobe)."""
    if lesson.get('video_seconds'):
        return int(lesson['video_seconds'])
    if not lesson.get('video_file'):
        return 0
    from . import media as M
    import subprocess
    path = M.abs_path(lesson['video_file'])
    if not path:
        return 0
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        secs = int(float(out))
    except Exception:
        secs = 0
    if not secs:
        try:
            secs = int(_mp4_duration(path))
        except Exception:
            secs = 0
    if not secs:
        return 0
    db = get_db()
    db.execute("UPDATE academy_lessons SET video_seconds=%s WHERE id=%s", (secs, lesson['id']))
    db.commit()
    return secs


def video_progress(enrollment_id, lesson_id):
    return get_db().execute("SELECT * FROM academy_video_progress WHERE enrollment_id=%s AND lesson_id=%s",
                            (enrollment_id, lesson_id)).fetchone()


def video_ok(enr, lesson):
    """True when the lesson has no uploaded video, or the learner has watched it to the end."""
    if not lesson.get('video_file'):
        return True
    vp = video_progress(enr['id'], lesson['id'])
    return bool(vp and vp['completed_at'])


def video_event(enr, lesson, action, position):
    """Record start / progress / completion. Positions are only accepted if they are plausible
    for real-time playback since the previous report, so skipping ahead is never recorded."""
    db = get_db()
    secs = video_seconds(lesson)
    now = datetime.now(timezone.utc)
    vp = video_progress(enr['id'], lesson['id'])
    if not vp:
        db.execute("""INSERT INTO academy_video_progress (enrollment_id, lesson_id) VALUES (%s,%s)
                      ON CONFLICT DO NOTHING""", (enr['id'], lesson['id']))
        db.commit()
        vp = video_progress(enr['id'], lesson['id'])
    if vp['completed_at']:
        return dict(ok=True, completed=True, max=float(vp['max_position']))
    pos = max(0.0, min(float(position or 0), float(secs or position or 0)))
    elapsed = (now - vp['last_update_at']).total_seconds()
    allowed = float(vp['max_position']) + elapsed * 1.25 + 5
    new_max = float(vp['max_position'])
    if pos > new_max and pos <= allowed:
        new_max = pos
    completed = None
    if action == 'complete' and secs:
        since_start = (now - vp['started_at']).total_seconds()
        if new_max >= secs * VIDEO_DONE_RATIO and since_start >= secs * VIDEO_WALLCLOCK_RATIO:
            completed = now
    db.execute("""UPDATE academy_video_progress SET max_position=%s, last_update_at=%s,
                  completed_at=COALESCE(completed_at, %s) WHERE enrollment_id=%s AND lesson_id=%s""",
               (new_max, now, completed, enr['id'], lesson['id']))
    db.commit()
    if completed:
        audit('video_completed', enr['learner_id'], f"lesson {lesson['id']}")
    return dict(ok=True, completed=bool(completed), max=new_max)


def _mp4_duration(path):
    """Duration in seconds from the MP4 'mvhd' box (pure Python; no ffprobe needed)."""
    import struct
    def boxes(f, start, end):
        pos = start
        while pos + 8 <= end:
            f.seek(pos)
            size, kind = struct.unpack('>I4s', f.read(8))
            hdr = 8
            if size == 1:
                size = struct.unpack('>Q', f.read(8))[0]; hdr = 16
            elif size == 0:
                size = end - pos
            if size < hdr:
                return
            yield kind, pos + hdr, pos + size
            pos += size
    with open(path, 'rb') as f:
        f.seek(0, 2); end = f.tell()
        for kind, a, b in boxes(f, 0, end):
            if kind == b'moov':
                for k2, a2, b2 in boxes(f, a, b):
                    if k2 == b'mvhd':
                        f.seek(a2); ver = f.read(1)[0]
                        if ver == 1:
                            f.seek(a2 + 20); ts, dur = struct.unpack('>IQ', f.read(12))
                        else:
                            f.seek(a2 + 12); ts, dur = struct.unpack('>II', f.read(8))
                        return dur / ts if ts else 0
    return 0
