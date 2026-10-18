# regcontrols — Python API for FRA controls

`regcontrols` is the shared foundation that turns every requirement in
[`FRA_NBFI_CONTROL_MAP.md`](FRA_NBFI_CONTROL_MAP.md) into a **control** that is
monitored, evidenced, remediated and reported. Other modules (lending,
prudential, AML hardening, cyber, carbon, inspection readiness) use it **only**
through `regcontrols/api.py`:

```python
from regcontrols.api import (
    get_param, get_param_record,          # regulatory numbers
    register_check, CheckResult,          # automated checks
    record_evidence,                      # evidence items
    raise_finding,                        # findings / remediation plans
    raise_alert, run_control,             # less common
    ParameterNotFound, ParameterNotSet,
)
```

Every call needs a Flask app context (it uses `database.db.get_db()`).

---

## 1. Regulatory parameters — `get_param`

**Rule: no regulatory number is hard-coded anywhere.** Caps, thresholds,
ceilings, SLAs and cycles are rows in `rc_parameters`.

```python
cap = get_param('lending.admin_fee_cap_pct', licence_type='microfinance')   # Decimal('2.5')
days = get_param('rc.escalation_days')                                       # int
window = get_param('lending.prepay_new_loan_window_days', default=None)      # None if missing / not set
old = get_param('lending.admin_fee_cap_pct', 'microfinance', as_of=date(2025, 6, 30))
rec = get_param_record('capital.min_paid_up', 'microfinance')                # full row: unit, legal_reference, needs_review …
```

| Behaviour | Detail |
|---|---|
| Licence | A version for the exact licence (`microfinance`, `consumer_finance`, `leasing`, `factoring`) beats the generic `all` version. |
| Date | The version in force on `as_of` (default today): `effective_from ≤ as_of ≤ effective_to`. Retired versions are ignored. |
| Types | `number` / `amount` / `percent` → `Decimal`; `integer` → `int`; `boolean` → `bool`; `json` → list/dict; `date` → `date`; `text` → `str`. |
| Missing | `ParameterNotFound` (no version covers the date) or `ParameterNotSet` (seeded, value still NULL). Pass `default=` to get a fallback instead. |

Inside a check use `ctx.param(key)` — it applies the company licence type
(Settings `fra_licence_type`, set on the Parameters page) and the run date.
If the parameter is missing the run is stored as **error** with a clear
message, never as a silent pass.

**Naming:** `<area>.<name>_<unit>` in lower case, e.g. `lending.admin_fee_cap_pct`,
`aml.unusual_txn_study_sla_days`, `kyc.refresh_months_high`. Add new keys with
`needs_review=true` and a `TODO(compliance-review)` note when the exact rule is
not confirmed. Seed keys for a new module in your own migration with the same
`WITH ins AS (INSERT … ON CONFLICT DO NOTHING RETURNING …) INSERT INTO
rc_parameter_changes …` pattern used in `20261018_regcontrols.sql`, so the
change history shows where the value came from.

**Changes are maker-checker.** The UI records a pending row in
`rc_parameter_changes`; a *different* user with `perm_regcontrols = admin`
approves it, and only then is `rc_parameters` updated. A new value with a new
effective date closes the previous version the day before (no overlap).

---

## 2. Automated checks — `register_check`

```python
# lending/checks.py
from regcontrols.api import register_check

@register_check('FRA-017', name='Admin fee within cap')
def admin_fee_cap(ctx):
    cap = ctx.param('lending.admin_fee_cap_pct')
    rows = ctx.db.execute("SELECT id, ref, admin_fee_pct FROM lending_loans WHERE admin_fee_pct > %s",
                          (cap,)).fetchall()
    if rows:
        return ctx.fail(f'{len(rows)} loan(s) above the {cap}% cap',
                        affected=[{'table': 'lending_loans', 'id': r['id'], 'label': r['ref']} for r in rows],
                        cap=str(cap))
    return ctx.ok('All loans within the cap')
```

Then add the module path to `CHECK_MODULES` in `regcontrols/engine.py`
(e.g. `'lending.checks'`) so the scheduler process imports it.

**The `ctx` object (`CheckContext`)**

| Attribute / method | Meaning |
|---|---|
| `ctx.control` | the `rc_controls` row (dict) |
| `ctx.as_of` | run date (`date`) |
| `ctx.licence_type` | company licence type |
| `ctx.org_unit_id` | company/unit scope of the run, or `None` |
| `ctx.db` | database connection — **read only**; do not commit inside a check |
| `ctx.param(key, default=…)` | typed parameter for this licence and date |
| `ctx.ok(summary, **details)` / `ctx.warn(summary, affected, **details)` / `ctx.fail(summary, affected, **details)` / `ctx.not_applicable(summary)` | build a `CheckResult` |

**Return values accepted:** `CheckResult`, `dict` with `status` (+ `summary`,
`details`, `affected`), tuple `(status, summary[, affected])`, a status string,
or `True`/`False`. Status is one of `pass`, `warning`, `fail`, `not_applicable`.
`affected` is a list of dicts (`table`, `id`, `label`, any scalar fields); up to
500 are stored, the full count is kept.

**Failure safety:** an exception, a missing parameter or an unknown return
value is stored as `error` and shown on the dashboard. Registering two
different functions for one control raises `ValueError` (use `replace=True`
only on purpose).

**Licence applicability:** a control whose `licence_types` does not include the
company licence (or `all`) is recorded as `not_applicable` without calling the check.

**Controls without a check** — evidence-type controls (and any control that
already has evidence uploaded) use the generic evidence check: pass if at
least one approved, in-date item exists; warning if only expiring or pending
items; fail otherwise. Other controls show "No check" until their module
registers one.

---

## 3. Evidence — `record_evidence`

```python
ev_id = record_evidence('FRA-069', 'Penetration test report 2026',
                        valid_from=date(2026, 3, 1), valid_to=date(2027, 2, 28),
                        reference_no='PT-2026-01', submitted_by=current_user.id,
                        file_path='/tmp/report.pdf', file_name='pentest.pdf')
# automatic, system-generated evidence (e.g. a scheduled SSL check) is stored approved:
record_evidence('FRA-072', 'SSL certificate valid — portal.example.com', valid_to=expiry,
                source='system', source_module='cyber')
```

* Status starts `pending`; a reviewer **other than the submitter** approves or rejects
  (rejection needs a comment). `source='system'` items are stored approved.
* Files go through the shared attachments store (`generic_attachments`, module
  `regcontrols`, record_type `rc_evidence`).
* Daily sweep: approved items past `valid_to` become `expired` and raise an
  `evidence_expired` alert; items within `rc.evidence_expiry_warning_days` raise
  `evidence_expiring`. Approving newer evidence clears both.

---

## 4. Findings & corrective actions — `raise_finding` (FRA-079)

```python
fid = raise_finding('PAR30 above threshold in Branch 3',
                    source='control_failure',          # regulator | internal_audit | self_identified | external_audit | control_failure
                    severity='high',                    # critical | high | medium | low
                    control_codes=['FRA-011', 'FRA-012'],
                    description='PAR30 = 7.2% vs 5% threshold',
                    due_date=date.today() + timedelta(days=30),
                    owner_user_id=credit_head_id,
                    dedupe=True)                        # default
```

* `dedupe=True` returns the existing finding when `(source, source_ref)` was
  already imported, or — for `control_failure` — when an open control-failure
  finding already exists for the first control. Safe to call on every failing run.
* Lifecycle: `open → action_plan → in_progress → pending_verification → closed`.
  Corrective actions (owner, due date, status, evidence) drive the status.
* **Closing requires verification**: every linked control is re-run; the finding
  closes only if they all pass. Controls with no check need a written manual
  verification by someone other than the finding owner.
* **Recurrence detection**: when a linked control fails again after the finding
  was closed as remediated, the finding is reopened, flagged `is_repeated`
  (`repeat_count` + 1) and a critical `repeated_violation` alert is raised.
  FRA-079's own check fails while any repeated violation is open.
* Imports: CSV (template on the Findings → Import page) and one-click import of
  open internal-audit findings (`source_ref = 'IA-<id>'`, linked through
  `rc_controls.erm_control_id`).

---

## 5. Alerts — `raise_alert`

Raised automatically for: `control_failed`, `evidence_expiring`,
`evidence_expired`, `finding_overdue`, `repeated_violation`. One live alert per
subject; a repeat failure refreshes it and re-notifies only every
`rc.alert_renotify_days`.

* Recipient: the control/finding owner; otherwise the Head(s) of Compliance
  (Settings `regcontrols_compliance_head_ids`, falling back to all admins and
  compliance officers). Delivered in-app and by email through
  `services.notification_service.notify`.
* Escalation to the Head(s) of Compliance after `rc.escalation_days`.
* A failed control opens a `REG_CONTROL` case in the unified case list when the
  control has *auto-open case* ticked, or when it is critical and
  `rc.auto_case_on_failure` is `true`.
* A passing run resolves the `control_failed` alert (and syncs the case).

---

## 6. Scheduling

* Cron (hourly is enough): `python scripts/regcontrols_run.py` — runs every
  control whose `next_run_due` has passed, then the evidence-expiry,
  overdue-finding and escalation sweeps. `--control FRA-079` runs one control;
  `--enqueue` hands the work to the RQ `events` worker instead.
* `next_run_due` = last run + the control's frequency (`event` / `on_demand`
  controls are never scheduled).
* `run_control(code, triggered_by='api')` runs one control immediately from code.

---

## 7. Permissions and scoping

`users.perm_regcontrols`: `none` / `view` / `edit` / `admin`.

| Level | Can |
|---|---|
| view | see dashboard, controls, runs, evidence, findings, alerts, parameters |
| edit | run controls, submit and review evidence, manage findings, actions, verification, alerts |
| admin | edit the control library, approve/reject parameter changes, close a finding without remediation, settings, run all due controls |

Records with `org_unit_id` (runs, evidence, findings, alerts) are filtered with
`services.org_service.scope_filter`, like other group/company-scoped modules.

---

## 8. Tables (migration `database/migrations/20261018_regcontrols.sql`)

`rc_parameters`, `rc_parameter_changes`, `rc_controls`, `rc_control_runs`,
`rc_evidence`, `rc_findings`, `rc_finding_controls`, `rc_corrective_actions`,
`rc_finding_events`, `rc_alerts`; plus `users.perm_regcontrols` and the
`REG_CONTROL` row in `case_sla_config`.

The control-library and parameter seed lives in `regcontrols/library.py`;
regenerate the SQL block with `python scripts/regcontrols_seed_sql.py`
(`--check` is run by the tests).

---

## 9. Checklist for a module that adds FRA controls

1. Put checks in `<module>/checks.py`, register with `@register_check('FRA-0xx')`, add the module to `CHECK_MODULES`.
2. Read every limit with `ctx.param(...)`; seed new keys in your migration with `needs_review=true` when unconfirmed.
3. Return `affected` records with `table` + `id` so inspectors can drill down.
4. Use `raise_finding(..., source='control_failure', dedupe=True)` when a breach needs a remediation plan (e.g. FRA-012).
5. Use `record_evidence(..., source='system')` for proofs the system generates itself.
6. Add unit tests for the check logic (keep the decision in a pure function, as `regcontrols/logic.py` does).
