#!/usr/bin/env python3
"""
Gold Set builder — a fixed, versioned set of labelled name pairs used to
measure the screening engine before every change (Phase 0, P0-2).

Every pair is (query, listed, label):
  label = 1  the query is the listed person / entity written another way
             (a Miss if the engine scores it below the alert threshold)
  label = 0  the query is a different person / entity
             (a False Positive if the engine scores it at or above it)

tier = 'core'          realistic for Egyptian customer / ID data -> headline rates and the gate
tier = 'supplementary' hard or exotic forms (Franco-Arabic chat spelling, Maghrebi spelling,
                       Persian / Pashto script, very small categories) -> reported, gated, but
                       kept out of the headline rate

Holdout: ~20 % of BASE NAMES (not pairs) are locked away, chosen with a secret salt
stored next to the data (screening/data/gold/.holdout_salt, never in git), so every
variant of a holdout name is in the holdout and membership cannot be recomputed from
the pair text. Holdout pairs are only ever reported as totals.

Pairs come from the live lists (read-only) and are written to
screening/data/gold/gold_v<N>.jsonl, which is NOT tracked in git because it
holds listed names.

    python scripts/gold_set_build.py --version 1 --review
"""
import argparse
import hashlib
import json
import os
import random
import re
import secrets
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

from screening.match_intel import tokens, normalize, _LEGAL_FORMS  # noqa: E402

OUT_DIR = os.path.join(BASE, 'screening', 'data', 'gold')
PER_CAT = 1900          # ~1,500 dev per category (+/-0.5 % at 1 %); the <1 % target is judged on pooled core pairs
SEED = 20261029

AR_COMMON_FIRST = ['محمد', 'احمد', 'محمود', 'مصطفي', 'علي', 'حسن', 'حسين', 'ابراهيم', 'خالد', 'عمر',
                   'يوسف', 'سيد', 'عادل', 'سامي', 'طارق', 'هشام', 'وليد', 'كريم', 'اسامه', 'ياسر']
# clearly different names that look alike; replacing one by the other = different person
AR_LOOKALIKE = {'محمد': 'محمود', 'محمود': 'محمد', 'حسن': 'حسين', 'حسين': 'حسن', 'سعد': 'سعيد',
                'سعيد': 'سعد', 'احمد': 'حامد', 'حامد': 'احمد', 'عمر': 'عمرو', 'عمرو': 'عمر',
                'كريم': 'كرم', 'سامي': 'سامح', 'سامح': 'سامي', 'جمال': 'كمال', 'كمال': 'جمال',
                'فتحي': 'فوزي', 'فوزي': 'فتحي', 'هشام': 'هاشم', 'عادل': 'عابد', 'ناصر': 'نصر',
                'منير': 'منيب', 'رافت': 'رفعت', 'رفعت': 'رافت', 'مجدي': 'حمدي', 'حمدي': 'مجدي',
                'نبيل': 'نبيه', 'ماجد': 'مجد', 'سمير': 'سمر'}
LOOKALIKE_CAP = 0.15     # no single replacement pair may exceed 15 % of the category
# hamza that is really part of the name
HAMZA = {'احمد': 'أحمد', 'اسامه': 'أسامة', 'اشرف': 'أشرف', 'ايمن': 'أيمن', 'امل': 'أمل', 'انور': 'أنور',
         'اسماء': 'أسماء', 'اميره': 'أميرة', 'امين': 'أمين', 'ابراهيم': 'إبراهيم', 'اسماعيل': 'إسماعيل',
         'ايمان': 'إيمان', 'اسراء': 'إسراء', 'اسلام': 'إسلام', 'ايهاب': 'إيهاب', 'الاء': 'آلاء', 'ادم': 'آدم'}
NO_TAA = {'الله', 'طه', 'عبده', 'ابو', 'وجيه', 'نزيه', 'فقيه', 'نبيه'}
ALEF_MAQSURA_MALE = ('مصطفي', 'موسي', 'عيسي', 'يحيي', 'مرتضي', 'مجتبي')
# only substitutions that really occur in Egyptian records (عثمان/عتمان, ذكي/زكي ...)
SOUND_SUBS = [('عثمان', 'عتمان'), ('ثابت', 'تابت'), ('هيثم', 'هيتم'), ('ذكي', 'زكي'), ('ذكري', 'زكري'),
              ('عبد الظاهر', 'عبد الزاهر'), ('مذكور', 'مزكور'), ('منذر', 'منزر'), ('عبد الرازق', 'عبد الرزاق')]
LAT_SPELL = [(r'\bMohammed\b', 'Mohamed'), (r'\bMuhammad\b', 'Mohamed'), (r'\bMohamed\b', 'Mohammed'),
             (r'\bHussain\b', 'Hussein'), (r'\bHussein\b', 'Hussain'), (r'\bAbdul\b', 'Abdel'),
             (r'\bAbdel\b', 'Abdul'), (r'\bYousef\b', 'Youssef'), (r'\bYusuf\b', 'Youssef'),
             (r'\bMustafa\b', 'Mostafa'), (r'\bAhmad\b', 'Ahmed'), (r'\bAhmed\b', 'Ahmad'),
             (r'\bKhalid\b', 'Khaled'), (r'\bOsama\b', 'Usama'), (r'\bIbrahim\b', 'Ebrahim')]
FRANCO_LAT = {'Hassan': '7assan', 'Hussein': '7ussein', 'Ali': '3ali', 'Omar': '3omar', 'Abdel': '3abdel',
              'Mahmoud': 'Ma7moud', 'Ahmed': 'A7med', 'Mohamed': 'Mo7amed', 'Khaled': '5aled',
              'Saeed': 'Sa3eed', 'Abdallah': '3abdallah', 'Hamdy': '7amdy', 'Fathy': 'Fat7y'}
MAGHREB = {'Mohamed': 'Mouhamed', 'Mohammed': 'Mouhammed', 'Youssef': 'Youcef', 'Hussein': 'Houcine',
           'Hassan': 'Hacen', 'Mustafa': 'Moustapha', 'Mostafa': 'Moustapha', 'Said': 'Saïd'}
CO_FORMS_AR = ['شركة {} ش.م.م', 'شركه {}', '{} ش.م.م', '{} ش.م.ق', 'شركة {}']
CO_FORMS_LAT = ['{} LLC', '{} Co.', '{} Ltd', '{} Company', '{} S.A.E.']
CO_SYN = [('بنك', 'مصرف'), ('مصرف', 'بنك'), ('للتجاره', 'للتجارة والتوزيع'), ('للاستثمار', 'للاستثمارات'),
          ('Bank', 'Banque'), ('Trading', 'Trade'), ('International', 'Intl'), ('Investment', 'Investments')]
CO_GENERIC = {'public', 'joint', 'stock', 'open', 'closed', 'limited', 'company', 'trading', 'group', 'international',
              'holding', 'the', 'and', 'of', 'for', 'al', 'el', 'llc', 'jsc', 'ooo', 'ojsc', 'pjsc', 'zao', 'oao',
              'co', 'ltd', 'inc', 'corporation', 'bank', 'general', 'national', 'state', 'federal', 'scientific',
              'research', 'institute', 'production', 'industrial', 'enterprise', 'shipping', 'maritime'}
NON_ARABIC_SCRIPT = re.compile('[پچژگکیۀٹڈڑںہےۓ]')
ORG_WORDS = re.compile(r'(^|\s)(لل\S+|شركه|مؤسسه|جمعيه|مكتب|مصنع|معرض|الدوليه|للتجاره|مجموعه)(\s|$)')

# Common Egyptian name elements and their usual written Latin form (as on IDs / passports)
EG_LATIN = {
 'محمد':'Mohamed','احمد':'Ahmed','محمود':'Mahmoud','علي':'Ali','حسن':'Hassan','حسين':'Hussein','ابراهيم':'Ibrahim',
 'مصطفي':'Mostafa','السيد':'Elsayed','سيد':'Sayed','عمر':'Omar','عمرو':'Amr','خالد':'Khaled','يوسف':'Youssef',
 'اسماعيل':'Ismail','عادل':'Adel','سامي':'Samy','طارق':'Tarek','هشام':'Hesham','وليد':'Walid','كريم':'Karim',
 'اسامه':'Osama','ياسر':'Yasser','جمال':'Gamal','كمال':'Kamal','فتحي':'Fathy','صلاح':'Salah','سعيد':'Saeed','سعد':'Saad',
 'رمضان':'Ramadan','شعبان':'Shaaban','عبده':'Abdo','عثمان':'Osman','عيد':'Eid','منصور':'Mansour','عاطف':'Atef',
 'عماد':'Emad','ايمن':'Ayman','اشرف':'Ashraf','شريف':'Sherif','هاني':'Hany','تامر':'Tamer','حمدي':'Hamdy','مجدي':'Magdy',
 'نبيل':'Nabil','سمير':'Samir','فاروق':'Farouk','رضا':'Reda','ممدوح':'Mamdouh','مدحت':'Medhat','عصام':'Essam',
 'حسام':'Hossam','هيثم':'Haitham','وائل':'Wael','ماجد':'Maged','سامح':'Sameh','ناصر':'Nasser','منير':'Mounir',
 'رافت':'Raafat','جلال':'Galal','صبري':'Sabry','عزت':'Ezzat','فوزي':'Fawzy','محسن':'Mohsen','عوض':'Awad','حامد':'Hamed',
 'زكريا':'Zakaria','موسي':'Moussa','عيسي':'Eissa','يحيي':'Yehia','زين':'Zein','نور':'Nour','رجب':'Ragab','عرفه':'Arafa',
 'سلامه':'Salama','عطيه':'Attia','حجازي':'Hegazy','انور':'Anwar','توفيق':'Tawfik','جابر':'Gaber','حسني':'Hosny',
 'خليل':'Khalil','رشاد':'Rashad','زكي':'Zaki','سالم':'Salem','سليمان':'Soliman','سليم':'Selim','شوقي':'Shawky',
 'صابر':'Saber','صادق':'Sadek','ضياء':'Diaa','طه':'Taha','عزيز':'Aziz','عمار':'Ammar','فرج':'Farag','فريد':'Farid',
 'فهمي':'Fahmy','قاسم':'Kassem','لطفي':'Lotfy','مبروك':'Mabrouk','متولي':'Metwally','مرسي':'Morsy','مسعود':'Masoud',
 'معتز':'Moataz','مهدي':'Mahdy','نصر':'Nasr','نجيب':'Naguib','هلال':'Helal','وجيه':'Wagih','يسري':'Yousry','يونس':'Younes',
 'بدوي':'Badawy','حسانين':'Hassanein','حسنين':'Hassanein','خلف':'Khalaf','دسوقي':'Desouky','شحاته':'Shehata','جمعه':'Gomaa',
 'حماده':'Hamada','رزق':'Rizk','بيومي':'Bayoumi','عزب':'Azab','شلبي':'Shalaby','سرور':'Sorour','زهران':'Zahran','نجم':'Negm',
 'بدر':'Badr','عرابي':'Orabi','غنيم':'Ghoneim','سلطان':'Soltan','شاكر':'Shaker','منسي':'Mansy','هيكل':'Heikal','عامر':'Amer',
 'فاطمه':'Fatma','مريم':'Mariam','مني':'Mona','هبه':'Heba','ساره':'Sara','نهي':'Noha','ياسمين':'Yasmine','امل':'Amal',
 'اسماء':'Asmaa','ايمان':'Eman','سعاد':'Soad','نجلاء':'Naglaa','رحاب':'Rehab','سحر':'Sahar','هدي':'Hoda','دعاء':'Doaa',
 'شيماء':'Shaimaa','اميره':'Amira','ناديه':'Nadia','سميره':'Samira','زينب':'Zeinab','عائشه':'Aisha','خديجه':'Khadiga',
 'هند':'Hend','ريهام':'Reham','رانيا':'Rania','داليا':'Dalia','مروه':'Marwa','نيرمين':'Nermine','غاده':'Ghada','لبني':'Lobna',
 'سلمي':'Salma','جنه':'Gana','حبيبه':'Habiba','ملك':'Malak','روان':'Rawan','اسراء':'Esraa','الاء':'Alaa','علاء':'Alaa',
 'عبد الله':'Abdallah','عبد الرحمن':'Abdelrahman','عبد العزيز':'Abdelaziz','عبد الحميد':'Abdelhamid','عبد الفتاح':'Abdelfattah',
 'عبد الرحيم':'Abdelrahim','عبد الحليم':'Abdelhalim','عبد السلام':'Abdelsalam','عبد الناصر':'Abdelnasser','عبد المنعم':'Abdelmoneim',
 'عبد الغني':'Abdelghany','عبد الكريم':'Abdelkarim','عبد الحكيم':'Abdelhakim','عبد الهادي':'Abdelhady','عبد الوهاب':'Abdelwahab',
 'عبد الجواد':'Abdelgawad','عبد الستار':'Abdelsattar','عبد العال':'Abdelaal','عبد اللطيف':'Abdellatif','عبد الباسط':'Abdelbasset',
 'عبد القادر':'Abdelkader','عبد المجيد':'Abdelmeguid','عبد العظيم':'Abdelazim','عبد الرازق':'Abdelrazek','عبد الحي':'Abdelhay',
 'عبد الصمد':'Abdelsamad','عبد المطلب':'Abdelmotaleb','عبد الخالق':'Abdelkhalek','عبد الرؤوف':'Abdelraouf','عبد الشافي':'Abdelshafy',
 'عبد الواحد':'Abdelwahed','عبد التواب':'Abdeltawab','عبد الحافظ':'Abdelhafez','عبد الدايم':'Abdeldayem','عبد الغفار':'Abdelghaffar',
 'ابو بكر':'Aboubakr','نور الدين':'Noureldin','عز الدين':'Ezzeldin','حسام الدين':'Hossameldin','صلاح الدين':'Salaheldin',
 'جمال الدين':'Gamaleldin','بهاء الدين':'Bahaaeldin','سيف الدين':'Seifeldin','علاء الدين':'Alaaeldin','محيي الدين':'Mohieldin',
}


def plain(n):
    n = re.sub('[إأآ]', 'ا', n or '').replace('ة', 'ه').replace('ى', 'ي')
    return re.sub(r'\s+', ' ', re.sub(r'[^ء-ي\s]', ' ', n)).strip()


def units(n):
    """Name elements with compounds kept whole: عبد X, ابو X, X الدين, X الله."""
    out = []
    for w in n.split():
        if out and (out[-1] in ('عبد', 'ابو') or w in ('الدين', 'الله', 'الاسلام')):
            out[-1] = out[-1] + ' ' + w
        else:
            out.append(w)
    return out


def eg_latin(us):
    out = []
    for u in us:
        if u in EG_LATIN:
            out.append(EG_LATIN[u])
        elif u.startswith('ال') and u[2:] in EG_LATIN:
            out.append('El' + EG_LATIN[u[2:]].lower())
        else:
            return None
    return ' '.join(out)


def translit(n):
    return eg_latin(units(n))


def pid(*parts):
    return hashlib.sha1('|'.join(parts).encode()).hexdigest()[:16]


class Builder:
    def __init__(self, rnd, salt):
        self.rnd, self.salt, self.pairs, self.seen = rnd, salt, [], set()
        self.parent = {}

    # union-find over name keys: every name that is tied to another (a pair of real names, the Arabic and
    # Latin names of one record, a name and the same name with an element more / less) ends up in one
    # group, and a whole group goes to the holdout or to dev together, so nothing leaks between them
    def key(self, n):
        return ' '.join(tokens(n))

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(self.key(a)), self.find(self.key(b))
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)

    def assign_holdout(self):
        for p in self.pairs:
            self.union(p['_base'], p['listed'])
            if p['_real_query']:
                self.union(p['_base'], p['query'])
        for p in self.pairs:
            root = self.find(self.key(p['_base']))
            h = hashlib.sha256((self.salt + '|' + root).encode()).hexdigest()
            p['holdout'] = int(h[:4], 16) < 13107        # ~20 % of name groups
            del p['_base'], p['_real_query']

    def add(self, cat, label, query, listed, src, note='', tier='core', base=None, real_query=False):
        query, listed = re.sub(r'\s+', ' ', query or '').strip(), re.sub(r'\s+', ' ', listed or '').strip()
        if not query or not listed or query == listed:
            return False
        k = (cat, query, listed)
        if k in self.seen:
            return False
        self.seen.add(k)
        self.pairs.append({'id': pid(cat, query, listed), 'cat': cat, 'label': label, 'tier': tier,
                           'query': query, 'listed': listed, 'src': src, 'note': note, 'holdout': None,
                           '_base': base or listed, '_real_query': real_query})
        return True

    def fill(self, cat, label, items, fn, src, n=PER_CAT, tier='core', real_query=False):
        items = list(items)
        self.rnd.shuffle(items)
        got = 0
        for it in items:
            if got >= n:
                break
            r = fn(it)
            if not r:
                continue
            q, l = r[0], r[1]
            note = r[2] if len(r) > 2 else ''
            base = r[3] if len(r) > 3 else None
            if self.add(cat, label, q, l, src, note, tier, base, real_query):
                got += 1
        return got


# ---- variant generators ----------------------------------------------------
def v_orthography(n, rnd):
    """How Egyptian records really vary: correct hamza on names that carry it, ة for a final ه
    (not on الله / طه / عبده ...), and the ubiquitous ى for a final ي."""
    us = units(n)
    out, changed = [], False
    for u in us:
        w = u
        if u in HAMZA and rnd.random() < 0.8:
            w = HAMZA[u]
        elif u.endswith('ه') and u.split()[-1] not in NO_TAA and len(u) >= 4 and rnd.random() < 0.7:
            w = u[:-1] + 'ة'
        elif u.endswith('ي') and len(u) >= 3 and rnd.random() < 0.5:
            w = u[:-1] + 'ى'
        changed = changed or w != u
        out.append(w)
    return ' '.join(out) if changed else None


def v_glued(n):
    t = n.replace('عبد ال', 'عبدال', 1)
    return t if t != n else None


def v_colloquial(n):
    for w in n.split():
        if w in ALEF_MAQSURA_MALE:
            return n.replace(w, w[:-1] + 'ا', 1)
    return None


def v_sound(n):
    for a, b in SOUND_SUBS:
        if re.search(r'(^|\s)' + a + r'(\s|$)', n):
            return re.sub(r'(^|\s)' + a + r'(\s|$)', lambda m: m.group(1) + b + m.group(2), n, count=1)
    return None


def v_typo(n, rnd):
    us = units(n)
    idx = [i for i, w in enumerate(us[1:-1], 1) if len(w) >= 5 and ' ' not in w] or \
          [i for i, w in enumerate(us) if len(w) >= 5 and ' ' not in w]
    if not idx:
        return None
    i = rnd.choice(idx)
    w = us[i]
    j = rnd.randrange(1, len(w) - 2)
    us[i] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
    return ' '.join(us)


def v_al_prefix(n):
    """السيد <-> سيد, and ال on a family / nisba element added or removed (الشناوي == شناوي).
    Never adds ال to a given name."""
    us = units(n)
    if 'السيد' in us:
        return ' '.join('سيد' if u == 'السيد' else u for u in us)
    last = us[-1]
    if ' ' in last:
        return None
    if last.startswith('ال') and len(last) > 5:
        us[-1] = last[2:]
    elif last.endswith('ي') and len(last) >= 5 and last not in EG_LATIN:
        us[-1] = 'ال' + last
    else:
        return None
    return ' '.join(us)


def lat_split(lat):
    """Elsayed -> El Sayed / El-Sayed, Abdelrahman -> Abd El Rahman / Abdul Rahman."""
    out, ch = [], False
    for w in lat.split():
        m = re.match(r'^(El)([a-z]{3,})$', w)
        a = re.match(r'^Abdel([a-z]{3,})$', w)
        if m:
            out.append(f'El {m.group(2).capitalize()}' if len(w) % 2 else f'El-{m.group(2).capitalize()}')
            ch = True
        elif a:
            out.append(f'Abd El {a.group(1).capitalize()}' if len(w) % 2 else f'Abdul {a.group(1).capitalize()}')
            ch = True
        else:
            out.append(w)
    return ' '.join(out) if ch else None


def lat_spelling(lat):
    for pat, rep in LAT_SPELL:
        t = re.sub(pat, rep, lat, flags=re.I)
        if t != lat:
            return t
    t = re.sub(r'([bcdfghjklmnpqrstvwxz])\1', r'\1', lat, count=1)
    return t if t != lat else None


def lat_franco(lat):
    out, ch = [], False
    for w in lat.split():
        f = FRANCO_LAT.get(w.capitalize())
        out.append(f if f else w)
        ch = ch or bool(f)
    return ' '.join(out) if ch else None


def lat_maghreb(lat):
    out, ch = [], False
    for w in lat.split():
        f = MAGHREB.get(w.capitalize())
        out.append(f if f else w)
        ch = ch or bool(f)
    return ' '.join(out) if ch else None


def strip_legal(o):
    prev = None
    while prev != o:
        prev = o
        o = re.sub(r'(^\s*شرك[ةه]\s+)|(\s+ش\s*\.?\s*م\s*\.?\s*[مق]\s*\.?\s*$)', ' ', o).strip()
        o = re.sub(r'[\s,]+(LLC|L\.L\.C\.?|Ltd\.?|Co\.?|Company|Limited|Inc\.?|S\.?A\.?E\.?|S\.?A\.?|JSC|OJSC|PJSC|OOO|'
                   r'CJSC|PLC|GmbH|Corp\.?|Corporation|FZE|FZCO|LLP|AG|BV|SRL|SARL)\s*$', '',
                   o, flags=re.I).strip()
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', type=int, default=1)
    ap.add_argument('--review', action='store_true', help='also write a 2 %% stratified human-review sample')
    a = ap.parse_args()
    rnd = random.Random(SEED + a.version)
    os.makedirs(OUT_DIR, exist_ok=True)
    salt_path = os.path.join(OUT_DIR, '.holdout_salt')
    if not os.path.exists(salt_path):
        with open(salt_path, 'w') as f:
            f.write(secrets.token_hex(16))
        os.chmod(salt_path, 0o600)
    salt = open(salt_path).read().strip()
    import psycopg2
    import psycopg2.extras
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ---- sources (read-only) ----
    cur.execute("""SELECT DISTINCT original_name n, national_id nid FROM internal_blacklist
                   WHERE is_active=1 AND upper(entity_type) IN ('INDIVIDUAL','PERSON') AND original_name ~ '[ء-ي]'
                   UNION SELECT DISTINCT full_name, NULL FROM screening_watchlist
                   WHERE source='emlcu' AND is_active=1 AND entity_type='PERSON'""")
    ar = {}
    for r in cur.fetchall():
        p = plain(r['n'])
        if 3 <= len(p.split()) <= 7 and '/' not in (r['n'] or '') and not ORG_WORDS.search(p):
            ar.setdefault(p, re.sub(r'\D', '', r['nid'] or ''))
    ar_names = sorted(ar)
    cur.execute("""SELECT full_name_arabic a, full_name l FROM screening_watchlist
                   WHERE is_active=1 AND source IN ('un','ofac','eu','hmt','opensanctions')
                     AND upper(entity_type) IN ('PERSON','INDIVIDUAL')
                     AND full_name_arabic ~ '[ء-ي]' AND full_name ~ '^[A-Za-z .''-]+$'""")
    xs = [(r['a'].strip(), r['l'].strip()) for r in cur.fetchall()
          if len(tokens(r['a'])) >= 2 and len(tokens(r['l'])) >= 2]
    cur.execute("""SELECT full_name l, date_of_birth d FROM screening_watchlist
                   WHERE is_active=1 AND source IN ('un','ofac','eu','hmt') AND upper(entity_type) IN ('PERSON','INDIVIDUAL')
                     AND full_name ~ '^[A-Za-z .''-]+$'""")
    lat = [(r['l'].strip(), r['d']) for r in cur.fetchall() if len(r['l'].split()) >= 3]
    cur.execute("""SELECT DISTINCT original_name n FROM internal_blacklist WHERE is_active=1
                   AND upper(entity_type) IN ('ORGANIZATION','ENTITY') AND original_name ~ '[ء-ي]'""")
    org_ar = sorted({strip_legal(r['n']) for r in cur.fetchall()
                     if r['n'] and '/' not in r['n'] and 2 <= len(tokens(r['n'])) <= 6})
    cur.execute("""SELECT DISTINCT full_name n FROM screening_watchlist WHERE is_active=1
                   AND source IN ('un','ofac','eu','hmt') AND upper(entity_type) IN ('ENTITY','ORGANIZATION')
                   AND full_name ~ '^[A-Za-z .&''-]+$'""")
    org_lat = sorted({strip_legal(r['n']) for r in cur.fetchall() if 2 <= len(r['n'].split()) <= 6})
    print(f'sources: arabic persons {len(ar_names)}, cross-script {len(xs)}, latin persons {len(lat)}, '
          f'org ar {len(org_ar)}, org lat {len(org_lat)}', file=sys.stderr)

    B = Builder(rnd, salt)
    four = [n for n in ar_names if len(units(n)) >= 4]
    four_lat = [n for n in four if translit(n)]
    print(f'names with a curated Latin form: {len(four_lat)}', file=sys.stderr)

    # ---- positives: Arabic as written in Egyptian records ----
    B.fill('ar_orthography', 1, ar_names, lambda n: (v_orthography(n, rnd), n), 'ar_lists')
    B.fill('ar_glued', 1, [n for n in ar_names if 'عبد ال' in n], lambda n: (v_glued(n), n), 'ar_lists')
    B.fill('ar_colloquial', 1, [n for n in ar_names if any(w in ALEF_MAQSURA_MALE for w in n.split())],
           lambda n: (v_colloquial(n), n), 'ar_lists')
    B.fill('ar_sound_letters', 1, ar_names, lambda n: (v_sound(n), n), 'ar_lists')
    B.fill('ar_al_prefix', 1, four, lambda n: (v_al_prefix(n), n), 'ar_lists')
    B.fill('ar_typo', 1, four, lambda n: (v_typo(n, rnd), n), 'ar_lists')
    B.fill('ar_extra_name', 1, four, lambda n: (n + ' ' + rnd.choice(AR_COMMON_FIRST), n), 'ar_lists')

    def drop_later(n):
        # only the grandfather or a later element may be missing; dropping the father makes another person
        us = units(n)
        if len(us) < 4:
            return None
        i = rnd.randrange(2, len(us) - 1)
        return ' '.join(us[:i] + us[i + 1:]), n
    B.fill('ar_missing_later', 1, four, drop_later, 'ar_lists')
    B.fill('ar_titles', 1, four, lambda n: (rnd.choice(['الحاج ', 'د. ', 'د/ ', 'المهندس ', 'المستشار ', 'الشيخ ']) + n, n),
           'ar_lists')
    # ---- positives: cross-script and Latin ----
    B.fill('cross_egyptian_latin', 1, four_lat, lambda n: (translit(n), n), 'ar_lists')
    B.fill('cross_arabic_query_latin_listed', 1, four_lat, lambda n: (n, translit(n), '', n), 'ar_lists')
    B.fill('lat_el_split', 1, four_lat, lambda n: (lat_split(translit(n)), translit(n), '', n), 'ar_lists')
    B.fill('cross_official', 1, [p for p in xs if not NON_ARABIC_SCRIPT.search(p[0])],
           lambda p: (p[1], p[0], '', p[0]) if rnd.random() < 0.5 else (p[0], p[1], '', p[0]), 'intl_lists',
           real_query=True)
    B.fill('lat_spelling', 1, lat, lambda p: (lat_spelling(p[0]), p[0]), 'intl_lists')
    PART = {'al', 'el', 'abu', 'abou', 'bin', 'ibn', 'bint', 'abd', 'abdul', 'abdel', 'ould', 'van', 'de', 'da', 'del'}

    def surname_first(name):
        w = name.split()
        k = len(w) - 1
        while k > 1 and w[k - 1].lower().strip('-') in PART:
            k -= 1
        if k == 0:
            return None
        return ' '.join(w[k:]).upper() + ', ' + ' '.join(w[:k]), name
    B.fill('lat_order', 1, lat, lambda p: surname_first(p[0]), 'intl_lists')
    B.fill('company_forms', 1, [('ar', o) for o in org_ar] + [('lat', o) for o in org_lat],
           lambda t: ((rnd.choice(CO_FORMS_AR) if t[0] == 'ar' else rnd.choice(CO_FORMS_LAT)).format(t[1]), t[1]),
           'org_lists')

    def syn(o):
        for x, y in CO_SYN:
            if re.search(r'(^|\s)' + re.escape(x) + r'(\s|$)', o):
                return re.sub(r'(^|\s)' + re.escape(x) + r'(?=\s|$)', lambda m: m.group(1) + y, o, count=1), o
        return None
    # ---- supplementary (reported separately, not in the headline rate) ----
    B.fill('sup_company_synonyms', 1, org_ar + org_lat, syn, 'org_lists', tier='supplementary')
    B.fill('sup_lat_franco', 1, four_lat, lambda n: (lat_franco(translit(n)), n), 'ar_lists', n=900,
           tier='supplementary')
    B.fill('sup_lat_maghreb', 1, lat, lambda p: (lat_maghreb(p[0]), p[0]), 'intl_lists', n=900, tier='supplementary')
    B.fill('sup_cross_non_arabic_script', 1, [p for p in xs if NON_ARABIC_SCRIPT.search(p[0])],
           lambda p: (p[1], p[0], '', p[0]), 'intl_lists', n=900, tier='supplementary')

    # ---- negatives ----
    lk_count = {}

    def lookalike(n):
        us = units(n)
        alt = AR_LOOKALIKE.get(us[0])
        if not alt:
            return None
        if lk_count.get(us[0], 0) >= LOOKALIKE_CAP * PER_CAT:
            return None
        lk_count[us[0]] = lk_count.get(us[0], 0) + 1
        return ' '.join([alt] + us[1:]), n, f'first name {us[0]} replaced by look-alike {alt}'
    B.fill('neg_lookalike_first', 0, four, lookalike, 'ar_lists')

    def sibling(n):
        us = units(n)
        alt = rnd.choice([f for f in AR_COMMON_FIRST if f != us[0] and AR_LOOKALIKE.get(us[0]) != f])
        return ' '.join([alt] + us[1:]), n, 'different first name, same father / family (sibling)'
    B.fill('neg_sibling', 0, four, sibling, 'ar_lists')
    families = [units(n)[-1] for n in four if ' ' not in units(n)[-1]]

    def other_family(n):
        us = units(n)
        alt = rnd.choice(families)
        if alt == us[-1] or ' ' in us[-1]:
            return None
        return ' '.join(us[:-1] + [alt]), n, 'same first / father / grandfather, different family'
    B.fill('neg_family_diff', 0, four, other_family, 'ar_lists')

    def latin_sibling(n):
        us = units(n)
        alts = [f for f in AR_COMMON_FIRST if f != us[0] and f in EG_LATIN]
        q = eg_latin([rnd.choice(alts)] + us[1:])
        return (q, n, 'Latin form of a sibling vs the listed Arabic name') if q else None
    B.fill('neg_cross_script_sibling', 0, four_lat, latin_sibling, 'ar_lists')

    # real distinct people on the lists: share the first two elements, different valid national IDs,
    # and neither name is the other plus / minus elements (that is a positive variant, not a negative)
    by2 = {}
    for n in four:
        by2.setdefault(' '.join(units(n)[:2]), []).append(n)
    real = []
    for v in by2.values():
        v = [x for x in v if len(ar.get(x, '')) == 14]
        for i in range(len(v) - 1):
            a1, b1 = v[i], v[i + 1]
            ta, tb = set(tokens(a1)), set(tokens(b1))
            if ar[a1] != ar[b1] and not (ta <= tb or tb <= ta):
                real.append((a1, b1))
    B.fill('neg_real_distinct_ar', 0, real, lambda p: (p[0], p[1], 'different national IDs'), 'ar_lists', real_query=True)
    byl = {}
    for l, d in lat:
        byl.setdefault(' '.join(l.split()[:2]).lower(), []).append((l, d))
    reall = []
    for v in byl.values():
        for i in range(len(v) - 1):
            (a1, d1), (b1, d2) = v[i], v[i + 1]
            ta, tb = set(tokens(a1)), set(tokens(b1))
            if d1 and d2 and abs(int(str(d1)[:4]) - int(str(d2)[:4])) >= 3 and not (ta <= tb or tb <= ta):
                reall.append((a1, b1))
    B.fill('neg_real_distinct_lat', 0, reall, lambda p: (p[0], p[1], 'years of birth 3+ apart'), 'intl_lists',
           real_query=True)

    def distinctive(o):
        return [w for w in tokens(o) if w not in CO_GENERIC and w not in _LEGAL_FORMS and len(w) > 2]
    byo = {}
    for o in org_ar + org_lat:
        d = distinctive(o)
        if d:
            byo.setdefault(d[0], []).append(o)
    oreal = []
    for v in byo.values():
        for i in range(len(v) - 1):
            ta, tb = set(distinctive(v[i])), set(distinctive(v[i + 1]))
            if ta and tb and not (ta <= tb or tb <= ta):
                oreal.append((v[i], v[i + 1]))
    B.fill('neg_company_similar', 0, oreal, lambda p: (p[0], p[1]), 'org_lists', real_query=True)

    # tie together the Arabic and Latin names of one international record, and names that are the same
    # name with one element more or less, before choosing the holdout
    for a_, l_ in xs:
        B.union(a_, l_)
    full = {tuple(tokens(n)): n for n in ar_names}
    for t, n in full.items():
        for i in range(len(t)):
            other = full.get(t[:i] + t[i + 1:])
            if other:
                B.union(n, other)          # the same name with one element more / less
    B.assign_holdout()

    from collections import Counter
    path = os.path.join(OUT_DIR, f'gold_v{a.version}.jsonl')
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        for p in B.pairs:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    os.replace(path + '.tmp', path)
    c = Counter((p['cat'], p['label'], p['tier']) for p in B.pairs)
    h = Counter(p['cat'] for p in B.pairs if p['holdout'])
    meta = {'version': a.version, 'seed': SEED + a.version, 'pairs': len(B.pairs),
            'holdout': sum(p['holdout'] for p in B.pairs),
            'by_category': {k[0]: {'label': k[1], 'tier': k[2], 'n': v, 'holdout': h.get(k[0], 0)}
                            for k, v in sorted(c.items())},
            'sha256': hashlib.sha256(open(path, 'rb').read()).hexdigest()}
    if a.review:
        rv = []
        for cat in sorted({p['cat'] for p in B.pairs}):
            ps = [p for p in B.pairs if p['cat'] == cat and not p['holdout']]
            rv += rnd.sample(ps, min(len(ps), max(5, round(len(ps) * 0.02))))
        with open(os.path.join(OUT_DIR, f'gold_v{a.version}.review.jsonl'), 'w', encoding='utf-8') as f:
            for p in rv:
                f.write(json.dumps(p, ensure_ascii=False) + '\n')
        meta['review_sample'] = len(rv)
    json.dump(meta, open(os.path.join(OUT_DIR, f'gold_v{a.version}.meta.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
