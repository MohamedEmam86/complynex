# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================
"""Tenant isolation (Phase 6: P6-1 tenant_id + PostgreSQL row-level security, P6-3 private lists).

One database serves several companies (tenants). Every tenant-owned table carries a
``tenant_id`` column and a row-level-security policy::

    tenant_id = current_setting('app.tenant_id')::int

The application sets ``app.tenant_id`` on every connection it takes from a pool (web
requests: from the logged-in user or the API key; the screening engine: at the start of
each screening). The screening lists stay SHARED: ``screening_watchlist`` rows with
``tenant_id IS NULL`` are the public lists (UN, OFAC, EMLCU, OpenSanctions ...) and rows
with a tenant_id are that tenant's private internal-list copies.

Everything here is inert until ``TENANCY_ENFORCED=1``:
  * with the flag off, the request / pool / engine paths do not call bind() at all (no extra
    DB round trip; bind() itself still works for scripts and tests) and the ES filter is not
    added, so behaviour is exactly as before;
  * the schema changes are produced by ``scripts/tenancy_sql.py`` and applied by hand
    (see docs/TENANCY.md), never by deploy.sh.

A large tenant can instead get its own database: same code, its own DATABASE settings
(POSTGRES_DB ...), one tenant (id 1) inside it. Nothing in this module changes for that.
"""
import logging
import os

logger = logging.getLogger(__name__)

SETTING = 'app.tenant_id'
DEFAULT_TENANT = 1

# --------------------------------------------------------------------------- classification
# Shared reference data, maintained centrally (list loaders, central config): no tenant_id.
SHARED_TABLES = frozenset({
    'screening_data_sources', 'screening_list_versions', 'screening_list_alerts',
    'screening_list_update_log', 'screening_update_log', 'screening_update_logs',
    'screening_entity_clusters', 'screening_entity_links', 'screening_entity_unlinks',
    'screening_entity_link_runs', 'screening_pep_relations', 'screening_quality_runs',
    'screening_qa_cases', 'screening_qa_runs', 'screening_metrics', 'screening_config',
    'sanctions_lists', 'sanctions_entries', 'data_source_urls', 'data_update_audit_log',
    'high_risk_countries', 'carbon_emission_factors', 'regulators',
    # central Egyptian PEP reference database (pep management module)
    'pep_master', 'pep_positions', 'pep_sources', 'pep_aliases', 'pep_database',
    'pep_update_logs', 'pep_duplicate_candidates', 'pep_corporate_links',
})
# Platform-level tables that belong to no tenant (academy / talent pool of the operator,
# backups taken by hand, the tenants table itself).
SYSTEM_TABLES = frozenset({'tenants', 'academy_settings', 'academy_rejected_domains', 'talent_settings'})
SYSTEM_PREFIXES = ('bk_', 'academy_', 'talent_')
# Tenant-owned but WITHOUT row-level security: they are read before the tenant is known
# (login by e-mail, API key lookup). The application filters them itself.
TAGGED_NO_RLS = frozenset({'users', 'api_keys'})
# Shared table with private rows: tenant_id NULL = shared row, otherwise that tenant's row.
MIXED_TABLES = frozenset({'screening_watchlist'})
# Private lists per tenant (P6-3): tenant-owned (the default class); listed for the docs/tests.
PRIVATE_LIST_TABLES = ('internal_blacklist', 'internal_blacklist_audit', 'internal_pep',
                       'internal_pep_audit', 'screening_whitelist', 'screening_whitelist_matches',
                       'screening_whitelist_audit', 'blacklist_bulk_imports')


def classify(table):
    """'shared' | 'system' | 'tagged' | 'mixed' | 'tenant' (the default: tenant-owned with RLS)."""
    t = (table or '').lower()
    if t in MIXED_TABLES:
        return 'mixed'
    if t in SHARED_TABLES:
        return 'shared'
    if t in SYSTEM_TABLES or t.startswith(SYSTEM_PREFIXES):
        return 'system'
    if t in TAGGED_NO_RLS:
        return 'tagged'
    return 'tenant'


def enforced():
    return os.getenv('TENANCY_ENFORCED', '0').strip().lower() in ('1', 'true', 'yes', 'on')


# --------------------------------------------------------------------------- request context
def _as_int(v):
    try:
        return int(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


def current_tenant_id():
    """Tenant of the current request: explicit (set_request_tenant) > API key > logged-in user.
    None outside a request or for an anonymous visitor."""
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        if g.get('tenant_id') is not None:
            return g.get('tenant_id')
        key = g.get('api_key')
        if key and _as_int(dict(key).get('tenant_id')) is not None:
            return _as_int(dict(key).get('tenant_id'))
        from flask_login import current_user
        if getattr(current_user, 'is_authenticated', False):
            tid = _as_int(getattr(current_user, 'tenant_id', None))
            return tid if tid is not None else DEFAULT_TENANT
    except Exception as e:      # never break a request over this
        logger.debug('tenant lookup failed: %s', e)
    return None


def set_request_tenant(tenant_id):
    """Fix the tenant of this request (API key auth, admin switching tenant) and re-bind the
    request's pooled connection if it was already taken."""
    from flask import g
    g.tenant_id = _as_int(tenant_id)
    db = g.get('db')
    if db is not None and enforced():
        bind(getattr(db, '_conn', db), g.tenant_id)


# --------------------------------------------------------------------------- connections
def bind(conn, tenant_id=None):
    """Set app.tenant_id on a raw psycopg2 connection (session level, so it survives the
    commits of the request). '' when no tenant: under enforcement that sees no tenant rows.
    Committed at once when the connection was idle, so a later rollback cannot undo it."""
    if conn is None:
        return False
    value = '' if tenant_id is None else str(int(tenant_id))
    try:
        idle = True
        try:
            import psycopg2.extensions as _ext
            idle = conn.get_transaction_status() == _ext.TRANSACTION_STATUS_IDLE
        except Exception:
            pass
        cur = conn.cursor()
        cur.execute("SELECT set_config(%s, %s, false)", (SETTING, value))
        cur.close()
        if idle:
            conn.commit()
        return True
    except Exception as e:
        logger.warning('could not set %s on a connection: %s', SETTING, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def unbind(conn):
    """Clear the tenant before a connection goes back to a pool."""
    return bind(conn, None)


def bind_current(conn):
    return bind(conn, current_tenant_id())


# --------------------------------------------------------------------------- search index
def es_filter(tenant_id):
    """ES clause: the shared documents (no tenant_id) plus this tenant's private ones."""
    shared = {'bool': {'must_not': {'exists': {'field': 'tenant_id'}}}}
    if tenant_id is None:
        return shared
    return {'bool': {'should': [shared, {'term': {'tenant_id': int(tenant_id)}}],
                     'minimum_should_match': 1}}


def es_filter_current():
    """None while the flag is off (the query stays exactly as before)."""
    if not enforced():
        return None
    return es_filter(current_tenant_id())


def private_source_id(source_id, tenant_id):
    """Private-list copies in the shared watchlist must not collide across tenants
    (UNIQUE (source, source_id)); tenant 1 keeps today's ids."""
    tid = _as_int(tenant_id)
    if tid in (None, DEFAULT_TENANT):
        return source_id
    return f'{source_id}-t{tid}'


# --------------------------------------------------------------------------- flask
def init_app(app):
    """Bind the request's tenant once the user / API key is known."""
    @app.before_request
    def _cx_bind_tenant():
        try:
            from flask import g
            tid = current_tenant_id()
            g.tenant_id = tid
            db = g.get('db')
            if db is not None and enforced():   # flag off: no DB round trip per request
                bind(getattr(db, '_conn', db), tid)
        except Exception as e:
            logger.debug('tenant bind skipped: %s', e)
