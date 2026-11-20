-- Exact owner / operator lookup of vessel screening (vessel_engine.exact_owner_records,
-- vessel_store._resolve_parties): an index on the comparable name, so the lookup is not a sequential scan of
-- screening_watchlist. CONCURRENTLY: no lock on the table while it builds; therefore no BEGIN/COMMIT here.
-- Needs cx_party_key() from 20261120_vessel_provenance.sql (applied first: file name order).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_wl_party_key ON screening_watchlist (cx_party_key(full_name));
