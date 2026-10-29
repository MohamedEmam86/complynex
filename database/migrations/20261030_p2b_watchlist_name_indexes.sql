-- Phase 2: the match profile looks up the same name on other lists by exact name
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_wl_full_name_eq ON screening_watchlist (full_name);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_wl_original_name_eq ON screening_watchlist (original_name);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_wl_full_name_ar_eq ON screening_watchlist (full_name_arabic);
