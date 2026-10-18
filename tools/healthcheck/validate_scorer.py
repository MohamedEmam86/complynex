#!/usr/bin/env python3
"""
Scorer regression harness.

Run BEFORE and AFTER the scorer fix. Two sets that must move in opposite
directions:

  TRUE POSITIVES  — names that ARE on a list. These must still score high.
                    Pulled live from internal_blacklist so they are guaranteed
                    to be real listed entities, plus known sanctions figures.

  FALSE POSITIVES — the merchant/list pairs confirmed as wrong by inspection.
                    These must drop below 85.

Any true positive that falls below 85 after the fix is a regression and must
block the change.

Usage: validate_scorer.py before|after
"""
import json
import os
import sys

sys.path.insert(0, '/var/www/complynex')
os.chdir('/var/www/complynex')
from dotenv import load_dotenv
load_dotenv('/var/www/complynex/.env')

from app import create_app
from database.db import get_db

app = create_app()
LABEL = sys.argv[1] if len(sys.argv) > 1 else 'run'
OUT = '/tmp/scorer_%s.json' % LABEL

# merchant names whose top match was confirmed WRONG by inspection
FALSE_POSITIVES = [
    'احمد صبره احمد عواجه',
    'احمد نظمى محمد',
    'اشرف محمد احمد منصور',
    'خالد مصطفى امين محمد',
    'احمد محمد احمد محمد العجمى',
    'احمد محمد محمد شافع',
    'السيد جمعة السيد جمعة',
    ',عبد الله محمد علي توفيق',
    'احمد اسماعيل حسين',
    'احمد حافظ عبده حافظ',
]

# well-known sanctioned/PEP figures — must keep matching
KNOWN = [
    'حسني مبارك',
    'Osama Bin Laden',
    'Saddam Hussein',
    'Bashar al-Assad',
]


def main():
    with app.app_context():
        db = get_db()
        # real listed entities, taken verbatim from the list itself
        rows = db.execute("""
            SELECT original_name FROM internal_blacklist
             WHERE confirmation_type = 'OFFICIAL_LIST'
               AND original_name <> ''
               AND length(original_name) > 12
             ORDER BY id LIMIT 12
        """).fetchall()
        true_pos = [dict(r)['original_name'] for r in rows]

    results = {'true_positives': [], 'false_positives': [], 'known': []}

    with app.app_context():
        from screening.routes import get_engine
        eng = get_engine()

        def screen(n):
            try:
                res = eng.screen_person(name=n, entity_type='INDIVIDUAL',
                                        include_media=False)
                ms = res.get('matches') or []
                top = max((m.get('match_score', 0) for m in ms), default=0)
                n85 = len([m for m in ms if m.get('match_score', 0) >= 85])
                best = max(ms, key=lambda m: m.get('match_score', 0)) if ms else {}
                return (round(top, 1), len(ms), n85,
                        (best.get('original_name') or best.get('full_name') or '')[:40])
            except Exception as e:
                return (-1, 0, 0, str(e)[:40])

        print('=== TRUE POSITIVES (verbatim listed names — must stay >=85) ===')
        print('%-44s %6s %7s %6s' % ('NAME', 'TOP', 'matches', '>=85'))
        for n in true_pos:
            top, cnt, n85, best = screen(n)
            results['true_positives'].append(
                {'name': n, 'top': top, 'matches': cnt, 'ge85': n85})
            flag = '' if top >= 85 else '   <== REGRESSION'
            print('%-44s %6s %7s %6s%s' % (n[:44], top, cnt, n85, flag))

        print('\n=== KNOWN SANCTIONED / PEP FIGURES (must stay >=85) ===')
        for n in KNOWN:
            top, cnt, n85, best = screen(n)
            results['known'].append(
                {'name': n, 'top': top, 'matches': cnt, 'ge85': n85,
                 'best': best})
            flag = '' if top >= 85 else '   <== REGRESSION'
            print('%-44s %6s %7s %6s  %s%s'
                  % (n[:44], top, cnt, n85, best[:30], flag))

        print('\n=== FALSE POSITIVES (must drop BELOW 85) ===')
        print('%-44s %6s %7s %6s %s' % ('MERCHANT', 'TOP', 'matches', '>=85',
                                        'TOP MATCH'))
        for n in FALSE_POSITIVES:
            top, cnt, n85, best = screen(n)
            results['false_positives'].append(
                {'name': n, 'top': top, 'matches': cnt, 'ge85': n85,
                 'best': best})
            flag = '   <== still flagging' if top >= 85 else ''
            print('%-44s %6s %7s %6s %s%s'
                  % (n[:44], top, cnt, n85, best[:30], flag))

    tp_ok = sum(1 for r in results['true_positives'] if r['top'] >= 85)
    kn_ok = sum(1 for r in results['known'] if r['top'] >= 85)
    fp_bad = sum(1 for r in results['false_positives'] if r['top'] >= 85)
    print('\nSUMMARY [%s]' % LABEL)
    print('  true positives still matching : %d / %d'
          % (tp_ok, len(results['true_positives'])))
    print('  known figures still matching  : %d / %d'
          % (kn_ok, len(results['known'])))
    print('  false positives still >=85    : %d / %d'
          % (fp_bad, len(results['false_positives'])))

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False)
    print('  written %s' % OUT)


if __name__ == '__main__':
    main()
