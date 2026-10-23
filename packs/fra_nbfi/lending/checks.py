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
FRA NBFI pack — automated checks for the Lending Conduct & Portfolio module,
registered with the regcontrols engine under fra_nbfi.lending.* keys and
bound to the pack's FRA controls in packs/fra_nbfi/library.py (CHECK_KEYS),
plus the data sweep that runs before them (recompute days past due and file
status, credit-study QA scan, PAR snapshot and remediation plans,
prepayment/refinance AML candidates).

Checks are read-only; anything that writes happens in lending_sweep().
The file checks still filter gaps by the FRA control a gap belongs to
(logic.file_gaps), which is why the FRA codes appear here — this module is
part of the FRA pack.
"""

from datetime import date

from regcontrols.api import raise_finding, register_check, register_expected_source, register_sweep

from . import logic, service


def _as_date(value):
    """regulatory_report_submissions.due_date is TEXT ('2026-11-15'); None if unreadable."""
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _rec(l, **extra):
    return dict({'table': 'ln_loans', 'id': l['id'], 'label': l.get('loan_ref')}, **extra)


def _loans(ctx, where="l.status = 'disbursed'"):
    return [dict(r) for r in ctx.db.execute(f"""
        SELECT l.*, c.client_ref FROM ln_loans l JOIN ln_clients c ON c.id = l.client_id WHERE {where}
        ORDER BY l.loan_ref""").fetchall()]


def _has_data(ctx):
    return ctx.db.execute("SELECT EXISTS (SELECT 1 FROM ln_loans) AS x").fetchone()['x']


def _file_check(ctx, control_code, describe):
    """FRA-009/013/014/015: disbursed loans whose file has gaps for this control.
    An approved 'file_incomplete' exception downgrades the loan to a warning."""
    if not _has_data(ctx):
        return ctx.not_applicable('No lending data imported yet')
    if control_code == 'FRA-013':
        ctx.param('lending.gps_mandatory_min_amount')
    bad, excepted = [], []
    for l in _loans(ctx):
        b = service.bundle(l['id'], ctx.db)
        gaps = [g for g in service.file_gaps(b) if g[0] == control_code]
        if gaps:
            target = excepted if service.approved_exception(b, 'file_incomplete') else bad
            target.append(_rec(l, client=l['client_ref'], gap='; '.join(g[2] for g in gaps)))
    if bad:
        return ctx.fail(f'{len(bad)} disbursed loan(s) {describe}', bad + excepted, excepted=len(excepted))
    if excepted:
        return ctx.warn(f'{len(excepted)} loan(s) {describe} under an approved exception', excepted)
    return ctx.ok('All disbursed loan files complete for this requirement')


@register_check('fra_nbfi.lending.contracts_signed', name='Contracts signed by both parties')
def contracts_signed(ctx):
    return _file_check(ctx, 'FRA-009', 'with an unsigned or incomplete contract / missing required documents')


@register_check('fra_nbfi.lending.gps_recorded', name='Project GPS above threshold')
def gps_recorded(ctx):
    return _file_check(ctx, 'FRA-013', 'above the GPS threshold without coordinates')


@register_check('fra_nbfi.lending.receipt_ack', name='Receipt acknowledgement on file')
def receipt_ack(ctx):
    return _file_check(ctx, 'FRA-014', 'without the client receipt acknowledgement')


@register_check('fra_nbfi.lending.credit_study', name='Structured credit study')
def credit_study(ctx):
    return _file_check(ctx, 'FRA-015', 'without a complete credit study')


@register_check('fra_nbfi.lending.eligibility', name='Clients within licensed scope')
def eligibility(ctx):
    if not _has_data(ctx):
        return ctx.not_applicable('No lending data imported yet')
    rev, size = ctx.param('lending.max_client_monthly_revenue'), ctx.param('lending.max_project_size')
    bad, excepted = [], []
    for l in _loans(ctx, "l.status IN ('approved', 'disbursed')"):
        c = dict(ctx.db.execute("SELECT * FROM ln_clients WHERE id = %s", (l['client_id'],)).fetchone())
        br = logic.eligibility_breaches(c, max_monthly_revenue=rev, max_project_size=size)
        if br:
            b = service.bundle(l['id'], ctx.db)
            rec = _rec(l, client=c['client_ref'], breach=', '.join(f'{f} {v} > {m}' for f, v, m in br))
            (excepted if service.approved_exception(b, 'eligibility') else bad).append(rec)
    if bad:
        return ctx.fail(f'{len(bad)} loan(s) to clients above the licence ceilings', bad + excepted)
    if excepted:
        return ctx.warn(f'{len(excepted)} loan(s) above the ceilings under an approved exception', excepted)
    return ctx.ok('All clients within the licensed activity scope')


@register_check('fra_nbfi.lending.study_quality', name='Credit-study QA queue')
def study_quality(ctx):
    if not _has_data(ctx):
        return ctx.not_applicable('No lending data imported yet')
    rows = [dict(r) for r in ctx.db.execute("""
        SELECT f.*, l.loan_ref FROM ln_qa_flags f JOIN ln_loans l ON l.id = f.loan_id
        WHERE f.status IN ('open', 'confirmed') ORDER BY l.loan_ref""").fetchall()]
    if rows:
        aff = [{'table': 'ln_loans', 'id': r['loan_id'], 'label': r['loan_ref'], 'flag': r['flag_type'],
                'status': r['status'], 'detail': r['detail']} for r in rows]
        return ctx.fail(f'{len(rows)} credit-study QA flag(s) open or confirmed', aff)
    return ctx.ok('No open credit-study QA flags')


def _fee_check(ctx, code, keys, label):
    if not _has_data(ctx):
        return ctx.not_applicable('No lending data imported yet')
    for k in keys:
        ctx.param(k)
    br = service.fee_breaches(ctx.db, ctx.as_of)[code]
    if br:
        total = sum(logic.D(b['overcharge']) for b in br)
        return ctx.fail(f'{len(br)} {label} above the limit; total over-charge EGP {total}',
                        [dict(b, table='ln_loans', id=b['loan_id'], label=b['loan_ref']) for b in br],
                        total_overcharge=str(total))
    return ctx.ok(f'All {label} within the limit')


@register_check('fra_nbfi.lending.admin_fee_cap', name='Admin fee cap')
def admin_fee_cap(ctx):
    return _fee_check(ctx, 'FRA-017', ['lending.admin_fee_cap_pct'], 'admin fee(s)')


@register_check('fra_nbfi.lending.admin_fee_tiers', name='Admin fee tiers')
def admin_fee_tiers(ctx):
    return _fee_check(ctx, 'FRA-018', ['lending.admin_fee_tiers'], 'admin fee(s) (tier table)')


@register_check('fra_nbfi.lending.late_penalties', name='Late-payment penalties')
def late_penalties(ctx):
    return _fee_check(ctx, 'FRA-020', ['lending.late_penalty_rate_pct', 'lending.late_penalty_cap_pct'],
                      'late penalty(ies)')


@register_check('fra_nbfi.lending.transfer_fees', name='Instalment transfer fees')
def transfer_fees(ctx):
    return _fee_check(ctx, 'FRA-025', ['lending.transfer_fee_cap'], 'transfer fee(s)')


@register_check('fra_nbfi.lending.rescheduling_fees', name='Rescheduling fees')
def rescheduling_fees(ctx):
    return _fee_check(ctx, 'FRA-026', ['lending.rescheduling_fee_cap'], 'rescheduling fee(s)')


def _er_check(ctx, column, label):
    rows = [dict(r) for r in ctx.db.execute(f"""
        SELECT e.id, e.loan_id, l.loan_ref FROM ln_early_repayments e JOIN ln_loans l ON l.id = e.loan_id
        WHERE e.status = 'executed' AND NOT ({column})""").fetchall()]
    total = ctx.db.execute("SELECT count(*) AS n FROM ln_early_repayments WHERE status = 'executed'").fetchone()['n']
    if not total:
        return ctx.not_applicable('No executed early repayments')
    if rows:
        return ctx.fail(f'{len(rows)} of {total} early repayment(s) executed {label}',
                        [{'table': 'ln_early_repayments', 'id': r['id'], 'label': r['loan_ref']} for r in rows])
    return ctx.ok(f'All {total} early repayment(s) compliant')


@register_check('fra_nbfi.lending.er_disclosure', name='Early-repayment cost disclosure')
def er_disclosure(ctx):
    return _er_check(ctx, 'e.disclosed_at IS NOT NULL', 'without a written cost disclosure')


@register_check('fra_nbfi.lending.er_consent', name='Signed consent before early repayment')
def er_consent(ctx):
    return _er_check(ctx, 'e.consent_signed', 'without signed client consent')


@register_check('fra_nbfi.lending.er_ack', name='Client acknowledged the cost impact')
def er_ack(ctx):
    return _er_check(ctx, 'e.cost_acknowledged', 'without the client acknowledging the cost impact')


@register_check('fra_nbfi.lending.refinance', name='Prepayment followed by a costlier loan')
def refinance(ctx):
    window = ctx.param('lending.prepay_new_loan_window_days')
    ers = [dict(r) for r in ctx.db.execute("SELECT * FROM ln_early_repayments WHERE status = 'executed'").fetchall()]
    if not ers:
        return ctx.not_applicable('No executed early repayments')
    loans = [dict(r) for r in ctx.db.execute("SELECT * FROM ln_loans").fetchall()]
    refs = {l['id']: l['loan_ref'] for l in loans}
    hits = logic.costlier_refinance(ers, loans, window)
    if hits:
        aff = [{'table': 'ln_loans', 'id': h['new_loan_id'], 'label': refs[h['new_loan_id']],
                'repaid_loan': refs[h['old_loan_id']], 'days': h['days'], 'reason': h['reason']} for h in hits]
        return ctx.fail(f'{len(hits)} early repayment(s) followed by a costlier new loan within {window} days '
                        f'(registered as AML unusual-transaction candidates)', aff)
    return ctx.ok('No prepayment-to-costlier-loan pattern found')


@register_check('fra_nbfi.lending.followup', name='Post-disbursement follow-up visits')
def followup(ctx):
    if not _has_data(ctx):
        return ctx.not_applicable('No lending data imported yet')
    days = ctx.param('lending.followup_visit_days')
    loans = _loans(ctx)
    visits = [dict(r) for r in ctx.db.execute("SELECT * FROM ln_visits").fetchall()]
    missing, overdue = logic.visit_gaps(loans, visits, days, ctx.as_of)
    aff = [_rec(l, client=l['client_ref'], visit_due_by=str(dl)) for l, dl in missing]
    aff += [{'table': 'ln_visits', 'id': v['id'], 'label': f"visit planned {v['planned_date']}"} for v in overdue]
    if aff:
        return ctx.fail(f'{len(missing)} loan(s) without a follow-up visit, {len(overdue)} planned visit(s) overdue',
                        aff)
    return ctx.ok('Follow-up visits up to date')


def _par_breaches(ctx):
    threshold = ctx.param('portfolio.par30_threshold_pct')
    loans = service.active_portfolio(db=ctx.db)
    company = logic.portfolio_metrics(loans)
    branches = logic.par_by(loans, 'branch_code')
    out = []
    if company['loans'] and company['par'][30] > logic.D(threshold):
        out.append(('company', 'ALL', company['par'][30]))
    out += [('branch', k, m['par'][30]) for k, m in branches.items() if m['par'][30] > logic.D(threshold)]
    return threshold, company, out


@register_check('fra_nbfi.lending.par_threshold', name='PAR30 within threshold')
def par_threshold(ctx):
    if not _has_data(ctx):
        return ctx.not_applicable('No lending data imported yet')
    threshold, company, breaches = _par_breaches(ctx)
    aff = [{'table': 'ln_par_snapshots', 'id': 0, 'label': f'{dim} {val}', 'par30': str(p)} for dim, val, p in breaches]
    if breaches:
        return ctx.fail(f'PAR30 above {threshold}% in {len(breaches)} place(s); company PAR30 {company["par"][30]}%',
                        aff, company_par30=str(company['par'][30]))
    return ctx.ok(f'Company PAR30 {company["par"][30]}% within {threshold}%', company_par30=str(company['par'][30]))


@register_check('fra_nbfi.lending.par_remediation', name='Remediation plan for portfolio deterioration')
def par_remediation(ctx):
    """Every PAR breach must have an open remediation finding with at least
    one corrective action, re-measured this month."""
    if not _has_data(ctx):
        return ctx.not_applicable('No lending data imported yet')
    threshold, _, breaches = _par_breaches(ctx)
    if not breaches:
        return ctx.ok('No PAR breach requiring a remediation plan')
    problems = []
    for dim, val, p in breaches:
        f = ctx.db.execute("""SELECT f.id, f.reference, (SELECT count(*) FROM rc_corrective_actions a
                                WHERE a.finding_id = f.id) AS n_actions
                              FROM rc_findings f WHERE f.source = 'control_failure' AND f.source_ref = %s""",
                           (f'PAR30-{dim}-{val}',)).fetchone()
        snap = ctx.db.execute("""SELECT 1 FROM ln_par_snapshots WHERE dimension = %s AND dim_value = %s
                                 AND date_trunc('month', period) = date_trunc('month', %s::date)""",
                              (dim, val, ctx.as_of)).fetchone()
        prev = service.previous_snapshot(dim, val, date(ctx.as_of.year, ctx.as_of.month, 1), ctx.db)
        worse = prev is not None and logic.D(p) > logic.D(prev['par30'])
        issue = []
        if not f:
            issue.append('no remediation plan')
        elif not f['n_actions']:
            issue.append(f"{f['reference']} has no corrective actions")
        if not snap:
            issue.append('not re-measured this month')
        if worse:
            issue.append(f"worsening vs {prev['period']} ({prev['par30']}% → {p}%)")
        if issue:
            problems.append({'table': 'rc_findings', 'id': f['id'] if f else 0, 'label': f'{dim} {val}',
                             'par30': str(p), 'issue': '; '.join(issue)})
    if problems:
        return ctx.fail(f'{len(problems)} PAR breach(es) without an effective remediation plan', problems)
    return ctx.ok(f'{len(breaches)} PAR breach(es), each with an active remediation plan')


@register_check('fra_nbfi.lending.pricing_disclosure', name='Responsible-pricing disclosure submitted')
def pricing_disclosure(ctx):
    rows = service.disclosure_submissions(ctx.db)
    if not rows:
        return ctx.warn('No FRA-RPD submissions are scheduled in the regulatory calendar '
                        '(Regulatory Reports > FRA-RPD > generate schedule)')
    late = [r for r in rows if _as_date(r['due_date']) and _as_date(r['due_date']) < ctx.as_of
            and r['status'] not in ('submitted',)]
    if late:
        return ctx.fail(f'{len(late)} responsible-pricing disclosure(s) past due and not submitted',
                        [{'table': 'regulatory_report_submissions', 'id': r['id'], 'label': f"due {r['due_date']}",
                          'status': r['status']} for r in late])
    return ctx.ok('All due responsible-pricing disclosures submitted')


# ------------------------------------------------------------------ sweep
@register_sweep(pack='fra_nbfi')
def lending_sweep():
    """Refresh derived lending data and act on breaches (runs before the checks)."""
    from database.db import get_db
    db = get_db()
    if not db.execute("SELECT EXISTS (SELECT 1 FROM ln_loans) AS x").fetchone()['x']:
        return 'no data'
    service.refresh_dpd(db=db)
    service.refresh_all_files(db)
    qa_open = service.qa_scan(db)
    hits = service.refinance_hits(db) or []
    today = date.today()
    service.snapshot_par(today, db)
    threshold = service.param('portfolio.par30_threshold_pct')
    opened = 0
    if threshold is not None:
        loans = service.active_portfolio(db=db)
        company = logic.portfolio_metrics(loans)
        places = ([('company', 'ALL', company['par'][30])] if company['loans'] and company['par'][30] > logic.D(threshold)
                  else [])
        places += [('branch', k, m['par'][30]) for k, m in logic.par_by(loans, 'branch_code').items()
                   if m['par'][30] > logic.D(threshold)]
        for dim, val, p in places:
            raise_finding(f'PAR30 {p}% above {threshold}% — {dim} {val}', source='control_failure',
                          source_ref=f'PAR30-{dim}-{val}', severity='high', area='origination',
                          control_codes=['FRA-011', 'FRA-012'],
                          description=(f'Portfolio at risk over 30 days is {p}% against a threshold of {threshold}%. '
                                       f'Agree a remediation plan (collections, officer follow-up, '
                                       f'origination tightening) and re-measure monthly.'))
            opened += 1
    return {'qa_open': qa_open, 'refinance_hits': len(hits), 'par_breaches': opened}


def _refinance_expected(db):
    """Every prepayment-to-costlier-loan hit must be on the AML register (FRA-035)."""
    from regcontrols.api import get_param
    window = get_param('lending.prepay_new_loan_window_days', default=None)
    if window is None:
        return []
    ers = [dict(r) for r in db.execute("SELECT * FROM ln_early_repayments WHERE status = 'executed'").fetchall()]
    loans = [dict(r) for r in db.execute("SELECT * FROM ln_loans").fetchall()] if ers else []
    refs = {l['id']: l['loan_ref'] for l in loans}
    return [('ln_early_repayments', h['early_repayment_id'], f"lending refinance {refs.get(h['new_loan_id'], '')}")
            for h in logic.costlier_refinance(ers, loans, window)]


register_expected_source('fra_nbfi.lending.refinance', _refinance_expected)
