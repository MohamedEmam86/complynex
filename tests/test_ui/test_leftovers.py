# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""Leftover fixes: regulator-neutral wording, screening config columns, TM rule
Arabic name, whitelist migration review window, regcontrols area labels (no database)."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from flask import Flask  # noqa: E402
from flask_babel import Babel  # noqa: E402
from utils import labels as L  # noqa: E402

app = Flask(__name__)
Babel(app)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


NEUTRAL = ['templates/policies/gap_analysis.html', 'templates/policies/manage_gap_requirements.html',
           'templates/policies/detail.html', 'templates/policies/create.html', 'templates/policies/pending.html',
           'templates/policies/upcoming_reviews.html', 'templates/ghe/create.html', 'templates/ghe/list.html',
           'templates/whistleblowing/anonymous_info.html', 'templates/screening/reports_dashboard.html',
           'templates/screening/ongoing.html', 'templates/screening/sar_preview.html',
           'templates/cyber/dashboard.html', 'whistleblowing/routes.py', 'screening/result_view.py']


def test_no_hard_coded_central_bank_in_ui_text():
    for rel in NEUTRAL:
        text = _read(rel)
        assert 'Central Bank' not in text and 'البنك المركزي' not in text, rel
        assert not re.search(r"_\([\"'][^\"']*\bCBE\b", text), rel
        assert "'CBE General'" not in text and "'CBE Circular 2023'" not in text, rel
    assert "or 'CBE Circular 2023'" not in _read('policies/routes.py')


def test_screening_config_template_reads_real_columns():
    t = _read('templates/screening/config_edit.html')
    assert 's.config_key' in t and 's.config_value' in t
    assert 's.key' not in t and 's.value' not in t


def test_tm_rule_forms_and_routes_carry_arabic_name():
    for rel in ('templates/aml/rule_form.html', 'templates/aml/rules/form.html'):
        assert 'name="rule_name_ar"' in _read(rel), rel
    routes = _read('aml/routes.py')
    assert routes.count('rule_name_ar') >= 8


def test_whitelist_migration_gives_legacy_entries_a_review_window():
    sql = _read('database/migrations/20261110_screening_four_eyes_whitelist.sql')
    assert 'GREATEST(' in sql and "(CURRENT_DATE + 30)" in sql
    assert re.search(r"WHERE approval_basis IS NULL\s+AND review_date", sql)


def test_regcontrols_area_codes_have_labels():
    from packs.fra_nbfi.library import AREAS
    with app.test_request_context():
        for code, (en, _ar) in AREAS.items():
            assert L.label(code) == en, code
        assert L.label('aml_cft') == 'AML/CFT'
        assert L.label('UNAUTH_TXN') == 'Unauthorised transaction'
        assert L.label('CASH_DEPOSIT') == 'Cash deposit'
