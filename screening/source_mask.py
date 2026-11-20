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
What a client may see about WHERE a local / internal list entry comes from.

Internal and local lists are loaded from the institution's own files: their category often carries the Excel
sheet or file name (an order reference, a unit name with a date, dataset codes, properties.sheet …). Showing
that tells a client how the institution works. Every user except the platform
superadmin therefore sees a generic, meaningful category instead (owner decision, round 4):

    Egyptian local list – asset-freeze order      قائمة محلية مصرية – أمر تجميد أموال
    Egyptian terrorist list                        قائمة الإرهابيين المصرية
    Egyptian terrorist entities list               قائمة الكيانات الإرهابية المصرية
    UN sanctions committee list                    قائمة لجنة عقوبات مجلس الأمن
    Internal PEP list                              قائمة داخلية للأشخاص المعرضين سياسياً
    Internal list                                  قائمة داخلية

The mapping is data (RULES, keywords in Arabic and English, first match wins). Masking happens at the
presentation layer — result, profile, evidence pack, PDF, exports, API, history, bulk, notifications — with
mask_match() / mask_matches(); stored data is never changed, so the superadmin keeps the real source.
"""
import copy
import json
import re

# (code, keywords, English, Arabic) — first rule whose keyword occurs in the raw category / sheet wins
RULES = [
    ('PEP', ('pep', 'سياسي', 'سياسيا', 'معرض'), 'Internal PEP list', 'قائمة داخلية للأشخاص المعرضين سياسياً'),
    ('UN_COMMITTEE', ('مجلس الأمن', 'مجلس الامن', 'لجنة العقوبات', 'لجنة عقوبات', 'security council', 'sanctions committee',
                      '1267', '1718', '1988', '1373', 'unsc', 'الأمم المتحدة', 'الامم المتحدة'),
     'UN sanctions committee list', 'قائمة لجنة عقوبات مجلس الأمن'),
    ('TERROR_ENTITIES', ('كيانات', 'الكيانات', 'entities', 'organisations', 'organizations'),
     'Egyptian terrorist entities list', 'قائمة الكيانات الإرهابية المصرية'),
    ('TERROR', ('إرهاب', 'ارهاب', 'الإرهابيين', 'الارهابيين', 'terror'), 'Egyptian terrorist list',
     'قائمة الإرهابيين المصرية'),
    ('FREEZE_ORDER', ('النائب العام', 'نائب العام', 'تجميد', 'تحفظ', 'التحفظ', 'أمر', 'امر', 'نيابة', 'prosecutor',
                      'freeze', 'asset-freeze', 'order', 'court', 'محكمة'),
     'Egyptian local list – asset-freeze order', 'قائمة محلية مصرية – أمر تجميد أموال'),
]
DEFAULT = ('INTERNAL', 'Internal list', 'قائمة داخلية')
LABELS = {code: (en, ar) for code, _k, en, ar in RULES}
LABELS[DEFAULT[0]] = DEFAULT[1:]

LOCAL_SOURCES = ('internal', 'emlcu')          # source / dataset prefixes of the institution's own lists
HIDDEN_KEYS = ('sheet', 'sheet_name', 'file', 'file_name', 'filename', 'source_file', 'upload', 'upload_file',
               'batch', 'import_file', 'workbook', 'tab')


def can_see_sources(user=None):
    """Only the platform superadmin sees the real sheet / file / dataset of a local list."""
    if user is None:
        try:
            from flask_login import current_user as user
        except Exception:
            return False
    try:
        return bool(getattr(user, 'is_authenticated', False)) and (getattr(user, 'role', '') or '') == 'superadmin'
    except Exception:
        return False


def _lang(lang=None):
    if lang:
        return str(lang)[:2]
    try:
        from flask_babel import get_locale
        return str(get_locale() or 'en')[:2]
    except Exception:
        return 'en'


def public_code(*raw):
    text = ' '.join(str(r) for r in raw if r).lower()
    for code, keys, _en, _ar in RULES:
        if any(k.lower() in text for k in keys):
            return code
    return DEFAULT[0]


def public_label(code, lang=None):
    en, ar = LABELS.get(code, DEFAULT[1:])
    return ar if _lang(lang) == 'ar' else en


def public_category(*raw, lang=None):
    return public_label(public_code(*raw), lang)


def _as_dict(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip().startswith('{'):
        try:
            d = json.loads(v)
            return d if isinstance(d, dict) else None
        except Exception:
            return None
    return None


def is_local(m):
    src = str(m.get('source') or m.get('list_source') or '').lower()
    ds = str(m.get('dataset') or '').lower()
    return src.startswith(LOCAL_SOURCES) or ds.startswith(LOCAL_SOURCES)


def mask_match(m, user=None, lang=None, force=False):
    """A copy of one hit / listed record that a client may see. Unchanged for the superadmin (unless force)."""
    if not isinstance(m, dict) or (not force and can_see_sources(user)) or not is_local(m):
        return m
    out = copy.copy(m)
    props, det = _as_dict(m.get('properties')) or {}, _as_dict(m.get('details')) or {}
    raw = [m.get('category'), m.get('list_type'), m.get('program'), props.get('sheet'), props.get('program'),
           det.get('category'), det.get('sheet'), m.get('dataset'), m.get('source')]
    code = 'PEP' if str(m.get('list_type') or '').upper() == 'PEP' or 'pep' in str(m.get('source') or '').lower() \
        else public_code(*raw)
    label = public_label(code, lang)
    out['category'] = label
    out['list_category_code'] = code
    if m.get('list_type') not in (None, '') and str(m.get('list_type')).upper() not in ('PEP', 'SANCTIONS', 'TERROR'):
        lt = 'PEP' if code == 'PEP' else 'SANCTIONS'
        out['list_type'] = lt.lower() if str(m.get('list_type')).islower() else lt
    if m.get('program'):
        out['program'] = label
    out['dataset'] = None
    if m.get('source_name'):
        out['source_name'] = label
    for key, d in (('properties', props), ('details', det)):
        if d:
            clean = {k: v for k, v in d.items() if k.lower() not in HIDDEN_KEYS}
            for k in ('category', 'program', 'programs'):
                if k in clean and clean[k]:
                    clean[k] = label
            out[key] = clean if isinstance(m.get(key), dict) else json.dumps(clean, ensure_ascii=False)
    return out


def mask_matches(matches, user=None, lang=None, force=False):
    """Mask a list of hits, including the hits nested in them (grouped hits, cluster members)."""
    if not isinstance(matches, list) or (not force and can_see_sources(user)):
        return matches
    return mask_tree(matches, user, lang, force)


def mask_tree(obj, user=None, lang=None, force=False, _depth=0):
    """Mask every hit inside a stored result / API payload (nested dicts and lists)."""
    if _depth > 6 or (not force and can_see_sources(user)):
        return obj
    if isinstance(obj, list):
        return [mask_tree(x, user, lang, force, _depth + 1) for x in obj]
    if isinstance(obj, dict):
        o = mask_match(obj, user, lang, force) if any(k in obj for k in ('source', 'dataset', 'list_source')) else obj
        if o is obj:
            o = dict(obj)
        for k, v in list(o.items()):
            if isinstance(v, (list, dict)) and k not in ('properties', 'details'):
                o[k] = mask_tree(v, user, lang, force, _depth + 1)
        return o
    return obj


def mask_text(text, user=None):
    """Remove a local list's sheet / file name from free text shown to a client (notifications, exports)."""
    if not text or can_see_sources(user):
        return text
    return re.sub(r'(?i)\b(sheet|file|ورقة|ملف)\s*[:：]\s*[^;,\n|]+', r'\1: —', str(text))
