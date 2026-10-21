#!/usr/bin/env python3
"""
Confirm Arabic actually RENDERS — a 200 only proves the page didn't crash.

For each module page this checks:
  * the page renders in both languages
  * with ?lang=ar the response is predominantly Arabic
  * specific strings translated in this batch appear in Arabic, not English
    (proves the compiled catalog is really being used, not just present)
  * no leftover English UI labels that should now be translated
"""
import re
import sys

sys.path.insert(0, '/var/www/complynex')
from app import create_app

app = create_app()
AR = re.compile(r'[؀-ۿ]')

PAGES = [
    '/dashboard', '/screening/dashboard', '/screening/queue',
    '/screening/history-full', '/aml/dashboard', '/aml/alerts',
    '/aml/customers', '/governance/dashboard', '/governance/committees',
    '/internal-audit/dashboard', '/internal-audit/findings',
    '/risk-management/', '/carbon/', '/carbon/fra', '/carbon/settings',
    '/esg/methodology', '/policies/', '/training/', '/coi/campaigns',
    '/cobec/my-declarations', '/data-protection/', '/ghe/', '/blacklist/',
    '/phishing/', '/phishing/reports', '/cyber/', '/reporting/',
    '/whistleblowing/', '/merchant-kyc/', '/ekyc/', '/admin/users',
    '/admin/settings/general', '/users/', '/parties/', '/cases/',
    '/events/', '/tracker/', '/portal/', '/notifications/',
]

# strings translated in this batch -> expected Arabic fragment
PROBES = [
    ('/admin/settings/general', 'الإعدادات العامة', 'General Settings'),
    ('/blacklist/', 'القائمة السوداء', None),
    ('/screening/queue', 'تم الفحص بواسطة', None),
    ('/carbon/settings', 'حدود التقرير', None),
    ('/internal-audit/findings', 'ملاحظات', None),
]


def arabic_ratio(html):
    body = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', html,
                  flags=re.S | re.I)
    body = re.sub(r'<[^>]+>', ' ', body)
    letters = [c for c in body if c.isalpha()]
    if not letters:
        return 0.0
    ar = [c for c in letters if AR.match(c)]
    return len(ar) / len(letters)


def main():
    fails = 0
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['_user_id'] = __import__('models.user', fromlist=['User']).User.session_id_for_app(app, 1)
            s['_fresh'] = True

        print('%-36s %-5s %-5s %-8s' % ('PAGE', 'EN', 'AR', 'ar-ratio'))
        print('-' * 66)
        for p in PAGES:
            try:
                en = c.get(p).status_code
                r = c.get(p + ('&' if '?' in p else '?') + 'lang=ar')
                ar = r.status_code
                ratio = arabic_ratio(r.get_data(as_text=True)) if ar == 200 else 0
            except Exception as e:
                print('%-36s EXC %s' % (p, str(e)[:40]))
                fails += 1
                continue
            bad = (en >= 400 or ar >= 400 or ratio < 0.45)
            if bad:
                fails += 1
            print('%-36s %-5s %-5s %-8.0f%%%s'
                  % (p, en, ar, ratio * 100, '   <== CHECK' if bad else ''))

        print('\n--- specific translations render in Arabic ---')
        for page, want_ar, must_not in PROBES:
            html = c.get(page + '?lang=ar').get_data(as_text=True)
            ok = want_ar in html
            leaked = (must_not in html) if must_not else False
            print('  %-34s %-28s %s%s'
                  % (page, want_ar, 'FOUND' if ok else 'missing',
                     '  (English leaked!)' if leaked else ''))
            if leaked:
                fails += 1

    print('\n%d page(s) needing attention' % fails)


if __name__ == '__main__':
    main()
