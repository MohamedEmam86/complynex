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

"""
Demo parameter values for the FICTIONAL demo tenant ("Nile Microfinance
S.A.E."). Every value is ILLUSTRATIVE, not a regulatory value: each row it
fills is marked needs_review with the note "DEMO VALUE". Only parameters that
are still empty are filled, and only on an installation flagged as a demo
tenant (Settings rc_demo_tenant = true, set by the demo seed scripts after
they have checked that no real data exists).
"""

DEMO_NOTE = 'DEMO VALUE — illustrative only, not a regulatory value (fictional demo tenant)'

DEMO_PARAMETERS = {
    # capital & solvency
    'capital.min_paid_up': '20000000',
    'solvency.max_leverage_ratio': '7',
    # lending conduct
    'lending.max_client_monthly_revenue': '50000', 'lending.max_project_size': '500000',
    'lending.gps_mandatory_min_amount': '30000', 'lending.followup_visit_days': '30',
    'portfolio.par30_threshold_pct': '5', 'lending.min_cost_lines': '3', 'lending.max_dsr_pct': '50',
    'lending.admin_fee_cap_pct': '3',
    'lending.admin_fee_tiers': '[{"max_amount": 20000, "cap_pct": 3}, {"max_amount": null, "cap_pct": 2}]',
    'lending.late_penalty_rate_pct': '2', 'lending.late_penalty_cap_pct': '10', 'lending.transfer_fee_cap': '100',
    'lending.rescheduling_fee_cap': '250', 'lending.prepay_new_loan_window_days': '30',
    # AML / KYC
    'aml.unusual_txn_study_sla_days': '15', 'aml.watchlist_freshness_max_hours': '24',
    'aml.employee_rescreen_months': '12', 'kyc.refresh_months_high': '12', 'kyc.refresh_months_medium': '24',
    'kyc.refresh_months_low': '36', 'policy.max_days_pending_board_approval': '90',
    # governance, finance, IT
    'branch.min_loan_officers': '3', 'branch.manager_vacancy_max_days': '60',
    'finance.balance_confirmation_max_age_days': '90', 'finance.accrual_tolerance_pct': '5',
    'finance.ecl_refresh_months': '12', 'it.dr_test_max_age_months': '12', 'it.offsite_backup_max_age_days': '7',
    'it.risk_register_max_age_days': '180',
    'carbon.report_due_days': '120',
}


def mark_demo_tenant():
    from models.settings import Settings
    Settings.set('rc_demo_tenant', 'true', 'Fictional demo tenant: demo parameter values allowed')
    if (Settings.get('rc_licence_type', 'all') or 'all') == 'all':
        Settings.set('rc_licence_type', 'microfinance', 'Licence type used to select regulatory parameter values')


def is_demo_tenant():
    from models.settings import Settings
    return str(Settings.get('rc_demo_tenant', '') or '').lower() == 'true'


def apply_demo_parameters(db):
    """Fill still-empty pack parameters with demo values. Returns {key: 'set' | 'kept'}."""
    if not is_demo_tenant():
        raise RuntimeError('not a demo tenant — refusing to write demo parameter values')
    out = {}
    for key, value in DEMO_PARAMETERS.items():
        n = db.execute("""UPDATE rc_parameters SET value_text = %s, needs_review = TRUE, review_note = %s
                          WHERE param_key = %s AND value_text IS NULL AND status = 'active'""",
                       (value, DEMO_NOTE, key)).rowcount
        out[key] = 'set' if n else 'kept'
    db.commit()
    return out
