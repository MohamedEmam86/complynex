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

"""
Phishing Awareness Module — Routes
ComplyNex CMS — Cybersecurity Awareness Program
"""

import os
import re
import uuid
import json
import csv
import io
import smtplib
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask_babel import gettext
from flask import (
    render_template, redirect, url_for, request,
    flash, current_app, abort, session, jsonify, Response
)
from flask_login import login_required, current_user

from phishing import phishing_bp
from database.db import get_db, query_db, execute_db
from utils.decorators import permission_required
from utils.file_validator import validate_file, secure_filename_strict

UPLOAD_FOLDER = 'static/uploads/phishing'


def _log_audit(action, details=''):
    try:
        execute_db(
            """INSERT INTO audit_logs (user_id, action, details, ip_address, created_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (current_user.id, f'phishing:{action}', details,
             request.headers.get('X-Forwarded-For', request.remote_addr),
             datetime.now())
        )
    except Exception as e:
        current_app.logger.warning(f"Phishing audit log failed: {e}")


def _build_email_html(name, tracking_url, campaign):
    custom_html = campaign.get('custom_html')
    if custom_html:
        return (custom_html
                .replace('{{TRACKING_URL}}', tracking_url)
                .replace('{{RECIPIENT_NAME}}', name))

    sender_display = campaign.get('sender_display', 'Carrefour Egypt')
    offer_title    = campaign.get('offer_title', 'عرض حصري لك')
    offer_body     = campaign.get('offer_body', 'بناءً على تعاونك معنا، اخترنا لك هذه الصفقات المميزة.')
    expiry_text    = campaign.get('expiry_text', 'حتى 30 يونيو 2026')
    cta_text       = campaign.get('cta_text', 'استفد من العرض الآن ←')

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:'Segoe UI',Arial,sans-serif;direction:rtl;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;">
<tr><td align="center" style="padding:24px 12px 32px;">
<table width="600" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 6px 30px rgba(0,0,0,0.14);max-width:600px;">
<tr><td style="background:#e62429;padding:20px 30px;text-align:center;">
  <span style="color:#fff;font-size:22px;font-weight:bold;letter-spacing:1px;">{sender_display}</span>
</td></tr>
<tr><td style="padding:32px 40px 8px 40px;text-align:right;direction:rtl;">
  <h1 style="margin:0 0 16px 0;font-size:24px;color:#1a1a1a;">
    {offer_title}<br>مرحباً <span style="color:#e62429;">{name}</span>،
  </h1>
  <p style="margin:0 0 20px 0;font-size:15px;color:#444;line-height:1.8;">{offer_body}</p>
</td></tr>
<tr><td style="padding:20px 40px;text-align:center;">
  <a href="{tracking_url}"
     style="display:inline-block;background-color:#e62429;color:#fff;font-size:17px;font-weight:bold;
            text-decoration:none;padding:15px 56px;border-radius:8px;">{cta_text}</a>
</td></tr>
<tr><td style="padding:16px 40px 28px;text-align:center;">
  <p style="margin:0;color:#bbb;font-size:11px;line-height:1.7;">
    يسري هذا العرض {expiry_text} · تطبّق الشروط والأحكام
  </p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


# ── GUIDED DESIGN GENERATOR ─────────────────────────────────────────────────────
# Builds a ready-to-send email + a matching landing page from a handful of plain-
# English answers (company name, logo, scenario-specific details) instead of
# requiring the user to write HTML. Two scenarios: 'coupon' (exclusive discount)
# and 'delivery' (package delivery notice). Both follow the same email-HTML rules
# documented in campaign_form.html (table layout, inline styles, no <script>,
# absolute image URLs, {{TRACKING_URL}}/{{RECIPIENT_NAME}} placeholders for the
# email; {{SUBMIT_URL}}/{{TOKEN}}/{{CSRF_TOKEN}} placeholders for the landing page).

def _logo_header_html(company_name, logo_url, brand_color):
    """Shared header block: logo image if one was uploaded, else the company name as text."""
    if logo_url:
        return f'<img src="{logo_url}" alt="{company_name}" style="max-height:44px;max-width:220px;">'
    return f'<span style="color:#fff;font-size:22px;font-weight:bold;letter-spacing:1px;">{company_name}</span>'


def generate_coupon_design(company_name, logo_url, brand_color, discount_amount, expiry_text, cta_text):
    header = _logo_header_html(company_name, logo_url, brand_color)

    email_html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:'Segoe UI',Arial,sans-serif;direction:rtl;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;">
<tr><td align="center" style="padding:24px 12px 32px;">
<table width="600" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 6px 30px rgba(0,0,0,0.14);max-width:600px;">
<tr><td style="background:{brand_color};padding:22px 30px;text-align:center;">{header}</td></tr>
<tr><td style="padding:32px 40px 8px 40px;text-align:right;direction:rtl;">
  <h1 style="margin:0 0 16px 0;font-size:24px;color:#1a1a1a;">
    عرض حصري لك، مرحباً <span style="color:{brand_color};">{{{{RECIPIENT_NAME}}}}</span>
  </h1>
  <p style="margin:0 0 20px 0;font-size:15px;color:#444;line-height:1.8;">
    بناءً على تعاونك معنا، اخترنا لك هذا العرض المميز بشكل خاص. لا يفوتك — العرض محدود!
  </p>
</td></tr>
<tr><td style="padding:0 40px 24px;">
  <table width="100%" cellpadding="0" cellspacing="0"
    style="border:2px dashed {brand_color};border-radius:8px;background:#fafafa;">
    <tr><td style="padding:18px;text-align:center;">
      <div style="font-size:36px;font-weight:bold;color:{brand_color};">{discount_amount}</div>
      <div style="font-size:12px;color:#777;margin-top:2px;">خصم فوري على مشترياتك القادمة</div>
    </td></tr>
  </table>
</td></tr>
<tr><td style="padding:8px 40px 20px;text-align:center;">
  <a href="{{{{TRACKING_URL}}}}"
     style="display:inline-block;background-color:{brand_color};color:#fff;font-size:17px;font-weight:bold;
            text-decoration:none;padding:15px 56px;border-radius:8px;">{cta_text}</a>
</td></tr>
<tr><td style="padding:16px 40px 28px;text-align:center;">
  <p style="margin:0;color:#bbb;font-size:11px;line-height:1.7;">
    يسري هذا العرض {expiry_text} · تطبّق الشروط والأحكام
  </p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    landing_html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{company_name} — استلم عرضك الآن</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;direction:rtl}}
.wrapper{{max-width:520px;margin:30px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.13)}}
.header{{background:{brand_color};padding:20px 24px;text-align:center}}
.header img{{max-height:48px;max-width:240px}}
.header .brand-name{{color:#fff;font-size:26px;font-weight:bold;letter-spacing:1px}}
.body{{padding:28px 32px 24px}}
.body h2{{color:{brand_color};font-size:20px;margin-bottom:10px}}
.body p{{color:#444;font-size:14px;line-height:1.7;margin-bottom:20px}}
.coupon-box{{border:2px dashed {brand_color};border-radius:8px;padding:16px 20px;text-align:center;margin-bottom:24px;background:#fafafa}}
.coupon-box .amount{{font-size:40px;font-weight:bold;color:{brand_color}}}
.coupon-box .label{{font-size:13px;color:#666}}
label{{display:block;font-size:13px;color:#333;margin-bottom:5px;font-weight:bold}}
input[type=email],input[type=text]{{width:100%;padding:11px 14px;border:1px solid #ccc;border-radius:6px;font-size:14px;margin-bottom:16px;text-align:right;direction:rtl}}
input:focus{{outline:none;border-color:{brand_color}}}
.btn-submit{{width:100%;background:{brand_color};color:#fff;border:none;border-radius:6px;font-size:17px;font-weight:bold;padding:13px;cursor:pointer}}
.terms{{text-align:center;color:#aaa;font-size:11px;margin-top:14px;line-height:1.5}}
.footer{{background:#2c2c2c;padding:16px;text-align:center;color:#aaa;font-size:11px}}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    {f'<img src="{logo_url}" alt="{company_name}">' if logo_url else f'<div class="brand-name">{company_name}</div>'}
  </div>
  <div class="body">
    <h2>استلم عرضك الخاص الآن</h2>
    <p>تم اختيارك للحصول على عرض حصري. أدخل بياناتك أدناه لاستلام التفاصيل على بريدك الإلكتروني فوراً.</p>
    <div class="coupon-box">
      <div class="amount">{discount_amount}</div>
      <div class="label">خصم فوري على مشترياتك القادمة</div>
    </div>
    <form action="{{{{SUBMIT_URL}}}}" method="POST">
      <input type="hidden" name="csrf_token" value="{{{{CSRF_TOKEN}}}}">
      <input type="hidden" name="token" value="{{{{TOKEN}}}}">
      <label for="email">البريد الإلكتروني</label>
      <input type="email" id="email" name="email" placeholder="example@company.com" required>
      <label for="card">رقم العضوية (اختياري)</label>
      <input type="text" id="card" name="card" placeholder="XXXX-XXXX-XXXX">
      <button type="submit" class="btn-submit">استلم العرض الآن ←</button>
    </form>
    <p class="terms">يسري هذا العرض {expiry_text} · تطبّق الشروط والأحكام</p>
  </div>
  <div class="footer">جميع الحقوق محفوظة {company_name} © 2026</div>
</div>
</body>
</html>"""
    return email_html, landing_html


def generate_delivery_design(company_name, logo_url, brand_color, tracking_number, delivery_date, cta_text):
    header = _logo_header_html(company_name, logo_url, brand_color)

    email_html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:'Segoe UI',Arial,sans-serif;direction:rtl;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f0f0;">
<tr><td align="center" style="padding:24px 12px 32px;">
<table width="600" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 6px 30px rgba(0,0,0,0.14);max-width:600px;">
<tr><td style="background:{brand_color};padding:22px 30px;text-align:center;">{header}</td></tr>
<tr><td style="padding:32px 40px 8px 40px;text-align:right;direction:rtl;">
  <h1 style="margin:0 0 16px 0;font-size:22px;color:#1a1a1a;">
    لديك طرد بانتظار التسليم، <span style="color:{brand_color};">{{{{RECIPIENT_NAME}}}}</span>
  </h1>
  <p style="margin:0 0 20px 0;font-size:15px;color:#444;line-height:1.8;">
    لم نتمكن من إتمام عملية التسليم في المحاولة الأخيرة بسبب عدم اكتمال بيانات العنوان.
    يرجى تأكيد بياناتك لإعادة جدولة التسليم في {delivery_date}.
  </p>
</td></tr>
<tr><td style="padding:0 40px 24px;">
  <table width="100%" cellpadding="0" cellspacing="0"
    style="border:1px solid #e0e0e0;border-radius:8px;background:#fafafa;">
    <tr><td style="padding:16px 20px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="font-size:12px;color:#777;padding-bottom:4px;">رقم الشحنة</td>
        </tr>
        <tr>
          <td style="font-size:18px;font-weight:bold;color:#1a1a1a;font-family:monospace;letter-spacing:1px;">{tracking_number}</td>
        </tr>
      </table>
    </td></tr>
  </table>
</td></tr>
<tr><td style="padding:8px 40px 20px;text-align:center;">
  <a href="{{{{TRACKING_URL}}}}"
     style="display:inline-block;background-color:{brand_color};color:#fff;font-size:17px;font-weight:bold;
            text-decoration:none;padding:15px 56px;border-radius:8px;">{cta_text}</a>
</td></tr>
<tr><td style="padding:16px 40px 28px;text-align:center;">
  <p style="margin:0;color:#bbb;font-size:11px;line-height:1.7;">
    في حال عدم تأكيد العنوان خلال 48 ساعة، سيتم إعادة الشحنة إلى المستودع
  </p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    landing_html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{company_name} — تأكيد بيانات التسليم</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;direction:rtl}}
.wrapper{{max-width:520px;margin:30px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.13)}}
.header{{background:{brand_color};padding:20px 24px;text-align:center}}
.header img{{max-height:48px;max-width:240px}}
.header .brand-name{{color:#fff;font-size:26px;font-weight:bold;letter-spacing:1px}}
.body{{padding:28px 32px 24px}}
.body h2{{color:{brand_color};font-size:20px;margin-bottom:10px}}
.body p{{color:#444;font-size:14px;line-height:1.7;margin-bottom:20px}}
.tracking-box{{border:1px solid #e0e0e0;border-radius:8px;padding:14px 18px;margin-bottom:24px;background:#fafafa}}
.tracking-box .label{{font-size:12px;color:#777}}
.tracking-box .value{{font-size:17px;font-weight:bold;color:#1a1a1a;font-family:monospace;letter-spacing:1px;margin-top:2px}}
label{{display:block;font-size:13px;color:#333;margin-bottom:5px;font-weight:bold}}
input[type=email],input[type=text]{{width:100%;padding:11px 14px;border:1px solid #ccc;border-radius:6px;font-size:14px;margin-bottom:16px;text-align:right;direction:rtl}}
input:focus{{outline:none;border-color:{brand_color}}}
.btn-submit{{width:100%;background:{brand_color};color:#fff;border:none;border-radius:6px;font-size:17px;font-weight:bold;padding:13px;cursor:pointer}}
.terms{{text-align:center;color:#aaa;font-size:11px;margin-top:14px;line-height:1.5}}
.footer{{background:#2c2c2c;padding:16px;text-align:center;color:#aaa;font-size:11px}}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    {f'<img src="{logo_url}" alt="{company_name}">' if logo_url else f'<div class="brand-name">{company_name}</div>'}
  </div>
  <div class="body">
    <h2>تأكيد بيانات التسليم</h2>
    <p>يرجى تأكيد بياناتك لإتمام عملية التسليم في أقرب موعد متاح.</p>
    <div class="tracking-box">
      <div class="label">رقم الشحنة</div>
      <div class="value">{tracking_number}</div>
    </div>
    <form action="{{{{SUBMIT_URL}}}}" method="POST">
      <input type="hidden" name="csrf_token" value="{{{{CSRF_TOKEN}}}}">
      <input type="hidden" name="token" value="{{{{TOKEN}}}}">
      <label for="email">البريد الإلكتروني</label>
      <input type="email" id="email" name="email" placeholder="example@company.com" required>
      <label for="card">العنوان بالتفصيل (اختياري)</label>
      <input type="text" id="card" name="card" placeholder="المدينة، الحي، الشارع">
      <button type="submit" class="btn-submit">تأكيد بيانات التسليم ←</button>
    </form>
    <p class="terms">الموعد المتوقع لإعادة التسليم: {delivery_date}</p>
  </div>
  <div class="footer">جميع الحقوق محفوظة {company_name} © 2026</div>
</div>
</body>
</html>"""
    return email_html, landing_html


def _send_one_email(recipient_name, recipient_email, tracking_url, campaign, gmail_user, gmail_pass):
    sender_display = campaign.get('sender_display', 'Carrefour Egypt')
    email_subject  = campaign.get('email_subject', '🎟️ عرض حصري لك!')

    msg = MIMEMultipart('alternative')
    msg['Subject']  = email_subject
    msg['From']     = f'"{sender_display}" <{gmail_user}>'
    msg['To']       = recipient_email
    msg['Reply-To'] = f'"{sender_display}" <noreply@example.com>'
    msg.attach(MIMEText(_build_email_html(recipient_name, tracking_url, campaign), 'html', 'utf-8'))

    # Was hard-coded to smtp.hostinger.com:587 with its own GMAIL_* variables,
    # so the phishing module had a second, separate mail configuration that
    # drifted from the rest of the app. It now uses the same central settings.
    from flask import current_app as _app
    _host = _app.config.get('MAIL_SERVER', 'smtp.hostinger.com')
    _port = int(_app.config.get('MAIL_PORT', 465))
    _ctx = smtplib.SMTP_SSL(_host, _port, timeout=30) if _port == 465 \
           else smtplib.SMTP(_host, _port, timeout=30)
    with _ctx as srv:
        srv.ehlo()
        if _port != 465:
            srv.starttls()
        srv.ehlo()
        srv.login(gmail_user, gmail_pass)
        srv.send_message(msg, from_addr=gmail_user, to_addrs=[recipient_email])


# ── DASHBOARD ──────────────────────────────────────────────────────────────────

@phishing_bp.route('/')
@login_required
@permission_required('phishing')
def dashboard():
    campaigns = query_db(
        """SELECT c.*,
                  COUNT(DISTINCT r.id) AS recipient_count,
                  SUM(CASE WHEN r.clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS click_count,
                  SUM(CASE WHEN r.submitted_at IS NOT NULL THEN 1 ELSE 0 END) AS submit_count
           FROM phishing_campaigns c
           LEFT JOIN phishing_recipients r ON r.campaign_id = c.id
           GROUP BY c.id
           ORDER BY c.created_at DESC"""
    )
    stats = query_db(
        """SELECT
             COUNT(DISTINCT c.id) AS total_campaigns,
             COUNT(DISTINCT r.id) AS total_recipients,
             SUM(CASE WHEN r.clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS total_clicks,
             SUM(CASE WHEN r.submitted_at IS NOT NULL THEN 1 ELSE 0 END) AS total_submits
           FROM phishing_campaigns c
           LEFT JOIN phishing_recipients r ON r.campaign_id = c.id""",
        one=True
    )
    return render_template('phishing/dashboard.html', campaigns=campaigns, stats=stats)


# ── CREATE CAMPAIGN ────────────────────────────────────────────────────────────

@phishing_bp.route('/campaign/new', methods=['GET', 'POST'])
@login_required
@permission_required('phishing', level='edit')
def create_campaign():
    if request.method == 'POST':
        name           = request.form.get('name', '').strip()
        description    = request.form.get('description', '').strip()
        sender_display = request.form.get('sender_display', 'Carrefour Egypt').strip()
        email_subject  = request.form.get('email_subject', '').strip()
        offer_title    = request.form.get('offer_title', '').strip()
        offer_body     = request.form.get('offer_body', '').strip()
        expiry_text    = request.form.get('expiry_text', '').strip()
        cta_text       = request.form.get('cta_text', '').strip()
        custom_html    = request.form.get('custom_html', '').strip()
        custom_landing_html = request.form.get('custom_landing_html', '').strip()
        scenario_type  = request.form.get('scenario_type', '').strip()
        company_name   = request.form.get('company_name', '').strip()
        logo_url       = request.form.get('logo_url', '').strip()

        if not name or not email_subject:
            flash(gettext('Campaign name and email subject are required.'), 'danger')
            return render_template('phishing/campaign_form.html')

        # execute_db() returns rowcount on Postgres, not the new row's id (a pre-existing
        # bug — every campaign created through this route redirected to campaign id 1
        # regardless of which one was actually created). Use RETURNING id directly instead.
        db = get_db()
        cursor = db.execute(
            """INSERT INTO phishing_campaigns
                 (name, description, sender_display, email_subject,
                  offer_title, offer_body, expiry_text, cta_text, custom_html,
                  custom_landing_html, scenario_type, company_name, logo_url,
                  status, created_by, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
               RETURNING id""",
            (name, description, sender_display, email_subject,
             offer_title, offer_body, expiry_text, cta_text, custom_html or None,
             custom_landing_html or None, scenario_type or None, company_name or None, logo_url or None,
             current_user.id, datetime.now())
        )
        campaign_id = cursor.fetchone()['id']
        db.commit()
        _log_audit('campaign_created', f'Campaign: {name} (id={campaign_id})')
        flash(gettext('Campaign "%(name)s" created successfully.', name=name), 'success')
        return redirect(url_for('phishing.campaign_detail', campaign_id=campaign_id))

    return render_template('phishing/campaign_form.html')


# ── IMAGE UPLOAD (for custom HTML campaigns) ───────────────────────────────────

@phishing_bp.route('/upload-image', methods=['POST'])
@login_required
@permission_required('phishing', level='edit')
def upload_image():
    file = request.files.get('image')
    is_valid, error = validate_file(file, upload_type='image')
    if not is_valid:
        return jsonify({'error': error}), 400

    upload_path = os.path.join(current_app.root_path, UPLOAD_FOLDER)
    os.makedirs(upload_path, exist_ok=True)
    stored_name = secure_filename_strict(file.filename)
    file.save(os.path.join(upload_path, stored_name))

    _log_audit('image_uploaded', f'File: {stored_name}')
    return jsonify({'url': url_for('static', filename=f'uploads/phishing/{stored_name}')})


@phishing_bp.route('/generate-design', methods=['POST'])
@login_required
@permission_required('phishing', level='edit')
def generate_design():
    """Build a ready-to-use email + landing page from the guided generator's answers."""
    from markupsafe import escape

    data = request.get_json(silent=True) or {}
    scenario = data.get('scenario')
    company_name = str(escape(data.get('company_name', '').strip() or 'Our Company'))
    logo_url = data.get('logo_url', '').strip()
    brand_color = data.get('brand_color', '').strip()
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', brand_color or ''):
        brand_color = '#c0392b'
    cta_text = str(escape(data.get('cta_text', '').strip() or 'View Now'))

    if scenario == 'coupon':
        discount_amount = str(escape(data.get('discount_amount', '').strip() or '20%'))
        expiry_text = str(escape(data.get('expiry_text', '').strip() or 'for a limited time'))
        email_html, landing_html = generate_coupon_design(
            company_name, logo_url, brand_color, discount_amount, expiry_text, cta_text
        )
    elif scenario == 'delivery':
        tracking_number = str(escape(data.get('tracking_number', '').strip() or 'TRK-000000000'))
        delivery_date = str(escape(data.get('delivery_date', '').strip() or 'the next business day'))
        email_html, landing_html = generate_delivery_design(
            company_name, logo_url, brand_color, tracking_number, delivery_date, cta_text
        )
    else:
        return jsonify({'error': 'Unknown scenario.'}), 400

    _log_audit('design_generated', f'Scenario: {scenario}, Company: {company_name}')
    return jsonify({'email_html': email_html, 'landing_html': landing_html})


# ── CAMPAIGN DETAIL ────────────────────────────────────────────────────────────

@phishing_bp.route('/campaign/<int:campaign_id>')
@login_required
@permission_required('phishing')
def campaign_detail(campaign_id):
    campaign = query_db('SELECT * FROM phishing_campaigns WHERE id = %s', (campaign_id,), one=True)
    if not campaign:
        abort(404)

    recipients = query_db(
        'SELECT * FROM phishing_recipients WHERE campaign_id = %s ORDER BY created_at DESC',
        (campaign_id,)
    )
    events = query_db(
        """SELECT e.*, r.recipient_name, r.recipient_email
           FROM phishing_events e
           JOIN phishing_recipients r ON r.id = e.recipient_id
           WHERE e.campaign_id = %s
           ORDER BY e.created_at DESC LIMIT 100""",
        (campaign_id,)
    )
    stats = query_db(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS clicked,
             SUM(CASE WHEN submitted_at IS NOT NULL THEN 1 ELSE 0 END) AS submitted
           FROM phishing_recipients WHERE campaign_id = %s""",
        (campaign_id,), one=True
    )
    return render_template('phishing/campaign_detail.html',
                           campaign=campaign, recipients=recipients,
                           events=events, stats=stats)


# ── RECIPIENTS ─────────────────────────────────────────────────────────────────

@phishing_bp.route('/campaign/<int:campaign_id>/recipients', methods=['GET', 'POST'])
@login_required
@permission_required('phishing', level='edit')
def manage_recipients(campaign_id):
    campaign = query_db('SELECT * FROM phishing_campaigns WHERE id = %s', (campaign_id,), one=True)
    if not campaign:
        abort(404)
    if campaign['status'] == 'sent':
        flash(gettext('Cannot modify recipients of a sent campaign.'), 'warning')
        return redirect(url_for('phishing.campaign_detail', campaign_id=campaign_id))

    if request.method == 'POST':
        bulk_text = request.form.get('bulk_recipients', '').strip()
        added = 0
        errors = []

        for line in bulk_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if ',' in line:
                parts = line.split(',', 1)
                rec_name  = parts[0].strip()
                rec_email = parts[1].strip()
            else:
                rec_email = line
                rec_name  = rec_email.split('@')[0].title()

            if '@' not in rec_email:
                errors.append(f'Invalid email: {line}')
                continue

            existing = query_db(
                'SELECT id FROM phishing_recipients WHERE campaign_id = %s AND recipient_email = %s',
                (campaign_id, rec_email), one=True
            )
            if existing:
                errors.append(f'Already added: {rec_email}')
                continue

            token = uuid.uuid4().hex[:12]
            execute_db(
                """INSERT INTO phishing_recipients
                     (campaign_id, recipient_name, recipient_email, token, created_at)
                   VALUES (%s, %s, %s, %s, %s)""",
                (campaign_id, rec_name, rec_email, token, datetime.now())
            )
            added += 1

        if added:
            flash(gettext('%(added)s recipient(s) added.', added=added), 'success')
            _log_audit('recipients_added', f'Campaign {campaign_id}: {added} added')
        for err in errors[:5]:
            flash(err, 'warning')

        return redirect(url_for('phishing.campaign_detail', campaign_id=campaign_id))

    return render_template('phishing/recipients_form.html', campaign=campaign)


# ── SEND CAMPAIGN ──────────────────────────────────────────────────────────────

@phishing_bp.route('/campaign/<int:campaign_id>/send', methods=['POST'])
@login_required
@permission_required('phishing', level='edit')
def send_campaign(campaign_id):
    campaign = query_db('SELECT * FROM phishing_campaigns WHERE id = %s', (campaign_id,), one=True)
    if not campaign:
        abort(404)
    if campaign['status'] == 'sent':
        flash(gettext('Already sent.'), 'warning')
        return redirect(url_for('phishing.campaign_detail', campaign_id=campaign_id))

    recipients = query_db(
        'SELECT * FROM phishing_recipients WHERE campaign_id = %s AND sent_at IS NULL',
        (campaign_id,)
    )
    if not recipients:
        flash(gettext('No recipients to send to.'), 'warning')
        return redirect(url_for('phishing.campaign_detail', campaign_id=campaign_id))

    from flask import current_app as _app
    gmail_user = (_app.config.get('MAIL_USERNAME')
                  or os.environ.get('EMAIL_USER', '')
                  or os.environ.get('GMAIL_USER', ''))
    gmail_pass = (_app.config.get('MAIL_PASSWORD')
                  or os.environ.get('EMAIL_PASS', '')
                  or os.environ.get('GMAIL_PASS', ''))
    app_url    = os.environ.get('APP_URL', request.url_root.rstrip('/'))

    if not gmail_user or not gmail_pass:
        flash('Outbound email is not configured. Run '
              'scripts/setup_email.sh on the server to set it.', 'danger')
        return redirect(url_for('phishing.campaign_detail', campaign_id=campaign_id))

    camp_dict    = dict(campaign)
    sent_count   = 0
    failed_count = 0

    for recipient in recipients:
        tracking_url = f"{app_url}/phishing/t/{recipient['token']}"
        try:
            _send_one_email(
                recipient['recipient_name'], recipient['recipient_email'],
                tracking_url, camp_dict, gmail_user, gmail_pass
            )
            execute_db(
                'UPDATE phishing_recipients SET sent_at = %s WHERE id = %s',
                (datetime.now(), recipient['id'])
            )
            sent_count += 1
        except Exception as e:
            current_app.logger.error(f"Phishing send failed for {recipient['recipient_email']}: {e}")
            failed_count += 1
        time.sleep(1)

    if sent_count:
        execute_db(
            "UPDATE phishing_campaigns SET status = 'sent', sent_at = %s WHERE id = %s",
            (datetime.now(), campaign_id)
        )
    _log_audit('campaign_sent', f'Campaign {campaign_id}: {sent_count} sent, {failed_count} failed')

    if sent_count and failed_count:
        flash(gettext('Sent %(sent_count)s. %(failed_count)s failed — check logs.', sent_count=sent_count, failed_count=failed_count), 'warning')
    elif sent_count:
        flash(gettext('Successfully sent %(sent_count)s emails.', sent_count=sent_count), 'success')
    else:
        flash(gettext('All %(failed_count)s emails failed to send — campaign left as draft, check mail server logs.', failed_count=failed_count), 'danger')

    return redirect(url_for('phishing.campaign_detail', campaign_id=campaign_id))


# ── DELETE CAMPAIGN ────────────────────────────────────────────────────────────

@phishing_bp.route('/campaign/<int:campaign_id>/delete', methods=['POST'])
@login_required
@permission_required('phishing', level='edit')
def delete_campaign(campaign_id):
    campaign = query_db('SELECT * FROM phishing_campaigns WHERE id = %s', (campaign_id,), one=True)
    if not campaign:
        abort(404)
    if campaign['status'] == 'sent':
        flash(gettext('Cannot delete a sent campaign.'), 'danger')
        return redirect(url_for('phishing.campaign_detail', campaign_id=campaign_id))

    execute_db('DELETE FROM phishing_events     WHERE campaign_id = %s', (campaign_id,))
    execute_db('DELETE FROM phishing_recipients WHERE campaign_id = %s', (campaign_id,))
    execute_db('DELETE FROM phishing_campaigns  WHERE id = %s',          (campaign_id,))
    _log_audit('campaign_deleted', f'Campaign: {campaign["name"]} (id={campaign_id})')
    flash(gettext('Campaign deleted.'), 'success')
    return redirect(url_for('phishing.dashboard'))


# ── PUBLIC TRACKING (no login) ─────────────────────────────────────────────────

@phishing_bp.route('/t/<token>')
def track_click(token):
    recipient = query_db(
        'SELECT * FROM phishing_recipients WHERE token = %s', (token,), one=True
    )
    if not recipient:
        return redirect('https://www.complynex.online')

    ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr)
    ua      = request.headers.get('User-Agent', '')

    if not recipient['clicked_at']:
        execute_db(
            'UPDATE phishing_recipients SET clicked_at = %s WHERE id = %s',
            (datetime.now(), recipient['id'])
        )

    execute_db(
        """INSERT INTO phishing_events
             (campaign_id, recipient_id, event_type, ip_address, user_agent, created_at)
           VALUES (%s, %s, 'click', %s, %s, %s)""",
        (recipient['campaign_id'], recipient['id'], ip_addr, ua[:500], datetime.now())
    )

    session['phishing_token'] = token

    campaign = query_db(
        'SELECT custom_landing_html FROM phishing_campaigns WHERE id = %s',
        (recipient['campaign_id'],), one=True
    )
    if campaign and campaign.get('custom_landing_html'):
        from flask_wtf.csrf import generate_csrf
        html = (campaign['custom_landing_html']
                .replace('{{SUBMIT_URL}}', url_for('phishing.track_submit'))
                .replace('{{TOKEN}}', token)
                .replace('{{CSRF_TOKEN}}', generate_csrf()))
        return Response(html, mimetype='text/html')

    return render_template('phishing/landing.html', token=token, recipient=recipient)


@phishing_bp.route('/submit', methods=['POST'])
def track_submit():
    token = request.form.get('token') or session.get('phishing_token', '')
    recipient = query_db(
        'SELECT * FROM phishing_recipients WHERE token = %s', (token,), one=True
    ) if token else None

    ip_addr       = request.headers.get('X-Forwarded-For', request.remote_addr)
    entered_email = request.form.get('email', '')
    entered_card  = request.form.get('card', '')

    if recipient:
        if not recipient['submitted_at']:
            execute_db(
                """UPDATE phishing_recipients
                   SET submitted_at = %s, submitted_email = %s, submitted_card = %s
                   WHERE id = %s""",
                (datetime.now(), entered_email, entered_card, recipient['id'])
            )
        execute_db(
            """INSERT INTO phishing_events
                 (campaign_id, recipient_id, event_type, ip_address, user_agent, extra_data, created_at)
               VALUES (%s, %s, 'submit', %s, %s, %s, %s)""",
            (recipient['campaign_id'], recipient['id'], ip_addr,
             request.headers.get('User-Agent', '')[:500],
             json.dumps({'email': entered_email, 'card': entered_card}),
             datetime.now())
        )

    session.pop('phishing_token', None)
    return redirect(url_for('phishing.caught'))


@phishing_bp.route('/caught')
def caught():
    return render_template('phishing/caught.html')


# ── REPORTS ────────────────────────────────────────────────────────────────────

@phishing_bp.route('/reports')
@login_required
@permission_required('phishing')
def reports():
    campaign_stats = query_db(
        """SELECT c.id, c.name, c.sent_at, c.status,
                  COUNT(r.id) AS total_sent,
                  SUM(CASE WHEN r.clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS clicks,
                  SUM(CASE WHEN r.submitted_at IS NOT NULL THEN 1 ELSE 0 END) AS submits
           FROM phishing_campaigns c
           LEFT JOIN phishing_recipients r ON r.campaign_id = c.id
           GROUP BY c.id ORDER BY c.created_at DESC"""
    )
    high_risk = query_db(
        """SELECT r.recipient_name, r.recipient_email,
                  r.submitted_at, r.submitted_email, r.submitted_card,
                  c.name AS campaign_name
           FROM phishing_recipients r
           JOIN phishing_campaigns c ON c.id = r.campaign_id
           WHERE r.submitted_at IS NOT NULL
           ORDER BY r.submitted_at DESC LIMIT 50"""
    )
    return render_template('phishing/reports.html',
                           campaign_stats=campaign_stats, high_risk=high_risk)


@phishing_bp.route('/reports/export')
@login_required
@permission_required('phishing')
def export_reports():
    """Export full campaign status and analytics (per-recipient detail) as CSV"""
    rows = query_db(
        """SELECT c.name AS campaign_name, c.status AS campaign_status, c.sent_at AS campaign_sent_at,
                  r.recipient_name, r.recipient_email, r.sent_at, r.clicked_at, r.submitted_at, r.submitted_email
           FROM phishing_campaigns c
           LEFT JOIN phishing_recipients r ON r.campaign_id = c.id
           ORDER BY c.created_at DESC, r.recipient_name ASC"""
    )

    output = io.StringIO()
    output.write('﻿')  # BOM for Excel compatibility
    writer = csv.writer(output)

    writer.writerow([
        'Campaign', 'Campaign Status', 'Campaign Sent Date',
        'Recipient Name', 'Recipient Email',
        'Email Sent At', 'Link Clicked At', 'Form Submitted At',
        'Email Entered on Fake Form', 'Clicked Link', 'Submitted Form'
    ])

    for r in rows:
        writer.writerow([
            r['campaign_name'],
            (r['campaign_status'] or '').title(),
            r['campaign_sent_at'].strftime('%Y-%m-%d %H:%M') if r['campaign_sent_at'] else '',
            r['recipient_name'] or '',
            r['recipient_email'] or '',
            r['sent_at'].strftime('%Y-%m-%d %H:%M') if r['sent_at'] else '',
            r['clicked_at'].strftime('%Y-%m-%d %H:%M') if r['clicked_at'] else '',
            r['submitted_at'].strftime('%Y-%m-%d %H:%M') if r['submitted_at'] else '',
            r['submitted_email'] or '',
            'Yes' if r['clicked_at'] else 'No',
            'Yes' if r['submitted_at'] else 'No',
        ])

    output.seek(0)
    _log_audit('Export Phishing Analytics', 'Exported full campaign status/analytics CSV')

    filename = f"Phishing_Awareness_Analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename={filename}'}
    )
