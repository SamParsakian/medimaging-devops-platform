#!/usr/bin/env bash
# Downloads the 24 chest X-ray images listed in evaluation/manifest.csv from
# Kaggle's "NIH Chest X-rays (sample)" dataset (nih-chest-xrays/sample) - the
# NIH's own official 5% sample release, CC0-1.0 licensed, with ground-truth
# labels in its own sample_labels.csv (see docs/sample-data.md). One file is
# downloaded at a time by name, not the whole ~1.1 GB dataset.
#
# Requires the Kaggle CLI (`pip install kaggle`) and a Kaggle API token,
# either as the KAGGLE_API_TOKEN environment variable or a token file at
# ~/.kaggle/access_token - see https://www.kaggle.com/settings -> API.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v kaggle >/dev/null 2>&1; then
  echo "The Kaggle CLI is not installed. Run: pip install kaggle" >&2
  exit 1
fi

DEST_DIR="sample-data/downloads/xray-eval"
mkdir -p "$DEST_DIR"

MANIFEST="evaluation/manifest.csv"

echo "Downloading sample_labels.csv (ground-truth reference)..."
kaggle datasets download -d nih-chest-xrays/sample -f sample_labels.csv -p "$DEST_DIR" -q
mv "$DEST_DIR/sample_labels.csv" "$DEST_DIR/nih_sample_labels_reference.csv"

tail -n +2 "$MANIFEST" | while IFS=, read -r sample_id source_filename rest; do
  if [ -f "$DEST_DIR/$source_filename" ]; then
    echo "Already have $source_filename, skipping."
    continue
  fi
  echo "Downloading $source_filename ($sample_id)..."
  kaggle datasets download -d nih-chest-xrays/sample -f "sample/images/$source_filename" -p "$DEST_DIR" -q
done

echo "Saved 24 images plus the labels reference to $DEST_DIR"
