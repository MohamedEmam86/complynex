-- Run this if tables are missing

-- Encryption audit (if missing)
CREATE TABLE IF NOT EXISTS encryption_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    action TEXT NOT NULL,
    user_id INTEGER,
    ip_address TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Data breaches (if missing)
CREATE TABLE IF NOT EXISTS data_breaches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovery_date TIMESTAMP NOT NULL,
    breach_type TEXT NOT NULL,
    affected_records INTEGER NOT NULL,
    affected_data_types TEXT NOT NULL,
    severity INTEGER NOT NULL,
    description TEXT NOT NULL,
    notification_deadline TIMESTAMP NOT NULL,
    status TEXT NOT NULL,
    reported_by INTEGER NOT NULL
);

-- Screening data sources (if missing)
CREATE TABLE IF NOT EXISTS screening_data_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    url TEXT,
    is_active BOOLEAN DEFAULT 1,
    priority INTEGER DEFAULT 1,
    last_updated TIMESTAMP,
    records_count INTEGER DEFAULT 0
);

-- Watchlist (if missing)
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source TEXT NOT NULL,
    reason TEXT,
    status TEXT DEFAULT 'ACTIVE',
    added_by INTEGER,
    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add missing columns to existing tables
-- These will fail if they already exist, which is fine in sqlite script if handled, 
-- but better to run safely or manually. 
-- In SQLite, ADD COLUMN is supported.
-- We wrap in transaction to ensure consistency? No, SQLite doesn't support IF NOT EXISTS for columns easily in one CLI call.
-- We will assume they might fail and that's okay, or we can use a python script to check first.

-- However, for this script, we'll try to add them. If they fail, they fail (if using sqlite3 shell).
-- better to do this in python `verify_database_schema.py` where we can check column existence.

-- But I will include them here commented out or as instructions? 
-- The guide said "RUN: sqlite3 complynex.db < scripts/create_missing_tables.sql"
-- So I should include them.
-- If I run this and columns exist, it will error.
-- I'll put them at the end.

ALTER TABLE customers ADD COLUMN email_encrypted TEXT;
ALTER TABLE customers ADD COLUMN phone_encrypted TEXT;
ALTER TABLE customers ADD COLUMN national_id_hash TEXT;
ALTER TABLE customers ADD COLUMN is_encrypted INTEGER DEFAULT 0;

ALTER TABLE users ADD COLUMN password_hash TEXT;
ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP;
