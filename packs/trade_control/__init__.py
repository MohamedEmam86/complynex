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
    menu=[('dualuse.index', 'Overview & search', 'نظرة عامة وبحث', 'dualuse'),
          ('dualuse.browse', 'Browse catalogue', 'تصفح الفهرس', 'dualuse'),
          ('dualuse.screen', 'Screen a product', 'فحص منتج', 'dualuse'),
          ('dualuse.batch', 'Batch screening', 'الفحص المجمّع', 'dualuse'),
          ('dualuse.screenings', 'Screenings', 'عمليات الفحص', 'dualuse')],
    badges=badges,
    permissions=[('dualuse', 'Dual-use goods screening', 'فحص السلع مزدوجة الاستخدام',
                  ('none', 'view', 'edit', 'admin'))],
    # Per-user features (access/registry.py): each one can be granted on its own.
    access_modules=[{
        'key': 'dualuse', 'label_en': 'Dual-use goods screening', 'label_ar': 'فحص السلع مزدوجة الاستخدام',
        'area': 'screening', 'icon': 'bi-box-seam', 'blueprints': ('dualuse',), 'default': 'dualuse.view',
        'landing': 'dualuse.index', 'order': 60,
        'desc_en': 'Search the dual-use control lists and screen products, invoices and packing lists.',
        'desc_ar': 'البحث في قوائم الرقابة على السلع مزدوجة الاستخدام وفحص المنتجات والفواتير وقوائم التعبئة.',
        'features': [
            {'key': 'dualuse.view', 'label_en': 'Screenings & results', 'label_ar': 'عمليات الفحص ونتائجها',
             'patterns': ['dualuse.screenings', 'dualuse.screening']},
            {'key': 'dualuse.search', 'label_en': 'Search control lists', 'label_ar': 'البحث في قوائم الرقابة',
             'patterns': ['dualuse.index', 'dualuse.api_search', 'dualuse.api_suggest', 'dualuse.entry',
                          'dualuse.chemical', 'dualuse.browse', 'dualuse.browse_category', 'dualuse.guide',
                          'dualuse.api_check']},
            {'key': 'dualuse.screen', 'label_en': 'Screen a product', 'label_ar': 'فحص منتج',
             'patterns': ['dualuse.screen', 'dualuse.line_answers'], 'requires': ('dualuse.view',), 'kind': 'action'},
            {'key': 'dualuse.batch', 'label_en': 'Batch screening (invoices, packing lists)',
             'label_ar': 'الفحص المجمّع (الفواتير وقوائم التعبئة)', 'patterns': ['dualuse.batch*'],
             'requires': ('dualuse.view',), 'kind': 'action'},
            {'key': 'dualuse.decide', 'label_en': 'Decide lines (with reason)', 'label_ar': 'البت في البنود (مع السبب)',
             'patterns': ['dualuse.line_confirm', 'dualuse.line_decide', 'dualuse.line_guidance'],
             'requires': ('dualuse.view',),
             'kind': 'action'},
            {'key': 'dualuse.export', 'label_en': 'Export PDF / Excel and decision memo',
             'label_ar': 'تصدير PDF / Excel ومذكرة القرار', 'patterns': ['dualuse.export_*'], 'requires': ('dualuse.view',), 'kind': 'action',
             'sensitive': True},
            {'key': 'dualuse.team', 'label_en': "See colleagues' screenings (team view)",
             'label_ar': 'رؤية عمليات فحص الزملاء (عرض الفريق)', 'patterns': [], 'perms': [],
             'legacy': ('any', [('role', ('superadmin', 'it_admin')), ('perm', 'dualuse', 'edit')]),
             'requires': ('dualuse.view',), 'workspace': False,
             'hint_en': 'Without it the user sees only their own screenings. Never given in a restricted workspace.',
             'hint_ar': 'بدونها يرى المستخدم عمليات الفحص الخاصة به فقط. لا تُمنح أبداً في مساحة العمل المقيدة.'},
            {'key': 'dualuse.admin', 'label_en': 'Module administration (lists & dictionary)',
             'label_ar': 'إدارة الوحدة (القوائم والقاموس)', 'patterns': ['dualuse.admin'], 'kind': 'admin'},
            # the real list names, versions and the guidance library are shared by every tenant: platform
            # superadmin only (never offered in the matrix, refused to everyone else)
            {'key': 'dualuse.lists', 'label_en': 'List updates & guidance library (platform superadmin)',
             'label_ar': 'تحديثات القوائم ومكتبة الإرشادات (المسؤول الأعلى للمنصة)',
             'patterns': ['dualuse.admin_lists', 'dualuse.admin_check', 'dualuse.admin_upload',
                          'dualuse.admin_version', 'dualuse.admin_guidance', 'dualuse.admin_guidance_edit'],
             'kind': 'admin', 'platform': True},
        ]}],
))
