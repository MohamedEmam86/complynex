"""Enterprise risk management: risk register (35 risks), score history over 12 months, appetite,
control library + tests, KRIs with 12 monthly measurements, treatments / action plans."""
from datetime import date, datetime, timedelta

FREQ_DAYS = {'MONTHLY': 30, 'QUARTERLY': 91, 'SEMI_ANNUAL': 182, 'ANNUAL': 365}

NEW_CATEGORIES = [
    ('ESG', 'ESG & Climate Risk', 'Environmental, social and governance risks, including physical and transition '
                                  'climate risk in the loan portfolio and FRA sustainability disclosures.'),
    ('LEG', 'Legal Risk', 'Unenforceable contracts, litigation, data-protection and other legal exposures.'),
]

# key, cat, dept, owner, title, description, existing controls, L, I, start residual (l,i), final residual (l,i),
# control effectiveness, response, review frequency, created days ago, status, overdue review
RISKS = [
    ('par', 'CRD', 'NMF-OPS', 'ops', 'Deterioration of portfolio quality - PAR30 above the 5% FRA threshold',
     'Portfolio at risk over 30 days has risen from 3.1% to 9.8% over the year, driven mainly by the Cairo Downtown '
     'branch (micro-trade clients hit by price inflation). Sustained PAR above 5% breaches the FRA prudential '
     'threshold and erodes capital through higher ECL provisions.',
     'Daily arrears report per loan officer; weekly branch portfolio review; collections escalation matrix.',
     4, 5, (2, 4), (4, 4), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'MONTHLY', 360, 'ACTIVE', False),
    ('overindebt', 'CRD', 'NMF-OPS', 'ops', 'Over-indebtedness of clients borrowing from several MFIs',
     'Group-lending and individual micro clients increasingly hold loans with two or more finance companies. '
     'Credit-bureau checks are not consistently performed for renewals below EGP 30,000.',
     'I-Score credit bureau inquiry for new clients; debt-service ratio cap of 50% of net household income.',
     4, 3, (3, 3), (3, 3), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 355, 'ACTIVE', False),
    ('creditstudy', 'CRD', 'NMF-OPS', 'ops', 'Weak credit studies - templated cash-flow figures in loan files',
     'File reviews found identical income and expense figures copied across unrelated loan files, so repayment '
     'capacity is not really assessed. Raised by the FRA inspection and confirmed by internal audit.',
     'Credit committee sign-off above EGP 50,000; branch manager review of every file.',
     4, 4, (3, 4), (2, 4), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 300, 'ACTIVE', False),
    ('sector', 'CRD', 'NMF-RISK', 'risk', 'Sector concentration in micro-trade and food retail (Giza)',
     'Over 40% of the Giza branch portfolio is in small grocery and food retail, which is sensitive to '
     'price controls and inflation.',
     'Monthly sector concentration report; branch sector limits in the credit policy.',
     3, 3, (3, 2), (3, 2), 'EFFECTIVE', 'ACCEPT', 'SEMI_ANNUAL', 350, 'ACTIVE', False),
    ('lofraud', 'OPR', 'NMF-OPS', 'ops', 'Loan officer fraud - ghost borrowers and diversion of loan proceeds',
     'Loan officers control the client relationship end to end (origination, disbursement follow-up and '
     'collection), which allows fictitious clients or diversion of funds if supervision is weak.',
     'Client acknowledgement of receipt of funds; random client visits by branch manager; job rotation.',
     3, 4, (2, 4), (2, 4), 'EFFECTIVE', 'MITIGATE', 'QUARTERLY', 358, 'ACTIVE', False),
    ('cash', 'OPR', 'NMF-OPS', 'br1', 'Cash handling losses at branches',
     'Branches still receive part of the instalments in cash; shortages, counterfeit notes and robbery '
     'exposure during transfer to the bank.',
     'Daily cash count with dual custody; cash-in-transit insurance; vault limits per branch.',
     3, 3, (3, 3), (2, 3), 'EFFECTIVE', 'TRANSFER', 'QUARTERLY', 340, 'ACTIVE', False),
    ('resched', 'OPR', 'NMF-OPS', 'ops', 'Manual errors in rescheduling and fee calculation',
     'Rescheduling and early-repayment calculations are partly done in spreadsheets outside the core system, '
     'causing wrong fees and client disputes.',
     'Second-person check of rescheduling calculations; monthly sample review by Finance.',
     3, 3, (3, 3), (2, 2), 'EFFECTIVE', 'MITIGATE', 'QUARTERLY', 330, 'ACTIVE', False),
    ('keypeople', 'OPR', 'NMF-HR', 'hr', 'Loan officer turnover and vacancies in key functions',
     'Annual loan officer turnover reached 28%; portfolios are reassigned to new officers with no client history. '
     'Two key functions notified to the FRA were vacant for over 60 days during the year.',
     'Retention bonus for loan officers; succession plan for key functions; notification checklist to FRA.',
     4, 3, (2, 3), (3, 3), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 320, 'ACTIVE', False),
    ('cdd', 'FCR', 'NMF-COMP', 'mlro', 'Incomplete customer due diligence for micro-enterprise clients',
     'KYB fields (tax card, senior management, beneficial owners) are missing on part of the micro-enterprise '
     'portfolio and KYC refresh is overdue for some high-risk clients.',
     'Mandatory KYC fields in the core system; quarterly KYC completeness report; EDD for high-risk clients.',
     4, 4, (4, 3), (3, 3), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'MONTHLY', 362, 'ACTIVE', False),
    ('str', 'FCR', 'NMF-COMP', 'mlro', 'Late detection and reporting of unusual transactions to EMLCU',
     'Unusual repayment patterns (early settlement in cash, third-party repayments) are identified late and '
     'some cases were studied after the internal SLA.',
     'Transaction monitoring rules on repayments; unusual-transactions register; MLRO weekly review.',
     3, 5, (3, 4), (2, 4), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 362, 'ACTIVE', False),
    ('sanctions', 'FCR', 'NMF-COMP', 'aml', 'Sanctions and terrorist-list screening gaps',
     'Failure to screen clients, guarantors or staff against the UN Security Council and local terrorist lists '
     'at onboarding and on every list update.',
     'Automated screening at onboarding; daily re-screening on list updates; staff screening at hiring.',
     2, 5, (2, 5), (1, 5), 'EFFECTIVE', 'MITIGATE', 'QUARTERLY', 362, 'ACTIVE', False),
    ('mule', 'FCR', 'NMF-COMP', 'aml', 'Misuse of loans for illicit purposes or third-party repayment',
     'Loan proceeds used by a third party or repaid from unrelated sources (money-mule pattern).',
     'Post-disbursement visit within 30 days; repayment source checks above EGP 20,000.',
     2, 4, (2, 3), (2, 3), 'EFFECTIVE', 'MITIGATE', 'SEMI_ANNUAL', 250, 'ACTIVE', False),
    ('amlgov', 'FCR', 'NMF-COMP', 'mlro', 'AML governance - MLRO independence and board approval of the AML report',
     'The FRA inspection noted that the MLRO reporting line and the board approval of the annual AML report '
     'were not evidenced.',
     'MLRO reports to the Board Audit & Risk Committee; annual AML report on the board agenda.',
     3, 4, (2, 3), (3, 3), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 200, 'ACTIVE', False),
    ('ransom', 'TEC', 'NMF-IT', 'it', None, None,
     'EDR on all endpoints; offline encrypted backups; MFA for remote access.',
     3, 5, (3, 5), (2, 5), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 345, 'ACTIVE', False),
    ('lockin', 'TEC', 'NMF-IT', 'it', None, None,
     'Escrow agreement for source code; annual vendor performance review.',
     3, 3, (3, 3), (3, 3), 'PARTIALLY_EFFECTIVE', 'ACCEPT', 'SEMI_ANNUAL', 345, 'ACTIVE', False),
    ('vulns', 'TEC', 'NMF-IT', 'it', 'Unpatched vulnerabilities and weak privileged access management',
     'The latest penetration test reported 4 critical / 9 high findings on the client portal and core system; '
     'shared administrator accounts are still used on two servers.',
     'Monthly patch cycle; annual penetration test; privileged access review.',
     4, 4, (3, 3), (3, 4), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'MONTHLY', 280, 'ACTIVE', False),
    ('drsite', 'TEC', 'NMF-IT', 'it', 'Inadequate disaster recovery site and backups',
     'The DR site test in August 2025 was only partly successful (core system RTO 31h against 8h target) and '
     'off-site encrypted backups did not cover every system.',
     'Nightly backups; DR site with replication; annual DR test.',
     3, 4, (3, 4), (2, 4), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 362, 'ACTIVE', True),
    ('mobile', 'TEC', 'NMF-IT', 'itsup', 'Outages of the mobile collection channel and e-wallet integration',
     'Instalments paid by e-wallet are posted late when the integration fails, generating false arrears and '
     'client complaints.',
     'Integration monitoring with alerting; daily reconciliation of e-wallet receipts.',
     3, 3, (3, 3), (2, 3), 'EFFECTIVE', 'MITIGATE', 'QUARTERLY', 210, 'ACTIVE', False),
    ('missell', 'CON', 'NMF-CS', 'cs', 'Inadequate disclosure of total cost of credit and early-repayment cost',
     'Clients are not always given the written cost comparison before early repayment followed by a new, '
     'costlier loan, contrary to FRA consumer-protection rules.',
     'Key facts statement at disbursement; written early-repayment disclosure signed by the client.',
     3, 4, (3, 3), (2, 3), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 300, 'ACTIVE', False),
    ('collect', 'CON', 'NMF-OPS', 'ops', 'Aggressive collection practices by field staff',
     'Complaints of repeated visits at night and pressure on guarantors; risk of FRA sanctions and reputational '
     'damage.',
     'Code of conduct for collections; complaints hotline; call recording for collection calls.',
     3, 4, (2, 3), (2, 4), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 290, 'ACTIVE', False),
    ('complaints', 'CON', 'NMF-CS', 'cs', 'Complaints not resolved within FRA timelines',
     'Branch complaints were logged late in the central system; part of them exceeded the 15-day resolution target.',
     'Central complaints register; weekly ageing report; escalation after 10 days.',
     3, 3, (3, 3), (2, 3), 'EFFECTIVE', 'MITIGATE', 'QUARTERLY', 330, 'ACTIVE', False),
    ('funding', 'LIQ', 'NMF-FIN', 'cfo', 'Funding concentration on two bank credit lines',
     'Two banks provide 78% of borrowings; a non-renewal or covenant breach would stop new disbursements.',
     'Monthly covenant monitoring; funding plan approved by the board; relationship with three additional lenders.',
     4, 4, (3, 4), (3, 4), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'MONTHLY', 362, 'ACTIVE', False),
    ('mismatch', 'LIQ', 'NMF-FIN', 'cfo', 'Liquidity gap between disbursement pipeline and available funding',
     'Seasonal peaks (Ramadan, school season) push disbursement demand above available cash; disbursements were '
     'delayed in March 2026.',
     '13-week cash-flow forecast; minimum cash buffer of 30 days of disbursements.',
     3, 4, (3, 4), (2, 4), 'EFFECTIVE', 'MITIGATE', 'MONTHLY', 362, 'ACTIVE', False),
    ('capital', 'CMP', 'NMF-FIN', 'cfo', 'Paid-up capital below the FRA licence minimum pending capital increase',
     'Losses from higher provisions reduced equity; paid-up capital is below the licence minimum until the '
     'capital increase approved by the EGM is paid in.',
     'Monthly capital adequacy monitoring; EGM-approved capital increase with shareholder commitments.',
     4, 5, (2, 4), (3, 5), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'MONTHLY', 362, 'ACTIVE', False),
    ('regreport', 'CMP', 'NMF-COMP', 'co', 'Late or inaccurate regulatory reporting to the FRA',
     'Monthly and quarterly FRA returns depend on manual extracts; one return was filed late during the year.',
     'Regulatory calendar with reminders; four-eyes review of every return before submission.',
     3, 4, (3, 3), (2, 3), 'EFFECTIVE', 'MITIGATE', 'QUARTERLY', 362, 'ACTIVE', False),
    ('feecap', 'CMP', 'NMF-COMP', 'co', 'Administrative fees above the FRA cap',
     'Administrative fees on some small loans exceed the cap and the tiered fee schedule by financing bracket.',
     'Fee table configured in the core system; monthly fee compliance check by Compliance.',
     3, 4, (2, 3), (3, 4), 'INEFFECTIVE', 'MITIGATE', 'MONTHLY', 280, 'ACTIVE', False),
    ('digital', 'STR', 'NMF', 'ceo', 'Competition from digital lenders and buy-now-pay-later apps',
     'Digital lenders target the same urban micro-entrepreneurs with instant approval; client retention in Cairo '
     'fell during the year.',
     'Product committee; quarterly market review; digital onboarding project.',
     4, 3, (3, 3), (4, 3), 'NOT_ASSESSED', 'ACCEPT', 'SEMI_ANNUAL', 362, 'ACTIVE', False),
    ('transform', 'STR', 'NMF-IT', 'it', 'Delay in the core lending system upgrade programme',
     'The core system upgrade (digital onboarding, automated scoring) is four months behind plan.',
     'Steering committee every month; vendor milestone payments.',
     3, 3, (2, 3), (3, 3), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 240, 'ACTIVE', False),
    ('fx', 'STR', 'NMF-FIN', 'cfo', 'EGP depreciation raising operating and technology costs',
     'Software licences and hardware are priced in USD; further EGP depreciation raises the cost-to-income ratio.',
     'Annual budget with FX sensitivity; local-currency contracts where possible.',
     3, 3, (3, 3), (3, 3), 'NOT_ASSESSED', 'ACCEPT', 'ANNUAL', 330, 'ACCEPTED', False),
    ('climate', 'ESG', 'NMF-RISK', 'risk', 'Climate-related losses in the agricultural portfolio of Upper Egypt',
     'Heat waves and irrigation water shortages affect crop yields of Assiut agricultural clients, raising '
     'default risk in that segment.',
     'Climate vulnerability flag at loan approval; seasonal repayment schedules for farmers.',
     3, 4, (2, 3), (3, 3), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'SEMI_ANNUAL', 270, 'ACTIVE', False),
    ('esgdisc', 'ESG', 'NMF-RISK', 'risk', 'Non-compliance with FRA ESG, TCFD and carbon-footprint reporting',
     'First-year FRA sustainability disclosures and the verified carbon-footprint report require data that is '
     'not yet collected systematically.',
     'ESG reporting calendar; carbon data owners per site; external verifier engaged.',
     3, 3, (3, 3), (2, 3), 'EFFECTIVE', 'MITIGATE', 'QUARTERLY', 300, 'ACTIVE', False),
    ('contracts', 'LEG', 'NMF-LEG', 'dpo', 'Unenforceable loan contracts - missing signatures and guarantor documents',
     'Some financing contracts were not signed by both parties or lack guarantor IDs, weakening legal recovery.',
     'Contract checklist before disbursement; legal review of templates.',
     3, 4, (3, 3), (2, 3), 'EFFECTIVE', 'MITIGATE', 'QUARTERLY', 320, 'ACTIVE', False),
    ('pdpl', 'LEG', 'NMF-LEG', 'dpo', 'Non-compliance with the Personal Data Protection Law (151/2020)',
     'Client data is shared with collection agents and kept beyond retention periods; consent records are '
     'incomplete.',
     'Data protection policy; DPO appointed; data processing agreements with vendors.',
     3, 4, (3, 4), (2, 4), 'PARTIALLY_EFFECTIVE', 'MITIGATE', 'QUARTERLY', 300, 'ACTIVE', True),
    ('media', 'REP', 'NMF', 'ceo', 'Negative media and social-media coverage of collection practices',
     'A viral post about collection visits could damage the brand and attract FRA attention.',
     'Media response protocol; social-media monitoring; complaint escalation to the CEO office.',
     2, 4, (2, 3), (2, 3), 'EFFECTIVE', 'MITIGATE', 'SEMI_ANNUAL', 290, 'ACTIVE', False),
    ('agents', 'TPR', 'NMF-OPS', 'ops', 'Dependence on third-party payment collection networks',
     'Most instalments are collected through outsourced payment networks; outages or late settlement '
     'distort arrears and liquidity.',
     'Service level agreements with penalties; daily settlement reconciliation.',
     3, 3, (3, 3), (2, 3), 'EFFECTIVE', 'TRANSFER', 'SEMI_ANNUAL', 330, 'ACTIVE', False),
    ('paperfiles', 'OPR', 'NM-GIZ-02', 'br1', 'Loss of paper loan files at the Giza branch archive',
     'Paper loan files were stored in an unprotected room exposed to fire and water damage.',
     'Fire-proof cabinets; scanning of all active files into the document management system.',
     3, 3, (2, 3), (1, 2), 'EFFECTIVE', 'MITIGATE', 'SEMI_ANNUAL', 362, 'CLOSED', False),
    ('genai', 'TEC', 'NMF-IT', 'it', 'Staff use of public generative-AI tools with client data',
     'Staff may paste client data into public AI chat tools when drafting letters or credit memos.',
     None, 3, 3, None, None, None, None, 'QUARTERLY', 9, 'DRAFT', False),
]
EXISTING = {'ransom': 'RSK-IT-DEMO-1', 'lockin': 'RSK-IT-DEMO-2'}

APPETITE = [  # category, level, inherent max, residual max, text
    (None, 'CAUTIOUS', 16, 10, 'Nile Microfinance takes credit risk to serve micro-entrepreneurs but will not accept '
     'risks that threaten its licence, its capital or fair treatment of clients. Any residual risk above 10 is '
     'reported to the Board Audit & Risk Committee.'),
    ('CRD', 'OPEN', 20, 12, 'Credit risk is our core business. PAR30 must stay below the FRA 5% threshold and '
     'write-offs below 2% of the average portfolio.'),
    ('OPR', 'CAUTIOUS', 12, 8, 'Operational losses must stay below 0.5% of annual income; no tolerance for staff fraud.'),
    ('FCR', 'AVERSE', 9, 6, 'Zero tolerance for knowingly facilitating money laundering or terrorist financing; '
     'all FRA and EMLCU AML/CFT requirements must be met.'),
    ('TEC', 'CAUTIOUS', 12, 9, 'Critical systems must be recoverable within 8 hours; no critical vulnerability '
     'open for more than 30 days.'),
    ('CON', 'MINIMAL', 9, 6, 'Clients must be treated fairly: full cost disclosure, no abusive collection, '
     'complaints resolved within 15 days.'),
    ('LIQ', 'CAUTIOUS', 12, 9, 'Keep at least 30 days of planned disbursements in cash and no single lender above '
     '50% of borrowings.'),
    ('CMP', 'AVERSE', 9, 6, 'No tolerance for breaches of FRA licensing, capital or reporting rules.'),
    ('STR', 'OPEN', 16, 12, 'We accept strategic risk to grow digital channels within the approved business plan.'),
    ('REP', 'MINIMAL', 9, 6, 'Protect the trust of clients, lenders and the regulator; reputational events are '
     'escalated to the CEO within 24 hours.'),
    ('TPR', 'CAUTIOUS', 12, 9, 'Critical outsourcing only with SLAs, exit plans and annual vendor review.'),
    ('ESG', 'CAUTIOUS', 12, 9, 'Climate exposure of the agricultural portfolio is monitored; FRA sustainability '
     'disclosures are filed on time and verified.'),
    ('LEG', 'MINIMAL', 9, 6, 'Every financing contract must be enforceable; personal data processed lawfully.'),
]

# code, name, description, type, nature, owner, dept, frequency, [(risk key, reliance)], test results oldest->newest,
# days since last test
CONTROLS = [
    ('CTL-CRD-001', 'Credit bureau (I-Score) inquiry before every new loan and renewal',
     'System blocks disbursement until a bureau report under 30 days old is attached.', 'PREVENTIVE',
     'IT_DEPENDENT', 'ops', 'NMF-OPS', 'QUARTERLY', [('overindebt', 'PRIMARY'), ('par', 'SECONDARY')],
     ['EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE'], 25),
    ('CTL-CRD-002', 'Credit committee approval of loans above EGP 50,000',
     'Committee of branch manager, regional credit officer and Risk reviews the credit study.', 'PREVENTIVE',
     'MANUAL', 'ops', 'NMF-OPS', 'QUARTERLY', [('creditstudy', 'PRIMARY'), ('par', 'SECONDARY')],
     ['PARTIALLY_EFFECTIVE', 'INEFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE'], 40),
    ('CTL-CRD-003', 'Daily arrears report and collection escalation matrix',
     'Arrears by officer are reviewed daily; cases above 15 days escalate to the branch manager.', 'DETECTIVE',
     'IT_DEPENDENT', 'ops', 'NMF-OPS', 'MONTHLY', [('par', 'PRIMARY')],
     ['EFFECTIVE'] * 6 + ['PARTIALLY_EFFECTIVE'] * 3 + ['INEFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE'], 18),
    ('CTL-CRD-004', 'Sector concentration limits per branch', 'Monthly report against board-approved sector limits.',
     'DETECTIVE', 'MANUAL', 'risk', 'NMF-RISK', 'SEMI_ANNUAL', [('sector', 'PRIMARY')], ['EFFECTIVE', 'EFFECTIVE'], 60),
    ('CTL-OPR-001', 'Client acknowledgement of receipt of funds',
     'Client signs and is photographed at disbursement; random call-back by Customer Service.', 'PREVENTIVE',
     'MANUAL', 'ops', 'NMF-OPS', 'QUARTERLY', [('lofraud', 'PRIMARY'), ('mule', 'SECONDARY')],
     ['EFFECTIVE', 'EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE'], 35),
    ('CTL-OPR-002', 'Surprise client visits by branch managers', 'Five random client visits per officer per quarter.',
     'DETECTIVE', 'MANUAL', 'br1', 'NM-CAI-01', 'QUARTERLY', [('lofraud', 'PRIMARY')],
     ['EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE'], 120),
    ('CTL-OPR-003', 'Daily cash count under dual custody', 'Vault and teller cash counted by two staff and signed.',
     'DETECTIVE', 'MANUAL', 'br1', 'NM-CAI-01', 'MONTHLY', [('cash', 'PRIMARY')],
     ['EFFECTIVE'] * 10 + ['PARTIALLY_EFFECTIVE', 'EFFECTIVE'], 12),
    ('CTL-OPR-004', 'Second-person check of rescheduling and early-repayment calculations',
     'Finance reviews every rescheduling before it is posted.', 'PREVENTIVE', 'MANUAL', 'cfo', 'NMF-FIN',
     'QUARTERLY', [('resched', 'PRIMARY'), ('missell', 'SECONDARY')],
     ['PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE'], 30),
    ('CTL-OPR-005', 'Key-function succession plan and FRA notification checklist',
     'HR keeps successors for each key function; vacancies notified to the FRA within the legal period.',
     'CORRECTIVE', 'MANUAL', 'hr', 'NMF-HR', 'SEMI_ANNUAL', [('keypeople', 'PRIMARY')],
     ['PARTIALLY_EFFECTIVE', 'INEFFECTIVE'], 50),
    ('CTL-FCR-001', 'Mandatory KYC/KYB fields enforced in the core system',
     'Client cannot be activated without ID type, nationality, address, tax card and beneficial owners.',
     'PREVENTIVE', 'AUTOMATED', 'mlro', 'NMF-COMP', 'QUARTERLY', [('cdd', 'PRIMARY')],
     ['INEFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE'], 20),
    ('CTL-FCR-002', 'Risk-based KYC refresh and EDD for high-risk clients',
     'High-risk clients refreshed yearly with EDD sign-off by the MLRO.', 'PREVENTIVE', 'MANUAL', 'aml',
     'NMF-COMP', 'QUARTERLY', [('cdd', 'PRIMARY'), ('mule', 'SECONDARY')],
     ['PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'PARTIALLY_EFFECTIVE'], 45),
    ('CTL-FCR-003', 'Transaction monitoring of repayments and unusual-transactions register',
     'Rules on cash early settlement and third-party repayments feed the unusual-transactions register.',
     'DETECTIVE', 'IT_DEPENDENT', 'aml', 'NMF-COMP', 'QUARTERLY', [('str', 'PRIMARY'), ('mule', 'PRIMARY')],
     ['PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE'], 28),
    ('CTL-FCR-004', 'Automated sanctions screening with daily list updates',
     'Clients, guarantors and staff screened at onboarding and on every UN / local list update.', 'PREVENTIVE',
     'AUTOMATED', 'aml', 'NMF-COMP', 'QUARTERLY', [('sanctions', 'PRIMARY')], ['EFFECTIVE'] * 4, 15),
    ('CTL-FCR-005', 'MLRO direct reporting line to the Board Audit & Risk Committee',
     'MLRO presents quarterly to the committee; annual AML report approved by the board.', 'PREVENTIVE',
     'MANUAL', 'mlro', 'NMF-COMP', 'ANNUAL', [('amlgov', 'PRIMARY')], ['PARTIALLY_EFFECTIVE'], 150),
    ('CTL-TEC-001', 'Endpoint detection and response (EDR) on all endpoints',
     'Managed EDR with 24/7 alerting.', 'DETECTIVE', 'AUTOMATED', 'it', 'NMF-IT', 'QUARTERLY',
     [('ransom', 'PRIMARY')], ['EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE'], 22),
    ('CTL-TEC-002', 'Offline encrypted backups with monthly restore test',
     'Backups of every system copied offline and to the DR site; one restore test per month.', 'CORRECTIVE',
     'IT_DEPENDENT', 'itsup', 'NMF-IT', 'MONTHLY', [('ransom', 'PRIMARY'), ('drsite', 'PRIMARY')],
     ['INEFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE',
      'EFFECTIVE', 'EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE'], 75),
    ('CTL-TEC-003', 'Monthly patch cycle and annual penetration test',
     'Critical patches within 14 days; external penetration test every year.', 'PREVENTIVE', 'MANUAL', 'it',
     'NMF-IT', 'QUARTERLY', [('vulns', 'PRIMARY'), ('ransom', 'SECONDARY')],
     ['PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE', 'PARTIALLY_EFFECTIVE'], 33),
    ('CTL-TEC-004', 'Quarterly privileged access review',
     'Admin accounts recertified each quarter; shared accounts prohibited.', 'DETECTIVE', 'MANUAL', 'it', 'NMF-IT',
     'QUARTERLY', [('vulns', 'PRIMARY')], ['INEFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE'], 130),
    ('CTL-TEC-005', 'Annual disaster recovery test', 'Fail-over of core system and e-mail to the DR site.',
     'CORRECTIVE', 'MANUAL', 'it', 'NMF-IT', 'ANNUAL', [('drsite', 'PRIMARY'), ('lockin', 'SECONDARY')],
     ['PARTIALLY_EFFECTIVE'], 400),
    ('CTL-TEC-006', 'E-wallet receipts reconciliation and integration monitoring',
     'Daily matching of e-wallet and payment-network receipts to the core system.', 'DETECTIVE', 'AUTOMATED',
     'acc', 'NMF-FIN', 'MONTHLY', [('mobile', 'PRIMARY'), ('agents', 'PRIMARY')],
     ['EFFECTIVE'] * 7 + ['PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE'], 10),
    ('CTL-CON-001', 'Key facts statement and written early-repayment disclosure',
     'Client signs the cost disclosure before disbursement and before any early repayment.', 'PREVENTIVE',
     'MANUAL', 'cs', 'NMF-CS', 'QUARTERLY', [('missell', 'PRIMARY'), ('feecap', 'SECONDARY')],
     ['PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'PARTIALLY_EFFECTIVE'], 38),
    ('CTL-CON-002', 'Collections code of conduct and call recording',
     'All collection calls recorded; monthly sample listened to by Compliance.', 'DETECTIVE', 'MANUAL', 'co',
     'NMF-COMP', 'QUARTERLY', [('collect', 'PRIMARY'), ('media', 'SECONDARY')],
     ['EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE'], 42),
    ('CTL-CON-003', 'Complaints ageing report with escalation after 10 days',
     'Weekly ageing report to the Customer Service Manager and Compliance.', 'DETECTIVE', 'IT_DEPENDENT', 'cs',
     'NMF-CS', 'MONTHLY', [('complaints', 'PRIMARY'), ('media', 'SECONDARY')],
     ['PARTIALLY_EFFECTIVE'] * 3 + ['EFFECTIVE'] * 9, 16),
    ('CTL-CON-004', 'Fee table locked in the core system against the FRA cap',
     'Fees calculated by the system from the approved tiered table; overrides need CFO approval.', 'PREVENTIVE',
     'AUTOMATED', 'cfo', 'NMF-FIN', 'QUARTERLY', [('feecap', 'PRIMARY')],
     ['EFFECTIVE', 'EFFECTIVE', 'INEFFECTIVE', 'INEFFECTIVE'], 20),
    ('CTL-LIQ-001', 'Monthly lender covenant monitoring', 'Covenant ratios computed monthly and reported to the board.',
     'DETECTIVE', 'MANUAL', 'cfo', 'NMF-FIN', 'MONTHLY', [('funding', 'PRIMARY'), ('capital', 'SECONDARY')],
     ['EFFECTIVE'] * 8 + ['PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE'], 20),
    ('CTL-LIQ-002', '13-week cash-flow forecast and minimum cash buffer',
     'Treasury forecast reviewed weekly by the CFO.', 'PREVENTIVE', 'MANUAL', 'cfo', 'NMF-FIN', 'QUARTERLY',
     [('mismatch', 'PRIMARY'), ('funding', 'SECONDARY')], ['EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE'], 26),
    ('CTL-CMP-001', 'Regulatory calendar with four-eyes review of FRA returns',
     'Each return prepared by Compliance and reviewed by the CFO before submission.', 'PREVENTIVE', 'MANUAL',
     'co', 'NMF-COMP', 'QUARTERLY', [('regreport', 'PRIMARY'), ('esgdisc', 'SECONDARY')],
     ['EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE'], 24),
    ('CTL-CMP-002', 'Monthly capital adequacy and leverage monitoring',
     'Paid-up capital, equity and leverage compared with FRA minimums every month.', 'DETECTIVE', 'MANUAL', 'cfo',
     'NMF-FIN', 'MONTHLY', [('capital', 'PRIMARY')],
     ['EFFECTIVE'] * 9 + ['PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'PARTIALLY_EFFECTIVE'], 21),
    ('CTL-LEG-001', 'Pre-disbursement contract checklist', 'Branch operations check signatures and guarantor IDs.',
     'PREVENTIVE', 'MANUAL', 'dpo', 'NMF-LEG', 'QUARTERLY', [('contracts', 'PRIMARY')],
     ['PARTIALLY_EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE', 'EFFECTIVE'], 55),
    ('CTL-LEG-002', 'Data processing agreements and retention schedule',
     'Every vendor processing client data signs a DPA; records deleted per the retention schedule.', 'PREVENTIVE',
     'MANUAL', 'dpo', 'NMF-LEG', 'SEMI_ANNUAL', [('pdpl', 'PRIMARY'), ('agents', 'SECONDARY')],
     ['INEFFECTIVE', 'PARTIALLY_EFFECTIVE'], 95),
    ('CTL-ESG-001', 'Climate vulnerability flag and seasonal repayment schedules',
     'Agricultural loans tagged by climate exposure; repayment aligned with harvest.', 'PREVENTIVE', 'MANUAL',
     'risk', 'NMF-RISK', 'SEMI_ANNUAL', [('climate', 'PRIMARY')], ['PARTIALLY_EFFECTIVE', 'EFFECTIVE'], 70),
    ('CTL-ESG-002', 'ESG and carbon data collection with external verification',
     'Data owners per site submit quarterly; carbon report verified by an accredited verifier.', 'DETECTIVE',
     'MANUAL', 'risk', 'NMF-RISK', 'ANNUAL', [('esgdisc', 'PRIMARY')], ['EFFECTIVE'], 60),
]

# name, risk key, description, unit, frequency, target, warning, breach, direction, owner, 12 monthly values
KRIS = [
    ('PAR30 - company portfolio', 'par', 'Outstanding balance of loans more than 30 days past due / gross portfolio.',
     '%', 'MONTHLY', 3, 4, 5, 'UPPER', 'risk', [3.1, 3.3, 3.4, 3.9, 4.2, 4.6, 5.3, 5.9, 6.8, 7.6, 8.9, 9.8]),
    ('PAR30 - Cairo Downtown branch', 'par', 'PAR30 for the Cairo Downtown branch portfolio.', '%', 'MONTHLY',
     3, 5, 8, 'UPPER', 'br1', [4.0, 4.8, 6.1, 7.9, 9.5, 12.8, 15.2, 19.6, 24.1, 28.7, 33.0, 35.5]),
    ('Write-off ratio (annualised)', 'par', 'Loans written off in the month x 12 / average gross portfolio.', '%',
     'MONTHLY', 1, 1.5, 2, 'UPPER', 'cfo', [0.8, 0.9, 0.9, 1.0, 1.1, 1.0, 1.2, 1.3, 1.4, 1.6, 1.7, 1.9]),
    ('Clients with loans at 3 or more lenders', 'overindebt', 'Share of renewals where I-Score shows 3+ active lenders.',
     '%', 'MONTHLY', 8, 12, 15, 'UPPER', 'ops', [9, 10, 10, 11, 12, 13, 12, 12, 11, 11, 10, 10]),
    ('Loan officer annualised turnover', 'keypeople', 'Leavers in the last 12 months / average loan officer headcount.',
     '%', 'MONTHLY', 15, 20, 25, 'UPPER', 'hr', [18, 19, 21, 22, 24, 26, 27, 28, 28, 27, 26, 25]),
    ('KYC records with missing mandatory fields', 'cdd', 'Active clients missing at least one mandatory KYC/KYB field.',
     '%', 'MONTHLY', 1, 3, 5, 'UPPER', 'mlro', [11.2, 10.4, 9.8, 8.1, 7.2, 6.5, 5.6, 4.8, 4.1, 3.6, 3.2, 2.7]),
    ('Unusual transactions studied beyond SLA', 'str', 'Unusual transactions not studied within 10 working days.',
     'cases', 'MONTHLY', 0, 2, 5, 'UPPER', 'mlro', [7, 6, 6, 5, 4, 4, 3, 2, 2, 1, 1, 0]),
    ('Critical/high vulnerabilities open > 30 days', 'vulns', 'From the vulnerability scanner and penetration tests.',
     'count', 'MONTHLY', 0, 3, 6, 'UPPER', 'it', [2, 2, 3, 9, 13, 11, 8, 7, 6, 6, 5, 7]),
    ('Core system availability', 'mobile', 'Monthly availability of the core lending system in business hours.',
     '%', 'MONTHLY', 99.5, 99.0, 98.0, 'LOWER', 'it', [99.7, 99.6, 99.1, 99.8, 98.9, 99.7, 99.6, 97.4, 99.5, 99.8, 99.7, 99.6]),
    ('Complaints resolved beyond 15 days', 'complaints', 'Share of complaints closed after the 15-day target.',
     '%', 'MONTHLY', 2, 5, 10, 'UPPER', 'cs', [12, 11, 9, 8, 7, 6, 6, 4, 4, 3, 3, 2]),
    ('Collection-conduct complaints per 1,000 active clients', 'collect', 'Complaints about collection behaviour.',
     'per 1,000', 'MONTHLY', 0.5, 1.0, 2.0, 'UPPER', 'co', [0.4, 0.5, 0.6, 0.6, 0.9, 1.1, 1.4, 1.2, 1.0, 1.3, 1.6, 2.1]),
    ('Largest lender share of borrowings', 'funding', 'Largest single lender / total borrowings.', '%', 'MONTHLY',
     40, 45, 50, 'UPPER', 'cfo', [47, 47, 48, 49, 51, 52, 52, 50, 49, 48, 48, 46]),
    ('Cash buffer (days of planned disbursements)', 'mismatch', 'Cash and undrawn committed lines / average daily '
     'planned disbursements.', 'days', 'MONTHLY', 45, 30, 20, 'LOWER', 'cfo',
     [52, 48, 41, 35, 22, 18, 31, 38, 40, 36, 33, 29]),
    ('Paid-up capital vs FRA minimum', 'capital', 'Paid-up capital as a percentage of the licence minimum.', '%',
     'MONTHLY', 120, 105, 100, 'LOWER', 'cfo', [118, 117, 115, 114, 112, 110, 108, 106, 104, 101, 98, 97]),
    ('Loans with fees above the FRA cap', 'feecap', 'Loans disbursed in the month with administrative fees above '
     'the cap.', 'loans', 'MONTHLY', 0, 1, 5, 'UPPER', 'co', [0, 0, 0, 0, 1, 0, 2, 3, 6, 9, 8, 11]),
    ('Agricultural loans in climate-vulnerable districts', 'climate', 'Share of agricultural portfolio in districts '
     'rated high on the climate vulnerability index.', '%', 'MONTHLY', 25, 35, 45, 'UPPER', 'risk',
     [28, 28, 29, 30, 31, 31, 33, 35, 36, 37, 37, 38]),
]

# risk key, description, type, owner, created days ago, target (days from today), status, cost EGP
TREATMENTS = [
    ('par', 'Recovery plan for the Cairo Downtown branch: dedicated collections team, weekly review of the 50 '
     'largest arrears cases and suspension of new loans for officers with PAR30 above 15%.', 'MITIGATE', 'ops',
     120, -10, 'IN_PROGRESS', 350000),
    ('par', 'Increase ECL provision overlay for micro-trade clients and present impact to the board.', 'MITIGATE',
     'cfo', 95, -40, 'VERIFIED', None),
    ('par', 'Introduce behavioural early-warning score in the core system (missed instalment + bureau changes).',
     'MITIGATE', 'risk', 60, 75, 'APPROVED', 420000),
    ('overindebt', 'Make bureau inquiry mandatory for all renewals regardless of amount.', 'MITIGATE', 'ops', 300,
     -200, 'VERIFIED', 60000),
    ('overindebt', 'Cap total exposure at three lenders and train loan officers on over-indebtedness signs.',
     'MITIGATE', 'ops', 70, 40, 'IN_PROGRESS', 45000),
    ('creditstudy', 'Standard cash-flow template with system validation of income and expense ranges.', 'MITIGATE',
     'ops', 200, -60, 'COMPLETED', 120000),
    ('creditstudy', 'Retrain all loan officers on credit analysis and test them; quarterly file quality review.',
     'MITIGATE', 'hr', 180, -100, 'CLOSED', 80000),
    ('lofraud', 'Rotate loan officers between villages every 24 months.', 'MITIGATE', 'ops', 250, 30,
     'IN_PROGRESS', None),
    ('cash', 'Move 80% of collections to e-wallet and payment networks to reduce branch cash.', 'MITIGATE', 'ops',
     320, -90, 'VERIFIED', 150000),
    ('resched', 'Automate rescheduling and early-repayment calculations in the core system.', 'MITIGATE', 'it', 280,
     -45, 'COMPLETED', 200000),
    ('keypeople', 'Loan officer retention scheme (portfolio-quality bonus) and exit interviews.', 'MITIGATE', 'hr',
     210, 40, 'IN_PROGRESS', 900000),
    ('keypeople', 'Fill vacant key functions and notify the FRA; nominate deputies.', 'MITIGATE', 'hr', 90, -15,
     'IN_PROGRESS', None),
    ('cdd', 'KYC remediation project - complete missing KYB fields for 2,400 micro-enterprise clients.', 'MITIGATE',
     'mlro', 330, -150, 'VERIFIED', 250000),
    ('cdd', 'Block activation of clients without beneficial-owner declaration (system change).', 'MITIGATE', 'it',
     160, -70, 'CLOSED', 70000),
    ('cdd', 'Risk-based KYC refresh for high-risk clients overdue more than 90 days.', 'MITIGATE', 'aml', 60, 30,
     'IN_PROGRESS', None),
    ('str', 'Add repayment-pattern scenarios to transaction monitoring and tune thresholds.', 'MITIGATE', 'aml',
     300, -120, 'VERIFIED', 90000),
    ('amlgov', 'Board resolution confirming the MLRO reporting line and approval of the annual AML report.',
     'MITIGATE', 'mlro', 45, 20, 'APPROVED', None),
    ('ransom', 'Deploy immutable backups and MFA for all administrator accounts.', 'MITIGATE', 'it', 300, -140,
     'VERIFIED', 380000),
    ('vulns', 'Remediate critical and high findings from the 2026 penetration test and retest.', 'MITIGATE', 'it',
     150, -25, 'IN_PROGRESS', 160000),
    ('vulns', 'Implement a privileged access management (PAM) tool and remove shared admin accounts.', 'MITIGATE',
     'it', 100, 60, 'APPROVED', 650000),
    ('drsite', 'Upgrade DR site replication and repeat the full DR test.', 'MITIGATE', 'it', 330, 20,
     'IN_PROGRESS', 1100000),
    ('mobile', 'Second e-wallet integration provider for fail-over.', 'TRANSFER', 'it', 150, 50, 'PROPOSED', 240000),
    ('missell', 'Redesign the key facts statement and early-repayment disclosure; mystery-shopping in branches.',
     'MITIGATE', 'cs', 200, -50, 'COMPLETED', 40000),
    ('collect', 'Retrain collection staff on the code of conduct; ban visits after 8 pm.', 'MITIGATE', 'co', 80,
     15, 'IN_PROGRESS', 30000),
    ('complaints', 'Central complaints register for all branches with SMS acknowledgement to the client.',
     'MITIGATE', 'cs', 300, -160, 'VERIFIED', 55000),
    ('funding', 'Sign credit lines with two additional lenders to bring the largest lender below 40%.', 'MITIGATE',
     'cfo', 280, 45, 'IN_PROGRESS', None),
    ('mismatch', 'Seasonal funding plan for Ramadan and school season.', 'MITIGATE', 'cfo', 250, -170, 'CLOSED',
     None),
    ('capital', 'Complete the EGM-approved capital increase of EGP 25 million.', 'MITIGATE', 'cfo', 120, 30,
     'IN_PROGRESS', None),
    ('regreport', 'Automate extraction of the monthly FRA returns from the core system.', 'MITIGATE', 'co', 200, -80,
     'COMPLETED', 75000),
    ('feecap', 'Correct the fee table, refund over-charged clients and add a hard system block.', 'MITIGATE', 'cfo',
     40, -8, 'IN_PROGRESS', 180000),
    ('digital', 'Launch digital onboarding and instant renewals for repeat clients.', 'MITIGATE', 'ceo', 240, 120,
     'IN_PROGRESS', 2500000),
    ('digital', 'Partner with a BNPL provider for joint lending.', 'AVOID', 'ceo', 150, -60, 'REJECTED', None),
    ('climate', 'Pilot weather-index insurance for agricultural clients in Assiut.', 'TRANSFER', 'risk', 130, 90,
     'APPROVED', 300000),
    ('esgdisc', 'Appoint carbon and ESG data owners and engage an accredited verifier.', 'MITIGATE', 'risk', 260,
     -110, 'VERIFIED', 95000),
    ('contracts', 'Contract checklist in the core system - disbursement blocked until signed contract uploaded.',
     'MITIGATE', 'dpo', 230, -95, 'CLOSED', 50000),
    ('pdpl', 'Sign data processing agreements with collection agents and apply the retention schedule.',
     'MITIGATE', 'dpo', 140, 25, 'IN_PROGRESS', None),
    ('media', 'Social-media monitoring service and media response training for managers.', 'MITIGATE', 'ceo', 120,
     -30, 'COMPLETED', 60000),
    ('agents', 'Add settlement-delay penalties to payment network SLAs.', 'TRANSFER', 'cfo', 200, -75, 'CLOSED',
     None),
    ('paperfiles', 'Scan all active Giza loan files and move originals to an off-site archive.', 'MITIGATE', 'br1',
     340, -210, 'CLOSED', 85000),
    ('transform', 'Re-plan the core system upgrade with the vendor and add penalty clauses.', 'MITIGATE', 'it', 60,
     25, 'PROPOSED', None),
]

UP = ['{d}: residual likelihood raised - KRI moved into amber/red.', '{d}: deterioration observed, residual raised.',
      '{d}: control test found weaknesses, residual re-scored upwards.']
DOWN = ['{d}: residual reduced after action plan delivered.', '{d}: control effectiveness improved, residual lowered.',
        '{d}: KRI back within appetite, residual reduced.']
FLAT = ['{d}: no material change; controls operating as designed.', '{d}: residual confirmed, monitoring continues.']


def _month_ends(today, n):
    out = []
    for i in range(n, 0, -1):
        m = today.month - i + 1
        y = today.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        out.append(date(y, m, 1) - timedelta(days=1))
    return out


def seed(ctx):
    rnd = ctx.rnd
    today = ctx.today
    cats = {r['category_code']: r['id'] for r in ctx.q("SELECT id, category_code FROM risk_categories")}
    # test category left in the template by a smoke test - not part of a company taxonomy
    if 'CSRFTEST' in cats and not ctx.one("SELECT 1 FROM risks WHERE category_id = %s", (cats['CSRFTEST'],)):
        ctx.q("DELETE FROM risk_appetite_statements WHERE category_id = %s", (cats['CSRFTEST'],))
        ctx.q("DELETE FROM risk_categories WHERE id = %s", (cats.pop('CSRFTEST'),))
    for code, name, desc in NEW_CATEGORIES:
        if code not in cats:
            cats[code] = ctx.ins('risk_categories', category_code=code, category_name=name,
                                 category_description=desc, is_active=True, created_at=ctx.ago(380))

    # ---------------- appetite (board-approved Jan 2026; 2025 versions superseded)
    y = today.year
    for code, level, inh, res, text in APPETITE:
        ctx.ins('risk_appetite_statements', category_id=cats.get(code) if code else None, statement_text=text,
                appetite_level=level, max_acceptable_inherent_score=inh, max_acceptable_residual_score=res,
                effective_from=date(y, 1, 1), created_by=ctx.uid('risk'), created_at=ctx.ago((today - date(y - 1, 12, 20)).days, 11))
        if code in (None, 'CRD', 'TEC', 'CON'):
            ctx.ins('risk_appetite_statements', category_id=cats.get(code) if code else None,
                    statement_text=text + ' (2025 statement)', appetite_level='OPEN' if code == 'CRD' else level,
                    max_acceptable_inherent_score=inh, max_acceptable_residual_score=res + (3 if code == 'CRD' else 0),
                    effective_from=date(y - 1, 1, 1), effective_to=date(y - 1, 12, 31), created_by=ctx.uid('risk'),
                    created_at=ctx.ago((today - date(y - 2, 12, 18)).days, 10))
    appetite = {}
    for code, level, inh, res, text in APPETITE:
        appetite[code] = res

    # ---------------- risk register
    order = sorted(RISKS, key=lambda r: -r[14])
    seq_by_year = {}
    risk_ids = {}
    for (key, cat, dept, owner, title, desc, existing, L, I, r0, r1, eff, resp, freq, created, status,
         overdue) in order:
        created_at = ctx.ago(created, 10)
        fd = FREQ_DAYS[freq]
        res_l, res_i = (r1 or (None, None))
        res_score = res_l * res_i if r1 else None
        cat_id = cats[cat]
        res_max = appetite.get(cat, appetite[None])
        aligned = (res_score <= res_max) if res_score else None
        # review dates, newest first
        points = []
        if status != 'DRAFT':
            last = today - timedelta(days=(fd + rnd.randint(8, 30)) if overdue else rnd.randint(3, max(4, min(fd - 5, 60))))
            d = last
            while (d - created_at.date()).days > 20:
                points.append(d)
                d -= timedelta(days=fd)
            points.reverse()
            if not points:
                points = [created_at.date() + timedelta(days=14)]
        last_review = points[-1] if points else None
        next_review = (last_review + timedelta(days=fd)) if last_review else today + timedelta(days=30)
        if status == 'CLOSED':
            next_review = None
        vals = dict(category_id=cat_id, department_id=ctx.depts.get(dept), likelihood=L, impact=I,
                    inherent_risk_score=L * I, existing_controls=existing, control_effectiveness=eff,
                    residual_likelihood=res_l, residual_impact=res_i, residual_risk_score=res_score,
                    risk_response=resp, risk_owner_id=ctx.uid(owner), review_frequency=freq,
                    last_review_date=last_review, next_review_date=next_review, risk_appetite_aligned=aligned,
                    status=status, created_by=ctx.uid('risk'), created_at=created_at,
                    updated_at=datetime.combine(last_review, datetime.min.time()).replace(hour=14) if last_review else created_at)
        if key in EXISTING and ctx.one("SELECT id FROM risks WHERE risk_id = %s", (EXISTING[key],)):
            pk = ctx.one("SELECT id FROM risks WHERE risk_id = %s", (EXISTING[key],))['id']
            sets = ', '.join(f'{k} = %s' for k in vals)
            ctx.q(f"UPDATE risks SET {sets} WHERE id = %s", list(vals.values()) + [pk])
            if key == 'ransom':
                ctx.q("UPDATE risks SET risk_description = %s WHERE id = %s AND COALESCE(risk_description, '') = ''",
                      ('Encryption of the core lending system and file servers by ransomware would stop disbursements '
                       'and collections and could expose client data.', pk))
        else:
            if title is None:
                continue
            yr = created_at.year
            seq_by_year[yr] = seq_by_year.get(yr, 0) + 1
            pk = ctx.ins('risks', risk_id=f'RSK-{yr}-{seq_by_year[yr]:04d}', risk_title=title, risk_description=desc,
                         **vals)
        risk_ids[key] = pk

        # score history: registration, first residual assessment, then periodic reviews
        ctx.ins('risk_score_history', risk_id=pk, likelihood=L, impact=I, inherent_risk_score=L * I,
                changed_by=ctx.uid('risk'), change_reason='Initial risk registration', recorded_at=created_at)
        if status == 'DRAFT':
            continue
        n = len(points)
        drivers = ['Quarterly risk review' if freq == 'QUARTERLY' else 'Monthly risk review' if freq == 'MONTHLY'
                   else 'Periodic risk review'] * n
        for i, d in enumerate(points):
            frac = (i + 1) / n if n > 1 else 1.0
            if i == 0 and n > 1:
                frac = 0.0
            rl = round(r0[0] + (r1[0] - r0[0]) * frac)
            ri = round(r0[1] + (r1[1] - r0[1]) * frac)
            if i == 0:
                reason = 'Residual scoring after control effectiveness assessment'
                ceff = 'PARTIALLY_EFFECTIVE' if eff != 'NOT_ASSESSED' else 'NOT_ASSESSED'
            else:
                prev = (round(r0[0] + (r1[0] - r0[0]) * (i / n if n > 1 else 1)) *
                        round(r0[1] + (r1[1] - r0[1]) * (i / n if n > 1 else 1)))
                bucket = UP if rl * ri > prev else DOWN if rl * ri < prev else FLAT
                reason = rnd.choice(bucket).format(d=drivers[i])
                ceff = eff
            ctx.ins('risk_score_history', risk_id=pk, likelihood=L, impact=I, inherent_risk_score=L * I,
                    residual_likelihood=rl, residual_impact=ri, residual_risk_score=rl * ri,
                    control_effectiveness=ceff, changed_by=ctx.uid(owner if i else 'risk'), change_reason=reason,
                    recorded_at=datetime.combine(d, datetime.min.time()).replace(hour=rnd.randint(9, 16),
                                                                                 minute=rnd.randrange(60)))
        if status == 'CLOSED':
            ctx.ins('risk_score_history', risk_id=pk, likelihood=L, impact=I, inherent_risk_score=L * I,
                    residual_likelihood=1, residual_impact=2, residual_risk_score=2, control_effectiveness='EFFECTIVE',
                    changed_by=ctx.uid('risk'),
                    change_reason='Risk closed - all active files scanned and originals moved to off-site archive.',
                    recorded_at=ctx.ago(150, 12))
            ctx.q("UPDATE risks SET updated_at = %s, last_review_date = %s WHERE id = %s",
                  (ctx.ago(150, 12), ctx.dago(150), pk))
    ctx.data['risk_ids'] = risk_ids

    # ---------------- control library + tests
    ctl_ids = {}
    testers = ['risk', 'risk', 'co', 'risk']
    for (code, name, desc, ctype, nature, owner, dept, freq, links, results, since) in CONTROLS:
        fd = FREQ_DAYS.get(freq, 91)
        last = today - timedelta(days=since)
        test_dates = [last - timedelta(days=fd * (len(results) - 1 - i)) for i in range(len(results))]
        cid = ctx.ins('controls', control_code=code, control_name=name, control_description=desc,
                      control_type=ctype, control_nature=nature, control_owner_id=ctx.uid(owner),
                      department_id=ctx.depts.get(dept), testing_frequency=freq, last_tested_date=last,
                      last_test_result=results[-1], next_test_due_date=last + timedelta(days=fd), status='ACTIVE',
                      created_at=ctx.ago(min(370, (today - test_dates[0]).days + 20), 10))
        ctl_ids[code] = cid
        for rk, rel in links:
            if rk in risk_ids:
                ctx.ins('risk_controls', risk_id=risk_ids[rk], control_id=cid, reliance_level=rel,
                        created_at=ctx.ago(min(360, (today - test_dates[0]).days + 10), 11))
        for i, (d, res) in enumerate(zip(test_dates, results)):
            exc = None
            if res == 'PARTIALLY_EFFECTIVE':
                exc = rnd.choice(['Exceptions in 3 of 25 sampled items; evidence incomplete.',
                                  'Control performed late in 2 of 12 periods.',
                                  'Sign-off missing for a minority of the sample.'])
            elif res == 'INEFFECTIVE':
                exc = rnd.choice(['Control not performed for most of the period; sample failures above tolerance.',
                                  'Design gap: control does not cover the full population.'])
            ctx.ins('control_test_results', control_id=cid, tested_by=ctx.uid(testers[i % len(testers)]),
                    test_date=d, result=res, exceptions_noted=exc,
                    test_procedure=f'Second-line test of "{name}": walkthrough and sample of '
                                   f'{rnd.choice([10, 15, 20, 25])} items for the period.',
                    created_at=datetime.combine(d, datetime.min.time()).replace(hour=15))
    ctx.data['control_ids'] = ctl_ids
    # ERM controls behind some FRA compliance controls (regcontrols <-> RCM)
    for rc_code, erm in [('FRA-016', 'CTL-CRD-002'), ('FRA-015', 'CTL-CRD-002'), ('FRA-014', 'CTL-OPR-001'),
                         ('FRA-017', 'CTL-CON-004'), ('FRA-021', 'CTL-CON-001'), ('FRA-034', 'CTL-FCR-004'),
                         ('FRA-035', 'CTL-FCR-003'), ('FRA-050', 'CTL-FCR-002'), ('FRA-027', 'CTL-FCR-005'),
                         ('FRA-067', 'CTL-TEC-005'), ('FRA-069', 'CTL-TEC-003'), ('FRA-051', 'CTL-TEC-002'),
                         ('FRA-001', 'CTL-CMP-002'), ('FRA-009', 'CTL-LEG-001'), ('FRA-019', 'CTL-CMP-001')]:
        ctx.q("UPDATE rc_controls SET erm_control_id = %s WHERE control_code = %s AND erm_control_id IS NULL",
              (ctl_ids[erm], rc_code))

    # ---------------- KRIs + 12 monthly measurements
    months = _month_ends(today, 12)
    for (name, rk, desc, unit, freq, target, warn, breach, direction, owner, values) in KRIS:
        kid = ctx.ins('kris', risk_id=risk_ids.get(rk), kri_name=name, kri_description=desc, unit_of_measure=unit,
                      measurement_frequency=freq, target_value=target, warning_threshold=warn,
                      breach_threshold=breach, direction=direction, owner_id=ctx.uid(owner), is_active=True,
                      created_at=ctx.ago(375, 10))
        for d, v in zip(months, values):
            up = direction == 'UPPER'
            if (up and v >= breach) or (not up and v <= breach):
                st, note = 'RED', 'Breach - escalated to the Risk Committee.'
            elif (up and v >= warn) or (not up and v <= warn):
                st, note = 'AMBER', 'Above warning level - owner asked for an action plan.'
            else:
                st, note = 'GREEN', 'Within appetite.'
            ctx.ins('kri_measurements', kri_id=kid, measurement_date=d, actual_value=v, status=st, notes=note,
                    recorded_by=ctx.uid(owner),
                    created_at=datetime.combine(d + timedelta(days=rnd.randint(3, 9)), datetime.min.time()).replace(hour=11))

    # ---------------- treatments / action plans
    for (rk, desc, ttype, owner, created, target, status, cost) in TREATMENTS:
        if rk not in risk_ids:
            continue
        created_at = ctx.ago(created, 10)
        tdate = today + timedelta(days=target)
        comp = ver_by = ver_at = notes = None
        if status in ('COMPLETED', 'VERIFIED', 'CLOSED'):
            comp = min(today - timedelta(days=2), tdate - timedelta(days=rnd.randint(-6, 12)))
        if status in ('VERIFIED', 'CLOSED'):
            ver_by = ctx.uid('risk') if owner != 'risk' else ctx.uid('audit')
            ver_at = datetime.combine(min(today - timedelta(days=1), comp + timedelta(days=rnd.randint(5, 20))),
                                      datetime.min.time()).replace(hour=13)
            notes = rnd.choice(['Evidence reviewed; sample re-tested with no exceptions.',
                                'Verified by Risk Management - action implemented and operating.',
                                'Closure evidence on file; KRI back within appetite.'])
        if status == 'REJECTED':
            notes = 'Rejected by the Risk Committee - cost and dependency on a single partner outweigh the benefit.'
        upd = ver_at or (datetime.combine(comp, datetime.min.time()).replace(hour=12) if comp else
                         ctx.ago(max(1, created - rnd.randint(10, max(11, created - 1))), 12))
        ctx.ins('risk_treatments', risk_id=risk_ids[rk], treatment_description=desc, treatment_type=ttype,
                treatment_owner_id=ctx.uid(owner), estimated_cost=cost, budget_approved=bool(cost) and status != 'PROPOSED',
                target_date=tdate, completion_date=comp, status=status, verified_by=ver_by, verified_at=ver_at,
                verification_notes=notes, created_by=ctx.uid('risk'), created_at=created_at, updated_at=upd)

    # ---------------- links to source records in other modules
    links = [('par', '%PAR30 9.82%%', 'TRIGGER'), ('par', '%Portfolio at risk above threshold%', 'EVIDENCE'),
             ('capital', '%Paid-up capital below%', 'TRIGGER'), ('keypeople', '%Key functions vacant%', 'EVIDENCE'),
             ('feecap', '%Administrative fees above the cap%', 'TRIGGER'),
             ('missell', '%Early repayment followed%', 'EVIDENCE'), ('amlgov', '%MLRO independence%', 'TRIGGER'),
             ('amlgov', '%Annual AML report%', 'EVIDENCE'), ('drsite', '%DR test%', 'EVIDENCE'),
             ('vulns', '%Penetration test expired%', 'EVIDENCE'), ('esgdisc', '%Carbon activity data%', 'EVIDENCE')]
    for rk, pat, lt in links:
        f = ctx.one("SELECT id, created_at FROM rc_findings WHERE title ILIKE %s ORDER BY id LIMIT 1", (pat,))
        if f and rk in risk_ids:
            ctx.ins('risk_source_links', risk_id=risk_ids[rk], source_module='regcontrols', source_table='rc_findings',
                    source_record_id=f['id'], link_type=lt, linked_by=ctx.uid('risk'),
                    notes='Regulatory finding from the FRA inspection linked to this risk.')
    alert = ctx.one("SELECT id FROM tm_alerts WHERE UPPER(alert_severity) IN ('HIGH','CRITICAL') ORDER BY id LIMIT 1")
    if alert and 'str' in risk_ids:
        ctx.ins('risk_source_links', risk_id=risk_ids['str'], source_module='aml', source_table='tm_alerts',
                source_record_id=alert['id'], link_type='RELATED', linked_by=ctx.uid('mlro'),
                notes='Example of a repayment-pattern alert studied late.')

    # whole-minute timestamps, like records typed in by people
    for table, cols in [('risks', ['created_at', 'updated_at']), ('risk_score_history', ['recorded_at']),
                        ('risk_treatments', ['created_at', 'updated_at']), ('controls', ['created_at']),
                        ('risk_controls', ['created_at']), ('kris', ['created_at']),
                        ('risk_appetite_statements', ['created_at']), ('risk_categories', ['created_at'])]:
        for c in cols:
            ctx.q(f"UPDATE {table} SET {c} = date_trunc('minute', {c})")
