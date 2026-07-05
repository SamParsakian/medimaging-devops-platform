"""
Demo-grade DICOM anonymizer. Reads one local DICOM file, replaces a
handful of identifying tags with fixed demo values, and writes the
result to a local, git-ignored output folder. Run manually, one file
at a time - no batch processing, no queue.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import pydicom
from dotenv import load_dotenv

from rules import ANONYMIZATION_RULES

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

SERVICE_NAME = "anonymizer"


def log_event(action, status="success", study_id=None, error=None, level="INFO", **extra):
    """Prints one JSON line per event, so the run's structured logs show
    up in the terminal this script is run from. No Loki/Grafana yet."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": SERVICE_NAME,
        "action": action,
        "study_id": study_id,
        "status": status,
        "error": error,
    }
    entry.update(extra)
    print(json.dumps(entry), flush=True)

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "medimaging")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "medimaging")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "changeme")

SAMPLE_URL = (
    "https://github.com/pydicom/pydicom/raw/main/"
    "src/pydicom/data/test_files/CT_small.dcm"
)
DEFAULT_INPUT = Path("sample-data/downloads/CT_small.dcm")
OUTPUT_DIR = Path("services/anonymizer/output")

TAGS_TO_SHOW = list(ANONYMIZATION_RULES.keys()) + ["StudyInstanceUID"]


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


def ensure_input_file(path):
    if path.exists():
        return
    print(f"No local file at {path}, downloading the demo sample instead...")
    path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(SAMPLE_URL, path)


def print_tags(label, dataset):
    print(label)
    for tag in TAGS_TO_SHOW:
        value = getattr(dataset, tag, "")
        print(f"  {tag}: {value}")


def anonymize(input_path, output_path):
    dataset = pydicom.dcmread(input_path)
    study_uid = dataset.StudyInstanceUID
    log_event("anonymize_file", status="started", study_id=study_uid, input_path=str(input_path))

    try:
        print_tags("Before:", dataset)

        for tag, replacement in ANONYMIZATION_RULES.items():
            if not hasattr(dataset, tag) and replacement == "":
                continue
            setattr(dataset, tag, replacement)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        dataset.save_as(output_path)

        print_tags("After:", dataset)
        print(f"\nSaved anonymized file to {output_path}")
    except Exception as exc:
        update_pipeline_status(study_uid, "anonymization_status", "failed", str(exc))
        log_event(
            "anonymize_file", status="failed", level="ERROR",
            study_id=study_uid, error=str(exc),
        )
        raise

    update_pipeline_status(study_uid, "anonymization_status", "done")
    log_event("anonymize_file", status="success", study_id=study_uid, output_path=str(output_path))
    return study_uid


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    ensure_input_file(input_path)

    output_path = OUTPUT_DIR / f"anonymized_{input_path.name}"

    try:
        anonymize(input_path, output_path)
    except Exception as exc:
        print(f"ERROR: could not anonymize {input_path}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
