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

"""The governance profile against a real database: a superadmin crawls every page the instance offers and no
rendered page (dashboard, sidebar, any other) holds an /_off/ link or a link that answers 404.

Skipped unless INSTANCE_TEST_DB names a scratch database (schema of the main database, e.g. from
pg_dump --schema-only) and POSTGRES_DB is set to it. The crawl runs in a fresh interpreter with
CX_INSTANCE_PROFILE=governance."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DBNAME = os.environ.get('INSTANCE_TEST_DB', '')
pytestmark = pytest.mark.skipif(not DBNAME or os.environ.get('POSTGRES_DB') != DBNAME,
                                reason='needs INSTANCE_TEST_DB=<scratch db> and POSTGRES_DB set to it')

CRAWL = r'''
import json, logging, re, sys
logging.disable(logging.CRITICAL)
from config import config
import app as appmod
a = appmod.create_app()
a.config.update(WTF_CSRF_ENABLED=False, TESTING=True)
from models.user import User
from database.db import get_db
EMAIL = 'cx-gov-crawl@example.test'
with a.app_context():
    u = User.get_by_email(EMAIL) or User.create_user(EMAIL, 'Str0ng!Passw0rd#x', 'Crawl', 'Super', role='superadmin',
                                                     cms_access_level='edit')
    u = User.get_by_email(EMAIL)
    db = get_db()
    db.execute('UPDATE users SET must_change_password = FALSE, mfa_required_override = FALSE WHERE id = %s', (u.id,))
    db.commit()
    uid = u.id
c = a.test_client()
with c.session_transaction() as s:
    s['_user_id'] = User.session_id_for_app(a, uid)
    s['_fresh'] = True
routes = sorted({r.rule for r in a.url_map.iter_rules() if 'GET' in r.methods and not r.arguments
                 and not r.rule.startswith(('/static', '/auth/logout', '/auth/logout-everywhere', '/metrics'))})
seen, status, off_pages, found = {}, {}, {}, {}
queue = ['/dashboard'] + routes
while queue and len(seen) < 600:
    p = queue.pop(0)
    if p in seen:
        continue
    r = c.get(p)
    seen[p] = r.status_code
    if r.status_code != 200 or r.mimetype != 'text/html':
        continue
    html = r.get_data(as_text=True)
    if '/_off/' in html:
        off_pages[p] = sorted(set(re.findall(r'/_off/[A-Za-z0-9_.]+', html)))[:10]
    for h in set(re.findall(r'(?:href|action)="(/[^"#?]*)', html)):
        if h.startswith(('/static/', '/auth/logout', '/_off/')):
            continue
        found.setdefault(h, p)
        if h not in seen:
            queue.append(h)
broken = {h: [seen[h], found.get(h)] for h in seen if seen[h] in (404, 500) and h in found}
errors = {h: v for h, v in seen.items() if v >= 500}
print('JSON' + json.dumps({'pages': len(seen), 'off_pages': off_pages, 'broken_links': broken, 'errors': errors,
                           'dashboard': seen.get('/dashboard'),
                           'security': [seen.get('/admin/security/access-review'), seen.get('/admin/security/audit-chain')]}))
'''


@pytest.fixture(scope='module')
def crawl():
    env = dict(os.environ)
    env.update(CX_INSTANCE_PROFILE='governance', PYTHONPATH=ROOT + os.pathsep + env.get('PYTHONPATH', ''))
    env.setdefault('SECRET_KEY', 'crawl-test')
    env.setdefault('FLASK_ENV', 'development')
    r = subprocess.run([sys.executable, '-c', CRAWL], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    line = [x for x in r.stdout.splitlines() if x.startswith('JSON')]
    assert line, (r.stdout[-2000:], r.stderr[-4000:])
    return json.loads(line[-1][4:])


def test_dashboard_and_every_page_have_no_off_links(crawl):
    assert crawl['dashboard'] == 200
    assert crawl['pages'] > 50
    assert crawl['off_pages'] == {}, crawl['off_pages']


def test_no_rendered_link_answers_404_or_fails(crawl):
    assert crawl['broken_links'] == {}, crawl['broken_links']
    assert crawl['errors'] == {}, crawl['errors']


def test_superadmin_reaches_the_security_pages(crawl):
    assert crawl['security'] == [200, 200]
