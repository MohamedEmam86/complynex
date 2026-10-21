# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""METHOD GUARD: no state-changing endpoint may answer GET.

A GET that deletes or changes data can be triggered by a link (CSRF) and by
link pre-fetchers. Endpoints whose name says they change state must be POST-only.
Exceptions must be listed in ALLOW with a reason.
"""
import os, re, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.CRITICAL)
from app import app  # noqa: E402

VERBS = re.compile(r'(^|[._])(delete|remove|deactivate|reactivate|activate|approve|reject|toggle|'
                   r'mark_all|archive|restore|revoke|disable|enable|unlock|purge|reset)(_|$)', re.I)
ALLOW = {
    # endpoint: reason
}
bad = []
for r in app.url_map.iter_rules():
    if 'GET' in r.methods and VERBS.search(r.endpoint.split('.')[-1]) and r.endpoint not in ALLOW:
        bad.append(f'{r.rule}  ->  {r.endpoint}')
if bad:
    print('METHOD GUARD: state-changing endpoints answer GET:')
    for b in bad:
        print('  ' + b)
    print(f'METHOD GUARD: {len(bad)} problem(s)')
    sys.exit(1)
print('METHOD GUARD: clean — no state-changing GET endpoints')
