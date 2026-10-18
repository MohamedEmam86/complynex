# Lending data import — CSV, Excel and JSON API

ComplyNex is not the core lending system. Lending data reaches it in three ways:

1. **File upload** — Lending > Import data, one CSV or Excel (.xlsx) file per data type. Templates can be downloaded from the same page.
2. **JSON API** — `POST /api/v1/fra-nbfi/lending/import` with header `X-API-Key` (a key with scope `lending:write`, issued under `/api/v1/keys`).
3. **Manual entry** — New client / New loan, and the forms on the loan page (contract, documents, credit study, visits). Meant for small portfolios.

Rows are matched on their reference (`client_ref`, `loan_ref`, `loan_ref`+`seq` …), so re-sending a file **updates** rows instead of duplicating them. Invalid rows are reported with their line number; valid rows in the same file are still saved. National ID numbers are never stored — only a hash, as elsewhere in ComplyNex.

**Order:** clients → loans → contracts, documents, credit_studies, instalments, visits, early_repayments, reschedulings, transfers.

**Formats:** dates `YYYY-MM-DD`; amounts as plain numbers (thousand separators allowed); yes/no columns accept `yes/no/1/0/true/false/نعم`; `cost_lines` is a JSON list such as `[{"label": "rent", "amount": 1500}]`.

## Columns (required in bold)

- **clients**: **client_ref**, **full_name**, client_type, national_id, gender, phone, address, governorate, business_activity, monthly_revenue, project_size
- **loans**: **loan_ref**, **client_ref**, **amount**, product_code, tenor_months, interest_rate_pct, apr_pct, admin_fee_amount, other_fees_amount, branch_code, officer_code, status, application_date, approval_date, disbursement_date, maturity_date, outstanding_principal, days_past_due, gps_lat, gps_lng, purpose
- **contracts**: **loan_ref**, contract_no, contract_date, signed_by_lender, lender_signed_at, signed_by_client, client_signed_at, penalty_clause_rate_pct, penalty_clause_cap_pct
- **documents**: **loan_ref**, **doc_type**, received_date, reference_no, notes
- **credit_studies**: **loan_ref**, study_date, officer_code, monthly_revenue, monthly_costs_total, cost_lines, household_expenses, other_debt_service, net_income, dsr_pct
- **instalments**: **loan_ref**, **seq**, **due_date**, principal_due, interest_due, fees_due, paid_amount, paid_date, penalty_charged, status
- **visits**: **loan_ref**, planned_date, visit_date, officer_code, outcome, notes
- **early_repayments**: **loan_ref**, **settlement_amount**, request_date, prepayment_fee, executed_date, consent_signed, cost_acknowledged, disclosure_given
- **reschedulings**: **loan_ref**, **resched_date**, fee_amount, old_tenor, new_tenor, reason
- **transfers**: **loan_ref**, **transfer_date**, instalments_moved, fee_amount

Loan `status`: application, approved, disbursed, closed, written_off, rejected. Document `doc_type`: national_id, contract, receipt_acknowledgement, credit_study, guarantor_id, project_photo, commercial_register, tax_card, utility_bill, resignation_letter, other.

## JSON API

```http
POST /api/v1/fra-nbfi/lending/import
X-API-Key: <key with lending:write>
Content-Type: application/json

{"kind": "loans", "rows": [{"loan_ref": "L-1001", "client_ref": "C-77", "amount": 25000, "status": "disbursed", "disbursement_date": "2026-09-01"}]}
```

Response `200` when every row was saved, `207` when some rows failed:

```json
{"success": true, "data": {"batch_id": 19, "rows_total": 2, "rows_ok": 1, "rows_failed": 1, "errors": [{"line": 2, "error": "unknown loan_ref NOPE"}]}}
```

For the API, `line` is the row number in `rows` (starting at 1). At most 5,000 rows per call.

## What happens after an import

- Each touched loan's origination file is re-checked (FRA-009, 013, 014, 015 and product documents).
- New clients are linked to the party registry (Entity 360, role `LENDING_CLIENT`).
- The scheduled regcontrols run (`scripts/regcontrols_run.py`) refreshes days past due, the credit-study QA queue, PAR snapshots, PAR remediation findings and prepayment/refinance AML candidates, then runs the lending checks.
- A loan imported as `disbursed` with an incomplete file is recorded as it is (it already happened). The checks report it. The disbursement gate applies only when the status is changed inside ComplyNex.
