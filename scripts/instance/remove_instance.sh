#!/bin/bash
# =============================================================================
# ComplyNex — remove a SECONDARY instance created by create_instance.sh.
#
#   sudo remove_instance.sh <name> --confirm <name> [--purge-backups]
#
# Only an instance that is listed in the root-owned /etc/complynex/instances.list AND has its
# /var/www/complynex-<name>/.cx_instance marker is removed; reserved names and any database other than
# complynex_<name> (never complynex_db) are refused. Takes a last database dump into
# /var/backups/complynex-<name>/ (kept unless --purge-backups), then deletes its systemd units, database,
# role, Redis db (number taken from the list), system user, folder (git worktree), list line and state file.
# Never touches the main instance, nginx or TLS.
# =============================================================================
set -euo pipefail
die() { echo "REFUSED: $*" >&2; exit 2; }
NAME="${1:-}"
[ "${2:-}" = "--confirm" ] && [ "${3:-}" = "$NAME" ] || die "usage: $0 <name> --confirm <name> [--purge-backups]"
PURGE=0; if [ "${4:-}" = "--purge-backups" ]; then PURGE=1; fi
RESERVED="demo main db test www root admin postgres complynex"
[[ "$NAME" =~ ^[a-z][a-z0-9]{1,19}$ ]] || die "invalid name"
for r in $RESERVED; do [ "$NAME" != "$r" ] || die "reserved name: $NAME"; done
MAIN="${CX_MAIN:-/var/www/complynex}"
INST="/var/www/complynex-$NAME"; DB="complynex_$NAME"; ROLE="complynex_$NAME"; UNIT="complynex-$NAME"; USR="cx-$NAME"
BK="/var/backups/complynex-$NAME"; LIST=/etc/complynex/instances.list
case "$DB" in complynex_db|complynex|postgres|template0|template1) die "database $DB is not an instance database";; esac
[[ "$DB" =~ ^complynex_[a-z][a-z0-9]{1,19}$ ]] || die "unexpected database name $DB"
[ "$INST" != "$MAIN" ] || die "that is the main instance"
[ "$(id -u)" = 0 ] || die "run as root"
# the list must be root-owned and writable by root only, and must name this instance
[ -f "$LIST" ] || die "$LIST missing"
[ "$(stat -c '%u' "$LIST")" = 0 ] && [ -z "$(find "$LIST" -perm /022)" ] || die "$LIST is not root-owned / is writable by others"
LINE=$(awk -v n="$NAME" '$1==n' "$LIST")
[ -n "$LINE" ] || die "$NAME is not in $LIST"
[ -f "$INST/.cx_instance" ] || die "$INST/.cx_instance missing"
RDB=$(echo "$LINE" | awk '{print $3}')

if sudo -u postgres psql -qtAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
  if [ "$PURGE" = 0 ]; then
    install -d -m 700 -o root -g root "$BK"
    sudo -u postgres pg_dump -Fc -d "$DB" > "$BK/final_$(date +%Y%m%d_%H%M%S).dump"
    echo "final dump kept in $BK"
  fi
fi
systemctl disable --now "$UNIT-backup.timer" "$UNIT.service" 2>/dev/null || true
rm -f "/etc/systemd/system/$UNIT.service" "/etc/systemd/system/$UNIT-backup.service" "/etc/systemd/system/$UNIT-backup.timer"
systemctl daemon-reload
systemctl reset-failed "$UNIT.service" "$UNIT-backup.service" 2>/dev/null || true
sudo -u postgres dropdb --if-exists "$DB"
sudo -u postgres psql -qc "DROP ROLE IF EXISTS $ROLE"
# its Redis database (from the root-owned list; never 0, the main instance's)
if [[ "$RDB" =~ ^[0-9]+$ ]] && [ "$RDB" -ge 1 ] && [ "$RDB" -le 15 ]; then redis-cli -n "$RDB" FLUSHDB >/dev/null || true; fi
git -C "$MAIN" -c safe.directory='*' -c core.hooksPath=/dev/null worktree remove --force "$INST" 2>/dev/null || true
rm -rf --one-file-system "$INST"
git -C "$MAIN" -c safe.directory='*' -c core.hooksPath=/dev/null worktree prune
if id "$USR" >/dev/null 2>&1; then userdel "$USR" 2>/dev/null || true; fi
getent group "$USR" >/dev/null && groupdel "$USR" 2>/dev/null || true
{ grep -v "^$NAME " "$LIST" || true; } > "$LIST.new"; chown root:root "$LIST.new"; chmod 644 "$LIST.new"; mv "$LIST.new" "$LIST"
rm -f "/root/.complynex_instances/$NAME"
# the shared backup script goes with the last instance
if [ ! -s "$LIST" ]; then rm -f /usr/local/sbin/complynex-instance-backup; fi
if [ "$PURGE" = 1 ]; then rm -rf "$BK"; fi
echo "instance $NAME removed"
