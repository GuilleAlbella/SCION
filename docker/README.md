# SCION — Docker

This folder contains the **build inputs** for the SCION container
images: Dockerfiles, the entrypoint script, and the dev nginx config.
It is _not_ where end users go to deploy SCION.

## For end users (deploy SCION on a VM)

The deploy artifacts (`docker-compose.yml`, `nginx.conf`, install
scripts) live in a separate **public** repository so the one-liner
installer can pull them anonymously. The SCION application source —
this repo — stays private.

→ **<https://github.com/GuilleAlbella/scion-deploy>**

That repo's README has the full deploy guide (Linux one-liner,
Windows one-liner, manual fallback, troubleshooting, version
pinning).

## For developers (smoke-test the full stack from a SCION clone)

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

This combines:

- `docker-compose.yml` — the production stack (backend, frontend,
  nginx, watchtower) using GHCR images by default.
- `docker-compose.build.yml` — an override that swaps the GHCR images
  for local builds against the working tree.

End result: a stack identical to what the installer brings up on a
VM, but using your in-progress code instead of the published images.
Useful for catching deploy issues before they reach a tag.

`./docker/nginx.conf` is mounted by the dev compose. The one in
`scion-deploy` is the canonical version that ships to users; keep
them in sync when you change either.

## Files in this folder

| File                  | Used at         | Purpose                                  |
| --------------------- | --------------- | ---------------------------------------- |
| `backend.Dockerfile`  | `docker build`  | Backend image (FastAPI + uvicorn)        |
| `frontend.Dockerfile` | `docker build`  | Frontend image (Next.js standalone)      |
| `entrypoint.sh`       | runtime         | Runs `db_init.py init` before uvicorn    |
| `nginx.conf`          | dev smoke test  | Dev copy of the reverse-proxy config     |

## Publishing a new image release

Tag the SCION repo with `vX.Y.Z`:

```bash
git tag v1.22.0
git push origin v1.22.0
```

The `.github/workflows/publish-images.yml` workflow builds and pushes
both images to GHCR with tags `X.Y.Z`, `X.Y`, and `latest` (the
`latest` alias is skipped for `-rc` / `-beta` / `-alpha`).

After publish, the `scion-deploy` repo doesn't need any change for
the new version to roll out — the installed Watchtower instances
will pick up the new `:latest` within 6 hours, or users can run
`update.sh` / `update.ps1` to upgrade immediately.

If a deploy-side change is needed too (e.g. a new env var, an extra
service in compose), update `scion-deploy` first; users on Watchtower
will keep using the old compose until they re-run the installer or
manually pull the new compose with `update.sh` / `update.ps1`.
