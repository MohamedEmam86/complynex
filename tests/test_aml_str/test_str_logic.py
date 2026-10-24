"""Unit tests for the one STR register, TM alert helpers and employee reports — pure functions, no database."""
from datetime import date

from aml import employee_reports as empr
from aml import str_register as sr
from aml import tm_alerts as tm

TODAY = date(2026, 11, 10)


class TestDeadline:
    def test_detection_basis(self):
        case = {'discovery_date': '2026-11-01', 'investigation_status': 'UNDER_INVESTIGATION'}
        assert sr.case_deadline(case, 15) == date(2026, 11, 16)
        flag = sr.deadline_flag(case, 15, 'detection', TODAY)
        assert flag == {'deadline': date(2026, 11, 16), 'overdue': False, 'days': 6}

    def test_overdue(self):
        flag = sr.deadline_flag({'discovery_date': '2026-10-01', 'investigation_status': 'NEW'}, 15, 'detection', TODAY)
        assert flag['overdue'] and flag['days'] == 25

    def test_no_days_configured_means_no_flag(self):
        assert sr.deadline_flag({'discovery_date': '2026-10-01'}, None, 'detection', TODAY) is None

    def test_closed_case_has_no_flag(self):
        for st in sr.CLOSED_STATUSES:
            assert sr.deadline_flag({'discovery_date': '2026-10-01', 'investigation_status': st}, 15, 'detection',
                                    TODAY) is None

    def test_decision_basis_starts_at_decision_to_report(self):
        case = {'discovery_date': '2026-10-01', 'investigation_status': 'PENDING_DECISION'}
        assert sr.case_deadline(case, 5, 'decision') is None
        case.update(decision='FILE_SAR', decision_date='2026-11-08', investigation_status='FILE_SAR')
        assert sr.deadline_flag(case, 5, 'decision', TODAY)['days'] == 3

    def test_falls_back_to_report_date(self):
        assert sr.case_deadline({'report_date': '2026-11-01 10:00:00'}, 1) == date(2026, 11, 2)


class TestLabels:
    def test_every_status_and_source_has_arabic(self):
        for pairs in (sr.STATUSES, sr.SOURCES, sr.LINK_TYPES, tm.STATUSES, tm.SEVERITIES, tm.ACTIONS,
                      empr.STATUSES, empr.SUBJECT_TYPES, empr.ACTIONS):
            for code, en, ar in pairs:
                assert en and ar and ar != en, code

    def test_legacy_status_labelled(self):
        assert sr.status_labels(True)['CLOSED'] == 'مغلق'
        assert sr.status_labels(False)['NO_SAR'].startswith('Closed')

    def test_rule_label(self):
        assert tm.rule_label('High Velocity', 'تكرار مرتفع', True) == 'تكرار مرتفع'
        assert tm.rule_label('High Velocity', None, True) == 'High Velocity'
        assert tm.rule_label('High Velocity', 'تكرار مرتفع', False) == 'High Velocity'


class TestAlerts:
    def test_score(self):
        assert tm.alert_score('HIGH') == 80
        assert tm.alert_score('LOW', [None, 35]) == 35
        assert tm.alert_score('unknown') == 0

    def test_triggered_ids(self):
        assert tm.triggered_ids({'triggered_transactions': '[1, "2", "x"]'}) == [1, 2]
        assert tm.triggered_ids({'triggered_transactions': 'not json'}) == []


class TestEmployeeReport:
    GOOD = {'subject_type': 'customer', 'subject_name': 'A. Customer', 'description': 'x' * 30,
            'activity_from': '2026-11-01', 'activity_to': '2026-11-05'}

    def test_valid(self):
        assert empr.validate(self.GOOD, TODAY) == []

    def test_errors(self):
        errs = empr.validate(dict(self.GOOD, subject_type='bank', description='short', activity_from='2026-11-09',
                                  activity_to='2026-11-02'), TODAY)
        assert len(errs) == 3

    def test_future_and_bad_dates(self):
        assert empr.validate(dict(self.GOOD, activity_to='2026-12-01'), TODAY) == ['Dates cannot be in the future.']
        assert empr.validate(dict(self.GOOD, activity_from='01/11/2026'), TODAY) == ['Enter valid dates.']
