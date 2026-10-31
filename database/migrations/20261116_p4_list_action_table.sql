-- P4-3: action by list type (screening/workflow.py). Seeded with the default table; the MLRO
-- changes it on /screening/config/list-actions (reason required, audited). Idempotent.
INSERT INTO screening_config (config_key, config_value, category, description, updated_at)
SELECT 'list_action_table',
       '{"CONTEXT": "INFORMATION", "COUNTER_SANCTIONS": "REVIEW", "CRIME": "MLRO_DECISION", "DEBARMENT": "REVIEW", "EMLCU": "FREEZE_REPORT", "EXPORT_CONTROL": "REVIEW", "INTERNAL": "FREEZE_REPORT", "PEP": "EDD", "PMA": "FREEZE_REPORT", "POI": "INFORMATION", "REGULATORY": "KYB_REVIEW", "REG_ACTION": "REVIEW", "SANCTIONS": "FREEZE_ESCALATE", "SANCTION_LINKED": "MLRO_DECISION", "TERROR": "FREEZE_ESCALATE", "TRADE_RISK": "REVIEW", "UNCLASSIFIED": "FREEZE_ESCALATE"}',
       'workflow', 'Action required for each kind of list (MLRO)', CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM screening_config WHERE config_key = 'list_action_table');
