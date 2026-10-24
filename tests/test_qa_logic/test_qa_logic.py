"""DB-free checks for the QA logic fixes: training video length, whitelist
revoke, merchant resubmission, policy maker-checker, displayed risk score,
minutes attendance, KYB sanctions summary, MP4 length reader."""
import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from training import watch as W  # noqa: E402
from training.media import mp4_duration_seconds  # noqa: E402
from merchant_kyc import workflow as MW  # noqa: E402
from policies import review_rules as RR  # noqa: E402
from aml import edd_logic as EL  # noqa: E402
from governance import meeting_logic as GL  # noqa: E402
from kyb import logic as KL  # noqa: E402


def _read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as f:
        return f.read()


# ----------------------------------------------------------------- training
def test_video_length_never_from_browser():
    # signature has no "reported" length any more: only server-known values
    assert W.video_length(None, 15) == 900
    assert W.video_length(300, 15) == 300
    assert W.video_length(None, None) is None
    # a forged 1-second length cannot be passed in
    assert W.video_length(None, 15) != 1


def test_heartbeat_does_not_store_client_length():
    src = _read('models/training.py')
    assert 'reported_duration' not in src
    assert 'GREATEST(COALESCE(video_duration_seconds' not in src
    assert "data.get('duration')" not in _read('training/routes.py')


def _mp4(seconds, timescale=1000):
    mvhd = b'\x00\x00\x00\x00' + struct.pack('>II', 0, 0) + struct.pack('>II', timescale, seconds * timescale) + b'\x00' * 80
    mvhd_box = struct.pack('>I4s', 8 + len(mvhd), b'mvhd') + mvhd
    moov = struct.pack('>I4s', 8 + len(mvhd_box), b'moov') + mvhd_box
    ftyp = struct.pack('>I4s', 16, b'ftyp') + b'isom\x00\x00\x02\x00'
    return ftyp + moov


def test_mp4_duration_reader():
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        f.write(_mp4(125))
        p = f.name
    try:
        assert mp4_duration_seconds(p) == 125
    finally:
        os.unlink(p)
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        f.write(b'not a video at all')
        p = f.name
    try:
        assert mp4_duration_seconds(p) is None
    finally:
        os.unlink(p)
    assert mp4_duration_seconds('/nonexistent/file.mp4') is None


# ----------------------------------------------------------------- whitelist
def test_whitelist_has_no_hard_delete():
    src = _read('screening/routes.py')
    assert 'DELETE FROM screening_whitelist WHERE' not in src
    assert 'CL.can_approve(current_user)' in src.split('def revoke_whitelist')[1].split('def reinstate_whitelist')[0]
    tpl = _read('templates/screening/whitelist.html')
    assert 'value="delete"' not in tpl


# ----------------------------------------------------------------- merchant
def test_rejected_merchant_can_be_resubmitted_with_note():
    assert MW.submit_error('PENDING') is None
    assert MW.submit_error('REJECTED', '') is not None
    assert MW.submit_error('REJECTED', 'Corrected the CR extract and owner IDs') is None
    assert MW.submit_error('APPROVED', 'anything at all here') is not None
    assert MW.submit_error('SUBMITTED') is not None
    # four-eyes still applies to the resubmitter
    assert MW.four_eyes_error(5, created_by=1, submitted_by=5) is not None


# ----------------------------------------------------------------- policies
def test_policy_review_maker_checker_and_decisions():
    assert RR.author_error(3, 3) is not None
    assert RR.author_error(3, 4) is None
    assert RR.reviewer_assignment_error(3, 3) is not None
    assert RR.reviewer_assignment_error(None, 3) is not None
    assert RR.reviewer_assignment_error(4, 3) is None
    assert RR.review_error(4, 3, 'approved', '', True) is None
    assert RR.review_error(4, 3, 'published', '', True) == 'Invalid decision.'
    assert RR.review_error(4, 3, 'rejected', '  ', True) is not None
    assert RR.review_error(3, 3, 'approved', 'ok', True) is not None
    assert RR.review_error(4, 3, 'approved', 'ok', False) is not None


# ----------------------------------------------------------------- risk score
def test_effective_score_matches_rating():
    assert EL.effective_score(0, 'HIGH') == (70, 0, 70)
    assert EL.effective_score(85, 'HIGH') == (85, 85, None)
    assert EL.effective_score(10, 'MEDIUM') == (30, 10, 30)
    assert EL.effective_score(10, 'LOW') == (10, 10, None)
    assert EL.effective_score(None, None) == (0, 0, None)


# ----------------------------------------------------------------- governance
def test_minutes_need_recorded_attendance():
    kw = dict(actor_id=1, drafted_by=3, capacity='chair')
    assert GL.minutes_transition_error('approve', 'circulated', present_count=0, **kw) is not None
    assert GL.minutes_transition_error('approve', 'circulated', present_count=2, **kw) is None
    assert GL.minutes_transition_error('approve', 'circulated', **kw) is None   # legacy callers


def test_new_meeting_cannot_be_created_completed():
    tpl = _read('templates/governance/meeting_form.html')
    assert '{% if meeting %}' in tpl.split('name="status"')[0][-400:]


# ----------------------------------------------------------------- KYB
def test_sanctions_summary_includes_owners():
    people = [{'screening_state': KL.CLEAR}, {'screening_state': KL.NOT_SCREENED}]
    s = KL.sanctions_summary(True, people)
    assert not s['complete'] and s['people_screened'] == 1 and s['people_total'] == 2
    assert KL.sanctions_summary(True, [{'screening_state': KL.CLEAR}])['complete']
    assert not KL.sanctions_summary(False, [])['complete']
    assert not KL.sanctions_summary(True, [])['complete']      # no owner declared yet
    assert KL.sanctions_summary(True, [{'screening_state': KL.OPEN}])['people_open'] == 1


def test_kyb_prefills_cr_from_customer_identity():
    from kyb import service as S
    pre = S.SUBJECTS['aml_customer']['prefill']
    assert pre({'id_type': 'COMMERCIAL_REG', 'id_number': '12345'}) == {'cr_number': '12345'}
    assert pre({'id_type': 'NATIONAL_ID', 'id_number': '2990'}) == {}


def test_engine_connection_is_per_thread():
    # importing the engine needs the application config; check the source
    src = _read('screening/complynex_engine.py')
    cls = src.split('class ComplyNexScreeningEngine')[1][:2500]
    assert 'threading.local()' in cls and '@db_conn.setter' in cls
    kyb = _read('kyb/service.py')
    assert '_release_engine_connection()' in kyb
