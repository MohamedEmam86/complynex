#!/bin/bash
# =============================================================================
# ComplyNex — remove a SECONDARY instance created by create_instance.sh.
#
#   sudo remove_instance.sh <name> --confirm <name> [--purge-backups]
#
# Takes a last database dump into /var/backups/complynex-<name>/ (kept unless --purge-backups), then stops
# and deletes its systemd units, its database, role and Redis db, its folder (git worktree), its line in
# /etc/complynex/instances.list and its state file. Never touches the main instance, nginx or TLS.
# =============================================================================
set -euo pipefail
NAME="${1:-}"; [ "${2:-}" = "--confirm" ] && [ "${3:-}" = "$NAME" ] || { echo "usage: $0 <name> --confirm <name> [--purge-backups]"; exit 2; }
PURGE=0; if [ "${4:-}" = "--purge-backups" ]; then PURGE=1; fi
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 2; }
[[ "$NAME" =~ ^[a-z][a-z0-9]{1,19}$ ]] || { echo "invalid name"; exit 2; }
MAIN="${CX_MAIN:-/var/www/complynex}"
INST="/var/www/complynex-$NAME"; DB="complynex_$NAME"; ROLE="complynex_$NAME"; UNIT="complynex-$NAME"
BK="/var/backups/complynex-$NAME"; LIST=/etc/complynex/instances.list
[ "$INST" != "$MAIN" ] || exit 2
if [ -e "$INST" ] && [ ! -f "$INST/.cx_instance" ]; then echo "$INST has no .cx_instance marker: refusing"; exit 2; fi

if sudo -u postgres psql -qtAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
  if [ "$PURGE" = 0 ]; then
    install -d -m 700 "$BK"
    sudo -u postgres pg_dump -Fc -d "$DB" > "$BK/final_$(date +%Y%m%d_%H%M%S).dump"
    echo "final dump kept in $BK"
  fi
fi
systemctl disable --now "$UNIT-backup.timer" "$UNIT.service" 2>/dev/null || true
rm -f "/etc/systemd/system/$UNIT.service" "/etc/systemd/system/$UNIT-backup.service" "/etc/systemd/system/$UNIT-backup.timer"
systemctl daemon-reload
systemctl reset-failed "$UNIT.service" "$UNIT-backup.service" 2>/dev/null || true
sudo -u postgres dropdb --if-exists "$DB"
# its Redis database (never 0, the main instance's)
RDB=$(sed -n 's/^redis_db=//p' "$INST/.cx_instance" 2>/dev/null || true)
if [[ "$RDB" =~ ^[0-9]+$ ]] && [ "$RDB" -ge 1 ] && [ "$RDB" -le 15 ]; then redis-cli -n "$RDB" FLUSHDB >/dev/null || true; fi
sudo -u postgres psql -qc "DROP ROLE IF EXISTS $ROLE"
if [ -e "$INST/.git" ]; then git -C "$MAIN" -c safe.directory='*' worktree remove --force "$INST"; fi
rm -rf "$INST"
git -C "$MAIN" -c safe.directory='*' worktree prune
if [ -f "$LIST" ]; then grep -v "^$NAME " "$LIST" > "$LIST.new" || true; mv "$LIST.new" "$LIST"; chmod 644 "$LIST"; fi
rm -f "/root/.complynex_instances/$NAME"
# the shared backup script goes with the last instance
if [ ! -s "$LIST" ]; then rm -f /usr/local/sbin/complynex-instance-backup; fi
if [ "$PURGE" = 1 ]; then rm -rf "$BK"; fi
echo "instance $NAME removed"
