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


def process_session(session_id):
    """RQ job entrypoint: run the full verification pipeline for one session."""
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
    # Backstop for the OMP_NUM_THREADS/OPENBLAS_NUM_THREADS/MKL_NUM_THREADS
    # env vars set in complynex-ekyc-worker.service: pin BLAS/OpenMP thread
    # pools to 1 in-process too, so this worker stays memory/CPU-safe on the
    # 8GB box even if a future deploy script drops those env vars. cv2 and
    # torch each maintain their own thread pool independently of the env
    # vars above, so both need pinning explicitly.
    import cv2
    import torch
    cv2.setNumThreads(1)
    torch.set_num_threads(1)

    from rq.worker import SimpleWorker
    from ekyc.queue import _redis_connection, QUEUE_NAME

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    worker = SimpleWorker([QUEUE_NAME], connection=_redis_connection())
    worker.work(with_scheduler=False)
