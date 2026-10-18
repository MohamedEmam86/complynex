-- Metrics & Monitoring Table
-- Stores performance and quality metrics for each screening request

CREATE TABLE IF NOT EXISTS screening_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_time_ms REAL,
    total_candidates INTEGER,
    total_matches INTEGER,
    highest_score REAL,
    cache_hit BOOLEAN DEFAULT 0,
    screened_name VARCHAR(255),
    entity_type VARCHAR(50),
    match_status VARCHAR(50) -- 'CLEAR', 'POTENTIAL_MATCH', 'CONFIRMED_HIT'
);

CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON screening_metrics(timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_status ON screening_metrics(match_status);
