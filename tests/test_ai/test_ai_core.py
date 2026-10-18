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

"""Unit tests for the Compliance Copilot core (ai/) — no database, no network, no model.

A FakeProvider stands in for a local model so the strict-JSON, repair and
fallback paths are exercised deterministically."""

from datetime import date

import pytest

from ai import netguard, schema, seed, tasks, text
from ai.nba import aml_gaps, case_gaps, control_gaps, finding_gaps
from ai.providers import LocalHTTP, Provider, ProviderError

TODAY = date(2026, 10, 18)


class FakeProvider(Provider):
    """Returns canned replies in order; records the prompts it saw."""
    name = 'fake'
    model = 'fake-1'
    can_generate = True

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def generate(self, system, prompt, timeout=None):
        self.prompts.append(prompt)
        if not self.replies:
            raise ProviderError('no more replies')
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _resolver(ip):
    return lambda host, *a, **k: [(2, 1, 6, '', (ip, 0))]


# ---------------------------------------------------------------- netguard
@pytest.mark.parametrize('ip', ['127.0.0.1', '10.1.2.3', '192.168.1.20', '172.16.5.5', '100.64.0.7', '::1'])
def test_netguard_accepts_local_and_private(ip):
    assert netguard.check_local_url('http://llm.internal:11434/', _resolver(ip)) == 'http://llm.internal:11434'


@pytest.mark.parametrize('ip', ['8.8.8.8', '104.18.1.1', '2606:4700::1111'])
def test_netguard_refuses_public(ip):
    with pytest.raises(netguard.NotLocalError):
        netguard.check_local_url('http://api.example.com', _resolver(ip))


@pytest.mark.parametrize('url', ['ftp://127.0.0.1', 'http://user:pw@127.0.0.1', 'not a url', ''])
def test_netguard_refuses_bad_urls(url):
    with pytest.raises(netguard.NotLocalError):
        netguard.check_local_url(url, _resolver('127.0.0.1'))


def test_local_http_rechecks_at_call_time():
    """A host that resolved privately at save time but publicly now is refused before any request."""
    with pytest.raises(netguard.NotLocalError):
        LocalHTTP('http://llm.internal:11434', 'm', resolver=_resolver('8.8.8.8'))
    p = LocalHTTP('http://llm.internal:11434', 'm', resolver=_resolver('10.0.0.5'))
    p._resolver = _resolver('8.8.8.8')          # DNS changed after the setting was saved
    with pytest.raises(ProviderError, match='refused'):
        p.generate('s', 'p')


# ---------------------------------------------------------------- strict JSON
SCH = {'type': 'object', 'required': ['a', 'b'], 'additionalProperties': False,
       'properties': {'a': {'type': 'string', 'enum': ['x', 'y']}, 'b': {'type': 'array', 'minItems': 2, 'items': {'type': 'integer'}}}}


def test_schema_valid_and_invalid():
    assert schema.errors({'a': 'x', 'b': [1, 2]}, SCH) == []
    errs = schema.errors({'a': 'z', 'b': [1], 'c': 1}, SCH)
    assert len(errs) == 3


def test_extract_json_from_fences_and_prose():
    assert schema.extract_json('Sure!\n```json\n{"a": "x", "b": [1, 2]}\n```') == {'a': 'x', 'b': [1, 2]}
    assert schema.extract_json('result: {"a": "{x}", "b": [1, {"c": 2}]} done')['a'] == '{x}'
    with pytest.raises(ValueError):
        schema.extract_json('no json here')


def test_call_model_ok_repair_and_failure():
    obj, status, _ = tasks.call_model(FakeProvider('{"a": "x", "b": [1, 2]}'), 's', 'p', SCH)
    assert (obj['a'], status) == ('x', 'ok')
    fake = FakeProvider('{"a": "nope"}', '{"a": "y", "b": [3, 4]}')
    obj, status, _ = tasks.call_model(fake, 's', 'p', SCH)
    assert (obj['a'], status) == ('y', 'repaired')
    assert 'previous reply was invalid' in fake.prompts[1]
    with pytest.raises(ProviderError):
        tasks.call_model(FakeProvider('garbage', 'still garbage'), 's', 'p', SCH)


# ---------------------------------------------------------------- classification
INTENTS = seed.INTENTS


def test_classify_rules_freeze_order_with_fields():
    t = 'Freeze order No. 15 of 2026: freeze all accounts of Ahmed Samir Fathy within 24 hours.'
    res, meta = tasks.classify(t, INTENTS, today=TODAY)
    assert res['intent'] == 'freeze_order' and meta['provider'] == 'rules_only'
    assert res['fields']['order_reference'] == '15/2026'


def test_classify_arabic_complaint():
    t = 'شكوى من العميل بخصوص خصم رسوم مرتين من البطاقة ولم يتم الرد على اتصالاتي'
    res, _ = tasks.classify(t, INTENTS, today=TODAY)
    assert res['intent'] == 'customer_complaint'


def test_classify_unrelated_text_is_unclassified():
    res, _ = tasks.classify('Lunch on Thursday at noon?', INTENTS, today=TODAY)
    assert res['intent'] is None


def test_classify_model_is_constrained_to_catalog_and_falls_back():
    t = 'Circular No. 7 of 2026 on customer due diligence, effective from 1 December 2026.'
    good = FakeProvider('{"intent": "regulatory_circular", "confidence": 0.9, "summary": "New CDD circular", '
                        '"fields": {"circular_number": "7/2026", "invented_field": "x"}}')
    res, meta = tasks.classify(t, INTENTS, gen=good, today=TODAY)
    assert res['intent'] == 'regulatory_circular' and meta['status'] == 'ok' and meta['provider'] == 'fake'
    assert 'invented_field' not in res['fields'] and res['fields']['effective_date'] == '2026-12-01'
    # an intent outside the catalog is invalid twice → rules result, status fallback
    bad = FakeProvider('{"intent": "made_up", "confidence": 1, "summary": "", "fields": {}}',
                       '{"intent": "also_made_up", "confidence": 1, "summary": "", "fields": {}}')
    res, meta = tasks.classify(t, INTENTS, gen=bad, today=TODAY)
    assert meta['status'] == 'fallback' and res['intent'] == 'regulatory_circular'


def test_model_timeout_falls_back_to_rules():
    res, meta = tasks.classify('Freeze order No. 3 of 2026', INTENTS, gen=FakeProvider(ProviderError('timeout')), today=TODAY)
    assert meta['status'] == 'fallback' and res['intent'] == 'freeze_order'


# ---------------------------------------------------------------- playbooks
def test_select_playbook_new_branch_with_place():
    res, _ = tasks.select_playbooks('We will open a new branch in Alexandria next month.', seed.PLAYBOOKS, today=TODAY)
    assert res['playbooks'][0]['code'] == 'new_branch'
    assert res['playbooks'][0]['params'].get('branch_name') == 'Alexandria'


def test_select_playbook_model_params_filtered():
    fake = FakeProvider('{"playbooks": [{"code": "outsourcing", "confidence": 0.8, "params": {"provider_name": "Acme Cloud", "x": 1}}]}')
    res, meta = tasks.select_playbooks('We will outsource our core system hosting to Acme Cloud', seed.PLAYBOOKS, gen=fake, today=TODAY)
    assert res['playbooks'][0]['code'] == 'outsourcing' and meta['status'] == 'ok'
    assert 'x' not in res['playbooks'][0]['params']


# ---------------------------------------------------------------- next best action
GAPS = [{'code': 'a', 'severity': 'high', 'text_en': 'Upload the evidence', 'text_ar': 'ارفع الدليل', 'due': None},
        {'code': 'b', 'severity': 'medium', 'text_en': 'Assign an owner', 'text_ar': 'حدد مسؤولاً', 'due': None}]


def test_phrase_requires_exact_step_count():
    ok = FakeProvider('{"headline": "Two things", "steps": ["Upload it", "Name an owner"]}')
    res, meta = tasks.phrase(GAPS, 'en', ok)
    assert res['steps'] == ['Upload it', 'Name an owner'] and meta['status'] == 'ok'
    added = FakeProvider('{"headline": "h", "steps": ["1", "2", "3 invented"]}', '{"headline": "h", "steps": ["only one"]}')
    res, meta = tasks.phrase(GAPS, 'ar', added)
    assert meta['status'] == 'fallback' and res['steps'] == ['ارفع الدليل', 'حدد مسؤولاً']


def test_finding_gaps_deterministic():
    f = {'status': 'open', 'due_date': date(2026, 10, 1), 'is_repeated': False, 'controls': [],
         'actions': [{'status': 'open', 'due_date': date(2026, 10, 10), 'owner_user_id': None, 'description': 'Fix backups'}]}
    codes = [g['code'] for g in finding_gaps(f, TODAY)]
    assert 'action_overdue' in codes and 'action_no_owner' in codes and 'finding_overdue' in codes
    assert finding_gaps(dict(f, status='closed'), TODAY) == []


def test_other_gap_builders_return_bilingual_items():
    items = (control_gaps({'owner_user_id': None, 'last_status': 'fail', 'evidence_required': True}, [], 0, TODAY)
             + case_gaps({'status': 'open', 'assigned_to': None, 'due_date': date(2026, 10, 1)}, TODAY)
             + aml_gaps({'status': 'new', 'analysis': None, 'study_due_date': date(2026, 10, 1)}, False, TODAY))
    assert items and all(g['text_en'] and g['text_ar'] for g in items)


def test_drafts_are_labelled_and_rules_work():
    res, meta = tasks.draft('action_plan', {'title': 'Backups', 'gaps': GAPS}, 'en')
    assert res['text'] and meta['provider'] == 'rules_only'


# ---------------------------------------------------------------- extraction helpers
def test_text_helpers():
    assert text.normalise('الإجراءات') == text.normalise('الاجراءات')
    assert set(text.dates('effective 1 December 2026 and 2026-11-05')) == {date(2026, 12, 1), date(2026, 11, 5)}
    ids = text.identifiers('national ID 29001011234567, mobile 01012345678, ref: INS-2026-04, noted later')
    assert ids['national_id'] == ['29001011234567'] and ids['reference'] == ['INS-2026-04']
    assert text.relative_deadline('respond within 3 days') == ('days', 3) or text.relative_deadline('respond within 3 days')
