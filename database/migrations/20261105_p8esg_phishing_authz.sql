-- Phase 8 (ESG/phishing review fixes): phishing authorisation history + evidence retention.
--
-- B1  A revoked authorisation must not be editable back into force, and once a
--     signed document has been attached the record locks. Re-authorisation is a
--     NEW record: drop the one-row-per-campaign UNIQUE and track the live record
--     with an is_current flag (one current row per campaign, enforced by a
--     partial index). document_attached_at latches when a document is first
--     attached so the lock survives deleting the PDF.
-- 8   Keep the signed authorisation as evidence: the campaign FK becomes
--     ON DELETE RESTRICT (exactly one FK), so a campaign carrying an
--     authorisation cannot be silently deleted.
--
-- Constraint/index names are discovered from the catalog (they were created by
-- an earlier migration and may be named differently on different deployments),
-- dropped whatever they are called, and the result is verified.
BEGIN;

ALTER TABLE phishing_authorisations
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE phishing_authorisations
    ADD COLUMN IF NOT EXISTS document_attached_at TIMESTAMP;

-- Replace the per-campaign UNIQUE with "at most one CURRENT record per campaign".
DO $$
DECLARE
    r record;
    col smallint;
BEGIN
    SELECT attnum INTO col FROM pg_attribute
     WHERE attrelid = 'phishing_authorisations'::regclass
       AND attname = 'campaign_id' AND NOT attisdropped;

    -- drop any UNIQUE constraint that is exactly on (campaign_id)
    FOR r IN
        SELECT conname FROM pg_constraint
         WHERE conrelid = 'phishing_authorisations'::regclass
           AND contype = 'u' AND conkey = ARRAY[col]::smallint[]
    LOOP
        EXECUTE format('ALTER TABLE phishing_authorisations DROP CONSTRAINT %I', r.conname);
    END LOOP;

    -- drop any NON-partial unique index on exactly (campaign_id) not backing a constraint
    FOR r IN
        SELECT i.relname FROM pg_index x
          JOIN pg_class i ON i.oid = x.indexrelid
         WHERE x.indrelid = 'phishing_authorisations'::regclass
           AND x.indisunique AND x.indpred IS NULL
           AND x.indnatts = 1 AND x.indkey::text = col::text
           AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = x.indexrelid)
    LOOP
        EXECUTE format('DROP INDEX %I', r.relname);
    END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_phishing_auth_current
    ON phishing_authorisations (campaign_id)
    WHERE is_current;

-- Evidence must survive: ensure exactly ONE campaign FK, ON DELETE RESTRICT.
DO $$
DECLARE
    r record;
    col smallint;
BEGIN
    SELECT attnum INTO col FROM pg_attribute
     WHERE attrelid = 'phishing_authorisations'::regclass
       AND attname = 'campaign_id' AND NOT attisdropped;

    FOR r IN
        SELECT conname FROM pg_constraint
         WHERE conrelid = 'phishing_authorisations'::regclass
           AND contype = 'f' AND conkey = ARRAY[col]::smallint[]
    LOOP
        EXECUTE format('ALTER TABLE phishing_authorisations DROP CONSTRAINT %I', r.conname);
    END LOOP;

    ALTER TABLE phishing_authorisations
        ADD CONSTRAINT phishing_authorisations_campaign_id_fkey
        FOREIGN KEY (campaign_id) REFERENCES phishing_campaigns(id) ON DELETE RESTRICT;
END $$;

-- Verify: no non-partial UNIQUE on (campaign_id) must remain.
DO $$
DECLARE
    col smallint;
    bad int;
BEGIN
    SELECT attnum INTO col FROM pg_attribute
     WHERE attrelid = 'phishing_authorisations'::regclass
       AND attname = 'campaign_id' AND NOT attisdropped;

    SELECT count(*) INTO bad FROM pg_index x
     WHERE x.indrelid = 'phishing_authorisations'::regclass
       AND x.indisunique AND x.indpred IS NULL
       AND x.indnatts = 1 AND x.indkey::text = col::text;

    IF bad > 0 THEN
        RAISE EXCEPTION 'a non-partial UNIQUE on phishing_authorisations(campaign_id) still exists (count=%)', bad;
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON phishing_authorisations TO complynex;
COMMIT;
