"""
Demo-grade DICOM anonymizer. Reads one local DICOM file, replaces a
handful of identifying tags with fixed demo values, and writes the
result to a local, git-ignored output folder. Run manually, one file
at a time - no batch processing, no queue.
"""

import sys
import urllib.request
from pathlib import Path

import pydicom

from rules import ANONYMIZATION_RULES

SAMPLE_URL = (
    "https://github.com/pydicom/pydicom/raw/main/"
    "src/pydicom/data/test_files/CT_small.dcm"
)
DEFAULT_INPUT = Path("sample-data/downloads/CT_small.dcm")
OUTPUT_DIR = Path("services/anonymizer/output")

TAGS_TO_SHOW = list(ANONYMIZATION_RULES.keys()) + ["StudyInstanceUID"]


def ensure_input_file(path):
    if path.exists():
        return
    print(f"No local file at {path}, downloading the demo sample instead...")
    path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(SAMPLE_URL, path)


def print_tags(label, dataset):
    print(label)
    for tag in TAGS_TO_SHOW:
        value = getattr(dataset, tag, "")
        print(f"  {tag}: {value}")


def anonymize(input_path, output_path):
    dataset = pydicom.dcmread(input_path)

    print_tags("Before:", dataset)

    for tag, replacement in ANONYMIZATION_RULES.items():
        if not hasattr(dataset, tag) and replacement == "":
            continue
        setattr(dataset, tag, replacement)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.save_as(output_path)

    print_tags("After:", dataset)
    print(f"\nSaved anonymized file to {output_path}")


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    ensure_input_file(input_path)

    output_path = OUTPUT_DIR / f"anonymized_{input_path.name}"
    anonymize(input_path, output_path)


if __name__ == "__main__":
    main()
