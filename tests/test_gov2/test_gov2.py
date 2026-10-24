"""DB-free checks: meeting workflow rules, policy versioning, server-side
training watch time / quiz rules, labels and the general F&P form."""
import json
import os
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from governance import meeting_logic as L  # noqa: E402
from policies import versioning as V  # noqa: E402
from training import watch as W  # noqa: E402


# ------------------------------------------------------------------ minutes
def test_minutes_versions_draft_then_revision():
    assert L.new_minutes_version([]) == ('new', 1, [])
    assert L.new_minutes_version([{'id': 1, 'version_no': 1, 'status': 'draft'}]) == ('update', 1, [])
    mode, n, sup = L.new_minutes_version([{'id': 1, 'version_no': 1, 'status': 'circulated'}])
    assert (mode, n, sup) == ('new', 2, [1])
    # an approved version stays in force until the revision is approved
    assert L.new_minutes_version([{'id': 1, 'version_no': 1, 'status': 'approved'}]) == ('new', 2, [])
    assert L.change_note_required([{'id': 1, 'version_no': 1, 'status': 'approved'}])
    assert not L.change_note_required([])


def test_minutes_approval_rules():
    assert L.minutes_transition_error('approve', 'draft', capacity='chair') is not None
    assert 'chair or as secretary' in L.minutes_transition_error('approve', 'circulated', capacity=None)
    assert 'drafted' in L.minutes_transition_error('approve', 'circulated', actor_id=3, drafted_by=3, capacity='chair')
    assert L.minutes_transition_error('approve', 'circulated', actor_id=1, drafted_by=3, capacity='secretary') is None
    assert L.minutes_transition_error('return', 'circulated', note='') is not None
    assert L.minutes_transition_error('circulate', 'draft') is None
    assert L.minutes_target('approve') == 'approved'


# ------------------------------------------------------------------ resolutions / actions
def test_vote_result_and_dissent():
    assert L.vote_result(4, 1, 1) == 'passed'
    assert L.vote_result(2, 3) == 'rejected'
    assert L.vote_result(0, 0, 5) == 'deferred'
    errs = L.resolution_errors({'decision_text': 'x', 'votes_for': '3', 'votes_against': '1'})
    assert any('dissenting' in e for e in errs)
    assert L.resolution_errors({'decision_text': 'x', 'votes_for': '3', 'votes_against': '1',
                                'dissent_notes': 'Member A: cost'}) == []
    assert L.resolution_errors({'decision_text': '', 'votes_for': 'abc'})
    assert L.next_reference('BM-2026-09', ['BM-2026-09/R01', 'BM-2026-09/D03']) == 'BM-2026-09/R04'


def test_action_overdue_and_updates():
    today = date(2026, 10, 24)
    assert L.is_overdue({'due_date': '2026-10-01', 'status': 'PENDING'}, today)
    assert not L.is_overdue({'due_date': '2026-10-01', 'status': 'COMPLETED'}, today)
    assert not L.is_overdue({'due_date': '2026-11-01', 'status': 'IN_PROGRESS'}, today)
    assert L.action_update_error('PENDING', 'COMPLETED', '') is not None
    assert L.action_update_error('PENDING', 'IN_PROGRESS', '') is None
    assert L.action_update_error('COMPLETED', 'IN_PROGRESS', 'x') is not None
    assert L.action_errors({'action_description': 'a', 'responsible_person': 'Ext', 'due_date': '2026-12-01'}) == []
    assert len(L.action_errors({})) == 3


def test_external_participant_validation():
    assert L.external_errors({'full_name': 'A', 'role': 'Independent member', 'email': 'a@b.example'}) == []
    errs = L.external_errors({'full_name': '', 'role': '', 'email': 'bad'})
    assert len(errs) == 3


# ------------------------------------------------------------------ policy versioning
def test_next_version_numbers():
    assert V.next_version('1.0') == '2.0'
    assert V.next_version('3') == '4'
    assert V.next_version('v2.1') == 'v3.0'
    assert V.next_version(None) == '2.0'


def test_new_version_rules():
    assert V.new_version_error('draft') is not None
    assert V.new_version_error('published', open_draft_id=7, change_summary='x') is not None
    assert V.new_version_error('published', change_summary='') is not None
    assert V.new_version_error('published', change_summary='New thresholds') is None
    assert V.is_locked('archived') and V.is_locked('Published') and not V.is_locked('draft')


# ------------------------------------------------------------------ training
def test_heartbeat_credit_is_server_clock_and_capped():
    now = datetime(2026, 10, 24, 12, 0, 0)
    assert W.credit_seconds(None, now) == 0                       # first heartbeat starts the clock
    assert W.credit_seconds(now - timedelta(seconds=5), now) == 5
    assert W.credit_seconds(now - timedelta(seconds=40), now) == W.HEARTBEAT_MAX_CREDIT
    assert W.credit_seconds(now - timedelta(minutes=10), now) == 0  # stale session
    assert W.credit_seconds(now - timedelta(seconds=5), now, playing=False) == 0


def test_completion_threshold_default_90():
    assert W.threshold_pct(None) == 90
    assert not W.completion_reached(89, 100)
    assert W.completion_reached(90, 100)
    assert W.completion_reached(80, 100, 80)
    assert not W.completion_reached(1000, None)
    assert W.video_length(120.4) == 120
    assert W.video_length(None, 5) == 300
    assert W.video_length(None, None) is None
    assert W.video_length(600, 1) == 600


def test_quiz_attempts_and_language():
    assert W.max_attempts(None) == 3
    assert W.attempts_remaining(None, 3) == 0
    assert W.attempts_remaining(None, 3, extra=1) == 1
    assert W.quiz_language('ar', 'en') == 'ar'
    assert W.quiz_language(None, 'ar') == 'ar'
    q = {'question_text': 'Q', 'question_text_ar': 'س', 'options': ['a', 'b'], 'options_ar': ['أ', 'ب']}
    assert W.localize_question(q, 'ar')['display_text'] == 'س'
    assert W.localize_question(q, 'ar')['display_options'] == ['أ', 'ب']
    only_en = {'question_text': 'Q', 'options': ['a', 'b']}
    assert W.localize_question(only_en, 'ar')['display_text'] == 'Q'      # fallback
    partial = {'question_text': 'Q', 'options': ['a', 'b', 'c'], 'options_ar': ['أ']}
    assert W.localize_question(partial, 'ar')['display_options'] == ['a', 'b', 'c']  # keep index order


# ------------------------------------------------------------------ labels / F&P
def test_labels_humanize_unknown_codes():
    from governance import labels
    assert labels.humanize('SOME_NEW_CODE') == 'Some new code'
    assert 'consumer_finance' in labels.SECTORS and 'microfinance' in labels.SECTORS
    for kind in ('meeting_type', 'meeting_status', 'committee_type', 'policy_status', 'coi_status'):
        assert labels.KINDS[kind]


def test_general_fp_form_has_microfinance_and_is_sector_neutral():
    path = os.path.join(ROOT, 'governance', 'fp', 'forms', 'general_board_fp.json')
    d = json.load(open(path, encoding='utf-8'))
    text = json.dumps(d, ensure_ascii=False)
    assert '"microfinance"' in text
    for word in ('PSP', 'payment institution', 'e-money'):
        assert word not in text


def test_demo_seed_uses_microfinance_licence():
    src = open(os.path.join(ROOT, 'scripts', 'demo_data', 'm_regcontrols.py'), encoding='utf-8').read()
    assert "code = 'microfinance'" in src
    base = open(os.path.join(ROOT, 'scripts', 'demo_data', 'm_base.py'), encoding='utf-8').read()
    assert "licence_type='microfinance'" in base
