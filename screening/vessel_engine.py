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
    'word_mismatch_cap': 70.0,     # names of several words where a word has no counterpart (BALTIC / ATLANTIC DAWN)
    'word_match_min': 75.0,        # ... a counterpart: a word of the other name at least this similar
    'flag_bonus': 3.0,             # same flag (current or former) on a name hit
    'owner_bonus': 4.0,            # the declared owner is the listed ship's owner, on a name hit
    'name_hit_max': 94.0,          # a name hit never reaches CONFIRMED by itself
    'single_word_min': 97.0,       # a one-word name (TRIUMPH, MARINA) alerts only when it is the same word ...
    'single_word_max': 75.0,       # ... and a COMMON one-word name stays review (LOW): many ships carry it
    'single_word_rare_score': 85.0,  # an exact one-word name that is rare in the fleet sample: potential match
    'common_name_hulls': 3,        # a one-word name carried now by this many distinct hulls (or more) across
                                   # EVERY vessel record held (sanctions, bans, port-state control, analysis:
                                   # a sample of the world fleet) is a common ship name: review, IMO needed
    # common ship words: maritime vocabulary used as ship names the world over, common whatever the sample
    # holds (editable in screening_config 'vessel_engine'). Names, mythology and virtues are NOT listed here:
    # how common they are is measured from the data (common_name_hulls).
    'common_ship_words': ['ADMIRAL', 'ANCHOR', 'ARCTIC', 'ATLANTIC', 'BALTIC', 'BREEZE', 'CAPTAIN', 'CARGO',
                          'CARRIER', 'COMMODORE', 'CORAL', 'CRUISER', 'DOLPHIN', 'EXPLORER', 'EXPRESS', 'FERRY',
                          'HARBOR', 'HARBOUR', 'HORIZON', 'ISLAND', 'LAGOON', 'MARINA', 'MARINE', 'MARINER',
                          'MARITIME', 'NAVIGATOR', 'NEPTUNE', 'OCEAN', 'OCEANIC', 'PACIFIC', 'PEARL', 'PILOT',
                          'PIONEER', 'PORT', 'POSEIDON', 'SAILOR', 'SEA', 'SEAWAY', 'SHIP', 'SKIPPER', 'STAR',
                          'TANKER', 'TIDE', 'TRADER', 'TRITON', 'TUG', 'VOYAGER', 'WAVE'],
    'typo_score': 85.0,            # a distinctive multi-word name with one keying error (ERERNAL 8): potential
    'near_imo_score': 75.0,        # an IMO failing its check digit one keying error from a listed IMO: review
    'near_imo_name_score': 90.0,   # ... with the same name as well: an obvious typo of that ship's IMO
    'conflict_review_score': 75.0, # same name, different valid IMO that no list knows (possible false IMO): review
    'owner_weight': 0.95,          # the screening's score from a listed owner
    'risk': {'invalid_imo': 20, 'invalid_mmsi': 10, 'foc': 15, 'high_risk_flag': 25, 'false_flag': 30,
             'flag_changes': 15, 'listed_flag_changes': 10, 'listed_renamed': 5, 'owner_listed': 40,
             'psc': 10, 'psc_repeated': 10, 'intel': 5, 'name_differs': 20},
    'renamed_below': 80.0,         # an identifier hit whose listed names all score below this against the
                                   # entered name: "listed under another name" (renaming is a red flag)
}


def config(conn=None, override=None):
    """The engine weights: DEFAULTS < screening_config 'vessel_engine' < override."""
    cfg = json.loads(json.dumps(DEFAULTS))
    if conn is not None:
        try:
            from screening.vessel_store import config_json
            stored = config_json(conn, 'vessel_engine')
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
        elif isinstance(cfg[k], list):
            if isinstance(v, list):
                cfg[k] = [str(x) for x in v if str(x).strip()][:500]
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
    'renamed': ('Listed under the name "{l}"; the name you entered ("{q}") may be a new or unofficial name - '
                'renaming is a red flag: get the ship\'s current registry documents',
                'مدرجة باسم "{l}"؛ والاسم الذي أدخلته ("{q}") قد يكون اسمًا جديدًا أو غير رسمي - تغيير الاسم مؤشر '
                'خطر: اطلب مستندات التسجيل الحالية للسفينة'),
    'known_name': ('Matched a name ComplyNex has recorded for this ship that the lists have not published yet',
                   'التطابق مع اسم سجّلته ComplyNex لهذه السفينة ولم تنشره القوائم بعد'),
    'r_name_differs': ('The identifier matches a listed ship that is listed under another name: possible renaming '
                       'to hide the listing', 'المعرّف يطابق سفينة مدرجة باسم آخر: احتمال تغيير الاسم لإخفاء الإدراج'),
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
    'ban_record': ('Banned or excluded ship (port ban, exclusion or import ban): not a sanctions listing',
                   'سفينة محظورة أو مستبعدة (حظر موانئ أو استبعاد أو حظر استيراد): ليست إدراجًا على قائمة عقوبات'),
    # risk lines
    'r_psc': ('Port-state-control record: detained or inspected with deficiencies ({n} record(s)); a risk '
              'factor, not a listing', 'سجل رقابة دولة الميناء: احتجاز أو تفتيش بملاحظات ({n} سجل)؛ عامل مخاطر وليس إدراجًا'),
    'r_intel': ('Mentioned in analytical or press material about sanctions; a risk note, not a listing',
                'مذكورة في مواد تحليلية أو صحفية عن العقوبات؛ ملاحظة مخاطر وليست إدراجًا'),
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
    'near_imo': ('The IMO {q} fails its check digit; {l} (one keying error away) is listed: check the number',
                 'رقم IMO {q} لا يجتاز رقم التحقق؛ والرقم {l} (بفارق خطأ إدخال واحد) مدرج: تحقق من الرقم'),
    'word_mismatch': ('A word of the name has no counterpart in the listed name: probably another ship',
                      'كلمة في الاسم لا يقابلها مثيل في الاسم المدرج: غالبًا سفينة أخرى'),
    'one_typo': ('One keying error away from the listed name', 'بفارق خطأ إدخال واحد عن الاسم المدرج'),
    'single_word': ('Common ship name ({n} ship(s) carry it in the vessel records held): the name alone cannot '
                    'identify the ship - IMO number needed (review)',
                    'اسم سفينة شائع (تحمله {n} سفينة في سجلات السفن المتاحة): لا يكفي الاسم وحده لتحديد السفينة - '
                    'يلزم رقم IMO (للمراجعة)'),
    'single_word_word': ('Common ship word used as a name by many ships: the name alone cannot identify the ship '
                         '- IMO number needed (review)',
                         'كلمة شائعة في أسماء السفن: لا يكفي الاسم وحده لتحديد السفينة - يلزم رقم IMO (للمراجعة)'),
    'single_word_rare': ('Exact one-word name, rare among the vessel records held ({n} ship(s) carry it): '
                         'possible match - confirm with the IMO number, flag and owner',
                         'اسم مطابق من كلمة واحدة ونادر في سجلات السفن المتاحة (تحمله {n} سفينة): تطابق محتمل - '
                         'تأكد برقم IMO ودولة العلم والمالك'),
    'imo_conflict_review': ('Same name, but the IMO {q} differs from the listed {l} and is on no list: possibly a '
                            'same-name ship or a false IMO - compare the particulars',
                            'نفس الاسم، لكن رقم IMO {q} يختلف عن المدرج {l} وغير مدرج في أي قائمة: قد تكون سفينة '
                            'بنفس الاسم أو رقم IMO مزيف - قارن البيانات'),
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


_AR_VK = str.maketrans({'ب': 'b', 'ت': 't', 'ث': 'z', 'ج': 'g', 'ح': 'h', 'خ': 'k', 'د': 'd', 'ذ': 'z', 'ر': 'r',
                        'ز': 'z', 'س': 's', 'ش': 'x', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': '', 'غ': 'g',
                        'ف': 'f', 'ق': 'k', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'u', 'ي': 'i',
                        'ى': 'a', 'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ة': 'a', 'ء': '', 'ئ': 'i', 'ؤ': 'u',
                        'پ': 'b', 'گ': 'g', 'چ': 'x', 'ڤ': 'f', ' ': ''})
# Latin spellings -> the sounds Arabic script writes (foreign names are written as they sound)
_LAT_VK = (('tch', 'x'), ('sch', 'x'), ('ch', 'x'), ('sh', 'x'), ('zh', 'g'), ('kh', 'k'), ('gh', 'g'), ('ph', 'f'),
           ('th', 'z'), ('dh', 'z'), ('ck', 'k'), ('qu', 'k'), ('q', 'k'), ('x', 'x'), ('j', 'g'), ('v', 'f'),
           ('p', 'b'), ('w', 'u'), ('o', 'u'), ('y', 'i'), ('e', 'i'))


def _vkey(norm):
    """Sound key that keeps the vowels Arabic writes (long vowels): 'أتيكا' and 'ATTICA' -> 'atika',
    'UTAKI' -> 'utaki'. Used with the consonant skeleton so that names sharing only their consonants
    (ATTICA / UTAKI / YATEEKA) are not taken for one another."""
    words = VU.name_words(norm)
    if VU.is_arabic(norm):
        k = ''.join(words).replace('تش', 'ش')
        k = k.translate(_AR_VK)
        k = re.sub(r'h$', 'a', k)
        k = re.sub(r'ng$', 'n', re.sub(r'ng(?=[^aiu]|$)', 'n', k))          # غ after ن: the "ng" sound
    else:
        parts = []
        for w in _join_article(words):
            w = w.lower()
            w = re.sub(r'c(?=[eiy])', 's', w)                                # PACIFIC -> pasifik
            w = re.sub(r'ght', 't', w)                                       # MIGHTY
            w = re.sub(r'(?<=[a-z])a([bdfgklmnprstvz])e$', r'i\1', w)          # LAKE, GATE: "ei", Arabic ي
            w = re.sub(r'(?<=[a-z]{3})e$', '', w)                            # silent final e
            for x, y in _LAT_VK:
                w = w.replace(x, y)
            w = w.replace('c', 'k')
            parts.append(w)
        k = ''.join(parts)
        k = re.sub(r'h$', '', k) if len(k) > 3 else k
        k = re.sub(r'ng(?=[^aiu]|$)', 'n', k)
    return re.sub(r'(.)\1+', r'\1', k)


def _consonants(k):
    return re.sub(r'[aiu]', '', k)


def cross_script_score(qn, ln):
    """Similarity of an Arabic-script and a Latin-script ship name from their sound keys: the full key (with
    the vowels Arabic writes), and for long names the consonants alone (Arabic often leaves short vowels out)."""
    from rapidfuzz import fuzz
    a, b = _vkey(qn), _vkey(ln)
    if not a or not b:
        return 0.0
    s = fuzz.ratio(a, b)
    # Latin V is written ف (Arabic) or و (Persian): try the other reading too
    lat = ln if not VU.is_arabic(ln) else qn
    if 'V' in lat.upper():
        alt = _vkey(lat.upper().replace('V', 'W'))
        s = max(s, fuzz.ratio(a if lat is ln else alt, alt if lat is ln else b))
    ca, cb = _consonants(a), _consonants(b)
    if min(len(ca), len(cb)) >= 5:
        s = max(s, fuzz.ratio(ca, cb) * 0.95)
    return float(s)


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
        s = max(fz, cross_script_score(qn, ln) * 0.97)
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
            if s < 95 and len(qw) >= 2 and len(lw) >= 2 and fuzz.ratio(a.replace(' ', ''), b.replace(' ', '')) < 95:
                # every distinctive word must have a counterpart in the other name: BALTIC DAWN is not ATLANTIC
                # DAWN, SINAI SPIRIT is not NAVIG8 SPIRIT (the shared word carries the character similarity)
                def _orphan(xs, ys):
                    return any(len(x) > 2 and not any(fuzz.ratio(x, y) >= cfg['word_match_min'] or _one_edit(x, y)
                                                          for y in ys) for x in xs)
                if _orphan(qw, lw) or _orphan(lw, qw):
                    s = min(s, cfg['word_mismatch_cap'])
                    reasons.append('word_mismatch')
            if len(qw) == 1 and len(lw) > 1 and fuzz.ratio(a.replace(' ', ''), b.replace(' ', '')) < 95:
                # one word against a longer listed name ("OCEAN" vs "OCEAN GLORY", "ATLANTIC" vs
                # "HS ATLANTICA") is not that ship; the joined form of the whole name (SANSEVERUS) is
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
    keys, vals, sks, vks = [], [], [], []
    for i, c in enumerate(cands):
        for n in c['names']:
            nn = VU.norm_name(n)
            if nn:
                keys.append(i)
                vals.append(nn)
                sks.append(' '.join(_skeletons(nn)))
                vks.append(_vkey(nn))
    idx = (keys, vals, sks, vks)
    _PF['idx'] = (key, len(cands), idx)
    return idx


def _alerting(cands):
    """The candidates that can produce a hit (sanctions and bans), cached with the candidate list."""
    from screening import vessel_provenance as VP
    hit = _PF.get('alerting')
    if hit and hit[0] is cands and hit[1] == len(cands):
        return hit[2]
    out = [c for c in cands if VP.alerts(c.get('provenance') or VP.SANCTION)]
    _PF['alerting'] = (cands, len(cands), out)
    return out


def hull_counts(cands, extra=None):
    """{normalised one-word name: number of distinct hulls carrying it now} over EVERY vessel record held
    (sanctions, bans, port-state control, analysis - not only the alerting ones): the current name and the
    aliases count, former names do not. A hull is its IMO (valid) or its record group. Cached with the
    candidate list. extra: {name: {hull keys}} from another fleet sample (Gold Set evaluation)."""
    hit = _PF.get('hulls')
    if hit and hit[0] is cands and hit[1] == len(cands) and hit[2] is extra:
        return hit[3]
    seen = {}
    for c in cands:
        imo = c.get('imo')
        hull = ('IMO:' + imo) if imo and VU.imo_valid(imo) else (c.get('group_key') or 'WL:%s' % c.get('watchlist_id'))
        prev = set(c.get('previous_names') or [])
        for nm in [c.get('name')] + list(c.get('names') or []):
            if not nm or nm in prev:
                continue
            k = VU.norm_name(nm)
            if k and ' ' not in k:
                seen.setdefault(k, set()).add(hull)
    for k, hulls in (extra or {}).items():
        seen.setdefault(k, set()).update(hulls)
    out = {k: len(v) for k, v in seen.items()}
    _PF['hulls'] = (cands, len(cands), extra, out)
    return out


def _prefilter(query, cands, limit=60, cfg=None):
    """Cheap recall over every listed name (rapidfuzz on normalised names + the cross-script skeleton)."""
    from rapidfuzz import fuzz, process
    cfg = cfg or DEFAULTS
    qn = VU.norm_name(query)
    if not qn:
        return []
    keys, vals, sks, vks = _prefilter_index(cands)
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
    if VU.is_arabic(qn):        # Arabic script: the sound key (as Arabic writes foreign names)
        qv = _vkey(qn)
        if qv:
            for _, sc, idx in process.extract(qv, vks, scorer=fuzz.ratio, limit=limit, score_cutoff=70):
                picked.add(keys[idx])
    return [cands[i] for i in picked]


def _one_edit(a, b):
    """One keying error between two names (spaces ignored): substitution, insertion, deletion or a swap."""
    from rapidfuzz.distance import DamerauLevenshtein
    a, b = a.replace(' ', ''), b.replace(' ', '')
    return a != b and DamerauLevenshtein.distance(a, b) <= 1


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
                  links=None, whitelist=None, config_override=None, max_hits=25, fleet_sample=None):
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
    fleet_sample  {normalised one-word name: {hull keys}} added to the records held when measuring how common
                  a one-word name is (Gold Set evaluation with a larger sample)
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

    own_candidates = candidates is None
    if candidates is None:
        candidates = VS.load_candidates(conn) if conn is not None else []
    by_id = {c['watchlist_id']: c for c in candidates}
    from screening import vessel_provenance as VP
    risk_records = {}           # identifier matches on records that never alert (port-state control, analysis)

    def cand(wid):
        """The candidate of an identifier hit; a record listed after this worker's cache was filled reloads it."""
        nonlocal candidates, by_id
        c = by_id.get(wid)
        if c is None and own_candidates and conn is not None and not cand.reloaded:
            cand.reloaded = True
            candidates = VS.load_candidates(conn, force=True)
            by_id = {x['watchlist_id']: x for x in candidates}
            c = by_id.get(wid)
        if c is not None and not VP.alerts(c.get('provenance') or VP.SANCTION):
            risk_records[wid] = c
            return None
        return c
    cand.reloaded = False

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
            c = cand(wid)
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

    # ---- layer 1b: an IMO failing its check digit, one keying error from a listed IMO (review)
    if q_imo and not q_imo_ok:
        for n in VU.imo_neighbours(q_imo):
            for wid, is_current in ids_for('IMO', n):
                c = by_id.get(wid)
                if c is None or not VP.alerts(c.get('provenance') or VP.SANCTION):
                    continue
                add(c, cfg['near_imo_score'], 'identifier', [say('near_imo', q=q_imo, l=n)],
                    fields={'IMO number': {'query': q_imo, 'listed': n, 'match': False}})

    # ---- layer 2: names
    q_norm = VU.norm_name(q_name) if q_name else ''
    single_word = bool(q_norm) and len(q_norm.split()) == 1
    # the screened IMO belongs to a listed (alerting) ship; an IMO known only from port-inspection records is a
    # real ship, but not a listed one
    q_imo_listed = bool(q_imo_ok and any(VP.alerts((by_id.get(w) or {}).get('provenance') or VP.SANCTION)
                                         for w, _ in ids_for('IMO', q_imo) if w in by_id))
    similar = []                # one-word names that are close but not the same word (shown, never alerted)
    q_tokens = q_norm.split()
    counts = hull_counts(candidates, fleet_sample) if single_word else {}
    common_words = {VU.norm_name(w) for w in (cfg.get('common_ship_words') or [])} if single_word else set()
    if q_name:
        for c in _prefilter(q_name, _alerting(candidates), cfg=cfg):
            ns, nm, nr = best_name(q_name, c['names'], cfg)
            if ns < cfg['name_min']:
                continue
            # a one-word name: the screened name and the listed name are both one word (a joined form
            # of a two-word listed name such as SANSEVERUS / SAN SEVERUS is not)
            one_word = single_word and len(VU.norm_name(nm or '').split()) <= 1
            if one_word and ns < cfg['single_word_min']:
                if ns >= 85:
                    similar.append({'name': c['name'], 'matched_name': nm, 'imo': c.get('imo'), 'score': round(ns, 1),
                                    'watchlist_id': c['watchlist_id']})
                continue
            near = hits.get(c['watchlist_id'])
            near_imo = bool(near and any(e['code'] == 'near_imo' for e in near['explanation']))
            sc = ns * cfg['name_weight']
            expl = [say('name_match', s='%.0f' % ns, n=nm or c['name'])] + _reason_items(nr)
            if nm and nm in (c.get('previous_names') or []):
                expl.append(say('former_name'))
            fields = {'name': {'query': q_name, 'listed': nm, 'match': ns >= cfg['name_strong']}}
            if q_imo and c.get('imo'):
                fields['IMO number'] = {'query': q_imo, 'listed': c['imo'], 'match': q_imo == c['imo']}
                if imo_conflict(c):
                    primary = VU.norm_name(nm or '') == VU.norm_name(c.get('name') or '')
                    if ns >= cfg['name_strong'] and not q_imo_listed and not one_word and primary:
                        # the screened IMO is on no list and the name is the listed ship's own (current) name:
                        # a same-name ship, or a falsified IMO (shadow fleet). A former name or alias with another
                        # IMO is another ship now carrying that name (the IMO stays with the hull).
                        sc = min(sc, cfg['conflict_review_score'])
                        expl.append(say('imo_conflict_review', q=q_imo, l=c['imo']))
                    else:
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
            if near_imo and ns >= cfg['name_strong']:
                sc = max(sc, cfg['near_imo_name_score'])      # mistyped IMO + the same name: that ship
            elif (not one_word and 80 <= ns < cfg['name_strong'] and len(q_tokens) >= 2
                  and len(''.join(q_tokens)) >= 7 and not imo_conflict(c)
                  and _one_edit(q_norm, VU.norm_name(nm or '')) and
                  VU.name_numbers(q_norm) == VU.name_numbers(VU.norm_name(nm or ''))):
                # a distinctive name of several words with one keying error (letter wrong, missing, extra or
                # two letters swapped): treated as that name, still never confirmed by the name alone
                sc = max(sc, cfg['typo_score'])
                expl.append(say('one_typo'))
            elif one_word:
                # an exact one-word name: a potential match when the name is rare among every ship record held,
                # review when it is a common ship name (many hulls carry it, or a common ship word)
                k = VU.norm_name(nm or '')
                n = max(counts.get(k, 0), counts.get(q_norm, 0), 1)
                if k in common_words or q_norm in common_words:
                    sc = min(sc, cfg['single_word_max'])
                    expl.append(say('single_word_word'))
                elif n >= int(cfg['common_name_hulls']):
                    sc = min(sc, cfg['single_word_max'])
                    expl.append(say('single_word', n=n))
                elif not imo_conflict(c):
                    bonus = max(0.0, sc - ns * cfg['name_weight'])        # same flag / same owner
                    sc = min(ns * cfg['name_weight'], cfg['single_word_rare_score']) + bonus
                    expl.append(say('single_word_rare', n=n))
                else:
                    sc = min(sc, cfg['single_word_max'])
            add(c, min(sc, cfg['name_hit_max']), 'name', expl, matched_name=nm, fields=fields)
            if c['watchlist_id'] in hits:
                hits[c['watchlist_id']]['name_sim'] = max(hits[c['watchlist_id']].get('name_sim') or 0, ns)

    # ---- layer 3: owner / operator / manager
    owner_hits = []
    if query['owner'] and screen_party:
        try:
            for ph in screen_party(query['owner']) or []:
                s = float(ph.get('score') or 0)
                if s >= low:
                    owner_hits.append({'query': query['owner'], 'name': ph.get('name'), 'score': round(s, 1),
                                       'tier': ph.get('tier') or tier_of(s, th),
                                       'list_type': list_category(ph.get('list_type_raw') or ph.get('list_type')),
                                       'list_type_raw': ph.get('list_type_raw') or ph.get('list_type'),
                                       'source': ph.get('source'), 'watchlist_id': ph.get('watchlist_id')})
        except Exception as e:
            logger.warning(f'[VESSELS] owner screening failed: {e}')
            warnings.append(say('w_owner_unavailable'))
        # one hit per listed owner: the same organisation on several lists (or under several spellings of the
        # same name) is one decision, with the number of list records behind it
        from screening.vessel_store import party_key as _pk
        by_owner = {}
        for o in sorted(owner_hits, key=lambda o: -o['score']):
            k = _pk(o['name'])
            if k in by_owner:
                by_owner[k]['records'] += 1
            else:
                by_owner[k] = dict(o, records=1)
        owner_hits = list(by_owner.values())

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
        view = VS.merge_group([m for m in members if VP.alerts(m.get('provenance') or VP.SANCTION)] or members)
        for m in members:                       # port-state-control records of the same ship: risk, not a hit
            if not VP.alerts(m.get('provenance') or VP.SANCTION):
                risk_records[m['watchlist_id']] = m
        gclass = max((m.get('provenance') or VP.SANCTION for m in members
                      if VP.alerts(m.get('provenance') or VP.SANCTION)), key=lambda x: VP.ORDER[x], default=VP.SANCTION)
        if links is not None:
            view['parties'] = [p for m in members for p in links.get(m['watchlist_id'], [])] or view['parties']
        h = dict(best_h)
        expl = list(h['explanation'])
        for _, other in items[1:]:
            for e in other['explanation']:
                if e['code'] not in {x['code'] for x in expl}:
                    expl.append(e)
        if any(p.get('party_listed') and p.get('role') not in VS.NOT_CONTROL_ROLES for p in view['parties']):
            expl.append(say('owner_listed'))
        if len(view['sources']) > 1:
            expl.append(say('several_lists', n=len(view['sources'])))
        if q_name and best_h.get('layer') == 'identifier' and h['score'] >= cfg['mmsi_score'] - 1:
            # the ship is confirmed by its identifier: is the entered name one of its names (official or known)?
            gns, _gnm, _ = best_name(q_name, view.get('names') or [view.get('name')], cfg)
            if gns < cfg['renamed_below']:
                expl.append(say('renamed', l=view.get('name') or '', q=q_name))
                kind = next((k for k, code in (('IMO', 'same_imo'), ('MMSI', 'same_mmsi'), ('CALLSIGN', 'same_callsign'))
                             if any(e['code'] == code for e in expl)), 'IMO')
                h['entered_name_differs'] = {'entered': q_name, 'listed': view.get('name'), 'identifier': kind}
        if best_h.get('layer') == 'identifier' and h['score'] >= th[2]:
            # confirmed by the identifier: the name-only caveats (one-word names) do not apply
            expl = [e for e in expl if not e['code'].startswith('single_word')]
        kn = {n for m in members for n in m.get('known_names') or []}
        if kn and h.get('matched_name') in kn:
            expl.append(say('known_name'))
            h['known_name'] = h.get('matched_name')
        h['explanation'] = expl
        h.update({k: view.get(k) for k in ('group_key', 'sources', 'member_ids', 'list_types', 'name', 'imo',
                                           'mmsi', 'call_sign', 'flag', 'flags_past', 'type', 'year_built',
                                           'gross_tonnage', 'measures', 'parties', 'previous_names',
                                           'risk_score', 'list_type', 'regimes')})
        h['provenance'] = gclass
        h['list_type'] = list_category(h.get('list_type'))          # categories only, never a list's name
        h['list_types'] = sorted({list_category(x) or 'OTHER' for x in h.get('list_types') or []})
        h['watchlist_id'] = best_c['watchlist_id']
        h['source'] = best_c['source']
        h['names'] = view.get('names')
        h['flags_all'] = view.get('flags_all')
        h['alert_type'] = 'ban' if gclass == VP.BAN else 'sanction'
        if h['alert_type'] == 'ban':
            h['explanation'].insert(0, say('ban_record'))
        h['listed_key'] = VS.listed_key(h)
        h['listed_fp'] = VS.listed_fingerprint(h)
        h.pop('names', None)
        h.pop('flags_all', None)
        merged.append(h)
    # equal scores: a ship whose own (primary) name matched before one matched through an alias
    # equal scores, in order: the ship whose own IMO is the screened IMO (a record may also list another
    # ship's IMO), the closer name, a ship whose own (primary) name matched before an alias, then a stable key
    merged.sort(key=lambda h: (-h['score'], bool(q_imo) and h.get('imo') != q_imo, -(h.get('name_sim') or 0),
                               VU.norm_name(h.get('matched_name')) != VU.norm_name(h.get('name')),
                               str(h.get('group_key'))))

    # ---- whitelist (cleared false matches): suppressed while nothing changed on either side
    qkey = VU.query_key(q_name, q_imo, q_mmsi, query['flag'])
    qfp = VS.query_fingerprint(query)
    if whitelist is None and conn is not None:
        whitelist = VS.whitelist_for(conn, qkey)
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
        if top.get('entered_name_differs'):
            lines.append(say('r_name_differs'))
            risk += rw['name_differs']
    if owner_hits:
        lines.append(say('r_owner_listed'))
        risk += rw['owner_listed']
    psc = sorted({d for c in risk_records.values() for d in (c.get('risk_datasets') or [])})
    if psc:
        lines.append(say('r_psc', n=len(psc)))
        risk += rw['psc'] + (rw['psc_repeated'] if len(psc) >= 3 else 0)
    if any((c.get('provenance') == VP.INTEL) for c in risk_records.values()):
        lines.append(say('r_intel'))
        risk += rw['intel']

    for h in merged + suppressed:
        h['tier'] = tier_of(h['score'], th)
    alerts = [h for h in merged if h['score'] >= low and h['alert_type'] == 'sanction'][:max_hits]
    # a ban / exclusion reached only through a common one-word name (ATLANTIC, MARINA) is too weak to alert:
    # it is not a sanctions listing, and many ships carry the name - shown with the names below the threshold
    def _generic_ban(h):
        return h.get('layer') == 'name' and any(e['code'] in ('single_word', 'single_word_word')
                                                for e in h['explanation'])
    ban_hits = [h for h in merged if h['score'] >= low and h['alert_type'] == 'ban' and not _generic_ban(h)][:max_hits]
    near = [{'name': h['name'], 'matched_name': h['matched_name'], 'score': h['score'],
             'explanation': h['explanation'], 'watchlist_id': h['watchlist_id']}
            for h in merged if h['score'] < low or (h['alert_type'] == 'ban' and _generic_ban(h))][:5]
    # the name given without a hull number (ADRIAN DARYA, DREAM): the numbered listed ships of that name are
    # shown so the officer can ask which hull it is - never alerted (another number is another ship)
    related = []
    if q_name and not VU.name_numbers(q_norm):
        qw = VU.name_words(q_norm)
        for h in merged:
            if h['score'] >= low:
                continue
            hn = VU.norm_name(h.get('matched_name') or h['name'])
            if VU.name_numbers(hn) and VU.name_words(hn) == qw:
                related.append({'name': h['name'], 'matched_name': h.get('matched_name'), 'imo': h.get('imo'),
                                'flag': h.get('flag'), 'watchlist_id': h['watchlist_id'],
                                'provenance': h.get('provenance'), 'regimes': h.get('regimes') or []})
    score = alerts[0]['score'] if alerts else 0.0
    if owner_hits:
        score = max(score, max(o['score'] for o in owner_hits) * cfg['owner_weight'])
    tier = tier_of(score, th) if (alerts or owner_hits) else 'CLEAR'
    if tier in ('BELOW', 'CLEAR') and ban_hits:
        # a ban / exclusion alerts for review, never as a sanctions match
        tier, score = 'LOW', max(score, low)
    if tier == 'BELOW':
        tier = 'CLEAR'
    return {'query': query, 'warnings': warnings, 'tier': tier, 'score': round(score, 1), 'hits': alerts,
            'ban_hits': ban_hits, 'related_hulls': related[:12], 'similar_names': similar[:8],
            'owner_hits': owner_hits, 'risk': {'score': int(min(risk, 100)), 'lines': lines}, 'near': near,
            'suppressed': [{'name': h['name'], 'imo': h.get('imo'), 'score': h['score'], 'tier': h['tier'],
                            'listed_key': h['listed_key'], 'watchlist_id': h['watchlist_id'],
                            'whitelisted': h['whitelisted'], 'explanation': h['explanation']}
                           for h in suppressed],
            'query_key': qkey, 'query_fp': qfp, 'thresholds': thresholds}


_LEGAL_FORMS = (('LIMITED', 'LTD'), ('COMPANY', 'CO'), ('CORPORATION', 'CORP'), ('INCORPORATED', 'INC'),
                ('L L C', 'LLC'))


def owner_variants(name):
    """Comparable forms of a company name with its legal form spelt both ways ('SKADI LTD' / 'SKADI LIMITED')."""
    from screening.vessel_store import party_key
    k = party_key(name)
    raw = re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9\u0600-\u06ff]+', ' ',
                                      re.sub(r'[(][^)]*[)]', ' ', str(name or '')).upper())).strip()
    out = {k, raw}                       # accents stripped / as the SQL key writes them
    for base in list(out):
        for long_, short in _LEGAL_FORMS:
            for a, b in ((long_, short), (short, long_)):
                if re.search(r'\b%s$' % a, base):
                    out.add(re.sub(r'\b%s$' % a, b, base))
    return sorted(x for x in out if x)


def exact_owner_records(conn, name, limit=5):
    """Active list records (not ships) whose name is the declared owner's, legal form aside. The person / entity
    engine groups records sharing a name, so a company named like one of its ships can hide behind the ship."""
    if conn is None or not name:
        return []
    keys = owner_variants(name)
    if not keys:
        return []
    from screening.vessel_store import read_rows
    # cx_party_key() is the SQL twin of party_key and is indexed (20261120b_vessel_owner_index.sql)
    rows = read_rows(conn, """SELECT id, full_name, source, list_type FROM screening_watchlist
                              WHERE cx_party_key(full_name) = ANY(%s) AND is_active = 1
                                AND coalesce(entity_type, '') NOT IN ('VESSEL', 'INDIVIDUAL')
                              ORDER BY id LIMIT %s""", (keys, limit)) or []
    # an acronym or other alias the list gives for the company (IRISL): exact alias, any case
    # (aliases is a JSON list; the trigram index on aliases serves the ILIKE)
    raw = re.sub(r'\s+', ' ', str(name or '')).strip()
    if 2 <= len(raw) <= 120 and '%' not in raw and '_' not in raw:
        rows += [r for r in read_rows(conn, """SELECT id, full_name, source, list_type FROM screening_watchlist
                                               WHERE aliases ILIKE %s AND is_active = 1
                                                 AND coalesce(entity_type, '') NOT IN ('VESSEL', 'INDIVIDUAL')
                                               ORDER BY id LIMIT %s""", ('%"' + raw.replace('"', '') + '"%', limit)) or []
                 if r['id'] not in {x['id'] for x in rows}]
    return rows


def list_category(lt):
    from screening.vessel_store import list_category as _lc
    return _lc(lt)


def party_screener(conn=None):
    """screen_party callable backed by the person / entity engine (company screening, no media), plus an exact
    lookup of the owner's name among the listed organisations."""
    def _run(name):
        from screening.routes import get_engine
        eng = get_engine()
        res = eng.screen_person(name=name, entity_type='ENTITY', include_media=False)
        out = []
        for m in (res or {}).get('matches') or []:
            if str(m.get('entity_type') or '').upper() == 'VESSEL':
                continue        # a ship is not an owner; vessel hits come from layers 1-2
            out.append({'name': m.get('full_name') or m.get('name'), 'score': m.get('match_score') or 0,
                        'tier': (m.get('decision') or {}).get('tier'), 'list_type': list_category(m.get('list_type')),
                        'list_type_raw': m.get('list_type'),
                        'source': m.get('source') or m.get('list_source'),
                        'watchlist_id': m.get('id') or m.get('entity_id')})
        db = conn
        if db is None:
            try:
                from database.db import get_db
                db = get_db()
            except Exception:
                db = None
        have = {o['watchlist_id'] for o in out}
        for r in exact_owner_records(db, name):
            if r['id'] not in have:
                out.append({'name': r['full_name'], 'score': 100.0, 'tier': None,
                            'list_type': list_category(r.get('list_type')), 'list_type_raw': r.get('list_type'),
                            'source': r.get('source'), 'watchlist_id': r['id'], 'exact': True})
        out.sort(key=lambda o: -float(o.get('score') or 0))
        return out[:10]
    return _run


def decision(res):
    """The screening's outcome in three words, for the Gold Set gate, the API and bulk summaries:
       'match'    an alert that identifies a listed ship or a listed owner (CONFIRMED / POTENTIAL tier)
       'review'   an alert an analyst must look at, but that does not identify a hull (LOW tier)
       'no_match' nothing at or above the alert threshold (risk indicators never count)
    Returns (decision, imo of the top listed ship or None, score)."""
    hits = res.get('hits') or []
    owners = res.get('owner_hits') or []
    if not hits and not owners and res.get('ban_hits'):
        b = res['ban_hits'][0]
        return 'review', b.get('imo'), float(res.get('score') or 0)
    top = hits[0] if hits else None
    best_t = top['tier'] if top else 'BELOW'
    owner_t = owners[0]['tier'] if owners else 'BELOW'
    rank = {'CONFIRMED': 3, 'POTENTIAL': 2, 'LOW': 1, 'BELOW': 0}
    t = max(best_t, owner_t, key=lambda x: rank.get(x, 0))
    if rank.get(t, 0) == 0:
        return 'no_match', None, float(res.get('score') or 0)
    dec = 'match' if rank[t] >= 2 else 'review'
    # the ship is named only when a ship hit decides the outcome (an owner hit alone names no hull)
    imo = top.get('imo') if top and rank.get(best_t, 0) >= rank[t] else None
    return dec, imo, float(res.get('score') or 0)
