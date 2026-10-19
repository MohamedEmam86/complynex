# Compliance Copilot — AI architecture (phase 1)

> **Local only.** ComplyNex never calls an external AI service (no OpenAI, Anthropic, Google,
> Azure or any hosted model / embedding API), and there is no option to enable one. All
> inference runs on the customer's own server or private network. Without a model, every
> feature still works on deterministic rules (`rules_only`, the default).

## 1. Principle: the AI selects, fills and explains — data defines the flow

| Who decides | What |
|---|---|
| **Data** (catalogs, editable in the UI) | intake intents and their fields and routing target, playbooks and their steps, controls, requirements, owner roles, deadlines |
| **Deterministic code** | gaps on a record (missing evidence, overdue actions, approvals, SLA), record creation through module APIs, permissions |
| **AI (optional local model)** | which catalog entry fits a free text, field values found in the text, wording of steps and drafts |
| **The user** | every record is created only after the user confirms; drafts are labelled "AI draft — review required" |

The model can only choose codes that exist in the catalog (JSON enum). It cannot add steps, change
dates, create a flow or take a decision.

## 2. Components (`ai/`)

| Module | Role |
|---|---|
| `providers.py` | Provider interface. Exactly three providers: `rules_only` (default), `local_http` (Ollama or llama.cpp server API), `local_embeddings` (the semantic screening service's model, or a model folder on disk). |
| `netguard.py` | Refuses any URL that does not resolve to localhost, a private range (10/8, 172.16/12, 192.168/16), link-local or 100.64/10. Checked when settings are saved **and before every call** (DNS can change). |
| `schema.py` | Strict JSON: extract one object from the reply, validate it against a schema. |
| `tasks.py` | Classification, extraction, playbook selection, next-best-action phrasing, drafts. Each task: rules result first → optional model call → schema check → one repair retry → fallback to rules. |
| `text.py` | Arabic/English normalisation, keywords, character n-grams, dates (incl. Arabic months and digits), amounts, identifiers. |
| `catalog.py`, `seed.py` | Intents and playbooks as data; 10 generic intents and 5 generic playbooks seeded once. |
| `handlers.py` | Code adapters to existing module APIs (finding, evidence, AML candidate, complaint, whistleblowing case, playbook, link, guidance, manual). Intents point to a handler by code. |
| `playbooks.py` | Instantiates a playbook: one finding + one dated corrective action per step, linked to the step controls, through the regcontrols API. |
| `nba.py` | Deterministic gaps for findings, controls, cases and AML unusual-activity items. |
| `intake.py` | Submission → proposal → confirm / reject. |
| `audit.py` | Suggestion log and retention purge. |
| `service.py` | Jobs (RQ or inline), health, feature dispatch. |
| `extract.py` | Text from uploads: txt/eml/html/docx, PDF text layer (pypdf), scanned PDFs and images with the **local** Tesseract binary. Records the method (`text` / `pypdf` / `ocr` / `none`) and a note on the intake item. |
| `freeze_screening.py` | Freeze orders: on confirmation, every name and ID number of the order is screened (DB only, synchronously) against customers, merchants (and their UBOs), beneficial owners, other KYC subjects and the last N days of transaction counterparties. Decisions per match: freeze / false positive. |
| `library.py` | Regulatory-library index (policies, framework requirements, submitted circulars → paragraphs, optional local embeddings) and citation-only answers to policy questions. |
| `mailbox.py` | Optional monitored mailbox (IMAP over TLS) → intake items. |

Content packs add intents, keywords, playbooks and steps as data through `regcontrols.api`
(`install_ai_intent`, `extend_ai_intent`, `install_ai_playbook`, `install_ai_playbook_step`). The core never imports a pack.

## 3. Data flow

```
user ─ text / file ─► ai_intake_items ─► job (RQ queue "events", or inline)
                                         │ rules: keywords + n-grams (+ embeddings)
                                         │ model (optional, local): JSON with enum of catalog codes
                                         ▼
                              proposal (intent, fields, target, controls, owner role, priority, deadline)
                                         │ user reviews / edits
                                         ▼ confirm
                handler → existing module API (regcontrols, aml.unusual, complaints, whistleblowing …)
                                         ▼
                ai_suggestions: input hash, provider, model, prompt version, output, latency, decision
```

Long calls run as RQ jobs on the existing `events` queue (`ai.service.job_entry`); the page polls
`/ai/api/jobs/<id>`. Without Redis or a worker, jobs run inline. With `rules_only` everything runs inline (milliseconds).

## 4. Privacy guarantees

- No outbound call except to the configured local / private host; public hosts are refused at save and at call time.
  The only other connection is the optional monitored mailbox (§10), which only reads the configured IMAP
  mailbox over TLS — no AI, OCR or cloud service is ever called.
- No model weights are downloaded by the code; the embeddings folder must already exist locally (`HF_HUB_OFFLINE`).
- Prompts and outputs stay in the ComplyNex database (`ai_suggestions`). Only a SHA-256 of the input is kept
  after the retention period (AI settings → *Prompt log retention*, default 90 days); the body of decided
  intake items is removed too. The purge runs daily (`scripts/ai_retention.py` from `scripts/daily_tasks.sh`)
  and on demand (AI log → *Apply retention now*).
- Model output is always shown as text (never as HTML) and every page keeps the CSP nonce rules.
- Permission `perm_ai`: `none` / `view` (see pages and log) / `use` (submit, confirm, drafts) / `admin` (settings, catalogs, prompt details).

## 5. Installing a local model (optional)

**Ollama** (simplest), on the ComplyNex server or a private-network host:

```bash
curl -fsSL https://ollama.com/install.sh | sh          # or the offline package from your IT team
ollama pull qwen2.5:7b-instruct                        # any instruct model with good Arabic; 7–8B runs on CPU
# Ollama listens on 127.0.0.1:11434 by default — keep it bound to localhost / the private network
```

**llama.cpp server**: `llama-server -m /opt/models/<model>.gguf --host 127.0.0.1 --port 8080` and choose API style
*llama.cpp server (/v1 compatible)* with URL `http://127.0.0.1:8080`.

Then: **Compliance Copilot → AI settings & health** → provider *Local inference server*, URL, model name, timeout → Save.
The health panel shows whether the server answers and the model is present. Run the evaluation to compare with rules:

```bash
python scripts/ai_eval.py --url http://127.0.0.1:11434 --model qwen2.5:7b-instruct
```

A 7B model on CPU needs ~8 GB RAM and answers in 5–60 s, so keep *Run model calls as background jobs* on and
make sure the RQ worker (`events/worker.py`) is running.

**Embeddings** (optional, improves rules matching): choose *Reuse the semantic screening service*; it calls
`POST /embed` on the existing service (`127.0.0.1:8100`), so no second model is loaded. Or point *Local model folder* at a
sentence-transformers model already copied to the server.

## 6. Evaluation

`tests/ai_eval/dataset.json` holds 70 synthetic intake texts and 20 playbook situations (Arabic and English,
fictional names). `scripts/ai_eval.py` reports accuracy per provider; unit tests (`tests/test_ai/`) use a fake
provider for the JSON / repair / fallback paths.

`tests/test_ai/test_ai_ocr_screening.py` covers extraction with generated PDFs and a fake Tesseract / pdftoppm,
name and ID matching on fixture records, citation-only answers and the IMAP import with a fake server (no database).
`tests/test_ai/test_ai_copilot_db.py` runs the same flows end to end on a test database (skipped when none is configured).

## 7. Scanned documents: local OCR (optional)

Text PDFs are read with **pypdf** (in `requirements.txt`). Scanned PDFs and images (png, jpg) are read with
the **Tesseract** binary on the ComplyNex server — never an online OCR service. Install it with the Arabic
language data and the PDF renderer:

```bash
sudo apt install tesseract-ocr tesseract-ocr-ara poppler-utils
tesseract --list-langs        # must list "ara" and "eng"
```

The code never downloads language data. It uses `ara+eng` when both are installed; without `ara` it still
runs in English and says so on the item. Without `pdftoppm` (poppler-utils) a scanned PDF cannot be rendered
and the item records "OCR not possible". The method that produced the text (`text`, `pypdf`, `ocr`, `none`)
and any note are stored on the intake item and shown on the review page; OCR text must be checked against
the original (names and numbers). AI settings → Health shows whether OCR is available.

## 8. Freeze orders: screening on confirmation

An intent whose routing parameters contain `"screen_subjects": true` (the generic `freeze_order` intent
does) is screened **synchronously** right after the user confirms it — freeze turnaround is time-critical and
the screening uses the database only (no Elasticsearch, no semantic service):

- **Subjects**: the confirmed "Persons / entities named" and "Identification numbers" fields, plus any
  14-digit national ID found in the text.
- **Sources** (missing tables or columns are skipped and listed on the page): `customers` (names in Arabic
  and English, `id_number`, `registration_number`, and `national_id_hash` through the same
  `EncryptionService.hash_value`), `merchants` (name, trade name, CR / tax number) and their UBO
  (`ubo_name`, `ubo_id_number`), `beneficial_owners`, `kyc_beneficial_owners`, any other KYC subject a module
  or pack registers in `amlkyc.subjects`, and the counterparties of `transactions` of the last N days
  (AI settings, default 90).
- **Matching**: exact ID number (Arabic digits normalised), and names with the screening module's scorer
  (`screening/name_normalizer.score_match`: Arabic ↔ English transliteration, phonetic normalisation,
  bidirectional Jaro-Winkler, common-name guard) after a rapidfuzz pre-filter. Minimum name score: AI
  settings (default 0.80, as the screening search).
- **Decisions** (perm_ai `use` + AML edit rights): *Freeze* records the decision, registers an AML candidate
  per match (`aml_unusual_transactions`, rule `freeze_order_match`), appends it to the order's own candidate
  and writes the audit log; *False positive* requires a reason. Core customer state is **not** changed (no
  freeze API exists in the core): the freeze itself is applied in the core banking / payment system.
- **Timer**: the review page shows the time since receipt — the earlier of the submission time and the date
  of the e-mail or of the order ("dated …", within 30 days) — live, from the server's elapsed time.

## 9. Regulatory library index and policy questions

`ai_library_paragraphs` holds the paragraphs of active policies (description, content and the attached
document), of every active framework's requirements (English and Arabic text, legal reference) and of
circulars submitted with the channel *Regulatory circular*. With embeddings configured, each paragraph also
gets a vector from the **local** embeddings provider. Rebuild: AI settings → *Rebuild the library index*
(RQ job, inline without a worker), daily via `scripts/ai_library_index.py` in `scripts/daily_tasks.sh`.

A *policy question* is answered **only** with cited paragraphs (embedding cosine when available, otherwise
character n-grams + IDF-weighted word coverage), each with a link to its source page. When no paragraph
passes the threshold (AI settings: rules 0.30, embeddings 0.55), the answer is "No source found" and the
question goes to the compliance team. A local model, if configured, may only summarise the cited paragraphs
and must cite at least one of them (enum-validated JSON); otherwise only the paragraphs are shown.
Rules retrieval works within one language (an Arabic question finds Arabic text); cross-language retrieval
needs embeddings.

## 10. Monitored mailbox (optional, off by default)

AI settings → *Monitored mailbox*: IMAP host, port, user, password, folder, messages per run, channel.
IMAP is not an AI service, so the mail host may be outside the private network, but it is read **only over
TLS** (implicit SSL on 993 or STARTTLS on 143, certificate verified). The content is only read from that
mailbox and stays in ComplyNex. The password is stored encrypted (`EncryptionService`, Fernet; key from
`ENCRYPTION_KEY` or `SECRET_KEY`) or given as an environment reference `env:COMPLYNEX_IMAP_PASSWORD`; it is
never shown again.

Schedule the import (each unseen message → one intake item with its attachments, stored like intake uploads;
marked seen only after the item exists; a Message-ID already imported is skipped):

```bash
*/5 * * * * cd /opt/complynex && venv/bin/python scripts/ai_mail_import.py
```

Imported items have no submitter: users with perm_ai `use` see them in the intake queue. The dashboard has a
*Submit to Compliance* button for users with perm_ai `use` or `admin`.
