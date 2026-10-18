-- API v1 schema additions
-- Run once: psql -d complynex_db -f schema_api_v1.sql

-- API key store
CREATE TABLE IF NOT EXISTS api_keys (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(120) NOT NULL,
    key_hash        VARCHAR(64) NOT NULL UNIQUE,   -- SHA-256 hex of the raw key
    key_prefix      VARCHAR(8)  NOT NULL,           -- first 8 chars shown in UI
    owner_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    scopes          TEXT NOT NULL DEFAULT 'screening:read,aml:read,kyc:read',
    rate_limit      INTEGER NOT NULL DEFAULT 100,   -- requests per minute
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at    TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL
);

-- Per-key audit log (separate from the main audit_logs for query efficiency)
CREATE TABLE IF NOT EXISTS api_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    key_id          INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    key_prefix      VARCHAR(8),
    endpoint        VARCHAR(200) NOT NULL,
    method          VARCHAR(10) NOT NULL,
    status_code     INTEGER,
    request_ip      VARCHAR(45),
    request_body    TEXT,           -- truncated PII-scrubbed snapshot
    response_ms     INTEGER,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_audit_key  ON api_audit_log (key_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_audit_time ON api_audit_log (created_at DESC);

-- AML rule management additions
ALTER TABLE tm_rules
    ADD COLUMN IF NOT EXISTS created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS approved_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS approved_at   TIMESTAMP,
    ADD COLUMN IF NOT EXISTS status        VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                                           CHECK (status IN ('PENDING','ACTIVE','DISABLED')),
    ADD COLUMN IF NOT EXISTS version       INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS previous_id   INTEGER REFERENCES tm_rules(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_at    TIMESTAMP;

-- Back-fill: treat all existing rules as already active
UPDATE tm_rules SET status = CASE WHEN is_active = 0 OR is_active IS FALSE THEN 'DISABLED' ELSE 'ACTIVE' END WHERE status IS NULL OR status = '';
