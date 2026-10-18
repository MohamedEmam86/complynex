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
Per-installation (tenant) AI settings, stored in system_settings, and the
provider objects built from them. Any misconfiguration degrades to
rules_only — it never blocks a compliance flow.
"""

import logging

from . import netguard
from .providers import LocalEmbeddings, LocalHTTP, ProviderError, RulesOnly

logger = logging.getLogger(__name__)

DEFAULTS = {
    'ai.enabled': 'true',                 # AI features (all providers, incl. rules) on/off
    'ai.provider': 'rules_only',          # rules_only | local_http
    'ai.base_url': 'http://127.0.0.1:11434',
    'ai.api_style': 'ollama',             # ollama | openai_compat (llama.cpp server)
    'ai.model': '',
    'ai.timeout_s': '90',
    'ai.embeddings': 'off',               # off | semantic_service | local_path
    'ai.embeddings_url': 'http://127.0.0.1:8100',
    'ai.embeddings_path': '',
    'ai.log_retention_days': '90',
    'ai.async': 'true',                   # run model calls as RQ jobs (falls back inline without Redis)
}
PROVIDERS = ('rules_only', 'local_http')
EMBEDDINGS = ('off', 'semantic_service', 'local_path')


def get_config():
    try:
        from models.settings import Settings
        vals = Settings.get_many(list(DEFAULTS))
    except Exception:
        vals = {}
    cfg = {k: (vals.get(k) if vals.get(k) not in (None, '') else v) for k, v in DEFAULTS.items()}
    cfg['ai.enabled'] = str(cfg['ai.enabled']).lower() == 'true'
    cfg['ai.async'] = str(cfg['ai.async']).lower() == 'true'
    for k in ('ai.timeout_s', 'ai.log_retention_days'):
        try:
            cfg[k] = int(cfg[k])
        except (TypeError, ValueError):
            cfg[k] = int(DEFAULTS[k])
    return cfg


def save_config(data):
    """Validate and store. Raises ValueError (incl. NotLocalError) on a bad value."""
    from models.settings import Settings
    prov = data.get('ai.provider', 'rules_only')
    if prov not in PROVIDERS:
        raise ValueError('unknown provider')
    emb = data.get('ai.embeddings', 'off')
    if emb not in EMBEDDINGS:
        raise ValueError('unknown embeddings mode')
    if prov == 'local_http':
        data['ai.base_url'] = netguard.check_local_url(data.get('ai.base_url'))
        if not (data.get('ai.model') or '').strip():
            raise ValueError('name the local model (e.g. qwen2.5:7b-instruct)')
    if emb == 'semantic_service':
        data['ai.embeddings_url'] = netguard.check_local_url(data.get('ai.embeddings_url'))
    if emb == 'local_path':
        import os
        if not os.path.isdir(data.get('ai.embeddings_path') or ''):
            raise ValueError('the embeddings model path must be a directory on this server')
    for k in ('ai.timeout_s', 'ai.log_retention_days'):
        if not str(data.get(k, DEFAULTS[k])).isdigit():
            raise ValueError(f'{k} must be a whole number')
    if data.get('ai.api_style', 'ollama') not in ('ollama', 'openai_compat'):
        raise ValueError('unknown API style')
    Settings.set_many({k: str(data.get(k, DEFAULTS[k])) for k in DEFAULTS})


def generator(cfg=None):
    """The text-generation provider, or RulesOnly when none is configured / valid."""
    cfg = cfg or get_config()
    if cfg['ai.enabled'] and cfg['ai.provider'] == 'local_http':
        try:
            return LocalHTTP(cfg['ai.base_url'], cfg['ai.model'], cfg['ai.api_style'], cfg['ai.timeout_s'])
        except (netguard.NotLocalError, ProviderError) as e:
            logger.warning('AI: local_http not usable (%s); using rules_only', e)
    return RulesOnly()


def embedder(cfg=None):
    cfg = cfg or get_config()
    if not cfg['ai.enabled'] or cfg['ai.embeddings'] == 'off':
        return None
    try:
        return LocalEmbeddings(cfg['ai.embeddings'], cfg['ai.embeddings_url'], cfg['ai.embeddings_path'], 10)
    except (netguard.NotLocalError, ProviderError) as e:
        logger.warning('AI: embeddings not usable (%s)', e)
        return None
