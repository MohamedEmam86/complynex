-- G13: relatives and close associates of PEPs (screening/pep_relations.py,
-- scripts/import_pep_relations.py). One row per relation; listed records are never changed.
BEGIN;

CREATE TABLE IF NOT EXISTS screening_pep_relations (
    id                SERIAL PRIMARY KEY,
    relation_key      TEXT NOT NULL UNIQUE,      -- 'os:<OpenSanctions relation id>' or 'manual:...'
    pep_source        TEXT NOT NULL,             -- 'opensanctions' covers both OpenSanctions feeds
    pep_source_id     TEXT NOT NULL,             -- screening_watchlist.source_id of the PEP side
    related_source    TEXT NOT NULL,
    related_source_id TEXT NOT NULL,
    relation_type     TEXT NOT NULL CHECK (relation_type IN ('family', 'associate')),
    relationship      TEXT,                      -- as the source words it (spouse, child, ...)
    origin            TEXT NOT NULL DEFAULT 'opensanctions',
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_by        INTEGER,
    reason            TEXT,
    removed_by        INTEGER,                   -- an MLRO removal is never undone by a re-import
    removed_reason    TEXT,
    last_seen_at      TIMESTAMP,                 -- last import that still carried the relation
    created_at        TIMESTAMP NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_spr_pep ON screening_pep_relations (pep_source, pep_source_id) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_spr_rel ON screening_pep_relations (related_source, related_source_id) WHERE is_active;

GRANT SELECT, INSERT, UPDATE ON screening_pep_relations TO complynex;
GRANT USAGE, SELECT, UPDATE ON SEQUENCE screening_pep_relations_id_seq TO complynex;

COMMIT;
