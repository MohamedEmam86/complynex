-- Security hardening (2026-10-21 review)
-- 1) account lockout + session revocation columns
-- 2) users.expires_at / last_login: text -> timestamptz (expiry is now enforced)
-- 3) tamper-evident audit_logs: hash chain + no UPDATE/DELETE
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
  IF (SELECT data_type FROM information_schema.columns
       WHERE table_name = 'users' AND column_name = 'expires_at') = 'text' THEN
    ALTER TABLE users ALTER COLUMN expires_at TYPE TIMESTAMPTZ
      USING NULLIF(btrim(expires_at), '')::timestamptz;
  END IF;
  IF (SELECT data_type FROM information_schema.columns
       WHERE table_name = 'users' AND column_name = 'last_login') = 'text' THEN
    ALTER TABLE users ALTER COLUMN last_login TYPE TIMESTAMPTZ
      USING NULLIF(btrim(last_login), '')::timestamptz;
  END IF;
END $$;

-- tamper-evident audit trail ---------------------------------------------------
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS prev_hash TEXT;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS row_hash  TEXT;

CREATE OR REPLACE FUNCTION audit_logs_row_digest(p_prev TEXT, r audit_logs) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $f$
  SELECT encode(sha256(convert_to(concat_ws('|', COALESCE(p_prev, 'GENESIS'), r.id, r.user_id, r.action,
         r.module, r.item_id, r.details, r.ip_address, r.created_at), 'UTF8')), 'hex')
$f$;

-- backfill existing rows once, in id order
DO $$
DECLARE rec audit_logs; prev TEXT := NULL;
BEGIN
  IF EXISTS (SELECT 1 FROM audit_logs WHERE row_hash IS NULL) THEN
    FOR rec IN SELECT * FROM audit_logs ORDER BY id LOOP
      UPDATE audit_logs SET prev_hash = prev, row_hash = audit_logs_row_digest(prev, rec) WHERE id = rec.id;
      prev := audit_logs_row_digest(prev, rec);
    END LOOP;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION audit_logs_chain() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_logs_chain'));
  IF NEW.id IS NULL THEN NEW.id := nextval('audit_logs_id_seq'); END IF;
  SELECT row_hash INTO NEW.prev_hash FROM audit_logs ORDER BY id DESC LIMIT 1;
  NEW.row_hash := audit_logs_row_digest(NEW.prev_hash, NEW);
  RETURN NEW;
END $f$;

CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  RAISE EXCEPTION 'audit_logs is append-only (% refused)', TG_OP;
END $f$;

DROP TRIGGER IF EXISTS trg_audit_logs_chain ON audit_logs;
CREATE TRIGGER trg_audit_logs_chain BEFORE INSERT ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_logs_chain();
DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;
CREATE TRIGGER trg_audit_logs_immutable BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable();

-- verification: returns the first id whose hash does not match (none = intact)
CREATE OR REPLACE FUNCTION audit_logs_verify() RETURNS TABLE(broken_id INTEGER, checked BIGINT)
LANGUAGE plpgsql STABLE AS $f$
DECLARE rec audit_logs; prev TEXT := NULL; n BIGINT := 0;
BEGIN
  FOR rec IN SELECT * FROM audit_logs ORDER BY id LOOP
    n := n + 1;
    IF rec.row_hash IS DISTINCT FROM audit_logs_row_digest(prev, rec)
       OR rec.prev_hash IS DISTINCT FROM prev THEN
      broken_id := rec.id; checked := n; RETURN NEXT; RETURN;
    END IF;
    prev := rec.row_hash;
  END LOOP;
  broken_id := NULL; checked := n; RETURN NEXT;
END $f$;

REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM complynex;
GRANT SELECT, INSERT ON audit_logs TO complynex;
GRANT USAGE, SELECT ON SEQUENCE audit_logs_id_seq TO complynex;
GRANT EXECUTE ON FUNCTION audit_logs_verify() TO complynex;
GRANT SELECT, UPDATE ON users TO complynex;

COMMIT;
