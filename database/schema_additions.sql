
-- ============================================================================
-- AUDIT LOG (Enhancement)
-- ============================================================================
CREATE TABLE IF NOT EXISTS data_update_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    update_type VARCHAR(50) DEFAULT 'FULL_UPDATE',
    initiated_by INTEGER,
    total_sources INTEGER,
    records_added INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_unchanged INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'IN_PROGRESS',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    duration_seconds INTEGER NULL,
    error_message TEXT NULL,
    FOREIGN KEY (initiated_by) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_audit_log_status ON data_update_audit_log(status);
CREATE INDEX IF NOT EXISTS idx_audit_log_started ON data_update_audit_log(started_at DESC);

-- ============================================================================
-- WATCHLIST SCREENING (Enhancement)
-- ============================================================================

CREATE TABLE IF NOT EXISTS screening_data_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(20) NOT NULL,
    source_url VARCHAR(500),
    is_active BOOLEAN DEFAULT 1,
    priority INTEGER DEFAULT 0,
    last_successful_update TIMESTAMP
);

CREATE TABLE IF NOT EXISTS screening_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset VARCHAR(50), 
    name VARCHAR(500),
    aliases TEXT,
    type VARCHAR(50),
    source VARCHAR(50),
    list_type VARCHAR(50),
    reference_number VARCHAR(100),
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_watchlist_name ON screening_watchlist(name);
CREATE INDEX IF NOT EXISTS idx_watchlist_source ON screening_watchlist(source);
