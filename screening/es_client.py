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


PRODUCTION_DB = 'complynex_db'


class ESTargetError(RuntimeError):
    """A process reading one database tried to write to the search index of another."""


def _current_db():
    try:
        from config import Config
        cfg = Config.POSTGRES_CONFIG
        return cfg.get('database') or cfg.get('dbname')
    except Exception:
        return os.getenv('POSTGRES_DB', PRODUCTION_DB)


def es_write_allowed(db_name=None):
    """(ok, why). The index names are fixed (aml_watchlist ...) and belong to ONE database:
    ES_INDEX_DB (default complynex_db). A process reading any other database (a scratch
    or test copy, the demo) must never write to them: on 30 Oct 2026 a scratch test
    overwrote 593 production documents this way."""
    db = db_name or _current_db()
    expected = os.getenv('ES_INDEX_DB', PRODUCTION_DB)
    if db != expected:
        return False, (f"refusing to write to the search index: this process reads database '{db}', "
                       f"the index belongs to '{expected}'")
    return True, ''


def guard_es_write(what='search index write', db_name=None):
    """Raise ESTargetError unless es_write_allowed(). Call before any index write."""
    ok, why = es_write_allowed(db_name)
    if not ok:
        raise ESTargetError(f'{what}: {why}')


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
