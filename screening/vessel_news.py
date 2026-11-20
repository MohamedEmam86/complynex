# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""
News about a ship, through ComplyNex's adverse-media pipeline (screening/waterfall_scraper.py: the news sources
already configured in screening/adverse_media_config.py; no AI, no other external service).

Relevance is strict, because ship names are ordinary words: an article counts only when it carries the ship's
IMO number, or the ship's full name together with maritime context (vessel, tanker, port, cargo ... in English
or Arabic). Risk terms are read with adverse_relevance.classify. Results are cached per ship
(vessel_news_cache, NEWS_TTL_HOURS) and every failure degrades to "not available now".
"""
import asyncio
import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

NEWS_TTL_HOURS = 24
MAX_ARTICLES = 12
TOTAL_TIMEOUT = 25

_MARITIME = re.compile(
    r'\b(vessels?|ships?|tankers?|cargo|freighters?|bulk carriers?|container ships?|shipping|maritime|ports?|'
    r'harbou?r|crew|captain|master|flag(ged)?|imo|mmsi|ship-to-ship|sts|dark fleet|shadow fleet|seized|'
    r'detained|anchorage|voyage|oil cargo|crude)\b|'
    r'سفين|ناقل|ميناء|موانئ|شحن|بحري|طاقم|قبطان|ربان|حمولة|أسطول', re.I)


_SHIP_WORD = re.compile(r'\b(vessel|ship|tanker|freighter|carrier|m/?v|m/?t|mt|mv|ss|cargo ship)\b|سفينة|ناقلة|الناقلة|السفينة',
                        re.I)


def _norm(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def relevant(article, name=None, imo=None):
    """None when the article is not about this ship, else {'why': 'imo' | 'name', 'categories', 'terms'}."""
    text = _norm(' '.join(str(article.get(k) or '') for k in ('title', 'description', 'content')))
    if not text:
        return None
    why = None
    if imo and re.search(r'(?<!\d)' + re.escape(str(imo)) + r'(?!\d)', text):
        why = 'imo'
    elif name:
        n = _norm(name)
        m = re.search(r'(?<![\w])' + re.escape(n) + r'(?![\w])', text, re.I) if len(n) >= 3 else None
        if m and _MARITIME.search(text):
            if len(n.split()) >= 2:
                why = 'name'              # a name of several words: maritime context anywhere in the article
            else:
                # a one-word name is an ordinary word (ATTICA is also a region, a ferry company ...): a ship
                # word must stand right next to it ("tanker Attica", "Attica, the vessel")
                near = ' '.join(text[:m.start()].split()[-3:] + text[m.end():].split()[:3])
                if _SHIP_WORD.search(near):
                    why = 'name'
    if not why:
        return None
    try:
        from screening.adverse_relevance import classify
        c = classify(text)
    except Exception:
        c = {'categories': [], 'terms': [], 'severity': 0}
    return {'why': why, 'categories': c.get('categories') or [], 'terms': c.get('terms') or [],
            'severity': c.get('severity') or 0}


def _queries(name, imo):
    """The sources search each query as a phrase first, then loosely."""
    q = []
    if imo:
        q.append(f'IMO {imo}')
    if name:
        q.append(f'{name} vessel')
        q.append(f'{name} tanker')
    return q[:3]


def _config():
    """The adverse-media configuration plus the international English news edition (ship news is mostly
    international); everything else as configured."""
    import copy
    from screening.adverse_media_config import ADVERSE_MEDIA_CONFIG
    cfg = copy.deepcopy(ADVERSE_MEDIA_CONFIG)
    g = cfg.get('google_news') or {}
    g['editions'] = [('en-US', 'US', 'US:en'), ('ar', 'EG', 'EG:ar')]
    cfg['google_news'] = g
    return cfg


def _search(queries):
    """Run the adverse-media sources for the queries (the pipeline's async search, in its own loop)."""
    from concurrent.futures import ThreadPoolExecutor
    from screening.waterfall_scraper import WaterfallAdverseMediaScraper
    scraper = WaterfallAdverseMediaScraper(config=_config())

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(asyncio.gather(*[scraper.search(q, use_cache=False) for q in queries]))
        finally:
            loop.close()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        res = ex.submit(run).result(timeout=TOTAL_TIMEOUT)
    finally:
        ex.shutdown(wait=False)
    articles, used, failed = [], set(), set()
    for r in res or []:
        articles += r.get('articles') or []
        used.update(r.get('sources_used') or [])
        failed.update(r.get('sources_failed') or [])
    return articles, sorted(used), sorted(failed - used)


def news_for(conn, name=None, imo=None, refresh=False, search=None):
    """{'items': [...], 'sources_used', 'sources_failed', 'cached', 'fetched_at', 'error'} for one ship.
    search: callable(queries) -> (articles, used, failed), for tests."""
    key = ('IMO:' + imo) if imo else ('NAME:' + _norm(name).upper()[:70])
    from screening.vessel_store import read_rows
    if not refresh and conn is not None:
        rows = read_rows(conn, """SELECT payload, fetched_at FROM vessel_news_cache WHERE cache_key = %s
                                  AND fetched_at > now() - make_interval(hours => %s)""", (key, NEWS_TTL_HOURS))
        if rows:
            p = rows[0]['payload']
            p = p if isinstance(p, dict) else json.loads(p)
            p['cached'] = True
            return p
    try:
        articles, used, failed = (search or _search)(_queries(name, imo))
    except Exception as e:
        logger.warning(f'[VESSELS] news search failed: {e}')
        return {'items': [], 'sources_used': [], 'sources_failed': [], 'cached': False, 'error': 'unavailable'}
    items, seen = [], set()
    for a in articles:
        r = relevant(a, name=name, imo=imo)
        if not r:
            continue
        url = a.get('url') or ''
        k = url or _norm(a.get('title')).lower()
        if k in seen:
            continue
        seen.add(k)
        pub = a.get('published_at')
        items.append({'title': _norm(a.get('title'))[:300], 'url': url if url.startswith(('http://', 'https://')) else '',
                      'source': _norm(a.get('source'))[:80], 'published_at': pub.isoformat() if isinstance(pub, datetime) else str(pub or '')[:25],
                      'why': r['why'], 'categories': r['categories'], 'terms': r['terms'], 'severity': r['severity']})
    items.sort(key=lambda x: (-x['severity'], x['why'] != 'imo', x['published_at'] or ''), reverse=False)
    out = {'items': items[:MAX_ARTICLES], 'sources_used': used, 'sources_failed': failed, 'cached': False,
           'fetched_at': datetime.now().isoformat(timespec='minutes'),
           'error': None if used else 'unavailable'}
    if conn is not None and used:
        read_rows(conn, """INSERT INTO vessel_news_cache (cache_key, payload, fetched_at) VALUES (%s, %s, now())
                           ON CONFLICT (cache_key) DO UPDATE SET payload = EXCLUDED.payload, fetched_at = now()
                           RETURNING cache_key""", (key, json.dumps(out, ensure_ascii=False, default=str)))
        try:
            conn.commit()
        except Exception:
            pass
    return out
