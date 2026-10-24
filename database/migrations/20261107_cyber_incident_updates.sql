-- Cyber incident response hub: status changes and notes per incident.
BEGIN;
CREATE TABLE IF NOT EXISTS cyber_incident_updates (
    id          SERIAL PRIMARY KEY,
    incident_id INTEGER NOT NULL,
    old_status  TEXT,
    new_status  TEXT,
    note        TEXT,
    created_by  INTEGER,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cyber_incident_updates_incident ON cyber_incident_updates (incident_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON cyber_incident_updates TO complynex;
GRANT USAGE, SELECT ON SEQUENCE cyber_incident_updates_id_seq TO complynex;
COMMIT;
