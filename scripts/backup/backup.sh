#!/usr/bin/env bash
# Backs up PostgreSQL, the MinIO bucket, and Orthanc's storage volume
# into a timestamped folder under scripts/backup/output/ (git-ignored).
# Demo-grade: good enough to restore this local stack, not a
# production backup strategy.
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

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="scripts/backup/output/${TIMESTAMP}"
mkdir -p "$BACKUP_DIR"

echo "Backing up PostgreSQL..."
docker exec postgres pg_dump -U "$POSTGRES_USER" --clean --if-exists "$POSTGRES_DB" > "$BACKUP_DIR/postgres.sql"

echo "Backing up MinIO bucket '$MINIO_BUCKET'..."
docker exec minio mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
docker exec minio rm -rf /tmp/medimaging-backup
docker exec minio mc mirror --quiet "local/$MINIO_BUCKET" /tmp/medimaging-backup
docker cp minio:/tmp/medimaging-backup "$BACKUP_DIR/minio"
docker exec minio rm -rf /tmp/medimaging-backup

echo "Backing up Orthanc storage..."
docker exec orthanc tar czf /tmp/orthanc-storage.tar.gz -C /var/lib/orthanc/db .
docker cp orthanc:/tmp/orthanc-storage.tar.gz "$BACKUP_DIR/orthanc-storage.tar.gz"
docker exec orthanc rm -f /tmp/orthanc-storage.tar.gz

echo
echo "Backup complete: $BACKUP_DIR"
du -sh "$BACKUP_DIR"/* 2>/dev/null
