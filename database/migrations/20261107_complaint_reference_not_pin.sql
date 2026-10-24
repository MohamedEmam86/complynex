-- Consumer complaints: the unified case registry used the customer's secret
-- tracking PIN as the staff-facing reference. Replace it with CP-<id>.
BEGIN;
UPDATE cases SET reference = 'CP-' || source_record_id
 WHERE source_table = 'consumer_complaints'
   AND reference IS DISTINCT FROM 'CP-' || source_record_id;
COMMIT;
