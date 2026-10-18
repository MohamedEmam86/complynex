# =============================================================================
# ComplyNex — notification delivery (Phase 5)
#
# WHY THIS EXISTS
# Nothing in ComplyNex could send an email: EMAIL_MOCK_MODE defaults to True,
# and config.py reads EMAIL_USER/EMAIL_PASS while .env holds GMAIL_USER/
# GMAIL_PASS — the names never matched. The Training module's "Send reminders"
# button looped over enrolments, called print(), and flashed "Sent N reminder
# emails". Nothing was ever sent.
#
# So delivery is abstracted. In-app notifications are real today; email is a
# channel behind a config flag. Turning email on later is configuration, not a
# rewrite — and nothing claims to have sent something it did not.
# =============================================================================
from datetime import datetime

from flask import current_app, url_for

from database.db import get_db


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def email_enabled():
    """True only when email could actually leave the building."""
    try:
        cfg = current_app.config
        if cfg.get('EMAIL_MOCK_MODE', True):
            return False
        return bool(cfg.get('MAIL_USERNAME') and cfg.get('MAIL_PASSWORD'))
    except Exception:
        return False


def delivery_status():
    """For the UI, so a screen can say what will really happen."""
    return {
        'inapp': True,
        'email': email_enabled(),
        'note': ('In-app only. Email is not configured — set EMAIL_USER, '
                 'EMAIL_PASS and EMAIL_MOCK_MODE=False in .env to enable it.')
               if not email_enabled() else 'In-app and email.',
    }


def notify(user_ids, title, message, link=None, category='info', channels=('inapp',)):
    """Send to one or many users. Returns what was actually delivered.

    Never reports an email as sent when the mail path is not configured.
    """
    if isinstance(user_ids, int):
        user_ids = [user_ids]
    user_ids = [u for u in dict.fromkeys(user_ids) if u]
    if not user_ids:
        return {'inapp': 0, 'email': 0, 'skipped': 0}

    db = get_db()
    sent_inapp = 0
    if 'inapp' in channels:
        for uid in user_ids:
            db.execute(
                "INSERT INTO notifications (user_id, title, message, type, is_read, link, created_at) "
                "VALUES (%s,%s,%s,%s,0,%s,%s)",
                (uid, title[:200], message, category, link, _now()))
            sent_inapp += 1
        db.commit()

    sent_email = 0
    if 'email' in channels and email_enabled():
        rows = db.execute("SELECT id, email FROM users WHERE id = ANY(%s)", (user_ids,)).fetchall()
        try:
            from services.email_service import email_service
            for r in rows:
                r = dict(r)
                if r['email'] and email_service._send_email(r['email'], title, message):
                    sent_email += 1
        except Exception as e:
            current_app.logger.warning(f'email delivery failed: {e}')

    return {'inapp': sent_inapp, 'email': sent_email,
            'skipped': len(user_ids) - sent_inapp if 'inapp' in channels else 0}
