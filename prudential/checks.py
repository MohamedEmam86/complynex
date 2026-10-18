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
Generic prudential / governance / financial-reporting checks for the
regcontrols engine. Any framework binds its controls to these keys and tunes
them through the control's check_config; thresholds come from parameters.

    core.prudential.min_capital       config: min_param (default capital.min_paid_up)
    core.prudential.deadlines         config: categories (default all), alert_param
    core.prudential.solvency          config: max_leverage_param, min_equity_param, min_capital_base_param,
                                              max_age_days (default 120)
    core.governance.registered_address  —
    core.governance.key_functions     config: functions (default all required types)
    core.governance.branch_managers   config: vacancy_param (default branch.manager_vacancy_max_days)
    core.governance.branch_staffing   —   (minimums per role: Branch roles page)
    core.finance.balance_confirmations config: max_age_param (default finance.balance_confirmation_max_age_days)
    core.finance.accrued_interest     config: tolerance_param (default finance.accrual_tolerance_pct)
    core.finance.facility_status      config: statuses (default ["default", "rescheduled"])
    core.finance.related_parties      config: item_types (default all)
    core.finance.exiting_dues         —
    core.finance.study                config: study_type (e.g. "ecl", "deferred_tax")
"""

from datetime import timedelta

from regcontrols.api import register_check, register_sweep

from . import logic, service


def _issue_rows(table, items):
    return [{'table': table, 'id': i, 'label': label, 'issue': issue} for i, label, issue in items]


@register_check('core.prudential.min_capital', name='Paid-up capital at or above the minimum')
def min_capital(ctx):
    minimum = ctx.param(ctx.config.get('min_param') or 'capital.min_paid_up')
    levels = logic.capital_levels(service.capital_events(ctx.db), ctx.as_of)
    issues = logic.capital_issues(levels, minimum)
    if not levels:
        return ctx.fail('No capital register entries (Prudential > Capital)')
    crit = [i for i in issues if i[0] in ('below_minimum', 'no_paid_up', 'paid_above_issued', 'issued_above_authorised')]
    aff = [{'table': 'pr_capital_events', 'id': (levels.get('paid_up') or {}).get('id') or 0, 'label': code, 'issue': msg}
           for code, msg in issues]
    if crit:
        return ctx.fail('; '.join(m for _, m in crit), aff)
    if issues:
        return ctx.warn('; '.join(m for _, m in issues), aff)
    return ctx.ok(f"Paid-up capital {levels['paid_up']['amount']:,.0f} meets the minimum {minimum:,.0f}")


@register_check('core.prudential.deadlines', name='Regulatory deadlines met (incl. extensions)')
def deadlines(ctx):
    cats = ctx.config.get('categories')
    rows = [d for d in service.deadlines(ctx.db) if not cats or d['category'] in cats]
    open_ = [d for d in rows if d['status'] == 'open']
    missed = [d for d in rows if d['status'] == 'missed']
    over = [d for d in open_ if d['state'] == 'overdue']
    soon = [d for d in open_ if d['state'] == 'due_soon']
    aff = _issue_rows('pr_deadlines', [(d['id'], d['title'], 'overdue') for d in over] +
                      [(d['id'], d['title'], 'missed') for d in missed] +
                      [(d['id'], d['title'], f"due in {d['days_left']} day(s)") for d in soon])
    if over or missed:
        return ctx.fail(f'{len(over)} deadline(s) overdue, {len(missed)} missed', aff)
    if soon:
        return ctx.warn(f'{len(soon)} deadline(s) inside the alert window', aff)
    if not rows:
        return ctx.not_applicable('No regulatory deadlines registered')
    return ctx.ok(f'{len(open_)} open deadline(s), none at risk')


@register_check('core.prudential.solvency', name='Solvency standards met (latest period)')
def solvency(ctx):
    cfg = ctx.config
    max_lev = ctx.param(cfg.get('max_leverage_param') or 'solvency.max_leverage_ratio')
    min_eq = ctx.param(cfg.get('min_equity_param') or 'solvency.min_equity')
    min_cb = ctx.param(cfg['min_capital_base_param']) if cfg.get('min_capital_base_param') else None
    approved = [p for p in service.periods(ctx.db) if p['status'] == 'approved' and p['period_end'] <= ctx.as_of]
    if not approved:
        return ctx.fail('No approved financial period (Prudential > Solvency)')
    p = approved[-1]
    max_age = int(cfg.get('max_age_days') or 120)
    stale = (ctx.as_of - p['period_end']).days > max_age
    br = logic.solvency_breaches(p, max_lev, min_eq, min_cb)
    aff = [{'table': 'pr_financial_periods', 'id': p['id'], 'label': str(p['period_end']), 'metric': m,
            'value': str(v) if v is not None else None, 'limit': str(lim) if lim is not None else None, 'severity': s}
           for m, v, lim, s in br]
    if br:
        crit = any(s == 'critical' for *_, s in br)
        return ctx.fail(('CRITICAL — ' if crit else '') + f"{p['period_end']}: " +
                        ', '.join(f'{m} {v} vs limit {lim}' for m, v, lim, _ in br), aff)
    if stale:
        return ctx.warn(f"Latest approved period {p['period_end']} is older than {max_age} days")
    r = p['ratios']
    return ctx.ok(f"{p['period_end']}: equity {r['equity']:,.0f}, leverage {r['leverage']}x (limit {max_lev}x)")


@register_check('core.governance.registered_address', name='Registered address consistent on official documents')
def registered_address(ctx):
    prof = service.profile(ctx.db)
    if not service.registered_addresses(prof):
        return ctx.fail('Registered address not set in the corporate profile (Prudential > Corporate profile)')
    docs = service.documents(ctx.db)
    bad = [d for d in docs if d['address_ok'] is False]
    unknown = [d for d in docs if d['address_ok'] is None]
    aff = _issue_rows('pr_documents', [(d['id'], d['title'], f"address: {d['address_on_document']}") for d in bad])
    if bad:
        return ctx.fail(f'{len(bad)} document(s) state an address different from the registered address', aff)
    if unknown:
        return ctx.warn(f'{len(unknown)} document(s) without the stated address recorded',
                        _issue_rows('pr_documents', [(d['id'], d['title'], 'address not recorded') for d in unknown]))
    return ctx.ok(f'{len(docs)} document(s) consistent with the registered address' if docs
                  else 'Registered address set; no documents registered yet')


@register_check('core.governance.key_functions', name='Key functions filled, fit & proper and notified')
def key_functions(ctx):
    only = ctx.config.get('functions')
    rows = [m for m in service.key_function_matrix(ctx.db) if not only or m['type']['code'] in only]
    bad = [m for m in rows if any(c not in ('fit_proper_pending',) for c, _ in m['issues'])]
    pend = [m for m in rows if m['issues'] and m not in bad]
    aff = [{'table': 'pr_key_functions', 'id': (m['holder'] or {}).get('id') or 0, 'label': m['type']['name_en'],
            'issue': '; '.join(x for _, x in m['issues'])} for m in bad + pend]
    if bad:
        return ctx.fail(f'{len(bad)} key function(s) vacant, not notified or without no-objection', aff)
    if pend:
        return ctx.warn(f'{len(pend)} key function(s) with fit & proper pending', aff)
    return ctx.ok(f'{len(rows)} key function(s) filled and notified')


@register_check('core.governance.branch_managers', name='Branch managers appointed with no-objection')
def branch_managers(ctx):
    max_days = ctx.param(ctx.config.get('vacancy_param') or 'branch.manager_vacancy_max_days')
    rows = [b for b in service.branches(ctx.db) if b['status'] == 'active']
    if not rows:
        return ctx.not_applicable('No active branches registered')
    bad, warn = [], []
    for b in rows:
        for code, msg in logic.branch_issues(b, ctx.as_of, max_days):
            (warn if code == 'vacancy_within_limit' else bad).append((b['id'], f"{b['code']} {b['name_en']}", msg))
    if bad:
        return ctx.fail(f'{len(bad)} branch(es) without an approved manager', _issue_rows('pr_branches', bad + warn))
    if warn:
        return ctx.warn(f'{len(warn)} branch manager post(s) vacant within the {max_days}-day limit',
                        _issue_rows('pr_branches', warn))
    return ctx.ok(f'{len(rows)} active branch(es) with an approved manager')


@register_check('core.governance.branch_staffing', name='Minimum staffing per branch')
def branch_staffing(ctx):
    roles = [r for r in service.branch_roles(ctx.db) if r.get('is_active')]
    # a role whose minimum is a parameter makes the run an error while the value is not set
    mins = {r['code']: (ctx.param(r['param_key']) if r.get('param_key') else r.get('min_count')) for r in roles}
    br = [b for b in service.branches(ctx.db) if b['status'] == 'active']
    if not br:
        return ctx.not_applicable('No active branches registered')
    gaps = logic.staffing_gaps(br, roles, service.staffing(ctx.db), mins)
    if gaps:
        return ctx.fail(f'{len(gaps)} staffing gap(s)', [{'table': 'pr_branches', 'id': b['id'], 'label': b['code'],
                                                          'role': r['code'], 'have': have, 'need': need}
                                                         for b, r, have, need in gaps])
    return ctx.ok(f'{len(br)} active branch(es) meet the minimum staffing')


@register_check('core.finance.balance_confirmations', name='Recent balance confirmations for facilities')
def balance_confirmations(ctx):
    max_age = ctx.param(ctx.config.get('max_age_param') or 'finance.balance_confirmation_max_age_days')
    rows = [f for f in service.facilities(ctx.db) if f['status'] != 'closed']
    if not rows:
        return ctx.not_applicable('No open facilities registered')
    bad = [(f['id'], f"{f['reference']} {f['lender_name']}", logic.confirmation_issue(f, ctx.as_of, max_age))
           for f in rows]
    bad = [b for b in bad if b[2]]
    if bad:
        return ctx.fail(f'{len(bad)} facility(ies) without a recent balance confirmation', _issue_rows('pr_facilities', bad))
    return ctx.ok(f'{len(rows)} facility(ies) confirmed within {max_age} days')


@register_check('core.finance.accrued_interest', name='Accrued interest calculated and booked')
def accrued_interest(ctx):
    tol = ctx.param(ctx.config.get('tolerance_param') or 'finance.accrual_tolerance_pct')
    rows = [f for f in service.facilities(ctx.db) if f['status'] != 'closed' and (f.get('interest_rate_pct') or 0) > 0]
    if not rows:
        return ctx.not_applicable('No interest-bearing facilities registered')
    bad = []
    for f in rows:
        g = logic.accrual_gap(f, tol)
        label = f"{f['reference']} {f['lender_name']}"
        if g is None:
            bad.append((f['id'], label, 'accrual not measurable (accrual start / booked-as-of date missing)'))
        elif g['breach']:
            bad.append((f['id'], label, f"expected {g['expected']:,.2f}, booked {g['booked']:,.2f}"))
    if bad:
        return ctx.fail(f'{len(bad)} facility(ies) with accrued interest missing or off by more than {tol}%',
                        _issue_rows('pr_facilities', bad))
    return ctx.ok(f'Accrued interest booked for {len(rows)} facility(ies) within {tol}%')


@register_check('core.finance.facility_status', name='Lender defaults and reschedulings escalated and approved')
def facility_status(ctx):
    sts = ctx.config.get('statuses')          # e.g. ["default"] or ["rescheduled"]; default both
    rows = [f for f in service.facilities(ctx.db)
            if not sts or f['status'] in sts or ('default' in sts and f.get('covenant_breach'))]
    bad = [(f['id'], f"{f['reference']} {f['lender_name']}", '; '.join(logic.facility_status_issues(f))) for f in rows]
    bad = [b for b in bad if b[2]]
    if bad:
        return ctx.fail(f'{len(bad)} facility(ies) in default/rescheduled without board escalation or approval',
                        _issue_rows('pr_facilities', bad))
    n = sum(1 for f in rows if f['status'] in ('default', 'rescheduled') or f['covenant_breach'])
    return ctx.ok(f'{n} facility(ies) in default/rescheduled, all escalated and approved' if n
                  else 'No facility in default or rescheduled')


@register_check('core.finance.related_parties', name='Related-party items attributed and documented')
def related_parties(ctx):
    types = ctx.config.get('item_types')
    rows = [r for r in service.rp_review(ctx.db) if not types or r['item']['item_type'] in types]
    if not rows:
        return ctx.not_applicable('No related-party items registered')
    bad = [(r['item']['id'], f"{r['item']['party_name']} · {r['item']['item_type']} {r['item']['amount']:,.0f}",
            '; '.join(r['issues'])) for r in rows if any('exiting shareholder' not in i for i in r['issues'])]
    if bad:
        return ctx.fail(f'{len(bad)} related-party item(s) misattributed or undocumented', _issue_rows('pr_rp_items', bad))
    return ctx.ok(f'{len(rows)} related-party item(s) attributed to the right party and documented')


@register_check('core.finance.exiting_dues', name="Exiting shareholders' dues classified as liabilities")
def exiting_dues(ctx):
    rows = [r for r in service.rp_review(ctx.db) if r['item']['relation'] == 'exiting_shareholder']
    if not rows:
        return ctx.not_applicable('No items for exiting shareholders')
    bad = [(r['item']['id'], r['item']['party_name'], 'not classified as a liability') for r in rows
           if any('exiting shareholder' in i for i in r['issues'])]
    if bad:
        return ctx.fail(f'{len(bad)} due(s) to exiting shareholders not classified as liabilities',
                        _issue_rows('pr_rp_items', bad))
    return ctx.ok(f'{len(rows)} item(s) for exiting shareholders correctly classified')


@register_check('core.finance.study', name='Approved and current study (ECL, deferred tax …)')
def study(ctx):
    st = ctx.config.get('study_type')
    if not st:
        return ctx.warn('No study_type in this control\'s check settings')
    issue = logic.study_issue(service.studies(ctx.db, st), ctx.as_of)
    if issue:
        return ctx.fail(f'{st}: {issue}')
    return ctx.ok(f'{st}: approved study in force')


@register_sweep()
def prudential_sweep():
    """Countdown notifications and board escalation for regulatory deadlines."""
    return service.deadline_sweep()
