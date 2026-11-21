#!/bin/bash
# =============================================================================
# ComplyNex — create (or complete) a SECONDARY instance on this server.
#
#   sudo /var/www/complynex/scripts/instance/create_instance.sh <name> <port> <redis_db> [host]
#
#   name      lower-case letters/digits (2-20), e.g. "acme"   -> /var/www/complynex-acme
#   port      local port for its gunicorn (127.0.0.1 only), e.g. 8010
#   redis_db  Redis database number 1-15 not used by another instance (the main one uses 0)
#   host      public host name (default <name>.complynex.online) -> APP_URL / MAIN_HOSTS
#
# Optional environment: PROFILE (default governance; must be a profile of utils/instance_profile.py),
# QUOTA_MB (default 5120), WORKERS (default 1), CX_REV (commit to check out instead of the deployed one;
# deploy.sh moves it to each new main anyway), HARDEN_MAIN (default 1: the main instance's data folders
# uploads/ backups/ attachments/ deploy_logs/ ekyc_storage/ logs/ lose their "other" permissions).
#
# Creates, idempotently (re-running skips what exists and never overwrites .env or the database):
#   - system user cx-<name> (no login shell): runs the instance, owns only .env, uploads/, logs/
#   - /var/www/complynex-<name>: git worktree of the main repository (code owned by root, read-only)
#   - .env from scripts/instance/env.template with fresh secrets (never printed or put on a command line)
#   - PostgreSQL role + database complynex_<name>: schema = schema-only dump of the main database (the
#     migrations alone cannot build the schema from empty), no data; only its own role may connect
#   - complynex-<name>.service: gunicorn on 127.0.0.1:<port>, sandboxed (the main instance's folder is
#     invisible except the shared virtualenv, read-only), memory cap
#   - complynex-<name>-backup.timer: daily pg_dump -Fc + uploads tar, 7 kept, dump verified with pg_restore -l
#   - a line in /etc/complynex/instances.list (root-owned), so deploy.sh updates it after the main deploy
# It does NOT touch nginx, TLS or DNS. Remove an instance with remove_instance.sh.
# =============================================================================
set -euo pipefail
umask 022
NAME="${1:-}"; PORT="${2:-}"; RDB="${3:-}"; HOST="${4:-${NAME}.complynex.online}"
PROFILE="${PROFILE:-governance}"; QUOTA_MB="${QUOTA_MB:-5120}"; WORKERS="${WORKERS:-1}"
MAIN="${CX_MAIN:-/var/www/complynex}"
HERE="$(cd "$(dirname "$0")" && pwd)"
RESERVED="demo main db test www root admin postgres complynex"
die() { echo "ERROR: $*" >&2; exit 2; }
log() { echo "[$(date +%T)] $*"; }

[[ "$NAME" =~ ^[a-z][a-z0-9]{1,19}$ ]] || die "usage: $0 <name> <port> <redis_db> [host]  (name: a-z0-9, 2-20 chars)"
for r in $RESERVED; do [ "$NAME" != "$r" ] || die "reserved name: $NAME"; done
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] && [ "$PORT" != 8000 ] || die "port must be 1024-65535 and not 8000"
[[ "$RDB" =~ ^[0-9]+$ ]] && [ "$RDB" -ge 1 ] && [ "$RDB" -le 15 ] || die "redis_db must be 1-15 (0 is the main instance)"
[[ "$HOST" =~ ^[a-z0-9.-]+$ ]] || die "invalid host"
[[ "$QUOTA_MB" =~ ^[0-9]+$ ]] || die "QUOTA_MB must be a number"
[[ "$WORKERS" =~ ^[1-4]$ ]] || die "WORKERS must be 1-4"
# the profile must exist in the code (an unknown profile would refuse to start)
python3 - "$HERE/../../utils/instance_profile.py" "$PROFILE" <<'PY' || die "unknown PROFILE: $PROFILE"
import ast, sys
tree = ast.parse(open(sys.argv[1], encoding='utf-8').read())
keys = [k.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'PROFILES' for t in n.targets)
        for k in n.value.keys]
sys.exit(0 if sys.argv[2] in keys else 1)
PY
[ "$(id -u)" = 0 ] || die "run as root (sudo)"
[ -f "$MAIN/app.py" ] || die "main repository not found at $MAIN"

INST="/var/www/complynex-$NAME"
DB="complynex_$NAME"; ROLE="complynex_$NAME"; USR="cx-$NAME"
UNIT="complynex-$NAME"
BK="/var/backups/complynex-$NAME"
LIST=/etc/complynex/instances.list
STATE="/root/.complynex_instances/$NAME"
G="git -C $MAIN -c safe.directory=* -c core.hooksPath=/dev/null"
WTGIT="$MAIN/.git/worktrees/complynex-$NAME"
igit() { git --git-dir="$WTGIT" --work-tree="$INST" -c safe.directory='*' -c core.hooksPath=/dev/null -c core.fsmonitor=false "$@"; }

# port / redis db not taken by ANOTHER instance
install -d -m 755 -o root -g root /etc/complynex; [ -f "$LIST" ] || install -m 644 -o root -g root /dev/null "$LIST"
if awk -v n="$NAME" -v p="$PORT" '$1!=n && $2==p {f=1} END {exit !f}' "$LIST"; then die "port $PORT is used by another instance"; fi
if awk -v n="$NAME" -v r="$RDB" '$1!=n && $3==r {f=1} END {exit !f}' "$LIST"; then die "redis db $RDB is used by another instance"; fi
if ss -ltnH "sport = :$PORT" | grep -q . && ! systemctl is-active --quiet "$UNIT"; then die "port $PORT is already in use"; fi

log "1/8 system user $USR"
if ! id "$USR" >/dev/null 2>&1; then
  useradd --system --user-group --no-create-home --home-dir "$INST" --shell /usr/sbin/nologin "$USR"
fi

# the main instance's data folders were world-readable (nginx serves only static/): instance users must not
# read them, also outside their sandbox (HARDEN_MAIN=0 skips this)
if [ "${HARDEN_MAIN:-1}" = 1 ]; then
  for d in uploads backups attachments deploy_logs ekyc_storage logs; do
    [ -d "$MAIN/$d" ] && [ ! -L "$MAIN/$d" ] && chmod o-rwx "$MAIN/$d"
  done
  [ -f "$MAIN/.env" ] && chmod o-rwx "$MAIN/.env"
fi

log "2/8 code: $INST (git worktree, detached, owned by root)"
if [ ! -e "$INST/.git" ]; then
  [ ! -e "$INST" ] || die "$INST exists and is not a worktree"
  REV=${CX_REV:-$($G rev-parse HEAD)}
  $G worktree add -q --detach "$INST" "$REV"
fi
[ -d "$WTGIT" ] || die "worktree metadata $WTGIT missing (worktree registered under another name?)"
# the gitdir pointer: root-owned, exact content (git runs as root in this folder)
printf 'gitdir: %s\n' "$WTGIT" > "$INST/.git"; chown root:root "$INST/.git"; chmod 644 "$INST/.git"
REV=$(igit rev-parse HEAD)
chown "root:$USR" "$INST"; chmod 751 "$INST"        # its user lists it; others traverse only (nginx: static/)
install -d -m 750 -o "$USR" -g "$USR" "$INST/logs" "$INST/uploads"

log "3/8 state and secrets"
install -d -m 700 -o root -g root /root/.complynex_instances
[ -f "$STATE" ] || install -m 600 -o root -g root /dev/null "$STATE"
get() { grep -E "^$1=" "$STATE" | cut -d= -f2- || true; }
put() { { grep -v "^$1=" "$STATE" || true; echo "$1=$2"; } > "$STATE.new"; chmod 600 "$STATE.new"; mv "$STATE.new" "$STATE"; }
rnd() { openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | head -c "${1:-32}"; }
[ -n "$(get DB_PASS)" ] || put DB_PASS "$(rnd 40)"

log "4/8 PostgreSQL role and database $DB"
PSQL="sudo -u postgres psql -qtA -v ON_ERROR_STOP=1"
if ! $PSQL -c "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'" | grep -q 1; then
  # the password goes through stdin, never on a command line
  { printf '\\set pw %s\n' "$(get DB_PASS)"; echo "CREATE ROLE $ROLE LOGIN PASSWORD :'pw';"; } | $PSQL >/dev/null
fi
if ! $PSQL -c "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
  sudo -u postgres createdb "$DB"
  $PSQL -c "REVOKE CONNECT, TEMPORARY ON DATABASE $DB FROM PUBLIC" >/dev/null
  # schema only, no data: everything the main instance has now; later migrations come through deploy.sh
  if ! sudo -u postgres pg_dump --schema-only --no-owner --no-privileges -d complynex_db \
       | sudo -u postgres psql -q -v ON_ERROR_STOP=1 -d "$DB" >/dev/null; then
    sudo -u postgres dropdb "$DB"; die "schema copy failed (database removed, nothing else changed)"
  fi
  put SCHEMA_FROM "complynex_db@$(date +%F)"
fi
$PSQL -c "GRANT CONNECT, TEMPORARY ON DATABASE $DB TO $ROLE" >/dev/null
sudo -u postgres psql -q -v ON_ERROR_STOP=1 -d "$DB" >/dev/null <<SQL
GRANT USAGE ON SCHEMA public TO $ROLE;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $ROLE;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO $ROLE;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO $ROLE;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $ROLE;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO $ROLE;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO $ROLE;
DO \$\$ BEGIN
  IF to_regclass('public.audit_logs') IS NOT NULL THEN
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM $ROLE';
  END IF;
END \$\$;
SQL

log "5/8 .env (secrets generated here, never printed)"
if [ ! -f "$INST/.env" ]; then
  # secrets reach the template through the environment of one python process, not its arguments
  CX_SK="$(rnd 64)" CX_DBP="$(get DB_PASS)" CX_TEMPLATE="$($G show "$REV:scripts/instance/env.template")" \
  CX_VALUES="DB=$DB ROLE=$ROLE REDIS_DB=$RDB HOST=$HOST PROFILE=$PROFILE QUOTA_MB=$QUOTA_MB INST=$INST" \
  "$MAIN/venv/bin/python" - "$INST/.env.new" <<'PY'
import os, re, sys
from cryptography.fernet import Fernet
vals = dict(kv.split('=', 1) for kv in os.environ['CX_VALUES'].split())
vals.update(SECRET_KEY=os.environ['CX_SK'], DB_PASS=os.environ['CX_DBP'], ENCRYPTION_KEY=Fernet.generate_key().decode())
out = re.sub(r'__([A-Z_]+)__', lambda m: vals[m.group(1)], os.environ['CX_TEMPLATE'])
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write(out)
PY
  mv "$INST/.env.new" "$INST/.env"
fi
chown "$USR:$USR" "$INST/.env"; chmod 600 "$INST/.env"
# deployment fingerprint (system_fingerprint.py writes it on first start, but the folder is read-only for the app)
if [ ! -s "$INST/.fingerprint" ]; then
  rm -f "$INST/.fingerprint"
  (cd "$INST" && "$MAIN/venv/bin/python" -c 'from dotenv import load_dotenv; load_dotenv(".env"); import system_fingerprint as s; s.verify_on_startup()') >/dev/null 2>&1
fi
[ -s "$INST/.fingerprint" ] || die "could not write $INST/.fingerprint"
chown "$USR:$USR" "$INST/.fingerprint"; chmod 400 "$INST/.fingerprint"

log "6/8 marker, backups, systemd units"
[ -n "$(get CREATED)" ] || put CREATED "$(date -Is)"
cat > "$INST/.cx_instance" <<MARK
name=$NAME
port=$PORT
redis_db=$RDB
host=$HOST
profile=$PROFILE
database=$DB
user=$USR
created=$(get CREATED)
MARK
chown root:root "$INST/.cx_instance"; chmod 644 "$INST/.cx_instance"
install -d -m 700 -o root -g root "$BK"
# root runs the backup script: install it from the MAIN repository's commit, never from the instance folder
$G show "$REV:scripts/instance/backup_instance.sh" > /usr/local/sbin/complynex-instance-backup.new
chmod 755 /usr/local/sbin/complynex-instance-backup.new
mv /usr/local/sbin/complynex-instance-backup.new /usr/local/sbin/complynex-instance-backup
cat > "/etc/systemd/system/$UNIT.service" <<UNITF
[Unit]
Description=ComplyNex secondary instance $NAME ($PROFILE profile; own user, folder, database and Redis db)
After=network.target postgresql.service redis-server.service

[Service]
User=$USR
Group=$USR
WorkingDirectory=$INST
EnvironmentFile=$INST/.env
Environment="PATH=$MAIN/venv/bin:/usr/bin:/bin" "HOME=/run/$UNIT" "XDG_CACHE_HOME=/run/$UNIT/.cache"
ExecStart=$MAIN/venv/bin/gunicorn -c $INST/gunicorn.conf.py --workers $WORKERS --bind 127.0.0.1:$PORT --control-socket /run/$UNIT/gunicorn.ctl "app:create_app()"
RuntimeDirectory=$UNIT
Restart=always
RestartSec=5
# sandbox: nothing of /var/www but its own folder (read-only; uploads, logs writable) and the shared
# virtualenv (read-only); no backups, no root home, no other instance
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
TemporaryFileSystem=/var/www:ro
BindReadOnlyPaths=$MAIN/venv $INST
BindPaths=$INST/uploads $INST/logs
InaccessiblePaths=-/var/backups -/etc/complynex -/root
MemoryHigh=450M
MemoryMax=600M

[Install]
WantedBy=multi-user.target
UNITF
cat > "/etc/systemd/system/$UNIT-backup.service" <<UNITF
[Unit]
Description=ComplyNex secondary instance $NAME: daily backup (database + uploads, 7 kept)
After=postgresql.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/complynex-instance-backup $NAME
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=6
UNITF
cat > "/etc/systemd/system/$UNIT-backup.timer" <<UNITF
[Unit]
Description=ComplyNex secondary instance $NAME: daily backup

[Timer]
OnCalendar=*-*-* 01:37:00
RandomizedDelaySec=20m
Persistent=true

[Install]
WantedBy=timers.target
UNITF
systemctl daemon-reload
systemctl enable --quiet "$UNIT.service" "$UNIT-backup.timer"
systemctl restart "$UNIT.service"
systemctl start "$UNIT-backup.timer"

log "7/8 deploy list: $LIST"
{ grep -v "^$NAME " "$LIST" || true; echo "$NAME $PORT $RDB $HOST"; } > "$LIST.new"
chown root:root "$LIST.new"; chmod 644 "$LIST.new"; mv "$LIST.new" "$LIST"

log "8/8 health check on 127.0.0.1:$PORT"
CODE=000
for i in $(seq 1 40); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" || true)
  [ "$CODE" = 200 ] && break; sleep 2
done
echo
echo "Instance $NAME: $INST  user=$USR  unit=$UNIT  port=$PORT  redis_db=$RDB  db=$DB  profile=$PROFILE  health=$CODE"
echo "Next: first superadmin (prints a one-time set-password link):"
echo "  sudo -u $USR $MAIN/venv/bin/python $INST/scripts/instance/create_superadmin.py --email <address>"
echo "Then add the nginx server block for $HOST -> 127.0.0.1:$PORT (not done by this script)."
[ "$CODE" = 200 ] || { echo "WARNING: health check did not return 200 — journalctl -u $UNIT -n 80"; exit 1; }
