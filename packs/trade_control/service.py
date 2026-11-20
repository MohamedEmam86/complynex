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
import re
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
# Owner decision: clients never see the source lists, only this generic label (real names: site admins only).
CLIENT_LIST_LABEL = ('International export-control lists (dual-use items, controlled chemicals, explosives '
                     'precursors, high-priority diversion items)',
                     'قوائم الرقابة الدولية على الصادرات (الأصناف مزدوجة الاستخدام، والمواد الكيميائية الخاضعة '
                     'للرقابة، وسلائف المتفجرات، والأصناف عالية الأولوية لخطر التحويل)')
# What clients see on each result instead of the source list's name (owner decision, round 3).
CLIENT_LABELS = {
    'item': ('Controlled item – international export-control list',
             'صنف خاضع للرقابة – قائمة دولية للرقابة على الصادرات'),
    'chemical': ('Controlled chemical – international chemical-weapons control list',
                 'مادة كيميائية خاضعة للرقابة – قائمة دولية لحظر الأسلحة الكيميائية'),
    'precursor_I': ('Restricted explosives precursor', 'سليفة متفجرات مقيدة'),
    'precursor_II': ('Reportable explosives precursor', 'سليفة متفجرات واجبة الإبلاغ'),
    'priority': ('High-priority diversion item', 'صنف عالي الأولوية لخطر التحويل'),
    'hs_map': ('Customs-code correlation (indicative)', 'ربط أكواد التعريفة الجمركية (استرشادي)'),
}


def client_label_key(list_code, extra=None):
    if list_code == 'eu_expl_precursors':
        return 'precursor_%s' % ((extra or {}).get('annex') or 'I')
    if list_code in ('cwc', 'chemicals'):
        return 'chemical'
    if list_code == 'chpl':
        return 'priority'
    if list_code == 'eu_cn_correlation':
        return 'hs_map'
    return 'item'


def client_label(list_code, extra=None):
    return CLIENT_LABELS[client_label_key(list_code, extra)]
# Short real names of the lists - shown to site administrators only.
LIST_SHORT = {'eu_annex1': 'EU 2021/821 Annex I', 'us_ccl': 'US CCL (EAR Part 774)', 'cwc': 'CWC schedules',
              'chemicals': 'Chemicals register', 'eu_cn_correlation': 'EU CN / dual-use correlation',
              'chpl': 'Common High Priority List', 'eu_expl_precursors': 'EU 2019/1148 explosives precursors'}
CHEM_LEVEL = {1: ('Listed toxic chemical - highest concern', 'مادة كيميائية سامة مدرجة - أعلى درجة خطورة'),
              2: ('Listed toxic chemical or precursor - high concern', 'مادة سامة أو سليفة مدرجة - خطورة مرتفعة'),
              3: ('Listed toxic chemical or precursor - elevated concern', 'مادة سامة أو سليفة مدرجة - خطورة ملحوظة')}
DISCLAIMER = ('This is a screening result that supports your own assessment. It is not a legal classification, an '
              'export or import licence decision, or a clearance. The English text of each control entry is the '
              'reference; the decision and its justification are recorded by the user.',
              'هذه نتيجة فحص تدعم تقييمك الخاص، وليست تصنيفًا قانونيًا ولا قرارًا بترخيص تصدير أو استيراد ولا إفراجًا. '
              'النص الإنجليزي لكل بند رقابة هو المرجع، والقرار ومبرراته يسجلها المستخدم.')
KIND_LABELS = {'item': ('Controlled item', 'صنف خاضع للرقابة'), 'chemical': ('Controlled chemical', 'مادة كيميائية خاضعة للرقابة'),
               'priority': ('High-priority item', 'صنف عالي الأولوية')}
RISK_LABELS = {'high': ('High', 'مرتفع'), 'medium': ('Medium', 'متوسط'), 'low': ('Low', 'منخفض')}
OUTCOME_LABELS = {'clear': ('Clear', 'لا مؤشرات'), 'review': ('Review', 'مراجعة'), 'hold': ('Hold', 'إيقاف')}
OUTCOME_HELP = {
    'clear': ('No control entry or flag remains open for the data given.',
              'لا يوجد بند رقابة أو مؤشر مفتوح للبيانات المدخلة.'),
    'review': ('Possible control entries: answer the technical questions or check the specifications.',
               'بنود رقابة محتملة: أجب عن الأسئلة الفنية أو راجع المواصفات.'),
    'hold': ('A listed chemical, a control code on the document or a met threshold: do not proceed until assessed.',
             'مادة كيميائية مدرجة أو كود رقابة في المستند أو حد فني مستوفى: لا تستكمل قبل التقييم.')}
# Owner decision: the real list names, versions and links are for the platform superadmin only. The
# superadmin and it_admin use the module without a per-user permission (the vessel module's rule); the
# client's 'admin' gets 'edit' through User._get_perm but never sees the sources.
SOURCE_ROLES = ('superadmin',)
BYPASS_ROLES = ('superadmin', 'it_admin')
VESSEL_TIERS = {'CONFIRMED': ('Confirmed match', 'تطابق مؤكد'), 'POTENTIAL': ('Potential match', 'تطابق محتمل'),
                'POTENTIAL_MATCH': ('Potential match', 'تطابق محتمل'), 'LOW': ('Low - review', 'منخفض - للمراجعة'),
                'CLEAR': ('No match', 'لا يوجد تطابق'), 'INCOMPLETE': ('Incomplete', 'غير مكتمل')}
# a vessel hit carries the vessel module's generic label, not the dual-use one
VESSEL_LIST_LABEL = ('International approved lists', 'قوائم دولية معتمدة')
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
    from . import guidance as G
    g = G.install(db)
    db.commit()
    return {'terms': n, 'guidance': g}


# ------------------------------------------------------------------ index
def _stamp(db):
    r = db.execute("""SELECT (SELECT coalesce(string_agg(id::text, ',' ORDER BY id), '') FROM dualuse_list_versions
                              WHERE is_current) AS v,
                             (SELECT coalesce(max(id), 0) FROM dualuse_terms) AS t,
                             (SELECT count(*) FROM dualuse_terms) AS tc,
                             (SELECT coalesce(max(ar_updated_at)::text, '') FROM dualuse_items) AS a""").fetchone()
    return '%s|%s|%s|%s|%s' % (r['v'], r['t'], r['tc'], r['a'], _code_stamp())


def _code_stamp():
    """The synonyms file and the search code are part of the index: a deploy that changes them rebuilds it."""
    import hashlib
    h = hashlib.sha256()
    base = os.path.dirname(os.path.abspath(__file__))
    for name in (os.path.join('seed', 'synonyms.csv'), 'search.py', 'text.py', 'service.py'):
        try:
            with open(os.path.join(base, name), 'rb') as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()[:12]


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
    parents = {r['parent_code'] for r in rows if r['parent_code']}
    for r in rows:
        if r['level'] == 0:
            titles[(r['list_code'], r['code'])] = (r['title_en'] or r['text_en'] or '', r['title_ar'] or '')
    for r in rows:
        extra = r['extra'] or {}
        if r['list_code'] == 'cwc' and extra.get('cas'):
            continue                # the chemicals register carries every listed chemical with a CAS number
        kind = 'chemical' if r['list_code'] == 'cwc' else 'item'
        entry = titles.get((r['list_code'], r['entry_code']), ('', ''))
        # A US entry's own text is its whole list of items (each item is also its own document): index the
        # heading only, or the entry would match every word of every sub-item.
        has_children = r['level'] == 0 and r['list_code'] == 'us_ccl' and r['code'] in parents
        docs.append({'id': r['id'], 'list_code': r['list_code'], 'code': r['code'], 'entry_code': r['entry_code'],
                     'index_text': (r['title_en'] or '') if has_children else None,
                     'parent_code': r['parent_code'], 'level': r['level'], 'category': r['category'], 'group': r['grp'],
                     'title_en': r['title_en'], 'title_ar': r['title_ar'],
                     'context_en': entry[0][:300] if r['level'] else None,
                     'context_ar': entry[1][:300] if r['level'] else None,
                     'text_en': r['text_en'], 'text_ar': r['text_ar'],
                     'notes': ' '.join(r['notes_en'] or [])[:3000],
                     'hs': sorted(hs.get(r['code'], set()) | set(extra.get('hs') or [])),
                     'cas': extra.get('cas') or [], 'risk': r['risk_level'], 'reasons': r['reasons'],
                     'params': params.get(r['id'], []), 'kind': kind, 'ar_status': r['ar_status'],
                     'extra': {k: extra.get(k) for k in ('schedule', 'category_title', 'common_name', 'annex',
                                                         'complete', 'regime', 'limit_text', 'upper_text', 'cn')
                               if extra.get(k) is not None}})
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
                               'ag_precursor': r['ag_precursor'], 'item_codes': refs,
                               'listings': r['listings'] or []}})
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


def synonyms():
    """English synonym groups shipped with the pack (seed/synonyms.csv, one group per line, ';'-separated)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seed', 'synonyms.csv')
    try:
        with open(path, encoding='utf-8') as f:
            return [[x.strip() for x in r['group'].split(';') if x.strip()] for r in csv.DictReader(f)]
    except OSError:
        return []


# Every kind of list must have a current, non-empty version before anything can be screened as clear.
REQUIRED_LISTS = ('eu_annex1', 'us_ccl', 'cwc', 'chemicals', 'eu_cn_correlation', 'chpl')


def readiness(db):
    rows = {r['code']: r['n'] for r in db.execute("""SELECT l.code, coalesce(v.record_count, 0) AS n FROM dualuse_lists l
                LEFT JOIN dualuse_list_versions v ON v.list_id = l.id AND v.is_current WHERE l.is_active""").fetchall()}
    missing = [c for c in REQUIRED_LISTS if not rows.get(c)]
    return {'ready': not missing, 'missing': missing, 'counts': rows}


def _pickle_path(stamp):
    import hashlib
    import tempfile
    d = os.path.join(tempfile.gettempdir(), 'complynex_dualuse_index')
    os.makedirs(d, mode=0o700, exist_ok=True)
    if os.stat(d).st_uid != os.getuid():          # never read a cache another account could have written
        return None
    return os.path.join(d, hashlib.sha256(stamp.encode()).hexdigest()[:24] + '.pkl')


def _load_or_build(db, stamp):
    """The index of this stamp: from the cache file another worker of this server wrote, else built here
    (about 3 s) and written for the others. The cache is versioned by the stamp of the list versions,
    the dictionary and the Arabic texts."""
    import pickle
    path = None
    try:
        path = _pickle_path(stamp)
        if path and os.path.exists(path):
            with open(path, 'rb') as f:
                idx = pickle.load(f)
            if getattr(idx, 'version', None) == stamp:
                return idx
    except Exception:
        log.warning('dual-use: index cache unreadable, rebuilding', exc_info=True)
    docs, terms = load_docs(db)
    idx = SE.Index(docs, terms, version=stamp, synonyms=synonyms())
    try:
        if path:
            tmp = path + '.%d.tmp' % os.getpid()
            with open(tmp, 'wb') as f:
                pickle.dump(idx, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
            for old in os.listdir(os.path.dirname(path)):          # keep only the current stamp
                if old.endswith('.pkl') and os.path.join(os.path.dirname(path), old) != path:
                    try:
                        os.remove(os.path.join(os.path.dirname(path), old))
                    except OSError:
                        pass
    except Exception:
        log.warning('dual-use: index cache not written', exc_info=True)
    return idx


def get_index(db=None, force=False):
    """The index shared by the requests of this worker: built lazily once, rebuilt only when a list version,
    the dictionary or an Arabic text changes (the stamp is checked every 60 s). Never rolls back the
    request's transaction: the stamp query runs in a savepoint."""
    now = time.time()
    if not force and _cache['index'] is not None and now - _cache['checked'] < 60:
        return _cache['index']
    db = db or get_db()
    with _lock:
        if not force and _cache['index'] is not None and now - _cache['checked'] < 60:
            return _cache['index']
        try:
            db.execute("SAVEPOINT du_index")
            stamp = _stamp(db)
            ready = readiness(db)
            db.execute("RELEASE SAVEPOINT du_index")
        except Exception:
            try:
                db.execute("ROLLBACK TO SAVEPOINT du_index")
            except Exception:
                pass
            log.warning('dual-use: tables not available', exc_info=True)
            idx = _cache['index'] or SE.Index([], [])
            return idx
        _cache['checked'] = now
        if force or stamp != _cache['stamp'] or _cache['index'] is None:
            t0 = time.time()
            idx = _load_or_build(db, stamp)
            _cache['index'], _cache['stamp'] = idx, stamp
            log.info('dual-use index: %d entries in %.1fs', len(idx.docs), time.time() - t0)
        _cache['index'].ready = ready['ready'] and len(_cache['index'].docs) > 0
        _cache['index'].readiness = ready
    return _cache['index']


def coverage_lines(list_versions, lang='en', db=None):
    """The list versions a screening used, without naming a list: 'List versions used: #21 of 2026-11-18, ...'
    (the audit trail needs the versions; the source names stay with the superadmin)."""
    ids = [v for v in (list_versions or {}).values() if v]
    if not ids:
        return []
    db = db or get_db()
    rows = db.execute("""SELECT v.id, v.loaded_at FROM dualuse_list_versions v WHERE v.id = ANY(%s) ORDER BY v.id""",
                      (ids,)).fetchall()
    word = ('إصدارات القوائم المستخدمة', 'بتاريخ') if lang == 'ar' else ('List versions used', 'of')
    return ['%s: %s' % (word[0], ', '.join('#%s %s %s' % (r['id'], word[1], r['loaded_at'].strftime('%Y-%m-%d')
                                                          if r['loaded_at'] else '') for r in rows))]


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


# ------------------------------------------------------------------ list updates
# A list not confirmed against its publisher for this many days is flagged as stale (superadmin view).
STALE_DAYS = int(os.getenv('DUALUSE_STALE_DAYS') or 45)
RUN_STATUS = {'running': ('Running', 'قيد التنفيذ'), 'ok': ('Completed', 'اكتمل'),
              'blocked': ('Source blocked the download', 'المصدر منع التنزيل'), 'failed': ('Failed', 'فشل')}
RESULT_STATUS = {'loaded': ('New version loaded', 'تم تحميل إصدار جديد'), 'unchanged': ('No change', 'لا تغيير'),
                 'blocked': ('Blocked by the source - upload the file manually', 'منعه المصدر - ارفع الملف يدويًا'),
                 'refused': ('Refused by the safety checks', 'رفضته فحوص الأمان'), 'failed': ('Failed', 'فشل'),
                 'dry-run': ('Dry run', 'تجربة')}
MODE_LABELS = {'scheduled': ('Scheduled check', 'فحص مجدول'), 'manual': ('"Check now" button', 'زر «افحص الآن»'),
               'upload': ('Uploaded file', 'ملف مرفوع'), 'command': ('Command line', 'سطر الأوامر')}


def update_runs(db=None, limit=15):
    db = db or get_db()
    try:
        db.execute("SAVEPOINT du_runs")
        rows = db.execute("""SELECT *, (status = 'running' AND started_at < now() - interval '45 minutes') AS stuck
                             FROM dualuse_update_runs ORDER BY id DESC LIMIT %s""", (limit,)).fetchall()
        db.execute("RELEASE SAVEPOINT du_runs")
        return rows
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT du_runs")
        return []


def list_overview(db=None):
    """Per list: current version, counts, the last check that reached the publisher, the last result and the
    stale flag (no confirmed check for STALE_DAYS days)."""
    from datetime import timezone
    db = db or get_db()
    rows = [dict(r) for r in list_status(db)]
    runs = update_runs(db, 200)
    last_ok, last = {}, {}
    for run in reversed(runs):                       # oldest first: the newest result wins
        for res in run['summary'] or []:
            c = res.get('code')
            if not c:
                continue
            last[c] = dict(res, at=run['finished_at'] or run['started_at'], mode=run['mode'])
            if res.get('status') in ('loaded', 'unchanged'):
                last_ok[c] = run['finished_at'] or run['started_at']
    now = datetime.now(timezone.utc)
    for r in rows:
        ok = last_ok.get(r['code']) or r.get('loaded_at')
        r['last_ok'] = ok
        r['last'] = last.get(r['code'])
        r['age_days'] = (now - ok).days if ok else None
        r['stale'] = r['code'] != 'chemicals' and (ok is None or (now - ok).days > STALE_DAYS)
    return rows


def version_changes(vid, db=None):
    db = db or get_db()
    v = db.execute("""SELECT v.*, l.code AS list_code, l.legal_name FROM dualuse_list_versions v
                      JOIN dualuse_lists l ON l.id = v.list_id WHERE v.id = %s""", (vid,)).fetchone()
    if not v:
        return None, None
    prev = db.execute("""SELECT id, version_label, loaded_at FROM dualuse_list_versions WHERE list_id = %s AND id < %s
                         ORDER BY id DESC LIMIT 1""", (v['list_id'], vid)).fetchone()
    return v, prev


def versions(list_code, db=None, limit=12):
    db = db or get_db()
    return db.execute("""SELECT v.id, v.version_label, v.loaded_at, v.loaded_by, v.record_count, v.is_current, v.diff,
                                v.source_url FROM dualuse_list_versions v JOIN dualuse_lists l ON l.id = v.list_id
                         WHERE l.code = %s ORDER BY v.id DESC LIMIT %s""", (list_code, limit)).fetchall()


def start_check(who, db=None):
    """'Check for updates now': record a run and start the importer in the background (it downloads only from
    the official publishers). -> run id, or None when a check is already running."""
    import subprocess
    import sys
    db = db or get_db()
    if db.execute("""SELECT id FROM dualuse_update_runs WHERE status = 'running'
                     AND started_at > now() - interval '45 minutes'""").fetchone():
        return None
    rid = db.execute("""INSERT INTO dualuse_update_runs (mode, triggered_by, status) VALUES ('manual', %s, 'running')
                        RETURNING id""", ((who or '')[:80],)).fetchone()['id']
    db.commit()
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cmd = [sys.executable, os.path.join(root, 'scripts', 'dualuse', 'import_lists.py'), '--apply',
           '--run-id', str(rid), '--who', (who or 'manual')[:60]]
    _spawn(cmd, root)
    return rid


def _spawn(cmd, cwd):
    import subprocess
    subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


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


def _vessel_text(VE, items):
    """Explanation items of the vessel engine as [(english, arabic)] (older results stored plain strings)."""
    try:
        en, ar = VE.text(items, 'en'), VE.text(items, 'ar')
    except Exception:
        en = ar = [str(i) for i in items]
    return [[e or a, a or e] for e, a in zip(en, ar)][:4]


def screen_vessel(name, imo, db=None):
    """The vessel named on the bill of lading through the vessel screening engine, when that engine and its
    tables exist on this installation. Never raises: returns {} when there is nothing to screen and
    {'error': 'unavailable'} when vessel screening is not available."""
    name, imo = (name or '').strip()[:200], (imo or '').strip()[:20]
    if not (name or imo):
        return {}
    db = db or get_db()
    try:
        from screening import vessel_engine as VE
    except Exception:
        return {'name': name, 'imo': imo, 'error': 'unavailable'}
    try:
        if not db.execute("SELECT to_regclass('public.vessel_identifier') AS t").fetchone()['t']:
            return {'name': name, 'imo': imo, 'error': 'unavailable'}
        res = VE.screen_vessel(name=name or None, imo=imo or None, conn=db)
    except Exception:
        log.warning('dual-use: vessel screening failed', exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return {'name': name, 'imo': imo, 'error': 'failed'}
    hits = [{'name': h.get('name'), 'matched_name': h.get('matched_name'), 'imo': h.get('imo'),
             'flag': h.get('flag'), 'tier': h.get('tier'), 'score': h.get('score'), 'source': h.get('source'),
             'explanation': _vessel_text(VE, h.get('explanation') or [])} for h in (res.get('hits') or [])[:5]]
    return {'name': name, 'imo': imo, 'tier': res.get('tier'), 'score': res.get('score'), 'hits': hits,
            'warnings': res.get('warnings') or []}


# ------------------------------------------------------------------ screenings
def _ref():
    return 'DU-%s-%s' % (datetime.now().strftime('%y%m%d'), secrets.token_hex(3).upper())


def _cand_codes(cands):
    return sorted({(c.get('code') or '') for c in cands or []})


def _reuse(db, key, versions, res, line):
    """An earlier decision on the identical product (description, model, HS and CAS) that may be PROPOSED for
    the new line: same list versions, same suggestion, same candidate entries, and no hold or priority flag on
    the new line. The proposal is never a decision: a user confirms it under their own name."""
    if not key or res.get('hard'):
        return None
    r = db.execute("SELECT * FROM dualuse_item_master WHERE item_key = %s", (key,)).fetchone()
    if not r:
        return None
    lv = r['list_versions'] or {}
    if any(lv.get(c) != v['id'] for c, v in versions.items() if c in lv):
        return None
    initial = SC.evaluate(res['candidates'], res['hard'], res['questions'], {}, line)[0]
    if (r.get('suggested') or None) != initial or list(r.get('candidate_codes') or []) != _cand_codes(
            res['candidates']):
        return None
    return r


def _tenant():
    try:
        from database.tenancy import current_tenant_id
        return current_tenant_id()
    except Exception:
        return None


def run_lines(db, screening_id, lines, index, versions, batch=False):
    counts = {'clear': 0, 'review': 0, 'hold': 0}
    tenant = _tenant()
    for n, line in enumerate(lines, start=1):
        res = SC.screen_line(index, line)
        sug = SC.batch_suggestion(res) if batch else res['suggested']
        key = SC.line_key(line, tenant)
        prev = _reuse(db, key, versions, res, line)
        proposal = {'decision': prev['decision'], 'reason': prev['reason'], 'comment': (prev['comment'] or '')[:1000],
                    'decided_at': prev['decided_at'].isoformat() if prev['decided_at'] else None,
                    'master_id': prev['id']} if prev else None
        db.execute("""INSERT INTO dualuse_screening_lines (screening_id, line_no, description, hs_code, cas, model,
                      origin, quantity, item_key, candidates, hard_flags, questions, answers, suggested, reused_from,
                      proposal, hs_warning)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (screening_id, line.get('line_no') or n, line.get('description'), line.get('hs_code'),
                    line.get('cas'), line.get('model'), line.get('origin'), line.get('quantity'), key,
                    json.dumps(res['candidates']), json.dumps(res['hard']), json.dumps(res['questions']),
                    json.dumps(res['answers'] or {}), sug, prev['id'] if prev else None,
                    json.dumps(proposal) if proposal else None, line.get('hs_warning')))
        counts[sug] += 1
    return counts


class ListsUnavailable(RuntimeError):
    """The control lists are not loaded (or one of them is empty): nothing may be screened as clear."""
    def __init__(self, missing):
        super().__init__('control lists not loaded: %s' % ', '.join(missing))
        self.missing = missing
        self.en = 'The control lists are not loaded on this installation, so no screening can be made yet.'
        self.ar = 'قوائم الرقابة غير محمّلة في هذا النظام، لذلك لا يمكن إجراء أي فحص بعد.'


def create_screening(header, lines, user_id, batch=False, file_name=None, db=None):
    db = db or get_db()
    index = get_index(db)
    if not getattr(index, 'ready', False):
        raise ListsUnavailable((getattr(index, 'readiness', None) or {}).get('missing') or ['all'])
    versions = current_versions(db)
    sid = db.execute("""INSERT INTO dualuse_screenings (ref, kind, title, file_name, supplier, consignee, end_user, origin,
                        transport_doc, vessel_name, vessel_imo, list_versions, line_count, created_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (_ref(), 'batch' if batch else 'single', (header.get('title') or '')[:200] or None, file_name,
                      header.get('supplier'), header.get('consignee'), header.get('end_user'), header.get('origin'),
                      header.get('transport_doc'), header.get('vessel_name'), header.get('vessel_imo'),
                      json.dumps({k: v['id'] for k, v in versions.items()}), len(lines), user_id)).fetchone()['id']
    run_lines(db, sid, lines, index, versions, batch)
    _recount(db, sid)
    db.commit()
    parties = [('supplier', header.get('supplier')), ('consignee', header.get('consignee')),
               ('end_user', header.get('end_user'))]
    if any(n for _, n in parties):
        pr = screen_parties(parties, user_id, sid)
        db.execute("UPDATE dualuse_screenings SET party_results = %s WHERE id = %s", (json.dumps(pr), sid))
        db.commit()
    vr = screen_vessel(header.get('vessel_name'), header.get('vessel_imo'), db)
    if vr:
        db.execute("UPDATE dualuse_screenings SET vessel_result = %s WHERE id = %s", (json.dumps(vr, default=str), sid))
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


def save_line_guidance(line_id, category, data, db=None):
    """The user's checklist against the guidance of one category (asked / documents / red flags / notes)."""
    db = db or get_db()
    db.execute("""UPDATE dualuse_screening_lines SET guidance = coalesce(guidance, '{}'::jsonb) || jsonb_build_object(%s, %s::jsonb)
                  WHERE id = %s""", (category, json.dumps(data, ensure_ascii=False), line_id))
    db.commit()


def recent(user_id=None, limit=6, db=None):
    db = db or get_db()
    try:
        return history({}, limit=limit, db=db, user_id=user_id)[:limit]
    except Exception:
        db.rollback()
        return []


def get_line(line_id, db=None):
    db = db or get_db()
    return db.execute("SELECT * FROM dualuse_screening_lines WHERE id = %s", (line_id,)).fetchone()


def answer_line(line_id, answers, db=None):
    """Store answers to the questions and recompute the suggestion."""
    db = db or get_db()
    ln = get_line(line_id, db)
    if not ln:
        return None
    sug, state = SC.evaluate(ln['candidates'] or [], ln['hard_flags'] or [], ln['questions'] or [], answers, ln)
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
        errs.append(('Choose Clear or Hold.', 'اختر «لا مؤشرات» أو «إيقاف».'))
    if reason not in REASON_CODES:
        errs.append(('Choose a reason.', 'اختر السبب.'))
    if len((comment or '').strip()) < MIN_COMMENT:
        errs.append(('Write a comment of at least %d characters.' % MIN_COMMENT,
                     'اكتب تعليقًا لا يقل عن %d حروف.' % MIN_COMMENT))
    return errs


def _initial_suggestion(ln):
    """The suggestion of the line before any answer (what a new identical line will get)."""
    return SC.evaluate(ln['candidates'] or [], ln['hard_flags'] or [], ln['questions'] or [], {}, ln)[0]


def decide_line(line_id, decision, reason, comment, user_id, remember=False, db=None):
    db = db or get_db()
    ln = get_line(line_id, db)
    if not ln:
        return None
    now = datetime.now()
    db.execute("""UPDATE dualuse_screening_lines SET decision = %s, reason = %s, comment = %s, decided_by = %s,
                  decided_at = %s, proposal = NULL WHERE id = %s""",
               (decision, reason, comment.strip()[:4000], user_id, now, line_id))
    if remember and ln['item_key']:
        s = db.execute("SELECT list_versions FROM dualuse_screenings WHERE id = %s", (ln['screening_id'],)).fetchone()
        db.execute("""INSERT INTO dualuse_item_master (item_key, description, hs_code, cas, model, decision, reason, comment,
                      list_versions, decided_by, decided_at, screening_line_id, candidate_codes, suggested)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (item_key) DO UPDATE SET decision = EXCLUDED.decision, reason = EXCLUDED.reason,
                      comment = EXCLUDED.comment, list_versions = EXCLUDED.list_versions, decided_by = EXCLUDED.decided_by,
                      decided_at = EXCLUDED.decided_at, screening_line_id = EXCLUDED.screening_line_id,
                      candidate_codes = EXCLUDED.candidate_codes, suggested = EXCLUDED.suggested""",
                   (ln['item_key'], ln['description'], ln['hs_code'], ln['cas'], ln['model'], decision, reason,
                    comment.strip()[:4000], json.dumps(s['list_versions'] or {}), user_id, now, line_id,
                    _cand_codes(ln['candidates']), _initial_suggestion(ln)))
    s = db.execute("SELECT list_versions FROM dualuse_screenings WHERE id = %s", (ln['screening_id'],)).fetchone()
    db.execute("""INSERT INTO dualuse_decisions (line_id, screening_id, decision, reason, comment, suggested, answers,
                  list_versions, decided_by, decided_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
               (line_id, ln['screening_id'], decision, reason, comment.strip()[:4000], ln['suggested'],
                json.dumps(ln['answers'] or {}), json.dumps(s['list_versions'] or {}), user_id, now))
    _recount(db, ln['screening_id'])
    db.commit()
    return ln['screening_id']


def decisions(sid, db=None):
    """Every decision recorded in a screening, oldest first: {line_id: [rows]}."""
    db = db or get_db()
    out = {}
    for r in db.execute("""SELECT d.*, u.first_name || ' ' || u.last_name AS decided_by_name FROM dualuse_decisions d
                           LEFT JOIN users u ON u.id = d.decided_by WHERE d.screening_id = %s
                           ORDER BY d.decided_at, d.id""", (sid,)).fetchall():
        out.setdefault(r['line_id'], []).append(r)
    return out


def _recount(db, sid):
    r = db.execute("""SELECT count(*) FILTER (WHERE coalesce(decision, suggested) = 'clear') AS clear,
                             count(*) FILTER (WHERE decision IS NULL AND suggested = 'review') AS review,
                             count(*) FILTER (WHERE coalesce(decision, suggested) = 'hold') AS hold,
                             count(*) FILTER (WHERE decision IS NULL) AS open
                      FROM dualuse_screening_lines WHERE screening_id = %s""", (sid,)).fetchone()
    db.execute("UPDATE dualuse_screenings SET counts = %s, status = %s, updated_at = now() WHERE id = %s",
               (json.dumps({'clear': r['clear'], 'review': r['review'], 'hold': r['hold']}),
                'decided' if r['open'] == 0 else 'open', sid))


def history(args, limit=50, db=None, user_id=None, offset=0):
    """Screenings, newest first; user_id limits them to one user's own (view-only users)."""
    db = db or get_db()
    where, params = ['TRUE'], []
    if user_id is not None:
        where.append('s.created_by = %s')
        params.append(user_id)
    if args.get('status') in ('open', 'decided'):
        where.append('s.status = %s')
        params.append(args['status'])
    for k, op in (('date_from', '>='), ('date_to', '<')):
        v = (args.get(k) or '').strip()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', v):
            where.append('s.created_at %s %%s::date%s' % (op, " + 1" if k == 'date_to' else ''))
            params.append(v)
    q = (args.get('q') or '').strip()[:100]
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_') + '%'
        where.append("""(s.ref ILIKE %s OR s.title ILIKE %s OR s.supplier ILIKE %s OR s.consignee ILIKE %s OR EXISTS (
                         SELECT 1 FROM dualuse_screening_lines l WHERE l.screening_id = s.id
                         AND (l.description ILIKE %s OR l.model ILIKE %s OR l.hs_code ILIKE %s)))""")
        params += [like] * 7
    return db.execute(f"""SELECT s.*, u.first_name || ' ' || u.last_name AS created_by_name FROM dualuse_screenings s
                          LEFT JOIN users u ON u.id = s.created_by WHERE {' AND '.join(where)}
                          ORDER BY s.created_at DESC LIMIT %s OFFSET %s""", params + [limit + 1, offset]).fetchall()


def stats(db=None, user_id=None):
    """Landing counts; user_id limits them to one user's own screenings (view-only users)."""
    db = db or get_db()
    own = ' AND s.created_by = %(u)s' if user_id is not None else ''
    try:
        db.execute("SAVEPOINT du_stats")
        r = db.execute(f"""SELECT (SELECT count(*) FROM dualuse_screenings s WHERE TRUE{own}) AS screenings,
                    (SELECT count(*) FROM dualuse_screening_lines l JOIN dualuse_screenings s ON s.id = l.screening_id
                     WHERE l.decision IS NULL{own}) AS open_lines,
                    (SELECT count(*) FROM dualuse_screening_lines l JOIN dualuse_screenings s ON s.id = l.screening_id
                     WHERE l.decision = 'hold'{own}) AS held,
                    (SELECT count(*) FROM dualuse_item_master) AS known_items""", {'u': user_id}).fetchone()
        db.execute("RELEASE SAVEPOINT du_stats")
        return r
    except Exception:
        try:
            db.execute("ROLLBACK TO SAVEPOINT du_stats")
        except Exception:
            pass
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
# The batch runs inside the web request (no background worker for this module yet): 200 lines take a few
# seconds; a longer invoice is split by the user. Matching uses at most screening.MAX_MATCH_CHARS per line.
MAX_BATCH_LINES = 200
HEADER_SCAN = 30                          # title rows ("COMMERCIAL INVOICE", seller, buyer...) above the header
MAX_TOTAL_CHARS = 2 * 1000 * 1000          # an upload is refused beyond 2 million characters of cell text


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_XLSX_UNZIPPED = 60 * 1024 * 1024     # an .xlsx expands about 100x: refuse a "zip bomb" before parsing
MAX_COLUMNS = 50
MAX_CELL = 2000


class TableError(ValueError):
    """A batch file that cannot be used; carries the message in English and Arabic."""
    def __init__(self, en, ar):
        super().__init__(en)
        self.en, self.ar = en, ar


def _limited(rows_iter):
    """Rows with at most MAX_COLUMNS cells of at most MAX_CELL characters; stops as soon as the file is
    over the line limit (title rows + header + MAX_BATCH_LINES) or MAX_TOTAL_CHARS, so a huge or crafted file
    is never read to the end."""
    out, total = [], 0
    for r in rows_iter:
        cells = [('' if c is None else (repr(c) if isinstance(c, float) else str(c))).strip()[:MAX_CELL]
                 for c in list(r)[:MAX_COLUMNS]]
        if any(cells):
            total += sum(len(c) for c in cells)
            if total > MAX_TOTAL_CHARS:
                raise TableError('The file holds too much text (more than 2 million characters).',
                                 'الملف يحتوي على نص كثير جدًا (أكثر من مليوني حرف).')
            out.append(cells)
            if len(out) > MAX_BATCH_LINES + HEADER_SCAN + 1:
                raise TableError('At most %d lines per file: split the invoice.' % MAX_BATCH_LINES,
                                 'الحد الأقصى %d بند في الملف: قسّم الفاتورة.' % MAX_BATCH_LINES)
    return out


def header_row(rows):
    """Index of the header row: the first of the first HEADER_SCAN rows with at least two cells that name a
    known column (description, HS code, quantity ...); 0 when none does."""
    for i, r in enumerate(rows[:HEADER_SCAN]):
        if len(guess_mapping(r)) >= 2:
            return i
    return 0


def read_table(filename, data):
    """Excel / CSV bytes -> (header, rows as lists). Raises TableError (English and Arabic message)."""
    import io
    import zipfile
    name = (filename or '').lower()
    if len(data or b'') > MAX_UPLOAD_BYTES:
        raise TableError('The file is larger than 10 MB.', 'حجم الملف أكبر من 10 ميجابايت.')
    if name.endswith(('.xlsx', '.xlsm')):
        import openpyxl
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_XLSX_UNZIPPED:
                    raise TableError('The Excel file is too large once unpacked.',
                                     'ملف Excel كبير جدًا بعد فك الضغط.')
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            rows = _limited(wb.worksheets[0].iter_rows(values_only=True))
        except TableError:
            raise
        except Exception:
            raise TableError('The Excel file could not be read.', 'تعذرت قراءة ملف Excel.')
    elif name.endswith(('.csv', '.txt')):
        text = None
        for enc in ('utf-8-sig', 'cp1256', 'latin-1'):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:4000], delimiters=',;\t') if text else csv.excel
        except csv.Error:
            dialect = csv.excel
        try:
            rows = _limited(csv.reader(io.StringIO(text or ''), dialect))
        except csv.Error:
            raise TableError('The CSV file could not be read.', 'تعذرت قراءة ملف CSV.')
    else:
        raise TableError('Upload an Excel (.xlsx) or CSV file.', 'ارفع ملف Excel (.xlsx) أو CSV.')
    h = header_row(rows)
    header, rows = (rows[h] if rows else []), rows[h + 1:]
    if not rows:
        raise TableError('The file has no data rows.', 'الملف لا يحتوي على بنود.')
    if len(rows) > MAX_BATCH_LINES + 5:
        raise TableError('At most %d lines per file: split the invoice.' % MAX_BATCH_LINES,
                         'الحد الأقصى %d بند في الملف: قسّم الفاتورة.' % MAX_BATCH_LINES)
    return header, rows


def guess_mapping(header):
    from . import text as T
    m = {}
    for i, h in enumerate(header):
        hf = T.fold(h).strip()
        for field, keys in _GUESS.items():
            if field not in m and any(hf == T.fold(k) or hf.startswith(T.fold(k)) for k in keys):
                m[field] = i
    return m


_TOTAL_ROW = re.compile(r'^\s*(?:sub\s*-?\s*)?totals?\b|^\s*grand total|^\s*(?:ال)?(?:مجموع|اجمالي|إجمالي)', re.I)


def lines_from(rows, mapping):
    """Product lines of the mapped columns. Rows without a description, HS code, CAS or model, and total /
    subtotal rows, are skipped. Tariff codes read as Excel numbers are repaired (9026.2 -> 9026.20) and the
    repair is shown on the line."""
    from . import text as T
    out = []
    for n, r in enumerate(rows, start=1):
        line = {'line_no': n}
        for field, _, _ in COLUMNS:
            i = mapping.get(field)
            line[field] = (r[i] if i is not None and i < len(r) else '').strip()[:1000] or None
        if not any(line.get(f) for f in ('description', 'hs_code', 'cas', 'model')):
            continue
        if _TOTAL_ROW.match(line.get('description') or '') and not (line.get('hs_code') or line.get('cas')):
            continue
        if line.get('hs_code'):
            hs, warn = T.normalize_hs(line['hs_code'])
            if hs:
                shown = '.'.join(x for x in (hs[:4], hs[4:6], hs[6:]) if x)
                if shown.replace('.', '') != re.sub(r'\D', '', line['hs_code']):
                    line['hs_warning'] = '%s -> %s (%s)' % (line['hs_code'], shown, warn or 'normalised')
                line['hs_code'] = shown
            else:
                line['hs_warning'] = '%s: not a tariff code, ignored' % line['hs_code']
        out.append(line)
    return out
