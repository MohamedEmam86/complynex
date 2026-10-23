#!/bin/bash
# Reset the DEMO instance: empty its database back to reference data, clear its
# uploaded files and cache, load the fictional company again, restart it.
# Usage (root):  /var/www/complynex-demo/scripts/demo_data/reset.sh
set -euo pipefail
DEMO=$(cd "$(dirname "$0")/../.." && pwd)
[ -f "$DEMO/.demo_instance" ] || { echo "refused: $DEMO is not a demo instance"; exit 1; }
PY="$DEMO/venv/bin/python"
echo "== $(date '+%F %T') demo reset ($DEMO)"
systemctl stop complynex-demo 2>/dev/null || true
W="sudo -u complynex env -C $DEMO $PY scripts/demo_data/wipe_sql.py"
# foreign keys are not checked while tables are emptied and refilled (replica mode)
export PGOPTIONS='-c session_replication_role=replica'
$W wipe | sudo -u postgres PGOPTIONS="$PGOPTIONS" psql -d complynex_demo -v ON_ERROR_STOP=1 -q > /dev/null
# reference content (regulatory library, list sources, factors, settings) from the main instance
for t in $($W keep); do
  sudo -u postgres PGOPTIONS="$PGOPTIONS" bash -c "psql -d complynex_db -qc 'COPY \"$t\" TO STDOUT' | psql -d complynex_demo -qc 'COPY \"$t\" FROM STDIN'"
done
$W fix | sudo -u postgres PGOPTIONS="$PGOPTIONS" psql -d complynex_demo -v ON_ERROR_STOP=1 -q > /dev/null
unset PGOPTIONS
redis-cli -n 1 FLUSHDB > /dev/null || true
# uploaded files (never tracked code): uploads/ and ekyc_storage/ only
for d in uploads ekyc_storage; do
  [ -d "$DEMO/$d" ] && [ ! -L "$DEMO/$d" ] && find "$DEMO/$d" -mindepth 1 -delete 2>/dev/null || true
done
# academy course media is shared read-only with the main instance
[ -d /var/www/complynex/uploads/academy ] && ln -sfn /var/www/complynex/uploads/academy "$DEMO/uploads/academy"
sudo -u complynex env -C "$DEMO" "$PY" scripts/demo_data/seed.py
systemctl start complynex-demo 2>/dev/null || true
echo "== $(date '+%F %T') demo reset done"
