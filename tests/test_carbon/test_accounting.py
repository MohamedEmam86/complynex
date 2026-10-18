"""Worked-example tests for carbon.accounting (pure functions, no database).

Each test states the hand calculation it checks, so an auditor can re-do it."""
from datetime import date

import pytest

from carbon import accounting as A
from carbon.engine import compute_scope_totals


class TestBoundary:
    ent = {'ownership_pct': 60, 'operational_control': True, 'financial_control': False, 'included': True}

    def test_approaches(self):
        assert A.inclusion_share(self.ent, 'equity_share') == 0.6
        assert A.inclusion_share(self.ent, 'operational_control') == 1.0
        assert A.inclusion_share(self.ent, 'financial_control') == 0.0
        assert A.inclusion_share(dict(self.ent, included=False), 'equity_share') == 0.0
        assert A.inclusion_share(None, 'equity_share') == 1.0

    def test_worked_equity_share(self):
        # 10,000 kWh x 0.5 kgCO2e/kWh = 5,000 kg = 5 tCO2e gross; 60% equity share -> 3 tCO2e consolidated
        r = A.compute_activity(10000, {'factor_kgco2e': 0.5, 'unit': 'kWh'}, 0.6, 'kWh')
        assert r['gross_tco2e'] == 5.0 and r['tco2e'] == 3.0 and r['unit_ok']

    def test_unit_mismatch(self):
        assert not A.compute_activity(100, {'factor_kgco2e': 2.6, 'unit': 'litre'}, 1, 'kWh')['unit_ok']


class TestFactorVersions:
    v = [{'id': 1, 'effective_from': date(2024, 1, 1), 'effective_to': date(2024, 12, 31), 'factor_kgco2e': 0.50},
         {'id': 2, 'effective_from': date(2025, 1, 1), 'effective_to': None, 'factor_kgco2e': 0.47}]

    def test_by_activity_date(self):
        assert A.select_factor_version(self.v, date(2024, 6, 1))['id'] == 1
        assert A.select_factor_version(self.v, date(2025, 3, 1))['id'] == 2
        assert A.select_factor_version(self.v, date(2023, 3, 1)) is None

    def test_worked_grid_change(self):
        # Same 1,000 kWh: 2024 version 0.50 -> 0.5 t ; 2025 version 0.47 -> 0.47 t
        f24, f25 = (A.select_factor_version(self.v, date(y, 6, 1)) for y in (2024, 2025))
        assert A.compute_activity(1000, f24)['tco2e'] == 0.5
        assert A.compute_activity(1000, f25)['tco2e'] == 0.47


class TestScope2AndScope3Helpers:
    def test_dual_reporting(self):
        rows = [{'scope': 'scope2', 'tco2e': 4.7, 'basis': 'location'}, {'scope': 'scope2', 'tco2e': 1.0, 'basis': 'market'},
                {'scope': 'scope1', 'tco2e': 2.0}]
        t = compute_scope_totals(rows)
        assert t['scope2_location'] == 4.7 and t['scope2_market'] == 1.0 and t['total_location_based'] == 6.7

    def test_market_based_fallback(self):
        # Site 1 Jan: 10 t grid; a green-tariff instrument covers it at 0 t -> market 0 for that month.
        # Site 1 Feb: 8 t grid, no instrument -> grid used as fallback. Location 18 t, market 8 t.
        rows = [{'scope': 'scope2', 'site_id': 1, 'activity_month': date(2025, 1, 1), 'tco2e': 10, 'basis': 'location'},
                {'scope': 'scope2', 'site_id': 1, 'activity_month': date(2025, 1, 1), 'tco2e': 0, 'basis': 'market'},
                {'scope': 'scope2', 'site_id': 1, 'activity_month': date(2025, 2, 1), 'tco2e': 8, 'basis': 'location'}]
        assert A.scope2_dual(rows) == (18.0, 8.0)

    def test_commuting(self):
        # 50 employees x 220 days x 15 km x 2 = 330,000 passenger-km
        assert A.commuting_quantity(50, 220, 15) == 330000

    def test_travel(self):
        # 4 trips x 650 km x 2 travellers x 2 (return) = 10,400 passenger-km
        assert A.travel_quantity(4, 650, 2) == 10400


class TestPCAF:
    def test_business_loan_reported(self):
        # Loan EGP 2m to a company with equity+debt EGP 10m and 500 tCO2e -> AF 0.2 -> 100 tCO2e, score 2
        r = A.pcaf_exposure({'outstanding': 2e6, 'attribution_base': 10e6, 'method': 'reported', 'borrower_emissions_tco2e': 500})
        assert r == {'attribution': 0.2, 'financed_tco2e': 100.0, 'score': 2, 'error': None}

    def test_revenue_based(self):
        # AF 0.25; revenue EGP 4m x 30 tCO2e per EGP m = 120 t; financed = 30 t; score 4
        r = A.pcaf_exposure({'outstanding': 1e6, 'attribution_base': 4e6, 'method': 'revenue', 'borrower_revenue_egp': 4e6}, 30)
        assert r['financed_tco2e'] == 30.0 and r['score'] == 4

    def test_asset_based(self):
        # Micro-loan book EGP 50m x 12 tCO2e per EGP m outstanding = 600 t; score 5
        assert A.pcaf_exposure({'outstanding': 50e6, 'method': 'asset'}, 12)['financed_tco2e'] == 600.0

    def test_attribution_capped_and_errors(self):
        assert A.pcaf_exposure({'outstanding': 5e6, 'attribution_base': 1e6, 'method': 'reported',
                                'borrower_emissions_tco2e': 10})['attribution'] == 1.0
        assert A.pcaf_exposure({'outstanding': 1, 'method': 'reported'})['error'] == 'attribution base missing'
        assert A.pcaf_exposure({'outstanding': 1, 'method': 'asset'})['error'] == 'sector factor missing'

    def test_weighted_score(self):
        # (2 x 2m + 5 x 8m) / 10m = 4.4
        res = [({'outstanding': 2e6, 'asset_class': 'business_loans'}, {'financed_tco2e': 100.0, 'score': 2, 'error': None}),
               ({'outstanding': 8e6, 'asset_class': 'business_loans'}, {'financed_tco2e': 96.0, 'score': 5, 'error': None})]
        s = A.pcaf_portfolio(res)
        assert s['weighted_score'] == 4.4 and s['financed_tco2e'] == 196.0 and s['coverage_pct'] == 100.0


class TestDataQuality:
    start, end = date(2025, 1, 1), date(2025, 3, 31)

    def e(self, i, m, q=100, unit='kWh', fu='kWh'):
        return {'id': i, 'site_id': 1, 'factor_code': 'GRID', 'activity': 'Electricity', 'activity_month': m,
                'quantity': q, 'unit': unit, 'factor_unit': fu}

    def test_missing_month_and_unit(self):
        rows = [self.e(1, date(2025, 1, 1)), self.e(2, date(2025, 3, 1), unit='MWh')]
        iss = A.dq_issues(rows, self.start, self.end)
        codes = sorted(i['code'] for i in iss)
        assert codes == ['missing_months', 'unit_mismatch']
        assert '2025-02' in next(i for i in iss if i['code'] == 'missing_months')['message']

    def test_outlier_and_evidence(self):
        rows = [self.e(m, date(2025, m, 1), q=300) for m in (1, 2, 3)]
        prev = [self.e(9, date(2024, m, 1), q=100) for m in (1, 2, 3)]
        iss = A.dq_issues(rows, self.start, self.end, prev, 50, has_evidence=lambda e: e['id'] != 2)
        assert {i['code'] for i in iss} == {'outlier', 'unsupported'}
        assert next(i for i in iss if i['code'] == 'unsupported')['severity'] == 'critical'


class TestWorkflow:
    def test_segregation(self):
        assert A.next_state({}, 'submit', 1) == 'in_review'
        with pytest.raises(ValueError):
            A.next_state({'status': 'preparing'}, 'submit', 1, critical_issues=2)
        with pytest.raises(ValueError):
            A.next_state({'status': 'in_review', 'prepared_by': 1}, 'review', 1)
        assert A.next_state({'status': 'in_review', 'prepared_by': 1}, 'review', 2) == 'reviewed'
        with pytest.raises(ValueError):
            A.next_state({'status': 'reviewed', 'prepared_by': 1, 'reviewed_by': 2}, 'approve', 2)
        assert A.next_state({'status': 'reviewed', 'prepared_by': 1, 'reviewed_by': 2}, 'approve', 3) == 'approved'
        assert A.is_locked({'status': 'approved'}) and not A.is_locked({'status': 'reviewed'})
        with pytest.raises(ValueError):
            A.next_state({'status': 'approved'}, 'submit', 1)


class TestIntensity:
    def test_worked(self):
        # 120 tCO2e, 40 staff -> 3.0 ; 1,500 m2 -> 0.08 ; EGP 60m revenue -> 2.0 per EGP m ;
        # 600 t financed on EGP 200m -> 3.0 per EGP m financed
        i = A.intensities(120, 40, 1500, 60e6, 200e6, 600)
        assert i == {'per_employee': 3.0, 'per_m2': 0.08, 'per_egp_m_revenue': 2.0, 'per_egp_m_financed': 3.0}

    def test_offsets_not_netted(self):
        assert A.offsets_view(100, 20) == {'gross_tco2e': 100, 'offsets_retired_tco2e': 20, 'net_shown': False}
