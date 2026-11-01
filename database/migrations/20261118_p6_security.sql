-- Phase 6 security (P6-5 / P6-6), 1 Nov 2026.
-- Additive only: new columns / tables / functions; existing rows are not changed.
--  * users.lock_count (lockout back-off), users.mfa_prompted_at (enrolment grace period)
--  * password_history (no re-use of recent passwords)
--  * audit_anchors: append-only, hash-chained checkpoints of the audit_logs chain
--  * access_reviews: record of periodic user-access reviews
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS lock_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_prompted_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS password_history (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_password_history_user ON password_history (user_id, created_at DESC);

-- audit_logs_verify() (broken_id, checked) already exists (20261029_security_hardening).

-- anchors: checkpoints of the chain (last id, its hash, row count), themselves
-- chained, append-only. A rewritten or truncated audit trail no longer matches
-- the anchors written before the change.
CREATE TABLE IF NOT EXISTS audit_anchors (
    id               SERIAL PRIMARY KEY,
    taken_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_id          INTEGER,
    last_hash        TEXT,
    row_count        BIGINT,
    chain_ok         BOOLEAN,
    first_bad_id     INTEGER,
    taken_by         INTEGER,
    note             TEXT,
    prev_anchor_hash TEXT,
    anchor_hash      TEXT
);

CREATE OR REPLACE FUNCTION audit_anchor_digest(p_prev TEXT, a audit_anchors) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $f$
  SELECT encode(sha256(convert_to(concat_ws('|',
        COALESCE(p_prev, 'GENESIS'), a.id::text, extract(epoch FROM a.taken_at)::text,
        COALESCE(a.last_id::text, '<null>'), COALESCE(a.last_hash, '<null>'),
        COALESCE(a.row_count::text, '<null>'), COALESCE(a.chain_ok::text, '<null>'),
        COALESCE(a.first_bad_id::text, '<null>'), COALESCE(a.taken_by::text, '<null>'),
        COALESCE(a.note, '<null>')), 'UTF8')), 'hex')
$f$;

CREATE OR REPLACE FUNCTION audit_anchors_chain() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_anchors_chain'));
  NEW.id := nextval('audit_anchors_id_seq');
  NEW.taken_at := COALESCE(NEW.taken_at, now());
  SELECT anchor_hash INTO NEW.prev_anchor_hash FROM audit_anchors ORDER BY id DESC LIMIT 1;
  NEW.anchor_hash := audit_anchor_digest(NEW.prev_anchor_hash, NEW);
  RETURN NEW;
END $f$;

-- every anchor still matches its digest and its predecessor
CREATE OR REPLACE FUNCTION audit_anchors_verify()
RETURNS TABLE (checked BIGINT, first_bad_id INTEGER)
LANGUAGE sql STABLE AS $f$
  WITH r AS (
    SELECT a.id,
           (a.anchor_hash IS DISTINCT FROM audit_anchor_digest(a.prev_anchor_hash, a)
            OR a.prev_anchor_hash IS DISTINCT FROM lag(a.anchor_hash) OVER (ORDER BY a.id)) AS bad
      FROM audit_anchors a)
  SELECT count(*)::bigint, min(id) FILTER (WHERE bad) FROM r
$f$;

CREATE OR REPLACE FUNCTION audit_anchors_immutable() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  RAISE EXCEPTION 'audit_anchors is append-only';
END $f$;

DROP TRIGGER IF EXISTS trg_audit_anchors_chain ON audit_anchors;
CREATE TRIGGER trg_audit_anchors_chain BEFORE INSERT ON audit_anchors
  FOR EACH ROW EXECUTE FUNCTION audit_anchors_chain();
DROP TRIGGER IF EXISTS trg_audit_anchors_immutable ON audit_anchors;
CREATE TRIGGER trg_audit_anchors_immutable BEFORE UPDATE OR DELETE ON audit_anchors
  FOR EACH ROW EXECUTE FUNCTION audit_anchors_immutable();

-- periodic access reviews -------------------------------------------------------
CREATE TABLE IF NOT EXISTS access_reviews (
    id              SERIAL PRIMARY KEY,
    reviewed_by     INTEGER,
    reviewed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    users_count     INTEGER,
    note            TEXT,
    snapshot_sha256 TEXT
);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'complynex') THEN
    GRANT SELECT, INSERT, DELETE ON password_history TO complynex;
    GRANT USAGE, SELECT ON SEQUENCE password_history_id_seq TO complynex;
    GRANT SELECT, INSERT ON audit_anchors TO complynex;
    GRANT USAGE, SELECT ON SEQUENCE audit_anchors_id_seq TO complynex;
    GRANT SELECT, INSERT ON access_reviews TO complynex;
    GRANT USAGE, SELECT ON SEQUENCE access_reviews_id_seq TO complynex;
    REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs, audit_anchors FROM complynex;
  END IF;
END $$;

COMMIT;
