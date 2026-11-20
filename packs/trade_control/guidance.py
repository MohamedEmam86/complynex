# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Practical guidance shown next to every result: what the item is in plain words, why it is controlled, the
threshold in plain words (with a check of the user's value), what to ask the customer, which documents to
collect, the competent Egyptian authority (or "no specific Egyptian authority - apply international practice"),
red flags, and the sources with their confidence.

The guidance is DATA: seed/guidance.json is loaded into dualuse_guidance (one current version per category,
bilingual); the superadmin edits it on the guidance page (each edit is a new version). Categories are matched
to a result by keys: control-code prefixes ('5A002', '0A'), 'HS<digits>', 'CHPL-T<tier>', 'CWC-S<schedule>',
'AG-CHEM' and 'EU-2019/1148-ANNEX-I/II'. Nothing here calls an external service.
"""
import hashlib
import json
import logging
import os
import re
import threading
import time

from . import screening as SC
from . import text as T

log = logging.getLogger(__name__)
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seed', 'guidance.json')
FIELDS = ('why_it_matters', 'ask_customer', 'documents', 'egyptian_authority', 'red_flags')
LIST_FIELDS = ('ask_customer', 'documents', 'red_flags')
FALLBACK = 'general'
_CODE_KEY = re.compile(r'^\d[A-E](?:\d{3}(?:\.[a-z0-9.]+)?)?$', re.I)
_lock = threading.Lock()
_cache = {'stamp': None, 'cats': None, 'checked': 0.0}


# ------------------------------------------------------------------ seed -> table
def seed():
    with open(SEED, encoding='utf-8') as f:
        return json.load(f)


def _sha(cat):
    return hashlib.sha256(json.dumps(cat, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def install(db):
    """Load the seed: a category not in the table is added; a category still at a seed version follows a newer
    seed (new version); a category edited by the superadmin is never overwritten. -> {added, updated}."""
    added = updated = 0
    for c in seed():
        sha = _sha(c)
        cur = db.execute("SELECT * FROM dualuse_guidance WHERE category = %s AND is_current", (c['category'],)).fetchone()
        if cur and (cur['origin'] != 'seed' or cur['seed_sha'] == sha):
            continue
        ver = 1
        if cur:
            ver = db.execute("SELECT max(version) AS v FROM dualuse_guidance WHERE category = %s",
                             (c['category'],)).fetchone()['v'] + 1
            db.execute("UPDATE dualuse_guidance SET is_current = FALSE WHERE id = %s", (cur['id'],))
            updated += 1
        else:
            added += 1
        db.execute("""INSERT INTO dualuse_guidance (category, version, is_current, label_en, label_ar, keys, content,
                      sources, confidence, origin, seed_sha) VALUES (%s,%s,TRUE,%s,%s,%s,%s,%s,%s,'seed',%s)""",
                   (c['category'], ver, c['label_en'], c.get('label_ar'), c.get('keys') or [],
                    json.dumps({'en': c.get('en') or {}, 'ar': c.get('ar') or {}}, ensure_ascii=False),
                    json.dumps(c.get('sources') or []), c.get('confidence'), sha))
    return {'added': added, 'updated': updated}


def _row(r):
    content = r['content'] or {}
    return {'id': r['id'], 'category': r['category'], 'version': r['version'], 'label_en': r['label_en'],
            'label_ar': r['label_ar'] or r['label_en'], 'keys': list(r['keys'] or []), 'en': content.get('en') or {},
            'ar': content.get('ar') or {}, 'sources': r['sources'] or [], 'confidence': r['confidence'] or '',
            'origin': r['origin'], 'created_at': r['created_at'], 'edited_by': r['edited_by'], 'note': r['note']}


def categories(db=None, force=False):
    """Current guidance categories (cached per worker, re-read when a version is added). The seed is loaded
    on first use when the table is empty. Never raises: [] when the table does not exist yet."""
    now = time.time()
    if not force and _cache['cats'] is not None and now - _cache['checked'] < 60:
        return _cache['cats']
    from database.db import get_db
    db = db or get_db()
    with _lock:
        try:
            db.execute("SAVEPOINT du_guidance")
            stamp = db.execute("SELECT coalesce(max(id), 0) AS m, count(*) AS n FROM dualuse_guidance").fetchone()
            if not stamp['n']:
                install(db)
                stamp = db.execute("SELECT coalesce(max(id), 0) AS m, count(*) AS n FROM dualuse_guidance").fetchone()
            key = '%s|%s' % (stamp['m'], stamp['n'])
            if force or key != _cache['stamp'] or _cache['cats'] is None:
                rows = db.execute("SELECT * FROM dualuse_guidance WHERE is_current ORDER BY id").fetchall()
                _cache['cats'], _cache['stamp'] = [_row(r) for r in rows], key
            db.execute("RELEASE SAVEPOINT du_guidance")
            try:
                db.commit()           # the seed loaded on first use stays loaded
            except Exception:
                pass
        except Exception:
            try:
                db.execute("ROLLBACK TO SAVEPOINT du_guidance")
            except Exception:
                pass
            log.warning('dual-use: guidance not available', exc_info=True)
            return _cache['cats'] or []
        _cache['checked'] = now
    return _cache['cats']


def reset_cache():
    _cache['cats'], _cache['stamp'], _cache['checked'] = None, None, 0.0


def history(category, db):
    return [_row(r) for r in db.execute("SELECT * FROM dualuse_guidance WHERE category = %s ORDER BY version DESC",
                                        (category,)).fetchall()]


def save(db, category, data, user_id, note=None):
    """A superadmin's edit -> a new current version (the previous ones stay)."""
    cur = db.execute("SELECT * FROM dualuse_guidance WHERE category = %s AND is_current", (category,)).fetchone()
    if not cur:
        raise KeyError(category)
    ver = db.execute("SELECT max(version) AS v FROM dualuse_guidance WHERE category = %s", (category,)).fetchone()['v'] + 1
    db.execute("UPDATE dualuse_guidance SET is_current = FALSE WHERE id = %s", (cur['id'],))
    db.execute("""INSERT INTO dualuse_guidance (category, version, is_current, label_en, label_ar, keys, content, sources,
                  confidence, origin, seed_sha, note, edited_by) VALUES (%s,%s,TRUE,%s,%s,%s,%s,%s,%s,'edited',%s,%s,%s)""",
               (category, ver, data['label_en'], data.get('label_ar'), data.get('keys') or [],
                json.dumps({'en': data['en'], 'ar': data['ar']}, ensure_ascii=False),
                json.dumps(data.get('sources') or []), data.get('confidence'), cur['seed_sha'], note, user_id))
    db.commit()
    reset_cache()
    return ver


def from_form(form, current):
    """Edit form -> guidance data (list fields: one entry per line). -> (data, errors)."""
    def lines(v):
        return [x.strip()[:600] for x in (v or '').splitlines() if x.strip()][:30]
    data = {'label_en': (form.get('label_en') or '').strip()[:200], 'label_ar': (form.get('label_ar') or '').strip()[:200],
            'keys': [k.strip()[:40] for k in re.split(r'[\s,;]+', form.get('keys') or '') if k.strip()][:200],
            'sources': [u for u in lines(form.get('sources')) if re.match(r'https?://', u)][:30],
            'confidence': (form.get('confidence') or '').strip()[:2000], 'en': {}, 'ar': {}}
    for lang in ('en', 'ar'):
        for f in FIELDS:
            v = form.get('%s_%s' % (lang, f))
            data[lang][f] = lines(v) if f in LIST_FIELDS else (v or '').strip()[:3000]
    errs = []
    if not data['label_en']:
        errs.append(('The English name is required.', 'الاسم بالإنجليزية مطلوب.'))
    if not data['en']['why_it_matters'] or not data['en']['egyptian_authority']:
        errs.append(('"Why it matters" and "Egyptian authority" are required in English.',
                     'حقلا «سبب الأهمية» و«الجهة المصرية» مطلوبان بالإنجليزية.'))
    if current['category'] == FALLBACK:
        data['keys'] = []
    return data, errs


# ------------------------------------------------------------------ matching
def _score(k, list_code, code, hs, extra, codes):
    K = k.strip().upper()
    if K.startswith('HS') and K[2:].isdigit():
        d = K[2:]
        return 10 + len(d) if any((h or '').startswith(d) for h in hs) else 0
    if K.startswith('EU-2019/1148-ANNEX-'):
        return 99 if list_code == 'eu_expl_precursors' and (extra.get('annex') or '') == K.rsplit('-', 1)[1] else 0
    if K.startswith('CWC-S'):
        sch = extra.get('cwc_schedule') or extra.get('schedule')
        return 95 if sch and K == 'CWC-S%s' % sch else 0
    if K == 'AG-CHEM':
        return 94 if extra.get('ag_precursor') else 0
    if K.startswith('CHPL-T'):
        return 90 if list_code == 'chpl' and str(extra.get('tier') or '').upper().startswith(K[6:]) else 0
    if _CODE_KEY.match(K):
        best = 0
        for c in codes:
            c = (c or '').upper()
            if c == K or c.startswith(K + '.') or (len(K) == 2 and c.startswith(K)):
                best = max(best, 50 + len(K))
        return best
    return 0


def match(list_code, code, hs=(), extra=None, cats=None):
    """The guidance category of a result (the most specific key wins), else the general category."""
    cats = cats if cats is not None else categories()
    extra = extra or {}
    codes = [code] if list_code in ('eu_annex1', 'us_ccl') else []
    codes += list(extra.get('item_codes') or [])            # a chemical's control entries
    hs = [re.sub(r'\D', '', h or '') for h in (hs or [])]
    best, fallback = (0, None), None
    for c in cats:
        if c['category'] == FALLBACK:
            fallback = c
        for k in c['keys']:
            s = _score(k, list_code, code, hs, extra, codes)
            if s > best[0]:
                best = (s, c)
    return best[1] or fallback


def for_doc(d, cats=None):
    if d is None:
        return None
    return match(d.list_code, d.code, d.hs, d.extra, cats)


# ------------------------------------------------------------------ plain language
def _cat(d):
    from .service import CATEGORY_LABELS, GROUP_LABELS
    c = CATEGORY_LABELS.get(d.category or '')
    g = GROUP_LABELS.get(d.group or '')
    return c, g


def plain(d, entry=None):
    """What the item is, in plain words -> (en, ar)."""
    x = d.extra or {}
    if d.list_code == 'eu_expl_precursors':
        name = d.title_en or d.code
        if x.get('annex') == 'I':
            return ('%s is a chemical sold for ordinary uses (fertiliser, cleaning, laboratory, industry) that can '
                    'also be misused to make home-made explosives. Above the limit value it must not be sold to '
                    'the general public.' % name,
                    '%s مادة كيميائية تُباع لاستخدامات عادية (أسمدة أو تنظيف أو معامل أو صناعة) لكن يمكن إساءة '
                    'استخدامها في تصنيع متفجرات بدائية. فوق القيمة الحدية لا يجوز بيعها لعامة الجمهور.' % name)
        return ('%s is an everyday chemical that can also be used to make home-made explosives: there is no '
                'concentration limit, but suspicious transactions, disappearances and thefts must be reported.' % name,
                '%s مادة كيميائية شائعة يمكن استخدامها أيضًا في تصنيع متفجرات بدائية: لا يوجد حد للتركيز، '
                'لكن يجب الإبلاغ عن المعاملات المشبوهة وحالات الفقد والسرقة.' % name)
    if d.kind == 'priority':
        hs = (d.hs or [d.code])[0]
        return ('Goods under customs code %s.%s (%s). International export-control authorities identify this code '
                'as high priority for diversion to weapons programmes (priority tier %s).'
                % (hs[:4], hs[4:6], (d.title_en or '')[:160], x.get('tier') or '-'),
                'سلع تحت الكود الجمركي %s.%s (%s). تعتبر سلطات الرقابة الدولية على الصادرات هذا الكود عالي '
                'الأولوية لخطر التحويل إلى برامج التسليح (فئة الأولوية %s).'
                % (hs[:4], hs[4:6], (d.title_ar or d.title_en or '')[:160], x.get('tier') or '-'))
    if d.list_code in ('chemicals', 'cwc'):
        name = d.title_en or d.code
        cas = (' (CAS %s)' % d.code) if d.list_code == 'chemicals' else ''
        return ('%s%s is a listed toxic chemical or a precursor that can be used to make chemical weapons; most '
                'listed chemicals also have ordinary industrial uses.' % (name, cas),
                '%s%s مادة كيميائية سامة مدرجة أو سليفة يمكن استخدامها في تصنيع أسلحة كيميائية؛ ولمعظم المواد '
                'المدرجة استخدامات صناعية عادية أيضًا.' % (d.title_ar or name, cas))
    c, g = _cat(d)
    title = (d.title_en if not d.level and d.title_en else (d.text_en or ''))[:220]
    title_ar = (d.title_ar if not d.level and d.title_ar else (d.text_ar or ''))[:220] or title
    ctx = ''
    ctx_ar = ''
    if d.level and d.context_en:
        ctx, ctx_ar = ' It belongs to: %s.' % d.context_en[:160], ' ويندرج ضمن: %s.' % (d.context_ar or d.context_en)[:160]
    area = ' Area: %s — %s.' % (c[0], g[0]) if c and g else ''
    area_ar = ' المجال: %s — %s.' % (c[1], g[1]) if c and g else ''
    return ('An item of this kind: "%s".%s%s Such items have civilian uses but can also serve weapons or military '
            'programmes, so their export is controlled when they meet the technical parameters.' % (title, ctx, area),
            'صنف من هذا النوع: «%s».%s%s لهذه الأصناف استخدامات مدنية لكنها قد تخدم برامج التسليح أو الأغراض '
            'العسكرية، لذلك يخضع تصديرها للرقابة متى استوفت المعايير الفنية.' % (title_ar, ctx_ar, area_ar))


def _pname(p):
    return SC._clean_param(p.get('parameter')) or ''


# a parameter label that already ends with its verb / preposition joins the value directly:
# "fertilizer blends containing" -> "fertilizer blends containing more than 15 %"
_JOINS = re.compile(r'\b(?:containing|contain|contains|having|with|of|at|exceeding|rated\s+at|that\s+contains?)$', re.I)
PARAM_AR = {'nitrogen content (w/w)': 'محتوى النيتروجين (وزن/وزن)', 'concentration (w/w)': 'التركيز (وزن/وزن)',
            'particle size': 'حجم الجسيمات', 'metal content (w/w)': 'محتوى المعدن (وزن/وزن)'}
OP_PLAIN = {'>': ('more than', 'أكثر من'), '>=': ('at least', 'لا يقل عن'), '<': ('less than', 'أقل من'),
            '<=': ('at most', 'لا يزيد عن')}


def _phrase(p):
    """'the output power is more than 1 W' / 'fertilizer blends containing more than 15 %' (+ Arabic)."""
    en_op, ar_op = OP_PLAIN[p['operator']]
    unit = p.get('unit') or ''
    val = '%s %s' % ('%g' % p['value'], unit) if unit else '%g' % p['value']
    rng_en = rng_ar = ''
    if p.get('upper_op') in OP_PLAIN and p.get('upper_value') is not None:
        ue, ua = OP_PLAIN[p['upper_op']]
        uu = p.get('upper_unit') or unit
        rng_en = ' and %s %g %s' % (ue, p['upper_value'], uu)
        rng_ar = ' و%s %g %s' % (ua, p['upper_value'], uu)
    name = _pname(p)
    low = name[:1].lower() + name[1:]
    joined = bool(_JOINS.search(name))
    if joined:
        en = '%s %s %s%s' % (low, en_op, val, rng_en)
    else:
        verb = 'are' if re.search(r'[^s]s$', low.split(' (')[0]) else 'is'
        en = 'the %s %s %s %s%s' % (low, verb, en_op, val, rng_en)
    ar_name = p.get('parameter_ar') or PARAM_AR.get(low) or name
    ar = '«%s» %s %s%s' % (ar_name, ar_op, val, rng_ar)
    return re.sub(r'\s+', ' ', en).strip(), re.sub(r'\s+', ' ', ar).strip(), joined


def thresholds(d, limit=6):
    """The entry's thresholds in plain words, each with what the check needs -> [dict]. A threshold of an exclusion
    clause says when the entry does NOT apply."""
    out = []
    x = d.extra or {}
    for n, p in enumerate(d.params or []):
        if p.get('operator') not in OP_PLAIN or p.get('value') is None or not _pname(p):
            continue
        en, ar, joined = _phrase(p)
        role = p.get('role') or 'control'
        if role == 'exclusion':
            text_en = 'Not covered by this entry (exclusion): %s.' % en
            text_ar = 'لا يشمله هذا البند (استثناء): %s.' % ar
        elif joined and d.list_code != 'eu_expl_precursors':
            text_en = 'Controlled: %s.' % en
            text_ar = 'يخضع للرقابة: %s.' % ar
        elif d.list_code == 'eu_expl_precursors' and x.get('annex') == 'I':
            text_en = 'Restricted when %s. At or below that value the product is outside this restriction.' % en
            text_ar = 'يكون مقيدًا عندما تكون قيمة %s. عند هذه القيمة أو أقل منها يكون المنتج خارج هذا القيد.' % ar
        elif d.list_code == 'eu_expl_precursors':
            text_en = 'Covered when %s.' % en
            text_ar = 'يشمله البند عندما تكون قيمة %s.' % ar
        else:
            text_en = 'Controlled when %s.' % en
            text_ar = 'يخضع للرقابة عندما تكون قيمة %s.' % ar
        out.append({'n': n, 'name': _pname(p) + (' (exclusion)' if role == 'exclusion' else ''), 'en': text_en,
                    'ar': text_ar, 'unit': p.get('unit') or '', 'raw': p.get('raw') or '', 'role': role})
        if len(out) >= limit:
            break
    return out


def check(d, n, value, unit):
    """The user's value against threshold n of the entry -> {'result': 'above' | 'below' | 'excluded' |
    'not_excluded' | 'ask' | 'unknown', en, ar}."""
    params = d.params or []
    if not (0 <= n < len(params)):
        return {'result': 'unknown', 'en': 'Unknown threshold.', 'ar': 'حد غير معروف.'}
    p = params[n]
    q = {'operator': p.get('operator'), 'base_value': p.get('base_value'), 'base_unit': p.get('base_unit'),
         'unit': p.get('unit'), 'upper_op': p.get('upper_op'), 'upper_base': p.get('upper_base')}
    if q['base_value'] is None and p.get('unit'):
        q['base_value'], q['base_unit'] = T.to_base(p.get('value'), p.get('unit'))
    value, unit = str(value or '').strip()[:30], (unit or '').strip()[:20]
    m = re.match(r'^\s*([-+]?[\d.,]+)\s*(.*)$', value)          # "34 % N" typed in the value box
    if m and m.group(2).strip():
        value, unit = m.group(1), m.group(2).strip()
    unit = unit or p.get('unit') or ''
    try:
        num = T.number(value)
    except (ValueError, TypeError):
        num = None
    # 0.34 against a percentage threshold is most likely a fraction (34 %): ask instead of answering
    if num is not None and T.percent_factor(unit) == 1.0 and p.get('unit') == '%' and 0 < num < 1 \
            and (p.get('value') or 0) >= 1:
        return {'result': 'ask',
                'en': '%g looks like a fraction: did you mean %g %%? Enter the value as a percentage. (If the product '
                      'really contains %g %%, it is below this threshold.)' % (num, num * 100, num),
                'ar': 'القيمة %g تبدو كنسبة عشرية: هل تقصد %g٪؟ أدخل القيمة كنسبة مئوية. (إذا كان المنتج يحتوي فعلًا '
                      'على %g٪ فهي أقل من هذا الحد.)' % (num, num * 100, num)}
    r = SC._threshold_result(q, {'value': value, 'unit': unit})
    if (p.get('role') or 'control') == 'exclusion':
        if r == 'yes':
            return {'result': 'excluded', 'en': 'Your value falls in the exclusion: this entry does not apply to the '
                                                'product (keep the specification as evidence).',
                    'ar': 'القيمة المدخلة تقع ضمن الاستثناء: لا ينطبق هذا البند على المنتج (احتفظ بالمواصفات كدليل).'}
        if r == 'no':
            return {'result': 'not_excluded', 'en': 'Your value is not in the exclusion: the control thresholds of the '
                                                    'entry decide.',
                    'ar': 'القيمة المدخلة ليست ضمن الاستثناء: تحدد الحدود الرقابية للبند النتيجة.'}
    precursor = d.list_code == 'eu_expl_precursors' and (d.extra or {}).get('annex') == 'I'
    if r == 'yes':
        if precursor:
            return {'result': 'above', 'en': 'Above the limit value: restricted explosives precursor. Follow the next steps below.',
                    'ar': 'أعلى من القيمة الحدية: سليفة متفجرات مقيدة. اتبع الخطوات التالية أدناه.'}
        return {'result': 'above', 'en': 'Your value meets this threshold: the entry may apply. Follow the next steps below.',
                'ar': 'القيمة المدخلة تستوفي هذا الحد: قد ينطبق البند. اتبع الخطوات التالية أدناه.'}
    if r == 'no':
        if precursor and (d.extra or {}).get('complete'):
            return {'result': 'below', 'en': 'At or below the limit value: outside this restriction (based on the value '
                                             'you entered — keep the product specification as evidence).',
                    'ar': 'عند القيمة الحدية أو أقل: خارج هذا القيد (بناءً على القيمة المدخلة — احتفظ بمواصفات '
                          'المنتج كدليل).'}
        return {'result': 'below', 'en': 'Your value is below this threshold. Other parameters of the entry may still '
                                         'apply: check them too.',
                'ar': 'القيمة المدخلة أقل من هذا الحد. قد تنطبق معايير أخرى في البند: راجعها أيضًا.'}
    return {'result': 'unknown', 'en': 'Enter a number with a unit of the same kind (%s), e.g. 34 %%, 34 %% N, 340 g/kg.'
                                       % (p.get('unit') or '-') if p.get('unit') == '%' else
            'Enter a number with a unit of the same kind (%s).' % (p.get('unit') or '-'),
            'ar': 'أدخل رقمًا بوحدة من النوع نفسه (%s).' % (p.get('unit') or '-')}


# ------------------------------------------------------------------ sources
def confidence_level(text):
    t = (text or '').lower()
    if 'unverified' in t or 'not found' in t or 'inferred' in t:
        return ('Partly unverified — check before relying on it', 'غير مؤكد جزئيًا — تحقق قبل الاعتماد عليه'), 'low'
    if 'secondary' in t:
        return ('Secondary sources', 'مصادر ثانوية'), 'medium'
    return ('Confirmed in primary sources', 'مؤكد من مصادر أولية'), 'high'


# Owner decision: clients never see the names of the source lists. The guidance texts cite them (they were
# written for the superadmin's review); for everyone else these names become the generic wording.
NEUTRAL = [   # (pattern, English, Arabic) - applied in order
    (r'(?:\b[Tt]he\s+)?(?:EU\s+)?(?:Regulation\s+\(EU\)\s*|EU\s+Regulation\s+)?2019/1148(?:\s+Annex\s+I{1,2}\b)?',
     'the international explosives-precursor list', None),
    (r'(?:ال)?(?:لائحة|اللائحة)\s+الأوروبية\s*(?:رقم\s*)?2019/1148|2019/1148', None, 'القائمة الدولية لسلائف المتفجرات'),
    (r'(?:\b[Tt]he\s+)?(?:EU\s+)?(?:Regulation\s+\(EU\)\s*)?2021/821(?:\s+Annex\s+I\b)?'
     r'|(?:\b[Tt]he\s+)?\bEU\s+Annex\s+I\b(?:\s+Cat\.\s*\d)?(?:\s+Part\s+\d)?(?:\s+note\s+\d)?',
     'the international export-control list', None),
    (r'(?:اللائحة\s+الأوروبية\s*(?:رقم\s*)?)?2021/821', None, 'القائمة الدولية للرقابة على الصادرات'),
    (r'(?:\b[Tt]he\s+)?\bUS\s+\d[A-E]\d{3}(?:\s*/\s*740\.17)?(?:\s+self-classification)?', 'a self-classification', None),
    (r'(?:\bUS\s+)?\bEAR\b', 'export-control regulations', None),
    (r'\bECCN\b', 'export-control classification number', None),
    (r'\bEU\s+control\s+entry\b', 'control-list entry', None),
    (r'\bEU\s+classification\b', 'control-list classification', None),
    (r'(?:\b[Tt]he\s+)?\bCHPL\b(?:\s+Tiers?\s+\d(?:\s*[–-]\s*\d)?(?:\.[AB])?)?(?:\s+diversion\s+controls)?',
     'the high-priority diversion list', None),
    (r'([وب]?)قائمة\s+(?:البنود\s+ذات\s+الأولوية\s+القصوى\s*)?\(?CHPL\)?', None, r'\1قائمة الأصناف عالية الأولوية لخطر التحويل'),
    (r'\(?\bCHPL\b\)?', None, 'قائمة الأصناف عالية الأولوية لخطر التحويل'),
    (r'Chemical\s+Weapons\s+Convention|\bCWC\b', 'chemical-weapons convention', 'اتفاقية حظر الأسلحة الكيميائية'),
    (r'(?:\b[Tt]he\s+)?\bAustralia\s+Group\b(?:\s+list)?', 'the international chemical and biological control list', None),
    (r'(?:قائمة\s+)?مجموعة\s+أستراليا', None, 'القائمة الدولية للرقابة الكيميائية والبيولوجية'),
    (r'\b(?:MTCR|Wassenaar(?:\s+Arrangement)?|NSG)\b', 'international export-control regimes', 'أنظمة الرقابة الدولية على الصادرات'),
    (r'\bBIS\b', 'international', 'الدولية'),
    (r'(?:\b[Tt]he\s+)?\bUS\s+Munitions\s+List\b|\(?\bUSML\b\)?', 'the munitions list', None),
    (r'القائمة\s+الأمريكية\s+للذخائر\s*\(?USML\)?|\(?USML\)?', None, 'قائمة الذخائر'),
    (r'قائمة\s+الأوروبية', None, 'قائمة الدولية'),
    (r'(?:من\s+)?الملحق\s+الأول\s+الأوروبي', None, 'من القائمة الدولية'),
    (r'\bEU-style\b', 'international', None),
    (r'(?:\b[Tt]he\s+)?\bUN,\s+(?:Egyptian\s+\(Law 8/2015 lists\),\s+)?EU,\s+OFAC\s+and\s+UK\s+lists',
     'the international and Egyptian sanctions lists', None),
    (r'قوائم\s+الأمم\s+المتحدة\s+والاتحاد\s+الأوروبي\s+ومكتب\s+مراقبة\s+الأصول\s+الأجنبية\s+الأمريكي(?:\s+والمملكة\s+المتحدة)?',
     None, 'قوائم العقوبات الدولية'),
    (r'(?:وقوائم|قوائم)\s+الاتحاد\s+الأوروبي\s+ومكتب\s+مراقبة\s+الأصول\s+الأجنبية\s+الأمريكي(?:\s+والمملكة\s+المتحدة)?',
     None, 'وقوائم العقوبات الدولية'),
    (r'البند\s+الأوروبي', None, 'بند قائمة الرقابة'),
    (r'لوائح\s+التصدير\s+الأمريكية(?:\s+EAR)?', None, 'لوائح الرقابة على الصادرات'),
    (r'(?:رقم\s+التصنيف\s+)?ECCN', None, 'كود الرقابة'),
    (r'\bEAR\b', None, 'لوائح الرقابة على الصادرات'),
    (r'التصنيف\s+الذاتي\s+الأمريكي\s*\d[A-E]\d{3}(?:\s*/\s*740\.17)?', None, 'التصنيف الذاتي'),
    (r'(?:\bthe\s+)?\bEU\s+(?=list\b)', 'the international ', None),
]
_NEUTRAL = [(re.compile(p), en, ar) for p, en, ar in NEUTRAL]


def neutral(text, lang='en'):
    """A guidance text without the names of the source lists (clients)."""
    if not text:
        return text
    if isinstance(text, list):
        return [neutral(t, lang) for t in text]
    for rx, en, ar in _NEUTRAL:
        rep = ar if lang == 'ar' else en
        if rep is None:
            continue
        text = rx.sub(rep, text)
    text = re.sub(r'\b([Tt]he)\s+the\b', r'\1', text)
    return re.sub(r'(^|[.!?]\s+)the\b', lambda m: m.group(1) + 'The', text)


def client_label(cat):
    """The category name for clients: without the names of the source lists written in brackets."""
    en = re.sub(r'\s*\([^)]*\)', '', cat['label_en']).strip()
    ar = re.sub(r'\s*\([^)]*\)', '', cat['label_ar'] or '').strip() or en
    return en, ar


def view(cat, lang='en', sources=False):
    """Category -> the fields to show, English-first with the Arabic used field by field when present. Without
    `sources` (every user but the superadmin) the names of the source lists are replaced by generic wording."""
    if not cat:
        return None
    out = {'category': cat['category'], 'version': cat['version'], 'label': cat['label_en'], 'label_ar': cat['label_ar'],
           'client_label': client_label(cat), 'sources': cat['sources'], 'confidence': cat['confidence'],
           'level': confidence_level(cat['confidence'])}
    for f in FIELDS:
        en, ar = cat['en'].get(f), cat['ar'].get(f)
        use_ar = bool(lang == 'ar' and ar)
        out[f] = ar if use_ar else en
        if not sources:
            out[f] = neutral(out[f], 'ar' if use_ar else 'en')
        out[f + '_is_ar'] = use_ar
    auth = (cat['en'].get('egyptian_authority') or '').lower()
    out['no_authority'] = auth.startswith('no specific') or 'no specific egyptian' in auth
    shown = (out.get('egyptian_authority') or '').strip()
    out['auth_prefix'] = out['no_authority'] and not shown.lower().startswith(('no specific', 'لا توجد', 'لم يتم'))
    return out
