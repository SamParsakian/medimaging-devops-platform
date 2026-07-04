# Local Stack

Three services make up the base stack:

- **Orthanc** - the DICOM server (PACS). Receives, stores, and serves medical images, and exposes a REST API and web UI on top of the standard DICOM protocol.
- **PostgreSQL** - holds structured metadata about the imaging data (e.g. a reference table for studies), separate from the actual image files.
- **MinIO** - S3-compatible object storage, for anything file-based that isn't a raw DICOM image: processed previews, AI outputs, and backups, added in later steps.

## Local URLs

- Orthanc web UI / REST API: http://localhost:8042
- PostgreSQL: `localhost:5432`
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001

Credentials for all three come from `.env` (copy `.env.example` to get started).

## Metadata extractor

`services/metadata-extractor/extract.py` is a small script, run manually on the host, that reads studies from Orthanc's REST API and stores their metadata in the PostgreSQL `studies` table. Since it runs on the host rather than inside Docker Compose, it connects using `localhost` (via `ORTHANC_HOST` and `POSTGRES_HOST` in `.env`) instead of the container service names.

```bash
cd services/metadata-extractor
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cd ../..
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/extract.py
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
