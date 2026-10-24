# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""utils.labels: readable labels and display formatting (no database)."""
import os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from flask import Flask
from flask_babel import Babel
from utils import labels as L

app = Flask(__name__)
Babel(app)


def test_known_codes_and_fallback():
    with app.test_request_context():
        assert L.label('IN_PROGRESS') == 'In Progress'
        assert L.label('in_progress') == 'In Progress'
        assert L.label('compliance_officer') == 'Compliance Officer'
        assert L.label('NOT_YET_TESTED') == 'Not yet tested'
        assert L.label('Operational Risk Review') == 'Operational Risk Review'
        assert L.label(None) == '—' and L.label('', '-') == '-'
        assert L.label(3) == 3
        assert L.label('PEP') == 'PEP'
        assert L.label(True) == 'Yes'


def test_numbers():
    assert L.num(1234567) == '1,234,567'
    assert L.num('1234.5000') == '1,234.5'
    assert L.num(None) == '—'
    assert L.money(1250000) == '1,250,000.00'
    assert L.money(10, 'EGP') == '10.00 EGP'
    assert L.pct(12.345) == '12.3%'
    assert L.pct(0.5, ratio=True) == '50%'
    assert L.num('abc') == 'abc'


def test_dates():
    aware = datetime(2026, 1, 15, 10, 30, 12, 123456, tzinfo=timezone.utc)
    assert L.fmt_dt(aware) == '2026-01-15 12:30'          # Cairo = UTC+2 in January
    assert L.fmt_date('2026-03-01T08:00:00') == '2026-03-01'
    assert '.' not in L.fmt_dt(datetime.now())
    assert L.fmt_dt(None) == '—'
