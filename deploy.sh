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

# ---- quality gate (Phase 0): engine tests + Gold Set must not get worse -------------
# Runs on the new code before migrations, so a failure only needs a code rollback.
# Emergency override (logged): sudo QUALITY_GATE_OVERRIDE="reason" ./deploy.sh
echo "-- quality gate"
GATE_OK=1
T_OUT=$(timeout 300 sudo -u complynex env -C "$APP" PYTHONPATH="/opt/pytest_lib:$APP" "$APP/venv/bin/python" -m pytest -q   --noconftest -p no:cacheprovider tests/test_screening_intel 2>&1) && T_RC=0 || T_RC=$?
echo "$T_OUT" | tail -3
[ "$T_RC" = "0" ] || GATE_OK=0
G_OUT=$(timeout 300 sudo -u complynex bash -c "set -a; . $APP/.env; set +a; cd $APP && $APP/venv/bin/python scripts/gold_set_eval.py --gate" 2>&1)   && G_RC=0 || G_RC=$?
echo "$G_OUT" | grep -v -i -e warn -e faiss -e '^INFO' | tail -30 || true
[ "$G_RC" = "0" ] || GATE_OK=0
if [ "$GATE_OK" != "1" ]; then
  if [ -n "${QUALITY_GATE_OVERRIDE:-}" ]; then
    echo "QUALITY GATE FAILED but overridden: $QUALITY_GATE_OVERRIDE"
  else
    echo "QUALITY GATE FAILED — rolling code back to $PREV (nothing else changed)"
    $G reset --hard --quiet "$PREV"; exit 1
  fi
fi

for m in $MIGR; do
  echo "-- migration $m"
  if ! sudo -u postgres psql -d complynex_db -v ON_ERROR_STOP=1 -q < "$APP/$m"; then
    echo "MIGRATION FAILED — rolling code back to $PREV"; $G reset --hard --quiet "$PREV"; restart || true; exit 1
  fi
done

echo "-- guards"
for g in csp_guard endpoint_guard url_guard method_guard; do
  sudo -u complynex env -C "$APP" "$APP/venv/bin/python" "scripts/$g.py" 2>&1 | grep -v '^INFO' | tail -2 || true
done

echo "-- restart"
if restart; then
  echo "DEPLOYED OK: $PREV -> $TARGET  (health 200)"
  # post-deploy smoke check: known names through the live engine (report only — an
  # infrastructure problem is not fixed by rolling code back)
  echo "-- smoke check"
  S_OUT=$(sudo -u complynex bash -c "set -a; . $APP/.env; set +a; cd $APP && timeout 600 $APP/venv/bin/python scripts/post_deploy_smoke.py" 2>&1) \
    && S_RC=0 || S_RC=$?
  echo "$S_OUT" | grep -v -i -e warn -e faiss -e '^INFO' | tail -15 || true
  [ "$S_RC" = "0" ] || echo "WARNING: SMOKE CHECK FAILED — investigate before relying on screening results"
  # ratchet: only after a clean deploy (gate passed without override, smoke passed) the
  # baseline keeps the best of before / now per category — it can only get stricter
  if [ "$GATE_OK" = "1" ] && [ -z "${QUALITY_GATE_OVERRIDE:-}" ] && [ "$S_RC" = "0" ]; then
    timeout 300 sudo -u complynex bash -c "set -a; . $APP/.env; set +a; cd $APP && $APP/venv/bin/python scripts/gold_set_eval.py --ratchet" \
      2>&1 | grep -i -e 'baseline' || echo "WARNING: baseline ratchet did not run"
  else
    echo "baseline NOT changed (gate overridden or smoke check failed)"
  fi
  # The eKYC worker is a separate process: restart it so it runs the same code.
  systemctl restart complynex-ekyc-worker 2>/dev/null && echo "ekyc worker restarted" || true
  # Demo instance (same code in its own folder, own database of fictional data).
  # Its problems never roll back or block the main instance.
  DEMO=/var/www/complynex-demo
  if [ -f "$DEMO/.demo_instance" ]; then
    echo "-- demo instance"
    if git -C "$DEMO" -c safe.directory='*' checkout -q --detach "$TARGET"; then
      git -C "$DEMO" -c safe.directory='*' ls-files -z | (cd "$DEMO" && xargs -0 chown complynex:complynex) || true
      for m in $MIGR; do
        sudo -u postgres psql -d complynex_demo -v ON_ERROR_STOP=1 -q < "$APP/$m" || echo "WARNING: demo migration failed: $m"
      done
      systemctl restart complynex-demo || true
      systemctl is-enabled --quiet complynex-demo-ekyc-worker 2>/dev/null && systemctl restart complynex-demo-ekyc-worker || true
      for i in $(seq 1 30); do sleep 3; [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/health)" = 200 ] && break; done
      echo "demo health: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/health)"
    else
      echo "WARNING: demo code update failed (main instance is deployed and fine)"
    fi
  fi
else
  echo "UNHEALTHY after deploy — rolling code back to $PREV"
  $G reset --hard --quiet "$PREV"
  if restart; then echo "ROLLED BACK — site is up on the previous version."; else echo "ROLLBACK RESTART FAILED — check: journalctl -u complynex -n 80"; fi
  [ -n "$MIGR" ] && echo "NOTE: migrations already applied are not reversed (they are additive). Schema backup: schema_predeploy_$TS.sql"
  exit 1
fi
