#!/usr/bin/env bash
# =============================================================================
# ComplyNex — install a NEW instance on a fresh Ubuntu 24.04 server
# (client on-premises / Egyptian data centre). One server = one client.
#
#   sudo ./deploy/install_server.sh --domain cms.client.local \
#        [--cert /path/fullchain.pem --key /path/privkey.pem] \
#        [--es-deb /path/elasticsearch-8.x-amd64.deb] [--es-heap 2g] [--skip-firewall]
#
# Run it from a copy of the repository placed at /var/www/complynex (the systemd
# units use that path). Idempotent: re-running skips what already exists.
# Secrets are generated on the server and written only to .env (chmod 600) and
# /root/.complynex_install (chmod 600); nothing is printed except the first
# admin password, once.
# =============================================================================
set -euo pipefail
APP=/var/www/complynex
APPUSER=complynex
DB=complynex_db
DOMAIN=""; CERT=""; KEY=""; ES_DEB=""; ES_HEAP="2g"; FIREWALL=1
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2;; --cert) CERT="$2"; shift 2;; --key) KEY="$2"; shift 2;;
    --es-deb) ES_DEB="$2"; shift 2;; --es-heap) ES_HEAP="$2"; shift 2;; --skip-firewall) FIREWALL=0; shift;;
    *) echo "unknown option $1"; exit 2;;
  esac
done
[ -n "$DOMAIN" ] || { echo "--domain is required"; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 2; }
[ -f "$APP/app.py" ] || { echo "repository not found at $APP"; exit 2; }
log() { echo "[$(date +%T)] $*"; }
rnd() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "${1:-32}"; }
umask 077
STATE=/root/.complynex_install; touch "$STATE"
get() { grep -E "^$1=" "$STATE" | cut -d= -f2- || true; }
put() { grep -q "^$1=" "$STATE" && sed -i "s|^$1=.*|$1=$2|" "$STATE" || echo "$1=$2" >> "$STATE"; }

log "1/10 system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3.12 python3.12-venv python3.12-dev build-essential git curl openssl \
  postgresql-16 redis-server nginx libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgl1 libglib2.0-0 \
  libmagic1 fail2ban unattended-upgrades ufw
systemctl enable --now redis-server postgresql nginx fail2ban

log "2/10 Elasticsearch 8 (localhost only, authentication on)"
if ! dpkg -s elasticsearch >/dev/null 2>&1; then
  if [ -n "$ES_DEB" ]; then dpkg -i "$ES_DEB"
  else
    curl -fsSL https://artifacts.elastic.co/GPG-KEY-elasticsearch | gpg --dearmor -o /usr/share/keyrings/elastic.gpg
    echo "deb [signed-by=/usr/share/keyrings/elastic.gpg] https://artifacts.elastic.co/packages/8.x/apt stable main" \
      > /etc/apt/sources.list.d/elastic-8.x.list
    apt-get update -q && apt-get install -y -q elasticsearch
  fi
fi
YML=/etc/elasticsearch/elasticsearch.yml
sed -i '/^xpack.security\|^http.host\|^network.host\|^discovery.type\|^cluster.initial_master_nodes/d' "$YML"
cat >> "$YML" <<YML
http.host: 127.0.0.1
discovery.type: single-node
xpack.security.enabled: true
xpack.security.http.ssl.enabled: false
xpack.security.transport.ssl.enabled: false
YML
printf -- "-Xms%s\n-Xmx%s\n" "$ES_HEAP" "$ES_HEAP" > /etc/elasticsearch/jvm.options.d/heap.options
systemctl enable elasticsearch && systemctl restart elasticsearch
for i in $(seq 1 60); do [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:9200 || true)" = 401 ] && break; sleep 3; done
if [ -z "$(get ES_ELASTIC)" ]; then
  put ES_ELASTIC "$(/usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic -b -s)"
fi
[ -n "$(get ES_APP)" ] || put ES_APP "$(rnd 32)"
EP="$(get ES_ELASTIC)"; AP="$(get ES_APP)"
curl -s -u "elastic:$EP" -X PUT localhost:9200/_security/role/complynex_app -H 'Content-Type: application/json' \
  -d '{"cluster":["monitor"],"indices":[{"names":["aml_*","complynex_*"],"privileges":["all"]}]}' >/dev/null
curl -s -u "elastic:$EP" -X PUT localhost:9200/_security/user/complynex_app -H 'Content-Type: application/json' \
  -d "{\"password\":\"$AP\",\"roles\":[\"complynex_app\"]}" >/dev/null

log "3/10 application user and files"
id "$APPUSER" >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin "$APPUSER"
mkdir -p "$APP"/{logs,uploads,ekyc_storage,backups,.cache}
chown -R "$APPUSER:$APPUSER" "$APP"

log "4/10 Python environment (CPU-only torch first)"
if [ ! -x "$APP/venv/bin/python" ]; then sudo -u "$APPUSER" python3.12 -m venv "$APP/venv"; fi
TORCH=$(grep -E '^torch==' "$APP/requirements.txt" | sed 's/+cpu//'); TV=$(grep -E '^torchvision==' "$APP/requirements.txt" | sed 's/+cpu//')
sudo -u "$APPUSER" HOME="$APP" "$APP/venv/bin/pip" install -q --upgrade pip
sudo -u "$APPUSER" HOME="$APP" "$APP/venv/bin/pip" install -q "$TORCH" "$TV" --index-url https://download.pytorch.org/whl/cpu
grep -vE '^(torch|torchvision)==' "$APP/requirements.txt" > /tmp/cx_req.txt
sudo -u "$APPUSER" HOME="$APP" "$APP/venv/bin/pip" install -q -r /tmp/cx_req.txt
# screening name-similarity model (the services run with HF_HUB_OFFLINE=1). On an offline network copy
# $APP/.cache/huggingface from another instance instead.
sudo -u "$APPUSER" HOME="$APP" HF_HOME="$APP/.cache/huggingface" "$APP/venv/bin/python" -c \
  "from sentence_transformers import SentenceTransformer as S; S('paraphrase-multilingual-MiniLM-L12-v2')" \
  || log "   could not download the similarity model — copy .cache/huggingface from another instance"

log "5/10 PostgreSQL database"
[ -n "$(get DB_PASS)" ] || put DB_PASS "$(rnd 32)"
DBP="$(get DB_PASS)"
sudo -u postgres psql -qtAc "SELECT 1 FROM pg_roles WHERE rolname='$APPUSER'" | grep -q 1 || \
  sudo -u postgres psql -qc "CREATE ROLE $APPUSER LOGIN PASSWORD '$DBP'"
if ! sudo -u postgres psql -qtAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
  sudo -u postgres createdb "$DB"
  sudo -u postgres psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$APP/database/baseline/schema.sql"
fi
sudo -u postgres psql -q -d "$DB" <<SQL
GRANT USAGE ON SCHEMA public TO $APPUSER;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $APPUSER;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO $APPUSER;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO $APPUSER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $APPUSER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO $APPUSER;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM $APPUSER;
SQL

log "6/10 .env"
if [ ! -f "$APP/.env" ]; then
  FK=$("$APP/venv/bin/python" -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
  sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$(rnd 64)|" -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DBP|" \
      -e "s|^DATABASE_URI=.*|DATABASE_URI=postgresql://$APPUSER:$DBP@127.0.0.1:5432/$DB|" \
      -e "s|^ES_PASSWORD=.*|ES_PASSWORD=$AP|" -e "s|^EKYC_ENCRYPTION_KEY_V1=.*|EKYC_ENCRYPTION_KEY_V1=$FK|" \
      -e "s|^APP_URL=.*|APP_URL=https://$DOMAIN|" "$APP/deploy/env.example" > "$APP/.env"
  chown "$APPUSER:$APPUSER" "$APP/.env"; chmod 600 "$APP/.env"
fi

log "7/10 systemd units"
cp "$APP"/deploy/systemd/*.service "$APP"/deploy/systemd/*.timer /etc/systemd/system/
for d in "$APP"/deploy/systemd/*.d; do [ -d "$d" ] && cp -r "$d" /etc/systemd/system/; done
systemctl daemon-reload
while read -r u; do
  case "$u" in complynex-backup.timer) continue;; esac   # off-site backup target is decided per client
  systemctl enable "$u" >/dev/null 2>&1 || true
done < "$APP/deploy/systemd/ENABLED"
systemctl restart complynex complynex-semantic complynex-ekyc-worker complynex-event-dispatcher complynex-pep-scheduler || true
systemctl start $(grep '\.timer$' "$APP/deploy/systemd/ENABLED" | grep -v backup) || true

log "8/10 nginx and TLS"
if [ -z "$CERT" ]; then
  CERT=/etc/ssl/complynex/fullchain.pem; KEY=/etc/ssl/complynex/privkey.pem
  if [ ! -f "$CERT" ]; then
    mkdir -p /etc/ssl/complynex
    openssl req -x509 -nodes -newkey rsa:3072 -days 365 -subj "/CN=$DOMAIN" -keyout "$KEY" -out "$CERT" 2>/dev/null
    log "   self-signed certificate created — replace it with the client's certificate"
  fi
fi
sed -e "s|__DOMAIN__|$DOMAIN|g" -e "s|__APP__|$APP|g" -e "s|__CERT__|$CERT|g" -e "s|__KEY__|$KEY|g" \
    "$APP/deploy/nginx/complynex.conf" > /etc/nginx/sites-available/complynex
ln -sf /etc/nginx/sites-available/complynex /etc/nginx/sites-enabled/complynex
rm -f /etc/nginx/sites-enabled/default
sed -i 's/^\s*# server_tokens off;/\tserver_tokens off;/' /etc/nginx/nginx.conf
nginx -t && systemctl reload nginx

log "9/10 firewall and SSH"
if [ "$FIREWALL" = 1 ]; then ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null; fi
printf "X11Forwarding no\nPermitRootLogin no\nPasswordAuthentication no\n" > /etc/ssh/sshd_config.d/99-complynex-hardening.conf
sshd -t && systemctl reload ssh || true

log "10/10 first administrator and health check"
for i in $(seq 1 40); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health || true)" = 200 ] && break; sleep 3; done
if [ -z "$(get ADMIN_CREATED)" ]; then
  sudo -u "$APPUSER" bash -c "cd $APP && set -a && . ./.env && set +a && venv/bin/python create_admin.py"
  put ADMIN_CREATED 1
fi
log "done: https://$DOMAIN  (health $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health))"
log "next: load the sanctions lists (scripts/run_sanctions_update.py, or upload files on an offline network),"
log "      build the search indexes (scripts/es_full_migrate.py, scripts/rebuild_semantic_index.py),"
log "      enable the regulatory packs of the client (Compliance Controls > Packs)."
