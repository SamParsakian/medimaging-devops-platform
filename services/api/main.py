"""
Read-only FastAPI service exposing study metadata and preview info
from the PostgreSQL `studies` table (populated by
services/metadata-extractor/extract.py), plus a small static
dashboard (services/api/static/) that reads the same endpoints, and
a basic audit trail of who looked at what. No real auth yet - one
fixed demo user, protected by a single shared API key.
"""

import io
import json
import os
import time
import uuid
from datetime import datetime, timezone

import numpy as np
import psycopg2
import pydicom
import requests
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from minio import Minio
from minio.error import S3Error
from PIL import Image
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

# Ops Dashboard (Step 28 addition): where each group of services actually
# runs. All three default to "localhost" since everything runs on one
# machine today - a real multi-node deployment (Step 29) only needs these
# three values changed in .env, no code changes here.
APP_NODE_HOST = os.environ.get("APP_NODE_HOST", "localhost")
DATA_NODE_HOST = os.environ.get("DATA_NODE_HOST", "localhost")
OPS_NODE_HOST = os.environ.get("OPS_NODE_HOST", "localhost")
API_PORT = os.environ.get("API_PORT", "8000")
MINIO_CONSOLE_PORT = os.environ.get("MINIO_CONSOLE_PORT", "9001")
ORTHANC_HTTP_PORT = os.environ.get("ORTHANC_HTTP_PORT", "8042")
PROMETHEUS_PORT = os.environ.get("PROMETHEUS_PORT", "9090")
GRAFANA_PORT = os.environ.get("GRAFANA_PORT", "3000")

# Where the API's own backend actually reaches each service for the Ops
# Dashboard's reachability check (build_ops_links below) - separate from
# APP_NODE_HOST/DATA_NODE_HOST/OPS_NODE_HOST above, which are the public
# addresses a browser uses. On one machine these default to the Compose
# service names (see docker-compose.yml's "api" environment block); on a
# real multi-node deployment (Step 29) they're set to each node's private
# network address instead, so the check travels over the private network
# rather than back out over the public internet.
ORTHANC_HOST = os.environ.get("ORTHANC_HOST", "orthanc")
PROMETHEUS_HOST = os.environ.get("PROMETHEUS_HOST", "prometheus")
GRAFANA_HOST = os.environ.get("GRAFANA_HOST", "grafana")

# Step 29 addition: the real DICOM pipeline demo (see build_pipeline_status
# below) needs the API to talk to Orthanc's own REST API directly, not just
# check it's reachable - so it needs real credentials, unlike ORTHANC_HOST
# above which was reachability-check only until now.
ORTHANC_USER = os.environ.get("ORTHANC_USER", "orthanc")
ORTHANC_PASSWORD = os.environ.get("ORTHANC_PASSWORD", "changeme")

# This platform's safety rule is "no real patient data, ever" - every
# study it ever holds is demo/anonymized data by design, so PatientID
# is always safe to expose here.
DEMO_DATA_ONLY = True

# No real auth yet - every request is logged under this one demo user.
DEMO_USER_ID = "demo-user"

# Doctor-controlled default for new uploads (Step 28): whether a radiographer's
# upload runs AI immediately or waits for a doctor to trigger it explicitly
# from the Doctor Review view. In-memory only, same demo-grade limitation as
# everything else here without a real settings table - it resets to True if
# the api container restarts, which is fine for a local demo.
APP_SETTINGS = {"auto_ai_default": True}

# Demo-grade security: one shared API key from the environment, checked
# against the X-API-Key header, an api_key query parameter, or an api_key
# cookie (Step 29: the dashboard now sets this cookie once via auth.js
# instead of carrying the key in the URL - the query param stays supported
# as a one-time bootstrap for an old bookmarked link, and for curl/scripts).
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "changeme")
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/metrics"}
# The whole /dashboard/ static mount is public (Step 29) - it's a separate
# StaticFiles mount from every real data endpoint below (/studies,
# /audit-events, /ai-results, and the rest all live at the top level, still
# fully protected), so serving its HTML/CSS/JS without a key first leaks no
# study or patient data. It has to be public for auth.js to even run: on a
# first visit with no api_key cookie yet, the page itself would otherwise
# 401 before its own script had a chance to prompt for the key and set one.
PUBLIC_PATH_PREFIXES = ("/dashboard/",)

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

    if path not in PUBLIC_PATHS and not path.startswith(PUBLIC_PATH_PREFIXES):
        provided_key = (
            request.headers.get("X-API-Key")
            or request.query_params.get("api_key")
            or request.cookies.get("api_key")
        )

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
    "preview_status, upload_status, last_error, workflow_status, created_at"
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
        "workflow_status": row[14],
        "created_at": row[15].isoformat() if row[15] else None,
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


def set_workflow_status(study_id, workflow_status, last_error=None):
    """Updates a study's workflow_status (see infra/postgres/init.sql) as
    POST /studies/upload works through received -> stored -> ai_processing
    -> ready_for_review/failed, so the current stage is visible to anyone
    looking at the study, not only revealed once the whole request finishes."""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE studies SET workflow_status = %s, last_error = %s, "
                    "updated_at = now() WHERE orthanc_study_id = %s",
                    (workflow_status, last_error, study_id),
                )
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


@app.get("/settings")
def get_settings():
    """The doctor-controlled default from the Doctor Review view - whether
    a new upload runs AI automatically or waits for an explicit doctor
    trigger. The Radiographer Upload view reads this too, so a radiographer
    can see the current policy without being able to change it themselves."""
    return dict(APP_SETTINGS)


@app.post("/settings")
def update_settings(request: Request, auto_ai_default: bool = Body(..., embed=True)):
    APP_SETTINGS["auto_ai_default"] = auto_ai_default
    log_audit_event(request, "update_settings", None, "success")
    return dict(APP_SETTINGS)


def build_ops_links():
    """The Ops Dashboard's link list (Step 28 addition). Each entry's "url"
    (what the browser opens) comes from APP_NODE_HOST/DATA_NODE_HOST/
    OPS_NODE_HOST - grouped by which node each service runs on. Each one
    points at the specific page worth seeing, not just the service's home
    page (Step 29) - the bucket browser, the DICOM explorer, Prometheus's
    targets list, and the AI inference Grafana dashboard. "check_url" is
    separate on purpose: it's where the API's own backend reaches each
    service from inside its own node, which is MINIO_HOST/ORTHANC_HOST/
    PROMETHEUS_HOST/GRAFANA_HOST - Compose service names on one machine,
    each node's private network address on the real Step 29 deployment."""
    return [
        {
            "name": "API Docs", "node": "app", "description": "Swagger UI for this API",
            "url": f"http://{APP_NODE_HOST}:{API_PORT}/docs",
            "check_url": "http://localhost:8000/docs",
        },
        {
            "name": "MinIO Console", "node": "data", "description": "Object storage browser",
            "url": f"http://{DATA_NODE_HOST}:{MINIO_CONSOLE_PORT}/browser/{MINIO_BUCKET}",
            "check_url": f"http://{MINIO_HOST}:9001",
        },
        {
            "name": "Orthanc Explorer", "node": "data", "description": "DICOM server",
            "url": f"http://{DATA_NODE_HOST}:{ORTHANC_HTTP_PORT}/app/explorer.html",
            "check_url": f"http://{ORTHANC_HOST}:{ORTHANC_HTTP_PORT}",
        },
        {
            "name": "Prometheus", "node": "ops", "description": "Metrics and alerts",
            "url": f"http://{OPS_NODE_HOST}:{PROMETHEUS_PORT}/targets",
            "check_url": f"http://{PROMETHEUS_HOST}:9090",
        },
        {
            "name": "Grafana", "node": "ops", "description": "Monitoring dashboards",
            "url": f"http://{OPS_NODE_HOST}:{GRAFANA_PORT}/d/ai-inference-overview",
            "check_url": f"http://{GRAFANA_HOST}:3000",
        },
    ]


@app.get("/ops-links")
def get_ops_links():
    """Reachability is checked server-side against check_url (not url,
    and not by the browser) so a private/internal-only node address still
    reports correctly even though the browser viewing this page might not
    be able to reach it directly - the check only proves the API's own
    network path to each service."""
    links = build_ops_links()
    for link in links:
        check_url = link.pop("check_url")
        try:
            response = requests.get(check_url, timeout=1.5)
            link["reachable"] = response.status_code < 500
        except requests.RequestException:
            link["reachable"] = False
    return links


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


@app.post("/studies/upload")
async def upload_study(
    request: Request, file: UploadFile = File(...), label: str = Form(""),
    auto_ai: str | None = Form(None),
):
    """The Radiographer Upload view's endpoint (Step 28): takes a plain
    image file straight from the browser (no DICOM, no Orthanc - same
    "already a PNG" shortcut Steps 24/26 used for their own X-ray samples),
    creates a new study for it, and walks it through the same pipeline a
    real upload would need: store the file, run it through the existing
    AI inference path, and record the result - updating workflow_status at
    each stage so the current step is visible on the studies list the whole
    time, not only once everything finishes. Whether AI runs automatically
    is the doctor's call, not the radiographer's - see APP_SETTINGS and
    GET/POST /settings - so auto_ai isn't normally sent by the upload form
    at all; it's only accepted here as an explicit override for testing.
    When skipped, the study sits at "awaiting_review" until a doctor runs
    it explicitly via POST /studies/{id}/infer (see run_inference below)."""
    study_id = f"clinic-upload-{uuid.uuid4().hex[:8]}"
    file_bytes = await file.read()

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO studies (
                        orthanc_study_id, study_instance_uid, modality, study_description,
                        series_count, instance_count, processing_status, anonymization_status,
                        preview_status, upload_status, workflow_status
                    )
                    VALUES (%s, %s, 'CR', %s, 1, 1, 'done', 'skipped', 'done', 'done', 'received')
                    """,
                    (
                        study_id,
                        f"clinic-upload.{study_id}",
                        label or f"Clinic workflow upload ({file.filename})",
                    ),
                )
    finally:
        conn.close()

    object_path = f"samples/clinic-upload/{study_id}/{file.filename}"
    try:
        client = get_minio_client()
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
        client.put_object(
            MINIO_BUCKET, object_path, io.BytesIO(file_bytes), length=len(file_bytes),
            content_type=file.content_type or "image/png",
        )
    except S3Error as exc:
        set_workflow_status(study_id, "failed", str(exc))
        log_audit_event(request, "upload_study", study_id, "error")
        raise HTTPException(status_code=502, detail="Could not store the uploaded image") from exc

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE studies SET preview_object_path = %s WHERE orthanc_study_id = %s",
                    (object_path, study_id),
                )
    finally:
        conn.close()
    set_workflow_status(study_id, "stored")

    if auto_ai is None:
        run_ai_now = APP_SETTINGS["auto_ai_default"]
    else:
        run_ai_now = auto_ai.lower() in ("true", "1", "yes", "on")
    ai_result = None
    upload_ok = True
    if run_ai_now:
        set_workflow_status(study_id, "ai_processing")
        try:
            ai_response = requests.post(
                f"http://{AI_INFERENCE_HOST}:{AI_INFERENCE_PORT}/infer",
                json={"object_path": object_path}, timeout=30,
            )
            ai_response.raise_for_status()
            ai_result = ai_response.json()
            ai_result["result_id"] = store_ai_result(study_id, ai_result)
            set_workflow_status(study_id, "ready_for_review")
        except (requests.RequestException, KeyError) as exc:
            set_workflow_status(study_id, "failed", str(exc))
            upload_ok = False
    else:
        set_workflow_status(study_id, "awaiting_review")

    log_audit_event(request, "upload_study", study_id, "success" if upload_ok else "error")
    return {"study": fetch_study(study_id), "ai_result": ai_result}


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
    or ai-inference access - same idea as stream_minio_object above. For
    a clinic-workflow study (Step 28, workflow_status is set), this is
    also what the Doctor Review view's "Run AI Evaluation" button calls
    when a radiographer uploaded with auto_ai off - so a successful run
    here advances workflow_status the same way an automatic one would."""
    try:
        study = fetch_study(study_id)
    except HTTPException:
        log_audit_event(request, "run_inference", study_id, "not_found")
        raise

    object_path = study["preview_object_path"]
    if not object_path:
        log_audit_event(request, "run_inference", study_id, "not_found")
        raise HTTPException(status_code=404, detail="No preview available for this study")

    if study["workflow_status"]:
        set_workflow_status(study_id, "ai_processing")

    try:
        ai_response = requests.post(
            f"http://{AI_INFERENCE_HOST}:{AI_INFERENCE_PORT}/infer",
            json={"object_path": object_path},
            timeout=10,
        )
    except requests.RequestException as exc:
        if study["workflow_status"]:
            set_workflow_status(study_id, "failed", str(exc))
        log_audit_event(request, "run_inference", study_id, "error")
        raise HTTPException(status_code=502, detail="AI inference service unavailable") from exc

    if ai_response.status_code != 200:
        try:
            detail = ai_response.json().get("detail", "AI inference service returned an error")
        except ValueError:
            detail = "AI inference service returned an error"
        if study["workflow_status"]:
            set_workflow_status(study_id, "failed", detail)
        log_audit_event(request, "run_inference", study_id, "error")
        # Forwards ai-inference's own status code (e.g. 404 for a missing
        # object, 422 for a bad image) instead of flattening every
        # non-200 response into a generic 502 - only an actual connection
        # failure to the service itself is a 502, handled above.
        raise HTTPException(status_code=ai_response.status_code, detail=detail)

    result = ai_response.json()
    result["result_id"] = store_ai_result(study_id, result)
    if study["workflow_status"]:
        set_workflow_status(study_id, "ready_for_review")
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
def list_audit_events(study_id: str | None = None):
    """study_id is optional - passing it doesn't add a new tracking
    feature, it just filters the same audit trail every other endpoint
    already writes to. The Doctor Review view (Step 28) uses this to show
    "Reviewed" for a study only once a real view_study event exists for
    it, instead of a separate reviewed flag with nothing behind it."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if study_id:
                cur.execute(
                    f"SELECT {AUDIT_COLUMNS} FROM audit_events WHERE study_id = %s "
                    "ORDER BY event_id DESC LIMIT 50",
                    (study_id,),
                )
            else:
                cur.execute(f"SELECT {AUDIT_COLUMNS} FROM audit_events ORDER BY event_id DESC LIMIT 50")
            rows = cur.fetchall()
    finally:
        conn.close()
    return [row_to_audit_event(row) for row in rows]



# --- Step 29: real DICOM pipeline stepper -----------------------------
#
# Every earlier X-ray demo in this project (Steps 21-28) fed the AI model
# a preview image that already existed - it never showed the actual
# DICOM -> Orthanc -> anonymize -> preview -> MinIO pipeline that Steps
# 1-18 built, running against a real remote deployment. This section
# lets one DICOM study, already uploaded to Orthanc by hand (through its
# own web interface, not this API), be walked through that pipeline one
# stage at a time from the dashboard's home page - each stage is a real
# action against Orthanc, Postgres, or MinIO, not a simulation.
#
# State is a single in-memory dict, the same demo-grade pattern as
# APP_SETTINGS above - one pipeline run at a time, reset if the api
# container restarts. That matches how this is actually used: one DICOM
# file, walked through by hand, during a demo recording.

PIPELINE_STAGE_ORDER = ["extracted", "anonymized", "preview", "dicom_uploaded", "preview_uploaded", "inference"]
PIPELINE_STAGE_LABELS = {
    "extracted": "Study Found & Metadata Saved",
    "anonymized": "DICOM Anonymized",
    "preview": "Preview Generated",
    "dicom_uploaded": "Anonymized DICOM Stored in MinIO",
    "preview_uploaded": "Preview Stored in MinIO",
    "inference": "AI Inference + Heatmap",
}
PIPELINE_SCRATCH_DIR = "/tmp/pipeline-scratch"

# Duplicated from services/anonymizer/rules.py - the api container can't
# import that service's module directly (separate image, separate
# dependencies), so the same small rule set is kept here instead.
PIPELINE_ANONYMIZATION_RULES = {
    "PatientName": "Anonymous^Demo",
    "PatientID": "ANON0001",
    "PatientBirthDate": "",
    "AccessionNumber": "",
    "InstitutionName": "Demo Institution",
    "ReferringPhysicianName": "",
}

PIPELINE_STATE = {
    "orthanc_study_id": None,
    "study_instance_uid": None,
    "first_instance_id": None,
    "anonymized_path": None,
    "preview_path": None,
    "completed": [],
    "details": {},
}


def pipeline_orthanc_get(path):
    response = requests.get(
        f"http://{ORTHANC_HOST}:{ORTHANC_HTTP_PORT}{path}",
        auth=(ORTHANC_USER, ORTHANC_PASSWORD),
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def pipeline_to_8bit_pixels(dataset):
    """Same windowing logic as services/preview-generator/generate_preview.py's
    to_8bit_pixels - duplicated here for the same reason as the
    anonymization rules above."""
    pixels = dataset.pixel_array.astype(np.float64)

    slope = float(getattr(dataset, "RescaleSlope", 1))
    intercept = float(getattr(dataset, "RescaleIntercept", 0))
    pixels = pixels * slope + intercept

    center = getattr(dataset, "WindowCenter", None)
    width = getattr(dataset, "WindowWidth", None)
    if isinstance(center, pydicom.multival.MultiValue):
        center = center[0]
    if isinstance(width, pydicom.multival.MultiValue):
        width = width[0]

    if center is not None and width is not None:
        low = float(center) - float(width) / 2
        high = float(center) + float(width) / 2
    else:
        low = pixels.min()
        high = pixels.max()

    pixels = np.clip(pixels, low, high)
    if high > low:
        pixels = (pixels - low) / (high - low) * 255.0
    else:
        pixels = np.zeros_like(pixels)

    return pixels.astype(np.uint8)


def pipeline_stage_extracted():
    """Mirrors services/metadata-extractor/extract.py: that script finds
    every study currently in Orthanc and saves each one's metadata to
    Postgres in a single run. This stage does the same two things for
    one study, one at a time, so each can be a separate stop here."""
    study_ids = pipeline_orthanc_get("/studies")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT orthanc_study_id FROM studies")
            known_ids = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    candidates = [study_id for study_id in study_ids if study_id not in known_ids]
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail="No new study found in Orthanc - upload a DICOM file through Orthanc's own web interface first.",
        )

    orthanc_study_id = candidates[0]
    PIPELINE_STATE["orthanc_study_id"] = orthanc_study_id

    study = pipeline_orthanc_get(f"/studies/{orthanc_study_id}")
    main_tags = study.get("MainDicomTags", {})
    patient_tags = study.get("PatientMainDicomTags", {})
    series_ids = study.get("Series", [])

    series_instance_uid = None
    modality = None
    instance_count = 0
    first_instance_id = None
    for index, series_id in enumerate(series_ids):
        series = pipeline_orthanc_get(f"/series/{series_id}")
        instance_ids = series.get("Instances", [])
        instance_count += len(instance_ids)
        if index == 0:
            series_tags = series.get("MainDicomTags", {})
            series_instance_uid = series_tags.get("SeriesInstanceUID")
            modality = series_tags.get("Modality")
            if instance_ids:
                first_instance_id = instance_ids[0]

    study_instance_uid = main_tags.get("StudyInstanceUID")
    study_date_raw = main_tags.get("StudyDate")
    study_date = None
    if study_date_raw:
        try:
            study_date = datetime.strptime(study_date_raw, "%Y%m%d").date()
        except ValueError:
            study_date = None

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO studies (
                        orthanc_study_id, study_instance_uid, series_instance_uid,
                        patient_id, patient_name, modality, study_date, study_description,
                        series_count, instance_count, processing_status, last_error, updated_at,
                        workflow_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'done', NULL, now(), 'received')
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
                        updated_at = now()
                    """,
                    (
                        orthanc_study_id, study_instance_uid, series_instance_uid,
                        patient_tags.get("PatientID"), patient_tags.get("PatientName"), modality,
                        study_date, main_tags.get("StudyDescription"),
                        len(series_ids), instance_count,
                    ),
                )
    finally:
        conn.close()

    PIPELINE_STATE["study_instance_uid"] = study_instance_uid
    PIPELINE_STATE["first_instance_id"] = first_instance_id
    return {
        "orthanc_study_id": orthanc_study_id,
        "patient_id": patient_tags.get("PatientID"),
        "modality": modality,
        "study_description": main_tags.get("StudyDescription"),
    }


def pipeline_stage_anonymized():
    instance_id = PIPELINE_STATE["first_instance_id"]
    response = requests.get(
        f"http://{ORTHANC_HOST}:{ORTHANC_HTTP_PORT}/instances/{instance_id}/file",
        auth=(ORTHANC_USER, ORTHANC_PASSWORD),
        timeout=20,
    )
    response.raise_for_status()
    dataset = pydicom.dcmread(io.BytesIO(response.content))

    for tag, replacement in PIPELINE_ANONYMIZATION_RULES.items():
        if not hasattr(dataset, tag) and replacement == "":
            continue
        setattr(dataset, tag, replacement)

    os.makedirs(PIPELINE_SCRATCH_DIR, exist_ok=True)
    filename = f"anonymized_{PIPELINE_STATE['orthanc_study_id']}.dcm"
    output_path = os.path.join(PIPELINE_SCRATCH_DIR, filename)
    dataset.save_as(output_path)

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE studies SET anonymization_status = %s, updated_at = now() WHERE study_instance_uid = %s",
                    ("done", PIPELINE_STATE["study_instance_uid"]),
                )
    finally:
        conn.close()

    PIPELINE_STATE["anonymized_path"] = output_path
    return {"anonymized_filename": filename}


def pipeline_stage_preview():
    dataset = pydicom.dcmread(PIPELINE_STATE["anonymized_path"])
    pixels = pipeline_to_8bit_pixels(dataset)

    filename = f"preview_{PIPELINE_STATE['orthanc_study_id']}.png"
    output_path = os.path.join(PIPELINE_SCRATCH_DIR, filename)
    Image.fromarray(pixels).save(output_path)

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE studies SET preview_status = %s, updated_at = now() WHERE study_instance_uid = %s",
                    ("done", PIPELINE_STATE["study_instance_uid"]),
                )
    finally:
        conn.close()

    PIPELINE_STATE["preview_path"] = output_path
    return {"preview_filename": filename}


def pipeline_stage_dicom_uploaded():
    """Mirrors services/minio-uploader/upload.py: uploads the anonymized
    DICOM file to MinIO. A separate, independent script from the preview
    upload below - it has no involvement in storing the preview PNG."""
    study_uid = PIPELINE_STATE["study_instance_uid"]
    client = get_minio_client()
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)

    anonymized_path = PIPELINE_STATE["anonymized_path"]
    anonymized_object = f"processed/anonymized/{study_uid}/{os.path.basename(anonymized_path)}"
    client.fput_object(MINIO_BUCKET, anonymized_object, anonymized_path)

    return {"minio_anonymized_object": anonymized_object}


def pipeline_stage_preview_uploaded():
    """Mirrors services/preview-generator/upload_preview.py: uploads the
    preview PNG to MinIO. A separate, independent script from the DICOM
    upload above - it has no involvement in storing the anonymized DICOM."""
    study_uid = PIPELINE_STATE["study_instance_uid"]
    client = get_minio_client()
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)

    preview_path = PIPELINE_STATE["preview_path"]
    preview_object = f"processed/previews/{study_uid}/{os.path.basename(preview_path)}"
    client.fput_object(MINIO_BUCKET, preview_object, preview_path)

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE studies SET preview_object_path = %s, upload_status = %s, updated_at = now() "
                    "WHERE study_instance_uid = %s",
                    (preview_object, "done", study_uid),
                )
    finally:
        conn.close()

    return {"minio_preview_object": preview_object}


def pipeline_stage_inference():
    orthanc_study_id = PIPELINE_STATE["orthanc_study_id"]
    study = fetch_study(orthanc_study_id)
    object_path = study["preview_object_path"]
    if not object_path:
        raise HTTPException(status_code=404, detail="No preview available yet - run the earlier stages first.")

    # Same Upload Review Policy (APP_SETTINGS["auto_ai_default"], see
    # review.html's toggle) that governs the Step 28 clinic upload also
    # governs this last pipeline stage - when it's off, AI evaluation stays
    # the doctor's call, run from Doctor Review's "Run AI Evaluation"
    # button (POST /studies/{id}/infer), not something "Next" does for them.
    if not APP_SETTINGS["auto_ai_default"]:
        set_workflow_status(orthanc_study_id, "awaiting_review")
        return {"awaiting_doctor_review": True}

    ai_response = requests.post(
        f"http://{AI_INFERENCE_HOST}:{AI_INFERENCE_PORT}/infer",
        json={"object_path": object_path},
        timeout=10,
    )
    if ai_response.status_code != 200:
        try:
            detail = ai_response.json().get("detail", "AI inference service returned an error")
        except ValueError:
            detail = "AI inference service returned an error"
        raise HTTPException(status_code=ai_response.status_code, detail=detail)

    result = ai_response.json()
    result_id = store_ai_result(orthanc_study_id, result)
    set_workflow_status(orthanc_study_id, "ready_for_review")
    return {
        "prediction_label": result.get("prediction_label"),
        "confidence": result.get("confidence"),
        "heatmap_object": result.get("heatmap_object"),
        "result_id": result_id,
    }


PIPELINE_STAGE_FUNCTIONS = {
    "extracted": pipeline_stage_extracted,
    "anonymized": pipeline_stage_anonymized,
    "preview": pipeline_stage_preview,
    "dicom_uploaded": pipeline_stage_dicom_uploaded,
    "preview_uploaded": pipeline_stage_preview_uploaded,
    "inference": pipeline_stage_inference,
}


def pipeline_status_payload():
    return {
        "stages": [
            {
                "key": key,
                "label": PIPELINE_STAGE_LABELS[key],
                "done": key in PIPELINE_STATE["completed"],
                "detail": PIPELINE_STATE["details"].get(key),
            }
            for key in PIPELINE_STAGE_ORDER
        ],
        "orthanc_study_id": PIPELINE_STATE["orthanc_study_id"],
        "next_stage": next((k for k in PIPELINE_STAGE_ORDER if k not in PIPELINE_STATE["completed"]), None),
    }


@app.get("/pipeline/status")
def get_pipeline_status():
    return pipeline_status_payload()


@app.post("/pipeline/reset")
def reset_pipeline(request: Request):
    """Clears the in-memory pipeline demo state, so a newly uploaded
    DICOM study can be walked through from the first stage again."""
    PIPELINE_STATE.update({
        "orthanc_study_id": None,
        "study_instance_uid": None,
        "first_instance_id": None,
        "anonymized_path": None,
        "preview_path": None,
        "completed": [],
        "details": {},
    })
    log_audit_event(request, "reset_pipeline", None, "success")
    return pipeline_status_payload()


@app.post("/pipeline/next")
def pipeline_next(request: Request):
    next_stage = next((k for k in PIPELINE_STAGE_ORDER if k not in PIPELINE_STATE["completed"]), None)
    if next_stage is None:
        raise HTTPException(status_code=400, detail="Pipeline already complete for this study.")

    try:
        detail = PIPELINE_STAGE_FUNCTIONS[next_stage]()
    except HTTPException:
        log_audit_event(request, f"pipeline_{next_stage}", PIPELINE_STATE.get("orthanc_study_id"), "error")
        raise
    except Exception as exc:
        log_audit_event(request, f"pipeline_{next_stage}", PIPELINE_STATE.get("orthanc_study_id"), "error")
        raise HTTPException(status_code=500, detail=f"Pipeline stage '{next_stage}' failed: {exc}") from exc

    PIPELINE_STATE["completed"].append(next_stage)
    PIPELINE_STATE["details"][next_stage] = detail
    log_audit_event(request, f"pipeline_{next_stage}", PIPELINE_STATE.get("orthanc_study_id"), "success")
    return pipeline_status_payload()


app.mount("/dashboard", StaticFiles(directory="static", html=True), name="dashboard")
