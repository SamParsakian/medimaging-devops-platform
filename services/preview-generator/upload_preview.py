"""
Uploads a generated PNG preview to MinIO as a processed imaging
object. Run manually, after generate_preview.py. The study UID comes
from the source anonymized DICOM file, not the PNG itself.
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

DEFAULT_PNG = ROOT_DIR / "services/preview-generator/output/preview_CT_small.png"


def infer_dicom_path(png_path):
    name = png_path.stem
    if name.startswith("preview_"):
        name = name[len("preview_"):]
    return ROOT_DIR / "services/anonymizer/output" / f"anonymized_{name}.dcm"


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


def build_object_name(dicom_path, png_path):
    dataset = pydicom.dcmread(dicom_path)
    study_uid = dataset.StudyInstanceUID
    return f"processed/previews/{study_uid}/{png_path.name}"


def main():
    png_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PNG
    dicom_path = Path(sys.argv[2]) if len(sys.argv) > 2 else infer_dicom_path(png_path)

    if not png_path.exists():
        print(f"No preview PNG found at {png_path}")
        print("Run services/preview-generator/generate_preview.py first.")
        sys.exit(1)

    if not dicom_path.exists():
        print(f"No anonymized DICOM found at {dicom_path} to read the study UID from.")
        print("Run services/anonymizer/anonymize.py first.")
        sys.exit(1)

    object_name = build_object_name(dicom_path, png_path)

    client = get_client()
    ensure_bucket(client, MINIO_BUCKET)
    client.fput_object(MINIO_BUCKET, object_name, str(png_path))

    print(f"Uploaded {png_path} to {MINIO_BUCKET}/{object_name}")


if __name__ == "__main__":
    main()
