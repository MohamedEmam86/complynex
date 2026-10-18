"""Tests for the carbon reporting journey (carbon/journey.py) and the Carbon → ESG
links (carbon/links.py). Pure functions on snapshot dicts, no database."""

from carbon import journey as J
from carbon import links as L

# A period where everything up to submission is complete.
COMPLETE = {
    'period': True, 'approach': 'operational_control', 'base_year': 2024, 'enabled': ['scope1', 'scope2'],
    'entities': 0, 'sites_active': 2, 'factors_by_scope': {'scope1': 3, 'scope2': 1, 'scope3': 0},
    'entries_in': 24, 'entries_in_evidence': 24, 'entries_out': 0, 'entries_no_month': 0,
    'dq_critical': 0, 'dq_warning': 0, 'wf_status': 'approved', 'disclosure_exported': True,
    'regulator_applies': True, 'offsets_apply': True, 'regulator_status': 'Submitted',
    'obligation': {'status': 'FULFILLED', 'required': 10, 'purchased': 10},
}


def status(j):
    return {s['key']: s['status'] for s in j['steps']}


def missing(j, key):
    return [m[0] for m in next(s for s in j['steps'] if s['key'] == key)['missing']]


def test_nine_steps_in_order_with_pages():
    j = J.compute({})
    assert [s['key'] for s in j['steps']] == ['boundary', 'sites', 'factors', 'activity', 'quality', 'review',
                                              'disclosure', 'regulator', 'offsets']
    assert [s['n'] for s in j['steps']] == list(range(1, 10))
    assert all(s['endpoint'].startswith('carbon.') for s in j['steps'])


def test_fresh_installation():
    j = J.compute({'enabled': ['scope1', 'scope2']})
    st = status(j)
    assert st['boundary'] == st['sites'] == st['factors'] == J.NOT_STARTED
    assert st['activity'] == J.BLOCKED and missing(j, 'activity') == ['no_period']
    assert st['quality'] == st['review'] == st['disclosure'] == J.BLOCKED
    assert j['next']['key'] == 'boundary' and j['done'] == 0


def test_everything_done():
    j = J.compute(COMPLETE)
    assert set(status(j).values()) == {J.DONE}
    assert j['next'] is None and j['done'] == j['applicable'] == 9


def test_boundary_half_done():
    j = J.compute(dict(COMPLETE, base_year=None))
    assert status(j)['boundary'] == J.IN_PROGRESS and missing(j, 'boundary') == ['no_base_year']
    assert j['next']['key'] == 'boundary'


def test_sites_needed_even_with_entities():
    j = J.compute(dict(COMPLETE, sites_active=0, entities=2))
    assert status(j)['sites'] == J.IN_PROGRESS and missing(j, 'sites') == ['no_sites']


def test_factors_per_scope_in_boundary():
    j = J.compute(dict(COMPLETE, enabled=['scope1', 'scope2', 'scope3']))
    assert status(j)['factors'] == J.IN_PROGRESS
    assert next(s for s in j['steps'] if s['key'] == 'factors')['missing'] == [('no_factors_scope', 'scope3')]


def test_activity_evidence_and_notes():
    j = J.compute(dict(COMPLETE, entries_in_evidence=20, entries_no_month=2, entries_out=5, wf_status='preparing',
                       disclosure_exported=False, regulator_status='Draft', obligation=None))
    st = status(j)
    assert st['activity'] == J.IN_PROGRESS
    assert missing(j, 'activity') == ['no_evidence', 'no_month', 'outside_boundary']
    act = next(s for s in j['steps'] if s['key'] == 'activity')
    assert ('no_evidence', 4) in act['missing'] and ('outside_boundary', 5) in act['missing']
    assert j['next']['key'] == 'activity'


def test_no_entries_blocks_quality_and_review():
    j = J.compute(dict(COMPLETE, entries_in=0, entries_in_evidence=0, wf_status='preparing', disclosure_exported=False,
                       regulator_status='Draft', obligation=None))
    st = status(j)
    assert st['activity'] == J.NOT_STARTED and st['quality'] == st['review'] == J.BLOCKED
    assert st['disclosure'] == st['regulator'] == st['offsets'] == J.BLOCKED


def test_critical_issues_block_submission():
    j = J.compute(dict(COMPLETE, dq_critical=3, dq_warning=1, wf_status='preparing', disclosure_exported=False,
                       regulator_status='Draft', obligation=None))
    st = status(j)
    assert st['quality'] == J.IN_PROGRESS and missing(j, 'quality') == ['critical', 'warnings']
    assert st['review'] == J.BLOCKED and missing(j, 'review') == ['fix_critical']


def test_warnings_do_not_block():
    j = J.compute(dict(COMPLETE, dq_warning=2, wf_status='preparing', disclosure_exported=False,
                       regulator_status='Draft', obligation=None))
    assert status(j)['quality'] == J.DONE and missing(j, 'quality') == ['warnings']
    assert status(j)['review'] == J.NOT_STARTED and j['next']['key'] == 'review'


def test_review_in_progress_states():
    for wf, code in (('in_review', 'awaiting_review'), ('reviewed', 'awaiting_approval')):
        j = J.compute(dict(COMPLETE, wf_status=wf, disclosure_exported=False, regulator_status='Draft', obligation=None))
        assert status(j)['review'] == J.IN_PROGRESS and missing(j, 'review') == [code]
        assert status(j)['disclosure'] == J.BLOCKED


def test_disclosure_needs_export_after_approval():
    j = J.compute(dict(COMPLETE, disclosure_exported=False, regulator_status='Draft', obligation=None))
    assert status(j)['disclosure'] == J.NOT_STARTED and status(j)['regulator'] == J.NOT_STARTED
    assert j['next']['key'] == 'disclosure'


def test_regulator_progress_and_profile_unknown():
    j = J.compute(dict(COMPLETE, regulator_status='Sent to Verifier', obligation=None))
    assert status(j)['regulator'] == J.IN_PROGRESS
    assert next(s for s in j['steps'] if s['key'] == 'regulator')['missing'] == [('regulator_status', 'Sent to Verifier')]
    j = J.compute(dict(COMPLETE, regulator_applies=None, offsets_apply=None, regulator_status='Draft', obligation=None))
    assert missing(j, 'regulator') == ['start_submission', 'profile_unknown']
    assert status(j)['offsets'] == J.BLOCKED


def test_not_applicable_when_no_regulation():
    j = J.compute(dict(COMPLETE, regulator_applies=False, offsets_apply=False, regulator_status='Draft', obligation=None))
    st = status(j)
    assert st['regulator'] == st['offsets'] == J.NA
    assert j['applicable'] == 7 and j['done'] == 7 and j['next'] is None


def test_offsets_only_where_required():
    j = J.compute(dict(COMPLETE, offsets_apply=False, obligation=None))
    assert status(j)['regulator'] == J.DONE and status(j)['offsets'] == J.NA


def test_offset_obligation_states():
    j = J.compute(dict(COMPLETE, obligation={'status': 'OPEN', 'required': 40, 'purchased': 15.5}))
    off = next(s for s in j['steps'] if s['key'] == 'offsets')
    assert off['status'] == J.IN_PROGRESS and off['missing'] == [('offset_remaining', 24.5)]
    j = J.compute(dict(COMPLETE, obligation={'status': 'OVERDUE', 'required': 40, 'purchased': 0}))
    assert next(s for s in j['steps'] if s['key'] == 'offsets')['missing'] == [('offset_overdue', 40.0)]
    j = J.compute(dict(COMPLETE, obligation=None))
    assert status(j)['offsets'] == J.BLOCKED and missing(j, 'offsets') == ['needs_submission']


def test_boundary_split():
    rows = [{'scope': 'scope1'}, {'scope': 'scope3'}, {'scope': 'scope2'}]
    inside, outside = J.boundary_split(rows, ['scope1', 'scope2'])
    assert [r['scope'] for r in inside] == ['scope1', 'scope2'] and outside == [{'scope': 'scope3'}]


# ------------------------------------------------------------------ Carbon → ESG links
def test_detect_metric_from_reference_and_title():
    assert L.detect('GRI 305-1', 'Direct GHG emissions') == 'scope1'
    assert L.detect('GRI 305-2') == 'scope2'
    assert L.detect('', 'Other indirect (Scope 3) GHG emissions') == 'scope3'
    assert L.detect('GRI 305-4', 'GHG emissions intensity') == 'intensity_employee'
    assert L.detect('S2-29a', 'Greenhouse gas emissions') == 'total'
    assert L.detect('', 'انبعاثات النطاق 2') == 'scope2'
    assert L.detect('GRI 405-1', 'Diversity of governance bodies') is None


VALUES = {'enabled': ['scope1', 'scope2'], 'values': {'total': 120.0, 'scope1': 20.0, 'scope2': 100.0, 'scope3': 0.0,
                                                    'intensity_employee': 1.2}}


def test_feed_respects_configuration_and_boundary():
    assert L.feed({'ref_code': 'GRI 305-1'}, VALUES, 'ref_code')['value'] == 20.0
    assert L.feed({'ref_code': 'GRI 305-1', 'carbon_metric': 'none'}, VALUES, 'ref_code') is None
    f = L.feed({'ref_code': 'GRI 405-1', 'carbon_metric': 'total'}, VALUES, 'ref_code')
    assert f['value'] == 120.0 and f['configured']
    f = L.feed({'ref_code': 'GRI 305-3'}, VALUES, 'ref_code')
    assert f['in_boundary'] is False and f['value'] is None
    assert L.feed({'ref_code': 'GRI 305-1'}, None, 'ref_code') is None
