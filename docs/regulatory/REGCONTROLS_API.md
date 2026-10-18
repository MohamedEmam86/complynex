# regcontrols — generic compliance control framework

`regcontrols` is the core that lets ComplyNex monitor, evidence, remediate and
report compliance with **any** regulator, regulation or standard — a central
bank's PSP rules, a financial regulator's NBFI requirements, a data-protection
law or a foreign framework. Nothing in the core is tied to one company, sector
or regulator:

* **Data, not code** — regulators, frameworks, requirements, controls, areas,
  licence types, owner roles and regulatory parameters are rows, editable in
  the UI (Compliance Controls → Frameworks & Library / Controls / Parameters),
  each with legal references, jurisdiction and licence type where relevant.
* **Content packs** — regulator- or sector-specific content *and logic* come
  in optional packs under `packs/<code>/`, enabled per installation on
  Compliance Controls → Content packs. The core never imports a pack.

```
core (regcontrols/)                          optional packs (packs/<code>/)
────────────────────────────────────────     ─────────────────────────────────────
regulators · frameworks · requirements        framework + requirements + controls (data)
controls ↔ requirements (many-to-many)        areas · licence types · owner roles
check registry (by check key)                 regulatory parameters (needs_review)
evidence · manual tests · findings · CAPs     sector modules & their checks/sweeps
alerts · escalation · cases                   (e.g. lending conduct in fra_nbfi)
parameter registry (maker-checker)            menus · module permissions
generic checks (core.*)
```

Other modules use the core through `regcontrols/api.py`:

```python
from regcontrols.api import (
    get_param, get_param_record,          # regulatory numbers
    register_check, CheckResult,          # automated checks (by check key)
    register_sweep,                       # data refreshes that write, run before checks
    record_evidence, record_manual_test,  # evidence items / manual test results
    raise_finding, raise_alert,           # findings / alerts
    run_control,
    Pack, register_pack, catalog,         # writing a content pack
    register_unusual_candidate,           # put a detected event on the AML unusual-transactions register
    register_expected_source,             # declare a detector whose events must all be on that register
    install_key_function_type,            # pack vocabulary for Prudential > Key functions
    install_branch_role,                  # pack vocabulary for Prudential > Branches (minimum staffing)
    install_integration,                  # declare an expected external integration (IT resilience)
    ParameterNotFound, ParameterNotSet,
)
```

Every call needs a Flask app context (it uses `database.db.get_db()`).

---

## 1. Data model

| Table | What it holds |
|---|---|
| `regulators` (existing table, + `name_ar`, `jurisdiction`) | any regulator / standard-setter |
| `rc_frameworks` | a regulation, rulebook or standard (code, regulator, jurisdiction, version, source document, `pack_code`) |
| `rc_requirements` | requirements of a framework (ref code, title/text EN/AR, legal reference, area) |
| `rc_controls` | the organisation's controls (type, frequency, criticality, owner, licence types, **check_key**, parameters used) |
| `rc_control_requirements` | which requirements a control satisfies — one control can serve several frameworks |
| `rc_areas`, `rc_licence_types`, `rc_owner_roles` | vocabularies (data, not code) |
| `rc_parameters` (+ `rc_parameter_changes`) | regulatory numbers by licence type and date, maker-checker history |
| `rc_control_runs` | every automated check run and manual test result |
| `rc_evidence` | evidence items with validity, four-eyes review, files in `generic_attachments` |
| `rc_findings`, `rc_finding_controls`, `rc_corrective_actions`, `rc_finding_events` | findings, action plans, history |
| `rc_alerts` | live alerts, escalation, optional case |
| `rc_packs`, `user_module_permissions` | pack state per installation, permissions for pack modules |

Fixed, regulator-neutral vocabularies (control types, frequencies,
criticality) live in `regcontrols/vocab.py`.

---

## 2. Regulatory parameters — `get_param`

**Rule: no regulatory number is hard-coded anywhere.** Caps, thresholds,
ceilings, SLAs and cycles are rows in `rc_parameters`.

```python
cap = get_param('lending.admin_fee_cap_pct', licence_type='microfinance')   # Decimal('2.5')
days = get_param('rc.escalation_days')                                       # int
window = get_param('aml.unusual_txn_study_sla_days', default=None)           # None if missing / not set
old = get_param('lending.admin_fee_cap_pct', 'microfinance', as_of=date(2025, 6, 30))
rec = get_param_record('capital.min_paid_up', 'microfinance')                # full row: unit, legal_reference, needs_review …
```

| Behaviour | Detail |
|---|---|
| Licence | A version for the exact licence type beats the generic `all` version. Licence types are data (`rc_licence_types`). |
| Date | The version in force on `as_of` (default today). Retired versions are ignored. |
| Types | `number` / `amount` / `percent` → `Decimal`; `integer` → `int`; `boolean` → `bool`; `json` → list/dict; `date`; `text`. |
| Missing | `ParameterNotFound` / `ParameterNotSet` — or pass `default=`. |

Inside a check use `ctx.param(key)`: it applies the installation's licence type
(Settings `rc_licence_type`, chosen on the Parameters page) and the run date. A
missing parameter makes the run an **error** with a clear message, never a pass.
Changes are maker-checker: a *different* admin approves before a value applies.

**Naming:** `<area>.<name>_<unit>`, lower case. Engine settings use `rc.*` and
ship with the core; regulatory parameters ship with a pack or are added in the UI.

---

## 3. Automated checks — `register_check` (by check key)

A check is registered under a **check key**; a control is bound to it through
`rc_controls.check_key` (set by a pack, or chosen from a dropdown on the
control's edit page). The same check can test controls of different frameworks.

```python
from regcontrols.api import register_check

@register_check('my_pack.fee_cap', name='Fee within cap')
def fee_cap(ctx):
    cap = ctx.param('lending.admin_fee_cap_pct')
    rows = ctx.db.execute("SELECT id, ref FROM ... WHERE fee_pct > %s", (cap,)).fetchall()
    if rows:
        return ctx.fail(f'{len(rows)} item(s) above the {cap}% cap',
                        affected=[{'table': '...', 'id': r['id'], 'label': r['ref']} for r in rows])
    return ctx.ok('All within the cap')
```

**Check settings (`rc_controls.check_config`)** — one generic check can serve many
frameworks; each control tunes it with a JSON object (edited on the control page,
read as `ctx.config`). Example: `core.kyc.fields` with
`{"subjects": ["aml_customer"], "fields": ["gender"]}`. The AML/KYC core checks
(`amlkyc/checks.py`, keys `core.aml.*`, `core.kyc.*`, `core.screening.*`,
`core.audit.*`, `core.policies.*`, `core.training.*`) list their settings in the
module docstring. The prudential / governance / financial-reporting checks
(`prudential/checks.py`: `core.prudential.*`, `core.governance.*`, `core.finance.*`)
work the same way. Finance figures reach them through `prudential/providers.py`, so a
future ERP / finance module can feed the same checks by registering a provider.
The IT / cyber / business-continuity checks (`cyber/checks.py`: `core.cyber.*`,
`core.risk.register_fresh`) read the IT-resilience registers of the cyber module; backup
jobs and integrations can report through `POST /api/v1/cyber/backup-status` and
`POST /api/v1/cyber/integration-exchange` (API key scope `cyber:write`).

Key prefixes: `core.` for checks shipped with the core (`regcontrols/builtin_checks.py`,
always loaded), `<pack_code>.` for a pack's checks (loaded only while the pack is enabled).

| `ctx` | |
|---|---|
| `ctx.control` | the `rc_controls` row |
| `ctx.as_of`, `ctx.licence_type`, `ctx.org_unit_id` | run date, installation licence, scope |
| `ctx.db` | connection — **read only**; writes go in a sweep |
| `ctx.param(key, default=…)` | typed parameter |
| `ctx.ok / warn / fail / not_applicable` | build a `CheckResult` |

Return values accepted: `CheckResult`, a dict with `status`, a tuple
`(status, summary[, affected])`, a status string, or `True`/`False`.

Safety: an exception, a missing parameter, an unknown return value, or a
`check_key` whose pack is disabled all store an **error** run. Registering two
different functions under one key raises.

**Controls without a check** — evidence-type controls (and any control with
evidence uploaded) use the generic evidence check. Any control can also get a
**manual test result** (`record_manual_test` / "Record a manual test" on the
control page): pass / warning / fail / not applicable with a description, with
the same alert and recurrence consequences as an automated run.

**Sweeps** — work that writes (recompute derived data, open a remediation
finding, register an AML candidate) runs before the scheduled checks:

```python
from regcontrols.api import register_sweep

@register_sweep(pack='my_pack')          # runs only while my_pack is enabled
def refresh():
    ...
    return {'updated': n}                # logged by scripts/regcontrols_run.py
```

---

## 4. Evidence, findings, alerts

```python
record_evidence('CTRL-069', 'Penetration test report 2026', valid_from=..., valid_to=...,
                submitted_by=user_id, file_path='/tmp/report.pdf')
record_evidence('CTRL-072', 'Certificate valid — portal.example.com', valid_to=expiry,
                source='system', source_module='cyber')            # system evidence is stored approved

fid = raise_finding('Portfolio at risk above threshold — branch B3', source='control_failure',
                    source_ref='PAR30-branch-B3', severity='high', control_codes=['CTRL-011'],
                    due_date=..., dedupe=True)
```

* Evidence: validity period, review by someone other than the submitter, daily expiry sweep.
* Findings: regulator / internal audit / external audit / self-identified / control failure;
  optional `regulator_id` / `framework_id`; action plan; **closing requires verification**
  (every linked control re-run and passing, or a written manual verification by someone
  other than the owner); **recurrence detection** reopens a closed finding as a repeated
  violation when a linked control fails again. CSV import and one-click import of open
  internal-audit findings.
* Alerts: control failed / evidence expiring / evidence expired / finding overdue /
  repeated violation → owner (in-app + email), reminders, escalation to the Head(s) of
  Compliance after `rc.escalation_days`, optional `REG_CONTROL` case.

---

## 5. Writing a content pack

```
packs/my_pack/
  __init__.py      manifest: register_pack(Pack(...)) + install(db)
  library.py       data: regulator, framework, requirements/controls, vocabularies, parameters
  checks.py        optional: @register_check('my_pack.…') / @register_sweep(pack='my_pack')
  <module>/        optional sector module (blueprint, service, templates)
```

```python
from regcontrols.api import Pack, catalog, register_pack

def install(db):                      # idempotent; never overwrites UI edits
    reg = catalog.install_regulator('CB', 'Central Bank (example)', jurisdiction='EG', db=db)
    catalog.install_ref('licence_types', 'psp', 'Payment service provider', pack_code='my_pack',
                        regulator_id=reg, db=db)
    fw = catalog.install_framework('CB-PSP', 'PSP rulebook', regulator_id=reg, pack_code='my_pack', db=db)
    req = catalog.install_requirement(fw, 'Art. 5', 'Merchant due diligence', db=db)
    catalog.install_control({'code': 'PSP-001', 'title_en': '...', 'control_type': 'automated',
                             'check_key': 'core.findings_not_repeated'},
                            pack_code='my_pack', requirement_ids=[req], db=db)
    catalog.install_parameter({'key': 'psp.kyb_refresh_months', 'value': None, 'value_type': 'integer',
                               'needs_review': True, 'review_note': 'TODO(compliance-review)'},
                              pack_code='my_pack', framework_id=fw, db=db)
    db.commit()

register_pack(Pack(
    code='my_pack', name_en='…', name_ar='…', version='1', install=install,
    check_modules=['packs.my_pack.checks'],
    blueprints=['packs.my_pack.module.routes:bp'],          # pages answer 404 while disabled
    menu=[('my_module.dashboard', 'Dashboard', 'لوحة', 'my_module')],
    menu_title_en='My pack', menu_title_ar='…',
    permissions=[('my_module', 'My module', '…', ('none', 'view', 'edit'))],
))
```

Pack rules:

1. The core must not reference the pack. Core → pack is never imported; pack → core only through `regcontrols.api`.
2. All content is data installed through `catalog.install_*`, so users can edit it later.
3. Pack module permissions are declared in the manifest and stored in
   `user_module_permissions` (no new `users` column); the user form shows them automatically.
4. Pack schema goes in its own migration `database/migrations/<date>_pack_<code>_<name>.sql`.
   Tables are harmless while the pack is disabled.
5. Demo data uses a **fictional** company only — never a real client name, figure, bank or branch.

Enabling a pack runs `install()` and switches its controls on. Disabling it switches them
off (remembering which) and hides its pages and menus. Its data is kept.

---

## 6. Scheduling, permissions, scoping

* Cron (hourly is enough): `python scripts/regcontrols_run.py` — sweeps, due controls,
  evidence-expiry / overdue-finding / escalation sweeps. `--control CODE` runs one control;
  `--enqueue` hands it to the RQ `events` worker.
* `users.perm_regcontrols`: `view` (see), `edit` (run, test, evidence, findings, alerts),
  `admin` (library, frameworks, parameters approval, packs, settings).
* Records with `org_unit_id` are filtered with `services.org_service.scope_filter`.

The first example pack is `packs/fra_nbfi/` (Egypt FRA requirements for non-bank financial
institutions), built from `docs/regulatory/FRA_NBFI_CONTROL_MAP.md`.
