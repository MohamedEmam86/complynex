# ComplyNex CMS — System Whiteboard

> One-sitting map of the whole platform: architecture, every module's real
> features, and the eKYC pipeline. For deep technical detail beyond this
> doc, see `EKYC_MODULE.md` (eKYC internals), `PHISHING_INTEGRATION.md`
> (mail/tracking integration history), and `SYSTEM_SPECIFICATIONS.md`
> (deployment/infra reference — **note: that doc predates eKYC/Phishing and
> still describes SQLite as primary; this doc reflects the current
> production stack below**).
>
> Generated: 2026-06-22.

---

## 1. What this is

ComplyNex CMS is a Flask compliance-management platform for ComplyNex
Egypt, a CBE-regulated fintech. It covers the full compliance lifecycle:
sanctions/PEP screening, AML/CFT, governance, ethics declarations,
whistleblowing, data protection, regulatory reporting, electronic KYC
(eKYC), and a phishing-awareness training tool — all as independent Flask
Blueprints sharing one codebase, one Postgres database, and one set of
auth/permission/audit primitives.

**22 registered Blueprints** (confirmed from `app.py`'s
`register_blueprint` calls), each self-contained: own `routes.py`, own
templates under `templates/<module>/`, own models.

---

## 2. Architecture at a glance

```
                                   ┌─────────────────────┐
                                   │   Browser (staff /   │
                                   │   public / customer) │
                                   └──────────┬───────────┘
                                              │ HTTPS
                                   ┌──────────▼───────────┐
                                   │   Nginx (reverse      │
                                   │   proxy, TLS)         │
                                   └──────────┬───────────┘
                                              │
                                   ┌──────────▼───────────┐
                                   │  Gunicorn (gevent)    │
                                   │  complynex.service     │
                                   │  app.py — 22 Blueprints│
                                   └──┬───────┬──────┬─────┘
                                      │       │      │
                       ┌──────────────┘       │      └─────────────┐
                       ▼                      ▼                    ▼
              ┌─────────────────┐   ┌─────────────────┐  ┌──────────────────┐
              │  PostgreSQL 16  │   │     Redis        │  │  Elasticsearch   │
              │  (complynex_db)    │   │ db0 cache         │  │  watchlist index │
              │  all app data   │   │ db1 rate-limiter  │  │  (screening/AML) │
              │                 │   │ db2 ekyc job queue│  │                  │
              └─────────────────┘   └─────────┬─────────┘  └──────────────────┘
                                              │ RQ job
                                   ┌──────────▼───────────┐
                                   │  ekyc-worker.service  │
                                   │  EasyOCR / insightface│
                                   │  MiniFASNet (CPU)     │
                                   └───────────────────────┘
```

Two more standalone systemd units sit alongside the web app:
`complynex-ekyc-worker.service` (long-lived eKYC pipeline consumer) and
`complynex-ekyc-purge.timer` (daily retention purge of expired eKYC media).

### Confirmed production stack (read from live `.env` / `systemctl`, 2026-06-22)

| Layer | Technology | Notes |
|---|---|---|
| App server | Gunicorn (gevent workers) behind Nginx | `complynex.service` |
| Database | **PostgreSQL 16** (`complynex_db`) | Primary store for all 22 modules — not SQLite in this deployment |
| Cache / queues | **Redis** | db0 dashboard cache, db1 rate-limiter, db2 eKYC job queue (RQ) |
| Search | **Elasticsearch** | Watchlist/blacklist indexing for fast screening lookups |
| Async workers | RQ (`rq` lib) | `ekyc-worker` is the only persistent consumer; one job at a time, BLAS threads pinned to 1 |
| ML/CV stack | EasyOCR, insightface (ArcFace/SCRFD), MiniFASNet (Silent-Face-AntiSpoofing), OpenCV, scikit-learn, RapidFuzz/jellyfish/thefuzz, PyArabic | Split across screening (name matching) and eKYC (document/face/liveness) |
| Frontend | Bootstrap 5.3 + vanilla JS/jQuery, full Arabic RTL, MediaPipe FaceLandmarker (client-side), OpenCV.js + Tesseract.js (client-side OCR hint, self-hosted) | |

---

## 3. Module map

Grouped by function. Each entry: purpose, then concrete features (grounded
in actual routes/templates, not guesses).

### 3.1 Identity & onboarding

#### eKYC (`/ekyc/`) — see §4 for the full pipeline breakdown
Customer-facing electronic identity verification: ID card + selfie capture
→ async ML pipeline (OCR, face match, liveness, document-PAD) → fused
PASS/REVIEW/FAIL decision, auto-routed through the screening engine.
- No-login customer capture flow via one-time tokenized link (bilingual consent screen)
- Burst capture for ID front/back, short video for selfie, in-browser active-liveness challenge (MediaPipe)
- Dedicated `ekyc-worker` process for ML inference, Fernet-encrypted media at rest, 30-day retention purge
- Staff dashboard: view sessions, decrypted document/selfie viewing (fully audit-logged), full per-layer score breakdown
- Runtime-configurable risk-fusion weights and decision thresholds (`ekyc_config` table)

#### merchant_kyc (`/merchant_kyc/`)
Merchant KYC directory for onboarding/verifying business customers, with
both staff-initiated and public self-service paths.
- Merchant KYC record creation with UBO/signatory details, document upload (PDF/images/Office/spreadsheets)
- Approval/rejection workflow, risk level + status tracking (PENDING → SENT → SUBMITTED → APPROVED/REJECTED)
- Public token-based self-service form with GPS location capture, WhatsApp link distribution
- Merchant screening against internal blacklist/sanctions, CSV export

### 3.2 Sanctions & financial crime

#### screening (`/screening/`)
The system's largest module: multi-source sanctions/PEP screening engine.
- **Data sources:** OpenSanctions (PEP + Sanctions, ~1.5M records), UN Consolidated, OFAC SDN, EU Consolidated, HM Treasury UK, Egypt EMLCU PEP list, plus internal custom blacklist/PEP
- **Matching:** ensemble of Levenshtein/RapidFuzz, Jaro-Winkler, token-set/partial ratios, Soundex/Metaphone phonetics, Arabic transliteration, ML confidence calibration (default threshold 0.75/70%)
- Manual screening (name/DOB/nationality, adjustable threshold slider) and bulk CSV/Excel upload with parallel job processing
- Whitelist management (mark false positives, auto-skip on future matches), resolve hits true/false-positive
- Adverse-media subsearch (Google News waterfall scraper) per screening
- Source management: enable/disable, manual or auto-sync, full sync audit log, incremental Elasticsearch indexing
- PDF report export of screening results with matched entities

#### aml (`/aml/`)
Anti-Money Laundering: customer due diligence, risk scoring, transaction monitoring, SAR generation.
- Customer onboarding with KYC/CDD and risk classification (high/medium/low)
- Suspicious Activity Report (SAR) registration and investigation workflow
- Transaction monitoring with rule engine, alerting, and analytics dashboard
- Beneficial ownership (UBO) verification/screening, transaction upload, printable compliance forms

#### blacklist (`/blacklist/`)
Internal watchlist/PEP list, feeding the screening engine.
- Blacklist + PEP entry management (add/edit/delete), position tracking for PEPs
- CSV/Excel bulk import with header-mapping, template download
- Filtering, pagination, full audit trail, CSV export
- Auto-sync to screening watchlist and Elasticsearch on any change

### 3.3 Governance & ethics

#### governance (`/governance/`)
Board/corporate governance tracking for CBE compliance.
- Board member, committee, and meeting management (attendance, decisions, invitations)
- Fit & Proper assessments with printable reports, independence declarations
- Skills matrix and board evaluation, CBE governance compliance reports

#### ghe (`/ghe/`) — Gifts, Hospitality & Entertainment
- Declaration submission with value estimates and business purpose
- Auto-approval under 500 EGP; tiered escalation above it: employee → manager → compliance
- Clarification requests, rejection with mandatory comments, full approval-history audit trail
- Public submission form with email notifications

#### coi (`/coi/`) — Conflict of Interest
- Campaign-based annual declarations + an always-open "Ad-hoc Disclosures" campaign for event-driven reporting
- Multi-checkbox conflict questionnaire (financial interests, family ties, outside employment, gifts...)
- Manager/compliance review, escalation to linked mitigation plans (strategy, owner, target date)
- Campaign completion stats, CSV compliance export

#### cobec (`/cobec/`) — Code of Business Ethics & Conduct
- One annual attestation per employee (duplicate-submission prevented)
- Compliance review queue (approve / request clarification), participation-rate dashboard

#### whistleblowing (`/whistleblowing/`)
Dual-track anonymous + identified speak-up channel.
- Public anonymous form (no login, no IP/cookie logging) with access-code case tracking
- Identified submission route for logged-in employees
- Investigator assignment, investigation notes, internal attachments
- Status workflow New → Under Review → Resolved → Closed; submitter-visible vs internal-only comments
- CBE-compliant case reporting interface

### 3.4 Policy, training & risk

#### policies (`/policies/`)
- Versioning with change history and side-by-side comparison
- Multi-stage workflow: submit → review → approve → publish → archive
- Category organization, gap analysis against regulatory requirements, attachments
- Acknowledgment tracking with reminders and per-user dashboards

#### training (`/training/`)
- Course library (create/edit/delete), quiz-based assessment, certificate generation
- Enrollment + progress tracking, bulk reminder sending
- Training-requirement rules (auto-assignment by role/department, configured in `admin`)
- Compliance reporting/export for audit

#### reporting (`/reporting/`)
- CBE-required report template/definition management
- Regulator contact database, submission tracking, ICS calendar export for submission planning
- Pulls acknowledgment/compliance data from other modules into regulatory documents

#### data_protection (`/data-protection/`) — PDPL/GDPR
- Data Subject Requests (DSRs) with 30-day response-clock tracking, identity verification
- Data breach reporting with risk assessment + regulatory notification capability
- DPIAs with approval workflow, consent log + consent-purpose management
- Data processing activity registry, full audit trail

### 3.5 Incident & complaint channels

#### consumer_protection (`/consumer_protection/`)
Public complaint system, CBE Banking Law 194/2020.
- Public submission form (category, description, optional attachments)
- Auto-generated reference number + PIN; public tracker by reference or email+PIN
- Internal dashboard with status filters/overdue stats, attachment-backed status updates, full activity log
- Bilingual (Arabic/English) confirmation emails

#### cyber (`/cyber/`)
CBE Circular (Dec 2023) cyber-incident compliance.
- Incident reporting (type, severity Low/High/Critical, description), auto-generated reference (`INC-YYYYMMDD-HEX`)
- High/Critical auto-flags mandatory CBE notification (6-24hr window)
- Severity-sorted active-incident dashboard, status workflow New → Investigating → Resolved → Closed

#### phishing (`/phishing/`) — security-awareness simulation
Internal phishing-simulation campaigns (not a compliance-record module — a training tool).
- Campaign creation with structured template fields **or** custom raw HTML (image upload supported, magic-byte validated)
- Per-recipient tokenized tracking links (`/phishing/t/<token>`), click + form-submit event capture
- SMTP send via Hostinger (`smtp.hostinger.com`), Arabic-safe (`send_message`, not raw `sendmail`)
- Results dashboard per campaign and aggregate reports, gated by `permission_required('phishing')`

### 3.6 Platform & administration

#### admin (`/admin/`)
- User management (create/edit/delete/bulk CSV), granular per-module permissions, temp/contract accounts with expiry
- Department management, audit-log viewer (module/action/date filters)
- Centralized approvals dashboard (GHE/COI/COBEC pending items)
- System settings (auto-approval thresholds, KYC rules), training auto-assignment rules
- Secured admin terminal (whitelisted commands, fully audit-logged)

#### auth (`/auth/`)
- Separate login flows for CMS staff vs. employee portal
- Rate-limited attempts (10/min), account lockout, deactivation enforcement
- Legacy password-hash upgrade on login, full auth audit trail with IP

#### users (`/users/`)
- Profile self-service (contact info, password change, avatar upload)
- Personal compliance-submission history (COI/COBEC/GHE/policies/training)
- Admin view of any user's full compliance status, admin-driven password reset/role change

#### portal (`/portal/`)
Public (no-CMS-login) employee-facing companion to several modules above.
- Compliance dashboard (COI/COBEC/GHE/policy/training status)
- Annual COI/COBEC declaration forms, ad-hoc COI/GHE incident submission with attachments
- Policy acknowledgment signing, training course browsing/enrollment
- PIN-verified secure response to COI clarification requests; tracking-ID thank-you pages

#### tracker (`/tracker/`)
Cross-module analytics for compliance officers.
- Submission-rate statistics (COI/COBEC/GHE, year-selectable), employee × declaration status matrix
- Department-level summaries, CSV export per declaration type plus full roster export

---

## 4. eKYC pipeline — condensed deep-dive

(Full detail: `EKYC_MODULE.md`. This is the module most worth a closer
look since it's the newest and most ML-heavy.)

**Flow:** staff generates a one-time link → customer completes a no-login
consent → capture → processing UI (front/back ID burst capture, selfie
video with an in-browser active-liveness challenge) → upload enqueues onto
a dedicated Redis queue (db 2) → `ekyc-worker` (its own systemd service,
loads ML models once) runs the pipeline → result + audit trail visible to
staff, decrypted on the fly and never written unencrypted to disk.

**Pipeline layers, in order** (`ekyc/pipeline.py`):

| # | Layer | Engine |
|---|---|---|
| 1 | Card alignment | Canny edges + contour boundary detection, perspective warp |
| 2 | Field layout | Fixed fractional crop boxes (Egyptian ID-1 layout; no YOLO — AGPL-incompatible) |
| 3 | Capture-quality guard | Resolution/blur(Laplacian)/brightness/glare checks |
| 4 | OCR | EasyOCR (Arabic+English), per-field multi-frame consensus |
| 5 | National ID decode | Pure logic: century/DOB/governorate/gender from the 14-digit number (check digit never validated — no published algorithm) |
| 6 | Face match | ArcFace/insightface (`buffalo_l`), best cosine similarity across selfie frames vs. ID photo |
| 7 | Passive liveness | Vendored Silent-Face-Anti-Spoofing, dual MiniFASNet checkpoints |
| 8 | Document PAD | Moire (frequency-domain) + reflection/hologram-variance signals, weighted vote |
| 9 | Active liveness | Client-evaluated (MediaPipe blink/turn/smile), taken as-reported |
| 10 | Government verification | Stub, always returns `None` ("not checked," intentionally out of scope) |
| 11 | Risk fusion | Configurable weights → 0-100 score → PASS/REVIEW/FAIL (`ekyc_config` table, runtime-editable) |
| 12 | Screening hook | OCR'd identity run through the `screening` engine; any hit caps the decision at REVIEW |

**Honest limitations (carried forward — read before trusting output for anything real):**
- No real Egyptian ID/selfie samples used anywhere yet — every self-test is synthetic; proves code paths, not real-world accuracy.
- Face-match threshold (0.42) and document-PAD thresholds are community-benchmark/placeholder, not tuned on real local data.
- Active-liveness challenge logic has never been exercised in a real browser end-to-end.
- The old synchronous per-side OCR/PAD capture-time gate was removed (routinely took 40-60s+ on this CPU-only box) — a bad capture is now only caught later, by the async pipeline routing to officer review, not blocked at the moment of capture.
- AdaFace (original brief's first choice) and PaddleOCR (intended second OCR engine) were both dropped for integration-risk/platform-compatibility reasons — ArcFace and EasyOCR are the only engines, no fallback.

---

## 5. Security & access control (platform-wide)

| Feature | Implementation |
|---|---|
| Authentication | Flask-Login + bcrypt; legacy hash auto-upgrade on login |
| Session management | Server-side sessions, 30-min timeout, HttpOnly + SameSite cookies |
| CSRF | Flask-WTF tokens on all POST forms |
| Authorization | Role-based (admin / compliance_officer / compliance_manager / employee) + granular per-module permission grid |
| File uploads | Magic-byte content validation (not just extension), size limits, `secure_filename_strict()` |
| Audit logging | Every compliance action + every eKYC document *view* (not just edit) logged with user/timestamp/IP |
| eKYC media | Fernet encryption at rest, versioned keys, 30-day auto-purge, decrypted only in-memory on staff view |
| Public-facing forms | Where no login is possible by design (whistleblowing, consumer complaints, eKYC capture, phishing landing) — CSRF still enforced wherever a session exists; anonymous channels explicitly avoid IP/cookie logging |

---

## 6. Where to go for more detail

| Doc | Covers |
|---|---|
| `EKYC_MODULE.md` | Full eKYC design rationale, every layer's docstring-level detail, deployment/env vars, self-tests |
| `PHISHING_INTEGRATION.md` | Phishing module's mail-delivery migration history (Render → Hostinger), what was tested |
| `SYSTEM_SPECIFICATIONS.md` | Infra sizing, env var reference, backup/recovery procedure — **stale on module count/DB choice, accurate on everything else listed there** |
| `SETUP_GUIDE.md` | Local dev setup |
