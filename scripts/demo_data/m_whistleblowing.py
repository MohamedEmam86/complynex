"""Whistleblowing: 13 cases over 12 months (anonymous + named), assignments, update timelines, tokens, stats."""
import json
import string
from datetime import timedelta

from cryptography.fernet import Fernet

# days ago, anonymous, submitter (user key | (name, email) | None), type, severity, priority, title, description,
# location, final status, outcome(substantiated?), investigator, resolution summary, resolution action, suspected
CASES = [
    (352, True, None, 'FRAUD', 'HIGH', 'HIGH', 'Fictitious borrowers in the Giza group-lending portfolio',
     'Several group loans in Giza appear to be issued to people who do not exist or never received the money. '
     'The same phone numbers are repeated across different groups and repayments are made in cash by the same person.',
     'Giza Branch', 'RESOLVED', True, 'audit',
     'Substantiated. Internal Audit traced 23 loans (EGP 412,000) to fictitious borrowers created by one loan officer '
     'using copied national IDs. Repayments were made from the officer\'s own funds to hide arrears.',
     'Loan officer dismissed and referred to the public prosecutor; loans written off; duplicate-phone and '
     'biometric checks added to onboarding.', 'Loan officer, Giza Branch'),
    (318, False, ('Reem Adel Shaker', 'reem.shaker@nilemicro.example'), 'HARASSMENT', 'MEDIUM', 'NORMAL',
     'Harassment by a supervisor at Cairo Downtown branch',
     'A supervisor repeatedly makes inappropriate comments to female staff and assigns unfair targets to those who object.',
     'Cairo Downtown Branch', 'RESOLVED', True, 'hr',
     'Substantiated. Four witness statements confirmed the behaviour.',
     'Final written warning, removal from people-management duties for 6 months and mandatory '
     'respect-at-work training for the branch.', 'Branch operations supervisor'),
    (281, True, None, 'CORRUPTION', 'HIGH', 'HIGH', 'Loan officer asking borrowers for facilitation payments',
     'Borrowers in Assiut say a loan officer asks for EGP 300-500 in cash to speed up approval. I heard it from three customers.',
     'Assiut Branch', 'RESOLVED', True, 'mlro',
     'Substantiated. Interviews with 11 borrowers and a mystery-shopper visit confirmed solicitation of payments; '
     'linked to consumer complaint received the same month.',
     'Officer dismissed; affected borrowers refunded EGP 4,100; anti-bribery reminder issued to all branches.',
     'Loan officer, Assiut Branch'),
    (247, True, None, 'AML_VIOLATION', 'CRITICAL', 'URGENT', 'Large cash early repayments and instructions to split deposits',
     'A customer is repaying several loans early in large cash amounts. Branch staff were told to split the cash '
     'into smaller deposits so it does not appear in reports.',
     'Cairo Downtown Branch', 'RESOLVED', True, 'mlro',
     'Substantiated. Cash repayments of EGP 1.9m over 5 months with no business rationale; structuring instruction '
     'confirmed by two staff members.',
     'STR filed with EMLCU; relationship exited; branch staff retrained on structuring red flags.',
     'Branch cashier (instruction), customer'),
    (215, False, 'acc', 'CONFLICT_INTEREST', 'MEDIUM', 'NORMAL', 'Branch furniture bought from a manager\'s relative',
     'The furniture for the new Assiut branch was bought from a company owned by a relative of a department manager.',
     'Head Office - Procurement', 'DISMISSED', False, 'co',
     'Unsubstantiated. The relationship had been disclosed in the COI register before the tender; the manager '
     'did not take part in the evaluation and the supplier was the lowest of three quotes.',
     'No action; procurement reminded to attach COI clearance to tender files.', 'Department manager'),
    (184, True, None, 'REGULATORY', 'HIGH', 'HIGH', 'Loans disbursed before KYC documents are complete',
     'To meet monthly targets, some loans are disbursed and the missing KYC documents (utility bill, '
     'commercial activity proof) are collected later or never.',
     'Giza Branch', 'RESOLVED', True, 'co',
     'Partly substantiated. 14 of 60 sampled files lacked proof of activity at disbursement; no fraud found.',
     'System hard-stop added (no disbursement without complete KYC checklist); branch target scheme revised.',
     'Giza Branch lending team'),
    (150, True, None, 'MISUSE_ASSETS', 'LOW', 'NORMAL', 'Company car used for personal trips',
     'A pool car is used at weekends for personal travel.',
     'Head Office', 'DISMISSED', False, 'hr',
     'Unsubstantiated. Fleet logs show weekend use was for an approved off-site collection campaign.',
     'No action.', 'Unknown driver'),
    (118, False, 'lo2', 'RETALIATION', 'HIGH', 'HIGH', 'Retaliation after cooperating with an investigation',
     'Since I gave a statement in a previous investigation I was moved to a remote village route and excluded from the incentive scheme.',
     'Assiut Branch', 'INVESTIGATING', None, 'hr', None, None, 'Branch management'),
    (88, True, None, 'DATA_BREACH', 'CRITICAL', 'URGENT', 'Customer list copied to a USB stick by a collection agent',
     'An agent of the outsourced collection company copied the overdue customers list (names, IDs, phones, balances) '
     'to a personal USB stick and said he will use it for his own business.',
     'Outsourced collection agency', 'INVESTIGATING', None, 'dpo', None, None, 'Collection agency staff member'),
    (57, True, None, 'FRAUD', 'HIGH', 'HIGH', 'Manipulation of arrears ageing in collection reports',
     'Some overdue loans are restructured at month end only to reset the days-past-due so the portfolio-at-risk looks better.',
     'Head Office - Collections', 'INVESTIGATING', None, 'audit', None, None, 'Collections unit'),
    (31, False, 'agent', 'UNETHICAL', 'LOW', 'NORMAL', 'Pressure to sell optional insurance',
     'We are pushed to tell customers that the optional health insurance add-on is mandatory.',
     'Customer Service', 'UNDER_REVIEW', None, 'co', None, None, None),
    (9, True, None, 'AML_VIOLATION', 'MEDIUM', 'HIGH', 'Unregistered person collecting repayments in cash',
     'A person who is not an employee is collecting instalments in cash from women groups in a village near Assiut.',
     'Assiut - village route', 'SUBMITTED', None, None, None, None, None),
    (2, True, None, 'HARASSMENT', 'MEDIUM', 'NORMAL', 'Verbal abuse during field visits',
     'A field collector insults borrowers during home visits.',
     'Giza - field collection', 'SUBMITTED', None, None, None, None, None),
]


def _ts(d):
    return d.strftime('%Y-%m-%d %H:%M:%S')


def _wh(d, rnd):
    """Move a timestamp into working hours (Sun-Thu, 09:00-17:00)."""
    if d.hour >= 17:
        d = (d + timedelta(days=1)).replace(hour=rnd.randint(9, 11))
    elif d.hour < 9:
        d = d.replace(hour=rnd.randint(9, 11))
    while d.weekday() in (4, 5):
        d += timedelta(days=1)
    return d


def seed(ctx):
    rnd = ctx.rnd
    per_year = {}
    created = []
    for row in CASES:
        (days, anon, sub, typ, sev, prio, title, desc, loc, status, subst, inv, res_sum, res_act, suspect) = row
        sub_at = ctx.ago(days, hour=rnd.randint(8, 22) if anon else rnd.randint(9, 16))
        yr = sub_at.year
        per_year[yr] = per_year.get(yr, 0) + 1
        num = f"WB-{yr}-{per_year[yr]:04d}"
        sub_id = sub_name = sub_email = None
        dept = None
        if isinstance(sub, str):
            u = ctx.user(sub)
            sub_id, sub_name, sub_email = u['id'], f"{u['first_name']} {u['last_name']}", u['email']
            dept = ctx.one("SELECT department FROM users WHERE id = %s", (sub_id,))['department']
        elif isinstance(sub, tuple):
            sub_name, sub_email = sub
            dept = 'Cairo Downtown Branch'
        code = key = None
        if anon:
            code = 'WB-' + ''.join(rnd.choice(string.ascii_uppercase) for _ in range(3)) + '-' + \
                ''.join(rnd.choice(string.digits) for _ in range(3)) + '-' + \
                ''.join(rnd.choice(string.ascii_uppercase) for _ in range(3))
            key = Fernet.generate_key().decode()
        t_review = _wh(sub_at + timedelta(days=rnd.randint(1, 3), hours=2), rnd)
        t_assign = t_review + timedelta(hours=3)
        resolved_at = None
        if status in ('RESOLVED', 'DISMISSED'):
            resolved_at = _wh(sub_at + timedelta(days=rnd.randint(22, 55) if subst else rnd.randint(12, 25)), rnd)
        cid = ctx.ins('whistleblowing_cases', case_number=num, submitted_at=_ts(sub_at), is_anonymous=1 if anon else 0,
                      submitter_id=sub_id, submitter_name=None if anon else sub_name,
                      submitter_email=None if anon else sub_email,
                      submitter_phone=None if anon else f"+20 10 0000 {rnd.randint(1000, 9999)}",
                      submitter_department=dept, incident_type=typ, incident_category=typ, severity=sev,
                      incident_date=(sub_at - timedelta(days=rnd.randint(5, 40))).date().isoformat(),
                      incident_location=loc, title=title, description=desc,
                      evidence_description='Screenshots / names of affected customers provided' if rnd.random() < .5 else None,
                      witnesses='Two colleagues (names held by Compliance)' if not anon else None,
                      suspected_individuals=suspect, status=status, priority=prio,
                      assigned_to=ctx.uid(inv) if inv else None,
                      assigned_at=_ts(t_assign) if inv else None,
                      reviewed_by=ctx.uid('mlro') if status != 'SUBMITTED' else None,
                      reviewed_at=_ts(t_review) if status != 'SUBMITTED' else None,
                      resolution_summary=res_sum, resolution_action=res_act,
                      resolved_at=_ts(resolved_at) if resolved_at else None,
                      resolved_by=ctx.uid('mlro') if resolved_at else None,
                      anonymous_code=code, encryption_key=key, is_confidential=1,
                      requires_investigation=1 if inv else 0, is_urgent=1 if sev in ('HIGH', 'CRITICAL') else 0,
                      updated_at=_ts(resolved_at or (t_assign if inv else sub_at)))
        created.append(cid)

        def upd(at, typ_, text, old=None, new=None, by=None, visible=True):
            ctx.ins('whistleblowing_updates', case_id=cid, update_type=typ_, update_text=text, old_value=old,
                    new_value=new, created_by=ctx.uid(by) if by else None, created_at=_ts(at),
                    is_visible_to_submitter=1 if visible else 0)

        upd(sub_at, 'STATUS_CHANGE', 'Case submitted', None, 'SUBMITTED', sub if isinstance(sub, str) else None)
        if anon:
            last = min(ctx.now, sub_at + timedelta(days=rnd.randint(5, 30)))
            ctx.ins('whistleblowing_anonymous_tokens', case_id=cid,
                    access_token=''.join(rnd.choice(string.ascii_letters + string.digits + '-_') for _ in range(43)),
                    access_code=code, created_at=_ts(sub_at), last_accessed=_ts(last),
                    access_count=rnd.randint(1, 6), expires_at=_ts(sub_at + timedelta(days=365)),
                    is_active=1 if days < 365 else 0)
        if status == 'SUBMITTED':
            continue
        upd(t_review, 'STATUS_CHANGE', 'Initial assessment by the MLRO: report is credible and in scope of the policy',
            'SUBMITTED', 'UNDER_REVIEW', 'mlro')
        # assignment engine rows
        sla = 45 if sev in ('HIGH', 'CRITICAL') else 30  # investigation target
        ctx.ins('whistleblowing_assignments', case_id=cid, assigned_to=ctx.uid(inv), assigned_by=ctx.uid('mlro'),
                assigned_at=_ts(t_assign), assigned_at_ts=t_assign, action_type='assign',
                to_org_unit_id=ctx.one("SELECT org_unit_id FROM users WHERE id=%s", (ctx.uid(inv),))['org_unit_id'],
                assignment_note=f'Assigned to {ctx.name(inv)} for investigation',
                comments='Keep the reporter\'s identity strictly confidential.' if not anon else None,
                status_at_assignment='UNDER_REVIEW', sla_due_at=t_assign + timedelta(days=sla),
                is_current=status not in ('RESOLVED', 'DISMISSED'))
        upd(t_assign, 'ASSIGNMENT', f'Case assigned to {ctx.name(inv)} for investigation', by='mlro', visible=False)
        if status == 'UNDER_REVIEW':
            upd(t_assign + timedelta(days=2), 'INVESTIGATION_NOTE',
                'Preliminary review of the sales script and incentive scheme requested from Customer Service.', by=inv)
            continue
        t_inv = _wh(t_assign + timedelta(days=rnd.randint(2, 5)), rnd)
        upd(t_inv, 'STATUS_CHANGE', 'Formal investigation opened; evidence preservation notice sent to IT',
            'UNDER_REVIEW', 'INVESTIGATING', inv)
        notes = ['Documents and system logs collected; interview plan agreed with Compliance.',
                 'Interviews held with witnesses; statements signed and filed.',
                 'Interim report shared with the MLRO and the CEO.']
        t = t_inv
        end = resolved_at or ctx.now
        for k, n in enumerate(notes):
            t = _wh(t + timedelta(days=rnd.randint(4, 12)), rnd)
            if t >= end:
                break
            upd(t, 'INVESTIGATION_NOTE', n, by=inv, visible=k == 0)
        if typ == 'RETALIATION':
            # escalated: HR -> CEO because branch management is involved
            t_esc = _wh(t_inv + timedelta(days=9), rnd)
            ctx.q("UPDATE whistleblowing_assignments SET is_current = FALSE, unassigned_at = %s, unassigned_by = %s "
                  "WHERE case_id = %s", (_ts(t_esc), ctx.uid('mlro'), cid))
            ctx.ins('whistleblowing_assignments', case_id=cid, assigned_to=ctx.uid('ceo'), assigned_by=ctx.uid('mlro'),
                    assigned_at=_ts(t_esc), assigned_at_ts=t_esc, action_type='escalate',
                    previous_owner_id=ctx.uid('hr'), from_org_unit_id=ctx.units['NMF-HR'], to_org_unit_id=ctx.units['NMF'],
                    assignment_reason='Branch and operations management are involved; decision needs CEO authority.',
                    status_at_assignment='INVESTIGATING', sla_due_at=t_esc + timedelta(days=120), is_current=True,
                    assignment_note='Escalated to CEO')
            ctx.q("UPDATE whistleblowing_cases SET assigned_to = %s WHERE id = %s", (ctx.uid('ceo'), cid))
            upd(t_esc, 'ASSIGNMENT', 'Escalated to the CEO: operations management involved', by='mlro', visible=False)
            upd(t_esc + timedelta(days=1), 'INVESTIGATION_NOTE',
                'Interim protection: reporter returned to original route and incentive restored pending outcome.',
                by='ceo')
        if resolved_at:
            new = 'RESOLVED' if status == 'RESOLVED' else 'DISMISSED'
            if status == 'RESOLVED':
                upd(resolved_at, 'RESOLUTION', 'Case resolved - allegation substantiated. ' + res_act, 'INVESTIGATING',
                    new, 'mlro')
            else:
                upd(resolved_at, 'STATUS_CHANGE', 'Case closed - allegation not substantiated. ' + res_sum[:160],
                    'INVESTIGATING', new, 'mlro')
            ctx.ins('whistleblowing_assignments', case_id=cid, assigned_to=None, assigned_by=ctx.uid('mlro'),
                    assigned_at=_ts(resolved_at), assigned_at_ts=resolved_at, action_type='close',
                    previous_owner_id=ctx.uid(inv), assignment_reason='Investigation completed', comments=res_sum[:300],
                    status_at_assignment=new, is_current=False, assignment_note='Investigation completed')
            ctx.q("UPDATE whistleblowing_assignments SET unassigned_at = %s, unassigned_by = %s "
                  "WHERE case_id = %s AND action_type = 'assign'", (_ts(resolved_at), ctx.uid('mlro'), cid))

    # monthly statistics snapshots (12 months)
    for m in range(11, -1, -1):
        cut = (ctx.today.replace(day=1) - timedelta(days=30 * m)).replace(day=1)
        rows = ctx.q("SELECT * FROM whistleblowing_cases WHERE submitted_at::date < %s", (cut + timedelta(days=31),))
        rows = [r for r in rows if r['submitted_at'][:7] <= cut.strftime('%Y-%m')]
        res = [r for r in rows if r['resolved_at'] and r['resolved_at'][:7] <= cut.strftime('%Y-%m')]
        by = lambda k: json.dumps({v: sum(1 for r in rows if r[k] == v) for v in sorted({r[k] for r in rows})})
        avg = None
        if res:
            from datetime import datetime as _dt
            avg = round(sum((_dt.fromisoformat(r['resolved_at']) - _dt.fromisoformat(r['submitted_at'])).days
                            for r in res) / len(res), 1)
        ctx.ins('whistleblowing_stats', stat_date=cut.isoformat(), total_cases=len(rows),
                anonymous_cases=sum(1 for r in rows if r['is_anonymous']), resolved_cases=len(res),
                avg_resolution_days=avg, cases_by_type=by('incident_type'), cases_by_severity=by('severity'),
                cases_by_status=by('status'))

    ctx.commit()
    from models.case import Case
    for cid in created:
        Case.sync_from_source('WHISTLEBLOWING', cid)
    ctx.data['wb_ids'] = created
    print(f'    whistleblowing cases: {len(created)}')
