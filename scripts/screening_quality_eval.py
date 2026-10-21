#!/usr/bin/env python3
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
Screening quality evaluation — measures the engine the way an inspector would.

Samples real listed names (internal asset-freeze / terrorist lists, the EMLCU
list, UN names), derives the variants a customer record realistically carries
(spelling, typo, extra or missing name, Latin script, short form), adds the
national-ID cases (same ID confirms, different ID must not confirm) and random
names that are on no list (false positives), runs every case through the live
engine WITHOUT saving anything, and stores the results in
screening_quality_runs for the Screening Quality page.

    python scripts/screening_quality_eval.py            # default ~45 names
    python scripts/screening_quality_eval.py --names 20 --kind manual
"""
import argparse
import json
import logging
import os
import random
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
logging.disable(logging.WARNING)

from screening.match_intel import tokens  # noqa: E402

LAT = {'محمد': 'Mohamed', 'احمد': 'Ahmed', 'محمود': 'Mahmoud', 'علي': 'Aly', 'حسن': 'Hassan',
       'حسين': 'Hussein', 'ابراهيم': 'Ibrahim', 'عبدالله': 'Abdallah', 'السيد': 'Elsayed',
       'مصطفي': 'Moustafa', 'يوسف': 'Youssef', 'خالد': 'Khaled', 'عمر': 'Omar', 'سيد': 'Sayed',
       'اسماعيل': 'Ismail', 'صلاح': 'Salah', 'جمال': 'Gamal', 'فتحي': 'Fathy', 'سعيد': 'Said'}
CH = dict(zip('ابتثجحخدذرزسشصضطظعغفقكلمنهوية',
              ['a', 'b', 't', 'th', 'g', 'h', 'kh', 'd', 'z', 'r', 'z', 's', 'sh', 's', 'd', 't', 'z',
               'a', 'gh', 'f', 'k', 'k', 'l', 'm', 'n', 'h', 'o', 'y', 'a']))
FIRST = ['محمد', 'احمد', 'محمود', 'مصطفي', 'كريم', 'عمرو', 'هاني', 'تامر', 'وليد', 'شريف', 'مني', 'هبه', 'ساره', 'نهي', 'ريهام']
MID = ['عادل', 'سمير', 'فاروق', 'رمضان', 'صبري', 'نبيل', 'حمدي', 'جلال', 'منير', 'رفعت']
LAST = ['الشناوي', 'البنا', 'عبدالعال', 'القاضي', 'الجمال', 'الدسوقي', 'الفقي', 'رضوان', 'بدوي', 'الحفناوي']


def _plain(n):
    n = re.sub('[إأآ]', 'ا', n).replace('ة', 'ه').replace('ى', 'ي')
    return re.sub(r'\s+', ' ', re.sub(r'[^ء-ي\s]', ' ', n)).strip()


_REV = None


def _reverse_dict():
    """Arabic element -> its most common real-world Latin spelling, from the
    learned dictionary (official list transliterations)."""
    global _REV
    if _REV is None:
        _REV = {}
        try:
            from screening.match_intel import _xs_dict
            best = {}
            for lat, cands in _xs_dict().items():
                for ar, c in cands:
                    if c > best.get(ar, (0, ''))[0]:
                        best[ar] = (c, lat)
            _REV = {ar: lat for ar, (c, lat) in best.items() if c >= 3}
        except Exception:
            pass
    return _REV


def translit_crude(n):
    out = []
    for w in _plain(n).split():
        if w in LAT:
            out.append(LAT[w])
        else:
            out.append(''.join(CH.get(c, '') for c in w).capitalize())
    return ' '.join(out)


def translit(n):
    """How the name is usually written in Latin script (realistic spelling)."""
    rev = _reverse_dict()
    out = []
    for w in tokens(n):
        lat = rev.get(w)
        out.append((lat or translit_crude(w)).capitalize())
    return ' '.join(out)


def variants(n):
    toks = n.split()
    v = {'exact': n}
    sp = ' '.join(('أ' + t[1:] if t.startswith('ا') and not t.startswith('ال') and len(t) > 3 else t) for t in toks)
    sp = re.sub(r'ي(\s|$)', r'ى\1', sp)
    sp = re.sub(r'ه(\s|$)', r'ة\1', sp)
    v['spelling'] = sp
    if len(toks) >= 4:
        v['missing_name'] = ' '.join(toks[:-2] + toks[-1:])
    v['extra_name'] = n + ' محمد'
    mid = max(toks[1:-1] or toks, key=len)
    if len(mid) > 3:
        i = len(mid) // 2
        v['typo'] = n.replace(mid, mid[:i - 1] + mid[i] + mid[i - 1] + mid[i + 1:], 1)
    v['latin'] = translit(n)
    v['latin_crude'] = translit_crude(n)
    v['short_form'] = toks[0] + ' ' + toks[-1]
    return v


# stress tests reported separately, not in the headline detection rate:
# a first+family short form and a same-name/different-ID case SHOULD not be
# confirmed, and the crude letter-by-letter Latin is harsher than real life
NOT_IN_RECALL = ('id_different', 'short_form', 'latin_crude')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--names', type=int, default=45)
    ap.add_argument('--kind', default='scheduled')
    ap.add_argument('--seed', type=int, default=None)
    a = ap.parse_args()
    rnd = random.Random(a.seed if a.seed is not None else int(time.time()) // 86400)

    import psycopg2
    import psycopg2.extras
    from config import Config
    conn = psycopg2.connect(**Config.POSTGRES_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def pick(sql, k):
        cur.execute(sql)
        rows = [r for r in cur.fetchall() if len(_plain(r['n']).split()) >= 4]
        return rnd.sample(rows, min(k, len(rows)))

    per = max(1, a.names // 3)
    T = [dict(r, grp='Asset-freeze orders') for r in pick(
        "SELECT original_name n, national_id nid FROM internal_blacklist WHERE is_active=1 "
        "AND entity_type='INDIVIDUAL' AND category ILIKE 'Legal Order%%' AND original_name ~ '[ء-ي]'", per)]
    T += [dict(r, grp='Local terrorist lists') for r in pick(
        "SELECT original_name n, national_id nid FROM internal_blacklist WHERE is_active=1 "
        "AND entity_type='INDIVIDUAL' AND category='Terrorism' AND original_name ~ '[ء-ي]'", per)]
    T += [dict(r, grp='EMLCU website list') for r in pick(
        "SELECT full_name n, '' nid FROM screening_watchlist WHERE source='emlcu' AND is_active=1 "
        "AND entity_type='PERSON'", per)]

    for t in T:
        t['targets'] = {' '.join(tokens(t['n']))}
        t['jobs'] = None
    # international lists: official Arabic and Latin forms of the same person
    cur.execute("""SELECT full_name_arabic ar, full_name lat FROM screening_watchlist
                   WHERE is_active=1 AND source IN ('un','ofac','eu') AND entity_type IN ('PERSON','INDIVIDUAL')
                     AND full_name_arabic ~ '[ء-ي]' AND full_name ~ '^[A-Za-z .''-]+$'""")
    intl = [r for r in cur.fetchall() if len(tokens(r['ar'])) >= 3 and len(tokens(r['lat'])) >= 3]
    for r in rnd.sample(intl, min(max(4, per // 2), len(intl))):
        lat_var = re.sub(r'\bMohammed\b', 'Mohamed', r['lat'], flags=re.I).replace('-', ' ')
        T.append({'n': r['ar'], 'nid': None, 'grp': 'International lists (UN / OFAC / EU)',
                  'targets': {' '.join(tokens(r['ar'])), ' '.join(tokens(r['lat']))},
                  'jobs': [('intl_arabic', r['ar']), ('intl_latin', r['lat']), ('intl_latin_variant', lat_var)]})
    # companies / entities
    cur.execute("""SELECT original_name n FROM internal_blacklist WHERE is_active=1 AND entity_type='ORGANIZATION'
                   AND original_name ~ '[ء-ي]'""")
    # a company is searched by its trading name; descriptive records
    # ("... owned by the terrorist / X") are not names anyone types
    orgs = [r['n'] for r in cur.fetchall() if 2 <= len(tokens(r['n'])) <= 6 and '/' not in r['n']]
    for n in rnd.sample(orgs, min(max(3, per // 3), len(orgs))):
        bare = re.sub(r'^\s*شرك[ةه]\s+', '', n)
        T.append({'n': n, 'nid': None, 'grp': 'Companies / entities', 'targets': {' '.join(tokens(n))},
                  'jobs': [('company_exact', n), ('company_legal_form', 'شركة ' + bare + ' ش.م.م'),
                           ('company_latin', translit(n))]})

    cur.execute("SELECT coalesce(original_name, full_name) n FROM internal_blacklist WHERE is_active=1 "
                "UNION ALL SELECT full_name FROM screening_watchlist WHERE source='emlcu'")
    listed = '\n'.join(' '.join(tokens(r['n'])) for r in cur.fetchall())
    NEG = []
    while len(NEG) < 20:
        n = ' '.join([rnd.choice(FIRST), rnd.choice(MID), rnd.choice(MID), rnd.choice(LAST)])
        if ' '.join(tokens(n)) not in listed and n not in NEG:
            NEG.append(n)

    from screening.routes import get_engine
    engine = get_engine()
    # never write evaluation queries into the production metrics / history
    try:
        engine.local_engine.metrics.log = lambda *x, **k: None
    except Exception:
        pass

    def run(q, nid=None):
        t = time.time()
        try:
            r = engine.screen_person(q, include_media=False, national_id=nid)
        except Exception as ex:
            return {'err': str(ex)[:200], 'matches': [], 'status': 'ERROR', 'sec': 0}
        ms = [((m.get('watchlist_name_ar') or m.get('original_name') or ''), (m.get('full_name') or ''),
               float(m.get('match_score') or 0), (m.get('decision') or {}).get('tier'))
              for m in (r.get('matches') or [])]
        return {'status': r.get('screening_result'), 'matches': ms, 'sec': round(time.time() - t, 2)}

    cases, t0 = [], time.time()
    for t in T:
        targets = t['targets']
        if t.get('jobs'):
            vs = {}
            jobs = [(k, q, None) for k, q in t['jobs']]
        else:
            vs = variants(t['n'])
            jobs = [(k, q, None) for k, q in vs.items()]
        nid = re.sub(r'\D', '', str(t.get('nid') or ''))
        if len(nid) == 14 and vs:
            jobs.append(('id_same', vs.get('typo', t['n']), nid))
            wrong = nid[:-4] + ('%04d' % ((int(nid[-4:]) + 1111) % 10000))
            jobs.append(('id_different', t['n'], wrong))
        for k, q, qn in jobs:
            r = run(q, qn)
            score, tier = 0.0, None
            for ar, en, sc, tr in r['matches']:
                if targets & {' '.join(tokens(ar)), ' '.join(tokens(en))}:
                    if sc > score:
                        score, tier = sc, tr
            cases.append({'group': t['grp'], 'variant': k, 'query': q, 'found': score > 0, 'score': score,
                          'tier': tier, 'status': r['status'], 'sec': r['sec']})
            if len(cases) % 25 == 0:
                print(f'... {len(cases)} checks', file=sys.stderr, flush=True)
    for q in NEG:
        r = run(q)
        top = max([m[2] for m in r['matches']] or [0])
        cases.append({'group': 'Not on any list', 'variant': 'negative', 'query': q, 'found': False,
                      'score': top, 'tier': None, 'status': r['status'], 'sec': r['sec'],
                      'top_hit': (r['matches'][0][0] or r['matches'][0][1]) if r['matches'] else None})

    def rate(xs, f):
        return round(100.0 * sum(1 for x in xs if f(x)) / len(xs), 1) if xs else None

    pos = [c for c in cases if c['variant'] != 'negative']
    neg = [c for c in cases if c['variant'] == 'negative']
    by_var = {}
    for c in pos:
        by_var.setdefault(c['variant'], []).append(c)
    summary = {
        'names_tested': len(T), 'cases': len(cases),
        'recall': rate([c for c in pos if c['variant'] not in NOT_IN_RECALL], lambda c: c['found']),
        'by_variant': {k: {'n': len(v), 'found': rate(v, lambda c: c['found']),
                           'confirmed': rate(v, lambda c: c['tier'] == 'CONFIRMED')} for k, v in by_var.items()},
        'by_group': {g: rate([c for c in pos if c['group'] == g and c['variant'] not in NOT_IN_RECALL],
                             lambda c: c['found']) for g in sorted({c['group'] for c in pos})},
        'false_confirmed_rate': rate(neg, lambda c: c['status'] == 'CONFIRMED_HIT'),
        'false_alert_rate': rate(neg, lambda c: c['status'] in ('CONFIRMED_HIT', 'POTENTIAL_MATCH')),
        'id_conflict_confirmed': rate(by_var.get('id_different', []), lambda c: c['tier'] == 'CONFIRMED'),
        'avg_seconds': round(sum(c['sec'] or 0 for c in cases) / max(1, len(cases)), 2),
    }
    dur = round(time.time() - t0, 1)
    cur.execute("INSERT INTO screening_quality_runs (kind, summary, cases, duration_s) VALUES (%s,%s,%s,%s) RETURNING id",
                (a.kind, json.dumps(summary, ensure_ascii=False), json.dumps(cases, ensure_ascii=False), dur))
    rid = cur.fetchone()['id']
    conn.commit()
    print(json.dumps({'run_id': rid, **summary}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
