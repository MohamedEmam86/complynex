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
"""Screening of one product line against the control lists (pure logic).

Stages: HS / tariff pre-filter -> CAS exact -> text search on the description and
model -> 2 to 5 targeted questions on the technical thresholds. An HS code alone
never clears or confirms an item: it only proposes candidates.

The result is a SUGGESTION (clear / review / hold). The user records the final
decision with a reason and a comment.
"""
import hashlib
import re

from . import text as T

MAX_CANDIDATES = 6
MAX_QUESTIONS = 5
OUTCOMES = ('clear', 'review', 'hold')

HARD_LABELS = {
    'cwc': ('Chemical on a chemical-weapons schedule', 'مادة كيميائية مدرجة في جداول الأسلحة الكيميائية'),
    'precursor': ('Chemical-weapons precursor', 'سلائف أسلحة كيميائية'),
    'priority': ('High-priority item (diversion risk)', 'صنف عالي الأولوية (خطر تحويل الاستخدام)'),
    'code': ('Control code given on the document', 'كود الرقابة مذكور في المستند'),
}
OP_TEXT = {'>': ('more than', 'أكثر من'), '>=': ('at least', 'لا يقل عن'), '<': ('less than', 'أقل من'),
           '<=': ('at most', 'لا يزيد عن')}


def line_key(line):
    """Item-master key: the same product (model / description + HS + CAS) reuses an earlier decision."""
    model = re.sub(r'[^a-z0-9]', '', (line.get('model') or '').lower())
    desc = ' '.join(t for t, _ in T.tokens(line.get('description') or ''))
    base = model or desc
    if not base:
        return None
    raw = '|'.join([base, re.sub(r'\D', '', line.get('hs_code') or '')[:8], (line.get('cas') or '').strip()])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def _cand(d, reason, strength):
    return {'list_code': d.list_code, 'code': d.code, 'kind': d.kind, 'title_en': d.title_en or (d.text_en or '')[:200],
            'title_ar': d.title_ar or '', 'risk': d.risk, 'reasons': [reason], 'strength': strength,
            'category': d.category, 'group': d.group, 'lists': [d.list_code]}


def find_candidates(index, line):
    """(candidates, hard_flags). Candidates are control entries; hard flags are hits that suggest a hold."""
    cands, hard = {}, []

    def add(d, reason, strength):
        if d.kind == 'priority':
            hard.append({'flag': 'priority', 'code': d.code, 'tier': d.extra.get('tier'), 'list_code': d.list_code})
            return
        key = (d.code or '').lower()          # one candidate per control code, whichever list publishes it
        if key in cands:
            c = cands[key]
            if reason not in c['reasons']:
                c['reasons'].append(reason)
            c['strength'] = max(c['strength'], strength)
            if d.list_code not in c['lists']:
                c['lists'].append(d.list_code)
        else:
            cands[key] = _cand(d, reason, strength)

    # 1. a control code written on the invoice / description
    for word in re.findall(r'\b\d[A-Ea-e]\d{3}(?:\.[a-z0-9]{1,3})*\b', ' '.join(
            str(line.get(k) or '') for k in ('description', 'model', 'control_code'))):
        code = T.control_code(word)
        for i in index.by_code.get(code.lower(), ()) if code else ():
            add(index.docs[i], 'code', 1.0)
            hard.append({'flag': 'code', 'code': index.docs[i].code, 'list_code': index.docs[i].list_code})
    # 2. HS / tariff code
    hs = T.hs_digits(line.get('hs_code') or '')
    if hs:
        for k in range(len(hs), 3, -1):
            if k % 2 == 0 and hs[:k] in index.by_hs:
                for i in index.by_hs[hs[:k]]:
                    add(index.docs[i], 'hs', 0.5 if k >= 6 else 0.3)
                break
    # 3. CAS number
    for cas in set(T.find_cas(line.get('cas') or '') + T.find_cas(line.get('description') or '')):
        for i in index.by_cas.get(cas, ()):
            d = index.docs[i]
            if d.kind == 'chemical':
                if d.extra.get('cwc_schedule'):
                    hard.append({'flag': 'cwc', 'code': cas, 'schedule': d.extra['cwc_schedule'],
                                 'list_code': d.list_code})
                if d.extra.get('ag_precursor'):
                    hard.append({'flag': 'precursor', 'code': cas, 'list_code': d.list_code})
                for ref in d.extra.get('item_codes') or []:
                    for j in index.by_code.get(ref.lower(), ()):
                        add(index.docs[j], 'cas', 0.95)
            else:
                add(d, 'cas', 0.95)
    # 4. text: description and model
    q = ' '.join(x for x in (line.get('description'), line.get('model')) if x)
    if q.strip():
        res = index.search(q, limit=12)
        top = res['results'][0]['score'] if res['results'] else 0
        for r in res['results']:
            d = r['doc']
            if d.kind == 'chemical':
                continue
            if r['score'] >= max(2.5, 0.35 * top):
                add(d, 'text', min(0.9, r['score'] / (top or 1) * 0.8))
    ordered = sorted(cands.values(), key=lambda c: (-c['strength'], -len(c['reasons']), c['code']))
    return ordered[:MAX_CANDIDATES], _dedupe(hard)


def _dedupe(hard):
    seen, out = set(), []
    for h in hard:
        k = (h['flag'], h.get('code'))
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out


def _clean_param(name):
    name = re.sub(r'^(?:a|an|the|its|their|having|with)\s+', '', (name or '').strip(), flags=re.I)
    name = re.sub(r'\s+(?:of|at|for|in)$', '', name)
    return name[:1].upper() + name[1:] if name else 'Value'


def questions_for(index, candidates, line=None, limit=MAX_QUESTIONS):
    """Targeted yes / no / value questions, at most `limit`, spread across the candidates (strongest first).
    Thresholds whose parameter words appear in the product description are asked first."""
    desc_tokens = {t for t, _ in T.tokens(' '.join(str((line or {}).get(k) or '') for k in ('description', 'model')))}
    qs, seen = [], set()
    per = max(1, limit // max(1, len(candidates))) if candidates else 0
    for c in candidates:
        d = index.get(c['list_code'], c['code'])
        if d is None:
            continue
        pool = [(p, d) for p in d.params]
        if not pool:
            pool = [(p, ch) for ch in index.family(d)[:40] for p in ch.params]

        def rel(item):
            p, owner = item
            words = {t for t, _ in T.tokens((p.get('parameter') or '') + ' ' + (owner.text_en or '')[:300])}
            return -len(words & desc_tokens)
        pool.sort(key=rel)
        taken = 0
        for p, owner in pool:
            if taken >= max(1, per) or len(qs) >= limit:
                break
            if p.get('operator') not in OP_TEXT or p.get('value') is None:
                continue
            name = _clean_param(p.get('parameter'))
            en, ar = OP_TEXT[p['operator']]
            unit = p.get('unit') or ''
            val = '%g' % p['value']
            text_en = '%s: %s %s %s?' % (name, en, val, unit)
            if text_en.lower() in seen:
                continue
            seen.add(text_en.lower())
            qs.append({'id': 'q%d' % (len(qs) + 1), 'type': 'threshold', 'list_code': c['list_code'], 'code': c['code'],
                       'item_code': owner.code, 'text_en': text_en,
                       'text_ar': '%s: %s %s %s؟' % (p.get('parameter_ar') or name, ar, val, unit),
                       'operator': p['operator'], 'value': p['value'], 'unit': unit,
                       'base_value': p.get('base_value'), 'base_unit': p.get('base_unit'), 'raw': p.get('raw'),
                       'param_words': sorted({t for t, _ in T.tokens(p.get('parameter') or '')})})
            taken += 1
        if taken == 0 and len(qs) < limit:
            txt = (d.text_en or d.title_en or '')[:220]
            if ('d:' + txt.lower()) not in seen:
                seen.add('d:' + txt.lower())
                qs.append({'id': 'q%d' % (len(qs) + 1), 'type': 'describes', 'list_code': c['list_code'],
                           'code': c['code'], 'item_code': d.code,
                           'text_en': 'Does this description fit the product: "%s"?' % txt,
                           'text_ar': 'هل ينطبق هذا الوصف على المنتج: «%s»؟' % ((d.text_ar or d.title_ar or txt)[:220])})
        if len(qs) >= limit:
            break
    return qs


def prefill(questions, line):
    """Answers taken from values written in the description (e.g. '6 GHz bandwidth'), only when the question's
    parameter words appear in the description too. Marked 'auto' so the user confirms them."""
    text = ' '.join(str(line.get(k) or '') for k in ('description', 'model'))
    qty = T.quantities(text)
    if not qty:
        return {}
    words = {t for t, _ in T.tokens(text)}
    out = {}
    for q in questions:
        if q.get('type') != 'threshold' or not (set(q.get('param_words') or []) & words):
            continue
        for v, base, raw in qty:
            m = re.match(r'([\d.,]+)\s*(.+)$', raw.strip())
            if base == q.get('base_unit') and m:
                out[q['id']] = {'value': m.group(1), 'unit': m.group(2), 'auto': True}
                break
    return out


def evaluate(candidates, hard, questions, answers):
    """answers: {question_id: 'yes' | 'no' | 'unknown' | {'value': 12, 'unit': 'GHz'}} -> (suggested, per_candidate)."""
    answers = answers or {}
    state = {(c['list_code'], c['code']): 'open' for c in candidates}
    asked = {}
    for q in questions:
        k = (q['list_code'], q['code'])
        a = answers.get(q['id'])
        res = None
        if isinstance(a, dict) and a.get('value') not in (None, ''):
            try:
                v, base = T.to_base(float(str(a['value']).replace(',', '.')), a.get('unit') or q.get('unit'))
            except ValueError:
                v, base = None, None
            if base and base == q.get('base_unit'):
                res = 'yes' if T.compare(v, q['operator'], q['base_value']) else 'no'
        elif a in ('yes', 'no', 'unknown'):
            res = a
        asked.setdefault(k, []).append(res)
    for k, rs in asked.items():
        if k not in state:
            continue
        if 'yes' in rs:
            state[k] = 'controlled'
        elif rs and all(r == 'no' for r in rs):
            state[k] = 'cleared'
    if hard or any(s == 'controlled' for s in state.values()):
        suggested = 'hold'
    elif not candidates or all(s == 'cleared' for s in state.values()):
        suggested = 'clear'
    else:
        suggested = 'review'
    return suggested, state


def screen_line(index, line, answers=None):
    """Full screening of one line -> dict ready to store (candidates, hard flags, questions, suggestion)."""
    candidates, hard = find_candidates(index, line)
    qs = questions_for(index, candidates, line)
    if answers is None:
        answers = prefill(qs, line)
    suggested, state = evaluate(candidates, hard, qs, answers)
    for c in candidates:
        c['state'] = state.get((c['list_code'], c['code']), 'open')
    return {'candidates': candidates, 'hard': hard, 'questions': qs, 'answers': answers or {},
            'suggested': suggested, 'key': line_key(line)}


def batch_suggestion(result):
    """No questions in a batch: hold on a hard flag, review when any candidate remains, else clear."""
    if result['hard']:
        return 'hold'
    return 'review' if result['candidates'] else 'clear'
