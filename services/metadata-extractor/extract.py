"""
One-shot script: reads every study currently in Orthanc and stores its
metadata in the PostgreSQL `studies` table. Meant to be run manually
for now - no background queue, no API, no scheduling.
"""

import os
from datetime import datetime

import psycopg2
import requests
from dotenv import load_dotenv

ROOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
load_dotenv(os.path.join(ROOT_DIR, ".env"))

ORTHANC_HOST = os.environ.get("ORTHANC_HOST", "localhost")
ORTHANC_HTTP_PORT = os.environ.get("ORTHANC_HTTP_PORT", "8042")
ORTHANC_USER = os.environ.get("ORTHANC_USER", "orthanc")
ORTHANC_PASSWORD = os.environ.get("ORTHANC_PASSWORD", "changeme")
ORTHANC_URL = f"http://{ORTHANC_HOST}:{ORTHANC_HTTP_PORT}"
ORTHANC_AUTH = (ORTHANC_USER, ORTHANC_PASSWORD)

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "medimaging")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "medimaging")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "changeme")

UPSERT_SQL = """
INSERT INTO studies (
    orthanc_study_id, study_instance_uid, series_instance_uid,
    patient_id, patient_name, modality, study_date, study_description,
    series_count, instance_count, processing_status, last_error, updated_at
) VALUES (
    %(orthanc_study_id)s, %(study_instance_uid)s, %(series_instance_uid)s,
    %(patient_id)s, %(patient_name)s, %(modality)s, %(study_date)s, %(study_description)s,
    %(series_count)s, %(instance_count)s, 'done', NULL, now()
)
ON CONFLICT (orthanc_study_id) DO UPDATE SET
    study_instance_uid = EXCLUDED.study_instance_uid,
    series_instance_uid = EXCLUDED.series_instance_uid,
    patient_id = EXCLUDED.patient_id,
    patient_name = EXCLUDED.patient_name,
    modality = EXCLUDED.modality,
    study_date = EXCLUDED.study_date,
    study_description = EXCLUDED.study_description,
    series_count = EXCLUDED.series_count,
    instance_count = EXCLUDED.instance_count,
    processing_status = 'done',
    last_error = NULL,
    updated_at = now();
"""

FAIL_UPDATE_SQL = """
UPDATE studies
SET processing_status = 'failed', last_error = %(error)s, updated_at = now()
WHERE orthanc_study_id = %(orthanc_study_id)s;
"""


def get_json(path):
    response = requests.get(f"{ORTHANC_URL}{path}", auth=ORTHANC_AUTH, timeout=10)
    response.raise_for_status()
    return response.json()


def parse_study_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def collect_study_metadata(orthanc_study_id):
    study = get_json(f"/studies/{orthanc_study_id}")
    main_tags = study.get("MainDicomTags", {})
    patient_tags = study.get("PatientMainDicomTags", {})
    series_ids = study.get("Series", [])

    series_instance_uid = None
    modality = None
    instance_count = 0

    for index, series_id in enumerate(series_ids):
        series = get_json(f"/series/{series_id}")
        instance_count += len(series.get("Instances", []))
        if index == 0:
            series_tags = series.get("MainDicomTags", {})
            series_instance_uid = series_tags.get("SeriesInstanceUID")
            modality = series_tags.get("Modality")

    return {
        "orthanc_study_id": orthanc_study_id,
        "study_instance_uid": main_tags.get("StudyInstanceUID"),
        "series_instance_uid": series_instance_uid,
        "patient_id": patient_tags.get("PatientID"),
        "patient_name": patient_tags.get("PatientName"),
        "modality": modality,
        "study_date": parse_study_date(main_tags.get("StudyDate")),
        "study_description": main_tags.get("StudyDescription"),
        "series_count": len(series_ids),
        "instance_count": instance_count,
    }


def main():
    study_ids = get_json("/studies")
    print(f"Found {len(study_ids)} study(ies) in Orthanc.")

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
                for orthanc_study_id in study_ids:
                    try:
                        metadata = collect_study_metadata(orthanc_study_id)
                        cur.execute(UPSERT_SQL, metadata)
                        print(
                            f"Stored study {orthanc_study_id}: "
                            f"{metadata['patient_name']} / {metadata['study_description']}"
                        )
                    except Exception as exc:
                        print(f"Failed to process study {orthanc_study_id}: {exc}")
                        cur.execute(FAIL_UPDATE_SQL, {"orthanc_study_id": orthanc_study_id, "error": str(exc)})
    finally:
        conn.close()

    print("Done.")


if __name__ == "__main__":
    main()
