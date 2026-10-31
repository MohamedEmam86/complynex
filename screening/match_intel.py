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
Match intelligence: how an experienced screening analyst decides whether a
name hit is the listed person.

Three pieces, all pure functions except the candidate search:

1. ``name_match(query, listed)`` — token-by-token alignment of two names after
   Arabic/Latin normalisation. Each element is weighted by rarity (name_idf),
   coverage is measured BOTH ways (how much of the listed name is in the query
   and how much of the query is in the listed name), order and first/family
   name agreement are checked. A two-word listed name inside a four-word
   customer name is therefore a partial match, not a 100% hit.

2. ``identity_verdict(...)`` / ``decide(...)`` — secondary identifiers settle
   what names cannot: an Egyptian national ID encodes birth date, governorate
   and gender; an exact ID match confirms, a different valid ID contradicts.
   Without an ID on the listed record the decision rests on the name and the
   country / nationality, as agreed with Compliance (2026-10-21): country
   agreement adds weight, a different or missing nationality never lowers the
   name score. CONFIRMED_HIT is reserved for a hit where an IDENTIFIER agrees
   (national ID, date / year of birth, passport) and nothing contradicts it.
   Without an identifier match the engine's highest label is POTENTIAL match:
   a human decides.

3. ``search_internal(table, name)`` — candidate recall for the internal lists
   (asset-freeze orders, local terrorist lists, internal PEPs). Replaces the
   old "whole query string contained in the record" ILIKE, which missed every
   customer whose ID name is longer than the listed name and every spelling
   variant of hamza / taa marbuta / alef maqsura.
"""
import json
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- normalisation
from screening import company_match as _cm   # P3-6 company words
from screening import name_variants as _nv   # P3-7 / P3-8 Franco-Arabic and dialect spellings

_AR_DIACRITICS = re.compile(r'[ً-ْٰـ]')
_ARABIC = re.compile(r'[؀-ۿ]')
_PARTICLES = {'ال', 'بن', 'ابن', 'بنت', 'ابو', 'عبد', 'ال', 'al', 'el', 'bin', 'ben', 'ibn',
              'abu', 'abou', 'abo', 'abd', 'abdel', 'abdul', 'abdal', 'يل'}
# European name particles and their Arabic renderings (Alfred de Zayas = آلفرد د زایاس). They are KEPT as
# name elements with a low weight, not deleted: Van / Thi are Vietnamese middle names, Du a Chinese surname,
# Di Maria is not Maria. A Latin particle and its Arabic rendering count as the same element.
_SOFT_PARTICLE_GROUPS = (('de', 'di', 'du', 'da', 'د', 'دي', 'دو', 'دا'), ('dos', 'das', 'دوس', 'داس'),
                         ('van', 'فان'), ('von', 'فون'), ('der', 'دير'), ('del', 'della', 'ديل'))
# legal-form words in company names carry no identity (شركة ... ش.م.م / ... LLC)
_LEGAL_FORMS = {'شركه', 'شركة', 'ش', 'م', 'ذ', 'ق', 'مؤسسه', 'منشاه', 'co', 'company', 'llc', 'ltd', 'limited',
                'inc', 'corp', 'corporation', 'sae', 's', 'a', 'e', 'plc', 'llp', 'gmbh', 'sa', 'sarl', 'fzco',
                'fze', 'the', 'and', 'for', 'of', 'و', 'junior', 'jr', 'snr', 'jnr', 'ii', 'iii', 'جونيور',
                # titles
                'دكتور', 'الدكتور', 'مهندس', 'المهندس', 'الحاج', 'الحاجه', 'لواء', 'اللواء', 'المستشار',
                'mr', 'mrs', 'ms', 'dr', 'eng', 'haj', 'hajj', 'sheikh'}
# Arabic sound classes for phonetic equality of one element (ث/س/ص, ذ/ز/ظ, ...)
_AR_SOUND = str.maketrans({'ث': 'س', 'ص': 'س', 'ذ': 'ز', 'ظ': 'ز', 'ض': 'د', 'ط': 'ت',
                           'ق': 'ك', 'غ': 'خ', 'ح': 'ه', 'ع': 'ا', 'ء': 'ا', 'ؤ': 'و', 'ئ': 'ي'})
_LATIN_CANON = [
    # generic spelling rules first: ph = f (Mostapha), doubled letters (Wahhab, Hassan)
    (r'ph', 'f'), (r'([a-z])\1+', r'\1'),
    (r'\b(mo|mu)ha?mm?[ae]d\b', 'mohamed'), (r'\bahm[ae]d\b', 'ahmed'), (r'\bma[hk]m[ou]+d\b', 'mahmoud'),
    (r'\b(mo|mu|mou)st?[ae]fa\b', 'mostafa'), (r'\bh[ou]ss?[ae]i?n\b', 'hussein'), (r'\bh[ae]ss?an\b', 'hassan'),
    (r'\b(a|e)l[iy]\b', 'ali'), (r'\baly\b', 'ali'), (r'\by[ou]ss?[eo]f\b', 'youssef'), (r'\bkh?al[ei]d\b', 'khaled'),
    (r'\b(g|j)amal\b', 'gamal'), (r'\bibrah[ie]m\b', 'ibrahim'), (r'\bism[ae]e?il\b', 'ismail'),
    (r'\b(o|u)sa?ma\b', 'osama'), (r'\bom[ae]r\b', 'omar'), (r'\bs[ae]y+[ie]?d\b', 'sayed'),
    (r'\beb?rahim\b', 'ibrahim'), (r'ou', 'u'), (r'ee', 'i'), (r'oo', 'u'),
]


# first parts of "... ad-Din" compound names (Salah ad-Din, Seif ad-Din, Nour ad-Din ...)
_DIN_HEADS = ('salah|slah|sala|seif|saif|sayf|sif|nur|nor|ala|iz|ez|shams|gamal|jamal|kamal|nasr|naser|nasir|'
              'sharaf|badr|zein|zain|zin|taj|tag|fakhr|fakhar|hosam|husam|emad|imad|baha|mohy|muhy|mohi|muhi|'
              'mohyi|muhyi|sad|nizam|jalal|galal|khair|kheir|khayr|siraj|serag|burhan|qutb|kutb|shihab|shehab|'
              'rukn|diya|dia|sam|sayed|ghias|ghiyas|ghiath|ghiyath|ghus|ghaus|nazir|qamar|wahid|nagm|najm|'
              'hesam|hisham|saf|safi|alam|tag|shuja|zahir|zaher|nasser')


def is_arabic(text):
    return bool(_ARABIC.search(str(text or '')))


# Persian / Urdu / Kurdish letters (lists such as OpenSanctions carry names in these scripts) -> the Arabic
# letter an Arabic reader would write. Without this they were stripped as "not Arabic" and صدیق read as صد ق.
_FA_TO_AR = str.maketrans({'ی': 'ي', 'ې': 'ي', 'ے': 'ي', 'ۍ': 'ي', 'ێ': 'ي', 'ٸ': 'ي', 'ک': 'ك', 'ڪ': 'ك',
                           'گ': 'ج', 'ڳ': 'ج', 'پ': 'ب', 'چ': 'ج', 'ڤ': 'ف', 'ڥ': 'ف', 'ژ': 'ج', 'ہ': 'ه',
                           'ھ': 'ه', 'ۀ': 'ه', 'ە': 'ه', 'ۃ': 'ه', 'ٹ': 'ت', 'ڈ': 'د', 'ڑ': 'ر', 'ں': 'ن',
                           'ڵ': 'ل', 'ۆ': 'و', 'ۇ': 'و', 'ۈ': 'و', 'ۋ': 'و', 'ٶ': 'و', 'ڕ': 'ر', 'ڎ': 'د'})


def _split_glued(t):
    """Two names typed without a space before a compound: محمدعبد العزيز,
    محمدعبدالعزيز, احمدابوبكر -> محمد عبد...  The family name العبد, and words
    where the compound does not start a name, are left alone."""
    words = t.split()
    out = []
    for k, w in enumerate(words):
        nxt = words[k + 1] if k + 1 < len(words) else ''
        m = re.search('(عبد|ابو)', w[2:])
        if m:
            i = m.start() + 2
            head, rest = w[:i], w[i + 3:]
            if head not in ('ال',) and not head.endswith('ال') and (
                    len(rest) >= 3 or (rest == '' and nxt.startswith('ال'))):
                out.extend([head, w[i:]])
                continue
        out.append(w)
    return ' '.join(out)


# "X Allah" compounds (Nasrallah, Fadlallah, Khairallah, Fathallah): written glued or split, in any
# vowel (Nasrullah, Nasrollah). They are one name element; the part before Allah alone is another name
# (Nasr is not Nasrallah). Abd Allah keeps its own handling (Abd + Allah).
_ALLAH_HEAD_STOP = {'abd', 'abdul', 'abdel', 'abdal', 'abdoul', 'abu', 'abou', 'abo', 'bin', 'ben', 'ibn',
                    'el', 'al', 'ul', 'abdu'}
_ALLAH_HEAD_STOP_AR = {'عبد', 'ابو', 'بن', 'ابن', 'بنت', 'ال'}
# first parts of the common "X Allah" names. A split "X الله" is glued only after one of these: any other
# word before الله is a separate element (a name with a part left out, محمد احمد الله, stays three elements)
_ALLAH_HEADS_AR = {'نصر', 'فضل', 'خير', 'جاد', 'عطا', 'عطاء', 'فتح', 'سعد', 'حمد', 'نعمت', 'نعمه', 'رزق', 'ضيف',
                   'عوض', 'حسب', 'جار', 'فرج', 'شكر', 'هبه', 'هبت', 'منه', 'كرم', 'نور', 'سيف', 'روح', 'ولي',
                   'حب', 'ثناء', 'عزت', 'ذكر', 'خلف', 'دخيل', 'مال', 'رحمه', 'رحمت', 'فيض', 'قدر', 'شرف', 'بركه',
                   'حجت', 'حبيب', 'اسد', 'عبيد', 'عزيز', 'حيات', 'عنايت', 'سميع', 'ضياء', 'قدرت', 'امان', 'كليم',
                   'ذبيح', 'جند', 'حزب', 'انصار', 'ثار', 'لطف', 'فيض', 'وجه', 'حرز', 'جبر'}
_ALLAH_HEADS_LAT = {'nasr', 'fadl', 'fadel', 'khair', 'kheir', 'khayr', 'kher', 'gad', 'jad', 'ata', 'fath', 'fat',
                    'saad', 'sad', 'hamd', 'hamad', 'nimat', 'nemat', 'neamat', 'rizk', 'rizq', 'rezk', 'deif', 'daif',
                    'dhaif', 'awad', 'hasab', 'gar', 'jar', 'farag', 'faraj', 'shukr', 'shokr', 'heba', 'hiba', 'hibat',
                    'minat', 'karam', 'nour', 'nur', 'seif', 'saif', 'sayf', 'ruh', 'rouh', 'wali', 'waly', 'hab',
                    'hob', 'sana', 'thana', 'ezzat', 'izzat', 'zikr', 'zekr', 'khalaf', 'dakhil', 'mal', 'rahmat',
                    'rahma', 'faid', 'feid', 'qadr', 'kadr', 'sharaf', 'baraka', 'hojat', 'hujjat', 'habib', 'asad',
                    'obaid', 'ubaid', 'ubayd', 'aziz', 'hayat', 'inayat', 'enayat', 'sami', 'zia', 'ziya', 'qudrat',
                    'aman', 'kalim', 'zabih', 'jund', 'hizb', 'ansar', 'lutf', 'wajh', 'jabr', 'gabr'}
_LAT_ALLAH_SPLIT = re.compile(r'\b([a-z]{2,}) (allah|alla|ullah|ulla|ollah|alah|ulah|olah)\b')
_LAT_ALLAH_STEM = re.compile(r'^([a-z]{3,}?)[aeiou]?l{1,2}ah$')
_AR_ALLAH_SPLIT = re.compile(r'(?<![ء-ي])([ء-ي]{2,})\s+الله(?![ء-ي])')


def _glue_allah_lat(t):
    # "Nasr Allah" is written as the glued form a Latin writer uses ("Nasrallah"); glued spellings are
    # left as written (Saifullah stays close to a letter-by-letter Arabic rendering سايفوللاح)
    return _LAT_ALLAH_SPLIT.sub(lambda m: m.group(1) + m.group(2)
                                if re.sub(r'(.)\1+', r'\1', m.group(1)) in _ALLAH_HEADS_LAT
                                or m.group(1) in _ALLAH_HEADS_LAT else m.group(0), t)


def _glue_allah_ar(t):
    return _AR_ALLAH_SPLIT.sub(lambda m: m.group(1) + 'الله'
                               if m.group(1).replace('ة', 'ه') in _ALLAH_HEADS_AR else m.group(0), t)


def _allah_stem(t):
    """'nasralah' -> 'nasr', 'نصرالله' -> 'نصر'; None when t is not an X-Allah compound."""
    if is_arabic(t):
        return t[:-4] if t.endswith('الله') and len(t) >= 6 else None
    m_ = _LAT_ALLAH_STEM.match(t)
    return m_.group(1) if m_ and m_.group(1) not in _ALLAH_HEAD_STOP and not m_.group(1).startswith('abd') \
        else None


def normalize(text):
    """One canonical spelling for comparison (both scripts)."""
    t = str(text or '').strip()
    if not t:
        return ''
    if is_arabic(t):
        t = _AR_DIACRITICS.sub('', t)
        t = t.translate(_FA_TO_AR)
        t = re.sub('[إأآٱ]', 'ا', t)
        t = t.replace('ة', 'ه').replace('ى', 'ي')
        # colloquial contraction عبال... = عبد ال... (عبالعزيز = عبد العزيز)
        t = re.sub('عبال(?=[ء-ي]{2,})', 'عبد ال', t)
        # Abdul written letter by letter from a Latin source (ابدول مانان = Abdul Manan)
        t = re.sub(r'(?<![ء-ي])(?:ابدو?ل+ا[هح]?ي?|عبدو?ل+ا[هح]?ي|عبدول+ا[هح]?)(?![ء-ي])', 'عبد الله', t)   # Abdullahi
        t = re.sub(r'(?<![ء-ي])(?:ابدول|ابدل|ابديل|ابد|عبدول|عبدل)(?![ء-ي])', 'عبد', t)
        t = re.sub(r'(?<![ء-ي])(?:ابدول|ابدو|عبدول)(?=[ء-ي]{3,})', 'عبد ', t)     # ابدولحاميد = Abdulhamid
        # a letter typed three times or more (سيييد) is a slip: Arabic never writes it
        t = re.sub(r'([ء-ي])\1{2,}', r'\1', t)
        t = _split_glued(t)
        # fused compounds: عبدالرحمن / ابوبكر -> عبد الرحمن / ابو بكر
        t = re.sub(r'\b(عبد|ابو)(?=ال|[ء-ي]{3,})', r'\1 ', t)
        t = _glue_allah_ar(t)
        t = re.sub(r'[^ء-ي\s]', ' ', t)
    else:
        t = _nv.latin(t.lower())       # Franco-Arabic digits, accents, dialect spellings (name_variants.py)
        t = re.sub(r"['`’‘ʿʾ´]", '', t)
        t = re.sub(r"[\-\.]", ' ', t)
        # every spelling of Abd-Allah (Abdallah, Abdullah, Abdullahi, Abdalla, Abdula, Abd Allah) -> one form
        t = re.sub(r'\babd ?[aeiu]?l{1,2}ah?i?\b', 'abd alah', t)
        # Abd al-Aal (Abdelaal, Abd El Aal): "aal" would collapse to "al" and read as the article
        t = re.sub(r'\babd ?(?:[aeu]l ?)?aal\b', 'abd eal', t)
        t = re.sub(r'\b(?:[ae]l ?)?aal\b', 'eal', t)
        # Abd + el/ul assimilated to the next letter: Abdellatif = Abd Latif, Abdessalam = Abd Salam,
        # Abdallah / Abdullah = Abd Lah (the doubled letter would otherwise be collapsed into "atif")
        t = re.sub(r'\babd ?[aeu]([lnrstdz])\1', r'abd \1', t)
        # glued "... el-Din" compounds: Salaheldin, Seifeldin, Noureddine = Salah / Seif / Nour + Din
        t = re.sub(r'\b(abdul|abdel|abdal|abd)(?=[a-z]{3,})', r'\1 ', t)
        t = re.sub(r'\b(abu|abou)(?=[bcdfghjklmnpqrstvwxz][a-z]{3,})', r'\1 ', t)
        # every spelling of Allah after Abd (Abdallah, Abdullah, Abdullahi, Abdalah, Abdalla) -> one form
        t = re.sub(r'\b(abd|abdul|abdel|abdal) ([aeiu]?l+ahi?)\b', 'abd alah', t)
        t = _glue_allah_lat(t)
        t = re.sub(r'[^a-z\s]', ' ', t)
        for pat, rep in _LATIN_CANON:
            t = re.sub(pat, rep, t)
        # "... ad-Din" compounds, glued or not, in any spelling (Salaheldin, Salah Eddine, Salahudin,
        # Ezeldin, Nour Eldin) -> first part + din; only after a known first part (not LinkedIn, Geraldine)
        t = re.sub(r'\b(' + _DIN_HEADS + r') ?(?:[aeiu]l?)?d(?:in|ine|en|ein)\b', r'\1 din', t)
        t = re.sub(r'\b(?:eldin|eldine|elden|edin|edine|udin|aldin|adin)\b', 'din', t)
    return re.sub(r'\s+', ' ', t).strip()


# The generic Latin spelling rules above also apply to the stop-word lists, so
# a form like "LLC" (normalised to "lc" by the doubled-letter rule) is still
# recognised and dropped.
_LEGAL_FORMS = _LEGAL_FORMS | {normalize(x) for x in _LEGAL_FORMS}
_PARTICLES = _PARTICLES | {normalize(x) for x in _PARTICLES}
_SOFT_PARTICLE = {}
for _gi, _grp in enumerate(_SOFT_PARTICLE_GROUPS):
    for _x in _grp:
        _SOFT_PARTICLE[_x] = _gi
        _SOFT_PARTICLE[normalize(_x)] = _gi
SOFT_PARTICLE_WEIGHT = 1.0
# honorifics / ranks written BEFORE a name (د/ ، المهندس ، الشيخ ، اللواء ، Dr ، Sheikh ...). Only dropped at
# the start of the name and only while two elements remain: الشيخ / الحاج / الامير are also family names.
_TITLES = {normalize(x) for x in (
    'د', 'دكتور', 'الدكتور', 'دكتورة', 'الدكتورة', 'م', 'مهندس', 'المهندس', 'مهندسة', 'المهندسة',
    'ا', 'أ', 'استاذ', 'الاستاذ', 'الأستاذ', 'استاذة', 'الاستاذة', 'الأستاذة', 'شيخ', 'الشيخ', 'الشيخة',
    'حاج', 'الحاج', 'حاجة', 'الحاجة', 'لواء', 'اللواء', 'عميد', 'العميد', 'عقيد', 'العقيد', 'مقدم', 'المقدم',
    'الرائد', 'النقيب', 'مستشار', 'المستشار', 'المستشارة', 'سفير', 'السفير', 'السفيرة',
    'الامير', 'الأمير', 'الاميرة', 'الأميرة', 'النائب', 'النائبة', 'محاسب', 'المحاسب',
    'كابتن', 'الكابتن', 'فضيلة', 'سيادة', 'معالي', 'سعادة', 'القس', 'الانبا', 'الأنبا',
    'dr', 'doctor', 'prof', 'professor', 'eng', 'engineer', 'mr', 'mrs', 'ms', 'miss', 'sir',
    'sheikh', 'shaikh', 'sheik', 'shaykh', 'haj', 'hajj', 'hajji', 'hadj', 'gen', 'general', 'col', 'colonel',
    'maj', 'major', 'capt', 'captain', 'lt', 'brig', 'judge', 'counsellor', 'amb', 'ambassador', 'prince',
    'princess', 'lord', 'lady', 'mme', 'mlle', 'madame', 'monsieur', 'senator', 'sen', 'hon', 'rev',
    'مس', 'مستر', 'مدام', 'لورد', 'اللورد', 'سيناتور', 'السيناتور', 'مسز', 'حاجي', 'حاجى', 'الحاجي',
    'انجينئر', 'انجينير', 'مولوي', 'مولانا', 'maulavi', 'maulvi', 'mawlawi', 'maulana', 'mawlana')} - {''}


_TITLE_ABBREV = {normalize(x) for x in ('د', 'م', 'ا', 'أ', 'dr', 'eng', 'mr', 'mrs', 'ms', 'prof', 'capt', 'col',
                                          'gen', 'lt', 'maj', 'brig', 'amb')} - {''}


def _drop_titles(a, b):
    # leading titles of name `a` (list of (element, raw form)): abbreviations (د/ م/ Dr) while one element
    # remains, title words (الشيخ، اللواء ...) while two remain - they can also be a family name - and
    # never when name `b` starts with the same element (then they simply match)
    while a and a[0][1] in _TITLES and not (b and b[0][0] == a[0][0]):
        if len(a) > 2 or (len(a) > 1 and a[0][1] in _TITLE_ABBREV):
            a = a[1:]
        else:
            break
    return a


def _uncomma(name, arabic_comma=True):
    # 'SURNAME, Given Names' (list format) -> 'Given Names SURNAME'. The Arabic comma form (Surname، Given)
    # is read on listed names only: a customer writes "محمد علي، القاهرة" (name, then a place)
    s = str(name or '')
    if s.count(',') == 1 and not is_arabic(s):
        head, tail = [x.strip() for x in s.split(',')]
        if head and tail:
            return f'{tail} {head}'
    if arabic_comma and s.count('،') == 1 and ',' not in s and is_arabic(s):
        head, tail = [x.strip() for x in s.split('،')]
        if head and tail and not re.search(r'\d', tail):
            return f'{tail} {head}'
    return s

def tokens(text):
    """Identity-bearing elements of a name, in order, particles dropped and
    the leading ال of a family element removed (الشاذلي == شاذلي)."""
    return [t for t, _ in _tokens_raw(text)]


def _tokens_raw(text):
    """tokens() with each element's normalised form before ال / el was removed
    (a typo can move the ال: اسليد = السيد, اليشخ = الشيخ)."""
    out = []
    for tok in normalize(text).split():
        raw = tok
        if tok in _PARTICLES or tok in _LEGAL_FORMS:
            continue
        if is_arabic(tok) and tok.startswith('ال') and len(tok) > 4:
            tok = tok[2:]
        if not is_arabic(tok) and tok.startswith(('el', 'al')) and len(tok) > 5:
            tok = tok[2:]
        out.append((tok, raw))
    return out


def _weight(tok):
    if len(tok) == 1 and tok not in _SOFT_PARTICLE:
        return 0.6          # an initial (W., M.): it can confirm, it cannot identify
    if tok in _SOFT_PARTICLE:
        return SOFT_PARTICLE_WEIGHT   # de / van / di: part of the name, carries little identity
    try:
        from screening import name_idf
        w = name_idf.weight(tok)
    except Exception:
        w = 6.0
    return max(0.6, min(float(w), 12.0))


# --------------------------------------------------------------------------- Latin <-> Arabic
_XS_DICT = None
_AR_TO_KEY = str.maketrans({'ب': 'b', 'ت': 't', 'ث': 's', 'ج': 'g', 'ح': 'h', 'خ': 'k', 'د': 'd', 'ذ': 'z',
                            'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'x', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z',
                            'ع': '', 'غ': 'g', 'ف': 'f', 'ق': 'k', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
                            'ه': 'h', 'و': '', 'ي': '', 'ا': '', 'ء': '', 'ئ': '', 'ؤ': '', 'ة': ''})
# most likely Arabic letter for a Latin consonant (recall only; scoring uses keys)
_LAT_TO_AR = [('sh', 'ش'), ('kh', 'خ'), ('gh', 'غ'), ('th', 'ث'), ('dh', 'ذ'), ('ou', 'و'), ('oo', 'و'),
              ('ee', 'ي'), ('b', 'ب'), ('t', 'ت'), ('g', 'ج'), ('j', 'ج'), ('h', 'ه'), ('d', 'د'),
              ('r', 'ر'), ('z', 'ز'), ('s', 'س'), ('f', 'ف'), ('q', 'ق'), ('k', 'ك'), ('l', 'ل'),
              ('m', 'م'), ('n', 'ن'), ('w', 'و'), ('y', 'ي'), ('i', 'ي'), ('u', 'و'), ('o', 'و'),
              ('a', 'ا'), ('e', ''), ('p', 'ب'), ('v', 'ف'), ('c', 'ك'), ('x', 'كس')]


def _xs_dict():
    """Latin element -> Arabic elements, learned from records that carry both
    (scripts/build_latin_arabic_dict.py). Missing file -> empty dictionary."""
    global _XS_DICT
    if _XS_DICT is None:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'latin_arabic_dict.json')
        try:
            with open(path, encoding='utf-8') as f:
                _XS_DICT = json.load(f)
        except Exception:
            _XS_DICT = {}
    return _XS_DICT


def _xs_key(t):
    """Consonant key shared by both scripts (vowels dropped, sound classes merged)."""
    if is_arabic(t):
        k = t[:-1] + ('' if t.endswith('ه') and len(t) > 2 else t[-1]) if t else ''
        k = k.translate(_AR_TO_KEY)
    else:
        k = t.lower()
        for a, b in (('sh', 'x'), ('kh', 'k'), ('gh', 'g'), ('th', 's'), ('dh', 'z'), ('ph', 'f'),
                     ('q', 'k'), ('c', 'k'), ('j', 'g'), ('v', 'f'), ('p', 'b')):
            k = k.replace(a, b)
        k = re.sub('[aeiouwy]', '', k)
        if k.endswith('h') and len(k) > 2:
            k = k[:-1]
    return re.sub(r'(.)\1+', r'\1', k)


_XS_CONS = {'ب': '(?:b|p|v)', 'ت': 't', 'ث': '(?:th|s|t)', 'ج': '(?:g|j|dj|dg|ch|tch|tsh|zh)', 'ح': 'h', 'خ': '(?:kh|k|h|ch|x)',
            'د': 'd', 'ذ': '(?:dh|z|d|th)', 'ر': 'r', 'ز': '(?:z|s)', 'س': '(?:s|c)', 'ش': '(?:sh|ch|sch|s|x)',
            'ص': 's', 'ض': '(?:d|dh|z)', 'ط': 't', 'ظ': '(?:z|dh|d)', 'غ': '(?:gh|g|r)', 'ف': '(?:f|v)',
            'ق': '(?:q|k|g|c)', 'ك': '(?:ck|k|c|q)', 'ل': 'l', 'م': 'm', 'ن': 'n', 'ه': 'h'}
_ONE_LAT = str.maketrans({'b': 'ب', 'd': 'د', 'f': 'ف', 'g': 'ج', 'h': 'ه', 'j': 'ج', 'k': 'ك', 'l': 'ل',
                         'm': 'م', 'n': 'ن', 'r': 'ر', 's': 'س', 't': 'ت', 'z': 'ز'})
_ALLAH = {'alah', 'lah', 'ulah', 'elah', 'ilah', 'alh'}


def _ar_pattern(ar):
    """Regular expression of the Latin spellings an Arabic element can have: consonants as written,
    long vowels (ا و ي) required, ع / ء free, a short vowel allowed between consonants."""
    cache = _ar_pattern.__dict__.setdefault('cache', {})
    if ar in cache:
        return cache[ar]
    parts, n = [], len(ar)
    for i, ch in enumerate(ar):
        first, last = i == 0, i == n - 1
        if i and ch == ar[i - 1] and ch not in 'هاوي':
            # a doubled letter in a foreign name written in Arabic (ناسسيم = Nassim, يننا = Inna): the Latin
            # side collapses doubled letters, so one letter is enough here
            parts.append('')
            continue
        if ch == 'ش' and i and ar[i - 1] == 'ت':
            parts[-1] = '(?:tsh|tch|ch|c|tz|ts)'      # تش = ch (Chuck = تشاك، Lamichhane = لاميتشهان)
            p = '' if last else '[aeiou]?'
            parts.append(p)
            continue
        if ch == 'ا':
            p = '[aeiou]?' if first else ('(?:a|e|o|ah)' if last else '(?:a|e|o|u)')
        elif ch == 'و':
            p = '(?:w|v|u|o)[aeiou]?' if first else '(?:o|u|w|v|ow|aw|ew|uw|wa|we|wi|wo|wu|va|ve|vi|vo)'
        elif ch == 'ي':
            p = '(?:y|i|j|e)[aeiou]?' if first else ('(?:i|y|e|a|ie|ey|ei|iy|ay|ai)' if last
                                             else '(?:i|e|y|j|ei|ey|ie|ai|ay|ya|ye|yi|iy|ja|je)')
        elif ch == 'ع':
            p = '[aeiou]{0,2}'
        elif ch in 'ءئؤ':
            p = '[aeiouyw]?'
        elif ch == 'ه' and last and n > 2:
            p = '(?:a|ah|eh|e|at|et|h)?'
        elif ch in _XS_CONS:
            if not last:
                p = _XS_CONS[ch] + '[aeiou]?'
            elif i and ar[i - 1] in 'اوي':
                p = _XS_CONS[ch] + 'e?'          # a silent final e after a long vowel (Pierre, Rachide, Amine = امين)
            else:
                # a silent final e only when no Latin vowel stands before the consonant: "-ine" carries a
                # long i the Arabic lacks (Houcine / Hassine are حسين, not حسن; Amine is not امن)
                p = '(?:' + _XS_CONS[ch] + '|(?<![aeiou])' + _XS_CONS[ch] + 'e)'
        else:
            p = ''
        parts.append(p)
    try:
        rx = re.compile(''.join(parts))
    except re.error:
        rx = None
    if len(cache) < 50000:
        cache[ar] = rx
    return rx


def _xs_phonetic(lat, ar):
    if ar == 'الله':
        return lat in _ALLAH
    if ar == 'دين':
        return lat in ('din', 'deen', 'den', 'dine')
    if len(ar) < 2 or len(lat) < 2 or len(ar) > 15 or len(lat) > 2 * len(ar) + 4 or re.search('[عءئؤ]{2,}', ar):
        return False      # nonsense / hostile input: no expensive pattern
    rx = _ar_pattern(ar)
    return bool(rx and (rx.fullmatch(lat) or ('x' in lat and rx.fullmatch(lat.replace('x', 'ks')))))


_AR_LETTER_NAMES = {'a': ('اي', 'ايه', 'ا'), 'b': ('بي',), 'c': ('سي',), 'd': ('دي',), 'e': ('اي', 'ي'),
                    'f': ('اف',), 'g': ('جي',), 'h': ('اتش', 'اش', 'اتش'), 'i': ('اي', 'اى'), 'j': ('جي', 'جيه', 'جاي'),
                    'k': ('كيه', 'كي', 'كاي'), 'l': ('ال', 'يل'), 'm': ('ام', 'م', 'يم'), 'n': ('ان', 'ن'),
                    'o': ('او',), 'p': ('بي',), 'q': ('كيو',), 'r': ('ار',), 's': ('اس', 'يس'), 't': ('تي',),
                    'u': ('يو',), 'v': ('في',), 'w': ('دبليو', 'دبليوو'), 'x': ('اكس',), 'y': ('واي', 'وي'),
                    'z': ('زد', 'زي')}


_LOOSE = str.maketrans({'k': 'K', 'g': 'K', 'h': 'K', 'x': 'S', 's': 'S', 'z': 'S', 't': 'T', 'd': 'T',
                        'b': 'B', 'f': 'B', 'v': 'B', 'p': 'B', 'q': 'K', 'c': 'K', 'j': 'K'})


def loose_ratio(lat, ar):
    """How alike the consonant skeletons of a Latin and an Arabic element are, with the sounds languages
    write differently merged (Jorge / خورخي, Chuck / تشاك). 1.0 when one side has no consonant to compare."""
    kl = re.sub(r'(.)\1+', r'\1', _xs_key(lat).translate(_LOOSE))
    ka = re.sub(r'(.)\1+', r'\1', _xs_key(ar).translate(_LOOSE))
    if not kl or not ka:
        return 1.0
    import difflib
    return difflib.SequenceMatcher(None, kl, ka).ratio()


_LAT_LONG_END = re.compile(r'(?:[aeiou][bcdfghjklmnpqrstvwxz]e|(?:ei|ai|ee|ie|ii|ey|ay)[bcdfghjklmnpqrstvwxz]e?)$')


# letters a Latin spelling cannot tell apart: علاء and الاء are both Alaa, so neither vetoes the other
_HOMOPHONE = str.maketrans({'ع': 'ا', 'ء': 'ا', 'ئ': 'ا', 'ؤ': 'ا', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ة': 'ه'})


def _long_end_veto(lat, ar):
    # only when the Arabic has no long vowel at all after its first letter (حسن، امن): a long vowel elsewhere
    # (مايكل = Michail) means the Latin vowel is written, just not right before the last letter
    return len(lat) >= 2 and len(ar) >= 3 and ar[-1] in _XS_CONS and ar[-1] != 'ه' \
        and not any(ch in 'اويىءئؤع' for ch in ar[1:]) and bool(_LAT_LONG_END.search(lat))


def _xs_same(lat, ar):
    """Same name element written in Latin and in Arabic? (_xs_same_raw plus two vetoes)"""
    s = _xs_same_raw(lat, ar)
    if not s or len(lat) < 2 or len(ar) < 3:
        return s
    # 1. the Latin ends in a long vowel + consonant (-ine, -ein, -een) and the Arabic has no long vowel
    #    there: Hassine / Houcine are حسين, not حسن (also when the dictionary learned such a pair)
    if _long_end_veto(lat, ar):
        return 0.0
    # 2. look-alike names across scripts: when the Latin spelling is, by far, the usual spelling of another
    #    short, well-known Arabic name with (almost) the same letters, it is that name (Hamed = حامد, not
    #    احمد; Hosni = حسني, not حسين) - the same rule as for two Arabic names
    cands = _xs_dict().get(lat)
    if cands and len(ar) <= 5:
        total = sum(c for _, c in cands)
        top, top_c = cands[0]
        mine = sum(c for a, c in cands if a == ar)
        if top != ar and top.translate(_HOMOPHONE) != ar.translate(_HOMOPHONE) \
                and (total >= 8 or (mine == 0 and total >= 3)) and top_c / total >= 0.5 \
                and mine / total < 0.2 and len(top) == len(ar) \
                and (sorted(top) == sorted(ar) or _osa(top, ar) <= 1) and _attested(top) and _attested(ar):
            return 0.0
    return s


def _drops_initial_vowel(lat, ar):
    """The Arabic starts with a written alif before a consonant (احمد، امجد، اشرف) but the Latin starts
    with that consonant: the Latin is another name (Hamid is حامد / حميد, not احمد)."""
    return 3 <= len(ar) <= 5 and ar[0] in 'اأإآ' and ar[1] not in 'اويىءئؤل' \
        and len(lat) >= 2 and lat[0] not in 'aeiouy' and lat[1] in 'aeiou' and _attested(ar)


def _xs_phonetic_score(lat, ar):
    """Score of a spelling that fits the Arabic by sound (no learned pair): 0.95 when it is a clean,
    standard transliteration of a well-known name (every consonant the same sound class, the first
    letter in place: Hamid = حامد, Majid = ماجد, Saeed = سعيد), else 0.85."""
    if _drops_initial_vowel(lat, ar):
        return 0.0
    if not _xs_phonetic(lat, ar):
        return 0.0
    if 3 <= len(ar) <= 6 and len(lat) >= 4 and loose_ratio(lat, ar) == 1.0 and _attested(ar):
        return 0.95
    return 0.85


def _xs_same_raw(lat, ar):
    """Same name element written in Latin and in Arabic?"""
    if len(lat) == 1:
        return 0.9 if ar in _AR_LETTER_NAMES.get(lat, ()) or ar == lat.translate(_ONE_LAT) else 0.0
    cands = _xs_dict().get(lat)
    if cands:
        total = sum(c for _, c in cands)
        for a, c in cands:
            if a == ar or (len(a) == len(ar) and a.translate(_AR_SOUND) == ar.translate(_AR_SOUND)):
                if (c < 10 or c / total < 0.1) and loose_ratio(lat, ar) < 0.7:
                    break        # a rare learned pair whose sounds do not agree: a list alias of someone else
                if c / total >= 0.1:
                    return 0.95
                # a less frequent learned pair that is also a clean standard transliteration of a
                # well-known name keeps full strength (Majid = ماجد although lists write مجيد more often)
                return 0.95 if c / total >= 0.05 and _xs_phonetic_score(lat, ar) >= 0.95 else 0.85
        if lat in _canon_names():
            return 0.0          # a standard spelling of another well-known name (Mahmoud is محمود, not محمد)
        ps = _xs_phonetic_score(lat, ar)
        if ps:
            return ps           # the spelling fits this Arabic name too (Hamid = حامد as well as حميد)
        if total >= 8:
            return 0.0          # a well-known element that is written otherwise (Mohamed is not محمود)
    ps = _xs_phonetic_score(lat, ar)
    if ps:
        return ps
    if _drops_initial_vowel(lat, ar):
        return 0.0
    kl, ka = _xs_key(lat), _xs_key(ar)
    if len(kl) >= 2 and kl == ka:
        return 0.85
    if min(len(kl), len(ka)) >= 4 and _osa(kl, ka) <= 1:
        return 0.75
    return 0.0


def to_arabic(name):
    """Most likely Arabic spelling of a Latin name (used to search Arabic-only lists)."""
    out = []
    for t in tokens(name):
        if is_arabic(t):
            out.append(t)
            continue
        if t in ('alah', 'din'):
            out.append('الله' if t == 'alah' else 'الدين')
            continue
        if _allah_stem(t) and not _xs_dict().get(t):
            out.append(to_arabic(_allah_stem(t)) + 'الله')
            continue
        cands = _xs_dict().get(t)
        if cands:
            out.append(cands[0][0])
            continue
        w, i = '', 0
        while i < len(t):
            for lat, ar in _LAT_TO_AR:
                if t.startswith(lat, i):
                    w += ar
                    i += len(lat)
                    break
            else:
                i += 1
        out.append(w)
    return ' '.join(x for x in out if x)


def to_arabic_display(name):
    """Arabic rendering that keeps the compound particles a reader writes
    (Abdelaziz -> عبد العزيز, El Sayed -> السيد) — for searching the news,
    where the name must look the way an Arabic article prints it."""
    words = normalize(name).split()
    out, i = [], 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w in ('abd', 'abdel', 'abdul', 'abdal') and nxt:
            core = to_arabic(nxt)
            out.append('عبد ' + ('ال' + core if not core.startswith('ال') else core))
            i += 2
            continue
        if w in ('el', 'al') and nxt:
            core = to_arabic(nxt)
            out.append(core if core.startswith('ال') else 'ال' + core)
            i += 2
            continue
        if w in ('abu', 'abou', 'abo') and nxt:
            out.append('ابو ' + to_arabic(nxt))
            i += 2
            continue
        if w in _PARTICLES or w in _LEGAL_FORMS:
            i += 1
            continue
        out.append(to_arabic(w))
        i += 1
    return ' '.join(x for x in out if x)


def _same_token(a, b, first=False):
    """Are two name elements the same name, allowing for spelling?

    Arabic is stricter than Latin on purpose: inserting a long vowel changes
    the name (محمد/محمود, حسن/حسين, سعد/سعيد), so Arabic only tolerates a
    same-length substitution or swap, or near-identity on long elements.
    """
    if a == b:
        return 1.0
    if a in _SOFT_PARTICLE or b in _SOFT_PARTICLE:
        # name particles only match each other (de = د, van = فان), never a name element
        if a in _SOFT_PARTICLE and b in _SOFT_PARTICLE and _SOFT_PARTICLE[a] == _SOFT_PARTICLE[b] \
                and is_arabic(a) != is_arabic(b):
            return 0.95
        if is_arabic(a) != is_arabic(b):
            lat, arb = (b, a) if is_arabic(a) else (a, b)
            if len(lat) == 1:
                return _xs_same(lat, arb)               # an initial and its Arabic letter name: D. = دي.
        return 0.0
    if _cm.same_class(a, b):                          # generic company words: Trade = Trading = تجارة
        return 1.0
    if is_arabic(a) != is_arabic(b):                 # Latin vs Arabic
        lat, arb = (b, a) if is_arabic(a) else (a, b)
        sl, sa = _allah_stem(lat), _allah_stem(arb)
        if sl and sa:
            # Nasrallah = نصرالله when Nasr = نصر. A spelling that fits the first part counts in full: the
            # compound itself is the identity (lists write Nasr for ناصر too, which weakens Nasr = نصر alone)
            s = _same_token(sl, sa)
            return 0.95 if s >= 0.85 else s
        s = _xs_same(lat, arb)
        if not s and _nv.canon(lat) != lat and not _long_end_veto(lat, arb):   # dialect spelling (Mehmet)
            s = _xs_same(_nv.canon(lat), arb)
        return s
    ar = is_arabic(a) and is_arabic(b)
    if not is_arabic(a) and not is_arabic(b):
        sa_, sb_ = _allah_stem(a), _allah_stem(b)
        if sa_ and sb_:
            st = 1.0 if sa_ == sb_ else _same_token(sa_, sb_)
            return 0.95 if st >= 0.85 else st      # Nasrullah = Nasrallah (the linking vowel varies)
    if not ar and a in _canon_names() and b in _canon_names():
        return 0.0     # two different well-known names (Mohamed / Mahmoud share a consonant skeleton)
    if not ar and _nv.canon(a) == _nv.canon(b) and (_nv.canon(a) != a or _nv.canon(b) != b):
        return 0.95    # dialect spelling of the same name: Houcine = Hussein, Hacen = Hassan, Mehmet = Mohamed
    if ar and a.translate(_AR_SOUND) == b.translate(_AR_SOUND):
        return 0.95
    if ar and min(len(a), len(b)) >= 4 and len(a) == len(b) and a[:-1] == b[:-1] \
            and {a[-1], b[-1]} <= {'ا', 'ي'}:
        return 0.95                                   # مصطفا / مصطفى
    if ar and _long_vowel_variant(a, b):
        return 0.9     # ميرفت / مرفت، شيرين / شرين، جيهان / جهان (Turkish / Persian names, the long i is optional)
    if ar and len(a) == len(b) and _eg_variant(a) == _eg_variant(b):
        return 0.9     # Egyptian spelling of the same name (ثامر / تامر، عثمان / عتمان، رءوف / رؤوف، مدحت / مدحه)
    if ar and len(a) == len(b) <= 5 and _attested(a) and _attested(b) and (first or sorted(a) != sorted(b)):
        return 0.0     # two short, real, known names one letter apart (احمد / حامد، سامي / سامح، احمد / محمد) are
                       # different names; only two swapped letters inside the chain pass as a typo (حنفي / حفني)
    try:
        from rapidfuzz import fuzz
        r = fuzz.ratio(a, b)
    except Exception:
        import difflib
        r = difflib.SequenceMatcher(None, a, b).ratio() * 100
    if ar:
        if len(a) == len(b) >= 4 and _osa(a, b) <= 1:
            return 0.88
        if min(len(a), len(b)) >= 6 and r >= 88:
            return 0.85
        return 0.0
    if min(len(a), len(b)) >= 4 and r >= 85:
        return 0.9
    if min(len(a), len(b)) >= 5 and _osa(a, b) <= 1:
        return 0.88
    sa, sb = _skeleton(a), _skeleton(b)
    if len(sa) >= 3 and sa == sb:
        return 0.85
    return 0.0


_CANON_NAMES = None
ATTESTED_WEIGHT = 9.0      # name_idf weight below which an element is a name seen many times in the lists


_EG_VARIANT = str.maketrans({'ث': 'ت', 'ذ': 'د', 'ظ': 'ض', 'ء': 'ا', 'ؤ': 'ا', 'ئ': 'ا'})


def _long_vowel_variant(a, b):
    """Same Arabic name with and without a long i (ي) right after the first letter: ميرفت / مرفت، نيرمين /
    نرمين، جيهان / جهان. Only there, and only on names of 4+ letters: elsewhere a long vowel makes another
    name (محمد / محمود، حسن / حسين، سعد / سعيد)."""
    if abs(len(a) - len(b)) != 1:
        return False
    s, l = (a, b) if len(a) < len(b) else (b, a)
    return len(s) >= 4 and l[0] == s[0] and l[1] == 'ي' and l[2:] == s[1:] and s[1] not in 'اوي'


def _eg_variant(t):
    t = t.translate(_EG_VARIANT)
    return t[:-1] + 'ت' if t.endswith('ه') else t


def _distinct_names(a, b):
    """Two first names that are both real, known names in the same script (احمد / حامد, Mohamed / Mahmoud).
    An unknown or foreign spelling is not enough to call two people different."""
    if is_arabic(a) and is_arabic(b):
        return _attested(a) and _attested(b)
    if not is_arabic(a) and not is_arabic(b):
        return a in _canon_names() and b in _canon_names()
    return False


def _attested(t):
    try:
        from screening import name_idf
        return name_idf.weight(t) < ATTESTED_WEIGHT
    except Exception:
        return False


def _canon_names():
    global _CANON_NAMES
    if _CANON_NAMES is None:
        _CANON_NAMES = {normalize(rep) for pat, rep in _LATIN_CANON if pat.startswith(r'\b')}
    return _CANON_NAMES


def _skeleton(t):
    s = re.sub('[aeiouwy]', '', t).replace('kh', 'k').replace('gh', 'g').replace('q', 'k')
    return re.sub(r'(.)\1+', r'\1', s)


def _osa(a, b):
    """Optimal-string-alignment distance (Levenshtein + adjacent swaps)."""
    try:
        from rapidfuzz.distance import OSA
        return OSA.distance(a, b)
    except Exception:
        pass
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


# --------------------------------------------------------------------------- name match
def _swap_only(a, b):
    """Same letters with exactly one adjacent swap (a typing slip), length >= 5."""
    return len(a) == len(b) >= 5 and a != b and sorted(a) == sorted(b) and _osa(a, b) == 1


def _pair_score(c, q, cr, qr, ci, qi):
    ct, qt = c[ci], q[qi]
    s = _same_token(ct, qt, first=(ci in (0, len(c) - 1) or qi in (0, len(q) - 1)))
    if s < 0.88 and (cr[ci][1] != ct or qr[qi][1] != qt) and is_arabic(ct) and is_arabic(qt) \
            and _swap_only(cr[ci][1], qr[qi][1]):
        s = 0.88
    if s < 0.85 and is_arabic(ct) != is_arabic(qt) and (cr[ci][1] != ct or qr[qi][1] != qt):
        # a foreign name that only looks like it starts with the article: Elaine / الين, Alexander / الكسندر
        # (the article is removed on one script only when the element is long enough, so compare as written)
        for a, b in ((cr[ci][1], qr[qi][1]), (cr[ci][1], qt), (ct, qr[qi][1])):
            if (a, b) != (ct, qt):
                s = max(s, min(0.85, _same_token(a, b)))
    return s


def _align(c, q, cr, qr):
    """Pair the elements of two names: best-scoring pairs first, the closer position wins a tie. (Taking the
    listed elements in order let an early element take a later element's partner: Inna / SVYATENKO.)"""
    cand = []
    for ci in range(len(c)):
        for qi in range(len(q)):
            s = _pair_score(c, q, cr, qr, ci, qi)
            if s > 0:
                cand.append((-s, abs(ci - qi), ci, qi))
    cand.sort()
    used_c, used_q, pairs = set(), set(), []
    for ns, _, ci, qi in cand:
        if ci in used_c or qi in used_q:
            continue
        used_c.add(ci)
        used_q.add(qi)
        pairs.append((ci, qi, -ns))
    return pairs, _joins(c, q, used_c, used_q, pairs)


def _joins(c, q, used_c, used_q, pairs):
    """One element on one side written as two on the other, across scripts only (Khoshsima / خوش سیما,
    Gulbuddin / غلب الدين, Shamsunnahar / شمس النهار). Returns the extra elements covered: [('c'|'q', i, s)]."""
    extra = []
    for side, one, two, u1, u2 in (('q', c, q, used_c, used_q), ('c', q, c, used_q, used_c)):
        for i in range(len(one)):
            if i in u1:
                continue
            for j in range(len(two) - 1):
                if j in u2 or j + 1 in u2 or is_arabic(two[j]) != is_arabic(two[j + 1]) \
                        or is_arabic(one[i]) == is_arabic(two[j]):
                    continue
                joined = two[j] + two[j + 1]
                if len(joined) < 4 or len(joined) > 24:
                    continue
                s = _same_token(one[i], joined) if side == 'q' else _same_token(joined, one[i])
                if s >= 0.85:
                    u1.add(i)
                    u2.update((j, j + 1))
                    if side == 'q':
                        pairs.append((i, j, s))
                    else:
                        pairs.append((j, i, s))
                    extra.append((side, j + 1, s))
                    break
    return extra


def name_match(query, listed):
    """Analyst-style comparison of two names. Returns a dict with ``score``
    (0-100) and the evidence behind it."""
    qr, cr = _tokens_raw(_uncomma(query, arabic_comma=False)), _tokens_raw(_uncomma(listed))
    qr, cr = _drop_titles(qr, cr), _drop_titles(cr, qr)
    q, c = [t for t, _ in qr], [t for t, _ in cr]
    res = {'score': 0.0, 'q_tokens': q, 'l_tokens': c, 'matched': [], 'missing_from_query': [],
           'extra_in_query': [], 'cov_listed': 0.0, 'cov_query': 0.0, 'order_ok': False,
           'first_ok': False, 'family_ok': False, 'complete': False, 'partial': True}
    if not q or not c:
        return res
    pairs, joined = _align(c, q, cr, qr)
    used = {qi for _, qi, _ in pairs} | {i for side, i, _ in joined if side == 'q'}
    wl = [_weight(t) for t in c]
    wq = [_weight(t) for t in q]
    got_l = sum(wl[ci] * s for ci, qi, s in pairs) + sum(wl[i] * s for side, i, s in joined if side == 'c')
    got_q = sum(wq[qi] * s for ci, qi, s in pairs) + sum(wq[i] * s for side, i, s in joined if side == 'q')
    cov_l = got_l / sum(wl)
    cov_q = got_q / sum(wq)
    qidx = [qi for ci, qi, s in sorted(pairs)]
    order_ok = qidx == sorted(qidx)
    matched_c = {ci for ci, _, _ in pairs} | {i for side, i, _ in joined if side == 'c'}
    first_ok = 0 in matched_c and dict((ci, qi) for ci, qi, _ in pairs).get(0) == 0
    family_ok = (len(c) - 1) in matched_c
    score = 100.0 * (0.55 * cov_l + 0.45 * cov_q)
    if not order_ok:
        score -= 5
    if not first_ok:
        score -= 10
    if len(c) >= 3 and len(q) >= 3 and not family_ok and (len(q) - 1) not in used:
        # neither side's family element is matched: different families
        score = min(score, 74.0)
    complete = (len(matched_c) == len(c) and len(used) == len(q) and order_ok and first_ok)
    missing = [c[i] for i in range(len(c)) if i not in matched_c]
    extra = [q[i] for i in range(len(q)) if i not in used]
    if len(c) >= 3 and len(q) >= 3 and 0 not in matched_c and 0 not in used and _distinct_names(c[0], q[0]):
        # each name starts with a different, known first name (a brother, a cousin): different people
        score = min(score, 74.0)
    elif (len(c) >= 4 and len(q) >= 3 and len(used) == len(q) and order_ok and first_ok and family_ok
            and len(missing) == 1 and 0 < [i for i in range(len(c)) if i not in matched_c][0] < len(c) - 1):
        # the customer left out one middle element (a father's second name / grandfather): a lead to review
        score = max(score, 76.0)
    left_out = missing + extra
    if left_out and all(t in _SOFT_PARTICLE for t in left_out) and \
            min(sum(t not in _SOFT_PARTICLE for t in c), sum(t not in _SOFT_PARTICLE for t in q)) <= 1:
        # the names differ only by a particle and one element is all that is left (Maria / Di Maria,
        # Hai / Van Hai): one given name is not an identity (Isabel Santos = Isabel dos Santos still is)
        score = min(score, 74.0)
    if len(c) >= 3 and len(q) >= 3 and missing and extra:
        # both names carry an element the other lacks at the same place in the
        # chain (a different father / grandfather): different people unless an
        # identifier says otherwise
        score = min(score, 74.0)
    res.update({
        'score': round(max(0.0, min(100.0, score)), 2),
        'matched': [(c[ci], q[qi]) for ci, qi, _ in sorted(pairs)],
        'missing_from_query': missing,
        'extra_in_query': extra,
        'cov_listed': round(cov_l, 3), 'cov_query': round(cov_q, 3),
        'order_ok': order_ok, 'first_ok': first_ok, 'family_ok': family_ok,
        'complete': complete, 'partial': not complete,
    })
    return res


# --------------------------------------------------------------------------- identifiers
_GOVERNORATES = {
    '01': 'Cairo', '02': 'Alexandria', '03': 'Port Said', '04': 'Suez', '11': 'Damietta',
    '12': 'Dakahlia', '13': 'Sharqia', '14': 'Qalyubia', '15': 'Kafr El Sheikh', '16': 'Gharbia',
    '17': 'Monufia', '18': 'Beheira', '19': 'Ismailia', '21': 'Giza', '22': 'Beni Suef',
    '23': 'Fayoum', '24': 'Minya', '25': 'Asyut', '26': 'Sohag', '27': 'Qena', '28': 'Aswan',
    '29': 'Luxor', '31': 'Red Sea', '32': 'New Valley', '33': 'Matrouh', '34': 'North Sinai',
    '35': 'South Sinai', '88': 'Born abroad',
}


def decode_egyptian_nid(nid):
    """14-digit Egyptian national ID -> {'valid', 'dob', 'governorate', 'gender'}.
    Digit 1 = century (2: 1900s, 3: 2000s), 2-7 = YYMMDD, 8-9 = governorate,
    13 = gender (odd male, even female)."""
    d = re.sub(r'\D', '', str(nid or ''))
    out = {'valid': False, 'nid': d}
    if len(d) != 14 or d[0] not in '23' or d[7:9] not in _GOVERNORATES:
        return out
    try:
        y = (1900 if d[0] == '2' else 2000) + int(d[1:3])
        dob = date(y, int(d[3:5]), int(d[5:7]))
    except ValueError:
        return out
    out.update({'valid': True, 'dob': dob.isoformat(), 'year': y,
                'governorate': _GOVERNORATES.get(d[7:9], d[7:9]),
                'gender': 'M' if int(d[12]) % 2 else 'F'})
    return out


def _as_list(v):
    if v is None or v == '':
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v if x not in (None, '')]
    s = str(v).strip()
    if s.startswith('['):
        try:
            return [str(x) for x in json.loads(s) if x]
        except Exception:
            pass
    return [p.strip() for p in re.split(r'[;,|]', s) if p.strip()]


def _years(v):
    ys = set()
    for p in _as_list(v):
        for m in re.findall(r'(19\d{2}|20\d{2})', p):
            ys.add(int(m))
    return ys


_COUNTRY_ALIASES = {
    'eg': 'egypt', 'egy': 'egypt', 'egyptian': 'egypt', 'مصر': 'egypt', 'مصري': 'egypt', 'مصرى': 'egypt',
    'ps': 'palestine', 'palestinian': 'palestine', 'فلسطيني': 'palestine', 'فلسطين': 'palestine',
    'sy': 'syria', 'syrian': 'syria', 'iq': 'iraq', 'iraqi': 'iraq', 'ly': 'libya', 'libyan': 'libya',
    'sd': 'sudan', 'sudanese': 'sudan', 'sa': 'saudi arabia', 'saudi': 'saudi arabia', 'ye': 'yemen',
    'yemeni': 'yemen', 'af': 'afghanistan', 'afghan': 'afghanistan', 'ir': 'iran', 'iranian': 'iran',
    'kp': 'north korea', "democratic people's republic of korea": 'north korea', 'tr': 'turkey', 'qa': 'qatar',
}


def _countries(*vals):
    out = set()
    for v in vals:
        for p in _as_list(v):
            k = p.strip().lower()
            if not k or k in ('na', 'none', 'unknown'):
                continue
            out.add(_COUNTRY_ALIASES.get(k, k))
    return out


def _iso2(*vals):
    """ISO alpha-2 codes in the values (screening/country_codes.py: codes, names, demonyms,
    Arabic). The same file is added by the P2-6 entity-links branch (identical copy)."""
    try:
        from screening.country_codes import to_iso2
        return to_iso2(*vals)
    except Exception:
        return set()


def countries_agree(query_vals, listed_vals):
    """True / False / None (not comparable). RU, Russia, Russian and Russian Federation are
    one country; the older name table still counts as agreement, so nothing that agreed
    before stops agreeing."""
    qi, li = _iso2(*query_vals), _iso2(*listed_vals)
    qn, ln = _countries(*query_vals), _countries(*listed_vals)
    if (qi and li and qi & li) or (qn and ln and qn & ln):
        return True
    if (qi and li) or (qn and ln):
        return False
    return None


# lists kept for Egyptian subjects: their 14-digit numbers are Egyptian national IDs even
# when the record carries no nationality (and even when a typed number does not decode)
EGYPTIAN_SOURCES = {'emlcu', 'internal_blacklist', 'internal_pep'}


def _egyptian_source(source):
    s = str(source or '').strip().lower()
    return s in EGYPTIAN_SOURCES or s.startswith('eg_')


def country_score_adjust(score, submitted_country, candidate_country, bonus=8.0):
    """Engine scoring step for nationality / country: agreement ADDS a bonus,
    a different or missing country leaves the name score unchanged. Lists
    record past and second nationalities inconsistently, and when a record
    has no national ID the decision rests on the name and the country, so
    agreement is a positive factor and disagreement is only shown to the
    analyst — it never hides a name match."""
    if not submitted_country or not candidate_country:
        return score
    sub, cand = str(submitted_country).lower().strip(), str(candidate_country).lower().strip()
    if countries_agree((submitted_country,), (candidate_country,)) or (sub and cand and (sub in cand or cand in sub)):
        return score + bonus
    return score


_ID_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
MIN_ID_LEN = 8           # shorter numbers (registers, old cards) collide across countries


def _id_key(x):
    """An identifier as compared: letters and digits only (Arabic / Persian digits read as
    digits), upper case. Letters are kept: 'RU-123456' is not '123456'."""
    return re.sub(r'[^0-9A-Z]', '', str(x or '').translate(_ID_DIGITS).upper())


def _eg_nids(x):
    """Valid 14-digit Egyptian national IDs written in a value ('29001011234567',
    'NID: 2900101 1234567', Arabic digits)."""
    s = str(x or '').translate(_ID_DIGITS)
    found = set()
    for cand in [re.sub(r'\D', '', s)] + re.findall(r'(?<!\d)[23]\d{13}(?!\d)', s):
        if decode_egyptian_nid(cand).get('valid'):
            found.add(cand)
    return found


def id_relation(query_id, listed_ids, query_country=None, listed_countries=None, listed_source=None):
    """How the customer's ID relates to the IDs on a listed record:
    'match'            both are the same valid Egyptian 14-digit national ID, or the full
                       alphanumeric numbers (>= 8 characters) are equal AND the record's
                       country / nationality agrees with the customer's;
    'match_unverified' equal numbers but the issuing country is not confirmed: supporting
                       evidence only, never CONFIRMED on its own (lists such as OpenSanctions
                       carry ID / register numbers from every country);
    'conflict'         the customer has a valid Egyptian national ID and an Egyptian-side
                       record (Egyptian list, or nationality empty / Egypt) carries a
                       different valid Egyptian national ID - never for a foreign number;
    None               nothing comparable."""
    q = _id_key(query_id)
    if not q:
        return None
    listed = _as_list(listed_ids)
    if not listed:
        return None
    q_eg = q if (q.isdigit() and decode_egyptian_nid(q).get('valid')) else None
    l_eg = set()
    for x in listed:
        l_eg |= _eg_nids(x)
    if q_eg and q_eg in l_eg:
        return 'match'
    eg_src = _egyptian_source(listed_source)
    keys = {_id_key(x) for x in listed}
    keys = {k for k in keys if len(k) >= MIN_ID_LEN and not set(k) <= {'0'}}
    if len(q) >= MIN_ID_LEN and q in keys:
        if eg_src:          # Egyptian list: the number typed exactly as listed (as before)
            return 'match'
        agree = countries_agree((query_country, 'egypt' if q_eg else None), (listed_countries,))
        return 'match' if agree else 'match_unverified'
    if q_eg and l_eg:
        li, ln = _iso2(listed_countries), _countries(listed_countries)
        egyptian_side = eg_src or (not li and not ln) or 'eg' in li or 'egypt' in ln
        return 'conflict' if egyptian_side else None
    return None


def _passports(v):
    return {k for k in (_id_key(x) for x in _as_list(v)) if len(k) >= 6}


def identity_verdict(query_nid=None, query_dob=None, query_country=None,
                     listed_nids=None, listed_dob=None, listed_countries=None, listed_gender=None,
                     query_passport=None, listed_passports=None, listed_source=None):
    """Compare secondary identifiers. Returns {'verdict', 'reasons',
    'identifier_match', 'dob', 'country'}.

    verdict: id_match | id_conflict | gender_conflict | dob_conflict |
             country_conflict | corroborated | unknown
    identifier_match: True when an IDENTIFIER agrees (national ID, birth date
             / year, passport). Country agreement is supporting evidence, not
             an identifier.
    dob / country: 'agree' | 'differ' | None (not comparable).
    """
    reasons, qd = [], decode_egyptian_nid(query_nid) if query_nid else {'valid': False}
    id_support = False
    qp, lp = _passports(query_passport), _passports(listed_passports)
    if qp and lp and qp & lp:
        # a passport number is unique only within its issuing country
        if countries_agree((query_country,), (listed_countries,)):
            return {'verdict': 'id_match', 'reasons': ['passport number matches the listed record'],
                    'identifier_match': True, 'dob': None, 'country': None}
        reasons.append('passport number equals one on the record, issuing country not confirmed '
                       '(supporting evidence only)')
        id_support = True
    rel = id_relation(query_nid, listed_nids, query_country, listed_countries, listed_source)
    if rel == 'match':
        return {'verdict': 'id_match', 'reasons': ['national ID matches the listed record'],
                'identifier_match': True, 'dob': None, 'country': None}
    if rel == 'conflict':
        return {'verdict': 'id_conflict', 'identifier_match': False, 'dob': None, 'country': None,
                'reasons': ['listed record carries a different national ID']}
    if rel == 'match_unverified':
        reasons.append('an ID number on the record equals the customer\'s, issuing country not '
                       'confirmed (supporting evidence only)')
        id_support = True
    # digits of the listed IDs: an Egyptian national ID among them gives gender / birth year
    lids = [re.sub(r'\D', '', x.translate(_ID_DIGITS)) for x in _as_list(listed_nids)]
    lids = [x for x in lids if len(x) >= 6 and not set(x) <= {'0'}]
    # gender: the 13th digit of an Egyptian national ID, on either side
    q_gender = qd.get('gender') if qd.get('valid') else None
    l_gender = None
    for x in lids:
        d = decode_egyptian_nid(x)
        if d.get('valid'):
            l_gender = d['gender']
            break
    if not l_gender and listed_gender:
        g = str(listed_gender).strip().lower()
        l_gender = 'M' if g in ('m', 'male', 'ذكر') else ('F' if g in ('f', 'female', 'انثى', 'أنثى') else None)
    # P3-10: gender is information for the analyst only. It never removes or
    # lowers a hit (lists record it inconsistently, transliteration hides it).
    gender_state = None
    if q_gender and l_gender:
        gender_state = 'agree' if q_gender == l_gender else 'differ'
        if gender_state == 'differ':
            reasons.append('gender differs (information only, does not lower the score)')
    # date of birth: given, or decoded from the customer's national ID
    q_years = _years(query_dob)
    if not q_years and qd.get('valid'):
        q_years = {qd['year']}
    l_years = _years(listed_dob)
    for x in lids:
        d = decode_egyptian_nid(x)
        if d.get('valid'):
            l_years.add(d['year'])
    corroborated, dob_ok = id_support, False
    dob_state = country_state = None
    if q_years and l_years:
        if min(abs(a - b) for a in q_years for b in l_years) > 2:
            return {'verdict': 'dob_conflict', 'identifier_match': False, 'dob': 'differ', 'country': None,
                    'gender': gender_state,
                    'reasons': reasons + [f'birth year differs ({sorted(q_years)[0]} vs {sorted(l_years)[0]})']}
        reasons.append('birth year agrees')
        corroborated = dob_ok = True
        dob_state = 'agree'
    # country / nationality (the decisive check when the record has no ID):
    # agreement supports the match; a difference is reported for the analyst
    # but never counts against the name (people hold or held other
    # nationalities, lists record them inconsistently)
    qc = _countries(query_country, 'egypt' if qd.get('valid') else None)
    lc = _countries(listed_countries)
    agree = countries_agree((query_country, 'egypt' if qd.get('valid') else None), (listed_countries,))
    if agree is True:
        reasons.append('nationality / country agrees')
        corroborated = True
        country_state = 'agree'
    elif agree is False:
        reasons.append(f"nationality differs ({', '.join(sorted(qc))} vs {', '.join(sorted(lc))})")
        country_state = 'differ'
    if not lids and not l_years and not lc:
        reasons.append('listed record has no identifiers: decision rests on the name')
    if corroborated:
        verdict = 'corroborated'
    elif country_state == 'differ':
        verdict = 'country_conflict'
    else:
        verdict = 'unknown'
    return {'verdict': verdict, 'reasons': reasons, 'identifier_match': dob_ok,
            'dob': dob_state, 'country': country_state, 'gender': gender_state}


# --------------------------------------------------------------------------- decision
CONFIRMED = 95.0
POTENTIAL = 80.0
LOW = 75.0


def _listed_name(m, query):
    """The listed name to judge against: the record's form in the query's
    script when it has one, otherwise its other-script form (compared
    element by element across scripts)."""
    names = [m.get('watchlist_name_ar'), m.get('original_name'), m.get('full_name_arabic'),
             m.get('full_name'), m.get('candidate_name')]
    names = [n for n in names if n]
    q_ar = is_arabic(query)
    same = [n for n in names if is_arabic(n) == q_ar]
    if same:
        return same[0]
    return names[0] if names else ''


def _best_listed(m, query):
    names = [m.get('watchlist_name_ar'), m.get('original_name'), m.get('full_name_arabic'),
             m.get('full_name'), m.get('candidate_name')]
    names = [n for n in dict.fromkeys(names) if n and str(n).strip()]
    best = (None, None, False)
    q_ar = is_arabic(query)
    for n in names:
        nm = name_match(query, n)
        cross = is_arabic(n) != q_ar
        if cross:
            nm['score'] = round(nm['score'] * 0.97, 2)   # transliteration is never certain
        if best[1] is None or nm['score'] > best[1]['score'] or (
                nm['score'] == best[1]['score'] and best[2] and not cross):
            best = (n, nm, cross)
    return best


def decide(m, query, national_id=None, dob=None, nationality=None, passport=None):
    """Apply the analyst decision to one match dict (mutates and returns it)."""
    score = float(m.get('match_score') or 0.0)
    original = score
    reasons = []
    # judge against every form the record carries (Arabic original, Latin
    # rendering, aliases) and keep the best: a listed Latin spelling made by
    # a machine must not hide an Arabic original the query matches
    listed, nm, cross = _best_listed(m, query)
    if nm is not None and cross:
        reasons.append('compared across scripts (Latin / Arabic)')
    idv = identity_verdict(
        national_id, dob, nationality,
        m.get('national_id') or m.get('national_id_numbers'),
        m.get('date_of_birth') or m.get('year_of_birth'),
        [m.get('nationality'), m.get('countries'), m.get('country')],
        m.get('gender'),
        query_passport=passport,
        listed_passports=m.get('passport_number') or m.get('passport_numbers') or m.get('passport'),
        listed_source=m.get('source'))
    tier = None
    if idv['verdict'] == 'id_match':
        score, tier = 100.0, 'CONFIRMED'
    elif idv['verdict'] == 'id_conflict':
        score = min(score, LOW + 1)
    elif idv['verdict'] == 'dob_conflict':
        score = min(score - 15, POTENTIAL - 1)
    # (gender is never used to lower a score - P3-10; see identity_verdict)
    # a different nationality (country_conflict) lowers nothing: the name
    # score stands and the analyst sees the difference among the reasons
    reasons += idv['reasons']

    if nm is not None and tier != 'CONFIRMED':
        # the structural name verdict may lower a generous fuzzy score, never raise it
        if nm['score'] < score - 10:
            reasons.append(f"name structure: {nm['score']:.0f}")
            score = (score + nm['score']) / 2
        if nm['partial']:
            if len(nm['l_tokens']) <= 2 and len(nm['q_tokens']) >= 3:
                # a two-word listed name inside a longer name: a lead, not an alert,
                # unless an identifier agrees
                cap = POTENTIAL + 5 if idv['verdict'] == 'corroborated' else POTENTIAL - 1
                score = min(score, cap)
                reasons.append('listed name is a short form inside a longer name')
            if nm['missing_from_query']:
                reasons.append('not in the customer name: ' + ' '.join(nm['missing_from_query'][:4]))
            if nm['extra_in_query']:
                reasons.append('extra in the customer name: ' + ' '.join(nm['extra_in_query'][:4]))
            score = min(score, CONFIRMED - 1)          # a partial name never auto-confirms
        elif len(nm['l_tokens']) < 3:
            score = min(score, CONFIRMED - 1)          # two-word names are too common to confirm
            reasons.append('complete but short name')
        elif cross and idv['verdict'] != 'corroborated':
            score = min(score, CONFIRMED - 1)          # across scripts the name alone does not confirm
            reasons.append('complete match across scripts: confirm with an identifier')
        else:
            reasons.append('complete name match, same order')
    elif nm is None and tier != 'CONFIRMED':
        # different scripts and no same-script form on the record: identifiers decide
        if idv['verdict'] not in ('corroborated',):
            score = min(score, CONFIRMED - 1)
            reasons.append('cross-script match without a corroborating identifier')

    if tier is None and score >= CONFIRMED and not idv.get('identifier_match'):
        # no national ID / date of birth / passport agrees: the engine never
        # confirms on the name (and country) alone — at most a potential match
        score = CONFIRMED - 1
        reasons.append('no identifier match (national ID / date of birth / passport): '
                       'at most a potential match')
    if tier is None:
        if score >= CONFIRMED and idv['verdict'] in ('corroborated', 'unknown', 'country_conflict'):
            tier = 'CONFIRMED'
        elif score >= POTENTIAL:
            tier = 'POTENTIAL'
        elif score >= LOW:
            tier = 'LOW'
        else:
            tier = 'BELOW'
    m['match_score'] = round(max(0.0, min(100.0, score)), 2)
    m['decision'] = {
        'tier': tier, 'original_score': round(original, 2), 'final_score': m['match_score'],
        'identity': idv['verdict'], 'reasons': reasons, 'judged_against': listed,
        'identifier_match': bool(idv.get('identifier_match')),
        'dob': idv.get('dob'), 'country': idv.get('country'), 'gender': idv.get('gender'),
        'name': ({k: nm[k] for k in ('matched', 'missing_from_query', 'extra_in_query',
                                     'cov_listed', 'cov_query', 'order_ok', 'complete')}
                 if nm else None),
    }
    return m


def _dedupe_key(m):
    name = m.get('watchlist_name_ar') or m.get('original_name') or m.get('full_name') or ''
    nid = re.sub(r'\D', '', str(m.get('national_id') or ''))
    return (' '.join(tokens(name)), nid if len(nid) == 14 else '')


def dedupe(matches):
    """One row per listed person: keep the best-scored occurrence and list the
    other sources it also appears in."""
    best, order = {}, []
    # at equal score the official list leads and aggregators become "also
    # listed in": OFAC / UN / EU / UK / EMLCU / internal orders, then copies
    def _rank(x):
        src = str(x.get('source') or '').lower()
        if src.startswith('internal') or src in ('emlcu', 'emlcu_egypt'):
            return 0
        if src in ('un', 'un_consolidated', 'ofac', 'ofac_sdn', 'eu', 'eu_sanctions', 'hmt', 'uk_hmt', 'pma_ps'):
            return 1
        return 2
    for m in sorted(matches, key=lambda x: (-round(float(x.get('match_score') or 0), 1), _rank(x))):
        k = _dedupe_key(m)
        if not k[0]:
            order.append(m)
            continue
        src = f"{m.get('source_name') or m.get('source') or ''} · {m.get('category') or m.get('dataset') or ''}".strip(' ·')
        if k in best:
            also = best[k].setdefault('also_listed_in', [])
            if src and src not in also:
                also.append(src)
            continue
        best[k] = m
        order.append(m)
    return order


def apply_decisions(matches, query, national_id=None, dob=None, nationality=None, passport=None):
    out = []
    for m in matches:
        try:
            out.append(decide(m, query, national_id, dob, nationality, passport))
        except Exception as e:                       # never drop a hit because of this layer
            logger.warning('[MATCH-INTEL] decision failed: %s', e)
            out.append(m)
    # The same listed name often sits on several records (asset-freeze order,
    # terrorist list, semantic index) and only some carry the national ID. If
    # one of them proves a DIFFERENT ID and none proves the same ID, the
    # ID-less copies must not auto-confirm on the name alone.
    by_name = {}
    for m in out:
        k = _dedupe_key(m)[0]
        if k:
            by_name.setdefault(k, []).append(m)
    for k, group in by_name.items():
        ids = {(g.get('decision') or {}).get('identity') for g in group}
        if 'id_conflict' in ids and 'id_match' not in ids:
            for g in group:
                d = g.get('decision') or {}
                if d.get('identity') != 'id_conflict' and d.get('tier') == 'CONFIRMED':
                    g['match_score'] = min(float(g['match_score']), POTENTIAL + 5)
                    d['tier'] = 'POTENTIAL'
                    d['final_score'] = g['match_score']
                    d.setdefault('reasons', []).append(
                        'another record of this listed name carries a different national ID')
    return dedupe(out)


def overall_status(matches):
    tiers = [((m.get('decision') or {}).get('tier'), float(m.get('match_score') or 0)) for m in matches]
    if any(t == 'CONFIRMED' for t, _ in tiers):
        return 'CONFIRMED_HIT'
    top = max([s for _, s in tiers] or [0.0])
    if top >= POTENTIAL:
        return 'POTENTIAL_MATCH'
    if top >= LOW:
        return 'LOW_MATCH'
    return 'CLEAR'


# --------------------------------------------------------------------------- internal list recall
_TRANSLATE = "translate(lower(coalesce({c},'')), 'أإآٱةى', 'اااايهي')"
_COLS_CACHE = {}


def _columns(cur, table):
    if table not in _COLS_CACHE:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
        _COLS_CACHE[table] = {r['column_name'] if isinstance(r, dict) else r[0] for r in cur.fetchall()}
    return _COLS_CACHE[table]


def _recall(cur, table, cols, field, q, limit, raw=False):
    # raw=True: the elements are already in the stored spelling (lower-case
    # Latin as typed) — the list's name_search column is not canonicalised, so
    # 'kouchouk' must be searched as written, not as the canonical 'kuchuk'
    norm_q = list(q) if raw else [normalize(t) for t in q]
    frags = []
    for t in dict.fromkeys(norm_q):
        if t:
            frags.append((t, t if len(t) <= 4 else t[:len(t) - 1]))   # tolerate a changed last letter
    if not frags:
        return []
    ranked = sorted(frags, key=lambda x: -_weight(x[0]))
    distinctive = [f for t, f in ranked if _weight(t) >= 2.5 and len(f) >= 3][:3] or \
                  [f for t, f in ranked if len(f) >= 3][:2] or [ranked[0][1]]
    count_frags = [f for t, f in ranked][:6]
    count_w = [round(_weight(t), 2) for t, f in ranked][:6]
    need = 1 if len(q) <= 1 else 2
    where = ' OR '.join([f'{field} LIKE %s'] * len(distinctive))
    hits = ' + '.join([f'(CASE WHEN {field} LIKE %s THEN 1 ELSE 0 END)'] * len(count_frags))
    # rank by the RARITY of the elements found, not just how many: with a common name ('علي حسن')
    # hundreds of records tie on the count and the LIMIT cut the one carrying the rare element
    weighted = ' + '.join([f'(CASE WHEN {field} LIKE %s THEN {w} ELSE 0 END)' for w in count_w])
    active = 'COALESCE(is_active,1) != 0' if 'is_active' in cols else 'TRUE'
    sql = (f"SELECT * FROM (SELECT *, ({hits}) AS _tok_hits, ({weighted}) AS _tok_w FROM {table} "
           f"WHERE {active} AND ({where})) s WHERE _tok_hits >= %s ORDER BY _tok_w DESC, _tok_hits DESC, length({field}), id LIMIT %s")
    params = ([f'%{f}%' for f in count_frags] + [f'%{f}%' for f in count_frags] + [f'%{f}%' for f in distinctive]
              + [min(need, len(count_frags)), limit])
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def search_internal(conn, table, name, limit=150, min_score=None):
    """Token-based recall + analyst scoring over an internal list table.
    Returns rows (dicts) with ``_match_score`` in 0..1 and ``_name_match``.

    Recall uses the trigram-indexed ``name_search`` column (migration
    20261027_internal_list_search) on the query's most identifying elements,
    then counts how many of its elements each candidate carries. A Latin
    query is also searched through its most likely Arabic spelling, because
    the local lists are Arabic first."""
    if min_score is None:
        min_score = LOW
    q = tokens(name)
    if not q:
        return []
    cur = conn.cursor()
    cols = _columns(cur, table)
    if 'name_search' in cols:
        field = 'name_search'
    else:                                   # before the migration: slower expression
        field = _TRANSLATE.format(c="coalesce(original_name,'') || ' ' || coalesce(full_name,'')")
    q_ar = is_arabic(name)
    rows = {r['id']: r for r in _recall(cur, table, cols, field, q, limit)}
    if not q_ar:
        typed = [w for w in re.sub(r"[^a-z\s]", " ", str(name).lower()).split()
                 if len(w) >= 2 and w not in _PARTICLES and w not in _LEGAL_FORMS]
        if typed and typed != q:
            for r in _recall(cur, table, cols, field, typed, limit, raw=True):
                rows.setdefault(r['id'], r)
        ar = to_arabic(name)
        if ar:
            for r in _recall(cur, table, cols, field, tokens(ar), limit):
                rows.setdefault(r['id'], r)
    out = []
    for r in rows.values():
        primary = r.get('original_name') if q_ar else r.get('full_name')
        forms = [primary, r.get('full_name') if q_ar else r.get('original_name')]
        forms += [a for a in _as_list(r.get('aliases')) if is_arabic(a) == q_ar][:12]
        best = None
        for f in dict.fromkeys(x for x in forms if x):
            nm = name_match(name, f)
            if is_arabic(f) != q_ar:
                nm['score'] = round(nm['score'] * 0.97, 2)       # across scripts
            if best is None or nm['score'] > best['score']:
                best = nm
                if nm['score'] >= 99.9:
                    break
        if best and best['score'] >= min_score:
            r.pop('_tok_hits', None)
            r.pop('name_search', None)
            r['_match_score'] = best['score'] / 100.0
            r['match_score'] = best['score']
            r['_name_match'] = best
            out.append(r)
    out.sort(key=lambda x: -x['_match_score'])
    return out[:100]
