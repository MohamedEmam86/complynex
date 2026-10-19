-- =============================================================================
-- Compliance Copilot — OCR, freeze-order screening, regulatory-library index,
-- monitored mailbox (all local; no external AI / OCR / cloud service).
--
--  * ai_intake_items: how the text was extracted (text / pypdf / ocr / none),
--    the extraction note, when the item was received (e-mail Date header or
--    the order date), the source e-mail Message-ID (de-duplication) and when
--    its subjects were screened.
--  * ai_screening_matches: freeze-order subjects screened against customers,
--    merchants, beneficial owners and recent counterparties, with the
--    decision (freeze / false positive) per match.
--  * ai_library_paragraphs: paragraphs of policies, framework requirements and
--    circulars with an optional local embedding vector, used to cite the
--    source of every policy-question answer.
--
-- Idempotent. DDL runs as postgres; GRANTs at the end.
-- =============================================================================
BEGIN;

ALTER TABLE ai_intake_items ADD COLUMN IF NOT EXISTS extraction_method VARCHAR(10);   -- text | pypdf | ocr | none
ALTER TABLE ai_intake_items ADD COLUMN IF NOT EXISTS extraction_note   TEXT;
ALTER TABLE ai_intake_items ADD COLUMN IF NOT EXISTS received_at       TIMESTAMP;     -- e-mail Date / order date (if earlier than created_at)
ALTER TABLE ai_intake_items ADD COLUMN IF NOT EXISTS source_message_id VARCHAR(300);  -- IMAP import: Message-ID
ALTER TABLE ai_intake_items ADD COLUMN IF NOT EXISTS screened_at       TIMESTAMP;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_intake_message_id ON ai_intake_items(source_message_id) WHERE source_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ai_screening_matches (
    id               SERIAL PRIMARY KEY,
    item_id          INTEGER NOT NULL REFERENCES ai_intake_items(id) ON DELETE CASCADE,
    query_name       VARCHAR(300),                 -- name as written in the order
    query_id         VARCHAR(40),                  -- identification number as written in the order
    source           VARCHAR(30) NOT NULL,         -- customer | merchant | beneficial_owner | counterparty
    source_table     VARCHAR(60) NOT NULL,
    record_id        INTEGER NOT NULL,
    matched_name     VARCHAR(300),
    match_type       VARCHAR(12) NOT NULL CHECK (match_type IN ('id', 'name')),
    score            NUMERIC(5,3) NOT NULL DEFAULT 0,
    detail           TEXT,
    status           VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'frozen', 'false_positive')),
    reason           TEXT,
    aml_unusual_id   INTEGER,
    decided_by       INTEGER REFERENCES users(id),
    decided_at       TIMESTAMP,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ai_screening_match_uniq UNIQUE (item_id, source_table, record_id, match_type)
);
CREATE INDEX IF NOT EXISTS idx_ai_screening_item ON ai_screening_matches(item_id);

CREATE TABLE IF NOT EXISTS ai_library_paragraphs (
    id            SERIAL PRIMARY KEY,
    source_type   VARCHAR(20) NOT NULL,            -- policy | requirement | framework | circular
    source_id     INTEGER NOT NULL,
    para_no       INTEGER NOT NULL DEFAULT 1,
    ref_label     VARCHAR(200),                    -- e.g. policy number, framework + requirement reference
    title         VARCHAR(400),
    body          TEXT NOT NULL,
    endpoint      VARCHAR(100),                    -- Flask endpoint of the source page
    endpoint_args JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding     DOUBLE PRECISION[],              -- optional, from the local embeddings provider
    embed_model   VARCHAR(120),
    indexed_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ai_library_para_uniq UNIQUE (source_type, source_id, para_no)
);
CREATE INDEX IF NOT EXISTS idx_ai_library_source ON ai_library_paragraphs(source_type, source_id);

-- The generic freeze-order intent screens its subjects on confirmation (data flag; editable in the intake catalog).
UPDATE ai_intents SET handler_params = handler_params || '{"screen_subjects": true}'::jsonb
 WHERE code = 'freeze_order' AND NOT (handler_params ? 'screen_subjects');

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_intake_items, ai_screening_matches, ai_library_paragraphs TO complynex;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO complynex;

COMMIT;
