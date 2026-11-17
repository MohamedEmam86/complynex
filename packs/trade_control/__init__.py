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
Trade control pack — dual-use goods screening.

Screens imported (or exported) goods against the international dual-use control lists:
bilingual Arabic / English search over every control entry, a guided single-product
screening (HS code, CAS number, description, technical thresholds) and batch screening
of invoices / packing lists. The user records each decision (clear / hold) with a reason
and a comment. Parties on the transaction go through the sanctions screening service.

Lists are loaded by scripts/dualuse/import_lists.py; Arabic texts by
scripts/dualuse/import_arabic.py. Access is granted per user (module 'dualuse').
"""
from regcontrols.api import Pack, register_pack

from . import service as S


def install(db):
    return S.install_defaults(db)


def badges(user):
    """Sidebar: product lines waiting for a decision."""
    if not user.can_view(S.MODULE):
        return {}
    try:
        n = (S.stats() or {}).get('open_lines') or 0
    except Exception:
        n = 0
    return {'dualuse.screenings': n} if n else {}


PACK = register_pack(Pack(
    code='trade_control',
    name_en='Dual-use goods screening',
    name_ar='فحص السلع مزدوجة الاستخدام',
    description_en=('Screen goods against the international approved dual-use control lists: Arabic / English search '
                    'of every control entry, single-product screening by HS code, CAS number, description and '
                    'technical thresholds, batch screening of invoices and packing lists, decisions with reason and '
                    'comment, and sanctions screening of the parties. Access is granted per user.'),
    description_ar=('فحص السلع مقابل القوائم الدولية المعتمدة للسلع مزدوجة الاستخدام: بحث بالعربية والإنجليزية في كل '
                    'بنود الرقابة، وفحص منتج واحد بكود HS ورقم CAS والوصف والحدود الفنية، وفحص مجمّع للفواتير وقوائم '
                    'التعبئة، وقرارات بسبب وتعليق، وفحص أطراف المعاملة على قوائم العقوبات. الصلاحية تُمنح لكل مستخدم.'),
    version='1',
    install=install,
    blueprints=['packs.trade_control.routes:bp'],
    menu_title_en='Dual-use goods', menu_title_ar='السلع مزدوجة الاستخدام', menu_icon='bi-box-seam',
    menu=[('dualuse.index', 'Search control lists', 'البحث في قوائم الرقابة', 'dualuse'),
          ('dualuse.screen', 'Screen a product', 'فحص منتج', 'dualuse'),
          ('dualuse.batch', 'Batch screening', 'الفحص المجمّع', 'dualuse'),
          ('dualuse.screenings', 'Screenings', 'عمليات الفحص', 'dualuse')],
    badges=badges,
    permissions=[('dualuse', 'Dual-use goods screening', 'فحص السلع مزدوجة الاستخدام',
                  ('none', 'view', 'edit', 'admin'))],
))
