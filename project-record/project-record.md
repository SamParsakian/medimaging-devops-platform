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
