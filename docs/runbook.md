# Operations Runbook

A practical checklist for when something on this local stack isn't working. Each section is: what you'd notice, what to check, and what usually fixes it. This is a demo-grade local stack, not a production on-call rotation, so the fixes here are mostly "restart it" and "look at the logs" - there's no paging, no SLAs, no auto-remediation.

Start with the basics before jumping into a specific incident below:

```bash
docker compose ps
docker compose logs <service> --tail 50
```

`docker compose ps` shows every container and whether Docker considers it healthy. `docker compose logs <service>` (`orthanc`, `postgres`, `minio`, `api`, `prometheus`, or `grafana`) shows that one container's recent output - for `api`, this includes the structured JSON logs from every request.

## Where to check things

| What | Where | Notes |
|---|---|---|
| Study list, previews | `http://localhost:8000/dashboard/?api_key=<key>` | The dashboard needs the key in the URL once |
| API shape / try requests | `http://localhost:8000/docs` | Swagger UI, no key needed to view it |
| Metrics, targets, alerts | `http://localhost:9090` | Prometheus - `/targets`, `/rules`, `/alerts` |
| Dashboards | `http://localhost:3000` | Grafana - log in with `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD` from `.env` |
| Container logs | `docker compose logs <service>` | Add `-f` to follow live, `--tail 50` to limit |
| Studies / audit data | `docker exec postgres psql -U medimaging -d medimaging` | See queries throughout this doc |
| Uploaded files, previews | `http://localhost:9001` | MinIO console, log in with `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` |

## API is down

**Notice:** dashboard/Swagger won't load, `curl http://localhost:8000/health` fails, or Prometheus's Targets page shows the `api` job as down.

```bash
docker compose ps api
docker compose logs api --tail 50
curl http://localhost:8000/health
```

Usually a crash on startup (bad `.env` value, Postgres/MinIO not ready yet) or the container just never started. Fix:

```bash
docker compose up -d --build api
```

If it keeps crash-looping, the log right before the restart is almost always the reason (missing env var, Postgres unreachable, etc.).

## Orthanc is down

**Notice:** `http://localhost:8042` won't load, DICOM upload fails, metadata extraction can't reach Orthanc.

```bash
docker compose ps orthanc
docker compose logs orthanc --tail 50
```

Fix:

```bash
docker compose up -d orthanc
```

Check `ORTHANC_USER` / `ORTHANC_PASSWORD` in `.env` match what's actually configured if login fails through the web UI or a script.

## PostgreSQL is down

**Notice:** the API returns 500s, any script talking to Postgres fails to connect, `docker compose ps` shows `postgres` unhealthy.

```bash
docker compose ps postgres
docker compose logs postgres --tail 50
docker exec postgres pg_isready -U medimaging -d medimaging
```

Fix:

```bash
docker compose up -d postgres
```

If it won't start at all, check disk space first - a full disk is the most common reason a database container refuses to come up.

## MinIO is down

**Notice:** preview images won't load, uploads fail, `http://localhost:9001` won't load.

```bash
docker compose ps minio
docker compose logs minio --tail 50
docker exec minio mc ready local
```

Fix:

```bash
docker compose up -d minio
```

## Prometheus/Grafana is down

**Notice:** `http://localhost:9090` or `http://localhost:3000` won't load, Grafana panels show "No data" even though the API is fine.

```bash
docker compose ps prometheus grafana
docker compose logs prometheus --tail 50
docker compose logs grafana --tail 50
```

Fix:

```bash
docker compose up -d prometheus grafana
```

If Grafana comes up but the dashboard has no datasource, check `infra/monitoring/grafana/provisioning/datasources/prometheus.yml` is still mounted and the container was actually recreated (not just restarted) after any change to it.

## DICOM upload fails

**Notice:** `scripts/upload-sample-dicom.sh` or a manual upload to Orthanc returns an error instead of the new instance's ID.

```bash
docker compose logs orthanc --tail 50
curl -u orthanc:<password> http://localhost:8042/system
```

Common causes: Orthanc isn't up yet (see above), wrong `ORTHANC_USER`/`ORTHANC_PASSWORD`, or the file being uploaded isn't a valid DICOM file at all.

## Metadata extraction fails

**Notice:** `extract.py` prints an `extract_study` event with `"status": "failed"`, or the study never shows up in `GET /studies`.

```bash
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/extract.py
docker exec postgres psql -U medimaging -d medimaging -c "SELECT orthanc_study_id, processing_status, last_error FROM studies;"
```

`last_error` has the exact reason. Usually Orthanc being unreachable (see above) or a study missing an expected DICOM tag.

## Anonymization fails

**Notice:** `anonymize.py` exits with an error, or `anonymization_status` shows `failed`.

```bash
./services/anonymizer/.venv/bin/python services/anonymizer/anonymize.py
docker exec postgres psql -U medimaging -d medimaging -c "SELECT orthanc_study_id, anonymization_status, last_error FROM studies;"
```

Common cause: the input DICOM file is missing, corrupted, or missing `StudyInstanceUID` entirely (pydicom can't read it far enough to even find the study).

## Preview generation fails

**Notice:** `generate_preview.py` exits with an error, or `preview_status` shows `failed`.

```bash
./services/preview-generator/.venv/bin/python services/preview-generator/generate_preview.py
docker exec postgres psql -U medimaging -d medimaging -c "SELECT orthanc_study_id, preview_status, last_error FROM studies;"
```

Common cause: the anonymized file doesn't exist yet (run the anonymizer first), or the file's pixel data is incomplete/corrupted - pydicom's own error message says this directly (e.g. "number of bytes of pixel data is less than expected").

## MinIO upload fails

**Notice:** `upload.py` or `upload_preview.py` exits with an error, or `upload_status` shows `failed`.

```bash
docker exec minio mc ready local
docker exec postgres psql -U medimaging -d medimaging -c "SELECT orthanc_study_id, upload_status, last_error FROM studies;"
```

Common cause: MinIO is down (see above), or the file being uploaded (anonymized DICOM or preview PNG) doesn't exist yet because an earlier pipeline stage hasn't run or failed.

## Backup fails

**Notice:** `scripts/backup/backup.sh` exits with an error partway through.

```bash
docker compose ps postgres minio orthanc
ls -la scripts/backup/output/
```

`backup.sh` needs Postgres, MinIO, and Orthanc all up and healthy - it stops on the first failing command. Check disk space if it fails while writing the Orthanc tarball, since that's usually the largest file.

## Restore check fails

**Notice:** `scripts/backup/restore.sh` errors out, or the data doesn't look right after a restore.

```bash
ls scripts/backup/output/
docker compose ps postgres minio
```

Make sure the backup folder passed as an argument actually exists and has `postgres.sql` and a `minio/` folder inside it. After restoring, verify the data actually came back:

```bash
docker exec postgres psql -U medimaging -d medimaging -c "SELECT COUNT(*) FROM studies;"
docker exec minio mc ls local/medimaging/processed/previews --recursive
```

See `docs/backup-restore.md` for the full restore process, including Orthanc's manual-only restore.

## Alert is firing

**Notice:** the Prometheus Alerts page (`http://localhost:9090/alerts`) shows something other than all-inactive.

```text
http://localhost:9090/alerts
```

There's no Alertmanager and no email/Slack notification - the Alerts page itself is the only place a firing alert shows up, so it has to be checked directly. Match the alert name to the relevant section above:

```text
APITargetDown             -> "API is down"
HighFailedProcessingCount -> whichever pipeline stage's last_error is set (check the studies table)
NoStudiesAvailable        -> run the metadata extractor, or check why it hasn't run
HighAPIErrorRate          -> docker compose logs api, look for repeated 4xx/5xx lines
```
