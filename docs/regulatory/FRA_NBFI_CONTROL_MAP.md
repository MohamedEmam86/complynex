# FRA NBFI Regulatory Control Map (anonymised)

Source: findings of an FRA inspection memo of an Egyptian microfinance / consumer-finance company, generalised into
requirements. **No client name, branch, counterparty or figure from the memo may appear in code, seed data or UI.**
Demo data must use a fictional company ("Nile Microfinance S.A.E." or similar).

Goal: turn ComplyNex into a **regulatory control system** for FRA-supervised non-bank financial institutions
(microfinance, consumer finance, leasing, factoring): each requirement below becomes a **control** that is
monitored automatically where data allows, raises an alert/case when breached, needs evidence when it cannot be
automated, and rolls up into an "Inspection Readiness" score. Every numeric limit is a **configurable regulatory
parameter** (value, unit, effective date, legal reference, licence type) — never hard-coded. Where the memo does not
give the exact rule, seed the parameter with `needs_review=true` and a `TODO(compliance-review)` note.

Columns: **ID · requirement · control type** (A = automated rule on data, E = evidence/attestation with due date,
W = workflow/approval gate, M = metric/KPI) **· what the system must do · module**.

## 1. Capital, solvency, licensing, key functions
| ID | Requirement | Type | System behaviour | Module |
|---|---|---|---|---|
| FRA-001 | Paid-up capital ≥ licence minimum | A/M | Capital register (authorised/issued/paid/registered, by date); compare with minimum per licence type; red if below; days-to-deadline | Prudential |
| FRA-002 | Capital increase completed within granted extensions | W/A | Regulatory deadlines register (general/special extensions, letters); countdown alerts at 60/30/7 days; escalation to board | Prudential |
| FRA-003 | Solvency standards (equity, leverage, capital base) | A/M | Quarterly solvency calculator from financial data input/import; negative equity = critical; trend chart | Prudential |
| FRA-004 | Clients within licensed activity scope (e.g. microfinance revenue/size ceilings) | A | Eligibility rule at origination and on portfolio import: client monthly revenue / project size vs ceiling parameter; breach → block or exception with approval | Lending conduct |
| FRA-005 | Consistent registered address on official documents | A/E | Corporate profile is single source of truth for address; document templates pull it; checker flags uploaded board minutes/letters whose address ≠ registered | Governance |
| FRA-006 | Key functions filled and notified to FRA | W/E | Key-functions register (role, holder, fit&proper, FRA notification date/ref, no-objection status); vacancy and "filled but not notified" alerts | Governance |
| FRA-007 | Branch manager appointed with FRA no-objection; replacement after resignation | W | Branch register with manager; no-objection required before "active"; vacancy timer | Governance |
| FRA-008 | Minimum operational staffing per branch (e.g. loan officers) | A/M | Branch staffing matrix vs required roles parameter | Governance |
| FRA-009 | Financing contracts signed by both parties; resignations signed | A/E | Contract completeness check (lender signature, client signature, dates); unsigned → cannot mark disbursed | Lending conduct |

## 2. Origination, client files, portfolio follow-up
| ID | Requirement | Type | System behaviour | Module |
|---|---|---|---|---|
| FRA-010 | Post-disbursement client follow-up | A/M | Follow-up visits schedule per loan; overdue visits alert; PAR30 by branch/officer | Lending conduct |
| FRA-011 | Collections & arrears monitoring | A/M | Ageing buckets (1-30, 31-60, 61-90, 91-120, >120); PAR thresholds parameters; branch heatmap | Lending conduct |
| FRA-012 | Effective remediation plan for portfolio deterioration | W | Breach of PAR threshold auto-opens a remediation plan (actions, owner, deadline, monthly re-measure); worsening vs previous inspection flagged | Lending conduct + Findings |
| FRA-013 | Project location (GPS) in client file and database (mandatory above amount threshold) | A | Mandatory lat/long above parameter amount; missing → file incomplete | Lending conduct |
| FRA-014 | Client acknowledgement of receipt of funds | A | Required document type before "disbursed" | Lending conduct |
| FRA-015 | Detailed client solvency/credit study | A | Structured credit-study template (revenues, cost lines, household expenses, debt service, DSR); minimum fields | Lending conduct |
| FRA-016 | Due care in credit study (no templated/copied figures) | A | Anomaly detection: identical figures across clients/officer, round numbers, too few cost lines, revenue/cost ratios outliers → QA flag | Lending conduct |

## 3. Pricing, fees, penalties, consumer protection
| ID | Requirement | Type | System behaviour | Module |
|---|---|---|---|---|
| FRA-017 | Administrative fees within cap (% parameter) | A | Fee engine validation on each loan; breach list | Lending conduct |
| FRA-018 | Tiered admin fees by financing bracket | A | Tier table parameter; validator | Lending conduct |
| FRA-019 | Responsible-pricing disclosure forms submitted to FRA on schedule | E/A | Regulatory reporting calendar (frequency, due date, submission evidence); missed → alert | Reg. reporting |
| FRA-020 | Late-payment penalty per rules (rate, cap, method) | A | Penalty calculator per parameters; contract clause check; over-charge detection | Lending conduct |
| FRA-021 | Written disclosure of early-repayment cost difference | W/A | Early repayment flow generates disclosure (original vs new cost) | Lending conduct |
| FRA-022 | Client signed consent before early repayment executed | W | Signed consent upload required before execution | Lending conduct |
| FRA-023 | Early repayment linked to a new, costlier loan | A | Detect prepayment + new loan to same client within N days with higher APR/fees → conduct alert + AML unusual-transaction candidate | Lending conduct + AML |
| FRA-024 | Client awareness of the cost impact | W | Mandatory acknowledgement in the refinance flow | Lending conduct |
| FRA-025 | Instalment transfer fees within rules | A | Fee validator parameter | Lending conduct |
| FRA-026 | Rescheduling fees within rules | A | Fee validator parameter | Lending conduct |

## 4. AML/CFT
| ID | Requirement | Type | System behaviour | Module |
|---|---|---|---|---|
| FRA-027 | MLRO independence (reporting line) | A/E | Org chart check: MLRO must not report to risk/business heads; board-level reporting evidence | AML governance |
| FRA-028 | No conflicting roles for MLRO (e.g. internal control at the parent) | A | Role-conflict matrix on user/positions | AML governance |
| FRA-029 | FRA licence/approval for combined roles | W/E | Combined role requires approval reference | AML governance |
| FRA-030 | AML policy manual updated and board-approved | W | Policy versioning + board approval record; "drafted but not approved" ageing alert | Policies |
| FRA-031 | Off-site and on-site AML monitoring of departments/branches | W/M | AML monitoring programme: annual plan, checklists per branch, findings, follow-up | AML governance |
| FRA-032 | Watchlists include UN Security Council lists | A | Coverage check: required list sources configured & loaded (UN, local terrorist lists, freeze orders…); missing → critical | Screening |
| FRA-033 | Watchlists kept up to date | A | Freshness SLA per source; last-sync age alert | Screening |
| FRA-034 | Effective name matching (tested) | A/M | Screening QA harness: periodic test with seeded test names (incl. Arabic variants, local lists, freeze orders); recall %; failure → finding | Screening |
| FRA-035 | Unusual-transactions register complete | A | Reconcile register vs detected events (e.g. all early repayments meeting criteria must be logged) | AML |
| FRA-036 | Each unusual transaction studied & documented | W | SLA to study; required analysis + decision (STR / no STR) + documents | AML |
| FRA-037 | Red flags from internal audit studied | W | Internal-audit findings tagged as AML indicators auto-create AML cases | Internal audit → AML |
| FRA-038–042 | KYC natural person: gender, nationality(ies), residence, address, ID document type | A | Mandatory-field rules + completeness score per file; incomplete blocks onboarding | KYC |
| FRA-043–045 | KYB: tax card no. & issuer, senior management names, beneficial owners | A | Mandatory KYB fields; UBO structure | KYC/KYB |
| FRA-046 | Beneficial-owner declaration by client | W | Signed declaration (self or named other BO) required | KYC |
| FRA-047 | KYC refresh by risk level | A | Review cycle by risk band; overdue list | KYC |
| FRA-048 | Adequate risk-rating basis (multi-factor) | A | Configurable risk model (customer, geography, product, channel, PEP, behaviour) | Risk rating |
| FRA-049 | Risk rating at onboarding / during relationship, not after exit | A | Rating mandatory before approval; re-rating on triggers | Risk rating |
| FRA-050 | EDD applied to high-risk clients | W | High risk → EDD checklist + senior approval gate | KYC |
| FRA-051 | Off-site secured backup of records | E/A | Backup evidence register; system backup status (last successful off-site backup) | IT/BCP |
| FRA-052 | Employees screened against watchlists | A | Employee screening (onboarding + periodic) | Screening/HR |
| FRA-053 | Board approval of the annual MLRO report | W | Annual report generation + board approval record | AML governance |
| FRA-054 | Internal audit scope covers regulatory findings | M | Coverage matrix: audit plan vs control library; gaps flagged | Internal audit |
| OBS-01 | AML training coverage of all staff | M | Training coverage KPI by department (target parameter, e.g. 100%) | Training |

## 5. Accounting, financial statements, related parties
| ID | Requirement | Type | System behaviour | Module |
|---|---|---|---|---|
| FRA-055 | Proper accounting information system (not spreadsheets) | E | Financial-controls checklist; link to ERP when available | Financial controls |
| FRA-056 | Recent balance confirmations for borrowings/facilities | E/A | Confirmations register (counterparty, balance, confirmation date); stale > N days alert | Financial controls |
| FRA-057–058 | Accrued interest booked on facilities | A/E | Facility register with rate; expected accrual vs booked check | Financial controls |
| FRA-059–060 | Defaults on lender balances / rescheduling | M/W | Facility status, covenants, rescheduling tracker; board escalation | Financial controls |
| FRA-061 | Exiting shareholders' dues classified as liabilities | E | Review checklist item with evidence | Financial controls |
| FRA-062–063 | Capital contributions & related-party balances attributed to the right party with documents | W/E | Related-party register; contribution evidence required; mismatch flag | Financial controls |
| FRA-064–065 | Deferred tax assets supported (recoverability evidence, auditor certificate) | E | Evidence item with due date | Financial controls |
| FRA-066 | Approved ECL study | E/W | ECL study status, approval, refresh frequency | Financial controls |

## 6. IT, cyber, continuity
| ID | Requirement | Type | System behaviour | Module |
|---|---|---|---|---|
| FRA-067 | Backup / DR site for business continuity | E | BCP/DR register, last DR test date | Cyber/BCP |
| FRA-068 | Electronic link of collection system with EMLCU for freeze-order checks | E/A | Integration status; screening of collection counterparties against freeze orders | Screening/Cyber |
| FRA-069 | Recent penetration & malware test by qualified provider | E | Evidence with validity period | Cyber |
| FRA-070 | WAF details & active licences | E | Asset/licence register with expiry | Cyber |
| FRA-071 | EPP & EDR effective; no sensitive data sent abroad | E | Licence + data-residency attestation | Cyber |
| FRA-072 | Valid SSL certificate | A | Automatic certificate expiry check for declared domains | Cyber |
| FRA-073 | Detailed CIS benchmark report | E | Evidence with date | Cyber |
| FRA-074 | Board-approved information-security policies | W | Policies module with board approval | Policies |
| FRA-075–077 | IT governance, IT risk and cybersecurity frameworks aligned to FRA requirements | E/M | Framework mapping & maturity self-assessment | Cyber |
| FRA-078 | Updated IT risk register | A/M | IT risks inside ERM risk register; staleness alert | Risk |

## 7. Remediation
| ID | Requirement | Type | System behaviour | Module |
|---|---|---|---|---|
| FRA-079 | Prior findings remediated and not repeated | W/A | Inspection findings tracker: import findings, corrective-action plans, owners, deadlines, evidence, verification re-test, **recurrence detection** (same control failing again), board reporting | Findings |
