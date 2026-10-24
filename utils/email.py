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

import logging
from flask import render_template, current_app
from flask_mail import Message
from extensions import mail

logger = logging.getLogger(__name__)

def _send_in_background(app, msg, to_email):
    """Deliver one message outside the request; failures are logged, never raised."""
    try:
        with app.app_context():
            mail.send(msg)
        logger.info("Email sent successfully to %s", to_email)
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, e)


def send_mail_async(msg, to_email=None):
    """Hand a Flask-Mail message to a background worker so SMTP never blocks a
    web response (a slow SMTP server once turned /whistleblowing/submit into a 504).
    Under gunicorn+gevent the thread is a greenlet. On the demo instance nothing
    leaves the server: the message is only logged."""
    from utils.demo import is_demo
    to_email = to_email or ', '.join(msg.recipients or [])
    if is_demo():
        logger.info("demo instance: email to %s not sent (subject: %s)", to_email, msg.subject)
        return False
    import threading
    app = current_app._get_current_object()
    threading.Thread(target=_send_in_background, args=(app, msg, to_email),
                     daemon=True).start()
    return True


def send_confirmation_email(to_email, subject, template, **kwargs):
    """
    Send a confirmation email using Flask-Mail, without blocking the request.

    The body is rendered here (inside the request, so locale and url_for work);
    delivery happens in the background via send_mail_async().

    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        template (str): Template path (e.g., 'emails/confirmation.html')
        **kwargs: Context variables for the template
    """
    try:
        app = current_app._get_current_object()
        html_body = render_template(template, **kwargs)
        msg = Message(
            subject=subject,
            recipients=[to_email],
            html=html_body,
            sender=app.config.get('MAIL_USERNAME', 'noreply@complynex.online')
        )
        return send_mail_async(msg, to_email)
    except Exception as e:
        logger.error(f"Failed to queue email to {to_email}: {str(e)}")
        # Don't raise error to avoid breaking the user flow, just log it
        return False
