-- ============================================================================
-- TABLE 1: Compliance Events (event bus log)
-- ============================================================================

CREATE TABLE compliance_events (
    id SERIAL PRIMARY KEY,

    event_type VARCHAR(100) NOT NULL,          -- e.g. 'screening.hit', 'merchant.ubo.updated'
    source_module VARCHAR(60),                 -- e.g. 'Customer KYC', 'Merchant KYC'
    source_table VARCHAR(60),
    source_record_id INTEGER,

    entity_type VARCHAR(30),                   -- e.g. 'CUSTOMER', 'MERCHANT'
    entity_id INTEGER,

    payload JSONB NOT NULL DEFAULT '{}',

    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, processed, error
    error_message TEXT,

    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_compliance_events_type ON compliance_events(event_type);
CREATE INDEX idx_compliance_events_status ON compliance_events(status);
CREATE INDEX idx_compliance_events_created ON compliance_events(created_at DESC);
CREATE INDEX idx_compliance_events_source ON compliance_events(source_module, source_table, source_record_id);


-- ============================================================================
-- TABLE 2: Event Routing Rules (admin-editable — data, not code)
-- ============================================================================

CREATE TABLE event_routing_rules (
    id SERIAL PRIMARY KEY,

    name VARCHAR(120) NOT NULL,
    event_type_pattern VARCHAR(100) NOT NULL,  -- exact 'merchant.ubo.updated' or prefix 'merchant.*'
    action_type VARCHAR(20) NOT NULL CHECK (action_type IN ('notify', 'screen')),
    action_config JSONB NOT NULL DEFAULT '{}',

    priority INTEGER NOT NULL DEFAULT 100,     -- lower runs first
    enabled BOOLEAN NOT NULL DEFAULT true,
    description TEXT,

    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_event_routing_rules_pattern ON event_routing_rules(event_type_pattern);
CREATE INDEX idx_event_routing_rules_enabled ON event_routing_rules(enabled);


-- ============================================================================
-- Default routing rules (P1: screening-hit notifications + merchant UBO
-- auto-screen). Admins can disable/edit these from the Event Bus admin UI —
-- nothing below is hardcoded into application code.
-- ============================================================================

INSERT INTO event_routing_rules (name, event_type_pattern, action_type, action_config, priority, description) VALUES
(
    'Notify compliance on screening hit',
    'screening.hit',
    'notify',
    '{"target_roles": ["admin", "compliance_officer"], "title": "Screening hit: {entity_name}", "message": "A {source_module} screening for \"{entity_name}\" returned {high_risk_matches} high-risk match(es) (highest score {highest_score}).", "link": "/screening/queue"}',
    100,
    'Fires when any screening run (customer onboarding, merchant KYC, etc.) records at least one high-risk match.'
),
(
    'Auto-screen merchant UBO on save',
    'merchant.ubo.updated',
    'screen',
    '{}',
    100,
    'Fires when a merchant is created/edited with UBO details, so the UBO gets sanctions/PEP screened without waiting for the manual "Run Screening" button.'
),
(
    'Notify compliance on merchant UBO screening hit',
    'merchant.screening.hit',
    'notify',
    '{"target_roles": ["admin", "compliance_officer"], "title": "Merchant UBO screening hit: {entity_name}", "message": "Automated UBO screening for \"{entity_name}\" returned {high_risk_matches} high-risk match(es).", "link": "/merchant-kyc/{source_record_id}"}',
    100,
    'Fires when the auto-screen-on-save rule above finds a high-risk match on a merchant UBO.'
);
