-- Phase 8 (ESG/phishing review fixes): phishing authorisation history + evidence retention.
--
-- B1  A revoked authorisation must not be editable back into force. Re-authorisation
--     is a NEW record: drop the one-row-per-campaign UNIQUE and track the live record
--     with an is_current flag (one current row per campaign, enforced by a partial index).
-- 8   Keep the signed authorisation as evidence: the campaign FK becomes ON DELETE
--     RESTRICT, so a campaign that carries an authorisation cannot be silently deleted.
BEGIN;

ALTER TABLE phishing_authorisations
    ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT TRUE;

-- Replace the per-campaign UNIQUE with "at most one CURRENT record per campaign".
ALTER TABLE phishing_authorisations
    DROP CONSTRAINT IF EXISTS phishing_authorisations_campaign_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_phishing_auth_current
    ON phishing_authorisations (campaign_id)
    WHERE is_current;

-- Evidence must survive: deleting a campaign that still has an authorisation is refused.
ALTER TABLE phishing_authorisations
    DROP CONSTRAINT IF EXISTS phishing_authorisations_campaign_id_fkey;
ALTER TABLE phishing_authorisations
    ADD CONSTRAINT phishing_authorisations_campaign_id_fkey
        FOREIGN KEY (campaign_id) REFERENCES phishing_campaigns(id) ON DELETE RESTRICT;

COMMIT;
