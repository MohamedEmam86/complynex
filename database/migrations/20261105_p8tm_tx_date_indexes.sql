-- Phase 8 TM review fix B3: live monitoring loads a customer's / a card's look-back with plain
-- ISO range comparisons on transactions.transaction_date (TEXT, C collation), served by these
-- indexes; open TM alerts are looked up by customer and rule code.
-- deploy.sh feeds this file to psql on stdin with ON_ERROR_STOP and no single-transaction
-- mode, so each statement runs on its own (as 20261030_p2b_watchlist_name_indexes.sql).
-- CREATE INDEX CONCURRENTLY cannot run inside a transaction block: no BEGIN/COMMIT here.
-- An earlier failed run leaves an INVALID index that IF NOT EXISTS would keep for ever:
-- drop such leftovers first (psql \gexec runs each generated statement on its own).
SET lock_timeout = '10s';

SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %I', c.relname)
  FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
 WHERE c.relname IN ('idx_tx_customer_date', 'idx_tx_pan_date', 'ix_tm_alerts_customer_code')
   AND NOT i.indisvalid
\gexec

-- idx_tx_customer_date already exists on the running databases (customer_id, transaction_date DESC).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tx_customer_date ON transactions (customer_id, transaction_date DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tx_pan_date ON transactions (counterparty_account, transaction_date)
    WHERE counterparty_account IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tm_alerts_customer_code ON tm_alerts (customer_id, rule_code);
