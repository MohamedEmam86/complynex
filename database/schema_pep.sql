-- ============================================================================
-- TABLE 1: PEP Master Records
-- ============================================================================

CREATE TABLE pep_master (
    id SERIAL PRIMARY KEY,
    
    -- Identity
    canonical_name_en VARCHAR(255) NOT NULL,  -- Primary English name
    canonical_name_ar VARCHAR(255),            -- Primary Arabic name
    
    -- Personal Information
    date_of_birth DATE,
    place_of_birth VARCHAR(255),
    nationality VARCHAR(10) DEFAULT 'EG',     -- ISO country code
    gender VARCHAR(10),
    
    -- Current Status
    is_active BOOLEAN DEFAULT true,            -- Currently a PEP?
    pep_level VARCHAR(50),                     -- National, Regional, Local
    pep_category VARCHAR(50),                  -- Government, Military, Judicial, etc.
    risk_level VARCHAR(20),                    -- High, Medium, Low
    
    -- Metadata
    first_seen TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    last_verified TIMESTAMP,
    source_count INTEGER DEFAULT 0,            -- Number of sources confirming
    confidence_score FLOAT DEFAULT 0.0,        -- 0.0 to 1.0
    
    -- Full-text search
    search_vector TSVECTOR,
    
    -- Indexes will be created below
    CONSTRAINT unique_canonical_name UNIQUE(canonical_name_en, date_of_birth)
);

-- Create indexes for fast searching
CREATE INDEX idx_pep_master_name_en ON pep_master USING GIN (canonical_name_en gin_trgm_ops);
CREATE INDEX idx_pep_master_name_ar ON pep_master USING GIN (canonical_name_ar gin_trgm_ops);
CREATE INDEX idx_pep_master_dob ON pep_master(date_of_birth);
CREATE INDEX idx_pep_master_active ON pep_master(is_active);
CREATE INDEX idx_pep_master_search ON pep_master USING GIN(search_vector);


-- ============================================================================
-- TABLE 2: PEP Name Aliases & Transliterations
-- ============================================================================

CREATE TABLE pep_aliases (
    id SERIAL PRIMARY KEY,
    pep_id INTEGER REFERENCES pep_master(id) ON DELETE CASCADE,
    
    -- Name variations
    alias_name VARCHAR(255) NOT NULL,
    alias_language VARCHAR(10),                -- 'en', 'ar'
    alias_type VARCHAR(50),                    -- 'official', 'transliteration', 'nickname', 'maiden'
    
    -- Source tracking
    source VARCHAR(100),                       -- Which source provided this alias
    source_url TEXT,
    verified BOOLEAN DEFAULT false,
    
    -- Metadata
    added_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_aliases_pep_id ON pep_aliases(pep_id);
CREATE INDEX idx_aliases_name ON pep_aliases USING GIN (alias_name gin_trgm_ops);


-- ============================================================================
-- TABLE 3: Political Positions & Appointments
-- ============================================================================

CREATE TABLE pep_positions (
    id SERIAL PRIMARY KEY,
    pep_id INTEGER REFERENCES pep_master(id) ON DELETE CASCADE,
    
    -- Position details
    position_title_en VARCHAR(255),
    position_title_ar VARCHAR(255),
    organization_en VARCHAR(255),
    organization_ar VARCHAR(255),
    
    -- Dates
    start_date DATE,
    end_date DATE,                             -- NULL if current
    is_current BOOLEAN GENERATED ALWAYS AS (end_date IS NULL) STORED,
    
    -- Classification
    position_type VARCHAR(50),                 -- Minister, MP, Governor, etc.
    ministry VARCHAR(100),                     -- If applicable
    political_party VARCHAR(100),
    
    -- Source tracking
    source VARCHAR(100),
    source_url TEXT,
    verified BOOLEAN DEFAULT false,
    confidence FLOAT DEFAULT 0.5,
    
    -- Metadata
    added_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_positions_pep_id ON pep_positions(pep_id);
CREATE INDEX idx_positions_current ON pep_positions(is_current);
CREATE INDEX idx_positions_dates ON pep_positions(start_date, end_date);
CREATE INDEX idx_positions_org ON pep_positions(organization_en);


-- ============================================================================
-- TABLE 4: Corporate Links (from OpenCorporates)
-- ============================================================================

CREATE TABLE pep_corporate_links (
    id SERIAL PRIMARY KEY,
    pep_id INTEGER REFERENCES pep_master(id) ON DELETE CASCADE,
    
    -- Company information
    company_name VARCHAR(255) NOT NULL,
    company_jurisdiction VARCHAR(10),          -- 'eg' for Egypt
    company_number VARCHAR(100),               -- Official registration number
    
    -- Relationship
    role VARCHAR(100),                         -- Director, Officer, Shareholder, UBO
    ownership_percentage FLOAT,                -- If shareholder
    
    -- Dates
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN GENERATED ALWAYS AS (end_date IS NULL) STORED,
    
    -- Source
    source VARCHAR(100) DEFAULT 'OpenCorporates',
    source_url TEXT,
    opencorporates_url TEXT,
    
    -- Metadata
    added_at TIMESTAMP DEFAULT NOW(),
    last_verified TIMESTAMP
);

CREATE INDEX idx_corporate_pep_id ON pep_corporate_links(pep_id);
CREATE INDEX idx_corporate_company ON pep_corporate_links(company_name);
CREATE INDEX idx_corporate_current ON pep_corporate_links(is_current);


-- ============================================================================
-- TABLE 5: Source Provenance
-- ============================================================================

CREATE TABLE pep_sources (
    id SERIAL PRIMARY KEY,
    pep_id INTEGER REFERENCES pep_master(id) ON DELETE CASCADE,
    
    -- Source information
    source_name VARCHAR(100) NOT NULL,         -- 'opensanctions', 'wikidata', 'cabinet.gov.eg', etc.
    source_type VARCHAR(50),                   -- 'api', 'scrape', 'manual'
    source_url TEXT,
    source_record_id VARCHAR(255),             -- External ID from source
    
    -- Data snapshot
    raw_data JSONB,                            -- Original data as received
    
    -- Timestamps
    first_retrieved TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    last_verified TIMESTAMP,
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    confidence FLOAT DEFAULT 0.5
);

CREATE INDEX idx_sources_pep_id ON pep_sources(pep_id);
CREATE INDEX idx_sources_name ON pep_sources(source_name);
CREATE INDEX idx_sources_active ON pep_sources(is_active);


-- ============================================================================
-- TABLE 6: Update Logs
-- ============================================================================

CREATE TABLE pep_update_logs (
    id SERIAL PRIMARY KEY,
    
    -- Update information
    source_name VARCHAR(100) NOT NULL,
    update_type VARCHAR(50),                   -- 'full', 'incremental', 'manual'
    
    -- Results
    records_fetched INTEGER DEFAULT 0,
    records_added INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_merged INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    
    -- Status
    status VARCHAR(50),                        -- 'running', 'completed', 'failed'
    error_message TEXT,
    
    -- Timing
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    duration_seconds INTEGER GENERATED ALWAYS AS (
        EXTRACT(EPOCH FROM (completed_at - started_at))
    ) STORED
);

CREATE INDEX idx_update_logs_source ON pep_update_logs(source_name);
CREATE INDEX idx_update_logs_started ON pep_update_logs(started_at DESC);


-- ============================================================================
-- TABLE 7: Deduplication Tracking
-- ============================================================================

CREATE TABLE pep_duplicate_candidates (
    id SERIAL PRIMARY KEY,
    
    -- Potential duplicates
    pep_id_1 INTEGER REFERENCES pep_master(id) ON DELETE CASCADE,
    pep_id_2 INTEGER REFERENCES pep_master(id) ON DELETE CASCADE,
    
    -- Matching details
    match_score FLOAT NOT NULL,                -- 0.0 to 1.0
    match_reason VARCHAR(255),                 -- 'name_fuzzy', 'dob_exact', 'position_overlap'
    
    -- Resolution
    status VARCHAR(50) DEFAULT 'pending',      -- 'pending', 'merged', 'dismissed'
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    merged_into INTEGER REFERENCES pep_master(id),
    
    -- Metadata
    detected_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_duplicates_status ON pep_duplicate_candidates(status);
CREATE INDEX idx_duplicates_score ON pep_duplicate_candidates(match_score DESC);
