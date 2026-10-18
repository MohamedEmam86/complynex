#!/usr/bin/env bash
# =============================================================================
# ComplyNex — portable full backup for local reinstall.
#
# NOT a blind copy of 43 GB. A blind copy would include 6.3 GB of superseded
# FAISS indexes, a 1.5 GB Elasticsearch store that is rebuildable from
# PostgreSQL, and a virtualenv that must be rebuilt on the target machine
# anyway. This packages what is needed to stand the system up somewhere else.
#
#   sudo /var/www/complynex/scripts/portable_backup.sh
# =============================================================================
set -euo pipefail

APP=/var/www/complynex
STAMP=$(date +%Y%m%d_%H%M%S)
WORK=/var/tmp/cnx_portable_$STAMP
OUT="/var/tmp/complynex_portable_${STAMP}.tar.gz"
REMOTE="gdrive:Basata_Full_Backups"

echo "ComplyNex — portable backup"
echo "==========================="
mkdir -p "$WORK"/{code,database,indexes,config,docs}

# ---------------------------------------------------------------- 1. code
echo
echo "1. Source code (excluding venv, caches, dead indexes)..."
tar -czf "$WORK/code/complynex_source.tar.gz" -C /var/www \
    --exclude='complynex/venv' \
    --exclude='complynex/venv_deploy' \
    --exclude='*/__pycache__' \
    --exclude='*.pyc' \
    --exclude='complynex/logs/*' \
    --exclude='complynex/backups' \
    --exclude='complynex/*.index' \
    --exclude='complynex/screening/*.index' \
    --exclude='complynex/screening/*.stale-bak' \
    --exclude='complynex/screening/*.corrupted_*' \
    --exclude='complynex/screening/*_backup_*' \
    --exclude='complynex/uploads/*' \
    --exclude='complynex/*.jpg' \
    --exclude='complynex/provenance/manifest_2*' \
    --exclude='complynex/ekyc_storage/*' \
    --exclude='complynex/.env' \
    complynex 2>/dev/null
echo "   $(du -h "$WORK/code/complynex_source.tar.gz" | cut -f1)"

# ---------------------------------------------------------------- 2. database
echo "2. PostgreSQL dump..."
# Redirect from root's shell rather than -f: the postgres user cannot write
# into a root-owned work directory, which is why -f failed with EACCES.
sudo -u postgres pg_dump -d complynex_db -Fc > "$WORK/database/complynex_db.dump"
sudo -u postgres pg_dumpall --globals-only > "$WORK/database/globals.sql"
echo "   $(du -h "$WORK/database/complynex_db.dump" | cut -f1)"

# ------------------------------------------------------------- 3. live index
# Only the index actually in use. The others are superseded or backups and
# would add 6.3 GB for nothing.
echo "3. Live FAISS index only..."
LIVE=$APP/screening/watchlist_semantic_v2.index
if [[ -f "$LIVE" ]]; then
    cp "$LIVE" "$WORK/indexes/"
    [[ -f "${LIVE%.index}_meta.json" ]] && cp "${LIVE%.index}_meta.json" "$WORK/indexes/" || true
    echo "   $(du -h "$WORK/indexes/$(basename "$LIVE")" | cut -f1)"
else
    echo "   not found — the semantic index will need rebuilding"
fi

# ---------------------------------------------------------------- 4. config
echo "4. System configuration..."
cp /etc/systemd/system/complynex*.service "$WORK/config/" 2>/dev/null || true
cp /etc/systemd/system/complynex*.timer   "$WORK/config/" 2>/dev/null || true
cp /etc/nginx/sites-available/*           "$WORK/config/" 2>/dev/null || true
cp /etc/postgresql/16/main/conf.d/*.conf  "$WORK/config/" 2>/dev/null || true
[[ -f $APP/requirements.txt ]] && cp $APP/requirements.txt "$WORK/config/"
"$APP/venv/bin/pip" freeze > "$WORK/config/requirements_frozen.txt" 2>/dev/null || true

# .env keys WITHOUT values. The live file holds a working database password and
# a working mailbox password; copying those to cloud storage is a decision for
# you to make deliberately, not something a backup script should do quietly.
if [[ -f $APP/.env ]]; then
    sed -E 's/^([A-Za-z_]+)=.*/\1=<SET THIS LOCALLY>/' $APP/.env > "$WORK/config/env.template"
fi
echo "   systemd units, nginx, postgres tuning, requirements, env template"

# ------------------------------------------------------------ 5. provenance
echo "5. Provenance and integrity..."
cp -r $APP/provenance "$WORK/docs/" 2>/dev/null || true
git -C $APP log --format='%H|%ai|%an|%s' > "$WORK/docs/git_history.txt" 2>/dev/null || true

# --------------------------------------------------------------- 6. README
cat > "$WORK/README_RESTORE.md" <<'EOF'
# ComplyNex — local restore

## What is in here

| Folder | Contents |
|---|---|
| `code/` | Full source, minus venv, caches and generated indexes |
| `database/` | PostgreSQL custom-format dump + role globals |
| `indexes/` | The live FAISS semantic index only |
| `config/` | systemd units, nginx, PostgreSQL tuning, requirements, env template |
| `docs/` | Provenance manifests, RFC 3161 timestamps, git history |

**Not included, deliberately:**

- **`venv/`** — rebuild it; a virtualenv is not portable between machines.
- **Elasticsearch data** — rebuilt from PostgreSQL by the sync job. Saves 1.5 GB.
- **Superseded FAISS indexes** — 6.3 GB of old and backup index files.
- **`.env` values** — `config/env.template` has the keys with placeholders.
  The live file contains a working database password and mailbox password.
  Copy it across yourself if you want it.

## Restore

```bash
# 1. Prerequisites
sudo apt install -y python3 python3-venv postgresql redis-server nginx
# Elasticsearch 8.x separately if you want semantic/fuzzy search

# 2. Code
sudo mkdir -p /var/www && cd /var/www
sudo tar -xzf code/complynex_source.tar.gz

# 3. Python environment
cd /var/www/complynex
python3 -m venv venv
./venv/bin/pip install -r config/requirements_frozen.txt

# 4. Database
sudo -u postgres psql -f database/globals.sql
sudo -u postgres createdb complynex_db
sudo -u postgres pg_restore -d complynex_db --no-owner database/complynex_db.dump

# 5. Semantic index
cp indexes/watchlist_semantic_v2.index /var/www/complynex/screening/

# 6. Configuration
cp config/env.template /var/www/complynex/.env
#    then edit .env and set every value
chmod 600 /var/www/complynex/.env

# 7. Run
./venv/bin/python app.py          # development
#    or install the systemd units from config/ for production
```

## Verify the restore matches the original

```bash
python3 scripts/code_manifest.py verify
```

Compares every file against the manifest in `docs/provenance/`. "IDENTICAL"
means the restore is byte-for-byte the same code.

## After restoring

- Elasticsearch index rebuilds via the sync job, or screening falls back to
  PostgreSQL matching (slower, still correct)
- Set `EMAIL_USER` / `EMAIL_PASS` or reminders stay in-app only
- First start takes 25–30s while FAISS and the ML model load
EOF

# ---------------------------------------------------------------- package
echo "6. Packaging..."
tar -czf "$OUT" -C "$(dirname "$WORK")" "$(basename "$WORK")"
SIZE=$(du -h "$OUT" | cut -f1)
SHA=$(sha256sum "$OUT" | cut -d' ' -f1)
rm -rf "$WORK"
echo "   $OUT  ($SIZE)"

# ---------------------------------------------------------------- upload
echo
echo "7. Uploading to Google Drive..."
if ! rclone lsd "$REMOTE" >/dev/null 2>&1; then
    rclone mkdir "$REMOTE" 2>/dev/null || true
fi
rclone copy "$OUT" "$REMOTE" --progress 2>&1 | tail -2

# verify: rclone can exit 0 having copied nothing
REMOTE_SIZE=$(rclone size "$REMOTE/$(basename "$OUT")" --json 2>/dev/null | grep -oE '"bytes":[0-9]+' | cut -d: -f2)
LOCAL_SIZE=$(stat -c%s "$OUT")
echo
if [[ "$REMOTE_SIZE" == "$LOCAL_SIZE" ]]; then
    echo "   VERIFIED on Drive — $REMOTE_SIZE bytes, matches local"
else
    echo "   WARNING: remote size ($REMOTE_SIZE) != local ($LOCAL_SIZE)"
fi
echo
echo "   SHA-256: $SHA"
echo "   Local copy kept at $OUT"
