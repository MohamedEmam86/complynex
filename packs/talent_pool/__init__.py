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
Talent pool pack — a public application form for part-time / freelance
consultants and trainers, and the staff register that reviews them.

Generic: the organisation name, intro text, terms and expertise categories
are settings and data (Talent pool > Settings), not code. The public pages
live under /careers/ and can be served on a separate public host.
"""
from regcontrols.api import Pack, register_pack

from . import service as S


def install(db):
    return S.install_defaults(db)


PACK = register_pack(Pack(
    code='talent_pool',
    name_en='Talent pool (consultants & trainers)',
    name_ar='بنك المواهب (الاستشاريون والمدربون)',
    description_en=('Public application form for part-time / project consultants and trainers (e-mail verified by '
                    'a one-time code, CV upload checked for malware patterns), and a staff register to filter by '
                    'expertise, shortlist, contact, rate and export. Access is granted per user.'),
    description_ar=('نموذج تقديم عام للاستشاريين والمدربين بدوام جزئي أو بالمشروع (تأكيد البريد برمز لمرة واحدة، '
                    'وفحص السيرة الذاتية المرفوعة)، وسجل للموظفين للفرز حسب التخصص والاختيار والتواصل والتقييم '
                    'والتصدير. الصلاحية تُمنح لكل مستخدم.'),
    version='1',
    install=install,
    blueprints=['packs.talent_pool.routes:bp', 'packs.talent_pool.public:public_bp'],
    menu_title_en='Talent pool', menu_title_ar='بنك المواهب', menu_icon='bi-person-badge',
    menu=[('talent.index', 'Applicants', 'المتقدمون', 'talent')],
    permissions=[('talent', 'Talent pool (applicants & CVs)', 'بنك المواهب (المتقدمون والسير الذاتية)',
                  ('none', 'view', 'edit', 'admin'))],
))
