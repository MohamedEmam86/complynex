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
Generic AML/KYC checks for the regcontrols engine. Any framework binds its
controls to these keys and tunes them through the control's check_config;
regulatory cycles and thresholds come from parameters.

    core.aml.role_independence      config: role_codes (default ["mlro"])
    core.aml.role_conflicts         config: role_codes
    core.aml.combined_roles         config: role_codes
    core.aml.monitoring_programme   —
    core.aml.unusual_register       reconciliation against registered expected sources
    core.aml.unusual_studied        study SLA and documented decision
    core.aml.annual_report          config: role_code, approve_by_month (default 6)
    core.audit.red_flags_routed     internal-audit AML red flags reach the register
    core.audit.plan_coverage        config: criticality (default ["critical", "high"])
    core.policies.board_approval    config: max_days_param, name_contains
    core.screening.required_sources config: required [{label, match: [...]}]
    core.screening.source_freshness config: required (optional), max_age_param
    core.screening.qa_recall        config: max_age_days (31), min_recall_param
    core.screening.employees        config: months_param
    core.kyc.fields                 config: subjects, fields
    core.kyc.beneficial_owners      config: subjects
    core.kyc.bo_declaration         config: subjects, kinds
    core.kyc.refresh_cycle          config: subjects
    core.kyc.risk_model             —
    core.kyc.rated                  config: subjects
    core.kyc.edd_high_risk          config: subjects
    core.training.coverage          config: course_ids | category, target_param, window_months
"""

from datetime import date, datetime, timedelta

from regcontrols.api import register_check, register_sweep

from . import logic, service, subjects


def _as_date(value):
    """policies.updated_at/created_at are TEXT columns ('2026-10-01 09:00:00');
    other tables give datetime/date. None when it cannot be read."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _roles(ctx):
    codes = ctx.config.get('role_codes') or ['mlro']
    return codes, [service.effective_role(r) for r in service.key_roles(ctx.db) if r['role_code'] in codes]


@register_check('core.aml.role_independence', name='Key AML role independent (reporting line)')
def role_independence(ctx):
    codes, roles = _roles(ctx)
    if not roles:
        return ctx.fail(f'No holder registered for: {", ".join(codes)} (AML assurance > Key roles)')
    rules = service.conflict_rules(ctx.db)
    bad, warn = [], []
    for r in roles:
        c = [x for x in logic.role_conflicts(r, rules) if x[0] == 'reports_to']
        rec = {'table': 'aml_key_roles', 'id': r['id'], 'label': f"{r['role_code']} — {r.get('holder_name') or r.get('holder_user_name') or '?'}",
               'reports_to': r.get('reports_to_title') or ''}
        if c:
            bad.append(dict(rec, conflict='; '.join(f'{k}: {reason}' for _, k, reason in c)))
        elif not r.get('reports_to_board'):
            warn.append(dict(rec, conflict='no direct reporting line to the board recorded'))
    if bad:
        return ctx.fail(f'{len(bad)} key role(s) report to a conflicting position', bad + warn)
    if warn:
        return ctx.warn(f'{len(warn)} key role(s) without a recorded board reporting line', warn)
    return ctx.ok('Reporting lines independent; board reporting recorded')


@register_check('core.aml.role_conflicts', name='No conflicting positions for key AML roles')
def role_conflicts(ctx):
    codes, roles = _roles(ctx)
    if not roles:
        return ctx.fail(f'No holder registered for: {", ".join(codes)}')
    rules = service.conflict_rules(ctx.db)
    bad = []
    for r in roles:
        c = [x for x in logic.role_conflicts(r, rules) if x[0] == 'holds']
        if c:
            bad.append({'table': 'aml_key_roles', 'id': r['id'], 'label': r['role_code'],
                        'positions': r.get('other_positions'), 'conflict': '; '.join(f'{k}: {reason}' for _, k, reason in c)})
    return ctx.fail(f'{len(bad)} key role(s) hold conflicting positions', bad) if bad else ctx.ok('No conflicting positions')


@register_check('core.aml.combined_roles', name='Combined roles approved')
def combined_roles(ctx):
    codes, roles = _roles(ctx)
    bad = [{'table': 'aml_key_roles', 'id': r['id'], 'label': r['role_code'], 'positions': r.get('other_positions')}
           for r in roles if logic.combined_role_unapproved(r)]
    if bad:
        return ctx.fail(f'{len(bad)} combined role(s) without an approval reference', bad)
    return ctx.ok('Combined roles have an approval reference' if roles else 'No combined roles registered')


@register_check('core.policies.board_approval', name='Policies board-approved')
def policy_board_approval(ctx):
    max_days = ctx.param(ctx.config.get('max_days_param') or 'policy.max_days_pending_board_approval')
    words = [w.lower() for w in ctx.config.get('name_contains') or []]
    rows = service.board_policies(ctx.db)
    scope = [p for p in rows if p['requires_board_approval'] or
             (words and any(w in (p['policy_name'] or '').lower() for w in words))]
    if not scope:
        return ctx.warn('No policy is marked as requiring board approval (AML assurance > Board approvals)')
    today = ctx.as_of
    bad = []
    for p in scope:
        if p['board_approved_on']:
            continue
        since = _as_date(p.get('updated_at') or p.get('created_at'))
        age = (today - since).days if since else None
        rec = {'table': 'policies', 'id': p['id'], 'label': f"{p['policy_number'] or ''} {p['policy_name']}".strip(),
               'status': p['status'], 'days_waiting': age}
        if age is None or age > int(max_days):
            bad.append(rec)
    if bad:
        return ctx.fail(f'{len(bad)} policy(ies) not board-approved within {max_days} days', bad)
    return ctx.ok(f'{len(scope)} board-level policy(ies) approved or within {max_days} days')


@register_check('core.aml.monitoring_programme', name='AML monitoring programme on track')
def monitoring(ctx):
    year = ctx.as_of.year
    plan = ctx.db.execute("SELECT * FROM aml_monitoring_plans WHERE plan_year = %s", (year,)).fetchone()
    if not plan:
        return ctx.fail(f'No AML monitoring plan for {year}')
    rv = service.reviews(plan['id'], ctx.db)
    if not rv:
        return ctx.fail(f'The {year} plan has no reviews scheduled')
    late = logic.monitoring_gaps(rv, ctx.as_of)
    if late:
        return ctx.fail(f'{len(late)} planned review(s) overdue',
                        [{'table': 'aml_monitoring_reviews', 'id': r['id'], 'label': r['unit_label'],
                          'planned': str(r['planned_date'])} for r in late])
    done = sum(1 for r in rv if r['status'] == 'done')
    return ctx.ok(f'{done} of {len(rv)} planned review(s) done; none overdue')


@register_check('core.screening.required_sources', name='Required watchlist sources configured and loaded')
def required_sources(ctx):
    req = ctx.config.get('required') or []
    if not req:
        return ctx.warn('No required sources configured in this control\'s check settings')
    st = service.source_status(service.screening_sources(ctx.db), req)
    bad = [s for s in st if not s['loaded']]
    aff = [{'table': 'screening_data_sources', 'id': 0, 'label': s['label'],
            'issue': 'not configured' if not s['configured'] else 'never loaded'} for s in bad]
    if bad:
        return ctx.fail(f'{len(bad)} required list source(s) missing or never loaded', aff)
    return ctx.ok(f'All {len(st)} required list sources configured and loaded')


@register_check('core.screening.source_freshness', name='Watchlists up to date')
def source_freshness(ctx):
    hours = ctx.param(ctx.config.get('max_age_param') or 'aml.watchlist_freshness_max_hours')
    sources = service.screening_sources(ctx.db)
    req = ctx.config.get('required') or [{'label': s['name'], 'match': [s['name']]} for s in sources
                                         if s.get('is_active') not in (False, 0)]
    st = service.source_status(sources, req, hours, datetime.combine(ctx.as_of, datetime.max.time()))
    stale = [s for s in st if not s['fresh']]
    if stale:
        return ctx.fail(f'{len(stale)} list source(s) older than {hours} hours',
                        [{'table': 'screening_data_sources', 'id': 0, 'label': s['label'], 'last_update': s['last_update']}
                         for s in stale])
    return ctx.ok(f'{len(st)} list source(s) updated within {hours} hours')


@register_check('core.screening.qa_recall', name='Name matching tested (QA recall)')
def qa_recall(ctx):
    target = ctx.param(ctx.config.get('min_recall_param') or 'aml.screening_min_recall_pct')
    run = service.last_qa_run(ctx.db)
    max_age = int(ctx.config.get('max_age_days') or 31)
    if not run:
        return ctx.fail('The screening QA test set has never been run (AML assurance > Screening QA)')
    if run['error']:
        return ctx.fail(f"Last QA run failed: {run['error']}")
    age = (ctx.as_of - run['run_at'].date()).days
    misses = [d for d in (run['details'] or []) if d['expect_match'] and not d['found']]
    aff = [{'table': 'screening_qa_cases', 'id': d['case_id'], 'label': d['query'], 'expected': d['expected'],
            'variant': d['variant']} for d in misses]
    if run['recall_pct'] is None:
        return ctx.fail('The QA test set has no positive cases')
    if float(run['recall_pct']) < float(target) or misses:
        return ctx.fail(f"Recall {run['recall_pct']}% (target {target}%): {len(misses)} miss(es)", aff,
                        precision=str(run['precision_pct']))
    if age > max_age:
        return ctx.warn(f'Last QA run is {age} days old (run at least every {max_age} days)')
    return ctx.ok(f"Recall {run['recall_pct']}%, precision {run['precision_pct']}% ({run['cases']} cases)")


@register_check('core.screening.employees', name='Employees screened')
def employees(ctx):
    months = ctx.param(ctx.config.get('months_param') or 'aml.employee_rescreen_months')
    rows = service.employees_due(months, ctx.db, ctx.as_of)
    due = [r for r in rows if r['due']]
    hits = [r for r in rows if r['last_hits']]
    aff = [{'table': 'users', 'id': r['id'], 'label': f"{r['first_name']} {r['last_name']}",
            'last_screened': str(r['last_screened'] or 'never')} for r in due]
    aff += [{'table': 'users', 'id': r['id'], 'label': f"{r['first_name']} {r['last_name']}", 'issue': 'open match'}
            for r in hits]
    if due or hits:
        return ctx.fail(f'{len(due)} employee(s) not screened within {months} months; {len(hits)} with matches', aff)
    return ctx.ok(f'All {len(rows)} active employees screened within {months} months')


@register_check('core.aml.unusual_register', name='Unusual-transactions register complete')
def unusual_register(ctx):
    missing = service.reconcile_register(ctx.db)
    if missing:
        return ctx.fail(f'{len(missing)} detected event(s) not in the unusual-transactions register',
                        [dict(m, table=m['table'], label=m['label']) for m in missing])
    if not service.EXPECTED_SOURCES:
        return ctx.ok('Register reconciled (no detection sources registered by modules)')
    return ctx.ok(f'Register reconciled against {len(service.EXPECTED_SOURCES)} detection source(s)')


@register_check('core.aml.unusual_studied', name='Unusual transactions studied and documented')
def unusual_studied(ctx):
    rows = service.unusual_list(db=ctx.db)
    late = [r for r in rows if logic.study_overdue(r, ctx.as_of)]
    undocumented = [r for r in rows if r['status'] in ('str_filed', 'no_str') and not (r.get('analysis') or '').strip()]
    open_no_sla = [r for r in rows if r['status'] in ('candidate', 'under_study') and not r.get('study_due_date')]
    aff = [{'table': 'aml_unusual_transactions', 'id': r['id'], 'label': r['reference'], 'issue': 'study overdue',
            'due': str(r['study_due_date'])} for r in late]
    aff += [{'table': 'aml_unusual_transactions', 'id': r['id'], 'label': r['reference'], 'issue': 'decision without analysis'}
            for r in undocumented]
    if late or undocumented:
        return ctx.fail(f'{len(late)} study(ies) overdue, {len(undocumented)} decision(s) undocumented', aff)
    if open_no_sla:
        return ctx.warn(f'{len(open_no_sla)} open item(s) without a study deadline (set aml.unusual_txn_study_sla_days)')
    return ctx.ok(f'{sum(1 for r in rows if r["status"] in ("candidate", "under_study"))} open item(s), none overdue')


@register_check('core.audit.red_flags_routed', name='Internal-audit AML red flags studied')
def red_flags(ctx):
    try:
        rows = [dict(r) for r in ctx.db.execute("""
            SELECT af.id, af.finding_number, af.finding_title,
                   (SELECT u.status FROM aml_unusual_transactions u WHERE u.source_table = 'audit_findings'
                      AND u.source_record_id = af.id LIMIT 1) AS register_status
            FROM audit_findings af WHERE af.aml_red_flag""").fetchall()]
    except Exception:
        ctx.db.rollback()
        return ctx.not_applicable('Internal audit module not installed')
    missing = [r for r in rows if r['register_status'] is None]
    if missing:
        return ctx.fail(f'{len(missing)} AML red flag(s) from internal audit not in the register',
                        [{'table': 'audit_findings', 'id': r['id'], 'label': r['finding_number']} for r in missing])
    return ctx.ok(f'{len(rows)} red flag(s) routed to the register')


@register_check('core.aml.annual_report', name='Annual AML report approved by the board')
def annual_report(ctx):
    role = ctx.config.get('role_code') or 'mlro'
    by_month = int(ctx.config.get('approve_by_month') or 6)
    year = ctx.as_of.year - 1
    r = ctx.db.execute("SELECT * FROM aml_annual_reports WHERE report_year = %s AND role_code = %s", (year, role)).fetchone()
    if r and r['status'] == 'approved':
        return ctx.ok(f"{year} report approved by the board on {r['board_approved_on']}")
    if ctx.as_of.month <= by_month:
        return ctx.warn(f'{year} report not yet board-approved (due by month {by_month})')
    return ctx.fail(f'{year} annual report not board-approved' + (f" (status {r['status']})" if r else ' (not generated)'))


@register_check('core.audit.plan_coverage', name='Internal audit plan covers the control library')
def plan_coverage(ctx):
    cov = service.audit_coverage(ctx.as_of.year, ctx.db)
    crit = tuple(ctx.config.get('criticality') or ('critical', 'high'))
    gaps = logic.audit_coverage(cov['controls'], cov['covered'], crit)
    if not cov['controls']:
        return ctx.not_applicable('No active controls')
    if gaps:
        return ctx.fail(f'{len(gaps)} {"/".join(crit)} control(s) not covered by the {cov["year"]} audit plan',
                        [{'table': 'rc_controls', 'id': c['id'], 'label': c['control_code']} for c in gaps[:500]])
    return ctx.ok(f'All {"/".join(crit)} controls covered by the {cov["year"]} audit plan')


def _subjects(ctx):
    return [s for s in (ctx.config.get('subjects') or list(subjects.SUBJECTS)) if s in subjects.SUBJECTS]


@register_check('core.kyc.fields', name='KYC / KYB mandatory fields complete')
def kyc_fields(ctx):
    only = ctx.config.get('fields')
    bad, not_captured = [], set()
    total = 0
    for sub in _subjects(ctx):
        s = subjects.SUBJECTS[sub]
        flds = service.fields(sub, ctx.db)
        profs = service.profiles(sub, ctx.db)
        for r in subjects.rows(sub, ctx.db):
            if not s.active(r):
                continue
            st = service.file_status(sub, r, profs.get(r['id'], {}), flds, only=only)
            if not st['required']:
                continue
            total += 1
            if st['missing']:
                not_captured.update(st['not_captured'])
                bad.append({'table': s.table, 'id': r['id'], 'label': s.name(r), 'missing': ', '.join(st['missing'])})
    if bad:
        return ctx.fail(f'{len(bad)} of {total} file(s) incomplete', bad,
                        not_captured_by_system=', '.join(sorted(not_captured)) or None)
    return ctx.ok(f'{total} file(s) complete for the required fields') if total else \
        ctx.not_applicable('No active records for these fields')


def _entities(ctx, kinds=('entity',)):
    for sub in _subjects(ctx):
        s = subjects.SUBJECTS[sub]
        for r in subjects.rows(sub, ctx.db):
            if s.active(r) and s.kind(r) in kinds:
                yield sub, s, r


@register_check('core.kyc.beneficial_owners', name='Beneficial owners identified')
def beneficial_owners(ctx):
    bad, total = [], 0
    for sub, s, r in _entities(ctx):
        total += 1
        n = ctx.db.execute("SELECT count(*) AS n FROM kyc_beneficial_owners WHERE subject = %s AND subject_id = %s",
                           (sub, r['id'])).fetchone()['n']
        legacy = (r.get('ubo_name') or '').strip()
        if not n and not legacy:
            bad.append({'table': s.table, 'id': r['id'], 'label': s.name(r)})
    if bad:
        return ctx.fail(f'{len(bad)} of {total} entity file(s) without beneficial owners', bad)
    return ctx.ok(f'{total} entity file(s) with beneficial owners') if total else ctx.not_applicable('No active entities')


@register_check('core.kyc.bo_declaration', name='Signed beneficial-owner declaration')
def bo_declaration(ctx):
    kinds = tuple(ctx.config.get('kinds') or ('individual', 'entity'))
    bad, total = [], 0
    have = {(r['subject'], r['subject_id']) for r in ctx.db.execute(
        "SELECT DISTINCT subject, subject_id FROM kyc_bo_declarations").fetchall()}
    for sub, s, r in _entities(ctx, kinds):
        total += 1
        if (sub, r['id']) not in have:
            bad.append({'table': s.table, 'id': r['id'], 'label': s.name(r)})
    if bad:
        return ctx.fail(f'{len(bad)} of {total} file(s) without a signed beneficial-owner declaration', bad)
    return ctx.ok(f'{total} file(s) with a declaration') if total else ctx.not_applicable('No active records')


@register_check('core.kyc.refresh_cycle', name='KYC refreshed by risk level')
def refresh_cycle(ctx):
    for b in service.risk_bands(ctx.db):
        if b.get('refresh_param_key'):
            ctx.param(b['refresh_param_key'])
    rows = [dict(r) for r in ctx.db.execute("SELECT * FROM kyc_risk_ratings WHERE is_current").fetchall()]
    late = [r for r in rows if r['subject'] in _subjects(ctx) and logic.review_overdue(r, ctx.as_of)]
    if late:
        return ctx.fail(f'{len(late)} KYC review(s) overdue',
                        [{'table': 'kyc_risk_ratings', 'id': r['id'], 'label': f"{r['subject']} #{r['subject_id']}",
                          'band': r['band'], 'due': str(r['next_review_date'])} for r in late])
    return ctx.ok(f'{len(rows)} current rating(s), none overdue for review')


@register_check('core.kyc.risk_model', name='Multi-factor risk model')
def risk_model(ctx):
    gaps = logic.model_gaps(service.risk_factors(ctx.db))
    if gaps:
        return ctx.fail('Risk model has no active factor for: ' + ', '.join(gaps))
    return ctx.ok('Risk model covers customer, geography, product, channel, PEP and behaviour')


@register_check('core.kyc.rated', name='Risk rating before approval and during the relationship')
def rated(ctx):
    bad, total = [], 0
    for sub in _subjects(ctx):
        s = subjects.SUBJECTS[sub]
        ratings = {r['subject_id']: dict(r) for r in ctx.db.execute(
            "SELECT * FROM kyc_risk_ratings WHERE subject = %s AND is_current", (sub,)).fetchall()}
        first = {r['subject_id']: r['first'] for r in ctx.db.execute(
            "SELECT subject_id, min(rated_at) AS first FROM kyc_risk_ratings WHERE subject = %s GROUP BY subject_id",
            (sub,)).fetchall()}
        onb = {r['subject_id']: dict(r) for r in ctx.db.execute(
            "SELECT * FROM kyc_onboarding WHERE subject = %s AND status = 'approved'", (sub,)).fetchall()}
        for r in subjects.rows(sub, ctx.db):
            if not s.active(r):
                continue
            total += 1
            o = onb.get(r['id'])
            if r['id'] not in ratings:
                bad.append({'table': s.table, 'id': r['id'], 'label': s.name(r), 'issue': 'no risk rating'})
            elif o and o.get('approved_at') and first.get(r['id']) and first[r['id']] > o['approved_at']:
                bad.append({'table': s.table, 'id': r['id'], 'label': s.name(r), 'issue': 'rated only after approval'})
    if bad:
        return ctx.fail(f'{len(bad)} of {total} active relationship(s) not properly rated', bad)
    return ctx.ok(f'{total} active relationship(s) rated') if total else ctx.not_applicable('No active records')


@register_check('core.kyc.edd_high_risk', name='EDD and senior approval for high risk')
def edd(ctx):
    bad = []
    for sub in _subjects(ctx):
        for r in ctx.db.execute("""SELECT k.subject_id, o.edd_completed, o.senior_approved_by FROM kyc_risk_ratings k
                                   LEFT JOIN kyc_onboarding o ON o.subject = k.subject AND o.subject_id = k.subject_id
                                   WHERE k.subject = %s AND k.is_current AND k.band = 'high'""", (sub,)).fetchall():
            issues = [x for x, ok in (('EDD not completed', r['edd_completed']),
                                      ('no senior approval', r['senior_approved_by'])) if not ok]
            if issues:
                bad.append({'table': subjects.SUBJECTS[sub].table, 'id': r['subject_id'], 'label': f'{sub} #{r["subject_id"]}',
                            'issue': ', '.join(issues)})
    return ctx.fail(f'{len(bad)} high-risk relationship(s) without full EDD', bad) if bad else \
        ctx.ok('All high-risk relationships have EDD and senior approval')


@register_check('core.training.coverage', name='Training coverage by department')
def training(ctx):
    target = ctx.param(ctx.config.get('target_param') or 'training.aml_coverage_target_pct')
    cov, people, done = service.training_coverage(ctx.config.get('course_ids'), ctx.config.get('category'),
                                                  ctx.config.get('window_months'), ctx.db)
    if not people:
        return ctx.not_applicable('No active users')
    below = {g: v for g, v in cov.items() if v[2] < float(target)}
    overall = round(100 * len(done & {p['id'] for p in people}) / len(people), 1)
    if below:
        return ctx.fail(f'{len(below)} department(s) below {target}% (overall {overall}%)',
                        [{'table': 'departments', 'id': 0, 'label': g, 'completed': c, 'staff': t, 'pct': pct}
                         for g, (c, t, pct) in sorted(below.items())], overall_pct=overall)
    return ctx.ok(f'All departments at or above {target}% (overall {overall}%)', overall_pct=overall)


@register_sweep
def amlkyc_sweep():
    """Route internal-audit AML red flags to the unusual-transactions register."""
    return {'red_flags_routed': service.route_audit_red_flags()}
