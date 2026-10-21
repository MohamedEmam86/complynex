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
"""FRA sustainability pack — FRA ESG / TCFD disclosure and carbon-footprint rules.

Installs data only (regulator, framework, requirements, carbon controls, regulatory
parameters with their legal references, the regulatory calendar entries, the FRA
list of verification bodies and the FRA ESG / TCFD disclosure templates). The core
ESG and Carbon modules read it through the parameter registry and their own tables;
disable the pack and they keep working unchanged.
"""
from regcontrols.api import Pack, catalog, register_pack

from . import library as L


def _carbon_controls():
    """Same definitions (and checks) as the FRA NBFI pack — one source, no duplicate controls."""
    try:
        from packs.fra_nbfi import library as NB
        return [c for c in NB.CONTROLS if c['code'] in L.CONTROL_CODES]
    except Exception:
        return []


def _install_disclosure_templates(db):
    """Add the FRA ESG / TCFD template items to every reporting period that lacks them. The old
    summarised 'FRA-107' items are removed only where nobody has started them."""
    periods = db.execute("SELECT id FROM esg_reporting_periods").fetchall()
    added = 0
    for p in periods:
        db.execute("""DELETE FROM esg_disclosure_items
                      WHERE reporting_period_id = %s AND framework = 'FRA-107' AND status = 'not_started'
                        AND owner_id IS NULL AND COALESCE(evidence_notes, '') = '' AND COALESCE(evidence_path, '') = ''""",
                   (p['id'],))
        for fw, ref, t_en, t_ar, r_en, r_ar in L.ESG_TEMPLATE:
            r = db.execute("SELECT 1 FROM esg_disclosure_items WHERE reporting_period_id = %s AND framework = %s "
                           "AND ref_code = %s", (p['id'], fw, ref)).fetchone()
            if r:
                continue
            db.execute("""INSERT INTO esg_disclosure_items (reporting_period_id, framework, ref_code, title, title_ar,
                              requirement, requirement_ar, status)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,'not_started')""", (p['id'], fw, ref, t_en, t_ar, r_en, r_ar))
            added += 1
    return added


def install(db):
    """Idempotent: inserts what is missing and never overwrites UI edits."""
    catalog.install_ref('areas', 'climate', 'Climate & carbon footprint', 'المناخ والبصمة الكربونية',
                        pack_code=L.PACK_CODE, db=db)
    regulator_id = catalog.install_regulator(db=db, **L.REGULATOR)
    fw_id = catalog.install_framework(regulator_id=regulator_id, pack_code=L.PACK_CODE, db=db, **L.FRAMEWORK)
    req_ids = {}
    for n, (ref, en, ar, text_en, legal) in enumerate(L.REQUIREMENTS, start=1):
        req_ids[ref] = catalog.install_requirement(fw_id, ref, en, ar, text_en=text_en, legal_reference=legal,
                                                   area_code=None, sort_order=n, db=db)
    controls = _carbon_controls()
    for c in controls:
        catalog.install_control(c, pack_code=L.PACK_CODE, db=db,
                                requirement_ids=[req_ids[r] for r in L.CONTROL_REQUIREMENTS.get(c['code'], []) if r in req_ids])
    for p in L.PARAMETERS:
        catalog.install_parameter(p, pack_code=L.PACK_CODE, framework_id=fw_id, db=db)
    for code, name, freq, day, month, desc in L.REGULATORY_REPORTS:
        catalog.install_regulatory_report(code, name, freq, due_day=day, due_month=month, description=desc,
                                          regulator_id=regulator_id, submission_method='FRA portal / letter',
                                          responsible_department='Compliance', db=db)
    for name, contact, notes in L.VERIFIERS:
        db.execute("INSERT INTO fra_verifiers (name, contact_info, notes) VALUES (%s,%s,%s) ON CONFLICT (name) DO NOTHING",
                   (name, contact, notes))
    items = _install_disclosure_templates(db)
    db.commit()
    return {'requirements': len(L.REQUIREMENTS), 'controls': len(controls), 'parameters': len(L.PARAMETERS),
            'verifiers': len(L.VERIFIERS), 'disclosure_items_added': items}


PACK = register_pack(Pack(
    code=L.PACK_CODE,
    name_en='FRA sustainability & carbon pack (Egypt)',
    name_ar='حزمة الهيئة العامة للرقابة المالية للاستدامة والبصمة الكربونية (مصر)',
    description_en=('FRA ESG and TCFD disclosure templates (Decrees 107 & 108 of 2021) and the carbon-footprint rules of '
                    'Decisions 36/2026 and 115/2026: thresholds, Scope 1 + 2, VVB verification, 20 per cent offsets within '
                    '90 days, the 31 Dec 2026 first deadline, and the FRA list of verification bodies.'),
    description_ar=('نماذج الإفصاح عن ممارسات الاستدامة وTCFD (القراران 107 و108 لسنة 2021) وقواعد البصمة الكربونية في '
                    'القرارين 36 و115 لسنة 2026: الحدود والنطاقان الأول والثاني والتحقق من جهة معتمدة وتعويض 20% خلال '
                    '90 يومًا وموعد 31 ديسمبر 2026 وقائمة جهات التحقق المعتمدة.'),
    version='1',
    install=install,
    check_modules=[],
))
