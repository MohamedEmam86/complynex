"""The seed library must stay complete, consistent and in sync with the migration."""
import os
import re
import subprocess
import sys

from regcontrols import library

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_every_control_map_id_is_seeded():
    with open(os.path.join(ROOT, 'docs', 'regulatory', 'FRA_NBFI_CONTROL_MAP.md'), encoding='utf-8') as fh:
        text = fh.read()
    ids = set()
    for a, b in re.findall(r'\| (FRA-\d{3})(?:–(\d{3}))? \|', text):
        start = int(a[4:])
        for n in range(start, int(b) + 1 if b else start + 1):
            ids.add(f'FRA-{n:03d}')
    ids.update(re.findall(r'\| (OBS-\d{2}) \|', text))
    seeded = {c['code'] for c in library.CONTROLS}
    assert ids - seeded == set()
    assert len(ids) == 80 and len(seeded) == 80


def test_controls_are_well_formed():
    codes = [c['code'] for c in library.CONTROLS]
    assert len(codes) == len(set(codes))
    for c in library.CONTROLS:
        assert c['area'] in library.AREAS
        assert c['frequency'] in library.FREQUENCIES
        assert c['criticality'] in library.CRITICALITY
        assert c['owner_role'] in library.OWNER_ROLES
        assert c['title_ar'] and c['title_en']
        assert set(c['licence_types']) <= set(library.LICENCE_TYPES)


def test_linked_parameters_exist():
    keys = {p['key'] for p in library.PARAMETERS}
    missing = {k for c in library.CONTROLS for k in c['linked_params'] if k not in keys}
    assert missing == set()


def test_parameters_are_well_formed():
    from regcontrols.logic import validate_value
    seen = set()
    for p in library.PARAMETERS:
        assert (p['key'], p['licence_type']) not in seen
        seen.add((p['key'], p['licence_type']))
        assert validate_value(p['value'], p['value_type']) is None
        if p['value'] is None:
            assert p['needs_review'], f"{p['key']} has no value and must be flagged for review"
        if p['needs_review']:
            assert 'TODO(compliance-review)' in (p['review_note'] or '')


def test_migration_seed_block_is_current():
    out = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'regcontrols_seed_sql.py'), '--check'],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
