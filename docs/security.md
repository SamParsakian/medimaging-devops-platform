# Security

This document describes the security posture of this platform as it actually stands today: what's protected, what isn't, and where the real gaps are. It's a demo-grade local stack built to show DevOps and platform engineering practices, not a clinical system, and this document is deliberately honest about that difference rather than dressing the project up as more secure than it is.

## No real patient data, ever

This platform has never held real patient data and is not meant to. Every DICOM file it has ever processed is a public demo/sample file (see `docs/sample-data.md`), and the anonymizer (below) still runs on it anyway, out of habit rather than necessity. This rule is the foundation everything else in this document sits on top of - if this were ever violated, none of the other measures here would make the project appropriate for real patient data.

## Demo API key protection

The API (`services/api/main.py`) requires a shared secret key on every endpoint except `/health` and `/metrics` (see `docs/local-stack.md`). The key is checked against a single fixed value from `.env` - there are no user accounts, no sessions, and no per-user permissions. A missing key returns `401`, a wrong key returns `403`.

This is enough to stop a casual, unauthenticated request, but it is not real authentication: everyone who has the key has full access to everything, and the key itself is a plain string with no rotation, expiry, or per-client scoping.

## Secrets stay in `.env`

Every credential this project uses (Postgres, MinIO, Orthanc, the API key, Grafana's admin login) is read from environment variables at runtime, sourced from a single `.env` file. `.env.example` documents every variable with a placeholder value (`changeme`) but never the real one. Nothing in application code, `docker-compose.yml`, or any script has a credential hardcoded into it.

## `.env` is git-ignored

`.env` is excluded from version control:

```text
# --- Secrets & environment files ---
.env
.env.*
!.env.example
*.pem
*.key
secrets/
```

Only `.env.example` is ever committed. This has held since Step 0 and is checked before every commit as part of the normal review, not just written down once and forgotten.

## Anonymization before preview, storage, or AI

Every DICOM file goes through `services/anonymizer/anonymize.py` before anything else touches it - before a preview PNG is generated, before it's uploaded to MinIO, and before any future AI component would see it. The anonymizer replaces the tags most likely to identify a patient (`PatientName`, `PatientID`, `PatientBirthDate`, `AccessionNumber`, `InstitutionName`, `ReferringPhysicianName`) with fixed demo values.

This is explicitly demo-grade de-identification, not a clinical one - see "Production improvements" below for what a real de-identification pipeline would add.

## Audit logging

Every read through the API (`/studies`, `/studies/{id}`, `/studies/{id}/preview-info`, `/studies/{id}/preview-image`) is written to the `audit_events` table: who (`user_id`, currently always the one fixed `demo-user`), what (`action`), which study, when, from what IP address, and whether it succeeded. See `docs/local-stack.md` for the exact columns and how to query it.

There's no real user identity behind `user_id` yet, so this is closer to "there is a record of what was accessed and when" than "there is proof of who specifically accessed it."

## Backup and restore awareness

Backups (`scripts/backup/backup.sh`) are plain, unencrypted files written to a local, git-ignored folder - a full Postgres dump, a mirror of the MinIO bucket, and a tarball of Orthanc's storage. There's no offsite copy, no encryption at rest, and no retention policy; it's whatever's in `scripts/backup/output/` on the one machine running the stack. See `docs/backup-restore.md` for the full process and its limits.

## MinIO, PostgreSQL, and Orthanc access

All three data services are protected by credentials from `.env`, not left open. But `docker-compose.yml` publishes each one's port on every network interface on the host (the default for a `host:container` port mapping), not just `localhost` - so on a machine with no firewall between it and the local network, PostgreSQL, MinIO, and Orthanc are technically reachable from other devices on that same network, protected only by their passwords. On a personal laptop behind a home router this is a low-risk, well-understood tradeoff; it would not be acceptable as-is on a shared or public network.

## Local-only demo limits

Put plainly, this stack assumes a trusted single machine and a trusted single operator. There is no HTTPS anywhere (everything is plain HTTP on localhost), no reverse proxy, no rate limiting, no intrusion detection, no automatic security patching, and no separation between "admin" and "regular user" - there's only the one demo user and the one shared API key. None of this is hidden; it's the natural result of building a local demo stack instead of a deployed, internet-facing one.

## No clinical diagnosis claims

This platform does not interpret, diagnose, or make any clinical judgment about any image it stores or displays. It is a storage, processing, and observability demo, not a medical device, and nothing in its output should ever be read as a diagnosis or clinical recommendation. Any future AI component follows the same rule: it may describe or process pixel data, but it does not diagnose.

## Production improvements

These are the concrete steps that would matter most if this platform were ever adapted for something beyond a local demo. Naming them here is a design acknowledgment, not a task list for this project.

- **HTTPS / reverse proxy** - TLS termination (e.g. via Caddy or nginx) in front of every service, so nothing is ever sent in plaintext, even on a private network.
- **Real identity provider** - OAuth2/OIDC through an actual identity provider, replacing the single shared API key with per-user login and tokens that can be revoked individually.
- **RBAC** - role-based access control, so a viewer, an operator, and an admin don't all have the same access, unlike today's one flat demo user.
- **Stronger DICOM de-identification** - a real de-identification profile (DICOM PS3.15 / Supplement 142), which regenerates UIDs and strips a much larger, standardized set of identifying tags instead of the handful of fixed replacements used today.
- **Secret manager** - credentials in a proper secret store (e.g. Vault, AWS Secrets Manager) with rotation and access logging, instead of a plaintext `.env` file on disk.
- **Network segmentation** - PostgreSQL, MinIO, and Orthanc placed on a private network reachable only by the services that need them, with nothing but the API and a reverse proxy exposed at all.
- **Vulnerability scanning** - automated scanning of both container images and Python dependencies, so a known CVE in a base image or a library doesn't sit there unnoticed.
