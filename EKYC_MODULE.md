# eKYC Module

Electronic identity verification for ComplyNex: a customer-facing capture flow
(ID card + selfie video) feeds a server-side pipeline that validates the
identity, checks the selfie matches the ID, checks the person is physically
present (not a photo/replay/mask), checks the ID itself isn't a printed copy
or screen replay, and fuses all of that into one risk score and a
PASS/REVIEW/FAIL decision — which then auto-routes through ComplyNex's existing
sanctions/PEP screening engine.

This document is the single place that ties together the design decisions,
known limitations, and operational notes that are otherwise scattered across
the module's docstrings. Read the "Known limitations" section before trusting
this module's output for anything real.

## Why this module exists in this shape

The brief behind this build was explicit that no real Egyptian ID samples or
real spoof attempts exist yet, and that several layers (document
presentation-attack detection especially) are inherently research-grade
until real data is available. The module is built so it's honest about that:
every uncalibrated threshold says so in its docstring, every "not checked"
state (e.g. government verification) returns `None` rather than a fake
`False`, and every self-test is explicit about whether it proves "the code
path works" or "this is accurate against real-world input." Treat anything
below not flagged as a known limitation as solid; treat everything flagged
as a starting point pending real samples from Emam.

## Request flow

1. Staff creates a session (`ekyc.routes.new_session`) for a given document
   type and gets back a one-time `verify_url` to share with the customer.
2. Customer opens the link (`ekyc.routes.verify`, no login) — consent screen
   (bilingual, Arabic default) → capture screen → processing screen → done.
3. Capture (`static/ekyc/js/capture.js`, browser-side):
   - ID front/back: live camera with an immediately-enabled shutter button
     (no auto-detect gating — see "Known limitations"). One shutter press
     captures a quick burst (`BURST_FRAME_COUNT`, ~5 frames in well under a
     second — pure image capture, no OCR), and the customer reviews only
     the last (most-settled) frame to confirm it looks clear (or retakes)
     before anything uploads. `POST /ekyc/verify/<token>/check_side` saves
     the whole burst right away — no OCR/document-PAD gate at this point
     (see "Pipeline layers" below); the real OCR/PAD/decision still happens
     later, async, in step 5. The burst (not just the previewed frame)
     matters: `ekyc/document_pad.py`'s reflection-variance check needs >=3
     frames per side, and OCR consensus benefits from more than one.
   - Selfie: a short video, sampled client-side, with the user asked to
     tilt the ID card slightly during ITS capture — frames at different
     angles are what `ekyc/document_pad.py`'s reflection-variance check
     needs.
   - Runs an **active liveness challenge in-browser** via MediaPipe
     `FaceLandmarker`: a randomly chosen one of `blink` / `turn_head` /
     `smile`, tracked against the face mesh landmarks. The pass/fail result
     is reported to the server as-is, not independently re-verified
     server-side (see "Known limitations").
4. `POST /ekyc/verify/<token>/upload` stores the encrypted selfie frames
   (`ekyc/secure_storage.py`) and the active-liveness verdict, then enqueues
   the session onto the `ekyc` Redis queue (`ekyc/queue.py`) and marks it
   `QUEUED`. The processing page polls `/ekyc/verify/<token>/status`.
5. The dedicated `ekyc-worker` process (`ekyc/worker.py`, its own systemd
   service — see "Deployment") picks up the job and runs
   `ekyc.pipeline.run_pipeline`.
6. Staff view the result, document images (decrypted on the fly, never
   written to disk unencrypted), and full audit trail from the dashboard
   (`ekyc.routes.view_session` / `view_document`).

## Why a dedicated worker process

The pipeline loads several hundred MB of ML models (EasyOCR, insightface,
two MiniFASNet checkpoints) and does CPU-bound inference. Gunicorn's gevent
web workers are built for I/O concurrency — a blocking inference call there
would stall every other request on that worker, and each web worker would
otherwise load its own copy of every model. Instead the web process only
enqueues a Redis job (`ekyc/queue.py`, Redis **db 2**, isolated from the
dashboard cache on db 0 and the rate-limiter on db 1); a single `ekyc-worker`
process loads every model once and consumes the queue. See the docstrings in
`ekyc/queue.py` and `ekyc/worker.py`.

## Pipeline layers

`ekyc/pipeline.py:run_pipeline` orchestrates these, in order, logging an
audit-trail entry after each stage:

| Layer | Module | What it does |
|---|---|---|
| Card alignment | `document_capture.py` | Detects the ID card's quadrilateral boundary via Canny edges + contour approximation, warps it to a canonical fronto-parallel rectangle. Falls back to a plain resize (logged, lower confidence) if no boundary is found. |
| Field layout | `id_layout.py` | Fixed fractional crop boxes for each field on the canonical card (no ML object detector — Ultralytics YOLO is AGPL-3.0, incompatible with this project's licensing, and the Egyptian National ID has a fixed ID-1 layout anyway). **Uncalibrated against a real card — see "Known limitations".** |
| Capture-quality guard | `capture_quality.py` | Cheap per-frame checks (resolution, blur via Laplacian variance, brightness, glare) run before OCR; unusable frames are dropped before they can drag down the multi-frame consensus. |
| OCR | `ocr_engine.py`, `ocr_pipeline.py` | EasyOCR (Arabic + English, CPU). Each text-field crop is OCR'd both as-is and after `ocr_pipeline._clean_strip()` (grayscale → 2x upscale → adaptive Gaussian threshold, strips the card's printed background pattern from under the text), keeping whichever read scored higher confidence. Reads every usable frame, takes a per-field consensus across frames rather than trusting any single read; for the national ID field specifically, structurally-valid readings are preferred over invalid ones even if a garbage read scored higher OCR confidence. **This server-side read is the sole authority** — see "Browser OCR hint" below for what the browser does, which is never trusted here. |
| National ID decode/validate | `national_id.py` | Pure logic, no ML/IO. Decodes century/DOB/governorate/gender from the 14-digit number and cross-checks them against OCR'd fields elsewhere on the card. **Never validates the trailing check digit** — Egypt's civil registry has never published the algorithm, so a guessed one would risk false rejects or false confidence; that digit is extracted for display/audit only. |
| Face match | `face_match.py` | ArcFace via insightface's `buffalo_l` pack (SCRFD detector + w600k\_r50 recognition, ONNX/onnxruntime, CPU). Tries every selfie frame against the cropped ID photo, keeps the best cosine-similarity result. Threshold `MATCH_THRESHOLD = 0.42` is a community-benchmark starting point, **not calibrated against real Egyptian ID/selfie pairs.** |
| Passive liveness | `face_liveness.py` | Vendored Silent-Face-Anti-Spoofing (`ekyc/vendor/silent_face/`, Apache-2.0): two MiniFASNet checkpoints' summed 3-class softmax, decided by `argmax == real` exactly like the upstream reference, with the raw `P(real)` exposed as a calibrated score for fusion. Reuses insightface's detector instead of the vendor's own, so only one face detector loads per process. |
| Document presentation-attack detection (PAD) | `document_pad.py` | Two independent signals fused by simple weighted voting (no trained classifier — no labeled data exists to train one): **moire** (frequency-domain interference from photographing a screen, on raw frames) and **reflection/hologram variance** (per-pixel brightness variance across a perspective-corrected tilt sequence — genuine cards' security features change with viewing angle, flat printouts/screens don't). Explicitly "the hardest layer and research-grade" per the brief. |
| Active liveness | (client-evaluated; see capture flow above) | Pass/fail of the in-browser MediaPipe challenge, taken as reported. |
| Government verification | `gov_verification.py` | Pluggable stub, deliberately out of scope for this build (a real integration needs a licensed provider relationship and its own PII/data-protection review). Always returns `verified: None` — "not checked," never conflated with "checked and failed." |
| Risk fusion | `risk_engine.py` | Pure logic, no I/O. Turns each layer's output into a 0-100 sub-score, combines them via configurable weights into one risk score, and maps that to PASS / REVIEW / FAIL against two configurable thresholds. A failed OCR read (no usable ID frames at all) hard-overrides to FAIL regardless of how well other layers scored — there's no identity to weigh other signals against. |
| Screening hook | (in `pipeline.py`, calls `screening.complynex_engine`) | The OCR'd name (+ DOB/national ID) is run through ComplyNex's existing sanctions/PEP screening engine. A `CONFIRMED_HIT` or `POTENTIAL_MATCH` caps the decision at REVIEW even if every biometric/document signal scored perfectly — a compliance hit is never silently auto-passed. |

Risk-fusion weights and PASS/REVIEW thresholds live in the `ekyc_config`
table (`models.ekyc.EkycConfig`), editable at runtime without a deploy —
defaults are in `scripts/mig_ekyc_config.py`.

## Browser OCR hint (draft-only, never trusted)

`static/ekyc/js/capture.js`'s `readIdHint()` runs entirely in the browser,
front ID side only, right before that side's frames are uploaded:

1. **OpenCV.js** (self-hosted, `static/ekyc/vendor/opencv/opencv.js`) locates
   the card's quadrilateral boundary and perspective-warps it
   (`findCardCornersCv`/`warpCardCv`, the same Canny/contour/aspect-ratio
   algorithm as `ekyc/document_capture.py`'s `find_card_corners`), then
   slices and adaptive-thresholds the `national_id` and `full_name` strips
   (`cropRoiCv`/`cleanStripCv`, same boxes as `ekyc/id_layout.py`'s
   `FRONT_FIELDS`, same cleaning recipe as `ekyc/ocr_pipeline.py`'s
   `_clean_strip`). If no card boundary is found, it falls back to OCRing
   the whole captured frame instead — same graceful degradation as the
   server-side equivalent.
2. **Tesseract.js** (self-hosted, `static/ekyc/ocr/`, ara+eng, LSTM-only)
   reads each cleaned strip.
3. The whole attempt — both script loads, the OpenCV work, both OCR reads —
   is bounded by `OCR_HINT_TIMEOUT_MS`; on any failure or timeout
   `readIdHint()` resolves `null` and capture proceeds exactly as if no hint
   existed.

The result (`{national_id, full_name, raw_text, confidence, source}`) rides
along in the `check_side` upload as `ocr_hint`, gets persisted on the front
`ekyc_document` row (`client_ocr_hint` JSONB, `scripts/
mig_ekyc_ocr_hint.py`), and `ekyc/pipeline.py` adds it plus a
`national_id`-only agreement flag to `ekyc_result.raw_signals['ocr_hint']` /
`['ocr_hint_agrees_national_id']`. `templates/ekyc/review_detail.html`
surfaces an amber note **only on disagreement**, for the officer's
information.

**This is intentionally a one-way information flow.** Nothing computed in
the browser ever feeds `ocr_result`, `risk_engine.fuse_risk`, or the
decision — `ekyc/pipeline.py` always re-reads the same captured frames from
scratch via the server-side EasyOCR pipeline above, which remains the only
OCR result anything downstream acts on. Both libraries are self-hosted (not
CDN-loaded) so no ID image or extracted text ever has a third-party network
origin to reach, at any point.

## Data model

Four tables (`scripts/mig_ekyc_schema.py`), all additive (plus one new
`users.perm_ekyc` permission column):

- **`ekyc_session`** — one verification attempt: token, document type,
  status (`CREATED → CONSENT_GIVEN → CAPTURED → QUEUED → PROCESSING →
  COMPLETED|FAILED`, or `EXPIRED`), consent record, session/media expiry.
- **`ekyc_document`** — one captured media artifact (ID or selfie frame),
  pointing at its encrypted on-disk path; never the decrypted bytes.
- **`ekyc_result`** — the fused outcome: extracted fields, every layer's
  sub-score, the final decision + reasons, the screening result, and a
  `raw_signals` JSONB dump of every layer's full output for audit/debugging.
- **`ekyc_audit_log`** — append-only, session-scoped log of every consent,
  capture, decision, and **viewing** event (staff viewing a document image is
  logged regardless of permission level, since that's a biometric/PII access).

## Storage and encryption

Captured frames live under `ekyc_storage/` (outside `static/` and
`templates/`, mode `0700`, never web-served directly) encrypted at rest with
Fernet (`ekyc/secure_storage.py`). The encryption key is versioned via
`EKYC_ENCRYPTION_KEY_<version>` env vars (currently `v1`) so a future key
rotation can decrypt old files with the old key while writing new ones with
the new key — no flag day required. Staff viewing a document
(`ekyc.routes.view_document`) decrypts on the fly and streams it; a decrypted
copy is never written to disk.

## Retention

Per PDPL data-minimization, raw captured media is deleted
`EkycSession.DEFAULT_MEDIA_RETENTION_DAYS` (30) days after capture —
`scripts/ekyc_purge_expired.py`, run daily via the
`complynex-ekyc-purge.timer` systemd timer. Only the encrypted media file is
deleted (`ekyc_document.purged_at` is set); the `ekyc_document` row, the
`ekyc_result` decision, and the audit trail are kept indefinitely for
regulatory record-keeping — Law 80/2002-style retention obligations are
about the compliance record, not the biometric data itself.

## Deployment

- `complynex-ekyc-worker.service` — runs `python -m ekyc.worker` as its own
  long-lived process (`Restart=always`), separate from the Gunicorn web
  workers. Must be running for any session to ever leave `QUEUED`. Runs one
  job at a time (`rq.worker.SimpleWorker`, see its docstring) and pins
  `OMP_NUM_THREADS`/`OPENBLAS_NUM_THREADS`/`MKL_NUM_THREADS`/
  `NUMEXPR_NUM_THREADS` to `1` both via the unit's `Environment=` lines and
  (as a backstop) `cv2.setNumThreads(1)`/`torch.set_num_threads(1)` in
  `ekyc/worker.py`'s `__main__` — without this, EasyOCR/insightface/
  MiniFASNet's BLAS/OpenMP libraries would each size their thread pool to
  the host's core count, the real memory/CPU-thrash risk on a small VPS,
  not model weight size.
- `complynex-ekyc-purge.timer` / `.service` — daily retention purge, above.
- Both depend on Postgres and Redis being up first (see the unit files'
  `After=`).
- Required env vars: `EKYC_ENCRYPTION_KEY_V1` (Fernet key), the standard
  `POSTGRES_*` vars, `REDIS_URL` (defaults to `redis://localhost:6379/0`;
  the eKYC queue itself uses db 2 regardless of the path in this URL).

## Known limitations

These are the honest gaps, in rough order of how much they matter:

1. **No real Egyptian ID or selfie samples exist anywhere in this build.**
   Every self-test below uses synthetic data: a rendered mock ID card
   (`scripts/generate_synthetic_id.py`), insightface's own bundled
   multi-person sample photo, or Silent-Face-Anti-Spoofing's own published
   reference images. These prove the code paths work end-to-end; they prove
   nothing about real-world accuracy. **The single highest-value next input
   is 5-10 real (or realistic mock/expired) Egyptian ID photos with matching
   selfies from Emam.**
2. `id_layout.py`'s field crop boxes are best-effort estimates from the
   publicly known card layout, never measured against a real card.
3. `national_id.py` never validates the trailing check digit (no published
   algorithm exists to validate against) — `is_valid` rests only on century,
   calendar date, and governorate-code plausibility.
4. `face_match.py`'s `MATCH_THRESHOLD = 0.42` is a community-benchmark
   starting point, not tuned on real Egyptian ID/selfie pairs.
5. `document_pad.py`: the moire signal's threshold is validated against
   synthetic screen-replay simulations (reliably triggers on a fake, doesn't
   on a clean card) and is trusted enough to be the decisive signal alone.
   The reflection-variance threshold is an honest placeholder — only its
   *relative* ordering (genuine > flat) is validated, so it's weighted
   lower and can't independently fail a session.
6. **Active liveness has never been tested in a real browser** — the
   MediaPipe `FaceLandmarker` challenge logic in `capture.js` is written
   against MediaPipe's documented behavior but unverified end-to-end, and
   its pass/fail result is taken from the client as-is, not independently
   re-verified server-side.
7. AdaFace (the brief's stated primary face-match engine choice) was
   rejected for v1 on integration-risk grounds, not accuracy — both
   available distributions were unusable without vendoring undocumented or
   unverifiable code (see `face_match.py`'s docstring for specifics).
   ArcFace ships instead, the brief's own documented fallback. Revisit if
   real selfie testing shows ArcFace insufficient.
8. EasyOCR is the sole OCR engine — PaddleOCR (the brief's intended second
   engine for comparison) has no published wheel for this server's Python
   3.14 interpreter. There is no fallback if EasyOCR's Arabic accuracy
   proves insufficient on real samples; see that module's docstring for the
   isolated-venv option if that becomes necessary.
9. Government-database verification (`gov_verification.py`) is an
   intentional stub — out of scope for this build; wiring in a real
   provider (CBE Haweya or a licensed KYC vendor) needs its own
   contractual/data-protection decision first.
10. **A bad ID capture is no longer caught at capture time.** There used to
    be a synchronous per-side OCR/document-PAD gate (`ekyc.worker.
    check_id_side`) that rejected an unreadable/spoofed capture immediately.
    It was removed by explicit decision: on this CPU-only box it routinely
    took 40-60+ seconds and regularly exceeded its own 60s timeout,
    surfacing as a generic upload-failed error for what was really just a
    slow OCR call. The customer now judges their own photo's clarity
    (`static/ekyc/js/capture.js`'s image-preview step) and uploads
    immediately; a genuinely bad capture is now only caught later, by the
    real async OCR/PAD pipeline routing the session to officer review.
    Nothing about the eventual compliance decision changed — only *when* a
    bad capture is caught did.
11. The live on-screen card-detection overlay (`CardDetector`) no longer
    gates the shutter button — it's a visual aid only now (a real recording
    showed a clearly-framed card sitting in the guide for 80+ seconds
    without the detector ever firing). The shutter button is always
    enabled; the customer decides when to capture.

## Self-tests

Every layer that can be tested without real ID/selfie samples has its own
self-test script under `scripts/`, each independently runnable and each
exiting `0` on a full pass / `1` on any failure:

| Script | What it proves |
|---|---|
| `test_national_id.py` | Pure-logic decode/validate/cross-check correctness. |
| `test_risk_engine.py` | Pure-logic fusion math and screening-override behavior. |
| `test_capture_quality.py` | Synthetic blur/dark/overexposed/low-res frames are correctly rejected. |
| `test_ocr_pipeline.py` | Synthetic card → perspective correction → crop → OCR → decode plumbing works end-to-end; **not** real-world OCR accuracy. |
| `test_face_match.py` | insightface detection + ArcFace matching against a real (if unrelated-to-Egypt) photo with multiple distinct faces. |
| `test_face_liveness.py` | Against Silent-Face-Anti-Spoofing's own published real/fake reference images — the strongest validation available without real capture data. |
| `test_document_pad.py` | Synthetic moire/reflection simulations grounded in the underlying optical principles; proves the mechanics work, not real-world accuracy. |
| `test_pipeline_e2e.py` | Full `run_pipeline()` through a real database, two scenarios (matching and mismatched selfie), asserting on the final decision. Requires a reachable Postgres. |

Run all of them in one command with a consolidated report:

```
python scripts/run_ekyc_selftests.py
```

This is a thin aggregator (B9) — it adds no test logic of its own, it just
runs every script above as a subprocess and prints one pass/fail table
instead of eight. Use it after a deploy, a dependency bump, or any change to
a model/threshold, as a sanity check that nothing regressed. It is not a
substitute for real-sample validation of the items listed under "Known
limitations" above.
