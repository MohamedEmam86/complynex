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
AI providers — all local. Exactly three:

  rules_only        deterministic; always available; the default
  local_http        a local inference server (Ollama `/api/chat`, or the
                    OpenAI-compatible `/v1/chat/completions` that llama.cpp
                    server exposes). The URL must be localhost / private.
  local_embeddings  sentence embeddings from the semantic screening service
                    already running on this server (POST /embed), or a
                    SentenceTransformer loaded from a LOCAL path.

There is no code path to any external AI service; model weights are never
downloaded (paths/names are configuration only).
"""

import logging
import time

from . import netguard

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    pass


class Provider:
    name = 'base'
    model = None
    can_generate = False
    can_embed = False

    def health(self):
        return {'ok': True, 'detail': ''}

    def generate(self, system, prompt, timeout=None):
        raise ProviderError(f'{self.name} cannot generate text')

    def embed(self, texts, timeout=None):
        raise ProviderError(f'{self.name} cannot embed text')


class RulesOnly(Provider):
    name = 'rules_only'
    model = 'rules-v1'


class LocalHTTP(Provider):
    """Ollama or llama.cpp-server compatible local inference server."""
    name = 'local_http'
    can_generate = True

    def __init__(self, base_url, model, api_style='ollama', timeout=60, resolver=None):
        self.base_url = netguard.check_local_url(base_url, resolver)
        self.model = model or 'local-model'
        self.api_style = api_style if api_style in ('ollama', 'openai_compat') else 'ollama'
        self.timeout = float(timeout or 60)
        self._resolver = resolver

    def _url(self, path):
        # re-checked at every call: DNS for the configured host can change after it was saved
        try:
            return netguard.check_local_url(self.base_url, self._resolver) + path
        except netguard.NotLocalError as e:
            raise ProviderError(f'refused: {e}') from e

    def health(self):
        import requests
        try:
            if self.api_style == 'ollama':
                r = requests.get(self._url('/api/tags'), timeout=3)
                names = [m.get('name') for m in (r.json().get('models') or [])] if r.ok else []
                ok = r.ok and (not self.model or any((n or '').split(':')[0] == self.model.split(':')[0] for n in names))
                return {'ok': ok, 'detail': f'models: {", ".join(n for n in names if n) or "none"}'}
            r = requests.get(self._url('/v1/models'), timeout=3)
            return {'ok': r.ok, 'detail': f'HTTP {r.status_code}'}
        except ProviderError as e:
            return {'ok': False, 'detail': str(e)}
        except Exception as e:
            return {'ok': False, 'detail': f'not reachable: {e.__class__.__name__}'}

    def generate(self, system, prompt, timeout=None):
        import requests
        t = float(timeout or self.timeout)
        msgs = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
        try:
            if self.api_style == 'ollama':
                r = requests.post(self._url('/api/chat'), json={'model': self.model, 'messages': msgs, 'stream': False,
                                                                'format': 'json', 'options': {'temperature': 0}},
                                  timeout=t)
                r.raise_for_status()
                return (r.json().get('message') or {}).get('content', '')
            r = requests.post(self._url('/v1/chat/completions'),
                              json={'model': self.model, 'messages': msgs, 'temperature': 0,
                                    'response_format': {'type': 'json_object'}}, timeout=t)
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content']
        except netguard.NotLocalError:
            raise
        except Exception as e:
            raise ProviderError(f'local model call failed: {e.__class__.__name__}: {str(e)[:200]}')


class LocalEmbeddings(Provider):
    """Embeddings from the local semantic service, or a model loaded from a local directory."""
    name = 'local_embeddings'
    can_embed = True
    _models = {}

    def __init__(self, mode='semantic_service', url='http://127.0.0.1:8100', path=None, timeout=10, resolver=None):
        self.mode = mode if mode in ('semantic_service', 'local_path') else 'semantic_service'
        self.timeout = float(timeout or 10)
        if self.mode == 'semantic_service':
            self.url = netguard.check_local_url(url, resolver)
            self.model = 'semantic-service'
        else:
            import os
            if not path or not os.path.isdir(path):
                raise ProviderError('local embeddings: model path is not a local directory')
            self.path = path
            self.model = os.path.basename(path.rstrip('/'))
        self._resolver = resolver

    def health(self):
        try:
            v = self.embed(['health check'], timeout=5)
            return {'ok': bool(v and v[0]), 'detail': f'{self.mode}, dim {len(v[0]) if v and v[0] else 0}'}
        except Exception as e:
            return {'ok': False, 'detail': str(e)[:200]}

    def embed(self, texts, timeout=None):
        if self.mode == 'semantic_service':
            import requests
            try:
                r = requests.post(netguard.check_local_url(self.url, self._resolver) + '/embed',
                                  json={'texts': list(texts)}, timeout=float(timeout or self.timeout))
                r.raise_for_status()
                return r.json()['vectors']
            except netguard.NotLocalError:
                raise
            except Exception as e:
                raise ProviderError(f'embedding service failed: {e.__class__.__name__}')
        m = self._models.get(self.path)
        if m is None:
            try:
                import os
                os.environ.setdefault('HF_HUB_OFFLINE', '1')
                os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ProviderError('sentence-transformers is not installed')
            m = self._models[self.path] = SentenceTransformer(self.path)
        return [list(map(float, v)) for v in m.encode(list(texts), normalize_embeddings=True)]


def cosine(a, b):
    import math
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


def timed(fn, *a, **kw):
    t0 = time.monotonic()
    out = fn(*a, **kw)
    return out, int((time.monotonic() - t0) * 1000)
