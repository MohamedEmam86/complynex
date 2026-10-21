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
Elasticsearch client for ComplyNex screening engine.
Handles connection, index management, and candidate retrieval.
All connection details from .env — no hardcoded values.
"""
from elasticsearch import Elasticsearch
import os

def _load_credentials():
    """Scripts and timers may start without the app's environment: read the
    Elasticsearch credentials from the app's .env when they are not set."""
    if os.getenv('ES_PASSWORD'):
        return
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                key, _, val = line.strip().partition('=')
                if key in ('ES_USERNAME', 'ES_PASSWORD', 'ES_HOST', 'ES_PORT') and val:
                    os.environ.setdefault(key, val.strip().strip('"').strip("'"))
    except OSError:
        pass


def get_es_client(timeout=None):
    """The ONE way to open an Elasticsearch connection (credentials included)."""
    _load_credentials()
    host = os.getenv('ES_HOST', 'localhost')
    port = int(os.getenv('ES_PORT', 9200))
    username = os.getenv('ES_USERNAME', '')
    password = os.getenv('ES_PASSWORD', '')
    use_ssl  = os.getenv('ES_USE_SSL', 'false').lower() == 'true'

    scheme = 'https' if use_ssl else 'http'
    url = f"{scheme}://{host}:{port}"
    # Explicit timeout + one retry (2026-07-21, screening Rec #2). Previously
    # this relied on the library default (~10s, no retry): under load a slow
    # ES response silently pushed the engine onto the much weaker trigram
    # fallback with no indication on the result. 15s + retry_on_timeout
    # covers transient GC pauses; genuine outages still fail fast enough
    # and are now flagged on the screening result (see complynex_engine).
    timeout = int(timeout or os.getenv('ES_REQUEST_TIMEOUT', 15))
    if username and password:
        return Elasticsearch(hosts=[url], basic_auth=(username, password),
                             request_timeout=timeout, max_retries=1, retry_on_timeout=True)
    return Elasticsearch(hosts=[url], request_timeout=timeout, max_retries=1, retry_on_timeout=True)
