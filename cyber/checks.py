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
Generic IT / cyber / business-continuity checks for the regcontrols engine.
Any framework binds its controls to these keys and tunes them through the
control's check_config; ages and windows come from parameters.

    core.cyber.dr_readiness        config: max_age_param (default it.dr_test_max_age_months)
    core.cyber.offsite_backup      config: max_age_param (default it.offsite_backup_max_age_days)
    core.cyber.integration         config: codes [..] (required), max_age_hours (default 24)
    core.cyber.assessment          config: types [..] (e.g. ["pentest", "malware_test"]), max_open_critical (0)
    core.cyber.security_assets     config: types [..] (e.g. ["waf"]), warn_param (default it.licence_expiry_warning_days)
    core.cyber.data_residency      config: types [..] (e.g. ["epp", "edr"])
    core.cyber.tls_certificates    config: warn_param (default it.ssl_expiry_warning_days)
    core.cyber.maturity            config: frameworks [codes], max_age_months (12), min_avg (optional)
    core.risk.register_fresh       config: categories (default ["TEC"]), max_age_param (default it.risk_register_max_age_days)
"""

from datetime import datetime

from dateutil.relativedelta import relativedelta

from regcontrols.api import register_check, register_sweep

from . import resilience as svc
from . import resilience_logic as logic


def _aff(table, items):
    return [{'table': table, 'id': i, 'label': label, 'issue': issue} for i, label, issue in items]


@register_check('core.cyber.dr_readiness', name='Backup / DR site in place and tested')
def dr_readiness(ctx):
    months = ctx.param(ctx.config.get('max_age_param') or 'it.dr_test_max_age_months')
    issues = logic.dr_issues(svc.sites(ctx.db), svc.dr_tests(ctx.db), ctx.as_of, months)
    if issues:
        return ctx.fail('; '.join(issues))
    return ctx.ok(f'DR site tested within {months} months')


@register_check('core.cyber.offsite_backup', name='Off-site, encrypted, recent backups')
def offsite_backup(ctx):
    days = ctx.param(ctx.config.get('max_age_param') or 'it.offsite_backup_max_age_days')
    rows = [b for b in svc.backups(ctx.db) if b['is_active']]
    if not rows:
        return ctx.fail('No backup registered (IT resilience > Backups)')
    now = datetime.combine(ctx.as_of, datetime.max.time())
    bad = [(b['id'], b['system_name'], '; '.join(logic.backup_issues(b, now, days))) for b in rows]
    bad = [x for x in bad if x[2]]
    if bad:
        return ctx.fail(f'{len(bad)} of {len(rows)} system(s) without a recent off-site encrypted backup',
                        _aff('cy_backups', bad))
    return ctx.ok(f'{len(rows)} system(s) backed up off-site within {days} day(s)')


@register_check('core.cyber.integration', name='Required external integrations live')
def integration(ctx):
    codes = ctx.config.get('codes') or []
    if not codes:
        return ctx.warn('No integration codes in this control\'s check settings')
    have = {i['code']: i for i in svc.integrations(ctx.db)}
    hours = ctx.config.get('max_age_hours', 24)
    bad = []
    for c in codes:
        i = have.get(c)
        issue = 'not registered' if not i else logic.integration_issue(i, datetime.now(), hours)
        if issue:
            bad.append((i['id'] if i else 0, c, issue))
    if bad:
        return ctx.fail(f'{len(bad)} required integration(s) not live', _aff('cy_integrations', bad))
    return ctx.ok(f'{len(codes)} required integration(s) live')


@register_check('core.cyber.assessment', name='Security assessments current and accepted')
def assessment(ctx):
    types = ctx.config.get('types') or []
    if not types:
        return ctx.warn('No assessment types in this control\'s check settings')
    maxc = ctx.config.get('max_open_critical', 0)
    bad = [(0, t, logic.assessment_issue(svc.assessments(ctx.db, t), ctx.as_of, maxc)) for t in types]
    bad = [b for b in bad if b[2]]
    if bad:
        return ctx.fail('; '.join(f'{t}: {i}' for _, t, i in bad), _aff('cy_assessments', bad))
    return ctx.ok(f"Accepted, valid assessment on file for: {', '.join(types)}")


def _assets(ctx):
    types = ctx.config.get('types') or []
    return types, [a for a in svc.assets(ctx.db) if a['is_active'] and (not types or a['asset_type'] in types)]


@register_check('core.cyber.security_assets', name='Security tools in place with valid licences')
def security_assets(ctx):
    warn_days = ctx.param(ctx.config.get('warn_param') or 'it.licence_expiry_warning_days', default=30)
    types, rows = _assets(ctx)
    missing = [t for t in types if not any(a['asset_type'] == t for a in rows)]
    states = [(a, logic.asset_state(a, ctx.as_of, warn_days)) for a in rows]
    bad = [(a['id'], f"{a['asset_type']} {a['product']}", s) for a, s in states if s in ('expired', 'no_licence')]
    bad += [(0, t, 'not registered') for t in missing]
    soon = [(a['id'], f"{a['asset_type']} {a['product']}", f"licence expires {a['licence_expiry']}")
            for a, s in states if s == 'expiring']
    if bad:
        return ctx.fail(f'{len(bad)} security tool(s) missing or without a valid licence', _aff('cy_security_assets', bad + soon))
    if soon:
        return ctx.warn(f'{len(soon)} licence(s) expiring within {warn_days} days', _aff('cy_security_assets', soon))
    return ctx.ok(f'{len(rows)} security tool(s) licensed')


@register_check('core.cyber.data_residency', name='Endpoint protection effective; no data sent abroad')
def data_residency(ctx):
    types, rows = _assets(ctx)
    missing = [t for t in types if not any(a['asset_type'] == t for a in rows)]
    bad = [(0, t, 'not registered') for t in missing]
    for a in rows:
        st = logic.asset_state(a, ctx.as_of, None)
        issue = 'licence expired' if st in ('expired', 'no_licence') else logic.residency_issue(a)
        if issue:
            bad.append((a['id'], f"{a['asset_type']} {a['product']}", issue))
    if bad:
        return ctx.fail(f'{len(bad)} issue(s): licence or data residency', _aff('cy_security_assets', bad))
    return ctx.ok(f'{len(rows)} tool(s) licensed with in-country data attested')


@register_check('core.cyber.tls_certificates', name='Valid TLS / SSL certificates on declared domains')
def tls_certificates(ctx):
    warn = ctx.param(ctx.config.get('warn_param') or 'it.ssl_expiry_warning_days')
    rows = [d for d in svc.domains(ctx.db) if d['is_active']]
    if not rows:
        return ctx.fail('No domain declared for monitoring (IT resilience > Domains)')
    states = [(d, logic.cert_state(d, datetime.now(), warn)) for d in rows]
    bad = [(d['id'], d['domain'], s + (f": {d['last_error']}" if d.get('last_error') else '')) for d, s in states
           if s in ('expired', 'error', 'unchecked')]
    soon = [(d['id'], d['domain'], f"{s}, expires {d['cert_not_after']:%Y-%m-%d}" if d.get('cert_not_after') else s)
            for d, s in states if s in ('expiring', 'stale')]
    if bad:
        return ctx.fail(f'{len(bad)} domain(s) with an invalid, expired or unchecked certificate',
                        _aff('cy_domains', bad + soon))
    if soon:
        return ctx.warn(f'{len(soon)} certificate(s) expiring within {warn} days or not re-checked',
                        _aff('cy_domains', soon))
    return ctx.ok(f'{len(rows)} domain(s) with a valid certificate (> {warn} days)')


@register_check('core.cyber.maturity', name='Framework maturity self-assessment current')
def maturity(ctx):
    codes = ctx.config.get('frameworks') or []
    months = int(ctx.config.get('max_age_months') or 12)
    rows = [a for a in svc.maturity_assessments(ctx.db) if a['status'] == 'final' and (not codes or a['framework_code'] in codes)]
    bad, gaps_total = [], 0
    for code in codes or sorted({a['framework_code'] for a in rows}):
        mine = [a for a in rows if a['framework_code'] == code]
        if not mine:
            bad.append((0, code, 'no final self-assessment'))
            continue
        cur = mine[0]
        if cur['assessed_on'] < ctx.as_of - relativedelta(months=months):
            bad.append((cur['id'], code, f"last assessed {cur['assessed_on']}"))
        summ = logic.maturity_summary(svc.maturity_scores(cur['id'], ctx.db))
        gaps_total += len(summ['gaps'])
        if ctx.config.get('min_avg') is not None and (summ['avg_current'] or 0) < float(ctx.config['min_avg']):
            bad.append((cur['id'], code, f"average maturity {summ['avg_current']} below {ctx.config['min_avg']}"))
    if not codes and not rows:
        return ctx.fail('No final maturity self-assessment')
    if bad:
        return ctx.fail('; '.join(f'{c}: {i}' for _, c, i in bad), _aff('cy_maturity_assessments', bad))
    if gaps_total:
        return ctx.warn(f'Self-assessment current; {gaps_total} requirement(s) below target maturity')
    return ctx.ok('Self-assessment current; all requirements at target')


@register_check('core.risk.register_fresh', name='Risk register (selected categories) up to date')
def register_fresh(ctx):
    days = ctx.param(ctx.config.get('max_age_param') or 'it.risk_register_max_age_days')
    rows = svc.it_risks(ctx.config.get('categories'), ctx.db)
    active = [r for r in rows if r['status'] in ('ACTIVE', 'ACCEPTED')]
    if not active:
        return ctx.fail(f"No active risk in categories {', '.join(ctx.config.get('categories') or ['TEC'])} "
                        '(Risk Management > Register)')
    bad = [(r['id'], f"{r['risk_id']} {r['risk_title']}", logic.risk_stale(r, ctx.as_of, days)) for r in active]
    bad = [b for b in bad if b[2]]
    if bad:
        return ctx.fail(f'{len(bad)} of {len(active)} risk(s) not reviewed in time', _aff('risks', bad))
    return ctx.ok(f'{len(active)} risk(s) reviewed within {days} days')


@register_sweep()
def cyber_sweep():
    """Scheduled TLS certificate checks for declared domains."""
    return svc.tls_sweep()
