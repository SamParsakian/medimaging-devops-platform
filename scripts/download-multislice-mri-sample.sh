#!/usr/bin/env bash
# Downloads a small, representative set of slices from a real public-domain
# multi-slice MRI series - a structural T1-weighted brain scan from the
# studyforrest project, published via the datalad/example-dicom-structural
# repo under the Open Data Commons Public Domain Dedication and Licence
# (PDDL). See docs/sample-data.md for the full source and license note.
#
# The full series has 384 slices (~80MB total). Downloading all of them
# isn't needed for a demo, so this script only grabs 15, evenly spaced
# through the part of the volume that actually shows brain anatomy
# (the very first and last slices in the series are below the neck or
# above the top of the skull, and mostly blank).
set -euo pipefail

cd "$(dirname "$0")/.."

BASE_URL="https://raw.githubusercontent.com/datalad/example-dicom-structural/master/dicoms"
DEST_DIR="sample-data/downloads/multislice-mri"
SLICE_NUMBERS="105 120 135 150 165 180 195 210 225 240 255 270 285 300 315"

mkdir -p "$DEST_DIR"

for n in $SLICE_NUMBERS; do
  padded=$(printf "%04d" "$n")
  dest_file="$DEST_DIR/N2D_${padded}.dcm"
  echo "Downloading slice $padded..."
  curl -sL -o "$dest_file" "$BASE_URL/N2D_${padded}.dcm"
done

echo
echo "Saved $(echo "$SLICE_NUMBERS" | wc -w | tr -d ' ') slices to $DEST_DIR"
