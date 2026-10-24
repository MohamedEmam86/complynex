# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""Four-eyes clearance and whitelist governance rules (no database)."""
from datetime import date

from screening import clearance as CL


def test_needs_approval_by_score_or_sanctions():
    assert CL.needs_approval(85, False, 85)
    assert CL.needs_approval(99, False)
    assert not CL.needs_approval(84.9, False, 85)
    assert CL.needs_approval(40, True, 85)          # any sanctions-list hit
    assert not CL.needs_approval(None, False)


def test_sanctions_detection():
    assert CL.is_sanctions_hit('OFAC_SDN', {'category': 'Terrorism'})
    assert not CL.is_sanctions_hit('Adverse Media', {'hits': []})
    assert not CL.is_sanctions_hit('opensanctions_pep', {'topics': ['role.pep']})
    assert CL.is_sanctions_hit('Unknown', {})        # unknown -> stricter side


def test_maker_is_not_checker():
    assert CL.maker_checker_error(5, 5)
    assert CL.maker_checker_error(None, 5)
    assert CL.maker_checker_error(6, 5) is None
    assert CL.maker_checker_error(6, None) is None


def test_review_date_rules():
    today = date(2026, 11, 10)
    d, err = CL.parse_review_date('', today)
    assert err is None and d == date(2027, 11, 10)
    assert CL.parse_review_date('2028-11-10', today) == (date(2028, 11, 10), None)
    assert CL.parse_review_date('2028-11-11', today)[1]      # beyond 24 months
    assert CL.parse_review_date('2026-11-10', today)[1]      # not in the future
    assert CL.parse_review_date('nonsense', today)[1]
    assert CL.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_expired_entries_stop_counting_as_active():
    today = date(2026, 11, 10)
    assert CL.effective_wl_status('Active', '2026-11-09', today) == CL.WL_EXPIRED
    assert CL.effective_wl_status('Active', '2026-11-10', today) == 'Active'
    assert CL.effective_wl_status('Pending Approval', '2020-01-01', today) == 'Pending Approval'
    assert CL.effective_wl_status(None, None, today) == 'Active'


def test_approval_authority():
    class U:
        def __init__(self, role, admin_mod=False):
            self.role, self._a = role, admin_mod

        def can_admin_module(self, m):
            return self._a
    assert CL.can_approve(U('compliance_manager'))
    assert CL.can_approve(U('admin'))
    assert CL.can_approve(U('compliance_officer', admin_mod=True))
    assert not CL.can_approve(U('compliance_officer'))
    assert not CL.can_approve(None)
