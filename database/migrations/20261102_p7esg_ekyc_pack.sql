-- Phase 7 (H4): eKYC is an optional package; keep it ON where it is in use today.
BEGIN;
INSERT INTO rc_packs (code, enabled, installed_version, installed_at, updated_at)
VALUES ('ekyc', TRUE, '1', NOW(), NOW())
ON CONFLICT (code) DO NOTHING;
COMMIT;
