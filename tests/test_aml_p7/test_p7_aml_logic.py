"""Phase 7 AML (F1, F2, F4, F5, F6): pure logic, no database."""
import copy
from datetime import date, datetime, timedelta
from decimal import Decimal

from aml import freeze_log as FL
from aml import periodic_review as PR
from aml import str_draft as SD
from kyb import logic as K
from utils import aml_risk as R


# --------------------------------------------------------------------------- F1 risk model
class TestRiskModel:
    def test_default_is_valid_and_unchanged(self):
        assert R.validate(R.DEFAULT_MODEL) == []
        r = R.calculate_risk_score({'country': 'Iran', 'customer_type': 'CORPORATE', 'business_activity': 'Real estate',
                                    'annual_income_range': '>500K'}, model=R.DEFAULT_MODEL)
        assert r['score'] == 100 and r['classification'] == 'HIGH'
        assert R.calculate_risk_score({'country': 'EGYPT'}, model=R.DEFAULT_MODEL)['classification'] == 'LOW'
        assert R.calculate_risk_score({'country': 'FRANCE', 'business_activity': 'charity work'},
                                      model=R.DEFAULT_MODEL)['score'] == 40

    def test_table_source_uses_high_risk_rows(self):
        m = copy.deepcopy(R.DEFAULT_MODEL)
        m['country']['source'] = 'table'
        rows = [{'country_code': 'YE', 'country_name': 'Yemen', 'name_ar': 'اليمن', 'aliases': '', 'is_active': 1}]
        assert R.calculate_risk_score({'country': 'Yemen'}, model=m, high_risk_rows=rows)['score'] == 50
        # the built-in list no longer counts when the source is the table only
        assert R.calculate_risk_score({'country': 'Iran'}, model=m, high_risk_rows=rows)['score'] == 10
        m['country']['source'] = 'both'
        assert R.calculate_risk_score({'country': 'Iran'}, model=m, high_risk_rows=rows)['score'] == 50

    def test_bands_and_points_are_data(self):
        m = copy.deepcopy(R.DEFAULT_MODEL)
        m['bands'] = {'HIGH': 40, 'MEDIUM': 20}
        m['activity']['points'] = 25
        r = R.calculate_risk_score({'country': 'EGYPT', 'occupation': 'gambling hall'}, model=m)
        assert r['score'] == 25 and r['classification'] == 'MEDIUM'

    def test_validate_rejects_bad_models(self):
        m = copy.deepcopy(R.DEFAULT_MODEL)
        m['bands'] = {'HIGH': 20, 'MEDIUM': 30}
        m['country']['source'] = 'web'
        m['review_months']['HIGH'] = 0
        m['reminders']['enabled'] = 'yes'
        probs = ' '.join(R.validate(m))
        assert 'bands' in probs and 'country source' in probs and 'HIGH' in probs and 'reminders' in probs


# --------------------------------------------------------------------------- F2 periodic review
class TestPeriodicReview:
    M = R.DEFAULT_MODEL

    def test_due_from_last_review_by_rating(self):
        c = {'risk_classification': 'HIGH', 'last_review_date': '2025-11-02'}
        assert PR.due_date(c, self.M) == date(2026, 11, 2)
        c = {'risk_classification': 'LOW', 'onboarding_date': '2024-01-15'}
        assert PR.due_date(c, self.M) == date(2027, 1, 15)

    def test_explicit_next_review_wins_and_no_date(self):
        assert PR.due_date({'next_review_date': '2026-12-01', 'last_review_date': '2020-01-01'}, self.M) == date(2026, 12, 1)
        assert PR.due_date({'risk_classification': 'HIGH'}, self.M) is None

    def test_states(self):
        today = date(2026, 11, 2)
        assert PR.review_state(date(2026, 11, 1), today, 30) == 'overdue'
        assert PR.review_state(date(2026, 11, 20), today, 30) == 'due_soon'
        assert PR.review_state(date(2027, 3, 1), today, 30) == 'ok'
        assert PR.review_state(None, today, 30) == 'unknown'

    def test_next_after(self):
        assert PR.next_after(date(2026, 11, 2), 'MEDIUM', self.M) == date(2028, 11, 2)


# --------------------------------------------------------------------------- F6 freeze log
class TestFreezeLog:
    def test_timeline_and_targets(self):
        e = {'discovered_at': datetime(2026, 11, 1, 9, 0), 'frozen_at': datetime(2026, 11, 1, 15, 30),
             'reported_at': datetime(2026, 11, 2, 18, 0)}
        t = FL.timeline(e, {'freeze': 24, 'report': 24})
        assert t['to_freeze_h'] == 6.5 and t['freeze_check']['met']
        assert t['to_report_h'] == 26.5 and not t['report_check']['met']
        assert t['discovery_to_report_h'] == 33.0

    def test_running_clock_without_targets(self):
        now = datetime(2026, 11, 2, 9, 0)
        t = FL.timeline({'discovered_at': '2026-11-01 09:00'}, {'freeze': None, 'report': None}, now=now)
        assert t['to_freeze_h'] == 24.0 and not t['freeze_done'] and t['freeze_check'] is None
        assert t['to_report_h'] is None

    def test_step_order(self):
        e = {'discovered_at': datetime.now() - timedelta(hours=5)}
        try:
            FL.validate_step(e, 'reported', datetime.now() - timedelta(hours=1))
            assert False
        except FL.FreezeError as ex:
            assert 'freeze before the report' in str(ex)
        try:
            FL.validate_step(e, 'frozen', datetime.now() - timedelta(hours=6))
            assert False
        except FL.FreezeError:
            pass
        try:
            FL.validate_step(e, 'frozen', datetime.now() + timedelta(hours=1))
            assert False
        except FL.FreezeError:
            pass
        assert FL.validate_step(e, 'frozen', (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'))

    def test_duration_text_and_status(self):
        assert FL.duration_text(26.5) == '1d 2h 30m'
        assert FL.duration_text(None) == '—'
        assert FL.status_of({'frozen_at': 1}) == 'FROZEN'
        assert FL.status_of({'frozen_at': 1, 'reported_at': 1}) == 'REPORTED'
        assert FL.parse_dt('2026-11-02T10:15') == datetime(2026, 11, 2, 10, 15)


# --------------------------------------------------------------------------- F4 KYB
class TestKyb:
    def test_ofac_50_aggregate(self):
        ubos = [{'id': 1, 'full_name': 'A', 'ownership_pct': '30', 'control_type': 'ownership'},
                {'id': 2, 'full_name': 'B', 'ownership_pct': '25', 'control_type': 'ownership'},
                {'id': 3, 'full_name': 'C', 'ownership_pct': '45', 'control_type': 'ownership'}]
        states = {('ubo', 1): K.CONFIRMED, ('ubo', 2): K.CONFIRMED, ('ubo', 3): K.CLEAR}
        so = K.sanctioned_ownership(ubos, states)
        assert so['pct'] == Decimal('55') and so['deemed_sanctioned'] and so['owners'] == ['A', 'B']
        states[('ubo', 2)] = K.CLEARED
        assert not K.sanctioned_ownership(ubos, states)['deemed_sanctioned']

    def test_blocker_message(self):
        ent = {'cr_number': '1', 'tax_card_number': '1', 'legal_form': 'LLC', 'incorporation_date': '2020-01-01',
               'incorporation_country': 'EG'}
        ubos = [{'id': 1, 'full_name': 'A', 'ownership_pct': '60', 'control_type': 'ownership'}]
        sigs = [{'id': 9, 'full_name': 'S'}]
        out = K.approval_blockers(ent, ubos, sigs, {('ubo', 1): K.CONFIRMED, ('signatory', 9): K.CLEAR})
        assert any('50%% rule' in m[0] for m in out if isinstance(m, tuple))

    def test_palestinian_parties(self):
        assert K.palestinian_parties({'name': 'Co', 'incorporation_country': 'PS'},
                                     [{'full_name': 'X', 'nationality': 'Palestinian'},
                                      {'full_name': 'Y', 'nationality': 'Egyptian'}]) == ['Co', 'X']


# --------------------------------------------------------------------------- F5 STR draft
class TestStrDraft:
    def test_default_text_from_case(self):
        f = {'case': {'activity_description': 'Cash deposits split below the reporting threshold.',
                      'red_flags_identified': 'Structuring', 'investigation_findings': 'Linked to a listed person.'},
             'freezes': [{'frozen_at': datetime(2026, 11, 1, 10, 0), 'freeze_scope': 'wallet 1'}]}
        t = SD.default_text(f)
        assert 'Structuring' in t['grounds'] and 'wallet 1' in t['actions_taken']
        assert t['narrative'] == 'Linked to a listed person.'
