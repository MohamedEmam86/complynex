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
Core access catalogue: the modules and features of the generic platform, as data.

Each feature lists the endpoints it covers (fnmatch patterns on 'blueprint.function'); ``pair()`` makes a
'view' and a 'create & edit' feature over the same pages, the split taken from each view's own guard.
Endpoints of a module's blueprints that no feature names fall to the module's ``default``.
Optional content packs add their modules from their own manifest (Pack.access_modules) — never here.
"""

from .registry import ADMIN_ROLES, ENDPOINT_RULES, PUBLIC, Feature as F, Module, area, pair, register_module

CO_ROLES = ('admin', 'compliance_officer', 'compliance_manager')

area('screening', 'Screening & sanctions', 'الفحص والعقوبات', 10)
area('aml', 'AML/CFT & monitoring', 'مكافحة غسل الأموال والرقابة', 20)
area('kyc', 'Customers & KYC', 'العملاء واعرف عميلك', 30)
area('governance', 'Governance & conduct', 'الحوكمة والسلوك', 40)
area('risk', 'Risk, audit & controls', 'المخاطر والمراجعة والضوابط', 50)
area('security', 'Security, privacy & complaints', 'الأمن والخصوصية والشكاوى', 60)
area('esg', 'ESG & sustainability', 'الاستدامة والحوكمة البيئية', 70)
area('reporting', 'Regulatory reporting', 'التقارير الرقابية', 80)
area('learning', 'Training & academy', 'التدريب والأكاديمية', 90)
area('general', 'General', 'عام', 95)
area('admin', 'Administration', 'الإدارة', 100)
area('portal', 'Employee portal', 'بوابة الموظفين', 110)
area('packs', 'Content packs', 'حزم المحتوى', 120)


# Public pages (no sign-in): customers, complainants, whistle-blowers and phishing-test recipients.
# They belong to no module; a restricted user is refused them like any other page outside the workspace.
PUBLIC.extend([
    'merchant_kyc.public_kyc_form', 'ekyc.capture_status', 'ekyc.verify', 'ekyc.check_side', 'ekyc.give_consent',
    'ekyc.upload_capture', 'phishing.caught', 'phishing.track_*', 'consumer_protection.public_form',
    'consumer_protection.track_case', 'consumer_protection.submit_complaint', 'whistleblowing.anonymous_info',
    'whistleblowing.public_report', 'whistleblowing.submit_case', 'whistleblowing.track_case',
    'whistleblowing.track_reply',
])

# Views that only redirect to a guarded page of the same module: their old rule is that page's.
ENDPOINT_RULES.update({
    'screening.screening_index': ('perm', 'screening', 'view'),
    'screening.gold_review': ('role', ('admin',)),
    'aml.export_customer_pdf': ('perm', 'aml', 'view'),
    'aml.cft_dashboard': ('perm', 'aml', 'view'),
    'aml.freeze_log_moved': ('perm', 'aml', 'view'),
    'aml.freeze_new_moved': ('perm', 'aml', 'view'),
    'aml.freeze_view_moved': ('perm', 'aml', 'view'),
    'merchant_kyc.dashboard': ('perm', 'aml', 'view'),
    'consumer_protection.edit_complaint': ('perm', 'consumer_protection', 'view'),
    # list refresh of the vessel tables: the platform superadmin only (checked in the view)
    'vessels.updates_check': ('role', ('superadmin',)),
    'vessels.updates_rebuild': ('role', ('superadmin',)),
    'vessels.updates_upload': ('role', ('superadmin',)),
    'vessels.sync_source': ('role', ('superadmin',)),
    # names known for a listed ship before the lists publish them, and the queue of names seen in screenings
    'vessels.names': ('role', ('superadmin',)),
    'vessels.names_decide': ('role', ('superadmin',)),
    'vessels.known_name_add': ('role', ('superadmin',)),
    'vessels.known_name_revoke': ('role', ('superadmin',)),
})


def _vessel(level):
    # vessels_required(): site administrators always, else users.perm_vessels at that level
    return ('any', [('role', ADMIN_ROLES), ('perm', 'vessels', level)])


# ------------------------------------------------------------------ screening
register_module(Module(
    'screening', 'Name screening (sanctions & PEP)', 'فحص الأسماء (العقوبات والأشخاص المعرضين سياسياً)',
    'screening', 'bi-search', blueprints=('screening',), default='screening.name.view',
    landing='screening.manual_screen', order=10,
    desc_en='Screen people and companies against sanctions, PEP and internal lists.',
    desc_ar='فحص الأفراد والشركات مقابل قوائم العقوبات والأشخاص المعرضين سياسياً والقوائم الداخلية.',
    features=[
        F('screening.name.view', 'Dashboard, history & results', 'لوحة الفحص والسجل والنتائج',
          ['screening.dashboard', 'screening.screening_index', 'screening.history', 'screening.screening_history_*',
           'screening.view_result', 'screening.get_task_status', 'screening.reports_dashboard',
           'screening.team_report', 'screening.audit_log', 'screening.view_customer_transactions',
           'screening.kyc_periodic_review', 'screening.match_profile']),
        F('screening.name.screen', 'Screen a name', 'فحص اسم',
          ['screening.manual_screen', 'screening.api_screen_person', 'screening.api_adverse_media',
           'screening.api_screening_stats'], requires=('screening.name.view',), kind='action'),
        F('screening.name.whitelist', 'Whitelist (false-positive memory)', 'القائمة البيضاء (الإيجابيات الكاذبة)',
          ['screening.*whitelist*'], requires=('screening.name.view',), kind='action'),
        F('screening.name.bulk', 'Bulk screening (file upload)', 'الفحص المجمّع (رفع ملف)',
          ['screening.bulk_*'], requires=('screening.name.view',), kind='action'),
        F('screening.name.export', 'Export reports & evidence packs', 'تصدير التقارير وحزم الأدلة',
          ['screening.download_report', 'screening.evidence_pack', 'screening.generate_sar'],
          requires=('screening.name.view',), kind='action', sensitive=True),
        F('screening.name.decide', 'Review & decide hits (true / false match)', 'مراجعة النتائج والبت فيها (تطابق / عدم تطابق)',
          ['screening.alert*', 'screening.alerts_*', 'screening.resolve_hit', 'screening.confirmed_match*',
           'screening.queue_*', 'screening.screening_queue', 'screening.approval*', 'screening.entity_unlink',
           'screening.pep_relation_*'], requires=('screening.name.view',), kind='action'),
    ]))

register_module(Module(
    'screening_lists', 'Watchlists & list sources', 'قوائم الفحص ومصادرها', 'screening', 'bi-list-check',
    blueprints=('pep_api',), default='screening.lists', order=20,
    features=[
        F('screening.lists.admin', 'Upload lists & engine settings', 'رفع القوائم وإعدادات المحرك',
          ['screening.upload_sanctions', 'screening.update_source_url', 'screening.config', 'screening.gold_review',
           'pep_api.get_pep_details'], requires=('screening.lists.view',), kind='admin'),
        *pair('screening.lists', 'List sources, versions & quality', 'مصادر القوائم وإصداراتها وجودتها',
              ['screening.data_sources*', 'screening.list_*', 'screening.view_source_logs', 'screening.manage_urls',
               'screening.get_url_history', 'screening.validate_source_url', 'screening.update_watchlist',
               'screening.upload_source_file', 'screening.quality*', 'screening.drift_report*', 'pep_api.*'],
              manage=('Update & approve', 'تحديث واعتماد')),
    ]))

register_module(Module(
    'internal_lists', 'Internal blacklist & PEP lists', 'القائمة السوداء الداخلية وقوائم المعرضين سياسياً',
    'screening', 'bi-person-x', blueprints=('blacklist',), default='screening.internal', order=30,
    landing='blacklist.index',
    features=[
        F('screening.internal.export', 'Export internal lists', 'تصدير القوائم الداخلية',
          ['blacklist.export', 'screening.export_internal_pep'], requires=('screening.internal.view',), kind='admin'),
        *pair('screening.internal', 'Internal lists', 'القوائم الداخلية', ['blacklist.*']),
    ]))

register_module(Module(
    'ongoing_screening', 'Ongoing screening (re-screening)', 'الفحص المستمر (إعادة الفحص)', 'screening',
    'bi-arrow-repeat', default='screening.ongoing', order=40, landing='screening.ongoing_screening_dashboard',
    features=pair('screening.ongoing', 'Ongoing screening', 'الفحص المستمر',
                  ['screening.ongoing_*', 'screening.risk_criteria'], manage=('Run, decide & configure', 'تشغيل وبت وإعداد'))))

register_module(Module(
    'vessels', 'Vessel screening', 'فحص السفن', 'screening', 'bi-water', blueprints=('vessels',),
    default='vessels.view', landing='vessels.screen', order=50,
    desc_en='Screen ships by name or IMO number against international approved lists.',
    desc_ar='فحص السفن بالاسم أو رقم المنظمة البحرية الدولية مقابل القوائم الدولية المعتمدة.',
    features=[
        F('vessels.view', 'History & results', 'السجل والنتائج',
          ['vessels.index', 'vessels.history', 'vessels.result', 'vessels.result_news', 'vessels.profile'],
          legacy=_vessel('view'), perms=[('vessels', 'view')]),
        F('vessels.screen', 'Screen a vessel', 'فحص سفينة', ['vessels.screen'], legacy=_vessel('view'),
          perms=[('vessels', 'view')], requires=('vessels.view',), kind='action'),
        F('vessels.bulk', 'Bulk vessel screening', 'الفحص المجمّع للسفن',
          ['vessels.bulk', 'vessels.bulk_result', 'vessels.bulk_template'], legacy=_vessel('view'),
          perms=[('vessels', 'edit')], requires=('vessels.view',), kind='action'),
        F('vessels.export', 'Export PDF / Excel', 'تصدير PDF / Excel',
          ['vessels.result_pdf', 'vessels.bulk_csv', 'vessels.bulk_xlsx'], legacy=_vessel('view'),
          perms=[('vessels', 'view')], requires=('vessels.view',), kind='action', sensitive=True),
        F('vessels.decide', 'Decide hits & whitelist', 'البت في النتائج والقائمة البيضاء',
          ['vessels.decide', 'vessels.whitelist', 'vessels.whitelist_revoke'], legacy=_vessel('edit'),
          perms=[('vessels', 'edit')], requires=('vessels.view',), kind='action'),
        F('vessels.team', "See colleagues' screenings, bulk jobs and clearances (team view)",
          'رؤية عمليات فحص الزملاء والملفات الجماعية والاستثناءات (عرض الفريق)', [], legacy=_vessel('edit'), perms=[],
          requires=('vessels.view',), workspace=False,
          hint_en='Without it the user sees only their own screenings. Never given in a restricted workspace.',
          hint_ar='بدونها يرى المستخدم عمليات الفحص الخاصة به فقط. لا تُمنح أبداً في مساحة العمل المقيدة.'),
        F('vessels.flags', 'Flag-risk reference', 'مرجع مخاطر الأعلام', ['vessels.flags'], legacy=_vessel('view'),
          perms=[('vessels', 'view')], requires=('vessels.view',)),
        F('vessels.lists', 'List update status, checks & uploads (platform superadmin)',
          'حالة تحديث القوائم والفحص والرفع (المسؤول الأعلى للمنصة)',
          ['vessels.updates_check', 'vessels.updates_rebuild', 'vessels.updates_upload', 'vessels.sync_source',
           'vessels.names', 'vessels.names_decide', 'vessels.known_name_add', 'vessels.known_name_revoke'],
          legacy=('role', ('superadmin',)), perms=[], kind='admin', platform=True),
        F('vessels.updates', 'List update status & change log', 'حالة تحديث القوائم وسجل التغييرات', ['vessels.updates'],
          legacy=('any', [('role', ('superadmin',)), ('col', 'perm_vessels_db', ('view', 'use', 'edit', 'admin'))]),
          perms=[('vessels_db', 'view')], requires=('vessels.database',), grant_by=('superadmin',), sensitive=True),
        F('vessels.database', 'ComplyNex Vessels Database', 'قاعدة بيانات السفن في ComplyNex',
          ['vessels.database'],
          legacy=('any', [('role', ('superadmin',)), ('col', 'perm_vessels_db', ('view', 'use', 'edit', 'admin'))]),
          perms=[('vessels_db', 'view')], grant_by=('superadmin',), sensitive=True,
          hint_en='Only the platform superadmin can grant it (list data).',
          hint_ar='يمنحها المسؤول الأعلى للمنصة فقط (بيانات القوائم).'),
    ]))

# ------------------------------------------------------------------ AML
register_module(Module(
    'aml', 'AML/CFT', 'مكافحة غسل الأموال وتمويل الإرهاب', 'aml', 'bi-bank', blueprints=('aml', 'parties'),
    default='aml.monitoring', landing='aml.dashboard', order=10,
    features=[
        *pair('aml.customers', 'Customers, CDD/EDD & periodic review', 'العملاء والعناية الواجبة والمراجعة الدورية',
              ['aml.*customer*', 'aml.print_cdd_form', 'aml.periodic_reviews', 'aml.record_periodic_review',
               'aml.ubo_verification', 'aml.high_risk_countries', 'aml.risk_scoring', 'aml.screening',
               'aml.hits_to_act', 'aml.open_case_from_hit', 'parties.*']),
        *pair('aml.str', 'Suspicious transaction reports (STR)', 'تقارير المعاملات المشبوهة', ['aml.sar_*', 'aml.create_sar']),
        *pair('aml.escalations', 'Escalations, employee reports & freezes', 'التصعيدات وبلاغات الموظفين والتجميد',
              ['aml.escalation*', 'aml.employee_report_*', 'aml.freeze_*']),
        *pair('aml.monitoring', 'Transactions, alerts & monitoring rules', 'المعاملات والتنبيهات وقواعد الرقابة',
              ['aml.*']),
    ]))

register_module(Module(
    'cases', 'Case register', 'سجل الحالات', 'aml', 'bi-folder2-open', blueprints=('cases',), default='cases.view',
    order=20, features=[F('cases.view', 'Cross-module case register', 'سجل الحالات لجميع الوحدات', ['cases.*'],
                          legacy=('any', [('role', CO_ROLES), ('perm', 'config', 'admin')]))]))

register_module(Module(
    'amlkyc', 'AML assurance (KYC file, risk model, annual report)', 'ضمان مكافحة غسل الأموال (ملف اعرف عميلك ونموذج المخاطر والتقرير السنوي)',
    'aml', 'bi-clipboard2-check', blueprints=('amlkyc',), default='amlkyc', order=30, landing='amlkyc.dashboard',
    features=pair('amlkyc', 'AML assurance', 'ضمان مكافحة غسل الأموال', ['amlkyc.*'])))

register_module(Module(
    'tracker', 'Declarations tracker', 'متابعة الإقرارات', 'governance', 'bi-kanban', blueprints=('tracker',),
    default='tracker.view', order=90,
    features=[F('tracker.view', 'Declarations tracker & export', 'متابعة الإقرارات والتصدير', ['tracker.*'])]))

# ------------------------------------------------------------------ customers / KYC
register_module(Module(
    'merchant_kyc', 'Merchant KYC / KYB', 'اعرف عميلك للتجار', 'kyc', 'bi-shop', blueprints=('merchant_kyc',),
    default='merchant_kyc', order=10, landing='merchant_kyc.merchant_list',
    features=pair('merchant_kyc', 'Merchants', 'التجار', ['merchant_kyc.*'],
                  manage=('Onboard, approve & screen', 'تسجيل واعتماد وفحص'))))

register_module(Module(
    'ekyc', 'eKYC (remote onboarding)', 'التحقق الإلكتروني من الهوية', 'kyc', 'bi-person-badge', blueprints=('ekyc',),
    default='ekyc', order=20, landing='ekyc.dashboard',
    features=pair('ekyc', 'eKYC sessions & reviews', 'جلسات ومراجعات التحقق الإلكتروني', ['ekyc.*'],
                  manage=('Create, review & decide', 'إنشاء ومراجعة وبت'))))

# ------------------------------------------------------------------ governance & conduct
register_module(Module(
    'governance', 'Corporate governance', 'الحوكمة المؤسسية', 'governance', 'bi-building', blueprints=('governance',),
    default='governance.board', order=10, landing='governance.dashboard',
    features=[
        *pair('governance.meetings', 'Meetings, minutes & resolutions', 'الاجتماعات والمحاضر والقرارات',
              ['governance.*meeting*', 'governance.minutes_*', 'governance.resolution_*', 'governance.record_attendance',
               'governance.action_*', 'governance.report_attendance', 'governance.report_followup', 'governance.register_*']),
        *pair('governance.fit_proper', 'Fit & proper', 'الملاءمة والجدارة', ['governance.*fit_proper*', 'governance.fp_*']),
        *pair('governance.reports', 'Governance reports & disclosures', 'تقارير الحوكمة والإفصاح',
              ['governance.*report*']),
        *pair('governance.compliance', 'Governance compliance & settings', 'الالتزام بالحوكمة والإعدادات',
              ['governance.*compliance*', 'governance.gov_*']),
        *pair('governance.board', 'Board, committees & members', 'المجلس واللجان والأعضاء', ['governance.*']),
    ]))

register_module(Module(
    'policies', 'Policies & procedures', 'السياسات والإجراءات', 'governance', 'bi-journal-text', blueprints=('policies',),
    default='policies.library', order=20, landing='policies.list_policies',
    features=[
        *pair('policies.reviews', 'Review & approval workflow', 'سير المراجعة والاعتماد',
              ['policies.my_reviews', 'policies.review_policy', 'policies.decide_stage', 'policies.submit_for_approval',
               'policies.approve_policy', 'policies.workflow_management']),
        *pair('policies.ack', 'Acknowledgement tracking', 'متابعة الإقرار بالاطلاع',
              ['policies.acknowledgment_dashboard', 'policies.pending_acknowledgment', 'policies.policy_acknowledgments']),
        *pair('policies.gap', 'Gap analysis', 'تحليل الفجوات', ['policies.*gap*']),
        *pair('policies.library', 'Policy library', 'مكتبة السياسات', ['policies.*']),
    ]))

register_module(Module(
    'coi', 'Conflicts of interest (COI)', 'تعارض المصالح', 'governance', 'bi-people', blueprints=('coi',),
    default='coi.mine', order=30, landing='coi.my_declarations',
    features=[
        *pair('coi.campaigns', 'Annual campaigns & reminders', 'الحملات السنوية والتذكيرات',
              ['coi.*campaign*', 'coi.send_reminders']),
        *pair('coi.review', 'Review declarations & mitigation plans', 'مراجعة الإقرارات وخطط المعالجة',
              ['coi.pending_review', 'coi.review_declaration', 'coi.*mitigation*']),
        *pair('coi.mine', 'Own declarations', 'الإقرارات الخاصة', ['coi.*']),
    ]))

register_module(Module(
    'cobec', 'Code of business ethics (COBEC)', 'ميثاق أخلاقيات العمل', 'governance', 'bi-award', blueprints=('cobec',),
    default='cobec.mine', order=40,
    features=[*pair('cobec.review', 'Review & all declarations', 'المراجعة وكل الإقرارات',
                    ['cobec.pending_review', 'cobec.review_declaration', 'cobec.all_declarations']),
              *pair('cobec.mine', 'Own declarations', 'الإقرارات الخاصة', ['cobec.*'])]))

register_module(Module(
    'ghe', 'Gifts & hospitality (GHE)', 'الهدايا والضيافة', 'governance', 'bi-gift', blueprints=('ghe',),
    default='ghe.mine', order=50,
    features=[*pair('ghe.review', 'Approve & all declarations', 'الاعتماد وكل الإقرارات',
                    ['ghe.pending_approval', 'ghe.approve_declaration', 'ghe.reject_declaration',
                     'ghe.request_more_info', 'ghe.list_declarations', 'ghe.api_statistics', 'ghe.download_attachment']),
              *pair('ghe.mine', 'Own declarations', 'الإقرارات الخاصة', ['ghe.*'])]))

register_module(Module(
    'declarations', 'Declaration campaigns', 'حملات الإقرارات', 'governance', 'bi-envelope-paper',
    blueprints=('declarations',), default='declarations', order=60,
    features=pair('declarations', 'Declaration campaigns & reminders', 'حملات الإقرارات والتذكيرات', ['declarations.*'])))

register_module(Module(
    'prudential', 'Prudential registers', 'السجلات الاحترازية', 'governance', 'bi-safe', blueprints=('prudential',),
    default='prudential', order=70, landing='prudential.dashboard',
    features=pair('prudential', 'Capital, solvency, facilities & deadlines', 'رأس المال والملاءة والتسهيلات والمواعيد',
                  ['prudential.*'])))

# ------------------------------------------------------------------ risk, audit, controls
register_module(Module(
    'risk_management', 'Risk management', 'إدارة المخاطر', 'risk', 'bi-exclamation-triangle',
    blueprints=('risk_management',), default='risk.register', order=10, landing='risk_management.dashboard',
    features=[
        *pair('risk.controls', 'Controls & control testing', 'الضوابط واختبارها', ['risk_management.controls_*']),
        *pair('risk.kri', 'Key risk indicators', 'مؤشرات المخاطر الرئيسية', ['risk_management.kris_*']),
        *pair('risk.treatments', 'Risk treatments', 'معالجة المخاطر', ['risk_management.treatment*']),
        *pair('risk.register', 'Risk register, categories & appetite', 'سجل المخاطر والفئات والرغبة في المخاطرة',
              ['risk_management.*']),
    ]))

register_module(Module(
    'internal_audit', 'Internal audit', 'المراجعة الداخلية', 'risk', 'bi-clipboard-data', blueprints=('internal_audit',),
    default='audit.projects', order=20, landing='internal_audit.dashboard',
    features=[
        *pair('audit.plans', 'Audit universe & plans', 'نطاق المراجعة والخطط',
              ['internal_audit.plans*', 'internal_audit.universe*']),
        *pair('audit.findings', 'Findings & remediation', 'الملاحظات والمعالجة', ['internal_audit.finding*']),
        *pair('audit.committee', 'Audit committee reports', 'تقارير لجنة المراجعة', ['internal_audit.committee_report*']),
        *pair('audit.projects', 'Audit projects & working papers', 'مهام المراجعة وأوراق العمل', ['internal_audit.*']),
    ]))

register_module(Module(
    'regcontrols', 'Compliance controls (regulatory library)', 'ضوابط الالتزام (المكتبة الرقابية)', 'risk',
    'bi-ui-checks-grid', blueprints=('regcontrols',), default='regcontrols', order=30, landing='regcontrols.dashboard',
    features=[
        F('regcontrols.admin', 'Approve parameters, edit library & packs', 'اعتماد المعايير وتعديل المكتبة والحزم',
          ['regcontrols.*'], when=('admin',), requires=('regcontrols.view',), kind='admin'),
        *pair('regcontrols', 'Controls, tests, evidence & findings', 'الضوابط والاختبارات والأدلة والملاحظات',
              ['regcontrols.*']),
    ]))

# ------------------------------------------------------------------ security, privacy, complaints
register_module(Module(
    'cyber', 'Cyber security & resilience', 'الأمن السيبراني والمرونة', 'security', 'bi-shield-lock',
    blueprints=('cyber',), default='cyber.incidents', order=10, landing='cyber.dashboard',
    features=[*pair('cyber.resilience', 'Resilience (assets, backups, BCP, maturity)', 'المرونة (الأصول والنسخ الاحتياطي واستمرارية الأعمال والنضج)',
                    ['cyber.res_*']),
              *pair('cyber.incidents', 'Cyber incidents', 'الحوادث السيبرانية', ['cyber.*'])]))

register_module(Module(
    'pdpl', 'Data protection (PDPL)', 'حماية البيانات الشخصية', 'security', 'bi-incognito', blueprints=('dp',),
    default='pdpl.records', order=20, landing='dp.dashboard',
    features=[*pair('pdpl.dsr', 'Data subject requests', 'طلبات أصحاب البيانات', ['dp.*dsr*', 'dp.verify_identity']),
              *pair('pdpl.dpia', 'Impact assessments (DPIA)', 'تقييمات الأثر', ['dp.*dpia*']),
              *pair('pdpl.breach', 'Personal-data breaches', 'خروقات البيانات الشخصية', ['dp.*breach*']),
              *pair('pdpl.records', 'Processing records & consent', 'سجلات المعالجة والموافقات', ['dp.*'])]))

register_module(Module(
    'phishing', 'Phishing awareness', 'التوعية بالتصيد الاحتيالي', 'security', 'bi-envelope-exclamation',
    blueprints=('phishing',), default='phishing', order=30, landing='phishing.dashboard',
    features=pair('phishing', 'Phishing campaigns', 'حملات التصيد الاحتيالي', ['phishing.*'],
                  manage=('Create, authorise & send', 'إنشاء واعتماد وإرسال'))))

register_module(Module(
    'consumer_protection', 'Consumer protection & complaints', 'حماية المستهلك والشكاوى', 'security',
    'bi-chat-square-text', blueprints=('consumer_protection',), default='consumer', order=40,
    landing='consumer_protection.dashboard',
    features=pair('consumer', 'Complaints', 'الشكاوى', ['consumer_protection.*'])))

register_module(Module(
    'whistleblowing', 'Whistleblowing case management', 'إدارة بلاغات المخالفات', 'security', 'bi-megaphone',
    blueprints=('whistleblowing',), default='whistleblowing.cases', order=50, landing='whistleblowing.dashboard',
    features=pair('whistleblowing.cases', 'Whistleblowing cases', 'بلاغات المخالفات', ['whistleblowing.*'],
                  manage=('Investigate, assign & resolve', 'تحقيق وإسناد وإغلاق'))))

# ------------------------------------------------------------------ ESG
register_module(Module(
    'esg', 'ESG management', 'إدارة الاستدامة', 'esg', 'bi-tree', blueprints=('esg',), default='esg', order=10,
    landing='esg.dashboard', features=pair('esg', 'ESG scoring, materiality & disclosures', 'تقييم الاستدامة والأهمية النسبية والإفصاح', ['esg.*'])))

register_module(Module(
    'carbon', 'Carbon footprint', 'البصمة الكربونية', 'esg', 'bi-cloud', blueprints=('carbon',), default='carbon', order=20,
    landing='carbon.dashboard', features=pair('carbon', 'Emissions, factors & reports', 'الانبعاثات والمعاملات والتقارير', ['carbon.*'])))

# ------------------------------------------------------------------ reporting
register_module(Module(
    'reporting', 'Regulatory reports', 'التقارير الرقابية', 'reporting', 'bi-file-earmark-bar-graph',
    blueprints=('reporting',), default='reporting', order=10, landing='reporting.dashboard',
    features=pair('reporting', 'Regulatory reports & calendar', 'التقارير الرقابية والتقويم', ['reporting.*'])))

# ------------------------------------------------------------------ learning
register_module(Module(
    'training', 'Training administration', 'إدارة التدريب', 'learning', 'bi-mortarboard', blueprints=('training',),
    default='training.admin', order=10, landing='training.course_library',
    features=[*pair('training.admin', 'Courses, questions, enrolment & reports', 'الدورات والأسئلة والتسجيل والتقارير',
                    ['training.*'])]))

register_module(Module(
    'academy', 'Academy console', 'لوحة الأكاديمية', 'learning', 'bi-easel', blueprints=('academy_admin',),
    default='academy', order=20, landing='academy_admin.index',
    features=pair('academy', 'Academy courses, learners & certificates', 'دورات الأكاديمية والمتعلمون والشهادات', ['academy_admin.*'])))

# ------------------------------------------------------------------ AI
register_module(Module(
    'ai', 'Compliance copilot (AI)', 'المساعد الذكي للالتزام', 'general', 'bi-stars', blueprints=('ai',),
    default='ai', order=10, landing='ai.home',
    features=[F('ai.admin', 'Copilot settings, intents & playbooks', 'إعدادات المساعد والنوايا وخطط العمل', ['ai.*'],
                when=('admin',), requires=('ai.view',), kind='admin'),
              *pair('ai', 'Compliance copilot', 'المساعد الذكي', ['ai.*'], manage=('Use (submit, confirm, drafts)', 'استخدام (إرسال وتأكيد ومسودات)'))]))

# ------------------------------------------------------------------ general CMS pages
register_module(Module(
    'general', 'General pages', 'صفحات عامة', 'general', 'bi-grid', order=20, surface='shell',
    features=[
        F('general.notifications', 'Notifications', 'الإشعارات',
          ['notifications_list', 'open_notification', 'mark_all_notifications_read']),
        F('general.search', 'Global search', 'البحث العام', ['search']),
        F('general.operations', 'Compliance operations dashboard', 'لوحة عمليات الالتزام', ['compliance_operations'],
          legacy=('role', CO_ROLES)),
        F('general.guides', 'Rating & ESG guides', 'أدلة التقييم والاستدامة', ['guides.*']),
        F('general.attachments', 'Attachments (upload / download)', 'المرفقات (رفع / تنزيل)', ['attachments.*']),
        F('general.support', 'Support requests', 'طلبات الدعم', ['support']),
    ]))

# ------------------------------------------------------------------ administration
register_module(Module(
    'admin', 'Administration', 'الإدارة', 'admin', 'bi-gear', blueprints=('admin', 'events', 'api_admin', 'ops_status'),
    default='admin.settings', order=10,
    features=[
        F('admin.users', 'Users & access rights', 'المستخدمون وصلاحيات الوصول',
          ['admin.list_users', 'admin.add_user', 'admin.edit_user', 'admin.delete_user', 'admin.upload_users',
           'admin.user_mfa', 'admin.mfa_overview', 'admin.unlock_user', 'admin.settings_permissions_matrix',
           'users.list_users', 'users.reset_password', 'users.update_role', 'access.admin_*'],
          legacy=('role', ('admin', 'superadmin')), kind='admin'),
        F('admin.departments', 'Departments', 'الإدارات', ['admin.*department*', 'admin.training_requirements',
                                                           'admin.generate_calendar'],
          legacy=('role', ('admin', 'compliance_officer')), kind='admin'),
        F('admin.audit', 'Audit logs, approvals & access reviews', 'سجلات التدقيق والاعتمادات ومراجعات الوصول',
          ['admin.view_audit_logs', 'admin.audit_chain*', 'admin.access_review*', 'admin.approvals', 'admin.reports',
           'users.user_progress'],
          legacy=('role', CO_ROLES)),
        F('admin.api', 'API clients & webhooks', 'عملاء الواجهة البرمجية والويب هوك', ['api_admin.*'],
          legacy=('role', ('admin',)), kind='admin'),
        F('admin.ops', 'Server operations', 'عمليات الخادم', ['admin.ops_panel', 'admin.terminal', 'admin.run_op',
                                                              'ops_status.*'],
          legacy=('role', ADMIN_ROLES), kind='admin'),
        *pair('admin.settings', 'System settings, organisation & workflows', 'إعدادات النظام والهيكل التنظيمي وسير العمل',
              ['admin.*', 'events.*'], manage=('Change', 'تعديل')),
    ]))

# ------------------------------------------------------------------ employee portal (old rule: every signed-in user)
register_module(Module(
    'portal', 'Employee portal', 'بوابة الموظفين', 'portal', 'bi-house-heart', surface='portal',
    blueprints=('portal',), default='portal.home', order=10, landing='portal.dashboard',
    features=[
        F('portal.home', 'Portal home & my status', 'الصفحة الرئيسية للبوابة وحالتي',
          ['portal.dashboard', 'portal.status', 'portal.thank_you']),
        F('portal.coi', 'Conflict-of-interest declarations', 'إقرارات تعارض المصالح',
          ['portal.annual_coi', 'portal.incident_coi', 'portal.verify_coi_pin', 'portal.respond_coi_clarification'],
          requires=('portal.home',)),
        F('portal.cobec', 'Code of ethics (COBEC) declaration', 'إقرار ميثاق الأخلاقيات', ['portal.annual_cobec'],
          requires=('portal.home',)),
        F('portal.ghe', 'Gifts & hospitality reports', 'الإبلاغ عن الهدايا والضيافة', ['portal.incident_ghe'],
          requires=('portal.home',)),
        F('portal.policies', 'Read & acknowledge policies', 'قراءة السياسات والإقرار بها',
          ['portal.policy_list', 'portal.acknowledge_policy', 'policies.acknowledge_policy', 'policies.acknowledge_all',
           'policies.download_policy_document', 'policies.download_policy_attachment'], requires=('portal.home',)),
        F('portal.learning', 'Learning (my courses & certificates)', 'التعلم (دوراتي وشهاداتي)',
          ['portal.training_list', 'training.view_course', 'training.take_quiz', 'training.heartbeat',
           'training.my_certificates', 'training.course_asset', 'training.download_certificate'],
          requires=('portal.home',)),
        F('portal.suspicion', 'Report suspicious activity', 'الإبلاغ عن نشاط مشبوه',
          ['portal.suspicion_report*'], requires=('portal.home',)),
        F('portal.whistleblowing', 'My whistleblowing reports', 'بلاغاتي عن المخالفات',
          ['whistleblowing.my_cases', 'whistleblowing.my_case_status'], requires=('portal.home',)),
    ]))


# Modules whose pages serve reading and editing on the same URL (the page checks the edit level itself):
# their 'Create & edit' feature grants the edit level of the module instead of separate pages.
def _level_feature(key, module):
    from .registry import MODULES
    for m in MODULES.values():
        for f in m.features:
            if f.key == key:
                f.legacy = ('perm', module, 'edit')
                f.perms = [(module, 'edit')]
                f.hint_en = 'Edits on the same pages (the pages check this level).'
                f.hint_ar = 'التعديل من نفس الصفحات (تتحقق الصفحات من هذا المستوى).'


_level_feature('prudential.manage', 'prudential')
_level_feature('cyber.resilience.manage', 'cyber')
_level_feature('consumer.manage', 'consumer_protection')
