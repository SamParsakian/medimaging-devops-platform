"""
Read-only FastAPI service exposing study metadata and preview info
from the PostgreSQL `studies` table (populated by
services/metadata-extractor/extract.py), plus a small static
dashboard (services/api/static/) that reads the same endpoints, and
a basic audit trail of who looked at what. No real auth yet - one
fixed demo user, protected by a single shared API key.
"""

import json
import os
import time
from datetime import datetime, timezone

import psycopg2
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from minio import Minio
from minio.error import S3Error
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from psycopg2.extras import Json

SERVICE_NAME = "api"

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests handled by the API",
    ["method", "path", "status_code"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds",
    ["method", "path"],
)
STUDIES_TOTAL = Gauge("studies_total", "Total number of studies in the studies table")
STUDIES_FAILED_TOTAL = Gauge(
    "studies_failed_total", "Number of studies with at least one failed pipeline stage",
)


def log_event(action, status="success", study_id=None, error=None, level="INFO", **extra):
    """Prints one JSON line per event, so `docker compose logs api` shows
    structured logs. No Loki/Grafana yet - stdout is the whole pipeline."""
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

MINIO_HOST = os.environ.get("MINIO_HOST", "localhost")
MINIO_PORT = os.environ.get("MINIO_PORT", "9000")
MINIO_ROOT_USER = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "changeme")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "medimaging")

AI_INFERENCE_HOST = os.environ.get("AI_INFERENCE_HOST", "localhost")
AI_INFERENCE_PORT = os.environ.get("AI_INFERENCE_PORT", "8100")

# This platform's safety rule is "no real patient data, ever" - every
# study it ever holds is demo/anonymized data by design, so PatientID
# is always safe to expose here.
DEMO_DATA_ONLY = True

# No real auth yet - every request is logged under this one demo user.
DEMO_USER_ID = "demo-user"

# Demo-grade security: one shared API key from the environment, checked
# against either the X-API-Key header or an api_key query parameter (the
# query param exists so a browser can load /dashboard/?api_key=... directly).
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "changeme")
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/metrics"}

app = FastAPI(title="Medical Imaging Study API")


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    # Docker's own healthcheck, and Prometheus scraping /metrics, both hit
    # this middleware every few seconds - neither is a real event worth
    # logging or counting as API traffic.
    if request.url.path in {"/health", "/metrics"}:
        return await call_next(request)

    started = time.monotonic()
    method = request.method
    path = request.url.path

    if path not in PUBLIC_PATHS:
        provided_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")

        if not provided_key:
            REQUEST_COUNT.labels(method=method, path=path, status_code="401").inc()
            log_event(
                "http_request", status="unauthorized", level="WARNING",
                method=method, path=path, status_code=401,
            )
            return JSONResponse(status_code=401, content={"detail": "Missing API key"})
        if provided_key != API_SECRET_KEY:
            REQUEST_COUNT.labels(method=method, path=path, status_code="403").inc()
            log_event(
                "http_request", status="forbidden", level="WARNING",
                method=method, path=path, status_code=403,
            )
            return JSONResponse(status_code=403, content={"detail": "Invalid API key"})

    response = await call_next(request)
    duration_seconds = time.monotonic() - started
    duration_ms = round(duration_seconds * 1000, 1)
    REQUEST_COUNT.labels(method=method, path=path, status_code=str(response.status_code)).inc()
    REQUEST_DURATION.labels(method=method, path=path).observe(duration_seconds)
    log_event(
        "http_request",
        status="success" if response.status_code < 400 else "error",
        level="INFO" if response.status_code < 400 else "ERROR",
        method=method, path=path, status_code=response.status_code, duration_ms=duration_ms,
    )
    return response


STUDY_COLUMNS = (
    "orthanc_study_id, study_instance_uid, patient_id, modality, "
    "study_date, study_description, series_count, instance_count, "
    "processing_status, preview_object_path, anonymization_status, "
    "preview_status, upload_status, last_error"
)

AUDIT_COLUMNS = "event_id, user_id, action, study_id, timestamp, ip_address, status"

AI_RESULT_COLUMNS = (
    "result_id, orthanc_study_id, input_object, model_name, model_version, "
    "prediction_label, confidence, inference_time_ms, disclaimer, created_at, "
    "mode, findings, heatmap_object"
)

EVALUATION_COLUMNS = (
    "id, sample_id, orthanc_study_id, ai_result_id, expected_label, expected_group, "
    "top_finding, top_confidence, confidence_bucket, match_status, inference_time_ms, "
    "threshold_used, created_at"
)


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
        "anonymization_status": row[10],
        "preview_status": row[11],
        "upload_status": row[12],
        "last_error": row[13],
    }


def row_to_audit_event(row):
    return {
        "event_id": row[0],
        "user_id": row[1],
        "action": row[2],
        "study_id": row[3],
        "timestamp": row[4].isoformat() if row[4] else None,
        "ip_address": row[5],
        "status": row[6],
    }


def row_to_evaluation_sample(row):
    return {
        "id": row[0],
        "sample_id": row[1],
        "orthanc_study_id": row[2],
        "ai_result_id": row[3],
        "expected_label": row[4],
        "expected_group": row[5],
        "top_finding": row[6],
        "top_confidence": row[7],
        "confidence_bucket": row[8],
        "match_status": row[9],
        "inference_time_ms": row[10],
        "threshold_used": row[11],
        "created_at": row[12].isoformat() if row[12] else None,
    }


def row_to_ai_result(row):
    return {
        "result_id": row[0],
        "orthanc_study_id": row[1],
        "input_object": row[2],
        "model_name": row[3],
        "model_version": row[4],
        "prediction_label": row[5],
        "confidence": row[6],
        "inference_time_ms": row[7],
        "disclaimer": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
        "mode": row[10],
        # Named top_findings here (not the DB column name "findings") so
        # a stored result has the exact same shape as a live /infer
        # response, and the dashboard can render both with one function.
        "top_findings": row[11],
        "heatmap_object": row[12],
    }


def store_ai_result(study_id, result):
    """Inserts one ai_results row and returns its new result_id, so the
    caller can hand it straight back to the client - that's what lets
    the dashboard build a heatmap-image URL from a result it just got
    back from POST /infer, not only from a later GET .../ai-results."""
    findings = result.get("top_findings")
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_results (
                        orthanc_study_id, input_object, model_name, model_version,
                        prediction_label, confidence, inference_time_ms, disclaimer,
                        mode, findings, heatmap_object
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING result_id
                    """,
                    (
                        study_id,
                        result["input_object"],
                        result["model_name"],
                        result["model_version"],
                        result["prediction_label"],
                        result["confidence"],
                        result["inference_time_ms"],
                        result["disclaimer"],
                        result.get("mode"),
                        Json(findings) if findings is not None else None,
                        result.get("heatmap_object"),
                    ),
                )
                return cur.fetchone()[0]
    finally:
        conn.close()


def log_audit_event(request: Request, action: str, study_id, status: str):
    ip_address = request.client.host if request.client else None
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_events (user_id, action, study_id, ip_address, status)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (DEMO_USER_ID, action, study_id, ip_address, status),
                )
    finally:
        conn.close()
    # Covers study access, preview access, and audit events in one place,
    # since every one of those endpoints already calls this function.
    log_event(action, status=status, study_id=study_id, user_id=DEMO_USER_ID, ip_address=ip_address)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    """Prometheus scrapes this. studies_total and studies_failed_total are
    refreshed from Postgres on every scrape, so they're never stale."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM studies")
            STUDIES_TOTAL.set(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(*) FROM studies WHERE "
                "processing_status = 'failed' OR anonymization_status = 'failed' "
                "OR preview_status = 'failed' OR upload_status = 'failed'"
            )
            STUDIES_FAILED_TOTAL.set(cur.fetchone()[0])
    finally:
        conn.close()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/ai-config")
def get_ai_config():
    """Proxies ai-inference's own /config endpoint, so the dashboard
    can show the model's configuration without needing direct access
    to ai-inference - same reasoning as the /infer proxy below."""
    try:
        response = requests.get(f"http://{AI_INFERENCE_HOST}:{AI_INFERENCE_PORT}/config", timeout=5)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="AI inference service unavailable") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="AI inference service returned an error")

    return response.json()


@app.get("/studies")
def list_studies(request: Request):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {STUDY_COLUMNS} FROM studies ORDER BY id")
            rows = cur.fetchall()
    finally:
        conn.close()
    log_audit_event(request, "list_studies", None, "success")
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
def get_study(study_id: str, request: Request):
    try:
        study = fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "view_study", study_id, "not_found")
        raise
    log_audit_event(request, "view_study", study_id, "success")
    return study


@app.get("/studies/{study_id}/preview-info")
def get_preview_info(study_id: str, request: Request):
    try:
        study = fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "view_preview_info", study_id, "not_found")
        raise
    log_audit_event(request, "view_preview_info", study_id, "success")
    return {
        "orthanc_study_id": study["orthanc_study_id"],
        "study_instance_uid": study["study_instance_uid"],
        "preview_object_path": study["preview_object_path"],
        "available": study["preview_object_path"] is not None,
    }


def stream_minio_object(object_path):
    """Streams one object's bytes straight from MinIO, so a caller never
    needs direct MinIO access or credentials - the bucket stays private."""
    client = get_minio_client()
    response = client.get_object(MINIO_BUCKET, object_path)

    def iter_content():
        try:
            yield from response.stream(32 * 1024)
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(iter_content(), media_type="image/png")


@app.get("/studies/{study_id}/preview-image")
def get_preview_image(study_id: str, request: Request):
    """Streams the preview PNG from MinIO, so the dashboard (or any
    browser) can show it without needing direct MinIO access or
    credentials - MinIO's bucket stays private."""
    try:
        study = fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "view_preview_image", study_id, "not_found")
        raise

    object_path = study["preview_object_path"]
    if not object_path:
        log_audit_event(request, "view_preview_image", study_id, "not_found")
        raise HTTPException(status_code=404, detail="No preview available for this study")

    try:
        result = stream_minio_object(object_path)
    except S3Error as exc:
        log_audit_event(request, "view_preview_image", study_id, "not_found")
        raise HTTPException(status_code=404, detail="Preview object not found in MinIO") from exc

    log_audit_event(request, "view_preview_image", study_id, "success")
    return result


@app.post("/studies/{study_id}/infer")
def run_inference(study_id: str, request: Request):
    """Proxies to the ai-inference service (Step 21) using the study's
    own preview image as input, so a caller never needs direct MinIO
    or ai-inference access - same idea as stream_minio_object above."""
    try:
        study = fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "run_inference", study_id, "not_found")
        raise

    object_path = study["preview_object_path"]
    if not object_path:
        log_audit_event(request, "run_inference", study_id, "not_found")
        raise HTTPException(status_code=404, detail="No preview available for this study")

    try:
        ai_response = requests.post(
            f"http://{AI_INFERENCE_HOST}:{AI_INFERENCE_PORT}/infer",
            json={"object_path": object_path},
            timeout=10,
        )
    except requests.RequestException as exc:
        log_audit_event(request, "run_inference", study_id, "error")
        raise HTTPException(status_code=502, detail="AI inference service unavailable") from exc

    if ai_response.status_code != 200:
        log_audit_event(request, "run_inference", study_id, "error")
        try:
            detail = ai_response.json().get("detail", "AI inference service returned an error")
        except ValueError:
            detail = "AI inference service returned an error"
        # Forwards ai-inference's own status code (e.g. 404 for a missing
        # object, 422 for a bad image) instead of flattening every
        # non-200 response into a generic 502 - only an actual connection
        # failure to the service itself is a 502, handled above.
        raise HTTPException(status_code=ai_response.status_code, detail=detail)

    result = ai_response.json()
    result["result_id"] = store_ai_result(study_id, result)
    log_audit_event(request, "run_inference", study_id, "success")
    return result


@app.get("/studies/{study_id}/ai-results")
def list_ai_results(study_id: str, request: Request):
    """Every AI result ever stored for a study, newest first - so the
    dashboard can show the latest one without losing earlier runs."""
    try:
        fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "list_ai_results", study_id, "not_found")
        raise

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {AI_RESULT_COLUMNS} FROM ai_results "
                "WHERE orthanc_study_id = %s ORDER BY created_at DESC",
                (study_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    log_audit_event(request, "list_ai_results", study_id, "success")
    return [row_to_ai_result(row) for row in rows]


@app.get("/studies/{study_id}/ai-results/{result_id}/heatmap-image")
def get_ai_result_heatmap_image(study_id: str, result_id: int, request: Request):
    """Streams a stored AI result's Class Activation Mapping heatmap
    from MinIO, the same streaming pattern every other image endpoint
    in this API already uses. Not every result has one - the stat
    classifier never produces a heatmap, and an X-ray result can be
    missing one if heatmap generation itself failed."""
    try:
        fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "view_heatmap_image", study_id, "not_found")
        raise

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT heatmap_object FROM ai_results WHERE orthanc_study_id = %s AND result_id = %s",
                (study_id, result_id),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None or row[0] is None:
        log_audit_event(request, "view_heatmap_image", study_id, "not_found")
        raise HTTPException(status_code=404, detail="No heatmap available for this result")

    try:
        result = stream_minio_object(row[0])
    except S3Error as exc:
        log_audit_event(request, "view_heatmap_image", study_id, "not_found")
        raise HTTPException(status_code=404, detail="Heatmap object not found in MinIO") from exc

    log_audit_event(request, "view_heatmap_image", study_id, "success")
    return result


@app.get("/evaluation/summary")
def get_evaluation_summary():
    """Aggregate numbers from the last batch evaluation run (see
    evaluation/run_evaluation.py) - how many of the 24 known-label
    samples the X-ray model got right at the threshold that run used,
    not a live computation over every study in the platform."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT expected_group, match_status, inference_time_ms, threshold_used "
                "FROM xray_evaluation_results"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "total_samples": 0, "normal_count": 0, "abnormal_count": 0,
            "match_count": 0, "review_needed_count": 0, "mismatch_count": 0,
            "average_inference_time_ms": None, "threshold_used": None,
        }

    inference_times = [row[2] for row in rows if row[2] is not None]
    return {
        "total_samples": len(rows),
        "normal_count": sum(1 for row in rows if row[0] == "normal"),
        "abnormal_count": sum(1 for row in rows if row[0] == "abnormal"),
        "match_count": sum(1 for row in rows if row[1] == "match"),
        "review_needed_count": sum(1 for row in rows if row[1] == "review_needed"),
        "mismatch_count": sum(1 for row in rows if row[1] == "mismatch"),
        "average_inference_time_ms": round(sum(inference_times) / len(inference_times), 1)
        if inference_times else None,
        "threshold_used": rows[0][3],
    }


@app.get("/evaluation/samples")
def list_evaluation_samples():
    """Every sample from the last batch evaluation run, one row each -
    the dashboard's evaluation table reads this directly."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {EVALUATION_COLUMNS} FROM xray_evaluation_results "
                "ORDER BY expected_group, sample_id"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [row_to_evaluation_sample(row) for row in rows]


@app.get("/studies/{study_id}/slices")
def list_slices(study_id: str, request: Request):
    """Ordered list of slice previews for a multi-slice series (Step 18).
    Empty for studies that only have the one whole-study preview."""
    try:
        fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "list_slices", study_id, "not_found")
        raise

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT slice_index, instance_number, preview_object_path
                FROM study_slices
                WHERE orthanc_study_id = %s
                ORDER BY slice_index
                """,
                (study_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    log_audit_event(request, "list_slices", study_id, "success")
    return [
        {"slice_index": row[0], "instance_number": row[1], "preview_object_path": row[2]}
        for row in rows
    ]


@app.get("/studies/{study_id}/slices/{slice_index}/preview-image")
def get_slice_preview_image(study_id: str, slice_index: int, request: Request):
    """Streams one slice's preview PNG from MinIO, the same way
    /preview-image does for a study's single whole-study preview."""
    try:
        fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "view_slice_preview_image", study_id, "not_found")
        raise

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT preview_object_path FROM study_slices
                WHERE orthanc_study_id = %s AND slice_index = %s
                """,
                (study_id, slice_index),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        log_audit_event(request, "view_slice_preview_image", study_id, "not_found")
        raise HTTPException(status_code=404, detail="Slice not found for this study")

    try:
        result = stream_minio_object(row[0])
    except S3Error as exc:
        log_audit_event(request, "view_slice_preview_image", study_id, "not_found")
        raise HTTPException(status_code=404, detail="Preview object not found in MinIO") from exc

    log_audit_event(request, "view_slice_preview_image", study_id, "success")
    return result


@app.get("/audit-events")
def list_audit_events():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {AUDIT_COLUMNS} FROM audit_events ORDER BY event_id DESC LIMIT 50")
            rows = cur.fetchall()
    finally:
        conn.close()
    return [row_to_audit_event(row) for row in rows]


app.mount("/dashboard", StaticFiles(directory="static", html=True), name="dashboard")
