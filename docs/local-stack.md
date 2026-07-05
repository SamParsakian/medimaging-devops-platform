# Local Stack

Four services make up the stack:

- **Orthanc** - the DICOM server (PACS). Receives, stores, and serves medical images, and exposes a REST API and web UI on top of the standard DICOM protocol.
- **PostgreSQL** - holds structured metadata about the imaging data (e.g. a reference table for studies), separate from the actual image files.
- **MinIO** - S3-compatible object storage, for anything file-based that isn't in Orthanc directly: processed/anonymized DICOM files today, previews, AI outputs, and backups later.
- **API** - a read-only FastAPI service in front of the `studies` table, so study metadata and preview info can be queried over HTTP instead of going straight to Postgres.

## Local URLs

- Orthanc web UI / REST API: http://localhost:8042
- PostgreSQL: `localhost:5432`
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001
- API: http://localhost:8000 (Swagger UI at http://localhost:8000/docs)

Credentials for all three storage services come from `.env` (copy `.env.example` to get started). The API has no auth yet.

## Metadata extractor

`services/metadata-extractor/extract.py` is a small script, run manually on the host, that reads studies from Orthanc's REST API and stores their metadata in the PostgreSQL `studies` table. Since it runs on the host rather than inside Docker Compose, it connects using `localhost` (via `ORTHANC_HOST` and `POSTGRES_HOST` in `.env`) instead of the container service names.

```bash
cd services/metadata-extractor
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cd ../..
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/extract.py
```

`services/metadata-extractor/set_preview_path.py` is a second one-shot script that fills in a study's `preview_object_path` column once a preview PNG has been generated and uploaded to MinIO for it (see below). It takes an optional study UID and object path; without arguments it points at the Step 6/6B demo study.

```bash
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/set_preview_path.py
```

## Anonymizer

`services/anonymizer/anonymize.py` is a demo-grade anonymization step, meant to run in front of anything else that would process, preview, or share a DICOM file. It replaces a few identifying tags with fixed demo values (see `services/anonymizer/rules.py`) and writes the result to `services/anonymizer/output/`, which is git-ignored. It's not clinical-grade de-identification - just a habit worth having in place.

```bash
cd services/anonymizer
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cd ../..
./services/anonymizer/.venv/bin/python services/anonymizer/anonymize.py
```

## MinIO uploader

`services/minio-uploader/upload.py` takes an anonymized DICOM file and uploads it to MinIO, in the `medimaging` bucket, under a `processed/anonymized/{study_uid}/{filename}` path. It creates the bucket first if it doesn't exist yet.

```bash
cd services/minio-uploader
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cd ../..
./services/minio-uploader/.venv/bin/python services/minio-uploader/upload.py
```

## Preview generator

`services/preview-generator/generate_preview.py` reads the anonymized DICOM file, applies simple windowing to the pixel data (using `WindowCenter`/`WindowWidth` from the file if present, otherwise a plain min/max stretch) so the CT slice is actually viewable, and writes a PNG to `services/preview-generator/output/`, which is git-ignored.

`services/preview-generator/upload_preview.py` uploads that PNG to MinIO, in the `medimaging` bucket, under a `processed/previews/{study_uid}/{filename}` path. The study UID is read from the source DICOM file, not the PNG.

```bash
cd services/preview-generator
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cd ../..
./services/preview-generator/.venv/bin/python services/preview-generator/generate_preview.py
./services/preview-generator/.venv/bin/python services/preview-generator/upload_preview.py
```

## Study API

`services/api/` is a small read-only FastAPI service, `Dockerfile`-built and run as part of `docker compose up -d`, alongside Orthanc, PostgreSQL, and MinIO. Unlike the other scripts in this project, it isn't a one-shot host script - it's a long-running container, since it needs to keep answering HTTP requests. Inside Docker Compose it reaches PostgreSQL via the `postgres` service name rather than `localhost`.

No auth, no AI yet - just endpoints in front of the `studies` table:

- `GET /health` - basic liveness check
- `GET /studies` - every study currently in the table
- `GET /studies/{orthanc_study_id}` - one study's metadata
- `GET /studies/{orthanc_study_id}/preview-info` - just the MinIO preview object path (and whether one exists) for that study
- `GET /studies/{orthanc_study_id}/preview-image` - streams the actual preview PNG from MinIO
- `GET /audit-events` - the 50 most recent audit events

`PatientID` is always included in responses - this platform's rule is "no real patient data, ever," so every study it can ever hold is demo/anonymized data by definition.

```bash
docker compose up -d --build api
curl http://localhost:8000/health
curl http://localhost:8000/studies
```

Swagger UI (auto-generated by FastAPI) is at http://localhost:8000/docs.

## Dashboard

`services/api/static/` is a small dashboard (plain HTML/CSS/JS, no framework) served by the same FastAPI service at `/dashboard/`. It shows the study list from `GET /studies` on the left, and clicking a row loads that study's detail on the right, including its preview image.

The dashboard's `<img>` tag points at `GET /studies/{id}/preview-image` instead of MinIO directly, since the `medimaging` bucket is private. That endpoint reads the study's `preview_object_path` from Postgres, then streams the object's bytes straight from MinIO through the API - the browser never needs MinIO credentials.

```text
http://localhost:8000/dashboard/
```

## Audit trail

Every read through the API (`/studies`, `/studies/{id}`, `/studies/{id}/preview-info`, `/studies/{id}/preview-image`) is logged to a Postgres table:

```text
audit_events
```

Columns: `event_id`, `user_id`, `action`, `study_id`, `timestamp`, `ip_address`, `status`. There's no real auth yet, so every event is logged under one fixed `user_id`: `demo-user`. `status` is `success` or `not_found`, depending on whether the study/preview existed.

```bash
docker exec postgres psql -U medimaging -d medimaging -c "SELECT * FROM audit_events ORDER BY event_id DESC LIMIT 10;"
curl http://localhost:8000/audit-events
```

The dashboard also shows the 50 most recent events in a table at the bottom of the page, refreshed after every study list load or detail click.
