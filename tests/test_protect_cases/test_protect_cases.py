"""DB-free checks: case-registry status mapping, complaint handling report, whistleblowing
messaging confidentiality and data-protection record validation."""
import os
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from models.case import Case, normalize_priority, CASE_STATUSES  # noqa: E402
from consumer_protection import handling as H  # noqa: E402
from data_protection import records as R  # noqa: E402
from whistleblowing import messaging as M  # noqa: E402


# ---- case registry ---------------------------------------------------------

def test_every_mapped_status_is_a_unified_status():
    for case_type, mapping in Case.STATUS_MAP.items():
        for src, dst in mapping.items():
            assert dst in CASE_STATUSES, (case_type, src, dst)


def test_status_mapping_per_source():
    m = Case.map_status
    assert m('WHISTLEBLOWING', 'SUBMITTED') == 'OPEN'
    assert m('WHISTLEBLOWING', 'INVESTIGATING') == 'IN_PROGRESS'
    assert m('WHISTLEBLOWING', 'RESOLVED') == 'RESOLVED'
    assert m('WHISTLEBLOWING', 'DISMISSED') == 'CLOSED'          # was falling through to OPEN
    assert m('CONSUMER_COMPLAINT', 'ESCALATED') == 'IN_PROGRESS'  # was falling through to OPEN
    assert m('CONSUMER_COMPLAINT', 'CLOSED') == 'CLOSED'
    assert m('CYBER_INCIDENT', 'CONTAINED') == 'IN_PROGRESS'
    assert m('DSR', 'NEW') == 'OPEN'
    assert m('DSR', 'COMPLETED') == 'RESOLVED'
    assert m('DSR', 'REJECTED') == 'CLOSED'
    assert m('DATA_BREACH', 'REMEDIATING') == 'IN_PROGRESS'
    assert m('DATA_BREACH', 'CLOSED') == 'CLOSED'
    assert m('TM_ALERT', 'SAR_CREATED') == 'CLOSED'
    assert m('REG_CONTROL', 'acknowledged') == 'IN_PROGRESS'


def test_status_mapping_is_case_insensitive_and_defaults_open():
    assert Case.map_status('CYBER_INCIDENT', 'resolved') == 'RESOLVED'
    assert Case.map_status('REG_CONTROL', 'RESOLVED') == 'RESOLVED'
    assert Case.map_status('DSR', 'something-new') == 'OPEN'
    assert Case.map_status('DSR', None) == 'OPEN'


def test_every_case_type_has_a_source_and_sync_handler():
    for case_type in Case.SOURCES:
        assert case_type in Case.STATUS_MAP
        assert hasattr(Case, f'_sync_{case_type.lower()}')


def test_priority_normalisation():
    assert normalize_priority('NORMAL') == 'MEDIUM'
    assert normalize_priority('urgent') == 'HIGH'
    assert normalize_priority(None, 'critical') == 'CRITICAL'
    assert normalize_priority('weird') is None


# ---- complaints --------------------------------------------------------------

def test_resolution_details_validation():
    today = date(2026, 11, 10)
    assert H.validate_resolution_details('BAD', 'NONE', None, None, today)[0] == 'root_cause'
    assert H.validate_resolution_details('STAFF_ERROR', 'REFUND', '', '2026-11-01', today)[0] == 'amount_required'
    assert H.validate_resolution_details('STAFF_ERROR', 'REFUND', '-5', '2026-11-01', today)[0] == 'amount'
    assert H.validate_resolution_details('STAFF_ERROR', 'APOLOGY', None, None, today)[0] == 'date_required'
    assert H.validate_resolution_details('STAFF_ERROR', 'REFUND', '10', '2026-12-01', today)[0] == 'date_future'
    err, clean = H.validate_resolution_details('STAFF_ERROR', 'REFUND', '1,250.5', '2026-11-01', today)
    assert err is None and clean['redress_amount'] == 1250.5
    err, clean = H.validate_resolution_details('NO_FAULT', 'NONE', '99', '2026-11-01', today)
    assert err is None and clean['redress_amount'] is None and clean['redress_date'] is None


def test_periodic_summary_counts_and_overdue():
    today = date(2026, 11, 20)
    rows = [
        {'id': 1, 'complaint_category': 'FEES', 'status': 'RESOLVED', 'complaint_channel': 'BRANCH',
         'created_at': '2026-11-01 10:00:00', 'resolved_at': datetime(2026, 11, 5, 10), 'statutory_deadline_date': '2026-11-16'},
        {'id': 2, 'complaint_category': 'FEES', 'status': 'NEW', 'complaint_channel': 'EMAIL',
         'created_at': '2026-11-02 10:00:00', 'statutory_deadline_date': '2026-11-17'},
        {'id': 3, 'complaint_category': 'FRAUD', 'status': 'CLOSED', 'complaint_channel': 'BRANCH',
         'created_at': '2026-11-01 10:00:00', 'updated_at': '2026-11-19 10:00:00', 'statutory_deadline_date': '2026-11-16',
         'redress_amount': 100},
    ]
    r = H.summarize(rows, today)
    assert r['total'] == 3 and r['resolved'] == 2 and r['open'] == 1
    assert r['by_category'] == {'FEES': 2, 'FRAUD': 1}
    assert r['by_channel']['BRANCH'] == 2
    assert r['overdue_open'] == 1 and r['resolved_late'] == 1 and r['overdue'] == 2
    assert r['avg_resolution_days'] == 11.0   # (4 + 18) / 2
    assert r['redress_total'] == 100


def test_period_bounds():
    t = date(2026, 11, 10)
    assert H.period_bounds('month', today=t) == (date(2026, 11, 1), date(2026, 11, 30))
    assert H.period_bounds('last_month', today=t) == (date(2026, 10, 1), date(2026, 10, 31))
    assert H.period_bounds('quarter', today=t) == (date(2026, 10, 1), date(2026, 12, 31))
    assert H.period_bounds('last_quarter', today=t) == (date(2026, 7, 1), date(2026, 9, 30))
    assert H.period_bounds('custom', '2026-01-05', '2026-02-01', today=t) == (date(2026, 1, 5), date(2026, 2, 1))
    assert H.period_bounds('custom', '2026-03-01', '2026-02-01', today=t) == (date(2026, 11, 1), date(2026, 11, 30))


# ---- whistleblowing messaging ---------------------------------------------------

def test_public_thread_never_carries_staff_identity():
    msgs = [{'sender': 'STAFF', 'body': 'Please share dates', 'created_at': datetime.now(),
             'staff_user_id': 7, 'staff_name': 'Investigator Name', 'read_by_staff': 3}]
    pub = M.to_public(msgs)
    assert pub == [{'sender': 'STAFF', 'body': 'Please share dates', 'created_at': msgs[0]['created_at']}]


def test_message_cleaning_and_duplicates():
    assert M.clean_body('   ') is None
    assert len(M.clean_body('x' * (M.MAX_MESSAGE + 50))) == M.MAX_MESSAGE
    now = datetime.now()
    last = {'sender': 'REPORTER', 'body': 'hello', 'created_at': now - timedelta(seconds=30)}
    assert M.is_duplicate(last, 'REPORTER', 'hello', now)
    assert not M.is_duplicate(last, 'STAFF', 'hello', now)
    assert not M.is_duplicate(dict(last, created_at=now - timedelta(minutes=5)), 'REPORTER', 'hello', now)


# ---- data protection ------------------------------------------------------------

def test_dsr_intake_validation():
    t = date(2026, 11, 10)
    base = {'subject_name': 'A B', 'request_type': 'access', 'email': 'a@b.example', 'channel': 'EMAIL',
            'received_date': '2026-11-09', 'verification_method': 'ID_CARD'}
    err, d = R.validate_dsr_intake(base, t)
    assert err is None and d['request_type'] == 'ACCESS' and d['received_date'] == date(2026, 11, 9)
    assert R.validate_dsr_intake(dict(base, email='', phone=''), t)[0] == 'contact'
    assert R.validate_dsr_intake(dict(base, channel='FAX'), t)[0] == 'channel'
    assert R.validate_dsr_intake(dict(base, received_date='2026-12-01'), t)[0] == 'received_future'
    assert R.validate_dsr_intake(dict(base, verification_method='GUESS'), t)[0] == 'method'


def test_ropa_cross_border_needs_safeguards_and_changes_are_listed():
    bases = ('CONSENT', 'CONTRACT')
    f = {'activity_name': 'Payroll', 'processing_purpose': 'Pay staff', 'legal_basis': 'CONTRACT',
         'retention_period': '5 years', 'international_transfer': '1', 'transfer_countries': 'X'}
    assert R.validate_ropa(f, bases)[0] == 'transfer_safeguards'
    err, data = R.validate_ropa(dict(f, transfer_safeguards='Contract clauses', dpo_review_date='2026-11-01'), bases)
    assert err is None and data['international_transfer'] == 1 and data['dpo_review_date'] == '2026-11-01'
    changes = R.ropa_changes({'activity_name': 'Payroll', 'retention_period': '3 years'}, data)
    assert any(c.startswith('retention_period: 3 years -> 5 years') for c in changes)


def test_consent_and_withdrawal_validation():
    t = date(2026, 11, 10)
    f = {'subject': 'Cust 1', 'purpose_id': '3', 'channel': 'PAPER_FORM', 'consent_date': '2026-11-01', 'evidence': 'Form 12'}
    assert R.validate_consent(f, {3}, t)[0] is None
    assert R.validate_consent(dict(f, evidence=''), {3}, t)[0] == 'evidence'
    assert R.validate_consent(f, {4}, t)[0] == 'purpose'
    assert R.validate_withdrawal({'withdrawal_date': '2026-10-01', 'reason': 'x'}, '2026-11-01', t)[0] == 'before_consent'
    assert R.validate_withdrawal({'withdrawal_date': '2026-11-05'}, '2026-11-01', t)[0] == 'reason'


def test_breach_notification_record_validation():
    t = date(2026, 11, 10)
    assert R.validate_breach_notification({'regulator_date': '2026-11-03'}, '2026-11-02', t)[0] == 'reference'
    assert R.validate_breach_notification({'regulator_reference': 'R-1'}, '2026-11-02', t)[0] == 'regulator_date'
    assert R.validate_breach_notification({'regulator_date': '2026-11-01', 'regulator_reference': 'R'}, '2026-11-02', t)[0] == 'before_discovery'
    assert R.validate_breach_notification({'subjects_date': '2026-11-04'}, '2026-11-02', t)[0] == 'method'
    err, n = R.validate_breach_notification({'regulator_date': '2026-11-03', 'regulator_reference': 'R-1',
                                             'subjects_date': '2026-11-04', 'subjects_method': 'email',
                                             'subjects_count': '120'}, '2026-11-02', t)
    assert err is None and n['pdpc_notified'] == 1 and n['individuals_notification_method'] == 'EMAIL'
    assert n['individuals_notification_count'] == 120
