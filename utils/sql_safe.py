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
Safe SQL utilities to prevent SQL injection.
Use these functions anywhere user input touches SQL queries.
"""

# Whitelisted sort columns per table/endpoint
SORT_WHITELISTS = {
    'transactions': {
        'transaction_date', 'amount', 'transaction_type', 
        'currency', 'created_at', 'transaction_reference'
    },
    'customers': {
        'full_name', 'company_name', 'risk_classification',
        'onboarding_date', 'customer_reference', 'status'
    },
    'alerts': {
        'alert_date', 'alert_severity', 'status', 'created_at'
    },
    'screening': {
        'created_at', 'screened_name', 'highest_match_score', 'screening_result'
    },
    'users': {
        'first_name', 'last_name', 'email', 'created_at', 'role'
    },
}

SORT_DIRECTIONS = {'asc', 'desc', 'ASC', 'DESC'}


def safe_sort_column(column: str, table: str, default: str) -> str:
    """
    Validate sort column against whitelist.
    Returns the column if valid, default otherwise.
    Never passes raw user input to ORDER BY.
    """
    whitelist = SORT_WHITELISTS.get(table, set())
    if column and column.lower().split('.')[-1] in {c.lower() for c in whitelist}:
        return column
    return default


def safe_sort_direction(direction: str) -> str:
    """Returns 'DESC' or 'ASC' — never raw user input."""
    if direction and direction.upper() in {'ASC', 'DESC'}:
        return direction.upper()
    return 'DESC'


def safe_int(value, default=1, min_val=1, max_val=10000):
    """Safely convert to int with bounds checking."""
    try:
        v = int(value)
        return max(min_val, min(max_val, v))
    except (TypeError, ValueError):
        return default


def safe_page(value, default=1):
    """Safe page number from request."""
    return safe_int(value, default=default, min_val=1, max_val=100000)


def safe_per_page(value, default=25, max_val=200):
    """Safe per-page from request."""
    return safe_int(value, default=default, min_val=1, max_val=max_val)
