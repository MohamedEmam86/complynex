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
Generic checks shipped with the core. Any framework can bind its controls to
them through rc_controls.check_key. Pack-specific checks live in the pack.
"""

from datetime import date

from .engine import register_check
from . import logic


@register_check('core.findings_not_repeated', name='Findings remediated and not repeated')
def findings_not_repeated(ctx):
    """Fail while a repeated violation is open; warn while findings are overdue."""
    grace = ctx.param('rc.finding_overdue_grace_days', 0)
    rows = [dict(r) for r in ctx.db.execute(
        "SELECT id, reference, title, status, due_date, is_repeated FROM rc_findings "
        "WHERE status <> 'closed'").fetchall()]
    repeated = [r for r in rows if r['is_repeated']]
    overdue = [r for r in rows if logic.is_overdue(r['due_date'], r['status'], ctx.as_of or date.today(), grace)]

    def rec(r):
        return {'table': 'rc_findings', 'id': r['id'], 'label': f"{r['reference']} {r['title']}"[:200]}

    if repeated:
        return ctx.fail(f'{len(repeated)} repeated violation(s) open', [rec(r) for r in repeated],
                        overdue=len(overdue), open=len(rows))
    if overdue:
        return ctx.warn(f'{len(overdue)} finding(s) past their due date', [rec(r) for r in overdue],
                        open=len(rows))
    return ctx.ok(f'{len(rows)} open finding(s), none overdue or repeated', open=len(rows))
