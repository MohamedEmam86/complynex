# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
Vessel screening engine (V2) - four layers, from certain to inferred.

  1. Identifier   IMO (current or past) = the listed ship: CONFIRMED. MMSI / call sign alone = strong
                  but not decisive (both change when a ship is re-flagged): POTENTIAL; with the same name
                  as well they confirm. A different valid IMO on both sides caps any hit (another ship).
  2. Name         current and former names and aliases, any script: prefixes dropped (M/V, MT, م/ن ...),
                  every number in the name must be the same (STAR 1 is not STAR 2), fuzzy + cross-script
                  consonant skeleton. A name alone never confirms.
  3. Owner        the declared owner / operator / manager is screened with the person / entity engine;
                  a listed party = an ownership alert. The owners of the listed ships found are shown, and
                  the same owner on both sides supports a name hit.
  4. Risk         flag of convenience, high-risk / false flag, flag changes, invalid IMO check digit,
                  invalid MMSI, renamed listed ship: a separate risk score with one line per rule.
                  Never creates a match by itself.

The same ship on several lists (same valid IMO) is one hit, with every list behind it. Tiers use the live
screening thresholds (screening/thresholds.py), so the MLRO's threshold settings apply to vessels too; the
vessel-specific weights below can be changed in screening_config 'vessel_engine' (JSON) or per call
(config=...), e.g. by the Gold Set evaluation.

Explanations are {'code', 'en', 'ar'} items; the UI shows the user's language, the API the English text.
screen_vessel(...) is the single entry point (UI, bulk, API and the vessel Gold Set).
"""
import json
import logging
import re

from screening import vessel_utils as VU

logger = logging.getLogger(__name__)

DEFAULTS = {
    'name_weight': 0.9,            # an exact name alone scores 90: POTENTIAL, never CONFIRMED
    'name_min': 60.0,              # name similarity below this is not a candidate
    'prefilter_cutoff': 55.0,      # rapidfuzz recall cut-off over all listed names
    'mmsi_score': 90.0,            # same MMSI alone
    'callsign_score': 85.0,        # same call sign alone
    'mmsi_name_score': 96.0,       # same MMSI + same name (>= name_strong)
    'callsign_name_score': 93.0,   # same call sign + same name
    'name_strong': 90.0,           # a name similarity that counts as "the same name"
    'conflict_cap': 60.0,          # a different valid IMO on both sides: another ship
    'number_cap': 60.0,            # different numbers in the names (STAR 1 / STAR 2)
    'partial_word_cap': 60.0,      # one word of a longer listed name (OCEAN vs OCEAN GLORY)
    'flag_bonus': 3.0,             # same flag (current or former) on a name hit
    'owner_bonus': 4.0,            # the declared owner is the listed ship's owner, on a name hit
    'name_hit_max': 94.0,          # a name hit never reaches CONFIRMED by itself
    'owner_weight': 0.95,          # the screening's score from a listed owner
    'risk': {'invalid_imo': 20, 'invalid_mmsi': 10, 'foc': 15, 'high_risk_flag': 25, 'false_flag': 30,
             'flag_changes': 15, 'listed_flag_changes': 10, 'listed_renamed': 5, 'owner_listed': 40},
}


def config(conn=None, override=None):
    """The engine weights: DEFAULTS < screening_config 'vessel_engine' < override."""
    cfg = json.loads(json.dumps(DEFAULTS))
    if conn is not None:
        try:
            from screening.list_versions import _cfg_json
            stored = _cfg_json(conn, 'vessel_engine')
            _merge(cfg, stored)
        except Exception:
            pass
    _merge(cfg, override or {})
    return cfg


def _merge(cfg, upd):
    for k, v in (upd or {}).items():
        if k not in cfg:
            continue
        if isinstance(cfg[k], dict) and isinstance(v, dict):
            for k2, v2 in v.items():
                if k2 in cfg[k]:
                    try:
                        cfg[k][k2] = float(v2)
                    except (TypeError, ValueError):
                        pass
        else:
            try:
                cfg[k] = float(v)
            except (TypeError, ValueError):
                pass


def _thresholds():
    try:
        from screening import thresholds as T
        v = T.current()
        return float(v['low']), float(v['potential']), float(v['confirmed'])
    except Exception:
        try:
            from screening import match_intel as mi
            return float(mi.LOW), float(mi.POTENTIAL), float(mi.CONFIRMED)
        except Exception:
            return 75.0, 80.0, 95.0


def tier_of(score, th=None):
    low, pot, conf = th or _thresholds()
    if score >= conf:
        return 'CONFIRMED'
    if score >= pot:
        return 'POTENTIAL'
    if score >= low:
        return 'LOW'
    return 'BELOW'


# --------------------------------------------------------------------------- explanation texts
_TEXT = {
    'same_imo': ("Same IMO number ({v}), the listed ship's {when} IMO: the IMO identifies a ship for life",
                 'نفس رقم المنظمة البحرية الدولية IMO ({v}) وهو الرقم {when_ar} للسفينة المدرجة، ورقم IMO يعرّف السفينة طوال عمرها'),
    'same_mmsi': ("Same MMSI ({v}, {when})", 'نفس رقم MMSI ({v}، {when_ar})'),
    'same_callsign': ('Same call sign ({v}, {when})', 'نفس نداء الاتصال ({v}، {when_ar})'),
    'mmsi_changes': ('MMSI and call sign change when a ship is re-flagged: not decisive alone',
                     'رقم MMSI ونداء الاتصال يتغيران عند تغيير علم السفينة: لا يكفيان وحدهما'),
    'renamed': ('The name differs: the ship may have been renamed', 'الاسم مختلف: ربما تغيّر اسم السفينة'),
    'imo_conflict': ('Different IMO number ({q} / {l}): a different ship', 'رقم IMO مختلف ({q} / {l}): سفينة أخرى'),
    'name_match': ('Name match {s}% with "{n}"', 'تطابق الاسم بنسبة {s}% مع "{n}"'),
    'former_name': ('Matched a former name of the ship', 'التطابق مع اسم سابق للسفينة'),
    'cross_script': ('Compared across scripts (Arabic / Latin)', 'مقارنة بين الحروف العربية واللاتينية'),
    'spelling': ('Same name, another spelling', 'نفس الاسم بتهجئة أخرى'),
    'numbers_differ': ('The numbers in the names differ ({q} / {l}): a different ship',
                       'الأرقام في الاسمين مختلفة ({q} / {l}): سفينة أخرى'),
    'same_number': ('Same number in the name', 'نفس الرقم في الاسم'),
    'partial_word': ('Only one word of a longer listed name', 'كلمة واحدة فقط من اسم مدرج أطول'),
    'same_flag': ('Same flag (current or former): {v}', 'نفس العلم (الحالي أو السابق): {v}'),
    'other_flag': ('Different flag ({q} / {l}): ships change flags, not decisive', 'علم مختلف ({q} / {l}): السفن تغيّر أعلامها، غير حاسم'),
    'mmsi_differs': ('Different MMSI (it changes when a ship is re-flagged)', 'رقم MMSI مختلف (يتغير عند تغيير العلم)'),
    'same_owner': ('The declared owner is an owner / operator of the listed ship: {v}',
                   'المالك المُدخل هو مالك أو مشغّل للسفينة المدرجة: {v}'),
    'owner_listed': ('Owned / operated by a listed party', 'مملوكة أو مُشغّلة من طرف مدرج'),
    'several_lists': ('Listed on {n} lists', 'مدرجة في {n} قوائم'),
    'id_and_name': ('Identifier and name agree', 'المعرّف والاسم متطابقان'),
    'whitelisted': ('Cleared before as a false match by {who} on {when}; nothing has changed since',
                    'تم استبعادها سابقًا كتطابق خاطئ بواسطة {who} بتاريخ {when}، ولم يتغير شيء منذ ذلك'),
    'reopened': ('Re-opened: cleared on {when}, but {why}', 'أُعيد فتحها: تم استبعادها بتاريخ {when}، لكن {why_ar}'),
    # risk lines
    'r_invalid_imo': ('IMO number fails its check digit (possibly false or mistyped)',
                      'رقم IMO لا يجتاز رقم التحقق (قد يكون مزيفًا أو خطأ في الإدخال)'),
    'r_invalid_mmsi': ('MMSI is not a ship station number (first digit not 2-7)', 'رقم MMSI ليس رقم محطة سفينة (الرقم الأول ليس 2-7)'),
    'r_foc': ('Flag of convenience (open registry): {v}', 'علم مواءمة (سجل مفتوح): {v}'),
    'r_high_risk_flag': ('High-risk flag state: {v}', 'دولة علم عالية المخاطر: {v}'),
    'r_false_flag': ('False flag declared: {v}', 'علم مزيف: {v}'),
    'r_flag_changes': ('The ship changed flag {n} times', 'غيّرت السفينة علمها {n} مرات'),
    'r_listed_flag_changes': ('The matched listed ship changed flag {n} times', 'غيّرت السفينة المدرجة المطابقة علمها {n} مرات'),
    'r_listed_renamed': ('The matched listed ship has former names', 'للسفينة المدرجة المطابقة أسماء سابقة'),
    'r_owner_listed': ('The declared owner / operator matches a listed party', 'المالك أو المشغّل المُدخل يطابق طرفًا مدرجًا'),
    # warnings
    'w_imo_len': ('IMO number is not 7 digits: not used', 'رقم IMO ليس 7 أرقام: لم يُستخدم'),
    'w_mmsi_len': ('MMSI is not 9 digits: not used', 'رقم MMSI ليس 9 أرقام: لم يُستخدم'),
    'w_nothing': ('Nothing to screen', 'لا توجد بيانات للفحص'),
    'w_owner_unavailable': ('Owner screening unavailable: screen the owner separately',
                            'فحص المالك غير متاح: افحص المالك بشكل منفصل'),
}
_WHEN = {'current': ('current', 'الحالي'), 'former': ('former', 'السابق')}
_WHY_AR = {'the listed ship changed (name, flag or owner)': 'السفينة المدرجة تغيّرت (الاسم أو العلم أو المالك)',
           'the screened ship changed (name, flag or owner)': 'السفينة المفحوصة تغيّرت (الاسم أو العلم أو المالك)',
           'the listed ship is no longer on any list': 'السفينة لم تعد مدرجة في أي قائمة'}


def say(code, **p):
    """One explanation item {'code', 'en', 'ar', 'p'}."""
    en, ar = _TEXT[code]
    if 'when' in p:
        p.setdefault('when_ar', _WHEN.get(p['when'], (p['when'], p['when']))[1])
    if 'why' in p:
        p.setdefault('why_ar', _WHY_AR.get(p['why'], p['why']))
    try:
        return {'code': code, 'en': en.format(**p), 'ar': ar.format(**p), 'p': p}
    except (KeyError, IndexError):
        return {'code': code, 'en': en, 'ar': ar, 'p': p}


def text(items, lang='en'):
    """Plain strings of explanation items (old results stored plain strings: kept as they are)."""
    return [(i.get('ar') if lang == 'ar' else i.get('en')) if isinstance(i, dict) else str(i) for i in items or []]


# --------------------------------------------------------------------------- names
def _skeleton(word):
    """Consonant key shared by Arabic and Latin spellings (screening/match_intel._xs_key)."""
    try:
        from screening.match_intel import _xs_key
        return _xs_key(word.lower() if not VU.is_arabic(word) else word)
    except Exception:
        return re.sub('[aeiouyw]', '', word.lower())


def _join_article(words):
    """Latin 'AL AMAL' / 'EL NOUR' -> 'ALAMAL' / 'ELNOUR' (the Arabic article is written joined)."""
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if w in ('AL', 'EL', 'AS', 'AR', 'AD', 'AN', 'ASH', 'AZ') and i + 1 < len(words) and not words[i + 1].isdigit():
            out.append('AL' + words[i + 1])
            i += 2
            continue
        out.append(w)
        i += 1
    return out


_AR_VK = str.maketrans({'ب': 'b', 'ت': 't', 'ث': 's', 'ج': 'g', 'ح': 'h', 'خ': 'k', 'د': 'd', 'ذ': 'z', 'ر': 'r',
                        'ز': 'z', 'س': 's', 'ش': 'x', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': '', 'غ': 'g',
                        'ف': 'f', 'ق': 'k', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'u', 'ي': 'i',
                        'ى': 'a', 'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ة': 'a', 'ء': '', 'ئ': 'i', 'ؤ': 'u',
                        'پ': 'b', 'گ': 'g', 'چ': 'x', 'ڤ': 'f', ' ': ''})


def _vkey(norm):
    """Sound key that keeps the vowels Arabic writes (long vowels): 'أتيكا' and 'ATTICA' -> 'atika',
    'UTAKI' -> 'utaki'. Used with the consonant skeleton so that names sharing only their consonants
    (ATTICA / UTAKI / YATEEKA) are not taken for one another."""
    words = VU.name_words(norm)
    if VU.is_arabic(norm):
        k = ''.join(words).translate(_AR_VK)
        k = re.sub(r'h$', 'a', k)
    else:
        k = ''.join(_join_article(words)).lower()
        for a, b in (('sh', 'x'), ('kh', 'k'), ('gh', 'g'), ('th', 's'), ('dh', 'z'), ('ph', 'f'),
                     ('q', 'k'), ('c', 'k'), ('j', 'g'), ('v', 'f'), ('p', 'b'), ('e', 'a'), ('y', 'i'),
                     ('o', 'u'), ('w', 'u')):
            k = k.replace(a, b)
        k = re.sub(r'h$', '', k) if len(k) > 3 else k
    return re.sub(r'(.)\1+', r'\1', k)


def _skeletons(norm):
    words = VU.name_words(norm)
    if not VU.is_arabic(norm):
        words = _join_article(words)
    return [_skeleton(w) for w in words]


_TRANSLIT = {}


def _latin(name):
    """A Latin reading of an Arabic ship name (transliteration of each word), cached."""
    if not VU.is_arabic(name):
        return name
    if name in _TRANSLIT:
        return _TRANSLIT[name]
    try:
        from screening.arabic_transliteration_enhanced import transliterate_to_english
        out = transliterate_to_english(name)
    except Exception:
        out = name
    if len(_TRANSLIT) < 20000:
        _TRANSLIT[name] = out
    return out


def name_score(query, listed, cfg=None):
    """0-100 similarity of two ship names, with the reason codes. Numbers must agree exactly."""
    from rapidfuzz import fuzz
    cfg = cfg or DEFAULTS
    qn, ln = VU.norm_name(query), VU.norm_name(listed)
    if not qn or not ln:
        return 0.0, []
    reasons = []
    qnum, lnum = VU.name_numbers(qn), VU.name_numbers(ln)
    if VU.is_arabic(qn) != VU.is_arabic(ln):
        q_lat = VU.norm_name(_latin(query)) if VU.is_arabic(qn) else qn
        l_lat = VU.norm_name(_latin(listed)) if VU.is_arabic(ln) else ln
        qw, lw = VU.name_words(q_lat), VU.name_words(l_lat)
        fz = fuzz.token_sort_ratio(' '.join(qw), ' '.join(lw)) if qw and lw else 0.0
        # cross-script: compare the consonant skeleton of each word as well
        # the consonant skeleton says "could be the same name"; the vowel key (Arabic writes the long
        # vowels) says how close the two readings are
        qs, ls = _skeletons(qn), _skeletons(ln)
        vk = fuzz.ratio(_vkey(qn), _vkey(ln))
        if qs and ls and all(qs) and all(ls):
            sk = vk if qs == ls else min(vk, fuzz.ratio(''.join(qs), ''.join(ls)))
        else:
            sk = 0.0
        s = max(fz, sk * 0.97)
        reasons.append('cross_script')
        qnum = VU.name_numbers(q_lat) or qnum
        lnum = VU.name_numbers(l_lat) or lnum
    else:
        qw, lw = VU.name_words(qn), VU.name_words(ln)
        if not qw or not lw:
            s = 100.0 if qn == ln else 0.0
        else:
            a, b = ' '.join(qw), ' '.join(lw)
            s = max(fuzz.token_sort_ratio(a, b), fuzz.ratio(a.replace(' ', ''), b.replace(' ', '')))
            if s < 88:
                # spelling variants of the same words (NOOR / NOUR, AL AMAL / ALAMAL): same consonants
                qs, ls = _skeletons(qn), _skeletons(ln)
                if qs and all(qs) and qs == ls and fuzz.ratio(_vkey(qn), _vkey(ln)) >= 85 and \
                        _vkey(qn)[:1] == _vkey(ln)[:1]:
                    s = 88.0
                    reasons.append('spelling')
            if len(qw) == 1 and len(lw) > 1 and qw[0] in lw:
                # one word of a longer listed name ("OCEAN" vs "OCEAN GLORY") is not that ship
                s = min(s, cfg['partial_word_cap'])
                reasons.append('partial_word')
    if qnum != lnum:
        if qnum or lnum:
            reasons.append(('numbers_differ', ' '.join(map(str, qnum)) or '-', ' '.join(map(str, lnum)) or '-'))
            s = min(s, cfg['number_cap'])
    elif qnum:
        reasons.append('same_number')
    return round(float(s), 1), reasons


def best_name(query, names, cfg=None):
    best = (0.0, None, [])
    for n in names or []:
        s, r = name_score(query, n, cfg)
        if s > best[0]:
            best = (s, n, r)
    return best


def _reason_items(reasons):
    out = []
    for r in reasons:
        if isinstance(r, tuple):
            out.append(say(r[0], q=r[1], l=r[2]))
        else:
            out.append(say(r))
    return out


# --------------------------------------------------------------------------- candidates
_PF = {}


def _prefilter_index(cands):
    """Normalised names + skeletons of every listed name (cached on the candidate list object)."""
    key = id(cands)
    hit = _PF.get('idx')
    if hit and hit[0] == key and hit[1] == len(cands):
        return hit[2]
    keys, vals, sks = [], [], []
    for i, c in enumerate(cands):
        for n in c['names']:
            nn = VU.norm_name(n)
            if nn:
                keys.append(i)
                vals.append(nn)
                sks.append(' '.join(_skeletons(nn)))
    idx = (keys, vals, sks)
    _PF['idx'] = (key, len(cands), idx)
    return idx


def _prefilter(query, cands, limit=60, cfg=None):
    """Cheap recall over every listed name (rapidfuzz on normalised names + the cross-script skeleton)."""
    from rapidfuzz import fuzz, process
    cfg = cfg or DEFAULTS
    qn = VU.norm_name(query)
    if not qn:
        return []
    keys, vals, sks = _prefilter_index(cands)
    q_lat = VU.norm_name(_latin(query)) if VU.is_arabic(qn) else qn
    q_sk = ' '.join(_skeletons(qn))
    picked = set()
    for q in {qn, q_lat}:
        for _, sc, idx in process.extract(q, vals, scorer=fuzz.token_sort_ratio, limit=limit,
                                          score_cutoff=cfg['prefilter_cutoff']):
            picked.add(keys[idx])
    if q_sk:
        for _, sc, idx in process.extract(q_sk, sks, scorer=fuzz.ratio, limit=limit, score_cutoff=80):
            picked.add(keys[idx])
    return [cands[i] for i in picked]


def _flag_eq(a, b):
    a, b = VU.clean_flag(a), VU.clean_flag(b)
    return bool(a) and a == b


def _party_match(owner, parties):
    """The listed ship's party that matches the declared owner (name similarity >= 90), else None."""
    if not owner or not parties:
        return None
    from rapidfuzz import fuzz
    from screening.vessel_store import party_key
    q = party_key(owner)
    for p in parties:
        n = party_key(p.get('name'))
        if q and n and fuzz.token_sort_ratio(q, n) >= 90:
            return p
    return None


# --------------------------------------------------------------------------- main
def screen_vessel(name=None, imo=None, mmsi=None, call_sign=None, flag=None, owner=None, vessel_type=None,
                  flags_past=None, *, conn=None, candidates=None, id_index=None, screen_party=None, flags=None,
                  links=None, whitelist=None, config_override=None, max_hits=25):
    """Screen one vessel. Returns
      {'query', 'warnings', 'tier', 'score', 'hits': [...], 'owner_hits': [...], 'risk': {'score','lines'},
       'near': [...] (below-threshold names shown for transparency), 'suppressed': [...] (whitelisted),
       'thresholds': {...}}

    Each hit: {watchlist_id, group_key, sources, name, matched_name, imo, mmsi, call_sign, flag, flags_past,
               type, year_built, measures, parties, score, tier, layer, explanation[], fields{}}

    conn          DB connection (candidates, identifiers, flags, owner links and the whitelist come from it)
    candidates    list of vessel dicts (vessel_store.load_candidates format) - tests / Gold Set
    id_index      {('IMO','9123456'): [(watchlist_id, is_current)]} - tests / Gold Set
    screen_party  callable(name) -> [{'name','score','tier','list_type'}]: the person / entity engine
    flags         {flag-name-lower or iso2: {'foc': bool, 'high_risk': bool}}
    whitelist     {listed_key: entry} (vessel_store.whitelist_for) - tests
    config_override  engine weights (see DEFAULTS), e.g. from the Gold Set evaluation
    """
    from screening import vessel_store as VS
    cfg = config(conn, config_override)
    th = _thresholds()
    low = th[0]
    q_imo, q_mmsi, q_call = VU.norm_imo(imo), VU.norm_mmsi(mmsi), VU.norm_call_sign(call_sign)
    q_name = (name or '').strip()
    q_past = flags_past if isinstance(flags_past, (list, tuple)) else re.split(r'[;,|]', str(flags_past or ''))
    q_past = [f for f in dict.fromkeys(VU.clean_flag(x) for x in q_past if x and str(x).strip()) if f]
    query = {'name': q_name or None, 'imo': q_imo, 'mmsi': q_mmsi, 'call_sign': q_call,
             'flag': VU.clean_flag(flag), 'flags_past': q_past, 'owner': (owner or '').strip() or None,
             'type': (vessel_type or '').strip() or None}
    warnings = []
    if imo and not q_imo:
        warnings.append(say('w_imo_len'))
    if mmsi and not q_mmsi:
        warnings.append(say('w_mmsi_len'))
    thresholds = {'low': th[0], 'potential': th[1], 'confirmed': th[2]}
    if not (q_name or q_imo or q_mmsi or q_call or query['owner']):
        return {'query': query, 'warnings': warnings + [say('w_nothing')], 'tier': 'INCOMPLETE',
                'score': 0.0, 'hits': [], 'owner_hits': [], 'risk': {'score': 0, 'lines': []}, 'near': [],
                'suppressed': [], 'thresholds': thresholds}

    if candidates is None:
        candidates = VS.load_candidates(conn) if conn is not None else []
    by_id = {c['watchlist_id']: c for c in candidates}

    def ids_for(kind, value):
        if not value:
            return []
        if id_index is not None:
            return id_index.get((kind, value), [])
        return VS.identifier_hits(conn, kind, value) if conn is not None else []

    hits = {}

    def add(c, score, layer, expl, matched_name=None, fields=None):
        wid = c['watchlist_id']
        h = hits.get(wid)
        if h is None or score > h['score']:
            old = h
            h = dict(score=round(score, 1), layer=layer, explanation=list(expl),
                     matched_name=matched_name or c.get('name'), fields=fields or {})
            if old:
                for e in old['explanation']:
                    if e['code'] not in {x['code'] for x in h['explanation']}:
                        h['explanation'].append(e)
            hits[wid] = h
        else:
            for e in expl:
                if e['code'] not in {x['code'] for x in h['explanation']}:
                    h['explanation'].append(e)

    q_imo_ok = bool(q_imo and VU.imo_valid(q_imo))

    def imo_conflict(c):
        """Both sides carry a valid IMO and they differ: another ship."""
        return q_imo_ok and c.get('imo') and c['imo'] != q_imo and VU.imo_valid(c['imo'])

    # ---- layer 1: identifiers
    for kind, val, label in (('IMO', q_imo, 'IMO number'), ('MMSI', q_mmsi, 'MMSI'), ('CALLSIGN', q_call, 'call sign')):
        for wid, is_current in ids_for(kind, val):
            c = by_id.get(wid)
            if c is None:
                continue
            when = 'current' if is_current else 'former'
            fields = {label: {'query': val, 'listed': val, 'match': True}}
            ns, nm, nr = (best_name(q_name, c['names'], cfg) if q_name else (0.0, None, []))
            if q_name:
                fields['name'] = {'query': q_name, 'listed': nm or c['name'], 'match': ns >= cfg['name_strong']}
            if kind == 'IMO':
                sc = 100.0
                expl = [say('same_imo', v=val, when=when)]
                if q_name and ns < 70:
                    expl.append(say('renamed'))
            else:
                same_name = bool(q_name) and ns >= cfg['name_strong']
                sc = cfg['mmsi_name_score' if kind == 'MMSI' else 'callsign_name_score'] if same_name else \
                    cfg['mmsi_score' if kind == 'MMSI' else 'callsign_score']
                expl = [say('same_mmsi' if kind == 'MMSI' else 'same_callsign', v=val, when=when)]
                expl.append(say('id_and_name') if same_name else say('mmsi_changes'))
                if imo_conflict(c):
                    sc = min(sc, cfg['conflict_cap'])
                    expl.append(say('imo_conflict', q=q_imo, l=c['imo']))
                    fields['IMO number'] = {'query': q_imo, 'listed': c['imo'], 'match': False}
            add(c, sc, 'identifier', expl, matched_name=nm, fields=fields)

    # ---- layer 2: names
    if q_name:
        for c in _prefilter(q_name, candidates, cfg=cfg):
            ns, nm, nr = best_name(q_name, c['names'], cfg)
            if ns < cfg['name_min']:
                continue
            sc = ns * cfg['name_weight']
            expl = [say('name_match', s='%.0f' % ns, n=nm or c['name'])] + _reason_items(nr)
            if nm and nm in (c.get('previous_names') or []):
                expl.append(say('former_name'))
            fields = {'name': {'query': q_name, 'listed': nm, 'match': ns >= cfg['name_strong']}}
            if q_imo and c.get('imo'):
                fields['IMO number'] = {'query': q_imo, 'listed': c['imo'], 'match': q_imo == c['imo']}
                if imo_conflict(c):
                    sc = min(sc, cfg['conflict_cap'])
                    expl.append(say('imo_conflict', q=q_imo, l=c['imo']))
            if q_mmsi and c.get('mmsi') and q_mmsi != c['mmsi']:
                fields['MMSI'] = {'query': q_mmsi, 'listed': c['mmsi'], 'match': False}
                expl.append(say('mmsi_differs'))
            if query['flag']:
                listed_flags = [c.get('flag')] + list(c.get('flags_past') or [])
                same = any(_flag_eq(query['flag'], f) for f in listed_flags if f)
                fields['flag'] = {'query': query['flag'], 'listed': c.get('flag'), 'match': same}
                if same and sc >= low - cfg['flag_bonus'] and not imo_conflict(c):
                    sc = min(sc + cfg['flag_bonus'], cfg['name_hit_max'])
                    expl.append(say('same_flag', v=query['flag']))
                elif not same and c.get('flag'):
                    expl.append(say('other_flag', q=query['flag'], l=c.get('flag')))
            pm = _party_match(query['owner'], c.get('parties'))
            if pm:
                fields['owner'] = {'query': query['owner'], 'listed': pm.get('name'), 'match': True}
                if sc >= low - cfg['owner_bonus'] and not imo_conflict(c):
                    sc = min(sc + cfg['owner_bonus'], cfg['name_hit_max'])
                expl.append(say('same_owner', v=pm.get('name')))
            if query['type'] and c.get('type'):
                qt, lt = query['type'].lower(), str(c['type']).lower()
                fields['type'] = {'query': query['type'], 'listed': c['type'], 'match': qt in lt or lt in qt}
            add(c, min(sc, cfg['name_hit_max']), 'name', expl, matched_name=nm, fields=fields)

    # ---- layer 3: owner / operator / manager
    owner_hits = []
    if query['owner'] and screen_party:
        try:
            for ph in screen_party(query['owner']) or []:
                s = float(ph.get('score') or 0)
                if s >= low:
                    owner_hits.append({'query': query['owner'], 'name': ph.get('name'), 'score': round(s, 1),
                                       'tier': ph.get('tier') or tier_of(s, th), 'list_type': ph.get('list_type'),
                                       'source': ph.get('source'), 'watchlist_id': ph.get('watchlist_id')})
        except Exception as e:
            logger.warning(f'[VESSELS] owner screening failed: {e}')
            warnings.append(say('w_owner_unavailable'))

    # ---- one hit per ship: the same IMO on several lists
    groups = {}
    for wid, h in hits.items():
        c = by_id[wid]
        groups.setdefault(c.get('group_key') or 'WL:%d' % wid, []).append((c, h))
    merged = []
    for gk, items in groups.items():
        items.sort(key=lambda x: -x[1]['score'])
        best_c, best_h = items[0]
        members = [c for c, _ in items]
        # every list record of that ship, also those the query did not reach by name
        for c in candidates:
            if c.get('group_key') == gk and c['watchlist_id'] not in {m['watchlist_id'] for m in members}:
                members.append(c)
        view = VS.merge_group(members)
        if links is not None:
            view['parties'] = [p for m in members for p in links.get(m['watchlist_id'], [])] or view['parties']
        h = dict(best_h)
        expl = list(h['explanation'])
        for _, other in items[1:]:
            for e in other['explanation']:
                if e['code'] not in {x['code'] for x in expl}:
                    expl.append(e)
        if any(p.get('party_listed') for p in view['parties']):
            expl.append(say('owner_listed'))
        if len(view['sources']) > 1:
            expl.append(say('several_lists', n=len(view['sources'])))
        h['explanation'] = expl
        h.update({k: view.get(k) for k in ('group_key', 'sources', 'member_ids', 'list_types', 'name', 'imo',
                                           'mmsi', 'call_sign', 'flag', 'flags_past', 'type', 'year_built',
                                           'gross_tonnage', 'measures', 'parties', 'previous_names',
                                           'risk_score', 'list_type')})
        h['watchlist_id'] = best_c['watchlist_id']
        h['source'] = best_c['source']
        h['names'] = view.get('names')
        h['flags_all'] = view.get('flags_all')
        h['listed_key'] = VS.listed_key(h)
        h['listed_fp'] = VS.listed_fingerprint(h)
        h.pop('names', None)
        h.pop('flags_all', None)
        merged.append(h)
    merged.sort(key=lambda h: -h['score'])

    # ---- whitelist (cleared false matches): suppressed while nothing changed on either side
    qkey = VU.query_key(q_name, q_imo, q_mmsi, query['flag'])
    qfp = VS.query_fingerprint(query)
    if whitelist is None and conn is not None:
        try:
            whitelist = VS.whitelist_for(conn, qkey)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            whitelist = {}
    suppressed = []
    for h in merged:
        w = (whitelist or {}).get(h['listed_key'])
        if not w:
            continue
        when = str(w.get('created_at') or '')[:10]
        if w.get('status') == 'active' and w.get('listed_fp') == h['listed_fp'] and w.get('query_fp') == qfp:
            h['whitelisted'] = {'id': w.get('id'), 'by': w.get('by_name'), 'at': when, 'reason': w.get('reason')}
            h['explanation'].append(say('whitelisted', who=w.get('by_name') or '-', when=when))
            suppressed.append(h)
        else:
            why = w.get('reopened_reason') if w.get('status') == 'reopened' else (
                'the listed ship changed (name, flag or owner)' if w.get('listed_fp') != h['listed_fp']
                else 'the screened ship changed (name, flag or owner)')
            h['reopened'] = {'id': w.get('id'), 'at': when, 'why': why}
            h['explanation'].append(say('reopened', when=when, why=why))
    merged = [h for h in merged if not h.get('whitelisted')]

    # ---- layer 4: risk
    if flags is None and conn is not None:
        flags = VS.flag_risk(conn)
    flags = flags or {}
    rw = cfg['risk']
    lines, risk = [], 0

    def flag_info(f):
        return flags.get((f or '').lower()) or flags.get((VU.flag_code(f) or '-').lower()) or {}

    if q_imo and not VU.imo_valid(q_imo):
        lines.append(say('r_invalid_imo'))
        risk += rw['invalid_imo']
    if q_mmsi and not VU.mmsi_valid(q_mmsi):
        lines.append(say('r_invalid_mmsi'))
        risk += rw['invalid_mmsi']
    if query['flag']:
        fr = flag_info(query['flag'])
        if '(false flag)' in query['flag']:
            lines.append(say('r_false_flag', v=query['flag']))
            risk += rw['false_flag']
        if fr.get('foc'):
            lines.append(say('r_foc', v=query['flag']))
            risk += rw['foc']
        if fr.get('high_risk'):
            lines.append(say('r_high_risk_flag', v=query['flag']))
            risk += rw['high_risk_flag']
    hops = [f for f in q_past if f != query['flag']]
    if len(hops) >= 2:
        lines.append(say('r_flag_changes', n=len(hops)))
        risk += rw['flag_changes']
    top = merged[0] if merged and merged[0]['score'] >= low else None
    if top:
        fp = [f for f in (top.get('flags_past') or []) if f]
        if len(fp) >= 2:
            lines.append(say('r_listed_flag_changes', n=len(fp)))
            risk += rw['listed_flag_changes']
        if top.get('previous_names'):
            lines.append(say('r_listed_renamed'))
            risk += rw['listed_renamed']
    if owner_hits:
        lines.append(say('r_owner_listed'))
        risk += rw['owner_listed']

    for h in merged + suppressed:
        h['tier'] = tier_of(h['score'], th)
    alerts = [h for h in merged if h['score'] >= low][:max_hits]
    near = [{'name': h['name'], 'matched_name': h['matched_name'], 'score': h['score'],
             'explanation': h['explanation'], 'watchlist_id': h['watchlist_id']}
            for h in merged if h['score'] < low][:5]
    score = alerts[0]['score'] if alerts else 0.0
    if owner_hits:
        score = max(score, max(o['score'] for o in owner_hits) * cfg['owner_weight'])
    tier = tier_of(score, th) if (alerts or owner_hits) else 'CLEAR'
    if tier == 'BELOW':
        tier = 'CLEAR'
    return {'query': query, 'warnings': warnings, 'tier': tier, 'score': round(score, 1), 'hits': alerts,
            'owner_hits': owner_hits, 'risk': {'score': int(min(risk, 100)), 'lines': lines}, 'near': near,
            'suppressed': [{'name': h['name'], 'imo': h.get('imo'), 'score': h['score'], 'tier': h['tier'],
                            'listed_key': h['listed_key'], 'watchlist_id': h['watchlist_id'],
                            'whitelisted': h['whitelisted'], 'explanation': h['explanation']}
                           for h in suppressed],
            'query_key': qkey, 'query_fp': qfp, 'thresholds': thresholds}


def party_screener():
    """screen_party callable backed by the person / entity engine (company screening, no media)."""
    def _run(name):
        from screening.routes import get_engine
        eng = get_engine()
        res = eng.screen_person(name=name, entity_type='ENTITY', include_media=False)
        out = []
        for m in (res or {}).get('matches') or []:
            if str(m.get('entity_type') or '').upper() == 'VESSEL':
                continue        # a ship is not an owner; vessel hits come from layers 1-2
            out.append({'name': m.get('full_name') or m.get('name'), 'score': m.get('match_score') or 0,
                        'tier': (m.get('decision') or {}).get('tier'), 'list_type': m.get('list_type'),
                        'source': m.get('source') or m.get('list_source'),
                        'watchlist_id': m.get('id') or m.get('entity_id')})
        return out[:10]
    return _run
