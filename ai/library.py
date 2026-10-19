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
Local regulatory-library index: the organisation's policies, the
requirements of the regcontrols library (any framework, any regulator) and
circulars submitted through the intake (channel 'circular') split into
paragraphs, with an optional embedding vector from the configured LOCAL
embeddings provider.

Retrieval: embedding cosine when both the question and the paragraph have a
vector, otherwise rules (character n-grams + IDF-weighted word coverage,
ai/text.py). An answer is ONLY ever the cited paragraphs; a local model may
summarise them (and must cite at least one), never answer without them.
When no paragraph passes the threshold the answer is "no source found".
"""

import logging
import math
import os
import re
from collections import Counter
from datetime import datetime

from database.db import get_db

from . import text as T
from .providers import ProviderError, cosine

logger = logging.getLogger(__name__)

MIN_PARA, MAX_PARA = 60, 1200
_INACTIVE_POLICY = ('draft', 'retired', 'archived', 'rejected', 'superseded', 'withdrawn', 'inactive')
_CACHE = {'sig': None, 'rows': [], 'idf': {}}


# ------------------------------------------------------------------ paragraphs
def _strip_html(s):
    return re.sub(r'[ \t]+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'</(p|div|li|h\d)>|<br\s*/?>', '\n', s or '', flags=re.I)))


def _sentences(s, n):
    out, cur = [], ''
    parts = []
    for part in re.split(r'(?<=[.!?؟。])\s+', s):
        while len(part) > n:                        # no sentence end: cut at a space before n
            cut = part.rfind(' ', 0, n)
            cut = cut if cut > n // 2 else n
            parts.append(part[:cut])
            part = part[cut:].strip()
        parts.append(part)
    for part in parts:
        if cur and len(cur) + len(part) > n:
            out.append(cur.strip())
            cur = ''
        cur += part + ' '
    if cur.strip():
        out.append(cur.strip())
    return out


def paragraphs(text, min_len=MIN_PARA, max_len=MAX_PARA):
    """Split a text into citable paragraphs (blank lines / numbered items), merge short ones, cut long ones."""
    text = (text or '').replace('\r', '')
    blocks = []
    for b in re.split(r'\n\s*\n', text):
        b = b.strip()
        if not b:
            continue
        if len(b) > max_len:
            lines = [ln.strip() for ln in b.split('\n') if ln.strip()]
            for ln in lines:
                blocks.extend(_sentences(ln, max_len) if len(ln) > max_len else [ln])
        else:
            blocks.append(re.sub(r'[ \t]*\n[ \t]*', '\n', b))
    out, cur = [], ''
    for b in blocks:
        if cur and (len(cur) >= min_len or len(cur) + len(b) > max_len):
            out.append(cur)
            cur = ''
        cur = f'{cur}\n{b}'.strip() if cur else b
    if cur:
        if out and len(cur) < min_len and len(out[-1]) + len(cur) <= max_len:
            out[-1] = f'{out[-1]}\n{cur}'
        else:
            out.append(cur)
    return out


# ------------------------------------------------------------------ sources
def _cols(db, table):
    try:
        if not db.execute("SELECT to_regclass(%s) AS t", (table,)).fetchone()['t']:
            return set()
        return {r['column_name'] for r in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = current_schema()",
            (table,)).fetchall()}
    except Exception:
        db.rollback()
        return set()


def _file_text(rel_path):
    """Text of an uploaded file under the app root (policy document, circular attachment)."""
    from flask import current_app
    from . import extract
    if not rel_path:
        return ''
    root = os.path.realpath(current_app.root_path)
    p = os.path.realpath(os.path.join(root, rel_path))
    if not p.startswith(root + os.sep) or not os.path.isfile(p) or os.path.getsize(p) > 15 * 1024 * 1024:
        return ''
    with open(p, 'rb') as fh:
        return extract.extract(os.path.basename(p), fh.read())['text']


def policy_docs(db):
    cols = _cols(db, 'policies')
    if not {'id', 'policy_name'} <= cols:
        return []
    sel = ', '.join(c for c in ('id', 'policy_number', 'policy_name', 'description', 'content', 'attachment_path', 'status',
                                'regulatory_reference') if c in cols)
    out = []
    for r in db.execute(f"SELECT {sel} FROM policies ORDER BY id").fetchall():
        r = dict(r)
        if (r.get('status') or '').strip().lower() in _INACTIVE_POLICY:
            continue
        body = '\n\n'.join(x for x in (r.get('description'), _strip_html(r.get('content'))) if x)
        try:
            body = '\n\n'.join(x for x in (body, _file_text(r.get('attachment_path'))) if x)
        except Exception:
            logger.warning('library: could not read the document of policy %s', r['id'], exc_info=True)
        ref = ' · '.join(x for x in (r.get('policy_number'), r.get('regulatory_reference')) if x)
        out.append({'source_type': 'policy', 'source_id': r['id'], 'ref_label': ref or None, 'title': r['policy_name'],
                    'text': body or r['policy_name'], 'endpoint': 'policies.view_policy', 'endpoint_args': {'id': r['id']}})
    return out


def requirement_docs(db):
    if not _cols(db, 'rc_requirements'):
        return []
    out = []
    for f in db.execute("SELECT id, code, name_en, name_ar, description FROM rc_frameworks WHERE is_active ORDER BY id").fetchall():
        if f['description']:
            out.append({'source_type': 'framework', 'source_id': f['id'], 'ref_label': f['code'], 'title': f['name_en'],
                        'text': f['description'], 'endpoint': 'regcontrols.framework_detail',
                        'endpoint_args': {'framework_id': f['id']}})
    for q in db.execute("""SELECT q.id, q.ref_code, q.title_en, q.title_ar, q.text_en, q.text_ar, q.legal_reference,
                                  f.id AS framework_id, f.code AS framework
                           FROM rc_requirements q JOIN rc_frameworks f ON f.id = q.framework_id
                           WHERE f.is_active ORDER BY f.code, q.sort_order, q.ref_code""").fetchall():
        body = '\n\n'.join(x for x in (q['text_en'], q['text_ar'], q['legal_reference']) if x) or q['title_en']
        out.append({'source_type': 'requirement', 'source_id': q['id'], 'ref_label': f"{q['framework']} {q['ref_code']}",
                    'title': ' / '.join(x for x in (q['title_en'], q['title_ar']) if x), 'text': body,
                    'endpoint': 'regcontrols.framework_detail', 'endpoint_args': {'framework_id': q['framework_id']}})
    return out


def circular_docs(db):
    """Circulars submitted to the Copilot (channel 'circular') and their attachments."""
    out = []
    try:
        rows = db.execute("""SELECT id, subject, body FROM ai_intake_items WHERE channel = 'circular' AND status <> 'rejected'
                             ORDER BY id""").fetchall()
        files = {}
        for a in db.execute("""SELECT record_id, file_path FROM generic_attachments WHERE module = 'ai' AND record_type = 'ai_intake'
                               AND coalesce(is_deleted, 0) = 0""").fetchall():
            files.setdefault(a['record_id'], []).append(a['file_path'])
    except Exception:
        db.rollback()
        return []
    for r in rows:
        body = r['body'] or ''
        if not body.strip() or body.strip() == '(document)':
            body = '\n\n'.join(filter(None, (_file_text(p) for p in files.get(r['id'], []))))
        if body.strip():
            out.append({'source_type': 'circular', 'source_id': r['id'], 'ref_label': f"#{r['id']}",
                        'title': r['subject'] or T.excerpt(body, 80), 'text': body, 'endpoint': 'ai.intake_review',
                        'endpoint_args': {'item_id': r['id']}})
    return out


SOURCES = (policy_docs, requirement_docs, circular_docs)


# ------------------------------------------------------------------ build
def rebuild(db=None, embedder=None):
    """(Re)build the whole index. → stats."""
    import json
    db = db or get_db()
    docs, errors = [], []
    for fn in SOURCES:
        try:
            docs += fn(db)
        except Exception as e:
            db.rollback()
            logger.exception('library: source %s failed', fn.__name__)
            errors.append(f'{fn.__name__}: {e.__class__.__name__}')
    rows = []
    for d in docs:
        for i, p in enumerate(paragraphs(d['text']), start=1):
            rows.append(dict(d, para_no=i, body=p))
    vectors, model = [None] * len(rows), None
    if embedder is not None and rows:
        try:
            for s in range(0, len(rows), 32):
                batch = rows[s:s + 32]
                vectors[s:s + len(batch)] = embedder.embed([f"{r['title'] or ''}\n{r['body']}" for r in batch])
            model = embedder.model
        except (ProviderError, Exception) as e:
            vectors = [None] * len(rows)
            errors.append(f'embeddings: {str(e)[:120]}')
    db.execute("DELETE FROM ai_library_paragraphs")
    now = datetime.now()
    for r, v in zip(rows, vectors):
        db.execute("""INSERT INTO ai_library_paragraphs (source_type, source_id, para_no, ref_label, title, body, endpoint,
                      endpoint_args, embedding, embed_model, indexed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (source_type, source_id, para_no) DO NOTHING""",
                   (r['source_type'], r['source_id'], r['para_no'], (r['ref_label'] or '')[:200] or None, (r['title'] or '')[:400] or None,
                    r['body'], r['endpoint'], json.dumps(r['endpoint_args']), [float(x) for x in v] if v else None,
                    model if v else None, now))
    db.commit()
    _CACHE['sig'] = None
    by = Counter(d['source_type'] for d in docs)
    return {'documents': dict(by), 'paragraphs': len(rows), 'embedded': sum(1 for v in vectors if v), 'errors': errors,
            'indexed_at': now.isoformat(timespec='seconds')}


def status(db=None):
    db = db or get_db()
    try:
        r = db.execute("""SELECT count(*) AS n, count(embedding) AS embedded, max(indexed_at) AS indexed_at,
                          count(DISTINCT (source_type, source_id)) AS documents FROM ai_library_paragraphs""").fetchone()
        return dict(r)
    except Exception:
        db.rollback()
        return {'n': 0, 'embedded': 0, 'indexed_at': None, 'documents': 0}


# ------------------------------------------------------------------ retrieval
def _load(db):
    sig = db.execute("SELECT count(*) AS n, max(indexed_at) AS t FROM ai_library_paragraphs").fetchone()
    sig = (sig['n'], sig['t'])
    if _CACHE['sig'] != sig:
        rows = [dict(r) for r in db.execute("""SELECT id, source_type, source_id, para_no, ref_label, title, body, endpoint,
                                                endpoint_args, embedding FROM ai_library_paragraphs ORDER BY id""").fetchall()]
        df = Counter()
        for r in rows:
            full = f"{r['title'] or ''}\n{r['body']}"
            r['_ng'] = T.ngrams(full)
            r['_tok'] = set(T.tokens(full))
            df.update(r['_tok'])
        n = max(1, len(rows))
        _CACHE.update(sig=sig, rows=rows, idf={t: math.log(1 + n / c) for t, c in df.items()})
    return _CACHE['rows'], _CACHE['idf']


def _has(tokset, t):
    return t in tokset or (len(t) >= 4 and any(x.startswith(t) or (len(x) >= 4 and t.startswith(x)) for x in tokset))


def rules_score(question, row, idf):
    qt = [t for t in dict.fromkeys(T.tokens(question))]
    if not qt:
        return 0.0
    default = max(idf.values()) if idf else 1.0
    w = {t: idf.get(t, default) for t in qt}
    cov = sum(w[t] for t in qt if _has(row['_tok'], t)) / sum(w.values())
    return round(0.5 * T.cosine(T.ngrams(question), row['_ng']) + 0.5 * cov, 3)


def search(question, k=3, db=None, embedder=None, cfg=None):
    """Paragraphs that pass the threshold, best first: [{id, source_type, ref_label, title, body, url, score, by}]."""
    from . import settings
    from .handlers import _url
    db = db or get_db()
    cfg = cfg or settings.get_config()
    try:
        rows, idf = _load(db)
    except Exception:
        db.rollback()
        return []
    if not rows or not (question or '').strip():
        return []
    qe = None
    if embedder is not None and any(r['embedding'] for r in rows):
        try:
            qe = embedder.embed([question])[0]
        except (ProviderError, Exception):
            qe = None
    hits = []
    for r in rows:
        rs = rules_score(question, r, idf)
        es = cosine(qe, r['embedding']) if qe is not None and r['embedding'] else None
        ok = es >= cfg['ai.cite_min_embedding'] if es is not None else rs >= cfg['ai.cite_min_score']
        if ok:
            hits.append((es if es is not None else rs, rs, es, r))
    hits.sort(key=lambda h: -h[0])
    out, seen = [], Counter()
    for score, rs, es, r in hits:
        key = (r['source_type'], r['source_id'])
        if seen[key] >= 2:                     # at most two paragraphs per document: room for other sources
            continue
        seen[key] += 1
        args = r['endpoint_args'] or {}
        out.append({'id': r['id'], 'source_type': r['source_type'], 'source_id': r['source_id'], 'para_no': r['para_no'],
                    'ref_label': r['ref_label'], 'title': r['title'], 'body': r['body'], 'score': round(score, 3),
                    'by': 'embeddings' if es is not None else 'rules', 'endpoint': r['endpoint'], 'endpoint_args': args,
                    'url': _url(r['endpoint'], **args) if r['endpoint'] else None})
        if len(out) >= k:
            break
    return out


def with_urls(lib):
    """Resolve the source links in the current request (a background job has no request to build URLs in)."""
    from .handlers import _url
    for c in (lib or {}).get('citations') or []:
        if not c.get('url') and c.get('endpoint'):
            c['url'] = _url(c['endpoint'], **(c.get('endpoint_args') or {}))
    return lib


def answer(question, lang='en', gen=None, embedder=None, db=None, k=3):
    """→ ({'status': 'cited'|'no_source', 'citations': [...], 'answer': str|None}, meta).
    Without a citation there is no answer."""
    from . import tasks
    from .providers import RulesOnly
    gen = gen or RulesOnly()
    cites = search(question, k=k, db=db, embedder=embedder)
    if not cites:
        return {'status': 'no_source', 'citations': [], 'answer': None, 'question': question}, tasks._meta(gen, 'guidance')
    res, meta = tasks.summarise_citations(question, cites, lang, gen)
    used = set(res.get('cited') or [])
    for c in cites:
        c['used'] = c['id'] in used if used else True
    return {'status': 'cited', 'citations': cites, 'answer': res.get('answer'), 'question': question}, meta
