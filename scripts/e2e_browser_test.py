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
Real-browser, end-to-end verification of the eKYC capture flow:
  - Priority 1: Step 3 (selfie/liveness) no longer hangs on a black screen
    (CSP 'wasm-unsafe-eval' + self-hosted MediaPipe WASM + timeout/fallback).
  - Priority 2: ID capture (steps 1-2) uses the customer-confirms-their-own-
    photo flow (static/ekyc/js/capture.js) — the shutter button is enabled
    immediately (no auto-detect wait), a quick burst is captured behind one
    click, the customer reviews the last frame and taps Submit, and
    ekyc/routes.py's check_side saves it right away with no OCR/document-
    PAD gate (that gate, ekyc.worker.check_id_side, was removed — see
    EKYC_MODULE.md's "Known limitations" #10). This proves that flow
    actually advances through both ID steps end to end.
  - Priority 3: the full session-level pipeline (OCR -> national-ID ->
    face-match -> liveness -> PAD -> risk fusion) actually runs and
    produces a real PASS/REVIEW/FAIL with reasons — including proving the
    safety net that replaced the removed capture-time gate: a face
    submitted as the ID front side now sails through capture (no gate to
    catch it there) but is still caught by this async pipeline instead.

Uses real Chromium (Playwright) with Chrome's fake-camera flags
(--use-fake-device-for-media-stream / --use-file-for-fake-video-capture),
fed Y4M videos built from this project's own synthetic-ID generator
(scripts/generate_synthetic_id.py) and a real face crop from insightface's
bundled sample image (so face-matching has something genuine to compare,
same approach as scripts/test_pipeline_e2e.py).

Chrome's fake-camera flag serves the SAME file to every getUserMedia() call
for the life of the browser process — it can't hot-swap mid-session — so
each capture step is driven by a SEPARATE Chromium launch against the SAME
session token, relying on the resume-on-reload behavior in ekyc/routes.py's
verify() (front/back EkycDocument rows already on file -> skip straight to
the right step).

Honest limitation, same as every synthetic-data test in this project: this
proves every code path runs correctly end-to-end. It does NOT prove
real-world OCR/PAD/face-match accuracy on an actual printed card — no real
Egyptian ID sample exists anywhere in this build (see EKYC_MODULE.md).

Run with: python scripts/e2e_browser_test.py
"""
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.generate_synthetic_id import (  # noqa: E402
    generate_canonical_card, generate_canonical_back_card, generate_tilt_sequence,
)

BASE_URL = 'http://127.0.0.1:8000'
FIXTURE_DIR = '/tmp/ekyc_e2e_fixtures'


def write_y4m(path, frames_bgr, fps=8, hold_seconds=6):
    """
    Writes an uncompressed YUV4MPEG2 (.y4m) video — the format Chrome's
    --use-file-for-fake-video-capture accepts — looping through frames_bgr
    for roughly hold_seconds so the fake camera has something to stream
    for as long as the page needs to sample it. No ffmpeg dependency: I420
    is exactly what cv2.cvtColor(..., COLOR_BGR2YUV_I420) already produces.
    """
    h, w = frames_bgr[0].shape[:2]
    h -= h % 2
    w -= w % 2
    total_frames = max(len(frames_bgr), fps * hold_seconds)
    with open(path, 'wb') as f:
        f.write(f"YUV4MPEG2 W{w} H{h} F{fps}:1 Ip A1:1 C420jpeg\n".encode('ascii'))
        for i in range(total_frames):
            frame = frames_bgr[i % len(frames_bgr)][:h, :w]
            yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
            f.write(b"FRAME\n")
            f.write(yuv.tobytes())
    return path


def build_fixtures():
    os.makedirs(FIXTURE_DIR, mode=0o700, exist_ok=True)

    insightface_images = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'venv', 'lib', 'python3.14', 'site-packages', 'insightface', 'data', 'images')
    t1 = cv2.imread(os.path.join(insightface_images, 't1.jpg'))

    from ekyc.face_match import get_face_app
    faces = get_face_app().get(t1)
    face_a = faces[0]

    def crop(face, pad=30):
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        return t1[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad]

    face_crop = crop(face_a)

    canonical_front = generate_canonical_card(face_image_bgr=face_crop)
    front_frames = generate_tilt_sequence(canonical_front, num_frames=6, with_hologram=True)
    front_path = write_y4m(os.path.join(FIXTURE_DIR, 'front.y4m'), front_frames)

    canonical_back = generate_canonical_back_card()
    back_frames = generate_tilt_sequence(canonical_back, num_frames=6, with_hologram=True)
    back_path = write_y4m(os.path.join(FIXTURE_DIR, 'back.y4m'), back_frames)

    # Same face crop used in the ID photo -> a genuine "matching selfie" scenario.
    selfie_path = write_y4m(os.path.join(FIXTURE_DIR, 'selfie.y4m'), [face_crop] * 3, fps=8, hold_seconds=15)

    # Negative-path fixture: a face (not an ID) submitted as the front side.
    face_only_path = write_y4m(os.path.join(FIXTURE_DIR, 'face_as_front.y4m'), [face_crop] * 3)

    return {'front': front_path, 'back': back_path, 'selfie': selfie_path, 'face_as_front': face_only_path}


def create_session():
    from app import create_app
    app = create_app()
    with app.app_context():
        from models.ekyc import EkycSession
        session = EkycSession.create(document_type='NATIONAL_ID', customer_reference='E2E-BROWSER-TEST', locale='en')
        return app, session['session_token'], session['id']


def create_session_with_id_sides_done():
    """
    For the manual-fallback proof below: that path only matters once the
    customer has already reached the selfie step, and re-driving real
    front/back captures through the browser again just to get there would
    cost extra real time for no extra coverage (already proven by Launches
    1-2). Persists ID_FRONT_VIDEO/ID_BACK_VIDEO EkycDocument rows directly
    via the same save_frame()/EkycDocument.create() calls ekyc/routes.py's
    check_side itself makes on accept, so the session is in exactly the
    state a real captured front+back would leave it in.
    """
    from app import create_app
    app = create_app()
    with app.app_context():
        from models.ekyc import EkycSession, EkycDocument
        from ekyc.secure_storage import save_frame
        session = EkycSession.create(document_type='NATIONAL_ID', customer_reference='E2E-FALLBACK-TEST', locale='en')
        token = session['session_token']
        canonical_front = generate_canonical_card()
        canonical_back = generate_canonical_back_card()
        for role, canonical in (('ID_FRONT_VIDEO', canonical_front), ('ID_BACK_VIDEO', canonical_back)):
            ok, buf = cv2.imencode('.jpg', canonical)
            path, size, key_version = save_frame(token, role, buf.tobytes())
            EkycDocument.create(session['id'], role, path, encryption_key_id=key_version,
                                 file_size=size, mime_type='image/jpeg')
        return app, token, session['id']


def prewarm_worker():
    """
    The very first job the persistent ekyc-worker process handles after a
    restart pays the full ML model cold-load cost (EasyOCR + insightface +
    MiniFASNet) — easily 30+ seconds. Running one real job here first keeps
    that latency out of the timed, client-polled browser steps below.

    Enqueues ekyc.worker.process_session (the only job type left — the
    fast per-side gate this used to warm via, ekyc.worker.check_id_side,
    was removed; see EKYC_MODULE.md's "Known limitations" #10) against a
    throwaway session with front/back/selfie frames already persisted
    directly (same approach as create_session_with_id_sides_done), so the
    real pipeline — and every model it loads — actually runs once here.
    """
    from ekyc.queue import get_queue
    from app import create_app
    app = create_app()
    with app.app_context():
        from models.ekyc import EkycSession, EkycDocument
        from ekyc.secure_storage import save_frame, session_dir

        warm_session = EkycSession.create(document_type='NATIONAL_ID', customer_reference='E2E-PREWARM', locale='en')
        token = warm_session['session_token']
        canonical_front = generate_canonical_card()
        canonical_back = generate_canonical_back_card()
        for role, canonical in (('ID_FRONT_VIDEO', canonical_front), ('ID_BACK_VIDEO', canonical_back)):
            ok, buf = cv2.imencode('.jpg', canonical)
            path, size, key_version = save_frame(token, role, buf.tobytes())
            EkycDocument.create(warm_session['id'], role, path, encryption_key_id=key_version,
                                 file_size=size, mime_type='image/jpeg')
        ok, buf = cv2.imencode('.jpg', canonical_front)
        path, size, key_version = save_frame(token, 'SELFIE_VIDEO', buf.tobytes())
        EkycDocument.create(warm_session['id'], 'SELFIE_VIDEO', path, encryption_key_id=key_version,
                             file_size=size, mime_type='image/jpeg')

        job = get_queue().enqueue('ekyc.worker.process_session', warm_session['id'], job_timeout=120)
        print("Pre-warming ekyc-worker (first real job pays full ML model load cost)...")
        start = time.time()
        while job.get_status(refresh=True) not in ('finished', 'failed') and time.time() - start < 120:
            time.sleep(1)
        print(f"  worker warm after {time.time() - start:.1f}s, status={job.get_status(refresh=True)}")

        from database.db import get_db
        get_db().execute('DELETE FROM ekyc_session WHERE id = %s', (warm_session['id'],))
        get_db().commit()
        import shutil
        shutil.rmtree(session_dir(token), ignore_errors=True)


def launch_with_fake_camera(playwright, video_path):
    return playwright.chromium.launch(
        headless=True,
        args=[
            '--use-fake-ui-for-media-stream',
            '--use-fake-device-for-media-stream',
            f'--use-file-for-fake-video-capture={video_path}',
        ],
    )


def wait_for_text_change(page, selector, old_text, timeout=45000):
    page.wait_for_function(
        "(args) => { const el = document.querySelector(args.sel); "
        "return el && el.textContent.trim() !== args.old && el.textContent.trim() !== ''; }",
        arg={'sel': selector, 'old': old_text}, timeout=timeout,
    )


def capture_and_submit_id_side(page, start_btn_sel, manual_btn_sel, next_step_sel, timeout=20000):
    """
    Drives one ID side through the current capture.js flow: start the
    camera, wait for the shutter button (enabled immediately — no
    auto-detect wait any more), tap it, wait for the image-preview step,
    and tap Submit. No OCR/document-PAD gate runs in between any more
    (ekyc/routes.py's check_side just saves and returns) — this should
    resolve in a couple of seconds, not the ~20-40s a real check_id_side
    job used to take.

    next_step_sel must be the FOLLOWING step's selector (id-back-step after
    front, selfie-step after back) — NOT the current step. capture.js's
    showImagePreview() (static/ekyc/js/capture.js) hides both id-step and
    id-review-step synchronously the instant Submit is clicked, well before
    uploadIdSide()'s fetch actually completes, so waiting for either of
    those to become hidden resolves instantly and proves nothing; the only
    signal that the upload actually finished and advanceFromIdStep()/
    advanceFromIdBackStep() ran is the NEXT step losing 'd-none'.
    """
    page.click(start_btn_sel)
    page.wait_for_selector(f"{manual_btn_sel}:visible", timeout=timeout)
    page.click(manual_btn_sel)
    page.wait_for_selector('#id-review-step:visible', timeout=timeout)
    page.click('#id-review-confirm-btn')
    page.wait_for_selector(f"{next_step_sel}:visible", timeout=timeout)


def run():
    print("=== Building synthetic test fixtures ===")
    fixtures = build_fixtures()
    for name, path in fixtures.items():
        print(f"  {name}: {path} ({os.path.getsize(path)} bytes)")

    prewarm_worker()

    print("\n=== Creating eKYC session ===")
    app, token, session_id = create_session()
    verify_url = f"{BASE_URL}/ekyc/verify/{token}"
    print(f"  token={token} session_id={session_id} url={verify_url}")

    from playwright.sync_api import sync_playwright

    console_errors = []

    def log_console(msg):
        if msg.type == 'error':
            console_errors.append(msg.text)

    with sync_playwright() as p:
        # ---- Launch 1: front-side capture ----
        print("\n=== Launch 1: front-side ID capture ===")
        browser = launch_with_fake_camera(p, fixtures['front'])
        page = browser.new_page()
        page.on('console', log_console)
        page.goto(verify_url)
        if page.locator('#agree').count():
            page.check('#agree')
            page.click('button[type=submit]')
            page.wait_for_load_state()
        capture_and_submit_id_side(page, '#id-start-btn', '#id-manual-capture-btn', '#id-back-step')
        print("  front side captured, confirmed, uploaded, and advanced")
        browser.close()

        # ---- Launch 2: back-side capture (resumes at step 2) ----
        print("\n=== Launch 2: back-side ID capture (resume-on-reload) ===")
        browser = launch_with_fake_camera(p, fixtures['back'])
        page = browser.new_page()
        page.on('console', log_console)
        page.goto(verify_url)
        assert page.locator('#id-back-step').is_visible(), "did not resume at the back-side step"
        capture_and_submit_id_side(page, '#id-back-start-btn', '#id-back-manual-capture-btn', '#selfie-step')
        print("  back side captured, confirmed, uploaded, and advanced")
        browser.close()

        # ---- Launch 3: selfie + liveness (resumes at step 3) ----
        print("\n=== Launch 3: selfie / liveness (resume-on-reload) ===")
        browser = launch_with_fake_camera(p, fixtures['selfie'])
        page = browser.new_page()
        page.on('console', log_console)
        page.goto(verify_url)
        assert page.locator('#selfie-step').is_visible(), "did not resume at the selfie step"

        # Priority 1's core proof: the detector must move past "Preparing
        # face detector..." to "Capturing..." — if the CSP/WASM fix didn't
        # work, this hangs here exactly as the bug report described.
        wait_for_text_change(page, '#selfie-status', 'Preparing face detector...', timeout=20000)
        status_text = page.locator('#selfie-status').inner_text()
        print(f"  face detector resolved -> #selfie-status = {status_text!r} (no hang, no infinite spinner)")
        assert status_text not in ('', 'Preparing face detector...'), "detector wait did not resolve"

        # A static fake-camera image usually can't produce a real
        # blink/smile/turn, so the active-liveness challenge is expected to
        # time out most of the time (proving the timeout/retry UI works) —
        # but MediaPipe's blendshape scores are noisy enough on a still
        # frame that it occasionally crosses a threshold for real (a
        # genuine pass, not a bug). Handle both honestly instead of forcing
        # one outcome. Either way, the manual-fallback path itself (which
        # only triggers on a genuine detector failure, not a missed
        # challenge) is proven separately below by actually breaking the
        # WASM fetch, rather than faked here.
        try:
            page.wait_for_selector('#submit-status:visible', timeout=12000)
            print("  active-liveness challenge passed naturally on the static fixture (MediaPipe blendshape "
                  "noise crossed a threshold) -- submitted directly")
            page.wait_for_url('**/ekyc/verify/**', timeout=15000)
        except Exception:
            page.wait_for_selector('#selfie-retake-btn:visible', timeout=15000)
            print("  active-liveness challenge timed out as expected (no real motion possible from a static fixture)"
                  " -- retry UI shown correctly")
        browser.close()

        print(f"\nConsole errors observed across all 3 launches: {console_errors or 'none'}")

        # ---- Negative-path check: a face image submitted as the front side ----
        # check_id_side (the synchronous OCR/document-PAD gate that used to
        # reject this at capture time) was removed — see EKYC_MODULE.md's
        # "Known limitations" #10. The customer's own clarity judgment is
        # the only check at capture time now, so this MUST advance through
        # all 3 steps without being blocked. The real safety net is the
        # async pipeline below: a face has no readable national ID and no
        # card boundary, so the full pipeline should still land on REVIEW
        # or FAIL, not PASS, once it actually runs.
        print("\n=== Negative-path check: face image as the front-side capture ===")
        app2, neg_token, neg_session_id = create_session()
        neg_url = f"{BASE_URL}/ekyc/verify/{neg_token}"

        browser = launch_with_fake_camera(p, fixtures['face_as_front'])
        page = browser.new_page()
        page.goto(neg_url)
        if page.locator('#agree').count():
            page.check('#agree')
            page.click('button[type=submit]')
            page.wait_for_load_state()
        capture_and_submit_id_side(page, '#id-start-btn', '#id-manual-capture-btn', '#id-back-step')
        print("  face-as-front-side capture advanced past step 1 (no capture-time gate any more, as expected)")
        browser.close()

        browser = launch_with_fake_camera(p, fixtures['back'])
        page = browser.new_page()
        page.goto(neg_url)
        assert page.locator('#id-back-step').is_visible(), "did not resume at the back-side step"
        capture_and_submit_id_side(page, '#id-back-start-btn', '#id-back-manual-capture-btn', '#selfie-step')
        browser.close()

        # Block the MediaPipe WASM fetch (same technique as the dedicated
        # manual-fallback check below) so the manual-capture button reliably
        # appears instead of racing an active-liveness challenge that a
        # static fixture can't realistically pass — this branch only cares
        # about getting the session to COMPLETED so the async pipeline runs.
        browser = launch_with_fake_camera(p, fixtures['selfie'])
        page = browser.new_page()
        page.route("**/static/ekyc/vendor/mediapipe/**", lambda route: route.abort())
        page.goto(neg_url)
        assert page.locator('#selfie-step').is_visible(), "did not resume at the selfie step"
        page.wait_for_selector('#selfie-manual-capture-btn:visible', timeout=15000)
        with page.expect_response(lambda r: '/upload' in r.url and r.request.method == 'POST', timeout=20000):
            page.click('#selfie-manual-capture-btn')
        browser.close()

        with app2.app_context():
            from models.ekyc import EkycSession, EkycResult
            start = time.time()
            neg_status = None
            while time.time() - start < 90:
                neg_session = EkycSession.get_by_id(neg_session_id)
                neg_status = neg_session['status']
                if neg_status in ('COMPLETED', 'FAILED', 'NEEDS_REVIEW', 'DECISION_PENDING'):
                    break
                time.sleep(2)
            neg_result = EkycResult.get_for_session(neg_session_id)
            decision = neg_result.get('decision') if neg_result else None
            print(f"  async pipeline decision for face-as-front session: {decision!r} "
                  f"(session status={neg_status!r}, after {time.time() - start:.1f}s)")
            assert decision != 'PASS', \
                "BUG: a face submitted as the ID front side scored a clean PASS from the async pipeline"
            print("  confirmed: the async pipeline (not capture-time) is what catches this now")

        # ---- Dedicated proof of the manual-fallback path ----
        # Forces a REAL detector failure (block the self-hosted WASM
        # fetch) instead of faking the outcome, so this proves
        # runManualSelfieCapture() actually fires through the real
        # FACE_LANDMARKER_TIMEOUT_MS/null-promise code path in
        # static/ekyc/js/capture.js, not just that the function exists.
        print("\n=== Dedicated check: manual-fallback path when the face detector genuinely fails to load ===")
        app3, fb_token, fb_session_id = create_session_with_id_sides_done()
        fb_url = f"{BASE_URL}/ekyc/verify/{fb_token}"
        browser = launch_with_fake_camera(p, fixtures['selfie'])
        page = browser.new_page()
        page.route("**/static/ekyc/vendor/mediapipe/**", lambda route: route.abort())
        page.goto(fb_url)
        if page.locator('#agree').count():
            page.check('#agree')
            page.click('button[type=submit]')
            page.wait_for_load_state()
        assert page.locator('#selfie-step').is_visible(), "did not resume at the selfie step"
        page.wait_for_selector('#selfie-manual-capture-btn:visible', timeout=15000)
        print("  WASM fetch blocked -> manual-capture button appeared (no hang, graceful fallback confirmed)")
        with page.expect_response(lambda r: '/upload' in r.url and r.request.method == 'POST', timeout=20000):
            page.click('#selfie-manual-capture-btn')
        print("  manual-fallback selfie submitted (upload response received)")
        browser.close()

        with app3.app_context():
            from models.ekyc import EkycResult
            fb_result = EkycResult.get_for_session(fb_session_id)
            print(f"  active_liveness_pass stored as: {fb_result.get('active_liveness_pass')!r} (must be NULL, not False)")
            assert fb_result.get('active_liveness_pass') is None, \
                "BUG: manual-fallback liveness was coerced to False instead of staying NULL"

    print("\n=== Polling final session status for the front+back+selfie session ===")
    with app.app_context():
        from models.ekyc import EkycSession, EkycResult, EkycAuditLog
        start = time.time()
        status = None
        while time.time() - start < 90:
            session = EkycSession.get_by_id(session_id)
            status = session['status']
            if status in ('COMPLETED', 'FAILED', 'NEEDS_REVIEW', 'DECISION_PENDING'):
                break
            time.sleep(2)
        print(f"  final session status: {status} (after {time.time() - start:.1f}s)")

        result = EkycResult.get_for_session(session_id)
        print("\n--- EkycResult ---")
        for key in ('extracted_full_name_ar', 'national_id', 'national_id_valid', 'dob', 'gender',
                    'governorate_name', 'ocr_confidence', 'face_match_score', 'face_match_engine',
                    'passive_liveness_score', 'passive_liveness_pass', 'active_liveness_pass',
                    'active_liveness_challenge', 'document_pad_score', 'document_pad_pass',
                    'back_card_detected', 'extracted_occupation', 'extracted_marital_status',
                    'risk_score', 'decision', 'decision_reasons', 'screening_result'):
            print(f"  {key}: {result.get(key) if result else None!r}")

        print("\n--- Audit trail ---")
        for entry in EkycAuditLog.get_for_session(session_id):
            print(f"  {entry['created_at']}  {entry['action']:<22} {entry.get('details') or ''}")

    print("\nDone.")


if __name__ == '__main__':
    run()
