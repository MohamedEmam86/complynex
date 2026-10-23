# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Public (no staff login) URL prefixes that optional modules expose.

The public host (e.g. the Academy host) answers only its own pages plus the
prefixes registered here, and a CSRF failure on these paths sends the visitor
back to the form instead of to the staff login page. Modules register their
prefix at import time; the core never names a module.
"""

PUBLIC_HOST_PREFIXES = []


def register(prefix):
    prefix = '/' + prefix.strip('/') + '/'
    if prefix not in PUBLIC_HOST_PREFIXES:
        PUBLIC_HOST_PREFIXES.append(prefix)
    return prefix


def match(path):
    path = path or ''
    for p in PUBLIC_HOST_PREFIXES:
        if path.startswith(p) or path == p.rstrip('/'):
            return p
    return None
