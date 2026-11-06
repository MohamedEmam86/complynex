"""DB-free checks of the board-meeting record rules: quorum (first / second call,
capital), majority types and casting vote, never-reused numbers, proxies,
follow-up / filing / signature alerts, attendance statistics and the board
composition checks."""
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from governance import register_logic as RL  # noqa: E402
from governance import composition as C  # noqa: E402

BOARD = dict(quorum_type='MAJORITY', quorum_fraction=0.5, quorum_min=3, count_proxies=True, count_remote=True,
             majority_rule='SIMPLE_PRESENT', chair_casting_vote=True)


def test_required_count_majority_and_minimum():
    assert RL.required_count(7, 'MAJORITY', 0.5, 3) == 4
    assert RL.required_count(6, 'MAJORITY', 0.5, 3) == 4
    assert RL.required_count(4, 'MAJORITY', 0.5, 3) == 3
    assert RL.required_count(3, 'MAJORITY', 0.5, 3) == 3       # never fewer than 3
    assert RL.required_count(6, 'AT_LEAST', 0.5, None) == 3
    assert RL.required_count(5, 'AT_LEAST', 0.5, 2) == 3


def test_quorum_counts_remote_and_proxy_per_rule():
    q = RL.quorum(BOARD, 7, {'IN_PERSON': 2, 'REMOTE': 1, 'PROXY': 1})
    assert q['valid'] and q['counted'] == 4 and q['required'] == 4
    no_proxy = dict(BOARD, count_proxies=False)
    assert not RL.quorum(no_proxy, 7, {'IN_PERSON': 2, 'REMOTE': 1, 'PROXY': 1})['valid']
    no_remote = dict(BOARD, count_remote=False)
    assert RL.quorum(no_remote, 7, {'IN_PERSON': 3, 'REMOTE': 2})['counted'] == 3
    assert not RL.quorum(BOARD, 7, {'IN_PERSON': 3})['valid']                       # first call fails
    assert not RL.quorum(BOARD, 0, {})['valid']


def test_quorum_second_call_and_capital():
    ogm = dict(quorum_basis='CAPITAL', quorum_type='AT_LEAST', quorum_fraction=0.25, second_call_type='AT_LEAST',
               second_call_fraction=0)
    assert RL.quorum(ogm, 0, {}, 1, 30)['valid']
    assert not RL.quorum(ogm, 0, {}, 1, 20)['valid']
    assert RL.quorum(ogm, 0, {}, 2, 5)['valid']                                     # second meeting: any
    assert RL.quorum(ogm, 0, {}, 1, None)['valid'] is None
    egm = dict(quorum_basis='CAPITAL', quorum_type='AT_LEAST', quorum_fraction=0.5, second_call_type='AT_LEAST',
               second_call_fraction=0.25)
    assert not RL.quorum(egm, 0, {}, 1, 40)['valid'] and RL.quorum(egm, 0, {}, 2, 40)['valid']
    board2 = dict(BOARD, second_call_type='AT_LEAST', second_call_fraction=0.34, second_call_min=3)
    assert RL.quorum(board2, 7, {'IN_PERSON': 3}, 2)['valid']


def test_majority_rules_and_casting_vote():
    v = ['FOR'] * 4 + ['AGAINST'] * 2 + ['ABSTAIN']
    assert RL.majority('SIMPLE_PRESENT', v, eligible=7)[0]
    assert not RL.majority('SIMPLE_PRESENT', ['FOR'] * 3 + ['AGAINST'] * 2 + ['ABSTAIN'] * 2, eligible=7)[0]
    assert RL.majority('SIMPLE_CAST', ['FOR'] * 3 + ['AGAINST'] * 2 + ['ABSTAIN'] * 2)[0]
    tie = ['FOR', 'FOR', 'AGAINST', 'AGAINST']
    assert RL.majority('SIMPLE_CAST', tie, chair_vote='FOR')[0]
    assert not RL.majority('SIMPLE_CAST', tie, chair_vote='FOR', casting=False)[0]
    assert not RL.majority('SIMPLE_CAST', tie, chair_vote='AGAINST')[0]
    assert RL.majority('SIMPLE_PRESENT', tie, chair_vote='FOR')[0]
    # the casting vote breaks a tie between for and against only
    assert not RL.majority('SIMPLE_PRESENT', ['FOR', 'FOR', 'AGAINST', 'ABSTAIN'], chair_vote='FOR')[0]
    assert not RL.majority('SIMPLE_CAST', ['FOR', 'AGAINST', 'AGAINST'], chair_vote='FOR')[0]
    assert RL.majority('TWO_THIRDS', ['FOR'] * 4 + ['AGAINST'] * 2)[0]
    assert not RL.majority('TWO_THIRDS', ['FOR'] * 3 + ['AGAINST'] * 2)[0]
    assert not RL.majority('THREE_QUARTERS', ['FOR'] * 5 + ['AGAINST'] * 2)[0]
    assert RL.majority('UNANIMOUS', ['FOR'] * 5 + ['RECUSED', 'ABSENT'])[0]
    assert not RL.majority('UNANIMOUS', ['FOR'] * 5 + ['ABSTAIN'])[0]
    # recused / absent members are not in the base
    assert RL.majority('SIMPLE_PRESENT', ['FOR'] * 3 + ['AGAINST'] * 2 + ['RECUSED', 'ABSENT'])[1] == 3


def test_outcome_rules():
    assert RL.suggested_outcome(True) == 'APPROVED'
    assert RL.suggested_outcome(False, 'APPROVED') == 'REJECTED'
    assert RL.suggested_outcome(False, 'DEFERRED') == 'DEFERRED'
    assert RL.suggested_outcome(True, 'GA_RATIFICATION') == 'GA_RATIFICATION'
    assert RL.legacy_vote_result('APPROVED') == 'passed' and RL.legacy_vote_result('REJECTED') == 'rejected'
    assert RL.circulation_error('CIRCULATION', ['FOR', 'ABSENT'])
    assert RL.circulation_error('CIRCULATION', ['FOR', 'ABSENT'], {'circulation_requires_all': False}) is None
    assert RL.circulation_error('ORDINARY', ['FOR', 'ABSENT']) is None


def test_resolution_numbers_never_reused():
    assert RL.body_prefix('BOARD') == 'BOD'
    assert RL.body_prefix('COMMITTEE', 'aud') == 'AUD'
    assert RL.body_prefix('COMMITTEE') == 'COM'
    assert RL.body_prefix('BOARD', None, 'nfc') == 'NFC-BOD'
    assert RL.resolution_number('BOD', 2026, 5, 3) == 'BOD-2026-05-03'
    assert RL.resolution_number('BOD', 2026, 5, 3, {'BOD-2026-05-03'}) == 'BOD-2026-05-03A'
    assert RL.resolution_number('BOD', 2026, 5, 3, {'BOD-2026-05-03', 'BOD-2026-05-03A'}) == 'BOD-2026-05-03B'
    assert RL.next_item_no([1, 2, None, 4]) == 5 and RL.next_item_no([]) == 1
    assert RL.next_sequence([None, 2, 3]) == 4


def test_attendance_codes_and_legacy_columns():
    assert RL.attendance_code({'attended': 1}) == 'IN_PERSON'
    assert RL.attendance_code({'attended': 1, 'attended_remotely': 1}) == 'REMOTE'
    assert RL.attendance_code({'attended': 0, 'proxy_name': 'X'}) == 'PROXY'
    assert RL.attendance_code({'attended': 0, 'apology_received': 1, 'attendance_status': 'ABSENT_WITH_APOLOGY'}) == 'ABSENT_EXCUSED'
    assert RL.attendance_code({'attended': 0, 'attendance_status': 'ABSENT'}) == 'ABSENT_UNEXCUSED'
    assert RL.attendance_code({'attended': 0}) is None                                  # invited, not recorded
    for code in RL.ATTENDANCE:
        assert RL.attendance_code(dict(RL.legacy_columns(code), proxy_name='H' if code == 'PROXY' else None,
                                       recorded_at='x')) == code


def test_proxy_rules():
    rows = [dict(member_id=1, code='IN_PERSON', member_name='A'), dict(member_id=2, code='PROXY', proxy_holder_member_id=1, member_name='B'),
            dict(member_id=3, code='PROXY', proxy_holder_member_id=1, member_name='C'),
            dict(member_id=4, code='PROXY', proxy_holder_member_id=5, member_name='D'),
            dict(member_id=5, code='ABSENT_EXCUSED', member_name='E'), dict(member_id=6, code='PROXY', member_name='F')]
    errs = RL.proxy_errors(rows)
    assert ('proxy_one_only', 'A') in errs
    assert ('proxy_holder_absent', 'D') in errs
    assert ('proxy_holder_missing', 'F') in errs
    assert RL.proxy_errors(rows[:2]) == []


def test_followup_filing_signatures():
    today = date(2026, 11, 6)
    assert RL.followup_state({'action_owner': 'CFO', 'due_date': '2026-03-31', 'followup_status': 'IN_PROGRESS'}, today) == 'overdue'
    assert RL.followup_state({'due_date': '2026-03-31', 'followup_status': 'DONE'}, today) == 'closed'
    assert RL.followup_state({'due_date': '2026-12-31'}, today) == 'open'
    assert RL.followup_state({}, today) == 'none'
    assert RL.filing_due('2026-04-21', 10) == date(2026, 5, 1)
    assert RL.filing_due('2026-04-21', None) is None
    m = {'meeting_date': '2026-04-21', 'filing_due_date': date(2026, 5, 1), 'chair_signed_at': 'x', 'minutes_state': 'APPROVED'}
    assert set(RL.meeting_flags(m, today)) == {'filing_overdue', 'signature_overdue'}
    m.update(filed_on=date(2026, 4, 30), secretary_signed_at='y')
    assert RL.meeting_flags(m, today) == []
    assert RL.minutes_state({'chair_signed_at': 1, 'secretary_signed_at': 1}) == 'SIGNED'
    assert RL.minutes_state({'minutes_state': 'SIGNED', 'chair_signed_at': 1}) == 'APPROVED'
    assert RL.minutes_state({}, has_approved_version=True) == 'APPROVED'
    assert RL.meeting_flags({'meeting_date': '2027-01-01'}, today) == []


def test_attendance_stats_and_alerts():
    rules = [{'name_en': 'PSP', 'max_absence_pct': 25}, {'name_en': 'Code', 'max_missed_meetings': 3}]
    rows = [dict(member_id=1, year=2025, code=c) for c in ('IN_PERSON', 'ABSENT_EXCUSED', 'PROXY', 'ABSENT_UNEXCUSED')]
    rows += [dict(member_id=2, year=2025, code=c) for c in ('IN_PERSON', 'REMOTE', 'IN_PERSON', 'ABSENT_EXCUSED')]
    st = RL.attendance_stats(rows, rules)
    a = st[(1, 2025)]
    assert a['rate'] == 25.0 and a['absence_pct'] == 75.0 and a['absent'] == 3
    assert {x['code'] for x in a['alerts']} == {'absence_pct', 'missed_meetings'}
    b = st[(2, 2025)]
    assert b['rate'] == 75.0 and b['remote'] == 1 and b['alerts'] == []          # 25% is not more than 25%


def _m(i, flags, gender=None, since=None):
    return dict(id=i, member_name=f'M{i}', flags=set(flags), gender=gender, independent_since=since)


def test_board_composition_checks():
    rule = dict(name_en='FRA', min_board_size=3, non_exec_majority=True, min_indep_share_of_non_exec=50,
                min_women_share=25, chair_ceo_separate=True, independence_max_years=6, min_board_meetings_per_year=4)
    today = date(2026, 11, 6)
    good = [_m(1, ['chair', 'non_executive', 'independent'], 'M', date(2023, 4, 1)), _m(2, ['md', 'executive'], 'F'),
            _m(3, ['non_executive', 'independent'], 'F', date(2024, 1, 1)), _m(4, ['non_executive'], 'M')]
    f, st = C.check_board(good, [rule], 4, today)
    assert f == [] and st['women'] == 2 and st['independent'] == 2
    bad = [_m(1, ['chair', 'md', 'executive']), _m(2, ['executive'], 'M'), _m(3, ['non_executive', 'independent'], 'M', date(2019, 5, 1))]
    f, st = C.check_board(bad, [rule], 2, today)
    codes = {x['code'] for x in f}
    assert {'non_exec_majority', 'women_share', 'chair_ceo', 'independence_clock', 'board_meetings', 'gender_unknown'} <= codes
    assert C.check_board(bad, [], 0, today)[0] == []                                # no rule set chosen: nothing checked


def test_committee_independence_rules():
    c = dict(min_members=3, independent_majority=1, independent_chair=1, non_executive_chair=1, chairman_id=1)
    mem = [dict(member_id=1, is_independent=0, is_executive=1, status='ACTIVE'), dict(member_id=2, is_independent=1),
           dict(member_id=3, is_independent=0)]
    codes = {f['code'] for f in C.check_committee(c, mem, 4)}
    assert {'independent_majority', 'independent_chair', 'non_executive_chair'} <= codes


def test_quorum_counts_proxy_only_through_a_counted_holder():
    rows = [dict(member_id=1, code='IN_PERSON'), dict(member_id=2, code='PROXY', proxy_holder_member_id=1),
            dict(member_id=3, code='REMOTE'), dict(member_id=4, code='PROXY', proxy_holder_member_id=3),
            dict(member_id=5, code='PROXY', proxy_holder_member_id=6), dict(member_id=6, code='ABSENT_EXCUSED'),
            dict(member_id=7, code='IN_PERSON', voting=False)]
    assert RL.quorum_counts(rows, BOARD) == {'IN_PERSON': 1, 'REMOTE': 1, 'PROXY': 2}
    assert RL.quorum_counts(rows, dict(BOARD, count_remote=False))['PROXY'] == 1   # holder remote, remote not counted


def test_min_personal_and_second_call_minimum_fallback():
    r = dict(BOARD, min_personal=3)
    q = RL.quorum(r, 7, {'IN_PERSON': 2, 'REMOTE': 0, 'PROXY': 2})
    assert q['counted'] == 4 and not q['valid'] and q['personal'] == 2
    assert RL.quorum(r, 7, {'IN_PERSON': 3, 'PROXY': 1})['valid']
    second = dict(BOARD, second_call_type='AT_LEAST', second_call_fraction=0.25)       # no second-call minimum
    assert RL.quorum(second, 7, {'IN_PERSON': 2}, 2)['required'] == 3                # falls back to quorum_min 3
