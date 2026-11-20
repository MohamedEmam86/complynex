-- Vessel screening, after the first production load of the OpenSanctions default collection:
--  * provenance of each listed ship record (SANCTION / BAN / RISK / INTEL, screening/vessel_provenance.py),
--    its datasets and its port-state-control datasets: only SANCTION and BAN records alert; RISK / INTEL feed
--    the risk score. Filled by scripts/vessels_sync.py --sync from the rows already loaded (no download).
--  * cx_party_key(text): the comparable form of an organisation name (exact owner lookup), indexed by
--    20261120b_vessel_owner_index.sql (CREATE INDEX CONCURRENTLY, outside a transaction).
--  * vessel_data_version: a stamp bumped by every change of the vessel data or settings, read by the workers
--    to drop their caches (a newly listed IMO hits at once).
-- Idempotent; additive only.
BEGIN;
SET lock_timeout = '5s';

ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS provenance VARCHAR(10) NOT NULL DEFAULT 'SANCTION';
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS datasets TEXT;          -- JSON list (aggregated sources)
ALTER TABLE vessel_profile ADD COLUMN IF NOT EXISTS risk_datasets TEXT;     -- JSON list: port-state-control records
CREATE INDEX IF NOT EXISTS idx_vessel_profile_provenance ON vessel_profile (provenance);
CREATE INDEX IF NOT EXISTS idx_vessel_profile_source ON vessel_profile (source);

CREATE OR REPLACE FUNCTION cx_party_key(t text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT upper(btrim(regexp_replace(regexp_replace(regexp_replace(coalesce(t, ''), '[(][^)]*[)]', ' ', 'g'),
                                                   E'[^A-Za-z0-9؀-ۿ]+', ' ', 'g'), '\s+', ' ', 'g'))) $$;

CREATE TABLE IF NOT EXISTS vessel_data_version (
    id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version     BIGINT NOT NULL DEFAULT 1,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason      TEXT
);
INSERT INTO vessel_data_version (id, version, reason) VALUES (1, 1, 'created') ON CONFLICT (id) DO NOTHING;

GRANT SELECT, INSERT, UPDATE ON vessel_data_version TO complynex;
GRANT EXECUTE ON FUNCTION cx_party_key(text) TO complynex;
COMMIT;
