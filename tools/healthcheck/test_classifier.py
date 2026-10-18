#!/usr/bin/env python3
"""Test the new classifier against real production matches and show what
changes versus the old template logic."""
import json
import sys
from collections import Counter

sys.path.insert(0, '/var/www/complynex')
from app import create_app
from database.db import get_db
from screening.match_classifier import classify_match

app = create_app()


def old_logic(m):
    """Reproduction of the template's previous substring classification."""
    mtype = str(m.get('list_type') or '').lower()
    src = str(m.get('source') or '').lower()
    dataset = str(m.get('dataset') or '').lower()
    if 'pep' in mtype or 'politici' in mtype or 'peps' in dataset or 'pep' in src:
        return 'PEP'
    if ('sanction' in mtype or 'terror' in mtype or 'watch' in mtype
            or 'ofac' in src or 'un_consolidated' in src or 'hmt' in src
            or 'eu_sanctions' in src or 'blacklist' in src):
        return 'SANCTIONS'
    return 'SANCTIONS'   # template fallback also dumped into sanctions


with app.app_context():
    db = get_db()
    rows = db.execute("SELECT id, screened_name, matches FROM screening_results "
                      "WHERE total_matches_found > 0 ORDER BY id DESC "
                      "LIMIT 60").fetchall()

changed = []
tally_old, tally_new = Counter(), Counter()
total = 0

for row in rows:
    m = row['matches']
    try:
        matches = json.loads(m) if isinstance(m, str) else m
    except Exception:
        continue
    for x in matches or []:
        if not isinstance(x, dict):
            continue
        total += 1
        o, n = old_logic(x), classify_match(x)
        tally_old[o] += 1
        tally_new[n] += 1
        if o != n:
            changed.append((row['id'], x.get('full_name', '')[:30],
                            x.get('list_type'), x.get('dataset'),
                            x.get('category'), str(x.get('topics'))[:28], o, n))

print('matches examined: %d (across %d results)' % (total, len(rows)))
print('\nOLD classification:', dict(tally_old))
print('NEW classification:', dict(tally_new))
print('\nreclassified: %d' % len(changed))
print('\n%-6s %-30s %-14s %-18s %-30s %-28s %s' %
      ('res', 'name', 'list_type', 'dataset', 'category', 'topics', 'old->new'))
print('-' * 165)
for c in changed[:40]:
    print('%-6s %-30s %-14s %-18s %-30s %-28s %s->%s' %
          (c[0], c[1], str(c[2])[:14], str(c[3])[:18],
           str(c[4])[:30], c[5], c[6], c[7]))

print('\n--- sanity: nothing sanctioned became a PEP by mistake ---')
bad = [c for c in changed if c[6] == 'SANCTIONS' and c[7] == 'PEP'
       and ('sanction' in str(c[5]).lower() or 'terror' in str(c[5]).lower())]
print('suspicious downgrades:', len(bad))
for b in bad[:10]:
    print('   ', b)
