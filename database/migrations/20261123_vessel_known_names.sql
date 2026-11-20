-- Vessel screening round 4: names ComplyNex knows for a listed ship before the lists publish them (a ship
-- renamed after its listing), and the name / IMO mismatches seen in screenings, queued for the superadmin.
-- Both are shared reference data (maintained by the platform superadmin, read by every tenant).
BEGIN;

CREATE TABLE IF NOT EXISTS vessel_known_names (
    id              SERIAL PRIMARY KEY,
    group_key       VARCHAR(40) NOT NULL,             -- the ship: IMO:<n> or WL:<watchlist id>
    imo             VARCHAR(10),
    name            TEXT NOT NULL,
    name_norm       TEXT NOT NULL,
    kind            VARCHAR(12) NOT NULL DEFAULT 'new_name' CHECK (kind IN ('new_name', 'alias', 'former_name')),
    source_note     TEXT NOT NULL,                    -- where the name comes from (superadmin only)
    effective_date  DATE,                             -- when the ship took the name, if known
    status          VARCHAR(10) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    observation_id  INTEGER,                          -- confirmed from the review queue
    created_by      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_by      INTEGER,
    revoked_at      TIMESTAMPTZ,
    revoke_reason   TEXT
);
CREATE INDEX IF NOT EXISTS idx_vessel_known_names_group ON vessel_known_names (group_key) WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS uq_vessel_known_names_active
    ON vessel_known_names (group_key, name_norm) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS vessel_name_observations (
    id             SERIAL PRIMARY KEY,
    group_key      VARCHAR(40) NOT NULL,
    imo            VARCHAR(10),
    listed_name    TEXT,
    entered_name   TEXT NOT NULL,
    entered_norm   TEXT NOT NULL,
    identifier     VARCHAR(10) NOT NULL DEFAULT 'IMO',  -- what confirmed the ship: IMO / MMSI / CALLSIGN
    seen_count     INTEGER NOT NULL DEFAULT 1,
    first_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_screening_id INTEGER,
    status         VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'dismissed')),
    decided_by     INTEGER,
    decided_at     TIMESTAMPTZ,
    note           TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vessel_name_observations ON vessel_name_observations (group_key, entered_norm);
CREATE INDEX IF NOT EXISTS idx_vessel_name_observations_status ON vessel_name_observations (status, last_seen DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON vessel_known_names, vessel_name_observations TO complynex;
GRANT USAGE, SELECT ON SEQUENCE vessel_known_names_id_seq, vessel_name_observations_id_seq TO complynex;
COMMIT;
