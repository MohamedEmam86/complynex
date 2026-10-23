// eKYC capture flow: ID card frames (front + back, NATIONAL_ID only) and
// selfie frames with an active liveness challenge (MediaPipe Face Mesh,
// running in-browser).
//
// ⚠️ UNTESTED IN A REAL BROWSER. Written against MediaPipe's documented
// Tasks Vision API and the standard 468-point face mesh landmark
// topology, but this server has no camera/display to exercise it
// against. Calibration constants below (BLINK_*, SMILE_THRESHOLD,
// TURN_RATIO_DEVIATION, QUALITY_*, *_INTERVAL_MS) are best-effort defaults
// — expect to tune them after a real live test. See EKYC_MODULE.md.

const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]').content;
const captureRoot = document.getElementById('ekyc-capture-root');
const LOCALE = captureRoot.dataset.locale;
const UPLOAD_URL = captureRoot.dataset.uploadUrl;
const DOCUMENT_TYPE = captureRoot.dataset.documentType;
const CHECK_SIDE_URL = captureRoot.dataset.checkSideUrl;
// Set server-side from EkycDocument rows already on file for this session
// (see ekyc/routes.py's verify()) — lets a reloaded/resumed page skip
// straight to the first not-yet-passed step instead of always restarting
// at step 1.
const FRONT_DONE = captureRoot.dataset.frontDone === 'true';
const BACK_DONE = captureRoot.dataset.backDone === 'true';

// Only NATIONAL_ID has a calibrated back-side field layout
// (ekyc/id_layout.py's BACK_FIELDS) — see ekyc/routes.py's
// BACK_SIDE_REQUIRED_TYPES, which this must stay in sync with.
const BACK_SIDE_REQUIRED = DOCUMENT_TYPE === 'NATIONAL_ID';

const MODEL_URL = '/static/ekyc/models/face_landmarker.task';
// Self-hosted under /static (see static/ekyc/vendor/mediapipe/) rather than
// fetched from jsdelivr: the WASM compile this triggers needs
// 'wasm-unsafe-eval' in the page's CSP regardless of origin, and serving it
// same-origin avoids depending on a third-party CDN being reachable for a
// step that's already hard to debug when it fails.
const VISION_WASM_URL = '/static/ekyc/vendor/mediapipe';
const VISION_BUNDLE_URL = '/static/ekyc/vendor/mediapipe/vision_bundle.mjs';
const FACE_LANDMARKER_TIMEOUT_MS = 6000;
const UPLOAD_TIMEOUT_MS = 90000;

// Cheap client-side pre-filter thresholds (0-255 brightness, Laplacian-
// variance sharpness on a 64px-wide downsample) — loose on purpose, this
// only needs to catch "nothing usable at all" (lens cap, pointed at a
// blank wall, total darkness), not replace ekyc/capture_quality.py's
// proper per-frame guard, which still runs server-side on the full-res
// frame before OCR.
const QUALITY_MIN_BRIGHTNESS = 25;
const QUALITY_MAX_BRIGHTNESS = 240;
const QUALITY_MIN_SHARPNESS = 12;

// ID-card live detection + per-side backend validation (see
// ekyc.worker.check_id_side / ekyc/routes.py's check_side route). Matches
// ekyc/id_layout.py's CARD_ASPECT_RATIO so the on-screen guide lines up
// with the field crop boxes the backend uses once a card is captured.
const CARD_ASPECT_RATIO = 85.60 / 53.98;
const GUIDE_WIDTH_FRACTION = 0.84;
const DETECTOR_GRID_WIDTH = 160;
const DETECTOR_SAMPLE_INTERVAL_MS = 130;
// Best-effort, uncalibrated against a real card — same honest caveat as
// every other heuristic threshold in this project (see EKYC_MODULE.md).
// Only colors the live guide overlay (startLiveGuide) — never gates
// capture; the shutter button is enabled immediately regardless. Generous
// on purpose: a user framing a real card rarely matches an on-screen guide
// pixel-for-pixel, so this searches for the card wherever it actually is
// rather than assuming it sits exactly on the guide's drawn border.
const DETECTOR_SEARCH_MARGIN_FRACTION = 0.04;
const MIN_CARD_AREA_FRACTION = 0.12;
const MAX_CARD_AREA_FRACTION = 0.95;
const CARD_ASPECT_TOLERANCE = 0.45; // fractional deviation from CARD_ASPECT_RATIO still accepted (tilt/perspective)
const EDGE_PEAK_MIN_ABS = 6;
const EDGE_PEAK_TO_MEDIAN_RATIO = 2.2;
// A shutter press captures this many frames in quick succession (not just
// one) — see runIdSideCapture's comment for why: the async pipeline's OCR
// consensus and document-PAD reflection-variance check both need multiple
// frames, even though the customer only ever judges the last one.
const BURST_FRAME_COUNT = 5;
const BURST_INTERVAL_MS = 130;
// Only counts genuine upload failures (network/server) — a customer
// choosing to retake their own photo after the clarity check
// (showImagePreview) costs nothing server-side any more and isn't capped.
const MAX_RETRIES_PER_SIDE = 10;

// Self-hosted browser OCR hint: OpenCV.js (static/ekyc/vendor/opencv/) does
// the same perspective-correction + ROI-slicing + adaptive-threshold
// cleaning ekyc/document_capture.py + ekyc/id_layout.py + ekyc/
// ocr_pipeline.py already do server-side, then Tesseract.js
// (static/ekyc/ocr/, ara+eng) reads each cleaned strip. This is STILL a
// throwaway, low-bar draft read of the front-side ID only: it never gates
// capture and is never trusted server-side — ekyc.ocr_pipeline re-reads
// the same captured frame from scratch via the existing check_side worker
// job, which remains the sole authority an officer's decision depends on
// (see EKYC_MODULE.md). Both libraries are self-hosted, not loaded from a
// CDN, so no ID image/text data ever has a third-party origin to reach at
// runtime.
const OCR_HINT_BASE_URL = '/static/ekyc/ocr/';
const OCR_HINT_SCRIPT_URL = OCR_HINT_BASE_URL + 'tesseract.min.js';
const OPENCV_SCRIPT_URL = '/static/ekyc/vendor/opencv/opencv.js';
// One bound on the whole hint attempt (script loads + CV work + OCR) —
// first call on a cold cache pays the ~11MB OpenCV.js + ~8MB Tesseract.js
// core/traineddata download, later attempts (retakes) hit the browser
// cache and finish well inside this budget. Either way, timing out just
// means readIdHint() resolves null — see its docstring. This bounds the
// hint's OWN background work, not how long capture waits on it — see
// HINT_GRACE_MS below, which is the actual cap on added capture latency.
const OCR_HINT_TIMEOUT_MS = 6000;
// readIdHint() is kicked off in the background as soon as the first burst
// frame is captured (runIdSideCapture), overlapping with the rest of the
// burst loop and the real upload for free. At submission time, capture
// waits at most this long for it to finish — never the full
// OCR_HINT_TIMEOUT_MS — before giving up and submitting without a hint.
// The real OCR is server-side and authoritative regardless (see
// EKYC_MODULE.md's "Browser OCR hint" section), so a missing hint costs
// nothing but the officer's optional cross-reference for this one attempt.
const HINT_GRACE_MS = 400;

// Mirrors ekyc/id_layout.py's canonical card size + FRONT_FIELDS boxes
// exactly, so the client-side warp/crop lines up with what the server
// pipeline does. Same calibration-warning caveat as that file: not
// measured against a real card yet.
const HINT_CANONICAL_WIDTH = 1011;
const HINT_CANONICAL_HEIGHT = Math.round(HINT_CANONICAL_WIDTH / CARD_ASPECT_RATIO);
const HINT_NATIONAL_ID_BOX = [0.34, 0.72, 0.98, 0.84];
const HINT_FULL_NAME_BOX = [0.34, 0.18, 0.97, 0.36];
// Mirrors ekyc/document_capture.py's find_card_corners() constants exactly.
const HINT_MIN_CARD_AREA_FRACTION = 0.15;
const HINT_MAX_CARD_AREA_FRACTION = 0.98;
const HINT_CARD_MIN_ASPECT = 1.2;
const HINT_CARD_MAX_ASPECT = 2.2;
// Mirrors ekyc/ocr_pipeline.py's _clean_strip() constants exactly.
const HINT_STRIP_UPSCALE_FACTOR = 2;
const HINT_ADAPTIVE_BLOCK_SIZE = 31;
const HINT_ADAPTIVE_C = 11;
const AR_INDIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';

const SELFIE_FRAME_INTERVAL_MS = 200;
const CHALLENGE_TIMEOUT_MS = 10000;
const DETECTION_LOOP_DELAY_MS = 50;
// Android Chrome can briefly fail or hand back black frames if a new
// getUserMedia request lands before the camera HAL finishes releasing the
// previous stream — this gives it a moment between switching cameras
// (ID front -> back -> selfie).
const CAMERA_SWITCH_DELAY_MS = 400;

// Standard MediaPipe 468-point face mesh landmark indices (stable, widely
// documented topology): nose tip and the outer corner of each eye.
const LANDMARK_NOSE_TIP = 1;
const LANDMARK_RIGHT_EYE_OUTER = 33;
const LANDMARK_LEFT_EYE_OUTER = 263;

const BLINK_CLOSE_THRESHOLD = 0.5;
const BLINK_OPEN_THRESHOLD = 0.3;
const SMILE_THRESHOLD = 0.4;
const TURN_RATIO_DEVIATION = 0.25; // fractional change from the calibrated baseline ratio

const STRINGS = {
  ar: {
    cameraError: 'تعذر الوصول إلى الكاميرا. يرجى التحقق من الأذونات والمحاولة مرة أخرى.',
    cameraErrorInsecure: 'لا يمكن فتح الكاميرا لأن هذا الرابط غير محمي (HTTPS). يرجى التواصل مع الجهة المرسلة للحصول على رابط صحيح.',
    cameraErrorDenied: 'تم رفض إذن الكاميرا! يرجى السماح بالوصول إلى الكاميرا من إعدادات المتصفح، ثم اضغط "إعادة المحاولة". إذا كنت قد فتحت هذا الرابط من داخل تطبيق آخر (تيليجرام، واتساب، مسنجر)، فافتحه في كروم أو سفاري مباشرة.',
    cameraErrorBlocked: 'هذا المتصفح يحظر الكاميرا لهذا الموقع بشكل دائم، ولهذا لا يظهر أي طلب إذن. لإصلاح ذلك: اضغط على أيقونة القفل 🔒 المجاورة لعنوان الموقع في أعلى المتصفح ← الأذونات (Permissions) ← الكاميرا ← اختر "السماح" (Allow)، ثم أعد تحميل الصفحة واضغط "إعادة المحاولة".',
    cameraErrorNotFound: 'لم يتم العثور على كاميرا على هذا الجهاز. يرجى التأكد من توصيل كاميرا والمحاولة مرة أخرى.',
    cameraErrorInUse: 'الكاميرا قيد الاستخدام من برنامج آخر. يرجى إغلاق التطبيقات الأخرى التي تستخدم الكاميرا والمحاولة مرة أخرى.',
    cameraErrorUnsupported: 'هذا المتصفح لا يدعم الوصول إلى الكاميرا، وقد يكون ذلك بسبب فتح الرابط داخل تطبيق آخر. يرجى نسخ الرابط وفتحه مباشرة في كروم أو سفاري.',
    cameraRetry: 'إعادة المحاولة',
    captureRetryNeeded: 'لم نتمكن من الحصول على صورة واضحة. تأكد من وضع البطاقة بشكل مسطح داخل الإطار مع إضاءة جيدة، ثم حاول مرة أخرى.',
    captureBlankRetry: 'الصورة جاءت غير واضحة، جارٍ إعادة المحاولة...',
    idScanning: 'ضع بطاقة الهوية داخل الإطار...',
    verifying: 'جارٍ التحقق...',
    idTooManyAttempts: 'عدد كبير جدًا من المحاولات الفاشلة. يرجى التواصل مع الدعم للحصول على رابط تحقق جديد.',
    stepLabel: 'الخطوة',
    idFrontTitle: 'تصوير الهوية (الجانب الأمامي)',
    idBackTitle: 'تصوير الهوية (الجانب الخلفي)',
    selfieTitle: 'التحقق من الوجه',
    idInstruction: 'ضع بطاقة الهوية داخل الإطار وأمل ببطء من جانب إلى آخر',
    idBackInstruction: 'اقلب البطاقة وضع الجانب الخلفي داخل الإطار وأمل ببطء من جانب إلى آخر',
    capturing: 'جاري التصوير...',
    idDone: 'تم تصوير الهوية بنجاح',
    retake: 'إعادة التصوير',
    loadingDetector: 'جاري تجهيز كاشف الوجه...',
    challengeBlink: 'يرجى الرّمش',
    challengeTurn: 'يرجى تحريك رأسك إلى أحد الجانبين ثم العودة',
    challengeSmile: 'يرجى الابتسام',
    challengePassed: 'تم بنجاح!',
    challengeTimeout: 'لم يتم رصد الحركة، يرجى المحاولة مرة أخرى',
    manualCaptureInstruction: 'يرجى النظر إلى الكاميرا والضغط على زر التصوير',
    manualCaptureButton: 'تصوير',
    uploading: 'جاري الإرسال...',
    uploadError: 'حدث خطأ أثناء الإرسال. يرجى المحاولة مرة أخرى.',
    start: 'بدء التصوير',
    copyLink: 'نسخ الرابط',
    linkCopied: 'تم نسخ الرابط!',
    reviewHeading: 'هل الصورة واضحة؟',
    reviewNotice: 'تأكد أن جميع البيانات على البطاقة واضحة وغير مموهة وغير ناقصة. في حالة عدم وضوح الصورة، قد يتم رفض الطلب لاحقًا من قبل فريق الامتثال.',
    reviewConfirm: 'إرسال والمتابعة',
    reviewRetake: 'إعادة التصوير',
  },
  en: {
    cameraError: 'Could not access the camera. Please check permissions and try again.',
    cameraErrorInsecure: 'The camera can\'t open because this link isn\'t secure (HTTPS). Please ask for a valid link.',
    cameraErrorDenied: 'Camera permission was denied. Please allow camera access in your browser settings, then tap "Retry". If you opened this link inside another app (Telegram, WhatsApp, Messenger), open it in Chrome or Safari directly instead.',
    cameraErrorBlocked: 'Your browser has permanently blocked the camera for this site, which is why no permission prompt appears. To fix it: tap the lock icon 🔒 next to the address bar at the top of the browser → Permissions → Camera → choose "Allow", then reload the page and tap "Retry".',
    cameraErrorNotFound: 'No camera was found on this device. Please make sure a camera is connected and try again.',
    cameraErrorInUse: 'The camera is being used by another app. Please close other apps using the camera and try again.',
    cameraErrorUnsupported: 'This browser doesn\'t support camera access, possibly because this link was opened inside another app. Please copy the link and open it directly in Chrome or Safari.',
    cameraRetry: 'Retry',
    captureRetryNeeded: 'We couldn\'t get a clear shot. Make sure the card is flat inside the frame with good lighting, then try again.',
    captureBlankRetry: 'That capture came out blank — retrying...',
    idScanning: 'Place your ID card inside the frame...',
    verifying: 'Verifying...',
    idTooManyAttempts: 'Too many failed attempts. Please contact support for a new verification link.',
    stepLabel: 'Step',
    idFrontTitle: 'Capture the front of your ID',
    idBackTitle: 'Capture the back of your ID',
    selfieTitle: 'Face verification',
    idInstruction: 'Place your ID inside the frame and slowly tilt it side to side',
    idBackInstruction: 'Flip the card and place the back side inside the frame, then slowly tilt it side to side',
    capturing: 'Capturing...',
    idDone: 'ID captured successfully',
    retake: 'Retake',
    loadingDetector: 'Preparing face detector...',
    challengeBlink: 'Please blink',
    challengeTurn: 'Please turn your head to one side and back',
    challengeSmile: 'Please smile',
    challengePassed: 'Done!',
    challengeTimeout: 'No motion detected, please try again',
    manualCaptureInstruction: 'Please look at the camera and tap the capture button',
    manualCaptureButton: 'Capture',
    uploading: 'Uploading...',
    uploadError: 'Something went wrong while uploading. Please try again.',
    start: 'Start capture',
    copyLink: 'Copy link',
    linkCopied: 'Link copied!',
    reviewHeading: 'Is the image clear?',
    reviewNotice: 'Make sure every detail on the card is sharp, fully visible, and not blurry. If the image isn\'t clear, your application may be rejected later during compliance review.',
    reviewConfirm: 'Submit & continue',
    reviewRetake: 'Retake',
  },
};
const T = STRINGS[LOCALE] || STRINGS.en;
const CHALLENGE_LABELS = { blink: T.challengeBlink, turn_head: T.challengeTurn, smile: T.challengeSmile };

const idVideo = document.getElementById('id-video');
const idCanvas = document.getElementById('id-canvas');
const idGuideCanvas = document.getElementById('id-guide-canvas');
const idStatusEl = document.getElementById('id-status');
const idRetryStatusEl = document.getElementById('id-retry-status');
const idManualBtn = document.getElementById('id-manual-capture-btn');
const idStartBtn = document.getElementById('id-start-btn');
const idStepEl = document.getElementById('id-step');
const idStepHeadingEl = document.getElementById('id-step-heading');

const idBackVideo = document.getElementById('id-back-video');
const idBackCanvas = document.getElementById('id-back-canvas');
const idBackGuideCanvas = document.getElementById('id-back-guide-canvas');
const idBackStatusEl = document.getElementById('id-back-status');
const idBackRetryStatusEl = document.getElementById('id-back-retry-status');
const idBackManualBtn = document.getElementById('id-back-manual-capture-btn');
const idBackStartBtn = document.getElementById('id-back-start-btn');
const idBackStepEl = document.getElementById('id-back-step');
const idBackStepHeadingEl = document.getElementById('id-back-step-heading');

const idReviewStepEl = document.getElementById('id-review-step');
const idReviewHeadingEl = document.getElementById('id-review-heading');
const idReviewNoticeEl = document.getElementById('id-review-notice');
const idReviewImageEl = document.getElementById('id-review-image');
const idReviewRetakeBtn = document.getElementById('id-review-retake-btn');
const idReviewConfirmBtn = document.getElementById('id-review-confirm-btn');

const selfieVideo = document.getElementById('selfie-video');
const selfieCanvas = document.getElementById('selfie-canvas');
const selfieStatusEl = document.getElementById('selfie-status');
const selfieChallengeEl = document.getElementById('selfie-challenge');
const selfieStepEl = document.getElementById('selfie-step');
const selfieStepHeadingEl = document.getElementById('selfie-step-heading');
const selfieRetakeBtn = document.getElementById('selfie-retake-btn');
const selfieManualBtn = document.getElementById('selfie-manual-capture-btn');

const submitStepEl = document.getElementById('submit-step');
const submitStatusEl = document.getElementById('submit-status');
const errorEl = document.getElementById('capture-error');
const webviewBanner = document.getElementById('webview-banner');
const copyLinkBtn = document.getElementById('copy-link-btn');

// In-app browsers (Facebook/Messenger, Instagram, Twitter/X, Telegram,
// WhatsApp, TikTok, Snapchat) embed a stripped-down webview that often
// blocks or silently no-ops getUserMedia regardless of any Permissions-
// Policy header — the only real fix is opening the link in a full browser.
const IN_APP_UA_PATTERNS = [
  /FBAN|FBAV/i, // Facebook / Messenger
  /Instagram/i,
  /Twitter/i,
  /Telegram/i,
  /WhatsApp/i,
  /musical_ly|TikTok/i,
  /Snapchat/i,
];

function isInAppBrowser() {
  return IN_APP_UA_PATTERNS.some((re) => re.test(navigator.userAgent || ''));
}

async function copyPageLink() {
  try {
    await navigator.clipboard.writeText(window.location.href);
  } catch (e) {
    // Clipboard API is unavailable in some stripped-down in-app webviews;
    // fall back to a temporary selectable field the user can copy from.
    const input = document.createElement('input');
    input.value = window.location.href;
    input.style.position = 'fixed';
    input.style.opacity = '0';
    document.body.appendChild(input);
    input.select();
    try { document.execCommand('copy'); } catch (e2) { /* no-op */ }
    document.body.removeChild(input);
  }
  copyLinkBtn.textContent = T.linkCopied;
  setTimeout(() => { copyLinkBtn.textContent = T.copyLink; }, 2000);
}

function initWebviewBanner() {
  if (!isInAppBrowser()) return;
  webviewBanner.classList.remove('d-none');
  copyLinkBtn.textContent = T.copyLink;
  copyLinkBtn.addEventListener('click', copyPageLink);
}

function setStepHeadings() {
  selfieManualBtn.textContent = T.manualCaptureButton;
  idManualBtn.textContent = T.manualCaptureButton;
  idBackManualBtn.textContent = T.manualCaptureButton;
  idStepHeadingEl.textContent = `${T.stepLabel} 1: ${T.idFrontTitle}`;
  if (BACK_SIDE_REQUIRED) {
    idBackStepHeadingEl.textContent = `${T.stepLabel} 2: ${T.idBackTitle}`;
    selfieStepHeadingEl.textContent = `${T.stepLabel} 3: ${T.selfieTitle}`;
  } else {
    selfieStepHeadingEl.textContent = `${T.stepLabel} 2: ${T.selfieTitle}`;
  }
}

let selfieFrames = [];
let livenessResult = { challenge: null, passed: false };
let idStream = null;
let idBackStream = null;
let selfieStream = null;
const sideAttempts = { front: 0, back: 0 };

// Kicked off immediately at page load, in parallel with the ID (and back-
// side) capture steps, so that by the time the user reaches the selfie
// step the multi-MB WASM runtime + face model are already downloaded and
// compiled instead of the selfie step silently stalling on a cold load —
// the leading suspect for the "selfie screen goes black" reports, since a
// stalled main thread mid-WASM-instantiation can prevent the live video
// from visibly painting even though the stream itself is fine.
const faceLandmarkerPromise = (async () => {
  try {
    const vision = await import(VISION_BUNDLE_URL);
    const filesetResolver = await vision.FilesetResolver.forVisionTasks(VISION_WASM_URL);
    return await vision.FaceLandmarker.createFromOptions(filesetResolver, {
      baseOptions: { modelAssetPath: MODEL_URL, delegate: 'CPU' },
      outputFaceBlendshapes: true,
      runningMode: 'VIDEO',
      numFaces: 1,
    });
  } catch (err) {
    console.error('[ekyc] face landmarker preload failed:', err);
    return null;
  }
})();

function showError(message, onRetry) {
  errorEl.textContent = message;
  errorEl.classList.remove('d-none');
  errorEl.querySelector('button')?.remove();
  if (onRetry) {
    const retryBtn = document.createElement('button');
    retryBtn.type = 'button';
    retryBtn.className = 'btn btn-sm btn-outline-danger d-block mt-2';
    retryBtn.textContent = T.cameraRetry;
    retryBtn.addEventListener('click', () => {
      errorEl.classList.add('d-none');
      onRetry();
    }, { once: true });
    errorEl.appendChild(retryBtn);
  }
  // The active step can be well below the error banner in the DOM (e.g.
  // the selfie step), so without this the user just sees a frozen/black
  // video with no visible explanation above the fold.
  errorEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// 'denied' here means the browser has a *stored* block decision for this
// origin and will never show a permission prompt again — vs 'prompt',
// where the next getUserMedia call would actually ask the user. The two
// look identical from getUserMedia's thrown error alone (both are
// NotAllowedError), but need very different instructions: telling someone
// to "allow camera access" on a dialog that will never appear again just
// sends them in circles.
async function getCameraPermissionState() {
  try {
    if (navigator.permissions && navigator.permissions.query) {
      const status = await navigator.permissions.query({ name: 'camera' });
      return status.state;
    }
  } catch (e) { /* not all browsers support querying 'camera' (e.g. Safari) */ }
  return null;
}

// Maps getUserMedia failures to a specific, actionable message instead of
// one generic "check permissions" string — distinguishing "you denied it"
// (retry makes sense) from "no camera exists" or "link isn't HTTPS"
// (retry alone won't fix it) is the difference between a customer who can
// recover and one who gives up and calls support.
async function cameraErrorMessage(err) {
  console.error('[ekyc] camera error:', err && err.name, err);
  if (!window.isSecureContext) return T.cameraErrorInsecure;
  switch (err && err.name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError': {
      const state = await getCameraPermissionState();
      return state === 'denied' ? T.cameraErrorBlocked : T.cameraErrorDenied;
    }
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return T.cameraErrorNotFound;
    case 'OverconstrainedError':
    case 'ConstraintNotSatisfiedError':
      // startCamera() already retries once with relaxed constraints, so
      // reaching here means even an unconstrained camera request failed.
      return T.cameraErrorNotFound;
    case 'NotReadableError':
    case 'TrackStartError':
      return T.cameraErrorInUse;
    case 'SecurityError':
    case 'MediaDevicesUnsupportedError':
      // SecurityError here (distinct from the isSecureContext check above)
      // and a missing mediaDevices API both point to the same root cause on
      // mobile: a restrictive in-app webview rather than a fixable prompt.
      return T.cameraErrorUnsupported;
    default:
      return T.cameraError;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function drawFrameToCanvas(videoEl, canvasEl) {
  canvasEl.width = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  canvasEl.getContext('2d').drawImage(videoEl, 0, 0, canvasEl.width, canvasEl.height);
}

function canvasToBlob(canvasEl, quality = 0.85) {
  return new Promise((resolve) => canvasEl.toBlob(resolve, 'image/jpeg', quality));
}

function captureFrame(videoEl, canvasEl, quality = 0.85) {
  drawFrameToCanvas(videoEl, canvasEl);
  return canvasToBlob(canvasEl, quality);
}

// Cheap client-side pre-filter mirroring ekyc/capture_quality.py's
// brightness/blur checks on a tiny downsampled copy (fast enough to run
// per-frame in the capture loop). This can't tell a document from a wall
// — only "this frame is too dark/blurry to read anything off of" — the
// server-side pipeline remains the real gate; this only stops the
// flow from blindly grabbing nothing-useful and marching on regardless.
function assessFrameQuality(canvasEl) {
  const w = 64;
  const h = Math.max(1, Math.round(w * canvasEl.height / canvasEl.width)) || 40;
  const tmp = document.createElement('canvas');
  tmp.width = w;
  tmp.height = h;
  const tctx = tmp.getContext('2d');
  tctx.drawImage(canvasEl, 0, 0, w, h);
  const data = tctx.getImageData(0, 0, w, h).data;

  const gray = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) {
    gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  }

  let sum = 0;
  for (let i = 0; i < gray.length; i++) sum += gray[i];
  const brightness = sum / gray.length;

  let lapSum = 0, lapSqSum = 0, count = 0;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const idx = y * w + x;
      const lap = gray[idx - 1] + gray[idx + 1] + gray[idx - w] + gray[idx + w] - 4 * gray[idx];
      lapSum += lap;
      lapSqSum += lap * lap;
      count++;
    }
  }
  const lapMean = lapSum / count;
  const sharpness = lapSqSum / count - lapMean * lapMean;

  const isUsable = brightness >= QUALITY_MIN_BRIGHTNESS && brightness <= QUALITY_MAX_BRIGHTNESS
    && sharpness >= QUALITY_MIN_SHARPNESS;
  return { brightness, sharpness, isUsable };
}

// Draws one frame and checks it isn't blank/black before handing it back —
// a real phone test showed the burst capture occasionally grabbing a
// near-black frame right at the moment of capture (camera HAL/exposure
// hiccup, or a backgrounded <video> element a mobile browser silently
// paused), which check_id_side then correctly rejected as unreadable but
// with no way to tell that apart from a genuinely blank/empty card. This
// discards anything near-zero brightness and retries from the still-live
// stream — explicitly resuming playback first if the browser paused it —
// instead of ever letting a black frame reach the backend.
const BLANK_FRAME_BRIGHTNESS_THRESHOLD = 8;
const BLANK_FRAME_MAX_RETRIES = 6;

async function captureUsableFrame(videoEl, canvasEl) {
  for (let attempt = 0; attempt < BLANK_FRAME_MAX_RETRIES; attempt++) {
    if (videoEl.paused) {
      try { await videoEl.play(); } catch (e) { /* best effort — drawImage below just gets a stale frame */ }
    }
    drawFrameToCanvas(videoEl, canvasEl);
    const { brightness } = assessFrameQuality(canvasEl);
    if (brightness >= BLANK_FRAME_BRIGHTNESS_THRESHOLD) {
      return { blob: await canvasToBlob(canvasEl), brightness, blank: false };
    }
    console.warn(`[ekyc] discarding near-black frame (brightness=${brightness.toFixed(1)}), `
      + `retry ${attempt + 1}/${BLANK_FRAME_MAX_RETRIES}`);
    await sleep(BURST_INTERVAL_MS);
  }
  return { blob: null, brightness: null, blank: true };
}

function toAsciiDigits(s) {
  return s.replace(/[٠-٩]/g, (d) => String(AR_INDIC_DIGITS.indexOf(d)));
}

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('timed out')), ms)),
  ]);
}

// tesseract.min.js and opencv.js are both classic global/UMD scripts
// (window.Tesseract, window.cv), not ES modules like vision_bundle.mjs
// above, so each is loaded via a plain <script> tag rather than import() —
// at most once per page, cached for every subsequent hint attempt (retakes,
// back side never calls either of these).
let _tesseractScriptPromise = null;
function loadTesseractScript() {
  if (!_tesseractScriptPromise) {
    _tesseractScriptPromise = new Promise((resolve, reject) => {
      if (window.Tesseract) { resolve(window.Tesseract); return; }
      const script = document.createElement('script');
      script.src = OCR_HINT_SCRIPT_URL;
      script.onload = () => resolve(window.Tesseract);
      script.onerror = () => reject(new Error('failed to load self-hosted Tesseract.js'));
      document.head.appendChild(script);
    });
  }
  return _tesseractScriptPromise;
}

let _openCvPromise = null;
function loadOpenCv() {
  if (!_openCvPromise) {
    _openCvPromise = new Promise((resolve, reject) => {
      if (window.cv && window.cv.Mat) { resolve(window.cv); return; }
      const script = document.createElement('script');
      script.src = OPENCV_SCRIPT_URL;
      script.onload = () => {
        const cv = window.cv;
        if (!cv) { reject(new Error('opencv.js loaded but window.cv is undefined')); return; }
        if (cv.Mat) { resolve(cv); return; }
        cv.onRuntimeInitialized = () => resolve(cv);
      };
      script.onerror = () => reject(new Error('failed to load self-hosted opencv.js'));
      document.head.appendChild(script);
    });
  }
  return _openCvPromise;
}

function blobToCanvas(blob) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      canvas.getContext('2d').drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      resolve(canvas);
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('failed to decode captured frame')); };
    img.src = url;
  });
}

// OpenCV's own RotatedRect::points() formula (center/size/angle -> 4
// corners) — reimplemented here rather than relying on cv.boxPoints,
// which isn't in every OpenCV.js embind build's bound-function whitelist.
function rotatedRectPoints(rect) {
  const angleRad = (rect.angle * Math.PI) / 180;
  const b = Math.cos(angleRad) * 0.5;
  const a = Math.sin(angleRad) * 0.5;
  const { x: cx, y: cy } = rect.center;
  const { width: w, height: h } = rect.size;
  return [
    { x: cx - a * h - b * w, y: cy + b * h - a * w },
    { x: cx + a * h - b * w, y: cy - b * h - a * w },
    { x: cx + a * h + b * w, y: cy - b * h + a * w },
    { x: cx - a * h + b * w, y: cy + b * h + a * w },
  ];
}

// Orders 4 points as top-left, top-right, bottom-right, bottom-left — same
// approach as ekyc/document_capture.py's _order_corners.
function orderCorners(pts) {
  const sums = pts.map((p) => p.x + p.y);
  const diffs = pts.map((p) => p.y - p.x);
  return [
    pts[sums.indexOf(Math.min(...sums))],
    pts[diffs.indexOf(Math.min(...diffs))],
    pts[sums.indexOf(Math.max(...sums))],
    pts[diffs.indexOf(Math.max(...diffs))],
  ];
}

// Client-side mirror of ekyc/document_capture.py's find_card_corners() —
// same algorithm (Canny -> dilate/close -> largest-contours-by-box-area ->
// aspect-ratio filter), same uncalibrated-against-a-real-card caveat.
// Returns 4 ordered corners, or null if no card-like quad was found (the
// caller falls back to whole-frame OCR, same graceful degradation as the
// server-side equivalent).
function findCardCornersCv(cv, srcMat) {
  const frameArea = srcMat.rows * srcMat.cols;
  const gray = new cv.Mat();
  const blurred = new cv.Mat();
  const edges = new cv.Mat();
  const dilated = new cv.Mat();
  const closed = new cv.Mat();
  const contours = new cv.MatVector();
  const hierarchy = new cv.Mat();
  let kernel;
  try {
    cv.cvtColor(srcMat, gray, cv.COLOR_RGBA2GRAY);
    cv.GaussianBlur(gray, blurred, new cv.Size(5, 5), 0, 0, cv.BORDER_DEFAULT);
    cv.Canny(blurred, edges, 30, 150);
    kernel = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(7, 7));
    cv.dilate(edges, dilated, kernel, new cv.Point(-1, -1), 1);
    cv.morphologyEx(dilated, closed, cv.MORPH_CLOSE, kernel);
    cv.findContours(closed, contours, hierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);

    const candidates = [];
    for (let i = 0; i < contours.size(); i++) {
      const contour = contours.get(i);
      const rect = cv.minAreaRect(contour);
      candidates.push({ rect, area: rect.size.width * rect.size.height });
      contour.delete();
    }
    candidates.sort((x, y) => y.area - x.area);

    for (const { rect } of candidates.slice(0, 8)) {
      let rw = rect.size.width;
      let rh = rect.size.height;
      if (rw === 0 || rh === 0) continue;
      const boxArea = rw * rh;
      if (boxArea < HINT_MIN_CARD_AREA_FRACTION * frameArea || boxArea > HINT_MAX_CARD_AREA_FRACTION * frameArea) continue;
      if (rw < rh) { const tmp = rw; rw = rh; rh = tmp; }
      const aspectRatio = rw / rh;
      if (aspectRatio > HINT_CARD_MIN_ASPECT && aspectRatio < HINT_CARD_MAX_ASPECT) {
        return orderCorners(rotatedRectPoints(rect));
      }
    }
    return null;
  } finally {
    gray.delete(); blurred.delete(); edges.delete(); dilated.delete(); closed.delete();
    contours.delete(); hierarchy.delete();
    if (kernel) kernel.delete();
  }
}

// Warps srcMat so the card fills a HINT_CANONICAL_WIDTH x HINT_CANONICAL_HEIGHT
// rectangle — client-side mirror of ekyc/document_capture.py's correct_perspective.
function warpCardCv(cv, srcMat, corners) {
  const srcTri = cv.matFromArray(4, 1, cv.CV_32FC2, corners.flatMap((p) => [p.x, p.y]));
  const dstTri = cv.matFromArray(4, 1, cv.CV_32FC2, [
    0, 0,
    HINT_CANONICAL_WIDTH - 1, 0,
    HINT_CANONICAL_WIDTH - 1, HINT_CANONICAL_HEIGHT - 1,
    0, HINT_CANONICAL_HEIGHT - 1,
  ]);
  const matrix = cv.getPerspectiveTransform(srcTri, dstTri);
  const dst = new cv.Mat();
  try {
    cv.warpPerspective(srcMat, dst, matrix, new cv.Size(HINT_CANONICAL_WIDTH, HINT_CANONICAL_HEIGHT));
  } finally {
    srcTri.delete(); dstTri.delete(); matrix.delete();
  }
  return dst;
}

// [x0, y0, x1, y1] fractional box -> a cloned (independently-owned) sub-Mat.
function cropRoiCv(cv, mat, box) {
  const [x0f, y0f, x1f, y1f] = box;
  const w = mat.cols;
  const h = mat.rows;
  const rect = new cv.Rect(Math.round(x0f * w), Math.round(y0f * h),
                            Math.round((x1f - x0f) * w), Math.round((y1f - y0f) * h));
  const roi = mat.roi(rect);
  const cropped = roi.clone();
  roi.delete();
  return cropped;
}

// Client-side mirror of ekyc/ocr_pipeline.py's _clean_strip(): grayscale ->
// upscale -> adaptive Gaussian threshold, to strip the card's printed
// background pattern out from under the text before OCR.
function cleanStripCv(cv, stripMat) {
  const gray = new cv.Mat();
  const upscaled = new cv.Mat();
  const cleaned = new cv.Mat();
  try {
    cv.cvtColor(stripMat, gray, cv.COLOR_RGBA2GRAY);
    cv.resize(gray, upscaled, new cv.Size(0, 0), HINT_STRIP_UPSCALE_FACTOR, HINT_STRIP_UPSCALE_FACTOR, cv.INTER_CUBIC);
    cv.adaptiveThreshold(upscaled, cleaned, 255, cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY,
                          HINT_ADAPTIVE_BLOCK_SIZE, HINT_ADAPTIVE_C);
  } finally {
    gray.delete(); upscaled.delete();
  }
  return cleaned;
}

function matToCanvas(cv, mat) {
  const canvas = document.createElement('canvas');
  cv.imshow(canvas, mat);
  return canvas;
}

// Locates the card, warps it, slices+cleans the national_id and full_name
// strips (ekyc/id_layout.py's FRONT_FIELDS boxes) and returns them as
// ready-to-OCR canvases. Returns null (caller falls back to whole-frame
// OCR) if no card-like boundary was found — same fallback ekyc/
// document_capture.py's correct_perspective takes server-side.
function buildHintStripsCv(cv, frameMat) {
  const corners = findCardCornersCv(cv, frameMat);
  if (!corners) return null;
  const warped = warpCardCv(cv, frameMat, corners);
  try {
    const nationalIdRoi = cropRoiCv(cv, warped, HINT_NATIONAL_ID_BOX);
    const fullNameRoi = cropRoiCv(cv, warped, HINT_FULL_NAME_BOX);
    try {
      const nationalIdClean = cleanStripCv(cv, nationalIdRoi);
      const fullNameClean = cleanStripCv(cv, fullNameRoi);
      try {
        return {
          nationalIdCanvas: matToCanvas(cv, nationalIdClean),
          fullNameCanvas: matToCanvas(cv, fullNameClean),
        };
      } finally {
        nationalIdClean.delete(); fullNameClean.delete();
      }
    } finally {
      nationalIdRoi.delete(); fullNameRoi.delete();
    }
  } finally {
    warped.delete();
  }
}

// Structural plausibility check (length/digits/century/calendar date),
// client-side mirror of the deterministic part of ekyc/national_id.py's
// decode() — used only to decide whether to include a parsed national_id
// in the hint at all; never blocks submission either way (see
// readIdHint's docstring).
function isPlausibleNationalId(digits) {
  if (!/^\d{14}$/.test(digits)) return false;
  if (digits[0] !== '2' && digits[0] !== '3') return false;
  const year = (digits[0] === '2' ? 1900 : 2000) + parseInt(digits.slice(1, 3), 10);
  const month = parseInt(digits.slice(3, 5), 10);
  const day = parseInt(digits.slice(5, 7), 10);
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  const dob = new Date(year, month - 1, day);
  if (dob.getFullYear() !== year || dob.getMonth() !== month - 1 || dob.getDate() !== day) return false;
  return dob <= new Date();
}

async function _readIdHintInner(blob, cv, worker) {
  const canvas = await blobToCanvas(blob);
  const frameMat = cv.imread(canvas);
  let strips;
  try {
    strips = buildHintStripsCv(cv, frameMat);
  } catch (err) {
    console.warn('[ekyc] OpenCV card-warp failed, falling back to whole-frame OCR:', err && err.message);
    strips = null;
  } finally {
    frameMat.delete();
  }

  if (strips) {
    const [idResult, nameResult] = await Promise.all([
      worker.recognize(strips.nationalIdCanvas),
      worker.recognize(strips.fullNameCanvas),
    ]);
    const ascii = toAsciiDigits(idResult.data.text || '');
    const match = ascii.match(/\d{14}/);
    const nationalId = match ? match[0] : '';
    return {
      national_id: isPlausibleNationalId(nationalId) ? nationalId : '',
      full_name: (nameResult.data.text || '').trim().slice(0, 300),
      raw_text: `${idResult.data.text || ''} ${nameResult.data.text || ''}`.trim().slice(0, 500),
      confidence: typeof idResult.data.confidence === 'number' ? idResult.data.confidence : null,
      source: 'opencv_roi',
    };
  }

  // No card boundary found — OCR the whole captured frame instead (lower
  // confidence, but still just a throwaway hint either way).
  const { data } = await worker.recognize(blob);
  const ascii = toAsciiDigits(data.text || '');
  const match = ascii.match(/\d{14}/);
  const nationalId = match ? match[0] : '';
  return {
    national_id: isPlausibleNationalId(nationalId) ? nationalId : '',
    full_name: '',
    raw_text: (data.text || '').slice(0, 500),
    confidence: typeof data.confidence === 'number' ? data.confidence : null,
    source: 'whole_frame_fallback',
  };
}

// Throwaway browser-side OCR hint for the front ID side only. The whole
// attempt — both self-hosted script loads, the OpenCV card-warp/slice/
// clean, and both OCR reads — is raced against OCR_HINT_TIMEOUT_MS so a
// slow/failed load or a slow device never delays the existing capture
// flow. Returns null on any failure or timeout, and callers must treat
// that as fully optional (see ekyc/routes.py's check_side, which already
// treats ocr_hint as optional).
async function readIdHint(blob) {
  try {
    return await withTimeout(_readIdHintAttempt(blob), OCR_HINT_TIMEOUT_MS);
  } catch (err) {
    console.warn('[ekyc] browser OCR hint skipped:', err && err.message);
    return null;
  }
}

async function _readIdHintAttempt(blob) {
  const [Tesseract, cv] = await Promise.all([loadTesseractScript(), loadOpenCv()]);
  const worker = await Tesseract.createWorker('ara+eng', 1, {
    workerPath: OCR_HINT_BASE_URL + 'worker.min.js',
    corePath: OCR_HINT_BASE_URL,
    langPath: OCR_HINT_BASE_URL,
    gzip: false,
  });
  try {
    return await _readIdHintInner(blob, cv, worker);
  } finally {
    try { await worker.terminate(); } catch (e) { /* best effort */ }
  }
}

async function startCamera(videoEl, facingMode) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    // Old/stripped-down in-app webviews expose no mediaDevices API at all,
    // so calling getUserMedia would throw a generic TypeError instead of a
    // named MediaError — raise our own named error so cameraErrorMessage()
    // can give the "open in a real browser" guidance instead of the
    // catch-all message.
    const err = new Error('navigator.mediaDevices.getUserMedia is unavailable');
    err.name = 'MediaDevicesUnsupportedError';
    throw err;
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode, width: { ideal: 1280 }, height: { ideal: 960 } },
      audio: false,
    });
  } catch (err) {
    // Devices with no camera matching `facingMode` (e.g. a laptop with only
    // a front-facing webcam, asked for 'environment') throw
    // OverconstrainedError even though a usable camera exists — retry once
    // with the constraint dropped before giving up.
    if (err.name === 'OverconstrainedError' || err.name === 'ConstraintNotSatisfiedError') {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 960 } },
        audio: false,
      });
    } else {
      throw err;
    }
  }
  videoEl.srcObject = stream;
  await videoEl.play();
  return stream;
}

function stopStream(stream) {
  if (stream) stream.getTracks().forEach((track) => track.stop());
}

async function switchAwayFromCamera(stream) {
  stopStream(stream);
  await sleep(CAMERA_SWITCH_DELAY_MS);
}

// ---- Live in-browser card detection ----
// Lightweight real-time "is there a card-shaped object filling the guide
// frame" heuristic: a genuine ID edge produces a strong, mostly-continuous
// brightness gradient along each of the guide rectangle's 4 borders — the
// same underlying principle as ekyc/document_capture.py's Canny+contour
// corner detector server-side, just a cheap 1D-projection version suited to
// running every frame in plain JS (no CV library — see id_layout.py's
// licensing note on why this project avoids ML object detectors). A face
// or a blank/cluttered scene doesn't produce 4 clean orthogonal edge
// bands, which is what lets this reject those without ever needing to
// recognize "face" specifically.
//
// Like every other uncalibrated threshold in this project (see
// EKYC_MODULE.md), MIN_EDGE_STRENGTH/EDGE_TO_INTERIOR_RATIO are best-effort
// starting points, not measured against a real card — that's fine here
// because this only gates *when* to auto-capture; the backend check_side
// call that follows every capture is the real accept/reject authority.
class CardDetector {
  constructor(videoEl, guideCanvasEl) {
    this.videoEl = videoEl;
    this.guideCanvasEl = guideCanvasEl;
    this.sampleCanvas = document.createElement('canvas');
  }

  // The guide rectangle, in the video's native pixel coordinates, centered
  // and sized to ekyc/id_layout.py's CARD_ASPECT_RATIO.
  guideRect() {
    const vw = this.videoEl.videoWidth;
    const vh = this.videoEl.videoHeight;
    let gw = vw * GUIDE_WIDTH_FRACTION;
    let gh = gw / CARD_ASPECT_RATIO;
    if (gh > vh * 0.92) {
      gh = vh * 0.92;
      gw = gh * CARD_ASPECT_RATIO;
    }
    return { x: (vw - gw) / 2, y: (vh - gh) / 2, w: gw, h: gh };
  }

  // Draws the guide outline over the displayed video (green once detected,
  // dashed white otherwise) so the user knows exactly where to hold the card.
  drawGuide(detected) {
    const canvas = this.guideCanvasEl;
    const vw = this.videoEl.videoWidth;
    const vh = this.videoEl.videoHeight;
    if (!vw || !vh) return;
    canvas.width = this.videoEl.clientWidth;
    canvas.height = this.videoEl.clientHeight;
    const scaleX = canvas.width / vw;
    const scaleY = canvas.height / vh;
    const rect = this.guideRect();
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.lineWidth = 3;
    ctx.strokeStyle = detected ? '#28a745' : 'rgba(255,255,255,0.85)';
    ctx.setLineDash(detected ? [] : [10, 8]);
    ctx.strokeRect(rect.x * scaleX, rect.y * scaleY, rect.w * scaleX, rect.h * scaleY);
  }

  // Samples the current full video frame (downsampled) and searches for a
  // card-shaped quadrilateral wherever it actually is, rather than assuming
  // it sits exactly on the drawn guide border (a real user framing a real
  // card rarely matches an on-screen guide pixel-for-pixel). Never stores
  // or uploads the frame, just decides whether something card-shaped and
  // in-focus is currently in view.
  //
  // Method: a card's left/right boundary shows up as a column with
  // unusually high total horizontal gradient (summed down every row); its
  // top/bottom boundary shows up the same way in the row-summed vertical
  // gradient. This is the same underlying idea as
  // ekyc/document_capture.py's contour search, simplified to two 1D
  // projection-profile searches (cheap enough to run every frame here)
  // instead of full contour-finding.
  sample() {
    const vw = this.videoEl.videoWidth;
    const vh = this.videoEl.videoHeight;
    if (!vw || !vh) return { cardDetected: false, quality: null };

    const w = DETECTOR_GRID_WIDTH;
    const h = Math.max(20, Math.round(w * vh / vw));
    this.sampleCanvas.width = w;
    this.sampleCanvas.height = h;
    const ctx = this.sampleCanvas.getContext('2d');
    ctx.drawImage(this.videoEl, 0, 0, w, h);

    const quality = assessFrameQuality(this.sampleCanvas);

    const data = ctx.getImageData(0, 0, w, h).data;
    const gray = new Float32Array(w * h);
    for (let i = 0; i < w * h; i++) {
      gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
    }

    const gx = new Float32Array(w * h);
    const gy = new Float32Array(w * h);
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const idx = y * w + x;
        gx[idx] = Math.abs(gray[idx + 1] - gray[idx - 1]);
        gy[idx] = Math.abs(gray[idx + w] - gray[idx - w]);
      }
    }

    const colProfile = new Float64Array(w);
    const rowProfile = new Float64Array(h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        colProfile[x] += gx[y * w + x];
        rowProfile[y] += gy[y * w + x];
      }
    }

    const argMaxInRange = (arr, start, end) => {
      let best = start, bestVal = -Infinity;
      for (let i = start; i < end; i++) {
        if (arr[i] > bestVal) { bestVal = arr[i]; best = i; }
      }
      return best;
    };
    const median = (arr) => {
      const sorted = Array.from(arr).sort((a, b) => a - b);
      return sorted[Math.floor(sorted.length / 2)];
    };

    const marginX = Math.max(1, Math.round(DETECTOR_SEARCH_MARGIN_FRACTION * w));
    const marginY = Math.max(1, Math.round(DETECTOR_SEARCH_MARGIN_FRACTION * h));
    const leftX = argMaxInRange(colProfile, marginX, Math.floor(w / 2));
    const rightX = argMaxInRange(colProfile, Math.ceil(w / 2), w - marginX);
    const topY = argMaxInRange(rowProfile, marginY, Math.floor(h / 2));
    const bottomY = argMaxInRange(rowProfile, Math.ceil(h / 2), h - marginY);

    const cardW = rightX - leftX;
    const cardH = bottomY - topY;
    const areaFraction = (cardW * cardH) / (w * h);
    const aspect = cardW / Math.max(1, cardH);
    const aspectOk = Math.abs(aspect - CARD_ASPECT_RATIO) / CARD_ASPECT_RATIO < CARD_ASPECT_TOLERANCE;

    const colMedian = median(colProfile);
    const rowMedian = median(rowProfile);
    const edgesStrong = colProfile[leftX] > EDGE_PEAK_MIN_ABS && colProfile[rightX] > EDGE_PEAK_MIN_ABS
      && rowProfile[topY] > EDGE_PEAK_MIN_ABS && rowProfile[bottomY] > EDGE_PEAK_MIN_ABS
      && colProfile[leftX] > colMedian * EDGE_PEAK_TO_MEDIAN_RATIO
      && colProfile[rightX] > colMedian * EDGE_PEAK_TO_MEDIAN_RATIO
      && rowProfile[topY] > rowMedian * EDGE_PEAK_TO_MEDIAN_RATIO
      && rowProfile[bottomY] > rowMedian * EDGE_PEAK_TO_MEDIAN_RATIO;

    const cardDetected = areaFraction > MIN_CARD_AREA_FRACTION && areaFraction < MAX_CARD_AREA_FRACTION
      && aspectOk && edgesStrong;

    return { cardDetected, quality };
  }
}

// POSTs a customer-confirmed burst of frames (plus an optional draft
// ocrHint, see readIdHint(), front side only) to ekyc/routes.py's
// check_side route. Saved immediately there, no OCR/document-PAD gate, no
// job to poll for — see that route's docstring for why. Multiple frames
// (not just the one previewed) so the async pipeline still has enough for
// OCR consensus and ekyc/document_pad.py's reflection-variance check,
// which needs >=3 — a single frame would silently zero out that signal
// for every session. Returns {ok, error}.
async function uploadIdSide(side, frames, ocrHint) {
  const formData = new FormData();
  formData.append('csrf_token', CSRF_TOKEN);
  formData.append('side', side);
  frames.forEach((blob, i) => formData.append(`frame_${i}`, blob, `${side}_${i}.jpg`));
  // Draft-only client hint, front side only — see readIdHint()'s docstring.
  // Omitted entirely (not even an empty value) when capture, WASM load, or
  // recognize() failed/timed out, so the server can tell "no hint attempted"
  // apart from "hint attempted and empty".
  if (ocrHint) formData.append('ocr_hint', JSON.stringify(ocrHint));

  let response, data;
  try {
    response = await fetch(CHECK_SIDE_URL, { method: 'POST', body: formData });
    data = await response.json();
  } catch (err) {
    return { ok: false, error: T.uploadError };
  }
  if (!response.ok || !data.ok) {
    return { ok: false, error: data.error || T.uploadError };
  }
  return { ok: true, error: null };
}

// Shows the customer's own just-captured photo and asks them to confirm it
// looks clear before it's uploaded anywhere — there's no synchronous OCR
// result to show any more (see check_side's docstring), and a photo is
// something the customer can actually judge for themselves. Resolves true
// (submit) or false (retake).
function showImagePreview(side, blob) {
  return new Promise((resolve) => {
    idReviewHeadingEl.textContent = T.reviewHeading;
    idReviewNoticeEl.textContent = T.reviewNotice;
    const url = URL.createObjectURL(blob);
    idReviewImageEl.src = url;
    idReviewRetakeBtn.textContent = T.reviewRetake;
    idReviewConfirmBtn.textContent = T.reviewConfirm;
    idReviewStepEl.classList.remove('d-none');

    function cleanup() {
      idReviewStepEl.classList.add('d-none');
      URL.revokeObjectURL(url);
      idReviewConfirmBtn.removeEventListener('click', onConfirm);
      idReviewRetakeBtn.removeEventListener('click', onRetake);
    }
    function onConfirm() { cleanup(); resolve(true); }
    function onRetake() { cleanup(); resolve(false); }
    idReviewConfirmBtn.addEventListener('click', onConfirm, { once: true });
    idReviewRetakeBtn.addEventListener('click', onRetake, { once: true });
  });
}

// Colors the live guide overlay green when something card-shaped is in
// view — a visual aid only, never a precondition for capture. Previously
// gated the manual-capture button on CONSECUTIVE_DETECTIONS_REQUIRED good
// frames in a row; a real recording showed a clearly-framed card sitting
// in the guide for 80+ seconds without the detector ever firing (see
// CardDetector's header comment), which made customers wait on nothing.
// The shutter button is enabled immediately instead; this just keeps
// drawing the live feedback alongside it until told to stop.
function startLiveGuide(detector) {
  let cancelled = false;
  (async () => {
    while (!cancelled) {
      const { cardDetected, quality } = detector.sample();
      detector.drawGuide(cardDetected && quality && quality.isUsable);
      await sleep(DETECTOR_SAMPLE_INTERVAL_MS);
    }
  })();
  return () => { cancelled = true; };
}

// Drives one ID side end to end: live camera with an immediately-enabled
// shutter button (no waiting on auto-detection), a single-frame capture,
// then the customer's own clarity check (showImagePreview) before
// anything is uploaded. Submit uploads right away — no OCR/document-PAD
// gate (see check_side's docstring) — and advances; retake loops back to
// the live camera, which the stream stays open for the whole time (only
// ever stopped in beginIdCapture()/beginIdBackCapture() once this whole
// function resolves). MAX_RETRIES_PER_SIDE only caps genuine upload
// failures (network/server) now, not customer-chosen retakes — those cost
// nothing server-side any more, so there's nothing to cap. The real OCR/
// document-PAD/decision still happens later, async, via the existing full
// pipeline once the session is QUEUED.
async function runIdSideCapture(side, ctx) {
  const detector = new CardDetector(ctx.videoEl, ctx.guideCanvasEl);
  const stopGuide = startLiveGuide(detector);

  ctx.retryStatusEl.textContent = T.idScanning;
  ctx.manualBtn.classList.remove('d-none');
  ctx.manualBtn.disabled = false;

  // One shutter press behind the scenes still grabs a quick burst (not
  // just one frame) — purely image capture, no OCR, ~BURST_FRAME_COUNT *
  // BURST_INTERVAL_MS (well under a second) — so the async pipeline has
  // enough frames for OCR consensus and document-PAD's reflection-
  // variance check (needs >=3). The customer only ever sees and judges
  // the last (most-settled) frame in the preview below.
  const burst = await new Promise((resolve) => {
    ctx.manualBtn.addEventListener('click', async () => {
      ctx.manualBtn.disabled = true;
      ctx.retryStatusEl.textContent = T.capturing;
      const frames = [];
      for (let i = 0; i < BURST_FRAME_COUNT; i++) {
        const { blob, blank } = await captureUsableFrame(ctx.videoEl, ctx.canvasEl);
        if (blob) {
          frames.push(blob);
        } else if (blank) {
          break;
        }
        await sleep(BURST_INTERVAL_MS);
      }
      if (frames.length === 0) {
        // Every retry inside captureUsableFrame came back black — a
        // capture-side glitch, not something the customer did wrong. Let
        // them try the shutter again on the same still-live stream.
        ctx.manualBtn.disabled = false;
        ctx.retryStatusEl.textContent = T.captureBlankRetry;
        resolve(null);
        return;
      }
      resolve(frames);
    }, { once: true });
  });

  stopGuide();
  if (!burst) return runIdSideCapture(side, ctx);

  // Front side only (back/selfie carry no national-ID field to hint at) —
  // kicked off against the FIRST frame immediately and never awaited
  // before the preview/upload below, so it has the whole preview-viewing
  // time to make progress in the background. See readIdHint()'s docstring.
  const idHintPromise = side === 'front' ? readIdHint(burst[0]) : null;

  ctx.stepEl.classList.add('d-none');
  const confirmed = await showImagePreview(side, burst[burst.length - 1]);
  if (!confirmed) {
    ctx.stepEl.classList.remove('d-none');
    ctx.retryStatusEl.textContent = T.idScanning;
    return runIdSideCapture(side, ctx);
  }

  ctx.retryStatusEl.textContent = T.uploading;
  // Only a short, bounded wait for whatever head start the hint already
  // got above — never the full OCR_HINT_TIMEOUT_MS. If it's not ready by
  // now, this upload just goes without one.
  const idHint = idHintPromise
    ? await Promise.race([idHintPromise, sleep(HINT_GRACE_MS).then(() => null)])
    : null;
  const result = await uploadIdSide(side, burst, idHint);
  if (result.ok) return true;

  const attempt = ++sideAttempts[side];
  if (attempt >= MAX_RETRIES_PER_SIDE) {
    ctx.manualBtn.classList.add('d-none');
    ctx.statusEl.textContent = T.idTooManyAttempts;
    ctx.retryStatusEl.textContent = '';
    return false;
  }
  ctx.stepEl.classList.remove('d-none');
  ctx.retryStatusEl.textContent = result.error;
  await sleep(800); // brief pause so the error is actually readable before retrying
  return runIdSideCapture(side, ctx);
}

// ---- Step 1: ID front capture ----
// The camera prompt is requested from inside the button's click handler
// (not here, on page load) — mobile Chrome silently suppresses the
// getUserMedia permission prompt when there's no user gesture in the call
// stack, which looks identical to a denied/broken camera from the user's
// side.
function startIdStep() {
  if (FRONT_DONE) {
    advanceFromIdStep();
    return;
  }
  idStatusEl.textContent = T.idInstruction;
  idStartBtn.classList.remove('d-none');
  idStartBtn.textContent = T.start;
  idStartBtn.disabled = false;
  idStartBtn.addEventListener('click', beginIdCapture, { once: true });
}

async function beginIdCapture() {
  idStartBtn.disabled = true;
  idStartBtn.classList.add('d-none');
  try {
    idStream = await startCamera(idVideo, 'environment');
  } catch (err) {
    showError(await cameraErrorMessage(err), startIdStep);
    return;
  }
  const passed = await runIdSideCapture('front', {
    videoEl: idVideo, canvasEl: idCanvas, guideCanvasEl: idGuideCanvas,
    statusEl: idStatusEl, retryStatusEl: idRetryStatusEl, stepEl: idStepEl,
    manualBtn: idManualBtn,
  });
  await switchAwayFromCamera(idStream);
  // On exceeding MAX_RETRIES_PER_SIDE, the "too many attempts" message is
  // already shown and the start button stays hidden — the customer can't
  // keep hammering retries; staff must regenerate the link
  // (ekyc.regenerate_link) to issue a fresh one.
  if (passed) advanceFromIdStep();
}

function advanceFromIdStep() {
  idStepEl.classList.add('d-none');
  if (BACK_SIDE_REQUIRED) {
    idBackStepEl.classList.remove('d-none');
    startIdBackStep();
  } else {
    selfieStepEl.classList.remove('d-none');
    startSelfieStep();
  }
}

// ---- Step 2: ID back capture (NATIONAL_ID only) ----
function startIdBackStep() {
  if (BACK_DONE) {
    advanceFromIdBackStep();
    return;
  }
  idBackStatusEl.textContent = T.idBackInstruction;
  idBackStartBtn.classList.remove('d-none');
  idBackStartBtn.textContent = T.start;
  idBackStartBtn.disabled = false;
  idBackStartBtn.addEventListener('click', beginIdBackCapture, { once: true });
}

async function beginIdBackCapture() {
  idBackStartBtn.disabled = true;
  idBackStartBtn.classList.add('d-none');
  try {
    idBackStream = await startCamera(idBackVideo, 'environment');
  } catch (err) {
    showError(await cameraErrorMessage(err), startIdBackStep);
    return;
  }
  const passed = await runIdSideCapture('back', {
    videoEl: idBackVideo, canvasEl: idBackCanvas, guideCanvasEl: idBackGuideCanvas,
    statusEl: idBackStatusEl, retryStatusEl: idBackRetryStatusEl, stepEl: idBackStepEl,
    manualBtn: idBackManualBtn,
  });
  await switchAwayFromCamera(idBackStream);
  if (passed) advanceFromIdBackStep();
}

function advanceFromIdBackStep() {
  idBackStepEl.classList.add('d-none');
  selfieStepEl.classList.remove('d-none');
  startSelfieStep();
}

// Resumes at the right step on page load (see ekyc/routes.py's verify()
// passing down FRONT_DONE/BACK_DONE) instead of always restarting at step 1.
function startCaptureFlow() {
  if (FRONT_DONE && (!BACK_SIDE_REQUIRED || BACK_DONE)) {
    idStepEl.classList.add('d-none');
    idBackStepEl.classList.add('d-none');
    selfieStepEl.classList.remove('d-none');
    startSelfieStep();
  } else if (FRONT_DONE && BACK_SIDE_REQUIRED && !BACK_DONE) {
    idStepEl.classList.add('d-none');
    idBackStepEl.classList.remove('d-none');
    startIdBackStep();
  } else {
    startIdStep();
  }
}

// ---- Step 3: Selfie + active liveness ----
function dist2d(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

class ChallengeTracker {
  constructor(challenge) {
    this.challenge = challenge;
    this.passed = false;
    this.blinkWasClosed = false;
    this.turnBaselineRatio = null;
    this.turnDeviated = false;
  }

  // landmarks: array of {x,y,z} normalized points; blendshapes: {name: score}
  update(landmarks, blendshapes) {
    if (this.passed) return;

    if (this.challenge === 'blink') {
      const avg = ((blendshapes.eyeBlinkLeft || 0) + (blendshapes.eyeBlinkRight || 0)) / 2;
      if (avg > BLINK_CLOSE_THRESHOLD) this.blinkWasClosed = true;
      if (this.blinkWasClosed && avg < BLINK_OPEN_THRESHOLD) this.passed = true;
      return;
    }

    if (this.challenge === 'smile') {
      const avg = ((blendshapes.mouthSmileLeft || 0) + (blendshapes.mouthSmileRight || 0)) / 2;
      if (avg > SMILE_THRESHOLD) this.passed = true;
      return;
    }

    if (this.challenge === 'turn_head') {
      const nose = landmarks[LANDMARK_NOSE_TIP];
      const rightEye = landmarks[LANDMARK_RIGHT_EYE_OUTER];
      const leftEye = landmarks[LANDMARK_LEFT_EYE_OUTER];
      const ratio = dist2d(nose, rightEye) / dist2d(nose, leftEye);
      if (this.turnBaselineRatio === null) {
        this.turnBaselineRatio = ratio;
        return;
      }
      const deviation = Math.abs(ratio - this.turnBaselineRatio) / this.turnBaselineRatio;
      if (deviation > TURN_RATIO_DEVIATION) this.turnDeviated = true;
      if (this.turnDeviated && deviation < TURN_RATIO_DEVIATION / 2) this.passed = true;
    }
  }
}

async function startSelfieStep() {
  const challenge = ['blink', 'turn_head', 'smile'][Math.floor(Math.random() * 3)];
  livenessResult = { challenge, passed: false };
  selfieChallengeEl.textContent = CHALLENGE_LABELS[challenge];
  selfieRetakeBtn.classList.add('d-none');
  selfieManualBtn.classList.add('d-none');
  selfieStatusEl.textContent = '';

  try {
    selfieStream = await startCamera(selfieVideo, 'user');
  } catch (err) {
    showError(await cameraErrorMessage(err), startSelfieStep);
    return;
  }

  // The video is already live at this point (startCamera() assigns
  // srcObject and calls play() before this function ever touches the
  // detector) — what follows must never be able to leave the user staring
  // at that live-but-stalled video with no path forward, so the detector
  // wait is capped and always resolves to either a working detector or a
  // graceful fallback, never an indefinite spinner.
  selfieStatusEl.textContent = T.loadingDetector;
  const timeoutPromise = new Promise((resolve) => setTimeout(() => resolve(null), FACE_LANDMARKER_TIMEOUT_MS));
  const faceLandmarker = await Promise.race([faceLandmarkerPromise, timeoutPromise]);
  if (!faceLandmarker) {
    // Detector failed to load or took too long (CSP/WASM issue, slow
    // network, unsupported browser...). Camera stream stays live; drop the
    // active-liveness challenge for a manual photo capture instead of
    // showing an error and stopping the camera.
    console.warn('[ekyc] face landmarker unavailable or timed out — falling back to manual selfie capture');
    runManualSelfieCapture();
    return;
  }

  await runActiveLivenessChallenge(faceLandmarker, challenge);
}

async function runActiveLivenessChallenge(faceLandmarker, challenge) {
  const tracker = new ChallengeTracker(challenge);
  selfieFrames = [];
  const startTime = performance.now();
  let lastCaptureTime = 0;
  selfieStatusEl.textContent = T.capturing;

  while (performance.now() - startTime < CHALLENGE_TIMEOUT_MS) {
    const now = performance.now();
    const result = faceLandmarker.detectForVideo(selfieVideo, now);

    if (result.faceLandmarks && result.faceLandmarks.length > 0) {
      const landmarks = result.faceLandmarks[0];
      const blendshapeMap = {};
      if (result.faceBlendshapes && result.faceBlendshapes.length > 0) {
        for (const category of result.faceBlendshapes[0].categories) {
          blendshapeMap[category.categoryName] = category.score;
        }
      }
      tracker.update(landmarks, blendshapeMap);
    }

    if (now - lastCaptureTime > SELFIE_FRAME_INTERVAL_MS) {
      lastCaptureTime = now;
      const blob = await captureFrame(selfieVideo, selfieCanvas);
      if (blob && selfieFrames.length < 20) selfieFrames.push(blob);
    }

    if (tracker.passed) {
      livenessResult.passed = true;
      selfieStatusEl.textContent = T.challengePassed;
      break;
    }
    await sleep(DETECTION_LOOP_DELAY_MS);
  }

  stopStream(selfieStream);

  if (tracker.passed) {
    await submitCapture();
  } else {
    selfieStatusEl.textContent = T.challengeTimeout;
    selfieRetakeBtn.classList.remove('d-none');
  }
}

// Fallback when the in-browser face detector is unavailable: a single-shot
// manual photo capture, no active-liveness challenge. livenessResult.passed
// is explicitly null (not false) so the server/risk-fusion side can tell
// "not evaluated because our detector failed" apart from "evaluated and
// failed" — see ekyc/risk_engine.py's handling of active_liveness_pass=None.
function runManualSelfieCapture() {
  livenessResult = { challenge: null, passed: null, mode: 'manual_fallback' };
  selfieChallengeEl.textContent = T.manualCaptureInstruction;
  selfieStatusEl.textContent = '';
  selfieManualBtn.classList.remove('d-none');
  selfieManualBtn.disabled = false;
  selfieManualBtn.addEventListener('click', captureManualSelfie, { once: true });
}

async function captureManualSelfie() {
  selfieManualBtn.disabled = true;
  selfieStatusEl.textContent = T.capturing;
  selfieFrames = [];
  for (let i = 0; i < 6; i++) {
    const blob = await captureFrame(selfieVideo, selfieCanvas);
    if (blob) selfieFrames.push(blob);
    await sleep(150);
  }
  stopStream(selfieStream);
  selfieManualBtn.classList.add('d-none');
  await submitCapture();
}

selfieRetakeBtn.addEventListener('click', startSelfieStep);

// ---- Submit ----
async function submitCapture() {
  selfieStepEl.classList.add('d-none');
  submitStepEl.classList.remove('d-none');
  submitStatusEl.textContent = T.uploading;

  const formData = new FormData();
  formData.append('csrf_token', CSRF_TOKEN);
  // ID frames aren't sent here — they're already validated and persisted
  // one side at a time by runIdSideCapture()/check_side as each side passed.
  selfieFrames.forEach((blob, i) => formData.append(`selfie_frame_${i}`, blob, `selfie_${i}.jpg`));
  formData.append('liveness_result', JSON.stringify(livenessResult));

  // Capped wait: on a weak mobile connection the request could otherwise
  // sit forever with only "Uploading..." on screen. The selfie frames are
  // still in memory, so the retry button resends them without a retake.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
  try {
    const response = await fetch(UPLOAD_URL, { method: 'POST', body: formData, signal: controller.signal });
    const data = await response.json();
    clearTimeout(timer);
    if (response.ok && data.redirect) {
      window.location.href = data.redirect;
    } else if (response.status === 409) {
      // Already submitted (e.g. a retry after a response was lost) — the
      // verify page shows the right screen for the session's state.
      window.location.reload();
    } else {
      showError(T.uploadError, submitCapture);
    }
  } catch (err) {
    clearTimeout(timer);
    showError(T.uploadError, submitCapture);
  }
}

setStepHeadings();
initWebviewBanner();
startCaptureFlow();
