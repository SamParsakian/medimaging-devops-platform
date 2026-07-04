"""
Uploads an anonymized DICOM file to MinIO as a processed imaging
object. Run manually, one file at a time, after the anonymizer.
"""

import os
import sys
from pathlib import Path

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

DEFAULT_INPUT = ROOT_DIR / "services/anonymizer/output/anonymized_CT_small.dcm"


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


def build_object_name(input_path):
    dataset = pydicom.dcmread(input_path)
    study_uid = dataset.StudyInstanceUID
    return f"processed/anonymized/{study_uid}/{input_path.name}"


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT

    if not input_path.exists():
        print(f"No anonymized file found at {input_path}")
        print("Run services/anonymizer/anonymize.py first.")
        sys.exit(1)

    object_name = build_object_name(input_path)

    client = get_client()
    ensure_bucket(client, MINIO_BUCKET)
    client.fput_object(MINIO_BUCKET, object_name, str(input_path))

    print(f"Uploaded {input_path} to {MINIO_BUCKET}/{object_name}")


if __name__ == "__main__":
    main()
