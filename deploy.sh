#!/bin/bash
# =============================================================================
# ComplyNex deploy — bring a reviewed branch from GitHub onto the live server.
# Usage:  sudo /var/www/complynex/deploy.sh            (deploys origin/main)
#         sudo /var/www/complynex/deploy.sh <branch>   (deploys another branch)
#         sudo /var/www/complynex/deploy.sh --instances-only  (secondary instances to the deployed commit)
# Steps: schema backup -> fast-forward to origin/<branch> -> new SQL migrations ->
#        guards -> restart -> health check -> automatic code rollback if unhealthy ->
#        secondary instances (/etc/complynex/instances.list, see scripts/instance/).
# =============================================================================
set -euo pipefail
APP=/var/www/complynex
BR="${1:-main}"
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$APP/deploy_logs" /var/backups/complynex
LOG="$APP/deploy_logs/deploy_$TS.log"
exec > >(tee -a "$LOG") 2>&1
G="git -C $APP -c safe.directory=$APP -c core.hooksPath=/dev/null"
health() { curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health; }
restart() {
  systemctl restart complynex
  for i in $(seq 1 40); do sleep 3; [ "$(health)" = 200 ] && return 0; done
  return 1
}
# A secondary instance (scripts/instance/create_instance.sh): same code in its own folder (git worktree, code
# owned by root), own system user and database. Updated only after the main deploy succeeded; a failure here
# never rolls back the main instance. Git runs as root there: always with an explicit git dir / work tree,
# no hooks, and only after the folder's gitdir pointer was checked.
update_instance() {
  local n="$1" port="$2" dir="/var/www/complynex-$1" db="complynex_$1" rc=0 code m old migr
  local wt="$APP/.git/worktrees/complynex-$1"
  echo "-- instance $n ($dir, port $port)"
  [[ "$n" =~ ^[a-z][a-z0-9]{1,19}$ ]] || { echo "INSTANCE $n: invalid name in the list"; return 1; }
  [ -f "$dir/.cx_instance" ] || { echo "INSTANCE $n: $dir/.cx_instance missing"; return 1; }
  [ -d "$wt" ] || { echo "INSTANCE $n: worktree metadata $wt missing"; return 1; }
  if [ -L "$dir/.git" ] || [ "$(cat "$dir/.git" 2>/dev/null)" != "gitdir: $wt" ]; then
    echo "INSTANCE $n: REFUSED — $dir/.git is not the expected gitdir pointer (tampered?)"; return 1
  fi
  chown -h root:root "$dir/.git"; chmod 644 "$dir/.git"
  local ig="git --git-dir=$wt --work-tree=$dir -c safe.directory=* -c core.hooksPath=/dev/null -c core.fsmonitor=false"
  if [ -n "$($ig status --porcelain --untracked-files=no 2>&1)" ]; then
    echo "!!!!! INSTANCE $n: REFUSED — tracked files were changed in $dir:"; $ig status --short --untracked-files=no | head -10
    return 1
  fi
  old=$($ig rev-parse HEAD) || { echo "INSTANCE $n: cannot read its commit"; return 1; }
  # its own migrations: everything added between ITS commit and the target (it may have missed deploys)
  migr=$($G diff --name-only --diff-filter=A "$old" "$TARGET" -- 'database/migrations/*.sql' | sort || true)
  if [ "$old" = "$TARGET" ] && [ -z "$migr" ] && [ "${FORCE_RESTART:-0}" != 1 ]; then
    echo "   instance $n up to date ($TARGET)"; return 0
  fi
  $ig checkout -q --detach "$TARGET" || { echo "INSTANCE $n: code update failed"; return 1; }
  # root runs the backup script: install it from the main repository's commit, not from a file in a folder
  { $G show "$TARGET:scripts/instance/backup_instance.sh" > /usr/local/sbin/complynex-instance-backup.new && \
    chmod 755 /usr/local/sbin/complynex-instance-backup.new && \
    mv /usr/local/sbin/complynex-instance-backup.new /usr/local/sbin/complynex-instance-backup; } || rc=1
  for m in $migr; do
    echo "   migration $m"
    $G show "$TARGET:$m" | sudo -u postgres psql -d "$db" -v ON_ERROR_STOP=1 -q || { echo "INSTANCE $n: MIGRATION FAILED: $m"; rc=1; }
  done
  systemctl restart "complynex-$n" || { echo "INSTANCE $n: restart failed"; return 1; }
  code=000
  for i in $(seq 1 30); do
    sleep 2; code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/health" || true)
    [ "$code" = 200 ] && break
  done
  echo "   instance $n health: $code"
  [ "$code" = 200 ] || { echo "INSTANCE $n: UNHEALTHY — journalctl -u complynex-$n -n 80"; return 1; }
  return $rc
}
# Every instance of the root-owned list. Failures are reported loudly; the return code says whether any failed.
run_instances() {
  local list=/etc/complynex/instances.list failed="" iname iport _rest
  [ -s "$list" ] || return 0
  if [ "$(stat -c '%u' "$list")" != 0 ] || [ -n "$(find "$list" -perm /022)" ]; then
    echo "WARNING: $list is not root-owned / is writable by others — secondary instances NOT updated"; return 1
  fi
  while read -r iname iport _rest; do
    case "$iname" in ''|\#*) continue;; esac
    update_instance "$iname" "$iport" || failed="$failed $iname"
  done < "$list"
  if [ -n "$failed" ]; then
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "WARNING: SECONDARY INSTANCE UPDATE FAILED:$failed"
    echo "         The main instance is not affected (not rolled back). Fix the instance(s) above, then:"
    echo "         sudo $APP/deploy.sh --instances-only"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    return 1
  fi
  echo "secondary instances up to date"
}

if [ "$BR" = "--instances-only" ]; then
  # bring every secondary instance to the commit the main instance runs now (no main deploy)
  echo "== ComplyNex secondary instances $TS"
  TARGET=$($G rev-parse HEAD)
  run_instances && exit 0 || exit 1
fi

echo "== ComplyNex deploy $TS  branch=$BR"
if ! $G diff --quiet || ! $G diff --cached --quiet; then
  echo "STOP: the server has uncommitted changes to tracked files:"; $G status --short | grep -v '^??' | head -20
  echo "Commit or discard them first, so nothing is lost."; exit 1
fi
PREV=$($G rev-parse HEAD)
$G fetch --quiet origin
TARGET=$($G rev-parse "origin/$BR")
if [ "$PREV" = "$TARGET" ]; then echo "Already up to date ($PREV)."; run_instances || true; exit 0; fi
echo "-- changes:"; $G log --oneline "$PREV..$TARGET" | head -30
MIGR=$($G diff --name-only --diff-filter=A "$PREV" "$TARGET" -- 'database/migrations/*.sql' | sort || true)

echo "-- schema backup"
sudo -u postgres pg_dump -d complynex_db --schema-only > "/var/backups/complynex/schema_predeploy_$TS.sql"

$G merge --ff-only --quiet "$TARGET" || { echo "STOP: branch cannot fast-forward from the server version."; exit 1; }
$G ls-files -z | (cd "$APP" && xargs -0 chown -h complynex:complynex) || true   # -h: never follow a symlink

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
  # Secondary instances: each listed one gets the new code, its missing migrations and a restart.
  run_instances || true
else
  echo "UNHEALTHY after deploy — rolling code back to $PREV"
  $G reset --hard --quiet "$PREV"
  if restart; then echo "ROLLED BACK — site is up on the previous version."; else echo "ROLLBACK RESTART FAILED — check: journalctl -u complynex -n 80"; fi
  [ -n "$MIGR" ] && echo "NOTE: migrations already applied are not reversed (they are additive). Schema backup: schema_predeploy_$TS.sql"
  exit 1
fi
