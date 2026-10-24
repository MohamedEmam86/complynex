-- Policy versioning: each version is its own policies row linked to the
-- previous one. Publishing a new version archives (read-only) the version it
-- supersedes; acknowledgements stay attached to the version that was acknowledged.
BEGIN;
ALTER TABLE policies ADD COLUMN IF NOT EXISTS previous_version_id INTEGER;
ALTER TABLE policies ADD COLUMN IF NOT EXISTS version_group_id INTEGER;
ALTER TABLE policies ADD COLUMN IF NOT EXISTS change_summary TEXT;
ALTER TABLE policies ADD COLUMN IF NOT EXISTS superseded_by_id INTEGER;
ALTER TABLE policies ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMP;
ALTER TABLE policies ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;
ALTER TABLE policies ADD COLUMN IF NOT EXISTS published_by INTEGER;
CREATE INDEX IF NOT EXISTS idx_policies_version_group ON policies(version_group_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON policies TO complynex;
COMMIT;
