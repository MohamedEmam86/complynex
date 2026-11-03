-- Phase 7 AML (F1, F2, F5, F6): customer risk model versions, periodic reviews, STR drafts, freeze log.
-- Idempotent. Nothing is switched on: the default risk model stays the one in code until the MLRO saves a version.
BEGIN;

CREATE TABLE IF NOT EXISTS aml_risk_models (
    id          SERIAL PRIMARY KEY,
    model       JSONB NOT NULL,
    reason      TEXT NOT NULL,
    created_by  INTEGER,
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    is_current  BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX IF NOT EXISTS aml_risk_models_one_current ON aml_risk_models (is_current) WHERE is_current;

CREATE TABLE IF NOT EXISTS aml_customer_reviews (
    id                  SERIAL PRIMARY KEY,
    customer_id         INTEGER NOT NULL,
    review_date         DATE NOT NULL,
    outcome             TEXT NOT NULL,
    notes               TEXT,
    old_classification  TEXT,
    new_classification  TEXT,
    next_review_date    DATE,
    reviewed_by         INTEGER,
    created_at          TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS aml_customer_reviews_customer ON aml_customer_reviews (customer_id, review_date DESC);

CREATE TABLE IF NOT EXISTS aml_freeze_log (
    id                  SERIAL PRIMARY KEY,
    reference           TEXT NOT NULL UNIQUE,
    customer_id         INTEGER,
    subject_name        TEXT NOT NULL,
    listed_name         TEXT,
    list_name           TEXT,
    screening_queue_id  INTEGER,
    sar_id              INTEGER,
    discovered_at       TIMESTAMP NOT NULL,
    frozen_at           TIMESTAMP,
    frozen_by           INTEGER,
    freeze_scope        TEXT,
    amount_frozen       NUMERIC(18, 2),
    currency            TEXT DEFAULT 'EGP',
    reported_at         TIMESTAMP,
    reported_by         INTEGER,
    reported_to         TEXT,
    report_reference    TEXT,
    released_at         TIMESTAMP,
    release_reason      TEXT,
    status              TEXT NOT NULL DEFAULT 'DISCOVERED',
    notes               TEXT,
    created_by          INTEGER,
    created_at          TIMESTAMP NOT NULL DEFAULT now(),
    updated_at          TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS aml_freeze_log_queue ON aml_freeze_log (screening_queue_id);
CREATE INDEX IF NOT EXISTS aml_freeze_log_sar ON aml_freeze_log (sar_id);
CREATE INDEX IF NOT EXISTS aml_freeze_log_status ON aml_freeze_log (status, discovered_at DESC);

CREATE TABLE IF NOT EXISTS aml_sar_drafts (
    id          SERIAL PRIMARY KEY,
    sar_id      INTEGER NOT NULL,
    version     INTEGER NOT NULL,
    content     JSONB NOT NULL,
    created_by  INTEGER,
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (sar_id, version)
);

-- an STR case can link the screening hit itself (screening queue item)
ALTER TABLE aml_sar_links DROP CONSTRAINT IF EXISTS aml_sar_links_link_type_check;
ALTER TABLE aml_sar_links ADD CONSTRAINT aml_sar_links_link_type_check
    CHECK (link_type IN ('tm_alert', 'screening_alert', 'screening_hit', 'transaction'));

GRANT SELECT, INSERT, UPDATE ON aml_risk_models, aml_customer_reviews, aml_freeze_log, aml_sar_drafts TO complynex;
GRANT USAGE, SELECT ON SEQUENCE aml_risk_models_id_seq, aml_customer_reviews_id_seq, aml_freeze_log_id_seq,
      aml_sar_drafts_id_seq TO complynex;

COMMIT;
