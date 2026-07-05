"""
Uploads an anonymized DICOM file to MinIO as a processed imaging
object. Run manually, one file at a time, after the anonymizer.
"""

import os
import sys
from pathlib import Path

import psycopg2
import pydicom
from dotenv import load_dotenv
from minio import Minio

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

MINIO_HOST = os.environ.get("MINIO_HOST", "localhost")
MINIO_PORT = os.environ.get("MINIO_PORT", "9000")
MINIO_ROOT_USER = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "changeme")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "medimaging")

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "medimaging")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "medimaging")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "changeme")

DEFAULT_INPUT = ROOT_DIR / "services/anonymizer/output/anonymized_CT_small.dcm"


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


def get_client():
    return Minio(
        f"{MINIO_HOST}:{MINIO_PORT}",
        access_key=MINIO_ROOT_USER,
        secret_key=MINIO_ROOT_PASSWORD,
        secure=False,
    )


def ensure_bucket(client, bucket):
    if client.bucket_exists(bucket):
        print(f"Bucket already exists: {bucket}")
        return
    client.make_bucket(bucket)
    print(f"Created bucket: {bucket}")


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT

    if not input_path.exists():
        print(f"No anonymized file found at {input_path}")
        print("Run services/anonymizer/anonymize.py first.")
        sys.exit(1)

    study_uid = pydicom.dcmread(input_path).StudyInstanceUID
    object_name = f"processed/anonymized/{study_uid}/{input_path.name}"

    try:
        client = get_client()
        ensure_bucket(client, MINIO_BUCKET)
        client.fput_object(MINIO_BUCKET, object_name, str(input_path))
    except Exception as exc:
        update_pipeline_status(study_uid, "upload_status", "failed", str(exc))
        print(f"ERROR: could not upload {input_path}: {exc}")
        sys.exit(1)

    update_pipeline_status(study_uid, "upload_status", "done")
    print(f"Uploaded {input_path} to {MINIO_BUCKET}/{object_name}")


if __name__ == "__main__":
    main()
