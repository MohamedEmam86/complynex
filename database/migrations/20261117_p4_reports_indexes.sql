-- P4-10 / G11 (screening work and list reports): indexes for the per-user and per-period queries.
-- Small tables today; these keep the reports fast as history grows. Idempotent.
CREATE INDEX IF NOT EXISTS idx_hist_initiated_date ON screening_history (initiated_by, screening_date);
CREATE INDEX IF NOT EXISTS idx_hist_lower_name ON screening_history (lower(btrim(entity_name)), id);
CREATE INDEX IF NOT EXISTS idx_queue_resolved_by ON screening_queue (resolved_by, resolved_date);
CREATE INDEX IF NOT EXISTS idx_queue_created_at ON screening_queue (created_at);
CREATE INDEX IF NOT EXISTS idx_queue_history_id ON screening_queue (screening_history_id);
CREATE INDEX IF NOT EXISTS idx_scr_clearance_requested_by ON screening_clearance_requests (requested_by, requested_at);
CREATE INDEX IF NOT EXISTS idx_scr_clearance_decided_by ON screening_clearance_requests (decided_by, decided_at);
CREATE INDEX IF NOT EXISTS idx_evidence_packs_by ON screening_evidence_packs (generated_by, generated_at);
