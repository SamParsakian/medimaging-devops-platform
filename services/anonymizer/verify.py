"""
Prints the tags the anonymizer cares about for one DICOM file.
Useful for checking any file on its own - the original, the
anonymized output, or anything else.
"""

import sys
from pathlib import Path

import pydicom

from rules import ANONYMIZATION_RULES

TAGS_TO_SHOW = list(ANONYMIZATION_RULES.keys()) + ["StudyInstanceUID"]


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify.py <path-to-dicom-file>")
        sys.exit(1)

    path = Path(sys.argv[1])
    dataset = pydicom.dcmread(path)

    print(f"Tags in {path}:")
    for tag in TAGS_TO_SHOW:
        value = getattr(dataset, tag, "")
        print(f"  {tag}: {value}")


if __name__ == "__main__":
    main()
