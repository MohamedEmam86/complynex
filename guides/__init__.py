"""Guides: rating scales used across the system and the ESG / carbon assessment guideline."""
from flask import Blueprint, render_template, session
from flask_login import login_required

guides_bp = Blueprint('guides', __name__, url_prefix='/guides')


@guides_bp.route('/ratings')
@login_required
def ratings():
    from utils.rating_guides import all_guides
    return render_template('guides/ratings.html', guides=all_guides(), ar=session.get('lang') == 'ar')


@guides_bp.route('/esg-carbon')
@login_required
def esg_carbon():
    from utils.rating_guides import guide
    return render_template('guides/esg_carbon.html', ar=session.get('lang') == 'ar', guide=guide)
