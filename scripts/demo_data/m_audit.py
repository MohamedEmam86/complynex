"""Internal audit (universe, plans, engagements, programs, team, working papers, findings, committee narrative),
regulatory report submissions for the FRA / EMLCU returns and evidence items for FRA compliance controls."""
import os
import tempfile
from datetime import date, datetime, timedelta

from common import DOMAIN

AUDITORS = [  # key, first, last, title
    ('ia1', 'Mona', 'Ashraf', 'Senior Internal Auditor'),
    ('ia2', 'Islam', 'Farouk', 'IT Auditor'),
]

# name, description, risk level, unit, frequency, risk keys, FRA control codes
UNIVERSE = [
    ('AML/CFT programme & customer due diligence', 'KYC/KYB, EDD, screening, unusual-transactions register, '
     'MLRO governance and EMLCU reporting.', 'CRITICAL', 'NMF-COMP', 'ANNUAL',
     ['cdd', 'str', 'sanctions', 'amlgov', 'mule'],
     ['FRA-027', 'FRA-030', 'FRA-032', 'FRA-034', 'FRA-035', 'FRA-036', 'FRA-037', 'FRA-045', 'FRA-047', 'FRA-050',
      'FRA-053', 'FRA-054', 'OBS-01']),
    ('Loan origination & credit assessment', 'Client selection, credit study, bureau checks, credit committee, '
     'contract signature and disbursement.', 'CRITICAL', 'NMF-OPS', 'ANNUAL', ['creditstudy', 'overindebt', 'par'],
     ['FRA-009', 'FRA-013', 'FRA-014', 'FRA-015', 'FRA-016']),
    ('Collections, arrears & rescheduling', 'Arrears follow-up, collection conduct, rescheduling and write-offs.',
     'HIGH', 'NMF-OPS', 'ANNUAL', ['par', 'collect', 'resched'],
     ['FRA-010', 'FRA-011', 'FRA-012', 'FRA-025', 'FRA-026']),
    ('Pricing, fees & consumer protection', 'Fee caps, cost disclosure, early repayment and complaints handling.',
     'HIGH', 'NMF-CS', 'ANNUAL', ['feecap', 'missell', 'complaints'],
     ['FRA-017', 'FRA-018', 'FRA-019', 'FRA-020', 'FRA-021', 'FRA-022', 'FRA-023', 'FRA-024']),
    ('IT general controls & cybersecurity', 'Access management, patching, change management, EDR, WAF and '
     'security governance.', 'HIGH', 'NMF-IT', 'ANNUAL', ['vulns', 'ransom', 'mobile'],
     ['FRA-069', 'FRA-070', 'FRA-071', 'FRA-072', 'FRA-073', 'FRA-074', 'FRA-075', 'FRA-076', 'FRA-077',
      'FRA-078']),
    ('Business continuity & disaster recovery', 'BCP, DR site, backups and restore testing.', 'HIGH', 'NMF-IT',
     'ANNUAL', ['drsite', 'lockin'], ['FRA-067', 'FRA-051', 'FRA-068']),
    ('Financial reporting & ECL provisioning', 'Accounting system, accruals, ECL model, related parties and '
     'deferred tax.', 'HIGH', 'NMF-FIN', 'ANNUAL', ['capital', 'par'],
     ['FRA-055', 'FRA-057', 'FRA-058', 'FRA-063', 'FRA-064', 'FRA-065', 'FRA-066']),
    ('Treasury, funding & liquidity', 'Borrowings, covenants, cash forecasting and bank reconciliations.',
     'MEDIUM', 'NMF-FIN', 'ANNUAL', ['funding', 'mismatch'], ['FRA-056', 'FRA-059', 'FRA-060']),
    ('Branch operations - Cairo Downtown', 'Cash, loan files, client visits and branch compliance.', 'HIGH',
     'NM-CAI-01', 'ANNUAL', ['lofraud', 'cash', 'par'], ['FRA-008', 'FRA-012']),
    ('Branch operations - Giza', 'Cash, loan files, client visits and branch compliance.', 'MEDIUM', 'NM-GIZ-02',
     'ANNUAL', ['lofraud', 'cash', 'contracts'], ['FRA-008']),
    ('Branch operations - Assiut', 'Cash, loan files, client visits and branch compliance.', 'MEDIUM', 'NM-ASY-03',
     'ANNUAL', ['lofraud', 'cash', 'climate'], ['FRA-008', 'FRA-013']),
    ('Regulatory reporting & licensing compliance', 'FRA returns, capital and solvency, key functions and '
     'licence conditions.', 'HIGH', 'NMF-COMP', 'ANNUAL', ['regreport', 'capital', 'keypeople'],
     ['FRA-001', 'FRA-002', 'FRA-003', 'FRA-004', 'FRA-005', 'FRA-006', 'FRA-007', 'FRA-079']),
    ('Human resources, payroll & key functions', 'Hiring, payroll, leavers and succession.', 'MEDIUM', 'NMF-HR',
     'BIENNIAL', ['keypeople'], ['FRA-052']),
    ('Data protection & information governance', 'Personal data processing, consent, retention and DPAs.',
     'MEDIUM', 'NMF-LEG', 'BIENNIAL', ['pdpl'], []),
    ('Outsourcing & third-party payment networks', 'Vendor selection, SLAs and settlement of collections.',
     'MEDIUM', 'NMF-OPS', 'BIENNIAL', ['agents', 'mobile'], []),
    ('ESG, climate risk & carbon reporting', 'Climate risk in the portfolio, FRA ESG/TCFD disclosures and the '
     'verified carbon-footprint report.', 'MEDIUM', 'NMF-RISK', 'BIENNIAL', ['climate', 'esgdisc'],
     ['FRA-CF-01', 'FRA-CF-02', 'FRA-CF-03', 'FRA-CF-04', 'FRA-CF-05']),
]

# key, plan year offset (0 = this year), name, area index, type, scope, start (days from today), end, status, lead,
# team [(user, role, hours)], program [(procedure, control code, result)]
PROJECTS = [
    ('asy25', -1, 'Assiut Branch Operations Audit', 10, 'INTERNAL',
     'Cash management, loan file completeness, client visits and branch compliance with head-office procedures '
     '(January-September 2025).', -335, -310, 'CLOSED', 'ia1',
     [('ia1', 'LEAD', 120), ('ia2', 'AUDITOR', 40), ('audit', 'REVIEWER', 16)],
     [('Surprise cash count of vault and tellers; compare with vault limits.', 'CTL-OPR-003', 'PARTIALLY_EFFECTIVE'),
      ('Sample 30 loan files for completeness (contract, ID, GPS location, receipt of funds).', 'CTL-OPR-001',
       'PARTIALLY_EFFECTIVE'),
      ('Visit 10 clients selected at random to confirm the business exists and the loan was received.',
       'CTL-OPR-002', 'EFFECTIVE'),
      ('Review arrears follow-up for loans over 30 days past due.', 'CTL-CRD-003', 'EFFECTIVE')]),
    ('tre25', -1, 'Treasury & Funding Review', 7, 'INTERNAL',
     'Borrowings register, covenant calculations, bank reconciliations and cash forecasting.', -315, -290,
     'CLOSED', 'audit', [('audit', 'LEAD', 60), ('ia1', 'AUDITOR', 50)],
     [('Reconcile the borrowings register to bank confirmations.', None, 'EFFECTIVE'),
      ('Re-perform the covenant calculations for June and September 2025.', 'CTL-LIQ-001', 'PARTIALLY_EFFECTIVE'),
      ('Review the 13-week cash-flow forecast against actuals.', 'CTL-LIQ-002', 'EFFECTIVE')]),
    ('aml26', 0, 'AML/CFT Programme & Customer Due Diligence Audit', 0, 'INTERNAL',
     'KYC/KYB completeness, EDD for high-risk clients, sanctions screening, unusual-transactions register and '
     'MLRO governance, 2025 activity.', -262, -205, 'CLOSED', 'audit',
     [('audit', 'LEAD', 90), ('ia1', 'AUDITOR', 160), ('ia2', 'AUDITOR', 40)],
     [('Sample 60 micro-enterprise clients and test mandatory KYC/KYB fields.', 'CTL-FCR-001', 'INEFFECTIVE'),
      ('Test EDD documentation for 20 high-risk clients.', 'CTL-FCR-002', 'PARTIALLY_EFFECTIVE'),
      ('Re-perform screening of 200 clients and all staff against the UN and local lists.', 'CTL-FCR-004',
       'EFFECTIVE'),
      ('Trace 25 TM alerts to the unusual-transactions register and check study within SLA.', 'CTL-FCR-003',
       'PARTIALLY_EFFECTIVE'),
      ('Review MLRO reporting line and board approval of the annual AML report.', 'CTL-FCR-005',
       'PARTIALLY_EFFECTIVE'),
      ('Review third-party repayments above EGP 20,000.', None, 'PARTIALLY_EFFECTIVE')]),
    ('ext26', 0, 'External Auditor Management Letter FY2025 - Follow-up', 6, 'EXTERNAL',
     'Tracking of the points raised by the external auditor in the FY2025 management letter.', -230, -215,
     'CLOSED', 'audit', [('audit', 'LEAD', 24), ('ia1', 'AUDITOR', 16)],
     [('Obtain management letter and agree action owners.', None, 'N/A'),
      ('Review ECL model governance and board approval.', None, 'INEFFECTIVE'),
      ('Review deferred tax asset recoverability support.', None, 'PARTIALLY_EFFECTIVE')]),
    ('loan26', 0, 'Loan Origination & Credit Assessment Audit', 1, 'INTERNAL',
     'Credit studies, bureau checks, credit committee approvals and contract signature in the three branches, '
     'loans disbursed October 2025 - March 2026.', -200, -150, 'FOLLOW_UP', 'audit',
     [('audit', 'LEAD', 80), ('ia1', 'AUDITOR', 180), ('risk', 'OBSERVER', 8)],
     [('Sample 40 loan files and test the credit study for templated figures.', 'CTL-CRD-002', 'INEFFECTIVE'),
      ('Check that a bureau report under 30 days old is attached before disbursement.', 'CTL-CRD-001',
       'PARTIALLY_EFFECTIVE'),
      ('Check credit committee minutes and signatures for loans above EGP 50,000.', 'CTL-CRD-002',
       'PARTIALLY_EFFECTIVE'),
      ('Verify contracts are signed by the client, guarantor and company.', 'CTL-LEG-001', 'PARTIALLY_EFFECTIVE'),
      ('Confirm client acknowledgement of receipt of funds.', 'CTL-OPR-001', 'EFFECTIVE')]),
    ('fra26', 0, 'Follow-up Review of FRA Inspection Findings', 11, 'REGULATORY',
     'Status of the corrective actions for the findings of the FRA inspection; repeated findings.', -140, -120,
     'CLOSED', 'audit', [('audit', 'LEAD', 40), ('ia1', 'AUDITOR', 60)],
     [('Obtain the FRA inspection letter and the corrective action plan.', None, 'N/A'),
      ('Test closure evidence for each finding marked as closed.', 'CTL-CMP-001', 'PARTIALLY_EFFECTIVE'),
      ('Re-test the administrative fee cap on a sample of 30 loans.', 'CTL-CON-004', 'INEFFECTIVE')]),
    ('itgc26', 0, 'IT General Controls & Cybersecurity Audit', 4, 'INTERNAL',
     'Access management, privileged accounts, patching, backups and security governance (co-sourced penetration '
     'test results).', -110, -62, 'MANAGEMENT_RESPONSE', 'ia2',
     [('ia2', 'LEAD', 200), ('audit', 'REVIEWER', 30), ('ia1', 'AUDITOR', 40)],
     [('Review vulnerability scan and penetration test results; age of open critical/high items.', 'CTL-TEC-003',
       'INEFFECTIVE'),
      ('Test quarterly privileged access reviews and shared accounts.', 'CTL-TEC-004', 'INEFFECTIVE'),
      ('Test leavers: account disablement within 1 day for 25 leavers.', None, 'PARTIALLY_EFFECTIVE'),
      ('Inspect backup logs and restore test evidence.', 'CTL-TEC-002', 'PARTIALLY_EFFECTIVE'),
      ('Confirm EDR coverage against the asset inventory.', 'CTL-TEC-001', 'EFFECTIVE'),
      ('Review information-security policies and board approval.', None, 'EFFECTIVE')]),
    ('coll26', 0, 'Collections, Arrears & Rescheduling Audit', 2, 'INTERNAL',
     'Arrears follow-up, collection conduct, rescheduling approvals and fees, PAR reporting.', -75, -30,
     'REPORTING', 'ia1', [('ia1', 'LEAD', 160), ('audit', 'REVIEWER', 24)],
     [('Re-perform the PAR30 calculation for September including rescheduled loans.', 'CTL-CRD-003',
       'INEFFECTIVE'),
      ('Listen to 40 recorded collection calls and review visit logs.', 'CTL-CON-002', 'PARTIALLY_EFFECTIVE'),
      ('Test rescheduling approvals and fees on 30 rescheduled loans.', 'CTL-OPR-004', 'PARTIALLY_EFFECTIVE'),
      ('Review write-off approvals against the delegation of authority.', None, 'EFFECTIVE')]),
    ('price26', 0, 'Pricing, Fees & Consumer Protection Audit', 3, 'INTERNAL',
     'Fee caps and tiered fees, cost disclosure, early repayment and complaints handling.', -24, 16,
     'FIELDWORK', 'ia1', [('ia1', 'LEAD', 140), ('audit', 'REVIEWER', 16)],
     [('Recalculate administrative fees on 50 loans against the FRA cap and tiers.', 'CTL-CON-004', 'INEFFECTIVE'),
      ('Test key facts statements and early-repayment disclosures.', 'CTL-CON-001', None),
      ('Trace 30 complaints from receipt to resolution.', 'CTL-CON-003', None),
      ('Test responsible-pricing disclosure submissions to the FRA.', 'CTL-CMP-001', None)]),
    ('cai26', 0, 'Cairo Downtown Branch Operations Audit', 8, 'INTERNAL',
     'Branch with the highest PAR30: loan files, client visits, cash and arrears follow-up.', -9, 26, 'FIELDWORK',
     'ia1', [('ia1', 'LEAD', 150), ('ia2', 'AUDITOR', 30), ('audit', 'REVIEWER', 16)],
     [('Surprise cash count and vault limit review.', 'CTL-OPR-003', 'EFFECTIVE'),
      ('Visit 15 clients in arrears to confirm business and loan use.', 'CTL-OPR-002', None),
      ('Review portfolio by loan officer and PAR30 drivers.', 'CTL-CRD-003', None),
      ('Test loan files disbursed since April 2026.', 'CTL-OPR-001', None)]),
    ('fin26', 0, 'Financial Reporting & ECL Provisioning Review', 6, 'INTERNAL',
     'ECL model, provisioning overlays, accruals and capital adequacy reporting for the FY2026 close.', 12, 45,
     'PLANNED', 'audit', [('audit', 'LEAD', 80), ('ia1', 'AUDITOR', 80)],
     [('Review ECL model methodology and board approval.', None, None),
      ('Re-perform staging and provision for a sample of loans.', None, None),
      ('Review monthly capital adequacy reporting.', 'CTL-CMP-002', None)]),
    ('bcp26', 0, 'Business Continuity & Disaster Recovery Review', 5, 'INTERNAL',
     'BCP, DR site readiness and the repeated DR test.', 38, 70, 'PLANNED', 'ia2',
     [('ia2', 'LEAD', 100), ('audit', 'REVIEWER', 12)],
     [('Observe the DR fail-over test.', 'CTL-TEC-005', None),
      ('Review BCP and call tree for the three branches.', None, None)]),
]

# project, title, severity, description, root cause, recommendation, responsible, target (days), status,
# risk key, control code, created (days ago), management response
FINDINGS = [
    ('asy25', 'Vault cash above the insured limit', 'MEDIUM',
     'Vault cash exceeded the insured limit on 9 days in September 2025.', 'Late transfer of collections to the bank.',
     'Daily transfer of excess cash; alert when the vault limit is reached.', 'ops', -250, 'VERIFIED_CLOSED', 'cash',
     'CTL-OPR-003', 305, 'Agreed. Daily cash transfer introduced from November 2025.'),
    ('asy25', 'Project location (GPS) missing in client files', 'LOW',
     '7 of 30 sampled files had no GPS location of the project.', 'Field not mandatory in the mobile app.',
     'Make the GPS location mandatory before submission of the application.', 'ops', -230, 'VERIFIED_CLOSED',
     'lofraud', None, 305, 'Agreed. App release with mandatory GPS planned for January.'),
    ('tre25', 'Covenant certificate sent to lender without CFO review', 'MEDIUM',
     'The September 2025 covenant certificate was prepared and sent by Treasury without documented CFO review.',
     'No review step in the procedure.', 'Add CFO sign-off before any covenant certificate is sent.', 'cfo', -240,
     'VERIFIED_CLOSED', 'funding', 'CTL-LIQ-001', 288, 'Agreed and implemented immediately.'),
    ('aml26', 'KYB fields missing for micro-enterprise clients', 'HIGH',
     '11 of 60 sampled clients (18%) had no tax card number, senior management or beneficial-owner data.',
     'Fields were optional in the core system until 2025.', 'Complete the missing data and make the fields mandatory.',
     'mlro', -120, 'VERIFIED_CLOSED', 'cdd', 'CTL-FCR-001', 200,
     'Agreed. KYC remediation project launched; system change requested.'),
    ('aml26', 'Unusual transactions studied after the internal SLA', 'HIGH',
     '9 of 25 alerts were studied 12-35 days after detection against a 10-day SLA.', 'One AML analyst for all alerts.',
     'Prioritise alerts by risk and track SLA in the register.', 'mlro', -100, 'VERIFIED_CLOSED', 'str',
     'CTL-FCR-003', 200, 'Agreed. SLA tracking added; second analyst trained.'),
    ('aml26', 'EDD not documented for high-risk clients', 'MEDIUM',
     '6 of 20 high-risk clients had no documented source-of-funds review or MLRO sign-off.',
     'EDD checklist not embedded in the onboarding workflow.', 'Embed the EDD checklist and complete the 6 files.',
     'aml', -40, 'REMEDIATION_IN_PROGRESS', 'cdd', 'CTL-FCR-002', 200,
     'Agreed. Checklist will be added to the workflow; files to be completed.'),
    ('aml26', 'Third-party repayments not reviewed', 'HIGH',
     'Two loans were repaid early in full by unrelated third parties without review (possible money-mule '
     'pattern). Referred to the MLRO as an AML red flag.', 'No rule on third-party repayments.',
     'Study both cases, register them as unusual transactions and add a monitoring rule.', 'aml', -20,
     'REMEDIATED_PENDING_VERIFICATION', 'mule', 'CTL-FCR-003', 200,
     'Agreed. Cases registered and studied; rule deployed in September.'),
    ('ext26', 'ECL model assumptions not approved by the board', 'HIGH',
     'The external auditor noted that the forward-looking overlays of the ECL model were not board-approved.',
     'Model governance policy not in place.', 'Approve an ECL model governance policy and the current overlays.',
     'cfo', 40, 'REMEDIATION_IN_PROGRESS', 'par', None, 215,
     'Agreed. Policy drafted, to be presented to the Board Audit & Risk Committee.'),
    ('ext26', 'Deferred tax asset recoverability not supported', 'MEDIUM',
     'No profit forecast supported the recognition of the deferred tax asset.', 'Forecast not updated after losses.',
     'Prepare a tax-profit forecast and obtain the auditor certificate.', 'cfo', -90, 'VERIFIED_CLOSED', 'capital',
     None, 215, 'Agreed. Forecast prepared with the business plan.'),
    ('loan26', 'Templated cash-flow figures in credit studies', 'CRITICAL',
     '14 of 40 files used identical income and expense figures unrelated to the client business. The same issue '
     'was raised by the FRA.', 'Loan officers reuse a spreadsheet; no validation of figures.',
     'Use a system cash-flow template with range checks; retrain officers; review all files of the officers '
     'concerned.', 'ops', -15, 'REMEDIATION_IN_PROGRESS', 'creditstudy', 'CTL-CRD-002', 148,
     'Agreed. System template delivered; retraining 70% complete.'),
    ('loan26', 'Bureau report older than 30 days at disbursement', 'HIGH',
     '8 of 40 renewals were disbursed with a bureau report older than 30 days.', 'Manual check only.',
     'Block disbursement without a current bureau report.', 'ops', -60, 'VERIFIED_CLOSED', 'overindebt',
     'CTL-CRD-001', 148, 'Agreed. System block implemented in June.'),
    ('loan26', 'Contracts without guarantor signature', 'MEDIUM',
     '4 of 40 contracts were not signed by the guarantor.', 'No pre-disbursement contract checklist.',
     'Introduce a checklist and obtain the missing signatures.', 'dpo', -5, 'REMEDIATED_PENDING_VERIFICATION',
     'contracts', 'CTL-LEG-001', 148, 'Agreed. Missing signatures obtained; checklist in the system.'),
    ('loan26', 'Credit committee minutes not signed', 'LOW',
     'Minutes of 3 credit committee meetings were not signed by all members.', 'Minutes circulated by e-mail.',
     'Sign minutes at the end of each meeting.', 'ops', -90, 'VERIFIED_CLOSED', 'creditstudy', 'CTL-CRD-002', 148,
     'Agreed.'),
    ('fra26', 'FRA findings repeated after closure', 'HIGH',
     'Two findings reported as closed to the FRA (administrative fee cap and MLRO reporting line) were found '
     'again in testing.', 'Closure accepted without re-testing.',
     'Re-test every corrective action before reporting closure to the FRA.', 'mlro', 20,
     'MANAGEMENT_RESPONSE_RECEIVED', 'feecap', 'CTL-CMP-001', 118,
     'Agreed. Compliance will re-test before closure; independent verification by Internal Audit.'),
    ('itgc26', 'Critical vulnerabilities open beyond 30 days', 'CRITICAL',
     '4 critical and 9 high vulnerabilities from the penetration test were open for more than 30 days.',
     'Patching depends on vendor releases and change windows.', 'Emergency patch process and compensating '
     'controls (WAF rules) until patched.', 'it', -10, 'MANAGEMENT_RESPONSE_RECEIVED', 'vulns', 'CTL-TEC-003',
     58, 'Agreed. 2 critical items fixed; vendor patch for the others expected in November.'),
    ('itgc26', 'Shared administrator accounts on core servers', 'HIGH',
     'Two servers of the core system are administered with a shared account.', 'No PAM tool.',
     'Remove shared accounts and implement privileged access management.', 'it', 30, 'REMEDIATION_IN_PROGRESS',
     'vulns', 'CTL-TEC-004', 58, 'Agreed. PAM tool approved in the budget.'),
    ('itgc26', 'Privileged access review not evidenced', 'MEDIUM',
     'No evidence of the quarterly privileged access review for Q1 and Q2 2026.', 'Review done by e-mail only.',
     'Run the review in a tracked workflow and keep evidence.', 'it', 45, 'MANAGEMENT_RESPONSE_RECEIVED', 'vulns',
     'CTL-TEC-004', 58, 'Agreed. Q3 review performed in the workflow.'),
    ('itgc26', 'Leavers accounts disabled late', 'MEDIUM',
     'Accounts of 25 leavers were disabled on average 9 days after the last working day.',
     'HR notifies IT at month end.', 'HR to notify IT on the last working day; daily reconciliation.', 'hr', 30,
     'OPEN', 'keypeople', None, 58, None),
    ('itgc26', 'Backup restore tests not documented', 'LOW',
     'Monthly restore tests were performed but not documented for 4 months.', 'No template.',
     'Document restore tests with a standard template.', 'itsup', 20, 'REMEDIATION_IN_PROGRESS', 'drsite',
     'CTL-TEC-002', 58, 'Agreed.'),
    ('coll26', 'Collection visits after 8 pm and pressure on guarantors', 'HIGH',
     'Visit logs and 6 recorded calls show visits after 8 pm and repeated calls to guarantors.',
     'Collection targets per officer without conduct KPIs.', 'Enforce visiting hours and add conduct KPIs.', 'ops',
     45, 'OPEN', 'collect', 'CTL-CON-002', 12, None),
    ('coll26', 'Rescheduled loans not flagged in PAR reporting', 'HIGH',
     'Rescheduled loans are reset to current status, so PAR30 is understated by about 1.4 points.',
     'System resets arrears days on rescheduling.', 'Flag rescheduled loans and report PAR including them.', 'cfo',
     30, 'OPEN', 'par', 'CTL-CRD-003', 12, None),
    ('coll26', 'Rescheduling fees above the rules', 'MEDIUM', '7 of 30 rescheduled loans were charged fees above '
     'the rules.', 'Manual fee calculation.', 'Refund clients and automate the fee.', 'ops', 60, 'OPEN', 'resched',
     'CTL-OPR-004', 12, None),
    ('price26', 'Administrative fees above the FRA cap on small loans', 'HIGH',
     '11 of 50 loans below EGP 10,000 disbursed in September were charged fees above the cap.',
     'Fee table changed in August without Compliance review.', 'Correct the fee table, refund clients and '
     'require Compliance approval for fee changes.', 'cfo', 30, 'OPEN', 'feecap', 'CTL-CON-004', 6, None),
]

CAE_NARRATIVE = {
    'ia_committee_report_scope': (
        'This report covers the internal audit activity of Nile Microfinance S.A.E. for the 2026 audit plan up to '
        'the date of the report: completed engagements, the status of findings and management actions, and the '
        'top residual risks from the enterprise risk register. Figures are generated from the audit management '
        'system on the date shown.\n\n'
        'يغطي هذا التقرير نشاط المراجعة الداخلية لخطة 2026 حتى تاريخه: المهام المنتهية وحالة الملاحظات وخطط '
        'الإدارة وأعلى المخاطر المتبقية.'),
    'ia_committee_report_opinion': (
        'Based on the work performed, the control environment is "needs improvement". Controls over AML/CFT and '
        'sanctions screening have improved since the start of the year, but credit assessment, IT security '
        '(patching and privileged access) and fee compliance remain weak, and PAR30 is well above the FRA '
        'threshold. Five findings are past their agreed date.\n\n'
        'رأي رئيس المراجعة الداخلية: بيئة الرقابة "تحتاج إلى تحسين"، مع وجود ملاحظات متأخرة في دراسات الائتمان '
        'وأمن المعلومات والرسوم الإدارية.'),
    'ia_committee_report_actions': (
        '1. Require management to present a dated plan for the overdue critical finding on credit studies.\n'
        '2. Approve the ECL model governance policy at the next meeting.\n'
        '3. Monitor the capital increase and the PAR30 recovery plan monthly.\n'
        '4. Approve the draft 2027 risk-based audit plan in December.'),
    'ia_findings_report_scope': (
        'All findings raised by Internal Audit, the external auditor follow-up and the FRA follow-up review, with '
        'their status at the report date.'),
    'ia_findings_report_commentary': (
        'Most high findings from the AML/CFT audit are closed and verified. Open critical findings relate to credit '
        'studies and unpatched vulnerabilities. Draft findings from the collections audit are awaiting management '
        'responses.'),
    'ia_findings_report_actions': (
        'Owners of overdue findings to provide revised dates with interim controls by the end of the month; '
        'Internal Audit will verify closure evidence before any finding is reported closed to the FRA.'),
}

SEED_RPD = False


def _month_start(d, k):
    m = d.month + k
    y = d.year + (m - 1) // 12
    return date(y, (m - 1) % 12 + 1, 1)


def _pdf(path, title, lines):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('helvetica', 'B', 14)
    pdf.multi_cell(0, 8, 'Nile Microfinance S.A.E. (demo company)', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('helvetica', 'B', 12)
    pdf.multi_cell(0, 8, title, new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)
    pdf.set_font('helvetica', size=10)
    for ln in lines:
        pdf.multi_cell(0, 6, ln, new_x='LMARGIN', new_y='NEXT')
    pdf.ln(6)
    pdf.set_font('helvetica', 'I', 8)
    pdf.multi_cell(0, 5, 'Fictional demo document - all names and figures are invented.', new_x='LMARGIN', new_y='NEXT')
    pdf.output(path)


def _xlsx(path, title, header, rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Testing'
    ws.append([title])
    ws.append(['Nile Microfinance S.A.E. - fictional demo data'])
    ws.append([])
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)


def _auditors(ctx):
    admin = ctx.one("SELECT * FROM users WHERE id = %s", (ctx.uid('admin'),))
    perms = [c for c in ctx.cols('users') if c.startswith('perm_')]
    for i, (key, first, last, title) in enumerate(AUDITORS):
        vals = {p: 'none' for p in perms}
        for m, lvl in [('internal_audit', 'edit'), ('risk_management', 'view'), ('regcontrols', 'view'),
                       ('policies', 'view'), ('training', 'view'), ('governance', 'view'), ('aml', 'view'),
                       ('cyber', 'view'), ('pdpl', 'view'), ('consumer_protection', 'view')]:
            if f'perm_{m}' in vals:
                vals[f'perm_{m}'] = lvl
        ctx.users[key] = ctx.ins(
            'users', email=f'{key}@{DOMAIN}', password_hash=admin['password_hash'], first_name=first, last_name=last,
            role='employee', employee_id=f'NMF-{1021 + i}', department='Internal Audit', job_title=title,
            cms_access_level='edit', is_active=1, created_at=str(ctx.ago(370)), updated_at=str(ctx.ago(40)),
            department_id=ctx.depts.get('NMF-IA'), org_unit_id=ctx.units['NMF-IA'], authority_level='group',
            mfa_enabled=False, mfa_required_override=False, failed_login_count=0, auth_version=0,
            last_login=ctx.ago(ctx.rnd.randrange(0, 4), hour=9), can_assign_training=False,
            manager_id=ctx.uid('audit'), **vals)
    # 'group' authority = the whole organisation: give each such user the root-unit scope rule
    # (without a rule a non-admin user sees no scoped record at all).
    ctx.q("""INSERT INTO user_org_scope_rules (user_id, rule_type, org_unit_id)
             SELECT u.id, 'subtree', (SELECT id FROM org_units WHERE parent_id IS NULL ORDER BY id LIMIT 1)
               FROM users u
              WHERE u.authority_level = 'group'
                AND NOT EXISTS (SELECT 1 FROM user_org_scope_rules r WHERE r.user_id = u.id)""")


def seed(ctx):
    from flask import current_app
    rnd = ctx.rnd
    today = ctx.today
    risk_ids = ctx.data.get('risk_ids') or {}
    if not risk_ids:  # running alone on top of the risk area
        from m_risk import RISKS, EXISTING
        for r in RISKS:
            t = r[4] or ''
            row = ctx.one("SELECT id FROM risks WHERE risk_title = %s OR risk_id = %s", (t, EXISTING.get(r[0], '-')))
            if row:
                risk_ids[r[0]] = row['id']
    ctl = {r['control_code']: r['id'] for r in ctx.q("SELECT id, control_code FROM controls")}
    rc = {r['control_code']: r['id'] for r in ctx.q("SELECT id, control_code FROM rc_controls")}
    _auditors(ctx)

    def dt(days, hour=None):
        d = datetime.combine(today + timedelta(days=days), datetime.min.time())
        return d.replace(hour=hour if hour is not None else rnd.randint(9, 16), minute=rnd.randrange(60))

    # ---------------- audit universe
    uni = []
    for i, (name, desc, level, unit, freq, rks, rcs) in enumerate(UNIVERSE):
        uid = ctx.ins('audit_universe', auditable_area=name, area_description=desc, risk_level=level,
                      department_id=ctx.depts.get(unit), audit_frequency=freq,
                      responsible_department=ctx.one("SELECT name_en FROM org_units WHERE code = %s", (unit,))['name_en'],
                      is_active=True, created_at=ctx.ago(372, 10))
        uni.append(uid)
        for rk in rks:
            if rk in risk_ids:
                ctx.ins('audit_universe_risks', universe_id=uid, risk_id=risk_ids[rk])
        for code in rcs:
            if code in rc:
                ctx.ins('ia_area_controls', universe_id=uid, control_id=rc[code])

    # ---------------- annual plans
    y = today.year
    plans = {
        -1: ctx.ins('annual_audit_plans', plan_year=y - 1, plan_name=f'{y - 1} Risk-Based Internal Audit Plan',
                    status='CLOSED', approved_date=date(y - 2, 12, 17), approved_by=ctx.uid('ceo'),
                    created_at=datetime(y - 2, 11, 20, 10, 0)),
        0: ctx.ins('annual_audit_plans', plan_year=y, plan_name=f'{y} Risk-Based Internal Audit Plan',
                   status='IN_PROGRESS', approved_date=date(y - 1, 12, 16), approved_by=ctx.uid('ceo'),
                   created_at=datetime(y - 1, 11, 18, 10, 30)),
        1: ctx.ins('annual_audit_plans', plan_year=y + 1, plan_name=f'{y + 1} Risk-Based Internal Audit Plan (draft)',
                   status='DRAFT', created_at=ctx.ago(12, 11)),
    }

    # ---------------- engagements
    seq = {}
    proj = {}
    program_steps = {}
    for (key, py, name, area, atype, scope, start, end, status, lead, team, program) in sorted(
            PROJECTS, key=lambda p: p[6]):
        yr = y + py
        seq[yr] = seq.get(yr, 0) + (7 if yr < y and yr not in seq else 1)
        a_start = today + timedelta(days=start + rnd.randint(-2, 3)) if status != 'PLANNED' else None
        a_end = today + timedelta(days=end + rnd.randint(0, 6)) if status in ('CLOSED',) else None
        if a_end and a_end >= today:
            a_end = today - timedelta(days=1)
        pid = ctx.ins('audit_projects', plan_id=plans[py], audit_number=f'AUD-{yr}-{seq[yr]:04d}', audit_name=name,
                      auditable_area_id=uni[area], audit_type=atype, audit_scope=scope,
                      planned_start_date=today + timedelta(days=start), planned_end_date=today + timedelta(days=end),
                      actual_start_date=a_start, actual_end_date=a_end, lead_auditor_id=ctx.uid(lead), status=status,
                      created_at=dt(min(start - 30, -13), 10))
        proj[key] = dict(id=pid, start=start, end=end, status=status, lead=lead, team=team, name=name)
        for user, role, hours in team:
            ctx.ins('audit_team_members', project_id=pid, user_id=ctx.uid(user), role_on_engagement=role,
                    allocated_hours=hours)
        steps = []
        n = len(program)
        for i, (proc, ccode, result) in enumerate(program, start=1):
            performer = [u for u, r, h in team if r in ('LEAD', 'AUDITOR')]
            performer = performer[(i - 1) % len(performer)]
            done = result is not None and status != 'PLANNED'
            pday = min(-1, start + int((end - start) * i / (n + 1)))
            reviewed = done and status not in ('FIELDWORK',)
            sid = ctx.ins('audit_programs', project_id=pid, step_number=i, procedure_description=proc,
                          control_id=ctl.get(ccode), test_result=result if done else
                          ('NOT_TESTED' if status == 'FIELDWORK' else None),
                          workpaper_reference=f'WP-{i:02d}' if done else None,
                          performed_by=ctx.uid(performer) if done else None, performed_at=dt(pday) if done else None,
                          reviewed_by=ctx.uid('audit') if reviewed and performer != 'audit' else
                          (ctx.uid('ia1') if reviewed else None),
                          reviewed_at=dt(min(-1, pday + 6)) if reviewed else None)
            steps.append((sid, proc, ccode, result if done else None, pday))
            if done and ccode in ctl and result in ('EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE'):
                ctx.ins('control_test_results', control_id=ctl[ccode], tested_by=ctx.uid(performer),
                        test_date=today + timedelta(days=pday), test_procedure=proc, result=result,
                        exceptions_noted=None if result == 'EFFECTIVE' else 'See internal audit finding / working paper.',
                        audit_project_id=pid, created_at=dt(pday))
        program_steps[key] = steps

    # ---------------- findings
    fnum = {}
    fid_by = {}
    for (pk, title, sev, desc, cause, rec, resp, target, status, rk, ccode, created, mresp) in FINDINGS:
        p = proj[pk]
        fnum[pk] = fnum.get(pk, 0) + 1
        verifier = None
        if status == 'VERIFIED_CLOSED':
            verifier = 'audit' if p['lead'] != 'audit' or resp == 'audit' else 'ia1'
            if verifier == resp:
                verifier = 'ia1'
        ver_at = dt(min(-2, target + rnd.randint(2, 20)), 14) if verifier else None
        fid = ctx.ins('audit_findings', project_id=p['id'], finding_number=f'F-{fnum[pk]:03d}', finding_title=title,
                      finding_description=desc, severity=sev, root_cause=cause, recommendation=rec,
                      management_response=mresp, agreed_action=rec if mresp else None,
                      responsible_person_id=ctx.uid(resp), target_date=today + timedelta(days=target), status=status,
                      verified_by=ctx.uid(verifier) if verifier else None, verified_at=ver_at,
                      verification_notes=('Closure evidence inspected and a sample re-tested; no exceptions.'
                                          if verifier else None),
                      linked_risk_id=risk_ids.get(rk), linked_control_id=ctl.get(ccode),
                      created_at=dt(-created, 11), aml_red_flag=(title == 'Third-party repayments not reviewed'))
        fid_by[(pk, fnum[pk])] = fid
        if rk in risk_ids:
            ctx.ins('risk_source_links', risk_id=risk_ids[rk], source_module='internal_audit',
                    source_table='audit_findings', source_record_id=fid,
                    link_type='TRIGGER' if sev == 'CRITICAL' else 'EVIDENCE', linked_by=ctx.uid('audit'),
                    linked_at=dt(-created + 1, 12), notes=f'Internal audit finding {p["name"]} F-{fnum[pk]:03d}.')

    # ---------------- universe: last / next audit
    for key, p in proj.items():
        if p['status'] in ('CLOSED', 'FOLLOW_UP', 'MANAGEMENT_RESPONSE', 'REPORTING'):
            area_id = ctx.one("SELECT auditable_area_id FROM audit_projects WHERE id = %s", (p['id'],))['auditable_area_id']
            ctx.q("UPDATE audit_universe SET last_audit_date = GREATEST(COALESCE(last_audit_date, '1900-01-01'), %s) "
                  "WHERE id = %s", (today + timedelta(days=p['end']), area_id))
    freq_days = {'QUARTERLY': 91, 'SEMI_ANNUAL': 182, 'ANNUAL': 365, 'BIENNIAL': 730}
    for u in ctx.q("SELECT id, last_audit_date, audit_frequency, created_at FROM audit_universe"):
        nxt = None
        if u['last_audit_date']:
            nxt = u['last_audit_date'] + timedelta(days=freq_days[u['audit_frequency']])
        else:
            nxt = date(y + 1, rnd.choice([3, 5, 9]), 1)
        ctx.q("UPDATE audit_universe SET next_audit_due = %s WHERE id = %s", (nxt, u['id']))
    # areas planned this year but not yet audited
    for key in ('fin26', 'bcp26', 'price26', 'cai26'):
        ctx.q("UPDATE audit_universe SET next_audit_due = %s WHERE id = (SELECT auditable_area_id FROM audit_projects "
              "WHERE id = %s)", (today + timedelta(days=proj[key]['start']), proj[key]['id']))

    # ---------------- working papers (real files under uploads/)
    root = current_app.root_path
    for key, p in proj.items():
        if p['status'] == 'PLANNED':
            continue
        rel_dir = f"uploads/internal_audit/working_papers/{p['id']}"
        os.makedirs(os.path.join(root, rel_dir), exist_ok=True)
        papers = []
        steps = program_steps[key]
        papers.append(('planning_memo.pdf', 'Planning memorandum and risk assessment', None, None, p['start'],
                       lambda path, p=p: _pdf(path, f"{p['name']} - Planning memorandum",
                                              ['Objective: provide assurance on the design and operating '
                                               'effectiveness of key controls.',
                                               f"Scope: {ctx.one('SELECT audit_scope FROM audit_projects WHERE id = %s', (p['id'],))['audit_scope']}",
                                               'Approach: risk assessment, walkthroughs, sample testing, reporting.',
                                               'Team and budget as recorded in the engagement file.'])))
        for sid, proc, ccode, result, pday in steps:
            if result and result != 'N/A':
                papers.append((f'WP-{len(papers):02d}_testing.xlsx', f'Testing sheet - {proc[:80]}', sid, None, pday,
                               lambda path, proc=proc, result=result: _xlsx(
                                   path, proc, ['Sample #', 'Reference', 'Attribute tested', 'Result', 'Comment'],
                                   [[i + 1, f'DEMO-{rnd.randint(10000, 99999)}', 'As per procedure',
                                     'Exception' if (result != 'EFFECTIVE' and i % 5 == 2) else 'OK', '']
                                    for i in range(20)])))
        if p['status'] in ('CLOSED', 'FOLLOW_UP', 'MANAGEMENT_RESPONSE', 'REPORTING'):
            label = 'Draft audit report' if p['status'] == 'REPORTING' else 'Final audit report'
            papers.append((label.lower().replace(' ', '_') + '.pdf', label, None, None, p['end'] + 3,
                           lambda path, p=p, label=label: _pdf(
                               path, f"{p['name']} - {label}",
                               [f"Findings: {fnum.get(key, 0)}. Overall rating: "
                                f"{'Needs improvement' if fnum.get(key, 0) > 2 else 'Satisfactory with exceptions'}.",
                                'Detailed findings, root causes, recommendations and management responses are '
                                'recorded in the audit management system.'])))
        for i in range(1, fnum.get(key, 0) + 1):
            if i == 1:
                papers.append((f'finding_F-{i:03d}_evidence.pdf', f'Evidence supporting finding F-{i:03d}', None,
                               fid_by[(key, i)], p['end'],
                               lambda path, key=key, i=i: _pdf(path, f'Evidence for finding F-{i:03d}',
                                                               ['Copies of sampled documents and screenshots.'])))
        for fname, desc, sid, fid, day, make in papers:
            path = os.path.join(root, rel_dir, fname)
            make(path)
            ctx.ins('audit_working_papers', project_id=p['id'], program_step_id=sid, finding_id=fid,
                    file_path=f'{rel_dir}/{fname}', description=desc,
                    uploaded_by=ctx.uid(p['lead']), uploaded_at=dt(min(-1, day), 15))

    # committee report narrative (system_settings key/value store)
    for k, v in CAE_NARRATIVE.items():
        if ctx.one("SELECT 1 FROM system_settings WHERE setting_key = %s", (k,)):
            ctx.q("UPDATE system_settings SET setting_value = %s WHERE setting_key = %s", (v, k))
        else:
            ctx.q("INSERT INTO system_settings (setting_key, setting_value, updated_at) VALUES (%s, %s, %s)",
                  (k, v, str(ctx.ago(3, 16))))

    ctx.commit()
    # AML red flag from the audit -> unusual-transactions register (FRA-037)
    try:
        from amlkyc import service as amlsvc
        amlsvc.route_audit_red_flags()
    except Exception as e:  # keep the area running if that module changes
        print('    red-flag routing skipped:', str(e)[:120])
    ctx.commit()

    _reporting(ctx)
    _evidence(ctx)


# ---------------------------------------------------------------- regulatory reporting
def _reporting(ctx):
    rnd = ctx.rnd
    today = ctx.today
    # CBE returns do not apply to an FRA-licensed microfinance company
    ctx.q("UPDATE regulatory_reports SET is_active = 0 WHERE report_code LIKE 'CBE-%%'")
    # leftover test regulator with no reports
    ctx.q("UPDATE regulators SET is_active = 0 WHERE regulator_code = 'TR-001' AND regulator_name = 'Updated Regulator' "
          "AND NOT EXISTS (SELECT 1 FROM regulatory_reports r WHERE r.regulator_id = regulators.id)")
    reps = {r['report_code']: r for r in ctx.q("SELECT * FROM regulatory_reports WHERE is_active = 1")}
    rows = []  # code, start, end, due, submitted, status, notes, prep, rev

    def add(code, ps, pe, due, sub, status, notes, prep, rev):
        if code in reps:
            rows.append((code, ps, pe, due, sub, status, notes, prep, rev))

    # FRA-M01 consumer complaints log - monthly, due on the 7th
    for k in range(-12, 2):
        ps = _month_start(today, k - 1)
        pe = _month_start(today, k) - timedelta(days=1)
        due = _month_start(today, k) + timedelta(days=6)
        if due < today - timedelta(days=375):
            continue
        if due > today:
            add('FRA-M01', ps, pe, due, None, 'pending', None, 'cs', 'co')
        elif (today - due).days < 20:
            add('FRA-M01', ps, pe, due, None, 'in_progress',
                'Branch complaints for the period are still being reconciled with the central register.', 'cs', 'co')
        elif k == -5:
            add('FRA-M01', ps, pe, due, due + timedelta(days=4), 'submitted',
                'Submitted 4 days after the deadline - FRA portal outage on the due date and late branch data. '
                'Explanation letter sent to the FRA.', 'cs', 'co')
        else:
            add('FRA-M01', ps, pe, due, due - timedelta(days=rnd.randint(0, 3)), 'submitted', None, 'cs', 'co')
    # FRA-RPD responsible-pricing disclosure - quarterly, 15th of the month after the quarter
    # FRA-RPD (responsible-pricing disclosure) is left out on purpose: the FRA-019 check
    # (packs/fra_nbfi/lending/checks.py pricing_disclosure) compares the TEXT due_date with a date and
    # ends in a TypeError as soon as a submission exists. Set SEED_RPD = True once that is fixed.
    cqs = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    for k in (range(-4, 1) if SEED_RPD else ()):
        qs = _month_start(cqs, 3 * k)
        qe = _month_start(qs, 3) - timedelta(days=1)
        due = _month_start(qs, 3) + timedelta(days=14)
        if due > today:
            add('FRA-RPD', qs, qe, due, None, 'pending', None, 'co', 'mlro')
        else:
            add('FRA-RPD', qs, qe, due, due - timedelta(days=rnd.randint(1, 4)), 'submitted', None, 'co', 'mlro')
    # annual returns
    y = today.year
    add('FRA-A01', date(y - 1, 1, 1), date(y - 1, 12, 31), date(y, 1, 15), date(y, 1, 13), 'submitted',
        'Approved by the board on 11 January.', 'sec', 'mlro')
    add('FRA-A01', date(y, 1, 1), date(y, 12, 31), date(y + 1, 1, 15), None, 'pending', None, 'sec', 'mlro')
    add('FRA-ESG', date(y - 1, 1, 1), date(y - 1, 12, 31), date(y, 4, 30), date(y, 4, 27), 'submitted',
        'First ESG / TCFD disclosure templates.', 'risk', 'mlro')
    add('FRA-ESG', date(y, 1, 1), date(y, 12, 31), date(y + 1, 4, 30), None, 'pending', None, 'risk', 'mlro')
    add('FRA-CARBON', date(y - 1, 1, 1), date(y - 1, 12, 31), date(y, 12, 31), None, 'in_progress',
        'Activity data collected; verifier engaged for November.', 'risk', 'cfo')
    # EMLCU weekly suspicious-transaction summary - last 12 weeks, due the following Monday
    # weekly due_day 1 = Tuesday (Python weekday numbering, as the app's calendar projects it)
    monday = today - timedelta(days=(today.weekday() - 1) % 7)
    for w in range(12, -2, -1):
        due = monday - timedelta(days=7 * w)
        ws_ = due - timedelta(days=7)
        we = due - timedelta(days=1)
        if due > today:
            add('MLCU-W01', ws_, we, due, None, 'pending', None, 'aml', 'mlro')
        else:
            add('MLCU-W01', ws_, we, due, due, 'submitted', None, 'aml', 'mlro')
    n = 0
    for code, ps, pe, due, sub, status, notes, prep, rev in rows:
        created = min(today, ps + timedelta(days=(pe - ps).days + 1)) if status != 'pending' else today - timedelta(days=rnd.randint(5, 25))
        n += 1
        ctx.ins('regulatory_report_submissions', report_id=reps[code]['id'], reporting_period_start=str(ps),
                reporting_period_end=str(pe), due_date=str(due), submission_date=str(sub) if sub else None,
                status=status, notes=notes,
                submission_reference=f'{"EMLCU" if code.startswith("MLCU") else "FRA"}-DEMO-{due:%Y%m%d}-{n:03d}' if sub else None,
                prepared_by=ctx.uid(prep), reviewed_by=ctx.uid(rev) if status != 'pending' else None,
                approved_by=ctx.uid(rev) if sub else None, reminder_sent=1 if status != 'pending' or (due - today).days < 7 else 0,
                reminder_date=str(due - timedelta(days=5)) if status != 'pending' else None,
                created_at=f'{created} 09:{rnd.randrange(60):02d}:00',
                updated_at=f'{sub or (today - timedelta(days=rnd.randint(0, 4)))} 1{rnd.randint(0, 6)}:{rnd.randrange(60):02d}:00')


# ---------------------------------------------------------------- evidence for FRA controls
EVIDENCE = [  # control, title, description, reference, valid from (days), valid to (days), submitter, reviewer,
    # decision (approved / rejected / pending / system), unit
    ('FRA-069', 'External penetration test report 2026', 'Grey-box penetration test of the client portal and core '
     'system by an independent tester; includes retest letter.', 'DEMO-PT-2026-03', -150, 215, 'it', 'mlro',
     'approved', 'NMF-IT'),
    ('FRA-067', 'DR test report August 2025', 'Fail-over test of the core system to the DR site (partial success).',
     'DEMO-DR-2025-08', -430, -65, 'it', 'risk', 'approved', 'NMF-IT'),
    ('FRA-074', 'Board resolution approving the information-security policy set', 'Board meeting minutes extract.',
     'DEMO-BR-2026-02-07', -250, 480, 'sec', 'mlro', 'approved', 'NMF-LEG'),
    ('FRA-030', 'AML/CFT policy manual v4.0 - board approval', 'Updated manual and board resolution.',
     'DEMO-BR-2026-03-12', -220, 145, 'mlro', 'co', 'approved', 'NMF-COMP'),
    ('FRA-053', 'Annual MLRO report 2025 - board approval extract', 'Extract of the board minutes approving the '
     'annual MLRO report.', 'DEMO-BR-2026-10-05', -17, 348, 'mlro', None, 'pending', 'NMF-COMP'),
    ('FRA-065', 'External auditor certificate - deferred tax assets', 'Auditor certificate supporting DTA '
     'recoverability for FY2025.', 'DEMO-EXT-2026-044', -120, 245, 'cfo', 'mlro', 'approved', 'NMF-FIN'),
    ('FRA-066', 'ECL study FY2025', 'ECL methodology and results.', 'DEMO-ECL-2025', -60, 300, 'cfo', 'audit',
     'rejected', 'NMF-FIN'),
    ('FRA-054', 'Internal audit plan 2026 - board approval', 'Risk-based plan covering regulatory findings, '
     'approved by the board.', 'DEMO-BR-2025-12-16', -310, 70, 'audit', 'mlro', 'approved', 'NMF-IA'),
    ('FRA-001', 'Paid-up capital certificate', 'Bank certificate of paid-up capital.', 'DEMO-CAP-2025-11', -335, 18,
     'cfo', 'mlro', 'approved', 'NMF-FIN'),
    ('FRA-072', 'SSL certificate check - client portal', 'Automatic certificate check.', 'DEMO-SSL-AUTO',
     -40, 50, None, None, 'system', 'NMF-IT'),
    ('FRA-CF-04', 'Carbon footprint verification statement FY2025', 'Limited assurance statement by the accredited '
     'verifier.', 'DEMO-VVB-2025-117', -100, 265, 'risk', 'cfo', 'approved', 'NMF-RISK'),
    ('FRA-051', 'Off-site encrypted backup confirmation', 'Monthly confirmation from the backup provider.',
     'DEMO-BKP-2026-09', -21, 9, 'itsup', 'it', 'approved', 'NMF-IT'),
]


def _evidence(ctx):
    from regcontrols import evidence as ev
    today = ctx.today
    tmp = tempfile.mkdtemp(prefix='nmf_ev_')
    ctx.commit()
    made = []
    for (code, title, desc, ref, vf, vt, sub, rev, decision, unit) in EVIDENCE:
        if not ctx.one("SELECT 1 FROM rc_controls WHERE control_code = %s", (code,)):
            continue
        fname = f"{code}_{ref}.pdf".replace('/', '-')
        path = os.path.join(tmp, fname)
        _pdf(path, title, [desc, f'Reference: {ref}',
                           f'Valid from {today + timedelta(days=vf)} to {today + timedelta(days=vt)}.'])
        eid = ev.record_evidence(code, title, valid_from=today + timedelta(days=vf),
                                 valid_to=today + timedelta(days=vt), description=desc, reference_no=ref,
                                 submitted_by=ctx.uid(sub) if sub else None, org_unit_id=ctx.units.get(unit),
                                 source='system' if decision == 'system' else 'manual',
                                 source_module='cyber' if decision == 'system' else None,
                                 file_path=None if decision == 'system' else path, file_name=fname)
        if decision in ('approved', 'rejected'):
            ev.review(eid, ctx.uid(rev), decision,
                      comment=('ECL study is not yet approved by the board - resubmit with the board resolution.'
                               if decision == 'rejected' else 'Reviewed - document complete and in date.'))
        made.append((eid, vf, decision))
    ctx.commit()
    for eid, vf, decision in made:
        sub_at = datetime.combine(today + timedelta(days=min(-1, vf + ctx.rnd.randint(1, 10))), datetime.min.time()).replace(hour=11)
        rev_at = sub_at + timedelta(days=ctx.rnd.randint(1, 4), hours=3) if decision != 'pending' else None
        if rev_at and rev_at.date() >= today:
            rev_at = sub_at + timedelta(hours=4)
        ctx.q("UPDATE rc_evidence SET submitted_at = %s, reviewed_at = %s WHERE id = %s", (sub_at, rev_at, eid))
        ctx.q("UPDATE generic_attachments SET uploaded_at = %s WHERE module = 'regcontrols' AND "
              "record_type = 'rc_evidence' AND record_id = %s", (sub_at.strftime('%Y-%m-%d %H:%M:%S'), eid))
    ctx.commit()
    try:  # daily job: mark expired items and alert owners about expiring ones
        ev.sweep_expiry()
    except Exception as e:
        print('    evidence expiry sweep skipped:', str(e)[:120])
