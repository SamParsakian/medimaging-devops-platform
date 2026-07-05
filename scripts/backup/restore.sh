#!/usr/bin/env bash
# Restores PostgreSQL and the MinIO bucket from a backup folder created
# by backup.sh. Orthanc's storage is NOT auto-restored here - see
# docs/backup-restore.md for why, and the manual steps if you need it.
set -euo pipefail

cd "$(dirname "$0")/../.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-medimaging}"
POSTGRES_DB="${POSTGRES_DB:-medimaging}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-changeme}"
MINIO_BUCKET="${MINIO_BUCKET:-medimaging}"

BACKUP_DIR="${1:-}"

if [ -z "$BACKUP_DIR" ] || [ ! -d "$BACKUP_DIR" ]; then
  echo "Usage: $0 scripts/backup/output/<timestamp>"
  echo
  echo "Available backups:"
  ls -1 scripts/backup/output 2>/dev/null || echo "  (none found)"
  exit 1
fi

echo "This will overwrite the current PostgreSQL data (studies, audit_events)"
echo "and add/update MinIO objects, using the backup at: $BACKUP_DIR"
read -r -p "Continue? [y/N] " CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
  echo "Aborted, nothing was changed."
  exit 1
fi

echo "Restoring PostgreSQL..."
docker exec -i postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$BACKUP_DIR/postgres.sql"

echo "Restoring MinIO bucket '$MINIO_BUCKET'..."
docker exec minio mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
docker exec minio rm -rf /tmp/medimaging-restore
docker cp "$BACKUP_DIR/minio" minio:/tmp/medimaging-restore
docker exec minio mc mirror --quiet --overwrite /tmp/medimaging-restore "local/$MINIO_BUCKET"
docker exec minio rm -rf /tmp/medimaging-restore

echo
echo "Restore complete. Verify with:"
echo "  docker exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c 'SELECT COUNT(*) FROM studies;'"
echo "  docker exec minio mc ls local/$MINIO_BUCKET/processed/previews --recursive"
