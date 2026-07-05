#!/usr/bin/env bash
# Backs up PostgreSQL, the MinIO bucket, and Orthanc's storage volume
# into a timestamped folder under scripts/backup/output/ (git-ignored).
# Demo-grade: good enough to restore this local stack, not a
# production backup strategy.
set -euo pipefail

# Prints one JSON line per event, so the run's structured logs show up in
# the terminal this script is run from. No Loki/Grafana yet.
log_event() {
  local action="$1" status="$2" error="${3:-}"
  local level="INFO"
  [ "$status" = "failed" ] && level="ERROR"
  local timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ -n "$error" ]; then
    printf '{"timestamp":"%s","level":"%s","service":"backup","action":"%s","study_id":null,"status":"%s","error":"%s"}\n' \
      "$timestamp" "$level" "$action" "$status" "$error"
  else
    printf '{"timestamp":"%s","level":"%s","service":"backup","action":"%s","study_id":null,"status":"%s","error":null}\n' \
      "$timestamp" "$level" "$action" "$status"
  fi
}

trap 'log_event "backup_run" "failed" "command failed at line $LINENO: $BASH_COMMAND"' ERR

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

log_event "backup_run" "started"

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

log_event "backup_run" "done"
