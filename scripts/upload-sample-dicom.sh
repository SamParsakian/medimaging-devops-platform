#!/usr/bin/env bash
# Downloads one small public/demo DICOM file and uploads it to the local
# Orthanc instance, to check that the imaging stack actually works.
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

SAMPLE_URL="https://github.com/pydicom/pydicom/raw/main/src/pydicom/data/test_files/CT_small.dcm"
DEST_DIR="sample-data/downloads"
DEST_FILE="$DEST_DIR/CT_small.dcm"

mkdir -p "$DEST_DIR"

echo "Downloading sample DICOM file..."
curl -sL -o "$DEST_FILE" "$SAMPLE_URL"

echo "Uploading to Orthanc..."
curl -s -u "$ORTHANC_USER:$ORTHANC_PASSWORD" \
  -X POST "http://localhost:${ORTHANC_HTTP_PORT}/instances" \
  --data-binary @"$DEST_FILE"

echo
