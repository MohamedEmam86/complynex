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
FRA NBFI content pack — Egypt Financial Regulatory Authority requirements
for non-bank financial institutions (microfinance, consumer finance, leasing,
factoring).

The first example pack on top of the generic regcontrols core. It installs
DATA only through the core's catalog API (regulator, framework,
requirements, controls, areas, licence types, owner roles, parameters);
sector logic that has no generic home lives inside this package too:
lending/ — the Lending Conduct & Portfolio module (FRA-004, 009–026) with its
checks, sweep, pages and JSON API. Remove the package or disable the pack and the core
keeps working unchanged.
"""

from regcontrols.api import (Pack, catalog, extend_ai_intent, install_ai_playbook_step, install_branch_role,
                             install_integration, install_key_function_type, register_pack)

from . import library as L


def install(db):
    """Idempotent: inserts what is missing and never overwrites UI edits."""
    for code, (en, ar) in L.AREAS.items():
        catalog.install_ref('areas', code, en, ar, pack_code=L.PACK_CODE, db=db)
    for code, (en, ar) in L.OWNER_ROLES.items():
        catalog.install_ref('owner_roles', code, en, ar, pack_code=L.PACK_CODE, db=db)
    regulator_id = catalog.install_regulator(db=db, **L.REGULATOR)
    for code, (en, ar) in L.LICENCE_TYPES.items():
        catalog.install_ref('licence_types', code, en, ar, pack_code=L.PACK_CODE, db=db,
                            regulator_id=regulator_id, jurisdiction='EG')
    fw_id = catalog.install_framework(regulator_id=regulator_id, pack_code=L.PACK_CODE, db=db, **L.FRAMEWORK)
    for n, c in enumerate(L.CONTROLS, start=1):
        req_id = catalog.install_requirement(fw_id, c['code'], c['title_en'], c['title_ar'], text_en=c['requirement_en'],
                                             area_code=c['area'], sort_order=n, db=db)
        catalog.install_control(c, pack_code=L.PACK_CODE, requirement_ids=[req_id], db=db)
    for p in L.PARAMETERS:
        catalog.install_parameter(p, pack_code=L.PACK_CODE, framework_id=fw_id, db=db)
    # FRA-019: responsible-pricing disclosure in the regulatory calendar.
    # TODO(compliance-review): confirm frequency and due day with the FRA decree.
    catalog.install_regulatory_report(
        'FRA-RPD', 'FRA responsible-pricing disclosure', 'quarterly', due_day=15, regulator_id=regulator_id,
        description='Responsible-pricing disclosure forms for financing products (FRA-019). '
                    'Data: Lending > Pricing disclosure.',
        submission_method='FRA portal / letter', responsible_department='Compliance', db=db)
    for f in L.KEY_FUNCTIONS:
        install_key_function_type(pack_code=L.PACK_CODE, db=db, **f)
    for r in L.BRANCH_ROLES:
        install_branch_role(pack_code=L.PACK_CODE, db=db, **r)
    for i in L.INTEGRATIONS:
        install_integration(pack_code=L.PACK_CODE, db=db, **i)
    it_fw = catalog.install_framework(regulator_id=regulator_id, pack_code=L.PACK_CODE, db=db, **L.IT_FRAMEWORK)
    for n, (ref, en, ar) in enumerate(L.IT_REQUIREMENTS, start=1):
        catalog.install_requirement(it_fw, ref, en, ar, area_code='it_cyber', sort_order=n, db=db)
    for playbook_code, step in L.AI_PLAYBOOK_STEPS:
        install_ai_playbook_step(playbook_code, step, pack_code=L.PACK_CODE, db=db)
    for code, ext in L.AI_INTENT_EXTENSIONS:
        extend_ai_intent(code, db=db, **ext)
    db.commit()
    return {'controls': len(L.CONTROLS), 'parameters': len(L.PARAMETERS)}


PACK = register_pack(Pack(
    code=L.PACK_CODE,
    name_en='FRA NBFI pack (Egypt)',
    name_ar='حزمة الهيئة العامة للرقابة المالية للمؤسسات المالية غير المصرفية (مصر)',
    description_en=('Egypt FRA requirements for non-bank financial institutions: 80 requirements and controls '
                    '(capital, licensing, origination, pricing, AML/CFT, financial reporting, IT, remediation) '
                    'and the regulatory parameters they use (values to be confirmed by Compliance).'),
    description_ar=('متطلبات الهيئة العامة للرقابة المالية للمؤسسات المالية غير المصرفية: 80 متطلبًا وضابطًا '
                    '(رأس المال والترخيص ومنح التمويل والتسعير ومكافحة غسل الأموال والتقارير المالية '
                    'وتكنولوجيا المعلومات والمعالجة) والمعايير الرقابية المستخدمة (تؤكد قيمها إدارة الالتزام).'),
    version='7',
    install=install,
    check_modules=['packs.fra_nbfi.lending.checks'],
    blueprints=['packs.fra_nbfi.lending.routes:bp', 'packs.fra_nbfi.lending.api:api_bp'],
    menu_title_en='Lending Conduct & Portfolio', menu_title_ar='سلوكيات التمويل والمحفظة', menu_icon='bi-cash-coin',
    menu=[('lending.dashboard', 'Portfolio', 'المحفظة', 'lending'),
          ('lending.loans', 'Loans', 'التمويلات', 'lending'),
          ('lending.fees', 'Pricing & fees', 'التسعير والرسوم', 'lending'),
          ('lending.qa', 'Credit-study QA', 'جودة الدراسات الائتمانية', 'lending'),
          ('lending.disclosure', 'Pricing disclosure', 'الإفصاح عن التسعير', 'lending'),
          ('lending.import_data', 'Import data', 'استيراد البيانات', 'lending')],
    permissions=[('lending', 'Lending Conduct & Portfolio (FRA NBFI pack)',
                  'سلوكيات التمويل والمحفظة (حزمة الهيئة)', ('none', 'view', 'edit'))],
))

# The lending module attaches files (documents, signed consents) through the
# shared attachments widget.
from attachments.routes import register_module as _register_attachments  # noqa: E402

_register_attachments('lending')
