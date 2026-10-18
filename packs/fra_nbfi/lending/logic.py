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
Pure decision logic for the Lending Conduct & Portfolio module — no Flask, no
database. Every regulatory number arrives as an argument (read by the caller
from the regcontrols parameter registry), never as a literal here.

Covers: origination-file completeness (FRA-009, 013, 014, 015), eligibility
(FRA-004), credit-study anomaly detection (FRA-016), the pricing & fee engine
(FRA-017, 018, 020, 025, 026), early-repayment disclosure and the
"prepayment followed by a costlier loan" pattern (FRA-021–024), and
portfolio ageing / PAR (FRA-010–012).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal('0')
CENT = Decimal('0.01')


def D(v):
    """Decimal from anything numeric-ish; None stays None."""
    if v is None or v == '':
        return None
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v).replace(',', '').strip())


def money(v):
    return (D(v) or ZERO).quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Origination file completeness
# --------------------------------------------------------------------------

CORE_DOCS = ('national_id', 'contract', 'receipt_acknowledgement', 'credit_study')
STUDY_REQUIRED_FIELDS = ('monthly_revenue', 'monthly_costs_total', 'household_expenses',
                         'other_debt_service', 'net_income')


def file_gaps(loan, *, contract=None, documents=(), study=None, product_docs=(),
              gps_min_amount=None, min_cost_lines=None):
    """List what is missing from a loan file. Empty list = complete.

    Each gap is (control_code, code, message). gps_min_amount None means the
    GPS threshold is not configured — GPS is then not demanded (the check
    reports the missing parameter separately).
    """
    gaps = []
    doc_types = {d['doc_type'] for d in documents}
    # FRA-009 — contract signed by both parties, with dates
    if not contract:
        gaps.append(('FRA-009', 'contract_missing', 'No financing contract recorded'))
    else:
        if not contract.get('signed_by_lender') or not contract.get('lender_signed_at'):
            gaps.append(('FRA-009', 'lender_signature', 'Lender signature or date missing'))
        if not contract.get('signed_by_client') or not contract.get('client_signed_at'):
            gaps.append(('FRA-009', 'client_signature', 'Client signature or date missing'))
    # FRA-013 — GPS above the amount threshold
    if gps_min_amount is not None and (D(loan.get('amount')) or ZERO) > D(gps_min_amount):
        if loan.get('gps_lat') in (None, '') or loan.get('gps_lng') in (None, ''):
            gaps.append(('FRA-013', 'gps_missing', 'Project GPS coordinates missing'))
    # FRA-014 — receipt acknowledgement
    if 'receipt_acknowledgement' not in doc_types:
        gaps.append(('FRA-014', 'receipt_ack', 'Client acknowledgement of receipt of funds missing'))
    # FRA-015 — structured credit study
    if not study:
        gaps.append(('FRA-015', 'study_missing', 'No credit study recorded'))
    else:
        missing = [f for f in STUDY_REQUIRED_FIELDS if study.get(f) in (None, '')]
        if missing:
            gaps.append(('FRA-015', 'study_fields', 'Credit study fields missing: ' + ', '.join(missing)))
        if min_cost_lines is not None and len(study.get('cost_lines') or []) < int(min_cost_lines):
            gaps.append(('FRA-015', 'study_cost_lines', f'Fewer than {int(min_cost_lines)} cost lines'))
    # product-specific required documents
    for dt in product_docs or ():
        if dt not in doc_types and dt not in ('contract', 'receipt_acknowledgement', 'credit_study'):
            gaps.append(('FRA-009', f'doc_{dt}', f'Required document missing: {dt}'))
    return gaps


# --------------------------------------------------------------------------
# Eligibility (FRA-004)
# --------------------------------------------------------------------------

def eligibility_breaches(client, *, max_monthly_revenue=None, max_project_size=None):
    """Return the ceilings a client exceeds. A ceiling of None is not configured."""
    out = []
    rev, size = D(client.get('monthly_revenue')), D(client.get('project_size'))
    if max_monthly_revenue is not None and rev is not None and rev > D(max_monthly_revenue):
        out.append(('monthly_revenue', rev, D(max_monthly_revenue)))
    if max_project_size is not None and size is not None and size > D(max_project_size):
        out.append(('project_size', size, D(max_project_size)))
    return out


# --------------------------------------------------------------------------
# Credit-study quality (FRA-016)
# --------------------------------------------------------------------------

def study_anomalies(studies, *, min_cost_lines=None, round_share=Decimal('0.8'), ratio_z=Decimal('3')):
    """Flag credit studies that look templated or copied.

    studies: dicts with loan_id, officer_code, monthly_revenue, monthly_costs_total,
    household_expenses, cost_lines (list of {label, amount}).
    Returns {loan_id: [(flag_type, detail), ...]}.

    - identical_figures: same (revenue, costs, household) triple used for
      different clients of the same officer
    - round_numbers: at least `round_share` of the amounts are multiples of 1,000
    - few_cost_lines: fewer lines than the configured minimum
    - ratio_outlier: cost/revenue ratio more than `ratio_z` robust deviations
      from the officer's median (needs ≥ 5 studies for that officer)
    """
    flags = defaultdict(list)
    by_officer = defaultdict(list)
    for s in studies:
        by_officer[s.get('officer_code') or ''].append(s)

    for officer, rows in by_officer.items():
        seen = defaultdict(list)
        for s in rows:
            key = (D(s.get('monthly_revenue')), D(s.get('monthly_costs_total')), D(s.get('household_expenses')))
            if None not in key:
                seen[key].append(s['loan_id'])
        for key, loans in seen.items():
            if len(loans) > 1:
                for lid in loans:
                    flags[lid].append(('identical_figures',
                                       f'Same revenue/costs/household figures as {len(loans) - 1} other '
                                       f'study(ies) of officer {officer or "?"}'))
        ratios = []
        for s in rows:
            rev, cost = D(s.get('monthly_revenue')), D(s.get('monthly_costs_total'))
            if rev and cost is not None and rev > 0:
                ratios.append((s['loan_id'], cost / rev))
        if len(ratios) >= 5:
            vals = sorted(r for _, r in ratios)
            med = vals[len(vals) // 2]
            mad = sorted(abs(r - med) for r in vals)[len(vals) // 2] or Decimal('0.01')
            for lid, r in ratios:
                if abs(r - med) / mad > ratio_z:
                    flags[lid].append(('ratio_outlier', f'Cost/revenue ratio {r:.2f} vs officer median {med:.2f}'))

    for s in studies:
        amounts = [D(s.get(f)) for f in ('monthly_revenue', 'monthly_costs_total', 'household_expenses')]
        amounts += [D(c.get('amount')) for c in (s.get('cost_lines') or []) if isinstance(c, dict)]
        amounts = [a for a in amounts if a]
        if len(amounts) >= 3:
            rounded = sum(1 for a in amounts if a % 1000 == 0)
            if Decimal(rounded) / Decimal(len(amounts)) >= round_share:
                flags[s['loan_id']].append(('round_numbers', f'{rounded} of {len(amounts)} amounts are round thousands'))
        if min_cost_lines is not None and len(s.get('cost_lines') or []) < int(min_cost_lines):
            flags[s['loan_id']].append(('few_cost_lines',
                                        f'{len(s.get("cost_lines") or [])} cost line(s); minimum {int(min_cost_lines)}'))
    return dict(flags)


# --------------------------------------------------------------------------
# Pricing & fee engine (FRA-017, 018, 020, 025, 026)
# --------------------------------------------------------------------------

def admin_fee_cap_amount(amount, cap_pct):
    return money(D(amount) * D(cap_pct) / 100)


def tier_cap_pct(amount, tiers):
    """tiers: [{"max_amount": 10000, "cap_pct": 3}, {"max_amount": null, "cap_pct": 2}]
    sorted ascending by max_amount; the first tier whose max_amount ≥ amount (or
    is null) applies. Returns the cap % or None if no tier matches."""
    amount = D(amount)
    ordered = sorted(tiers or [], key=lambda t: (t.get('max_amount') is None, D(t.get('max_amount')) or ZERO))
    for t in ordered:
        mx = D(t.get('max_amount'))
        if mx is None or amount <= mx:
            return D(t.get('cap_pct'))
    return None


def admin_fee_breach(loan, cap_pct=None, tiers=None):
    """Over-charge of the admin fee against the flat cap and/or the tier table.
    Returns (overcharge, allowed, rule) or None when within the limits."""
    fee = money(loan.get('admin_fee_amount'))
    amount = D(loan.get('amount')) or ZERO
    limits = []
    if cap_pct is not None:
        limits.append((admin_fee_cap_amount(amount, cap_pct), 'cap'))
    if tiers:
        t = tier_cap_pct(amount, tiers)
        if t is not None:
            limits.append((admin_fee_cap_amount(amount, t), 'tier'))
    if not limits:
        return None
    allowed, rule = min(limits, key=lambda x: x[0])
    if fee > allowed:
        return fee - allowed, allowed, rule
    return None


def max_late_penalty(overdue_amount, days_late, rate_pct, cap_pct=None):
    """Highest penalty allowed on one overdue instalment.

    Method (TODO(compliance-review) — confirm against the FRA decree): the
    rate applies per started month of delay on the overdue amount, and the
    total is capped at cap_pct of the overdue amount.
    """
    overdue = D(overdue_amount) or ZERO
    days = max(int(days_late or 0), 0)
    if days == 0 or overdue <= 0:
        return ZERO
    months = (days + 29) // 30
    penalty = overdue * D(rate_pct) / 100 * months
    if cap_pct is not None:
        penalty = min(penalty, overdue * D(cap_pct) / 100)
    return money(penalty)


def penalty_overcharge(instalment, rate_pct, cap_pct=None, today=None):
    """Over-charge on one instalment's late penalty, or None."""
    charged = money(instalment.get('penalty_charged'))
    if charged <= 0:
        return None
    due = instalment.get('due_date')
    paid = instalment.get('paid_date') or today or date.today()
    days = (paid - due).days if due else 0
    overdue = (D(instalment.get('principal_due')) or ZERO) + (D(instalment.get('interest_due')) or ZERO)
    allowed = max_late_penalty(overdue, days, rate_pct, cap_pct)
    return (charged - allowed, allowed) if charged > allowed else None


def flat_fee_overcharge(fee, cap):
    fee, cap = money(fee), money(cap)
    return (fee - cap, cap) if fee > cap else None


# --------------------------------------------------------------------------
# Early repayment (FRA-021–024)
# --------------------------------------------------------------------------

def early_repayment_disclosure(remaining_instalments, settlement_amount, prepayment_fee=0):
    """Cost comparison shown to the client before an early repayment.

    remaining_instalments: unpaid instalments (principal_due, interest_due, fees_due).
    Returns dict with original remaining cost, new cost and the difference.
    """
    orig_principal = sum((D(i.get('principal_due')) or ZERO) for i in remaining_instalments)
    orig_cost = sum(((D(i.get('principal_due')) or ZERO) + (D(i.get('interest_due')) or ZERO)
                     + (D(i.get('fees_due')) or ZERO)) for i in remaining_instalments)
    new_cost = money(settlement_amount) + money(prepayment_fee)
    return {
        'remaining_principal': money(orig_principal),
        'original_remaining_cost': money(orig_cost),
        'settlement_amount': money(settlement_amount),
        'prepayment_fee': money(prepayment_fee),
        'new_total_cost': new_cost,
        'client_saving': money(orig_cost) - new_cost,
    }


def disclosure_text(d, lang='en'):
    if lang == 'ar':
        return (f"إفصاح السداد المعجل: التكلفة المتبقية وفق الجدول الأصلي {d['original_remaining_cost']} جنيه. "
                f"مبلغ السداد المعجل {d['settlement_amount']} جنيه ومصروفات السداد المعجل {d['prepayment_fee']} جنيه، "
                f"بإجمالي {d['new_total_cost']} جنيه. الفرق لصالح العميل {d['client_saving']} جنيه.")
    return (f"Early repayment disclosure: remaining cost under the original schedule EGP {d['original_remaining_cost']}. "
            f"Early settlement amount EGP {d['settlement_amount']} plus early-repayment fee EGP {d['prepayment_fee']}, "
            f"total EGP {d['new_total_cost']}. Difference in the client's favour: EGP {d['client_saving']}.")


def costlier_refinance(early_repayments, loans, window_days):
    """FRA-023: an executed early repayment followed, within `window_days`, by a
    new loan to the same client that costs more (higher APR, or higher admin-fee
    percentage when APR is missing).

    Returns list of dicts {early_repayment_id, old_loan_id, new_loan_id, client_id, days, reason}.
    """
    by_id = {l['id']: l for l in loans}
    by_client = defaultdict(list)
    for l in loans:
        by_client[l['client_id']].append(l)
    out = []
    for er in early_repayments:
        if er.get('status') != 'executed' or not er.get('executed_at'):
            continue
        old = by_id.get(er['loan_id'])
        if not old:
            continue
        d0 = er['executed_at'].date() if hasattr(er['executed_at'], 'date') else er['executed_at']
        for new in by_client[old['client_id']]:
            if new['id'] == old['id']:
                continue
            start = new.get('disbursement_date') or new.get('application_date')
            if not start or not (d0 <= start <= d0 + timedelta(days=int(window_days))):
                continue
            reason = None
            if D(new.get('apr_pct')) is not None and D(old.get('apr_pct')) is not None:
                if D(new['apr_pct']) > D(old['apr_pct']):
                    reason = f"APR {new['apr_pct']}% vs {old['apr_pct']}%"
            else:
                fo, fn = fee_pct(old), fee_pct(new)
                if fo is not None and fn is not None and fn > fo:
                    reason = f'admin fee {fn:.2f}% vs {fo:.2f}%'
            if reason:
                out.append({'early_repayment_id': er['id'], 'old_loan_id': old['id'], 'new_loan_id': new['id'],
                            'client_id': old['client_id'], 'days': (start - d0).days, 'reason': reason})
    return out


def fee_pct(loan):
    amt, fee = D(loan.get('amount')), D(loan.get('admin_fee_amount'))
    if not amt or fee is None:
        return None
    return fee / amt * 100


# --------------------------------------------------------------------------
# Portfolio: days past due, ageing buckets, PAR (FRA-010–012)
# --------------------------------------------------------------------------

BUCKETS = (('current', 0, 0), ('1-30', 1, 30), ('31-60', 31, 60), ('61-90', 61, 90),
           ('91-120', 91, 120), ('120+', 121, None))
PAR_LEVELS = (30, 60, 90, 120)


def days_past_due(instalments, today=None, fallback=None):
    """Days since the oldest unpaid due instalment; `fallback` (imported DPD)
    when no instalment schedule is available."""
    today = today or date.today()
    unpaid = [i['due_date'] for i in instalments
              if i.get('due_date') and i['due_date'] < today and i.get('status') != 'paid'
              and (D(i.get('paid_amount')) or ZERO) < ((D(i.get('principal_due')) or ZERO) + (D(i.get('interest_due')) or ZERO))]
    if unpaid:
        return (today - min(unpaid)).days
    if not instalments and fallback is not None:
        return int(fallback)
    return 0


def bucket_of(dpd):
    for label, lo, hi in BUCKETS:
        if dpd >= lo and (hi is None or dpd <= hi):
            return label
    return 'current'


def portfolio_metrics(loans):
    """loans: dicts with outstanding_principal and dpd. Returns totals, bucket
    amounts/counts and PAR30/60/90/120 percentages (of outstanding)."""
    total = sum((D(l.get('outstanding_principal')) or ZERO) for l in loans)
    buckets = {b[0]: {'count': 0, 'amount': ZERO} for b in BUCKETS}
    for l in loans:
        b = buckets[bucket_of(int(l.get('dpd') or 0))]
        b['count'] += 1
        b['amount'] += D(l.get('outstanding_principal')) or ZERO
    par = {}
    for lvl in PAR_LEVELS:
        amt = sum((D(l.get('outstanding_principal')) or ZERO) for l in loans if int(l.get('dpd') or 0) > lvl)
        par[lvl] = (amt / total * 100).quantize(CENT) if total else ZERO
    return {'loans': len(loans), 'outstanding': money(total), 'buckets': buckets, 'par': par}


def par_by(loans, key):
    groups = defaultdict(list)
    for l in loans:
        groups[l.get(key) or '-'].append(l)
    return {k: portfolio_metrics(v) for k, v in sorted(groups.items())}


def trend(current, previous):
    """Change in percentage points; None when no previous value."""
    if previous is None:
        return None
    return (D(current) - D(previous)).quantize(CENT)


def visit_gaps(loans, visits, followup_days, today=None):
    """FRA-010: disbursed loans with no follow-up visit within `followup_days`
    of disbursement (once that window has passed), plus planned visits past
    their date and not done."""
    today = today or date.today()
    done = defaultdict(list)
    for v in visits:
        if v.get('visit_date'):
            done[v['loan_id']].append(v['visit_date'])
    missing = []
    for l in loans:
        d = l.get('disbursement_date')
        if not d or l.get('status') != 'disbursed':
            continue
        deadline = d + timedelta(days=int(followup_days))
        if deadline < today and not any(d <= vd <= deadline for vd in done[l['id']]):
            missing.append((l, deadline))
    overdue_planned = [v for v in visits if not v.get('visit_date') and v.get('planned_date')
                       and v['planned_date'] < today]
    return missing, overdue_planned
