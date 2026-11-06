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

"""Resolutions search engine ("like sanctions screening" for board resolutions).

The user types what a resolution was about, a few keywords, a partial word or a
misspelling, in Arabic or English; every resolution is scored 0-100 by how close
it is, and the words that matched are highlighted.

Pipeline (the same for the indexed text and for the query):
  1. Arabic-Indic / Persian digits -> 0-9, diacritics and tatweel removed.
  2. Arabic words go through screening.match_intel.normalize (alef forms, ya,
     ta marbuta, diacritics) - imported, never modified. Latin words are lower-cased.
  3. Stop words are dropped; a light stemmer removes Arabic prefixes
     (و ب ل ف ال بال وال فال كال لل) and suffixes (ات ين ون ها ه) and common English endings.
Scoring per query word ("concept"), weighted by rarity (IDF over the corpus):
  exact stem 1.0 > synonym group (configurable, cross-script) 0.9 >
  prefix of a longer word 0.8 > typo (edit distance / trigram similarity) <= 0.85;
  multiplied by the field the word is in (title > tags > summary > category > text > agenda),
  plus a bonus when query words appear together as a phrase.
Stems are pre-computed per resolution (board_decisions.search_index); the corpus
(stems, document frequencies, vocabulary) is cached in-process and rebuilt when
a resolution or a synonym changes.
"""
import json
import math
import re
import threading
from collections import defaultdict

from markupsafe import Markup, escape

ENGINE_VERSION = 1
MAX_QUERY_WORDS = 10      # longer queries: the first 10 meaningful words
FIELD_WEIGHTS = {'t': 1.0, 'g': 0.9, 's': 0.85, 'c': 0.8, 'x': 0.75, 'a': 0.6}
W_SYNONYM, W_PREFIX, W_FUZZY = 0.9, 0.8, 0.85

_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_MARKS = re.compile('[ؐ-ًؚ-ٰٟۖ-ۭـ]')
_WORD = re.compile(r'[0-9A-Za-zÀ-ɏ]+|[ء-يٱ-ۓۺ-ۿ]+')
_AR = re.compile('[؀-ۿ]')

STOP = set("""
the of and to a an for on in at by with from as is are be was were this that these those or not no it its into
than then also all any each per via under over upon about after before between such which who whom whose
في من على الى إلى عن مع او أو ان أن إن ثم كما التي الذي الذين هذا هذه ذلك تلك وفق وفقا بشأن بخصوص حول
لدى عند كل اي أي قد تم يتم هو هي هم بين خلال حتى بعد قبل عدم غير لها له به بها ما لا
""".split())
STOP |= {re.sub('[إأآ]', 'ا', w).replace('ى', 'ي').replace('ة', 'ه') for w in STOP}


def _ar_normalize(word):
    try:
        from screening.match_intel import normalize
        return normalize(word)
    except Exception:   # the screening package unavailable: minimal equivalent
        w = re.sub('[إأآٱ]', 'ا', word)
        return w.replace('ة', 'ه').replace('ى', 'ي')


_AR_PREFIXES = ('وبال', 'وال', 'بال', 'فال', 'كال', 'لل', 'ال')
_AR_ONE = ('و', 'ب', 'ل', 'ف')   # one-letter prefixes: handled as aliases (see one_letter_alias)


def one_letter_alias(s):
    """'وتعي' -> 'تعي': a stem that may carry a conjunction / preposition letter also
    counts without it (the letter is not stripped, so وزار stays a word of its own)."""
    if len(s) >= 4 and s[0] in _AR_ONE and _AR.match(s):
        return s[1:]
    return None
_AR_SUFFIXES = ('ات', 'ين', 'ون', 'ها', 'ه')
_EN_SUFFIXES = ('ations', 'ation', 'ments', 'ment', 'ings', 'ing', 'ies', 'ed', 'es', 'al', 's')


def stem(w):
    if not w:
        return w
    if _AR.search(w):
        for p in _AR_PREFIXES:
            if w.startswith(p) and len(w) - len(p) >= 2:
                w = w[len(p):]
                break
        for s in _AR_SUFFIXES:
            if w.endswith(s) and len(w) - len(s) >= 3:
                w = w[:-len(s)]
                break
        return w
    if w.isdigit():
        return w
    for s in _EN_SUFFIXES:
        if w.endswith(s) and len(w) - len(s) >= 4:
            w = w[:-len(s)]
            break
    if len(w) > 4 and w.endswith('e'):
        w = w[:-1]
    return w


def words(text):
    """[(original word, start, end)] in the text (for highlighting)."""
    t = str(text or '')
    return [(m.group(0), m.start(), m.end()) for m in _WORD.finditer(t.translate(_DIGITS))]


def norm_word(w):
    """One raw word -> list of normalised words (normalize() may split a glued word)."""
    w = _MARKS.sub('', w.translate(_DIGITS))
    if not w:
        return []
    if _AR.search(w):
        return [x for x in _ar_normalize(w).split() if x]
    return [w.lower()]


def analyse(text):
    """text -> list of stems in order (stop words removed)."""
    out = []
    t = _MARKS.sub('', str(text or '').translate(_DIGITS))
    for m in _WORD.finditer(t):
        for n in norm_word(m.group(0)):
            if n in STOP or len(n) < 2 and not n.isdigit():
                continue
            s = stem(n)
            if s and s not in STOP:
                out.append(s)
    return out


def normalized_text(text):
    return ' '.join(analyse(text))


# ------------------------------------------------------------------ similarity
def _trigrams(w):
    p = f'  {w} '
    return {p[i:i + 3] for i in range(len(p) - 2)}


def trigram_sim(a, b):
    ta, tb = _trigrams(a), _trigrams(b)
    return len(ta & tb) / float(len(ta | tb)) if ta and tb else 0.0


def edit_distance(a, b, limit=2):
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            best = min(best, cur[j])
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def fuzzy_weight(q, term):
    """Similarity weight of vocabulary `term` for query stem `q` (0 when not close)."""
    if q == term:
        return 1.0
    best = 0.0
    if len(q) >= 3 and term.startswith(q) and len(term) > len(q):
        best = W_PREFIX * (0.85 + 0.15 * len(q) / len(term))
    if 3 <= min(len(q), len(term)) and abs(len(q) - len(term)) == 1 and max(len(q), len(term)) <= 4:
        lo, hi = (q, term) if len(q) < len(term) else (term, q)
        if any(hi[:i] + hi[i + 1:] == lo for i in range(len(hi))):
            best = max(best, W_FUZZY * 0.8)    # one letter left out / added in a short word (حسب -> حساب)
    if len(q) >= 4 and len(term) >= 4:
        lim = 1 if max(len(q), len(term)) <= 6 else 2
        d = edit_distance(q, term, lim)
        if d <= lim:
            best = max(best, W_FUZZY * (1 - d / float(max(len(q), len(term)) + 1)))
        if len(q) >= 5:
            s = trigram_sim(q, term)
            if s >= 0.45:
                best = max(best, W_FUZZY * s)
    return best


# ------------------------------------------------------------------ synonyms
def synonym_groups(rows):
    """rows: [{group_code, term}] -> (single {stem: {group}}, phrases [(stems tuple, group)])."""
    single, phrases = defaultdict(set), []
    for r in rows:
        st = tuple(analyse(r['term']))
        if not st:
            continue
        g = '§' + str(r['group_code']).upper()
        if len(st) == 1:
            single[st[0]].add(g)
        else:
            phrases.append((st, g))
    return single, phrases


def group_tokens(stems, single, phrases):
    """{group token: set of stems that produced it} found in a stem sequence.
    A synonym phrase wins over the single words inside it (تمويل الإرهاب is not a loan)."""
    out = defaultdict(set)
    covered = set()
    if phrases:
        n = len(stems)
        for st, g in phrases:
            k = len(st)
            for i in range(n - k + 1):
                if tuple(stems[i:i + k]) == st or tuple(one_letter_alias(x) or x for x in stems[i:i + k]) == st:
                    out[g].update(stems[i:i + k])
                    covered.update(range(i, i + k))
    for i, s in enumerate(stems):
        if i in covered:
            continue
        for key in (s, one_letter_alias(s)):
            for g in single.get(key, ()):
                out[g].add(s)
    return out


# ------------------------------------------------------------------ corpus
class Corpus:
    def __init__(self, docs, syn_rows):
        """docs: {id: {field: [stems]}}"""
        self.single, self.phrases = synonym_groups(syn_rows)
        self.docs = {}
        self.df = defaultdict(int)
        for rid, fields in docs.items():
            weights = {}
            seq = []
            for f, stems in fields.items():
                fw = FIELD_WEIGHTS.get(f, 0.5)
                for s in stems:
                    if weights.get(s, 0) < fw:
                        weights[s] = fw
                    a = one_letter_alias(s)
                    if a and weights.get(a, 0) < fw * 0.95:
                        weights[a] = round(fw * 0.95, 4)
                seq.append(stems)
            groups = {}
            fsets = []
            for f, stems in fields.items():
                fw = FIELD_WEIGHTS.get(f, 0.5)
                fset = set(stems) | {a for a in (one_letter_alias(x) for x in stems) if a}
                for g, src in group_tokens(stems, self.single, self.phrases).items():
                    fset.add(g)
                    if groups.get(g, (0, None))[0] < fw:
                        groups[g] = (fw, src)
                if fset:
                    fsets.append(fset)
            for g, (fw, _src) in groups.items():
                weights[g] = fw
            self.docs[rid] = dict(w=weights, seq=seq, groups=groups, fsets=fsets)
            for s in weights:
                self.df[s] += 1
        self.n = len(self.docs)
        self.vocab = [t for t in self.df if not t.startswith('§')]
        # candidates for typo / partial matching: by trigram and by the first two letters
        self.tri = defaultdict(set)
        self.pre = defaultdict(set)
        for t in self.vocab:
            for g in _trigrams(t):
                self.tri[g].add(t)
            self.pre[t[:2]].add(t)

    def candidates(self, q):
        """Vocabulary words that may be close to q: sharing two trigrams, or starting with its first two letters."""
        seen = defaultdict(int)
        for g in _trigrams(q):
            for t in self.tri.get(g, ()):
                seen[t] += 1
        out = {t for t, n in seen.items() if n >= 2 and abs(len(t) - len(q)) <= 3}
        out |= {t for t in self.pre.get(q[:2], ()) if t.startswith(q) or abs(len(t) - len(q)) <= 2}
        return out

    def idf(self, term):
        return math.log(1.0 + (self.n + 1.0) / (1.0 + self.df.get(term, 0)))

    def concepts(self, query):
        """Query -> [{q, alts: {term: weight}, idf}]"""
        qstems = analyse(query)[:MAX_QUERY_WORDS]
        if not qstems:
            return []
        qgroups = defaultdict(dict)   # index -> {group: weight}
        covered = set()
        for st, g in self.phrases:
            k = len(st)
            for i in range(len(qstems) - k + 1):
                if tuple(qstems[i:i + k]) == st or tuple(one_letter_alias(x) or x for x in qstems[i:i + k]) == st:
                    for j in range(i, i + k):
                        qgroups[j][g] = W_SYNONYM
                        covered.add(j)
        for i, s in enumerate(qstems):
            if i in covered:
                continue
            for key in (s, one_letter_alias(s)):
                for g in self.single.get(key, ()):
                    qgroups[i][g] = W_SYNONYM
        out, seen = [], set()
        for i, q in enumerate(qstems):
            if q in seen:
                continue
            seen.add(q)
            alts = {}
            if q in self.df:
                alts[q] = 1.0
            a = one_letter_alias(q)
            if a and a in self.df:
                alts[a] = max(alts.get(a, 0), 0.95)
            fuzzy = []
            for t in self.candidates(q):
                if t == q:
                    continue
                w = fuzzy_weight(q, t)
                if w > 0:
                    fuzzy.append((w, t))
            for w, t in sorted(fuzzy, reverse=True)[:8]:
                alts[t] = max(alts.get(t, 0), w)
                # a misspelt word also reaches the synonyms of the word it was meant to be
                for g in self.single.get(t, ()):
                    alts[g] = max(alts.get(g, 0), round(w * W_SYNONYM, 4))
            for g, w in qgroups.get(i, {}).items():
                alts[g] = max(alts.get(g, 0), w)
            if q in self.df:
                idf = self.idf(q)
            elif alts:
                idf = max(self.idf(t) for t in alts)
            else:
                idf = self.idf(q)
            out.append(dict(q=q, alts=alts, idf=idf))
        return out

    def support(self, concepts, rid):
        """Tie-breaker: in how many fields each query word (or a close equivalent) appears."""
        d = self.docs.get(rid)
        if not d:
            return 0
        n = 0
        for c in concepts:
            strong = [t for t, w in c['alts'].items() if w >= 0.8]
            n += sum(1 for fs in d['fsets'] if any(t in fs for t in strong))
        return n

    def score(self, concepts, rid, qstems=None):
        d = self.docs.get(rid)
        if not d or not concepts:
            return 0.0, set()
        total = sum(c['idf'] for c in concepts) or 1.0
        acc, matched = 0.0, set()
        hit_stems = []
        for c in concepts:
            best, best_t = 0.0, None
            for t, w in c['alts'].items():
                fw = d['w'].get(t)
                if fw and w * fw > best:
                    best, best_t = w * fw, t
            if best_t:
                if best_t != c['q'] and d['w'].get(c['q']):
                    best = min(1.0, best + 0.15)     # the exact word is there too
                acc += c['idf'] * best
                if best_t.startswith('§'):
                    matched.update(d['groups'].get(best_t, (0, set()))[1])
                else:
                    matched.add(best_t)
                    hit_stems.append(best_t)
        s = acc / total
        # phrase bonus: consecutive query words found next to each other in one field
        if qstems and len(qstems) >= 2 and s > 0:
            pairs = {(qstems[i], qstems[i + 1]) for i in range(len(qstems) - 1)}
            found = 0
            for seq in d['seq']:
                for i in range(len(seq) - 1):
                    if (seq[i], seq[i + 1]) in pairs:
                        found += 1
            s += min(0.15, 0.08 * found)
        return min(1.0, s), matched


_CACHE = {'key': None, 'corpus': None}
_LOCK = threading.Lock()


# ------------------------------------------------------------------ database side
def index_fields(row, agenda=None, category_names=()):
    """Per-field stems of one resolution row (board_decisions + extras)."""
    text = row.get('decision_text') or row.get('decision_description') or ''
    return {
        't': analyse(row.get('decision_title')),
        'g': analyse((row.get('tags') or '').replace(',', ' ')),
        's': analyse(row.get('summary')),
        'c': analyse(' '.join(category_names)),
        'x': analyse(text),
        'a': analyse(agenda or ''),
    }


def reindex(db, rid=None):
    """(Re)compute the stored stems of one resolution, or of every resolution whose
    index is missing / older than the engine version. Returns the number indexed."""
    where = "d.id = %s" if rid else "(d.search_index IS NULL OR COALESCE(d.search_version, 0) < %s)"
    args = (rid,) if rid else (ENGINE_VERSION,)
    rows = db.execute("""
        SELECT d.*, ai.item_title AS agenda_title, ai.item_description AS agenda_desc,
               c.name_en AS cat_en, c.name_ar AS cat_ar
        FROM board_decisions d
        LEFT JOIN meeting_agenda_items ai ON ai.id = d.agenda_item_id
        LEFT JOIN gov_resolution_categories c ON c.code = d.category_code
        WHERE """ + where, args).fetchall()
    for r in rows:
        r = dict(r)
        fields = index_fields(r, ' '.join(x for x in (r.get('agenda_title'), r.get('agenda_desc')) if x),
                              [x for x in (r.get('cat_en'), r.get('cat_ar')) if x])
        norm = ' '.join(' '.join(v) for v in fields.values() if v)
        db.execute("""UPDATE board_decisions SET search_index = %s::jsonb, search_norm = %s, search_version = %s,
                      search_updated_at = NOW() WHERE id = %s""",
                   (json.dumps(fields, ensure_ascii=False), norm, ENGINE_VERSION, r['id']))
    if rows:
        db.commit()
    return len(rows)


def corpus(db):
    reindex(db)
    # version counter bumped by database triggers on resolutions, agenda items, categories and synonyms
    k = db.execute("SELECT version FROM gov_search_state WHERE id = 1").fetchone()
    key = k['version'] if k else None
    with _LOCK:
        if key is not None and _CACHE['key'] == key and _CACHE['corpus'] is not None:
            return _CACHE['corpus']
    docs = {}
    for r in db.execute("SELECT id, search_index FROM board_decisions WHERE search_index IS NOT NULL").fetchall():
        idx = r['search_index']
        if isinstance(idx, str):
            idx = json.loads(idx)
        docs[r['id']] = idx or {}
    syn = [dict(r) for r in db.execute("SELECT group_code, term FROM gov_search_synonyms WHERE is_active").fetchall()]
    c = Corpus(docs, syn)
    with _LOCK:
        _CACHE['key'], _CACHE['corpus'] = key, c
    return c


def rank(corp, query, ids=None, min_score=0.25, limit=200):
    """[(rid, score, matched_stems)] best first."""
    concepts = corp.concepts(query)
    if not concepts:
        return []
    qstems = analyse(query)[:MAX_QUERY_WORDS]
    pool = ids if ids is not None else corp.docs.keys()
    out = []
    for rid in pool:
        s, m = corp.score(concepts, rid, qstems)
        if s >= min_score:
            out.append((rid, s, m, corp.support(concepts, rid)))
    out.sort(key=lambda x: (-round(x[1], 3), -x[3], -x[0]))
    return [(rid, s, m) for rid, s, m, _n in out[:limit]]


def highlight(text, matched):
    """HTML-escaped text with the words whose stem matched wrapped in <mark>."""
    t = str(text or '')
    if not matched or not t:
        return escape(t)
    parts, last = [], 0
    src = t.translate(_DIGITS)
    for m in _WORD.finditer(src):
        stems = [stem(n) for n in norm_word(m.group(0))]
        stems += [a for a in (one_letter_alias(x) for x in stems) if a]
        if any(s in matched for s in stems):
            parts.append(escape(t[last:m.start()]))
            parts.append(Markup('<mark>') + escape(t[m.start():m.end()]) + Markup('</mark>'))
            last = m.end()
    parts.append(escape(t[last:]))
    return Markup('').join(parts)


def snippet(text, matched, width=320):
    """A window of the text around the first matched word, highlighted."""
    t = str(text or '')
    if len(t) <= width:
        return highlight(t, matched)
    pos = 0
    if matched:
        src = t.translate(_DIGITS)
        for m in _WORD.finditer(src):
            stems = [stem(n) for n in norm_word(m.group(0))]
            stems += [a for a in (one_letter_alias(x) for x in stems) if a]
            if any(s in matched for s in stems):
                pos = m.start()
                break
    start = max(0, pos - width // 3)
    end = min(len(t), start + width)
    return (Markup('… ') if start else Markup('')) + highlight(t[start:end], matched) + \
        (Markup(' …') if end < len(t) else Markup(''))
