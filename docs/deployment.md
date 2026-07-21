# Deployment

This document started as a plan for moving this stack from a local Mac to a rented server, written before any server existed - the goal was to have every real decision (ports, secrets, backups, HTTPS) already thought through, so the day a VPS actually got rented it would be a checklist to follow rather than a design exercise to do under pressure. Most of it below is still that original plan; "Three-node deployment" documents what was actually rented and deployed for real, which ended up being three servers instead of one. No domain or certificate exists yet, on any node. GPU-specific concerns (Mac ARM64 vs cloud GPU, CPU vs GPU inference, NVIDIA Container Toolkit) are split out into `docs/gpu-demo-plan.md`.

## Docker Compose deployment flow

The original plan here was a single production server, running `docker-compose.yml` with a second override file (`docker-compose.prod.example.yml`) layered on top of it via Compose's multi-file support - overriding only what actually needs to change for a server instead of a laptop, not redefining any service from scratch. Writing that override file surfaced a real, worth-knowing fact about Compose: it merges the `ports` list across files by appending to it, not replacing it, so an override file can't unpublish a port the base file already defines (confirmed directly with `docker compose config`, not assumed). Closing ports to the public internet is a firewall job, not a Compose job - see "Firewall ports" below.

That single-server plan was superseded before ever being deployed - see "Three-node deployment" below for what was actually built and run.

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

## Three-node deployment

This plan was carried out for real: three small VPS nodes (2 vCPU, 3.7 GB RAM each), one per group of services - app (API, dashboard, ai-inference), data (Postgres, MinIO, Orthanc), and ops (Prometheus, Grafana) - connected over a private network in addition to each having its own public IP. The single `docker-compose.yml` doesn't work unmodified for this, since Compose's `depends_on`/health-check wiring only understands services inside its own project - three separate compose files exist instead, one per node, each defined only in terms of the services that node actually runs:

```text
docker-compose.data-node.example.yml
docker-compose.app-node.example.yml
docker-compose.ops-node.example.yml
.env.data-node.example
.env.app-node.example
.env.ops-node.example
```

Copied to their real (git-ignored) filenames on each server, filled in with real generated secrets, the same pattern `.env.production.example` already used. Cross-node service traffic - the app node's API reaching Postgres/MinIO/Orthanc on the data node, Prometheus on the ops node scraping the API/ai-inference on the app node - goes over each node's private network address instead of a Docker Compose service name, since service-name DNS only resolves inside one node's own Compose project:

```text
POSTGRES_HOST=<data node private IP>
MINIO_HOST=<data node private IP>
ORTHANC_HOST=<data node private IP>
PROMETHEUS_HOST=<ops node private IP>
GRAFANA_HOST=<ops node private IP>
```

The Ops Dashboard's own reachability check (`build_ops_links()` in `services/api/main.py`) needed the same treatment - it used to hardcode Docker's internal service names (`minio`, `orthanc`, `prometheus`, `grafana`) as the address it checks from the API's own backend, which only ever worked because every service used to live in one Compose project. Those are now `ORTHANC_HOST`/`PROMETHEUS_HOST`/`GRAFANA_HOST` environment variables instead (mirroring the `MINIO_HOST` variable the API already had), defaulting to the same service names for local single-machine use and set to each node's private IP for the real deployment - the check still travels over the private network rather than back out over the public internet.

Prometheus itself has no environment-variable substitution in its config file, so its scrape targets can't be set from `.env` the way everything else here is - `infra/monitoring/prometheus/prometheus.multi-node.example.yml` is a template with a placeholder (`APP_NODE_PRIVATE_HOST`) instead, copied to a real `prometheus.multi-node.yml` (git-ignored, since it contains a real private IP) on the ops node with the placeholder replaced, and mounted in place of the single-machine `prometheus.yml`.

### A real gotcha: ufw doesn't actually restrict Docker's published ports

The plan above (only the API's port public, everything else private-network-only) turned out not to be true by default. `ufw` showed a clean "deny incoming, only these ports allowed" status on every node, but every port a container publishes with `ports:` was still reachable from the public internet regardless - confirmed directly, not assumed, by testing Postgres's port from outside right after `ufw` reported it blocked. Docker manages its own `iptables` rules for published ports and inserts them ahead of `ufw`'s own chain, so `ufw`'s rules never actually get evaluated for container traffic at all.

The real fix uses Docker's own `DOCKER-USER` iptables chain, which Docker guarantees is evaluated before its own port-publishing rules:

```bash
iptables -A DOCKER-USER -i <private-interface> -j RETURN
iptables -A DOCKER-USER -i <public-interface> -p tcp --dport <allowed-port> -j RETURN
iptables -A DOCKER-USER -i <public-interface> -j DROP
```

Traffic arriving on the private network interface is always allowed through (`RETURN` continues on to Docker's normal handling); traffic arriving on the public interface only gets through for the specific ports meant to be public; anything else arriving on the public interface gets dropped before it ever reaches a container. Rule order matters - `iptables -I` (insert) without a position number keeps inserting at the top, which silently reverses the intended order if run more than once; `iptables -A` (append) after an `iptables -F` flush keeps them in the order written. This has to be set up separately from `ufw`, on every node that publishes a port that shouldn't be public, and doesn't persist across a reboot without extra configuration (`iptables-persistent` or similar) - worth doing for anything longer-lived than a demo that gets torn down.

### Real resource behavior on a small node

2 vCPU / 3.7 GB RAM with no swap was tight enough that a swap file was added before deploying anything (`scripts/deployment/setup-swap.sh`), sized to each node's actual job - 4 GB on the app node (API, dashboard, and ai-inference's torch/torchxrayvision model all share this node), 2 GB on the data and ops nodes. Building the ai-inference image (downloading torch and the model weights) took noticeably longer than on a development machine, as expected for 2 vCPUs - but once running, a real inference call against the deployed model still completed in a little over a second, which is fast enough that the demo doesn't feel slow even though it's running on CPU-only cloud hardware instead of a laptop.
