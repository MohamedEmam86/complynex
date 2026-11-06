"""Phase 7 AML (F1, F2, F4, F5, F6) and the Phase 8 fixes: pure logic, no database."""
import copy
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from aml import escalation_log as EL
from aml import high_risk_countries as HR
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

    def test_home_country_required_on_save_only(self):
        m = copy.deepcopy(R.DEFAULT_MODEL)
        m['country']['home_country'] = '  '
        assert 'the home country is required' in R.validate(m, for_save=True)
        # a stored model with a blank home country is still valid (read with the default), never replaced
        assert R.validate(m) == []
        assert R.merged(m)['country']['home_country'] == 'EGYPT'
        m['bands'] = {'HIGH': 75, 'MEDIUM': 35}
        assert R.merged(m)['bands'] == {'HIGH': 75, 'MEDIUM': 35}


# --------------------------------------------------------------------------- F2 periodic review
class TestPeriodicReview:
    M = R.DEFAULT_MODEL

    def test_due_from_last_review_by_rating(self):
        c = {'risk_classification': 'HIGH', 'last_review_date': '2025-11-02'}
        assert PR.due_date(c, self.M) == date(2026, 11, 2)
        c = {'risk_classification': 'LOW', 'onboarding_date': '2024-01-15'}
        assert PR.due_date(c, self.M) == date(2027, 1, 15)

    def test_due_is_earlier_of_stored_and_current_rating(self):
        # stored date earlier than last review + interval: the stored date
        assert PR.due_date({'risk_classification': 'LOW', 'next_review_date': '2026-12-01',
                            'last_review_date': '2026-01-01'}, self.M) == date(2026, 12, 1)
        # re-rated HIGH after a LOW-interval date was stored: the HIGH interval wins
        assert PR.due_date({'risk_classification': 'HIGH', 'next_review_date': '2029-01-01',
                            'last_review_date': '2026-01-01'}, self.M) == date(2027, 1, 1)
        assert PR.due_date({'next_review_date': '2026-12-01'}, self.M) == date(2026, 12, 1)
        assert PR.due_date({'risk_classification': 'HIGH'}, self.M) is None

    def test_missing_rating_is_not_low(self):
        assert PR.rating_class(None) == 'HIGH' and PR.rating_class('weird') == 'HIGH'
        assert PR.rating_class('medium') == 'MEDIUM'
        assert PR.due_date({'last_review_date': '2026-01-01'}, self.M) == date(2027, 1, 1)
        assert PR.next_after(date(2026, 1, 1), None, self.M) == date(2027, 1, 1)

    def test_states(self):
        today = date(2026, 11, 2)
        assert PR.review_state(date(2026, 11, 1), today, 30) == 'overdue'
        assert PR.review_state(date(2026, 11, 20), today, 30) == 'due_soon'
        assert PR.review_state(date(2027, 3, 1), today, 30) == 'ok'
        assert PR.review_state(None, today, 30) == 'unknown'

    def test_next_after(self):
        assert PR.next_after(date(2026, 11, 2), 'MEDIUM', self.M) == date(2028, 11, 2)


# --------------------------------------------------------------------------- F6 hit escalation log
class TestEscalationLog:
    def test_timeline_and_targets(self):
        e = {'discovered_at': datetime(2026, 11, 1, 9, 0), 'escalated_at': datetime(2026, 11, 1, 15, 30),
             'reported_at': datetime(2026, 11, 2, 18, 0)}
        t = EL.timeline(e, {'escalate': 24, 'report': 24})
        assert t['to_escalate_h'] == 6.5 and t['escalate_check']['met']
        assert t['to_report_h'] == 26.5 and not t['report_check']['met']
        assert t['discovery_to_report_h'] == 33.0

    def test_running_clock_without_targets(self):
        now = datetime(2026, 11, 2, 9, 0)
        t = EL.timeline({'discovered_at': '2026-11-01 09:00'}, {'escalate': None, 'report': None}, now=now)
        assert t['to_escalate_h'] == 24.0 and not t['escalate_done'] and t['escalate_check'] is None
        assert t['to_report_h'] is None

    def test_step_order(self):
        e = {'discovered_at': datetime.now() - timedelta(hours=5)}
        with pytest.raises(EL.EscalationError, match='escalation to the MLRO before the report'):
            EL.validate_step(e, 'reported', datetime.now() - timedelta(hours=1))
        with pytest.raises(EL.EscalationError):
            EL.validate_step(e, 'escalated', datetime.now() - timedelta(hours=6))
        with pytest.raises(EL.EscalationError):
            EL.validate_step(e, 'escalated', datetime.now() + timedelta(hours=1))
        assert EL.validate_step(e, 'escalated', (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'))

    def test_duration_text_and_status(self):
        assert EL.duration_text(26.5) == '1d 2h 30m'
        assert EL.duration_text(None) == '—'
        assert EL.status_of({}) == 'DISCOVERED'
        assert EL.status_of({'escalated_at': 1}) == 'ESCALATED'
        assert EL.status_of({'escalated_at': 1, 'reported_at': 1}) == 'REPORTED'
        # an old row with a freeze time only is not "frozen" any more: it is waiting for escalation
        assert EL.status_of({'frozen_at': 1}) == 'DISCOVERED'
        assert EL.parse_dt('2026-11-02T10:15') == datetime(2026, 11, 2, 10, 15)

    def test_no_freeze_anywhere(self):
        import inspect
        text = inspect.getsource(EL)
        for code, en, ar in EL.STATUSES:
            assert 'freez' not in en.lower() and 'تجميد' not in ar
        assert set(EL.TARGET_PARAMS) == {'escalate', 'report'}
        assert EL.TARGET_PARAMS['escalate'][0] == 'aml.escalation_target_hours'
        assert EL.TARGET_PARAMS['report'][0] == 'aml.report_target_hours'
        assert 'record_freeze' not in text and 'record_release' not in text


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

    def test_stake_counts_whatever_the_control_type(self):
        ubos = [{'id': 1, 'full_name': 'A', 'ownership_pct': '30', 'control_type': 'control'},
                {'id': 2, 'full_name': 'B', 'ownership_pct': '25', 'control_type': 'senior_manager'},
                {'id': 3, 'full_name': 'C', 'ownership_pct': None, 'control_type': 'control'}]
        states = {('ubo', 1): K.CONFIRMED, ('ubo', 2): K.CONFIRMED, ('ubo', 3): K.CONFIRMED}
        so = K.sanctioned_ownership(ubos, states)
        assert so['pct'] == Decimal('55') and so['deemed_sanctioned'] and so['owners'] == ['A', 'B']
        assert set(K.CONTROL_TYPES) == {'ownership', 'control', 'senior_manager'}

    def test_blocker_message(self):
        ent = {'cr_number': '1', 'tax_card_number': '1', 'legal_form': 'LLC', 'incorporation_date': '2020-01-01',
               'incorporation_country': 'EG'}
        ubos = [{'id': 1, 'full_name': 'A', 'ownership_pct': '60', 'control_type': 'ownership'}]
        sigs = [{'id': 9, 'full_name': 'S'}]
        out = K.approval_blockers(ent, ubos, sigs, {('ubo', 1): K.CONFIRMED, ('signatory', 9): K.CLEAR})
        msg = [m[0] for m in out if isinstance(m, tuple) and '50%% rule' in m[0]]
        assert msg and 'escalate to the MLRO' in msg[0] and 'outside this system' in msg[0]
        assert 'treat the entity' not in msg[0] and 'sanctioned' in msg[0].lower()
        assert msg[0] % {'pct': '60', 'threshold': '50'}      # the %% placeholders format

    def test_palestinian_parties(self):
        assert K.palestinian_parties({'name': 'Co', 'incorporation_country': 'PS'},
                                     [{'full_name': 'X', 'nationality': 'Palestinian'},
                                      {'full_name': 'Y', 'nationality': 'Egyptian'}]) == ['Co', 'X']


# --------------------------------------------------------------------------- F5 STR draft
class TestStrDraft:
    def test_default_text_from_case(self):
        f = {'case': {'activity_description': 'Cash deposits split below the reporting threshold.',
                      'red_flags_identified': 'Structuring', 'investigation_findings': 'Linked to a listed person.'},
             'escalations': [{'reference': 'ESC-1', 'escalated_at': datetime(2026, 11, 1, 10, 0),
                              'reported_at': datetime(2026, 11, 1, 12, 0), 'reported_to': 'the FIU',
                              'report_reference': 'R-9'}]}
        t = SD.default_text(f)
        assert 'Structuring' in t['grounds'] and 'escalated to the MLRO on 2026-11-01 10:00' in t['actions_taken']
        assert 'Reported to the FIU on 2026-11-01 12:00 (reference R-9).' in t['actions_taken']
        assert 'froz' not in t['actions_taken'].lower()
        assert t['narrative'] == 'Linked to a listed person.'

    def test_draft_visibility(self):
        class U:
            id = 7
        case = {'assigned_to': 7, 'reported_by': 3}
        assert SD.can_see(case, U(), False)
        assert SD.can_see({'assigned_to': 1, 'reported_by': 7}, U(), False)
        assert not SD.can_see({'assigned_to': 1, 'reported_by': 2}, U(), False)
        assert SD.can_see({'assigned_to': None, 'reported_by': None}, U(), True)


# --------------------------------------------------------------------------- Phase 8 fixes
class TestP8:
    def test_safe_back_rejects_other_hosts(self):
        from aml.p7_routes import _safe_back
        assert _safe_back('/aml/periodic-reviews?state=overdue', '/d') == '/aml/periodic-reviews?state=overdue'
        for bad in ('//evil.example', 'https://evil.example', '/\\evil.example', '', None, 'aml/x', '/x\r\nLocation: y',
                    '/x\ty', '/x\x00y', '/x\x7fy'):
            assert _safe_back(bad, '/d') == '/d'

    def test_high_risk_country_form(self):
        ok = HR.clean({'country_code': 'ye', 'country_name': 'Yemen', 'name_ar': 'اليمن', 'risk_category': 'INCREASED_MONITORING',
                       'source': 'FATF public statement, October 2026', 'effective_date': '2026-10-24',
                       'aliases': 'Yemeni | YEM | yemeni', 'is_active': '1'})
        assert ok['country_code'] == 'YE' and ok['aliases'] == 'Yemeni|YEM' and ok['is_active'] == 1
        for bad in ({'country_code': 'Y1'}, {'country_code': 'YE', 'country_name': 'Yemen', 'risk_category': 'X'},
                    {'country_code': 'YE', 'country_name': 'Yemen', 'risk_category': 'OTHER', 'source': 'x'},
                    {'country_code': 'YE', 'country_name': 'Yemen', 'risk_category': 'OTHER', 'source': 'FATF',
                     'effective_date': '2026-13-40'}):
            with pytest.raises(HR.CountryError):
                HR.clean(bad)
        with pytest.raises(HR.CountryError):
            HR.reason_of({'reason': 'no'})
        assert set(HR.CATEGORY_CODES) >= {'CALL_FOR_ACTION', 'INCREASED_MONITORING', 'INTERNAL', 'OTHER'}
        assert [k for k, *_r in HR.IMPACT] == ['floor', 'tm004', 'model', 'radar']


class TestNoFreeze:
    """Owner decision: ComplyNex only alerts and escalates."""

    def test_screening_texts(self):
        from screening import result_view as rv
        from screening import workflow as wf
        for t in (rv.ESCALATE_CONFIRMED, rv.ESCALATE_POTENTIAL, rv.SERIOUS_STRICT):
            assert 'freeze funds' not in t.lower() and 'freeze without' not in t.lower() and 'MLRO' in t
        for code in ('FREEZE_ESCALATE', 'FREEZE_REPORT'):
            for tier in ('CONFIRMED', 'POTENTIAL'):
                a = wf.action_for({'source': 'un' if code == 'FREEZE_ESCALATE' else 'internal_blacklist',
                                   'decision': {'tier': tier}}, wf.DEFAULT_TABLE)
                assert a['code'] == code and 'MLRO' in a['step']['en'] and '{list}' not in a['step']['en']
                assert 'freeze funds' not in a['step']['en'].lower() and 'جمّد' not in a['step']['ar']

    def test_api_reason_code(self):
        from api.v1_common import payment_decision
        d, reasons = payment_decision([{'role': 'payer', 'hits': [{'tier': 'CONFIRMED', 'action': {'code': 'FREEZE_ESCALATE'}}]}])
        assert d == 'BLOCK' and reasons[0]['code'] == 'confirmed_listed_escalate' and 'MLRO' in reasons[0]['en']
