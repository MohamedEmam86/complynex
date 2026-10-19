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
    'ai.freeze_match_threshold': '0.80',  # freeze-order screening: minimum name score (0-1), as the screening search
    'ai.freeze_counterparty_days': '90',  # freeze-order screening: counterparties of the last N days
    'ai.cite_min_score': '0.30',          # policy questions: minimum rules score of a cited paragraph (0-1)
    'ai.cite_min_embedding': '0.55',      # policy questions: minimum embedding cosine of a cited paragraph (0-1)
}
FLOATS = ('ai.freeze_match_threshold', 'ai.cite_min_score', 'ai.cite_min_embedding')
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
    for k in ('ai.timeout_s', 'ai.log_retention_days', 'ai.freeze_counterparty_days'):
        try:
            cfg[k] = int(cfg[k])
        except (TypeError, ValueError):
            cfg[k] = int(DEFAULTS[k])
    for k in FLOATS:
        try:
            cfg[k] = min(1.0, max(0.0, float(cfg[k])))
        except (TypeError, ValueError):
            cfg[k] = float(DEFAULTS[k])
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
    for k in ('ai.timeout_s', 'ai.log_retention_days', 'ai.freeze_counterparty_days'):
        data[k] = str(data.get(k) or DEFAULTS[k])
        if not data[k].isdigit():
            raise ValueError(f'{k} must be a whole number')
    for k in FLOATS:
        data[k] = str(data.get(k) or DEFAULTS[k])
        try:
            ok = 0 <= float(data[k]) <= 1
        except ValueError:
            ok = False
        if not ok:
            raise ValueError(f'{k} must be a number between 0 and 1')
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


# ------------------------------------------------------------------ monitored mailbox (IMAP, optional)
# IMAP is not AI: any mail host is allowed, but only over TLS (implicit SSL or STARTTLS).
# The password is stored encrypted (data_protection EncryptionService, Fernet) or as a
# reference to an environment variable ("env:NAME"); it is never shown back in the UI.
MAIL_DEFAULTS = {
    'ai.imap_enabled': 'false',
    'ai.imap_host': '',
    'ai.imap_port': '993',
    'ai.imap_security': 'ssl',            # ssl (implicit TLS, 993) | starttls (143 + STARTTLS)
    'ai.imap_user': '',
    'ai.imap_password': '',               # "enc:<token>" or "env:<VARIABLE>"
    'ai.imap_folder': 'INBOX',
    'ai.imap_max_messages': '20',
    'ai.imap_channel': 'email',           # channel of the created intake items
}
MAIL_SECURITY = ('ssl', 'starttls')


def get_mail_config():
    try:
        from models.settings import Settings
        vals = Settings.get_many(list(MAIL_DEFAULTS))
    except Exception:
        vals = {}
    cfg = {k: (vals.get(k) if vals.get(k) not in (None, '') else v) for k, v in MAIL_DEFAULTS.items()}
    cfg['ai.imap_enabled'] = str(cfg['ai.imap_enabled']).lower() == 'true'
    for k in ('ai.imap_port', 'ai.imap_max_messages'):
        try:
            cfg[k] = int(cfg[k])
        except (TypeError, ValueError):
            cfg[k] = int(MAIL_DEFAULTS[k])
    cfg['password_set'] = bool(cfg['ai.imap_password'])
    cfg['password_kind'] = 'env' if str(cfg['ai.imap_password']).startswith('env:') else ('stored' if cfg['password_set'] else None)
    return cfg


def save_mail_config(data):
    """data: form values. An empty password keeps the stored one; "env:NAME" stores a reference."""
    import re
    from models.settings import Settings
    cur = get_mail_config()
    out = {k: str(data.get(k, '') or '').strip() for k in MAIL_DEFAULTS if k != 'ai.imap_password'}
    out['ai.imap_enabled'] = 'true' if data.get('ai.imap_enabled') else 'false'
    if out['ai.imap_security'] not in MAIL_SECURITY:
        raise ValueError('the mailbox must be read over SSL/TLS or STARTTLS')
    for k in ('ai.imap_port', 'ai.imap_max_messages'):
        out[k] = out[k] or MAIL_DEFAULTS[k]
        if not out[k].isdigit() or not 0 < int(out[k]) < 65536:
            raise ValueError(f'{k} must be a whole number')
    out['ai.imap_folder'] = out['ai.imap_folder'] or 'INBOX'
    out['ai.imap_channel'] = out['ai.imap_channel'] if out['ai.imap_channel'] in ('email', 'alert', 'circular') else 'email'
    if out['ai.imap_host'] and not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', out['ai.imap_host']):
        raise ValueError('the mail server must be a host name or IP address')
    if out['ai.imap_enabled'] == 'true' and not (out['ai.imap_host'] and out['ai.imap_user']):
        raise ValueError('enter the mail server and the user name')
    pw = str(data.get('ai.imap_password') or '').strip()
    if pw.startswith('env:'):
        if not re.fullmatch(r'env:[A-Za-z_][A-Za-z0-9_]{0,80}', pw):
            raise ValueError('an environment reference looks like env:COMPLYNEX_IMAP_PASSWORD')
        out['ai.imap_password'] = pw
    elif pw:
        from data_protection.encryption_service import EncryptionService
        tok = EncryptionService.encrypt_value(pw)
        if not tok:
            raise ValueError('the password could not be encrypted: use an environment reference (env:NAME)')
        out['ai.imap_password'] = 'enc:' + tok
    elif data.get('clear_password'):
        out['ai.imap_password'] = ''
    else:
        out['ai.imap_password'] = cur['ai.imap_password'] if cur['password_set'] else ''
    Settings.set_many(out)


def mail_password(cfg=None):
    """The clear-text IMAP password (only in memory, for the login)."""
    import os
    raw = str((cfg or get_mail_config()).get('ai.imap_password') or '')
    if raw.startswith('env:'):
        return os.environ.get(raw[4:], '')
    if raw.startswith('enc:'):
        from data_protection.encryption_service import EncryptionService
        return EncryptionService.decrypt_value(raw[4:]) or ''
    return ''
