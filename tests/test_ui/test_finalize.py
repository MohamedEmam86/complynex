# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""utils.labels.finalize (applied to every {{ }} output), label_codes and
history_text (stored sentences shown in the reader's language). No database."""
import os, sys
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from flask import Flask, render_template_string
from flask_babel import Babel
from markupsafe import Markup
from utils import labels as L

app = Flask(__name__)
Babel(app)
L.register_filters.__globals__  # module import check
app.jinja_env.filters.update(label_codes=L.label_codes, history=L.history_text)
app.jinja_env.finalize = L.finalize

UTC = timezone.utc


def r(src, **ctx):
    with app.test_request_context():
        return render_template_string(src, **ctx)


def test_datetime_objects():
    aware = datetime(2026, 1, 15, 10, 30, 12, 640079, tzinfo=UTC)
    assert L.finalize(aware) == '2026-01-15 12:30'          # Cairo, no seconds / microseconds
    assert L.finalize(datetime(2026, 11, 3, 0, 0, 0)) == '2026-11-03'   # naive midnight = a date
    assert L.finalize(date(2026, 11, 3)) == date(2026, 11, 3)          # str(date) is already ISO
    naive = datetime(2026, 10, 24, 16, 44, 31, 640079)
    out = L.finalize(naive)
    assert len(out) == 16 and out.startswith('2026-10-24') and ':31' not in out


def test_timestamp_strings():
    assert L.finalize('2026-01-24 16:44:31.640079+02') == '2026-01-24 16:44'
    assert L.finalize('2026-01-24 16:44:31.640079+02:00') == '2026-01-24 16:44'
    assert L.finalize('2026-07-01 09:00:00+00') == '2026-07-01 12:00'      # Cairo summer time (UTC+3)
    assert L.finalize('2026-01-15 10:30:12+00') == '2026-01-15 12:30'
    assert L.finalize('2026-01-15T10:30:12.5Z') == '2026-01-15 12:30'
    assert L.finalize('2026-11-03 00:00:00') == '2026-11-03'
    # untouched: already display form, machine 'T' values for inputs, dates, other text
    assert L.finalize('2026-10-24 16:44') == '2026-10-24 16:44'
    assert L.finalize('2026-10-24T16:44') == '2026-10-24T16:44'
    assert L.finalize('2026-10-24T16:44:31') == '2026-10-24T16:44:31'
    assert L.finalize('2026-10-24') == '2026-10-24'
    assert L.finalize('INC-2026-0001: 10:30 call') == 'INC-2026-0001: 10:30 call'
    assert L.finalize('Room 12-14, floor 3') == 'Room 12-14, floor 3'


def test_embedded_timestamps():
    s = 'Reviewed at 2026-01-15 10:30:12.123456+00 by Salma'
    assert L.finalize(s) == 'Reviewed at 2026-01-15 12:30 by Salma'
    assert L.finalize('Due 2026-11-03 00:00:00 latest') == 'Due 2026-11-03 latest'
    assert L.finalize('id=2026-10-24T16:44:31 x') == 'id=2026-10-24T16:44:31 x'   # machine form kept


def test_numbers_stay_machine_readable():
    assert L.finalize(50000.0) == '50000'
    assert L.finalize(211500000.0) == '211500000'
    assert L.finalize(-0.0) == '0'
    assert L.finalize(2.6852) == '2.6852'              # precision kept for form values
    assert L.finalize(33.333333333333336) == '33.3333'
    assert L.finalize(12345.678) == '12345.68'
    assert L.finalize(0.1 + 0.2) == '0.3'
    assert L.finalize(0.000123456789) == '0.000123457'
    assert L.finalize(Decimal('24.0000')) == '24'
    assert L.finalize(Decimal('2.5000')) == '2.5'
    assert L.finalize(Decimal('0.0005')) == '0.0005'
    assert L.finalize(Decimal('1E+3')) == '1000'
    assert L.finalize(7) == 7 and L.finalize(True) is True
    for v in ('50000', '2.6852', '33.3333', '0.000123457', '2.5'):
        float(v)                                      # parseable, no thousands separator


def test_none_and_passthrough():
    assert L.finalize(None) == ''
    m = Markup('{"at": "2026-10-24 16:44:31.640079"}')
    assert L.finalize(m) is m                          # |tojson / |safe untouched
    assert L.finalize([1.0]) == [1.0]


def test_in_templates():
    out = r('<input type="number" name="t" value="{{ t }}"><p>{{ when }}</p><i>{{ missing }}</i>'
            '<script nonce="x">var d = {{ data|tojson }};</script>',
            t=50000.0, when=datetime(2026, 1, 15, 10, 30, 12, 9, tzinfo=UTC), missing=None,
            data={'at': '2026-01-15 10:30:12.000009', 'v': 1.0})
    assert 'value="50000"' in out
    assert '<p>2026-01-15 12:30</p>' in out
    assert '<i></i>' in out
    assert '"2026-01-15 10:30:12.000009"' in out and '"v": 1.0' in out   # JSON unchanged
    assert r('{{ x|default("-") }}') == '-'
    assert r('{{ "%.1f"|format(2.0) }}') == '2.0'      # explicit formatting is respected


def test_label_codes():
    with app.test_request_context():
        assert L.label_codes('Complaint via PUBLIC_FORM') == 'Complaint via Online form'
        assert L.label_codes('moved to IN_PROGRESS') == 'moved to In Progress'
        assert L.label_codes('source tm_alert') == 'source Transaction monitoring alert'
        assert L.label_codes('pentest: latest expired; malware_test: none') == 'pentest: latest expired; Malware test: none'
        assert L.label_codes('13 department(s) below 100% (overall 0.0%)') == '13 department(s) below 100% (overall 0%)'
        assert L.label_codes('INC-2026-0001 by ID') == 'INC-2026-0001 by ID'
        assert L.label_codes('see a@b.co and /aml/sars_list') == 'see a@b.co and /aml/sars_list'
        assert L.label_codes(None) == ''


def test_history_sentences():
    with app.test_request_context():
        assert L.history_text('Complaint submitted via PUBLIC_FORM') == 'Complaint submitted via Online form'
        assert L.history_text('Root cause: SYSTEM_ERROR; redress: FEE_WAIVER') == \
            'Root cause: System / technical error; redress: Fee waiver / reversal'
        assert L.history_text('Status changed from NEW to RESOLVED') == 'Status changed from New to Resolved'
        assert L.history_text('Status changed from IN_PROGRESS to RESOLVED. Fee refunded') == \
            'Status changed from In Progress to Resolved. Fee refunded'
        assert L.history_text('Identity verified via ID_CARD') == 'Identity verified via National ID card'
        assert L.history_text('Request received via EMAIL on 2026-10-01') == 'Request received via Email on 2026-10-01'
        assert L.history_text('SAR SAR-1 opened (source tm_alert)') == \
            'SAR SAR-1 opened (source: Transaction monitoring alert)'
        assert L.history_text('Free text typed by a user') == 'Free text typed by a user'
