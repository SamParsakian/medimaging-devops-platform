# Local Stack

Seven services make up the stack:

- **Orthanc** - the DICOM server (PACS). Receives, stores, and serves medical images, and exposes a REST API and web UI on top of the standard DICOM protocol.
- **PostgreSQL** - holds structured metadata about the imaging data (e.g. a reference table for studies), separate from the actual image files.
- **MinIO** - S3-compatible object storage, for anything file-based that isn't in Orthanc directly: processed/anonymized DICOM files today, previews, AI outputs, and backups later.
- **API** - a read-only FastAPI service in front of the `studies` table, so study metadata and preview info can be queried over HTTP instead of going straight to Postgres.
- **AI inference** - a separate FastAPI service that runs a small demo classifier over a study's preview image and returns a JSON result. CPU only, no trained neural network, no clinical use.
- **Prometheus** - scrapes and stores the API's metrics over time.
- **Grafana** - reads from Prometheus and shows those metrics on a dashboard.

## Local URLs

- Orthanc web UI / REST API: http://localhost:8042
- PostgreSQL: `localhost:5432`
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001
- API: http://localhost:8000 (Swagger UI at http://localhost:8000/docs)
- AI inference: http://localhost:8100 (Swagger UI at http://localhost:8100/docs)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

Credentials for all three storage services come from `.env` (copy `.env.example` to get started). The API requires an API key on every endpoint except `/health` and `/metrics` - see "API key security" below.

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

Endpoints in front of the `studies` table (all require an API key except `/health`):

- `GET /health` - basic liveness check, public
- `GET /studies` - every study currently in the table
- `GET /studies/{orthanc_study_id}` - one study's metadata
- `GET /studies/{orthanc_study_id}/preview-info` - just the MinIO preview object path (and whether one exists) for that study
- `GET /studies/{orthanc_study_id}/preview-image` - streams the actual preview PNG from MinIO
- `GET /studies/{orthanc_study_id}/slices` - ordered list of slice previews, for a multi-slice series (see "Multi-slice series" below); empty for a single-image study
- `GET /studies/{orthanc_study_id}/slices/{slice_index}/preview-image` - streams one slice's preview PNG from MinIO
- `GET /audit-events` - the 50 most recent audit events

`PatientID` is always included in responses - this platform's rule is "no real patient data, ever," so every study it can ever hold is demo/anonymized data by definition.

```bash
docker compose up -d --build api
curl http://localhost:8000/health
curl -H "X-API-Key: changeme" http://localhost:8000/studies
```

Swagger UI (auto-generated by FastAPI) is at http://localhost:8000/docs (not protected, since it's just a dev convenience for reading the API shape).

## API key security

All endpoints except `/health`, `/docs`, `/openapi.json`, `/redoc`, and `/metrics` require a shared API key, set via `API_SECRET_KEY` in `.env`. This is demo-grade security - one fixed key, no users, no sessions, no OAuth, no RBAC. `/metrics` is public because Prometheus scrapes it automatically and doesn't have the key.

The key can be sent either as a header or a query parameter:

```text
X-API-Key: <key>
```

```text
?api_key=<key>
```

The query parameter exists because a plain `<img>` tag (used for the preview image) can't send a custom header - everything else in the dashboard's own JavaScript uses the header.

- Missing key -> `401 Missing API key`
- Wrong key -> `403 Invalid API key`
- Correct key -> the request goes through as normal

```bash
curl http://localhost:8000/studies
curl -H "X-API-Key: wrong" http://localhost:8000/studies
curl -H "X-API-Key: changeme" http://localhost:8000/studies
```

## Dashboard

`services/api/static/` is a small dashboard (plain HTML/CSS/JS, no framework) served by the same FastAPI service at `/dashboard/`. It shows the study list from `GET /studies` on the left, and clicking a row loads that study's detail on the right, including its preview image.

The dashboard's `<img>` tag points at `GET /studies/{id}/preview-image` instead of MinIO directly, since the `medimaging` bucket is private. That endpoint reads the study's `preview_object_path` from Postgres, then streams the object's bytes straight from MinIO through the API - the browser never needs MinIO credentials.

Since the dashboard is also behind the API key now, open it with the key in the URL once:

```text
http://localhost:8000/dashboard/?api_key=changeme
```

The page reads the key from its own URL and attaches it to every API call it makes after that.

## AI inference

`services/ai-inference/` is a separate FastAPI service, its own container, that takes a preview image already stored in MinIO and returns a JSON result. It runs on CPU only - no GPU, no model training, and no external AI service is called.

The classifier itself (`services/ai-inference/main.py`, function `classify_pixels`) is based on pixel-intensity statistics: it converts the image to grayscale, measures how much its pixel intensities vary relative to their average brightness, and buckets that into one of three labels:

```text
low_variation_region
moderate_variation_region
high_variation_region
```

It has its own endpoints:

```text
GET  /health   - container healthcheck
POST /infer    - body: {"object_path": "processed/previews/.../preview_x.png"}
```

```bash
curl -X POST http://localhost:8100/infer \
  -H "Content-Type: application/json" \
  -d '{"object_path": "processed/previews/<study-uid>/<preview-file>.png"}'
```

The API service never needs MinIO credentials handed to a caller for this - a new endpoint, `POST /studies/{id}/infer`, looks up that study's own `preview_object_path` and proxies the call to the ai-inference service, the same "API is the only thing that talks to MinIO directly" pattern used everywhere else in this project. It's behind the same API key as every other non-public endpoint.

```bash
curl -X POST -H "X-API-Key: changeme" http://localhost:8000/studies/<orthanc-study-id>/infer
```

Every response, from either endpoint, includes the same fields:

```text
model_name             - "demo-image-stat-classifier"
model_version          - "0.1.0"
input_object           - the MinIO object path that was analyzed
prediction_label       - one of the three labels above
confidence             - 0-1, how far the measured variation sits from a label boundary
inference_time_ms      - how long the classification itself took
disclaimer             - "Technical demo only. Not for clinical diagnosis."
```

The dashboard's Study Detail panel has a "Run AI Demo Inference" button under the preview image, which calls the API's proxy endpoint and shows the same fields, disclaimer included. The ai-inference container itself has no API key check of its own - it isn't meant to be reached directly outside the demo, only through the API's proxy endpoint.

## Storing AI results

Every time `POST /studies/{id}/infer` gets a result back from ai-inference, it saves that result as a new row in a Postgres table before returning it, so a study's AI history isn't lost between requests:

```sql
CREATE TABLE IF NOT EXISTS ai_results (
    result_id SERIAL PRIMARY KEY,
    orthanc_study_id TEXT NOT NULL,
    input_object TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prediction_label TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    inference_time_ms DOUBLE PRECISION NOT NULL,
    disclaimer TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

A new endpoint lists every result stored for a study, newest first:

```bash
curl -H "X-API-Key: changeme" http://localhost:8000/studies/<orthanc-study-id>/ai-results
```

The dashboard's Study Detail panel loads this list alongside everything else and shows the newest entry in the same result box the "Run AI Demo Inference" button uses, so the most recent AI result for a study is visible as soon as it's selected, not only right after clicking the button. A study with no stored result yet shows a plain "No AI result yet for this study" message instead.

## Multi-slice series

Every study up to this point has been a single DICOM instance - one slice, one preview. Step 18 added a real multi-slice series (see `docs/sample-data.md` for where it comes from) and the pieces needed to page through it.

A new table holds one row per slice preview, separate from the single `preview_object_path` column every other study already uses:

```text
study_slices
```

Columns: `id`, `orthanc_study_id`, `slice_index` (0-based order), `instance_number` (the real DICOM `InstanceNumber`, for display), `preview_object_path`. Most studies never get a row here at all - it's only populated for a series with more than one slice to page through.

The pipeline for a multi-slice series reuses every existing script exactly as-is, just run once per slice instead of once per study:

```bash
./scripts/download-multislice-mri-sample.sh
./scripts/upload-multislice-series-to-orthanc.sh
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/extract.py
./scripts/process-multislice-series.sh
```

`process-multislice-series.sh` loops the anonymizer, preview generator, and MinIO uploader over every downloaded slice, then calls a new script, `services/metadata-extractor/register_slice_previews.py`, which writes one `study_slices` row per slice.

In the dashboard, a study with slices registered gets Previous/Next buttons and a slider under its preview image instead of a single static picture. Clicking through calls `GET /studies/{id}/slices/{slice_index}/preview-image` for whichever slice is selected, the same streaming-from-MinIO approach the single-image `preview-image` endpoint already used. A study with no slices registered still shows its one preview image exactly as before - nothing changed for the existing single-slice studies.

## Audit trail

Every read through the API (`/studies`, `/studies/{id}`, `/studies/{id}/preview-info`, `/studies/{id}/preview-image`) is logged to a Postgres table:

```text
audit_events
```

Columns: `event_id`, `user_id`, `action`, `study_id`, `timestamp`, `ip_address`, `status`. Every event is logged under one fixed `user_id`: `demo-user`. `status` is `success` or `not_found`, depending on whether the study/preview existed.

```bash
docker exec postgres psql -U medimaging -d medimaging -c "SELECT * FROM audit_events ORDER BY event_id DESC LIMIT 10;"
curl -H "X-API-Key: changeme" http://localhost:8000/audit-events
```

The dashboard also shows the 50 most recent events in a table at the bottom of the page, refreshed after every study list load or detail click.

## Backup and restore

`scripts/backup/backup.sh` and `scripts/backup/restore.sh` back up and restore PostgreSQL and MinIO (Orthanc's storage is documented separately since it needs a manual step). See `docs/backup-restore.md` for the full details.

## Pipeline status tracking

Every study row in `studies` now tracks whether each stage of the pipeline succeeded, not just metadata extraction:

```text
processing_status      - metadata extraction (from Orthanc)
anonymization_status   - services/anonymizer/anonymize.py
preview_status         - services/preview-generator/generate_preview.py
upload_status          - services/minio-uploader/upload.py and upload_preview.py
last_error             - the error message from whichever stage last failed, if any
```

Each status is `pending`, `done`, or `failed`. These fields come back from `GET /studies` and `GET /studies/{id}` alongside the existing fields, and the dashboard's Study Detail panel shows all four as colored labels, with the error text underneath if one exists.

```bash
docker exec postgres psql -U medimaging -d medimaging -c "SELECT orthanc_study_id, anonymization_status, preview_status, upload_status, last_error FROM studies;"
curl -H "X-API-Key: changeme" http://localhost:8000/studies/8a8cf898-ca27c490-d0c7058c-929d0581-2bbf104d
```

## Structured logging

The API and every pipeline script (metadata extractor, anonymizer, preview generator, preview uploader, MinIO uploader) print one JSON object per line for each event, instead of (or alongside) plain text. Each line has the same core fields:

```text
timestamp   - UTC, ISO 8601
level       - INFO or ERROR (WARNING for a rejected API key)
service     - api, metadata-extractor, anonymizer, preview-generator, minio-uploader, backup, restore
action      - what happened, e.g. http_request, view_study, extract_study, anonymize_file
study_id    - the study this event is about, or null if not applicable
status      - success, failed, not_found, started, done, unauthorized, forbidden, aborted
error       - the error message if status is failed, otherwise null
```

Extra fields are added per action where useful (`method`/`path`/`status_code`/`duration_ms` for API requests, `input_path`/`output_path`/`object_name` for pipeline steps). This is plain JSON on stdout - there's no Loki yet, so these logs aren't shipped anywhere or searchable outside the terminal. Grafana (see "Monitoring" below) only reads metrics so far, not these logs. It's readable directly through Docker Compose for the API service:

```bash
docker compose logs api
```

and directly in the terminal for the pipeline scripts, since those still run manually on the host:

```bash
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/extract.py
```

`scripts/backup/backup.sh` and `scripts/backup/restore.sh` print the same kind of JSON line at start, end, and on failure (`backup_run`/`restore_run` actions), using a small shell function instead of Python.

## Monitoring

Prometheus and Grafana were added as two more containers in `docker-compose.yml`. Prometheus scrapes metrics on a timer and stores them; Grafana reads from Prometheus and draws them on a dashboard. Neither of them touches the structured logs from the section above - that's a separate concern, for later.

Prometheus's config lives at `infra/monitoring/prometheus/prometheus.yml` and defines two scrape targets:

```yaml
scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: api
    metrics_path: /metrics
    static_configs:
      - targets: ["api:8000"]
```

The API exposes a `GET /metrics` endpoint (using the `prometheus-client` Python library) with these metrics:

```text
http_requests_total            - counter, labeled by method, path, and status code
http_request_duration_seconds  - histogram of how long each request took
studies_total                  - gauge, current row count in the studies table
studies_failed_total           - gauge, studies with at least one failed pipeline stage
process_start_time_seconds     - when the API process started (built into prometheus-client), used to derive uptime
```

`studies_total` and `studies_failed_total` are refreshed from Postgres every time Prometheus scrapes `/metrics`, so they're never stale. `/metrics` doesn't require the API key, since Prometheus has no way to send one, and it isn't counted as API traffic itself (same treatment as `/health`).

```bash
curl http://localhost:8000/metrics
```

Prometheus's own web UI, at http://localhost:9090, has a Targets page (**Status → Targets**) that shows whether each scrape target is reachable:

```text
http://localhost:9090/targets
```

Grafana, at http://localhost:3000, comes pre-configured with no manual setup needed: its Prometheus datasource and one dashboard, "Imaging API Overview," are both provisioned automatically from files under `infra/monitoring/grafana/provisioning/` and `infra/monitoring/grafana/dashboards/` when the container starts. The dashboard has six panels: API Up, Service Health (up, across every scrape target), Failed Processing Count, Total API Requests, Average Request Duration, and Studies Total.

```bash
docker compose up -d --build
```

Log in to Grafana with the admin credentials from `.env` (`GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`).

No Loki was added in this step. Alert rules were added in the next step, "Alerting" below.

## Alerting

Prometheus can evaluate rules on its own and show which ones are firing, without needing a separate Alertmanager - that's what this step uses, since there's no email or Slack notification to send anywhere yet. The rules live at `infra/monitoring/prometheus/alerts.yml` and are loaded by `prometheus.yml`:

```yaml
rule_files:
  - /etc/prometheus/alerts.yml
```

Four alerts are defined:

```text
APITargetDown          - fires if Prometheus can't scrape the API for 30 seconds
HighFailedProcessingCount - fires if any study has a failed pipeline stage, for 1 minute
NoStudiesAvailable      - fires if the studies table is empty, for 2 minutes
HighAPIErrorRate        - fires if over half of API requests in the last 5 minutes weren't 2xx, for 2 minutes
```

Each alert has a `for` duration so a single blip doesn't trigger it immediately - the underlying condition has to stay true for that whole window first. Prometheus's own web UI shows both the rule definitions and their live state:

```text
http://localhost:9090/rules
http://localhost:9090/alerts
```

The Rules page shows every rule that's loaded, its query, and whether it's currently healthy. The Alerts page shows the live state of each one: inactive, pending (condition is true but hasn't been true long enough yet), or firing.

No Alertmanager and no email/Slack notifications were added - an alert firing is only visible by looking at the Prometheus UI itself, which is enough for a local demo.

## Continuous integration

`.github/workflows/ci.yml` runs a few basic checks on every push and pull request, using only safe demo values (copied from `.env.example`) - no real secrets are needed to run CI:

```text
docker compose config          - the compose file and its env var substitutions are valid
bash -n on every script         - every shell script parses without syntax errors
python -m compileall             - every Python file parses without syntax errors
pytest tests/                    - a handful of small unit tests on pure logic
```

The same checks can be run on the host before pushing, the same way CI runs them:

```bash
cp .env.example .env
docker compose config
for f in $(find scripts -name "*.sh"); do bash -n "$f"; done
pip install pytest
for req in services/*/requirements.txt; do pip install -r "$req"; done
python -m compileall services scripts
pytest tests/ -v
```

No Docker images are published and nothing is deployed yet - this is just catching broken syntax and broken config before it reaches `main`.
