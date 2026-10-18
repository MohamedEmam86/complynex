# Phishing Awareness Module — Render → BCMS Integration

## What was Render-dependent

The blueprint, routes, templates, and `phishing_campaigns` / `phishing_recipients` /
`phishing_events` tables were already wired into `app.py` and the BCMS theme before
this pass — that part of the integration had already been done in an earlier session.
The actual live Render dependency was narrower than it looked: **`.env`'s `APP_URL`
was still set to `https://phishing-sim-hwpw.onrender.com`**, which is the value
`phishing/routes.py`'s `send_campaign()` uses to build every tracking link
(`{app_url}/phishing/t/{token}`). Every email sent while that was set would have
pointed recipients at the old Render app instead of complynex.online. The mail
account was also still a Gmail address (`carrefour.egypt.myclub@gmail.com`,
authenticated via a Gmail app password) sent through `smtp.gmail.com`.

There were no hardcoded `onrender`/`phishing-sim-hwpw` strings left anywhere in the
codebase (`grep -rn` came back empty) — the only Render reference was that one
environment variable.

## What changed

**`.env`** (`/var/www/complynex/.env`, kept at `chmod 600`):
```
GMAIL_USER=admin@complynex.online   # was carrefour.egypt.myclub@gmail.com
GMAIL_PASS=<Hostinger mailbox password>   # was a Gmail app password
APP_URL=https://complynex.online    # was https://phishing-sim-hwpw.onrender.com
```

**`phishing/routes.py`**:
- `_send_one_email()`: SMTP host changed from `smtp.gmail.com` to `smtp.hostinger.com`
  (port 587, STARTTLS — unchanged).
- `_send_one_email()`: replaced `srv.sendmail(gmail_user, recipient_email, msg.as_string())`
  with `srv.send_message(msg, from_addr=gmail_user, to_addrs=[recipient_email])`.
  The old call ASCII-encoded the message via `smtplib`, which raised
  `UnicodeEncodeError` on any campaign with Arabic content (the default templates
  are Arabic) — this was a **real, pre-existing bug**, not something the Hostinger
  switch introduced. It would have made every actual campaign send fail in
  production. Caught and fixed during the end-to-end test pass below.
- `_build_email_html()`: now checks `campaign.get('custom_html')` first. If a
  campaign has custom HTML, it's used as the email body as-is, with the literal
  tokens `{{TRACKING_URL}}` and `{{RECIPIENT_NAME}}` substituted in. Falls back to
  the original structured template (sender/offer/title/body/CTA fields) when
  `custom_html` is empty — no behavior change for existing campaigns.
- New route `POST /phishing/upload-image` (`login_required` +
  `permission_required('phishing', level='edit')`): accepts an image, validates it
  with the existing `utils.file_validator.validate_file(..., upload_type='image')`
  (magic-byte check, not just extension), saves it under
  `static/uploads/phishing/` using `secure_filename_strict()`, and returns its
  public URL so it can be referenced in `custom_html` (`<img>` tags need to be
  fetchable by the recipient's mail client without a login).
- `create_campaign()`: now also reads and stores `custom_html` from the form.

**`templates/phishing/campaign_form.html`**: added an "Advanced: Custom HTML
Design" section — an image upload control (AJAX, inserts the resulting `<img>`
tag into the textarea) and a textarea for raw HTML, so a campaign can mimic a
real marketing email's actual design instead of always using the same templated
look. Documented inline that `{{TRACKING_URL}}` must appear as a link for
click-tracking to work.

**`scripts/mig_phishing_custom_html.py`** (additive, idempotent): adds
`phishing_campaigns.custom_html TEXT`. Already applied to the live DB.

**eKYC, unrelated but fixed in the same pass** — see `templates/ekyc/capture.html`
and `static/ekyc/js/capture.js`: added a read-only OCR confirmation screen shown
after each ID side (front/back) passes `check_id_side`, displaying the
OCR-extracted fields (name, national ID, address / occupation, marital status,
gender, expiry) with Confirm/Retake buttons, before advancing to the next step.
Previously this data was extracted and stored correctly but never shown to the
customer — `outcome.fields` was received by the frontend and silently discarded.
Customers can't edit the fields (compliance: stored values must be what OCR
actually read off the card); "Retake" re-captures and re-runs OCR for that side.

## How the mail flow works now

1. `.env` provides `GMAIL_USER=admin@complynex.online`, `GMAIL_PASS`, and
   `APP_URL=https://complynex.online`.
2. `send_campaign()` builds a tracking URL per recipient:
   `{APP_URL}/phishing/t/{token}`.
3. `_build_email_html()` builds the body — either the structured template or a
   campaign's `custom_html`, with `{{TRACKING_URL}}`/`{{RECIPIENT_NAME}}`
   substituted.
4. `_send_one_email()` connects to `smtp.hostinger.com:587`, STARTTLS, logs in as
   `admin@complynex.online`, and sends via `send_message()`.
5. The recipient clicks the link → `GET /phishing/t/<token>` (public, no login —
   targets are simulation subjects, not BCMS users) records a `click` event and
   renders the landing page, which is served from complynex.online directly.
6. If they submit the landing form → `POST /phishing/submit` (CSRF-protected,
   same as any other form on the site) records a `submit` event with whatever
   they entered.
7. Staff view results at `/phishing/<campaign_id>` and `/phishing/reports`,
   gated by `login_required` + `permission_required('phishing')`.

## What was tested

- SMTP login to `smtp.hostinger.com:587` with the new credentials (succeeded;
  465/SSL fallback also coded but not needed).
- One real test email delivered to `admin@complynex.online`.
- The actual `_send_one_email()` code path with Arabic content (post-fix).
- Click tracking (`/phishing/t/<token>`) and submit tracking (`/phishing/submit`,
  including its real CSRF token) on the live complynex.online domain — both
  events recorded correctly in `phishing_events`/`phishing_recipients`.
- `custom_html` persistence through the real `create_campaign` form route, and
  the placeholder-substitution + structured-template-fallback logic.
- Image upload: valid JPEG accepted and served back publicly; a fake "image"
  with a shell-script signature rejected by the magic-byte check.
- All test data (campaigns/recipients/events, uploaded test image) was deleted
  after verification.
- Confirmed Phase A (login, screening), the eKYC worker, and Postgres/Redis/ES
  were unaffected throughout — no errors in `journalctl -u complynex.service`,
  all services `active` before and after each restart.

## Also fixed along the way (not phishing-specific)

Found and killed 4 orphaned `gunicorn` workers left running on `0.0.0.0:5000`
from a manual `nohup` test session on 2026-06-19 (~1.7GB RAM, not part of the
systemd-managed service, not reachable through nginx, zero active connections).
Available memory went from 256Mi to ~1.6Gi after killing them. Redis itself was
never the issue (~2MB used across both DBs); nothing screening- or
Elasticsearch-related was touched.
