#!/usr/bin/env bash
# Downloads two public chest X-ray sample images from the NIH ChestX-ray14
# dataset (public domain, no restrictions - see docs/sample-data.md), used
# to test the real TorchXRayVision inference path. One is labeled
# "Cardiomegaly" in the NIH dataset's own ground-truth metadata, the other
# "No Finding" - one abnormal sample, one normal sample.
set -euo pipefail

cd "$(dirname "$0")/.."

DEST_DIR="sample-data/downloads/xray"
mkdir -p "$DEST_DIR"

BASE_URL="https://raw.githubusercontent.com/mlmed/torchxrayvision/master/tests"

echo "Downloading abnormal sample (00000001_000.png, NIH label: Cardiomegaly)..."
curl -sL -o "$DEST_DIR/00000001_000.png" "$BASE_URL/00000001_000.png"

echo "Downloading normal sample (00027426_000.png, NIH label: No Finding)..."
curl -sL -o "$DEST_DIR/00027426_000.png" "$BASE_URL/00027426_000.png"

echo "Saved to $DEST_DIR"
