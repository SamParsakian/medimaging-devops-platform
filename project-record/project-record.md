# Project Record

This record documents the build of a medical imaging DevOps platform, step by step. The project is planned to grow from a basic imaging stack into a more complete platform, including DICOM handling, storage, security, monitoring, backup, and later deployment-related work.

## Step 0 — Verifying the Development Environment

Before the platform was built, the local environment was checked to confirm that the basic tools needed for the project were installed.

Required tools for the first steps:

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

Screenshot:

![Tool versions confirmed](images/step-0-tool-versions.png)

All three tools were found installed and working, so nothing was blocking the start of the actual build.

## Step 1 — Base Docker Compose Stack

The Docker Compose file was filled in with the first three real services: Orthanc for DICOM storage, PostgreSQL for imaging metadata, and MinIO for object storage. Each service was given a named volume, a restart policy, and a basic health check.

A minimal Orthanc config file was added at `infra/orthanc/orthanc.json` for non-secret settings like the name and AE title, while the actual login credentials are passed in through an environment variable at container start so they never end up committed to the repo. A small `init.sql` script was added for PostgreSQL, creating a `studies` table to hold basic imaging metadata. `infra/minio/README.md` explains what MinIO is for, even though nothing writes to it yet.

Commands used:

```bash
docker compose config
docker compose up -d
docker compose ps
docker volume ls
```

One problem came up along the way: the Orthanc image doesn't ship with `curl`, so the health check that was written for it kept failing even though the server itself was working fine. It was rewritten to use `python3`, which is available in the image, with a small script that sends an authenticated request instead.

All three containers ended up running and healthy, each with its own Docker volume, and Orthanc's REST API responded correctly once queried with the configured credentials.

Screenshots:

![Docker containers running](images/step-1-docker-containers-running.png)
![Orthanc running](images/step-1-orthanc-login-or-dashboard.png)
![MinIO console](images/step-1-minio-console.png)

## Step 2 — Sample DICOM Upload

To check that Orthanc actually receives and stores images, one small public test file was used: `CT_small.dcm` from the pydicom project's test data (MIT licensed, already anonymized, not real patient data). A script, `scripts/upload-sample-dicom.sh`, downloads it on the fly and uploads it straight to Orthanc through its REST API. The file itself is not stored in this repo.

Commands used:

```bash
docker compose ps
./scripts/upload-sample-dicom.sh
curl -s -u orthanc:changeme http://localhost:8042/studies
```

The upload came back with `"Status": "Success"`, and the study showed up right away when querying Orthanc's `/studies` endpoint. Checking the study's details showed a patient named `CompressedSamples^CT1` with patient ID `1CT1` — the well-known synthetic identity that ships with this test file, not a real person.

Screenshot:

![Orthanc uploaded study with metadata](images/step-2-orthanc-uploaded-study.png)
