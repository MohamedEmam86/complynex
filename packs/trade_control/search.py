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
"""In-memory bilingual search index over the dual-use control entries.

Why in-process and not Elasticsearch: the corpus is small (about ten thousand control entries, chemicals and
tariff mappings, rebuilt in a few seconds when a list version changes), so a Python index gives
millisecond, fully explainable ranking (every hit says WHY it matched), needs no extra service and keeps
working when Elasticsearch or Redis are down. PostgreSQL full-text search was not used either: it has no
Arabic stemmer, and the cross-language dictionary, unit-aware thresholds and code / CAS / HS logic would sit
outside it anyway.

Ranking: exact control code > CAS number > HS / tariff mapping > words. Word scoring is BM25-like (idf,
field weight, length normalisation) plus bonuses for adjacent words ("frequency synthesizer" as a phrase),
for words at the head of the entry and for a value that meets a threshold ("40 GHz"). Each query word is a
concept group: the word itself, its dictionary translations (Arabic <-> English), English synonyms and,
for unknown words, spelling corrections and completions.
"""
import math
import re
from collections import Counter, defaultdict

from . import text as T

try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz
except Exception:            # pragma: no cover - rapidfuzz is installed in production
    _rf_process = _rf_fuzz = None

FIELD_W = {'title_en': 3.0, 'title_ar': 3.0, 'text_en': 1.0, 'text_ar': 1.0, 'context_en': 0.4, 'context_ar': 0.4,
           'notes': 0.3, 'names': 3.5}
TEXT_FIELDS = ('text_en', 'text_ar', 'notes')
RISK_ORDER = {'high': 0, 'medium': 1, 'low': 2}
HS_AFFINITY = {'84': ('2', '3', '4', '5'), '85': ('3', '4', '5', '6'), '90': ('3', '6', '7', '2'),
               '88': ('9', '7'), '93': ('0', '1'), '28': ('1',), '29': ('1',), '38': ('1',), '81': ('1',),
               '72': ('1', '2'), '76': ('1',), '89': ('8',), '87': ('0', '9')}
Y_ITEM = re.compile(r'^\d[A-E][56]\d{2}\.y\b')
UNKNOWN_IDF = 5.0            # weight of a query word that no entry uses
LEAD = 10                    # words at the head of an entry ("Cameras, systems ...")
HOW_W = {'exact': 1.0, 'translated': 0.85, 'synonym': 0.8, 'fuzzy': 0.6, 'prefix': 0.7}


class Doc:
    __slots__ = ('i', 'id', 'list_code', 'code', 'entry_code', 'parent_code', 'level', 'category', 'group',
                 'title_en', 'title_ar', 'text_en', 'text_ar', 'context_en', 'context_ar', 'notes', 'hs', 'cas',
                 'risk', 'reasons', 'params', 'kind', 'ar_status', 'extra', 'index_text')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))
        self.hs = list(kw.get('hs') or [])
        self.cas = list(kw.get('cas') or [])
        self.params = list(kw.get('params') or [])
        self.reasons = list(kw.get('reasons') or [])
        self.extra = dict(kw.get('extra') or {})

    @property
    def title(self):
        return self.title_en or (self.text_en or '')[:200]


class Index:
    def __init__(self, docs, terms=(), version=None, synonyms=()):
        """docs: iterable of dicts (Doc fields). terms: (term_en, term_ar) pairs. synonyms: lists of
        same-language phrases that mean the same thing (["drone", "UAV", "unmanned aerial vehicle"])."""
        self.version = version
        self.docs = []
        self.readiness = None              # set by the service: which lists are loaded
        self.post = defaultdict(dict)          # token -> {doc_i: weight}
        self.title_tok = []                    # per doc: set of title tokens (phrase bonus)
        self.lead_tok = []                     # per doc: {token: first position} among the first LEAD words
        self.bigrams = []                      # per doc: set of adjacent token pairs
        self.by_code = defaultdict(list)
        self.by_cas = defaultdict(list)
        self.by_hs = defaultdict(set)          # hs prefix (4..10 digits) -> doc indexes
        self.hs_exact = defaultdict(set)       # full hs / cn code as published -> doc indexes
        self.surface = {'en': Counter(), 'ar': Counter()}
        self.surface_of = {}                   # stem -> most common surface word
        raw = []
        for d in docs:
            doc = Doc(i=len(self.docs), **d)
            self.docs.append(doc)
            raw.append(self._fields(doc))
        lens = [sum(len(v) for f, v in r.items() if f in TEXT_FIELDS) for r in raw]
        self.avgdl = (sum(lens) / len(lens)) if lens else 1.0
        for doc, fields, dl in zip(self.docs, raw, lens):
            self._add(doc, fields, dl)
        n = max(1, len(self.docs))
        self.idf = {t: math.log(1 + n / len(p)) for t, p in self.post.items()}
        self.vocab = {'en': sorted({t for t in self.post if not T.is_arabic(t) and not t[0].isdigit()}),
                      'ar': sorted({t for t in self.post if T.is_arabic(t)})}
        self.syn = defaultdict(dict)           # phrase key -> {other phrase key: 'translated' | 'synonym'}
        self.terms = []
        for en, ar in terms:
            self.add_term(en, ar)
        for group in synonyms:
            self.add_synonyms(group)
        # an empty index can never clear anything; the service also checks every list kind is loaded
        self.ready = bool(self.docs)

    # ------------------------------------------------------------- building
    @staticmethod
    def _key(s):
        return ' '.join(t for t, _ in T.tokens(s))

    def add_term(self, en, ar):
        en_k, ar_k = self._key(en), self._key(ar)
        if not en_k or not ar_k or en_k == ar_k:
            return
        self.terms.append((en, ar))
        self.syn[ar_k][en_k] = 'translated'
        self.syn[en_k][ar_k] = 'translated'

    def add_synonyms(self, group):
        keys = [k for k in dict.fromkeys(self._key(g) for g in group) if k]
        for a in keys:
            for b in keys:
                if a != b and self.syn[a].get(b) != 'translated':
                    self.syn[a][b] = 'synonym'

    def _fields(self, d):
        """field -> stemmed tokens (in order)."""
        text_en = d.index_text if d.index_text is not None else d.text_en
        vals = {'title_en': d.title_en, 'title_ar': d.title_ar, 'text_en': text_en, 'text_ar': d.text_ar,
                'context_en': d.context_en, 'context_ar': d.context_ar, 'notes': d.notes,
                'names': ' '.join(d.extra.get('names') or [])}
        out = {}
        for f, val in vals.items():
            if not val:
                continue
            out[f] = [t for t, _ in T.tokens(val)]
            if f in ('title_en', 'title_ar', 'text_en', 'text_ar', 'names'):
                for w, lang in T.tokens(val, stem=False):
                    if lang == 'en' and (w[0].isdigit() or '.' in w):
                        continue
                    self.surface[lang][w] += 1
                    st = T.stem_ar(w) if lang == 'ar' else T.stem_en(w)
                    cur = self.surface_of.get(st)
                    if cur is None or self.surface[lang][w] > self.surface[lang].get(cur, 0):
                        self.surface_of[st] = w
        return out

    def _add(self, d, fields, dl):
        norm = 1.0 / (0.55 + 0.45 * min(4.0, dl / (self.avgdl or 1.0)))
        weights = defaultdict(float)
        title_tokens, lead, pairs = set(), {}, set()
        for f, toks in fields.items():
            fw = FIELD_W[f] * (norm if f in TEXT_FIELDS else 1.0)
            for t in toks:
                weights[t] = max(weights[t], fw)
            if f in ('title_en', 'title_ar', 'names'):
                title_tokens.update(toks)
            if f in ('title_en', 'title_ar', 'text_en', 'text_ar', 'names'):
                for pos, t in enumerate(toks[:LEAD]):
                    lead[t] = min(pos, lead.get(t, LEAD))
                pairs.update(zip(toks, toks[1:]))
        code_l = (d.code or '').lower()
        if code_l:
            weights[code_l] = max(weights[code_l], 5.0)
        for t, w in weights.items():
            self.post[t][d.i] = w
        self.title_tok.append(title_tokens)
        self.lead_tok.append(lead)
        self.bigrams.append(pairs)
        if d.code:
            self.by_code[d.code.lower()].append(d.i)
        for c in d.cas:
            self.by_cas[c].append(d.i)
        for h in d.hs:
            h = re.sub(r'\D', '', str(h))
            self.hs_exact[h].add(d.i)
            for k in range(4, len(h) + 1, 2):
                self.by_hs[h[:k]].add(d.i)

    # ------------------------------------------------------------- query parsing
    def _related(self, key, w=1.0):
        """Translations and synonyms of a phrase key, one hop plus the same-language synonyms reached through a
        translation (drone -> طائرة بدون طيار -> unmanned aerial vehicle)."""
        out = []
        for other, kind in self.syn.get(key, {}).items():
            out.append((tuple(other.split()), w * HOW_W[kind], kind))
            if kind == 'translated':
                for back, k2 in self.syn.get(other, {}).items():
                    if back != key:
                        out.append((tuple(back.split()), w * HOW_W[kind] * 0.9, 'translated'))
        return out

    def _expand(self, q):
        """Query -> list of concept groups; each group is a list of alternatives (tokens, weight, how).
        A document scores a group by its best alternative; a multi-word alternative counts in full only
        when all its words are present (a partial match is damped by the square of the share present)."""
        groups = []
        toks = T.tokens(q)
        words = [t for t, _ in toks]
        used = set()
        i = 0
        while i < len(words):            # dictionary phrases first (2-4 words): "آلة تشغيل" is one concept
            for n in (4, 3, 2):
                key = ' '.join(words[i:i + n])
                if len(words[i:i + n]) == n and key in self.syn:
                    groups.append([(tuple(words[i:i + n]), 1.0, 'exact')] + self._related(key))
                    used.update(range(i, i + n))
                    i += n
                    break
            else:
                i += 1
        for idx, (t, lang) in enumerate(toks):
            if idx in used:
                continue
            g = [((t,), 1.0, 'exact')] + self._related(t)
            known = t in self.post or t in self.syn
            if not known and len(t) >= 4 and _rf_process is not None and not t[0].isdigit():
                voc = self.vocab['ar' if lang == 'ar' else 'en']
                # a real word missing from the lists is not "corrected" into another real word
                # (hydrofluoric -> hydrochloric): the cut-off is high and the first letters must agree
                for cand, score, _ in _rf_process.extract(t, voc, scorer=_rf_fuzz.ratio, limit=3, score_cutoff=86):
                    if cand[:2] != t[:2]:
                        continue
                    g.append(((cand,), HOW_W['fuzzy'] * score / 100, 'fuzzy'))
                    g += [(alt, w * HOW_W['fuzzy'] * score / 100, 'fuzzy') for alt, w, _ in self._related(cand)]
                dict_keys = [k for k in self.syn if ' ' not in k and (T.is_arabic(k) == (lang == 'ar'))]
                for cand, score, _ in _rf_process.extract(t, dict_keys, scorer=_rf_fuzz.ratio, limit=2,
                                                          score_cutoff=82):
                    g += [(alt, w * HOW_W['fuzzy'] * score / 100, 'fuzzy') for alt, w, _ in self._related(cand)]
            if not known and len(t) >= 3 and len(g) == 1:      # a word still being typed ("encryp")
                voc = self.vocab['ar' if lang == 'ar' else 'en']
                g += [((v,), HOW_W['prefix'], 'prefix') for v in voc if v.startswith(t)][:5]
                if len(g) == 1 and len(t) >= 5:     # a known stem plus a typo at the end ("imagin" -> imag)
                    g += [((v,), HOW_W['prefix'], 'prefix') for v in voc
                          if len(v) >= 4 and t.startswith(v) and len(t) - len(v) <= 3][:3]
            # the same concept typed twice ("quadcopter drone", "drone UAV") counts once
            alts = {a for a, _, _ in g}
            if any((t,) in {a for a, _, _ in prev} or alts & {a for a, _, _ in prev} - {()} and
                   (t,) in {a for a, _, _ in prev} for prev in groups):
                continue
            if any(len(alts & {a for a, _, _ in prev}) >= 2 for prev in groups):
                continue
            groups.append(g)
        return groups, words

    def _group_weight(self, g):
        """How informative a query concept is: the idf of its own words; a word the lists never use counts
        as fairly informative ('office' in 'office chairs' is why that query is not a controlled item)."""
        toks = [t for t in g[0][0] if len(t) > 2 and not any(c.isdigit() for c in t)]
        if not toks:
            return 0.0
        return max(self.idf.get(t, UNKNOWN_IDF) for t in toks)

    def _score_group(self, g):
        """{doc: (score, how, tokens)} for one concept group."""
        best = {}
        for alt, w, how in g:
            acc = defaultdict(float)
            hit = defaultdict(int)
            for tok in alt:
                for i, fw in self.post.get(tok, {}).items():
                    acc[i] += self.idf.get(tok, 1.0) * fw
                    hit[i] += 1
            for i, s in acc.items():
                s = s * w * (hit[i] / len(alt)) ** 2
                if len(alt) > 1 and hit[i] == len(alt) and all(p in self.bigrams[i] for p in zip(alt, alt[1:])):
                    s *= 1.3                                   # the phrase itself, words adjacent
                if s > best.get(i, (0,))[0]:
                    best[i] = (s, how, alt)
        return best

    # ------------------------------------------------------------- identifiers in the query
    def _cas_in(self, q):
        out = list(T.find_cas(q))
        for d in re.findall(r'(?<![\d.\-])(\d{5,10})(?![\d.\-])', q):   # CAS typed without dashes
            c = '%s-%s-%s' % (d[:-3].lstrip('0') or '0', d[-3:-1], d[-1])
            if T.cas_valid(c) and c in self.by_cas:
                out.append(c)
        return list(dict.fromkeys(out))

    # ------------------------------------------------------------- search
    def search(self, q, filters=None, limit=20, offset=0, show_lists=False):
        filters = filters or {}
        q = (q or '').strip()[:300]
        scores = defaultdict(float)
        why = defaultdict(set)
        matched_terms = defaultdict(set)
        coverage = defaultdict(float)          # idf-weighted share of the query's concepts found in the entry
        exact_kind = None

        code = T.control_code(q)
        if code:
            exact_kind = 'code'
            cl = code.lower()
            for k, idxs in self.by_code.items():
                if k == cl:
                    for i in idxs:
                        scores[i] += 1000
                        why[i].add('code')
                elif k.startswith(cl + '.'):
                    for i in idxs:
                        scores[i] += 700 - 20 * k.count('.')
                        why[i].add('code')
        cas_hits = self._cas_in(q)
        for cas in cas_hits:
            exact_kind = exact_kind or 'cas'
            for i in self.by_cas.get(cas, ()):
                scores[i] += 950 + (30 if self.docs[i].kind == 'chemical' else 0)
                why[i].add('cas')
        hs = T.hs_digits(q) if not (code or cas_hits) else None
        if hs:
            exact_kind = exact_kind or 'hs'
            for k in range(len(hs), 3, -1):            # the longest prefix that maps
                if k % 2 == 0 and hs[:k] in self.by_hs:
                    for i in self.by_hs[hs[:k]]:
                        d = self.docs[i]
                        exact = any(re.sub(r'\D', '', str(h)).startswith(hs[:k]) and len(re.sub(r'\D', '', str(h))) <= k
                                    for h in d.hs)
                        # most specific mapping first: priority heading, exact code, entries mapped by few
                        # tariff lines, then the categories that usually match the tariff chapter
                        scores[i] += 600 + 10 * k + (40 if d.kind == 'priority' else 0) + (20 if exact else 0) \
                            - 3 * (d.level or 0) - min(30, len(d.hs) / 4.0) \
                            + (15 if d.category in HS_AFFINITY.get(hs[:2], ()) else 0)
                        why[i].add('hs')
                    break

        if not q:                                       # browse by filters: the main entries only
            exact_kind = 'browse'
            for d in self.docs:
                if d.level == 0:
                    scores[d.i] = 1.0
        qty = T.quantities(q)
        # values with units ("6 GHz") are compared with the thresholds below, not searched as words
        q_words = T.strip_quantities(q) if qty else q
        single_id = bool(code or cas_hits or hs) and len(q.split()) == 1
        text_groups, q_tokens = ([], []) if (not q or single_id) else self._expand(q_words)
        n_groups = len(text_groups)
        if text_groups:
            per_doc_groups = defaultdict(int)
            lead_hits = defaultdict(int)
            gw = [self._group_weight(g) for g in text_groups]
            total_w = sum(gw) or 1.0
            for g, w_g in zip(text_groups, gw):
                for i, (s, how, alt) in self._score_group(g).items():
                    scores[i] += s
                    per_doc_groups[i] += 1
                    coverage[i] += w_g * (0.5 if how in ('fuzzy', 'prefix') else 1.0) / total_w
                    why[i].add(how)
                    matched_terms[i].update(alt)
                    pos = min((self.lead_tok[i].get(t, LEAD) for t in alt), default=LEAD)
                    if pos < LEAD:
                        lead_hits[i] += 1 - pos / LEAD     # the earlier the better: the head noun of the entry
            pairs = list(zip(q_tokens, q_tokens[1:]))
            wants_sw = bool({'software', 'technology', 'program', 'firmware', 'know-how', 'source',
                             'برمج', 'برنامج', 'تقني', 'تكنولوجيا'} & set(q_tokens))
            for i, k in per_doc_groups.items():
                cov = k / n_groups
                scores[i] *= (0.35 + cov)
                scores[i] *= 1 + 0.5 * lead_hits[i] / n_groups
                d = self.docs[i]
                if d.group in ('D', 'E') and not wants_sw:
                    scores[i] *= 0.35                  # software / technology entries after the goods themselves
                if Y_ITEM.match(d.code or ''):
                    scores[i] *= 0.4                   # ".y" parts of the 500/600 series (knobs, pads, switches)
                if d.kind == 'priority':
                    scores[i] *= 0.75                  # tariff-heading hints rank after the control entries
                if pairs:
                    adj = sum(1 for p in pairs if p in self.bigrams[i])
                    if adj:
                        scores[i] *= 1 + 0.35 * adj / len(pairs)
                        why[i].add('phrase')
                if k == n_groups:
                    title_hit = sum(1 for g in text_groups
                                    if any(all(t in self.title_tok[i] for t in alt)
                                           for alt, _, how in g if how in ('exact', 'translated')))
                    if title_hit == n_groups:
                        scores[i] *= 1.3
                        why[i].add('phrase')
        meets = defaultdict(list)
        if qty:
            for i in list(scores):
                for p in self.docs[i].params:
                    for v, base, raw in qty:
                        if p.get('base_unit') == base and p.get('base_value') is not None:
                            ok = T.compare(v, p.get('operator'), p['base_value'])
                            if ok:
                                meets[i].append((raw, p))
                                scores[i] *= 1.25
                                why[i].add('threshold')
                                break

        # filters
        def keep(d):
            if filters.get('category') and d.category != filters['category']:
                return False
            if filters.get('group') and d.group != filters['group']:
                return False
            if filters.get('risk') and d.risk != filters['risk']:
                return False
            if filters.get('kind') and d.kind != filters['kind']:
                return False
            if show_lists and filters.get('list') and d.list_code != filters['list']:
                return False
            if filters.get('chapter') and not any(str(h).startswith(filters['chapter']) for h in d.hs):
                return False
            return True

        top = max(scores.values()) if scores else 0
        min_score = 0.0 if exact_kind else max(0.6, 0.04 * top)
        ranked = [i for i in scores if scores[i] > min_score and keep(self.docs[i])
                  and (exact_kind or not text_groups or coverage.get(i, 0) >= 0.15)]
        ranked.sort(key=lambda i: (-round(scores[i], 3), RISK_ORDER.get(self.docs[i].risk, 3), self.docs[i].level or 0,
                                   self.docs[i].code or ''))
        # merge the same control code published by several lists into one result
        merged, seen = [], {}
        for i in ranked:
            d = self.docs[i]
            key = (d.kind, (d.code or '').lower())
            if key in seen:
                if d.list_code not in seen[key]['also'] and d.list_code != seen[key]['doc'].list_code:
                    seen[key]['also'].append(d.list_code)
                continue
            r = {'doc': d, 'score': round(scores[i], 2), 'why': sorted(why[i]), 'also': [],
                 'terms': sorted(matched_terms[i]), 'meets': meets.get(i, []),
                 'coverage': round(coverage.get(i, 1.0 if exact_kind else 0.0), 3)}
            seen[key] = r
            merged.append(r)
        facets = self._facets([r['doc'] for r in merged], show_lists)
        total = len(merged)
        page = merged[offset:offset + limit]
        terms_for_snip = set()
        for g in text_groups:
            for alt, _, _ in g:
                for t in alt:
                    terms_for_snip.add(t)
                    terms_for_snip.add(self.surface_of.get(t, t))
        for r in page:
            d = r['doc']
            ts = set(r['terms']) | {self.surface_of.get(t, t) for t in r['terms']} | terms_for_snip
            ts |= {m[0] for m in r['meets']}
            body = d.index_text if d.index_text is not None else (d.text_en or d.title_en)
            r['snippet_en'] = T.snippet(body, ts) if body and body != d.title_en else ''
            r['snippet_ar'] = T.snippet(d.text_ar or d.title_ar or '', ts) if (d.text_ar or d.title_ar) else ''
        return {'total': total, 'results': page, 'facets': facets, 'exact': exact_kind, 'query': q,
                'groups': len(text_groups),
                'expanded': sorted({' '.join(self.surface_of.get(t, t) for t in alt)
                                    for g in text_groups for alt, _, how in g if how != 'exact'})[:12]}

    @staticmethod
    def _facets(docs, show_lists):
        f = {'category': Counter(), 'group': Counter(), 'risk': Counter(), 'kind': Counter(), 'chapter': Counter()}
        if show_lists:
            f['list'] = Counter()
        for d in docs:
            if d.category:
                f['category'][d.category] += 1
            if d.group:
                f['group'][d.group] += 1
            if d.risk:
                f['risk'][d.risk] += 1
            if d.kind:
                f['kind'][d.kind] += 1
            for ch in {str(h)[:2] for h in d.hs}:
                f['chapter'][ch] += 1
            if show_lists:
                f['list'][d.list_code] += 1
        return {k: v.most_common(30) for k, v in f.items()}

    # ------------------------------------------------------------- autocomplete
    def suggest(self, prefix, limit=8):
        p = (prefix or '').strip()
        if len(p) < 2:
            return []
        out = []
        code = T.control_code(p) or (p.upper() if re.match(r'^\d[A-Ea-e]\d{0,3}', p) else None)
        if code:
            cl = code.lower()
            for k in sorted(self.by_code, key=lambda x: (x.count('.'), x)):
                if k.startswith(cl):
                    d = self.docs[self.by_code[k][0]]
                    out.append({'type': 'code', 'value': d.code, 'label': (d.title_en or d.text_en or '')[:90],
                                'label_ar': (d.title_ar or '')[:90]})
                    if len(out) >= limit:
                        return out
        digits = re.sub(r'[\s.\-]', '', p)
        if re.match(r'^\d{2,7}-', p) or (digits.isdigit() and len(digits) >= 5):
            for c in sorted(self.by_cas):
                if c.startswith(p) or c.replace('-', '').startswith(digits):
                    d = self.docs[self.by_cas[c][0]]
                    out.append({'type': 'cas', 'value': c, 'label': (d.title_en or '')[:90], 'label_ar': ''})
                    if len(out) >= limit:
                        return out
        if digits.isdigit() and len(digits) >= 4 and not re.match(r'^\d{2,7}-', p):
            for h in sorted(k for k in self.hs_exact if k.startswith(digits))[:limit - len(out)]:
                d = self.docs[sorted(self.hs_exact[h])[0]]
                label = d.title_en if d.kind == 'priority' else (d.code + ' ' + (d.title_en or d.text_en or ''))
                out.append({'type': 'hs', 'value': '%s.%s%s' % (h[:4], h[4:6], ('.' + h[6:]) if len(h) > 6 else ''),
                            'label': (label or '')[:90], 'label_ar': ''})
            if out:
                return out[:limit]
        last = T.fold(p).split()[-1] if p.split() else ''
        lang = 'ar' if T.is_arabic(last) else 'en'
        head = ' '.join(p.split()[:-1])
        cands = [(w, n) for w, n in self.surface[lang].items() if w.startswith(last) and len(w) > len(last)]
        if lang == 'ar':
            last_s = T.stem_ar(last)
            cands += [(w, n) for w, n in self.surface[lang].items()
                      if T.stem_ar(w).startswith(last_s) and not w.startswith(last)]
        # dictionary terms first: they are the product names people type
        fp = T.fold(p)
        for en, ar in self.terms:
            if len(out) >= limit // 2:
                break
            if T.fold(ar).startswith(fp) or T.fold(en).startswith(fp):
                out.append({'type': 'term', 'value': ar if T.is_arabic(p) else en,
                            'label': en if T.is_arabic(p) else ar, 'label_ar': ''})
        for w, _ in sorted(cands, key=lambda x: -x[1])[:limit]:
            out.append({'type': 'term', 'value': (head + ' ' + w).strip(), 'label': '', 'label_ar': ''})
        seen, uniq = set(), []
        for o in out:
            if o['value'] not in seen:
                seen.add(o['value'])
                uniq.append(o)
        return uniq[:limit]

    def get(self, list_code, code):
        for i in self.by_code.get((code or '').lower(), ()):
            if self.docs[i].list_code == list_code:
                return self.docs[i]
        return None

    def by_id(self, doc_id):
        if not hasattr(self, '_ids'):
            self._ids = {d.id: d for d in self.docs}
        return self._ids.get(doc_id)

    def family(self, d):
        """Children of an entry (direct and deeper) in the same list, ordered by code."""
        pre = (d.code or '').lower() + '.'
        out = []
        for k, idxs in self.by_code.items():
            if k.startswith(pre):
                out += [self.docs[i] for i in idxs if self.docs[i].list_code == d.list_code]
        return sorted(out, key=lambda x: _code_key(x.code))


def _code_key(code):
    """5A002.a.10 after 5A002.a.9."""
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in re.split(r'\.', code or '')]
