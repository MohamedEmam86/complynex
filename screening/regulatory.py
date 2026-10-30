"""
Regulatory-measures lists (Phase 2, P2-4): lists of supervisory sanctions taken against
financial institutions and their staff for breaching AML/CFT requirements - for example the
Palestine Monetary Authority list published under Article 58 of Decree-Law 39/2022
(banks, money changers, specialised lending institutions, e-payment companies).

These are not asset-freeze / designation lists: a hit is risk information for onboarding a
financial-institution customer or counterparty (KYB / correspondent / agent due diligence),
not a reason to block. So they are searched only where the compliance officer has chosen:

    screening_config.regulatory_lists_scope
        'kyb'  (default) - KYB / merchant / entity screenings only
        'all'            - every screening
        'off'            - never

A caller can also decide per screening with include_regulatory=True / False
(e.g. an API client or a specific onboarding flow), which overrides the setting.
Records carry list_type 'REGULATORY' and the topic 'reg.action'.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

LIST_TYPE = 'REGULATORY'
CONFIG_KEY = 'regulatory_lists_scope'
SCOPES = ('kyb', 'all', 'off')
DEFAULT = 'kyb'
KYB_TYPES = ('KYB', 'MERCHANT', 'KYB_ENTITY', 'CORPORATE', 'ENTITY')
INDIVIDUAL_TYPES = ('INDIVIDUAL', 'PERSON', 'NATURAL_PERSON', '')
CACHE_SECONDS = 60

_lock = threading.Lock()
_cache = {'at': 0.0, 'scope': DEFAULT}


def scope(force=False):
    """The scope in force (cached; on any error the last good value, initially the default)."""
    now = time.time()
    if not force and now - _cache['at'] < CACHE_SECONDS:
        return _cache['scope']
    with _lock:
        try:
            import psycopg2
            from config import Config
            conn = psycopg2.connect(**Config.POSTGRES_CONFIG, connect_timeout=5)
            try:
                cur = conn.cursor()
                cur.execute("SELECT config_value FROM screening_config WHERE config_key = %s", (CONFIG_KEY,))
                row = cur.fetchone()
            finally:
                conn.close()
            val = str(row[0]).strip().lower() if row and row[0] else DEFAULT
            if val not in SCOPES:
                logger.warning('regulatory_lists_scope %r is invalid; using %s', val, DEFAULT)
                val = DEFAULT
        except Exception as ex:
            logger.debug('regulatory scope not readable (%s); keeping %s', ex, _cache['scope'])
            val = _cache['scope']
        _cache['scope'], _cache['at'] = val, now
        return val


def included(entity_type=None, screening_type=None, explicit=None, current_scope=None):
    """Should regulatory-measures lists be searched for this screening?"""
    if explicit is not None:
        return bool(explicit)
    sc = current_scope or scope()
    if sc == 'all':
        return True
    if sc == 'off':
        return False
    et = str(entity_type or '').strip().upper()
    sts = screening_type if isinstance(screening_type, (list, tuple, set)) else [screening_type]
    for st in sts:
        st = str(st or '').strip().upper()
        if st in KYB_TYPES or st.startswith(('KYB', 'MERCHANT')):
            return True
    return et not in INDIVIDUAL_TYPES


def is_regulatory(candidate):
    c = candidate or {}
    return (str(c.get('list_type') or '').upper() == LIST_TYPE
            or str(c.get('source') or '').strip().lower().endswith('_reg'))


def apply(candidates, include):
    """Drop regulatory-list candidates when they are not in scope."""
    if include or not candidates:
        return candidates
    return [c for c in candidates if not is_regulatory(c)]
