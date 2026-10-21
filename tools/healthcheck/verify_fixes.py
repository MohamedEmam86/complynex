#!/usr/bin/env python3
"""Verify the specific URLs the user reported, plus the ones the crawler
flagged, in BOTH languages. Run as the service user, not root."""
import sys

sys.path.insert(0, '/var/www/complynex')
from app import create_app  # noqa: E402

app = create_app()

URLS = [
    # --- reported by the user -----------------------------------------
    ('/governance/committee/3/charter', 'user-reported 404'),
    ('/governance/committee', 'user-reported 404'),
    ('/governance/committees', 'canonical listing'),
    ('/carbon/fra', 'user-reported 500'),
    ('/phishing/', 'user-reported error'),
    ('/internal-audit/findings/6', 'user-reported (evidence upload)'),
    # --- found by the crawler -----------------------------------------
    ('/carbon/fra/report', 'template was unreadable'),
    ('/carbon/settings', 'template was unreadable'),
    ('/phishing/reports', 'template was unreadable'),
    ('/phishing/campaign/new', 'template was unreadable'),
    ('/phishing/caught', '500: CSS wrapped in gettext'),
    ('/coi/declarations/1/mitigation/create', "500: {% set _ %} shadowing"),
    ('/risk-management/register/1/link-source', '500: no null guard'),
    ('/risk-management/register/1/treatments/new', '500: no null guard'),
    ('/users/1/avatar', '500: missing model attribute'),
    # --- null-guard regression checks: ids that do NOT exist ----------
    ('/governance/committee/999999/members', 'guard: missing committee'),
    ('/governance/meeting/summary/999999', 'guard: missing meeting'),
    ('/governance/fit-proper/add/999999', 'guard: missing member'),
    ('/governance/skills/assess/999999', 'guard: missing member'),
    ('/internal-audit/projects/999999/findings/new', 'guard: missing project'),
    ('/internal-audit/findings/999999/link-risk', 'guard: missing finding'),
    ('/risk-management/register/999999/link-source', 'guard: missing risk'),
    ('/risk-management/register/999999/treatments/new', 'guard: missing risk'),
    ('/risk-management/controls/999999/test', 'guard: missing control'),
    ('/training/course/999999/quiz', 'guard: missing course'),
]


def main():
    fails = 0
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['_user_id'] = __import__('models.user', fromlist=['User']).User.session_id_for_app(app, 1)
            s['_fresh'] = True
        print('%-46s %-5s %-5s  %s' % ('URL', 'EN', 'AR', 'NOTE'))
        print('-' * 100)
        for url, note in URLS:
            codes = []
            for suffix in ('', '?lang=ar'):
                try:
                    r = c.get(url + suffix, follow_redirects=False)
                    codes.append(r.status_code)
                except Exception as e:
                    codes.append('EXC:' + type(e).__name__)
            bad = any(str(x).startswith('5') or x == 404 for x in codes)
            if bad:
                fails += 1
            print('%-46s %-5s %-5s  %s%s' %
                  (url, codes[0], codes[1], note, '   <== STILL BROKEN' if bad else ''))
    print('\n%d of %d URLs still failing' % (fails, len(URLS)))


if __name__ == '__main__':
    main()
