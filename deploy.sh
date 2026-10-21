#!/bin/bash
# =============================================================================
# ComplyNex deploy — bring a reviewed branch from GitHub onto the live server.
# Usage:  sudo /var/www/complynex/deploy.sh            (deploys origin/main)
#         sudo /var/www/complynex/deploy.sh <branch>   (deploys another branch)
# Steps: schema backup -> fast-forward to origin/<branch> -> new SQL migrations ->
#        guards -> restart -> health check -> automatic code rollback if unhealthy.
# =============================================================================
set -euo pipefail
APP=/var/www/complynex
BR="${1:-main}"
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$APP/deploy_logs" /var/backups/complynex
LOG="$APP/deploy_logs/deploy_$TS.log"
exec > >(tee -a "$LOG") 2>&1
G="git -C $APP -c safe.directory=$APP"
health() { curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health; }
restart() {
  systemctl restart complynex
  for i in $(seq 1 40); do sleep 3; [ "$(health)" = 200 ] && return 0; done
  return 1
}

echo "== ComplyNex deploy $TS  branch=$BR"
if ! $G diff --quiet || ! $G diff --cached --quiet; then
  echo "STOP: the server has uncommitted changes to tracked files:"; $G status --short | grep -v '^??' | head -20
  echo "Commit or discard them first, so nothing is lost."; exit 1
fi
PREV=$($G rev-parse HEAD)
$G fetch --quiet origin
TARGET=$($G rev-parse "origin/$BR")
if [ "$PREV" = "$TARGET" ]; then echo "Already up to date ($PREV)."; exit 0; fi
echo "-- changes:"; $G log --oneline "$PREV..$TARGET" | head -30
MIGR=$($G diff --name-only --diff-filter=A "$PREV" "$TARGET" -- 'database/migrations/*.sql' | sort || true)

echo "-- schema backup"
sudo -u postgres pg_dump -d complynex_db --schema-only > "/var/backups/complynex/schema_predeploy_$TS.sql"

$G merge --ff-only --quiet "$TARGET" || { echo "STOP: branch cannot fast-forward from the server version."; exit 1; }
$G ls-files -z | (cd "$APP" && xargs -0 chown complynex:complynex) || true

for m in $MIGR; do
  echo "-- migration $m"
  if ! sudo -u postgres psql -d complynex_db -v ON_ERROR_STOP=1 -q < "$APP/$m"; then
    echo "MIGRATION FAILED — rolling code back to $PREV"; $G reset --hard --quiet "$PREV"; restart || true; exit 1
  fi
done

echo "-- guards"
for g in csp_guard endpoint_guard url_guard method_guard; do
  sudo -u complynex env -C "$APP" "$APP/venv/bin/python" "scripts/$g.py" 2>&1 | grep -v '^INFO' | tail -2
done

echo "-- restart"
if restart; then
  echo "DEPLOYED OK: $PREV -> $TARGET  (health 200)"
else
  echo "UNHEALTHY after deploy — rolling code back to $PREV"
  $G reset --hard --quiet "$PREV"
  if restart; then echo "ROLLED BACK — site is up on the previous version."; else echo "ROLLBACK RESTART FAILED — check: journalctl -u complynex -n 80"; fi
  [ -n "$MIGR" ] && echo "NOTE: migrations already applied are not reversed (they are additive). Schema backup: schema_predeploy_$TS.sql"
  exit 1
fi
