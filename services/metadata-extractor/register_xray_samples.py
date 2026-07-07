"""
One-shot script: registers the two chest X-ray sample PNGs (see
docs/sample-data.md) as their own studies. They're already plain
images - no DICOM, no Orthanc, no anonymizer/preview-generator
pipeline needed - so this uploads each one straight to MinIO and
inserts one studies row per sample, reusing the same table and
columns every other study already uses. That's what lets them show up
in the dashboard and be run through the AI inference button exactly
like any other study.
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from minio import Minio

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "medimaging")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "medimaging")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "changeme")

MINIO_HOST = os.environ.get("MINIO_HOST", "localhost")
MINIO_PORT = os.environ.get("MINIO_PORT", "9000")
MINIO_ROOT_USER = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "changeme")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "medimaging")

SAMPLES_DIR = ROOT_DIR / "sample-data" / "downloads" / "xray"

SAMPLES = [
    {
        "orthanc_study_id": "xray-sample-abnormal",
        "study_instance_uid": "nih-cxr14.00000001_000",
        "study_description": "NIH ChestX-ray14 sample - Cardiomegaly (ground truth)",
        "source_file": SAMPLES_DIR / "00000001_000.png",
        "object_path": "samples/xray/00000001_000.png",
    },
    {
        "orthanc_study_id": "xray-sample-normal",
        "study_instance_uid": "nih-cxr14.00027426_000",
        "study_description": "NIH ChestX-ray14 sample - No Finding (ground truth)",
        "source_file": SAMPLES_DIR / "00027426_000.png",
        "object_path": "samples/xray/00027426_000.png",
    },
]


def get_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )


def get_minio_client():
    return Minio(
        f"{MINIO_HOST}:{MINIO_PORT}",
        access_key=MINIO_ROOT_USER,
        secret_key=MINIO_ROOT_PASSWORD,
        secure=False,
    )


def register_sample(conn, minio_client, sample):
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)

    minio_client.fput_object(MINIO_BUCKET, sample["object_path"], str(sample["source_file"]))

    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO studies (
                    orthanc_study_id, study_instance_uid, modality,
                    study_description, series_count, instance_count,
                    processing_status, preview_object_path,
                    anonymization_status, preview_status, upload_status
                )
                VALUES (%s, %s, 'CR', %s, 1, 1, 'done', %s, 'skipped', 'done', 'done')
                ON CONFLICT (orthanc_study_id) DO UPDATE SET
                    preview_object_path = EXCLUDED.preview_object_path,
                    study_description = EXCLUDED.study_description,
                    updated_at = now()
                """,
                (
                    sample["orthanc_study_id"],
                    sample["study_instance_uid"],
                    sample["study_description"],
                    sample["object_path"],
                ),
            )
    print(f"Registered {sample['orthanc_study_id']} -> {sample['object_path']}")


def main():
    missing = [s for s in SAMPLES if not s["source_file"].exists()]
    if missing:
        print("Missing sample file(s):")
        for sample in missing:
            print(f"  {sample['source_file']}")
        print("Run scripts/download-xray-samples.sh first.")
        sys.exit(1)

    conn = get_connection()
    minio_client = get_minio_client()
    try:
        for sample in SAMPLES:
            register_sample(conn, minio_client, sample)
    finally:
        conn.close()

    print(f"Done. Registered {len(SAMPLES)} X-ray sample(s).")


if __name__ == "__main__":
    main()
