-- audit_logs hash chain fixes (review of 20261029_security_hardening):
-- * ids are allocated INSIDE the advisory lock, so id order == chain order
--   even with concurrent writers;
-- * the digest marks NULL fields explicitly (concat_ws dropped them);
-- * existing rows are re-hashed once with the new digest.
BEGIN;

CREATE OR REPLACE FUNCTION audit_logs_row_digest(p_prev TEXT, r audit_logs) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $f$
  SELECT encode(sha256(convert_to(concat_ws('|',
         COALESCE(p_prev, 'GENESIS'), r.id::text,
         COALESCE(r.user_id::text, '<null>'), COALESCE(r.action, '<null>'),
         COALESCE(r.module, '<null>'), COALESCE(r.item_id::text, '<null>'),
         COALESCE(r.details, '<null>'), COALESCE(r.ip_address, '<null>'),
         COALESCE(r.created_at, '<null>')), 'UTF8')), 'hex')
$f$;

CREATE OR REPLACE FUNCTION audit_logs_chain() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_logs_chain'));
  NEW.id := nextval('audit_logs_id_seq');          -- allocated under the lock
  SELECT row_hash INTO NEW.prev_hash FROM audit_logs ORDER BY id DESC LIMIT 1;
  NEW.row_hash := audit_logs_row_digest(NEW.prev_hash, NEW);
  RETURN NEW;
END $f$;

LOCK TABLE audit_logs IN EXCLUSIVE MODE;
ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_immutable;
DO $$
DECLARE rec audit_logs; prev TEXT := NULL; h TEXT;
BEGIN
  FOR rec IN SELECT * FROM audit_logs ORDER BY id LOOP
    h := audit_logs_row_digest(prev, rec);
    UPDATE audit_logs SET prev_hash = prev, row_hash = h WHERE id = rec.id;
    prev := h;
  END LOOP;
END $$;
ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_logs_immutable;

COMMIT;
