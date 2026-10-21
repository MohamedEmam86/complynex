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
"""FRA sustainability pack — DATA only.

Egypt Financial Regulatory Authority (FRA) rules on ESG / climate disclosure and
the carbon footprint of non-bank financial companies. Sources (checked 2026-10-21):
  * FRA Board Decision 36/2026 (28 Jan 2026): annual carbon-footprint report,
    Scope 1 + 2, verified by an FRA-accredited validation & verification body
    (VVB); offset about 20 % of reported emissions with certificates registered
    in the FRA voluntary carbon market database, within 90 days of submission;
    applies to NBFS companies with issued capital or net equity > EGP 100 m.
    https://fra.gov.eg/en/fra_news/ (news of 15 Feb 2026)
  * FRA Board Decision 115/2026: first report deadline moved to 31 Dec 2026
    (amends Art. 1 of 36/2026). https://fra.gov.eg/en/?p=23202911
  * FRA Board Decrees 107 & 108 of 2021: ESG disclosure (listed companies and NBFS
    companies with capital / equity >= EGP 100 m) and TCFD climate disclosure
    (>= EGP 500 m). https://fra.gov.eg/en/?p=13761632
  * FRA disclosure templates as published in the FRA annual reports on ESG and
    TCFD disclosure practices (FY2024): 17 ESG KPIs (B1-B5, C1-C6, H1-H6) and the
    TCFD questions (1a-4b), each answered yes/no with an explanation, attached to
    the board's annual report that accompanies the annual financial statements.
  * FRA list of approved validation and verification bodies (published 2024).
Values that rest on press wording only keep needs_review=True.
"""

PACK_CODE = 'fra_sustainability'

REGULATOR = {'code': 'FRA', 'name_en': 'Financial Regulatory Authority', 'name_ar': 'الهيئة العامة للرقابة المالية',
             'jurisdiction': 'EG', 'website': 'https://fra.gov.eg'}

FRAMEWORK = {
    'code': 'FRA-SUST', 'name_en': 'FRA sustainability, climate and carbon-footprint rules',
    'name_ar': 'قواعد الهيئة العامة للرقابة المالية للاستدامة والمناخ والبصمة الكربونية', 'jurisdiction': 'EG',
    'version': '2026.2',
    'description': 'FRA Board Decisions 36/2026 and 115/2026 (carbon footprint, verification, offsets) and '
                   'FRA Board Decrees 107 & 108 of 2021 (ESG and TCFD disclosure).',
    'source_document': 'https://fra.gov.eg/en/?p=23202911',
}

# (ref, title_en, title_ar, text_en, legal_reference)
REQUIREMENTS = [
    ('FRA-36/2026-REPORT', 'Annual carbon-footprint report (Scope 1 and Scope 2)',
     'تقرير سنوي عن البصمة الكربونية (النطاق الأول والثاني)',
     'Non-banking financial companies with issued capital or net equity above EGP 100 million prepare an annual '
     'carbon-footprint report in tonnes of CO2-equivalent covering Scope 1 and Scope 2 emissions.',
     'FRA Board Decision 36/2026'),
    ('FRA-36/2026-VVB', 'Report verified by an FRA-accredited validation and verification body',
     'التحقق من التقرير من جهة تحقق ومصادقة معتمدة لدى الهيئة',
     'Emission data is audited and verified by a validation and verification body (VVB) accredited by the FRA '
     'before submission.', 'FRA Board Decision 36/2026'),
    ('FRA-36/2026-OFFSET', 'Offset part of the reported emissions within 90 days',
     'تعويض جزء من الانبعاثات المفصح عنها خلال 90 يومًا',
     'About 20 per cent of the reported annual emissions is offset by buying carbon-reduction certificates '
     'registered in the FRA database of the regulated voluntary carbon market, within 90 days of submitting '
     'the report.', 'FRA Board Decision 36/2026'),
    ('FRA-115/2026-DEADLINE', 'First carbon report due by 31 December 2026',
     'تقديم أول تقرير للبصمة الكربونية في موعد أقصاه 31 ديسمبر 2026',
     'The first carbon-footprint report is due by 31 December 2026 (previously 30 June 2026); later reports '
     'follow each company\'s financial year.', 'FRA Board Decision 115/2026 (amends Art. 1 of Decision 36/2026)'),
    ('FRA-ESG-2021', 'Annual ESG disclosure on the FRA template',
     'الإفصاح السنوي عن ممارسات الاستدامة على نموذج الهيئة',
     'Companies listed on the EGX and non-banking financial companies with paid-up capital or net equity of '
     'EGP 100 million or more answer the FRA ESG template (17 indicators) and attach it to the board\'s annual '
     'report that accompanies the annual financial statements.', 'FRA Board Decrees 107 & 108 of 2021'),
    ('FRA-TCFD-2021', 'Annual TCFD climate disclosure on the FRA template',
     'الإفصاح السنوي عن المخاطر المناخية وفق توصيات TCFD على نموذج الهيئة',
     'Companies with paid-up capital or net equity of EGP 500 million or more also answer the FRA TCFD template '
     '(governance, strategy, risk management, metrics and targets).', 'FRA Board Decrees 107 & 108 of 2021'),
]

# Carbon controls: the same codes and checks as the FRA NBFI pack, so enabling both never duplicates them.
CONTROL_CODES = ['FRA-CF-01', 'FRA-CF-02', 'FRA-CF-03', 'FRA-CF-04', 'FRA-CF-05']
CONTROL_REQUIREMENTS = {'FRA-CF-01': ['FRA-36/2026-REPORT', 'FRA-115/2026-DEADLINE'],
                        'FRA-CF-02': ['FRA-36/2026-REPORT'], 'FRA-CF-03': ['FRA-36/2026-REPORT'],
                        'FRA-CF-04': ['FRA-36/2026-VVB'], 'FRA-CF-05': ['FRA-36/2026-OFFSET']}


def _p(key, value, value_type, unit, desc_en, desc_ar, legal_ref, needs_review=False, note=None):
    return {'key': key, 'licence_type': 'all', 'value': value, 'value_type': value_type, 'unit': unit,
            'description_en': desc_en, 'description_ar': desc_ar, 'legal_reference': legal_ref,
            'needs_review': needs_review, 'review_note': note}


PARAMETERS = [
    _p('carbon.report_threshold_egp', '100000000', 'amount', 'EGP',
       'Issued capital or net equity above which the carbon-footprint report and offsets apply',
       'رأس المال المصدر أو صافي حقوق الملكية الذي يسري فوقه تقرير البصمة الكربونية والتعويض',
       'FRA Board Decision 36/2026'),
    _p('carbon.offset_pct', '20', 'percent', '%', 'Share of reported emissions to offset with certificates',
       'نسبة الانبعاثات المفصح عنها الواجب تعويضها بشهادات خفض الانبعاثات', 'FRA Board Decision 36/2026',
       needs_review=True, note='FRA announcement says "approximately 20%": confirm the exact share in the decision text '
                               'published in the Official Gazette.'),
    _p('carbon.offset_deadline_days', '90', 'integer', 'days', 'Days after report submission to buy the offset certificates',
       'عدد الأيام بعد تقديم التقرير لشراء شهادات التعويض', 'FRA Board Decision 36/2026'),
    _p('carbon.first_report_deadline', '2026-12-31', 'date', None, 'Deadline of the first carbon-footprint report',
       'الموعد النهائي لتقديم أول تقرير للبصمة الكربونية',
       'FRA Board Decision 115/2026 (amends Art. 1 of Decision 36/2026)'),
    _p('carbon.scopes_required', '["scope1", "scope2"]', 'json', None, 'Scopes the carbon-footprint report must cover',
       'النطاقات التي يجب أن يغطيها تقرير البصمة الكربونية', 'FRA Board Decision 36/2026'),
    _p('carbon.esg_report_threshold_egp', '100000000', 'amount', 'EGP',
       'Paid-up capital or net equity from which the FRA ESG disclosure applies (NBFS companies; listed companies always)',
       'رأس المال المدفوع أو صافي حقوق الملكية الذي يسري عنده الإفصاح عن ممارسات الاستدامة',
       'FRA Board Decrees 107 & 108 of 2021'),
    _p('carbon.tcfd_threshold_egp', '500000000', 'amount', 'EGP',
       'Paid-up capital or net equity from which the TCFD climate disclosure applies',
       'رأس المال المدفوع أو صافي حقوق الملكية الذي يسري عنده الإفصاح وفق توصيات TCFD',
       'FRA Board Decrees 107 & 108 of 2021'),
    _p('carbon.deadline_alert_days', '[60, 30, 7]', 'json', 'days',
       'Days before a carbon / ESG deadline when reminders are shown', 'الأيام السابقة للموعد التي تظهر فيها التنبيهات',
       'Internal alerting policy'),
    _p('carbon.outlier_pct', '50', 'percent', '%', 'Change vs previous period flagged as an outlier',
       'نسبة التغير عن الفترة السابقة التي تُعد قيمة شاذة', 'Internal data-quality rule'),
]

REGULATORY_REPORTS = [
    ('FRA-CARBON', 'FRA carbon-footprint report (Scope 1 & 2, VVB-verified)', 'annual', 31, 12,
     'Annual carbon-footprint report under FRA Decision 36/2026; first report due 31 Dec 2026 (Decision 115/2026), '
     'later reports aligned with the financial year. Offsets due within 90 days of submission. '
     'Data: Carbon > Regulator submission & offsets.'),
    ('FRA-ESG', 'FRA ESG and TCFD disclosure templates', 'annual', None, None,
     'FRA ESG template (17 indicators) and, from EGP 500 m capital/equity, the TCFD template; attached to the '
     'board annual report that accompanies the annual financial statements (Decrees 107 & 108 of 2021). '
     'Data: ESG > Disclosures (frameworks FRA-ESG and FRA-TCFD).'),
]

# Official FRA ESG template (FY2024 edition): framework code, ref, title_en, title_ar, requirement_en, requirement_ar
ESG_TEMPLATE = [
    ('FRA-ESG', 'E1', 'Environmental operations and oversight', 'العمليات والرقابة البيئية (ب 1)',
     'Environmental policy, environmental risk assessment, waste / water / energy policies, emission-reduction targets, ISO 14001.',
     'السياسة البيئية وتقييم المخاطر البيئية وسياسات المخلفات والمياه والطاقة وأهداف خفض الانبعاثات وشهادة ISO 14001.'),
    ('FRA-ESG', 'E2', 'Carbon emissions', 'انبعاثات الكربون (ب 2)',
     'Annual calculation of the company\'s carbon emissions.', 'حساب انبعاثات الكربون السنوية للشركة.'),
    ('FRA-ESG', 'E3', 'Energy use and energy mix', 'استخدام مصادر الطاقة وتنوعها (ب 3)',
     'Direct energy consumption, consumption by source, energy savings.', 'استهلاك الطاقة المباشر والاستهلاك حسب نوع المصدر ووفورات الطاقة.'),
    ('FRA-ESG', 'E4', 'Water use', 'استخدام المياه (ب 4)',
     'Total water consumed; water recycled and treated.', 'إجمالي المياه المستهلكة والمياه المعاد تدويرها ومعالجتها.'),
    ('FRA-ESG', 'E5', 'Waste management', 'إدارة المخلفات (ب 5)',
     'Waste generated, recycled or treated, by type and weight.', 'المخلفات الناتجة والمعاد تدويرها أو معالجتها حسب النوع والوزن.'),
    ('FRA-ESG', 'S1', 'Gender diversity and pay ratio', 'التنوع بين الجنسين ونسبة الأجور (ج 1)',
     'Gender diversity of the workforce and pay ratio.', 'التنوع بين الجنسين في العاملين ونسبة الأجور.'),
    ('FRA-ESG', 'S2', 'Employee turnover', 'معدل دوران العاملين (ج 2)',
     'Turnover of permanent, temporary and contract / consultant staff.', 'معدل دوران العاملين الدائمين والمؤقتين والمتعاقدين والاستشاريين.'),
    ('FRA-ESG', 'S3', 'Non-discrimination', 'عدم التمييز (ج 3)',
     'Anti-harassment and non-discrimination policy.', 'سياسة مكافحة التحرش وعدم التمييز.'),
    ('FRA-ESG', 'S4', 'Occupational health and safety', 'المعايير العالمية للصحة والسلامة (ج 4)',
     'Health and safety policy, injury counts, safety training hours.', 'سياسة الصحة والسلامة المهنية وعدد الإصابات وساعات التدريب.'),
    ('FRA-ESG', 'S5', 'Child and forced labour', 'الأطفال والعمالة الجبرية (ج 5)',
     'Prohibition of child and forced labour, including suppliers.', 'حظر عمالة الأطفال والعمالة الجبرية بما في ذلك لدى الموردين.'),
    ('FRA-ESG', 'S6', 'Labour rights', 'حقوق العمال (ج 6)',
     'Labour-rights commitments beyond Egyptian labour law, including suppliers.', 'الالتزام بحقوق العمال بما يتجاوز قانون العمل المصري بما في ذلك لدى الموردين.'),
    ('FRA-ESG', 'G1', 'Board diversity', 'تنوع مجلس الإدارة (ح 1)',
     'Board seats and committee chairs by gender.', 'مقاعد مجلس الإدارة ورئاسة اللجان حسب النوع.'),
    ('FRA-ESG', 'G2', 'Anti-bribery and anti-corruption', 'الرشوة ومكافحة الفساد (ح 2)',
     'Anti-bribery and anti-corruption policy and decisions.', 'سياسات وقرارات مكافحة الرشوة والفساد.'),
    ('FRA-ESG', 'G3', 'Ethical conduct and code of conduct', 'السلوك الأخلاقي وميثاق الشرف (ح 3)',
     'Code of conduct and ethics.', 'ميثاق الشرف وقواعد السلوك الأخلاقي.'),
    ('FRA-ESG', 'G4', 'Data privacy', 'خصوصية البيانات (ح 4)',
     'Data-privacy framework beyond Egyptian law.', 'إطار خصوصية البيانات بما يتجاوز القانون المصري.'),
    ('FRA-ESG', 'G5', 'Sustainability reporting and disclosure', 'الإبلاغ عن ممارسات الاستدامة والإفصاح عنها (ح 5)',
     'Sustainability reporting (GRI, SASB, CDP), SDG targets, CSR commitment, community investment.',
     'التقارير وفق المعايير (GRI وSASB وCDP) وأهداف التنمية المستدامة والمسؤولية المجتمعية والاستثمار المجتمعي.'),
    ('FRA-ESG', 'G6', 'External assurance', 'الضمانات الخارجية (ح 6)',
     'Independent third-party review of the ESG disclosures.', 'مراجعة مستقلة من طرف ثالث للإفصاحات.'),
    ('FRA-TCFD', '1a', 'Board oversight of climate-related risks and opportunities', 'رقابة مجلس الإدارة على المخاطر والفرص المتعلقة بالمناخ',
     'Does the board oversee climate-related risks and opportunities?', 'هل يقوم مجلس الإدارة بمراقبة المخاطر والفرص المتعلقة بالمناخ؟'),
    ('FRA-TCFD', '1b', 'Management role in climate-related risks', 'دور الإدارة في المخاطر والفرص المتعلقة بالمناخ',
     'Does management assess and manage climate-related risks and opportunities?', 'هل تقوم إدارة الشركة بأي دور في تقييم المخاطر والفرص المتعلقة بالمناخ وإدارتها؟'),
    ('FRA-TCFD', '2a', 'Climate risks and opportunities by horizon', 'المخاطر والفرص المناخية حسب المدى الزمني',
     'Are climate-related risks and opportunities identified over the short, medium and long term?', 'هل تحدد الشركة أي مخاطر أو فرص متعلقة بالمناخ على المدى القصير والمتوسط والطويل؟'),
    ('FRA-TCFD', '2b', 'Climate in strategy and financial planning', 'إدراج المناخ في الاستراتيجية والتخطيط المالي',
     'Are climate-related risks and opportunities built into strategy and financial planning?', 'هل تقوم الشركة بتضمين الفرص والمخاطر المتعلقة بالمناخ في استراتيجيتها وتخطيطها المالي؟'),
    ('FRA-TCFD', '2c', 'Investment in climate resilience', 'الاستثمار في مقاومة تغير المناخ والتكيف',
     'Does the company invest each year in climate resilience, adaptation and product development?', 'هل تستثمر الشركة سنويًا في البنية التحتية المتعلقة بمقاومة تغيرات المناخ والقدرة على التكيف وتطوير المنتجات؟'),
    ('FRA-TCFD', '3a', 'Identifying and assessing climate risks', 'تحديد المخاطر المناخية وتقييمها',
     'Is there a defined approach to identify and assess climate-related risks?', 'هل وضعت الشركة نهجًا معينًا لتحديد المخاطر المتعلقة بالمناخ وتقييمها؟'),
    ('FRA-TCFD', '3b', 'Managing climate risks', 'إدارة المخاطر المناخية',
     'Is there a clear approach to manage climate-related risks?', 'هل تتبنى الشركة نهجًا واضحًا لإدارة المخاطر المتعلقة بالمناخ؟'),
    ('FRA-TCFD', '3c', 'Climate risk in enterprise risk management', 'دمج المخاطر المناخية في إدارة المخاطر الشاملة',
     'Are climate-related risks integrated into enterprise risk management?', 'هل تدمج الشركة المخاطر المتعلقة بالمناخ ضمن استراتيجيتها الشاملة لإدارة المخاطر؟'),
    ('FRA-TCFD', '4a', 'Climate metrics', 'مقاييس المخاطر والفرص المناخية',
     'Are metrics used to assess climate-related risks and opportunities in line with strategy and risk management?', 'هل تستخدم الشركة أي مقاييس لتقييم المخاطر والفرص المتعلقة بالمناخ بما يتماشى مع استراتيجيتها وعملية إدارة المخاطر؟'),
    ('FRA-TCFD', '4b', 'Scope 1 emissions disclosed', 'الإفصاح عن انبعاثات النطاق الأول',
     'Does the company disclose total Scope 1 CO2 emissions?', 'هل تفصح الشركة عن إجمالي انبعاثات ثاني أكسيد الكربون، النطاق الأول (إن وجد)؟'),
]

# FRA list of approved validation & verification bodies (published 2024). Registrations run one year from
# the registration date: the installation keeps them for reference and Compliance confirms the current list.
VERIFIERS = [
    ('TÜV NORD CERT GmbH', 'Am TÜV 1, 45307 Essen, Germany · info.tncert@tuevnord.de',
     'FRA registration no. 339 of 08/02/2024 (one year). Registries: CDM, Verra, Gold Standard. '
     'Confirm renewal on the current FRA list.'),
    ('TÜV NORD Egypt for Inspection Services', '34 El Riyad St., Mohandessin, Giza · tuvegypt@tuvnord.com',
     'FRA registration no. 340 of 08/02/2024 (one year). Registries: CDM, Verra, Gold Standard. '
     'Confirm renewal on the current FRA list.'),
    ('Center of Organic Agriculture in Egypt (COAE)', '3 Bilbis Desert Road, Cairo · info@coaeegypt.com',
     'FRA registration no. 341 of 08/02/2024 (one year). Registry: Economy of Love (EOL). '
     'Confirm renewal on the current FRA list.'),
]
