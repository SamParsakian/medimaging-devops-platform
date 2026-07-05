"""
One-shot script: sets a study's preview_object_path column once a
preview PNG has been generated and uploaded to MinIO for it (see
services/preview-generator/). Run manually, one study at a time.
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

ROOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
load_dotenv(os.path.join(ROOT_DIR, ".env"))

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "medimaging")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "medimaging")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "changeme")

DEFAULT_STUDY_UID = "1.3.6.1.4.1.5962.1.2.1.20040119072730.12322"
DEFAULT_OBJECT_PATH = (
    f"processed/previews/{DEFAULT_STUDY_UID}/preview_CT_small.png"
)


def main():
    study_uid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STUDY_UID
    object_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OBJECT_PATH

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
                    """
                    UPDATE studies
                    SET preview_object_path = %s, updated_at = now()
                    WHERE study_instance_uid = %s
                    """,
                    (object_path, study_uid),
                )
                print(f"Updated {cur.rowcount} row(s) for study {study_uid} -> {object_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
