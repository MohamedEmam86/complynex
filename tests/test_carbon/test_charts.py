"""Chart specs and S/G feed matching (pure functions, no database)."""
from datetime import date

import pytest
from flask import Flask
from flask_babel import Babel

from carbon import charts as CH
from esg import feeds as F


@pytest.fixture(autouse=True)
def _ctx():
    app = Flask(__name__)
    Babel(app)
    with app.test_request_context():
        yield


E = [
    {'scope': 'scope1', 'category': 'mobile_combustion', 'tco2e': 2.0, 'activity_month': date(2026, 1, 1), 'site_id': 1},
    {'scope': 'scope2', 'category': 'purchased_electricity', 'tco2e': 5.0, 'activity_month': date(2026, 1, 1), 'site_id': 2},
    {'scope': 'scope2', 'category': 'purchased_electricity', 'tco2e': 4.0, 'activity_month': date(2026, 2, 1), 'site_id': 2},
    {'scope': 'scope3', 'category': 'business_travel', 'tco2e': 1.5, 'activity_month': None, 'site_id': None},
]


def test_monthly_stacks_only_enabled_scopes_and_counts_undated():
    s = CH.monthly_by_scope(E, ['scope1', 'scope2'])
    assert s['labels'] == ['2026-01', '2026-02']
    assert [x['data'] for x in s['series']] == [[2.0, 0.0], [5.0, 4.0]]
    assert s['no_month'] == 1


def test_monthly_needs_two_months():
    assert CH.monthly_by_scope(E[:2], ['scope1', 'scope2']) is None


def test_category_largest_first():
    s = CH.by_category(E)
    assert s['series'][0]['data'] == [9.0, 2.0, 1.5]


def test_site_needs_two_sites():
    assert CH.by_site(E[:1], {}) is None
    s = CH.by_site(E, {1: 'HQ', 2: 'Branch'})
    assert s['labels'][0] == 'Branch' and s['series'][0]['data'][0] == 9.0


def test_pathway_linear_to_2030():
    # base 2026: 100 t, target 70 t by 2030 -> 7.5 t a year
    s = CH.pathway({'baseline_year': 2026}, {'baseline_tco2e': 100, 'target_tco2e': 70}, 95, {'end_date': date(2027, 12, 31)})
    assert s['labels'] == ['2026', '2027', '2028', '2029', '2030']
    assert s['series'][0]['data'] == [100.0, 92.5, 85.0, 77.5, 70.0]
    assert s['series'][1]['data'][1] == 95.0


def test_offset_doughnut():
    s = CH.offset_doughnut(30, 40)
    assert s['series'][0]['data'] == [30.0, 10.0] and s['centre'][0] == '75%'
    assert CH.offset_doughnut(5, 0) is None


@pytest.mark.parametrize('text,metric', [
    ('GRI 404-1 Average hours of training per employee', 'training'),
    ('Whistleblowing & Grievance Mechanism', 'whistleblowing'),
    ('خصوصية البيانات (ح 4)', 'data_protection'),
    ('Conflicts of Interest Management', 'coi'),
    ('Board Composition & Independence', 'board'),
    ('Energy consumption', None),
])
def test_feed_detection(text, metric):
    assert F.detect(text) == metric
