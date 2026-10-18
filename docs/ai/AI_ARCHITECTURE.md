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
