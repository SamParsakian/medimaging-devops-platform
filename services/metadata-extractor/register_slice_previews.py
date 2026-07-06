"""
One-shot script: registers one row per slice preview in the
study_slices table, for a multi-slice series that's already been
through the anonymizer, preview generator, and MinIO uploader (see
scripts/process-multislice-series.sh). Most studies only ever need
the single whole-study preview on studies.preview_object_path - this
is only for series with more than one image to page through.
"""

import glob
import os
import sys
from pathlib import Path

import psycopg2
import pydicom
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "medimaging")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "medimaging")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "changeme")

ANONYMIZED_DIR = ROOT_DIR / "services/anonymizer/output"
DEFAULT_PREFIX = "N2D_"


def get_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )


def build_preview_name(anonymized_path):
    name = anonymized_path.stem
    if name.startswith("anonymized_"):
        name = name[len("anonymized_"):]
    return f"preview_{name}.png"


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PREFIX

    anonymized_files = sorted(
        Path(p) for p in glob.glob(str(ANONYMIZED_DIR / f"anonymized_{prefix}*.dcm"))
    )
    if not anonymized_files:
        print(f"No anonymized files found matching anonymized_{prefix}*.dcm in {ANONYMIZED_DIR}")
        sys.exit(1)

    first_dataset = pydicom.dcmread(anonymized_files[0])
    study_uid = first_dataset.StudyInstanceUID

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT orthanc_study_id FROM studies WHERE study_instance_uid = %s",
                    (study_uid,),
                )
                row = cur.fetchone()
                if row is None:
                    print(f"No study in the studies table with study_instance_uid {study_uid}")
                    print("Run services/metadata-extractor/extract.py first.")
                    sys.exit(1)
                orthanc_study_id = row[0]

                for slice_index, anonymized_path in enumerate(anonymized_files):
                    dataset = pydicom.dcmread(anonymized_path)
                    preview_name = build_preview_name(anonymized_path)
                    object_path = f"processed/previews/{study_uid}/{preview_name}"

                    cur.execute(
                        """
                        INSERT INTO study_slices
                            (orthanc_study_id, slice_index, instance_number, preview_object_path)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (orthanc_study_id, slice_index)
                        DO UPDATE SET
                            instance_number = EXCLUDED.instance_number,
                            preview_object_path = EXCLUDED.preview_object_path
                        """,
                        (orthanc_study_id, slice_index, dataset.get("InstanceNumber"), object_path),
                    )
                    print(f"Registered slice {slice_index}: {object_path}")
    finally:
        conn.close()

    print(f"Done. Registered {len(anonymized_files)} slice(s) for study {orthanc_study_id}.")


if __name__ == "__main__":
    main()
