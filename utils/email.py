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

def send_confirmation_email(to_email, subject, template, **kwargs):
    """
    Send a confirmation email using Flask-Mail.
    
    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        template (str): Template path (e.g., 'emails/confirmation.html')
        **kwargs: Context variables for the template
    """
    try:
        app = current_app._get_current_object()
        
        # Render HTML body
        html_body = render_template(template, **kwargs)
        
        msg = Message(
            subject=subject,
            recipients=[to_email],
            html=html_body,
            sender=app.config.get('MAIL_USERNAME', 'noreply@complynex.online')
        )
        
        mail.send(msg)
        logger.info(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        # Don't raise error to avoid breaking the user flow, just log it
        return False
