-- Local negative-lists workbook import (screening/local_lists, scripts/import_local_lists.py).
-- local_list_imports : one row per applied / blocked / failed import (the version record). Sheet names are
--                      internal (superadmin only); counts per sheet, category and change type.
-- local_list_records : stable identity of every record ever imported (hashed key, never an ID in clear), its
--                      status (LISTED / LIFTED / REMOVED), content hash and the internal_blacklist row it owns.
-- local_list_changes : change log per import: ADDED / ADOPTED / CHANGED / LIFTED / RELISTED / REMOVED.
-- Nothing is ever deleted: a lifted or removed record keeps its row (legal_status / is_active). Idempotent.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS local_list_imports (
    id              SERIAL PRIMARY KEY,
    status          TEXT NOT NULL CHECK (status IN ('RUNNING', 'APPLIED', 'BLOCKED', 'FAILED')),
    trigger         TEXT,
    triggered_by    INTEGER,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    file_name       TEXT,
    file_sha256     TEXT,
    content_sha256  TEXT,
    edition_date    DATE,
    allow_shrink    BOOLEAN NOT NULL DEFAULT FALSE,
    sheets          JSONB,
    counts          JSONB,
    totals          JSONB,
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS idx_lli_started ON local_list_imports (started_at DESC);

CREATE TABLE IF NOT EXISTS local_list_records (
    id                 SERIAL PRIMARY KEY,
    record_key         TEXT NOT NULL,
    kind               TEXT NOT NULL,
    category           TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('LISTED', 'LIFTED', 'REMOVED')),
    blacklist_id       INTEGER,
    content_sha256     TEXT,
    content            JSONB,
    provenance         JSONB,
    first_import       INTEGER,
    last_import        INTEGER,
    last_change_import INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT local_list_records_key_unique UNIQUE (record_key)
);
CREATE INDEX IF NOT EXISTS idx_llr_category ON local_list_records (category, status);
CREATE INDEX IF NOT EXISTS idx_llr_blacklist ON local_list_records (blacklist_id);

CREATE TABLE IF NOT EXISTS local_list_changes (
    id            BIGSERIAL PRIMARY KEY,
    import_id     INTEGER NOT NULL REFERENCES local_list_imports(id),
    record_key    TEXT NOT NULL,
    category      TEXT NOT NULL,
    change        TEXT NOT NULL CHECK (change IN ('ADDED', 'ADOPTED', 'CHANGED', 'LIFTED', 'RELISTED', 'REMOVED',
                                                  'RETIRED')),
    blacklist_id  INTEGER,
    old_status    TEXT,
    new_status    TEXT,
    fields        JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_llc_import ON local_list_changes (import_id, change);
CREATE INDEX IF NOT EXISTS idx_llc_record ON local_list_changes (record_key);

GRANT SELECT, INSERT, UPDATE ON local_list_imports, local_list_records, local_list_changes TO complynex;
GRANT USAGE, SELECT ON SEQUENCE local_list_imports_id_seq, local_list_records_id_seq, local_list_changes_id_seq
    TO complynex;
COMMIT;
