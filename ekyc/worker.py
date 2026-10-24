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
Dedicated eKYC pipeline worker. Run as its own process (see the
complynex-ekyc-worker systemd service), separate from the Gunicorn web
workers, so that:
  - every ML model is loaded exactly once (not duplicated per web worker)
  - long CPU-bound inference never blocks the gevent web workers

Each pipeline layer (OCR, face match, liveness, document-PAD) is added to
_run_pipeline as it's built (see ekyc/pipeline.py). The only job type this
module handles is process_session() — the full async pipeline, run once per
session after CAPTURE is complete.

Previously also handled check_id_side(): a synchronous fast per-side OCR/
document-PAD gate, run immediately after each ID side was captured. Removed
by explicit decision — on this CPU-only box, EasyOCR's detection+recognition
on up to 5 frames x 4 fields routinely took 40-60+ seconds and regularly
exceeded its own 60s RQ job_timeout, while the client's own poll loop gave
up after 30s regardless, surfacing as a generic "failed to fetch" error for
what was actually just a slow OCR call. The capture flow now shows the
customer their own just-captured photo for a manual clarity check instead
(static/ekyc/js/capture.js) and uploads it immediately — real OCR/PAD/
decision still happens here, async, via process_session. Nothing about the
eventual compliance decision changed; only WHEN a bad capture is caught
(officer review instead of capture time) — an explicit, accepted tradeoff,
not an oversight.
"""
import logging

logger = logging.getLogger(__name__)

_app = None


def _get_app():
    """Lazily build the Flask app once per worker process (for app/db context only)."""
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app


def warm_up():
    """Load the OCR, face and liveness models once at start-up, so the
    first customer after a restart does not wait ~40s for them."""
    import time
    started = time.time()
    try:
        from ekyc.ocr_engine import get_reader
        from ekyc.face_match import get_face_app
        from ekyc.face_liveness import get_models
        get_reader()
        get_face_app()
        get_models()
        try:
            from ekyc.ocr_pipeline import _get_yolo_session
            _get_yolo_session()
        except Exception:
            pass
        logger.info(f"eKYC models loaded in {time.time() - started:.1f}s")
    except Exception:
        logger.exception("eKYC model warm-up failed; models will load on the first job")


_models_loaded = [False]


def _set_threads():
    """Thread counts for OpenCV/torch, set when the models are first needed
    (importing torch at start-up alone costs ~300 MB of an idle worker)."""
    import os
    import cv2
    import torch
    threads = max(1, int(os.environ.get('EKYC_THREADS') or 3))
    cv2.setNumThreads(threads)
    torch.set_num_threads(threads)


def process_session(session_id):
    """RQ job entrypoint: run the full verification pipeline for one session."""
    if not _models_loaded[0]:
        _set_threads()
    _models_loaded[0] = True
    app = _get_app()
    with app.app_context():
        _process_session_impl(session_id)


def _process_session_impl(session_id):
    from models.ekyc import EkycSession

    session = EkycSession.get_by_id(session_id)
    if not session:
        logger.warning(f"eKYC session {session_id} not found, skipping job")
        return

    EkycSession.update_status(session_id, 'PROCESSING')
    try:
        # run_pipeline sets the session's final status itself
        # (DECISION_PENDING or NEEDS_REVIEW, see ekyc/pipeline.py) once the
        # decision and any screening hits are known — nothing to set here on
        # success, only on the exception path below.
        from ekyc.pipeline import run_pipeline
        run_pipeline(session_id)
    except Exception as exc:
        logger.exception(f"eKYC pipeline failed for session {session_id}")
        EkycSession.update_status(session_id, 'FAILED', error_message=str(exc))


if __name__ == '__main__':
    # SimpleWorker, not the default Worker: the default forks a fresh child
    # process per job for crash isolation, which silently defeated this
    # module's entire reason for existing as a dedicated process — every
    # job re-loaded EasyOCR/insightface/MiniFASNet from scratch in its own
    # short-lived child instead of reusing the already-warm singletons
    # cached in ekyc/ocr_engine.py, ekyc/face_match.py, ekyc/face_liveness.py
    # (each forked child starts with those module caches empty and dies
    # with them at the end of the job, so the *next* job forks from this
    # same cold parent again). SimpleWorker runs jobs inline in this one
    # long-lived process instead, so those caches actually stay warm across
    # jobs as originally intended. Trade-off: a hard crash in job code
    # takes the whole worker down rather than just one child — acceptable
    # here since systemd's Restart=always (see complynex-ekyc-worker.service)
    # already brings it back up, and a crash mid-job already requires
    # investigation regardless of which process it happened in.
    # EKYC_THREADS (default 3 on this 6-core box) replaces the earlier
    # hard pin to 1 thread, which made one session take over two minutes
    # (about 20s of OCR per frame). Memory does not grow with threads; the
    # unit's OMP/OPENBLAS/MKL env vars carry the same value.
    # Memory: models load on the first job (EKYC_WARMUP=0) and the process
    # exits after EKYC_IDLE_EXIT_SECONDS without a job once they are loaded;
    # systemd (Restart=always) starts a fresh, light process that waits for the
    # next job. The first session after a quiet period waits ~40 s longer for
    # its result (the customer already sees the "done" page immediately).
    import os
    import sys

    from rq.worker import SimpleWorker
    from ekyc.queue import _redis_connection

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    _get_app()  # loads .env (app.py) so queue_name() sees this instance's EKYC_QUEUE
    from ekyc.queue import queue_name
    if os.environ.get('EKYC_WARMUP', '1') == '1':
        _set_threads()
        warm_up()
        _models_loaded[0] = True
    idle = int(os.environ.get('EKYC_IDLE_EXIT_SECONDS') or 0) or None
    worker = SimpleWorker([queue_name()], connection=_redis_connection())
    logger.info(f"eKYC worker listening on queue '{queue_name()}'"
                + (f", releasing models after {idle}s idle" if idle else ''))
    while True:
        worker.work(with_scheduler=False, max_idle_time=idle)
        if not idle:
            break
        if _models_loaded[0]:
            logger.info(f"eKYC worker idle for {idle}s; exiting to release model memory")
            sys.exit(0)
        # nothing loaded yet: keep waiting with a fresh worker registration
        worker = SimpleWorker([queue_name()], connection=_redis_connection())
