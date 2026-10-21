#!/usr/bin/env python3
"""Check whether the low-Arabic-ratio pages are genuinely untranslated, or
simply dominated by Latin-script DATA (customer names, watchlist entries).
Looks at the UI chrome only: table headers, buttons, labels."""
import re
import sys

sys.path.insert(0, '/var/www/complynex')
from app import create_app

app = create_app()
AR = re.compile(r'[؀-ۿ]')

PAGES = ['/aml/customers', '/cases/', '/screening/queue', '/notifications']

CHROME = re.compile(
    r'<(th|button|label|h[1-6]|legend)\b[^>]*>(.*?)</\1>', re.S | re.I)


def main():
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['_user_id'] = __import__('models.user', fromlist=['User']).User.session_id_for(1)
            s['_fresh'] = True
        for p in PAGES:
            r = c.get(p + '?lang=ar')
            print('\n=== %s  (status %s) ===' % (p, r.status_code))
            if r.status_code >= 400:
                # try without trailing slash / common alternates
                for alt in (p.rstrip('/'), p + '/', p + 's'):
                    if alt == p:
                        continue
                    r2 = c.get(alt + '?lang=ar')
                    if r2.status_code == 200:
                        print('   (alternate URL %s -> 200)' % alt)
                        r = r2
                        break
                else:
                    continue
            html = r.get_data(as_text=True)
            texts = []
            for m in CHROME.finditer(html):
                t = re.sub(r'<[^>]+>', ' ', m.group(2))
                t = ' '.join(t.split())
                if t and len(t) > 1:
                    texts.append(t)
            ar = [t for t in texts if AR.search(t)]
            en_only = [t for t in texts
                       if not AR.search(t) and re.search(r'[A-Za-z]{3,}', t)]
            print('   UI chrome elements: %d | Arabic: %d | English-only: %d'
                  % (len(texts), len(ar), len(en_only)))
            if en_only:
                print('   English-only chrome (first 12):')
                for t in en_only[:12]:
                    print('      %r' % t[:70])
            else:
                print('   -> all UI chrome is Arabic; the low ratio is DATA '
                      '(Latin-script names), not untranslated interface.')


if __name__ == '__main__':
    main()
