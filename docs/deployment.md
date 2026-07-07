# Deployment

This document plans out what moving this stack from a local Mac to a rented server would actually involve. It's preparation only - nothing here has been deployed, no server has been rented, and no domain or certificate exists yet. The goal is to have every real decision (ports, secrets, backups, HTTPS) already thought through and written down, so the day a VPS actually gets rented, it's a checklist to follow rather than a design exercise to do under pressure. GPU-specific concerns (Mac ARM64 vs cloud GPU, CPU vs GPU inference, NVIDIA Container Toolkit) are split out into `docs/gpu-demo-plan.md`.

## Docker Compose deployment flow

The stack is already fully defined in `docker-compose.yml` - the plan is not to rewrite it for production, but to layer a second file on top of it using Compose's multi-file support:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.example.yml --env-file .env.production up -d --build
```

`docker-compose.prod.example.yml` (added in this step, see below) only overrides what actually needs to change for a server instead of a laptop - it doesn't redefine any service from scratch, and the base `docker-compose.yml` stays the single source of truth for what each service is and how they connect to each other. It deliberately does not try to change which ports get published - Compose merges the `ports` list across files by appending to it, not replacing it, so an override file can't unpublish a port the base file already defines (confirmed directly with `docker compose config` while writing this - see the file's own comments). Closing ports to the public internet is a firewall job, not a Compose job - see "Firewall ports" below.

## Persistent volumes

Five named volumes already exist and already hold everything that must survive a restart:

```text
orthanc-storage
postgres-data
minio-data
prometheus-data
grafana-data
```

On a VPS, these need to sit on the server's actual persistent disk, not on ephemeral/scratch storage some providers offer cheaper - losing any one of them means losing real data (Postgres's metadata, MinIO's stored files, Orthanc's DICOM storage) or just historical monitoring data (Prometheus, Grafana), not something that regenerates on its own. Docker's default named-volume behavior already writes to the host's persistent disk, so no extra configuration is required here beyond picking a VPS plan with real (not purely ephemeral) block storage.

## Model weight/cache handling

`services/ai-inference/Dockerfile` already downloads the TorchXRayVision model weights at build time, not at container startup (see Step 24) - this matters just as much for deployment as it did for local development. Building the image on the VPS means that build step runs again there, so the server needs working internet access at build time even though the running container never needs it afterward. There's no separate weight cache volume to manage: the weights live inside the built image layer itself. Rebuilding the image (e.g. to switch to a GPU-enabled base, see `docs/gpu-demo-plan.md`) means paying that download cost again.

## Backup before deployment

Before doing anything to move or change environments, `scripts/backup/backup.sh` (Step 11) gets run against the current local stack first - a full Postgres dump, a MinIO mirror, and an Orthanc storage tarball, timestamped under `scripts/backup/output/`. This isn't a deployment-specific script, it's the same backup this project already has; the plan is simply to never treat "about to deploy" as an exception to running it.

## Restore check after deployment

Standing the stack up on a VPS for the first time is not the same environment as this Mac, so `scripts/backup/restore.sh` working here is not proof it works there. The plan is to run a restore on the fresh VPS deployment immediately after it's up (using the backup taken above), before trusting the new environment with anything real - the same "restore was actually tested, not just assumed" habit from Step 11, applied to a new machine instead of a damaged local one.

## Firewall ports

The full port list this stack uses today, all bound to every network interface by default (see `docs/security.md`):

```text
8042  Orthanc HTTP/REST
4242  Orthanc DICOM
5432  PostgreSQL
9000  MinIO API
9001  MinIO console
8000  API (+ dashboard)
8100  AI inference
9090  Prometheus
3000  Grafana
```

On a laptop behind a home router this is a manageable tradeoff; on a public VPS with a real public IP, it isn't. The plan is that only port 8000 (the API, which also serves the dashboard) would ever be open to the public internet, and only through the reverse proxy below rather than directly. Every other port - Postgres, MinIO, Orthanc, Prometheus, Grafana, and the raw ai-inference port - would stay closed at the VPS firewall level (e.g. a cloud provider's security group, or `ufw`/`iptables` on the host) and only reachable over the server's own internal Docker network, the same way `api` already reaches `postgres` and `minio` by service name instead of a published port.

## Reverse proxy / HTTPS plan

Not implemented yet, on purpose - this needs a real domain name first, which doesn't exist. The plan: a reverse proxy (Caddy is the leading candidate, since it handles automatic HTTPS certificate provisioning with very little manual configuration) sits in front of the `api` service only, terminating TLS on port 443 and forwarding plain HTTP internally to `api:8000`. Nothing else in the stack would ever be reachable from outside the server at all, per the firewall plan above. Until a domain exists, this stays a plan rather than a config file - there's nothing real to point a reverse proxy at yet.

## Secrets handling

`.env.production.example` (added in this step) documents every variable a production deployment needs, the same way `.env.example` already does for local development - placeholder values only, never committed with anything real. The actual `.env.production` file would be created directly on the VPS (or generated via whatever secret-injection method the hosting provider supports) and never leave that machine or enter version control - `.gitignore`'s existing `.env.*` pattern already covers it. Production secrets should also be different values from the local `.env`'s, not a copy of them - a leaked local demo key shouldn't also compromise a real deployment.

## Public demo limitations

Everything in `docs/security.md` about this being a local, single-operator, no-real-auth demo stack still applies once it's reachable on the internet instead of `localhost` - the security posture doesn't change just because the URL does. If this were ever deployed as a public demo, the same API key model described there would still be the only thing standing between the internet and the API, which is a materially bigger risk on a public IP than on a home network. This is a real limitation to accept consciously before deploying, not a gap to paper over.

This platform holds no real patient data and makes no clinical diagnosis claims, on a rented VPS exactly the same as it doesn't today - deploying it changes where it runs, not what it's allowed to hold or claim.
