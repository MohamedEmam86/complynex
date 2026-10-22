"""Policy library: documents, versions, review workflow, approval chain, board approvals,
applicability and staff acknowledgments."""
from datetime import timedelta

# name, cat, doc type, owner, unit, version, status, effective(days ago), next review(days from today),
# board?, board meeting (days ago), mandatory, public, reg ref, scope units, purpose
POLICIES = [
    ('Anti-Money Laundering (AML) / KYC Policy', 1, 'POLICY', 'mlro', 'NMF-COMP', '4.0', 'published', 262, 103, True, 268, 1, 1,
     'AML Law 80/2002 and its executive regulations; EMLCU & FRA guidance', ['NMF'],
     'sets the company-wide framework to prevent money laundering and terrorist financing, including risk-based customer due diligence, ongoing monitoring, STR reporting and record keeping'),
    ('Customer Due Diligence & KYC Procedure', 1, 'PROCEDURE', 'mlro', 'NMF-COMP', '3.2', 'published', 240, 125, False, None, 1, 0,
     'FRA KYC requirements for microfinance clients', ['NMF-OPS', 'NMF-COMP', 'NMF-CS'],
     'defines step-by-step customer identification, verification, risk rating and enhanced due diligence for microfinance and consumer-finance clients'),
    ('Sanctions & Trade Compliance Policy', 1, 'POLICY', 'mlro', 'NMF-COMP', '2.1', 'published', 230, 135, True, 268, 1, 0,
     'UN Security Council lists; local terrorist lists', ['NMF'],
     'requires screening of customers, guarantors and vendors against UN and local lists before onboarding and on every list update'),
    ('Credit Policy - Microfinance & Consumer Finance', 7, 'POLICY', 'risk', 'NMF-RISK', '5.0', 'published', 262, 103, True, 268, 1, 0,
     'FRA microfinance and consumer finance rules', ['NMF-OPS', 'NMF-RISK', 'NMF-FIN'],
     'governs credit underwriting, loan limits, pricing, approval authorities, collateral/guarantees, rescheduling and write-off'),
    ('Risk Management Policy', 7, 'POLICY', 'risk', 'NMF-RISK', '3.0', 'published', 262, 103, True, 268, 1, 0,
     'FRA risk management requirements for NBFIs', ['NMF'],
     'establishes the enterprise risk management framework, risk appetite, the three lines model and risk reporting to the Board'),
    ('Customer Protection Policy', 5, 'POLICY', 'cs', 'NMF-CS', '2.0', 'published', 300, 65, True, 330, 1, 1,
     'FRA consumer protection rules for non-bank finance', ['NMF'],
     'ensures fair treatment, transparent pricing and disclosure, responsible lending, fair collection practices and protection of vulnerable clients'),
    ('Complaints Handling Procedure', 5, 'PROCEDURE', 'cs', 'NMF-CS', '2.3', 'published', 345, 18, False, None, 1, 1,
     'FRA complaints handling requirements', ['NMF-CS', 'NMF-OPS'],
     'sets channels, acknowledgement and resolution timelines (15 working days), escalation and root-cause analysis for customer complaints'),
    ('Data Privacy & Protection Policy', 2, 'POLICY', 'dpo', 'NMF-LEG', '2.0', 'published', 112, 253, True, 118, 1, 1,
     'Personal Data Protection Law 151/2020', ['NMF'],
     'defines lawful processing, consent, data subject rights, retention, breach notification and DPIA requirements'),
    ('Information Security Policy', 3, 'POLICY', 'it', 'NMF-IT', '3.1', 'published', 112, 253, True, 118, 1, 0,
     'FRA IT governance requirements; ISO/IEC 27001 (reference)', ['NMF'],
     'sets controls for access management, passwords and MFA, encryption, logging, vulnerability management and acceptable use'),
    ('Business Continuity Plan (BCP)', 4, 'POLICY', 'it', 'NMF-IT', '1.4', 'published', 390, -25, True, 330, 1, 0,
     'FRA operational resilience expectations', ['NMF'],
     'defines critical processes, recovery time objectives, DR site arrangements, call trees and annual BCP testing'),
    ('Whistleblowing Policy', 6, 'POLICY', 'mlro', 'NMF-COMP', '2.0', 'published', 330, 35, True, 330, 1, 1,
     'FRA corporate governance rules; good practice', ['NMF'],
     'provides confidential and anonymous channels to report misconduct and protects whistleblowers from retaliation'),
    ('Conflict of Interest (COI) Policy', 6, 'POLICY', 'mlro', 'NMF-COMP', '2.2', 'published', 250, 115, True, 268, 1, 1,
     'FRA corporate governance rules', ['NMF'],
     'requires annual and event-driven declarations of interests and sets mitigation measures and approval rules'),
    ('Gifts & Hospitality Policy', 6, 'POLICY', 'mlro', 'NMF-COMP', '1.3', 'published', 250, 115, False, None, 1, 1,
     'Anti-bribery good practice', ['NMF'],
     'sets the EGP 1,000 declaration threshold, pre-approval rules, prohibited gifts and the gifts register'),
    ('Ethical Code of Conduct', 6, 'COC', 'hr', 'NMF-HR', '3.0', 'published', 280, 85, True, 268, 1, 1,
     'FRA governance rules; company values', ['NMF'],
     'describes expected behaviour on integrity, confidentiality, fair treatment, use of company assets and disciplinary consequences'),
    ('Related Party Transactions Policy', 8, 'POLICY', 'dpo', 'NMF-LEG', '1.1', 'published', 165, 200, True, 160, 1, 0,
     'Companies Law 159/1981; FRA rules', ['NMF-LEG', 'NMF-FIN'],
     'defines related parties, approval thresholds, abstention of interested directors and disclosure'),
    ('Corporate Governance Framework', 8, 'FRAMEWORK', 'sec', 'NMF-LEG', '2.0', 'published', 205, 160, True, 208, 1, 1,
     'FRA corporate governance rules for NBFIs', ['NMF'],
     'describes the board, committees, delegation of authority, three lines model and governance disclosures'),
    ('Compliance Manual', 8, 'MANUAL', 'mlro', 'NMF-COMP', '2.4', 'published', 180, 185, False, None, 1, 0,
     'FRA and EMLCU requirements', ['NMF'],
     'consolidates the compliance programme: monitoring plan, regulatory change management, reporting calendar and breach handling'),
    ('Internal Audit Charter', 18, 'CHARTER', 'audit', 'NMF-IA', '2.0', 'published', 205, 160, True, 208, 1, 0,
     'IIA Global Internal Audit Standards; FRA governance rules', ['NMF'],
     'sets the mandate, independence, authority and reporting lines of Internal Audit to the Audit Committee'),
    ('Human Resources Policy', 6, 'POLICY', 'hr', 'NMF-HR', '4.1', 'published', 150, 215, False, None, 0, 1,
     'Labour Law 14/2025 (as applicable)', ['NMF'],
     'covers recruitment and screening, onboarding, performance management, leave, disciplinary process and staff training'),
    ('Procurement Policy', 8, 'POLICY', 'cfo', 'NMF-FIN', '1.0', 'approved', 0, 365, False, None, 0, 0,
     'Internal control framework', ['NMF'],
     'sets procurement thresholds, three-quote rule, vendor due diligence and segregation of duties'),
    ('Outsourcing & Vendor Management Policy', 7, 'POLICY', 'risk', 'NMF-RISK', '1.0', 'pending_approval', 0, 365, True, None, 1, 0,
     'FRA outsourcing expectations', ['NMF'],
     'requires risk assessment, due diligence, contractual safeguards, monitoring and exit plans for material outsourcing'),
    ('Anti-Bribery and Corruption (ABAC) Policy', 6, 'POLICY', 'mlro', 'NMF-COMP', '1.0', 'pending_approval', 0, 365, True, None, 1, 1,
     'Penal Code provisions on bribery; good practice', ['NMF'],
     'sets zero tolerance for bribery, facilitation payments and improper payments to officials or third parties'),
    ('ESG & Climate Risk Policy', 7, 'POLICY', 'risk', 'NMF-RISK', '0.3', 'draft', 0, 365, True, None, 0, 0,
     'FRA sustainability and climate-related disclosure requirements', ['NMF'],
     'integrates environmental and social risk screening into lending and sets the climate risk governance and disclosure approach'),
    ('Remote Work Policy (2021)', 6, 'POLICY', 'hr', 'NMF-HR', '1.2', 'archived', 1500, -400, False, None, 0, 0,
     'Internal', ['NMF'],
     'temporary remote working arrangements, now superseded by the Human Resources Policy'),
]

VERSION_NOTES = ['Initial issue.', 'Annual review - minor wording updates.', 'Aligned with new regulatory guidance.',
                 'Restructured roles and responsibilities; added escalation matrix.',
                 'Updated thresholds and approval authorities.', 'Added risk-based approach and KPIs.']


def _content(name, purpose, ref, owner_title, unit_name):
    return (f"1. Purpose\nThis {name} {purpose}.\n\n"
            f"2. Scope\nApplies to all employees, branches and outsourced service providers of Nile Microfinance S.A.E. "
            f"within the units listed in the applicability matrix.\n\n"
            f"3. Regulatory basis\n{ref}.\n\n"
            f"4. Roles and responsibilities\n- Board of Directors: approves the policy and oversees its implementation.\n"
            f"- {owner_title}: owns the policy, monitors compliance and proposes updates.\n"
            f"- Department heads: implement the policy in their units.\n- Internal Audit: provides independent assurance.\n\n"
            f"5. Key requirements\n- Requirements are applied on a risk-based approach.\n"
            f"- Exceptions require written approval by the policy owner and are logged.\n"
            f"- Breaches are reported to Compliance within 2 working days.\n\n"
            f"6. Monitoring and review\nThe {unit_name} reviews this document at least annually or upon material "
            f"regulatory change. (Fictional demo document.)")


def _ago(ctx, days, hour=None):
    """ctx.ago without microseconds (several pages print the raw timestamp)."""
    return ctx.ago(days, hour).replace(microsecond=0)


def seed(ctx):
    rnd = ctx.rnd
    dtypes = {r['code']: r['id'] for r in ctx.q("SELECT id, code FROM document_types")}
    wf_stages = {}
    for r in ctx.q("""SELECT w.document_type_id, s.* FROM approval_workflows w
                      JOIN approval_workflow_stages s ON s.workflow_id = w.id
                      WHERE w.is_active AND s.is_enabled ORDER BY s.stage_order"""):
        wf_stages.setdefault(r['document_type_id'], []).append(r)
    units = {r['code']: r for r in ctx.q("SELECT id, code, name_en, head_user_id FROM org_units")}
    staff = [r for r in ctx.q("SELECT id, first_name, last_name, role, email FROM users WHERE is_active = 1 ORDER BY id")]
    bmeet = {}
    for r in ctx.q("SELECT meeting_date, meeting_reference FROM board_meetings WHERE committee_id IS NULL"):
        bmeet[r['meeting_date']] = r['meeting_reference']

    def board_ref(days):
        d = str(ctx.dago(days))
        return bmeet.get(d) or f'BM-{ctx.dago(days).year}-XX'

    counts = dict(policies=0, versions=0, reviews=0, approvals=0, board=0, applic=0, acks=0)
    seq = {}
    ids = {}
    for (name, cat, dtype, owner, unit, ver, status, eff, nxt, board, bdays, mand, public, ref, scope,
         purpose) in POLICIES:
        prefix = {'POLICY': 'POL', 'PROCEDURE': 'PRC', 'FRAMEWORK': 'FRM', 'MANUAL': 'MAN', 'CHARTER': 'CHR',
                  'COC': 'COC'}[dtype]
        seq[prefix] = seq.get(prefix, 0) + 1
        number = f'NMF-{prefix}-{seq[prefix]:03d}'
        draft = status in ('draft', 'pending_approval', 'approved')
        created_days = (eff + 30) if not draft else rnd.randrange(12, 60)
        if status == 'archived':
            created_days = 1500
        major = int(float(ver))
        owner_title = ctx.user(owner)['job_title']
        content = _content(name, purpose, ref, owner_title, units[unit]['name_en'])
        approved_days = None if status in ('draft', 'pending_approval') else (eff + 3 if eff else rnd.randrange(3, 10))
        pid = ctx.ins(
            'policies', policy_number=number, policy_name=name, category_id=cat, version=ver,
            effective_date=str(ctx.dago(eff)) if not draft else None,
            review_date=str(ctx.dago(eff + 10)) if not draft else None,
            next_review_date=str(ctx.dago(-nxt)), owner_id=ctx.uid(owner),
            owner_function=f"{units[unit]['name_en']} ({unit})",
            description=f'This document {purpose}.', content=content, status=status,
            regulatory_reference=ref, cbe_requirement=None, is_public=public,
            issuing_date=str(ctx.dago(eff + 5)) if not draft else None, approval_cycle='Annual',
            approved_by=ctx.uid('ceo') if approved_days else None,
            approval_date=str(_ago(ctx, approved_days, 12)) if approved_days else None,
            created_by=ctx.uid(owner), created_at=str(_ago(ctx, min(created_days, 1500), 10)),
            updated_by=ctx.uid(owner), updated_at=str(_ago(ctx, max(eff - 1, 1) if not draft else rnd.randrange(1, 10), 15)),
            is_mandatory=mand, department_id=ctx.depts.get(unit), is_internal=0 if public else 1,
            document_type_id=dtypes.get(dtype), org_unit_id=units[unit]['id'], requires_board_approval=board)
        ids[name] = pid
        counts['policies'] += 1

        # versions: one row per major version, last one is current
        vers = [f'{v}.0' for v in range(1, major + 1)] if major >= 1 else []
        if ver not in vers:
            vers.append(ver)
        span = max(eff, 1) + 365 * (len(vers) - 1)
        for i, v in enumerate(vers):
            vd = eff + (len(vers) - 1 - i) * 365 if not draft else created_days
            ctx.ins('policy_versions', policy_id=pid, version=v,
                    change_summary=VERSION_NOTES[0] if i == 0 else VERSION_NOTES[min(i, len(VERSION_NOTES) - 1)],
                    content=content if v == ver else content.replace('at least annually', 'every two years'),
                    effective_date=str(ctx.dago(vd)) if not draft else None, created_by=ctx.uid(owner),
                    created_at=str(_ago(ctx, vd + 5, 11)))
            counts['versions'] += 1

        # review workflow (legacy reviewers)
        start = eff + 25 if not draft else created_days - 2
        stages = [('Compliance Review', 'co' if owner == 'mlro' else 'mlro'),
                  ('Legal Review', 'dpo' if owner != 'dpo' else 'sec'),
                  ('Executive Approval', 'ceo')]
        if name.startswith('Outsourcing'):
            stages.insert(2, ('IT & Systems Review', 'admin'))
        for i, (stage, who) in enumerate(stages):
            if status in ('published', 'approved', 'archived'):
                st, rd = 'approved', start - 4 * (i + 1)
            elif status == 'pending_approval':
                st = 'approved' if i == 0 else 'pending'
                rd = start - 3 if i == 0 else None
            else:
                break
            ctx.ins('policy_review_workflow', policy_id=pid, reviewer_id=ctx.uid(who), stage_name=stage, status=st,
                    comments=rnd.choice(['Reviewed - no further comments.', 'Approved subject to minor wording changes (applied).',
                                         'Consistent with regulatory requirements.', 'OK.']) if st == 'approved' else None,
                    review_date=str(_ago(ctx, max(rd, 1), 13)) if rd is not None else None,
                    created_at=str(_ago(ctx, start, 9 + i)))
            counts['reviews'] += 1

        # approval chain snapshot for the document type
        for i, s in enumerate(wf_stages.get(dtypes.get(dtype), []), start=1):
            if s['approver_mode'] == 'org_unit_head':
                approver = units[unit]['head_user_id']
            elif s['approver_role'] == 'compliance_manager':
                approver = ctx.uid('mlro')
            elif s['approver_role'] == 'manager':
                approver = ctx.uid(owner) if owner != 'mlro' else ctx.uid('ceo')
            else:
                approver = ctx.uid('ceo') if 'Executive' in s['stage_name'] or 'CEO' in s['stage_name'] else ctx.uid('admin')
            if status in ('published', 'approved', 'archived'):
                st, dec = 'approved', start - 3 * i
            elif status == 'pending_approval':
                st, dec = ('approved', start - 2) if i == 1 else ('pending', None)
            else:
                st, dec = 'pending', None
            ctx.ins('document_approvals', policy_id=pid, workflow_id=s['workflow_id'], stage_order=i,
                    stage_name=s['stage_name'], approver_user_id=approver, approver_role=s['approver_role'], status=st,
                    decision_at=_ago(ctx, max(dec, 1), 14) if dec is not None else None,
                    decided_by=approver if dec is not None else None,
                    comments='Approved.' if dec is not None else None,
                    sla_due_at=_ago(ctx, start - (s['sla_days'] or 7) * i, 17), created_at=_ago(ctx, start, 9))
            counts['approvals'] += 1

        # board approvals (current version + the previous one)
        if board and bdays:
            ctx.ins('policy_board_approvals', policy_id=pid, policy_version=ver, approved_on=ctx.dago(bdays),
                    board_ref=board_ref(bdays), notes='Approved by the Board of Directors.',
                    recorded_by=ctx.uid('sec'), recorded_at=_ago(ctx, max(bdays - 2, 1), 11))
            counts['board'] += 1
            if len(vers) > 1:
                prev = vers[-2]
                ctx.ins('policy_board_approvals', policy_id=pid, policy_version=prev, approved_on=ctx.dago(bdays + 365),
                        board_ref=f'BM-{ctx.dago(bdays + 365).year}-04', notes='Prior version approval (migrated record).',
                        recorded_by=ctx.uid('sec'), recorded_at=_ago(ctx, bdays + 363, 11))
                counts['board'] += 1

        # applicability
        for code in scope:
            ctx.ins('policy_applicability', policy_id=pid, org_unit_id=units[code]['id'], include_descendants=True,
                    is_exclusion=False, created_by=ctx.uid(owner), created_at=_ago(ctx, created_days, 10))
            counts['applic'] += 1
        if name.startswith('Credit Policy'):
            ctx.ins('policy_applicability', policy_id=pid, org_unit_id=units['NMF-CS']['id'], include_descendants=True,
                    is_exclusion=True, created_by=ctx.uid(owner), created_at=_ago(ctx, created_days, 10))
            counts['applic'] += 1

        # acknowledgments (published only): most staff, faster for older docs
        if status == 'published':
            for u in staff:
                if u['role'] == 'admin':
                    if eff < 120:     # leave the newest ones pending for the admin
                        continue
                    p_ack = 1.0
                else:
                    p_ack = 0.96 if eff > 200 else 0.85 if eff > 100 else 0.7
                if rnd.random() > p_ack:
                    continue
                lag = min(int(rnd.expovariate(1 / 6)) + 1, max(eff - 1, 1))
                ctx.ins('policy_acknowledgments', policy_id=pid, employee_id=u['id'],
                        acknowledgment_date=str(_ago(ctx, max(eff - lag, 0), rnd.randrange(9, 17))),
                        ip_address=f'10.20.{rnd.randrange(1, 4)}.{rnd.randrange(10, 250)}',
                        digital_signature=f"{u['first_name']} {u['last_name']}")
                counts['acks'] += 1
    ctx.data['policies'] = ids
    print('    ' + ', '.join(f'{k} {v}' for k, v in counts.items()))
