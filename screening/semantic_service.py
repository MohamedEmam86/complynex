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
Dedicated semantic-search service. Run as its own process (see the
complynex-semantic systemd service), separate from the Gunicorn web
workers, for the same reason ekyc/worker.py is its own process: the
embedding model + FAISS index cost ~3.5GB RSS once loaded. Loading that
in-process inside every lazily-initialized ComplyNexScreeningEngine (one
per gunicorn web worker) would mean N workers x ~3.5GB, which does not fit
on this box. Loaded once here instead, and called over a local-only HTTP
API by screening/semantic_matcher.py's SemanticMatcherClient.

Binds to 127.0.0.1 only — never exposed outside this host.
"""
import logging
import os

os.environ.setdefault('SEMANTIC_MATCHER_ENABLED', 'true')
# The model is already fully cached locally under this app's working
# directory (.cache/huggingface) rather than $HOME/.cache/huggingface —
# same root cause as the OCR/face-match model paths (ekyc/ocr_engine.py,
# ekyc/face_match.py): the `complynex` service user's $HOME doesn't exist,
# so anything relying on default $HOME-relative cache resolution needs an
# explicit path instead. HF_HOME must be set BEFORE forcing offline mode
# below — with $HOME unresolvable, huggingface_hub's offline-mode lookup
# doesn't fall back to a cache dir on its own, it just fails outright
# ("couldn't find them in the cached files").
os.environ.setdefault('HF_HOME', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.cache', 'huggingface'))
# Without forcing offline mode, every process start makes ~10 HTTP HEAD/GET
# calls to huggingface.co just to revalidate files it already has —
# unnecessary latency, and an external network dependency for booting a
# core screening subsystem that has no reason to depend on internet
# reachability.
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

HOST = '127.0.0.1'
PORT = int(os.environ.get('SEMANTIC_SERVICE_PORT', 8100))

_matcher = None


def _get_matcher():
    global _matcher
    if _matcher is None:
        from screening.semantic_matcher import SemanticSequenceMatcher
        logger.info("Loading semantic matcher (embedding model + FAISS index)...")
        _matcher = SemanticSequenceMatcher()
        logger.info(f"Semantic matcher ready: enabled={_matcher.enabled}")
    return _matcher


def create_service_app():
    from flask import Flask, request, jsonify

    app = Flask(__name__)
    matcher = _get_matcher()

    # Warm-up: the first real search otherwise pays the full lazy-init cost
    # (torch kernels, tokenizer, first page-in of the index) and can exceed
    # the client's timeout, so the first screening after every service
    # restart would silently get zero semantic candidates.
    if matcher.enabled:
        try:
            matcher.search_index('warm-up probe', top_k=1)
            logger.info("Warm-up search done — service is hot.")
        except Exception:
            logger.exception("Warm-up search failed (service still serving)")

    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({'ok': True, 'enabled': matcher.enabled,
                         'entities': int(len(matcher.ids)) if matcher.ids is not None else 0,
                         'delta_entities': int(len(matcher.delta_ids)) if matcher.delta_ids is not None else 0})

    @app.route('/search', methods=['POST'])
    def search():
        data = request.get_json(silent=True) or {}
        name = data.get('name', '')
        top_k = int(data.get('top_k', 25))
        country = data.get('country')
        if not name:
            return jsonify({'error': 'name is required'}), 400
        try:
            results = matcher.search_index(name, top_k=top_k, country=country)
            return jsonify({'results': results})
        except Exception as e:
            logger.exception("Semantic search failed")
            return jsonify({'error': str(e)}), 500

    @app.route('/embed', methods=['POST'])
    def embed():
        """Text embeddings for the Compliance Copilot (ai/ local_embeddings
        provider) — reuses the already-loaded multilingual model, so no
        second model is held in memory. Read-only: the index is untouched."""
        if not matcher.enabled or matcher.model is None:
            return jsonify({'error': 'semantic matcher not enabled/loaded'}), 503
        data = request.get_json(silent=True) or {}
        texts = [str(t)[:2000] for t in (data.get('texts') or []) if t is not None][:256]
        if not texts:
            return jsonify({'error': 'texts (list of strings) is required'}), 400
        try:
            vecs = matcher.model.encode(texts, normalize_embeddings=True, batch_size=32)
            return jsonify({'vectors': [[round(float(x), 6) for x in v] for v in vecs]})
        except Exception as e:
            logger.exception("embed failed")
            return jsonify({'error': str(e)}), 500

    @app.route('/add_delta', methods=['POST'])
    def add_delta():
        """
        Embeds new records into the small delta index (see
        SemanticSequenceMatcher.add_to_delta / DELTA_INDEX_FILE) instead of
        the ~2.5M-vector main index — called by
        scripts/incremental_reindex.py. Growing the main index in-process
        (the first version of this endpoint) OOM-killed this service:
        faiss.Index.add() reallocates its whole internal buffer on any
        growth, which briefly needs ~2x the index's memory — fine for a
        delta index that's only ever a few thousand vectors, not for one
        that's already 3.88GB.
        """
        if not matcher.enabled:
            return jsonify({'error': 'semantic matcher not enabled/loaded'}), 503

        data = request.get_json(silent=True) or {}
        records = data.get('records') or []
        records = [r for r in records if r.get('id') is not None and r.get('name')]
        if not records:
            return jsonify({'error': 'records (list of {id, name}) is required'}), 400

        try:
            total = matcher.add_to_delta(records)
        except Exception as e:
            logger.exception("add_delta failed")
            return jsonify({'error': str(e)}), 500

        logger.info(f"Added {len(records)} records to delta index via /add_delta. "
                    f"Delta now has {total} vectors.")
        return jsonify({'added': len(records), 'delta_entities': total})

    return app


if __name__ == '__main__':
    # Manual/dev entry point only — the systemd service
    # (complynex-semantic.service) runs this through gunicorn instead
    # (`gunicorn 'screening.semantic_service:create_service_app()'`), not
    # Flask's own dev server, same as the main app.
    #
    # Same BLAS/OpenMP thread-pinning rationale as ekyc/worker.py: without
    # this, torch/faiss each spawn a thread pool sized to the host's core
    # count by default, which is the real CPU-thrash risk under concurrent
    # requests on this 2-core box, not model weight size. Also set via the
    # systemd unit's Environment= lines as a backstop, same pattern as
    # complynex-ekyc-worker.service.
    import torch
    torch.set_num_threads(1)

    app = create_service_app()
    # Single-threaded: this process exists to hold one big shared in-memory
    # index, not to serve concurrent request load — screening requests are
    # already infrequent relative to model inference time, and the gevent
    # web workers calling in have their own short client-side timeout (see
    # semantic_matcher.py's SemanticMatcherClient) so a slow/busy call here
    # degrades to "no semantic candidates" rather than blocking a request.
    app.run(host=HOST, port=PORT, threaded=False, debug=False)
