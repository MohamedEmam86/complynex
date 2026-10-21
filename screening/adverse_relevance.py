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


def name_presence(name, text):
    """How strongly the article names the person: exact / strong / partial / None."""
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
    for q in _name_forms(name):
        present = [t in flat for t in q]
        n, m = len(q), sum(present)
        level = None
        if n >= 2 and _phrase_in(stems, q, latin_prefix=False):
            level = 'exact'
        elif n >= 2 and m == n:
            level = 'strong'
        elif n >= 3 and present[0] and m >= 2:
            # a long Egyptian name reported by first + family name; a lead
            # only if the elements found are not all common ones
            if sum(mi._weight(t) for t, p in zip(q, present) if p) >= 7.0:
                level = 'partial'
        elif n == 1 and m == 1:
            level = 'partial'
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
            bonus = {'exact': 25, 'strong': 15, 'partial': 0}[level]
            a.update({'categories': c['categories'], 'matched_keywords': c['terms'],
                      'severity': c['severity'], 'risk_score': float(min(100, c['severity'] * 25 + bonus))})
            hits.append(a)
        else:
            a.update({'categories': [], 'matched_keywords': [], 'severity': 0, 'risk_score': 0.0})
            mentions.append(a)
    hits.sort(key=lambda x: (x['risk_score'], str(x.get('published_at') or '')), reverse=True)
    strong = [h for h in hits if h['name_match'] in ('exact', 'strong')]
    if any(h['severity'] >= 3 for h in strong):
        level = 'HIGH'
    elif any(h['severity'] >= 2 for h in strong) or any(h['severity'] >= 3 for h in hits):
        level = 'MEDIUM'
    elif hits:
        level = 'LOW'
    else:
        level = 'CLEAR'
    return {'hits': hits, 'mentions': mentions, 'unrelated': unrelated, 'risk_level': level,
            'risk_score': max([h['risk_score'] for h in hits] or [0.0])}
