"""Data protection (PDPL 151/2020): ROPA, consent purposes & consents, DSRs, breaches, DPIAs, DPO."""
from datetime import timedelta


def _ts(d):
    return d.strftime('%Y-%m-%d %H:%M:%S')


def _wh(d, rnd):
    if d.hour >= 17:
        d = (d + timedelta(days=1)).replace(hour=rnd.randint(9, 11))
    elif d.hour < 9:
        d = d.replace(hour=rnd.randint(9, 11))
    while d.weekday() in (4, 5):
        d += timedelta(days=1)
    return d


PURPOSES = [  # code, en, ar, desc_en, desc_ar, basis, required, categories, recipients, retention
    ('LOAN_SERVICING', 'Loan application & servicing', 'طلب التمويل وخدمته',
     'Assess, disburse and service microfinance loans.', 'دراسة وصرف وخدمة القروض متناهية الصغر.',
     'CONTRACT', 1, 'Identity, contact, business, financial', 'FRA, credit bureau', '5 years after loan closure'),
    ('CREDIT_BUREAU', 'Credit bureau inquiry & reporting', 'الاستعلام والإبلاغ للشركة المصرية للاستعلام الائتماني',
     'Inquiry before approval and monthly reporting of repayment behaviour.', 'الاستعلام قبل الموافقة والإبلاغ الشهري عن السداد.',
     'LEGAL_OBLIGATION', 1, 'Identity, credit history', 'Credit bureau (demo)', '5 years'),
    ('MARKETING_SMS', 'Marketing offers by SMS / phone', 'العروض التسويقية عبر الرسائل والهاتف',
     'Information about new loan products and renewals.', 'معلومات عن منتجات التمويل الجديدة والتجديد.',
     'CONSENT', 0, 'Name, phone, product history', 'None', 'Until consent is withdrawn'),
    ('INSURANCE', 'Credit life insurance enrolment', 'الاشتراك في تأمين الحياة على القرض',
     'Share data with the insurer to cover the outstanding balance.', 'مشاركة البيانات مع شركة التأمين لتغطية الرصيد القائم.',
     'CONTRACT', 1, 'Identity, date of birth, loan amount', 'Insurer (demo)', 'Policy term + 3 years'),
    ('ALT_DATA_SCORING', 'Alternative-data credit scoring', 'التقييم الائتماني بالبيانات البديلة',
     'Use mobile-wallet and utility payment history to score first-time borrowers.',
     'استخدام سجل المحفظة الإلكترونية وفواتير المرافق لتقييم المقترضين لأول مرة.',
     'CONSENT', 0, 'Payment history, telecom data', 'Scoring vendor (demo)', '2 years'),
    ('SURVEYS', 'Customer satisfaction surveys', 'استبيانات رضا العملاء',
     'Short surveys after disbursement and after complaint closure.', 'استبيانات قصيرة بعد الصرف وبعد غلق الشكوى.',
     'LEGITIMATE_INTERESTS', 0, 'Name, phone', 'None', '1 year'),
]

ROPA = [  # code, name, purpose, basis, categories, subjects, recipients, intl, system, owner, retention
    ('ROPA-01', 'Customer onboarding & KYC', 'Identify customers and meet AML/KYC obligations (Law 80/2002)',
     'LEGAL_OBLIGATION', 'National ID, photo, address, phone, business activity', 'Borrowers, guarantors',
     'EMLCU (on request), FRA', 0, 'Core lending system', 'ops', '5 years after relationship ends'),
    ('ROPA-02', 'Credit assessment', 'Assess creditworthiness and repayment capacity', 'CONTRACT',
     'Income, business revenue, household data, bureau report', 'Loan applicants', 'Credit bureau (demo)', 0,
     'Core lending system', 'ops', '5 years'),
    ('ROPA-03', 'Loan disbursement & repayment', 'Disburse funds and collect instalments', 'CONTRACT',
     'Account / wallet numbers, payment history', 'Borrowers', 'Payment aggregators (demo)', 0,
     'Core lending system', 'ops', '5 years after closure'),
    ('ROPA-04', 'Debt collection', 'Recover overdue amounts', 'LEGITIMATE_INTERESTS',
     'Contact data, balances, guarantor details', 'Borrowers, guarantors', 'Outsourced collection agency (demo)', 0,
     'Collection dialler', 'ops', '5 years'),
    ('ROPA-05', 'Credit bureau reporting', 'Monthly reporting to the credit bureau', 'LEGAL_OBLIGATION',
     'Identity, loan and repayment data', 'Borrowers', 'Credit bureau (demo)', 0, 'Bureau interface', 'risk', '5 years'),
    ('ROPA-06', 'AML screening & monitoring', 'Sanctions screening and transaction monitoring', 'LEGAL_OBLIGATION',
     'Identity, transactions, risk rating', 'Customers, counterparties', 'EMLCU', 0, 'ComplyNex', 'mlro',
     '5 years'),
    ('ROPA-07', 'Complaints handling', 'Register and resolve customer complaints', 'LEGAL_OBLIGATION',
     'Contact data, complaint details', 'Customers', 'FRA (referrals)', 0, 'ComplyNex', 'cs', '5 years'),
    ('ROPA-08', 'Marketing campaigns', 'Promote renewals and new products', 'CONSENT', 'Name, phone, product history',
     'Customers who opted in', 'SMS gateway (demo)', 0, 'CRM', 'cs', 'Until withdrawal'),
    ('ROPA-09', 'Credit life insurance', 'Insure outstanding balances', 'CONTRACT', 'Identity, age, loan amount',
     'Borrowers', 'Insurer (demo)', 0, 'Core lending system', 'cfo', 'Policy term + 3 years'),
    ('ROPA-10', 'Employee records & payroll', 'Employment administration', 'CONTRACT',
     'Identity, salary, bank account, social insurance', 'Employees', 'Social insurance authority, bank', 0,
     'HR system', 'hr', '10 years after exit'),
    ('ROPA-11', 'Recruitment', 'Select candidates', 'LEGITIMATE_INTERESTS', 'CV, contact data, references',
     'Applicants', 'None', 0, 'HR system', 'hr', '1 year'),
    ('ROPA-12', 'Branch CCTV', 'Security of staff, customers and cash', 'LEGITIMATE_INTERESTS', 'Video images',
     'Visitors, staff', 'Police (on request)', 0, 'CCTV recorder', 'it', '30 days'),
    ('ROPA-13', 'Whistleblowing', 'Receive and investigate reports of misconduct', 'LEGAL_OBLIGATION',
     'Reporter and suspect data, allegations', 'Employees, third parties', 'Prosecutor (if required)', 0,
     'ComplyNex', 'mlro', '5 years after closure'),
    ('ROPA-14', 'Cloud e-mail & collaboration', 'Internal and external communication', 'LEGITIMATE_INTERESTS',
     'Names, e-mail content, attachments', 'Staff, customers, suppliers', 'Cloud provider (demo)', 1,
     'Cloud e-mail (demo)', 'it', 'Per retention policy'),
    ('ROPA-15', 'Alternative-data scoring pilot', 'Score first-time borrowers without bureau history', 'CONSENT',
     'Wallet and utility payment history', 'Pilot applicants', 'Scoring vendor (demo)', 1,
     'Scoring vendor platform (demo)', 'risk', '2 years'),
]

DSRS = [  # days ago, type, channel, description, status
    (330, 'ACCESS', 'BRANCH', 'Copy of all personal data and loan history held by the company', 'COMPLETED'),
    (301, 'RECTIFICATION', 'BRANCH', 'Correct misspelled name and address on the loan file', 'COMPLETED'),
    (276, 'ERASURE', 'EMAIL', 'Delete all my data after full settlement of my loan', 'REJECTED'),
    (240, 'OBJECTION', 'HOTLINE', 'Stop marketing calls and SMS', 'COMPLETED'),
    (221, 'ACCESS', 'EMAIL', 'Copy of the credit study and the reasons for loan rejection', 'COMPLETED'),
    (190, 'RECTIFICATION', 'BRANCH', 'Update mobile number (old number recycled by operator)', 'COMPLETED'),
    (162, 'PORTABILITY', 'EMAIL', 'Repayment history in electronic format for another lender', 'COMPLETED'),
    (140, 'ERASURE', 'BRANCH', 'Delete data of a rejected loan application', 'COMPLETED'),
    (118, 'RESTRICTION', 'EMAIL', 'Restrict use of my data while a complaint about collection is investigated', 'COMPLETED'),
    (97, 'ACCESS', 'BRANCH', 'Copy of recorded collection calls about my loan', 'COMPLETED'),
    (74, 'OBJECTION', 'HOTLINE', 'Object to use of my wallet data in the scoring pilot', 'COMPLETED'),
    (58, 'ACCESS', 'EMAIL', 'All data shared with the collection agency', 'OVERDUE'),
    (44, 'ERASURE', 'EMAIL', 'Delete CCTV footage showing me at the Giza branch', 'OVERDUE'),
    (26, 'RECTIFICATION', 'BRANCH', 'Correct business activity recorded on my file', 'IN_PROGRESS'),
    (19, 'ACCESS', 'HOTLINE', 'Copy of my personal data and consents', 'IN_PROGRESS'),
    (12, 'OBJECTION', 'EMAIL', 'Stop surveys by phone', 'IN_PROGRESS'),
    (6, 'ACCESS', 'BRANCH', 'Copy of contract and payment schedule', 'NEW'),
    (2, 'RECTIFICATION', 'EMAIL', 'Update home address', 'NEW'),
]


def seed(ctx):
    rnd = ctx.rnd
    U = ctx.uid
    clients = ctx.q("SELECT client_ref, full_name, governorate FROM ln_clients ORDER BY id")

    # ---------------- DPO appointment & activities
    ctx.ins('dpo_appointments', dpo_name=ctx.name('dpo'), dpo_email='dpo@nilemicro.example', dpo_phone='+20 10 0000 4410',
            dpo_office_address='Head office, New Cairo (demo address)',
            qualifications='LL.B., 9 years in banking legal & privacy', certifications='CIPP/E (demo)',
            appointment_date=ctx.dago(420).isoformat(), appointed_by='Board of Directors',
            board_resolution_reference='BR-DEMO-2025-07', registered_with_pdpc=1,
            pdpc_registration_date=ctx.dago(300).isoformat(), pdpc_dpo_id='PDPC-DPO-DEMO-0193',
            published_on_website=1, website_publication_date=ctx.dago(295).isoformat(), is_active=1,
            backup_dpo_name=ctx.name('co'), backup_dpo_email='co@nilemicro.example', backup_dpo_phone='+20 10 0000 4411',
            created_at=_ts(ctx.ago(420, 10)), updated_at=_ts(ctx.ago(295, 11)))
    acts = [
        (350, 'ROPA_REVIEW', 'Annual review of the record of processing activities (15 activities)', 'ROPA updated; 2 new activities added', 0),
        (330, 'TRAINING', 'PDPL awareness session for branch managers and loan officers', '34 staff trained', 0),
        (300, 'REGULATOR', 'DPO registration filed with the Personal Data Protection Center', 'Registration confirmed', 0),
        (270, 'DPIA', 'DPIA review: mobile app & e-wallet repayments', 'Approved with conditions', 0),
        (240, 'POLICY', 'Data retention schedule approved by the Board', 'Retention schedule v2 published', 0),
        (210, 'AUDIT', 'Privacy walk-through of Assiut branch (clean desk, KYC storage)', '3 observations raised', 1),
        (180, 'VENDOR', 'Data processing agreement signed with the collection agency', 'DPA in force', 0),
        (150, 'DSR', 'Monthly DSR performance review', '100% within 30 days in Q1', 0),
        (120, 'DPIA', 'DPIA kick-off: alternative-data credit scoring', 'Vendor questionnaire sent', 1),
        (95, 'TRAINING', 'Phishing & privacy e-learning for head-office staff', '58 staff completed', 0),
        (88, 'BREACH', 'Breach BRC-2607 assessed; notification to PDPC within 72 hours', 'PDPC notified', 1),
        (70, 'BREACH', 'Notification letters to affected customers (BRC-2607)', '1,840 customers notified by SMS', 0),
        (45, 'BOARD', 'Quarterly privacy report to the Audit & Risk Committee', 'Committee requested agency audit', 1),
        (20, 'DSR', 'Escalation of two overdue DSRs to Operations', 'Target dates agreed', 1),
        (6, 'DPIA', 'DPIA review: cloud e-mail migration (draft)', 'Comments sent to IT', 1),
    ]
    for d, typ, desc, out, fu in acts:
        at = _wh(ctx.ago(d, 10), rnd)
        ctx.ins('dpo_activities', activity_date=at.date().isoformat(), activity_type=typ, activity_description=desc,
                outcome=out, follow_up_required=fu, follow_up_date=(at + timedelta(days=30)).date().isoformat() if fu else None,
                logged_by=U('dpo'), created_at=_ts(at))

    # ---------------- ROPA
    for i, (code, name, purpose, basis, cats, subj, recip, intl, system, owner, ret) in enumerate(ROPA):
        rev = ctx.dago(rnd.randint(20, 200))
        ctx.ins('data_processing_activities', activity_code=code, activity_name=name,
                activity_description=f'{name} at {ctx.data.get("company", "Nile Microfinance")} (demo)',
                processing_purpose=purpose, legal_basis=basis, data_categories=cats, data_subject_categories=subj,
                recipients=recip, international_transfer=intl,
                transfer_countries='EU (cloud region)' if intl else None,
                transfer_safeguards='Standard contractual clauses; PDPC licence for cross-border transfer requested' if intl else None,
                retention_period=ret, retention_justification='Retention schedule v2 / AML Law 80/2002',
                security_measures='Role-based access, encryption at rest, logging', data_owner=U(owner),
                system_name=system, last_review_date=rev.isoformat(),
                next_review_date=(rev + timedelta(days=365)).isoformat(), is_active=1,
                created_at=_ts(ctx.ago(400 - i, 10)), updated_at=_ts(ctx.ago(rnd.randint(20, 200), 11)))

    # ---------------- consent purposes & consents
    pids = {}
    for code, en, ar, den, dar, basis, req, cats, recip, ret in PURPOSES:
        r = ctx.one("SELECT id FROM consent_purposes WHERE purpose_code = %s", (code,))
        pids[code] = r['id'] if r else ctx.ins(
            'consent_purposes', purpose_code=code, purpose_name_en=en, purpose_name_ar=ar, purpose_description_en=den,
            purpose_description_ar=dar, legal_basis=basis, is_required=req, data_categories=cats, recipients=recip,
            retention_period=ret, version=1, active=1, created_at=_ts(ctx.ago(420, 10)))
    n_cons = 0
    for c in clients:
        given = ctx.ago(rnd.randint(30, 360), rnd.randint(9, 16))
        for code in ('LOAN_SERVICING', 'CREDIT_BUREAU', 'INSURANCE', 'MARKETING_SMS', 'SURVEYS', 'ALT_DATA_SCORING'):
            if code == 'ALT_DATA_SCORING' and rnd.random() < 0.7:
                continue
            if code in ('MARKETING_SMS', 'SURVEYS') and rnd.random() < 0.25:
                continue
            optional = code in ('MARKETING_SMS', 'SURVEYS', 'ALT_DATA_SCORING')
            withdrawn = optional and rnd.random() < 0.18
            wd = given + timedelta(days=rnd.randint(10, 120)) if withdrawn else None
            if wd and wd > ctx.now:
                wd, withdrawn = None, False
            ctx.ins('consents', data_subject_id=c['client_ref'], data_subject_identifier=c['full_name'],
                    purpose_id=pids[code], consent_given=1, consent_date=_ts(given),
                    consent_method='SIGNED_FORM' if code in ('LOAN_SERVICING', 'CREDIT_BUREAU', 'INSURANCE') else
                    rnd.choice(['SIGNED_FORM', 'SMS_OPT_IN', 'MOBILE_APP']),
                    consent_text=f'{code} consent text v1', ip_address=None, user_agent=None,
                    withdrawn=1 if withdrawn else 0, withdrawal_date=_ts(wd) if wd else None,
                    withdrawal_method=rnd.choice(['HOTLINE', 'BRANCH', 'SMS_STOP']) if wd else None,
                    withdrawal_reason='Customer request' if wd else None, created_at=_ts(given))
            n_cons += 1

    # ---------------- data subject requests
    dsr_ids = []
    for i, (d, typ, ch, desc, status) in enumerate(DSRS):
        c = clients[(i * 7) % len(clients)]
        req = _wh(ctx.ago(d, rnd.randint(9, 15)), rnd)
        due = (req + timedelta(days=30)).date()
        owner = 'dpo' if typ in ('ERASURE', 'RESTRICTION', 'PORTABILITY') else rnd.choice(['dpo', 'co'])
        done = status in ('COMPLETED', 'REJECTED')
        fin = _wh(req + timedelta(days=rnd.randint(9, 27)), rnd) if done else None
        verified = status != 'NEW'
        ver_at = _wh(req + timedelta(days=rnd.randint(1, 3)), rnd) if verified else None
        overdue = 1 if (not done and due < ctx.today) else 0
        rationale = None
        if status == 'REJECTED':
            rationale = ('Erasure refused: loan and KYC records must be kept 5 years after the end of the relationship '
                         '(AML Law 80/2002 & FRA rules); marketing data deleted and processing restricted.')
        elif done:
            rationale = 'Request fulfilled within the PDPL deadline.'
        rid = ctx.ins('data_subject_requests', request_reference=f"DSR-{req:%Y%m}-{1000 + i * 37:04X}",
                      data_subject_name=c['full_name'], data_subject_email=None,
                      data_subject_phone=f"+20 10 0000 {rnd.randint(1000, 9999)}", request_type=typ,
                      request_date=req.date().isoformat(), request_channel=ch, request_description=desc,
                      specific_data_requested=desc, identity_verified=1 if verified else 0,
                      verification_method=rnd.choice(['ID_CARD', 'IN_PERSON', 'EMAIL_TOKEN']) if verified else None,
                      verification_date=ver_at.date().isoformat() if ver_at else None,
                      verified_by=U(owner) if verified else None, assigned_to=U(owner) if verified else None,
                      status=status, due_date=due.isoformat(), days_remaining=(due - ctx.today).days if not done else None,
                      overdue=overdue, data_inventory_completed=1 if done or status == 'OVERDUE' else 0,
                      legal_review_completed=1 if typ == 'ERASURE' and done else 0,
                      legal_exceptions='AML record-keeping (5 years)' if status == 'REJECTED' else None,
                      decision=status if done else None, decision_date=fin.date().isoformat() if fin else None,
                      decision_by=U('dpo') if done else None, decision_rationale=rationale,
                      fulfilled=1 if status == 'COMPLETED' else 0,
                      fulfillment_date=fin.date().isoformat() if status == 'COMPLETED' else None,
                      fulfillment_method='Encrypted PDF by e-mail' if status == 'COMPLETED' and typ in ('ACCESS', 'PORTABILITY')
                      else ('System update' if status == 'COMPLETED' else None),
                      response_sent=1 if done else 0, response_date=fin.date().isoformat() if fin else None,
                      response_method=('Email' if ch == 'EMAIL' else 'Letter at branch') if done else None,
                      closed=1 if done else 0, closed_date=fin.date().isoformat() if fin else None,
                      escalated_to_pdpc=0, created_at=_ts(req), created_by=U('co'))
        dsr_ids.append(rid)

        def tl(at, typ_, text, by):
            ctx.ins('dsr_timeline', request_id=rid, action_date=_ts(at), action_type=typ_, action_description=text,
                    action_by=U(by) if by else None)
        tl(req, 'RECEIVED', f'{typ} request received via {ch.lower()}', 'co')
        if not verified:
            continue
        tl(ver_at, 'IDENTITY_VERIFIED', 'Identity verified against national ID copy on file', owner)
        tl(ver_at + timedelta(minutes=30), 'ASSIGNED', f'Assigned to {ctx.name(owner)}', 'dpo')
        t = _wh(ver_at + timedelta(days=rnd.randint(2, 6)), rnd)
        if t < ctx.now:
            tl(t, 'DATA_COLLECTED', 'Data inventory completed (core lending, CRM, dialler, ComplyNex)', owner)
        if typ == 'ERASURE' and (done or status == 'OVERDUE'):
            tl(t + timedelta(days=2), 'LEGAL_REVIEW', 'Legal review of retention obligations', 'dpo')
        if status == 'OVERDUE':
            tl(_wh(ctx.ago(rnd.randint(1, 5), 10), rnd), 'REMINDER',
               'Deadline passed - waiting for records from the collection agency / branch CCTV vendor; escalated to Head of Operations',
               'dpo')
        if done:
            tl(fin, status, f"Request {status.lower()}. {rationale}", 'dpo')
            tl(fin + timedelta(hours=2), 'RESPONSE_SENT', 'Response sent to the data subject', owner)

    # ---------------- breaches
    breaches = [
        dict(n='BRC-202512-0A41', d=305, typ='ACCIDENTAL_DISCLOSURE', by='Branch manager',
             method='Internal observation',
             desc='Printed KYC forms of 23 customers were found in a regular waste bin outside the Cairo Downtown branch '
                  'instead of the secure shredding box.',
             systems='Paper records', cnt=23, types='Name, national ID number, address', sens=0, harm='Identity misuse',
             sev='LOW', score=5, req=0, notified=0, ind_req=0, status='CLOSED',
             root='Shredding contractor visit missed; temporary staff unaware of the clean-desk procedure.',
             find='Documents recovered within 2 hours; no evidence of misuse.',
             cont='Documents recovered and shredded; bin area secured.', rem='Locked shredding consoles installed; clean-desk training.',
             lessons='Include temporary staff in privacy induction.',
             actions=[('Recover and shred documents', 'br1', 0, 1, 'COMPLETED'),
                      ('Install locked shredding consoles in all branches', 'ops', 20, 35, 'COMPLETED'),
                      ('Clean-desk refresher for branch staff', 'hr', 15, 30, 'COMPLETED')]),
        dict(n='BRC-202607-1C7E', d=88, typ='DATA_THEFT', by='Whistleblower report (WB-2026-0007)',
             method='Whistleblowing hotline',
             desc='An employee of the outsourced collection agency copied the overdue-customers list to a personal USB '
                  'stick. The file contained names, national IDs, phones and outstanding balances.',
             systems='Collection dialler export', cnt=1840, types='Name, national ID, phone, loan balance',
             sens=1, harm='Financial fraud and harassment risk', sev='CRITICAL', score=110, req=1, notified=1,
             ind_req=1, status='REMEDIATING',
             root='Agency workstations allowed USB storage and bulk export; DPA controls not audited.',
             find='USB recovered by the agency; forensic copy shows the file was copied once to a personal laptop.',
             cont='Agency access suspended; USB recovered; export function disabled.',
             rem='USB blocking on agency workstations, export approval workflow, agency audit.',
             lessons='Third-party access must be reviewed quarterly.',
             actions=[('Suspend agency access to the dialler', 'it', 0, 0, 'COMPLETED'),
                      ('Notify the PDPC within 72 hours', 'dpo', 1, 2, 'COMPLETED'),
                      ('Notify affected customers by SMS', 'cs', 5, 18, 'COMPLETED'),
                      ('Block USB storage on all agency workstations', 'it', 10, 25, 'COMPLETED'),
                      ('Onsite privacy audit of the collection agency', 'audit', 30, 75, 'IN_PROGRESS'),
                      ('Amend the DPA with audit and penalty clauses', 'dpo', 30, 95, 'PENDING')]),
        dict(n='BRC-202609-2B19', d=33, typ='PHISHING', by='IT Security (SIEM alert)', method='SIEM alert',
             desc='A head-office mailbox was accessed from abroad after the user entered credentials on a fake login '
                  'page. The mailbox contained about 140 customer e-mails with names and phone numbers.',
             systems='Cloud e-mail', cnt=140, types='Name, phone, e-mail', sens=0, harm='Phishing of customers',
             sev='MEDIUM', score=20, req=0, notified=0, ind_req=0, status='CONTAINED',
             root='MFA not yet enforced for the mailbox group migrated last; user clicked a phishing link.',
             find='No forwarding rules or downloads found; access lasted 40 minutes.',
             cont='Password reset, sessions revoked, MFA enforced.', rem='MFA for all users; phishing simulation follow-up.',
             lessons='Finish MFA rollout before mailbox migration.',
             actions=[('Reset password and revoke sessions', 'itsup', 0, 0, 'COMPLETED'),
                      ('Enforce MFA for all mailboxes', 'it', 3, 14, 'COMPLETED'),
                      ('Targeted phishing training for head office', 'hr', 10, 40, 'IN_PROGRESS')]),
    ]
    bids = []
    for b in breaches:
        disc = ctx.ago(b['d'], 11)
        bdate = disc - timedelta(days=2 if b['typ'] != 'PHISHING' else 0, hours=3)
        closed = disc + timedelta(days=45) if b['status'] == 'CLOSED' else None
        bid = ctx.ins('data_breaches', breach_number=b['n'], breach_date=bdate.date().isoformat(),
                      discovery_date=disc.date().isoformat(), discovered_by=b['by'], discovery_method=b['method'],
                      breach_type=b['typ'], breach_description=b['desc'], affected_systems=b['systems'],
                      affected_individuals_count=b['cnt'], data_types_affected=b['types'],
                      includes_sensitive_data=b['sens'], sensitive_data_types='Financial data (loan balances)' if b['sens'] else None,
                      potential_harm=b['harm'], severity=b['sev'], severity_score=b['score'],
                      pdpc_notification_required=b['req'],
                      pdpc_notification_deadline=_ts(disc + timedelta(hours=72)) if b['req'] else None,
                      pdpc_notified=b['notified'],
                      pdpc_notification_date=_ts(disc + timedelta(hours=46)) if b['notified'] else None,
                      pdpc_reference='PDPC-BR-DEMO-2026-0412' if b['notified'] else None,
                      individuals_notification_required=b['ind_req'], individuals_notified=b['ind_req'],
                      individuals_notification_date=(disc + timedelta(days=12)).date().isoformat() if b['ind_req'] else None,
                      individuals_notification_method='SMS + letter at branch' if b['ind_req'] else None,
                      individuals_notification_count=b['cnt'] if b['ind_req'] else None,
                      root_cause=b['root'], investigation_findings=b['find'], containment_actions=b['cont'],
                      containment_date=(disc + timedelta(days=1)).date().isoformat(), remediation_actions=b['rem'],
                      remediation_status='COMPLETED' if b['status'] == 'CLOSED' else 'IN_PROGRESS',
                      remediation_completion_date=closed.date().isoformat() if closed else None,
                      lessons_learned=b['lessons'], policy_changes='Clean-desk & disposal procedure v3' if closed else None,
                      status=b['status'], created_at=_ts(disc), created_by=U('dpo'), updated_at=_ts(closed or ctx.ago(3, 12)),
                      closed_date=closed.date().isoformat() if closed else None, closed_by=U('dpo') if closed else None)
        bids.append(bid)
        for desc, owner, start, tgt, st in b['actions']:
            target = (disc + timedelta(days=tgt)).date()
            comp = (disc + timedelta(days=max(tgt - rnd.randint(0, 3), start))).date() if st == 'COMPLETED' else None
            if st != 'COMPLETED' and target < ctx.today:
                target = ctx.today + timedelta(days=rnd.randint(10, 30))
            ctx.ins('breach_remediation_actions', breach_id=bid, action_description=desc, action_owner=U(owner),
                    target_date=target.isoformat(), completion_date=comp.isoformat() if comp else None, status=st,
                    notes='Evidence filed in breach folder' if st == 'COMPLETED' else None)
    ctx.data['breach_ids'] = bids

    # ---------------- DPIAs
    dpias = [
        ('DPIA-202511-01', 'Mobile app & e-wallet repayments', 'Customers repay instalments through the mobile app and e-wallets.',
         'Identity, wallet number, payment history', 'Repayment collection', 'Borrowers', 3, 3, 'HIGH', 'APPROVED', 330),
        ('DPIA-202601-02', 'eKYC with national ID verification', 'Remote onboarding with ID OCR and liveness check.',
         'National ID image, selfie / biometric template', 'Customer identification', 'Applicants', 4, 4, 'VERY_HIGH',
         'APPROVED', 270),
        ('DPIA-202603-03', 'Branch CCTV upgrade', 'IP cameras with 30-day retention in all branches.',
         'Video images', 'Security', 'Visitors, staff', 2, 2, 'MEDIUM', 'APPROVED', 210),
        ('DPIA-202606-04', 'Alternative-data credit scoring pilot', 'Vendor model using telecom and utility payment data.',
         'Payment history, telecom metadata', 'Credit assessment', 'First-time applicants', 4, 3, 'HIGH',
         'PENDING_APPROVAL', 120),
        ('DPIA-202608-05', 'Outsourced collection agency', 'Second agency for Upper Egypt with dialler access.',
         'Contact data, balances, guarantors', 'Debt collection', 'Borrowers, guarantors', 3, 4, 'HIGH', 'IN_PROGRESS', 60),
        ('DPIA-202610-06', 'Cloud e-mail migration (phase 2)', 'Move branch mailboxes to the cloud tenant.',
         'E-mail content', 'Communication', 'Staff, customers', 2, 3, 'MEDIUM', 'DRAFT', 9),
    ]
    for ref, name, desc, cats, purp, subj, lik, imp, lvl, st, d in dpias:
        created = ctx.ago(d, 10)
        appr = st == 'APPROVED'
        ctx.ins('dpias', assessment_reference=ref, system_name=name, processing_description=desc, data_categories=cats,
                purposes=purp, data_subjects_affected=subj, data_retention_period='Per retention schedule v2',
                data_security_measures='Encryption, RBAC, logging, vendor DPA', risk_likelihood=lik, risk_impact=imp,
                overall_risk_score=lik * imp, risk_level=lvl,
                mitigation_measures='Data minimisation, MFA, retention limits, vendor audit rights' if st != 'DRAFT' else None,
                residual_risk_acceptable=1 if appr else None,
                dpo_advice='Proceed with conditions: annual review and access logging' if appr or st == 'PENDING_APPROVAL' else None,
                dpo_consulted=1 if st != 'DRAFT' else 0,
                dpo_consultation_date=(created + timedelta(days=10)).date().isoformat() if st != 'DRAFT' else None,
                senior_management_approval=1 if appr else 0,
                approval_date=(created + timedelta(days=25)).date().isoformat() if appr else None,
                review_date=(created + timedelta(days=390)).date().isoformat() if appr else None,
                status=st, created_at=_ts(created), created_by=U('dpo'))

    print(f'    ropa {len(ROPA)}, consents {n_cons}, dsr {len(dsr_ids)}, breaches {len(bids)}, dpias {len(dpias)}')
