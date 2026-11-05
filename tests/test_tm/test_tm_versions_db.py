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
"""Four eyes on every path that puts a TM rule version in force (review finding B1,
should-fix 1/2/6). Runs against a DEMO database only (TM_TEST_DSN, e.g.
"dbname=complynex_demo"), inside one transaction that is always rolled back; the
Phase 8 migration is applied inside it. Skipped otherwise."""
import os
import re

import pytest

DSN = os.environ.get('TM_TEST_DSN', '')
pytestmark = pytest.mark.skipif('demo' not in DSN, reason='set TM_TEST_DSN to a *demo* database')

MIG = os.path.join(os.path.dirname(__file__), '..', '..', 'database', 'migrations', '20261105_p8tm_rule_status.sql')


class Conn:
    """get_db()-like wrapper: commit() is a no-op so the test transaction is rolled back."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        cur = self.raw.cursor()
        cur.execute(sql, args)
        return cur

    def commit(self):
        pass

    def rollback(self):
        raise AssertionError('tm_versions must not roll back the caller transaction')


@pytest.fixture
def db():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    raw = psycopg2.connect(DSN, cursor_factory=RealDictCursor)
    raw.autocommit = False
    c = Conn(raw)
    sql = open(MIG).read()
    sql = re.sub(r'^\s*(BEGIN|COMMIT);\s*$', '', sql, flags=re.M)
    sql = re.sub(r'^\s*GRANT .*$', '', sql, flags=re.M)
    c.execute(sql)
    u = [r['id'] for r in c.execute("SELECT id FROM users ORDER BY id LIMIT 2").fetchall()]
    assert len(u) == 2
    c.users = u
    try:
        yield c
    finally:
        raw.rollback()
        raw.close()


def _new_rule(db, V, code, user):
    rid = V.propose(db, None, {'rule_name': 'Test rule', 'threshold_value': 100, 'threshold_currency': 'EGP',
                                'severity': 'LOW', 'rule_type': 'THRESHOLD', 'rule_category': 'General'},
                    {}, 'test rule for four eyes', user, code=code)
    return rid


def test_migration_normalises_status_and_marks_legacy(db):
    assert db.execute("SELECT COUNT(*) AS n FROM tm_rules WHERE status IS NULL").fetchone()['n'] == 0
    legacy = db.execute("SELECT COUNT(*) AS n FROM tm_rules WHERE legacy_baseline").fetchone()['n']
    active = db.execute("SELECT COUNT(*) AS n FROM tm_rules WHERE is_active = 1 AND approved_at IS NULL "
                        "AND previous_id IS NULL").fetchone()['n']
    assert legacy == active


def test_rollback_to_a_rejected_or_unapproved_version_is_refused(db):
    from aml import tm_versions as V
    a, b = db.users
    v1 = _new_rule(db, V, 'ZZT01', a)
    V.approve(db, v1, b)
    v2 = V.propose(db, v1, {'threshold_value': 200}, {}, 'raise the threshold', a)
    V.reject(db, v2, b, 'not justified by data')
    # an edit opened from the REJECTED row still replaces the version in force
    v3 = V.propose(db, v2, {'threshold_value': 300}, {}, 'second attempt at it', a)
    assert db.execute("SELECT previous_id FROM tm_rules WHERE id=%s", (v3,)).fetchone()['previous_id'] == v1
    V.approve(db, v3, b)
    prev = V.rollback(db, v3, b, 'back to the approved one')
    assert prev['id'] == v1
    assert V.in_force(db, 'ZZT01')['id'] == v1
    # forge a previous_id that points at the rejected row: rollback refuses
    db.execute("UPDATE tm_rules SET status='ACTIVE', is_active=1, previous_id=%s WHERE id=%s", (v2, v3))
    db.execute("UPDATE tm_rules SET status='DISABLED', is_active=0 WHERE id=%s", (v1,))
    with pytest.raises(V.VersionError):
        V.rollback(db, v3, b, 'try to activate the rejected one')


def test_enable_requires_approval_and_retires_other_versions(db):
    from aml import tm_versions as V
    a, b = db.users
    v1 = _new_rule(db, V, 'ZZT02', a)
    db.execute("UPDATE tm_rules SET status='DISABLED' WHERE id=%s", (v1,))     # never approved
    with pytest.raises(V.VersionError):
        V.enable(db, v1, b, 'enable without approval')
    db.execute("UPDATE tm_rules SET status='PENDING' WHERE id=%s", (v1,))
    V.approve(db, v1, b)
    v2 = V.propose(db, v1, {'threshold_value': 500}, {}, 'tighten the rule', a)
    V.approve(db, v2, b)
    V.enable(db, v1, a, 'go back to version one')              # approved once: allowed, v2 retired
    rows = db.execute("SELECT id, status, is_active FROM tm_rules WHERE rule_code='ZZT02' ORDER BY id").fetchall()
    assert [(r['status'], r['is_active']) for r in rows] == [('ACTIVE', 1), ('DISABLED', 0)]


def test_approval_needs_a_recorded_proposer_and_another_person(db):
    from aml import tm_versions as V
    a, b = db.users
    v1 = _new_rule(db, V, 'ZZT03', a)
    with pytest.raises(V.VersionError):
        V.approve(db, v1, a)                                   # same person
    db.execute("UPDATE tm_rules SET created_by = NULL WHERE id=%s", (v1,))
    with pytest.raises(V.VersionError):
        V.approve(db, v1, b)                                   # nobody recorded


def test_editing_a_pack_rule_keeps_its_parameters(db):
    from aml import tm_engine as E
    from aml import tm_versions as V
    a, b = db.users
    E.ensure_packs_loaded()
    if db.execute("SELECT 1 FROM tm_rules WHERE rule_code='PSP02'").fetchone():
        pytest.skip('PSP02 already exists in this database')
    rid = V.propose(db, None, {'rule_name': 'Pass-through', 'threshold_value': 20000, 'threshold_currency': 'EGP',
                               'severity': 'HIGH'}, {'hours': '48', 'out_pct': '75'}, 'pack rule for the test', a,
                    code='PSP02')
    V.reject(db, rid, b, 'test: reject then edit')
    v2 = V.propose(db, rid, {'threshold_value': 25000}, {'out_pct': ''}, 'only the threshold changes', a)
    p = db.execute("SELECT parameters FROM tm_rules WHERE id=%s", (v2,)).fetchone()['parameters']
    assert p == {'hours': 48.0, 'out_pct': 75.0}


def test_rollback_to_a_rule_in_force_before_is_allowed(db):
    from aml import tm_versions as V
    a, b = db.users
    legacy = db.execute("SELECT * FROM tm_rules WHERE is_active = 1 AND (legacy_baseline OR approved_at IS NOT NULL) "
                        "ORDER BY legacy_baseline DESC LIMIT 1").fetchone()
    if not legacy:
        pytest.skip('no rule in force in this database')
    v2 = V.propose(db, legacy['id'], {}, {}, 'new version of a legacy rule', a)
    V.approve(db, v2, b)
    assert V.rollback(db, v2, b, 'back to the legacy version')['id'] == legacy['id']
