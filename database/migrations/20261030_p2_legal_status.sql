-- Phase 2: an order can be lifted (إنهاء أثر / رفع الحظر) while the record stays on the list for history.
-- legal_status = 'LIFTED' marks it; the hit is still shown, labelled, so the analyst sees it was lifted.
ALTER TABLE internal_blacklist ADD COLUMN IF NOT EXISTS legal_status TEXT;
ALTER TABLE internal_blacklist ADD COLUMN IF NOT EXISTS legal_status_note TEXT;
ALTER TABLE internal_blacklist ADD COLUMN IF NOT EXISTS legal_status_date TEXT;
