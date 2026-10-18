# ComplyNex — instructions for Claude (cloud sessions)

ComplyNex is a Flask compliance-management platform (sanctions & PEP screening, AML cases/STR, KYC/KYB & eKYC,
risk, governance, policies, declarations, whistleblowing, training, ESG/carbon, Integrys Academy) built for
Egyptian banks, fintechs and payment service providers (CBE / FRA context). Owner: Mohamed Emam.

## How work flows
- You work on **code only**. This repository never contains data: no `.env`, databases, uploads, backups,
  watchlists or personal data. Never add such files, and never commit secrets, real names or customer data.
- Do every task on a **new branch** and open a pull request with a clear summary: what changed, why,
  any **database migration**, and how to test. Mohamed reviews; deployment to the server is a separate,
  manual step (`deploy.sh`), so never assume your change is live.
- You cannot reach the production server, its PostgreSQL, Elasticsearch or Redis. Do not try.

## Stack
- Python 3.12, Flask (blueprints per module: `aml/`, `screening/`, `governance/`, `academy/`, …),
  Jinja templates in `templates/<module>/`, static assets in `static/`.
- PostgreSQL 16 via `database/db.py` (`get_db()` → psycopg2 with RealDictCursor). Gunicorn + gevent in production.
- i18n with Flask-Babel (`_()`), Arabic + English everywhere; RTL must keep working.
- Elasticsearch 8 and Redis are used by screening and rate limiting; code must degrade gracefully without them.

## Database changes
- Never edit live tables by hand in code. Put every schema change in a new file
  `database/migrations/YYYYMMDD_<short_name>.sql`, idempotent (`IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`),
  wrapped in `BEGIN; … COMMIT;`, ending with the needed `GRANT … TO complynex;` (DDL runs as `postgres`).
- New `perm_*` columns on `users` must also be loaded in `models/user.py` `_from_row` and saved in `create_user`.

## Known traps (each one has broken production before)
- **CSP with per-request nonce:** every `<script>` needs `nonce="{{ csp_nonce }}"`; **no inline handlers**
  (`onclick=`, `onchange=` …) — use `data-*` attributes + `static/js/csp_helpers.js` or a module script.
- **A bare `%` inside `_('…')` crashes the page** (gettext formatting): write `{{ _('Pass mark') ~ ' (%)' }}`.
- **psycopg2 treats `%` in SQL as a placeholder:** always parameterise; write `%%` for a literal percent.
- Escape dots in any regex/sed that matches endpoint names (`whistleblowing\.view_case`).
- `url_for()` targets must exist — a missing endpoint is a 500 on render.
- Templates are cached per worker in production; changes need a restart (handled by `deploy.sh`).

## Checks to run before opening a PR
```bash
python -m py_compile $(git diff --name-only origin/main -- '*.py')
for g in csp_guard endpoint_guard url_guard nullscan; do python scripts/$g.py | tail -3; done
```
(`csp_guard` and `url_guard` are pure static checks; `endpoint_guard` and `nullscan` import the app and may
need dependencies installed — if they cannot run in your environment, say so in the PR.)

## Style
- Keep changes focused; do not reformat unrelated code. Match existing patterns in the module you touch.
- Keep the copyright header used at the top of existing Python files on new files.
- User-facing text: English and Arabic, short and clear; compliance wording must stay accurate to Egyptian
  regulation — when unsure, leave a `TODO(compliance-review)` note in the PR instead of guessing.
