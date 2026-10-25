"""Public legal pages render without a login. No database."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from flask import Flask
from legal import legal_bp

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _client():
    app = Flask(__name__, template_folder=os.path.join(_ROOT, 'templates'))
    app.register_blueprint(legal_bp)
    return app.test_client()


def test_privacy_page_public_and_bilingual():
    r = _client().get('/privacy')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Privacy Policy' in body and 'سياسة الخصوصية' in body
    assert 'Limited Use' in body


def test_terms_page_public_and_bilingual():
    r = _client().get('/terms')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Terms of Use' in body and 'شروط الاستخدام' in body
