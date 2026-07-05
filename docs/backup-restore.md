# Backup and Restore

Two scripts, both run on the host with the stack up (`docker compose up -d`):

```text
scripts/backup/backup.sh
scripts/backup/restore.sh
```

This is demo-grade backup/restore for a local single-machine stack, not a production strategy - no encryption, no offsite copies, no scheduling.

## What gets backed up

`backup.sh` creates a timestamped folder under `scripts/backup/output/` (git-ignored - nothing here is ever committed) containing:

- `postgres.sql` - a full `pg_dump` of the PostgreSQL database (`studies`, `audit_events`), with `--clean --if-exists` so restoring it cleanly drops and recreates the tables.
- `minio/` - every object in the `medimaging` MinIO bucket, copied out with `mc mirror`.
- `orthanc-storage.tar.gz` - a tarball of Orthanc's storage volume (its DICOM files and internal index).

```bash
./scripts/backup/backup.sh
```

## What gets restored

`restore.sh` takes a backup folder as its one argument and restores:

- PostgreSQL, by piping `postgres.sql` back into `psql`.
- MinIO, by mirroring the backed-up objects back into the bucket.

```bash
./scripts/backup/restore.sh scripts/backup/output/<timestamp>
```

It asks for a `y`/`N` confirmation first, since it overwrites current data.

## Orthanc restore - manual only

`restore.sh` does not automatically restore Orthanc's storage. Orthanc keeps an internal SQLite index alongside the DICOM files, and that index has to be consistent with whatever's on disk - restoring the files while Orthanc is running risks corrupting that index. Automating a safe restore would mean stopping the container, wiping the volume, extracting the tarball, and restarting, which is more moving parts than this demo project needs right now.

If Orthanc's data ever needs restoring, do it by hand:

```bash
docker compose stop orthanc
docker run --rm -v medimaging-devops-platform_orthanc-storage:/data -v "$(pwd)/scripts/backup/output/<timestamp>:/backup" alpine sh -c "rm -rf /data/* && tar xzf /backup/orthanc-storage.tar.gz -C /data"
docker compose start orthanc
```

Check the actual volume name first with `docker volume ls | grep orthanc-storage` - it may differ from the example above depending on the Docker Compose project name.

## Verifying a restore

After running `restore.sh`, check the data is actually back:

```bash
docker exec postgres psql -U medimaging -d medimaging -c "SELECT COUNT(*) FROM studies;"
docker exec postgres psql -U medimaging -d medimaging -c "SELECT COUNT(*) FROM audit_events;"
docker exec minio mc ls local/medimaging/processed/previews --recursive
curl -H "X-API-Key: changeme" http://localhost:8000/studies
```
