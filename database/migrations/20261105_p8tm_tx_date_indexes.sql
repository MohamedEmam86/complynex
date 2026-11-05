-- Phase 8 TM review fix B3: live monitoring loads a customer's / a card's look-back with plain
-- ISO range comparisons on transactions.transaction_date (TEXT, C collation), served by these
-- indexes. CREATE INDEX CONCURRENTLY cannot run inside a transaction block, so this file has no
-- BEGIN/COMMIT (as 20261030_p2b_watchlist_name_indexes.sql). idx_tx_customer_date already exists
-- on the running databases (customer_id, transaction_date DESC); IF NOT EXISTS keeps it.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tx_customer_date ON transactions (customer_id, transaction_date DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tx_pan_date ON transactions (counterparty_account, transaction_date)
    WHERE counterparty_account IS NOT NULL;
