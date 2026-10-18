-- =============================================================================
-- AML unusual-transactions register (core, aml module)
-- Any module or pack that detects a pattern worth an AML study registers a
-- candidate here (aml/unusual.py); the AML team studies it and decides
-- STR / no STR. Idempotent.
-- =============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS aml_unusual_transactions (
    id               SERIAL PRIMARY KEY,
    reference        VARCHAR(30) UNIQUE,
    source_module    VARCHAR(40) NOT NULL,
    source_table     VARCHAR(60),
    source_record_id INTEGER,
    detection_rule   VARCHAR(60) NOT NULL,
    party_id         INTEGER REFERENCES parties(id) ON DELETE SET NULL,
    subject_name     VARCHAR(255),
    subject_ref      VARCHAR(80),
    amount           NUMERIC(18,2),
    description      TEXT,
    detected_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status           VARCHAR(20) NOT NULL DEFAULT 'candidate'
                     CHECK (status IN ('candidate', 'under_study', 'str_filed', 'no_str', 'dismissed')),
    study_due_date   DATE,
    analysis         TEXT,
    decision         VARCHAR(10) CHECK (decision IN ('str', 'no_str')),
    decision_by      INTEGER REFERENCES users(id),
    decision_at      TIMESTAMP,
    str_reference    VARCHAR(80),
    org_unit_id      INTEGER,
    created_by       INTEGER REFERENCES users(id),
    CONSTRAINT aml_unusual_uniq UNIQUE (source_table, source_record_id, detection_rule)
);
CREATE INDEX IF NOT EXISTS idx_aml_unusual_status ON aml_unusual_transactions(status);


GRANT SELECT, INSERT, UPDATE, DELETE ON aml_unusual_transactions TO complynex;
GRANT USAGE, SELECT ON aml_unusual_transactions_id_seq TO complynex;

COMMIT;
