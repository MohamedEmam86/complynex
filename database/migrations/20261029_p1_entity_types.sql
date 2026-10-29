-- Phase 1 (G2): one spelling per entity type in the internal lists (case variants and
-- ORGANIZATION meant the same thing and split person / company handling).
UPDATE internal_blacklist SET entity_type = 'INDIVIDUAL' WHERE entity_type = 'Individual';
UPDATE internal_blacklist SET entity_type = 'ENTITY' WHERE entity_type IN ('Entity', 'ORGANIZATION');
UPDATE internal_pep SET entity_type = 'INDIVIDUAL' WHERE entity_type = 'Individual';
