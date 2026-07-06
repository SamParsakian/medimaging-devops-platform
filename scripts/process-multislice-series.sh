#!/usr/bin/env bash
# Runs the existing single-file anonymizer / preview generator / MinIO
# uploader pipeline once per slice, for every slice downloaded by
# download-multislice-mri-sample.sh. None of those scripts change for
# this - they already take one input file at a time, so this script is
# just the loop, plus registering the resulting slice previews so the
# dashboard can page through them (see register_slice_previews.py).
set -euo pipefail

cd "$(dirname "$0")/.."

SRC_DIR="sample-data/downloads/multislice-mri"

if [ ! -d "$SRC_DIR" ] || [ -z "$(ls -A "$SRC_DIR" 2>/dev/null)" ]; then
  echo "No files found in $SRC_DIR"
  echo "Run ./scripts/download-multislice-mri-sample.sh first."
  exit 1
fi

for f in "$SRC_DIR"/*.dcm; do
  name=$(basename "$f")
  echo "=== $name ==="

  ./services/anonymizer/.venv/bin/python services/anonymizer/anonymize.py "$f"

  anonymized="services/anonymizer/output/anonymized_$name"
  ./services/preview-generator/.venv/bin/python services/preview-generator/generate_preview.py "$anonymized"

  preview="services/preview-generator/output/preview_${name%.dcm}.png"
  ./services/preview-generator/.venv/bin/python services/preview-generator/upload_preview.py "$preview" "$anonymized"

  ./services/minio-uploader/.venv/bin/python services/minio-uploader/upload.py "$anonymized"
done

echo
echo "=== Registering slice previews ==="
./services/metadata-extractor/.venv/bin/python services/metadata-extractor/register_slice_previews.py "N2D_"
