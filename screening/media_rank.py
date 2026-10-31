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
Adverse media (P4-8): one story once, the most relevant first, a fixed cap.

The news search (by the screened NAME only - owner decision) returns the same
story many times: the same URL from two queries, the same headline with a
different " - Outlet" suffix, and the same story re-published by several
outlets with slightly different headlines. Shown as-is, the analyst reads one
story ten times and a single report looks like ten.

consolidate():
  1. same URL (tracking parameters removed)            -> one article
  2. same headline once the outlet suffix is removed   -> one story
  3. near-identical headline (word overlap >= 0.8)     -> one story
  The story keeps its best-ranked copy; the other outlets are listed in
  'also_reported_by' (source + date + url) so nothing is hidden.
rank: name match in the headline, how strongly the article names the person
  (adverse_relevance: exact / strong / partial), severity of the risk terms,
  recency, and how many outlets reported it.
cap: at most MAX_HITS stories per screening (the rest counted, not shown).
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

MAX_HITS = 20
MAX_MENTIONS = 10
_TRACKING = re.compile(r'^(utm_|fbclid|gclid|mc_|ref$|ocid$|oc$|ved$|usg$)')
_NAME_RANK = {'exact': 3, 'strong': 2, 'partial': 1}


def safe_url(url):
    return str(url or '').strip().lower().startswith(('http://', 'https://'))


def canonical_url(url):
    u = str(url or '').strip()
    if not u:
        return ''
    try:
        p = urlsplit(u)
        q = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if not _TRACKING.match(k.lower())])
        host = p.netloc.lower()
        if host.startswith('www.'):
            host = host[4:]
        path = p.path.rstrip('/') or '/'
        return urlunsplit(('', host, path, q, ''))
    except Exception:
        return u.lower()


def _norm(text):
    t = str(text or '').lower()
    t = re.sub(r'[ً-ْٰـ]', '', t)
    t = re.sub('[إأآٱ]', 'ا', t).replace('ة', 'ه').replace('ى', 'ي')
    t = re.sub(r'[^a-z0-9ء-ي\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def headline_key(title, source=None):
    """Headline without the ' - Outlet' / ' | Outlet' suffix news aggregators add."""
    t = str(title or '')
    parts = re.split(r'\s+[-|–—]\s+', t)
    if len(parts) > 1:
        tail = parts[-1].strip()
        if (source and _norm(tail) == _norm(source)) or len(tail.split()) <= 4:
            t = ' '.join(parts[:-1])
    return _norm(t)


def _words(key):
    return {w for w in key.split() if len(w) > 2}


def _similar(a, b):
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    inter = len(wa & wb)
    return inter / max(1, min(len(wa), len(wb))) >= 0.8 and inter >= 3


def _date(a):
    d = a.get('published_at') or a.get('published')
    if isinstance(d, datetime):
        return d
    s = str(d or '').strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%a, %d %b %Y %H:%M:%S %Z', '%a, %d %b %Y %H:%M:%S %z'):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _age_days(a):
    d = _date(a)
    if not d:
        return None
    now = datetime.now(timezone.utc) if d.tzinfo else datetime.now()
    return max(0, (now - d).days)


def relevance(a, name=None):
    """Higher = shown first. Name strength and severity dominate; recency and
    corroboration (other outlets) break ties."""
    nm = _NAME_RANK.get(a.get('name_match'), 0)
    sev = int(a.get('severity') or 0)
    in_title = 0
    if name:
        try:
            from screening import adverse_relevance as ar
            in_title = 1 if ar.name_presence(name, a.get('title') or '') in ('exact', 'strong') else 0
        except Exception:
            in_title = 0
    age = _age_days(a)
    recency = 1.0 if age is None else (1.0 if age <= 30 else 0.8 if age <= 365 else 0.6 if age <= 5 * 365 else 0.4)
    corroboration = min(3, len(a.get('also_reported_by') or []))
    return round(nm * 10 + sev * 8 + in_title * 6 + recency * 4 + corroboration * 1.5, 2)


def consolidate(articles, name=None, cap=MAX_HITS):
    """(stories, info): de-duplicated, ranked, capped."""
    arts = [dict(a) for a in (articles or []) if isinstance(a, dict)]
    for a in arts:
        for k in ('url', 'link'):
            if a.get(k) is not None and not safe_url(a.get(k)):
                a[k] = None              # javascript:, data: ... never reach a link
        a['_rel0'] = relevance(a, name)
    arts.sort(key=lambda a: a['_rel0'], reverse=True)
    stories, by_url, by_head = [], {}, {}
    dup = 0
    for a in arts:
        cu = canonical_url(a.get('url') or a.get('link'))
        hk = headline_key(a.get('title'), a.get('source'))
        target = None
        if cu and cu in by_url:
            target = by_url[cu]
        elif hk and hk in by_head:
            target = by_head[hk]
        elif hk:
            for s in stories:
                if _similar(hk, s['_head']):
                    target = s
                    break
        if target is not None:
            dup += 1
            if cu and cu != target.get('_url'):
                target.setdefault('also_reported_by', []).append(
                    {'source': a.get('source'), 'published_at': a.get('published_at') or a.get('published'),
                     'url': a.get('url') or a.get('link')})
            if cu:
                by_url.setdefault(cu, target)
            continue
        a['_url'], a['_head'] = cu, hk
        a.setdefault('also_reported_by', [])
        stories.append(a)
        if cu:
            by_url[cu] = a
        if hk:
            by_head[hk] = a
    for s in stories:
        s['relevance'] = relevance(s, name)
        s['outlets'] = 1 + len(s.get('also_reported_by') or [])
    stories.sort(key=lambda s: (s['relevance'], str(s.get('published_at') or '')), reverse=True)
    shown = stories[:cap] if cap else stories
    for s in shown:
        for k in ('_rel0', '_url', '_head'):
            s.pop(k, None)
    return shown, {'articles': len(arts), 'stories': len(stories), 'duplicates_merged': dup,
                   'over_cap': max(0, len(stories) - len(shown))}
