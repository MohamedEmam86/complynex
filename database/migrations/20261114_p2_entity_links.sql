-- P2-6 / G5: the same person or entity on several lists, linked without merging rows.
-- Rows in screening_watchlist are never changed or merged: a cluster only groups
-- their ids. Built by scripts/build_entity_links.py (full rebuild, idempotent);
-- an MLRO "unlink" is kept in screening_entity_unlinks and respected by every rebuild.

CREATE TABLE IF NOT EXISTS screening_entity_clusters (
    id               SERIAL PRIMARY KEY,
    lead_watchlist_id INTEGER NOT NULL,          -- the official record that leads (EMLCU / PMA / internal / UN / OFAC / UK / EU before OpenSanctions)
    member_count     INTEGER NOT NULL,
    bases            TEXT,                       -- e.g. 'os_id,official_id'
    has_conflict     BOOLEAN NOT NULL DEFAULT FALSE,  -- members disagree on DOB / nationality / ID
    built_at         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS screening_entity_links (
    watchlist_id  INTEGER PRIMARY KEY,           -- one cluster per record
    cluster_id    INTEGER NOT NULL,
    source        TEXT,
    source_id     TEXT,
    basis         TEXT NOT NULL,                 -- os_id | os_referent | linked_internal | official_id | passport | name_dob_nationality | lead
    confidence    REAL NOT NULL DEFAULT 1.0,
    linked_to     INTEGER,                       -- the member it was linked through
    built_at      TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sel_cluster ON screening_entity_links (cluster_id);
CREATE INDEX IF NOT EXISTS idx_sel_source_sid ON screening_entity_links (source, source_id);

CREATE TABLE IF NOT EXISTS screening_entity_unlinks (
    id            SERIAL PRIMARY KEY,
    watchlist_id  INTEGER NOT NULL,              -- the record taken out of its group
    other_ids     TEXT NOT NULL,                 -- JSON list: it must never be linked to these again
    reason        TEXT NOT NULL,
    unlinked_by   INTEGER,
    unlinked_at   TIMESTAMP NOT NULL DEFAULT now(),
    revoked_at    TIMESTAMP,
    revoked_by    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_seu_wid ON screening_entity_unlinks (watchlist_id);

CREATE TABLE IF NOT EXISTS screening_entity_link_runs (
    id          SERIAL PRIMARY KEY,
    started_at  TIMESTAMP NOT NULL DEFAULT now(),
    finished_at TIMESTAMP,
    status      TEXT,
    clusters    INTEGER,
    links       INTEGER,
    stats       TEXT                             -- JSON counts by basis / source pair
);

GRANT SELECT, INSERT, UPDATE, DELETE ON screening_entity_clusters, screening_entity_links,
      screening_entity_unlinks, screening_entity_link_runs TO complynex;
GRANT USAGE, SELECT ON SEQUENCE screening_entity_clusters_id_seq, screening_entity_unlinks_id_seq,
      screening_entity_link_runs_id_seq TO complynex;
