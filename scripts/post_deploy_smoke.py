#!/usr/bin/env python3
"""
Post-deploy smoke check (Phase 0, P0-5): a fixed set of known names with the
result each one must give, run through the full live screening engine after
every deploy. A failure means the deployed engine, its indexes or the list
data are not behaving as before, even if the code tests passed.

The set is built once from the lists (it holds listed names, so it lives in
the untracked screening/data/gold folder) and then never changes unless
rebuilt on purpose:

    python scripts/post_deploy_smoke.py --build    # create smoke_v1.json
    python scripts/post_deploy_smoke.py            # run it; exit 1 on any failure
"""
import argparse
import json
import os
import random
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
import logging  # noqa: E402
logging.disable(logging.WARNING)

from screening.match_intel import tokens  # noqa: E402
from screening import match_intel as _mi  # noqa: E402

PATH = os.path.join(BASE, 'screening', 'data', 'gold', 'smoke_v1.json')
# common Egyptian names that must NOT produce a potential or confirmed hit
NEGATIVES = ['كريم عادل سمير الشناوي', 'مني فاروق رفعت البنا', 'تامر نبيل حمدي القاضي', 'هبه جلال منير الدسوقي',
             'وليد رمضان صبري الفقي', 'Karim Adel Samir Elshennawy', 'Mona Farouk Refaat Elbanna',
             'Tamer Nabil Hamdy Elkady', 'ساره عادل سمير رضوان', 'شريف منير رفعت بدوي']


def build():
    import psycopg2
    import psycopg2.extras
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    rnd = random.Random(20261029)
    cases = []

    def pick(sql, k, label):
        cur.execute(sql)
        rows = [r for r in cur.fetchall() if r['n'] and len(tokens(r['n'])) >= 3]
        for r in rnd.sample(rows, min(k, len(rows))):
            cases.append({'query': r['n'], 'expect': 'hit', 'target': ' '.join(tokens(r['n'])), 'group': label})
    pick("SELECT original_name n FROM internal_blacklist WHERE is_active=1 AND category ILIKE 'Legal Order%%' "
         "AND original_name ~ '[ء-ي]'", 4, 'asset-freeze order')
    pick("SELECT original_name n FROM internal_blacklist WHERE is_active=1 AND category='Terrorism' "
         "AND upper(entity_type) IN ('INDIVIDUAL','PERSON') AND original_name ~ '[ء-ي]'", 4, 'local terrorist list')
    pick("SELECT full_name n FROM screening_watchlist WHERE is_active=1 AND source='emlcu' AND entity_type='PERSON'",
         3, 'EMLCU list')
    pick("SELECT full_name n FROM screening_watchlist WHERE is_active=1 AND source='un' "
         "AND entity_type IN ('PERSON','INDIVIDUAL')", 3, 'UN list (Latin)')
    pick("SELECT full_name n FROM screening_watchlist WHERE is_active=1 AND source='ofac' "
         "AND entity_type IN ('PERSON','INDIVIDUAL')", 3, 'OFAC (Latin)')
    pick("SELECT full_name n FROM screening_watchlist WHERE is_active=1 AND source IN ('un','eu') "
         "AND entity_type IN ('ENTITY','ORGANIZATION')", 2, 'UN / EU entity')
    for n in NEGATIVES:
        cases.append({'query': n, 'expect': 'no_potential', 'group': 'not on any list'})
    json.dump({'version': 1, 'built': time.strftime('%Y-%m-%d'), 'cases': cases},
              open(PATH, 'w'), ensure_ascii=False, indent=1)
    print(f'smoke set written: {len(cases)} cases -> {PATH}')


def run():
    data = json.load(open(PATH))
    from screening.routes import get_engine
    engine = get_engine()
    # never log smoke checks as real screenings: refuse to run if that cannot be switched off
    try:
        if not callable(getattr(engine.local_engine.metrics, 'log', None)):
            raise AttributeError('metrics.log not found (renamed?)')
        engine.local_engine.metrics.log = lambda *x, **k: None
    except Exception as ex:
        print(f'smoke: cannot disable screening metrics logging ({ex}) - not running')
        sys.exit(1)
    fails, t0 = [], time.time()
    for c in data['cases']:
        try:
            r = engine.screen_person(c['query'], include_media=False)
        except Exception as ex:
            fails.append((c, f'error: {str(ex)[:120]}'))
            continue
        ms = r.get('matches') or []
        if c['expect'] == 'hit':
            names = {' '.join(tokens(m.get('watchlist_name_ar') or m.get('original_name') or '')) for m in ms} | \
                    {' '.join(tokens(m.get('full_name') or '')) for m in ms}
            if c['target'] not in names:
                fails.append((c, 'listed name not returned'))
        else:
            top = max([float(m.get('match_score') or 0) for m in ms] or [0])
            if top >= _mi.POTENTIAL:
                fails.append((c, f'unexpected hit at {top:.0f}'))
    n = len(data['cases'])
    print(f'smoke: {n - len(fails)}/{n} passed in {time.time() - t0:.0f}s')
    for c, why in fails:
        print(f"  FAIL [{c['group']}] {why}")
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', action='store_true')
    build() if ap.parse_args().build else run()
