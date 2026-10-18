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
AI tasks. Each task has a deterministic rules implementation (always
available) and a local-model implementation that must return strict JSON;
the model reply is schema-validated, repaired once if invalid, and the task
falls back to the rules result on any failure. The model may only choose
among catalog entries passed to it (enum-validated) — it can never invent
an intent, a playbook or an obligation.

Every function returns (result, meta) with meta = provider, model,
prompt_version, status (ok | repaired | fallback), latency_ms, prompt_text, error.
"""

import json
import re
from datetime import date, timedelta

from . import schema as S
from . import text as T
from .providers import ProviderError, RulesOnly, cosine

PROMPT_VERSIONS = {'intake': 'intake-v1', 'playbook': 'playbook-v1', 'nba': 'nba-v1', 'draft': 'draft-v1'}
RULES_THRESHOLD = 0.9          # below this rules score the item is "unclassified" (manual triage)

SYSTEM = ("You are the compliance assistant inside a compliance-management system of a regulated financial "
          "institution. You only classify, extract and phrase. You never decide, never invent obligations, "
          "laws, deadlines or names that are not in the input, and you reply with ONE JSON object only.")


# --------------------------------------------------------------------------
# scoring helpers (rules)
# --------------------------------------------------------------------------

def _entry_vectors(entry):
    texts = [entry.get('name_en') or '', entry.get('name_ar') or '', entry.get('description') or ''] + list(entry.get('examples') or [])
    return [T.ngrams(t) for t in texts if t]


def score_entries(text, entries, embedder=None):
    """Rank catalog entries for a text. Returns [(entry, score, why)] best first."""
    tv = T.ngrams(text)
    emb_text = emb_entries = None
    if embedder is not None:
        try:
            vecs = embedder.embed([text] + [' '.join([e.get('name_en') or '', e.get('description') or ''] + list(e.get('examples') or [])[:3])
                                            for e in entries])
            emb_text, emb_entries = vecs[0], vecs[1:]
        except (ProviderError, Exception):
            emb_text = None
    out = []
    for i, e in enumerate(entries):
        hits = T.keyword_hits(text, e.get('keywords'))
        kw = sum(1.5 if ' ' in T.normalise(h) else 1.0 for h in hits)
        sim = max([T.cosine(tv, v) for v in _entry_vectors(e)] or [0.0])
        es = cosine(emb_text, emb_entries[i]) if emb_text is not None else 0.0
        score = kw + 3.0 * sim + (4.0 * max(0.0, es - 0.2) if emb_text is not None else 0.0)
        out.append((e, round(score, 3), {'keywords': hits[:8], 'similarity': round(sim, 3),
                                          'embedding': round(es, 3) if emb_text is not None else None}))
    return sorted(out, key=lambda x: -x[1])


def _confidence(ranked):
    if not ranked or ranked[0][1] <= 0:
        return 0.0
    top = ranked[0][1]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return round(min(0.95, (top / (top + second + 0.5)) * min(1.0, top / 3.0) + 0.05), 2)


# --------------------------------------------------------------------------
# field extraction (rules)
# --------------------------------------------------------------------------

_NAME_LINE = re.compile(r'^\s*(?:\d+[.)-]\s*|[-•*]\s*)?([A-Za-z؀-ۿ][A-Za-z؀-ۿ\'.\- ]{4,60})\s*(?:[,،\-–(]|$)')
_PERSON_AFTER = re.compile(r'(?:my name is|name is|name\s*:|customer\s*:|client\s*:|\bmr\.?|\bmrs\.?|\bms\.?|السيد|السيدة|المدعو|المدعوة|العميل|العميلة|اسم العميل|الاسم)\s*[:.]?\s*'
                           r'([A-Za-z؀-ۿ]+(?:\s+[A-Za-z؀-ۿ]+){1,3})', re.I)
_NUMBER_OF = re.compile(r'(?:no\.?|number|رقم)\s*[:#]?\s*(\d{1,5})\s*(?:of|for|لسنة|لعام)\s*(20\d\d)', re.I)
_DATE_HINTS = {
    'effective_date': ('effective', 'from', 'اعتبارا', 'يعمل به', 'يسري', 'سريان'),
    'deadline': ('within', 'by', 'no later', 'deadline', 'خلال', 'موعد', 'قبل', 'في موعد'),
    'issue_date': ('dated', 'issued', 'بتاريخ', 'صادر'),
}
_STOPNAMES = set(T.normalise('''please freeze the following persons entities accounts funds immediately dear sirs regards
names list below attached kindly confirm action taken اسماء الاشخاص التاليه المدرجين ادناه برجاء نرجو تجميد الحسابات الاموال فورا
السادة تحية طيبة وبعد مع خالص التحية مرفق''').split())


def _names(text):
    out = []
    for line in (text or '').splitlines():
        m = _NAME_LINE.match(line)
        if not m:
            continue
        cand = m.group(1).strip()
        words = cand.split()
        nw = [T.normalise(w) for w in words]
        if 2 <= len(words) <= 5 and not any(w in _STOPNAMES for w in nw) and not any(ch.isdigit() for ch in cand):
            out.append(cand)
    return out[:20]


def _date_near(text, hints, window=60):
    """The date that follows one of the cue words most closely (within `window` characters)."""
    t = (text or '').translate(T._DIGITS).lower()
    best = None
    for d, pos in T.dates_pos(text):
        for h in hints:
            for m in re.finditer(re.escape(h.lower()), t):
                gap = pos - m.end()
                if 0 <= gap <= window and (best is None or gap < best[0]):
                    best = (gap, d)
    return best[1] if best else None


def extract_fields(text, field_defs, today=None):
    """Deterministic extraction for the field definitions of an intent / playbook."""
    ids = T.identifiers(text)
    ds = T.dates(text)
    amts = T.amounts(text)
    out = {}
    for f in field_defs or []:
        k, typ = f['key'], f.get('type', 'text')
        v = None
        if typ == 'date':
            v = _date_near(text, _DATE_HINTS.get(k, ())) if k in _DATE_HINTS else None
            if v is None and k == 'deadline':
                v = T.relative_deadline(text, today)
            if v is None and ds and k not in _DATE_HINTS:
                v = ds[0]
            v = v.isoformat() if v else None
        elif typ == 'amount':
            v = f'{amts[0][0]:,.0f} {amts[0][1]}' if amts else None
        elif typ == 'list' and k in ('subject_names',):
            v = ', '.join(_names(text)) or None
        elif typ in ('list', 'id') and k in ('national_id',):
            v = ', '.join(ids['national_id']) or None
        elif typ == 'email':
            v = ids['email'][0] if ids['email'] else None
        elif typ == 'phone':
            v = ids['phone'][0] if ids['phone'] else None
        elif typ == 'person':
            m = _PERSON_AFTER.search(text or '')
            v = m.group(1).strip() if m else (_names(text) or [None])[0]
        elif k in ('order_reference', 'circular_number', 'reference', 'reference_no'):
            m = _NUMBER_OF.search((text or '').translate(T._DIGITS))
            v = f'{m.group(1)}/{m.group(2)}' if m else (ids['reference'][0] if ids['reference'] else None)
        elif k in ('title', 'complaint_subject', 'topic', 'subject', 'summary'):
            first = next((ln.strip() for ln in (text or '').splitlines() if len(ln.strip()) > 8), '')
            v = T.excerpt(re.sub(r'^(subject|re|الموضوع)\s*[:：]\s*', '', first, flags=re.I), 120) or None
        if v:
            out[k] = v
    return out


# --------------------------------------------------------------------------
# model calls with schema validation + repair
# --------------------------------------------------------------------------

def call_model(gen, system, prompt, schema, timeout=None):
    """→ (obj, status 'ok' | 'repaired', latency_ms). Raises ProviderError when even the repair fails."""
    import time
    t0 = time.monotonic()
    reply = gen.generate(system, prompt, timeout)
    try:
        obj = S.extract_json(reply)
        errs = S.errors(obj, schema)
    except ValueError as e:
        obj, errs = None, [str(e)]
    status = 'ok'
    if errs:
        fix = (prompt + '\n\nYour previous reply was invalid: ' + '; '.join(errs[:6]) +
               '\nReply again with ONLY one JSON object that matches this JSON schema:\n' + json.dumps(schema))
        reply = gen.generate(system, fix, timeout)
        try:
            obj = S.extract_json(reply)
            errs = S.errors(obj, schema)
        except ValueError as e:
            errs = [str(e)]
        if errs:
            raise ProviderError('invalid model output after repair: ' + '; '.join(errs[:4]))
        status = 'repaired'
    return obj, status, int((time.monotonic() - t0) * 1000)


def _meta(gen, task, status='ok', latency=0, prompt=None, error=None):
    return {'provider': gen.name, 'model': gen.model, 'prompt_version': PROMPT_VERSIONS[task], 'status': status,
            'latency_ms': latency, 'prompt_text': prompt, 'error': error}


def _catalog_lines(entries, n_examples=1):
    lines = []
    for e in entries:
        ex = ' | '.join((e.get('examples') or [])[:n_examples])
        lines.append(f"- {e['code']}: {e.get('name_en')} / {e.get('name_ar') or ''}. {e.get('description') or ''}"
                     + (f" Example: {ex}" if ex else ''))
    return '\n'.join(lines)


# --------------------------------------------------------------------------
# 1. intake classification + extraction
# --------------------------------------------------------------------------

def classify_rules(text, intents, embedder=None, today=None):
    ranked = score_entries(text, intents, embedder)
    conf = _confidence(ranked)
    top = ranked[0] if ranked else None
    if not top or top[1] < RULES_THRESHOLD:
        return {'intent': None, 'confidence': conf, 'fields': {}, 'summary': T.excerpt(text, 200),
                'alternatives': [{'code': e['code'], 'score': s} for e, s, _ in ranked[:3]], 'why': {}}
    e = top[0]
    return {'intent': e['code'], 'confidence': conf, 'fields': extract_fields(text, e.get('fields'), today),
            'summary': T.excerpt(text, 200), 'why': top[2],
            'alternatives': [{'code': x['code'], 'score': s} for x, s, _ in ranked[1:4]]}


def classify(text, intents, gen=None, embedder=None, today=None):
    """Classify an intake text into one catalog intent and extract its fields."""
    gen = gen or RulesOnly()
    rules = classify_rules(text, intents, embedder, today)
    if not gen.can_generate:
        return rules, _meta(gen, 'intake')
    codes = [e['code'] for e in intents]
    by = {e['code']: e for e in intents}
    sch = {'type': 'object', 'required': ['intent', 'confidence', 'fields', 'summary'],
           'properties': {'intent': {'type': ['string', 'null'], 'enum': codes + [None]},
                          'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                          'fields': {'type': 'object'}, 'summary': {'type': 'string', 'maxLength': 600},
                          'language': {'type': 'string'}}}
    field_lines = '\n'.join(f"  {e['code']}: " + ', '.join(f"{f['key']} ({f.get('type', 'text')})" for f in e.get('fields') or [])
                            for e in intents)
    prompt = (f"Classify the submission into exactly one intent code from the catalog, or null if none fits.\n"
              f"Catalog:\n{_catalog_lines(intents)}\n\nFields to extract per intent (only values present in the text; "
              f"dates as YYYY-MM-DD; lists comma-separated):\n{field_lines}\n\n"
              f"Rules engine hint (may be wrong): {rules['intent']}\n\n"
              f"Submission:\n\"\"\"\n{(text or '')[:6000]}\n\"\"\"\n\n"
              'Reply as JSON: {"intent": "<code or null>", "confidence": 0.0-1.0, "fields": {...}, '
              '"summary": "<one sentence in the language of the submission>", "language": "ar|en"}')
    try:
        obj, status, ms = call_model(gen, SYSTEM, prompt, sch)
    except ProviderError as e:
        return rules, _meta(gen, 'intake', 'fallback', 0, prompt, str(e))
    allowed = {f['key'] for f in (by.get(obj['intent']) or {}).get('fields') or []}
    fields = {k: str(v) for k, v in (obj.get('fields') or {}).items() if k in allowed and v not in (None, '', [])}
    if obj['intent']:
        for k, v in extract_fields(text, by[obj['intent']].get('fields'), today).items():
            fields.setdefault(k, v)            # rules fill what the model left out
    res = {'intent': obj['intent'], 'confidence': round(float(obj['confidence']), 2), 'fields': fields,
           'summary': obj.get('summary') or rules['summary'], 'why': {'rules_hint': rules['intent']},
           'alternatives': rules['alternatives'] if rules['intent'] != obj['intent'] else rules['alternatives'][:2]}
    return res, _meta(gen, 'intake', status, ms, prompt)


# --------------------------------------------------------------------------
# 3. playbook selection
# --------------------------------------------------------------------------

_PLACE = re.compile(r'(?:branch|office|location)\s+(?:in|at)\s+([A-Z][\w-]+(?:\s+[A-Z][\w-]+)?)|(?:فرع|مقر)\s+(?:جديد\s+)?(?:في|ب)\s*([؀-ۿ]+)')


def _playbook_params(text, pb, today=None):
    params = extract_fields(text, pb.get('parameters'), today)
    for p in pb.get('parameters') or []:
        if p['key'] in params:
            continue
        if p['key'] in ('branch_name',):
            m = _PLACE.search(text or '')
            if m:
                params[p['key']] = (m.group(1) or m.group(2)).strip()
        elif p.get('required') and p.get('type', 'text') == 'text':
            params[p['key']] = T.excerpt(text, 80)
    return params


def select_playbooks_rules(text, playbooks, embedder=None, today=None, k=2):
    ranked = score_entries(text, playbooks, embedder)
    conf = _confidence(ranked)
    picks = [(e, s) for e, s, _ in ranked if s >= RULES_THRESHOLD][:k]
    return {'playbooks': [{'code': e['code'], 'confidence': conf if i == 0 else round(conf * s / ranked[0][1], 2),
                           'params': _playbook_params(text, e, today)} for i, (e, s) in enumerate(picks)]}


def select_playbooks(text, playbooks, gen=None, embedder=None, today=None):
    gen = gen or RulesOnly()
    rules = select_playbooks_rules(text, playbooks, embedder, today)
    if not gen.can_generate:
        return rules, _meta(gen, 'playbook')
    codes = [p['code'] for p in playbooks]
    by = {p['code']: p for p in playbooks}
    sch = {'type': 'object', 'required': ['playbooks'],
           'properties': {'playbooks': {'type': 'array', 'maxItems': 3, 'items': {
               'type': 'object', 'required': ['code', 'confidence'],
               'properties': {'code': {'type': 'string', 'enum': codes}, 'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                              'params': {'type': 'object'}}}}}}
    plines = '\n'.join(f"  {p['code']}: " + ', '.join(f"{x['key']} ({x.get('type', 'text')})" for x in p.get('parameters') or [])
                       for p in playbooks)
    prompt = (f"Select the playbook(s) from the catalog that fit the situation (best first, at most 3, empty list if none).\n"
              f"Catalog:\n{_catalog_lines(playbooks)}\n\nParameters per playbook (only values stated in the text):\n{plines}\n\n"
              f"Situation:\n\"\"\"\n{(text or '')[:4000]}\n\"\"\"\n\n"
              'Reply as JSON: {"playbooks": [{"code": "<code>", "confidence": 0.0-1.0, "params": {...}}]}')
    try:
        obj, status, ms = call_model(gen, SYSTEM, prompt, sch)
    except ProviderError as e:
        return rules, _meta(gen, 'playbook', 'fallback', 0, prompt, str(e))
    out = []
    for x in obj['playbooks']:
        allowed = {p['key'] for p in by[x['code']].get('parameters') or []}
        params = {k: str(v) for k, v in (x.get('params') or {}).items() if k in allowed and v not in (None, '')}
        for k, v in _playbook_params(text, by[x['code']], today).items():
            params.setdefault(k, v)
        out.append({'code': x['code'], 'confidence': round(float(x['confidence']), 2), 'params': params})
    return {'playbooks': out}, _meta(gen, 'playbook', status, ms, prompt)


# --------------------------------------------------------------------------
# 2. next-best-action phrasing and drafts
# --------------------------------------------------------------------------

def phrase_rules(gaps, lang='en'):
    k = 'text_ar' if lang == 'ar' else 'text_en'
    if not gaps:
        return {'headline': 'لا يوجد إجراء مطلوب الآن.' if lang == 'ar' else 'Nothing is required right now.', 'steps': []}
    first = gaps[0]
    head = ('الخطوة التالية: ' if lang == 'ar' else 'Next step: ') + first[k]
    return {'headline': head, 'steps': [g[k] for g in gaps]}


def phrase(gaps, lang='en', gen=None, context=None):
    """Phrase deterministic gaps for a user. The model may reword but not add or drop steps."""
    gen = gen or RulesOnly()
    rules = phrase_rules(gaps, lang)
    if not gen.can_generate or not gaps:
        return rules, _meta(gen, 'nba')
    sch = {'type': 'object', 'required': ['headline', 'steps'],
           'properties': {'headline': {'type': 'string', 'maxLength': 300},
                          'steps': {'type': 'array', 'minItems': len(gaps), 'maxItems': len(gaps), 'items': {'type': 'string', 'maxLength': 400}}}}
    language = 'Arabic (Modern Standard, simple)' if lang == 'ar' else 'plain English'
    items = '\n'.join(f"{i + 1}. {g['text_en']}" for i, g in enumerate(gaps))
    prompt = (f"Rewrite these compliance next steps for the person responsible, in {language}. Keep exactly the same "
              f"{len(gaps)} steps in the same order, keep every date, number and reference unchanged, add nothing new.\n"
              f"Context: {json.dumps(context or {}, ensure_ascii=False, default=str)[:1500]}\nSteps:\n{items}\n\n"
              'Reply as JSON: {"headline": "<one short sentence>", "steps": ["...", "..."]}')
    try:
        obj, status, ms = call_model(gen, SYSTEM, prompt, sch)
    except ProviderError as e:
        return rules, _meta(gen, 'nba', 'fallback', 0, prompt, str(e))
    return obj, _meta(gen, 'nba', status, ms, prompt)


DRAFT_KINDS = ('action_plan', 'str_narrative', 'board_summary')


def draft_rules(kind, ctx, lang='en'):
    ar = lang == 'ar'
    if kind == 'action_plan':
        lines = [f"{'الملاحظة' if ar else 'Finding'}: {ctx.get('title', '')}",
                 f"{'السبب الجذري (للاستكمال)' if ar else 'Root cause (to complete)'}: …"]
        for i, g in enumerate(ctx.get('gaps') or [], 1):
            lines.append(f"{i}. {g.get('text_ar' if ar else 'text_en')}")
        lines.append(f"{'التحقق' if ar else 'Verification'}: " + ('إعادة اختبار الضوابط المرتبطة بعد التنفيذ.' if ar
                                                                 else 're-test the linked controls after implementation.'))
        return {'title': ('خطة تصحيح: ' if ar else 'Action plan: ') + ctx.get('title', ''), 'text': '\n'.join(lines)}
    if kind == 'str_narrative':
        t = ctx
        text = (f"{'العميل' if ar else 'Subject'}: {t.get('subject_name') or '-'} {t.get('subject_ref') or ''}\n"
                f"{'الاكتشاف' if ar else 'Detection'}: {t.get('source_module')} / {t.get('detection_rule')} — {t.get('detected_at')}\n"
                f"{'المبلغ' if ar else 'Amount'}: {t.get('amount') or '-'}\n"
                f"{'الوقائع' if ar else 'Facts'}: {t.get('description') or ''}\n"
                f"{'التحليل (للاستكمال)' if ar else 'Analysis (to complete)'}: …\n"
                f"{'سبب الاشتباه (للاستكمال)' if ar else 'Grounds for suspicion (to complete)'}: …")
        return {'title': 'مسودة إخطار اشتباه' if ar else 'STR narrative draft', 'text': text}
    s = ctx
    text = (f"{'درجة الجاهزية' if ar else 'Readiness score'}: {s.get('score')} / 100 · {s.get('failing')} "
            f"{'ضوابط غير ملتزمة' if ar else 'failing controls'} · {s.get('open_findings')} {'ملاحظات مفتوحة' if ar else 'open findings'}.\n"
            + '\n'.join(f"- {g}" for g in s.get('gaps', [])[:5]))
    return {'title': 'ملخص لمجلس الإدارة' if ar else 'Board summary', 'text': text}


def draft(kind, ctx, lang='en', gen=None):
    gen = gen or RulesOnly()
    if kind not in DRAFT_KINDS:
        raise ValueError('unknown draft kind')
    rules = draft_rules(kind, ctx, lang)
    if not gen.can_generate:
        return rules, _meta(gen, 'draft')
    sch = {'type': 'object', 'required': ['title', 'text'],
           'properties': {'title': {'type': 'string', 'maxLength': 300}, 'text': {'type': 'string', 'maxLength': 6000}}}
    what = {'action_plan': 'a corrective-action plan (root cause placeholder, numbered actions with the given dates, verification step)',
            'str_narrative': 'a factual suspicious-transaction report narrative (facts only from the context, placeholders for analysis)',
            'board_summary': 'a short board summary of compliance readiness'}[kind]
    prompt = (f"Draft {what} in {'Arabic' if lang == 'ar' else 'English'}. Use ONLY facts from the context; write '…' where "
              f"information is missing. Do not conclude whether a crime occurred.\nContext: "
              f"{json.dumps(ctx, ensure_ascii=False, default=str)[:4000]}\n\nReply as JSON: {{\"title\": \"...\", \"text\": \"...\"}}")
    try:
        obj, status, ms = call_model(gen, SYSTEM, prompt, sch)
    except ProviderError as e:
        return rules, _meta(gen, 'draft', 'fallback', 0, prompt, str(e))
    return obj, _meta(gen, 'draft', status, ms, prompt)


def deadline_from(intent, fields, today=None):
    today = today or date.today()
    d = fields.get('deadline')
    if d:
        try:
            return date.fromisoformat(d)
        except ValueError:
            pass
    if intent.get('deadline_hours'):
        return today + timedelta(days=max(1, (int(intent['deadline_hours']) + 23) // 24))
    return None
