# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Talent pool — data access. Every query is parameterised (%s); column and
sort names come only from fixed whitelists, never from the request."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from html import escape

from flask import current_app, request

from database.db import get_db

MODULE = 'talent'
STATUSES = ('unverified', 'new', 'shortlisted', 'contacted', 'interview', 'engaged', 'on_hold', 'rejected', 'withdrawn')
STAFF_STATUSES = STATUSES[1:]
STATUS_LABELS = {
    'unverified': ('E-mail not verified', 'البريد لم يُؤكَّد'),
    'new': ('New', 'جديد'), 'shortlisted': ('Shortlisted', 'قائمة مختصرة'), 'contacted': ('Contacted', 'تم التواصل'),
    'interview': ('Interview', 'مقابلة'), 'engaged': ('Engaged (NDA + contract)', 'تم التعاقد (NDA + عقد)'),
    'on_hold': ('On hold', 'معلّق'), 'rejected': ('Not suitable', 'غير مناسب'), 'withdrawn': ('Withdrawn', 'انسحب'),
}
STATUS_COLORS = {'unverified': 'secondary', 'new': 'primary', 'shortlisted': 'info', 'contacted': 'warning',
                 'interview': 'warning', 'engaged': 'success', 'on_hold': 'secondary', 'rejected': 'dark',
                 'withdrawn': 'light'}
AVAILABILITY = {
    'lt10': ('Less than 10 hours / week', 'أقل من 10 ساعات أسبوعيًا'),
    '10_20': ('10–20 hours / week', '10–20 ساعة أسبوعيًا'),
    '20_30': ('20–30 hours / week', '20–30 ساعة أسبوعيًا'),
    'project': ('Per project (when available)', 'حسب المشروع (عند التوفر)'),
}
ENGAGEMENT = {
    'part_time': ('Part-time consulting', 'استشارات بدوام جزئي'),
    'project': ('Project-based', 'بالمشروع'),
    'training': ('Training delivery', 'تقديم التدريب'),
    'any': ('Any of the above', 'أي مما سبق'),
}
WORK_MODE = {'remote': ('Remote', 'عن بُعد'), 'onsite': ('On-site', 'في موقع العميل'), 'hybrid': ('Hybrid', 'مختلط')}
SENIORITY = {
    'junior': ('Junior (0–3 years)', 'مبتدئ (0–3 سنوات)'), 'mid': ('Mid-level (3–7 years)', 'متوسط (3–7 سنوات)'),
    'senior': ('Senior (7–12 years)', 'خبير (7–12 سنة)'), 'expert': ('Expert / leader (12+ years)', 'خبير أول / قيادي (12+ سنة)'),
}

OTP_TTL_MIN = 15
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60
OTP_MAX_PER_HOUR = 5
UNVERIFIED_KEEP_HOURS = 24

EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$')
PHONE_RE = re.compile(r'^\+?[0-9]{7,15}$')

DEFAULT_CATEGORIES = [
    ('grc', 'Governance, risk & compliance (GRC)', 'الحوكمة والمخاطر والالتزام'),
    ('aml_cft', 'AML / CFT', 'مكافحة غسل الأموال وتمويل الإرهاب'),
    ('sanctions', 'Sanctions & screening', 'العقوبات والفحص'),
    ('fincrime_fraud', 'Financial crime & fraud', 'الجرائم المالية والاحتيال'),
    ('internal_audit', 'Internal audit', 'المراجعة الداخلية'),
    ('infosec_privacy', 'Information security & data protection', 'أمن المعلومات وحماية البيانات'),
    ('esg_carbon', 'ESG & carbon footprint', 'الاستدامة والبصمة الكربونية'),
    ('training', 'Training & awareness', 'التدريب والتوعية'),
    ('legal_regulatory', 'Legal & regulatory', 'القانوني والتنظيمي'),
    ('regtech', 'RegTech & compliance systems', 'التكنولوجيا التنظيمية وأنظمة الالتزام'),
    ('other', 'Other', 'أخرى'),
]


def now():
    return datetime.now(timezone.utc)


def client_ip():
    return (request.headers.get('X-Real-IP') or request.remote_addr or '')[:64]


# ------------------------------------------------------------------ settings
def setting(key, default=None):
    try:
        row = get_db().execute("SELECT value FROM talent_settings WHERE key=%s", (key,)).fetchone()
    except Exception:
        get_db().rollback()
        return default
    return row['value'] if row and row['value'] not in (None, '') else default


def set_setting(key, value, user_id=None):
    db = get_db()
    db.execute("""INSERT INTO talent_settings (key, value, updated_by, updated_at) VALUES (%s,%s,%s,now())
                  ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=EXCLUDED.updated_by,
                  updated_at=now()""", (key, '' if value is None else str(value), user_id))
    db.commit()


def public_enabled():
    return setting('public_enabled', '0') == '1'


def branding():
    return {k: setting(k, d) for k, d in (
        ('org_name_en', 'Our consulting network'), ('org_name_ar', 'شبكة الاستشاريين'),
        ('website', ''), ('logo', ''), ('privacy_contact', ''),
        ('intro_en', ''), ('intro_ar', ''), ('terms_en', ''), ('terms_ar', ''))}


# ---------------------------------------------------------------- categories
def categories(active_only=True):
    sql = "SELECT * FROM talent_categories"
    if active_only:
        sql += " WHERE is_active"
    return get_db().execute(sql + " ORDER BY sort_order, id").fetchall()


def install_defaults(db):
    for n, (code, en, ar) in enumerate(DEFAULT_CATEGORIES, start=1):
        db.execute("""INSERT INTO talent_categories (code, name_en, name_ar, sort_order) VALUES (%s,%s,%s,%s)
                      ON CONFLICT (code) DO NOTHING""", (code, en, ar, n * 10))
    db.execute("""INSERT INTO talent_settings (key, value) VALUES ('public_enabled', '0')
                  ON CONFLICT (key) DO NOTHING""")
    db.commit()
    return {'categories': len(DEFAULT_CATEGORIES)}


def save_category(cat_id, name_en, name_ar, is_active, sort_order):
    db = get_db()
    name_en, name_ar = (name_en or '').strip()[:120], (name_ar or '').strip()[:120]
    if not name_en:
        return None
    if cat_id:
        db.execute("""UPDATE talent_categories SET name_en=%s, name_ar=%s, is_active=%s, sort_order=%s
                      WHERE id=%s""", (name_en, name_ar, bool(is_active), int(sort_order or 100), cat_id))
    else:
        code = re.sub(r'[^a-z0-9]+', '_', name_en.lower()).strip('_')[:40] or 'cat'
        code = f'{code}_{secrets.token_hex(2)}'
        db.execute("""INSERT INTO talent_categories (code, name_en, name_ar, is_active, sort_order)
                      VALUES (%s,%s,%s,%s,%s)""", (code, name_en, name_ar, True, int(sort_order or 100)))
    db.commit()
    return True


# ------------------------------------------------------------- applications
def _ref():
    return f"TP-{datetime.now():%y%m}-{secrets.token_hex(3).upper()}"


def clean_phone(v):
    v = re.sub(r'[\s\-().]', '', v or '')
    v = v.replace('٠', '0')
    v = v.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    if v.startswith('00'):
        v = '+' + v[2:]
    return v


def clean_linkedin(v):
    v = (v or '').strip()
    if not v:
        return None
    if not v.lower().startswith(('http://', 'https://')):
        v = 'https://' + v
    m = re.match(r'^https?://([a-z]{2,3}\.)?linkedin\.com/[A-Za-z0-9_\-/%.]{1,180}$', v, re.I)
    return v.replace('http://', 'https://', 1) if m else False


def create_application(data, cv_meta):
    db = get_db()
    row = db.execute("""INSERT INTO talent_applications
        (ref, full_name, email, phone, whatsapp, city, country, primary_category_id, other_category_ids,
         years_experience, current_title, seniority, availability, engagement, work_mode, languages,
         certifications, linkedin_url, expected_rate, summary, cv_path, cv_original_name, cv_size, cv_sha256,
         consent_privacy_at, ack_terms_at, status, source, ip_address, user_agent)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now(),'unverified',%s,%s,%s)
        RETURNING id, ref""",
        (_ref(), data['full_name'], data['email'], data['phone'], data.get('whatsapp'), data.get('city'),
         data.get('country'), data['primary_category_id'], data.get('other_category_ids') or [],
         data.get('years_experience'), data.get('current_title'), data.get('seniority'), data.get('availability'),
         data.get('engagement'), data.get('work_mode'), data.get('languages'), data.get('certifications'),
         data.get('linkedin_url'), data.get('expected_rate'), data.get('summary'),
         cv_meta.get('path'), cv_meta.get('original'), cv_meta.get('size'), cv_meta.get('sha256'),
         data.get('source'), client_ip(), (request.headers.get('User-Agent') or '')[:300])).fetchone()
    db.commit()
    return row


def get(app_id):
    return get_db().execute("""SELECT a.*, c.name_en AS cat_en, c.name_ar AS cat_ar
                               FROM talent_applications a LEFT JOIN talent_categories c ON c.id = a.primary_category_id
                               WHERE a.id=%s""", (app_id,)).fetchone()


def verify(app_id):
    db = get_db()
    db.execute("""UPDATE talent_applications SET status='new', email_verified_at=now(), updated_at=now()
                  WHERE id=%s AND status='unverified'""", (app_id,))
    db.commit()


def purge_unverified(app_root):
    """Remove applications whose e-mail was never confirmed (and their CV files)."""
    from . import cv
    db = get_db()
    rows = db.execute("""DELETE FROM talent_applications WHERE status='unverified'
                         AND created_at < now() - (%s || ' hours')::interval RETURNING cv_path""",
                      (str(UNVERIFIED_KEEP_HOURS),)).fetchall()
    db.commit()
    for r in rows:
        cv.remove(app_root, r['cv_path'])
    return len(rows)


# ---------------------------------------------------------------------- OTP
def _otp_hash(app_id, code):
    key = current_app.config['SECRET_KEY'].encode()
    return hmac.new(key, f'talent:{app_id}:{code}'.encode(), hashlib.sha256).hexdigest()


def otp_send_allowed(app_id):
    rows = get_db().execute("""SELECT created_at FROM talent_otp WHERE application_id=%s
                               AND created_at > now() - interval '1 hour' ORDER BY created_at DESC""",
                            (app_id,)).fetchall()
    if rows:
        since = (now() - rows[0]['created_at']).total_seconds()
        if since < OTP_RESEND_SECONDS:
            return False, int(OTP_RESEND_SECONDS - since)
        if len(rows) >= OTP_MAX_PER_HOUR:
            return False, int(3600 - (now() - rows[-1]['created_at']).total_seconds())
    return True, 0


def issue_otp(app_row, lang_ar=False):
    code = f'{secrets.randbelow(1_000_000):06d}'
    db = get_db()
    db.execute("UPDATE talent_otp SET consumed_at=now() WHERE application_id=%s AND consumed_at IS NULL",
               (app_row['id'],))
    db.execute("""INSERT INTO talent_otp (application_id, code_hash, expires_at, request_ip)
                  VALUES (%s,%s,%s,%s)""",
               (app_row['id'], _otp_hash(app_row['id'], code), now() + timedelta(minutes=OTP_TTL_MIN), client_ip()))
    db.commit()
    return _send_otp_email(app_row, code)


def check_otp(app_id, code):
    """'ok' | 'expired' | 'locked' | 'wrong' | 'none'"""
    db = get_db()
    row = db.execute("""SELECT * FROM talent_otp WHERE application_id=%s AND consumed_at IS NULL
                        ORDER BY created_at DESC LIMIT 1""", (app_id,)).fetchone()
    if not row:
        return 'none'
    if row['expires_at'] < now():
        return 'expired'
    if row['attempts'] >= OTP_MAX_ATTEMPTS:
        return 'locked'
    code = re.sub(r'\D', '', code or '')[:6]
    if hmac.compare_digest(row['code_hash'], _otp_hash(app_id, code)):
        db.execute("UPDATE talent_otp SET consumed_at=now() WHERE id=%s", (row['id'],))
        db.commit()
        return 'ok'
    db.execute("UPDATE talent_otp SET attempts = attempts + 1 WHERE id=%s", (row['id'],))
    db.commit()
    return 'locked' if row['attempts'] + 1 >= OTP_MAX_ATTEMPTS else 'wrong'


def _sender():
    cfg = current_app.config
    addr = cfg.get('MAIL_DEFAULT_SENDER') or cfg.get('MAIL_USERNAME')
    if isinstance(addr, (tuple, list)):
        addr = addr[-1]
    return (setting('sender_name', setting('org_name_en', 'Careers')), addr)


def _mail(to, subject, html, text, log_tag):
    from flask_mail import Message
    from extensions import mail
    if current_app.config.get('EMAIL_MOCK_MODE', True):
        current_app.logger.info(f'[TALENT MOCK MAIL] {log_tag}')
        return True
    try:
        mail.send(Message(subject=subject, recipients=[to], html=html, body=text, sender=_sender()))
        return True
    except Exception as e:
        current_app.logger.error(f'talent mail failed ({log_tag}): {e}')
        return False


def _send_otp_email(app_row, code):
    org = setting('org_name_en', 'Careers')
    org_ar = setting('org_name_ar', '')
    first = escape((app_row['full_name'] or '').split(' ')[0])
    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:auto;color:#0e2340">
<div style="border-top:4px solid #006B75;padding:24px 8px">
<p style="font-size:13px;color:#006B75;font-weight:700;letter-spacing:1px;margin:0">{escape(org.upper())} · CAREERS</p>
<p>Hello {first},</p><p>Thank you for applying. Your e-mail confirmation code is:</p>
<p style="font-size:32px;font-weight:700;letter-spacing:8px;margin:12px 0">{code}</p>
<p style="color:#555">It expires in {OTP_TTL_MIN} minutes. If you did not apply, ignore this e-mail and your details will be deleted.</p>
<hr style="border:none;border-top:1px solid #e5e7eb">
<p dir="rtl" style="color:#555">شكرًا لتقديمك{(' في ' + escape(org_ar)) if org_ar else ''}. رمز تأكيد البريد: <b>{code}</b> — صالح لمدة {OTP_TTL_MIN} دقيقة.
إذا لم تقم بالتقديم تجاهل هذه الرسالة وسيتم حذف البيانات.</p>
<p style="font-size:11px;color:#888">Reference {escape(app_row['ref'])}</p></div></div>"""
    text = (f'Your confirmation code is {code} (valid {OTP_TTL_MIN} minutes). Reference {app_row["ref"]}.\n'
            f'رمز التأكيد: {code}')
    return _mail(app_row['email'], f'{code} — confirm your application to {org}', html, text,
                 f'otp app={app_row["id"]}')


def notify_staff(app_row, staff_url):
    to = setting('notify_email')
    if not to or not EMAIL_RE.match(to):
        return False
    html = (f"<p>New verified application <b>{escape(app_row['ref'])}</b>: {escape(app_row['full_name'])}"
            f" — {escape(app_row.get('cat_en') or '')}.</p><p><a href=\"{escape(staff_url)}\">Open in ComplyNex</a></p>")
    return _mail(to, f'New consultant application {app_row["ref"]}', html,
                 f'New verified application {app_row["ref"]}: {staff_url}', f'notify app={app_row["id"]}')


# --------------------------------------------------------------- staff side
SORTS = {'newest': 'a.created_at DESC', 'oldest': 'a.created_at ASC', 'experience': 'a.years_experience DESC NULLS LAST',
         'rating': 'a.rating DESC NULLS LAST, a.created_at DESC', 'name': 'lower(a.full_name) ASC'}


def search(args, limit=500):
    where, params = ['a.erased_at IS NULL'], []
    status = args.get('status') or ''
    if status == 'all':
        pass
    elif status in STATUSES:
        where.append('a.status = %s')
        params.append(status)
    else:
        where.append("a.status <> 'unverified'")
    cat = args.get('category')
    if cat and str(cat).isdigit():
        where.append('(a.primary_category_id = %s OR %s = ANY(a.other_category_ids))')
        params += [int(cat), int(cat)]
    if args.get('availability') in AVAILABILITY:
        where.append('a.availability = %s')
        params.append(args['availability'])
    if args.get('min_years') and str(args['min_years']).isdigit():
        where.append('a.years_experience >= %s')
        params.append(int(args['min_years']))
    q = (args.get('q') or '').strip()[:100]
    if q:
        where.append("""(a.full_name ILIKE %s OR a.email ILIKE %s OR a.phone ILIKE %s OR a.ref ILIKE %s
                         OR a.current_title ILIKE %s OR a.certifications ILIKE %s OR a.summary ILIKE %s)""")
        like = '%' + q.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_') + '%'
        params += [like] * 7
    order = SORTS.get(args.get('sort'), SORTS['newest'])
    sql = f"""SELECT a.*, c.name_en AS cat_en, c.name_ar AS cat_ar,
                     (SELECT count(*) FROM talent_applications b WHERE lower(b.email)=lower(a.email)
                        AND b.id <> a.id AND b.erased_at IS NULL AND b.status <> 'unverified') AS other_apps
              FROM talent_applications a LEFT JOIN talent_categories c ON c.id = a.primary_category_id
              WHERE {' AND '.join(where)} ORDER BY {order} LIMIT %s"""
    return get_db().execute(sql, params + [limit]).fetchall()


def counts():
    db = get_db()
    by_status = {r['status']: r['n'] for r in db.execute(
        "SELECT status, count(*) AS n FROM talent_applications WHERE erased_at IS NULL GROUP BY status").fetchall()}
    by_cat = db.execute("""SELECT c.id, c.name_en, c.name_ar, count(a.id) AS n FROM talent_categories c
                           LEFT JOIN talent_applications a ON a.primary_category_id = c.id AND a.erased_at IS NULL
                                AND a.status <> 'unverified'
                           GROUP BY c.id ORDER BY c.sort_order, c.id""").fetchall()
    return by_status, by_cat


def notes(app_id):
    return get_db().execute("""SELECT n.*, TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS who
                               FROM talent_notes n LEFT JOIN users u ON u.id = n.user_id
                               WHERE n.application_id=%s ORDER BY n.created_at DESC""", (app_id,)).fetchall()


def add_note(app_id, user_id, body, kind='note'):
    body = (body or '').strip()[:4000]
    if not body:
        return False
    db = get_db()
    db.execute("INSERT INTO talent_notes (application_id, user_id, kind, body) VALUES (%s,%s,%s,%s)",
               (app_id, user_id, kind, body))
    db.execute("UPDATE talent_applications SET updated_at=now() WHERE id=%s", (app_id,))
    db.commit()
    return True


def set_status(app_ids, status, user_id):
    if status not in STAFF_STATUSES or not app_ids:
        return 0
    db = get_db()
    ids = [int(i) for i in app_ids if str(i).isdigit()][:500]
    rows = db.execute("""UPDATE talent_applications SET status=%s, status_changed_by=%s, status_changed_at=now(),
                         updated_at=now() WHERE id = ANY(%s) AND status <> 'unverified' AND erased_at IS NULL
                         RETURNING id""", (status, user_id, ids)).fetchall()
    for r in rows:
        db.execute("INSERT INTO talent_notes (application_id, user_id, kind, body) VALUES (%s,%s,'status',%s)",
                   (r['id'], user_id, f'status → {status}'))
    db.commit()
    return len(rows)


def set_rating(app_id, rating):
    r = int(rating) if str(rating).isdigit() and 1 <= int(rating) <= 5 else None
    db = get_db()
    db.execute("UPDATE talent_applications SET rating=%s, updated_at=now() WHERE id=%s", (r, app_id))
    db.commit()


def erase(app_id, app_root, user_id):
    """Data-subject erasure: personal data blanked, CV file deleted, the
    reference and dates kept so the register shows the request was honoured."""
    from . import cv
    db = get_db()
    row = get(app_id)
    if not row:
        return False
    cv.remove(app_root, row['cv_path'])
    db.execute("""UPDATE talent_applications SET full_name='[erased]', email='erased@invalid', phone='-',
                  whatsapp=NULL, city=NULL, country=NULL, current_title=NULL, languages=NULL, certifications=NULL,
                  linkedin_url=NULL, expected_rate=NULL, summary=NULL, cv_path=NULL, cv_original_name=NULL,
                  cv_size=NULL, cv_sha256=NULL, ip_address=NULL, user_agent=NULL, erased_at=now(), updated_at=now()
                  WHERE id=%s""", (app_id,))
    db.execute("DELETE FROM talent_notes WHERE application_id=%s AND kind='note'", (app_id,))
    db.execute("INSERT INTO talent_notes (application_id, user_id, kind, body) VALUES (%s,%s,'erasure',%s)",
               (app_id, user_id, 'personal data erased on request'))
    db.commit()
    return True


def csv_safe(v):
    s = '' if v is None else str(v)
    return "'" + s if s[:1] in ('=', '+', '-', '@', '\t', '\r') else s


def label(mapping, key, ar=False):
    v = mapping.get(key)
    if not v:
        return key or ''
    return v[1] if ar else v[0]
