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

from flask import current_app
from extensions import mail
from flask_mail import Message

class EmailService:
    """
    Email service for sending GHE notifications.
    Uses Flask-Mail for delivery and supports mock mode.
    """

    def __init__(self, app=None):
        self.app = app
        self.mock_mode = True

        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app configuration."""
        self.app = app
        self.mock_mode = app.config.get('EMAIL_MOCK_MODE', True)
        self.sender_email = app.config.get('MAIL_DEFAULT_SENDER', 'noreply@complynex.online')

    def _template_override(self, template_key, context):
        """
        Look up an admin-edited template (Settings > Email Templates). Returns
        (subject, html, text) tuples, each None if no active override exists
        for this key, so callers can fall back to their hardcoded default.
        Placeholders use {field_name} and missing keys are left as-is rather
        than raising, so a template referencing a field a caller didn't pass
        degrades gracefully instead of crashing the notification.
        """
        try:
            from database.db import get_db

            class _SafeDict(dict):
                def __missing__(self, key):
                    return '{' + key + '}'

            db = get_db()
            row = db.execute(
                'SELECT subject, body_html, body_text FROM email_templates WHERE template_key = %s AND is_active = TRUE',
                (template_key,)
            ).fetchone()
            if not row:
                return None, None, None
            safe_ctx = _SafeDict(context)
            subject = row['subject'].format_map(safe_ctx) if row['subject'] else None
            html = row['body_html'].format_map(safe_ctx) if row['body_html'] else None
            text = row['body_text'].format_map(safe_ctx) if row['body_text'] else None
            return subject, html, text
        except Exception as e:
            if current_app:
                current_app.logger.warning(f"Email template override lookup failed for '{template_key}': {e}")
            return None, None, None

    def _send_email(self, to_email, subject, html_content, text_content=None):
        """
        Send an email (or log it in mock mode).

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML body of the email
            text_content: Plain text fallback (optional)

        Returns:
            bool: True if sent successfully
        """
        if self.mock_mode:
            # Log email instead of sending
            if current_app:
                current_app.logger.info(f"[MOCK EMAIL] To: {to_email} | Subject: {subject} | Sender: {self.sender_email}")
            else:
                # Fallback if no app context (shouldn't happen in normal use)
                print(f"[MOCK EMAIL] To: {to_email} | Subject: {subject}")
            return True



        try:
            msg = Message(
                subject=subject,
                recipients=[to_email],
                html=html_content,
                body=text_content,
                sender=self.sender_email
            )

            # Use current_app context if available, otherwise app context
            if current_app:
                mail.send(msg)
            else:
                with self.app.app_context():
                    mail.send(msg)

            return True
        except Exception as e:
            if current_app:
                current_app.logger.error(f"Email send error: {str(e)}")
            else:
                print(f"❌ Email error: {str(e)}")
            return False

    def send_submission_confirmation(self, email, declaration):
        """
        Send confirmation email after public submission.
        
        Args:
            email: Submitter's email
            declaration: Declaration dict with tracking_id and declaration_number
        """
        override_subject, override_html, _ = self._template_override('ghe_submission_confirmation', declaration)
        subject = override_subject or f"GHE Declaration Received - {declaration['declaration_number']}"
        if override_html:
            return self._send_email(email, subject, override_html)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #0d6efd; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background: #f8f9fa; }}
                .tracking-box {{ background: #fff; border: 2px solid #0d6efd; padding: 15px; text-align: center; margin: 20px 0; }}
                .tracking-id {{ font-size: 24px; font-weight: bold; color: #0d6efd; }}
                .footer {{ text-align: center; padding: 10px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎁 GHE Declaration Received</h1>
                </div>
                <div class="content">
                    <p>Dear {declaration.get('submitter_name', 'Employee')},</p>
                    
                    <p>Thank you for submitting your Gift, Hospitality & Entertainment declaration. 
                    Your submission has been received and is being reviewed by our compliance team.</p>
                    
                    <div class="tracking-box">
                        <p>Your Tracking ID:</p>
                        <p class="tracking-id">{declaration['tracking_id']}</p>
                        <p><small>Please save this ID to check your declaration status</small></p>
                    </div>
                    
                    <h3>Submission Details:</h3>
                    <ul>
                        <li><strong>Declaration Number:</strong> {declaration['declaration_number']}</li>
                        <li><strong>Type:</strong> {declaration['ghe_type']}</li>
                        <li><strong>Value:</strong> {declaration['estimated_value_egp']:.2f} EGP</li>
                    </ul>
                    
                    <p>You will receive an email notification once a decision has been made.</p>
                    
                    <p>Best regards,<br>ComplyNex Compliance Team</p>
                </div>
                <div class="footer">
                    <p>This is an automated message from ComplyNex Full Compliance Platform</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(email, subject, html_content)
    
    def send_approval_notification(self, email, declaration):
        """Send notification when declaration is approved."""
        override_subject, override_html, _ = self._template_override('ghe_approval_notification', declaration)
        subject = override_subject or f"✅ GHE Declaration Approved - {declaration['declaration_number']}"
        if override_html:
            return self._send_email(email, subject, override_html)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #198754; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background: #f8f9fa; }}
                .status-box {{ background: #d1e7dd; border: 2px solid #198754; padding: 15px; text-align: center; margin: 20px 0; border-radius: 8px; }}
                .footer {{ text-align: center; padding: 10px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>✅ Declaration Approved</h1>
                </div>
                <div class="content">
                    <p>Dear {declaration.get('submitter_name', 'Employee')},</p>
                    
                    <div class="status-box">
                        <h2 style="color: #198754; margin: 0;">APPROVED</h2>
                        <p>Your GHE declaration has been approved</p>
                    </div>
                    
                    <h3>Declaration Details:</h3>
                    <ul>
                        <li><strong>Declaration Number:</strong> {declaration['declaration_number']}</li>
                        <li><strong>Type:</strong> {declaration['ghe_type']}</li>
                        <li><strong>Value:</strong> {declaration['estimated_value_egp']:.2f} EGP</li>
                    </ul>
                    
                    {f"<p><strong>Comments:</strong> {declaration.get('compliance_comments') or declaration.get('manager_comments', 'No additional comments')}</p>" if declaration.get('compliance_comments') or declaration.get('manager_comments') else ""}
                    
                    <p>Thank you for your compliance.</p>
                    
                    <p>Best regards,<br>ComplyNex Compliance Team</p>
                </div>
                <div class="footer">
                    <p>This is an automated message from ComplyNex Full Compliance Platform</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(email, subject, html_content)
    
    def send_rejection_notification(self, email, declaration, reason):
        """Send notification when declaration is rejected."""
        override_subject, override_html, _ = self._template_override(
            'ghe_rejection_notification', {**declaration, 'reason': reason})
        subject = override_subject or f"❌ GHE Declaration Rejected - {declaration['declaration_number']}"
        if override_html:
            return self._send_email(email, subject, override_html)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #dc3545; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background: #f8f9fa; }}
                .status-box {{ background: #f8d7da; border: 2px solid #dc3545; padding: 15px; text-align: center; margin: 20px 0; border-radius: 8px; }}
                .reason-box {{ background: #fff; border-left: 4px solid #dc3545; padding: 15px; margin: 15px 0; }}
                .footer {{ text-align: center; padding: 10px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>❌ Declaration Rejected</h1>
                </div>
                <div class="content">
                    <p>Dear {declaration.get('submitter_name', 'Employee')},</p>
                    
                    <div class="status-box">
                        <h2 style="color: #dc3545; margin: 0;">REJECTED</h2>
                        <p>Your GHE declaration has been rejected</p>
                    </div>
                    
                    <h3>Declaration Details:</h3>
                    <ul>
                        <li><strong>Declaration Number:</strong> {declaration['declaration_number']}</li>
                        <li><strong>Type:</strong> {declaration['ghe_type']}</li>
                        <li><strong>Value:</strong> {declaration['estimated_value_egp']:.2f} EGP</li>
                    </ul>
                    
                    <div class="reason-box">
                        <strong>Reason for Rejection:</strong>
                        <p>{reason}</p>
                    </div>
                    
                    <p>If you have questions about this decision, please contact the compliance team.</p>
                    
                    <p>Best regards,<br>ComplyNex Compliance Team</p>
                </div>
                <div class="footer">
                    <p>This is an automated message from ComplyNex Full Compliance Platform</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(email, subject, html_content)
    
    def send_info_request_notification(self, email, declaration, questions):
        """Send notification when more information is requested."""
        status_url = f"/ghe/public/status/{declaration['tracking_id']}"

        override_subject, override_html, _ = self._template_override(
            'ghe_info_request_notification', {**declaration, 'questions': questions, 'status_url': status_url})
        subject = override_subject or f"ℹ️ More Information Needed - {declaration['declaration_number']}"
        if override_html:
            return self._send_email(email, subject, override_html)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #ffc107; color: #000; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background: #f8f9fa; }}
                .status-box {{ background: #fff3cd; border: 2px solid #ffc107; padding: 15px; text-align: center; margin: 20px 0; border-radius: 8px; }}
                .question-box {{ background: #fff; border-left: 4px solid #ffc107; padding: 15px; margin: 15px 0; }}
                .action-btn {{ display: inline-block; background: #0d6efd; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin-top: 15px; }}
                .footer {{ text-align: center; padding: 10px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>ℹ️ More Information Needed</h1>
                </div>
                <div class="content">
                    <p>Dear {declaration.get('submitter_name', 'Employee')},</p>
                    
                    <div class="status-box">
                        <h2 style="color: #856404; margin: 0;">ACTION REQUIRED</h2>
                        <p>Additional information is needed for your declaration</p>
                    </div>
                    
                    <h3>Declaration Details:</h3>
                    <ul>
                        <li><strong>Declaration Number:</strong> {declaration['declaration_number']}</li>
                        <li><strong>Tracking ID:</strong> {declaration['tracking_id']}</li>
                    </ul>
                    
                    <div class="question-box">
                        <strong>Information Requested:</strong>
                        <p>{questions}</p>
                    </div>
                    
                    <p>Please provide the requested information as soon as possible to continue processing your declaration.</p>
                    
                    <p>Best regards,<br>ComplyNex Compliance Team</p>
                </div>
                <div class="footer">
                    <p>This is an automated message from ComplyNex Full Compliance Platform</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(email, subject, html_content)


# Global email service instance
email_service = EmailService()
