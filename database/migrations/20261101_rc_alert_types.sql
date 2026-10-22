-- rc_alerts.alert_type was limited to the five control-library types, but
-- regcontrols.api.raise_alert is the shared alert API for every module. The
-- nightly delta re-screening ('screening_delta_hit') was rejected on 2026-10-22.
-- Accept any well-formed type key instead of a fixed list.
BEGIN;
ALTER TABLE rc_alerts DROP CONSTRAINT IF EXISTS rc_alerts_alert_type_check;
ALTER TABLE rc_alerts ADD CONSTRAINT rc_alerts_alert_type_check
    CHECK (alert_type ~ '^[a-z][a-z0-9_]{2,59}$');
COMMIT;
