-- =============================================================================
-- Compliance Copilot (AI layer, phase 1) — local-only
--
-- Catalogs (DATA, editable in the UI): intake intents and playbooks with steps.
-- Work items: intake submissions, playbook runs, async jobs.
-- Governance: every AI suggestion with provider, model, prompt version,
-- latency and the user's decision; prompt text is purged after the
-- retention period (Settings ai.log_retention_days).
--
-- Idempotent. DDL runs as postgres; GRANTs at the end.
-- =============================================================================
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS perm_ai VARCHAR(10) DEFAULT 'none';   -- none | view | use | admin

CREATE TABLE IF NOT EXISTS ai_intents (
    code            VARCHAR(60) PRIMARY KEY,
    name_en         VARCHAR(200) NOT NULL,
    name_ar         VARCHAR(200),
    description     TEXT,
    keywords        TEXT[] NOT NULL DEFAULT '{}',      -- English and Arabic keywords / phrases
    examples        TEXT[] NOT NULL DEFAULT '{}',      -- short example texts (few-shot + similarity)
    fields          JSONB NOT NULL DEFAULT '[]'::jsonb, -- [{key, label_en, label_ar, type, required}]
    handler         VARCHAR(60) NOT NULL DEFAULT 'manual',   -- routing target (see ai/handlers.py)
    handler_params  JSONB NOT NULL DEFAULT '{}'::jsonb,
    control_codes   TEXT[] NOT NULL DEFAULT '{}',
    owner_role      VARCHAR(40),
    priority        VARCHAR(10) NOT NULL DEFAULT 'medium' CHECK (priority IN ('critical', 'high', 'medium', 'low')),
    deadline_hours  INTEGER,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    pack_code       VARCHAR(40),
    updated_by      INTEGER REFERENCES users(id),
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_playbooks (
    code         VARCHAR(60) PRIMARY KEY,
    name_en      VARCHAR(200) NOT NULL,
    name_ar      VARCHAR(200),
    description  TEXT,
    keywords     TEXT[] NOT NULL DEFAULT '{}',
    examples     TEXT[] NOT NULL DEFAULT '{}',
    parameters   JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{key, label_en, label_ar, type, required}]
    severity     VARCHAR(10) NOT NULL DEFAULT 'medium',
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    pack_code    VARCHAR(40),
    updated_by   INTEGER REFERENCES users(id),
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_playbook_steps (
    id             SERIAL PRIMARY KEY,
    playbook_code  VARCHAR(60) NOT NULL REFERENCES ai_playbooks(code) ON UPDATE CASCADE ON DELETE CASCADE,
    step_key       VARCHAR(60) NOT NULL,
    seq            INTEGER NOT NULL DEFAULT 100,
    step_type      VARCHAR(12) NOT NULL DEFAULT 'task' CHECK (step_type IN ('task', 'evidence', 'approval', 'control')),
    title_en       VARCHAR(300) NOT NULL,
    title_ar       VARCHAR(300),
    control_code   VARCHAR(30),                         -- optional: link the step's control (from any framework)
    owner_role     VARCHAR(40),
    due_days       INTEGER NOT NULL DEFAULT 14,         -- relative to the playbook start date
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    pack_code      VARCHAR(40),
    UNIQUE (playbook_code, step_key)
);

CREATE TABLE IF NOT EXISTS ai_playbook_runs (
    id            SERIAL PRIMARY KEY,
    playbook_code VARCHAR(60) NOT NULL,
    title         VARCHAR(300) NOT NULL,
    params        JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    finding_id    INTEGER REFERENCES rc_findings(id) ON DELETE SET NULL,
    suggestion_id INTEGER,
    created_by    INTEGER REFERENCES users(id),
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One "Submit to Compliance" item (text / document / forwarded alert or e-mail / circular).
-- File: generic_attachments module 'ai', record_type 'ai_intake'.
CREATE TABLE IF NOT EXISTS ai_intake_items (
    id             SERIAL PRIMARY KEY,
    channel        VARCHAR(20) NOT NULL DEFAULT 'text' CHECK (channel IN ('text', 'document', 'email', 'alert', 'circular')),
    subject        VARCHAR(300),
    body           TEXT,
    status         VARCHAR(12) NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'proposed', 'confirmed', 'rejected', 'failed')),
    proposal       JSONB,                 -- what the AI / rules proposed
    final          JSONB,                 -- what the user confirmed (after edits)
    created_refs   JSONB NOT NULL DEFAULT '[]'::jsonb,   -- records created on confirmation
    suggestion_id  INTEGER,
    created_by     INTEGER REFERENCES users(id),
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_by     INTEGER REFERENCES users(id),
    decided_at     TIMESTAMP
);

-- Governance log of every AI suggestion.
CREATE TABLE IF NOT EXISTS ai_suggestions (
    id              SERIAL PRIMARY KEY,
    feature         VARCHAR(30) NOT NULL,     -- intake, playbook, nba, draft
    object_type     VARCHAR(40),
    object_id       INTEGER,
    input_hash      CHAR(64) NOT NULL,
    provider        VARCHAR(30) NOT NULL,
    model           VARCHAR(120),
    prompt_version  VARCHAR(30) NOT NULL,
    prompt_text     TEXT,                     -- purged after the retention period
    output          JSONB,
    status          VARCHAR(12) NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'repaired', 'fallback', 'error')),
    error           TEXT,
    latency_ms      INTEGER,
    decision        VARCHAR(10) CHECK (decision IN ('accept', 'edit', 'reject')),
    decided_by      INTEGER REFERENCES users(id),
    decided_at      TIMESTAMP,
    user_id         INTEGER REFERENCES users(id),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    purged_at       TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_suggestions_created ON ai_suggestions(created_at);
CREATE INDEX IF NOT EXISTS idx_ai_suggestions_object ON ai_suggestions(object_type, object_id);

-- Async work (CPU-only servers are slow): the page polls this row.
CREATE TABLE IF NOT EXISTS ai_jobs (
    id            VARCHAR(36) PRIMARY KEY,
    feature       VARCHAR(30) NOT NULL,
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        VARCHAR(10) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    result        JSONB,
    error         TEXT,
    suggestion_id INTEGER,
    created_by    INTEGER REFERENCES users(id),
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at   TIMESTAMP
);

GRANT SELECT, INSERT, UPDATE, DELETE ON
    ai_intents, ai_playbooks, ai_playbook_steps, ai_playbook_runs, ai_intake_items, ai_suggestions, ai_jobs
    TO complynex;
GRANT USAGE, SELECT ON ai_playbook_steps_id_seq, ai_playbook_runs_id_seq, ai_intake_items_id_seq, ai_suggestions_id_seq
    TO complynex;

COMMIT;
