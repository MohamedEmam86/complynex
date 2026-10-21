-- Fast, spelling-tolerant recall for the internal lists: one normalised search
-- text per record (Arabic hamza / taa marbuta / alef maqsura unified, lower
-- case, primary + transliterated name + aliases), kept current by Postgres as
-- a generated column and indexed with trigrams so LIKE '%element%' is indexed.
BEGIN;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE OR REPLACE FUNCTION cx_name_search(o text, f text, a text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT translate(lower(coalesce(o, '') || ' ' || coalesce(f, '') || ' ' || coalesce(a, '')),
                   'أإآٱةى', 'اااايهي')
$$;
ALTER TABLE internal_blacklist ADD COLUMN IF NOT EXISTS name_search text
  GENERATED ALWAYS AS (cx_name_search(original_name, full_name, aliases)) STORED;
ALTER TABLE internal_pep ADD COLUMN IF NOT EXISTS name_search text
  GENERATED ALWAYS AS (cx_name_search(original_name, full_name, aliases)) STORED;
CREATE INDEX IF NOT EXISTS idx_internal_blacklist_name_search_trgm
  ON internal_blacklist USING gin (name_search gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_internal_pep_name_search_trgm
  ON internal_pep USING gin (name_search gin_trgm_ops);
GRANT EXECUTE ON FUNCTION cx_name_search(text, text, text) TO complynex;
COMMIT;
