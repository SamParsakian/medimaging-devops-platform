#!/usr/bin/env bash
# Runs the Step 28 clinic workflow demo end to end: uploads 3 public chest
# X-ray samples through the same POST /studies/upload endpoint the
# Radiographer Upload view uses, so the Doctor Review view has real studies
# to show without clicking through the browser 3 times by hand. Requires
# the stack to already be running (docker compose up -d).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

API_PORT="${API_PORT:-8000}"
API_SECRET_KEY="${API_SECRET_KEY:-changeme}"
API_URL="http://localhost:${API_PORT}"

SAMPLES_DIR="sample-data/downloads/xray-eval"

# Three samples already used in Step 26's evaluation set (see
# evaluation/manifest.csv and docs/sample-data.md) - one normal, two
# abnormal with different findings, for a demo with some real variety.
SAMPLES=(
  "00000017_001.png|Routine chest X-ray - no prior findings noted"
  "00000079_000.png|Follow-up chest X-ray - patient reported chest discomfort"
  "00000061_002.png|Chest X-ray - shortness of breath on admission"
)

MISSING=0
for entry in "${SAMPLES[@]}"; do
  filename="${entry%%|*}"
  if [ ! -f "$SAMPLES_DIR/$filename" ]; then
    echo "Missing sample file: $SAMPLES_DIR/$filename"
    MISSING=1
  fi
done
if [ "$MISSING" -eq 1 ]; then
  echo "Run scripts/download-xray-evaluation-set.sh first (needs a Kaggle API token - see docs/sample-data.md)."
  exit 1
fi

for entry in "${SAMPLES[@]}"; do
  filename="${entry%%|*}"
  label="${entry##*|}"
  echo "Uploading $filename ($label)..."
  response="$(curl -s -X POST "$API_URL/studies/upload" \
    -H "X-API-Key: $API_SECRET_KEY" \
    -F "file=@$SAMPLES_DIR/$filename" \
    -F "label=$label")"
  study_id="$(echo "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["study"]["orthanc_study_id"])')"
  status="$(echo "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["study"]["workflow_status"])')"
  echo "  -> $study_id : $status"
done

echo "Done. Open $API_URL/dashboard/review.html?api_key=$API_SECRET_KEY to see them."
