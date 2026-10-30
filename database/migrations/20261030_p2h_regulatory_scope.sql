-- Phase 2 (P2-4): regulatory-measures lists (e.g. PMA Art. 58 list) are searched only where the
-- MLRO chooses: 'kyb' (default: KYB / merchant / company screenings), 'all' or 'off'.
INSERT INTO screening_config (config_key, config_value, category, description, updated_at)
SELECT 'regulatory_lists_scope', 'kyb', 'lists',
       'Where regulatory-measures lists are searched: kyb / all / off', CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM screening_config WHERE config_key = 'regulatory_lists_scope');
