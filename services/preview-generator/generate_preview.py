"""
Generates a viewable PNG preview from a DICOM file's pixel data. Reads
the anonymized DICOM from Step 4, applies simple windowing so the CT
image isn't just black or blown out, and writes a PNG to a local,
git-ignored output folder. Run manually, one file at a time.
"""

import os
import sys
from pathlib import Path

import numpy as np
import psycopg2
import pydicom
from dotenv import load_dotenv
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "medimaging")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "medimaging")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "changeme")

DEFAULT_INPUT = ROOT_DIR / "services/anonymizer/output/anonymized_CT_small.dcm"
OUTPUT_DIR = ROOT_DIR / "services/preview-generator/output"


def update_pipeline_status(study_uid, column, status, error=None):
    """Updates one pipeline-stage status column for a study. A study
    that was never extracted from Orthanc (no matching row) is simply
    not updated - this is a no-op, not an error."""
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE studies SET {column} = %s, last_error = %s, updated_at = now() "
                    "WHERE study_instance_uid = %s",
                    (status, error, study_uid),
                )
    finally:
        conn.close()


def build_output_name(input_path):
    name = input_path.stem
    if name.startswith("anonymized_"):
        name = name[len("anonymized_"):]
    return f"preview_{name}.png"


def to_8bit_pixels(dataset):
    pixels = dataset.pixel_array.astype(np.float64)

    slope = float(getattr(dataset, "RescaleSlope", 1))
    intercept = float(getattr(dataset, "RescaleIntercept", 0))
    pixels = pixels * slope + intercept

    center = getattr(dataset, "WindowCenter", None)
    width = getattr(dataset, "WindowWidth", None)
    if isinstance(center, pydicom.multival.MultiValue):
        center = center[0]
    if isinstance(width, pydicom.multival.MultiValue):
        width = width[0]

    if center is not None and width is not None:
        low = float(center) - float(width) / 2
        high = float(center) + float(width) / 2
    else:
        low = pixels.min()
        high = pixels.max()

    pixels = np.clip(pixels, low, high)
    if high > low:
        pixels = (pixels - low) / (high - low) * 255.0
    else:
        pixels = np.zeros_like(pixels)

    return pixels.astype(np.uint8)


def generate_preview(input_path, output_path):
    dataset = pydicom.dcmread(input_path)
    study_uid = dataset.StudyInstanceUID

    try:
        pixels = to_8bit_pixels(dataset)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(pixels).save(output_path)

        print(f"Saved preview PNG to {output_path}")
    except Exception as exc:
        update_pipeline_status(study_uid, "preview_status", "failed", str(exc))
        raise

    update_pipeline_status(study_uid, "preview_status", "done")
    return study_uid


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT

    if not input_path.exists():
        print(f"No anonymized file found at {input_path}")
        print("Run services/anonymizer/anonymize.py first.")
        sys.exit(1)

    output_path = OUTPUT_DIR / build_output_name(input_path)

    try:
        generate_preview(input_path, output_path)
    except Exception as exc:
        print(f"ERROR: could not generate preview from {input_path}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
