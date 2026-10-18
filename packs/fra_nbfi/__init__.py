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
sector logic that has no generic home (e.g. lending-conduct checks) lives
inside this package too. Remove the package or disable the pack and the core
keeps working unchanged.
"""

from regcontrols.api import Pack, catalog, register_pack

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
    version='1',
    install=install,
))
