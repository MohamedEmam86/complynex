-- Dual-use goods (optional pack 'trade_control'), round 3:
--   * dualuse_update_runs: every list check (scheduled timer, "check now" button, upload, command line)
--     with its outcome per list (loaded / unchanged / blocked / refused) - shown to the superadmin.
--   * dualuse_guidance: the practical guidance shown next to a result (why it is controlled, what to ask the
--     customer, documents, competent authority, red flags, sources, confidence) as DATA, bilingual and
--     versioned: an edit by the superadmin adds a version and keeps the previous ones.
--   * dualuse_screening_lines.guidance: the user's checklist / notes against that guidance (decision memo).
--   * the pack is switched on by default where nobody decided otherwise (users still need the 'dualuse'
--     module permission; superadmin and it_admin always have it).
-- Shared reference tables (no tenant_id): dualuse_update_runs, dualuse_guidance.
-- Idempotent: safe to run more than once.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS dualuse_update_runs (
    id            SERIAL PRIMARY KEY,
    mode          TEXT NOT NULL DEFAULT 'command',      -- scheduled | manual | upload | command
    triggered_by  TEXT,
    status        TEXT NOT NULL DEFAULT 'running',      -- running | ok | blocked | failed
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    summary       JSONB NOT NULL DEFAULT '[]',          -- one result per list
    log           TEXT
);
CREATE INDEX IF NOT EXISTS idx_du_update_runs_started ON dualuse_update_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS dualuse_guidance (
    id            SERIAL PRIMARY KEY,
    category      TEXT NOT NULL,                        -- e.g. 'telecom_encryption'
    version       INTEGER NOT NULL DEFAULT 1,
    is_current    BOOLEAN NOT NULL DEFAULT TRUE,
    label_en      TEXT NOT NULL,
    label_ar      TEXT,
    keys          TEXT[] NOT NULL DEFAULT '{}',         -- control-code prefixes, HS<digits>, CHPL-T<n>, CWC-S<n> ...
    content       JSONB NOT NULL DEFAULT '{}',          -- {"en": {...}, "ar": {...}}
    sources       JSONB NOT NULL DEFAULT '[]',
    confidence    TEXT,
    origin        TEXT NOT NULL DEFAULT 'seed',         -- seed | edited
    seed_sha      TEXT,
    note          TEXT,
    edited_by     INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (category, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_du_guidance_current ON dualuse_guidance(category) WHERE is_current;

ALTER TABLE dualuse_screening_lines ADD COLUMN IF NOT EXISTS guidance JSONB NOT NULL DEFAULT '{}';

DO $$
BEGIN
    IF to_regclass('public.rc_packs') IS NOT NULL THEN
        INSERT INTO rc_packs (code, enabled, installed_version, installed_at, updated_at)
        VALUES ('trade_control', TRUE, '1', now(), now())
        ON CONFLICT (code) DO NOTHING;               -- never re-enable a pack someone switched off
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON dualuse_update_runs, dualuse_guidance TO complynex;
GRANT USAGE, SELECT ON SEQUENCE dualuse_update_runs_id_seq, dualuse_guidance_id_seq TO complynex;
COMMIT;
