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
Database helper utilities for safe record fetching.
Always use these instead of raw fetchone() to prevent 502 errors.
"""
from flask import abort
import logging

logger = logging.getLogger(__name__)


def get_or_404(db, query, params, error_msg=None):
    """
    Fetch a single record or abort with 404 if not found.
    Prevents 502 errors from unhandled None.fetchone() crashes.
    
    Usage:
        customer = get_or_404(db, 
            "SELECT * FROM customers WHERE id = %s", 
            (customer_id,))
    """
    try:
        result = db.execute(query, params).fetchone()
        if result is None:
            logger.info(f"Record not found: {query[:60]} params={params}")
            abort(404, description=error_msg or "Record not found")
        return result
    except Exception as e:
        if '404' in str(type(e).__name__):
            raise
        logger.error(f"Database error in get_or_404: {e}")
        raise


def get_or_none(db, query, params):
    """Fetch a single record or return None — never crashes."""
    try:
        return db.execute(query, params).fetchone()
    except Exception as e:
        logger.error(f"Database error in get_or_none: {e}")
        return None


def check_resource_access(db, table, record_id, user, admin_roles=None, owner_field=None, action='view'):
    """
    Check if user has access to a specific record.
    Prevents IDOR - users cannot access records that don't belong to them.
    Admins and compliance officers can access all records.

    Args:
        owner_field: column on `table` holding the owning user's id (e.g.
            'submitter_id', 'employee_id'). This platform is single-tenant, so
            there's no cross-company ownership to check — pass owner_field
            whenever a non-admin user should only be able to reach records
            that are actually theirs (typically for `action='edit'`). Without
            it, no ownership check is performed and any authenticated user can
            reach the record (matches this platform's "view broadly, edit only
            your own" model already used by portal/COI/COBEC/GHE routes).
        action: 'view' or 'edit' — included in the audit-log line if access
            is denied, for traceability.

    Returns the record if accessible, aborts 404/403 if not.
    """
    from flask import abort

    admin_roles = admin_roles or {'admin', 'compliance_officer', 'compliance_manager', 'superadmin'}

    result = db.execute(f"SELECT * FROM {table} WHERE id = %s", (record_id,)).fetchone()
    if result is None:
        abort(404, description=f"Record {record_id} not found")

    # Admins/compliance staff can access everything
    if hasattr(user, 'role') and user.role in admin_roles:
        return result

    # No owner_field given: caller didn't ask for an ownership check.
    if not owner_field:
        return result

    owner_id = result[owner_field] if owner_field in result.keys() else None
    if owner_id != user.id:
        logger.warning(
            f"IDOR attempt blocked: user {user.id} tried to {action} "
            f"{table}#{record_id} (owned by {owner_id!r})"
        )
        abort(403, description="You do not have access to this record")

    return result


def sanitize_form_fields(form_data, allowed_fields):
    """
    Prevent mass assignment attacks.
    Only allow explicitly whitelisted fields from form data.
    
    Usage:
        safe_data = sanitize_form_fields(request.form, 
            ['full_name', 'email', 'phone'])
    """
    return {k: v for k, v in form_data.items() if k in allowed_fields}
