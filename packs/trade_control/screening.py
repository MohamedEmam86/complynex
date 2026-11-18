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
# text candidates are the search ranking: entries within TEXT_FLOOR of the best score that contain at least
# MIN_TEXT_COVERAGE of the description's concepts (idf-weighted), at most MAX_TEXT_CANDIDATES
MIN_TEXT_COVERAGE = 0.35
HS_UNMAPPED_COVERAGE = 0.7
TEXT_FLOOR = 0.3
MAX_TEXT_CANDIDATES = 5
MAX_HS_ONLY = 3              # entries found only through a broad tariff heading
MAX_MATCH_CHARS = 400        # description characters used for matching (a 2,000-character cell is cut)

HARD_LABELS = {
    'cwc': ('Listed toxic chemical or precursor', 'مادة كيميائية سامة أو سليفة مدرجة'),
    'precursor': ('Chemical-weapons precursor', 'سلائف أسلحة كيميائية'),
    'priority': ('High-priority item (diversion risk)', 'صنف عالي الأولوية (خطر تحويل الاستخدام)'),
    'code': ('Control code given on the document', 'كود الرقابة مذكور في المستند'),
    'lists_unavailable': ('Control lists not loaded', 'قوائم الرقابة غير محمّلة'),
}
HOLD_FLAGS = ('cwc', 'precursor', 'code')     # 'priority' is a risk indicator: review, not hold
OP_TEXT = {'>': ('more than', 'أكثر من'), '>=': ('at least', 'لا يقل عن'), '<': ('less than', 'أقل من'),
           '<=': ('at most', 'لا يزيد عن')}


def line_key(line, tenant_id=None):
    """Item-master key of a product: its normalised description AND model AND tariff code AND CAS number (never
    the model alone - two different products can share a model number), within one tenant."""
    model = re.sub(r'[^a-z0-9]', '', (line.get('model') or '').lower())
    desc = ' '.join(sorted({t for t, _ in T.tokens(line.get('description') or '')}))
    if not (desc or model):
        return None
    hs = T.normalize_hs(line.get('hs_code'))[0] or ''
    cas = ','.join(sorted(T.find_cas(line.get('cas') or '')))
    raw = '|'.join(['t%s' % (tenant_id if tenant_id is not None else ''), desc, model, hs, cas])
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


def _w(en, ar):
    return [en, ar]


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
                add(index.docs[j], how, 0.95, _w('Listed chemical: %s (CAS %s)' % (d.title_en, d.code),
                                                 'مادة كيميائية مدرجة: %s (CAS %s)' % (d.title_en, d.code)))

    # 1. a control code written on the invoice / description
    for word in re.findall(r'\b\d[A-Ea-e]\d{3}(?:\.?[a-z0-9]{1,3})*\b', ' '.join(
            str(line.get(k) or '') for k in ('description', 'model', 'control_code'))):
        code = T.control_code(word)
        for i in index.by_code.get(code.lower(), ()) if code else ():
            add(index.docs[i], 'code', 1.0, _w('Control code %s written on the document' % code,
                                               'كود الرقابة %s مكتوب في المستند' % code))
            hard.append({'flag': 'code', 'code': index.docs[i].code, 'list_code': index.docs[i].list_code})
    # 2. HS / tariff code: the longest published prefix (candidates ranked after the text search below)
    hs, _warn = T.normalize_hs(line.get('hs_code'))
    hs_docs = []
    if hs:
        for k in range(len(hs), 3, -1):
            if k % 2 == 0 and hs[:k] in index.by_hs:
                for i in index.by_hs[hs[:k]]:
                    d = index.docs[i]
                    if d.kind == 'priority':
                        hard.append({'flag': 'priority', 'code': d.code, 'tier': d.extra.get('tier'),
                                     'list_code': d.list_code})
                    else:
                        hs_docs.append((d, k))
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
                add(d, 'cas', 0.95, None if in_register else _w('CAS %s is listed in this entry' % cas,
                                                                'رقم CAS %s مدرج في هذا البند' % cas))
    # 4. text: description and model, ranked by the same search as the search page (top results with a
    #    relative score floor), so the screening never drops what the search finds first
    q = ' '.join(x for x in (line.get('description'), line.get('model')) if x)[:MAX_MATCH_CHARS]
    text_score = {}
    if q.strip():
        q_tokens = {t for t, _ in T.tokens(q)}
        res = index.search(q, limit=30)
        items = [r for r in res['results'] if r['doc'].kind == 'item']
        top = items[0]['score'] if items else 0
        chem_seen = 0
        for n, r in enumerate(res['results']):
            d = r['doc']
            if d.list_code == 'chemicals':
                # a chemical named in the description, also through a synonym or a translation
                # ("hydrofluoric acid", «حمض الهيدروفلوريك» -> hydrogen fluoride)
                if not cas_list and (_names_in(d, q_tokens) or (chem_seen == 0 and n < 6 and _names_in(d, set(r['terms'])))):
                    chemical_hit(d, 'name')
                chem_seen += 1
                continue
            if d.kind != 'item':
                continue
            text_score[(d.code or '').lower()] = r['score'] / (top or 1)
        taken = 0
        # the tariff heading given correlates with no control entry: a text-only candidate must then match the
        # description closely (office chairs, printer paper ...)
        min_cov = HS_UNMAPPED_COVERAGE if (hs and not hs_docs) else MIN_TEXT_COVERAGE
        for r in items:
            d, cov = r['doc'], r.get('coverage', 0)
            rel = r['score'] / (top or 1)
            if rel < TEXT_FLOOR or cov < min_cov or taken >= MAX_TEXT_CANDIDATES:
                continue
            taken += 1
            words = ', '.join(sorted({index.surface_of.get(t, t) for t in r['terms']})[:6])
            add(d, 'text', min(0.9, 0.4 + 0.45 * rel * max(cov, 0.5)),
                _w('Description matches: %s' % words, 'الوصف يطابق: %s' % words) if words else None)
    # HS-correlated entries: agreement with the text first, then the most specific mappings, at most a few
    for d, k in hs_docs:
        key = (d.code or '').lower()
        if key in cands:
            add(d, 'hs', min(0.95, cands[key]['strength'] + 0.15),
                _w('Tariff code %s is correlated with this entry' % hs[:k], 'كود التعريفة %s مرتبط بهذا البند' % hs[:k]))
    hs_only = [(d, k) for d, k in hs_docs if (d.code or '').lower() not in cands]
    hs_only.sort(key=lambda x: (-text_score.get((x[0].code or '').lower(), 0), len(x[0].hs), -(x[0].level or 0),
                                x[0].code))
    for d, k in hs_only[:MAX_HS_ONLY]:
        add(d, 'hs', 0.4 if k >= 6 else 0.25,
            _w('Tariff code %s is correlated with this entry' % hs[:k], 'كود التعريفة %s مرتبط بهذا البند' % hs[:k]))
    cands = _drop_ancestors(cands)
    ordered = sorted(cands.values(), key=lambda c: (-c['strength'], -len(c['reasons']), c['code']))
    return ordered[:MAX_CANDIDATES], _dedupe(hard)


def _names_in(d, q_tokens):
    """A listed chemical's full name is written in the description ('Thionyl chloride 99 %, drums')."""
    for name in [d.title_en] + list(d.extra.get('names') or []):
        nt = [t for t, _ in T.tokens(re.sub(r'\([^)]*\)', ' ', name or ''))]   # "(anhydrous)" is a form, not the name
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
        own = [(p, d) for p in d.params if p.get('parameter')]
        pool = own or [(p, ch) for ch in index.family(d)[:60] for p in ch.params if p.get('parameter')]

        def rel(item):
            p, owner = item
            words = {t for t, _ in T.tokens((p.get('parameter') or '') + ' ' + (owner.text_en or '')[:300])}
            return len(words & desc_tokens)
        scored = sorted(((rel(it), n, it) for n, it in enumerate(pool)), key=lambda x: (-x[0], x[1]))
        if not scored or scored[0][0] == 0:
            scored = []                     # no threshold relates to the product: ask about the entry itself
        taken = 0
        for _, _, (p, owner) in scored:
            if taken >= per or len(qs) >= limit:
                break
            if p.get('operator') not in OP_TEXT or p.get('value') is None:
                continue
            name = _clean_param(p.get('parameter'))
            if not name:
                continue                    # never a question without the name of what is measured
            en, ar = OP_TEXT[p['operator']]
            unit = p.get('unit') or ''
            val = '%g' % p['value']
            text_en = '%s: %s %s %s' % (name, en, val, unit)
            text_ar = '%s: %s %s %s' % (p.get('parameter_ar') or name, ar, val, unit)
            if p.get('upper_op') in OP_TEXT and p.get('upper_value') is not None:
                uen, uar = OP_TEXT[p['upper_op']]
                uu = p.get('upper_unit') or unit
                text_en += ' and %s %g %s' % (uen, p['upper_value'], uu)
                text_ar += ' و%s %g %s' % (uar, p['upper_value'], uu)
            text_en, text_ar = re.sub(r'\s+', ' ', text_en).strip() + '?', re.sub(r'\s+', ' ', text_ar).strip() + '؟'
            k = text_en.lower()
            if k in seen:
                continue
            seen.add(k)
            qs.append({'id': 'q%d' % (len(qs) + 1), 'type': 'threshold', 'list_code': c['list_code'], 'code': c['code'],
                       'item_code': owner.code, 'text_en': text_en, 'text_ar': text_ar,
                       'context': (owner.text_en or '')[:240], 'context_ar': (owner.text_ar or '')[:240],
                       'operator': p['operator'], 'value': p['value'], 'unit': unit,
                       'base_value': p.get('base_value'), 'base_unit': p.get('base_unit'), 'raw': p.get('raw'),
                       'upper_op': p.get('upper_op'), 'upper_base': p.get('upper_base'),
                       'param_words': sorted({t for t, _ in T.tokens(p.get('parameter') or '')})})
            taken += 1
        if len(qs) < limit and ('d:' + c['code']) not in seen:
            # every candidate also gets the entry-level question: only "this entry does not describe the
            # product" can rule a candidate out
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


def _threshold_result(q, a):
    """'yes' / 'no' / 'unknown' / None for one threshold question and its answer (a value is compared, a
    range needs both bounds)."""
    if isinstance(a, dict) and a.get('value') not in (None, ''):
        try:
            num = T.number(str(a['value']))
        except ValueError:
            return None
        if q.get('base_unit') == T.UNITLESS:
            v, base = num, T.UNITLESS
        else:
            v, base = T.to_base(num, a.get('unit') or q.get('unit'))
        if not base or base != q.get('base_unit'):
            return None
        ok = T.compare(v, q['operator'], q['base_value'])
        if ok and q.get('upper_op') and q.get('upper_base') is not None:
            ok = T.compare(v, q['upper_op'], q['upper_base'])
        return 'yes' if ok else 'no'
    return a if a in ('yes', 'no', 'unknown') else None


def evaluate(candidates, hard, questions, answers, line=None, ready=True):
    """answers: {question_id: 'yes' | 'no' | 'unknown' | {'value': 12, 'unit': 'GHz'}} -> (suggested, per_candidate).

    Per candidate:
      controlled   a threshold is met, or the user says the entry describes the product
      cleared      the user says the entry does NOT describe the product (the only way to rule it out)
      below        the user's answers are below the asked thresholds: "below threshold - declared by the
                   user"; the parsed thresholds cover only part of an entry, so this stays REVIEW
      open         not answered
    Line:
      hold    a listed chemical / precursor, a control code on the document, or a controlled candidate
      clear   lists loaded, no flag, and either every candidate ruled out, or no candidate although an HS code
              or a CAS number was given (clear by absence)
      review  anything else, including a description-only line with no candidate (insufficient data) and
              a screening made while a list is not loaded"""
    answers = answers or {}
    state = {(c['list_code'], c['code']): 'open' for c in candidates}
    thr, desc = {}, {}
    for q in questions:
        k = (q['list_code'], q['code'])
        if q.get('type') == 'threshold':
            thr.setdefault(k, []).append(_threshold_result(q, answers.get(q['id'])))
        else:
            desc[k] = answers.get(q['id']) if answers.get(q['id']) in ('yes', 'no', 'unknown') else None
    for k in state:
        rs, d = thr.get(k, []), desc.get(k)
        if 'yes' in rs or (d == 'yes' and not rs):
            state[k] = 'controlled'
        elif d == 'no':
            state[k] = 'cleared'
        elif rs and all(r == 'no' for r in rs):
            state[k] = 'below'
    hold = any(h.get('flag') in HOLD_FLAGS for h in hard or [])
    soft = any(h.get('flag') not in HOLD_FLAGS for h in hard or [])
    identified = bool(line and (T.normalize_hs((line or {}).get('hs_code'))[0] or T.find_cas((line or {}).get('cas') or '')))
    if hold or any(s == 'controlled' for s in state.values()):
        suggested = 'hold'
    elif not ready or soft:
        suggested = 'review'
    elif candidates and all(s == 'cleared' for s in state.values()):
        suggested = 'clear'
    elif not candidates and (identified or line is None):
        suggested = 'clear'
    else:
        suggested = 'review'
    return suggested, state


def explain(candidates, hard, suggested, line=None, ready=True):
    """Plain-language reasons for the suggested outcome (English, Arabic) - shown on the page and the report."""
    out = []
    if not ready:
        out.append(('Control lists are not loaded on this installation: no product can be cleared.',
                    'قوائم الرقابة غير محمّلة في هذا النظام: لا يمكن اعتبار أي منتج خاليًا من المؤشرات.'))
    for h in hard or []:
        en, ar = HARD_LABELS.get(h.get('flag'), (h.get('flag'), h.get('flag')))
        out.append(('%s: %s' % (en, h.get('name') or h.get('code')), '%s: %s' % (ar, h.get('name') or h.get('code'))))
    for c in candidates:
        st = c.get('state') or 'open'
        head = '%s — %s' % (c['code'], (c.get('title_en') or '')[:120])
        head_ar = '%s — %s' % (c['code'], (c.get('title_ar') or c.get('title_en') or '')[:120])
        whys = [w if isinstance(w, (list, tuple)) else [w, w] for w in (c.get('why') or [])]
        if st == 'controlled':
            out.append(('%s: the answers meet the entry' % head, '%s: الإجابات تستوفي البند' % head_ar))
        elif st == 'cleared':
            out.append(('%s: the user declared that the entry does not describe the product' % head,
                        '%s: قرر المستخدم أن البند لا يصف المنتج' % head_ar))
        elif st == 'below':
            out.append(('%s: below the asked thresholds - declared by the user; the entry is not ruled out' % head,
                        '%s: أقل من الحدود المسؤول عنها - بإقرار المستخدم؛ ولم يُستبعد البند' % head_ar))
        else:
            out.append(('%s: possible match (%s) - open' % (head, '; '.join(w[0] for w in whys) or ', '.join(c['reasons'])),
                        '%s: تطابق محتمل (%s) - مفتوح' % (head_ar, '؛ '.join(w[1] for w in whys) or '، '.join(c['reasons']))))
    if not candidates and not hard and ready:
        if suggested == 'clear':
            out.append(('No control entry matched the tariff code / CAS number and the description given.',
                        'لم يطابق أي بند رقابة كود التعريفة / رقم CAS والوصف المدخلين.'))
        else:
            out.append(('Insufficient data: no entry matched the description alone. Add the HS code, the CAS number '
                        'or the technical specifications.',
                        'بيانات غير كافية: لم يطابق أي بند الوصف وحده. أضف كود HS أو رقم CAS أو المواصفات الفنية.'))
    return out


def screen_line(index, line, answers=None):
    """Full screening of one line -> dict ready to store (candidates, flags, questions, suggestion)."""
    ready = getattr(index, 'ready', True)
    candidates, hard = find_candidates(index, line)
    if not ready:
        hard = hard + [{'flag': 'lists_unavailable', 'code': ''}]
    qs = questions_for(index, candidates, line)
    if answers is None:
        answers = prefill(qs, line)
    suggested, state = evaluate(candidates, hard, qs, answers, line, ready)
    for c in candidates:
        c['state'] = state.get((c['list_code'], c['code']), 'open')
    return {'candidates': candidates, 'hard': hard, 'questions': qs, 'answers': answers or {},
            'suggested': suggested, 'key': line_key(line), 'ready': ready}


def batch_suggestion(result):
    """The batch keeps the suggestion of the single screening (prefilled values included)."""
    return result['suggested']
