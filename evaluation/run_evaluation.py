"""
Batch evaluation script for the X-ray AI model (Step 26). Reads
evaluation/manifest.csv (24 NIH ChestX-ray14 sample images, 12 labeled
"No Finding" and 12 labeled with a single distinct abnormal finding -
see docs/sample-data.md for where they came from), registers each one
as a study exactly like services/metadata-extractor/register_xray_samples.py
already does for the original two samples, then calls the running API's
own POST /studies/{id}/infer endpoint for each one - the same endpoint
the dashboard's "Run AI Demo Inference" button uses. That call already
runs the real X-ray model, generates a heatmap, uploads it to MinIO, and
stores a row in ai_results; this script's own job is only to compare
that result against the sample's known label and store the comparison
in a new xray_evaluation_results table (see infra/postgres/init.sql).

Run from the repo root, with the stack up (`docker compose up -d`):

    python3 evaluation/run_evaluation.py

Prints a plain-text summary at the end, including a threshold
sensitivity comparison at 0.5 / 0.6 / 0.7 computed from the model's own
stored probabilities - no re-running inference needed for that part.
"""

import csv
import os
import time
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv
from minio import Minio
from psycopg2.extras import Json

ROOT_DIR = Path(__file__).resolve().parents[1]
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

API_HOST = os.environ.get("API_HOST", "localhost")
API_PORT = os.environ.get("API_PORT", "8000")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "changeme")

MANIFEST_PATH = ROOT_DIR / "evaluation" / "manifest.csv"

# Kept in sync with services/ai-inference/model_config.py's
# CONFIDENCE_THRESHOLD - this is the threshold every headline match/mismatch
# number in the evaluation summary uses. THRESHOLD_SENSITIVITY_SET is a
# separate, wider check: the same 24 stored results are re-judged at two
# other thresholds too, using probabilities already returned by the model,
# so the summary is honest about how much the numbers would shift with a
# different cutoff instead of only showing the one threshold that was chosen.
PRIMARY_THRESHOLD = 0.5
THRESHOLD_SENSITIVITY_SET = [0.5, 0.6, 0.7]

# A result within this distance of the threshold is treated as a genuinely
# borderline call ("review_needed") rather than a clean match or a clean
# miss - e.g. a normal sample where the model's strongest finding lands at
# 0.53 against a 0.5 threshold isn't confidently wrong, it's ambiguous.
REVIEW_BAND = 0.05

BUCKET_LOW = "low"
BUCKET_UNCERTAIN = "uncertain"
BUCKET_STRONGER = "stronger_signal"


def get_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT, dbname=POSTGRES_DB,
        user=POSTGRES_USER, password=POSTGRES_PASSWORD,
    )


def get_minio_client():
    return Minio(
        f"{MINIO_HOST}:{MINIO_PORT}",
        access_key=MINIO_ROOT_USER, secret_key=MINIO_ROOT_PASSWORD,
        secure=False,
    )


def load_manifest():
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def register_sample(conn, minio_client, row):
    """Uploads the sample image to MinIO and inserts/updates its studies
    row, the same pattern register_xray_samples.py uses for the original
    two X-ray samples - each evaluation sample is just another study, so
    it shows up in the dashboard and can be run through /infer normally."""
    object_path = f"samples/xray-eval/{row['source_filename']}"
    source_file = ROOT_DIR / row["local_path"]

    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
    minio_client.fput_object(MINIO_BUCKET, object_path, str(source_file))

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
                    row["sample_id"],
                    f"nih-cxr14-sample.{row['source_filename']}",
                    f"NIH ChestX-ray14 sample evaluation - {row['expected_label']} (expected)",
                    object_path,
                ),
            )
    return object_path


def run_inference(sample_id):
    response = requests.post(
        f"http://{API_HOST}:{API_PORT}/studies/{sample_id}/infer",
        headers={"X-API-Key": API_SECRET_KEY},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def confidence_bucket(confidence):
    if confidence is None:
        return None
    if confidence >= 0.7:
        return BUCKET_STRONGER
    if confidence >= 0.5:
        return BUCKET_UNCERTAIN
    return BUCKET_LOW


def judge(row, result, threshold):
    """Applies the abnormal/normal match rules at one threshold. Returns
    (match_status, deciding_probability) - the deciding probability is
    the expected finding's own score for an abnormal sample, or the
    highest score across all 18 findings for a normal sample, so the
    caller can also check how close to the threshold the call was."""
    probabilities = result.get("finding_probabilities") or {}
    top_findings = [f["label"] for f in result.get("top_findings", [])]

    if row["expected_group"] == "abnormal":
        expected_prob = probabilities.get(row["expected_label"])
        in_top_k = row["expected_label"] in top_findings
        above_threshold = expected_prob is not None and expected_prob >= threshold
        deciding_prob = expected_prob
        is_match = in_top_k or above_threshold
    else:
        deciding_prob = max(probabilities.values()) if probabilities else None
        is_match = deciding_prob is not None and deciding_prob < threshold

    if is_match:
        return "match", deciding_prob
    if deciding_prob is not None and abs(deciding_prob - threshold) <= REVIEW_BAND:
        return "review_needed", deciding_prob
    return "mismatch", deciding_prob


def store_evaluation_result(conn, row, result, match_status, threshold):
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO xray_evaluation_results (
                    sample_id, orthanc_study_id, ai_result_id, expected_label,
                    expected_group, top_finding, top_confidence, confidence_bucket,
                    match_status, inference_time_ms, threshold_used, finding_probabilities
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["sample_id"], row["sample_id"], result.get("result_id"),
                    row["expected_label"], row["expected_group"],
                    result.get("prediction_label"), result.get("confidence"),
                    confidence_bucket(result.get("confidence")), match_status,
                    result.get("inference_time_ms"), threshold,
                    Json(result.get("finding_probabilities")),
                ),
            )


def print_summary(rows_with_results):
    total = len(rows_with_results)
    normal = sum(1 for r, _ in rows_with_results if r["expected_group"] == "normal")
    abnormal = total - normal
    matches = sum(1 for _, m in rows_with_results if m == "match")
    review = sum(1 for _, m in rows_with_results if m == "review_needed")
    mismatches = sum(1 for _, m in rows_with_results if m == "mismatch")

    print(f"\n=== Evaluation summary (threshold = {PRIMARY_THRESHOLD:.1f}) ===")
    print(f"Total samples:   {total}")
    print(f"Normal:          {normal}")
    print(f"Abnormal:        {abnormal}")
    print(f"Match:           {matches}")
    print(f"Review needed:   {review}")
    print(f"Mismatch:        {mismatches}")


def print_threshold_sensitivity(rows_with_full_results):
    print("\n=== Threshold sensitivity (recomputed from stored probabilities) ===")
    print(f"{'threshold':>10}  {'match':>6}  {'review':>7}  {'mismatch':>9}")
    for threshold in THRESHOLD_SENSITIVITY_SET:
        counts = {"match": 0, "review_needed": 0, "mismatch": 0}
        for row, result in rows_with_full_results:
            status, _ = judge(row, result, threshold)
            counts[status] += 1
        line = f"{threshold:>10.1f}  {counts['match']:>6}  {counts['review_needed']:>7}"
        line += f"  {counts['mismatch']:>9}"
        print(line)


def main():
    manifest = load_manifest()
    conn = get_connection()
    minio_client = get_minio_client()

    rows_with_results = []
    rows_with_full_results = []
    inference_times = []

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM xray_evaluation_results WHERE sample_id LIKE 'xray-eval-%'")
        conn.commit()

        for row in manifest:
            object_path = register_sample(conn, minio_client, row)
            print(f"Registered {row['sample_id']} -> {object_path}")

            started = time.monotonic()
            result = run_inference(row["sample_id"])
            elapsed_ms = round((time.monotonic() - started) * 1000, 1)
            inference_times.append(result.get("inference_time_ms", elapsed_ms))

            match_status, _ = judge(row, result, PRIMARY_THRESHOLD)
            store_evaluation_result(conn, row, result, match_status, PRIMARY_THRESHOLD)

            print(
                f"  expected={row['expected_label']!r} ({row['expected_group']}) "
                f"top_finding={result.get('prediction_label')!r} "
                f"confidence={result.get('confidence')} -> {match_status}"
            )

            rows_with_results.append((row, match_status))
            rows_with_full_results.append((row, result))
    finally:
        conn.close()

    print_summary(rows_with_results)
    print(f"\nAverage inference time: {round(sum(inference_times) / len(inference_times), 1)} ms")
    print_threshold_sensitivity(rows_with_full_results)

    print(f"\nDone. Evaluated {len(manifest)} sample(s).")


if __name__ == "__main__":
    main()
