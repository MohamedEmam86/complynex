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
Proof that the access-control migration changes nobody's access.

Default (safe on any database, read-only): for every user and every endpoint, the gate's decision from the
OLD rules (no grants) is compared with its decision from the user's stored grants (after
scripts/access_backfill.py). Any difference is listed; exit code 1 when there is one.

--http (local test databases only): additionally requests every GET route as each user twice — gate off
(app.config['ACCESS_CONTROL'] = False, i.e. only the modules' own guards) and gate on — and checks that the
gate never refuses a page the old guards served, and that every other response is identical.

    PYTHONPATH=. python scripts/access_equivalence.py [--http] [--users a@x,b@y]
"""

import argparse
import logging
import os
import sys
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DENY_LOC = {'/', '/dashboard', '/portal/', '/portal/dashboard', '/auth/login', '/auth/portal-login'}


def _get_urls(app):
    adapter = app.url_map.bind('localhost')
    out, seen = [], set()
    for r in sorted(app.url_map.iter_rules(), key=lambda r: r.endpoint):
        if 'GET' not in r.methods or r.endpoint in seen or r.endpoint in ('static', 'auth.logout', 'academy.logout',
                                                                              'prometheus_metrics'):
            continue
        vals = {a: (1 if 'Integer' in type(r._converters.get(a)).__name__ else 'x') for a in r.arguments}
        try:
            out.append((r.endpoint, adapter.build(r.endpoint, vals)))
            seen.add(r.endpoint)
        except Exception:
            continue
    return out


def _denied_before(resp, follow):
    if resp[0] in (401, 403, 404):
        return True
    if resp[0] in (301, 302) and (resp[1] in DENY_LOC or (follow and _denied_before(follow, None))):
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--http', action='store_true')
    ap.add_argument('--users', default='')
    args = ap.parse_args()
    logging.disable(logging.WARNING)
    from app import create_app
    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    from access import registry as R, service as S
    from models.user import User
    with app.app_context():
        users = [u for u in User.get_all() if not args.users or u.email in args.users.split(',')]
    endpoints = sorted({r.endpoint for r in app.url_map.iter_rules()})
    problems = 0
    for u in users:
        with app.app_context():
            old = S.compute(u, mode=R.legacy_mode(u), explicit={})
            new = S.compute(u)
        diff = [ep for ep in endpoints if S.endpoint_allowed(old, ep) != S.endpoint_allowed(new, ep)]
        mode_diff = old.mode != new.mode
        if diff or mode_diff:
            problems += 1
            print(f'DIFF user {u.id} {u.email}: mode {old.mode}->{new.mode}; {len(diff)} endpoint(s): {diff[:10]}')
    print(f'decision check: {len(users)} users x {len(endpoints)} endpoints, {problems} user(s) with a difference')
    if args.http:
        try:                       # the same pages are requested many times: rate limits would answer 429
            from extensions import limiter
            limiter.enabled = False
        except Exception:
            pass
        urls = _get_urls(app)
        same = refused = bad = 0
        for u in users:
            with app.app_context():
                sid = User.session_id_for(u.id)
            for ep, url in urls:
                res = {}
                for gate in (False, True):
                    app.config['ACCESS_CONTROL'] = gate
                    c = app.test_client()
                    with c.session_transaction() as s:
                        s['_user_id'] = sid
                        s['_fresh'] = True
                    r = c.get(url, headers={'Accept': 'text/html'})
                    loc = urlsplit(r.headers.get('Location', '')).path if r.status_code in (301, 302, 303, 307, 308) else ''
                    follow = None
                    if not gate and loc and loc not in DENY_LOC:
                        r2 = c.get(r.headers['Location'], headers={'Accept': 'text/html'})
                        follow = (r2.status_code, urlsplit(r2.headers.get('Location', '')).path)
                    res[gate] = ((r.status_code, loc), r.headers.get('X-CX-Gate', ''), follow)
                app.config['ACCESS_CONTROL'] = True
                if res[True][1] == 'denied':
                    refused += 1
                    if not _denied_before(res[False][0], res[False][2]):
                        bad += 1
                        print(f'GATE REFUSED A SERVED PAGE: {u.email} {ep} before={res[False][0]}')
                elif res[True][0] == res[False][0]:
                    same += 1
                else:
                    bad += 1
                    print(f'RESPONSE CHANGED: {u.email} {ep} {res[False][0]} -> {res[True][0]}')
        print(f'http check: {same} identical, {refused} refused by the gate (all refused before too unless listed), '
              f'{bad} problem(s)')
        problems += bad
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
