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

Stages: control code written on the document -> HS / tariff mapping -> CAS number (with or without dashes)
and chemical name -> text search on the description and model -> 2 to 5 targeted questions on the
technical thresholds. An HS code alone never clears or confirms an item: it only proposes candidates.

The result is a SUGGESTION (clear / review / hold) that supports the user's own assessment; it is not a
legal classification or an export / import authorisation. The user records the final decision with a
reason and a comment.
"""
import hashlib
import re

from . import text as T

MAX_CANDIDATES = 6
MAX_QUESTIONS = 5
OUTCOMES = ('clear', 'review', 'hold')
MIN_TEXT_COVERAGE = 0.6      # share of the description's concepts an entry must contain to be a text candidate

HARD_LABELS = {
    'cwc': ('Listed toxic chemical or precursor', 'مادة كيميائية سامة أو سليفة مدرجة'),
    'precursor': ('Chemical-weapons precursor', 'سلائف أسلحة كيميائية'),
    'priority': ('High-priority item (diversion risk)', 'صنف عالي الأولوية (خطر تحويل الاستخدام)'),
    'code': ('Control code given on the document', 'كود الرقابة مذكور في المستند'),
}
HOLD_FLAGS = ('cwc', 'precursor', 'code')     # 'priority' is a risk indicator: review, not hold
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
            'title_ar': d.title_ar or '', 'risk': d.risk, 'reasons': [reason], 'strength': round(strength, 3),
            'category': d.category, 'group': d.group, 'lists': [d.list_code], 'level': d.level or 0,
            'text_en': (d.text_en or '')[:400] if d.level else (d.title_en or '')[:400], 'why': []}


def _drop_ancestors(cands):
    """5A002 and 5A002.a.1 both found: keep the more precise entry and give it the parent's reasons."""
    codes = {c['code'].lower(): c for c in cands.values()}
    out = {}
    for k, c in cands.items():
        child = next((o for ck, o in codes.items() if ck != k and ck.startswith(k + '.')), None)
        if child is not None:
            for r in c['reasons']:
                if r not in child['reasons']:
                    child['reasons'].append(r)
            child['strength'] = max(child['strength'], c['strength'])
            for lc in c['lists']:
                if lc not in child['lists']:
                    child['lists'].append(lc)
            continue
        out[k] = c
    return out


def find_candidates(index, line):
    """(candidates, flags). Candidates are control entries; flags are hits that call for a hold (or, for a
    high-priority tariff heading, a review)."""
    cands, hard = {}, []

    def add(d, reason, strength, why=None):
        key = (d.code or '').lower()          # one candidate per control code, whichever list publishes it
        if key in cands:
            c = cands[key]
            if reason not in c['reasons']:
                c['reasons'].append(reason)
            c['strength'] = max(c['strength'], round(strength, 3))
            if d.list_code not in c['lists']:
                c['lists'].append(d.list_code)
        else:
            c = cands[key] = _cand(d, reason, strength)
        if why and why not in c['why']:
            c['why'].append(why)

    def chemical_hit(d, how):
        if d.extra.get('cwc_schedule'):
            hard.append({'flag': 'cwc', 'code': d.code, 'schedule': d.extra['cwc_schedule'], 'list_code': d.list_code,
                         'name': d.title_en, 'how': how})
        if d.extra.get('ag_precursor'):
            hard.append({'flag': 'precursor', 'code': d.code, 'list_code': d.list_code, 'name': d.title_en,
                         'how': how})
        for ref in d.extra.get('item_codes') or []:
            for j in index.by_code.get(ref.lower(), ()):
                add(index.docs[j], how, 0.95, 'Listed chemical: %s (CAS %s)' % (d.title_en, d.code))

    # 1. a control code written on the invoice / description
    for word in re.findall(r'\b\d[A-Ea-e]\d{3}(?:\.[a-z0-9]{1,3})*\b', ' '.join(
            str(line.get(k) or '') for k in ('description', 'model', 'control_code'))):
        code = T.control_code(word)
        for i in index.by_code.get(code.lower(), ()) if code else ():
            add(index.docs[i], 'code', 1.0, 'Control code %s written on the document' % code)
            hard.append({'flag': 'code', 'code': index.docs[i].code, 'list_code': index.docs[i].list_code})
    # 2. HS / tariff code: the longest published prefix
    hs = T.hs_digits(line.get('hs_code') or '')
    if hs:
        for k in range(len(hs), 3, -1):
            if k % 2 == 0 and hs[:k] in index.by_hs:
                for i in index.by_hs[hs[:k]]:
                    d = index.docs[i]
                    if d.kind == 'priority':
                        hard.append({'flag': 'priority', 'code': d.code, 'tier': d.extra.get('tier'),
                                     'list_code': d.list_code})
                    else:
                        add(d, 'hs', 0.4 if k >= 6 else 0.25, 'Tariff code %s is correlated with this entry' % hs[:k])
                break
    # 3. CAS number (also written without dashes, or in the description)
    cas_list = index._cas_in(' '.join(str(line.get(k) or '') for k in ('cas', 'description')))
    for cas in cas_list:
        docs = sorted((index.docs[i] for i in index.by_cas.get(cas, ())), key=lambda x: x.list_code != 'chemicals')
        in_register = False
        for d in docs:
            if d.list_code == 'chemicals':
                chemical_hit(d, 'cas')
                in_register = True
            elif d.kind != 'chemical':
                add(d, 'cas', 0.95, None if in_register else 'CAS %s is listed in this entry' % cas)
    # 4. text: description and model
    q = ' '.join(x for x in (line.get('description'), line.get('model')) if x)
    if q.strip():
        q_tokens = {t for t, _ in T.tokens(q)}
        res = index.search(q, limit=25)
        top = res['results'][0]['score'] if res['results'] else 0
        for r in res['results']:
            d = r['doc']
            if d.list_code == 'chemicals':
                if not cas_list and _names_in(d, q_tokens):   # chemical named in the description
                    chemical_hit(d, 'name')
                continue
            cov = r.get('coverage', 0)
            agrees = (d.code or '').lower() in cands and 'hs' in cands[(d.code or '').lower()]['reasons']
            if (cov < MIN_TEXT_COVERAGE and not (agrees and cov >= 0.3)) or r['score'] < 0.35 * top:
                continue
            if d.kind in ('chemical', 'priority'):
                continue
            words = ', '.join(sorted({index.surface_of.get(t, t) for t in r['terms']})[:6])
            strength = 0.35 + 0.5 * cov * min(1.0, r['score'] / (top or 1)) + (0.15 if agrees else 0)
            add(d, 'text', min(0.9, strength), 'Description matches: %s' % words if words else None)
    cands = _drop_ancestors(cands)
    ordered = sorted(cands.values(), key=lambda c: (-c['strength'], -len(c['reasons']), c['code']))
    return ordered[:MAX_CANDIDATES], _dedupe(hard)


def _names_in(d, q_tokens):
    """A listed chemical's full name is written in the description ('Thionyl chloride 99 %, drums')."""
    for name in [d.title_en] + list(d.extra.get('names') or []):
        nt = [t for t, _ in T.tokens(name or '')]
        if nt and set(nt) <= q_tokens and (len(nt) >= 2 or len(nt[0]) >= 8):
            return True
    return False


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
    return name[:1].upper() + name[1:] if name else ''


def _describes(c, d):
    txt = (d.title_en if not d.level and d.title_en else (d.text_en or d.title_en or ''))[:220]
    txt_ar = (d.title_ar if not d.level and d.title_ar else (d.text_ar or d.title_ar or ''))[:220] or txt
    return {'type': 'describes', 'list_code': c['list_code'], 'code': c['code'], 'item_code': d.code,
            'text_en': 'Does this entry describe the product: "%s"?' % txt,
            'text_ar': 'هل يصف هذا البند المنتج: «%s»؟' % txt_ar, 'context': ''}


def questions_for(index, candidates, line=None, limit=MAX_QUESTIONS):
    """Targeted yes / no / value questions, at most `limit`, spread across the candidates (strongest first).
    Thresholds whose parameter words appear in the product description are asked first; an entry whose
    thresholds have nothing to do with the description gets one question on the entry itself."""
    desc_tokens = {t for t, _ in T.tokens(' '.join(str((line or {}).get(k) or '') for k in ('description', 'model')))}
    qs, seen = [], set()
    per = max(1, limit // max(1, len(candidates))) if candidates else 0
    for c in candidates:
        if len(qs) >= limit:
            break
        d = index.get(c['list_code'], c['code'])
        if d is None:
            continue
        if any(r in ('cas', 'name') for r in c['reasons']):
            ck = 'cas:' + ','.join(sorted(d.cas)) if d.cas else 'd:' + c['code']
            if ck in seen:
                continue                    # the same chemical listed under another code: asked once
            seen.add(ck)
            q = {'type': 'describes', 'list_code': c['list_code'], 'code': c['code'], 'item_code': d.code,
                 'text_en': 'Is the product this chemical, or a mixture containing it at or above the concentration '
                            'stated in the entry: "%s"?' % (d.text_en or d.title_en or '')[:160],
                 'text_ar': 'هل المنتج هو هذه المادة الكيميائية أو خليط يحتويها بالتركيز المذكور في البند أو أعلى: «%s»؟'
                            % (d.text_ar or d.text_en or d.title_en or '')[:160], 'context': ''}
            if ('d:' + c['code']) not in seen:
                seen.add('d:' + c['code'])
                q['id'] = 'q%d' % (len(qs) + 1)
                qs.append(q)
            continue
        own = [(p, d) for p in d.params]
        pool = own or [(p, ch) for ch in index.family(d)[:60] for p in ch.params]

        def rel(item):
            p, owner = item
            words = {t for t, _ in T.tokens((p.get('parameter') or '') + ' ' + (owner.text_en or '')[:300])}
            return len(words & desc_tokens)
        scored = sorted(((rel(it), n, it) for n, it in enumerate(pool)), key=lambda x: (-x[0], x[1]))
        if not own and (not scored or scored[0][0] == 0):
            scored = []                     # nothing in the family relates to the product: ask about the entry
        taken = 0
        for _, _, (p, owner) in scored:
            if taken >= per or len(qs) >= limit:
                break
            if p.get('operator') not in OP_TEXT or p.get('value') is None:
                continue
            name = _clean_param(p.get('parameter'))
            en, ar = OP_TEXT[p['operator']]
            unit = p.get('unit') or ''
            val = '%g' % p['value']
            if name:
                text_en = '%s: %s %s %s?' % (name, en, val, unit)
                text_ar = '%s: %s %s %s؟' % (p.get('parameter_ar') or name, ar, val, unit)
            else:
                text_en = 'Does the product reach this value: %s %s %s?' % (en, val, unit)
                text_ar = 'هل يبلغ المنتج هذه القيمة: %s %s %s؟' % (ar, val, unit)
            k = text_en.lower()
            if k in seen:
                continue
            seen.add(k)
            qs.append({'id': 'q%d' % (len(qs) + 1), 'type': 'threshold', 'list_code': c['list_code'], 'code': c['code'],
                       'item_code': owner.code, 'text_en': text_en.replace('  ', ' '), 'text_ar': text_ar.replace('  ', ' '),
                       'context': (owner.text_en or '')[:240], 'context_ar': (owner.text_ar or '')[:240],
                       'operator': p['operator'], 'value': p['value'], 'unit': unit,
                       'base_value': p.get('base_value'), 'base_unit': p.get('base_unit'), 'raw': p.get('raw'),
                       'param_words': sorted({t for t, _ in T.tokens(p.get('parameter') or '')})})
            taken += 1
        if taken == 0 and len(qs) < limit and ('d:' + c['code']) not in seen:
            seen.add('d:' + c['code'])
            q = _describes(c, d)
            q['id'] = 'q%d' % (len(qs) + 1)
            qs.append(q)
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
        pw = set(q.get('param_words') or [])
        if q.get('type') != 'threshold' or not pw or not pw <= words:
            continue                        # every word of the parameter must be in the description
        for v, base, raw in qty:
            m = re.match(r'([\d.,]+)\s*(.+)$', raw.strip())
            if base == q.get('base_unit') and m:
                out[q['id']] = {'value': m.group(1), 'unit': m.group(2), 'auto': True}
                break
    return out


def evaluate(candidates, hard, questions, answers):
    """answers: {question_id: 'yes' | 'no' | 'unknown' | {'value': 12, 'unit': 'GHz'}} -> (suggested, per_candidate).

    hold    a listed chemical / precursor, a control code on the document, or a 'yes' / a value that meets a
            threshold of a candidate entry
    clear   no candidate and no flag, or every candidate answered below its thresholds / not describing it
    review  anything else (open questions, a high-priority tariff heading)"""
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
    hold = any(h.get('flag') in HOLD_FLAGS for h in hard or [])
    soft = any(h.get('flag') not in HOLD_FLAGS for h in hard or [])
    if hold or any(s == 'controlled' for s in state.values()):
        suggested = 'hold'
    elif not soft and (not candidates or all(s == 'cleared' for s in state.values())):
        suggested = 'clear'
    else:
        suggested = 'review'
    return suggested, state


def explain(candidates, hard, suggested):
    """Plain-language reasons for the suggested outcome (English, Arabic) - shown on the page and the report."""
    out = []
    for h in hard or []:
        en, ar = HARD_LABELS.get(h.get('flag'), (h.get('flag'), h.get('flag')))
        out.append(('%s: %s' % (en, h.get('name') or h.get('code')), '%s: %s' % (ar, h.get('name') or h.get('code'))))
    for c in candidates:
        st = c.get('state') or 'open'
        head = '%s — %s' % (c['code'], (c.get('title_en') or '')[:120])
        if st == 'controlled':
            out.append(('%s: the answers meet a control threshold' % head, '%s: الإجابات تستوفي حدًّا للرقابة' % head))
        elif st == 'cleared':
            out.append(('%s: the answers are below the control thresholds' % head,
                        '%s: الإجابات أقل من حدود الرقابة' % head))
        else:
            why = '; '.join(c.get('why') or []) or ', '.join(c.get('reasons') or [])
            out.append(('%s: possible match (%s) - open' % (head, why), '%s: تطابق محتمل (%s) - مفتوح' % (head, why)))
    if not out and suggested == 'clear':
        out.append(('No control entry matched the product data given.',
                    'لم يطابق أي بند رقابة بيانات المنتج المدخلة.'))
    return out


def screen_line(index, line, answers=None):
    """Full screening of one line -> dict ready to store (candidates, flags, questions, suggestion)."""
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
    """No questions in a batch: hold on a hold flag, review when a candidate or a priority flag remains, else
    clear."""
    hard = result['hard'] or []
    if any(h.get('flag') in HOLD_FLAGS for h in hard):
        return 'hold'
    return 'review' if (result['candidates'] or hard) else 'clear'
