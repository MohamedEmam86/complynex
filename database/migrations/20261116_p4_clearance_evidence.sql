-- P4-5 / P4-6 / P4-7 (Phase 4): clearance tied to the listed record and its content,
-- false-positive reason codes + SLA, evidence packs.

-- P4-5: a cleared hit is remembered per listed record (kind + id) with an order-insensitive
-- fingerprint of its identifying content. A change, a delisting / re-listing, or a new record
-- brings the hit back.
ALTER TABLE screening_whitelist_matches ADD COLUMN IF NOT EXISTS entity_kind TEXT NOT NULL DEFAULT 'watchlist';
ALTER TABLE screening_whitelist_matches ADD COLUMN IF NOT EXISTS cleared_by INTEGER;
ALTER TABLE screening_whitelist_matches ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMP;
ALTER TABLE screening_whitelist_matches ADD COLUMN IF NOT EXISTS deactivated_reason TEXT;
ALTER TABLE screening_whitelist_matches DROP CONSTRAINT IF EXISTS screening_whitelist_matches_whitelist_id_entity_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_wlm_wl_kind_entity
    ON screening_whitelist_matches (whitelist_id, entity_kind, entity_id);
CREATE INDEX IF NOT EXISTS idx_wlm_kind_entity ON screening_whitelist_matches (entity_kind, entity_id) WHERE is_active;

INSERT INTO screening_config (config_key, config_value, category, description, updated_at)
SELECT 'whitelist_legacy_mode', 'review', 'clearance',
       'Whitelist entries without a cleared-record baseline (name only): review = hits are shown with a note to re-confirm; suppress = old behaviour (the name is not screened)',
       CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM screening_config WHERE config_key = 'whitelist_legacy_mode');

-- P4-6: structured false-positive reasons and an SLA for pending decisions
ALTER TABLE screening_clearance_requests ADD COLUMN IF NOT EXISTS reason_codes TEXT;
ALTER TABLE screening_hit_decisions ADD COLUMN IF NOT EXISTS reason_codes TEXT;
INSERT INTO screening_config (config_key, config_value, category, description, updated_at)
SELECT 'clearance_sla_hours', '24', 'clearance',
       'Hours within which the MLRO should decide a pending clearance before it is shown overdue',
       CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM screening_config WHERE config_key = 'clearance_sla_hours');

-- P4-7: every evidence pack issued, with the hash printed on it
CREATE TABLE IF NOT EXISTS screening_evidence_packs (
    id            SERIAL PRIMARY KEY,
    result_id     INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    generated_by  INTEGER,
    generated_at  TIMESTAMP NOT NULL DEFAULT now(),
    size_bytes    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sep_result ON screening_evidence_packs (result_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sep_hash ON screening_evidence_packs (sha256);

GRANT SELECT, INSERT, UPDATE ON screening_evidence_packs TO complynex;
GRANT USAGE, SELECT ON SEQUENCE screening_evidence_packs_id_seq TO complynex;
GRANT SELECT, INSERT, UPDATE ON screening_whitelist_matches TO complynex;
