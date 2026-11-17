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
"""Database side of the dual-use module: the search index cache, screenings, decisions."""
import csv
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime

from database.db import get_db

from . import screening as SC
from . import search as SE

log = logging.getLogger(__name__)
MODULE = 'dualuse'
CLIENT_LIST_LABEL = ('International approved control lists', 'القوائم الدولية المعتمدة للرقابة')
KIND_LABELS = {'item': ('Controlled item', 'صنف خاضع للرقابة'), 'chemical': ('Controlled chemical', 'مادة كيميائية خاضعة للرقابة'),
               'priority': ('High-priority item', 'صنف عالي الأولوية')}
RISK_LABELS = {'high': ('High', 'مرتفع'), 'medium': ('Medium', 'متوسط'), 'low': ('Low', 'منخفض')}
OUTCOME_LABELS = {'clear': ('Clear', 'سليم'), 'review': ('Review', 'مراجعة'), 'hold': ('Hold', 'إيقاف')}
CATEGORY_LABELS = {
    '0': ('Nuclear materials, facilities and equipment', 'المواد والمنشآت والمعدات النووية'),
    '1': ('Special materials, chemicals, microorganisms and toxins', 'المواد الخاصة والكيماويات والكائنات الدقيقة والسموم'),
    '2': ('Materials processing', 'معالجة المواد'),
    '3': ('Electronics', 'الإلكترونيات'),
    '4': ('Computers', 'الحواسيب'),
    '5': ('Telecommunications and information security', 'الاتصالات وأمن المعلومات'),
    '6': ('Sensors and lasers', 'المستشعرات والليزر'),
    '7': ('Navigation and avionics', 'الملاحة وإلكترونيات الطيران'),
    '8': ('Marine', 'البحرية'),
    '9': ('Aerospace and propulsion', 'الفضاء الجوي والدفع'),
}
GROUP_LABELS = {'A': ('Systems, equipment and components', 'الأنظمة والمعدات والمكونات'),
                'B': ('Test, inspection and production equipment', 'معدات الاختبار والفحص والإنتاج'),
                'C': ('Materials', 'المواد'), 'D': ('Software', 'البرمجيات'), 'E': ('Technology', 'التقنية')}
DECISION_REASONS = [
    ('not_controlled', 'Product does not meet the control parameters', 'المنتج لا يستوفي معايير الرقابة'),
    ('different_product', 'Candidate entries describe a different product', 'البنود المرشحة تصف منتجًا مختلفًا'),
    ('licence_held', 'Licence / authorisation held for this import', 'يوجد ترخيص أو موافقة لهذا الاستيراد'),
    ('end_use_verified', 'End use and end user verified', 'تم التحقق من الاستخدام النهائي والمستخدم النهائي'),
    ('controlled_item', 'Product matches a controlled entry', 'المنتج يطابق بندًا خاضعًا للرقابة'),
    ('missing_information', 'Information missing: hold until provided', 'معلومات ناقصة: إيقاف لحين استكمالها'),
    ('party_concern', 'Concern about a party to the transaction', 'ملاحظة على أحد أطراف المعاملة'),
    ('other', 'Other (explain in the comment)', 'أخرى (يُوضَّح في التعليق)'),
]
REASON_CODES = {r[0] for r in DECISION_REASONS}
MIN_COMMENT = 10

_lock = threading.Lock()
_cache = {'index': None, 'stamp': None, 'checked': 0.0}


# ------------------------------------------------------------------ install
def install_defaults(db):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seed', 'terms.csv')
    n = 0
    with open(path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            db.execute("""INSERT INTO dualuse_terms (term_en, term_ar, source) VALUES (%s,%s,'seed')
                          ON CONFLICT (term_en, term_ar) DO NOTHING""", (r['term_en'].strip(), r['term_ar'].strip()))
            n += 1
    db.commit()
    return {'terms': n}


# ------------------------------------------------------------------ index
def _stamp(db):
    r = db.execute("""SELECT (SELECT coalesce(string_agg(id::text, ',' ORDER BY id), '') FROM dualuse_list_versions
                              WHERE is_current) AS v,
                             (SELECT coalesce(max(id), 0) FROM dualuse_terms) AS t,
                             (SELECT count(*) FROM dualuse_terms) AS tc,
                             (SELECT coalesce(max(ar_updated_at)::text, '') FROM dualuse_items) AS a""").fetchone()
    return '%s|%s|%s|%s' % (r['v'], r['t'], r['tc'], r['a'])


def load_docs(db):
    """Current versions of every list -> Doc dicts for the search index."""
    hs = {}
    for r in db.execute("""SELECT m.resolved_code, m.cn10, m.hs6 FROM dualuse_hs_map m
                           JOIN dualuse_list_versions v ON v.id = m.version_id AND v.is_current
                           JOIN dualuse_lists l ON l.id = v.list_id AND l.code = 'eu_cn_correlation'
                           WHERE m.resolved_code IS NOT NULL""").fetchall():
        hs.setdefault(r['resolved_code'], set()).add(r['cn10'] or r['hs6'])
    params = {}
    for r in db.execute("""SELECT p.* FROM dualuse_parameters p JOIN dualuse_items i ON i.id = p.item_id
                           JOIN dualuse_list_versions v ON v.id = i.version_id AND v.is_current""").fetchall():
        params.setdefault(r['item_id'], []).append(dict(r))
    docs = []
    rows = db.execute("""SELECT i.*, l.code AS list_code FROM dualuse_items i
                         JOIN dualuse_list_versions v ON v.id = i.version_id AND v.is_current
                         JOIN dualuse_lists l ON l.id = v.list_id AND l.is_active
                         WHERE NOT i.not_used ORDER BY l.display_order, i.code""").fetchall()
    titles = {}
    for r in rows:
        if r['level'] == 0:
            titles[(r['list_code'], r['code'])] = (r['title_en'] or r['text_en'] or '', r['title_ar'] or '')
    for r in rows:
        extra = r['extra'] or {}
        kind = 'chemical' if r['list_code'] == 'cwc' else 'item'
        entry = titles.get((r['list_code'], r['entry_code']), ('', ''))
        docs.append({'id': r['id'], 'list_code': r['list_code'], 'code': r['code'], 'entry_code': r['entry_code'],
                     'parent_code': r['parent_code'], 'level': r['level'], 'category': r['category'], 'group': r['grp'],
                     'title_en': r['title_en'], 'title_ar': r['title_ar'],
                     'context_en': entry[0][:300] if r['level'] else None,
                     'context_ar': entry[1][:300] if r['level'] else None,
                     'text_en': r['text_en'], 'text_ar': r['text_ar'],
                     'notes': ' '.join(r['notes_en'] or [])[:3000], 'hs': sorted(hs.get(r['code'], ())),
                     'cas': extra.get('cas') or [], 'risk': r['risk_level'], 'reasons': r['reasons'],
                     'params': params.get(r['id'], []), 'kind': kind, 'ar_status': r['ar_status'],
                     'extra': {k: extra.get(k) for k in ('schedule', 'category_title', 'common_name')}})
    for r in db.execute("""SELECT c.*, l.code AS list_code FROM dualuse_chemicals c
                           JOIN dualuse_list_versions v ON v.id = c.version_id AND v.is_current
                           JOIN dualuse_lists l ON l.id = v.list_id AND l.is_active""").fetchall():
        names = list(r['names_en'] or [])
        refs = [l['ref'] for l in (r['listings'] or []) if l.get('source') in ('eu_annex1', 'us_ccl')]
        risk = 'high' if (r['cwc_schedule'] or r['ag_precursor']) else 'medium'
        docs.append({'id': 'c%d' % r['id'], 'list_code': 'chemicals', 'code': r['cas'], 'level': 0,
                     'category': '1', 'group': 'C', 'title_en': names[0] if names else r['cas'],
                     'title_ar': (r['names_ar'] or [None])[0], 'text_en': '; '.join(names),
                     'text_ar': '; '.join(r['names_ar'] or []), 'cas': [r['cas']], 'risk': risk, 'kind': 'chemical',
                     'ar_status': r['ar_status'],
                     'extra': {'names': names + list(r['names_ar'] or []), 'cwc_schedule': r['cwc_schedule'],
                               'ag_precursor': r['ag_precursor'], 'item_codes': refs}})
    for r in db.execute("""SELECT m.*, l.code AS list_code FROM dualuse_hs_map m
                           JOIN dualuse_list_versions v ON v.id = m.version_id AND v.is_current
                           JOIN dualuse_lists l ON l.id = v.list_id AND l.code = 'chpl' AND l.is_active""").fetchall():
        docs.append({'id': 'p%d' % r['id'], 'list_code': 'chpl', 'code': r['hs6'][:4] + '.' + r['hs6'][4:],
                     'level': 0, 'title_en': r['description_en'], 'title_ar': r['description_ar'],
                     'text_en': r['description_en'], 'text_ar': r['description_ar'], 'hs': [r['hs6']],
                     'risk': 'high' if r['priority_tier'] in ('1', '2') else 'medium', 'kind': 'priority',
                     'extra': {'tier': r['priority_tier']}})
    terms = [(r['term_en'], r['term_ar']) for r in db.execute("SELECT term_en, term_ar FROM dualuse_terms").fetchall()]
    return docs, terms


def get_index(db=None, force=False):
    """The shared index, rebuilt when a list version, the dictionary or an Arabic text changes (checked every 60 s)."""
    now = time.time()
    if not force and _cache['index'] is not None and now - _cache['checked'] < 60:
        return _cache['index']
    db = db or get_db()
    with _lock:
        try:
            stamp = _stamp(db)
        except Exception:
            db.rollback()
            log.warning('dual-use: tables not available', exc_info=True)
            return _cache['index'] or SE.Index([], [])
        _cache['checked'] = now
        if force or stamp != _cache['stamp'] or _cache['index'] is None:
            t0 = time.time()
            docs, terms = load_docs(db)
            _cache['index'] = SE.Index(docs, terms, version=stamp)
            _cache['stamp'] = stamp
            log.info('dual-use index: %d entries in %.1fs', len(docs), time.time() - t0)
    return _cache['index']


def current_versions(db=None):
    db = db or get_db()
    return {r['code']: {'id': r['id'], 'label': r['version_label'], 'loaded_at': r['loaded_at'].isoformat()
                        if r['loaded_at'] else None}
            for r in db.execute("""SELECT l.code, v.id, v.version_label, v.loaded_at FROM dualuse_list_versions v
                                   JOIN dualuse_lists l ON l.id = v.list_id WHERE v.is_current""").fetchall()}


def list_status(db=None):
    db = db or get_db()
    return db.execute("""SELECT l.code, l.legal_name, l.kind, l.is_active, v.id AS version_id, v.version_label,
                                v.record_count, v.stats, v.diff, v.loaded_at, v.source_url,
                                (SELECT count(*) FROM dualuse_items i WHERE i.version_id = v.id
                                   AND i.ar_status IN ('verified', 'reviewed')) AS ar_done,
                                (SELECT count(*) FROM dualuse_items i WHERE i.version_id = v.id
                                   AND i.ar_status = 'draft') AS ar_draft,
                                (SELECT count(*) FROM dualuse_items i WHERE i.version_id = v.id
                                   AND i.ar_status = 'stale') AS ar_stale
                         FROM dualuse_lists l LEFT JOIN dualuse_list_versions v ON v.list_id = l.id AND v.is_current
                         ORDER BY l.display_order""").fetchall()


# ------------------------------------------------------------------ parties
def screen_parties(parties, user_id, screening_id):
    """Run the supplier / consignee / end user through the sanctions screening service."""
    out = []
    if not any(n for _, n in parties):
        return out
    try:
        from screening.customer_screening_service import screen_and_save
    except Exception:
        log.warning('dual-use: screening service not available', exc_info=True)
        return [{'role': r, 'name': n, 'error': 'unavailable'} for r, n in parties if n]
    try:
        for role, name in parties:
            if not name:
                continue
            try:
                res = screen_and_save(name=name, entity_type='ENTITY', source_module='Dual-use goods',
                                      source_record_id=screening_id, screening_type='TRADE', user_id=user_id,
                                      write_results_table=False)
                out.append({'role': role, 'name': name, 'history_id': res.get('history_id'),
                            'result': res.get('screening_result') or res.get('result'),
                            'highest_score': res.get('highest_score'), 'match_count': res.get('match_count')})
            except Exception as e:
                log.exception('dual-use party screening failed')
                out.append({'role': role, 'name': name, 'error': str(e)[:200]})
    finally:
        try:
            from screening import routes as _sr
            eng = getattr(_sr, '_engine_instance', None)
            if eng is not None:
                eng.close()
        except Exception:
            pass
    return out


# ------------------------------------------------------------------ screenings
def _ref():
    return 'DU-%s-%s' % (datetime.now().strftime('%y%m%d'), secrets.token_hex(3).upper())


def _reuse(db, key, versions):
    """An earlier decision on the same product, while the lists it was based on are still current."""
    if not key:
        return None
    r = db.execute("SELECT * FROM dualuse_item_master WHERE item_key = %s", (key,)).fetchone()
    if not r:
        return None
    lv = r['list_versions'] or {}
    if any(lv.get(c) != v['id'] for c, v in versions.items() if c in lv):
        return None
    return r


def run_lines(db, screening_id, lines, index, versions, batch=False):
    counts = {'clear': 0, 'review': 0, 'hold': 0}
    for n, line in enumerate(lines, start=1):
        res = SC.screen_line(index, line)
        sug = SC.batch_suggestion(res) if batch else res['suggested']
        prev = _reuse(db, res['key'], versions)
        db.execute("""INSERT INTO dualuse_screening_lines (screening_id, line_no, description, hs_code, cas, model, origin,
                      quantity, item_key, candidates, hard_flags, questions, suggested, reused_from, decision, reason,
                      comment, decided_by, decided_at)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (screening_id, line.get('line_no') or n, line.get('description'), line.get('hs_code'),
                    line.get('cas'), line.get('model'), line.get('origin'), line.get('quantity'), res['key'],
                    json.dumps(res['candidates']), json.dumps(res['hard']), json.dumps(res['questions']), sug,
                    prev['id'] if prev else None, prev['decision'] if prev else None,
                    prev['reason'] if prev else None,
                    ('Reused decision of an identical product (%s)' % prev['decided_at'].date()) if prev else None,
                    prev['decided_by'] if prev else None, datetime.now() if prev else None))
        counts[sug] += 1
    return counts


def create_screening(header, lines, user_id, batch=False, file_name=None, db=None):
    db = db or get_db()
    index = get_index(db)
    versions = current_versions(db)
    sid = db.execute("""INSERT INTO dualuse_screenings (ref, kind, title, file_name, supplier, consignee, end_user, origin,
                        list_versions, line_count, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (_ref(), 'batch' if batch else 'single', (header.get('title') or '')[:200] or None, file_name,
                      header.get('supplier'), header.get('consignee'), header.get('end_user'), header.get('origin'),
                      json.dumps({k: v['id'] for k, v in versions.items()}), len(lines), user_id)).fetchone()['id']
    counts = run_lines(db, sid, lines, index, versions, batch)
    db.execute("UPDATE dualuse_screenings SET counts = %s WHERE id = %s", (json.dumps(counts), sid))
    db.commit()
    parties = [('supplier', header.get('supplier')), ('consignee', header.get('consignee')),
               ('end_user', header.get('end_user'))]
    if any(n for _, n in parties):
        pr = screen_parties(parties, user_id, sid)
        db.execute("UPDATE dualuse_screenings SET party_results = %s WHERE id = %s", (json.dumps(pr), sid))
        db.commit()
    return sid


def get_screening(sid, db=None):
    db = db or get_db()
    s = db.execute("""SELECT s.*, u.first_name || ' ' || u.last_name AS created_by_name FROM dualuse_screenings s
                      LEFT JOIN users u ON u.id = s.created_by WHERE s.id = %s""", (sid,)).fetchone()
    if not s:
        return None, []
    lines = db.execute("""SELECT l.*, u.first_name || ' ' || u.last_name AS decided_by_name
                          FROM dualuse_screening_lines l LEFT JOIN users u ON u.id = l.decided_by
                          WHERE l.screening_id = %s ORDER BY l.line_no, l.id""", (sid,)).fetchall()
    return s, lines


def get_line(line_id, db=None):
    db = db or get_db()
    return db.execute("SELECT * FROM dualuse_screening_lines WHERE id = %s", (line_id,)).fetchone()


def answer_line(line_id, answers, db=None):
    """Store answers to the questions and recompute the suggestion."""
    db = db or get_db()
    ln = get_line(line_id, db)
    if not ln:
        return None
    sug, state = SC.evaluate(ln['candidates'] or [], ln['hard_flags'] or [], ln['questions'] or [], answers)
    cands = ln['candidates'] or []
    for c in cands:
        c['state'] = state.get((c['list_code'], c['code']), 'open')
    db.execute("UPDATE dualuse_screening_lines SET answers = %s, suggested = %s, candidates = %s WHERE id = %s",
               (json.dumps(answers), sug, json.dumps(cands), line_id))
    _recount(db, ln['screening_id'])
    db.commit()
    return sug


def validate_decision(decision, reason, comment):
    """-> list of error messages (English, Arabic)."""
    errs = []
    if decision not in ('clear', 'hold'):
        errs.append(('Choose Clear or Hold.', 'اختر سليم أو إيقاف.'))
    if reason not in REASON_CODES:
        errs.append(('Choose a reason.', 'اختر السبب.'))
    if len((comment or '').strip()) < MIN_COMMENT:
        errs.append(('Write a comment of at least %d characters.' % MIN_COMMENT,
                     'اكتب تعليقًا لا يقل عن %d حروف.' % MIN_COMMENT))
    return errs


def decide_line(line_id, decision, reason, comment, user_id, remember=True, db=None):
    db = db or get_db()
    ln = get_line(line_id, db)
    if not ln:
        return None
    now = datetime.now()
    db.execute("""UPDATE dualuse_screening_lines SET decision = %s, reason = %s, comment = %s, decided_by = %s,
                  decided_at = %s, reused_from = NULL WHERE id = %s""",
               (decision, reason, comment.strip()[:4000], user_id, now, line_id))
    if remember and ln['item_key']:
        s = db.execute("SELECT list_versions FROM dualuse_screenings WHERE id = %s", (ln['screening_id'],)).fetchone()
        db.execute("""INSERT INTO dualuse_item_master (item_key, description, hs_code, cas, model, decision, reason, comment,
                      list_versions, decided_by, decided_at, screening_line_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (item_key) DO UPDATE SET decision = EXCLUDED.decision, reason = EXCLUDED.reason,
                      comment = EXCLUDED.comment, list_versions = EXCLUDED.list_versions, decided_by = EXCLUDED.decided_by,
                      decided_at = EXCLUDED.decided_at, screening_line_id = EXCLUDED.screening_line_id""",
                   (ln['item_key'], ln['description'], ln['hs_code'], ln['cas'], ln['model'], decision, reason,
                    comment.strip()[:4000], json.dumps(s['list_versions'] or {}), user_id, now, line_id))
    _recount(db, ln['screening_id'])
    db.commit()
    return ln['screening_id']


def _recount(db, sid):
    r = db.execute("""SELECT count(*) FILTER (WHERE coalesce(decision, suggested) = 'clear') AS clear,
                             count(*) FILTER (WHERE decision IS NULL AND suggested = 'review') AS review,
                             count(*) FILTER (WHERE coalesce(decision, suggested) = 'hold') AS hold,
                             count(*) FILTER (WHERE decision IS NULL) AS open
                      FROM dualuse_screening_lines WHERE screening_id = %s""", (sid,)).fetchone()
    db.execute("UPDATE dualuse_screenings SET counts = %s, status = %s, updated_at = now() WHERE id = %s",
               (json.dumps({'clear': r['clear'], 'review': r['review'], 'hold': r['hold']}),
                'decided' if r['open'] == 0 else 'open', sid))


def history(args, limit=200, db=None):
    db = db or get_db()
    where, params = ['TRUE'], []
    if args.get('status') in ('open', 'decided'):
        where.append('s.status = %s')
        params.append(args['status'])
    q = (args.get('q') or '').strip()[:100]
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_') + '%'
        where.append("""(s.ref ILIKE %s OR s.title ILIKE %s OR s.supplier ILIKE %s OR s.consignee ILIKE %s OR EXISTS (
                         SELECT 1 FROM dualuse_screening_lines l WHERE l.screening_id = s.id
                         AND (l.description ILIKE %s OR l.model ILIKE %s OR l.hs_code ILIKE %s)))""")
        params += [like] * 7
    return db.execute(f"""SELECT s.*, u.first_name || ' ' || u.last_name AS created_by_name FROM dualuse_screenings s
                          LEFT JOIN users u ON u.id = s.created_by WHERE {' AND '.join(where)}
                          ORDER BY s.created_at DESC LIMIT %s""", params + [limit]).fetchall()


def stats(db=None):
    db = db or get_db()
    try:
        return db.execute("""SELECT (SELECT count(*) FROM dualuse_screenings) AS screenings,
                                    (SELECT count(*) FROM dualuse_screening_lines WHERE decision IS NULL) AS open_lines,
                                    (SELECT count(*) FROM dualuse_screening_lines WHERE decision = 'hold') AS held,
                                    (SELECT count(*) FROM dualuse_item_master) AS known_items""").fetchone()
    except Exception:
        db.rollback()
        return {}


def add_term(term_en, term_ar, user_id, db=None):
    db = db or get_db()
    db.execute("""INSERT INTO dualuse_terms (term_en, term_ar, source, created_by) VALUES (%s,%s,'analyst',%s)
                  ON CONFLICT (term_en, term_ar) DO NOTHING""", (term_en.strip()[:200], term_ar.strip()[:200], user_id))
    db.commit()


def terms(db=None):
    db = db or get_db()
    return db.execute("SELECT * FROM dualuse_terms ORDER BY term_en").fetchall()


# ------------------------------------------------------------------ batch file
COLUMNS = [('description', 'Description', 'الوصف'), ('hs_code', 'HS / tariff code', 'كود HS / البند الجمركي'),
           ('cas', 'CAS number', 'رقم CAS'), ('model', 'Model / part number', 'الموديل / رقم القطعة'),
           ('origin', 'Origin', 'المنشأ'), ('quantity', 'Quantity', 'الكمية')]
_GUESS = {'description': ('description', 'desc', 'goods', 'item', 'product', 'الوصف', 'البيان', 'الصنف', 'المنتج'),
          'hs_code': ('hs', 'hs code', 'tariff', 'cn', 'hts', 'customs code', 'البند', 'الكود الجمركي', 'رمز'),
          'cas': ('cas',), 'model': ('model', 'part', 'part no', 'part number', 'sku', 'الموديل', 'الطراز'),
          'origin': ('origin', 'country of origin', 'المنشأ', 'بلد المنشأ'), 'quantity': ('qty', 'quantity', 'الكمية')}
MAX_BATCH_LINES = 1000


def read_table(filename, data):
    """Excel / CSV bytes -> (header, rows as lists). Raises ValueError with a user message."""
    name = (filename or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        import io
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise ValueError('The Excel file could not be read.')
        rows = [[('' if c is None else str(c)).strip() for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
    elif name.endswith(('.csv', '.txt')):
        import io
        text = None
        for enc in ('utf-8-sig', 'cp1256', 'latin-1'):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=',;\t') if text else csv.excel
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    else:
        raise ValueError('Upload an Excel (.xlsx) or CSV file.')
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        raise ValueError('The file has no data rows.')
    if len(rows) - 1 > MAX_BATCH_LINES:
        raise ValueError('At most %d lines per file.' % MAX_BATCH_LINES)
    return rows[0], rows[1:]


def guess_mapping(header):
    from . import text as T
    m = {}
    for i, h in enumerate(header):
        hf = T.fold(h).strip()
        for field, keys in _GUESS.items():
            if field not in m and any(hf == T.fold(k) or hf.startswith(T.fold(k)) for k in keys):
                m[field] = i
    return m


def lines_from(rows, mapping):
    out = []
    for n, r in enumerate(rows, start=1):
        line = {'line_no': n}
        for field, _, _ in COLUMNS:
            i = mapping.get(field)
            line[field] = (r[i] if i is not None and i < len(r) else '').strip()[:1000] or None
        if any(line.get(f) for f in ('description', 'hs_code', 'cas', 'model')):
            out.append(line)
    return out
