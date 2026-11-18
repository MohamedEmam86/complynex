-- Dual-use goods screening (optional pack 'trade_control', permission module 'dualuse').
-- Control lists are loaded by scripts/dualuse/import_lists.py (versioned; a past screening
-- keeps the list versions it used). Clients see the lists only as "International control lists"
-- (قوائم الرقابة الدولية); the real list name (dualuse_lists.legal_name) is shown to site administrators only.
-- Idempotent: safe to run more than once.
BEGIN;

CREATE TABLE IF NOT EXISTS dualuse_lists (
    id              SERIAL PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,            -- internal id, e.g. 'list_a'
    legal_name      TEXT NOT NULL,                   -- internal only
    kind            TEXT NOT NULL DEFAULT 'control', -- control | hs_map | priority | chemicals
    display_order   INTEGER NOT NULL DEFAULT 100,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dualuse_list_versions (
    id              SERIAL PRIMARY KEY,
    list_id         INTEGER NOT NULL REFERENCES dualuse_lists(id),
    version_label   TEXT,
    in_force_date   DATE,
    source_url      TEXT,
    raw_sha256      TEXT,
    record_count    INTEGER NOT NULL DEFAULT 0,
    stats           JSONB NOT NULL DEFAULT '{}'::jsonb,
    diff            JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_current      BOOLEAN NOT NULL DEFAULT FALSE,
    loaded_by       TEXT,
    loaded_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_du_versions_list ON dualuse_list_versions(list_id, is_current);

CREATE TABLE IF NOT EXISTS dualuse_items (
    id              SERIAL PRIMARY KEY,
    version_id      INTEGER NOT NULL REFERENCES dualuse_list_versions(id) ON DELETE CASCADE,
    code            TEXT NOT NULL,
    parent_code     TEXT,
    entry_code      TEXT,
    level           SMALLINT NOT NULL DEFAULT 0,
    category        TEXT,
    grp             TEXT,
    title_en        TEXT,
    text_en         TEXT,
    notes_en        JSONB NOT NULL DEFAULT '[]'::jsonb,
    reasons         TEXT[] NOT NULL DEFAULT '{}',
    not_used        BOOLEAN NOT NULL DEFAULT FALSE,
    risk_level      TEXT NOT NULL DEFAULT 'medium',  -- high | medium | low
    title_ar        TEXT,
    text_ar         TEXT,
    ar_status       TEXT NOT NULL DEFAULT 'none',    -- none | draft | verified | reviewed | stale
    ar_updated_at   TIMESTAMPTZ,
    extra           JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (version_id, code)
);
CREATE INDEX IF NOT EXISTS idx_du_items_code ON dualuse_items(code);

CREATE TABLE IF NOT EXISTS dualuse_parameters (
    id              SERIAL PRIMARY KEY,
    item_id         INTEGER NOT NULL REFERENCES dualuse_items(id) ON DELETE CASCADE,
    parameter       TEXT,
    parameter_ar    TEXT,
    operator        TEXT NOT NULL,
    value           DOUBLE PRECISION,
    unit            TEXT,
    base_value      DOUBLE PRECISION,
    base_unit       TEXT,
    raw             TEXT,
    method          TEXT NOT NULL DEFAULT 'auto',    -- auto | analyst
    reviewed        BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_du_params_item ON dualuse_parameters(item_id);

CREATE TABLE IF NOT EXISTS dualuse_hs_map (
    id              SERIAL PRIMARY KEY,
    version_id      INTEGER NOT NULL REFERENCES dualuse_list_versions(id) ON DELETE CASCADE,
    cn10            TEXT,
    hs6             TEXT NOT NULL,
    hs4             TEXT,
    chapter         TEXT,
    control_code    TEXT,
    resolved_code   TEXT,
    taric_footnote  TEXT,
    priority_tier   TEXT,
    description_en  TEXT,
    description_ar  TEXT
);
CREATE INDEX IF NOT EXISTS idx_du_hs_hs6 ON dualuse_hs_map(hs6);

CREATE TABLE IF NOT EXISTS dualuse_chemicals (
    id              SERIAL PRIMARY KEY,
    version_id      INTEGER NOT NULL REFERENCES dualuse_list_versions(id) ON DELETE CASCADE,
    cas             TEXT NOT NULL,
    names_en        TEXT[] NOT NULL DEFAULT '{}',
    names_ar        TEXT[] NOT NULL DEFAULT '{}',
    cwc_schedule    SMALLINT,
    ag_precursor    BOOLEAN NOT NULL DEFAULT FALSE,
    listings        JSONB NOT NULL DEFAULT '[]'::jsonb,
    ar_status       TEXT NOT NULL DEFAULT 'none',
    UNIQUE (version_id, cas)
);

CREATE TABLE IF NOT EXISTS dualuse_terms (
    id              SERIAL PRIMARY KEY,
    term_en         TEXT NOT NULL,
    term_ar         TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'seed',    -- seed | analyst | translation
    created_by      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (term_en, term_ar)
);

CREATE TABLE IF NOT EXISTS dualuse_item_master (
    id              SERIAL PRIMARY KEY,
    item_key        TEXT NOT NULL UNIQUE,
    description     TEXT,
    hs_code         TEXT,
    cas             TEXT,
    model           TEXT,
    decision        TEXT NOT NULL,                    -- clear | hold
    reason          TEXT,
    comment         TEXT,
    list_versions   JSONB NOT NULL DEFAULT '{}'::jsonb,
    decided_by      INTEGER,
    decided_at      TIMESTAMPTZ DEFAULT now(),
    screening_line_id INTEGER
);

CREATE TABLE IF NOT EXISTS dualuse_screenings (
    id              SERIAL PRIMARY KEY,
    ref             TEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL DEFAULT 'single',   -- single | batch
    title           TEXT,
    file_name       TEXT,
    supplier        TEXT,
    consignee       TEXT,
    end_user        TEXT,
    origin          TEXT,
    party_results   JSONB NOT NULL DEFAULT '[]'::jsonb,
    list_versions   JSONB NOT NULL DEFAULT '{}'::jsonb,
    line_count      INTEGER NOT NULL DEFAULT 0,
    counts          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'open',     -- open | decided
    created_by      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_du_screenings_created ON dualuse_screenings(created_at DESC);

CREATE TABLE IF NOT EXISTS dualuse_screening_lines (
    id              SERIAL PRIMARY KEY,
    screening_id    INTEGER NOT NULL REFERENCES dualuse_screenings(id) ON DELETE CASCADE,
    line_no         INTEGER NOT NULL DEFAULT 1,
    description     TEXT,
    hs_code         TEXT,
    cas             TEXT,
    model           TEXT,
    origin          TEXT,
    quantity        TEXT,
    item_key        TEXT,
    candidates      JSONB NOT NULL DEFAULT '[]'::jsonb,
    hard_flags      JSONB NOT NULL DEFAULT '[]'::jsonb,
    questions       JSONB NOT NULL DEFAULT '[]'::jsonb,
    answers         JSONB NOT NULL DEFAULT '{}'::jsonb,
    suggested       TEXT NOT NULL DEFAULT 'review',   -- clear | review | hold
    reused_from     INTEGER,                          -- dualuse_item_master.id
    decision        TEXT,                             -- clear | hold (by the user)
    reason          TEXT,
    comment         TEXT,
    decided_by      INTEGER,
    decided_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_du_lines_screening ON dualuse_screening_lines(screening_id, line_no);

-- Transport document (bill of lading / airway bill) and the vessel screened through the vessel engine.
ALTER TABLE dualuse_screenings ADD COLUMN IF NOT EXISTS transport_doc TEXT;
ALTER TABLE dualuse_screenings ADD COLUMN IF NOT EXISTS vessel_name TEXT;
ALTER TABLE dualuse_screenings ADD COLUMN IF NOT EXISTS vessel_imo TEXT;
ALTER TABLE dualuse_screenings ADD COLUMN IF NOT EXISTS vessel_result JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Every decision ever recorded on a line (the line keeps only the latest): the audit trail of the module.
CREATE TABLE IF NOT EXISTS dualuse_decisions (
    id              SERIAL PRIMARY KEY,
    line_id         INTEGER NOT NULL REFERENCES dualuse_screening_lines(id) ON DELETE CASCADE,
    screening_id    INTEGER NOT NULL REFERENCES dualuse_screenings(id) ON DELETE CASCADE,
    decision        TEXT NOT NULL,                    -- clear | hold
    reason          TEXT NOT NULL,
    comment         TEXT NOT NULL,
    suggested       TEXT,                             -- the system suggestion at the time
    answers         JSONB NOT NULL DEFAULT '{}'::jsonb,
    list_versions   JSONB NOT NULL DEFAULT '{}'::jsonb,
    reused          BOOLEAN NOT NULL DEFAULT FALSE,   -- applied from an identical product decided earlier
    decided_by      INTEGER,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_du_decisions_line ON dualuse_decisions(line_id, decided_at);
CREATE INDEX IF NOT EXISTS idx_du_decisions_screening ON dualuse_decisions(screening_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON dualuse_lists, dualuse_list_versions, dualuse_items, dualuse_parameters,
    dualuse_hs_map, dualuse_chemicals, dualuse_terms, dualuse_item_master, dualuse_screenings,
    dualuse_screening_lines, dualuse_decisions TO complynex;
GRANT USAGE, SELECT ON SEQUENCE dualuse_lists_id_seq, dualuse_list_versions_id_seq, dualuse_items_id_seq,
    dualuse_parameters_id_seq, dualuse_hs_map_id_seq, dualuse_chemicals_id_seq, dualuse_terms_id_seq,
    dualuse_item_master_id_seq, dualuse_screenings_id_seq, dualuse_screening_lines_id_seq,
    dualuse_decisions_id_seq TO complynex;
COMMIT;
