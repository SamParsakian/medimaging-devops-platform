# Project Record

This record documents the build of a medical imaging DevOps platform, step by step. The project will grow from a basic imaging stack into a more complete platform, with DICOM handling, storage, security, monitoring, backup, and later deployment work.

## Step 0 - Verifying the Development Environment

In this step, the local machine was checked to make sure the basic tools for the project were already installed.

Required tools:

- Git
- Docker
- Docker Compose
- VS Code

Commands used:

```bash
git --version
docker --version
docker compose version
```

All three tools were found and working. Nothing was blocking the start of the actual build.

Screenshot:

![Tool versions confirmed](images/step-0-tool-versions.png)

## Step 1 - Base Docker Compose Stack

In this step, the first three real services were added to Docker Compose:

```text
orthanc
postgres
minio
```

Each service got a named Docker volume, a restart policy, and a basic health check.

Orthanc's config file was added at:

```text
infra/orthanc/orthanc.json
```

This file only holds non-secret settings, like the name and AE title. The login credentials are passed in as an environment variable at container start, so they are never committed to the repo.

A small SQL file was added for PostgreSQL:

```text
infra/postgres/init.sql
```

It creates a `studies` table to hold basic imaging metadata.

`infra/minio/README.md` explains what MinIO is for, even though nothing writes to it yet.

Commands used:

```bash
docker compose config
docker compose up -d
docker compose ps
docker volume ls
```

One problem came up: the Orthanc image does not include `curl`, so the health check kept failing even though the server was working fine. It was changed to use `python3` instead, which is available in the image.

All three containers came up healthy, each with its own Docker volume. Orthanc's REST API responded correctly with the configured login.

Screenshots:

![Docker containers running](images/step-1-docker-containers-running.png)

![Orthanc running](images/step-1-orthanc-login-or-dashboard.png)

![MinIO console](images/step-1-minio-console.png)

## Step 2 - Sample DICOM Upload

In this step, one small public test file was used to check that Orthanc actually receives and stores images.

```text
CT_small.dcm
```

This file comes from the pydicom project's test data. It is MIT licensed, already anonymized, and not real patient data.

A script downloads it and uploads it straight to Orthanc:

```text
scripts/upload-sample-dicom.sh
```

The file itself is not stored in this repo.

Commands used:

```bash
docker compose ps
./scripts/upload-sample-dicom.sh
curl -s -u orthanc:changeme http://localhost:8042/studies
```

The upload returned a success response, and the study showed up right away in Orthanc. The patient name and ID on the study are `CompressedSamples^CT1` and `1CT1`, the built-in test identity that ships with this file, not a real person.

Screenshot:

![Orthanc uploaded study with metadata](images/step-2-orthanc-uploaded-study.png)

## Step 3 - DICOM Metadata Extraction

In this step, the `studies` table in PostgreSQL was extended to hold real metadata instead of a placeholder:

```text
study_instance_uid
series_instance_uid
patient_id
patient_name
modality
study_date
study_description
series_count
instance_count
processing_status
```

The table was still empty, so it was safe to drop and recreate it with this new structure.

A Python script was added to do the actual extraction:

```text
services/metadata-extractor/extract.py
```

It reads the list of studies from Orthanc's REST API, pulls the relevant DICOM tags for each one, and writes or updates a matching row in PostgreSQL. This is a manual, one-shot script for now. No background job, no API, no queue.

The script runs on the host machine, not inside a container, so it connects to Orthanc and PostgreSQL through `localhost`. This uses `ORTHANC_HOST` and `POSTGRES_HOST` from `.env`.

Commands used:

```bash
docker compose ps
python3 -m venv services/metadata-extractor/.venv
./services/metadata-extractor/.venv/bin/pip install -r services/metadata-extractor/requirements.txt
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/extract.py
```

To check the result:

```bash
docker exec postgres psql -U medimaging -d medimaging -c "SELECT * FROM studies;"
```

Running the script against the demo study stored one row with patient `CompressedSamples^CT1`, modality `CT`, study date `2004-01-19`, 1 series, and 1 instance. This matches what Orthanc shows directly. Running the script again updated the same row instead of creating a new one.

Screenshots:

![Metadata extractor run](images/step-3-extractor-run.png)

![PostgreSQL studies row](images/step-3-postgres-studies-row.png)

## Step 4 - DICOM Anonymization

In this step, a basic anonymization step was added before future image processing work.

The goal was simple: before a DICOM file is used for preview generation, object storage, or AI testing, sensitive patient-related fields should be replaced with safe demo values.

This project only uses public demo data, not real patient data. Still, adding anonymization early makes the project closer to a real healthcare imaging workflow.

The anonymizer was added under:

```text
services/anonymizer/
```

The main files are:

```text
anonymize.py
verify.py
rules.py
```

The anonymization rules replace fields such as:

```text
PatientName
PatientID
PatientBirthDate
AccessionNumber
InstitutionName
ReferringPhysicianName
```

The generated anonymized DICOM file is written locally to:

```text
services/anonymizer/output/
```

This output folder is ignored by Git, so generated DICOM files are not committed to the repository.

For this first version, `StudyInstanceUID` was left unchanged. This made it easier to compare the anonymized copy with the original demo study. In a stronger real-world de-identification pipeline, this value would normally need more careful handling.

Commands used:

```bash
./services/anonymizer/.venv/bin/python services/anonymizer/anonymize.py
```

To check the original file:

```bash
./services/anonymizer/.venv/bin/python services/anonymizer/verify.py sample-data/downloads/CT_small.dcm
```

To check the anonymized file:

```bash
./services/anonymizer/.venv/bin/python services/anonymizer/verify.py services/anonymizer/output/anonymized_CT_small.dcm
```

The verification showed that the selected patient-related fields were replaced with demo values. The original file in Orthanc was not changed. The anonymization was tested only on a local copy of the demo DICOM file.

Screenshots:

![Anonymizer run output](images/step-4-anonymizer-run.png)

![Original DICOM tags](images/step-4-original-tags.png)

![Anonymized DICOM tags](images/step-4-anonymized-tags.png)

## Step 5 - Store Anonymized DICOM in MinIO

In this step, the anonymized DICOM file was uploaded to MinIO, as a processed imaging object.

A script was added under:

```text
services/minio-uploader/upload.py
```

It creates the bucket if it does not exist yet, then uploads the file. The bucket name is:

```text
medimaging
```

The object path pattern is:

```text
processed/anonymized/{study_uid}/{filename}
```

The study UID is read directly from the DICOM file itself, not typed in by hand.

Commands used:

```bash
docker compose ps
./services/anonymizer/.venv/bin/python services/anonymizer/anonymize.py
./services/minio-uploader/.venv/bin/python services/minio-uploader/upload.py
```

Running the script created the `medimaging` bucket and uploaded the file to:

```text
processed/anonymized/1.3.6.1.4.1.5962.1.2.1.20040119072730.12322/anonymized_CT_small.dcm
```

Running it a second time reused the existing bucket and just uploaded the file again to the same path. The object was also checked directly by listing the bucket's contents through the MinIO client.

Screenshot:

![MinIO console showing uploaded object](images/step-5-minio-object.png)

## Step 6 - Visual DICOM Preview

In this step, a PNG preview was generated from the anonymized DICOM file.

A script was added under:

```text
services/preview-generator/generate_preview.py
```

It reads the anonymized DICOM file from Step 4, applies the DICOM rescale slope/intercept plus simple windowing (`WindowCenter`/`WindowWidth` if present, otherwise a min/max stretch), and saves an 8-bit grayscale PNG with Pillow. Raw CT pixel values aren't 0-255 by default, so without this step the image would just render as solid black or white.

The PNG is written to:

```text
services/preview-generator/output/
```

This folder is git-ignored, same as the anonymizer's output folder.

A second script uploads the PNG to MinIO:

```text
services/preview-generator/upload_preview.py
```

It reads the study UID from the source DICOM file, not the PNG, and uploads to:

```text
processed/previews/{study_uid}/preview_CT_small.png
```

Commands used:

```bash
docker compose ps
./services/preview-generator/.venv/bin/python services/preview-generator/generate_preview.py
./services/preview-generator/.venv/bin/python services/preview-generator/upload_preview.py
```

The generator produced a 128x128 grayscale PNG. Opening it locally showed a clear CT cross-section, confirming the windowing worked. Listing the MinIO bucket confirmed the preview sits next to the Step 5 anonymized DICOM object.

Screenshots:

![Preview PNG opened locally](images/step-6-preview-local.png)

![MinIO console showing the preview object](images/step-6-minio-preview-object.png)

## Step 6B - Better Visual DICOM Sample

In this step, a bigger, clearer public DICOM sample replaced `CT_small.dcm` as input to the preview pipeline. `CT_small.dcm` is only 128x128, so its preview came out tiny.

A second sample was added: `examples_overlay.dcm`, also one of pydicom's bundled test files. It's a cropped copy of a real Siemens abdominal MR slice, originally from the GDCM project (BSD-style license), 300x484 pixels. Source and license details are in `docs/sample-data.md`.

A download script was added:

```text
scripts/download-better-dicom-sample.sh
```

It downloads the file into `sample-data/downloads/` (git-ignored) and does not touch Orthanc.

The raw file's `InstitutionName` tag was `AKH - WIEN`, a real hospital name. Running the Step 4 anonymizer on it replaced this with `Demo Institution`, the same as it does for `CT_small.dcm`.

`services/preview-generator/upload_preview.py` was updated to work out the matching anonymized DICOM file from whatever PNG path it's given, instead of a hardcoded filename, so the same script works for both samples.

Commands used:

```bash
docker compose ps
./scripts/download-better-dicom-sample.sh
./services/anonymizer/.venv/bin/python services/anonymizer/anonymize.py sample-data/downloads/examples_overlay.dcm
./services/preview-generator/.venv/bin/python services/preview-generator/generate_preview.py services/anonymizer/output/anonymized_examples_overlay.dcm
./services/preview-generator/.venv/bin/python services/preview-generator/upload_preview.py services/preview-generator/output/preview_examples_overlay.png
```

The new PNG (300x484) shows a real anatomical image - liver, kidneys, spine, and aorta are all visible. Listing the bucket confirmed all three processed objects sit side by side: the Step 5 anonymized DICOM, the Step 6 CT preview, and the new MR preview.

Screenshot:

![Better DICOM preview showing visible anatomy](images/step-6b-better-dicom-preview.png)

## Step 7 - FastAPI Study API

In this step, a small read-only API was added in front of the `studies` table.

A new service was added under:

```text
services/api/
```

It's a FastAPI app (`main.py`, `Dockerfile`, `requirements.txt`). It connects to PostgreSQL using the `postgres` service name, the same pattern the other containers already use.

It was added to `docker-compose.yml` as a fourth service:

```yaml
api:
  build:
    context: ./services/api
  container_name: api
  restart: unless-stopped
  ports:
    - "${API_PORT:-8000}:8000"
  environment:
    POSTGRES_HOST: postgres
    POSTGRES_PORT: 5432
    POSTGRES_DB: ${POSTGRES_DB}
    POSTGRES_USER: ${POSTGRES_USER}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
  depends_on:
    postgres:
      condition: service_healthy
```

Four endpoints:

```text
GET /health
GET /studies
GET /studies/{orthanc_study_id}
GET /studies/{orthanc_study_id}/preview-info
```

`preview-info` needed somewhere to read the MinIO object path from, so a `preview_object_path` column was added to the `studies` table:

```sql
ALTER TABLE studies ADD COLUMN IF NOT EXISTS preview_object_path TEXT;
```

This was run directly against the live database, and also added to `infra/postgres/init.sql` for fresh setups.

A small script fills that column in:

```text
services/metadata-extractor/set_preview_path.py
```

It takes an optional study UID and object path, and updates the matching row. No auth, no RBAC, no dashboard, no AI were added, per the task.

Commands used:

```bash
docker exec postgres psql -U medimaging -d medimaging -c "ALTER TABLE studies ADD COLUMN IF NOT EXISTS preview_object_path TEXT;"
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/set_preview_path.py
docker compose up -d --build api
curl http://localhost:8000/health
curl http://localhost:8000/studies
curl http://localhost:8000/studies/{orthanc_study_id}
curl http://localhost:8000/studies/{orthanc_study_id}/preview-info
```

The API was checked manually through the browser: Swagger UI lists all four endpoints, `/studies` shows the real demo study with its `preview_object_path`, and `/studies/{id}/preview-info` shows that same path with `"available": true`. A bad study ID was also tried and correctly returned a 404. The results are shown in the screenshots below.

Screenshots:

![Swagger UI listing all endpoints](images/step-7-swagger-ui.png)

![GET /studies response](images/step-7-studies-response.png)

![GET /studies/{id}/preview-info response](images/step-7-preview-info-response.png)

## Step 8 - Simple Imaging Dashboard

In this step, a small dashboard was added so studies can be browsed visually instead of through curl or Swagger.

It's served by the same FastAPI service, as static files under:

```text
services/api/static/
```

Files:

```text
index.html
style.css
app.js
```

Plain HTML, CSS, and vanilla JavaScript - no framework. The files are served by mounting this folder in `main.py`:

```python
app.mount("/dashboard", StaticFiles(directory="static", html=True), name="dashboard")
```

The page fetches `GET /studies` to build a table on the left. Clicking a row fetches `GET /studies/{id}` and `GET /studies/{id}/preview-info` and fills in a detail panel on the right, including the preview image.

MinIO's bucket is private, so the browser can't load the preview image directly from MinIO. A new endpoint streams it through the API instead:

```python
@app.get("/studies/{study_id}/preview-image")
def get_preview_image(study_id: str):
    study = fetch_study(study_id)
    object_path = study["preview_object_path"]
    if not object_path:
        raise HTTPException(status_code=404, detail="No preview available for this study")

    client = get_minio_client()
    try:
        response = client.get_object(MINIO_BUCKET, object_path)
    except S3Error as exc:
        raise HTTPException(status_code=404, detail="Preview object not found in MinIO") from exc

    def iter_content():
        try:
            yield from response.stream(32 * 1024)
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(iter_content(), media_type="image/png")
```

It reads the study's `preview_object_path` from Postgres, then streams the PNG bytes straight from MinIO. The dashboard's `<img>` tag just points at this endpoint, so the browser never needs MinIO credentials.

`docker-compose.yml`'s `api` service was given MinIO connection details for this:

```yaml
MINIO_HOST: minio
MINIO_PORT: 9000
MINIO_ROOT_USER: ${MINIO_ROOT_USER}
MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
MINIO_BUCKET: ${MINIO_BUCKET}
```

Commands used:

```bash
docker compose up -d --build api
curl http://localhost:8000/dashboard/
curl http://localhost:8000/studies/8a8cf898-ca27c490-d0c7058c-929d0581-2bbf104d/preview-image --output test.png
file test.png
```

The dashboard was checked manually through the browser at `http://localhost:8000/dashboard/`: the study list loaded with the demo study's Orthanc ID, modality, date, patient ID, status, and preview availability, and clicking it opened the detail panel with the preview image rendered inline and the MinIO object path shown as a technical detail. The `docker compose up -d --build api` rebuild was also checked directly in the terminal. The results are shown in the screenshots below.

Screenshots:

![Dashboard showing the study list and the selected study's detail panel with its preview image](images/step-8-dashboard.png)

![Terminal output of docker compose up -d --build api rebuilding and starting the api container](images/step-8-docker-build.png)
