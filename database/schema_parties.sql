-- ============================================================================
-- TABLE 1: Parties (canonical entity registry — Entity 360)
-- ============================================================================
-- Identity is matched on a deterministic hash of the raw ID/CR number, using
-- the same EncryptionService.hash_value() already used for
-- customers.national_id_hash (data_protection/encryption_service.py) — no
-- new hashing scheme introduced. No normalization is applied beyond what
-- hash_value() does today, matching that existing precedent; this means
-- matching is sensitive to formatting differences between sources (e.g.
-- "12345" vs "123-45") — a known limitation, not solved here.

CREATE TABLE parties (
    id SERIAL PRIMARY KEY,

    party_type VARCHAR(20) NOT NULL CHECK (party_type IN ('INDIVIDUAL', 'ENTITY')),

    full_name VARCHAR(255) NOT NULL,
    full_name_arabic VARCHAR(255),
    date_of_birth DATE,
    nationality VARCHAR(100),

    id_type VARCHAR(50),
    id_number_hash TEXT,        -- individuals: national ID / passport hash
    cr_number_hash TEXT,        -- entities: commercial registration number hash

    email VARCHAR(255),
    phone VARCHAR(50),
    risk_rating VARCHAR(20),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_parties_id_number_hash ON parties(id_number_hash);
CREATE INDEX idx_parties_cr_number_hash ON parties(cr_number_hash);
CREATE INDEX idx_parties_name ON parties USING GIN (full_name gin_trgm_ops);


-- ============================================================================
-- TABLE 2: Party Links (party <-> source record, many-to-one)
-- ============================================================================
-- One party can have multiple links (e.g. a person who is both an AML
-- customer and a merchant UBO); one source record links to exactly one party.

CREATE TABLE party_links (
    id SERIAL PRIMARY KEY,
    party_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,

    source_module VARCHAR(60) NOT NULL,
    source_table VARCHAR(60) NOT NULL,
    source_record_id INTEGER NOT NULL,
    link_role VARCHAR(30) NOT NULL,   -- CUSTOMER, MERCHANT, MERCHANT_UBO, EKYC_APPLICANT

    linked_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(source_table, source_record_id, link_role)
);

CREATE INDEX idx_party_links_party ON party_links(party_id);
CREATE INDEX idx_party_links_source ON party_links(source_table, source_record_id);
