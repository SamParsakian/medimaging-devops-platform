"""
Read-only FastAPI service exposing study metadata and preview info
from the PostgreSQL `studies` table (populated by
services/metadata-extractor/extract.py). No auth, no dashboard, no AI
yet - just a demo-grade read API in front of the existing pipeline.
"""

import os

import psycopg2
from fastapi import FastAPI, HTTPException

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "medimaging")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "medimaging")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "changeme")

# This platform's safety rule is "no real patient data, ever" - every
# study it ever holds is demo/anonymized data by design, so PatientID
# is always safe to expose here.
DEMO_DATA_ONLY = True

app = FastAPI(title="Medical Imaging Study API")

STUDY_COLUMNS = (
    "orthanc_study_id, study_instance_uid, patient_id, modality, "
    "study_date, study_description, series_count, instance_count, "
    "processing_status, preview_object_path"
)


def get_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )


def row_to_study(row):
    return {
        "orthanc_study_id": row[0],
        "study_instance_uid": row[1],
        "patient_id": row[2] if DEMO_DATA_ONLY else None,
        "modality": row[3],
        "study_date": row[4].isoformat() if row[4] else None,
        "study_description": row[5],
        "series_count": row[6],
        "instance_count": row[7],
        "processing_status": row[8],
        "preview_object_path": row[9],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/studies")
def list_studies():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {STUDY_COLUMNS} FROM studies ORDER BY id")
            rows = cur.fetchall()
    finally:
        conn.close()
    return [row_to_study(row) for row in rows]


def fetch_study(study_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {STUDY_COLUMNS} FROM studies WHERE orthanc_study_id = %s",
                (study_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return row_to_study(row)


@app.get("/studies/{study_id}")
def get_study(study_id: str):
    return fetch_study(study_id)


@app.get("/studies/{study_id}/preview-info")
def get_preview_info(study_id: str):
    study = fetch_study(study_id)
    return {
        "orthanc_study_id": study["orthanc_study_id"],
        "study_instance_uid": study["study_instance_uid"],
        "preview_object_path": study["preview_object_path"],
        "available": study["preview_object_path"] is not None,
    }
