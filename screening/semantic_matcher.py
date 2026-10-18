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

import os
import time
import logging
import json
import numpy as np

try:
    import faiss
    from sentence_transformers import SentenceTransformer
    LIBS_AVAILABLE = True
except ImportError:
    LIBS_AVAILABLE = False

logger = logging.getLogger(__name__)

# The semantic index covers all three name lists the engine screens against
# (screening_watchlist, internal_pep, internal_blacklist) in one shared
# FAISS index — internal lists must not be a second-class, semantic-search-
# blind pathway. Each of those three tables has its own independently-
# sequenced integer `id` column, so their raw ids collide (internal_pep.id=1
# and screening_watchlist.id=1 are different records) — these offsets give
# each table its own non-overlapping id range within the one index, with
# generous headroom against growth (screening_watchlist currently tops out
# around 9.6M; internal_pep/internal_blacklist are in the low thousands).
# scripts/rebuild_semantic_index.py applies these when building the index;
# complynex_engine.py's _recall_candidates decodes them back to route each
# hit's enrichment lookup at the correct table.
WATCHLIST_ID_OFFSET = 0
INTERNAL_PEP_ID_OFFSET = 1_000_000_000
INTERNAL_BLACKLIST_ID_OFFSET = 2_000_000_000

# Loading this class is expensive (as of 2026-07-11, with the index stored
# int8-quantized: ~0.8GB embedding model + ~1GB FAISS index + a small
# id-array, roughly ~1.9GB total — was ~4.75GB before the index switched
# from raw float32 vectors to int8), and complynex_engine.py.__init__
# unconditionally tries to construct one per ComplyNexScreeningEngine
# instance. Each of gunicorn's web workers lazily builds its own engine
# singleton on first use — instantiating this in-process there would mean
# N workers x several GB, which does not fit on this box. Until it runs behind
# its own dedicated shared service (the ekyc-worker.py pattern: one
# long-lived process, other processes call it instead of loading their own
# copy), it must stay opt-in via this env var rather than load automatically
# just because the class is importable.
SEMANTIC_MATCHER_ENABLED = os.environ.get('SEMANTIC_MATCHER_ENABLED', 'false').lower() == 'true'


class SemanticSequenceMatcher:
    """
    Semantic Search and Embedding Matcher for Multilingual Names
    This utilizes `sentence-transformers` to map both Arabic and English names
    into the same semantic space, completely bypassing the need for character transliteration.
    """

    MODEL_NAME = 'paraphrase-multilingual-MiniLM-L12-v2'
    INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist_semantic_v2.index')
    # Compact int64 array of watchlist_id, one per FAISS index position (same
    # order as the index was built in) — replaces the old per-record JSON
    # metadata file (1.57M dicts with name/dataset/country/etc., ~1.2GB once
    # deserialized) which is no longer needed here: search_index() now
    # returns bare ids, and the caller enriches the handful of actual hits
    # from PostgreSQL — the same enrichment pattern complynex_engine.py's
    # Elasticsearch recall path already uses. 12MB on disk vs 330MB, and
    # loads as one flat array instead of 1.57M individual Python dict
    # objects.
    IDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist_semantic_ids_v2.npy')

    # Small secondary index for records added since the last full rebuild
    # (see add_to_delta()) — never merged into INDEX_FILE in-process.
    # Growing the ~2.5M-vector main index by even one record via
    # faiss.Index.add() reallocates its whole internal buffer (a plain
    # contiguous std::vector<float> under IndexFlat), which briefly needs
    # ~2x the index's memory — confirmed live: appending a single record to
    # the (at the time) 3.88GB main index took anon-rss from ~3.6GB to
    # ~7.2GB and got the whole process OOM-killed on this 7.8GB box. A
    # delta index starts empty and only ever holds the handful-to-thousands
    # of records added between full rebuilds, so the same doubling-on-grow
    # behavior costs megabytes, not gigabytes. scripts/rebuild_semantic_index.py
    # folds delta records into the next full rebuild (they're already in
    # Postgres) and resets these files to empty afterward.
    DELTA_INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist_semantic_delta_v2.index')
    DELTA_IDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist_semantic_delta_ids_v2.npy')

    def __init__(self):
        self.enabled = False
        self.model = None
        self.index = None
        self.ids = None
        self.delta_index = None
        self.delta_ids = None

        if not SEMANTIC_MATCHER_ENABLED:
            logger.info("SemanticSequenceMatcher disabled (SEMANTIC_MATCHER_ENABLED is not 'true').")
            return

        if not LIBS_AVAILABLE:
            logger.warning("SemanticSequenceMatcher disabled: sentence-transformers or faiss-cpu not installed.")
            return

        if not (os.path.exists(self.INDEX_FILE) and os.path.exists(self.IDS_FILE)):
            logger.warning("SemanticSequenceMatcher disabled: index files not found.")
            return

        try:
            logger.info(f"Loading Semantic Model: {self.MODEL_NAME}")
            self.model = SentenceTransformer(self.MODEL_NAME)
            self._load_index()
            self._load_delta()
            self.enabled = self.index is not None
        except Exception as e:
            logger.error(f"Failed to load Semantic Matcher: {e}")
            self.enabled = False

    def _load_index(self):
        """Loads the FAISS index and id array if they exist."""
        if os.path.exists(self.INDEX_FILE) and os.path.exists(self.IDS_FILE):
            try:
                self.index = faiss.read_index(self.INDEX_FILE)
                self.ids = np.load(self.IDS_FILE)
                logger.info(f"Loaded Semantic Index with {len(self.ids)} entities.")
            except Exception as e:
                logger.error(f"Error loading Semantic Index: {e}")
                self.index = None
                self.ids = None

    def _load_delta(self):
        """Loads the delta index (records added since the last full rebuild)
        if present. Missing is the normal case right after a full rebuild —
        not an error."""
        if os.path.exists(self.DELTA_INDEX_FILE) and os.path.exists(self.DELTA_IDS_FILE):
            try:
                self.delta_index = faiss.read_index(self.DELTA_INDEX_FILE)
                self.delta_ids = np.load(self.DELTA_IDS_FILE)
                logger.info(f"Loaded delta index with {len(self.delta_ids)} entities.")
            except Exception as e:
                logger.error(f"Error loading delta index: {e}")
                self.delta_index = None
                self.delta_ids = None

    def build_index(self, records, batch_size=32, encode_chunk_size=50000):
        """
        Builds a FAISS semantic index from a list of records.
        records: list of dicts with 'id', 'name'
        """
        if not self.enabled or not records:
            return False

        logger.info(f"Building Semantic Index for {len(records)} records...")
        usable = [r for r in records if r.get('name')]
        names = [r['name'] for r in usable]

        # 1. Generate Embeddings (this takes time) — batch_size matters, but
        # not in the "bigger is faster" direction typical wisdom assumes.
        # Measured on this box against real watchlist text (combined
        # Arabic+Latin names, highly variable length): batches of 16-32
        # ran ~14ms/record; 256 and 512 were 20-35% *slower* (19-20ms/record)
        # because high length variance within a large batch means more
        # padding waste than the larger matmul saves — hence the small
        # default. Unrelated to calculate_similarity()'s single-item
        # encode() calls below, which don't benefit from batching at all.
        #
        # encode_chunk_size bounds peak memory: encoding all ~2.5M names in
        # one call and only then handing the whole matrix to FAISS meant
        # several full-size (~3.9GB) copies of the embeddings array existed
        # at once (encode()'s own internal concat, plus this function's old
        # `np.array(embeddings).astype('float32')` re-copy, plus FAISS's
        # own copy on .add()) — that's what OOM-killed the box on a real
        # full run. Encoding+adding in chunks keeps only one chunk's worth
        # of embeddings (~50k x dim x 4 bytes, tens of MB) in memory at a
        # time; the FAISS index itself still grows to full size, but that
        # single copy was always unavoidable.
        dimension = self.model.get_sentence_embedding_dimension()
        # int8 scalar-quantized (1 byte/dim) instead of raw IndexFlatIP
        # (4 bytes/dim, float32) — cuts the resident index from ~3.9GB to
        # ~1GB at the current ~2.5M-vector size, which is most of why
        # complynex-semantic.service needed ~4.75GB RSS. Validated
        # 2026-07-11 against 2000 real watchlist/PEP/blacklist queries
        # (exact-name and partial-name) run through both formats side by
        # side: only 2/2000 cases crossed the 85%-match threshold
        # differently, and both were the quantized index finding a real
        # match the float32 one missed, not the reverse — no case of a
        # real match silently lost to the coarser number format.
        self.index = faiss.IndexScalarQuantizer(dimension, faiss.ScalarQuantizer.QT_8bit, faiss.METRIC_INNER_PRODUCT)

        # Scalar quantizer needs a short "train" pass first to learn each
        # dimension's min/max range for the 8-bit mapping — a random sample
        # is enough for this (doesn't need every vector), so this is one
        # extra encode pass over a few hundred thousand names, not the
        # full set.
        train_n = min(300_000, len(names))
        rng = np.random.default_rng(42)
        train_pos = rng.choice(len(names), size=train_n, replace=False)
        logger.info(f"Training scalar quantizer on {train_n} sample names...")
        train_embeddings = self.model.encode(
            [names[i] for i in train_pos], batch_size=batch_size, show_progress_bar=False,
            normalize_embeddings=True, convert_to_numpy=True,
        ).astype('float32', copy=False)
        self.index.train(train_embeddings)
        del train_embeddings

        total = len(names)
        for start in range(0, total, encode_chunk_size):
            chunk = names[start:start + encode_chunk_size]
            chunk_embeddings = self.model.encode(
                chunk, batch_size=batch_size, show_progress_bar=False,
                normalize_embeddings=True, convert_to_numpy=True,
            ).astype('float32', copy=False)
            self.index.add(chunk_embeddings)
            logger.info(f"  ...embedded {min(start + encode_chunk_size, total)}/{total} records")

        # 2. Save to Disk
        faiss.write_index(self.index, self.INDEX_FILE)

        # Save just the id, in the same order as the index — the caller
        # (complynex_engine.py) enriches from PostgreSQL for the handful of
        # ids an actual query returns, so nothing else needs to live here.
        self.ids = np.array([r['id'] for r in usable], dtype='int64')
        np.save(self.IDS_FILE, self.ids)

        logger.info("Semantic Index Built & Saved successfully.")
        return True

    def calculate_similarity(self, name1, name2):
        """
        Calculate semantic cosine similarity between 2 strings (0.0 to 100.0).
        Handles cross-lingual (Arabic vs English natively).
        """
        if not self.enabled or not name1 or not name2:
            return 0.0
            
        try:
            emb1 = self.model.encode(name1, normalize_embeddings=True)
            emb2 = self.model.encode(name2, normalize_embeddings=True)
            similarity = np.dot(emb1, emb2)
            # Clip between 0 and 1, convert to 100-basis score
            score = max(0.0, min(1.0, float(similarity))) * 100.0
            return score
        except Exception as e:
            logger.error(f"Semantic similarity error: {e}")
            return 0.0

    def search_index(self, query_name, top_k=5, country=None):
        """
        Search the semantic index for the closest matches — the main index
        plus the delta index (records added since the last full rebuild,
        see add_to_delta()), merged by score.

        Returns bare {'id', 'semantic_score'} pairs, not full watchlist
        records — the caller looks up the actual name/dataset/DOB/etc. for
        these ids from PostgreSQL (see complynex_engine.py's
        _recall_candidates), the same enrichment pattern already used for
        Elasticsearch-sourced candidates.
        """
        if not self.enabled or self.index is None or self.ids is None:
            return []

        actual_top_k = 150 if country else top_k

        query_emb = self.model.encode([query_name], normalize_embeddings=True)
        query_emb = np.array(query_emb).astype('float32')

        def _search_one(index, ids):
            if index is None or ids is None or index.ntotal == 0:
                return []
            distances, indices = index.search(query_emb, min(actual_top_k, index.ntotal))
            out = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx != -1 and idx < len(ids):
                    # Increase strictness! Any semantic match below 85% is discarded as noise.
                    # Cross-lingual vectors tend to cluster, 85% is a safe lower bound for "same name".
                    score = max(0.0, min(1.0, float(dist))) * 100.0
                    if score >= 85.0:
                        out.append({'id': int(ids[idx]), 'semantic_score': score})
            return out

        results = _search_one(self.index, self.ids) + _search_one(self.delta_index, self.delta_ids)
        # Merging two independently-topK'd result sets can exceed
        # actual_top_k in total — re-sort and trim back to the same cap the
        # single-index search used to return.
        results.sort(key=lambda r: r['semantic_score'], reverse=True)
        return results[:actual_top_k]

    def add_to_delta(self, records):
        """
        Embeds `records` (list of {'id', 'name'}) and appends them to the
        small delta index, persisting both to disk. Never touches the main
        index/ids — see DELTA_INDEX_FILE's class docstring for why growing
        the ~2.5M-vector main index in-process is unsafe on this box.

        Idempotent by id: records already present in the delta index are
        silently skipped rather than re-embedded and re-appended. This
        matters because the caller (scripts/incremental_reindex.py) only
        saves its checkpoint AFTER this call succeeds for the *whole*
        batch — if a later chunk in the same run times out, or the run
        errors out client-side after some chunks already landed here, the
        client's checkpoint never moves and it retries the entire
        unchanged batch on the next 15-minute run. Without this guard that
        retry re-embeds and re-appends every record that already made it
        in, forever, until the failure clears — which is exactly what
        happened in production on 2026-07-24: repeated retries of the same
        ~191k-record batch grew this delta index from empty to 5.17M
        vectors (7.4GB), which OOM-killed this service's own cgroup and
        pushed the whole VM into swap.
        """
        if not self.enabled or self.model is None:
            raise RuntimeError("Matcher not enabled/loaded — cannot add to delta index.")

        if self.delta_ids is not None and len(self.delta_ids) > 0:
            existing = set(self.delta_ids.tolist())
            records = [r for r in records if r['id'] not in existing]

        if not records:
            return int(self.delta_index.ntotal) if self.delta_index is not None else 0

        names = [r['name'] for r in records]
        embeddings = self.model.encode(
            names, batch_size=32, normalize_embeddings=True, show_progress_bar=False,
        ).astype('float32', copy=False)
        new_ids = np.array([r['id'] for r in records], dtype='int64')

        if self.delta_index is None:
            dimension = self.model.get_sentence_embedding_dimension()
            self.delta_index = faiss.IndexFlatIP(dimension)
            self.delta_ids = np.array([], dtype='int64')

        self.delta_index.add(embeddings)
        self.delta_ids = np.concatenate([self.delta_ids, new_ids])

        faiss.write_index(self.delta_index, self.DELTA_INDEX_FILE)
        np.save(self.DELTA_IDS_FILE, self.delta_ids)

        return int(self.delta_index.ntotal)


class SemanticMatcherClient:
    """
    Lightweight stand-in for SemanticSequenceMatcher used by
    ComplyNexScreeningEngine — this is what actually gets constructed once
    per gunicorn web worker, and it does none of the heavy loading itself.
    It calls the dedicated semantic_service.py process (see
    complynex-semantic.service) over a local-only HTTP API instead.

    `enabled` reflects whether that service answered a health check just
    now, not whether the libraries/index files exist — if the service isn't
    running (not yet deployed, mid-restart, whatever), this degrades to
    "no semantic candidates" exactly like the matcher being disabled does
    today, rather than raising or blocking a screening request.
    """

    DEFAULT_BASE_URL = os.environ.get('SEMANTIC_SERVICE_URL', 'http://127.0.0.1:8100')
    HEALTH_TIMEOUT_S = 1.0
    # 5s, not 3s: after the service sits idle long enough for the kernel to
    # reclaim/swap its index pages, the first search pages the whole flat
    # index back in and takes >3s — with a 3s timeout every such screen
    # burned the full timeout AND got zero semantic candidates. The
    # keepalive timer (complynex-semantic-keepalive.timer) makes that cold
    # case rare; this headroom covers the gaps. Warm searches are
    # 160-260ms, so a healthy service never comes near either limit.
    SEARCH_TIMEOUT_S = 5.0
    HEALTH_RECHECK_INTERVAL_S = 60.0

    def __init__(self, base_url=None):
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.enabled = self._check_health()
        self._next_recheck = time.monotonic() + self.HEALTH_RECHECK_INTERVAL_S

    def _check_health(self):
        try:
            import requests
            resp = requests.get(f"{self.base_url}/health", timeout=self.HEALTH_TIMEOUT_S)
            return bool(resp.ok and resp.json().get('enabled'))
        except Exception as e:
            logger.info(f"Semantic service not reachable at {self.base_url}: {e}")
            return False

    def search_index(self, query_name, top_k=5, country=None):
        if not self.enabled:
            # A worker whose constructor ran while the semantic service was
            # down (mid-restart, not yet started) must not stay
            # semantic-blind for its whole lifetime — recheck at most once
            # a minute so a recovered service gets picked back up without
            # hammering a dead one on every screen.
            now = time.monotonic()
            if now < self._next_recheck:
                return []
            self._next_recheck = now + self.HEALTH_RECHECK_INTERVAL_S
            self.enabled = self._check_health()
            if not self.enabled:
                return []
        try:
            import requests
            resp = requests.post(
                f"{self.base_url}/search",
                json={'name': query_name, 'top_k': top_k, 'country': country},
                timeout=self.SEARCH_TIMEOUT_S,
            )
            if resp.ok:
                return resp.json().get('results', [])
            logger.warning(f"Semantic service returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            # A slow/unreachable semantic service must never take a
            # screening request down with it — same fallback behavior as
            # the service being disabled.
            logger.warning(f"Semantic service call failed: {e}")
        return []
