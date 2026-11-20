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
The names users see for the lists a subject was screened against (owner decision, round 5): users see which
KIND of list a match came from under ComplyNex's own names, never the data provider, the publisher or a
dataset code. Only the platform superadmin also sees the real source, in a small muted line.

    global_sanctions   aggregated sanctions database      ComplyNex Global Sanctions Lists
    global_pep         aggregated PEP database             ComplyNex Global PEP Database
    internal_pep       the institution's PEP list          ComplyNex PEP List
    local              internal / local lists              ComplyNex Sanctions List  (+ generic sub-label)
    international      official government / UN lists      International sanctions lists
    regulatory         regulatory-measure lists            Regulatory measures lists
    other              anything else                       Screening lists

The names are data: defaults below, overridden by the superadmin on the Sanctions Lists configuration page
(system setting ``screening.list_display_names``, JSON {group: {"en": .., "ar": ..}}). No third-party
trademark is used as a default name. Display only: the engine, scores and stored results never change.
"""
import json
import time

SETTING_KEY = 'screening.list_display_names'

GROUPS = {
    'global_sanctions': ('ComplyNex Global Sanctions Lists', 'قوائم ComplyNex العالمية للعقوبات'),
    'global_pep': ('ComplyNex Global PEP Database', 'قاعدة بيانات ComplyNex العالمية للأشخاص المعرضين سياسياً'),
    'internal_pep': ('ComplyNex PEP List', 'قائمة ComplyNex للأشخاص المعرضين سياسياً'),
    'local': ('ComplyNex Sanctions List', 'قائمة ComplyNex للعقوبات'),
    'international': ('International sanctions lists', 'قوائم العقوبات الدولية'),
    'regulatory': ('Regulatory measures lists', 'قوائم الإجراءات الرقابية'),
    'other': ('Screening lists', 'قوائم الفحص'),
}
GROUP_ORDER = list(GROUPS)
GROUP_HELP = {
    'global_sanctions': 'Aggregated sanctions, terrorism, crime and debarment database',
    'global_pep': 'Aggregated politically exposed persons database',
    'internal_pep': "The institution's own PEP list",
    'local': "The institution's internal and local lists (asset-freeze orders, local terrorist lists …)",
    'international': 'Official government and United Nations sanctions lists',
    'regulatory': 'Lists of regulatory measures',
    'other': 'Any other list',
}

# generic category of a record of an aggregated database (screening/list_category.py codes)
CATEGORY = {
    'SANCTIONS': ('Sanctions', 'عقوبات'),
    'TERROR': ('Terrorism', 'إرهاب'),
    'UNCLASSIFIED': ('Sanctions', 'عقوبات'),
    'SANCTION_LINKED': ('Linked to a sanctioned party', 'مرتبط بجهة معاقبة'),
    'CRIME': ('Criminal or wanted', 'جرائم / مطلوب'),
    'PEP': ('Politically exposed person', 'شخص معرض سياسياً'),
    'EXPORT_CONTROL': ('Export control', 'قيود تصدير'),
    'COUNTER_SANCTIONS': ('Counter-sanctions', 'عقوبات مضادة'),
    'DEBARMENT': ('Debarment', 'حرمان / استبعاد'),
    'REG_ACTION': ('Regulatory action', 'إجراء رقابي'),
    'TRADE_RISK': ('Trade risk', 'مخاطر تجارية'),
    'POI': ('Person of interest', 'شخص محل اهتمام'),
    'CONTEXT': ('Background data', 'بيانات مرجعية'),
}

_INTERNATIONAL = ('ofac', 'ofac_sdn', 'un', 'un_consolidated', 'eu', 'eu_sanctions', 'hmt', 'uk_hmt', 'uk',
                  'ofsi', 'seco', 'dfat', 'canada', 'osfi')
_PEP_DATASETS = ('opensanctions_peps', 'wikidata', 'open_sanctions_pep_eg', 'wikidata_pep_eg')
_CACHE = {'t': 0.0, 'v': None}


def can_see_sources(user=None):
    from screening.source_mask import can_see_sources as _c
    return _c(user)


def _lang(lang=None):
    if lang:
        return str(lang)[:2]
    try:
        from flask_babel import get_locale
        return str(get_locale() or 'en')[:2]
    except Exception:
        return 'en'


def overrides(force=False):
    """{group: {'en': .., 'ar': ..}} configured by the superadmin (cached 30 s per worker)."""
    if not force and _CACHE['v'] is not None and time.time() - _CACHE['t'] < 30:
        return _CACHE['v']
    v = {}
    try:
        from models.settings import Settings
        raw = Settings.get(SETTING_KEY)
        v = json.loads(raw) if raw else {}
        if not isinstance(v, dict):
            v = {}
    except Exception:
        v = {}
    _CACHE.update(t=time.time(), v=v)
    return v


def reset_cache():
    _CACHE.update(t=0.0, v=None)


def group_name(group, lang=None):
    lang = _lang(lang)
    o = (overrides().get(group) or {})
    en, ar = GROUPS.get(group, GROUPS['other'])
    if lang == 'ar':
        return (o.get('ar') or '').strip() or ar
    return (o.get('en') or '').strip() or en


def group_of(source=None, dataset=None, list_type=None):
    s = str(source or '').strip().lower().replace(' ', '_')
    d = str(dataset or '').strip().lower()
    lt = str(list_type or '').strip().upper()
    if s in ('internal_pep',) or (s.startswith('internal') and lt == 'PEP'):
        return 'internal_pep'
    if s.startswith('internal') or s.startswith('emlcu') or s in ('pma_ps', 'pma_ps_national_1373', 'local'):
        return 'local'
    if s.endswith('_reg') or 'regulatory' in s:
        return 'regulatory'
    if s == 'opensanctions_pep' or d in _PEP_DATASETS or 'pep' in s:
        return 'global_pep'
    if s.startswith('opensanctions') or s.startswith('open_sanctions'):
        return 'global_sanctions'
    if s in _INTERNATIONAL or s.startswith(('ofac', 'un_', 'eu_', 'uk_', 'hmt')):
        return 'international'
    return 'other'


def display(source=None, dataset=None, list_type=None, lang=None):
    """Our name for the list a record comes from."""
    return group_name(group_of(source, dataset, list_type), lang)


def category(m, lang=None):
    """A generic sub-label for a hit: the local-list category, or the kind of record of an aggregated
    database. Never a sheet, file, dataset or programme code."""
    lang = _lang(lang)
    m = m or {}
    g = group_of(m.get('source'), m.get('dataset'), m.get('list_type'))
    if g == 'local':
        from screening import source_mask as SM
        code = m.get('list_category_code') or SM.public_code(
            m.get('category'), m.get('list_type'), m.get('program'), m.get('dataset'))
        return SM.public_label(code, lang)
    if g in ('global_sanctions', 'global_pep'):
        try:
            from screening import list_category as LC
            code = LC.for_match(m)
        except Exception:
            code = None
        if code in CATEGORY:
            en, ar = CATEGORY[code]
            return ar if lang == 'ar' else en
    return None


def text_display(text, lang=None):
    """Map a free 'source · dataset' text (e.g. the also-listed-in entries) to our list name."""
    t = str(text or '').lower()
    src = t.split('·')[0].strip()
    if 'opensanctions' in t or 'open sanctions' in t:
        g = 'global_pep' if 'pep' in t else 'global_sanctions'
    elif 'internal' in src and 'pep' in src:
        g = 'internal_pep'
    elif 'internal' in src or 'blacklist' in src or 'emlcu' in src or 'local' in src:
        g = 'local'
    elif any(k in src for k in ('ofac', 'un ', 'united nations', 'security council', 'eu ', 'european', 'hm treasury',
                                'ofsi', 'uk ')) or src in _INTERNATIONAL:
        g = 'international'
    elif 'pep' in src:
        g = 'global_pep'
    else:
        g = group_of(src.replace(' ', '_'))
    return group_name(g, lang)


def coverage_rows(rows, lang=None):
    """'Lists searched' as users see it: one row per list group (records summed, latest update, worst state)."""
    out = {}
    rank = {'red': 0, 'amber': 1, 'yellow': 1, 'green': 2}
    for r in rows or []:
        g = group_of(r.get('source') or r.get('table'), r.get('dataset'))
        if g == 'other' and r.get('table'):
            g = 'internal_pep' if 'pep' in str(r['table']) else 'local'
        o = out.setdefault(g, {'name': group_name(g, lang), 'records': 0, 'updated': None, 'state': 'green',
                               'group': g, 'version': None, 'version_at': None})
        o['records'] += int(r.get('records') or 0)
        if r.get('updated') and (not o['updated'] or str(r['updated']) > str(o['updated'])):
            o['updated'] = r['updated']
        if rank.get(r.get('state'), 2) < rank.get(o['state'], 2):
            o['state'] = r.get('state')
    return sorted(out.values(), key=lambda x: GROUP_ORDER.index(x['group']))


_HIDE = ('source_url', 'url', 'datasets', 'dataset', 'source_name', 'referents', 'source_id')
_HIDE_PROPS = {'source_url', 'sourceurl', 'url', 'datasets', 'dataset', 'source', 'source_name', 'referents',
               'sheet', 'sheet_name', 'file', 'file_name', 'filename', 'publisher', 'programurl', 'program_url'}


def public_hit(m, lang=None):
    """A copy of one raw hit for a client (API, exports): our list name, a generic category, no dataset,
    provider id or official-profile link."""
    if not isinstance(m, dict) or not any(k in m for k in ('source', 'list_source')):
        return m
    src = m.get('source') or m.get('list_source')
    names = {group_name(g, 'en') for g in GROUPS} | {group_name(g, 'ar') for g in GROUPS}
    if str(src) in names:
        return m
    out = {k: v for k, v in m.items() if k not in _HIDE}
    out['source'] = display(src, m.get('dataset'), m.get('list_type'), lang)
    cat = category(m, lang)
    if cat:
        out['category'] = cat
    if isinstance(m.get('also_listed_in'), list):
        seen, also = {out['source']}, []
        for a in m['also_listed_in']:
            n = text_display(a, lang)
            if n not in seen:
                seen.add(n)
                also.append(n)
        out['also_listed_in'] = also
    for key in ('properties', 'details'):
        d = m.get(key)
        if isinstance(d, str) and d.strip().startswith('{'):
            try:
                d = json.loads(d)
            except ValueError:
                d = None
        if isinstance(d, dict):
            out[key] = {k: v for k, v in d.items() if str(k).lower() not in _HIDE_PROPS}
    return out


def public_tree(obj, lang=None, _depth=0):
    if _depth > 6:
        return obj
    if isinstance(obj, list):
        return [public_tree(x, lang, _depth + 1) for x in obj]
    if isinstance(obj, dict):
        o = public_hit(obj, lang)
        o = dict(o)
        for k, v in list(o.items()):
            if isinstance(v, (list, dict)) and k not in ('properties', 'details'):
                o[k] = public_tree(v, lang, _depth + 1)
        return o
    return obj


def save_overrides(values, user_id=None):
    """Store the superadmin's names: {group: {'en', 'ar'}} (empty = default)."""
    from models.settings import Settings
    clean = {}
    for g in GROUPS:
        v = values.get(g) or {}
        en, ar = str(v.get('en') or '').strip()[:120], str(v.get('ar') or '').strip()[:120]
        if en or ar:
            clean[g] = {'en': en, 'ar': ar}
    Settings.set(SETTING_KEY, json.dumps(clean, ensure_ascii=False),
                 'Names users see for the screening lists (display only)')
    try:
        from database.db import get_db
        get_db().commit()
    except Exception:
        pass
    reset_cache()
    return clean


# --- opaque profile references -------------------------------------------------------------------------
# A profile link names one listed record. Its URL must not carry the internal source code, so the pair
# (source, record id) travels encrypted (Fernet, key derived from the app secret). Old ?src=&rec= URLs still
# work: the superadmin uses them as they are, everyone else is redirected to the opaque form.

def _fernet():
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    from flask import current_app
    secret = str(current_app.config.get('SECRET_KEY') or '')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('cx-profile-ref:' + secret).encode('utf-8')).digest()))


def profile_ref(source, record):
    """Opaque token for (source, record id); '' when either is missing."""
    if not source or record in (None, ''):
        return ''
    return _fernet().encrypt(json.dumps([str(source), str(record)]).encode('utf-8')).decode('ascii')


def resolve_profile_ref(token):
    """(source, record id) from a token, or (None, None) when it is not one of ours."""
    try:
        src, rec = json.loads(_fernet().decrypt(str(token).encode('ascii')).decode('utf-8'))
        return str(src), str(rec)
    except Exception:
        return None, None


# --- reports: per-list figures under our names ----------------------------------------------------------

def _rate(n, d):
    return round(100.0 * n / d, 1) if d else None


def regroup_counts(by_key, lang=None, rates=True):
    """{list name: {counts}} -> the same figures summed under our list names (drift report). Rates are
    recomputed; averages that cannot be summed are dropped."""
    out = {}
    for k, d in (by_key or {}).items():
        if not isinstance(d, dict):
            continue
        name = text_display(k, lang)
        t = out.setdefault(name, {})
        for f, v in d.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and f not in ('fp_rate', 'delisted_pct',
                                                                                      'avg_score'):
                t[f] = (t.get(f) or 0) + v
            elif f == 'active' and v is None:
                t.setdefault('active', None)
    if rates:
        for t in out.values():
            if 'false_positives' in t:
                t['fp_rate'] = _rate(t['false_positives'], t.get('decided', t.get('true_matches', 0) + t['false_positives']))
                t['avg_score'] = None
            if 'delisted' in t:
                t['delisted_pct'] = _rate(t['delisted'], t.get('active') or 0)
    return out


def regroup_rows(rows, key='list', lang=None):
    """Rows of a 'hits by list' table regrouped under our list names, with no raw source (no drill-down link)."""
    out = {}
    for r in rows or []:
        name = display(r.get('raw_source') or r.get(key), None, None, lang) if r.get('raw_source') \
            else text_display(r.get(key), lang)
        t = out.setdefault(name, {key: name, 'raw_source': None, 'hits': 0, 'true_matches': 0,
                                  'false_positives': 0, 'pending': 0})
        for f in ('hits', 'true_matches', 'false_positives', 'pending'):
            t[f] += int(r.get(f) or 0)
    for t in out.values():
        t['fp_rate'] = _rate(t['false_positives'], t['true_matches'] + t['false_positives'])
    return sorted(out.values(), key=lambda r: (-r['hits'], str(r[key])))


def public_alerts(alerts, names, lang=None):
    """Drift alerts whose subject is a list: the list named under our names."""
    out = []
    for a in alerts or []:
        a = dict(a)
        s = a.get('subject')
        if s in names:
            n = text_display(s, lang)
            for k in ('en', 'ar'):
                if isinstance(a.get(k), str) and a[k].startswith(f'{s}:'):
                    a[k] = text_display(s, k) + a[k][len(s):]
            a['subject'] = n
        out.append(a)
    return out
