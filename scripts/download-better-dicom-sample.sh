#!/usr/bin/env bash
# Downloads a second, larger public/demo DICOM file - one that produces a
# clearer PNG preview than the tiny CT_small.dcm sample. Download only, no
# Orthanc upload; this file feeds the anonymizer / preview-generator /
# MinIO-uploader pipeline directly.
set -euo pipefail

cd "$(dirname "$0")/.."

SAMPLE_URL="https://github.com/pydicom/pydicom/raw/main/src/pydicom/data/test_files/examples_overlay.dcm"
DEST_DIR="sample-data/downloads"
DEST_FILE="$DEST_DIR/examples_overlay.dcm"

mkdir -p "$DEST_DIR"

echo "Downloading sample DICOM file..."
curl -sL -o "$DEST_FILE" "$SAMPLE_URL"

echo "Saved to $DEST_FILE"
