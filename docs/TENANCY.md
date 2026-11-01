# Tenant isolation (Phase 6: P6-1, P6-3)

Owner decision (Oct 2026): one database for many companies, every company-owned row carries a
`tenant_id`, PostgreSQL row-level security (RLS) keeps companies apart; the screening lists stay
shared; a large company can get its own database instead.

Status (1 Nov 2026): the framework is in the code and **switched off**. Nothing changes in
production until the steps under *Rollout* are done in order.

## Model

| Class | Tables (production, 1 Nov 2026) | tenant_id | RLS |
|---|---|---|---|
| tenant | 319 tables, ~135k rows (customers, cases, screening results/queue, internal lists, audit logs ...) | NOT NULL, default = session tenant | yes: `tenant_id = app.tenant_id` |
| tagged | `users`, `api_keys` | NOT NULL | no (read before the tenant is known: login, API key); the app filters them |
| mixed | `screening_watchlist` (2.9M rows) | NULL = shared list row, set = a tenant's private internal-list copy | yes: `tenant_id IS NULL OR tenant_id = app.tenant_id`; writes only for the own tenant |
| shared | 31 tables: list sources/versions/alerts, entity links, PEP relations, central PEP database, FATF table, emission factors, regulators, screening_config | none | none |
| system | 21 tables: `bk_*` backups, academy, talent pool, `tenants` | none | none |

The classification lives in `database/tenancy.py` (`classify()`); everything not listed is
tenant-owned, so a new table is isolated by default.

### Request context
* `database/tenancy.init_app` (registered right after the DB in `app.py`) sets `g.tenant_id`
  from the logged-in user (`users.tenant_id`) and re-binds the request connection.
* `database/db.get_db` binds every pooled connection to `g.tenant_id`; `close()` clears it before
  the connection goes back to the pool (`set_config('app.tenant_id', ..., false)`, committed at
  once so a later rollback cannot undo it). Safe with gevent: one pooled connection per request.
* API: `api/auth.require_api_key` fixes the tenant from the key (`api_keys.tenant_id`).
* Screening engine: `screen_person(..., tenant_id=None)` binds its own connection at the start of
  each screening (request tenant, or the explicit argument for background jobs) and, with the
  flag on, adds an ES filter: shared documents + this tenant's private ones.
* Private lists (P6-3): `internal_blacklist`, `internal_pep`, whitelist tables are tenant-owned;
  `scripts/sync_internal_to_watchlist.py` copies each row with its tenant and a tenant-specific
  `source_id` (`...-t<id>` for tenants other than 1).

### Fail closed
With enforcement, a connection with no tenant sees no tenant rows and cannot insert into a
tenant table (the strict default gives NULL -> NOT NULL error). Shared list rows stay visible.

## Proven (scratch database, 1 Nov 2026)
`scripts/tenancy_selftest.py` on a copy of the production schema (prepare + enforce applied, two
tenants, connected as the app role `complynex` without BYPASSRLS): 14/14 checks passed - each
tenant sees only its rows and the shared lists, cannot read, update, delete or write the other's
rows, cannot write shared list rows, no tenant = nothing visible and inserts refused, `users` stays
readable, a returned pooled connection carries no tenant. `relax` switched RLS off again cleanly.
The scratch database was dropped afterwards.

## Rollout (in this order; each step is reversible)
1. **Prepare (online, minutes):** `scripts/tenancy_sql.py --db complynex_db --phase prepare > prepare.sql`,
   review, back up (`pg_dump`), apply as postgres. Adds `tenants`, `tenant_id` (default 1) with
   index and FK, and the policies. RLS stays off: no behaviour change.
2. **Unique keys:** `--phase report` lists 71 UNIQUE constraints on tenant tables without
   tenant_id. Each one that is global by meaning (codes, references, e-mail templates, years)
   must become `UNIQUE (tenant_id, ...)` before a second tenant is created. Child-scoped ones
   (`project_id, ...`) can stay.
3. **Background jobs:** every process that opens its own connection (74 files call
   `psycopg2.connect`) must either run as the maintenance role (list loaders, ES sync, entity
   links, backfills, monitoring, migrations: create a LOGIN role with BYPASSRLS, its own
   password in `.env` as `MAINT_DB_USER/MAINT_DB_PASSWORD`) or bind a tenant explicitly
   (ongoing screening, bulk worker, re-screening, case sync, event dispatcher: per tenant, pass
   `tenant_id` to `screen_person`, call `tenancy.bind` on their connection).
4. **Config split:** `screening_config` is shared today. Tenant-level keys (thresholds, action
   table, regulatory scope, whitelist mode, four eyes) need a per-tenant override table; list
   operations keys (guard, max age, OpenSanctions mode) stay global.
5. **Admin screens:** tenant management (create tenant, first admin user), user list filtered by
   tenant, an operator role that can switch tenant (`tenancy.set_request_tenant`).
6. **Enforce:** `--phase enforce`, apply, set `TENANCY_ENFORCED=1`, restart. Watch the server
   status page and the logs for "permission denied" / NOT NULL errors on tenant_id.
7. **Emergency:** `--phase relax` switches RLS off again without losing columns or policies.

## A large tenant with its own database
Same code, separate installation of the database: create the database from
`database/baseline/schema.sql` + `database/migrations/*.sql` (see docs/OPERATIONS.md), point that
tenant's instance at it (`POSTGRES_DB` etc. in its `.env`), keep one tenant (id 1) inside it.
The shared lists are loaded by its own list update, or served by the central screening service
(P6-2) once that exists. RLS can stay off there (one tenant).

## Risks
* Every connection path must set the tenant before enforcement; a missed path fails closed
  (empty pages / errors), which is safe but visible: run step 3 completely and test on a copy.
* Superuser / table-owner sessions bypass RLS unless FORCE is set (enforce sets it).
* Entity links and PEP relations are shared: a private internal-list record of tenant A could
  be linked to shared records; RLS hides A's rows from B, but the cluster ids are shared.
