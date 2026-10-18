"""The FRA NBFI pack content must cover the control map and be consistent
with the generic core (vocabularies, check keys, parameters)."""
import os
import re

from packs.fra_nbfi import library as L
from regcontrols import vocab

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE_OWNER_ROLES = {'compliance_head', 'risk_head', 'cfo', 'it_head', 'ciso', 'internal_audit_head',
                    'operations_head', 'hr_head', 'board_secretary'}
CORE_PARAMS = {'rc.escalation_days', 'rc.evidence_expiry_warning_days', 'rc.finding_overdue_grace_days',
               'rc.alert_renotify_days', 'rc.auto_case_on_failure'}


def test_every_control_map_id_is_in_the_pack():
    with open(os.path.join(ROOT, 'docs', 'regulatory', 'FRA_NBFI_CONTROL_MAP.md'), encoding='utf-8') as fh:
        text = fh.read()
    ids = set()
    for a, b in re.findall(r'\| (FRA-\d{3})(?:–(\d{3}))? \|', text):
        start = int(a[4:])
        for n in range(start, int(b) + 1 if b else start + 1):
            ids.add(f'FRA-{n:03d}')
    ids.update(re.findall(r'\| (OBS-\d{2}) \|', text))
    seeded = {c['code'] for c in L.CONTROLS}
    assert ids - seeded == set()
    assert len(ids) == 80 and len(seeded) == 80


def test_controls_use_core_or_pack_vocabulary():
    codes = [c['code'] for c in L.CONTROLS]
    assert len(codes) == len(set(codes))
    for c in L.CONTROLS:
        assert c['area'] in L.AREAS
        assert c['control_type'] in vocab.CONTROL_TYPES
        assert c['frequency'] in vocab.FREQUENCIES
        assert c['criticality'] in vocab.CRITICALITY
        assert c['owner_role'] in CORE_OWNER_ROLES | set(L.OWNER_ROLES)
        assert c['title_ar'] and c['title_en']
        assert set(c['licence_types']) <= set(L.LICENCE_TYPES) | {'all'}


def test_linked_parameters_exist():
    keys = {p['key'] for p in L.PARAMETERS} | CORE_PARAMS
    assert {k for c in L.CONTROLS for k in c['linked_params'] if k not in keys} == set()


def test_parameters_are_well_formed():
    from regcontrols.logic import validate_value
    seen = set()
    for p in L.PARAMETERS:
        assert not p['key'].startswith('rc.'), 'engine parameters belong to the core'
        assert (p['key'], p['licence_type']) not in seen
        seen.add((p['key'], p['licence_type']))
        assert p['licence_type'] in set(L.LICENCE_TYPES) | {'all'}
        assert validate_value(p['value'], p['value_type']) is None
        if p['value'] is None:
            assert p['needs_review'], f"{p['key']} has no value and must be flagged for review"
        if p['needs_review']:
            assert 'TODO(compliance-review)' in (p['review_note'] or '')


def test_check_keys_resolve():
    from regcontrols import engine
    engine.load_checks(force=True)
    import regcontrols.builtin_checks  # noqa: F401 — core checks are always available
    pack_modules = []
    from packs.fra_nbfi import PACK
    import importlib
    for m in PACK.check_modules:
        pack_modules.append(importlib.import_module(m))
    bound = {c['check_key'] for c in L.CONTROLS if c.get('check_key')}
    assert bound, 'the pack binds at least one control to a check'
    assert bound - set(engine.CHECKS) == set()


def test_pack_registers_with_the_core():
    from regcontrols import packs
    packs.discover()
    assert 'fra_nbfi' in packs.PACKS
    p = packs.PACKS['fra_nbfi']
    assert callable(p.install) and p.name_ar


def test_no_real_company_data_in_pack():
    text = open(L.__file__, encoding='utf-8').read().lower()
    for word in ('basata', 'بساطة'):
        assert word not in text
