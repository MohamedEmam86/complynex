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

The corpus is small (about ten thousand entries), so an in-process index gives
sub-millisecond, fully explainable ranking and keeps working when Elasticsearch
is down. Ranking order: exact control code > CAS number > HS / tariff mapping >
phrase in the title > words in the text > fuzzy and cross-language matches.
"""
import math
import re
from collections import Counter, defaultdict

from . import text as T

try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz
except Exception:            # pragma: no cover - rapidfuzz is installed in production
    _rf_process = _rf_fuzz = None

FIELD_W = {'title_en': 3.0, 'title_ar': 3.0, 'text_en': 1.0, 'text_ar': 1.0, 'context_en': 0.5, 'context_ar': 0.5,
           'notes': 0.35, 'names': 3.5}
RISK_ORDER = {'high': 0, 'medium': 1, 'low': 2}


class Doc:
    __slots__ = ('i', 'id', 'list_code', 'code', 'entry_code', 'parent_code', 'level', 'category', 'group',
                 'title_en', 'title_ar', 'text_en', 'text_ar', 'context_en', 'context_ar', 'notes', 'hs', 'cas',
                 'risk', 'reasons',
                 'params', 'kind', 'ar_status', 'extra')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))
        self.hs = list(kw.get('hs') or [])
        self.cas = list(kw.get('cas') or [])
        self.params = list(kw.get('params') or [])
        self.reasons = list(kw.get('reasons') or [])
        self.extra = dict(kw.get('extra') or {})


class Index:
    def __init__(self, docs, terms=(), version=None):
        """docs: iterable of dicts (Doc fields). terms: iterable of (term_en, term_ar) pairs."""
        self.version = version
        self.docs = []
        self.post = defaultdict(dict)          # token -> {doc_i: weight}
        self.title_tok = []                    # per doc: set of title tokens (phrase bonus)
        self.by_code = defaultdict(list)
        self.by_cas = defaultdict(list)
        self.by_hs = defaultdict(set)          # hs prefix (4..10 digits) -> doc indexes
        self.surface = {'en': Counter(), 'ar': Counter()}
        self.surface_of = {}                   # stem -> most common surface word
        for d in docs:
            self._add(Doc(i=len(self.docs), **d))
        n = max(1, len(self.docs))
        self.idf = {t: math.log(1 + n / len(p)) for t, p in self.post.items()}
        self.vocab = {'en': sorted({t for t in self.post if not T.is_arabic(t) and not t[0].isdigit()}),
                      'ar': sorted({t for t in self.post if T.is_arabic(t)})}
        self.syn = defaultdict(set)            # token -> tokens in the other language
        self.terms = []
        for en, ar in terms:
            self.add_term(en, ar)

    # ------------------------------------------------------------- building
    def add_term(self, en, ar):
        en_t = [t for t, _ in T.tokens(en)]
        ar_t = [t for t, _ in T.tokens(ar)]
        if not en_t or not ar_t:
            return
        self.terms.append((en, ar))
        en_key, ar_key = ' '.join(en_t), ' '.join(ar_t)
        self.syn[ar_key].add(en_key)
        self.syn[en_key].add(ar_key)

    def _add(self, d):
        self.docs.append(d)
        weights = defaultdict(float)
        fields = {'title_en': d.title_en, 'title_ar': d.title_ar, 'text_en': d.text_en, 'text_ar': d.text_ar,
                  'context_en': d.context_en, 'context_ar': d.context_ar, 'notes': d.notes,
                  'names': ' '.join(d.extra.get('names') or [])}
        title_tokens = set()
        for f, val in fields.items():
            if not val:
                continue
            toks = T.tokens(val)
            for (t, lang) in toks:
                weights[t] = max(weights[t], FIELD_W[f])
                if f in ('title_en', 'title_ar', 'names'):
                    title_tokens.add(t)
            for w, lang in T.tokens(val, stem=False):
                if lang == 'en' and not w[0].isdigit() and '.' not in w:
                    self.surface['en'][w] += 1
                elif lang == 'ar':
                    self.surface['ar'][w] += 1
                st = T.stem_ar(w) if lang == 'ar' else T.stem_en(w)
                if st not in self.surface_of or self.surface[lang][w] > self.surface[lang].get(self.surface_of[st], 0):
                    self.surface_of[st] = w
        code_l = (d.code or '').lower()
        if code_l:
            weights[code_l] = max(weights[code_l], 5.0)
        for t, w in weights.items():
            self.post[t][d.i] = w
        self.title_tok.append(title_tokens)
        if d.code:
            self.by_code[d.code.lower()].append(d.i)
        for c in d.cas:
            self.by_cas[c].append(d.i)
        for h in d.hs:
            h = re.sub(r'\D', '', str(h))
            for k in range(4, len(h) + 1, 2):
                self.by_hs[h[:k]].add(d.i)

    # ------------------------------------------------------------- query parsing
    def _translations(self, key, w=0.85):
        """Other-language equivalents of a dictionary key (whole phrases), plus same-language synonyms reached
        through them (drone -> طائرة بدون طيار -> unmanned aerial vehicle)."""
        out = []
        for other in self.syn.get(key, ()):
            out.append((tuple(other.split()), w, 'translated'))
            for back in self.syn.get(other, ()):
                if back != key:
                    out.append((tuple(back.split()), w * 0.9, 'translated'))
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
        while i < len(words):            # dictionary phrases first (2-3 words): "آلة تشغيل" is one concept
            for n in (3, 2):
                key = ' '.join(words[i:i + n])
                if len(words[i:i + n]) == n and key in self.syn:
                    groups.append([(tuple(words[i:i + n]), 1.0, 'exact')] + self._translations(key))
                    used.update(range(i, i + n))
                    i += n
                    break
            else:
                i += 1
        for idx, (t, lang) in enumerate(toks):
            if idx in used:
                continue
            g = [((t,), 1.0, 'exact')] + self._translations(t)
            if t not in self.post and len(t) >= 4 and _rf_process is not None and not t[0].isdigit():
                voc = self.vocab['ar' if lang == 'ar' else 'en']
                for cand, score, _ in _rf_process.extract(t, voc, scorer=_rf_fuzz.ratio, limit=3, score_cutoff=82):
                    g.append(((cand,), 0.6 * score / 100, 'fuzzy'))
                    g += [(alt, w * 0.6 * score / 100, 'fuzzy+translated') for alt, w, _ in self._translations(cand, 1.0)]
            if t not in self.post and len(t) >= 4 and len(g) == 1:      # a word still being typed ("encryp")
                voc = self.vocab['ar' if lang == 'ar' else 'en']
                g += [((v,), 0.7, 'prefix') for v in voc if v.startswith(t)][:5]
            groups.append(g)
        return groups

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
                if s > best.get(i, (0,))[0]:
                    best[i] = (s, how, alt)
        return best

    # ------------------------------------------------------------- search
    def search(self, q, filters=None, limit=20, offset=0, show_lists=False):
        filters = filters or {}
        q = (q or '').strip()[:300]
        scores = defaultdict(float)
        why = defaultdict(set)
        matched_terms = defaultdict(set)
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
        for cas in T.find_cas(q):
            exact_kind = exact_kind or 'cas'
            for i in self.by_cas.get(cas, ()):
                scores[i] += 950
                why[i].add('cas')
        hs = T.hs_digits(q) if not code else None
        if hs:
            exact_kind = exact_kind or 'hs'
            hits = set()
            for k in range(len(hs), 3, -1):            # the longest prefix that maps
                key = hs[:k] if k % 2 == 0 else None
                if key and key in self.by_hs:
                    hits = self.by_hs[key]
                    break
            for i in hits:
                scores[i] += 600
                why[i].add('hs')

        if not q:                                       # browse by filters: the main entries only
            exact_kind = 'browse'
            for d in self.docs:
                if d.level == 0:
                    scores[d.i] = 1.0
        qty = T.quantities(q)
        # values with units ("6 GHz") are compared with the thresholds below, not searched as words
        q_words = T.strip_quantities(q) if qty else q
        text_groups = [] if (not q or code or (hs and len(q.split()) == 1)) else self._expand(q_words)
        n_groups = len(text_groups)
        if text_groups:
            per_doc_groups = defaultdict(int)
            for g in text_groups:
                for i, (s, how, alt) in self._score_group(g).items():
                    scores[i] += s
                    per_doc_groups[i] += 1
                    why[i].add('translated' if 'translated' in how else how)
                    matched_terms[i].update(alt)
            for i, k in per_doc_groups.items():
                cov = k / n_groups
                scores[i] *= (0.35 + cov)
                if k == n_groups:
                    title_hit = sum(1 for g in text_groups
                                    if any(all(t in self.title_tok[i] for t in alt) for alt, _, _ in g))
                    if title_hit == n_groups:
                        scores[i] *= 1.4
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

        min_score = 0.0 if exact_kind else 0.6
        ranked = [i for i in scores if scores[i] > min_score and keep(self.docs[i])]
        ranked.sort(key=lambda i: (-scores[i], RISK_ORDER.get(self.docs[i].risk, 3), self.docs[i].code or ''))
        # merge the same control code published by several lists into one result
        merged, seen = [], {}
        for i in ranked:
            d = self.docs[i]
            key = (d.kind, (d.code or '').lower())
            if key in seen:
                seen[key]['also'].append(d.list_code)
                continue
            r = {'doc': d, 'score': round(scores[i], 2), 'why': sorted(why[i]), 'also': [],
                 'terms': sorted(matched_terms[i]), 'meets': meets.get(i, [])}
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
            r['snippet_en'] = T.snippet(d.text_en or d.title_en, ts)
            r['snippet_ar'] = T.snippet(d.text_ar or d.title_ar or '', ts) if (d.text_ar or d.title_ar) else ''
        return {'total': total, 'results': page, 'facets': facets, 'exact': exact_kind, 'query': q,
                'groups': len(text_groups)}

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
            for k in sorted(self.by_code):
                if k.startswith(cl):
                    d = self.docs[self.by_code[k][0]]
                    out.append({'type': 'code', 'value': d.code, 'label': (d.title_en or d.text_en or '')[:90],
                                'label_ar': (d.title_ar or '')[:90]})
                    if len(out) >= limit:
                        return out
        if re.match(r'^\d{2,7}-', p):
            for c in sorted(self.by_cas):
                if c.startswith(p):
                    d = self.docs[self.by_cas[c][0]]
                    out.append({'type': 'cas', 'value': c, 'label': (d.title_en or '')[:90], 'label_ar': ''})
                    if len(out) >= limit:
                        return out
        last = T.fold(p).split()[-1] if p.split() else ''
        lang = 'ar' if T.is_arabic(last) else 'en'
        head = ' '.join(p.split()[:-1])
        cands = [(w, n) for w, n in self.surface[lang].items() if w.startswith(last) and len(w) > len(last)]
        if lang == 'ar':
            last_s = T.stem_ar(last)
            cands += [(w, n) for w, n in self.surface[lang].items()
                      if T.stem_ar(w).startswith(last_s) and not w.startswith(last)]
        for w, _ in sorted(cands, key=lambda x: -x[1])[:limit - len(out)]:
            out.append({'type': 'term', 'value': (head + ' ' + w).strip(), 'label': '', 'label_ar': ''})
        # dictionary terms in the other language
        for en, ar in self.terms:
            if len(out) >= limit:
                break
            if T.fold(ar).startswith(T.fold(p)) or T.fold(en).startswith(T.fold(p)):
                out.append({'type': 'term', 'value': ar if T.is_arabic(p) else en,
                            'label': en if T.is_arabic(p) else ar, 'label_ar': ''})
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

    def family(self, d):
        """Children of an entry (direct and deeper) in the same list, ordered by code."""
        pre = (d.code or '').lower() + '.'
        out = []
        for k, idxs in self.by_code.items():
            if k.startswith(pre):
                out += [self.docs[i] for i in idxs if self.docs[i].list_code == d.list_code]
        return sorted(out, key=lambda x: x.code)
