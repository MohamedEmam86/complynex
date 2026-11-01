"""
Gold Set v2 extension (Phase 5, P5-1): the categories added to the v1 set.

Every category here has a POSITIVE side (the same person / entity written the way a
customer from that region would write it) and a NEGATIVE side (a different person /
entity written the same way), so the miss rate AND the false-alert rate are measured.

All variants are produced by generic rules written for this file (letter / word rules
per dialect, never a copy of the matcher's own tables), from names that are on the
lists themselves (read on the server, written only to the git-ignored gold file).

Called by gold_set_build.py for --version >= 2; tier = 'extended'. The v1 file is not
touched; the deploy gate stays on v1 until the owner switches it.
"""
import re

TIER = 'extended'
N = 1100

# ---------------------------------------------------------------- dialect respelling (Latin)
# word rules first (whole common names), then letter rules; every rule is generic spelling
# practice of that region, written independently of screening/name_variants.py
LEV_WORDS = {'mohamed': 'Mohammad', 'mohammed': 'Mohammad', 'ahmed': 'Ahmad', 'mahmoud': 'Mahmud',
             'khaled': 'Khalid', 'hamed': 'Hamid', 'osama': 'Usama', 'omar': 'Umar', 'fatma': 'Fatmeh',
             'amira': 'Ameera', 'samir': 'Sameer', 'nabil': 'Nabeel', 'abdallah': 'Abdullah',
             'mostafa': 'Mustafa', 'youssef': 'Yousef', 'hussein': 'Husein', 'ibrahim': 'Ibraheem',
             'maged': 'Majed', 'gamal': 'Jamal', 'ragab': 'Rajab', 'gaber': 'Jaber', 'galal': 'Jalal',
             'hegazy': 'Hijazi', 'magdy': 'Majdi', 'gomaa': "Jum'a", 'naguib': 'Najib'}
GULF_WORDS = {'mohamed': 'Mohammed', 'ahmed': 'Ahmed', 'abdallah': 'Abdulla', 'abdullah': 'Abdulla',
              'kassem': 'Gasim', 'qasim': 'Gasim', 'gamal': 'Jamal', 'gaber': 'Jaber', 'ragab': 'Rajab',
              'saeed': 'Saeed', 'saad': "Sa'ad", 'khaled': 'Khalid', 'rashad': 'Rashed', 'youssef': 'Yousif',
              'maged': 'Majid', 'galal': 'Jalal', 'magdy': 'Majdi', 'naguib': 'Najeeb'}
MAG_WORDS = {'mohamed': 'Mouhamed', 'mohammed': 'Mhammed', 'youssef': 'Youcef', 'hussein': 'Houcine',
             'hassan': 'Hacen', 'ahmed': 'Ahmed', 'abdelkader': 'Abdelkader', 'kassem': 'Kacem',
             'mostafa': 'Mustapha', 'aisha': 'Aicha', 'khadiga': 'Khadija', 'omar': 'Omar',
             'gamal': 'Djamel', 'galal': 'Djelal', 'gaber': 'Djaber', 'ragab': 'Radjab', 'saeed': 'Said',
             'salah': 'Salah', 'ibrahim': 'Brahim', 'sherif': 'Cherif', 'shaaban': 'Chaabane'}
PER_WORDS = {'mohamed': 'Mohammad', 'mohammed': 'Mohammad', 'hussein': 'Hossein', 'hassan': 'Hasan',
             'ali': 'Ali', 'mahmoud': 'Mahmud', 'kassem': 'Ghasem', 'abdallah': 'Abdollah',
             'abdelrahman': 'Abdolrahman', 'reda': 'Reza', 'mahdy': 'Mahdi', 'mohsen': 'Mohsen',
             'mostafa': 'Mostafa', 'omar': 'Omar', 'osman': 'Osman', 'walid': 'Valid', 'wael': 'Vael',
             'yasser': 'Yaser', 'ibrahim': 'Ebrahim', 'ismail': 'Esmail', 'eissa': 'Isa', 'moussa': 'Musa'}
TUR_WORDS = {'mohamed': 'Mehmet', 'mohammed': 'Mehmet', 'ahmed': 'Ahmet', 'mahmoud': 'Mahmut',
             'hussein': 'Hüseyin', 'hassan': 'Hasan', 'osman': 'Osman', 'mostafa': 'Mustafa',
             'ibrahim': 'İbrahim', 'ismail': 'İsmail', 'youssef': 'Yusuf', 'khalil': 'Halil',
             'khaled': 'Halit', 'kamal': 'Kemal', 'gamal': 'Cemal', 'galal': 'Celal', 'omar': 'Ömer',
             'osama': 'Usame', 'soliman': 'Süleyman', 'saeed': 'Sait', 'salah': 'Salih', 'fatma': 'Fatma',
             'aisha': 'Ayşe', 'zeinab': 'Zeynep', 'mariam': 'Meryem', 'hamdy': 'Hamdi', 'wael': 'Vail'}

LEV_LETTERS = [(r'ee', 'i'), (r'ou', 'u'), (r'^El([a-z])', r'Al-\1'), (r'^Abdel', 'Abd al-'), (r'ah$', 'eh')]
GULF_LETTERS = [(r'^Q', 'G'), (r'q', 'g'), (r'ou', 'oo'), (r'^El([a-z])', r'Al \1'), (r'^Abdel', 'Abdul')]
MAG_LETTERS = [(r'sh', 'ch'), (r'Sh', 'Ch'), (r'^J', 'Dj'), (r'u', 'ou'), (r'^Abdel', 'Abdel'),
               (r'^El([a-z])', r'El \1')]
PER_LETTERS = [(r'^W', 'V'), (r'w', 'v'), (r'ou', 'u'), (r'ee', 'i'), (r'^Q', 'Gh'), (r'th', 's'),
               (r'dh', 'z'), (r'^Abdel', 'Abdol'), (r'^El([a-z])', r'\1')]
TUR_LETTERS = [(r'sh', 'ş'), (r'Sh', 'Ş'), (r'ch', 'ç'), (r'^J', 'C'), (r'j', 'c'), (r'^Kh', 'H'),
               (r'kh', 'h'), (r'^W', 'V'), (r'w', 'v'), (r'q', 'k'), (r'ou', 'u'), (r'ee', 'i'),
               (r'^El([a-z])', r'\1')]

DIALECTS = {
    'lev': (LEV_WORDS, LEV_LETTERS),
    'gulf': (GULF_WORDS, GULF_LETTERS),
    'maghreb': (MAG_WORDS, MAG_LETTERS),
    'persian': (PER_WORDS, PER_LETTERS),
    'turkish': (TUR_WORDS, TUR_LETTERS),
}


def respell(lat, dialect, rnd):
    """One Latin name written the way that region writes it; None when nothing changed."""
    words, letters = DIALECTS[dialect]
    out = []
    for w in lat.split():
        lw = w.lower().strip(",.'")
        if lw in words and rnd.random() < 0.9:
            out.append(words[lw])
            continue
        t = w
        for pat, rep in letters:
            if rnd.random() < 0.6:
                t2 = re.sub(pat, rep, t, count=1)
                if t2 != t:
                    t = t2
        out.append(t)
    if dialect == 'gulf' and len(out) >= 3 and rnd.random() < 0.7:
        out = [out[0], 'bin', out[1]] + out[2:]        # Gulf chains: X bin Y ... Al Z
    if dialect == 'maghreb' and len(out) >= 3 and rnd.random() < 0.4:
        out = out[:-1] + ['Ben ' + out[-1]] if not out[-1].startswith('Ben') else out
    r = ' '.join(out)
    return r if r.lower() != lat.lower() else None


# ---------------------------------------------------------------- Franco-Arabic (letter level)
def franco(arabic_units, latin, rnd):
    """Write the Latin form in chat style using the letters of the Arabic name:
    ح 7, ع 3, ء/أ 2, خ 5, ق 2 (Egyptian), غ 3', ط 6, ص 9."""
    lw = latin.split()
    if len(lw) != len(arabic_units):
        return None
    out, ch = [], False
    for a, l in zip(arabic_units, lw):
        t = l
        if 'ح' in a and re.search(r'(?<![kscgdtKSCGDT])h', t, flags=re.I):
            t = re.sub(r'(?<![kscgdtKSCGDT])[hH]', '7', t, count=1)
        if a.startswith('ع') and re.match(r'^[AaEeOoIi]', t):
            t = '3' + t[1:] if rnd.random() < 0.5 else '3' + t
        elif 'ع' in a[1:] and re.search(r'(aa|a\'a|ae)', t):
            t = re.sub(r'(aa|a\'a|ae)', 'a3', t, count=1)
        if 'خ' in a and 'kh' in t.lower():
            t = re.sub(r'[Kk]h', '5' if rnd.random() < 0.6 else "7'", t, count=1)
        if 'ق' in a and re.search(r'[qk]', t, flags=re.I) and rnd.random() < 0.6:
            t = re.sub(r'[QqKk]', '2', t, count=1)
        if 'ط' in a and rnd.random() < 0.5:
            t = re.sub(r'[Tt](?!h)', '6', t, count=1)
        ch = ch or t != l
        out.append(t.lower() if rnd.random() < 0.5 else t)
    return ' '.join(out) if ch else None


# ---------------------------------------------------------------- companies
ABBREV = [(r'\bInternational\b', 'Intl'), (r'\bCompany\b', 'Co'), (r'\bCorporation\b', 'Corp'),
          (r'\bLimited\b', 'Ltd'), (r'\bBrothers\b', 'Bros'), (r'\band\b', '&'), (r'\bManufacturing\b', 'Mfg'),
          (r'\bDevelopment\b', 'Dev'), (r'\bInvestments?\b', 'Invest'), (r'\bIndustries\b', 'Inds'),
          (r'\bAssociation\b', 'Assoc'), (r'\bEstablishment\b', 'Est'), (r'\bServices\b', 'Svcs'),
          (r'\bEngineering\b', 'Eng'), (r'\bSaint\b', 'St')]
LEGAL = ['LLC', 'Ltd', 'Co. Ltd', 'S.A.E.', 'JSC', 'PJSC', 'SARL', 'FZE', 'Inc.', 'PLC', 'GmbH', 'S.A.']
LEGAL_AR = ['ش.م.م', 'ش.م.م.', 'ش.م.ق', 'ذ.م.م', 'ش.ذ.م.م', 'المحدودة', 'ش.م.ع']
SYN_LAT = [(r'\bBank\b', 'Banque'), (r'\bTrading\b', 'Trade'), (r'\bOrganization\b', 'Organisation'),
           (r'\bOrganisation\b', 'Organization'), (r'\bIndustries\b', 'Industrial'), (r'\bHoldings?\b', 'Holding Group'),
           (r'\bGroup\b', 'Holding'), (r'\bCenter\b', 'Centre'), (r'\bCentre\b', 'Center'), (r'\bShipping\b', 'Maritime'),
           (r'\bTrade\b', 'Trading'), (r'\bInvestment\b', 'Investments'), (r'\bExchange\b', 'Exchange House')]
SYN_AR = [('بنك', 'مصرف'), ('مصرف', 'بنك'), ('للتجارة', 'للتجاره'), ('للتجاره', 'للتجارة العامة'),
          ('مؤسسة', 'مؤسسه'), ('مجموعة', 'مجموعه'), ('للاستثمار', 'للاستثمارات'), ('الدولية', 'العالمية'),
          ('للصرافة', 'للصرافه')]
BUSINESS = ['Trading', 'Bank', 'Insurance', 'Contracting', 'Shipping', 'Real Estate', 'Exchange', 'Industries',
            'Logistics', 'Pharmaceuticals', 'Construction', 'Petroleum', 'Investment', 'Tourism', 'Textiles']


def _sub_one(o, rules, rnd):
    rules = list(rules)
    rnd.shuffle(rules)
    for pat, rep in rules:
        t = re.sub(pat, rep, o, count=1)
        if t != o:
            return t
    return None


# ---------------------------------------------------------------- X-Allah, particles, long vowels
ALLAH_HEADS_AR = ('نصر', 'فضل', 'خير', 'جاد', 'عطا', 'عوض', 'فتح', 'رزق', 'حسب', 'جار', 'ضيف', 'خلف',
                  'حمد', 'سعد', 'فرج', 'مال', 'حرز', 'دخيل', 'جود', 'رحمه', 'نعمه', 'هبه', 'منه')
EU_PARTICLES = ('de', 'da', 'di', 'du', 'van', 'von', 'der', 'del', 'della', 'dos', 'das', 'le', 'la')


def build(B, rnd, src):
    """Add the v2 categories to builder B. src: dict of name sources and helpers from gold_set_build."""
    units, translit, eg_latin, tokens = src['units'], src['translit'], src['eg_latin'], src['tokens']
    four_lat, xs, lat = src['four_lat'], src['xs'], src['lat']
    org_ar, org_lat, org_x, ar_names, common = src['org_ar'], src['org_lat'], src['org_x'], src['ar_names'], src['common']
    counts = {}

    # base pairs (listed Arabic, its Latin form): Egyptian names with a known Latin form + official
    # cross-script pairs of the international lists
    base = [(n, translit(n)) for n in four_lat] + [(a, l) for a, l in xs if re.match(r"^[A-Za-z .'-]+$", l)]

    def fill(cat, label, items, fn, srcname, real_query=False, n=N):
        counts[cat] = B.fill(cat, label, items, fn, srcname, n=n, tier=TIER, real_query=real_query)

    # ---- dialect spellings: positives (dialect Latin of the same name vs the listed Arabic) and
    #      negatives (dialect Latin of a SIBLING, a different first name, vs the listed Arabic)
    sib_alts = [f for f in common if f in src['EG_LATIN']]

    def sibling_latin(n):
        us = units(n)
        alts = [f for f in sib_alts if f != us[0] and src['lookalike'].get(us[0]) != f]
        return eg_latin([rnd.choice(alts)] + us[1:]) if alts else None

    for d in ('lev', 'gulf', 'maghreb', 'persian', 'turkish'):
        def pos(p, d=d):
            q = respell(p[1], d, rnd)
            return (q, p[0], f'{d} spelling', p[0]) if q else None

        def neg(n, d=d):
            l = sibling_latin(n)
            q = respell(l, d, rnd) if l else None
            return (q, n, f'{d} spelling of a sibling (different first name)', n) if q else None
        fill(f'x_{d}_spelling', 1, base, pos, 'ar_lists')
        fill(f'x_neg_{d}_sibling', 0, four_lat, neg, 'ar_lists')

    # ---- Franco-Arabic at letter level
    def fr_pos(n):
        q = franco(units(n), translit(n), rnd)
        return (q, n, 'franco-arabic', n) if q else None

    def fr_neg(n):
        us = units(n)
        alts = [f for f in sib_alts if f != us[0] and src['lookalike'].get(us[0]) != f]
        if not alts:
            return None
        alt = [rnd.choice(alts)] + us[1:]
        q = franco(alt, eg_latin(alt) or '', rnd)
        return (q, n, 'franco-arabic of a sibling', n) if q else None
    fill('x_franco', 1, four_lat, fr_pos, 'ar_lists')
    fill('x_neg_franco_sibling', 0, four_lat, fr_neg, 'ar_lists')

    # ---- companies
    lat_cos = [o for o in org_lat if len(o.split()) >= 2]
    fill('x_company_abbrev', 1, lat_cos, lambda o: ((t, o) if (t := _sub_one(o, ABBREV, rnd)) else None), 'org_lists')
    fill('x_company_legal_swap', 1, lat_cos + org_ar,
         lambda o: ((o + ' ' + rnd.choice(LEGAL_AR if re.search('[ء-ي]', o) else LEGAL), o + ' ' +
                     rnd.choice(LEGAL_AR if re.search('[ء-ي]', o) else LEGAL))), 'org_lists')

    def co_syn(o):
        if re.search('[ء-ي]', o):
            for x, y in sorted(SYN_AR, key=lambda _: rnd.random()):
                if re.search(r'(^|\s)' + x + r'(\s|$)', o):
                    return re.sub(r'(^|\s)' + x + r'(?=\s|$)', lambda m: m.group(1) + y, o, count=1), o
            return None
        t = _sub_one(o, SYN_LAT, rnd)
        return (t, o) if t else None
    fill('x_company_synonym', 1, lat_cos + org_ar, co_syn, 'org_lists')
    fill('x_company_cross_script', 1, org_x,
         lambda p: (p[1], p[0], 'Latin and Arabic name of one listed entity', p[0]) if rnd.random() < 0.5
         else (p[0], p[1], 'Arabic and Latin name of one listed entity', p[0]), 'org_lists', real_query=True)

    def co_other_business(o):
        ws = o.split()
        hit = [b for b in BUSINESS if re.search(r'\b' + re.escape(b) + r'\b', o)]
        if not hit or len(ws) < 2:
            return None
        b = hit[0]
        alt = rnd.choice([x for x in BUSINESS if x != b])
        return re.sub(r'\b' + re.escape(b) + r'\b', alt, o, count=1), o, f'same name, {alt} instead of {b} (another company of a group)'
    fill('x_neg_company_other_business', 0, lat_cos, co_other_business, 'org_lists')
    by_first = {}
    for a, l in org_x:
        f = (l.split() or [''])[0].lower()
        if len(f) > 3:
            by_first.setdefault(f, []).append((a, l))
    co_x_neg = []
    for v in by_first.values():
        for i in range(len(v) - 1):
            if set(tokens(v[i][1])) != set(tokens(v[i + 1][1])):
                co_x_neg.append((v[i][1], v[i + 1][0]))
    fill('x_neg_company_cross_script', 0, co_x_neg,
         lambda p: (p[0], p[1], 'Latin name of one entity vs Arabic name of another with the same first word'),
         'org_lists', real_query=True)

    # ---- X-Allah compounds
    allah_ar = [n for n in ar_names if re.search(r'(^|\s)(' + '|'.join(ALLAH_HEADS_AR) + r') الله(\s|$)', n)]

    def allah_glue(n):
        t = re.sub(r'(^|\s)(' + '|'.join(ALLAH_HEADS_AR) + r') الله(?=\s|$)', r'\1\2الله', n, count=1)
        return (t, n) if t != n else None
    fill('x_allah_glued_ar', 1, allah_ar, allah_glue, 'ar_lists')
    allah_lat = [p for p in lat if re.search(r'[a-z]{3,}(allah|ullah|ollah|alla)\b', p[0], flags=re.I)
                 and not re.search(r'\babd', p[0], flags=re.I)]

    def allah_split(p):
        t = re.sub(r'\b([A-Za-z]{3,}?)(a|u|o)llah\b', r'\1 Allah', p[0], count=1, flags=re.I)
        return (t, p[0]) if t != p[0] else None
    fill('x_allah_split_lat', 1, allah_lat, allah_split, 'intl_lists')

    def allah_head_only(n):
        t = re.sub(r'(^|\s)(' + '|'.join(ALLAH_HEADS_AR) + r') الله(?=\s|$)', r'\1\2', n, count=1)
        return (t, n, 'X alone is another name than X Allah') if t != n else None
    fill('x_neg_allah_head_only', 0, allah_ar, allah_head_only, 'ar_lists')

    # ---- particles
    def bin_chain(n):
        us = units(n)
        if len(us) < 3 or any(u in ('بن', 'ابن') for u in us):
            return None
        return ' '.join([us[0], 'بن', us[1], 'بن'] + us[2:]), n
    fill('x_bin_chain_ar', 1, [n for n in ar_names if len(units(n)) >= 3], bin_chain, 'ar_lists')

    def abu_glue(n):
        t = re.sub(r'(^|\s)ابو (\S+)', r'\1ابو\2', n, count=1)
        return (t, n) if t != n else None
    fill('x_abu_glued_ar', 1, [n for n in ar_names if 'ابو ' in n], abu_glue, 'ar_lists')
    eu = [p for p in lat if any(w.lower() in EU_PARTICLES for w in p[0].split()[1:-1])]

    def eu_drop(p):
        ws = p[0].split()
        out = [w for i, w in enumerate(ws) if not (0 < i < len(ws) - 1 and w.lower() in EU_PARTICLES)]
        return (' '.join(out), p[0]) if len(out) >= 2 and len(out) != len(ws) else None
    fill('x_particle_dropped_lat', 1, eu, eu_drop, 'intl_lists')

    def particle_single(p):
        ws = p[0].split()
        for i in range(len(ws) - 1):
            if ws[i].lower() in EU_PARTICLES and len(ws[i + 1]) >= 4:
                return ws[i + 1], ws[i] + ' ' + ws[i + 1], 'surname without its particle, nothing else'
        return None
    fill('x_neg_particle_only', 0, eu, particle_single, 'intl_lists')

    def kunya(n):
        us = units(n)
        if ' ' in us[0]:
            return None
        return 'ابو ' + us[0], n, 'a kunya (father of X) is not the person X'
    fill('x_neg_kunya', 0, [n for n in ar_names if len(units(n)) >= 3], kunya, 'ar_lists')

    # ---- long vowels: written with / without ي after the first letter (foreign-origin names)
    def lv(n):
        us = units(n)
        for i, u in enumerate(us):
            if ' ' not in u and len(u) >= 5 and u[1] == 'ي' and u[0] not in 'اي':
                us2 = list(us)
                us2[i] = u[0] + u[2:]
                return ' '.join(us2), n
        return None
    fill('x_long_vowel', 1, ar_names, lv, 'ar_lists')
    # negative: a long vowel that makes ANOTHER known name (X + ي/و before the last letter),
    # both forms attested as first names on the lists
    firsts = {}
    for n in ar_names:
        u = units(n)[0]
        if ' ' not in u:
            firsts[u] = firsts.get(u, 0) + 1
    partner = {}
    for u in firsts:
        if len(u) >= 3:
            for v in ('ي', 'و'):
                w = u[:-1] + v + u[-1]
                if firsts.get(w, 0) >= 3 and firsts[u] >= 3:
                    partner.setdefault(u, []).append(w)
                    partner.setdefault(w, []).append(u)

    def lv_neg(n):
        us = units(n)
        alts = partner.get(us[0])
        return (' '.join([rnd.choice(alts)] + us[1:]), n, 'a long vowel that makes another name') if alts else None
    fill('x_neg_long_vowel', 0, ar_names, lv_neg, 'ar_lists')
    return counts
