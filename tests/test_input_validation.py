"""Unit tests for the server-side validation added to whistleblowing, complaints,
data protection, cyber, risk and reporting — no database."""
from datetime import date, datetime, timedelta

import pytest
from flask import Flask
from flask_babel import Babel


@pytest.fixture
def ctx():
    app = Flask(__name__)
    Babel(app)
    with app.test_request_context('/'):
        yield


def test_breach_dates_and_count(ctx):
    from data_protection.routes import validate_breach_report as v
    today = date(2026, 10, 24)
    assert v('2026-10-01', '2026-10-02', '5', today) is None
    assert v('2026-10-03', '2026-10-02', '5', today)            # breach after discovery
    assert v('2026-10-01', '2026-10-25', '5', today)            # discovery in the future
    assert v('2026-10-01', '2026-10-02', '-1', today)           # negative count
    assert v('', '2026-10-02', '0', today)


def test_breach_72h_overdue():
    from data_protection.routes import breach_notification_overdue as od
    b = {'pdpc_notification_required': 1, 'pdpc_notified': 0, 'discovery_date': '2026-10-20'}
    assert od(b, datetime(2026, 10, 23, 0, 1))
    assert not od(b, datetime(2026, 10, 22, 23, 0))
    assert not od(dict(b, pdpc_notified=1), datetime(2026, 10, 30))
    assert not od(dict(b, pdpc_notification_required=0), datetime(2026, 10, 30))


def test_kri_threshold_order(ctx):
    from risk_management.routes import validate_kri_thresholds as v
    assert v('UPPER', 0, 5, 10) is None                         # target 0 is a real value
    assert v('UPPER', 0, 10, 5)
    assert v('LOWER', 10, 5, 1) is None
    assert v('LOWER', 1, 5, 10)
    assert v('UPPER', None, 5, None) is None


def test_maturity_level_range():
    from cyber.resilience import _level, ResilienceError
    assert _level('') is None and _level('0') == 0 and _level('5') == 5
    for bad in ('7', '-1', 'x'):
        with pytest.raises(ResilienceError):
            _level(bad)


def test_public_complaint_validation(ctx):
    from consumer_protection.routes import validate_public_complaint as v
    good = {'customer_name': 'A B', 'customer_email': 'a@b.example', 'customer_phone': '+20 100 123 4567',
            'complaint_category': 'FEES', 'complaint_subject': 'Fees',
            'complaint_description': 'I was charged twice for one transfer.'}
    assert v(good, {'FEES'}) == []
    assert v(dict(good, customer_email='not-an-email'), {'FEES'})
    assert v(dict(good, customer_phone='12'), {'FEES'})
    assert v(dict(good, complaint_category='999'), {'FEES'})
    assert v(dict(good, complaint_description='x'), {'FEES'})


def test_report_overdue_flag():
    from models.reporting import RegulatoryReportSubmission as S
    past = (date.today() - timedelta(days=1)).isoformat()
    future = (date.today() + timedelta(days=1)).isoformat()
    assert S(due_date=past, status='pending').is_overdue
    assert not S(due_date=past, status='submitted').is_overdue
    assert not S(due_date=future, status='pending').is_overdue
