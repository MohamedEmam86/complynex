# Installing ComplyNex for a client (on-premises / Egyptian data centre)

One server (or VM) per client. Client data never shares a database with another client.

## Sizing (starting point)

| | Minimum | Recommended |
|---|---|---|
| CPU | 4 vCPU | 8 vCPU |
| RAM | 16 GB | 32 GB (Elasticsearch 2–4 GB heap, semantic index ~1 GB, 4 web workers) |
| Disk | 200 GB SSD | 500 GB SSD + separate backup volume |
| OS | Ubuntu 24.04 LTS | |

## Option A — virtual machine / bare metal (recommended)

```bash
sudo git clone <repository> /var/www/complynex      # or copy the release archive there
cd /var/www/complynex
sudo ./deploy/install_server.sh --domain cms.client.local \
     --cert /etc/ssl/client/fullchain.pem --key /etc/ssl/client/privkey.pem
```

The script installs PostgreSQL 16, Redis, Elasticsearch 8 (localhost only, authentication on), nginx,
the Python environment (CPU-only PyTorch), loads `database/baseline/schema.sql`, writes `.env` with
generated secrets (chmod 600), installs every systemd unit from `deploy/systemd/` and enables those in
`deploy/systemd/ENABLED`, renders the nginx site, turns on the firewall and SSH hardening, and prints the
first administrator password once. Re-running it is safe.

**Closed network (no internet):** pass `--es-deb` with the Elasticsearch package, pre-load the Python
wheels into a local index (`pip download -r requirements.txt`), and copy `.cache/huggingface` from another
instance. Sanctions lists are then imported from files (Screening → Sources → upload) instead of
`scripts/run_sanctions_update.py`.

After installation:
1. Load the sanctions lists and build the indexes: `scripts/run_sanctions_update.py`,
   `scripts/es_full_migrate.py`, `scripts/rebuild_semantic_index.py` (run as `complynex` with `.env` loaded).
2. Enable the client's regulatory packs (Compliance Controls → Packs), e.g. *FRA sustainability & carbon*.
3. Decide the backup target (client storage) and enable `complynex-backup.timer` with an encrypted target.
4. Replace the self-signed certificate if one was generated.

Updates: `sudo ./deploy.sh` (pulls the release branch, applies new migrations, runs the guards, restarts,
health-checks, rolls back automatically on failure).

## Option B — containers

`deploy/docker/` holds an image (`Dockerfile`), a compose stack (PostgreSQL, Redis, Elasticsearch, web,
semantic service, eKYC and events workers, a `jobs` scheduler and nginx). See the header of
`docker-compose.yml`. Status: provided for evaluation and container platforms; the VM path above is the
one used in production.
