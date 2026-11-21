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
# Optional environment: PROFILE (default governance), QUOTA_MB (default 5120), WORKERS (default 1),
# CX_REV (commit to check out instead of the deployed one; deploy.sh moves it to each new main anyway).
#
# Creates, idempotently (re-running skips what exists and never overwrites .env or the database):
#   - /var/www/complynex-<name>: git worktree of the main repository, detached at the deployed commit
#   - .env from scripts/instance/env.template with fresh secrets (never printed), chmod 600
#   - PostgreSQL role + database complynex_<name>: schema = schema-only dump of the main database (the
#     migrations alone cannot build the schema from empty), no data; only its own role may connect
#   - uploads/ and logs/, marker file .cx_instance
#   - complynex-<name>.service (gunicorn on 127.0.0.1:<port>, small worker count, memory cap)
#   - complynex-<name>-backup.timer: daily pg_dump -Fc + uploads tar, 7 kept, dump verified with pg_restore -l
#   - a line in /etc/complynex/instances.list, so deploy.sh updates it after the main deploy
# It does NOT touch nginx, TLS or DNS. Remove an instance with remove_instance.sh.
# =============================================================================
set -euo pipefail
umask 027
NAME="${1:-}"; PORT="${2:-}"; RDB="${3:-}"; HOST="${4:-${NAME}.complynex.online}"
PROFILE="${PROFILE:-governance}"; QUOTA_MB="${QUOTA_MB:-5120}"; WORKERS="${WORKERS:-1}"
MAIN="${CX_MAIN:-/var/www/complynex}"
APPUSER=complynex
die() { echo "ERROR: $*" >&2; exit 2; }
log() { echo "[$(date +%T)] $*"; }

[ "$(id -u)" = 0 ] || die "run as root (sudo)"
[[ "$NAME" =~ ^[a-z][a-z0-9]{1,19}$ ]] || die "usage: $0 <name> <port> <redis_db> [host]  (name: a-z0-9, 2-20 chars)"
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] && [ "$PORT" != 8000 ] || die "port must be 1024-65535 and not 8000"
[[ "$RDB" =~ ^[0-9]+$ ]] && [ "$RDB" -ge 1 ] && [ "$RDB" -le 15 ] || die "redis_db must be 1-15 (0 is the main instance)"
[[ "$HOST" =~ ^[a-z0-9.-]+$ ]] || die "invalid host"
[[ "$QUOTA_MB" =~ ^[0-9]+$ ]] || die "QUOTA_MB must be a number"
[[ "$WORKERS" =~ ^[1-4]$ ]] || die "WORKERS must be 1-4"
[ -f "$MAIN/app.py" ] || die "main repository not found at $MAIN"
case "$NAME" in demo|main|db|test|www) die "reserved name: $NAME";; esac

INST="/var/www/complynex-$NAME"
DB="complynex_$NAME"; ROLE="complynex_$NAME"
UNIT="complynex-$NAME"
BK="/var/backups/complynex-$NAME"
LIST=/etc/complynex/instances.list
STATE="/root/.complynex_instances/$NAME"
G="git -C $MAIN -c safe.directory=*"

# port / redis db not taken by ANOTHER instance
mkdir -p /etc/complynex; touch "$LIST"; chmod 644 "$LIST"
if awk -v n="$NAME" -v p="$PORT" '$1!=n && $2==p {f=1} END {exit !f}' "$LIST"; then die "port $PORT is used by another instance"; fi
if awk -v n="$NAME" -v r="$RDB" '$1!=n && $3==r {f=1} END {exit !f}' "$LIST"; then die "redis db $RDB is used by another instance"; fi
if ss -ltnH "sport = :$PORT" | grep -q . && ! systemctl is-active --quiet "$UNIT"; then die "port $PORT is already in use"; fi

log "1/8 code: $INST (git worktree, detached)"
if [ ! -e "$INST/.git" ]; then
  [ ! -e "$INST" ] || die "$INST exists and is not a worktree"
  REV=${CX_REV:-$($G rev-parse HEAD)}     # CX_REV: another commit (testing a branch before deploy)
  $G worktree add -q --detach "$INST" "$REV"
fi
mkdir -p "$INST/logs" "$INST/uploads"

log "2/8 state and secrets"
mkdir -p /root/.complynex_instances; chmod 700 /root/.complynex_instances
touch "$STATE"; chmod 600 "$STATE"
get() { grep -E "^$1=" "$STATE" | cut -d= -f2- || true; }
put() { grep -q "^$1=" "$STATE" && sed -i "s|^$1=.*|$1=$2|" "$STATE" || echo "$1=$2" >> "$STATE"; }
rnd() { openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | head -c "${1:-32}"; }
[ -n "$(get DB_PASS)" ] || put DB_PASS "$(rnd 40)"
DBP="$(get DB_PASS)"

log "3/8 PostgreSQL role and database $DB"
PSQL="sudo -u postgres psql -qtA -v ON_ERROR_STOP=1"
if ! $PSQL -c "SELECT 1 FROM pg_roles WHERE rolname='$ROLE'" | grep -q 1; then
  $PSQL -c "CREATE ROLE $ROLE LOGIN PASSWORD '$DBP'" >/dev/null
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

log "4/8 .env (secrets generated here, never printed)"
if [ ! -f "$INST/.env" ]; then
  SK="$(rnd 64)"
  EK="$("$MAIN/venv/bin/python" -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
  sed -e "s|__SECRET_KEY__|$SK|" -e "s|__ENCRYPTION_KEY__|$EK|" -e "s|__DB_PASS__|$DBP|g" \
      -e "s|__DB__|$DB|g" -e "s|__ROLE__|$ROLE|g" -e "s|__REDIS_DB__|$RDB|" -e "s|__HOST__|$HOST|g" \
      -e "s|__PROFILE__|$PROFILE|" -e "s|__QUOTA_MB__|$QUOTA_MB|" -e "s|__INST__|$INST|" \
      "$INST/scripts/instance/env.template" > "$INST/.env.new"
  ! grep -q '__[A-Z_]*__' "$INST/.env.new" || { rm -f "$INST/.env.new"; die ".env template has unfilled placeholders"; }
  mv "$INST/.env.new" "$INST/.env"
  unset SK EK
fi
chmod 600 "$INST/.env"

log "5/8 files and marker"
[ -n "$(get CREATED)" ] || put CREATED "$(date -Is)"
cat > "$INST/.cx_instance" <<MARK
name=$NAME
port=$PORT
redis_db=$RDB
host=$HOST
profile=$PROFILE
database=$DB
created=$(get CREATED)
MARK
chown -R "$APPUSER:$APPUSER" "$INST"
chmod 750 "$INST/uploads" "$INST/logs"
# nginx serves /static straight from the folder: traversable folder, world-readable static files only
chmod 711 "$INST"
chmod -R a+rX "$INST/static"
chmod 644 "$INST/.cx_instance"
install -d -m 700 -o root -g root "$BK"

log "6/8 systemd: $UNIT.service and $UNIT-backup.timer"
# root runs the backup script: install it from the commit, not from a file the app user can write
git -C "$INST" -c safe.directory='*' show HEAD:scripts/instance/backup_instance.sh > /usr/local/sbin/complynex-instance-backup.new
chmod 755 /usr/local/sbin/complynex-instance-backup.new
mv /usr/local/sbin/complynex-instance-backup.new /usr/local/sbin/complynex-instance-backup
cat > "/etc/systemd/system/$UNIT.service" <<UNITF
[Unit]
Description=ComplyNex secondary instance $NAME ($PROFILE profile; own folder, database and Redis db)
After=network.target postgresql.service redis-server.service

[Service]
User=$APPUSER
Group=$APPUSER
WorkingDirectory=$INST
EnvironmentFile=$INST/.env
Environment="PATH=$MAIN/venv/bin"
ExecStart=$MAIN/venv/bin/gunicorn -c $INST/gunicorn.conf.py --workers $WORKERS --bind 127.0.0.1:$PORT --pid /run/$UNIT/gunicorn.pid "app:create_app()"
RuntimeDirectory=$UNIT
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
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
grep -v "^$NAME " "$LIST" > "$LIST.new" || true
echo "$NAME $PORT $RDB $HOST" >> "$LIST.new"
mv "$LIST.new" "$LIST"; chmod 644 "$LIST"

log "8/8 health check on 127.0.0.1:$PORT"
CODE=000
for i in $(seq 1 40); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" || true)
  [ "$CODE" = 200 ] && break; sleep 2
done
echo
echo "Instance $NAME: $INST  unit=$UNIT  port=$PORT  redis_db=$RDB  db=$DB  profile=$PROFILE  health=$CODE"
echo "Next: first superadmin (prints a one-time set-password link):"
echo "  sudo -u $APPUSER $MAIN/venv/bin/python $INST/scripts/instance/create_superadmin.py --email <address>"
echo "Then add the nginx server block for $HOST -> 127.0.0.1:$PORT (not done by this script)."
[ "$CODE" = 200 ] || { echo "WARNING: health check did not return 200 — journalctl -u $UNIT -n 80"; exit 1; }
