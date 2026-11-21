#!/bin/bash
# =============================================================================
# ComplyNex — daily backup of one SECONDARY instance (run by complynex-<name>-backup.timer as root;
# installed as /usr/local/sbin/complynex-instance-backup by create_instance.sh and deploy.sh).
#
#   complynex-instance-backup <name>
#
# Writes /var/backups/complynex-<name>/db_<ts>.dump (pg_dump -Fc, verified with pg_restore -l) and
# uploads_<ts>.tar.gz; keeps the newest 7 of each. Exit code != 0 on any failure (visible in systemctl).
# =============================================================================
set -euo pipefail
umask 077
NAME="${1:-}"
[[ "$NAME" =~ ^[a-z][a-z0-9]{1,19}$ ]] || { echo "usage: $0 <name>"; exit 2; }
INST="/var/www/complynex-$NAME"; DB="complynex_$NAME"; BK="/var/backups/complynex-$NAME"; KEEP="${KEEP:-7}"
[ -f "$INST/.cx_instance" ] || { echo "not an instance: $INST"; exit 2; }
install -d -m 700 "$BK"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$BK/backup.log"
echo "[$(date -Is)] backup $NAME start" >> "$LOG"

DUMP="$BK/db_$TS.dump"
sudo -u postgres pg_dump -Fc -d "$DB" > "$DUMP.part"
N=$(pg_restore -l "$DUMP.part" | grep -c ' TABLE public ' || true)
[ "$N" -gt 0 ] || { echo "[$(date -Is)] FAILED: $DUMP has no tables" >> "$LOG"; rm -f "$DUMP.part"; exit 1; }
mv "$DUMP.part" "$DUMP"

UP="$BK/uploads_$TS.tar.gz"
tar -czf "$UP.part" -C "$INST" uploads
tar -tzf "$UP.part" > /dev/null
mv "$UP.part" "$UP"

ls -1t "$BK"/db_*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t "$BK"/uploads_*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "[$(date -Is)] backup $NAME ok: $(basename "$DUMP") ($N tables, $(du -h "$DUMP" | cut -f1)), $(basename "$UP") ($(du -h "$UP" | cut -f1))" | tee -a "$LOG"
