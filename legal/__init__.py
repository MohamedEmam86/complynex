"""Public legal pages of the platform: privacy policy and terms of use.

Plain public pages (no login), shown in English and Arabic on the same page.
They describe the ComplyNex service itself; a client company's own privacy
notice to its customers is the client's responsibility.
"""
from flask import Blueprint, render_template

legal_bp = Blueprint('legal', __name__)

UPDATED = '2026-10-25'
CONTACT = 'admin@complynex.online'


@legal_bp.route('/privacy')
def privacy():
    return render_template('legal/privacy.html', updated=UPDATED, contact=CONTACT)


@legal_bp.route('/terms')
def terms():
    return render_template('legal/terms.html', updated=UPDATED, contact=CONTACT)
