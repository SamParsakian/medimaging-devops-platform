#!/usr/bin/env bash
# Uploads every slice downloaded by download-multislice-mri-sample.sh to
# the local Orthanc instance, one instance at a time, the same way
# upload-sample-dicom.sh does for a single file. Since every slice shares
# the same StudyInstanceUID and SeriesInstanceUID, Orthanc groups them
# into one study with one series automatically - there's no separate
# "create a series" step.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

ORTHANC_HTTP_PORT="${ORTHANC_HTTP_PORT:-8042}"
ORTHANC_USER="${ORTHANC_USER:-orthanc}"
ORTHANC_PASSWORD="${ORTHANC_PASSWORD:-changeme}"

SRC_DIR="sample-data/downloads/multislice-mri"

if [ ! -d "$SRC_DIR" ] || [ -z "$(ls -A "$SRC_DIR" 2>/dev/null)" ]; then
  echo "No files found in $SRC_DIR"
  echo "Run ./scripts/download-multislice-mri-sample.sh first."
  exit 1
fi

for f in "$SRC_DIR"/*.dcm; do
  echo "Uploading $(basename "$f")..."
  curl -s -u "$ORTHANC_USER:$ORTHANC_PASSWORD" \
    -X POST "http://localhost:${ORTHANC_HTTP_PORT}/instances" \
    --data-binary @"$f" > /dev/null
done

echo
echo "Uploaded $(ls "$SRC_DIR"/*.dcm | wc -l | tr -d ' ') slices to Orthanc."
