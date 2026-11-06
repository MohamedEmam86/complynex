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
Adverse-media relevance: is this article about the screened person, and is it
adverse?

A news search returns every article that loosely matches the query. Shown
as-is, a search for a common Egyptian name returns a hundred unrelated
articles and the page says "adverse media detected" for an innocent
customer. An analyst reads each article for two things, and so does this
module:

1. Is the person named? The elements of the screened name must appear in the
   article (exact phrase, all elements, or for a long Egyptian name the first
   name plus at least one more distinctive element). Arabic prefixes
   (و ب ل ف ال) are stripped, so "وأحمد" counts as "أحمد".
2. Is it adverse? Whole-word risk terms (not substrings: "حكم" must not fire
   on "محكمة" or "الحكومة"), grouped into categories with a severity:
     3  terrorism / sanctions, financial crime
     2  criminal proceedings (arrest, charge, trial, conviction)
     1  regulatory / misconduct (investigation, violation, scandal)

Articles naming the person without any risk term are kept apart as
"mentions" — useful context, never an adverse finding.
"""
import re

from screening import match_intel as mi

# category -> (severity, label, [terms]). Latin terms are matched as word
# prefixes ("launder" covers laundering / laundered); Arabic terms on the
# normalised word with its prefixes removed.
CATEGORIES = {
    'terrorism_sanctions': (3, 'Terrorism / sanctions', [
        'terror', 'sanction', 'blacklist', 'ofac', 'sdn list', 'extremis', 'militant', 'jihad',
        'proliferation financ', 'asset freez', 'frozen asset', 'arms traffick', 'drug traffick',
        'human traffick', 'organized crime', 'organised crime', 'cartel', 'mafia',
        'ارهاب', 'ارهابي', 'ارهابيه', 'ارهابيين', 'تمويل ارهاب', 'عقوبات', 'قائمه سوداء',
        'تجميد اموال', 'تجميد اصول', 'تطرف', 'متطرف', 'تكفيري', 'تكفيريه', 'اتجار مخدرات',
        'اتجار بشر', 'اتجار سلاح', 'تهريب سلاح', 'تهريب مخدرات', 'جريمه منظمه']),
    'financial_crime': (3, 'Financial crime', [
        'fraud', 'embezzl', 'brib', 'corrupt', 'launder', 'tax evasion', 'ponzi', 'insider trading',
        'market manipulat', 'kickback', 'shell compan', 'illicit enrich', 'misappropriat', 'swindl',
        'counterfeit', 'scam',
        'احتيال', 'اختلاس', 'رشوه', 'رشاوي', 'رشاوى', 'فساد', 'غسل اموال', 'غسيل اموال',
        'تهرب ضريبي', 'تزوير', 'نصب', 'اثراء غير مشروع', 'استيلاء', 'توظيف اموال', 'تربح',
        'اموال مشبوهه', 'شركات وهميه', 'فواتير وهميه', 'مستريح']),
    'criminal_proceedings': (2, 'Criminal proceedings', [
        'arrest', 'indict', 'convict', 'sentenc', 'imprison', 'criminal charg', 'charged', 'charges against', 'torture',
        'prosecut', 'fugitive', 'arrest warrant', 'extradit', 'detain', 'guilty', 'seiz', 'confiscat',
        'forfeit', 'jail', 'prison',
        'اعتقال', 'قبض', 'محاكمه', 'ادانه', 'سجن', 'حبس', 'مذكره توقيف', 'توقيف', 'متهم',
        'متهمين', 'اتهام', 'اتهامات', 'بتهمه', 'تعذيب', 'جنايه', 'جنايات', 'مصادره', 'هارب', 'احاله للمحاكمه']),
    'regulatory_misconduct': (1, 'Regulatory / misconduct', [
        'scandal', 'misconduct', 'abuse of power', 'conflict of interest', 'nepotism', 'whistleblow',
        'investigat', 'probe', 'allegation', 'alleged', 'violation', 'disqualif',
        'فضيحه', 'مخالفات', 'تضارب مصالح', 'محسوبيه', 'وثائق مسربه', 'انتهاكات',
        'تحقيقات', 'شبهه', 'شبهات', 'غرامه']),
}

_AR_PREFIXES = ('وال', 'بال', 'فال', 'كال', 'لل', 'ال', 'و', 'ب', 'ل', 'ف')
_AR_SUFFIXES = ('ات', 'ين', 'ون')


def _norm_text(text):
    """Both scripts kept (articles mix them); Arabic letters unified."""
    t = str(text or '').lower()
    t = re.sub(r'[ً-ْٰـ]', '', t)
    t = re.sub('[إأآٱ]', 'ا', t).replace('ة', 'ه').replace('ى', 'ي')
    t = re.sub(r"[^a-z0-9ء-ي\s]", ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _ar_forms(word):
    """A word and the forms it takes without its attached prefixes/suffixes."""
    forms = {word}
    for p in _AR_PREFIXES:
        if word.startswith(p) and len(word) - len(p) >= 3:
            forms.add(word[len(p):])
    for f in list(forms):
        for s in _AR_SUFFIXES:
            if f.endswith(s) and len(f) - len(s) >= 3:
                forms.add(f[:-len(s)])
    return forms


def _words(text):
    return _norm_text(text).split()


def _stems(words):
    """Per position, the set of forms the word can stand for."""
    return [(_ar_forms(w) if mi.is_arabic(w) else {w}) for w in words]


# "fighting corruption" / "مكافحة الفساد" is not an allegation against anyone
_NEGATORS = {'مكافحه', 'لمكافحه', 'مواجهه', 'لمواجهه', 'محاربه', 'لمحاربه', 'ضد', 'منع', 'anti', 'counter',
             'combat', 'combating', 'combatting', 'fighting', 'against', 'prevent', 'preventing', 'countering'}


def _phrase_in(stems, phrase, latin_prefix, skip_negated=False):
    return _phrase_at(stems, phrase, latin_prefix, skip_negated) is not None


def _phrase_at(stems, phrase, latin_prefix, skip_negated=False):
    n = len(phrase)
    for i in range(len(stems) - n + 1):
        if skip_negated and any(stems[k] & _NEGATORS for k in range(max(0, i - 2), i)):
            continue
        ok = True
        for j, p in enumerate(phrase):
            forms = stems[i + j]
            if latin_prefix and not mi.is_arabic(p):
                if not any(f.startswith(p) for f in forms):
                    ok = False
                    break
            elif p not in forms:
                ok = False
                break
        if ok:
            return i
    return None


_COMPILED = {k: (sev, label, [(t, _norm_text(t).split()) for t in terms])
             for k, (sev, label, terms) in CATEGORIES.items()}


def classify(text):
    """Risk categories, the highest severity and the terms found."""
    words = _words(text)
    stems = _stems(words)
    cats, found, sev = [], [], 0
    for key, (s, label, terms) in _COMPILED.items():
        hit = []
        for t, ph in terms:
            at = _phrase_at(stems, ph, latin_prefix=True, skip_negated=True) if ph else None
            if at is not None:
                hit.append(' '.join(words[at:at + len(ph)]))   # the words as written
        if hit:
            cats.append(label)
            found += hit
            sev = max(sev, s)
    return {'categories': cats, 'terms': list(dict.fromkeys(found))[:6], 'severity': sev}


_JOIN_NEXT = {'عبد', 'ابو', 'أبو', 'بن', 'abd', 'abdel', 'abdul', 'abu', 'abou', 'el', 'al', 'bin', 'ben'}
# elements that attach to the element BEFORE them (…al-Din, …ullah): the Arabic
# compounds plus their bare Latin transliterations (Nour El Din -> one unit).
_JOIN_PREV = {'الدين', 'الله', 'الاسلام', 'الإسلام', 'eldin', 'el-din', 'allah', 'uddin', 'eddin',
              'din', 'deen', 'ullah'}
# a join-next chain merges BACKWARD (Nour + El Din) only when it STARTS WITH AN
# ARTICLE (el/al/ad/ed). 'عبد الله' / 'Abd Allah' / 'Abdel Allah' is itself a
# name element (Abdullah) and must NOT be glued onto the preceding name.
_ARTICLES = {'el', 'al', 'ad', 'ed'}

# weight thresholds on mi._weight scale (محمد 1.0, سعد 4.0, الشاطر 8.3, خيرت 8.7):
# a distinctive family element for a 4+ element short form, and the higher bar a
# 3-element name's family must clear to justify a first+family short form.
_RARE_WEIGHT = 6.0
_RARE_FAMILY_3 = 8.0
_SHORT_FORM_MIN_TOTAL = 9.0


def _units(name):
    """Name elements as a reader writes them: compounds kept together
    (عبد اللطيف، سعد الدين، Abd El Aziz، Nour El Din، عبد الله). A join-next
    connector (abd/abu/el/al/bin) chains onto the following element, chaining
    through a second connector too (Abd + El + Aziz -> 'Abd El Aziz'); a bare
    join-previous element (سعد + الدين) merges into the unit before it. A
    connector chain only merges backward when it begins with an article
    (Nour + El Din), so 'عبد الله' stays its own unit."""
    words = str(name or '').split()
    units, i, n = [], 0, len(words)
    while i < n:
        w = words[i]
        wl = w.lower()
        if wl in _JOIN_NEXT and i + 1 < n:
            parts = [w]
            i += 1
            while i + 1 < n and words[i].lower() in _JOIN_NEXT:   # abd EL aziz
                parts.append(words[i])
                i += 1
            parts.append(words[i])
            comp = ' '.join(parts)
            if units and parts[0].lower() in _ARTICLES and words[i].lower() in _JOIN_PREV:
                units[-1] = units[-1] + ' ' + comp               # Nour + (El Din)
            else:
                units.append(comp)                                # 'عبد الله', 'Abd El Aziz'
            i += 1
            continue
        if units and wl in _JOIN_PREV:                            # Saad + Din
            units[-1] = units[-1] + ' ' + w
            i += 1
            continue
        units.append(w)
        i += 1
    return units


def _fam_weight(unit):
    toks = mi.tokens(unit)
    return max((mi._weight(t) for t in toks), default=0.0)


def known_as_forms(name):
    """The shorter forms the press uses for a long Egyptian name.

    4+ elements: second+family (خيرت الشاطر, the best lead) and
    first+second+family (محمد خيرت الشاطر), when the family element is
    distinctive on its own (weight >= 6). The first+family form is NOT produced
    for a long name — a common first name plus a family name matches far too
    many unrelated people (محمد الشاطر).

    Exactly 3 elements: second+family AND first+family, but only when the family
    element is highly distinctive (weight >= 8) — a 3-element name has no middle
    to drop, so first+family is often the only form the press uses, yet it is
    still only ever a weak lead (name_presence returns 'partial', never HIGH).

    Every form must also carry enough total identifying weight (>= 9)."""
    u = _units(name)
    n = len(u)
    if n < 3:
        return []
    out = []

    def add(parts):
        s = ' '.join(parts)
        toks = mi.tokens(s)
        if len(toks) >= 2 and s not in out and sum(mi._weight(t) for t in toks) >= _SHORT_FORM_MIN_TOTAL:
            out.append(s)

    if n >= 4:
        if _fam_weight(u[-1]) >= _RARE_WEIGHT:
            add([u[1], u[-1]])              # second + family (best)
            add([u[0], u[1], u[-1]])        # first + second + family
    else:                                    # exactly three elements
        if _fam_weight(u[-1]) >= _RARE_FAMILY_3:
            add([u[1], u[-1]])              # second + family
            add([u[0], u[-1]])              # first + family (allowed only here)
    return out


def _name_forms(name):
    forms = [mi.tokens(name)]
    if not mi.is_arabic(name):
        try:
            ar = mi.tokens(mi.to_arabic_display(name))
            if ar and all(mi.is_arabic(t) for t in ar):
                forms.append(ar)
        except Exception:
            pass
    return [f for f in forms if f]


def _middle_tokens(name):
    """Canonical tokens that belong to a MIDDLE unit of the name (not the first
    and not the family unit). Computed on _units() positions, so a compound like
    'عبد اللطيف' counts as a single middle element, not two."""
    u = _units(name)
    if len(u) < 3:
        return set()
    mid = set()
    for unit in u[1:-1]:
        mid.update(mi.tokens(unit))
    first_fam = set(mi.tokens(u[0])) | set(mi.tokens(u[-1]))
    return mid - first_fam


def name_presence(name, text):
    """How strongly the article names the person: exact / strong / partial / None.
    A short-form ('known-as') hit is reported as 'partial' — it is a lead, never
    a strong finding, and (see assess()) can never on its own reach HIGH."""
    art = _words(text)
    # name elements are compared after the same canonicalisation as names
    canon = []
    for w in art:
        c = mi.tokens(w)
        canon.append(c[0] if c else w)
    stems = _stems(canon)
    flat = set().union(*stems) if stems else set()
    best = None
    rank = {'exact': 3, 'strong': 2, 'partial': 1}
    mid_toks = _middle_tokens(name)
    for q in _name_forms(name):
        present = [t in flat for t in q]
        n, m = len(q), sum(present)
        level = None
        if n >= 2 and _phrase_in(stems, q, latin_prefix=False):
            level = 'exact'
        elif n >= 2 and m == n:
            level = 'strong'
        elif n >= 3 and present[0] and m >= 2:
            # a long Egyptian name reported by first name + one or more other
            # elements. First + family name ALONE (no middle element) is too
            # weak — too many unrelated people share a common first name and a
            # family name (محمد الشاطر); require at least one matched element
            # that belongs to a MIDDLE unit of the name (unit-based, so a
            # compound middle name counts once).
            matched = [idx for idx, p in enumerate(present) if p]
            has_middle = any(q[idx] in mid_toks for idx in matched)
            if has_middle and sum(mi._weight(q[idx]) for idx in matched) >= 7.0:
                level = 'partial'
        elif n == 1 and m == 1:
            level = 'partial'
        if level in (None, 'partial') and n >= 3:
            # reported by a shorter form the press uses (خيرت الشاطر): the form's
            # elements together, in order. Always only 'partial' — a short form
            # identifies the person less firmly than the full name.
            for f in (known_as_forms(name) if q == mi.tokens(name) else []):
                ft = mi.tokens(f)
                if _phrase_in(stems, ft, latin_prefix=False):
                    level = 'partial'
                    break
        if level in ('exact', 'strong') and sum(mi._weight(t) for t in q) < 7.0:
            # a name made only of very common elements (محمد احمد) identifies
            # no one in a news article: a lead, never a strong finding
            level = 'partial'
        if level and (best is None or rank[level] > rank[best]):
            best = level
    return best


def assess(name, articles):
    """Split articles into adverse hits and plain mentions of the person."""
    hits, mentions, unrelated = [], [], 0
    for a in articles:
        text = f"{a.get('title') or ''} {a.get('description') or ''}"
        level = name_presence(name, text)
        if not level:
            unrelated += 1
            continue
        c = classify(text)
        a = dict(a)
        a['name_match'] = level
        if c['severity']:
            bonus = {'exact': 25, 'strong': 15}.get(level, 0)   # partial / anything else: no bonus
            a.update({'categories': c['categories'], 'matched_keywords': c['terms'],
                      'severity': c['severity'], 'risk_score': float(min(100, c['severity'] * 25 + bonus))})
            hits.append(a)
        else:
            a.update({'categories': [], 'matched_keywords': [], 'severity': 0, 'risk_score': 0.0})
            mentions.append(a)
    hits.sort(key=lambda x: (x['risk_score'], str(x.get('published_at') or '')), reverse=True)
    # only an exact / strong full-name match is "firm"; a partial / short-form
    # hit is a lead and can never, on its own, drive the assessment to HIGH.
    firm = [h for h in hits if h['name_match'] in ('exact', 'strong')]
    if any(h['severity'] >= 3 for h in firm):
        level = 'HIGH'
    elif any(h['severity'] >= 2 for h in firm) or any(h['severity'] >= 3 for h in hits):
        level = 'MEDIUM'
    elif hits:
        level = 'LOW'
    else:
        level = 'CLEAR'
    # explicit safety cap (independent of the logic above): HIGH requires at
    # least one firm match. A set of only partial/short-form hits is MEDIUM.
    if level == 'HIGH' and not firm:
        level = 'MEDIUM'
    return {'hits': hits, 'mentions': mentions, 'unrelated': unrelated, 'risk_level': level,
            'risk_score': max([h['risk_score'] for h in hits] or [0.0])}
