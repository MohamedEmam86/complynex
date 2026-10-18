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
Content of the FRA NBFI pack: Egypt's Financial Regulatory Authority (FRA)
requirements for non-bank financial institutions, as generalised in
docs/regulatory/FRA_NBFI_CONTROL_MAP.md (anonymised from one inspection memo).

This is DATA for the generic core: one framework, one requirement per map ID,
one control per requirement, the pack's areas / licence types / owner roles,
and the regulatory parameters its checks read. packs/fra_nbfi/__init__.py
installs it through regcontrols.catalog.

Grouped rows in the map (FRA-038–042, 043–045, 057–058, 059–060, 062–063,
064–065, 075–077) are split into one requirement/control per ID so each can
be evidenced, failed and reported on its own.

Nothing here may contain a client, branch, counterparty or figure from the
inspection memo. Regulatory numbers whose exact value the map does not give
are seeded with value NULL and needs_review=true — they must be confirmed by
Compliance before the check that reads them can pass.
"""

from regcontrols.vocab import TYPE_LETTERS

PACK_CODE = 'fra_nbfi'

REGULATOR = {'code': 'FRA', 'name_en': 'Financial Regulatory Authority', 'name_ar': 'الهيئة العامة للرقابة المالية',
             'jurisdiction': 'EG', 'website': 'https://fra.gov.eg'}

FRAMEWORK = {
    'code': 'FRA-NBFI', 'name_en': 'FRA requirements for non-bank financial institutions',
    'name_ar': 'متطلبات الهيئة العامة للرقابة المالية للمؤسسات المالية غير المصرفية', 'jurisdiction': 'EG',
    'version': '2026.1',
    'description': 'Requirements generalised from FRA inspection findings for microfinance, consumer-finance, '
                   'leasing and factoring companies.',
    'source_document': 'docs/regulatory/FRA_NBFI_CONTROL_MAP.md',
}

# --------------------------------------------------------------------------
# Pack vocabularies (installed into rc_areas / rc_licence_types / rc_owner_roles)
# --------------------------------------------------------------------------

AREAS = {
    'capital_licensing': ('Capital, solvency, licensing & key functions',
                          'رأس المال والملاءة والترخيص والوظائف الرئيسية'),
    'origination': ('Origination, client files & portfolio follow-up',
                    'منح التمويل وملفات العملاء ومتابعة المحفظة'),
    'pricing_conduct': ('Pricing, fees, penalties & consumer protection',
                        'التسعير والرسوم والغرامات وحماية العملاء'),
    'aml_cft': ('AML/CFT', 'مكافحة غسل الأموال وتمويل الإرهاب'),
    'financial_reporting': ('Accounting, financial statements & related parties',
                            'المحاسبة والقوائم المالية والأطراف ذات العلاقة'),
    'it_cyber': ('IT, cyber & continuity', 'تكنولوجيا المعلومات والأمن السيبراني واستمرارية الأعمال'),
    'remediation': ('Remediation of findings', 'معالجة الملاحظات'),
}

# Roles the core does not ship (the core has compliance_head, cfo, it_head, ciso,
# internal_audit_head, operations_head, hr_head, board_secretary, risk_head).
OWNER_ROLES = {
    'mlro': ('MLRO', 'مسؤول الإبلاغ عن غسل الأموال'),
    'credit_head': ('Head of Credit', 'رئيس إدارة الائتمان'),
    'cro': ('Chief Risk Officer', 'رئيس إدارة المخاطر'),
}

LICENCE_TYPES = {
    'microfinance': ('Microfinance', 'التمويل متناهي الصغر'),
    'consumer_finance': ('Consumer finance', 'التمويل الاستهلاكي'),
    'leasing': ('Financial leasing', 'التأجير التمويلي'),
    'factoring': ('Factoring', 'التخصيم'),
}

# Checks bound to controls. Core checks start with 'core.'; this pack's own
# checks (registered by its check modules) start with 'fra_nbfi.'.
CHECK_KEYS = {
    'FRA-079': 'core.findings_not_repeated',
    'FRA-004': 'fra_nbfi.lending.eligibility',
    'FRA-009': 'fra_nbfi.lending.contracts_signed',
    'FRA-010': 'fra_nbfi.lending.followup',
    'FRA-011': 'fra_nbfi.lending.par_threshold',
    'FRA-012': 'fra_nbfi.lending.par_remediation',
    'FRA-013': 'fra_nbfi.lending.gps_recorded',
    'FRA-014': 'fra_nbfi.lending.receipt_ack',
    'FRA-015': 'fra_nbfi.lending.credit_study',
    'FRA-016': 'fra_nbfi.lending.study_quality',
    'FRA-017': 'fra_nbfi.lending.admin_fee_cap',
    'FRA-018': 'fra_nbfi.lending.admin_fee_tiers',
    'FRA-019': 'fra_nbfi.lending.pricing_disclosure',
    'FRA-020': 'fra_nbfi.lending.late_penalties',
    'FRA-021': 'fra_nbfi.lending.er_disclosure',
    'FRA-022': 'fra_nbfi.lending.er_consent',
    'FRA-023': 'fra_nbfi.lending.refinance',
    'FRA-024': 'fra_nbfi.lending.er_ack',
    'FRA-025': 'fra_nbfi.lending.transfer_fees',
    'FRA-026': 'fra_nbfi.lending.rescheduling_fees',
    # AML/CFT & KYC — generic core checks, tuned through CHECK_CONFIG below.
    'FRA-027': 'core.aml.role_independence',
    'FRA-028': 'core.aml.role_conflicts',
    'FRA-029': 'core.aml.combined_roles',
    'FRA-030': 'core.policies.board_approval',
    'FRA-031': 'core.aml.monitoring_programme',
    'FRA-032': 'core.screening.required_sources',
    'FRA-033': 'core.screening.source_freshness',
    'FRA-034': 'core.screening.qa_recall',
    'FRA-035': 'core.aml.unusual_register',
    'FRA-036': 'core.aml.unusual_studied',
    'FRA-037': 'core.audit.red_flags_routed',
    'FRA-038': 'core.kyc.fields',
    'FRA-039': 'core.kyc.fields',
    'FRA-040': 'core.kyc.fields',
    'FRA-041': 'core.kyc.fields',
    'FRA-042': 'core.kyc.fields',
    'FRA-043': 'core.kyc.fields',
    'FRA-044': 'core.kyc.fields',
    'FRA-045': 'core.kyc.beneficial_owners',
    'FRA-046': 'core.kyc.bo_declaration',
    'FRA-047': 'core.kyc.refresh_cycle',
    'FRA-048': 'core.kyc.risk_model',
    'FRA-049': 'core.kyc.rated',
    'FRA-050': 'core.kyc.edd_high_risk',
    # FRA-051 (off-site backup) stays an evidence control until the IT module adds a check.
    'FRA-052': 'core.screening.employees',
    'FRA-053': 'core.aml.annual_report',
    'FRA-054': 'core.audit.plan_coverage',
    'OBS-01': 'core.training.coverage',
}

# Settings for the generic checks above (rc_controls.check_config, editable on
# the control's edit page). Source-name patterns are matched case-insensitively.
# TODO(compliance-review): confirm the list of mandatory watchlists and the
# exact KYC fields per FRA instructions before go-live.
_KYC = ['aml_customer']
_KYB = ['aml_customer', 'merchant']
CHECK_CONFIG = {
    'FRA-027': {'role_codes': ['mlro']},
    'FRA-028': {'role_codes': ['mlro']},
    'FRA-029': {'role_codes': ['mlro']},
    'FRA-030': {'name_contains': ['aml', 'money laundering', 'غسل']},
    'FRA-032': {'required': [
        {'label': 'UN Security Council consolidated list', 'match': ['un ', 'united nations', 'unsc', 'security council']},
        {'label': 'Local terrorist / terrorist-entity lists', 'match': ['terror', 'إرهاب', 'local']},
        {'label': 'Asset-freeze orders', 'match': ['freeze', 'تجميد']},
    ]},
    'FRA-033': {'max_age_param': 'aml.watchlist_freshness_max_hours'},
    'FRA-034': {'max_age_days': 31, 'min_recall_param': 'aml.screening_min_recall_pct'},
    'FRA-038': {'subjects': _KYC, 'fields': ['gender']},
    'FRA-039': {'subjects': _KYC, 'fields': ['nationality']},
    'FRA-040': {'subjects': _KYC, 'fields': ['residence_country']},
    'FRA-041': {'subjects': _KYC, 'fields': ['address']},
    'FRA-042': {'subjects': _KYC, 'fields': ['id_type']},
    'FRA-043': {'subjects': _KYB, 'fields': ['tax_card_number', 'tax_card_issuer']},
    'FRA-044': {'subjects': _KYB, 'fields': ['senior_management']},
    'FRA-045': {'subjects': _KYB},
    'FRA-046': {'subjects': _KYB, 'kinds': ['entity']},
    'FRA-047': {'subjects': _KYB},
    'FRA-049': {'subjects': _KYB},
    'FRA-050': {'subjects': _KYB},
    'FRA-052': {'months_param': 'aml.employee_rescreen_months'},
    'FRA-053': {'role_code': 'mlro', 'approve_by_month': 6},
    'FRA-054': {'criticality': ['critical', 'high']},
    'OBS-01': {'category': 'AML', 'target_param': 'training.aml_coverage_target_pct'},
}

_LENDING = ['microfinance', 'consumer_finance']


def _c(code, area, types, title_en, title_ar, behaviour, module, owner, freq,
       crit='high', params=None, licences=None):
    return {
        'code': code,
        'area': area,
        'type_codes': types,
        'control_type': TYPE_LETTERS[types[0]],
        'title_en': title_en,
        'title_ar': title_ar,
        'requirement_en': behaviour,
        'test_procedure_en': 'Confirm that: ' + behaviour[0].lower() + behaviour[1:].rstrip('.') + '.',
        'linked_module': module,
        'owner_role': owner,
        'frequency': freq,
        'criticality': crit,
        'linked_params': params or [],
        'licence_types': licences or ['all'],
        'check_key': CHECK_KEYS.get(code),
        'check_config': CHECK_CONFIG.get(code),
    }


CONTROLS = [
    # ---------------------------------------------------------------- 1
    _c('FRA-001', 'capital_licensing', 'A/M', 'Paid-up capital at or above the licence minimum',
       'رأس المال المدفوع لا يقل عن الحد الأدنى للترخيص',
       'Capital register (authorised/issued/paid/registered, by date) is compared with the minimum per licence '
       'type; red if below; days to deadline shown.',
       'prudential', 'cfo', 'monthly', 'critical', ['capital.min_paid_up']),
    _c('FRA-002', 'capital_licensing', 'W/A', 'Capital increase completed within granted extensions',
       'استكمال زيادة رأس المال خلال المهل الممنوحة',
       'Regulatory deadlines register (general/special extensions, letters) with countdown alerts at the '
       'configured days before the deadline and escalation to the board.',
       'prudential', 'board_secretary', 'daily', 'critical', ['capital.deadline_alert_days']),
    _c('FRA-003', 'capital_licensing', 'A/M', 'Solvency standards met (equity, leverage, capital base)',
       'الالتزام بمعايير الملاءة (حقوق الملكية والرافعة وقاعدة رأس المال)',
       'Quarterly solvency calculation from financial data input/import; negative equity is critical; trend '
       'over time.',
       'prudential', 'cfo', 'quarterly', 'critical', ['solvency.max_leverage_ratio', 'solvency.min_equity']),
    _c('FRA-004', 'capital_licensing', 'A', 'Clients within the licensed activity scope',
       'العملاء في نطاق النشاط المرخص به',
       'Eligibility rule at origination and on portfolio import: client monthly revenue / project size vs the '
       'licence ceiling; a breach blocks the loan or needs an approved exception.',
       'lending', 'credit_head', 'daily', 'high',
       ['lending.max_client_monthly_revenue', 'lending.max_project_size'], _LENDING),
    _c('FRA-005', 'capital_licensing', 'A/E', 'Consistent registered address on official documents',
       'توحيد العنوان المسجل في المستندات الرسمية',
       'Corporate profile is the single source of truth for the registered address; templates use it; uploaded '
       'board minutes/letters whose address differs are flagged.',
       'governance', 'board_secretary', 'quarterly', 'medium'),
    _c('FRA-006', 'capital_licensing', 'W/E', 'Key functions filled and notified to FRA',
       'شغل الوظائف الرئيسية وإخطار الهيئة بها',
       'Key-functions register (role, holder, fit & proper, FRA notification date/reference, no-objection '
       'status); vacancy and "filled but not notified" alerts.',
       'governance', 'compliance_head', 'monthly', 'high'),
    _c('FRA-007', 'capital_licensing', 'W', 'Branch manager appointed with FRA no-objection',
       'تعيين مدير الفرع بعد عدم ممانعة الهيئة',
       'Branch register with manager; FRA no-objection required before a branch is active; vacancy timer after '
       'a resignation.',
       'governance', 'operations_head', 'monthly', 'high', ['branch.manager_vacancy_max_days']),
    _c('FRA-008', 'capital_licensing', 'A/M', 'Minimum operational staffing per branch',
       'الحد الأدنى من العاملين بكل فرع',
       'Branch staffing matrix compared with the required roles per branch.',
       'governance', 'operations_head', 'monthly', 'medium', ['branch.min_loan_officers']),
    _c('FRA-009', 'capital_licensing', 'A/E', 'Financing contracts signed by both parties',
       'توقيع عقود التمويل من الطرفين',
       'Contract completeness check (lender signature, client signature, dates); an unsigned contract cannot '
       'be marked disbursed; resignations are signed.',
       'lending', 'operations_head', 'daily', 'high', None, _LENDING),
    # ---------------------------------------------------------------- 2
    _c('FRA-010', 'origination', 'A/M', 'Post-disbursement client follow-up',
       'متابعة العملاء بعد الصرف',
       'Follow-up visit schedule per loan; overdue visits alert; PAR30 by branch/officer.',
       'lending', 'credit_head', 'weekly', 'high', ['lending.followup_visit_days'], _LENDING),
    _c('FRA-011', 'origination', 'A/M', 'Collections and arrears monitored',
       'متابعة التحصيل والمتأخرات',
       'Ageing buckets (1-30, 31-60, 61-90, 91-120, >120) and PAR thresholds by branch.',
       'lending', 'credit_head', 'weekly', 'high', ['portfolio.par30_threshold_pct'], _LENDING),
    _c('FRA-012', 'origination', 'W', 'Effective remediation plan for portfolio deterioration',
       'خطة علاج فعالة لتدهور جودة المحفظة',
       'A PAR threshold breach opens a remediation plan (actions, owner, deadline, monthly re-measure); '
       'worsening vs the previous inspection is flagged.',
       'lending', 'credit_head', 'monthly', 'high', ['portfolio.par30_threshold_pct'], _LENDING),
    _c('FRA-013', 'origination', 'A', 'Project location (GPS) recorded in the client file',
       'تسجيل الموقع الجغرافي للمشروع في ملف العميل',
       'Latitude/longitude mandatory above the configured financing amount; missing coordinates make the file '
       'incomplete.',
       'lending', 'operations_head', 'daily', 'medium', ['lending.gps_mandatory_min_amount'], _LENDING),
    _c('FRA-014', 'origination', 'A', 'Client acknowledgement of receipt of funds',
       'إقرار العميل باستلام مبلغ التمويل',
       'Receipt acknowledgement is a required document before a loan is marked disbursed.',
       'lending', 'operations_head', 'daily', 'medium', None, _LENDING),
    _c('FRA-015', 'origination', 'A', 'Detailed client solvency / credit study',
       'دراسة ائتمانية تفصيلية لملاءة العميل',
       'Structured credit-study template (revenues, cost lines, household expenses, debt service, DSR) with '
       'minimum required fields.',
       'lending', 'credit_head', 'daily', 'high', ['lending.max_dsr_pct'], _LENDING),
    _c('FRA-016', 'origination', 'A', 'Due care in credit studies (no templated figures)',
       'بذل العناية الواجبة في الدراسة الائتمانية (عدم تكرار الأرقام)',
       'Anomaly detection: identical figures across clients of one officer, round numbers, too few cost lines, '
       'outlier revenue/cost ratios are sent to QA.',
       'lending', 'credit_head', 'weekly', 'medium', ['lending.min_cost_lines'], _LENDING),
    # ---------------------------------------------------------------- 3
    _c('FRA-017', 'pricing_conduct', 'A', 'Administrative fees within the cap',
       'المصروفات الإدارية في حدود الحد الأقصى',
       'Fee validation on each loan against the admin-fee cap; list of breaches.',
       'lending', 'credit_head', 'daily', 'high', ['lending.admin_fee_cap_pct'], _LENDING),
    _c('FRA-018', 'pricing_conduct', 'A', 'Tiered administrative fees by financing bracket',
       'تدرج المصروفات الإدارية حسب شريحة التمويل',
       'Admin-fee tier table validator per financing bracket.',
       'lending', 'credit_head', 'daily', 'medium', ['lending.admin_fee_tiers'], _LENDING),
    _c('FRA-019', 'pricing_conduct', 'E/A', 'Responsible-pricing disclosure submitted on schedule',
       'تقديم نماذج الإفصاح عن التسعير المسؤول في مواعيدها',
       'Regulatory reporting calendar entry (frequency, due date, submission evidence); a missed submission '
       'raises an alert.',
       'reporting', 'compliance_head', 'quarterly', 'high', None, _LENDING),
    _c('FRA-020', 'pricing_conduct', 'A', 'Late-payment penalties per the rules',
       'غرامات التأخير وفقًا للقواعد',
       'Penalty calculator (rate, cap, method) per parameters; contract clause check; over-charge detection.',
       'lending', 'credit_head', 'daily', 'high',
       ['lending.late_penalty_rate_pct', 'lending.late_penalty_cap_pct'], _LENDING),
    _c('FRA-021', 'pricing_conduct', 'W/A', 'Written disclosure of early-repayment cost difference',
       'إفصاح كتابي عن فرق تكلفة السداد المعجل',
       'The early-repayment flow generates a written disclosure (original vs new cost).',
       'lending', 'operations_head', 'event', 'high', None, _LENDING),
    _c('FRA-022', 'pricing_conduct', 'W', 'Signed client consent before early repayment',
       'موافقة موقعة من العميل قبل تنفيذ السداد المعجل',
       'Signed consent upload is required before an early repayment is executed.',
       'lending', 'operations_head', 'event', 'high', None, _LENDING),
    _c('FRA-023', 'pricing_conduct', 'A', 'Early repayment linked to a new, costlier loan',
       'سداد معجل مرتبط بتمويل جديد أعلى تكلفة',
       'Detect a prepayment followed by a new loan to the same client within the configured days with higher '
       'APR/fees; raise a conduct alert and an AML unusual-transaction candidate.',
       'lending', 'compliance_head', 'daily', 'critical', ['lending.prepay_new_loan_window_days'], _LENDING),
    _c('FRA-024', 'pricing_conduct', 'W', 'Client aware of the cost impact',
       'وعي العميل بأثر التكلفة',
       'Mandatory client acknowledgement in the refinance flow.',
       'lending', 'operations_head', 'event', 'medium', None, _LENDING),
    _c('FRA-025', 'pricing_conduct', 'A', 'Instalment transfer fees within the rules',
       'رسوم نقل الأقساط في حدود القواعد',
       'Fee validator for instalment transfers against the configured cap.',
       'lending', 'credit_head', 'daily', 'medium', ['lending.transfer_fee_cap'], _LENDING),
    _c('FRA-026', 'pricing_conduct', 'A', 'Rescheduling fees within the rules',
       'رسوم إعادة الجدولة في حدود القواعد',
       'Fee validator for reschedulings against the configured cap.',
       'lending', 'credit_head', 'daily', 'medium', ['lending.rescheduling_fee_cap'], _LENDING),
    # ---------------------------------------------------------------- 4
    _c('FRA-027', 'aml_cft', 'A/E', 'MLRO independence (reporting line)',
       'استقلالية مسؤول الإبلاغ (خط التبعية)',
       'Org-chart check: the MLRO must not report to risk or business heads; board-level reporting evidence.',
       'aml', 'compliance_head', 'quarterly', 'critical'),
    _c('FRA-028', 'aml_cft', 'A', 'No conflicting roles for the MLRO',
       'عدم تعارض مهام مسؤول الإبلاغ',
       'Role-conflict matrix on users/positions (e.g. internal control at the parent company).',
       'aml', 'compliance_head', 'quarterly', 'high'),
    _c('FRA-029', 'aml_cft', 'W/E', 'FRA approval for combined roles',
       'موافقة الهيئة على الجمع بين المهام',
       'Any combined role requires an FRA approval reference.',
       'aml', 'compliance_head', 'annual', 'high'),
    _c('FRA-030', 'aml_cft', 'W', 'AML policy manual updated and board-approved',
       'تحديث دليل سياسات مكافحة غسل الأموال واعتماده من المجلس',
       'Policy versioning with a board approval record; "drafted but not approved" ageing alert.',
       'policies', 'mlro', 'annual', 'high', ['policy.max_days_pending_board_approval']),
    _c('FRA-031', 'aml_cft', 'W/M', 'Off-site and on-site AML monitoring of branches/departments',
       'الرقابة المكتبية والميدانية على الفروع والإدارات',
       'AML monitoring programme: annual plan, checklists per branch, findings, follow-up.',
       'aml', 'mlro', 'quarterly', 'high'),
    _c('FRA-032', 'aml_cft', 'A', 'Watchlists include UN Security Council lists',
       'قوائم الحظر تشمل قوائم مجلس الأمن',
       'Coverage check: required list sources (UN, local terrorist lists, freeze orders) are configured and '
       'loaded; a missing source is critical.',
       'screening', 'mlro', 'daily', 'critical'),
    _c('FRA-033', 'aml_cft', 'A', 'Watchlists kept up to date',
       'تحديث قوائم الحظر بصفة مستمرة',
       'Freshness SLA per list source; last-sync age alert.',
       'screening', 'mlro', 'daily', 'critical', ['aml.watchlist_freshness_max_hours']),
    _c('FRA-034', 'aml_cft', 'A/M', 'Effective, tested name matching',
       'فعالية مطابقة الأسماء واختبارها',
       'Screening QA harness: periodic test with seeded synthetic names (incl. Arabic variants, local lists, '
       'freeze orders); recall measured; any miss is a finding.',
       'screening', 'mlro', 'monthly', 'high', ['aml.screening_min_recall_pct']),
    _c('FRA-035', 'aml_cft', 'A', 'Unusual-transactions register complete',
       'اكتمال سجل العمليات غير المعتادة',
       'Reconcile the register against detected events (e.g. every early repayment meeting the criteria is '
       'logged).',
       'aml', 'mlro', 'weekly', 'critical'),
    _c('FRA-036', 'aml_cft', 'W', 'Each unusual transaction studied and documented',
       'دراسة وتوثيق كل عملية غير معتادة',
       'SLA to study; required analysis, decision (STR / no STR) and documents.',
       'aml', 'mlro', 'weekly', 'critical', ['aml.unusual_txn_study_sla_days']),
    _c('FRA-037', 'aml_cft', 'W', 'Red flags from internal audit studied',
       'دراسة المؤشرات التي ترصدها المراجعة الداخلية',
       'Internal-audit findings tagged as AML indicators automatically open AML cases.',
       'internal_audit', 'mlro', 'event', 'high'),
    _c('FRA-038', 'aml_cft', 'A', 'KYC: gender recorded', 'اعرف عميلك: تسجيل النوع',
       'Mandatory-field rule (gender) with a completeness score per file; an incomplete file blocks onboarding.',
       'ekyc', 'mlro', 'daily', 'medium'),
    _c('FRA-039', 'aml_cft', 'A', 'KYC: nationality / nationalities recorded', 'اعرف عميلك: تسجيل الجنسية/الجنسيات',
       'Mandatory-field rule (all nationalities) with a completeness score per file; an incomplete file blocks '
       'onboarding.',
       'ekyc', 'mlro', 'daily', 'medium'),
    _c('FRA-040', 'aml_cft', 'A', 'KYC: country of residence recorded', 'اعرف عميلك: تسجيل بلد الإقامة',
       'Mandatory-field rule (residence) with a completeness score per file; an incomplete file blocks '
       'onboarding.',
       'ekyc', 'mlro', 'daily', 'medium'),
    _c('FRA-041', 'aml_cft', 'A', 'KYC: address recorded', 'اعرف عميلك: تسجيل العنوان',
       'Mandatory-field rule (address) with a completeness score per file; an incomplete file blocks '
       'onboarding.',
       'ekyc', 'mlro', 'daily', 'medium'),
    _c('FRA-042', 'aml_cft', 'A', 'KYC: identity document type recorded', 'اعرف عميلك: تسجيل نوع مستند الهوية',
       'Mandatory-field rule (ID document type) with a completeness score per file; an incomplete file blocks '
       'onboarding.',
       'ekyc', 'mlro', 'daily', 'medium'),
    _c('FRA-043', 'aml_cft', 'A', 'KYB: tax card number and issuing office', 'اعرف عميلك للشركات: رقم البطاقة الضريبية وجهة إصدارها',
       'Mandatory KYB fields: tax card number and issuing tax office.',
       'merchant_kyc', 'mlro', 'daily', 'medium'),
    _c('FRA-044', 'aml_cft', 'A', 'KYB: senior management names', 'اعرف عميلك للشركات: أسماء الإدارة العليا',
       'Mandatory KYB field: names of senior management.',
       'merchant_kyc', 'mlro', 'daily', 'medium'),
    _c('FRA-045', 'aml_cft', 'A', 'KYB: beneficial owners identified', 'اعرف عميلك للشركات: تحديد المستفيدين الحقيقيين',
       'Mandatory KYB field: beneficial owners with the ownership structure.',
       'merchant_kyc', 'mlro', 'daily', 'critical'),
    _c('FRA-046', 'aml_cft', 'W', 'Beneficial-owner declaration by the client', 'إقرار العميل بالمستفيد الحقيقي',
       'Signed declaration (self or a named other beneficial owner) required.',
       'ekyc', 'mlro', 'daily', 'high'),
    _c('FRA-047', 'aml_cft', 'A', 'KYC refreshed according to risk level', 'تحديث بيانات العملاء حسب درجة المخاطر',
       'Review cycle per risk band; overdue list.',
       'parties', 'mlro', 'weekly', 'high',
       ['kyc.refresh_months_high', 'kyc.refresh_months_medium', 'kyc.refresh_months_low']),
    _c('FRA-048', 'aml_cft', 'A', 'Adequate, multi-factor risk-rating basis', 'أساس متعدد العوامل لتصنيف المخاطر',
       'Configurable risk model (customer, geography, product, channel, PEP, behaviour).',
       'aml', 'mlro', 'annual', 'high'),
    _c('FRA-049', 'aml_cft', 'A', 'Risk rating at onboarding and during the relationship', 'تصنيف المخاطر عند بدء العلاقة وخلالها',
       'Rating mandatory before approval; re-rating on triggers; never only after exit.',
       'aml', 'mlro', 'daily', 'high'),
    _c('FRA-050', 'aml_cft', 'W', 'EDD applied to high-risk clients', 'تطبيق العناية الواجبة المعززة على العملاء مرتفعي المخاطر',
       'High risk requires an EDD checklist and a senior-approval gate.',
       'aml', 'mlro', 'daily', 'critical'),
    _c('FRA-051', 'aml_cft', 'E/A', 'Off-site secured backup of records', 'نسخ احتياطي مؤمن للسجلات خارج الموقع',
       'Backup evidence register; system backup status (last successful off-site backup).',
       'cyber', 'it_head', 'monthly', 'high', ['it.offsite_backup_max_age_days']),
    _c('FRA-052', 'aml_cft', 'A', 'Employees screened against watchlists', 'فحص العاملين على قوائم الحظر',
       'Employee screening at onboarding and periodically.',
       'screening', 'hr_head', 'monthly', 'high', ['aml.employee_rescreen_months']),
    _c('FRA-053', 'aml_cft', 'W', 'Board approval of the annual MLRO report', 'اعتماد مجلس الإدارة للتقرير السنوي لمسؤول الإبلاغ',
       'Annual report generation with a board approval record.',
       'aml', 'mlro', 'annual', 'high'),
    _c('FRA-054', 'aml_cft', 'M', 'Internal audit scope covers regulatory findings', 'شمول نطاق المراجعة الداخلية للملاحظات الرقابية',
       'Coverage matrix: audit plan vs control library; gaps flagged.',
       'internal_audit', 'internal_audit_head', 'annual', 'medium'),
    _c('OBS-01', 'aml_cft', 'M', 'AML training coverage of all staff', 'تغطية جميع العاملين ببرامج تدريب مكافحة غسل الأموال',
       'Training coverage KPI by department against the target.',
       'training', 'mlro', 'quarterly', 'medium', ['training.aml_coverage_target_pct']),
    # ---------------------------------------------------------------- 5
    _c('FRA-055', 'financial_reporting', 'E', 'Proper accounting information system', 'نظام معلومات محاسبي ملائم',
       'Financial-controls checklist showing the books are kept on an accounting system, not spreadsheets.',
       'prudential', 'cfo', 'annual', 'medium'),
    _c('FRA-056', 'financial_reporting', 'E/A', 'Recent balance confirmations for borrowings', 'مصادقات حديثة على أرصدة القروض والتسهيلات',
       'Confirmations register (counterparty, balance, confirmation date); stale confirmations alert.',
       'prudential', 'cfo', 'quarterly', 'high', ['finance.balance_confirmation_max_age_days']),
    _c('FRA-057', 'financial_reporting', 'A/E', 'Accrued interest calculated on all facilities', 'احتساب الفوائد المستحقة على جميع التسهيلات',
       'Facility register with rate; expected accrual calculated per facility.',
       'prudential', 'cfo', 'quarterly', 'high'),
    _c('FRA-058', 'financial_reporting', 'A/E', 'Accrued interest booked in the accounts', 'إثبات الفوائد المستحقة بالدفاتر',
       'Expected accrual vs booked accrual check per facility.',
       'prudential', 'cfo', 'quarterly', 'high', ['finance.accrual_tolerance_pct']),
    _c('FRA-059', 'financial_reporting', 'M/W', 'Defaults on lender balances monitored', 'متابعة التعثر في سداد أرصدة الجهات المقرضة',
       'Facility status and covenants tracked; defaults escalated to the board.',
       'prudential', 'cfo', 'monthly', 'high'),
    _c('FRA-060', 'financial_reporting', 'M/W', 'Lender reschedulings tracked', 'متابعة إعادة جدولة المديونيات مع الجهات المقرضة',
       'Rescheduling tracker per facility with board escalation.',
       'prudential', 'cfo', 'monthly', 'medium'),
    _c('FRA-061', 'financial_reporting', 'E', "Exiting shareholders' dues classified as liabilities", 'تبويب مستحقات المساهمين المتخارجين ضمن الالتزامات',
       'Review checklist item with evidence.',
       'prudential', 'cfo', 'annual', 'medium'),
    _c('FRA-062', 'financial_reporting', 'W/E', 'Capital contributions attributed to the right party', 'نسب مساهمات رأس المال إلى الطرف الصحيح',
       'Related-party register; contribution evidence required; payer mismatch flagged.',
       'prudential', 'cfo', 'annual', 'high'),
    _c('FRA-063', 'financial_reporting', 'W/E', 'Related-party balances supported by documents', 'تأييد أرصدة الأطراف ذات العلاقة بالمستندات',
       'Related-party balances attributed to the right party with supporting documents.',
       'prudential', 'cfo', 'quarterly', 'high'),
    _c('FRA-064', 'financial_reporting', 'E', 'Deferred tax asset recoverability supported', 'تأييد قابلية استرداد الأصول الضريبية المؤجلة',
       'Evidence item (recoverability study) with a due date.',
       'prudential', 'cfo', 'annual', 'medium'),
    _c('FRA-065', 'financial_reporting', 'E', 'Auditor certificate for deferred tax assets', 'شهادة مراقب الحسابات عن الأصول الضريبية المؤجلة',
       'Evidence item (auditor certificate) with a due date.',
       'prudential', 'cfo', 'annual', 'medium'),
    _c('FRA-066', 'financial_reporting', 'E/W', 'Approved ECL study', 'دراسة معتمدة للخسائر الائتمانية المتوقعة',
       'ECL study status, approval and refresh frequency.',
       'prudential', 'cfo', 'annual', 'high', ['finance.ecl_refresh_months']),
    # ---------------------------------------------------------------- 6
    _c('FRA-067', 'it_cyber', 'E', 'Backup / DR site for business continuity', 'موقع بديل لاستمرارية الأعمال',
       'BCP/DR register with the last DR test date.',
       'cyber', 'it_head', 'annual', 'high', ['it.dr_test_max_age_months']),
    _c('FRA-068', 'it_cyber', 'E/A', 'Collection system linked to EMLCU for freeze-order checks', 'ربط نظام التحصيل إلكترونيًا بوحدة مكافحة غسل الأموال لفحص قرارات التجميد',
       'Integration status evidence; collection counterparties screened against freeze orders.',
       'screening', 'it_head', 'monthly', 'critical'),
    _c('FRA-069', 'it_cyber', 'E', 'Recent penetration and malware test', 'اختبار اختراق وفحص برمجيات خبيثة حديث',
       'Evidence from a qualified provider with a validity period.',
       'cyber', 'ciso', 'annual', 'high'),
    _c('FRA-070', 'it_cyber', 'E', 'WAF in place with active licences', 'جدار حماية تطبيقات الويب بتراخيص سارية',
       'Asset/licence register with expiry.',
       'cyber', 'ciso', 'annual', 'medium'),
    _c('FRA-071', 'it_cyber', 'E', 'Effective EPP/EDR; no sensitive data sent abroad', 'فعالية حماية الأجهزة الطرفية وعدم إرسال بيانات حساسة للخارج',
       'Licence evidence plus a data-residency attestation.',
       'cyber', 'ciso', 'annual', 'high'),
    _c('FRA-072', 'it_cyber', 'A', 'Valid SSL certificates', 'شهادات SSL سارية',
       'Automatic certificate expiry check for the declared domains.',
       'cyber', 'it_head', 'daily', 'medium', ['it.ssl_expiry_warning_days']),
    _c('FRA-073', 'it_cyber', 'E', 'Detailed CIS benchmark report', 'تقرير تفصيلي لمعايير CIS',
       'Evidence with a date.',
       'cyber', 'ciso', 'annual', 'medium'),
    _c('FRA-074', 'it_cyber', 'W', 'Board-approved information-security policies', 'سياسات أمن المعلومات معتمدة من المجلس',
       'Policies module record with board approval.',
       'policies', 'ciso', 'annual', 'high'),
    _c('FRA-075', 'it_cyber', 'E/M', 'IT governance framework aligned to FRA requirements', 'إطار حوكمة تكنولوجيا المعلومات متوافق مع متطلبات الهيئة',
       'Framework mapping and maturity self-assessment (IT governance).',
       'cyber', 'it_head', 'annual', 'medium'),
    _c('FRA-076', 'it_cyber', 'E/M', 'IT risk management framework aligned to FRA requirements', 'إطار إدارة مخاطر تكنولوجيا المعلومات متوافق مع متطلبات الهيئة',
       'Framework mapping and maturity self-assessment (IT risk).',
       'cyber', 'cro', 'annual', 'medium'),
    _c('FRA-077', 'it_cyber', 'E/M', 'Cybersecurity framework aligned to FRA requirements', 'إطار الأمن السيبراني متوافق مع متطلبات الهيئة',
       'Framework mapping and maturity self-assessment (cybersecurity).',
       'cyber', 'ciso', 'annual', 'medium'),
    _c('FRA-078', 'it_cyber', 'A/M', 'Updated IT risk register', 'سجل محدث لمخاطر تكنولوجيا المعلومات',
       'IT risks inside the ERM risk register; staleness alert.',
       'risk_management', 'cro', 'quarterly', 'medium', ['it.risk_register_max_age_days']),
    # ---------------------------------------------------------------- 7
    _c('FRA-079', 'remediation', 'W/A', 'Prior findings remediated and not repeated', 'معالجة الملاحظات السابقة وعدم تكرارها',
       'Inspection findings tracker: import findings, corrective-action plans, owners, deadlines, evidence, '
       'verification re-test, recurrence detection (same control failing again), board reporting.',
       'regcontrols', 'compliance_head', 'weekly', 'critical',
       ['rc.finding_overdue_grace_days']),
]


# --------------------------------------------------------------------------
# Parameter seed
# --------------------------------------------------------------------------
# value None = "not configured yet" — get_param() raises ParameterNotSet, so a
# check that needs it records an error instead of silently passing.

TODO = 'TODO(compliance-review): confirm the value and legal reference before relying on this parameter.'


def _p(key, value, value_type, unit, desc_en, desc_ar, legal_ref, needs_review=True,
       licence='all', note=None):
    return {
        'key': key, 'licence_type': licence, 'value': value, 'value_type': value_type, 'unit': unit,
        'description_en': desc_en, 'description_ar': desc_ar, 'legal_reference': legal_ref,
        'needs_review': needs_review, 'review_note': note if note is not None else (TODO if needs_review else None),
    }


PARAMETERS = [
    # --- capital & solvency (FRA-001..003) ---
    _p('capital.min_paid_up', None, 'amount', 'EGP', 'Minimum paid-up capital for a microfinance licence',
       'الحد الأدنى لرأس المال المدفوع لترخيص التمويل متناهي الصغر',
       'Microfinance Law 141/2014 and FRA executive decrees', licence='microfinance'),
    _p('capital.min_paid_up', None, 'amount', 'EGP', 'Minimum paid-up capital for a consumer-finance licence',
       'الحد الأدنى لرأس المال المدفوع لترخيص التمويل الاستهلاكي',
       'Consumer Finance Law 18/2020 and FRA executive decrees', licence='consumer_finance'),
    _p('capital.min_paid_up', None, 'amount', 'EGP', 'Minimum paid-up capital for a financial-leasing licence',
       'الحد الأدنى لرأس المال المدفوع لترخيص التأجير التمويلي',
       'Financial Leasing and Factoring Law 176/2018 and FRA executive decrees', licence='leasing'),
    _p('capital.min_paid_up', None, 'amount', 'EGP', 'Minimum paid-up capital for a factoring licence',
       'الحد الأدنى لرأس المال المدفوع لترخيص التخصيم',
       'Financial Leasing and Factoring Law 176/2018 and FRA executive decrees', licence='factoring'),
    _p('capital.deadline_alert_days', '[60, 30, 7]', 'json', 'days',
       'Days before a regulatory deadline when countdown alerts are sent',
       'الأيام السابقة للموعد الرقابي التي ترسل فيها تنبيهات العد التنازلي',
       'FRA control map FRA-002 (internal alerting policy)', needs_review=False),
    _p('solvency.max_leverage_ratio', None, 'number', 'x', 'Maximum leverage (liabilities to equity)',
       'الحد الأقصى للرافعة المالية (الالتزامات إلى حقوق الملكية)', 'FRA solvency decrees'),
    _p('solvency.min_equity', '0', 'amount', 'EGP', 'Minimum equity (negative equity is a critical breach)',
       'الحد الأدنى لحقوق الملكية (حقوق الملكية السالبة مخالفة حرجة)', 'FRA solvency decrees'),
    # --- lending conduct (FRA-004, 010-026) ---
    _p('lending.max_client_monthly_revenue', None, 'amount', 'EGP',
       'Maximum client monthly revenue for a microfinance client',
       'الحد الأقصى لإيرادات العميل الشهرية لعميل التمويل متناهي الصغر',
       'Microfinance Law 141/2014 and FRA decrees', licence='microfinance'),
    _p('lending.max_project_size', None, 'amount', 'EGP', 'Maximum project size for a microfinance client',
       'الحد الأقصى لحجم مشروع عميل التمويل متناهي الصغر',
       'Microfinance Law 141/2014 and FRA decrees', licence='microfinance'),
    _p('lending.gps_mandatory_min_amount', None, 'amount', 'EGP',
       'Financing amount above which project GPS coordinates are mandatory',
       'مبلغ التمويل الذي يصبح فوقه تسجيل إحداثيات المشروع إلزاميًا', 'FRA decrees on client files'),
    _p('lending.followup_visit_days', None, 'integer', 'days', 'Days after disbursement by which a follow-up visit is due',
       'عدد الأيام بعد الصرف التي يجب خلالها إجراء زيارة متابعة', 'FRA decrees on portfolio follow-up'),
    _p('portfolio.par30_threshold_pct', None, 'percent', '%', 'PAR30 threshold that triggers a remediation plan',
       'نسبة المحفظة المعرضة للخطر لأكثر من 30 يومًا التي تستوجب خطة علاج', 'FRA decrees / internal risk appetite'),
    _p('lending.max_dsr_pct', None, 'percent', '%', 'Maximum debt-service ratio in the credit study',
       'الحد الأقصى لنسبة عبء الدين في الدراسة الائتمانية', 'FRA decrees / credit policy'),
    _p('lending.min_cost_lines', None, 'integer', 'lines', 'Minimum cost lines in a credit study',
       'الحد الأدنى لبنود التكاليف في الدراسة الائتمانية', 'Credit policy'),
    _p('lending.admin_fee_cap_pct', None, 'percent', '%', 'Administrative fee cap as a percentage of financing',
       'الحد الأقصى للمصروفات الإدارية كنسبة من التمويل', 'FRA decrees on fees'),
    _p('lending.admin_fee_tiers', None, 'json', None, 'Administrative fee tiers by financing bracket',
       'شرائح المصروفات الإدارية حسب قيمة التمويل', 'FRA decrees on fees'),
    _p('lending.late_penalty_rate_pct', None, 'percent', '%', 'Late-payment penalty rate',
       'معدل غرامة التأخير', 'FRA decrees on penalties'),
    _p('lending.late_penalty_cap_pct', None, 'percent', '%', 'Late-payment penalty cap',
       'الحد الأقصى لغرامة التأخير', 'FRA decrees on penalties'),
    _p('lending.transfer_fee_cap', None, 'amount', 'EGP', 'Instalment transfer fee cap',
       'الحد الأقصى لرسوم نقل الأقساط', 'FRA decrees on fees'),
    _p('lending.rescheduling_fee_cap', None, 'amount', 'EGP', 'Rescheduling fee cap',
       'الحد الأقصى لرسوم إعادة الجدولة', 'FRA decrees on fees'),
    _p('lending.prepay_new_loan_window_days', None, 'integer', 'days',
       'Window after an early repayment in which a new costlier loan is flagged',
       'المدة بعد السداد المعجل التي يتم خلالها رصد تمويل جديد أعلى تكلفة', 'FRA control map FRA-023'),
    # --- AML/CFT (FRA-030..054, OBS-01) ---
    _p('policy.max_days_pending_board_approval', None, 'integer', 'days',
       'Days a drafted policy may wait for board approval before an alert',
       'عدد الأيام التي يمكن أن تنتظرها السياسة المعدة قبل اعتماد المجلس قبل التنبيه', 'Internal governance policy'),
    _p('aml.watchlist_freshness_max_hours', None, 'integer', 'hours', 'Maximum age of a watchlist source since last sync',
       'الحد الأقصى لعمر مصدر قوائم الحظر منذ آخر تحديث', 'AML Law 80/2002 and EMLCU instructions'),
    _p('aml.screening_min_recall_pct', '100', 'percent', '%', 'Minimum recall of the screening QA test set',
       'الحد الأدنى لنسبة الاسترجاع في اختبار جودة الفحص', 'FRA control map FRA-034 (any miss is a failure)'),
    _p('aml.unusual_txn_study_sla_days', None, 'integer', 'days', 'Days to study an unusual transaction',
       'عدد الأيام لدراسة عملية غير معتادة', 'AML Law 80/2002 and EMLCU instructions'),
    _p('kyc.refresh_months_high', None, 'integer', 'months', 'KYC refresh cycle for high-risk clients',
       'دورة تحديث بيانات العملاء مرتفعي المخاطر', 'EMLCU KYC rules for NBFIs'),
    _p('kyc.refresh_months_medium', None, 'integer', 'months', 'KYC refresh cycle for medium-risk clients',
       'دورة تحديث بيانات العملاء متوسطي المخاطر', 'EMLCU KYC rules for NBFIs'),
    _p('kyc.refresh_months_low', None, 'integer', 'months', 'KYC refresh cycle for low-risk clients',
       'دورة تحديث بيانات العملاء منخفضي المخاطر', 'EMLCU KYC rules for NBFIs'),
    _p('aml.employee_rescreen_months', None, 'integer', 'months', 'Employee re-screening cycle',
       'دورة إعادة فحص العاملين', 'Internal AML policy'),
    _p('training.aml_coverage_target_pct', '100', 'percent', '%', 'AML training coverage target per department',
       'المستهدف لتغطية تدريب مكافحة غسل الأموال لكل إدارة', 'FRA control map OBS-01'),
    # --- financial reporting & IT (FRA-051, 056-078) ---
    _p('finance.balance_confirmation_max_age_days', None, 'integer', 'days',
       'Maximum age of a lender balance confirmation', 'الحد الأقصى لعمر مصادقة رصيد الجهة المقرضة',
       'External audit practice / FRA inspection'),
    _p('finance.accrual_tolerance_pct', None, 'percent', '%', 'Tolerance between expected and booked accrued interest',
       'هامش السماح بين الفوائد المستحقة المتوقعة والمثبتة', 'Internal finance policy'),
    _p('finance.ecl_refresh_months', None, 'integer', 'months', 'ECL study refresh frequency',
       'دورية تحديث دراسة الخسائر الائتمانية المتوقعة', 'Egyptian Accounting Standard 47 / FRA decrees'),
    _p('it.offsite_backup_max_age_days', None, 'integer', 'days', 'Maximum age of the last successful off-site backup',
       'الحد الأقصى لعمر آخر نسخة احتياطية ناجحة خارج الموقع', 'FRA IT / cybersecurity requirements'),
    _p('it.dr_test_max_age_months', None, 'integer', 'months', 'Maximum age of the last DR test',
       'الحد الأقصى لعمر آخر اختبار للموقع البديل', 'FRA IT / cybersecurity requirements'),
    _p('it.ssl_expiry_warning_days', '30', 'integer', 'days', 'Days before SSL certificate expiry when an alert is raised',
       'عدد الأيام قبل انتهاء شهادة SSL التي يصدر فيها تنبيه', 'Internal IT policy', needs_review=False),
    _p('it.risk_register_max_age_days', None, 'integer', 'days', 'Days after which an IT risk not reviewed is stale',
       'عدد الأيام التي تعتبر بعدها مخاطر تكنولوجيا المعلومات غير المحدثة متقادمة', 'FRA IT risk requirements'),
    _p('branch.min_loan_officers', None, 'integer', 'staff', 'Minimum loan officers per branch',
       'الحد الأدنى لمسؤولي الائتمان بكل فرع', 'FRA decrees on branches'),
    _p('branch.manager_vacancy_max_days', None, 'integer', 'days', 'Days a branch-manager post may stay vacant',
       'عدد الأيام التي يمكن أن يظل فيها منصب مدير الفرع شاغرًا', 'FRA decrees on branches'),
]
