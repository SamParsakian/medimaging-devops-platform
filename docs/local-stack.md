# Local Stack

Three services make up the base stack:

- **Orthanc** — the DICOM server (PACS). Receives, stores, and serves medical images, and exposes a REST API and web UI on top of the standard DICOM protocol.
- **PostgreSQL** — holds structured metadata about the imaging data (e.g. a reference table for studies), separate from the actual image files.
- **MinIO** — S3-compatible object storage, for anything file-based that isn't a raw DICOM image: processed previews, AI outputs, and backups, added in later steps.

## Local URLs

- Orthanc web UI / REST API: http://localhost:8042
- PostgreSQL: `localhost:5432`
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001

Credentials for all three come from `.env` (copy `.env.example` to get started).
