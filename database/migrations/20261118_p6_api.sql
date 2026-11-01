-- P6-2 / P6-8 / G12: screening API v1 — per-client keys (sandbox, rotation), idempotency,
-- the client's own screenings, signed webhooks with a delivery log.
BEGIN;

-- never wait long for a lock on a busy table (a running request holds users / api_keys)
SET lock_timeout = '5s';
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS client_id   INTEGER;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS sandbox     BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS rotated_from INTEGER;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS revoked_at  TIMESTAMP;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS revoked_by  INTEGER;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS description TEXT;

CREATE TABLE IF NOT EXISTS api_idempotency (
    id            BIGSERIAL PRIMARY KEY,
    client_id     INTEGER NOT NULL,
    idem_key      VARCHAR(200) NOT NULL,
    request_hash  CHAR(64) NOT NULL,
    status_code   INTEGER,
    response      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (client_id, idem_key)
);
CREATE INDEX IF NOT EXISTS idx_api_idem_created ON api_idempotency (created_at);

CREATE TABLE IF NOT EXISTS api_screenings (
    id            BIGSERIAL PRIMARY KEY,
    client_id     INTEGER NOT NULL,
    key_id        INTEGER,
    kind          VARCHAR(20) NOT NULL,              -- screening | payment | batch
    sandbox       BOOLEAN NOT NULL DEFAULT FALSE,
    customer_ref  VARCHAR(200),
    request_id    VARCHAR(64),
    history_id    INTEGER,                           -- screening_history.id (person / company screenings)
    result_id     INTEGER,                           -- screening_results.id
    job_id        VARCHAR(64),                       -- screening_bulk_jobs.id (batch)
    status        VARCHAR(40),
    decision      VARCHAR(10),                       -- payments: PASS | HOLD | BLOCK
    response      JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_api_scr_client ON api_screenings (client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_scr_history ON api_screenings (history_id);
CREATE INDEX IF NOT EXISTS idx_api_scr_job ON api_screenings (job_id);

CREATE TABLE IF NOT EXISTS api_webhooks (
    id            SERIAL PRIMARY KEY,
    client_id     INTEGER NOT NULL,
    url           TEXT NOT NULL,
    secret_enc    TEXT NOT NULL,
    events        TEXT NOT NULL DEFAULT 'screening.completed,hit.decided,list.updated',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_by    INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at   TIMESTAMPTZ,
    disabled_by   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_api_wh_client ON api_webhooks (client_id);

CREATE TABLE IF NOT EXISTS api_webhook_deliveries (
    id               BIGSERIAL PRIMARY KEY,
    webhook_id       INTEGER NOT NULL,
    event            VARCHAR(60) NOT NULL,
    event_key        VARCHAR(200),                   -- de-duplication of emitted events
    payload          JSONB NOT NULL,
    status           VARCHAR(12) NOT NULL DEFAULT 'PENDING',   -- PENDING | DELIVERED | DEAD
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_status_code INTEGER,
    last_error       TEXT,
    delivered_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (webhook_id, event_key)
);
CREATE INDEX IF NOT EXISTS idx_api_whd_due ON api_webhook_deliveries (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_api_whd_hook ON api_webhook_deliveries (webhook_id, created_at DESC);

CREATE TABLE IF NOT EXISTS api_event_cursors (
    name        VARCHAR(60) PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON api_keys, api_idempotency, api_screenings, api_webhooks,
      api_webhook_deliveries, api_event_cursors TO complynex;
GRANT USAGE, SELECT ON SEQUENCE api_idempotency_id_seq, api_screenings_id_seq, api_webhooks_id_seq,
      api_webhook_deliveries_id_seq TO complynex;

COMMIT;
