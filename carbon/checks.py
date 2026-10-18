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
Generic carbon-inventory checks for the regcontrols engine (any regulator or
voluntary framework can bind controls to them; numbers come from parameters
or the control's check settings).

    core.carbon.inventory_approved  config: due_days_param (days after period end, e.g. carbon.report_due_days)
    core.carbon.data_quality        —   (critical issues fail, warnings warn)
    core.carbon.evidence            —   every entry of the period supported
    core.carbon.verification        config: statuses (default ["Certified", "Submitted"])
    core.carbon.offsets             —   offset obligation fulfilled before its deadline
    core.carbon.factors_current     config: max_age_years (default 3)
"""

from datetime import timedelta

from regcontrols.api import register_check

from . import accounting as A
from . import service as S


def _last_closed(ctx):
    rows = [p for p in S.periods(ctx.db) if p.get('end_date') and p['end_date'] < ctx.as_of]
    return rows[0] if rows else None


@register_check('core.carbon.inventory_approved', name='Carbon inventory approved on time')
def inventory_approved(ctx):
    p = _last_closed(ctx)
    if not p:
        return ctx.not_applicable('No completed reporting period')
    due_days = ctx.param(ctx.config['due_days_param']) if ctx.config.get('due_days_param') else None
    wf = S.workflow(p['id'], ctx.db)
    if A.is_locked(wf):
        return ctx.ok(f"{p['label']} approved on {wf['approved_at']:%Y-%m-%d}")
    if due_days is not None and ctx.as_of <= p['end_date'] + timedelta(days=int(due_days)):
        return ctx.warn(f"{p['label']} not approved yet (due {p['end_date'] + timedelta(days=int(due_days))}); status {wf['status']}")
    return ctx.fail(f"{p['label']} inventory not approved (status {wf['status']})")


def _current(ctx):
    return S.period(None, ctx.db)


@register_check('core.carbon.data_quality', name='Carbon data quality')
def data_quality(ctx):
    p = _current(ctx)
    if not p:
        return ctx.not_applicable('No reporting period')
    dq = S.data_quality(p['id'], ctx.db)
    crit = [i for i in dq['issues'] if i['severity'] == 'critical']
    warn = [i for i in dq['issues'] if i['severity'] != 'critical']
    aff = [{'table': 'carbon_activity_entries', 'id': i.get('entry_id') or 0, 'label': i['code'], 'issue': i['message']}
           for i in crit + warn]
    if crit:
        return ctx.fail(f"{p['label']}: {len(crit)} critical data-quality issue(s)", aff)
    if warn:
        return ctx.warn(f"{p['label']}: {len(warn)} data-quality warning(s)", aff)
    return ctx.ok(f"{p['label']}: {dq['entries']} entries, no data-quality issue")


@register_check('core.carbon.evidence', name='Every activity entry supported by evidence')
def evidence(ctx):
    p = _current(ctx)
    if not p:
        return ctx.not_applicable('No reporting period')
    rows = S.entries(p['id'], ctx.db)
    if not rows:
        return ctx.fail(f"{p['label']}: no activity data recorded")
    bad = [e for e in rows if not S.has_evidence(e, ctx.db)]
    if bad:
        return ctx.fail(f'{len(bad)} of {len(rows)} entries without evidence',
                        [{'table': 'carbon_activity_entries', 'id': e['id'], 'label': e['activity']} for e in bad])
    return ctx.ok(f'{len(rows)} entries supported by evidence')


@register_check('core.carbon.verification', name='Carbon report verified by an independent verifier')
def verification(ctx):
    p = _last_closed(ctx)
    if not p:
        return ctx.not_applicable('No completed reporting period')
    ok = ctx.config.get('statuses') or ['Certified', 'Submitted']
    st = p.get('fra_status') or 'Draft'
    if st in ok:
        return ctx.ok(f"{p['label']}: {st}" + (f" by {p['verifier_name']}" if p.get('verifier_name') else ''))
    return ctx.fail(f"{p['label']}: report status {st}")


@register_check('core.carbon.offsets', name='Offset obligation fulfilled before its deadline')
def offsets(ctx):
    rows = [dict(r) for r in ctx.db.execute("""
        SELECT o.*, COALESCE((SELECT sum(quantity_tco2e) FROM carbon_offset_purchases x WHERE x.obligation_id = o.id), 0) AS bought
        FROM carbon_offset_obligations o ORDER BY o.deadline_date""").fetchall()]
    if not rows:
        return ctx.not_applicable('No offset obligation')
    late = [o for o in rows if float(o['bought']) < float(o['required_tco2e'] or 0) and o['deadline_date'] < ctx.as_of]
    open_ = [o for o in rows if float(o['bought']) < float(o['required_tco2e'] or 0) and o['deadline_date'] >= ctx.as_of]
    aff = [{'table': 'carbon_offset_obligations', 'id': o['id'], 'label': str(o['deadline_date']),
            'required': float(o['required_tco2e'] or 0), 'bought': float(o['bought'])} for o in late + open_]
    if late:
        return ctx.fail(f'{len(late)} offset obligation(s) past the deadline and not fulfilled', aff)
    if open_:
        return ctx.warn(f'{len(open_)} offset obligation(s) open, deadline {open_[0]["deadline_date"]}', aff)
    return ctx.ok(f'{len(rows)} offset obligation(s) fulfilled')


@register_check('core.carbon.factors_current', name='Emission factors sourced and current')
def factors_current(ctx):
    p = _current(ctx)
    if not p:
        return ctx.not_applicable('No reporting period')
    years = int(ctx.config.get('max_age_years') or 3)
    rows = S.entries(p['id'], ctx.db)
    nosrc = [e for e in rows if not e.get('factor_source_used') and not e.get('factor_id')]
    old = [e for e in rows if e.get('factor_vintage_used') and p['end_date'].year - int(e['factor_vintage_used']) > years]
    if nosrc:
        return ctx.fail(f'{len(nosrc)} entries without a traceable factor')
    if old:
        return ctx.warn(f'{len(old)} entries use a factor older than {years} years',
                        [{'table': 'carbon_activity_entries', 'id': e['id'], 'label': e['activity'],
                          'vintage': e['factor_vintage_used']} for e in old])
    return ctx.ok(f'{len(rows)} entries with sourced, current factors')
