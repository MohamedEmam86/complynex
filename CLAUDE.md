# ComplyNex — instructions for Claude (cloud sessions)

ComplyNex is a Flask compliance-management platform (sanctions & PEP screening, AML cases/STR, KYC/KYB & eKYC,
risk, governance, policies, declarations, whistleblowing, training, ESG/carbon, Integrys Academy) built for
Egyptian banks, fintechs and payment service providers (CBE / FRA context). Owner: Mohamed Emam.

## Product principle (most important)
ComplyNex is a **general, configurable Compliance Management System** that any organisation can adopt to meet
**any** regulatory or internal requirement — banks, PSPs, fintechs, NBFIs, insurers, listed companies or
non-financial firms, under any regulator (CBE, FRA, EMLCU, PDPL, ITIDA, or foreign frameworks).
- Never build features tied to one company, sector or regulator. Model them as **configuration**:
  regulators, frameworks and regulations as data; requirements → controls → tests → evidence; parameters
  (limits, thresholds, deadlines) per jurisdiction / licence type with legal references; sector-specific
  logic as optional **packs** that can be enabled per tenant (e.g. an "FRA NBFI pack", a "CBE PSP pack").
- A specific source (e.g. docs/regulatory/FRA_NBFI_CONTROL_MAP.md) is **one example pack** used to prove the
  framework — the engine, screens and data model must work unchanged for a different regulator's pack.
- Industry-specific data (loans, merchants, policies…) enters through generic import/API adapters into
  pack-owned tables; core modules must not depend on any pack.

## How work flows
- You work on **code only**. This repository never contains data: no `.env`, databases, uploads, backups,
  watchlists or personal data. Never add such files, and never commit secrets, real names or customer data.
- Do every task on a **new branch** and open a pull request with a clear summary: what changed, why,
  any **database migration**, and how to test. Mohamed reviews; deployment to the server is a separate,
  manual step (`deploy.sh`), so never assume your change is live.
- You cannot reach the production server, its PostgreSQL, Elasticsearch or Redis. Do not try.

## Generic core, optional packs (design rule)
- ComplyNex is a **general, configurable** Compliance Management System for any organisation, sector and
  regulator. Model regulators, frameworks, requirements, controls, tests, evidence and parameters as DATA
  (regcontrols catalog, editable in the UI) — never as code tied to one regulator or company.
- Regulator- or sector-specific content and logic go in an optional content pack under `packs/<code>/`
  (see `docs/regulatory/REGCONTROLS_API.md` §5). Core modules must never import or mention a pack.
- Demo / seed data uses a fictional company only. Never put a real client's name, figures, banks or branches
  in code, seed data, docs or commit messages.

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
- Anything that deletes or changes data is **POST-only** with a CSRF token (a `<form>` with a button, not an `<a href>`); `scripts/method_guard.py` blocks deploys that break this.
- Sessions carry `'<user id>:<auth_version>'` (`User.get_id`); test clients use `User.session_id_for_app(app, 1)`, not `'1'`.
- Templates are cached per worker in production; changes need a restart (handled by `deploy.sh`).

## Per-user access control (access/)
- Every module and feature a user can be granted is DATA: `access/catalog.py` (core) and each pack's manifest
  `Pack(access_modules=[...])` (packs only — the core never names a pack). A feature lists the endpoints it covers.
- One check for everything: `access.service.endpoint_allowed()` — used by the request gate (403 page / JSON), the
  sidebar (`{% filter cx_nav %}` prunes links), the employee portal (`cx_can('portal.coi')`), the restricted
  workspace and the matrix preview. Superadmin is unrestricted; `X-API-Key` requests keep their own scopes.
- A NEW PAGE must belong to a feature (an existing module's `pattern`/`default`, or a new feature);
  `tests/test_access/test_registry.py` fails on a page outside every module. Guards record their rule with
  `access.registry.mark(...)` (`permission_required` does it already) so backfill/old-rule derivation stays exact.
- Access types: `users.access_mode` = cms | portal | restricted. Grants: `user_access_grants`; changes:
  `user_access_audit`. Saving the matrix writes the module levels through to `perm_*` / `user_module_permissions`.

## Checks to run before opening a PR
```bash
python -m py_compile $(git diff --name-only origin/main -- '*.py')
for g in csp_guard endpoint_guard url_guard method_guard nullscan; do python scripts/$g.py | tail -3; done
```
(`csp_guard` and `url_guard` are pure static checks; `endpoint_guard` and `nullscan` import the app and may
need dependencies installed — if they cannot run in your environment, say so in the PR.)

## Style
- Keep changes focused; do not reformat unrelated code. Match existing patterns in the module you touch.
- Keep the copyright header used at the top of existing Python files on new files.
- User-facing text: English and Arabic, short and clear; compliance wording must stay accurate to Egyptian
  regulation — when unsure, leave a `TODO(compliance-review)` note in the PR instead of guessing.

## Fit & proper forms (governance/fp)
- Regulator and internal forms are DATA: `governance/fp/forms/<code>.json` (+ the regulator's original `.docx`
  when there is one). Regulator forms reproduce the questions word for word ("locked") and map every item to the
  content controls of the original Word file, so `/governance/fit-proper/forms/<id>/docx` returns the ORIGINAL
  regulator form filled in (empty fields = "N/A", signature fields left for wet/digital signature).
  `tests/test_fit_proper` checks that every control of the CBE form is mapped exactly once.
- Add a regulator's new/updated form by adding a JSON (and its .docx) — no code change.
- Workflow: draft -> candidate_completed -> under_review -> approved_internal -> signed (scan attached)
  -> submitted -> regulator_approved / regulator_rejected. Institution assessment: 5 criteria scored 1–5 with a
  written justification; the guides are in `utils/rating_guides.py`.
- Key officials (`fp_officials`): board members (imported from board_members), executives (users) and
  committee members who are not board members (`fp_official_committees`).

## Rating guides
`utils/rating_guides.py` holds what each level of every rating scale means (bilingual). Show it next to an input
with `{% from 'partials/rating_guide.html' import guide_panel with context %}{{ guide_panel('risk.likelihood') }}`;
all guides: `/guides/ratings`; ESG/carbon guideline: `/guides/esg-carbon`.

## Secondary instances and instance profiles (scripts/instance/)
- The same code can run as a SECONDARY instance on the server: own folder `/var/www/complynex-<name>` (git worktree,
  detached; `.cx_instance` marker), own database + role `complynex_<name>` (schema = schema-only dump of the main
  database: the migrations alone cannot build it from empty), own Redis db, `complynex-<name>.service` on
  127.0.0.1:<port> and a daily `complynex-<name>-backup.timer`. Create / remove: `scripts/instance/create_instance.sh`,
  `remove_instance.sh`; first superadmin (one-time set-password link): `scripts/instance/create_superadmin.py`.
  `deploy.sh` updates every instance in `/etc/complynex/instances.list` after the main deploy (code, new migrations,
  restart, health); an instance failure is reported loudly and never rolls back the main instance.
- `CX_INSTANCE_PROFILE` (default `full` = everything) chooses what an instance offers; profiles are DATA in
  `utils/instance_profile.py` (access-catalogue module / feature keys). `governance` registers only the governance,
  policies, COI, declarations, portal, admin and general pages and never imports screening, ML, Elasticsearch, eKYC
  or packs (an import guard refuses them; optional callers must keep catching ImportError). Pages outside the
  profile are 404 and `url_for()` of them gives an `/_off/` link that the menus drop. `CX_UPLOAD_QUOTA_MB` caps an
  instance's upload folder. Nothing in code, docs or commits names a client of an instance.
- (The earlier demo instance was removed in Nov 2026; `utils/demo.py` switches remain for its marker only.)
