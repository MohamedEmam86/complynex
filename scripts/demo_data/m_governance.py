"""Board of directors, committees, meetings (agenda, attendance, decisions, actions),
fit & proper, independence, skills, evaluation, board training, succession,
three lines of defence and the governance compliance tracker."""
import json
from datetime import timedelta

# key, name, name_ar, role, independent, executive, expertise, appointed(days ago), email-local, quals, years
MEMBERS = [
    ('chair', 'Dr. Hesham Abdel-Aziz', 'د. هشام عبد العزيز', 'Chairman', 0, 0,
     'Banking, strategy, microfinance', 1650, 'h.abdelaziz', 'PhD Finance; CFA', 31),
    ('vice', 'Eng. Tarek Mansour', 'م. طارق منصور', 'Vice Chairman', 0, 0,
     'Investment, private equity, operations', 1650, 't.mansour', 'MBA; BSc Engineering', 26),
    ('ceo', 'Mostafa El-Sayed', 'مصطفى السيد', 'CEO', 0, 1,
     'Microfinance operations, lending, financial inclusion', 1280, 'ceo', 'MBA; BCom Accounting', 22),
    ('nadia', 'Dr. Nadia Rashwan', 'د. نادية رشوان', 'Independent Director', 1, 0,
     'Audit, IFRS, financial reporting', 1100, 'n.rashwan', 'PhD Accounting; CPA', 28),
    ('waleed', 'Waleed Shawky', 'وليد شوقي', 'Independent Director', 1, 0,
     'Risk management, credit risk, IT governance', 1100, 'w.shawky', 'MSc Risk Management; FRM', 24),
    ('ghada', 'Ghada El-Masry', 'غادة المصري', 'Board Member', 0, 0,
     'Legal, compliance, consumer protection', 900, 'g.elmasry', 'LLM Commercial Law', 19),
    ('samir', 'Dr. Samir Halim', 'د. سمير حليم', 'Independent Director', 1, 0,
     'Human capital, remuneration, ESG', 205, 's.halim', 'PhD Organisational Psychology', 27),
]
FORMER = ('adel', 'Adel Fouad', 'عادل فؤاد', 'Independent Director', 1, 0, 'Human resources, governance', 2400,
          'a.fouad', 'MBA', 33)

# skills 1-5: financial, risk, compliance, technology, strategy, hr, legal, audit, marketing, operations
SKILLS = {
    'chair': (5, 4, 4, 3, 5, 3, 3, 3, 3, 4), 'vice': (5, 3, 3, 3, 5, 3, 2, 3, 4, 4),
    'ceo': (4, 4, 4, 3, 5, 3, 2, 2, 4, 5), 'nadia': (5, 4, 4, 2, 3, 2, 3, 5, 2, 3),
    'waleed': (4, 5, 4, 4, 3, 2, 2, 3, 2, 3), 'ghada': (3, 3, 5, 2, 3, 3, 5, 3, 2, 2),
    'samir': (3, 3, 3, 2, 4, 5, 3, 2, 3, 3), 'adel': (3, 3, 3, 2, 3, 5, 3, 2, 2, 3),
}

COMMITTEES = [  # key, name, ar, type, chair, members, freq, min/yr, charter version
    ('AUD', 'Audit Committee', 'لجنة المراجعة', 'AUDIT', 'nadia', ['waleed', 'ghada'], 'Quarterly', 4, '3.0'),
    ('RSK', 'Risk Committee', 'لجنة المخاطر', 'RISK', 'waleed', ['vice', 'ceo'], 'Quarterly', 4, '2.1'),
    ('NRC', 'Nomination & Remuneration Committee', 'لجنة الترشيحات والمكافآت', 'NOMREM', 'samir',
     ['chair', 'vice'], 'Semi-annual', 2, '2.0'),
    ('CMP', 'AML & Compliance Committee', 'لجنة الالتزام ومكافحة غسل الأموال', 'COMPLIANCE', 'ghada',
     ['nadia', 'ceo'], 'Semi-annual', 2, '1.2'),
]

# (days ago, committee key or None, type, agenda items [(title, type, presenter)], decisions [(title, text, owner, deadline+days, status)])
MEETINGS = [
    (330, None, 'BOARD', [
        ('Approval of Q3 2025 management accounts', 'APPROVAL', 'cfo'),
        ('Portfolio-at-risk (PAR30) trend and collections plan', 'DISCUSSION', 'ops'),
        ('Compliance & AML quarterly report', 'INFORMATION', 'mlro'),
        ('Branch expansion feasibility - Upper Egypt', 'DISCUSSION', 'ceo')],
     [('Approve Q3 2025 management accounts', 'The Board approved the Q3 2025 management accounts as presented by the CFO.', 'cfo', 14, 'COMPLETED'),
      ('Collections improvement plan', 'Management to implement an intensified collections plan for branches with PAR30 above 4%.', 'ops', 90, 'COMPLETED')]),
    (318, 'AUD', 'AUDIT_COMMITTEE', [
        ('Internal audit plan progress', 'INFORMATION', 'audit'),
        ('External auditor engagement for FY2025', 'APPROVAL', 'cfo'),
        ('Open audit findings - status', 'DISCUSSION', 'audit')],
     [('Recommend external auditor reappointment', 'The Committee recommends the reappointment of the external auditor for FY2025 subject to fee review.', 'cfo', 30, 'COMPLETED')]),
    (282, 'NRC', 'NOMREM_COMMITTEE', [
        ('Annual bonus pool FY2025', 'APPROVAL', 'hr'),
        ('Board succession: independent director vacancy', 'DISCUSSION', 'sec')],
     [('Approve FY2025 bonus pool', 'The Committee approved a bonus pool of 1.6 months of basic salary linked to KPIs and compliance gateways.', 'hr', 45, 'COMPLETED'),
      ('Start search for independent director', 'Secretariat to shortlist candidates with HR and ESG expertise to replace the retiring independent director.', 'sec', 120, 'COMPLETED')]),
    (268, None, 'BOARD', [
        ('Approval of the 2026 budget and business plan', 'APPROVAL', 'cfo'),
        ('Risk appetite statement 2026', 'APPROVAL', 'risk'),
        ('Updated AML/CFT policy (v4.0)', 'APPROVAL', 'mlro'),
        ('Board evaluation methodology 2025/2026', 'DISCUSSION', 'sec')],
     [('Approve 2026 budget', 'The Board approved the 2026 budget targeting a 22% growth in the active loan portfolio.', 'cfo', 7, 'COMPLETED'),
      ('Approve Risk Appetite Statement 2026', 'The Board approved the 2026 Risk Appetite Statement including a PAR30 tolerance of 5%.', 'risk', 14, 'COMPLETED'),
      ('Approve AML/CFT Policy v4.0', 'The Board approved version 4.0 of the AML/CFT policy aligned with the latest FRA and EMLCU guidance.', 'mlro', 30, 'COMPLETED')]),
    (240, 'RSK', 'RISK_COMMITTEE', [
        ('Credit risk dashboard and concentration', 'DISCUSSION', 'risk'),
        ('IFRS 9 ECL model recalibration', 'APPROVAL', 'risk'),
        ('Cybersecurity risk posture', 'INFORMATION', 'it')],
     [('Recalibrate ECL model', 'The Committee approved the recalibrated IFRS 9 ECL staging thresholds for microfinance loans.', 'risk', 60, 'COMPLETED'),
      ('Penetration test of mobile channel', 'IT to commission an independent penetration test of the mobile collection channel.', 'it', 75, 'COMPLETED')]),
    (222, 'AUD', 'AUDIT_COMMITTEE', [
        ('FY2025 audited financial statements', 'APPROVAL', 'cfo'),
        ('Management letter points', 'DISCUSSION', 'audit'),
        ('Internal audit annual report 2025', 'INFORMATION', 'audit')],
     [('Recommend FY2025 financial statements', 'The Committee recommends the FY2025 audited financial statements to the Board for approval.', 'cfo', 14, 'COMPLETED'),
      ('Close management letter points', 'Finance to close all high-rated management letter points before the half-year review.', 'cfo', 150, 'IN_PROGRESS')]),
    (208, None, 'BOARD', [
        ('Approval of FY2025 audited financial statements', 'APPROVAL', 'cfo'),
        ('Appointment of new independent director', 'APPROVAL', 'sec'),
        ('Corporate governance report 2025', 'APPROVAL', 'sec'),
        ('Annual AML/CFT report to EMLCU', 'INFORMATION', 'mlro')],
     [('Approve FY2025 financial statements', 'The Board approved the FY2025 audited financial statements and the dividend recommendation to the General Assembly.', 'cfo', 30, 'COMPLETED'),
      ('Appoint Dr. Samir Halim', 'The Board appointed Dr. Samir Halim as independent director subject to FRA fit & proper approval.', 'sec', 30, 'COMPLETED'),
      ('Approve governance report 2025', 'The Board approved the 2025 corporate governance report for disclosure.', 'sec', 21, 'COMPLETED')]),
    (186, 'CMP', 'COMPLIANCE_COMMITTEE', [
        ('Compliance monitoring plan H1 2026', 'APPROVAL', 'mlro'),
        ('Sanctions screening tuning results', 'DISCUSSION', 'aml'),
        ('Consumer complaints trend', 'INFORMATION', 'cs')],
     [('Approve compliance monitoring plan', 'The Committee approved the H1 2026 compliance monitoring plan covering 14 thematic reviews.', 'mlro', 20, 'COMPLETED'),
      ('Complaint root-cause review', 'Customer Service to present a root-cause analysis of repayment-schedule complaints.', 'cs', 60, 'COMPLETED')]),
    (160, None, 'EXTRAORDINARY', [
        ('Securitisation / bank funding facility of EGP 150m', 'APPROVAL', 'cfo'),
        ('Related-party aspects of the facility', 'DISCUSSION', 'dpo')],
     [('Approve bank funding facility', 'The Board approved a EGP 150 million senior funding facility; the Vice Chairman abstained due to a declared interest.', 'cfo', 45, 'COMPLETED')]),
    (152, 'RSK', 'RISK_COMMITTEE', [
        ('Liquidity and funding plan', 'DISCUSSION', 'cfo'),
        ('Climate-related risk assessment (FRA sustainability)', 'DISCUSSION', 'risk'),
        ('Key risk indicators Q1 2026', 'INFORMATION', 'risk')],
     [('Climate risk integration plan', 'Risk to integrate climate-related risk into the ICAAP-equivalent assessment and the risk register.', 'risk', 120, 'IN_PROGRESS')]),
    (124, 'AUD', 'AUDIT_COMMITTEE', [
        ('Q1 2026 financial results', 'INFORMATION', 'cfo'),
        ('Branch audit results - Assiut', 'DISCUSSION', 'audit'),
        ('Whistleblowing cases summary', 'INFORMATION', 'mlro')],
     [('Assiut branch cash-handling remediation', 'Operations to remediate cash-handling control gaps identified at the Assiut branch.', 'ops', 60, 'OVERDUE')]),
    (118, None, 'BOARD', [
        ('Q1 2026 performance and portfolio quality', 'DISCUSSION', 'ceo'),
        ('Information security policy update', 'APPROVAL', 'it'),
        ('Data protection compliance (Law 151/2020)', 'INFORMATION', 'dpo'),
        ('Board training plan 2026', 'APPROVAL', 'sec')],
     [('Approve Information Security Policy v3.1', 'The Board approved the updated Information Security Policy (v3.1).', 'it', 30, 'COMPLETED'),
      ('PDPL licence and registration', 'DPO to complete registration with the data protection regulator and close open gaps.', 'dpo', 120, 'IN_PROGRESS')]),
    (96, 'NRC', 'NOMREM_COMMITTEE', [
        ('Mid-year review of executive KPIs', 'DISCUSSION', 'hr'),
        ('Succession plan for key functions', 'APPROVAL', 'hr')],
     [('Update succession plans', 'HR to update succession plans for CEO, CRO and MLRO with named internal candidates.', 'hr', 90, 'IN_PROGRESS')]),
    (64, 'RSK', 'RISK_COMMITTEE', [
        ('Risk register review H1 2026', 'DISCUSSION', 'risk'),
        ('BCP test results', 'INFORMATION', 'it'),
        ('Outsourcing risk - core banking vendor', 'DISCUSSION', 'it')],
     [('Vendor exit plan', 'IT to document an exit plan for the core lending system vendor.', 'it', 45, 'OVERDUE')]),
    (40, 'AUD', 'AUDIT_COMMITTEE', [
        ('H1 2026 reviewed financial statements', 'APPROVAL', 'cfo'),
        ('Internal audit plan progress H1', 'INFORMATION', 'audit'),
        ('Overdue audit actions', 'DISCUSSION', 'audit')],
     [('Recommend H1 2026 statements', 'The Committee recommends the H1 2026 reviewed financial statements to the Board.', 'cfo', 14, 'COMPLETED'),
      ('Escalate overdue audit actions', 'Department heads with actions overdue more than 60 days to present remediation plans.', 'audit', 45, 'PENDING')]),
    (29, None, 'BOARD', [
        ('H1 2026 results and dividend policy', 'APPROVAL', 'cfo'),
        ('Compliance & AML semi-annual report', 'INFORMATION', 'mlro'),
        ('ESG and sustainability disclosure 2026', 'DISCUSSION', 'risk'),
        ('Board evaluation results 2025/2026', 'DISCUSSION', 'sec')],
     [('Approve H1 2026 financial statements', 'The Board approved the H1 2026 reviewed financial statements.', 'cfo', 14, 'COMPLETED'),
      ('Board evaluation action plan', 'Secretariat to implement the board evaluation action plan (digital board pack, risk deep-dives).', 'sec', 90, 'IN_PROGRESS'),
      ('Sustainability disclosure', 'Risk and Finance to prepare the first FRA sustainability disclosure for board review.', 'risk', 75, 'PENDING')]),
    (8, 'CMP', 'COMPLIANCE_COMMITTEE', [
        ('Compliance monitoring results H1 2026', 'DISCUSSION', 'mlro'),
        ('FRA inspection findings - remediation status', 'DISCUSSION', 'mlro'),
        ('AML training completion', 'INFORMATION', 'hr')],
     [('Close FRA inspection findings', 'Compliance to close the remaining FRA inspection findings and report evidence to the Committee.', 'mlro', 60, 'IN_PROGRESS'),
      ('Training completion escalation', 'HR to escalate staff with overdue mandatory AML training to their line managers.', 'hr', 21, 'PENDING')]),
    (-21, 'AUD', 'AUDIT_COMMITTEE', [
        ('Q3 2026 financial results', 'INFORMATION', 'cfo'),
        ('Internal audit plan 2027 (draft)', 'DISCUSSION', 'audit')], []),
    (-38, 'RSK', 'RISK_COMMITTEE', [
        ('Risk appetite statement 2027 (draft)', 'DISCUSSION', 'risk'),
        ('Cyber resilience review', 'INFORMATION', 'it')], []),
    (-55, None, 'BOARD', [
        ('Budget and business plan 2027', 'APPROVAL', 'cfo'),
        ('Risk appetite statement 2027', 'APPROVAL', 'risk'),
        ('Policy annual review cycle', 'APPROVAL', 'mlro')], []),
]

LOCATIONS = ['Head Office Boardroom, New Cairo', 'Head Office Boardroom, New Cairo', 'Hybrid - Boardroom & MS Teams']


def _ago(ctx, days, hour=None):
    """ctx.ago without microseconds (several pages print the raw timestamp)."""
    return ctx.ago(days, hour).replace(microsecond=0)


def seed(ctx):
    rnd = ctx.rnd
    sec, admin = ctx.uid('sec'), ctx.uid('admin')
    fra = ctx.one("SELECT id FROM regulators WHERE regulator_code = 'FRA'")['id']
    emlcu = (ctx.one("SELECT id FROM regulators WHERE regulator_code = 'EMLCU'") or {}).get('id')

    # ---------------------------------------------------------------- board members
    bm = {}
    for i, (key, name, ar, role, ind, exe, exp, appt, mail, quals, yrs) in enumerate(MEMBERS + [FORMER]):
        former = key == 'adel'
        appt_d = term_start = ctx.dago(appt)
        term_end = appt_d + timedelta(days=3 * 365)
        while term_end < ctx.today and not former:      # renewed term(s)
            term_start, term_end = term_end, term_end + timedelta(days=3 * 365)
        s = SKILLS[key]
        position = 'CHAIRMAN' if role == 'Chairman' else 'VICE_CHAIR' if role == 'Vice Chairman' else 'MEMBER'
        bm[key] = ctx.ins(
            'board_members', member_name=name, member_name_arabic=ar, nationality='Egyptian',
            national_id=f'DEMO-NID-{29000 + i * 137}', date_of_birth=str(ctx.dago(365 * (48 + i * 2) + 40 * i)),
            position=position, role=role,
            member_type='INDEPENDENT' if ind else 'EXECUTIVE' if exe else 'NON_EXECUTIVE',
            is_independent=ind, is_executive=exe, independence_criteria_met='YES' if ind else 'NO',
            highest_qualification=quals.split(';')[0], professional_certifications=quals,
            years_of_experience=yrs, expertise_areas=exp, industry_experience='Financial services; microfinance',
            board_experience=f'{max(2, yrs // 4)} years on boards of financial institutions',
            skills_financial=s[0], skills_risk_management=s[1], skills_compliance=s[2], skills_technology=s[3],
            skills_strategy=s[4], skills_hr=s[5], skills_legal=s[6], skills_audit=s[7], skills_marketing=s[8],
            skills_operations=s[9], appointment_date=str(appt_d), appointment_type='GENERAL_ASSEMBLY',
            term_start_date=str(term_start), term_end_date=str(term_end), term_duration_months=36,
            term_number=1 + (term_start - appt_d).days // 1090, max_consecutive_terms=3,
            email=('ceo@nilemicro.example' if key == 'ceo' else f'{mail}@board.nilemicro.example'),
            phone=f'+20 10 0000 {7100 + i * 11}',
            cbe_approval_reference=f'DEMO-FRA-FP-{2021 + i % 5}-{310 + i}',
            has_conflicts=1 if key == 'vice' else 0,
            conflict_details=('Shareholder in an investment firm that arranges bank funding for NBFIs; '
                              'abstains on related funding decisions.') if key == 'vice' else None,
            onboarding_completed=1, onboarding_date=str(appt_d + timedelta(days=20)),
            annual_fee=0 if exe else (240000 if key == 'chair' else 180000), meeting_fee=0 if exe else 7500,
            committee_fee=0 if exe else 5000, stock_options=0,
            status='INACTIVE' if former else 'ACTIVE',
            resignation_date=str(ctx.dago(214)) if former else None,
            resignation_reason='Retired at the end of his third consecutive term.' if former else None,
            replacement_required=0,
            bio=(f'{name} brings {yrs} years of experience in {exp.lower()}. '
                 f'Holds {quals}. Fictional demo profile.'),
            created_at=str(_ago(ctx, min(appt, 380))), created_by=sec, updated_at=str(_ago(ctx, rnd.randrange(5, 60))),
            updated_by=sec, is_deleted=0)
    active = [m[0] for m in MEMBERS]

    # ---------------------------------------------------------------- committees
    com = {}
    for key, name, ar, typ, chair, mems, freq, mn, ver in COMMITTEES:
        com[key] = ctx.ins(
            'board_committees', committee_name=name, committee_name_arabic=ar, committee_type=typ,
            is_mandatory=1 if typ in ('AUDIT', 'RISK', 'COMPLIANCE') else 0,
            regulatory_requirement='FRA corporate governance rules for non-bank financial institutions',
            chairman_id=bm[chair], min_members=3, max_members=5,
            independence_requirement='Majority independent' if typ in ('AUDIT', 'NOMREM') else 'Chair independent or non-executive',
            min_independent_members=2 if typ == 'AUDIT' else 1, requires_financial_expert=1 if typ == 'AUDIT' else 0,
            charter_version=ver, charter_last_review=str(ctx.dago(rnd.randrange(150, 300))),
            charter_next_review=str(ctx.dago(rnd.randrange(-200, -60))),
            terms_of_reference=f'Charter of the {name} (version {ver}), approved by the Board.',
            meeting_frequency=freq, min_meetings_per_year=mn, quorum_requirement='Majority of members incl. the chair',
            quorum_number=2, last_evaluation_date=str(ctx.dago(45)), evaluation_score=rnd.choice([78, 82, 85, 88]),
            effectiveness_rating='EFFECTIVE', reports_to='Board of Directors', reporting_frequency='After each meeting',
            last_report_date=str(ctx.dago(29)), next_report_due=str(ctx.dago(-55)), is_active=1,
            activation_date=str(ctx.dago(1500)), created_at=str(_ago(ctx, 380)), created_by=sec,
            updated_at=str(_ago(ctx, 45)))
        for j, mk in enumerate([chair] + mems):
            ctx.ins('committee_memberships', committee_id=com[key], member_id=bm[mk],
                    role='CHAIRMAN' if j == 0 else 'MEMBER', meets_requirements=1,
                    independence_status='INDEPENDENT' if mk in ('nadia', 'waleed', 'samir') else 'NON_INDEPENDENT',
                    has_required_expertise=1, expertise_verified_by=ctx.name('sec'),
                    expertise_verified_date=str(ctx.dago(300)),
                    joined_date=str(ctx.dago(200 if mk == 'samir' else 900)),
                    term_start=str(ctx.dago(200 if mk == 'samir' else 900)), term_end=str(ctx.dago(-400)),
                    is_active=1, created_at=str(_ago(ctx, 380)))
    # the retired director used to sit on NomRem
    ctx.ins('committee_memberships', committee_id=com['NRC'], member_id=bm['adel'], role='CHAIRMAN',
            meets_requirements=1, independence_status='INDEPENDENT', joined_date=str(ctx.dago(1500)),
            term_start=str(ctx.dago(1500)), term_end=str(ctx.dago(214)), is_active=0,
            departure_date=str(ctx.dago(214)), departure_reason='Retired from the Board', created_at=str(_ago(ctx, 380)))
    ctx.data['board_members'] = bm
    ctx.data['committees'] = com

    # ---------------------------------------------------------------- meetings
    seqs = {}
    att_tot = {k: [0, 0] for k in bm}
    com_att = {}
    meeting_ids = []
    n_dec = n_act = n_agenda = 0
    for days, ckey, mtype, agenda, decisions in MEETINGS:
        d = ctx.dago(days)
        past = days > 0
        prefix = {'AUD': 'AC', 'RSK': 'RC', 'NRC': 'NRC', 'CMP': 'CC'}.get(ckey, 'BM')
        ref = f'{prefix}-{d.year}-{d.month:02d}'
        agenda_txt = '; '.join(f'{i}. {a[0]}' for i, a in enumerate(agenda, 1))  # single line: summary page escapes <br>
        mid = ctx.ins('board_meetings', meeting_type=mtype, committee_id=com.get(ckey), meeting_date=str(d),
                      meeting_time=('10:00' if ckey is None else '13:00'),
                      location=LOCATIONS[2] if mtype == 'EXTRAORDINARY' else rnd.choice(LOCATIONS),
                      agenda=agenda_txt, minutes_file=None, quorum_met=1 if past else 0,
                      status='COMPLETED' if past else 'SCHEDULED', meeting_reference=ref)
        meeting_ids.append((mid, days, ckey, ref))
        # agenda items
        ag_ids = []
        for i, (title, itype, presenter) in enumerate(agenda, 1):
            ag_ids.append(ctx.ins('meeting_agenda_items', meeting_id=mid, item_number=i, item_title=title,
                                  item_description=f'{title} - paper circulated 7 days before the meeting.',
                                  item_type=itype, presenter_name=ctx.name(presenter),
                                  presenter_member_id=bm['ceo'] if presenter == 'ceo' else None,
                                  estimated_duration=rnd.choice([15, 20, 30, 45]), display_order=i))
            n_agenda += 1
        if not past:
            continue
        # attendance
        if ckey is None:
            people = active if days < 214 else [k for k in active if k != 'samir'] + ['adel']
        else:
            c = next(x for x in COMMITTEES if x[0] == ckey)
            people = [c[4]] + c[5]
            if ckey == 'NRC' and days > 214:
                people = ['adel', 'chair', 'vice']
        for k in people:
            absent = rnd.random() < 0.09
            remote = (not absent) and rnd.random() < 0.2
            ctx.ins('meeting_attendance', meeting_id=mid, member_id=bm[k],
                    attendance_status='ABSENT_WITH_APOLOGY' if absent else 'PRESENT', attended=0 if absent else 1,
                    apology_received=1 if absent else 0,
                    apology_date=str(d - timedelta(days=2)) if absent else None,
                    apology_reason=rnd.choice(['Travelling abroad', 'Medical appointment', 'Prior commitment'])
                    if absent else None, absence_authorized=1 if absent else 0,
                    arrival_time=None if absent else ('10:00' if ckey is None else '13:00'),
                    attended_remotely=1 if remote else 0, remote_platform='MS Teams' if remote else None,
                    technical_issues=0, spoke_in_meeting=0 if absent else 1,
                    contributions_count=0 if absent else rnd.randrange(1, 6),
                    questions_asked=0 if absent else rnd.randrange(0, 4),
                    recorded_at=str(_ago(ctx, days - 1, 15)) if days > 1 else str(_ago(ctx, 0, 15)), recorded_by=sec)
            if days <= 365:
                att_tot[k][1] += 1
                att_tot[k][0] += 0 if absent else 1
            if ckey:
                com_att.setdefault((ckey, k), [0, 0])
                com_att[(ckey, k)][1] += 1
                com_att[(ckey, k)][0] += 0 if absent else 1
        # decisions + action items
        for j, (title, text, owner, dl, status) in enumerate(decisions, 1):
            dl_d = d + timedelta(days=dl)
            if status in ('PENDING', 'IN_PROGRESS') and dl_d < ctx.today:
                status = 'OVERDUE'
            done = status == 'COMPLETED'
            comp = min(dl_d - timedelta(days=rnd.randrange(0, 10)), ctx.today - timedelta(days=1)) if done else None
            dref = f'{ref}/D{j:02d}'
            n_voting = len(people)
            abst = 1 if 'abstained' in text else 0
            ctx.ins('board_decisions', meeting_id=mid, decision_reference=dref, decision_number=dref,
                    decision_date=str(d), decision_title=title, decision_description=text, decision_text=text,
                    vote_type='UNANIMOUS' if not abst else 'MAJORITY', votes_for=n_voting - abst, votes_against=0,
                    votes_abstain=abst, action_required=text, responsible_person=ctx.name(owner),
                    implementation_deadline=str(dl_d), deadline=str(dl_d), implemented=1 if done else 0,
                    implementation_date=str(comp) if comp else None, completion_date=str(comp) if comp else None,
                    status=status, created_at=str(_ago(ctx, max(days - 1, 0), 16)))
            n_dec += 1
            ctx.ins('meeting_action_items', meeting_id=mid, agenda_item_id=ag_ids[min(j - 1, len(ag_ids) - 1)],
                    action_number=j, action_description=text, action_category='STRATEGIC' if ckey is None else 'OPERATIONAL',
                    responsible_person=ctx.name(owner), responsible_department=ctx.user(owner)['job_title'],
                    responsible_committee_id=com.get(ckey), due_date=str(dl_d),
                    priority='HIGH' if status == 'OVERDUE' or ckey in ('AUD', 'CMP') else rnd.choice(['MEDIUM', 'LOW', 'HIGH']),
                    status={'OVERDUE': 'DELAYED'}.get(status, status), completion_date=str(comp) if comp else None,
                    completion_notes='Evidence filed with the Board Secretariat.' if done else None)
            n_act += 1

    for k, (a, t) in att_tot.items():
        if t:
            ctx.q("""UPDATE board_members SET meetings_attended_ytd=%s, meetings_scheduled_ytd=%s,
                     attendance_rate=%s WHERE id=%s""", (a, t, round(100.0 * a / t, 1), bm[k]))
    for (ck, k), (a, t) in com_att.items():
        ctx.q("""UPDATE committee_memberships SET meetings_attended=%s, meetings_scheduled=%s, attendance_rate=%s
                 WHERE committee_id=%s AND member_id=%s""", (a, t, round(100.0 * a / t, 1), com[ck], bm[k]))
    ctx.data['board_meetings'] = meeting_ids

    # ---------------------------------------------------------------- fit & proper
    n_fp = 0
    for key in active + ['adel']:
        s = SKILLS[key]
        rows = []
        if key == 'samir':
            rows.append((212, 'INITIAL', 'APPROVED', 365))
        elif key == 'adel':
            rows.append((560, 'PERIODIC', 'APPROVED', 365))
        else:
            # periodic reviews; two members fall due within the next month
            last = {'chair': 345, 'vice': 352, 'ceo': 290, 'nadia': 250, 'waleed': 240, 'ghada': 180}[key]
            rows.append((last, 'REAPPOINTMENT' if key in ('chair', 'vice') else 'PERIODIC',
                         'CONDITIONAL' if key == 'vice' else 'APPROVED', 365))
        for ago_, typ, result, freq in rows:
            ad = ctx.dago(ago_)
            sc = [rnd.randrange(17, 21), 12 + s[4] + rnd.randrange(0, 3), rnd.randrange(16, 21),
                  rnd.randrange(17, 21), rnd.randrange(14, 20)]
            if result == 'CONDITIONAL':
                sc[4] = 13
            ctx.ins('fit_proper_assessments', member_id=bm[key], assessment_date=str(ad), assessment_type=typ,
                    assessment_period=str(ad.year), honesty_integrity_score=sc[0], competence_capability_score=sc[1],
                    financial_soundness_score=sc[2], reputation_score=sc[3], time_commitment_score=sc[4],
                    criminal_record_check=1, criminal_record_clear=1, credit_check=1, credit_score=rnd.randrange(690, 820),
                    credit_check_clear=1, regulatory_actions_check=1, regulatory_actions_found=0,
                    litigation_check=1, active_litigation=0, bankruptcy_check=1, bankruptcy_history=0,
                    references_checked=1, references_satisfactory=1,
                    references_summary='Two professional references obtained and found satisfactory.',
                    qualifications_verified=1, professional_licenses_valid=1,
                    relevant_experience_years=next(m for m in MEMBERS + [FORMER] if m[0] == key)[10],
                    board_experience_adequate=1, industry_knowledge_adequate=1, total_score=sum(sc),
                    assessment_result=result,
                    conditions_imposed=('Must reduce external board seats to a maximum of three within six months '
                                        'to ensure adequate time commitment.') if result == 'CONDITIONAL' else None,
                    submitted_to_cbe=0, regulator_id=fra, submitted_to_regulator=1,
                    regulator_submission_date=str(ad + timedelta(days=5)),
                    regulator_reference_number=f'DEMO-FRA-FP-{ad.year}-{400 + n_fp}',
                    regulator_approval_date=str(ad + timedelta(days=40)) if ago_ > 45 else None,
                    regulator_approval_status=result if ago_ > 45 else 'UNDER_REVIEW',
                    next_review_date=str(ad + timedelta(days=freq)), review_frequency_months=12,
                    assessed_by=ctx.name('sec'), approved_by='Nomination & Remuneration Committee',
                    created_at=str(_ago(ctx, ago_, 11)), created_by=sec)
            n_fp += 1
            ctx.q("""UPDATE board_members SET fit_proper_assessment_date=%s, fit_proper_status=%s, fit_proper_score=%s,
                     fit_proper_approved_by='FRA', fit_proper_approval_date=%s, fit_proper_next_review=%s WHERE id=%s""",
                  (str(ad), result, sum(sc), str(ad + timedelta(days=40)), str(ad + timedelta(days=freq)), bm[key]))

    # ---------------------------------------------------------------- independence declarations
    n_ind = 0
    for key in active:
        dd = 205 if key == 'samir' else 262 + rnd.randrange(0, 6)
        ind = key in ('nadia', 'waleed', 'samir')
        crit = {c: 1 for c in ('no_material_interest', 'no_employment_5years', 'no_relative_employment',
                               'no_professional_relationship', 'no_significant_business',
                               'no_remuneration_except_fees', 'no_other_directorships', 'served_less_than_9years')}
        expl = None
        if key == 'ceo':
            crit.update(no_employment_5years=0, no_remuneration_except_fees=0)
            expl = 'Executive director - employed by the company as Chief Executive Officer.'
        elif key == 'chair':
            crit.update(no_material_interest=0)
            expl = 'Represents the founding shareholder group (more than 5% shareholding).'
        elif key == 'vice':
            crit.update(no_material_interest=0, no_significant_business=0)
            expl = 'Represents an institutional shareholder; related investment firm arranges funding for the company.'
        elif key == 'ghada':
            crit.update(no_professional_relationship=0)
            expl = 'Her law firm provided paid legal advisory services to the company within the last 3 years.'
        failed = [k for k, v in crit.items() if not v]
        ctx.ins('independence_declarations', member_id=bm[key], declaration_date=str(ctx.dago(dd)),
                declaration_type='ON_APPOINTMENT' if key == 'samir' else 'ANNUAL',
                declaration_period=str(ctx.dago(dd).year), **crit,
                criteria_not_met=json.dumps(failed) if failed else None, explanation=expl,
                independence_status='INDEPENDENT' if ind else 'NON_INDEPENDENT', reviewed_by=sec,
                review_date=str(ctx.dago(dd - 4)), next_declaration_due=str(ctx.dago(dd - 365)))
        n_ind += 1
        ctx.q("UPDATE board_members SET independence_declaration_date=%s, independence_confirmed_by=%s, "
              "last_coi_declaration_date=%s WHERE id=%s",
              (str(ctx.dago(dd)), ctx.name('sec'), str(ctx.dago(dd)), bm[key]))

    # ---------------------------------------------------------------- skills matrix
    for key in active:
        s = SKILLS[key]
        tot = sum(s)
        avg = tot / 10
        lvl = 'EXPERT' if avg >= 4 else 'ADVANCED' if avg >= 3 else 'INTERMEDIATE' if avg >= 2 else 'DEVELOPING'
        gaps = [n for n, v in zip(['financial', 'risk', 'compliance', 'technology', 'strategy', 'HR', 'legal',
                                   'audit', 'marketing', 'operations'], s) if v <= 2]
        ctx.ins('board_skills_matrix', member_id=bm[key], assessment_date=str(ctx.dago(70)),
                assessment_period='2026', financial_expertise=s[0], risk_management=s[1], compliance_regulatory=s[2],
                technology_digital=s[3], strategy_business=s[4], human_resources=s[5], legal=s[6], audit=s[7],
                marketing_sales=s[8], operations=s[9], banking_finance=max(s[0] - 1, 2), payments_fintech=s[3],
                technology=s[3], retail=3, board_experience=4, committee_chair_experience=4 if key in (
                    'nadia', 'waleed', 'samir', 'ghada') else 2, crisis_management=3, stakeholder_management=4,
                arabic_proficiency=5, english_proficiency=4 if key != 'ghada' else 5, other_languages='French' if key in ('chair', 'ghada') else None,
                has_professional_certifications=1,
                certifications_list=next(m for m in MEMBERS if m[0] == key)[9], total_skill_score=tot,
                skill_level=lvl, skill_gaps=', '.join(gaps) or None,
                development_plan=('Targeted board training on ' + ', '.join(gaps)) if gaps else 'Maintain through annual CPD.',
                assessed_by=sec)
        ctx.q("UPDATE board_members SET last_evaluation_date=%s, evaluation_status='COMPLETED', "
              "last_evaluation_score=%s WHERE id=%s", (str(ctx.dago(45)), 70 + tot // 2, bm[key]))

    # ---------------------------------------------------------------- board evaluation
    evals = [('BOARD', None, None, 'External facilitator questionnaire + interviews', 1, 'Demo Governance Advisors (fictional)',
              (82, 76, 85, 80, 74, 84, 78, 79))]
    for key, name, *_ in COMMITTEES:
        evals.append(('COMMITTEE', com[key], None, 'Self-assessment questionnaire', 0, ctx.name('sec'),
                      tuple(rnd.randrange(70, 90) for _ in range(8))))
    for key in ('nadia', 'waleed', 'ghada', 'vice'):
        evals.append(('INDIVIDUAL', None, bm[key], 'Peer review led by the Chairman', 0, 'Dr. Hesham Abdel-Aziz',
                      tuple(rnd.randrange(72, 92) for _ in range(8))))
    for typ, cid, mid_, meth, ext, evaluator, sc in evals:
        avg = sum(sc) / 8
        rating = 'EXCELLENT' if avg >= 80 else 'GOOD' if avg >= 70 else 'SATISFACTORY' if avg >= 60 else 'NEEDS_IMPROVEMENT'
        ctx.ins('board_evaluations', evaluation_period='2025/2026', evaluation_type=typ, board_committee_id=cid,
                member_id=mid_, methodology=meth, evaluator=evaluator, is_external=ext,
                strategy_effectiveness_score=sc[0], risk_oversight_score=sc[1], financial_oversight_score=sc[2],
                compliance_oversight_score=sc[3], decision_quality_score=sc[4], meeting_effectiveness_score=sc[5],
                board_dynamics_score=sc[6], stakeholder_engagement_score=sc[7], independence_score=78,
                diversity_score=64, individual_contribution_score=80 if mid_ else None,
                individual_expertise_score=84 if mid_ else None, individual_commitment_score=82 if mid_ else None,
                total_score=sum(sc), overall_rating=rating,
                strengths='Strong financial oversight, open discussion culture, good attendance.',
                areas_for_improvement='Board packs circulated late; limited time on technology and cyber risk; gender diversity.',
                recommendations='Adopt a digital board portal; add a cyber deep-dive to the annual agenda; consider diversity in the next nomination.',
                action_plan='Board Secretariat action plan approved at the last board meeting.', action_items_created=3,
                improvement_deadline=str(ctx.dago(-60)), progress_review_date=str(ctx.dago(-30)),
                improvements_implemented=0, evaluation_completed=1, completion_date=str(ctx.dago(48)),
                presented_to_board=1 if typ == 'BOARD' else 0, presentation_date=str(ctx.dago(29)) if typ == 'BOARD' else None,
                created_at=str(_ago(ctx, 60)), conducted_by=sec)

    # ---------------------------------------------------------------- board training
    TRAIN = [
        (300, 'AML/CFT obligations of the Board under Law 80/2002', 'REGULATORY', 'AML/CFT', 3, 'IN_PERSON',
         'Compliance & AML Department', ctx.name('mlro'), 1, 'COMPLETED'),
        (245, 'IFRS 9 expected credit loss for microfinance', 'TECHNICAL', 'Finance', 2.5, 'IN_PERSON',
         'Demo Audit Academy (fictional)', 'External partner', 0, 'COMPLETED'),
        (170, 'Cyber risk oversight for directors', 'TECHNICAL', 'Cybersecurity', 2, 'VIRTUAL',
         'IT & Information Security', ctx.name('it'), 1, 'COMPLETED'),
        (110, 'Corporate governance rules for NBFIs - FRA update', 'REGULATORY', 'Governance', 2, 'IN_PERSON',
         'Legal & Board Secretariat', ctx.name('sec'), 1, 'COMPLETED'),
        (52, 'Climate-related financial risk and sustainability disclosure', 'STRATEGIC', 'ESG', 3, 'HYBRID',
         'Demo Sustainability Institute (fictional)', 'External partner', 0, 'COMPLETED'),
        (-28, 'Consumer protection and fair lending', 'REGULATORY', 'Consumer protection', 2, 'IN_PERSON',
         'Compliance & AML Department', ctx.name('co'), 1, 'SCHEDULED'),
        (-70, 'Data protection (Law 151/2020) for directors', 'REGULATORY', 'Data protection', 1.5, 'VIRTUAL',
         'Legal & Board Secretariat', ctx.name('dpo'), 0, 'SCHEDULED'),
    ]
    hours = {k: 0.0 for k in active}
    last_tr = {}
    n_tra = 0
    for days, title, typ, cat, hrs, how, prov, trainer, mand, st in TRAIN:
        td = ctx.dago(days)
        tid = ctx.ins('board_training', training_title=title, training_type=typ, training_category=cat,
                      training_date=str(td), training_time='14:00', duration_hours=hrs,
                      location='Head Office Boardroom, New Cairo' if how != 'VIRTUAL' else 'MS Teams',
                      delivery_method=how, provider_name=prov, provider_type='INTERNAL' if 'fictional' not in prov else 'EXTERNAL',
                      trainer_name=trainer, mandatory=mand, target_audience='All board members',
                      target_members=json.dumps([bm[k] for k in active]), assessment_required=1 if mand else 0,
                      min_pass_score=70 if mand else None, certificate_provided=1,
                      training_objectives=f'Equip directors to oversee {cat.lower()} matters effectively.',
                      status=st, completion_date=str(td) if st == 'COMPLETED' else None,
                      created_at=str(_ago(ctx, max(days + 30, 0) if days > 0 else 20)), created_by=sec,
                      updated_at=str(_ago(ctx, max(days, 1))))
        if st != 'COMPLETED':
            continue
        for k in (active if days < 214 else [x for x in active if x != 'samir']):
            ok = rnd.random() > 0.12
            ctx.ins('board_training_attendance', training_id=tid, member_id=bm[k], attended=1 if ok else 0,
                    attendance_duration=int(hrs * 60) if ok else 0, completion_status='COMPLETED' if ok else 'ABSENT',
                    completion_date=str(td) if ok else None,
                    assessment_score=rnd.randrange(75, 98) if ok and mand else None, passed=1 if ok else 0,
                    certificate_issued=1 if ok else 0, feedback_rating=rnd.randrange(3, 6) if ok else None,
                    feedback_comments=rnd.choice(['Very relevant', 'Useful case studies', 'Would like more time for Q&A', None]) if ok else None,
                    updated_at=str(_ago(ctx, max(days - 1, 0))))
            n_tra += 1
            if ok:
                hours[k] += hrs
                last_tr[k] = td
    for k in active:
        ctx.q("UPDATE board_members SET training_hours_ytd=%s, last_training_date=%s WHERE id=%s",
              (hours[k], str(last_tr.get(k)) if k in last_tr else None, bm[k]))

    # ---------------------------------------------------------------- succession plans
    SUCC = [
        ('Chairman of the Board', 'BOARD', bm['chair'], 'MEDIUM', 'LOW', None,
         [{'name': 'Eng. Tarek Mansour', 'readiness': 'Ready now'}], 0, bm['vice'],
         'Vice Chairman acts as interim chair; NomRem to run a search within 6 months.'),
        ('Chief Executive Officer', 'EXECUTIVE', bm['ceo'], 'HIGH', 'MEDIUM', None,
         [{'name': ctx.name('ops'), 'readiness': '1-2 years'}, {'name': ctx.name('cfo'), 'readiness': '1-2 years'}], 1, None,
         'Head of Operations & Lending acts as interim CEO under board supervision.'),
        ('Head of Compliance & MLRO', 'KEY_FUNCTION', None, 'HIGH', 'MEDIUM', None,
         [{'name': ctx.name('co'), 'readiness': 'Ready in < 1 year'}], 0, None,
         'Senior Compliance Officer acts as deputy MLRO (registered with EMLCU).'),
        ('Chief Risk Officer', 'KEY_FUNCTION', None, 'MEDIUM', 'LOW', None,
         [{'name': 'Risk Analyst (to be hired)', 'readiness': '2+ years'}], 1, None,
         'CFO covers risk reporting temporarily; external search via recruitment firm.'),
        ('Chief Financial Officer', 'EXECUTIVE', None, 'MEDIUM', 'LOW', None,
         [{'name': ctx.name('acc'), 'readiness': '2+ years'}], 1, None, 'Senior Accountant covers reporting; external search.'),
        ('Independent Director - Audit Committee Chair', 'BOARD', bm['nadia'], 'MEDIUM', 'MEDIUM',
         str(ctx.dago(-420)), [], 1, bm['waleed'], 'Waleed Shawky to chair the Audit Committee in the interim.'),
    ]
    for title, ptype, holder, risk, vac, exp_d, cands, ext, interim, plan in SUCC:
        ctx.ins('succession_plans', position_title=title, position_type=ptype, current_holder_id=holder,
                succession_risk=risk, vacancy_risk=vac, critical_position=1, expected_vacancy_date=exp_d,
                notice_period_months=3 if ptype != 'BOARD' else 1, search_timeline_months=6,
                transition_period_months=3, internal_candidates=json.dumps(cands), external_search_required=ext,
                recruitment_firm='Demo Executive Search (fictional)' if ext else None, interim_successor_id=interim,
                interim_plan=plan, acting_arrangements=plan,
                development_programs='Leadership programme; rotation through board committee meetings.',
                mentorship_arrangements='Mentored by the incumbent and a board member.', plan_status='ACTIVE',
                last_review_date=str(ctx.dago(90)), next_review_date=str(ctx.dago(-275)),
                created_at=str(_ago(ctx, 300)), updated_at=str(_ago(ctx, 90)))

    # ---------------------------------------------------------------- three lines of defence
    TLOD = [
        ('Operations & Lending (branches)', 1, 'NMF-OPS', 'ops', 'CEO', 'Loan origination, KYC at onboarding, collections, cash handling.'),
        ('Customer Service', 1, 'NMF-CS', 'cs', 'Head of Operations & Lending', 'Complaint intake, customer disclosures, fair treatment.'),
        ('Finance', 1, 'NMF-FIN', 'cfo', 'CEO', 'Financial reporting, treasury, funding and liquidity.'),
        ('IT & Information Security', 1, 'NMF-IT', 'it', 'CEO', 'System controls, access management, backups, cyber defence.'),
        ('Compliance & AML', 2, 'NMF-COMP', 'mlro', 'AML & Compliance Committee', 'Compliance monitoring, AML/CFT, sanctions screening, regulatory reporting.'),
        ('Risk Management', 2, 'NMF-RISK', 'risk', 'Risk Committee', 'Risk framework, risk appetite, credit and operational risk oversight.'),
        ('Data Protection Office', 2, 'NMF-LEG', 'dpo', 'CEO / Audit Committee', 'Personal data protection compliance and DPIAs.'),
        ('Internal Audit', 3, 'NMF-IA', 'audit', 'Audit Committee', 'Independent assurance over governance, risk management and control.'),
    ]
    for name, line, unit, head, rep, resp in TLOD:
        ctx.ins('three_lines_functions', function_name=name, line_of_defense=line, department=unit,
                function_head_id=ctx.uid(head), reporting_to=rep, independence_confirmed=1 if line > 1 else 0,
                independence_confirmation_date=str(ctx.dago(200)) if line > 1 else None,
                key_responsibilities=resp, created_at=str(_ago(ctx, 360)))
    RACI = [
        ('Customer onboarding & KYC', 'R/A - Branch loan officers perform CDD', 'C - Compliance sets KYC standards, monitors quality', 'I - Audits KYC files annually'),
        ('Transaction monitoring & STR filing', 'R - Branches escalate unusual activity', 'A - MLRO decides and files STRs with EMLCU', 'I - Tests the AML programme'),
        ('Credit approval', 'R/A - Credit committee & branch managers', 'C - Risk sets limits and reviews exceptions', 'I - Reviews credit files'),
        ('Complaints handling', 'R/A - Customer Service', 'C - Compliance monitors trends and root causes', 'I - Periodic review'),
        ('Policy management', 'R - Policy owners draft and implement', 'A - Compliance reviews; Board approves key policies', 'I - Assesses design'),
        ('Information security', 'R/A - IT runs controls', 'C - Risk monitors cyber KRIs', 'I - IT audit'),
        ('Regulatory reporting to FRA', 'R - Finance and Operations prepare data', 'A - Compliance validates and submits', 'I - Samples submissions'),
        ('Business continuity', 'R/A - IT and Operations', 'C - Risk reviews BIA and tests', 'I - Audits BCP'),
    ]
    for area, l1, l2, l3 in RACI:
        ctx.ins('three_lines_raci_matrix', process_area=area, first_line_role=l1, second_line_role=l2, third_line_role=l3,
                description=f'RACI for {area.lower()}.', created_at=str(_ago(ctx, 330)))

    # ---------------------------------------------------------------- governance compliance tracker
    GCT = [
        ('FRA-GOV-01', 'At least one third of the board are independent non-executive directors', 'Board Composition', fra, 'COMPLIANT', 'Board composition: 3 of 7 directors independent (43%).', 95),
        ('FRA-GOV-02', 'Separation of the roles of Chairman and CEO', 'Board Composition', fra, 'COMPLIANT', 'Chairman is non-executive; CEO is a separate person.', 200),
        ('FRA-GOV-03', 'Board meets at least four times a year with documented minutes', 'Board Meetings', fra, 'COMPLIANT', '6 board meetings held in the last 12 months; minutes signed.', 29),
        ('FRA-GOV-04', 'Audit Committee chaired by an independent director with financial expertise', 'Committees', fra, 'COMPLIANT', 'Audit Committee chaired by Dr. Nadia Rashwan (CPA).', 120),
        ('FRA-GOV-05', 'Risk Committee established with an approved charter', 'Committees', fra, 'COMPLIANT', 'Risk Committee charter v2.1 approved.', 150),
        ('FRA-GOV-06', 'Fit & proper approval obtained for all directors and key function holders', 'Fit & Proper', fra, 'IN_PROGRESS', 'FRA approval for the newly appointed independent director awaited; two periodic reviews due.', -20),
        ('FRA-GOV-07', 'Annual independence declarations from all directors', 'Independence', fra, 'COMPLIANT', 'Declarations on file for all 7 directors.', 260),
        ('FRA-GOV-08', 'Annual board and committee performance evaluation', 'Board Effectiveness', fra, 'COMPLIANT', 'External evaluation 2025/2026 completed and presented.', 48),
        ('FRA-GOV-09', 'Board-approved remuneration policy linked to risk and compliance', 'Remuneration', fra, 'PARTIAL', 'Policy approved; malus/clawback clause not yet implemented in contracts.', -45),
        ('FRA-GOV-10', 'Annual corporate governance report disclosed', 'Disclosure', fra, 'COMPLIANT', 'Governance report 2025 approved by the Board.', 208),
        ('FRA-GOV-11', 'Sustainability / climate-related disclosure in line with FRA requirements', 'Disclosure', fra, 'IN_PROGRESS', 'First disclosure being prepared by Risk and Finance.', -75),
        ('FRA-GOV-12', 'Board-approved succession plan for the Board and key executives', 'Succession', fra, 'PARTIAL', 'Plans exist; named candidates for CRO and CFO still missing.', -30),
        ('FRA-GOV-13', 'Related-party transactions approved by the Board with interested members abstaining', 'Conflicts of Interest', fra, 'COMPLIANT', 'Funding facility approved with Vice Chairman abstaining.', 160),
        ('FRA-GOV-14', 'Board-approved IT governance and cyber security framework', 'IT Governance', fra, 'NON_COMPLIANT', 'Vendor exit plan for core lending system overdue (Risk Committee action).', -10),
        ('EMLCU-GOV-01', 'Board oversight of the AML/CFT programme and approval of the AML policy', 'AML Governance', emlcu, 'COMPLIANT', 'AML/CFT policy v4.0 approved; semi-annual MLRO reports to the Board.', 268),
        ('EMLCU-GOV-02', 'Independent MLRO with direct access to the Board', 'AML Governance', emlcu, 'COMPLIANT', 'MLRO reports to the AML & Compliance Committee.', 186),
        ('INT-GOV-01', 'Board training plan delivered (minimum 8 hours per director per year)', 'Board Development', None, 'PARTIAL', 'Average 9.5 hours; two directors below 8 hours.', -70),
    ]
    for code, desc, area, reg, st, ev, dd in GCT:
        done = st == 'COMPLIANT'
        src = ('FRA corporate governance rules for NBFIs' if reg == fra else
               'AML Law 80/2002 & EMLCU guidance' if reg == emlcu else 'Board governance charter')
        ctx.ins('governance_compliance_tracker', requirement_code=code, requirement_description=desc,
                compliance_area=area, regulatory_source=src, compliance_status=st, evidence_description=ev,
                last_audit_date=str(ctx.dago(rnd.randrange(60, 200))), due_date=str(ctx.dago(dd)),
                completion_date=str(ctx.dago(dd)) if done else None, updated_at=str(_ago(ctx, rnd.randrange(3, 90))),
                notes=None if done else 'Tracked by the Board Secretariat; next update at the coming Board meeting.',
                regulator_id=reg, is_active=1)
    print(f'    board members {len(bm)}, committees {len(com)}, meetings {len(MEETINGS)}, agenda {n_agenda}, '
          f'decisions {n_dec}, actions {n_act}, F&P {n_fp}, independence {n_ind}, training attendance {n_tra}')
