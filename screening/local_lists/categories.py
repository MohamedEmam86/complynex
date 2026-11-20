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
Generic display categories of the local negative-lists workbook.

A sheet of the workbook (its name changes with every edition and is internal: superadmin only) is mapped to
ONE of these categories, which is what every user sees on a hit (internal_blacklist.category). The label is
bilingual in one field ("English / عربي") and is worded so that the presentation-layer masking of local
lists (keyword rules: prosecutor / terrorist / entities / security council) maps it to the same generic
class. Nothing here names the institution, the file or the sheet.
"""

# code -> (English, Arabic, default entity type)
CATEGORIES = {
    'EG_FREEZE_ORDER': ('Egyptian asset-freeze order (Public Prosecutor)',
                        'أمر منع من التصرف في الأموال (النائب العام)', 'INDIVIDUAL'),
    'EG_TERROR_PERSONS': ('Egyptian terrorist list', 'قائمة الإرهابيين المصرية', 'INDIVIDUAL'),
    'EG_TERROR_ENTITIES': ('Egyptian terrorist entities list', 'قائمة الكيانات الإرهابية المصرية', 'ENTITY'),
    'UN_DPRK': ('UN Security Council sanctions – DPRK (1718)',
                'عقوبات مجلس الأمن – كوريا الشمالية (1718)', 'INDIVIDUAL'),
    'UN_ISIL_AQ': ("UN Security Council sanctions – ISIL (Da'esh) and Al-Qaida (1267)",
                   'عقوبات مجلس الأمن – داعش والقاعدة (1267)', 'INDIVIDUAL'),
    'UN_TALIBAN': ('UN Security Council sanctions – Taliban (1988)',
                   'عقوبات مجلس الأمن – طالبان (1988)', 'INDIVIDUAL'),
    'UN_IRAN': ('UN Security Council sanctions – Iran', 'عقوبات مجلس الأمن – إيران', 'INDIVIDUAL'),
    'UN_OTHER': ('UN Security Council sanctions', 'عقوبات مجلس الأمن', 'INDIVIDUAL'),
}
ORDER = list(CATEGORIES)

# UN reference prefix (first two letters of e.g. "XXi.001") -> category
UN_PREFIX = {'KP': 'UN_DPRK', 'QD': 'UN_ISIL_AQ', 'QE': 'UN_ISIL_AQ', 'TA': 'UN_TALIBAN', 'TE': 'UN_TALIBAN',
             'IR': 'UN_IRAN'}
# when a UN sheet has no usable reference, its title / header text decides
UN_TITLE_HINTS = (('1718', 'UN_DPRK'), ('كوريا', 'UN_DPRK'), ('القاعدة', 'UN_ISIL_AQ'), ('داعش', 'UN_ISIL_AQ'),
                  ('1267', 'UN_ISIL_AQ'), ('1988', 'UN_TALIBAN'), ('طالبان', 'UN_TALIBAN'), ('ايران', 'UN_IRAN'),
                  ('إيران', 'UN_IRAN'), ('1737', 'UN_IRAN'), ('2231', 'UN_IRAN'))


def label(code, lang=None):
    """'English / عربي' (lang None), or one language."""
    en, ar, _t = CATEGORIES.get(code, CATEGORIES['UN_OTHER'] if str(code).startswith('UN') else
                                ('Local list', 'قائمة محلية', 'INDIVIDUAL'))
    if lang == 'en':
        return en
    if lang == 'ar':
        return ar
    return f'{en} / {ar}'


def code_of_label(text):
    """Category code of a stored category text written by this importer (None for anything else)."""
    t = str(text or '').strip()
    for code in CATEGORIES:
        if t == label(code) or t == label(code, 'en') or t == label(code, 'ar'):
            return code
    return None
