# SCION — Docker deploy

Two paths: a one-liner that handles everything end-to-end, or a manual
6-step path for environments where the bootstrap can't run as-is
(airgapped, restricted egress, custom Docker setup).

---

## Path A — One-liner (recommended)

On any Linux VM with internet access:

```bash
curl -fsSL https://raw.githubusercontent.com/GuilleAlbella/SCION/main/install.sh | bash
```

What it does:

1. Detects the distro (Ubuntu/Debian/RHEL/CentOS/Rocky/AlmaLinux/Fedora).
2. Installs Docker Engine + Compose plugin if missing.
3. Creates `/opt/scion` and downloads `docker-compose.yml` +
   `docker/nginx.conf` from the repo.
4. Prompts for region, public port, and Groq key (Enter accepts defaults).
5. **Auto-generates** a strong `API_KEY` — you don't think about it.
6. `docker compose pull && up -d`.
7. Prints the URL and admin key.

End result:

```
═══════════════════════════════════════════════════════════
  SCION is up
═══════════════════════════════════════════════════════════

  URL:        http://10.0.4.27:80
  Admin key:  3f9c…
  Config:     /opt/scion/.env

  Status:   cd /opt/scion && docker compose ps
  Logs:     cd /opt/scion && docker compose logs -f
  Update:   curl -fsSL .../update.sh | bash
  Stop:     cd /opt/scion && docker compose down

  Watchtower will auto-pull new releases every 6h.
```

### Updating

Watchtower auto-pulls new images every 6 hours. To force an upgrade now:

```bash
curl -fsSL https://raw.githubusercontent.com/GuilleAlbella/SCION/main/update.sh | bash
```

### Uninstalling

```bash
curl -fsSL https://raw.githubusercontent.com/GuilleAlbella/SCION/main/uninstall.sh | bash
```

The uninstaller asks before removing the data volume — declining keeps
your SQLite database on disk so a fresh install picks up where you left.

---

## Path B — Manual deploy (fallback)

Use this when `install.sh` fails (airgapped VM, locked-down sudo,
custom Docker install) or when you want to inspect every step.

### Prerequisites

- Linux VM with internet to `ghcr.io` and `docker.io`.
- Docker Engine ≥ 24 with the Compose plugin (`docker compose version`).

If Docker is missing, follow the official guide for your distro:
<https://docs.docker.com/engine/install/>.

### Steps

```bash
# 1. Create the deploy directory
sudo mkdir -p /opt/scion/docker
cd /opt/scion

# 2. Download the compose + nginx config
sudo curl -fsSL \
  https://raw.githubusercontent.com/GuilleAlbella/SCION/main/docker-compose.yml \
  -o docker-compose.yml
sudo curl -fsSL \
  https://raw.githubusercontent.com/GuilleAlbella/SCION/main/docker/nginx.conf \
  -o docker/nginx.conf
sudo curl -fsSL \
  https://raw.githubusercontent.com/GuilleAlbella/SCION/main/.env.example \
  -o .env.example

# 3. Create your .env from the template
sudo cp .env.example .env
sudo chmod 600 .env
sudo $EDITOR .env
#   At minimum set:
#     - API_KEY (generate with: openssl rand -hex 32)
#     - GROQ_API_KEY (if using TAISA)
#     - DATA_REGION
#     - SCION_PUBLIC_PORT (default 80)

# 4. Pull and start
sudo docker compose pull
sudo docker compose up -d

# 5. Verify
sudo docker compose ps
curl -fsS http://localhost/health/ready
```

To upgrade later:

```bash
cd /opt/scion
sudo docker compose pull
sudo docker compose up -d
```

---

## Building from source instead of pulling

When iterating on Dockerfiles or before the first GHCR publish:

```bash
git clone https://github.com/GuilleAlbella/SCION
cd SCION
cp .env.example .env && $EDITOR .env
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

---

## What gets deployed

| Container         | Image                                     | Purpose                                |
| ----------------- | ----------------------------------------- | -------------------------------------- |
| `scion-backend`   | `ghcr.io/guillealbella/scion-backend`     | FastAPI + uvicorn, runs `db_init.py`   |
| `scion-frontend`  | `ghcr.io/guillealbella/scion-frontend`    | Next.js standalone server              |
| `scion-nginx`     | `nginx:1.27-alpine`                       | Single public port, routes to the two |
| `scion-watchtower`| `containrrr/watchtower:1.7.1`             | Auto-pull new images every 6h          |

State lives in the named volume `scion-data` (mounted at `/data` on
the backend container). It contains the SQLite file
`/data/scion.db`. Container rebuilds and image upgrades preserve it;
`docker compose down -v` wipes it.

---

## VM sizing

Confirmed in Reunion 9 with Rahul + Asim:

- **Test (CloudBolt)**: 8 core / 32 GB RAM / SSD.
- **Prod (Azure AKS option)**: 8 core / 64 GB / 200 GB NVMe SSD.

Currently the Parser pipeline (Rahul's team) and SCION are intended
to share one VM. SCION is mostly idle outside ingest windows, so the
co-tenancy is fine.

---

## Troubleshooting

**Port 80 already in use** — change `SCION_PUBLIC_PORT` in `.env`,
then `docker compose up -d` (Compose recreates only nginx).

**Backend container restarting** — check `docker compose logs backend`.
The most common cause is `DATABASE_URL` pointing at an unwritable
location. The default `/data/scion.db` is on the named volume and
should always be writable by uid 1000.

**`db_init.py init` fails with "legacy"** — a previous DB on the
volume was created without Alembic. Either restore from backup or
`docker compose down -v` (destroys data) and start fresh.

**Watchtower not upgrading** — make sure each container has the
`com.centurylinklabs.watchtower.enable=true` label (the shipped
compose has it). Inspect with `docker logs scion-watchtower`.

**Need to roll back to a previous version** — pin the image tag in
`.env`:
```
SCION_BACKEND_IMAGE=ghcr.io/guillealbella/scion-backend:1.20.00
SCION_FRONTEND_IMAGE=ghcr.io/guillealbella/scion-frontend:1.20.00
```
then `docker compose up -d`. Watchtower respects pinned tags and
won't bump them.
