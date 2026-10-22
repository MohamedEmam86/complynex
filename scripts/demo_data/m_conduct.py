"""Conduct: conflict of interest (campaigns, declarations, mitigation plans), gifts & hospitality
declarations with approvals, code of business ethics declarations and the declaration campaigns
(org-wide tracker)."""
import uuid
from datetime import datetime, timedelta

STAFF = ['mlro', 'co', 'aml', 'ceo', 'risk', 'audit', 'it', 'dpo', 'cfo', 'ops', 'cs', 'hr', 'sec', 'br1',
         'lo1', 'lo2', 'acc', 'agent', 'itsup']
COI_MISSING = ['lo2', 'itsup']                 # never submitted a COI declaration (both cycles)
COBEC_MISSING = ['lo1', 'agent', 'itsup']      # 2026 code of ethics still outstanding (not yet due)

# annual COI declarations with a declared interest: key -> (field, details, outcome)
COI_PREV = {
    'it': ('outside_employment', 'Part-time visiting lecturer (information security) at a private university, '
           'two evenings per month; no link to company suppliers or customers.',
           ('Acceptance', 'Activity outside working hours; no access to university procurement. Annual re-confirmation '
            'and HR approval of the teaching schedule.', 'closed')),
    'br1': ('financial_interests', 'Holds 4% of the shares of a family-owned stationery and printing company '
            'that supplies loan application forms to the Cairo Downtown branch.',
            ('Transfer', 'Purchasing of printed forms for the branch moved to Head Office Procurement; '
             'branch manager excluded from supplier evaluation.', 'closed')),
    'hr': ('family_in_competitor', 'Sister works as a credit officer at another licensed microfinance company '
           '(no management role).', ('Acceptance', 'No access to competitor information expected; reminder of '
                                      'confidentiality obligations signed; reviewed annually.', 'closed')),
}
COI_CUR = {   # key -> (field, details, status, plan)
    'it': ('outside_employment', 'Continues part-time visiting lecturing (information security), unchanged from last year.',
           'approved', None),
    'hr': ('family_in_competitor', 'Sister still employed as credit officer at another microfinance company.',
           'approved', None),
    'ops': ('family_in_supplier', 'Spouse is a partner in a furniture and fit-out company that submitted a bid '
            'for the Assiut branch refurbishment tender.',
            'mitigation_in_progress', ('Avoidance', 'Head of Operations recused from the tender committee for the '
                                       'Assiut refurbishment; tender evaluated by Finance and Procurement only; '
                                       'decision documented in the tender file.', 'active')),
    'acc': ('received_gifts', 'Received a Ramadan gift basket (approx. EGP 850) from the external payroll '
            'software vendor; declared in the gifts register.', 'under_review', None),
    'lo1': ('outside_employment', 'Weekend sales work for a relative\'s mobile phone shop in Giza.',
            'requires_clarification', None),
}
COI_ADHOC = {  # event-driven disclosures this year
    'cfo': (130, 'family_in_supplier', 'Brother appointed as relationship manager at the bank arranging the '
            'EGP 150m senior funding facility.', ('Transfer', 'Negotiation of the facility led by the CEO and '
                                                 'the Treasury team; CFO not part of the negotiating team.', 'closed')),
    'lo1': (75, 'other_conflicts', 'Type: personal relationship\nDescription: A cousin applied for a micro-loan '
            'at the Giza branch.\nParties: Applicant (relative)\nMitigation: Application to be handled by another '
            'loan officer.', ('Avoidance', 'Application reassigned to another loan officer and approved by the '
                              'branch manager.', 'closed')),
    'risk': (24, 'other_conflicts', 'Type: family\nDescription: Spouse appointed to a senior role at a credit '
             'information bureau used by the company.\nParties: Credit bureau\nMitigation: Exclude from vendor '
             'decisions on the bureau contract.', ('Mitigation', 'CRO excluded from the credit bureau contract '
                                                   'renewal; contract owner moved to Operations.', 'monitoring')),
}

# GHE: (days ago, employee, type, direction, value, description, counterparty, company, purpose, gov official, outcome)
# outcome: auto | mgr_ok | mgr_pending | comp_ok | comp_reject | comp_pending | clarify
GHE = [
    (352, 'cfo', 'Gift', 'Received', 300, 'Desk calendar and pen set', 'Account manager', 'Horus Print House (demo)', 'New-year courtesy gift', 0, 'auto'),
    (340, 'ops', 'Hospitality', 'Received', 1400, 'Business lunch with the core lending system vendor', 'Sales director', 'Demo Core Systems Ltd', 'Annual service review', 0, 'mgr_ok'),
    (322, 'mlro', 'Hospitality', 'Received', 1800, 'Dinner at a compliance forum organised by an industry association', 'Event organiser', 'Microfinance Forum (demo)', 'Industry networking event', 0, 'mgr_ok'),
    (305, 'br1', 'Gift', 'Received', 250, 'Box of sweets from a client after loan disbursement', 'Client (micro-entrepreneur)', None, 'Thank-you gesture', 0, 'auto'),
    (290, 'it', 'Entertainment', 'Received', 2600, 'Two tickets to a football match', 'Account manager', 'Demo Network Solutions', 'Relationship building', 0, 'comp_reject'),
    (276, 'ceo', 'Hospitality', 'Given', 6500, 'Dinner for the funding bank delegation after signing the facility term sheet', 'Bank delegation (5 people)', 'Example Bank S.A.E. (fictional)', 'Funding relationship', 0, 'comp_ok'),
    (262, 'cs', 'Gift', 'Received', 450, 'Branded power bank', 'Sales representative', 'Demo SMS Gateway Co.', 'Vendor promotional item', 0, 'auto'),
    (248, 'lo2', 'Gift', 'Received', 700, 'Gold-plated pen from a guarantor', 'Guarantor of a group loan', None, 'Unsolicited gift', 0, 'mgr_ok'),
    (233, 'sec', 'Gift', 'Given', 1200, 'Commemorative gifts for board members (end of term)', 'Retiring independent director', None, 'Recognition of service', 0, 'mgr_ok'),
    (219, 'acc', 'Gift', 'Received', 850, 'Ramadan gift basket', 'Account manager', 'Demo Payroll Software', 'Seasonal gift', 0, 'mgr_ok'),
    (214, 'hr', 'Gift', 'Received', 850, 'Ramadan gift basket', 'Account manager', 'Demo Recruitment Partners', 'Seasonal gift', 0, 'mgr_ok'),
    (210, 'ops', 'Gift', 'Given', 3000, 'Eid gifts for local district officials', 'District office staff', 'Local district office', 'Goodwill', 1, 'comp_reject'),
    (196, 'risk', 'Hospitality', 'Received', 2200, 'Conference dinner at a credit risk summit', 'Conference organiser', 'Demo Credit Bureau', 'Industry event', 0, 'comp_ok'),
    (182, 'mlro', 'Hospitality', 'Given', 900, 'Working lunch for the FRA inspection team at Head Office', 'FRA inspection team', 'Financial Regulatory Authority', 'On-site inspection (working lunch, modest)', 1, 'comp_ok'),
    (168, 'br1', 'Gift', 'Received', 380, 'Notebook and agenda set', 'Branch relationship officer', 'Example Bank S.A.E. (fictional)', 'Courtesy gift', 0, 'auto'),
    (151, 'it', 'Gift', 'Received', 9000, 'Smartphone offered at product launch', 'Regional manager', 'Demo Network Solutions', 'Vendor launch event', 0, 'comp_reject'),
    (140, 'cfo', 'Hospitality', 'Received', 1600, 'Lunch with the external auditor engagement partner', 'Engagement partner', 'Demo Audit Partners', 'Year-end close meeting', 0, 'mgr_ok'),
    (126, 'agent', 'Gift', 'Received', 150, 'Chocolates from a customer', 'Customer', None, 'Thank-you gesture', 0, 'auto'),
    (112, 'ceo', 'Entertainment', 'Received', 4800, 'Invitation to a charity gala dinner', 'Board of trustees', 'Demo Development Foundation', 'CSR partnership', 0, 'comp_ok'),
    (98, 'lo1', 'Gift', 'Received', 600, 'Perfume from a loan applicant', 'Loan applicant', None, 'Unsolicited gift (returned)', 0, 'mgr_ok'),
    (90, 'dpo', 'Hospitality', 'Received', 1300, 'Training workshop lunch', 'Workshop organiser', 'Demo Privacy Academy', 'Professional development', 0, 'mgr_ok'),
    (77, 'aml', 'Gift', 'Received', 200, 'Branded mug and USB drive', 'Pre-sales consultant', 'Demo Screening Data Ltd', 'Vendor demo session', 0, 'auto'),
    (66, 'sec', 'Hospitality', 'Given', 2400, 'Lunch for board members after the strategy workshop', 'Board members', None, 'Board strategy day', 0, 'comp_ok'),
    (58, 'cs', 'Gift', 'Received', 1100, 'Gift voucher from a call-centre outsourcing provider', 'Account director', 'Demo Contact Centre Services', 'Contract renewal', 0, 'mgr_ok'),
    (47, 'br1', 'Gift', 'Given', 1800, 'Gifts for the winners of the branch client-of-the-year awards', 'Clients (3)', None, 'Customer engagement event', 0, 'mgr_ok'),
    (39, 'hr', 'Hospitality', 'Received', 1500, 'Dinner invitation from a training provider', 'Managing partner', 'Demo Learning Institute', 'Annual training plan discussion', 0, 'mgr_ok'),
    (31, 'ops', 'Gift', 'Received', 950, 'Leather portfolio', 'Sales manager', 'Demo Card Printing Co.', 'Supplier courtesy gift', 0, 'mgr_ok'),
    (26, 'cfo', 'Hospitality', 'Received', 5200, 'Two-night hotel stay at a funding conference (Sharm El-Sheikh)', 'Conference organiser', 'Demo Impact Investors Network', 'Funding conference speaker', 0, 'comp_ok'),
    (20, 'lo2', 'Gift', 'Received', 300, 'Home-made food basket from a client group', 'Women\'s solidarity group clients', None, 'Thank-you gesture', 0, 'auto'),
    (14, 'it', 'Hospitality', 'Received', 1700, 'Lunch at a cloud hosting provider\'s data centre visit', 'Account manager', 'Demo Cloud Hosting', 'Due-diligence site visit', 0, 'mgr_pending'),
    (11, 'risk', 'Entertainment', 'Received', 3500, 'Tickets to a concert at the Cairo Opera House', 'Partner', 'Demo Credit Bureau', 'Relationship building', 0, 'comp_pending'),
    (8, 'acc', 'Gift', 'Received', 1200, 'Tablet case and wireless headphones', 'Account manager', 'Demo Payroll Software', 'Contract renewal', 0, 'mgr_pending'),
    (6, 'ops', 'Hospitality', 'Given', 2800, 'Lunch for the municipality licensing team during branch inspection (Assiut)', 'Municipality licensing team', 'Assiut municipality', 'Branch licence inspection', 1, 'comp_pending'),
    (4, 'mlro', 'Gift', 'Received', 2100, 'Book set and fountain pen from a law firm', 'Senior partner', 'Demo Legal Advisors', 'Year-end gift', 0, 'clarify'),
    (2, 'agent', 'Gift', 'Received', 350, 'Flowers and chocolates from a customer', 'Customer', None, 'Complaint resolved', 0, 'auto'),
]


def _ago(ctx, days, hour=None):
    return ctx.ago(days, hour if hour is not None else ctx.rnd.randrange(9, 17)).replace(second=0, microsecond=0)


def _ts(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def seed(ctx):
    rnd = ctx.rnd
    U = ctx.uid
    mlro, co, admin = U('mlro'), U('co'), U('admin')
    year = ctx.today.year
    nm = {k: ctx.name(k) for k in STAFF}
    manager = {r['id']: r['manager_id'] for r in ctx.q("SELECT id, manager_id FROM users")}
    n = dict(campaigns=0, coi=0, coi_hist=0, plans=0, plan_hist=0, ghe=0, ghe_hist=0, cobec=0, dc=0, targets=0)

    # ------------------------------------------------------------------ COI
    def coi_campaign(name, yr, start, end, status, ctype, desc):
        n['campaigns'] += 1
        return ctx.ins('coi_campaigns', campaign_name=name, campaign_year=yr, start_date=str(ctx.dago(start)),
                       end_date=str(ctx.dago(end)), is_active=1 if status == 'active' else 0, description=desc,
                       status=status, campaign_type=ctype, created_by=mlro, created_at=_ts(_ago(ctx, start + 2, 10)))

    def hist(did, action, who, before, after, comment, when):
        ctx.ins('coi_declaration_history', declaration_id=did, action=action, performer_id=who, status_before=before,
                status_after=after, comments=comment, created_at=_ts(when))
        n['coi_hist'] += 1

    def plan(did, key, strategy, details, pstatus, created, reviewer):
        target = created + timedelta(days=45)
        pid = ctx.ins('coi_mitigation_plans', declaration_id=did, mitigation_strategy=strategy, plan_details=details,
                      assigned_to=U(key), target_date=str(target.date()), status=pstatus,
                      reviewer_comments='Evidence reviewed; plan completed.' if pstatus == 'closed' else None,
                      created_at=_ts(created), updated_at=_ts(min(target, ctx.now - timedelta(days=1))
                                                              if pstatus != 'active' else created),
                      created_by=reviewer)
        n['plans'] += 1
        ctx.q("UPDATE coi_declarations SET mitigation_plan_id=%s WHERE id=%s", (pid, did))
        ctx.ins('coi_mitigation_history', mitigation_plan_id=pid, action='created', action_by=reviewer,
                action_date=_ts(created), old_status=None, new_status='active', comments='Mitigation plan created')
        n['plan_hist'] += 1
        hist(did, 'mitigation_plan_created', reviewer, 'under_review', 'mitigation_in_progress',
             f'Mitigation plan created: {strategy}', created)
        if pstatus in ('monitoring', 'implemented', 'closed'):
            t = min(created + timedelta(days=20), ctx.now - timedelta(days=2))
            ctx.ins('coi_mitigation_history', mitigation_plan_id=pid, action='status_change', action_by=reviewer,
                    action_date=_ts(t), old_status='active', new_status='monitoring',
                    comments='Controls in place; starting monitoring phase')
            n['plan_hist'] += 1
        if pstatus == 'closed':
            t = min(created + timedelta(days=40), ctx.now - timedelta(days=1))
            ctx.ins('coi_mitigation_history', mitigation_plan_id=pid, action='closed', action_by=reviewer,
                    action_date=_ts(t), old_status='monitoring', new_status='closed',
                    comments='Plan closed and declaration approved')
            n['plan_hist'] += 1
            hist(did, 'approved', reviewer, 'mitigation_in_progress', 'approved', 'Mitigation plan closed', t)
        return pid

    def coi_decl(cid, key, when, conflict, status, reviewer, review_days=None, comment=None):
        flags = {f: 0 for f in ('financial_interests', 'family_in_competitor', 'family_in_supplier',
                                'outside_employment', 'received_gifts', 'other_conflicts')}
        det = {}
        if conflict:
            flags[conflict[0]] = 1
            det = {'financial_interests': 'financial_interests_details', 'family_in_competitor': 'family_competitor_details',
                   'family_in_supplier': 'family_supplier_details', 'outside_employment': 'outside_employment_details',
                   'received_gifts': 'gifts_details', 'other_conflicts': 'other_conflicts_details'}
            det = {det[conflict[0]]: conflict[1]}
        rd = when + timedelta(days=review_days) if review_days is not None else None
        did = ctx.ins('coi_declarations', employee_id=U(key), campaign_id=cid, declaration_date=_ts(when),
                      has_conflict=1 if conflict else 0, details=conflict[1] if conflict else 'No conflicts to declare.',
                      status=status, reviewed_by=reviewer if rd else None, reviewer_id=reviewer if rd else None,
                      review_date=_ts(rd) if rd else None, review_comments=comment if rd else None,
                      created_at=_ts(when), updated_at=_ts(rd or when),
                      **{f'has_{k}': v for k, v in flags.items()}, **det,
                      declaration_statement='I agree to the declaration statement', digital_signature=nm[key],
                      pin_code=f'{rnd.randrange(10000):04d}')
        n['coi'] += 1
        hist(did, 'submitted', U(key), None, 'under_review', 'Form submitted by employee', when)
        return did

    prev_start, prev_end = 340, 295
    c_prev = coi_campaign(f'Annual Conflict of Interest Declaration {year - 1}', year - 1, prev_start, prev_end, 'closed',
                          'annual', 'Annual declaration of interests by all employees as required by the COI Policy '
                                    '(NMF-POL-010). Covers financial interests, family relationships, outside '
                                    'employment and gifts.')
    c_cur = coi_campaign(f'Annual Conflict of Interest Declaration {year}', year, 32, 7, 'active', 'annual',
                         'Annual declaration of interests for the current year. Reminders are sent weekly to '
                         'employees who have not submitted.')
    c_adhoc = coi_campaign(f'Ad-hoc Disclosures {year}', year, (ctx.today - ctx.today.replace(month=1, day=1)).days,
                           -(ctx.today.replace(month=12, day=31) - ctx.today).days, 'active', 'adhoc',
                           'Container for ad-hoc conflict of interest disclosures reported outside of annual campaigns.')
    coi_last = {}
    for cid, start, end, conflicts in ((c_prev, prev_start, prev_end, COI_PREV), (c_cur, 32, 7, COI_CUR)):
        for key in STAFF:
            if key in COI_MISSING:
                ctx.ins('coi_campaign_employees', campaign_id=cid, employee_id=U(key), status='pending',
                        reminder_sent=1, reminder_date=_ts(_ago(ctx, end + 3)), completed_date=None)
                continue
            when = _ago(ctx, start - min(int(rnd.expovariate(1 / 7)), start - end + 4))
            c = conflicts.get(key)
            reviewer = co if key in ('mlro',) else rnd.choice([mlro, co])
            if reviewer == U(key):
                reviewer = mlro
            if cid == c_prev:
                if c:
                    did = coi_decl(cid, key, when, c, 'mitigation_in_progress', reviewer, 3, 'Conflict noted; mitigation plan required.')
                    plan(did, key, c[2][0], c[2][1], 'closed', when + timedelta(days=3, hours=1), reviewer)
                    ctx.q("UPDATE coi_declarations SET status='approved' WHERE id=%s", (did,))
                else:
                    did = coi_decl(cid, key, when, None, 'approved', reviewer, rnd.randrange(1, 6), 'No conflicts declared - approved.')
                    hist(did, 'approved', reviewer, 'under_review', 'approved', 'Approved', when + timedelta(days=2))
                ctx.ins('coi_campaign_employees', campaign_id=cid, employee_id=U(key), status='completed',
                        reminder_sent=0, completed_date=_ts(when + timedelta(days=5)))
            else:
                status = c[2] if c else ('under_review' if key in ('agent', 'sec') else 'approved')
                rdays = None if status == 'under_review' else min(rnd.randrange(1, 5), max((ctx.now - when).days - 1, 0))
                if status == 'requires_clarification':
                    did = coi_decl(cid, key, when, c, status, co, rdays,
                                   'Please confirm working hours and whether the shop sells to company clients.')
                    hist(did, 'requires_clarification', co, 'under_review', 'requires_clarification',
                         'Please confirm working hours and whether the shop sells to company clients.', when + timedelta(days=rdays))
                elif status == 'mitigation_in_progress':
                    did = coi_decl(cid, key, when, c, status, mlro, rdays, 'Material conflict - recusal required.')
                    plan(did, key, c[3][0], c[3][1], c[3][2], when + timedelta(days=rdays), mlro)
                elif status == 'approved':
                    did = coi_decl(cid, key, when, c, status, reviewer, rdays,
                                   'Consistent with last year - approved.' if c else 'No conflicts declared - approved.')
                    hist(did, 'approved', reviewer, 'under_review', 'approved', 'Approved', when + timedelta(days=rdays))
                else:
                    did = coi_decl(cid, key, when, c, status, None)
                ctx.ins('coi_campaign_employees', campaign_id=cid, employee_id=U(key),
                        status='completed' if status == 'approved' else 'submitted', reminder_sent=0,
                        completed_date=_ts(when))
            coi_last[key] = (did, when)
    for key, (days, field, text, pl) in COI_ADHOC.items():
        when = _ago(ctx, days)
        did = coi_decl(c_adhoc, key, when, (field, text), 'mitigation_in_progress', mlro, 2, 'Event-driven disclosure reviewed.')
        plan(did, key, pl[0], pl[1], pl[2], when + timedelta(days=2), mlro)
        if pl[2] == 'closed':
            ctx.q("UPDATE coi_declarations SET status='approved' WHERE id=%s", (did,))
        ctx.ins('coi_campaign_employees', campaign_id=c_adhoc, employee_id=U(key),
                status='completed' if pl[2] == 'closed' else 'submitted', reminder_sent=0, completed_date=_ts(when))

    # ------------------------------------------------------------------ GHE
    seq = {}
    for days, key, typ, direction, value, desc, person, company, purpose, gov, outcome in GHE:
        decl_d = _ago(ctx, days)
        event_d = ctx.dago(days + rnd.randrange(1, 6))
        datestr = decl_d.strftime('%Y%m%d')
        seq[datestr] = seq.get(datestr, 0) + 1
        num = f'GHE-{datestr}-{seq[datestr]:04d}'
        emp = U(key)
        mgr = manager.get(emp) or U('ceo')
        status, auto = {'auto': ('approved', 1), 'mgr_ok': ('approved', 0), 'mgr_pending': ('manager_review', 0),
                        'comp_ok': ('approved', 0), 'comp_reject': ('rejected', 0),
                        'comp_pending': ('compliance_review', 0), 'clarify': ('requires_clarification', 0)}[outcome]
        comp_officer = mlro if key != 'mlro' else co
        if key in ('co', 'aml'):
            comp_officer = mlro
        t1 = decl_d + timedelta(days=rnd.randrange(1, 3), hours=2)
        mgr_date = comp_date = None
        mgr_cmt = comp_cmt = None
        if outcome == 'mgr_ok':
            mgr_date, mgr_cmt = t1, rnd.choice(['Within policy limits - approved.', 'Approved; reasonable and infrequent.',
                                                'Approved - customary seasonal gift.'])
            if 'returned' in purpose:
                mgr_cmt = 'Gift returned to the applicant with a courtesy letter; recorded for transparency.'
        elif outcome in ('comp_ok', 'comp_reject'):
            comp_date = t1
            comp_cmt = ('Approved: proportionate, business purpose documented.' if outcome == 'comp_ok' else
                        'Rejected: value/nature not acceptable under the Gifts & Hospitality Policy; item to be '
                        'declined/returned to the provider.')
            if gov and outcome == 'comp_ok':
                comp_cmt = 'Approved: modest working lunch on company premises during the inspection; no personal benefit.'
            if gov and outcome == 'comp_reject':
                comp_cmt = 'Rejected: gifts to public officials are prohibited under the ABAC rules.'
        elif outcome == 'clarify':
            comp_date = None
        gid = ctx.ins(
            'ghe_declarations', declaration_number=num, employee_id=emp, declaration_date=decl_d.strftime('%Y-%m-%d'),
            ghe_type=typ, direction=direction, event_date=str(event_d), estimated_value_egp=value, currency='EGP',
            description=desc, provider_recipient_name=person, provider_recipient_company=company,
            business_purpose=purpose, is_government_official=gov,
            government_official_details=(company if gov else None),
            government_official_position=('Inspection team' if gov and 'FRA' in person else 'Municipal / district staff') if gov else None,
            status=status, auto_approved=auto,
            manager_id=mgr if outcome in ('mgr_ok', 'mgr_pending') else None,
            manager_approval_date=_ts(mgr_date) if mgr_date else None, manager_comments=mgr_cmt,
            compliance_officer_id=comp_officer if outcome in ('comp_ok', 'comp_reject', 'clarify') else None,
            compliance_approval_date=_ts(comp_date) if comp_date else None, compliance_comments=comp_cmt,
            is_public_submission=0, needs_more_info=1 if outcome == 'clarify' else 0,
            info_request_message=('Please confirm the relationship with the law firm (current/prospective adviser?) '
                                  'and attach a photo of the items.') if outcome == 'clarify' else None,
            info_request_date=_ts(t1) if outcome == 'clarify' else None,
            tracking_id=str(uuid.UUID(int=rnd.getrandbits(128))), created_at=_ts(decl_d),
            updated_at=_ts(mgr_date or comp_date or (t1 if outcome == 'clarify' else decl_d)),
            created_by=emp, updated_by=(mgr if mgr_date else comp_officer if (comp_date or outcome == 'clarify') else emp))
        n['ghe'] += 1
        # history (both tables: the internal and the public tracking view read different ones)
        first = {'auto': 'approved', 'mgr_ok': 'manager_review', 'mgr_pending': 'manager_review'}.get(outcome, 'compliance_review')
        reason = ('Escalation reason: Government Official involvement.' if gov else
                  'Escalation reason: Value exceeds manager approval threshold.' if first == 'compliance_review' else '')
        events = [('Auto-approved' if outcome == 'auto' else 'Created', emp, None, first,
                   f'Declaration submitted with value {float(value)} EGP. {reason}'.strip(), decl_d)]
        if outcome == 'mgr_ok':
            events.append(('Approved', mgr, 'manager_review', 'approved', mgr_cmt, mgr_date))
        elif outcome in ('comp_ok', 'comp_reject'):
            events.append(('Approved' if outcome == 'comp_ok' else 'Rejected', comp_officer, 'compliance_review',
                           status, comp_cmt, comp_date))
        elif outcome == 'clarify':
            events.append(('Clarification Requested', comp_officer, 'compliance_review', 'requires_clarification',
                           'Please confirm the relationship with the law firm and attach a photo of the items.', t1))
        for action, who, before, after, cmt, when in events:
            ctx.ins('ghe_declaration_history', declaration_id=gid, action=action, performer_id=who,
                    status_before=before, status_after=after, comments=cmt, created_at=_ts(when))
            ctx.ins('ghe_approval_history', ghe_declaration_id=gid, action=action, action_by=who,
                    action_date=_ts(when), comments=cmt, old_status=before, new_status=after)
            n['ghe_hist'] += 2

    # ------------------------------------------------------------------ COBEC (first annual cycle this year)
    cobec_open, cobec_due = 51, -9
    for key in STAFF:
        if key in COBEC_MISSING:
            continue
        when = _ago(ctx, cobec_open - 1 - min(int(rnd.expovariate(1 / 9)), 45))
        known = key == 'br1'
        prior = False
        if key in ('co', 'aml', 'sec'):
            status = 'under_review'
        elif known:
            status = 'escalated'
        elif key == 'lo2':
            status = 'requires_clarification'
        else:
            status = 'approved'
        reviewer = mlro if key != 'mlro' else co
        rdays = min(rnd.randrange(1, 6), max((ctx.now - when).days - 1, 0))
        rd = when + timedelta(days=rdays) if status != 'under_review' else None
        cmt = {'approved': rnd.choice(['Approved.', 'Declaration complete - approved.', 'Reviewed - no issues.']),
               'escalated': 'Escalated to the Head of Compliance: reported concern is being handled under the '
                            'Whistleblowing Policy.',
               'requires_clarification': 'Please confirm you have completed the Code of Conduct e-learning before '
                                         're-signing.'}.get(status)
        ctx.ins('cobec_declarations', employee_id=U(key), declaration_year=year, has_read_code=1,
                understands_responsibilities=1, commits_to_compliance=1, will_report_violations=1,
                has_known_violations=1 if known else 0,
                violation_details=('Observed a former colleague sharing client phone numbers with a third-party '
                                   'collection agent; reported to Compliance.') if known else '',
                has_prior_misconduct=1 if prior else 0, misconduct_details='', digital_signature=ctx.name(key),
                status=status, reviewer_id=reviewer if rd else None, review_date=_ts(rd) if rd else None,
                review_comments=cmt if rd else None, created_at=_ts(when), updated_at=_ts(rd or when))
        n['cobec'] += 1

    # ------------------------------------------------------------------ declaration campaigns (org-wide tracker)
    nmf = ctx.units['NMF']
    users = [r['id'] for r in ctx.q("SELECT id FROM users WHERE is_active = 1 ORDER BY id")]
    def coi_sub(cid):
        return {r['employee_id']: (r['id'], r['created_at']) for r in ctx.q(
            "SELECT employee_id, id, created_at FROM coi_declarations WHERE campaign_id = %s", (cid,))}
    cobec_sub = {r['employee_id']: (r['id'], r['created_at']) for r in ctx.q(
        "SELECT DISTINCT ON (employee_id) employee_id, id, created_at FROM cobec_declarations ORDER BY employee_id, id DESC")}
    DC = [('coi', f'COI annual declaration {year - 1}', year - 1, prev_start, prev_end, 'closed', coi_sub(c_prev)),
          ('coi', f'COI annual declaration {year}', year, 32, 7, 'open', coi_sub(c_cur)),
          ('cobec', f'Code of Business Ethics certification {year}', year, cobec_open, cobec_due, 'open', cobec_sub)]
    for module, name, yr, opens, due, status, sub in DC:
        cid = ctx.ins('declaration_campaigns', module=module, name=name, cycle_year=yr, opens_at=ctx.dago(opens),
                      due_at=ctx.dago(due), org_scope_unit_id=nmf, include_descendants=True, status=status,
                      created_by=mlro, created_at=_ago(ctx, opens + 1, 10))
        n['dc'] += 1
        reminders = []
        for uid in users:
            if uid == admin:
                ctx.ins('declaration_campaign_targets', campaign_id=cid, user_id=uid, status='exempt',
                        exempt_reason='System administration account - not an employee', reminder_count=0)
            elif uid in sub:
                did, created = sub[uid]
                ctx.ins('declaration_campaign_targets', campaign_id=cid, user_id=uid, status='submitted',
                        submitted_at=created,
                        declaration_id=did, reminder_count=0)
            else:
                st = 'overdue' if ctx.dago(due) < ctx.today else 'pending'
                rc = 2 if st == 'overdue' else 1
                ctx.ins('declaration_campaign_targets', campaign_id=cid, user_id=uid, status=st,
                        last_reminder_at=_ago(ctx, max(due - 3, 1) if st == 'overdue' else 5, 9), reminder_count=rc)
                reminders.append(uid)
            n['targets'] += 1
        if reminders:
            label = {'coi': 'Conflict of Interest', 'cobec': 'Code of Business Ethics'}[module]
            for i, d in enumerate([opens - 14, max(due - 3, 1)] if due > 0 else [5]):
                ctx.ins('reminder_log', campaign_id=cid, sent_by=mlro, recipients=len(reminders) + (2 if i == 0 and due > 0 else 0),
                        channel='inapp', subject=f'{label} reminder',
                        message=f'Your {label} declaration for {yr} is still outstanding. It was due by '
                                f'{ctx.dago(due).strftime("%d %b %Y")}.',
                        target_filter='all outstanding', sent_at=_ago(ctx, d, 9))
    print('    ' + ', '.join(f'{k} {v}' for k, v in n.items()))
