"""
AI inference microservice. Reads a preview PNG that already exists in
MinIO (produced earlier by services/preview-generator) and returns a
JSON result. The primary path runs a real pre-trained chest X-ray
model (TorchXRayVision's DenseNet, "densenet121-res224-all" weights);
a small pixel-statistics classifier, kept from Step 21, is used as a
fallback if the X-ray model isn't available or a caller asks for it
directly. CPU only, no GPU, no model training, no external AI service
calls. Every response carries a disclaimer making clear this is a
technical demo only.
"""

import io
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

import numpy as np
import torch
import torchvision.transforms
import torchxrayvision as xrv
from fastapi import FastAPI, HTTPException, Response
from minio import Minio
from minio.error import S3Error
from PIL import Image, UnidentifiedImageError
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, Info, generate_latest
from pydantic import BaseModel, Field

from model_config import (
    CONFIDENCE_THRESHOLD,
    DISCLAIMER,
    HEATMAP_TARGET_RULE,
    HIGH_VARIATION_THRESHOLD,
    LOW_VARIATION_THRESHOLD,
    MODEL_NAME,
    MODEL_VERSION,
    RUNTIME_MODE,
    TOP_FINDINGS_COUNT,
    XRAY_INPUT_SIZE,
    XRAY_MODEL_NAME,
    XRAY_MODEL_SOURCE,
    XRAY_MODEL_VERSION,
    XRAY_PREPROCESSING,
    XRAY_WEIGHTS,
)

SERVICE_NAME = "ai-inference"

INFERENCE_REQUESTS = Counter(
    "ai_inference_requests_total", "Total requests received by /infer",
)
INFERENCE_FAILURES = Counter(
    "ai_inference_failures_total", "Total /infer requests that failed",
    ["reason"],
)
INFERENCE_DURATION = Histogram(
    "ai_inference_duration_seconds", "Time spent handling an /infer request, in seconds",
)
MODEL_INFO = Info(
    "ai_inference_model", "Model name and version currently running",
)


def log_event(action, status="success", error=None, level="INFO", **extra):
    """Prints one JSON line per event, so `docker compose logs
    ai-inference` shows structured logs, the same pattern used by
    every other service in this project."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": SERVICE_NAME,
        "action": action,
        "status": status,
        "error": error,
    }
    entry.update(extra)
    print(json.dumps(entry), flush=True)


XRAY_MODEL = None
XRAY_TRANSFORM = None


def load_xray_model():
    """Loads the real chest X-ray model once, called at app startup
    rather than at import time - so importing this module (e.g. from a
    pytest file, to test classify_pixels or InferRequest) never
    triggers a model load or needs torch to actually run anything. If
    loading fails (e.g. weights weren't baked into the image and
    there's no internet at container startup), every /infer call just
    falls back to the stat classifier below instead of the service
    failing to start."""
    global XRAY_MODEL, XRAY_TRANSFORM
    try:
        XRAY_MODEL = xrv.models.DenseNet(weights=XRAY_WEIGHTS)
        XRAY_MODEL.eval()
        XRAY_TRANSFORM = torchvision.transforms.Compose(
            [xrv.datasets.XRayCenterCrop(), xrv.datasets.XRayResizer(XRAY_INPUT_SIZE)]
        )
        log_event("load_xray_model", status="success")
        MODEL_INFO.info({"model_name": XRAY_MODEL_NAME, "model_version": XRAY_MODEL_VERSION, "mode": "xray"})
    except Exception as exc:  # noqa: BLE001 - any load failure should fall back, not crash startup
        XRAY_MODEL = None
        XRAY_TRANSFORM = None
        log_event("load_xray_model", status="failed", level="ERROR", error=str(exc))
        MODEL_INFO.info({"model_name": MODEL_NAME, "model_version": MODEL_VERSION, "mode": "stat"})


MINIO_HOST = os.environ.get("MINIO_HOST", "localhost")
MINIO_PORT = os.environ.get("MINIO_PORT", "9000")
MINIO_ROOT_USER = os.environ.get("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "changeme")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "medimaging")


def get_minio_client():
    return Minio(
        f"{MINIO_HOST}:{MINIO_PORT}",
        access_key=MINIO_ROOT_USER,
        secret_key=MINIO_ROOT_PASSWORD,
        secure=False,
    )


def classify_pixels(pixels):
    """Pure demo classifier: buckets a grayscale image by how much its
    pixel intensities vary relative to their average brightness. No
    trained model is involved - this is descriptive statistics only,
    which is why the labels talk about "variation," not anatomy or
    pathology. Kept as the fallback path if the X-ray model isn't
    available."""
    pixels = pixels.astype(np.float64)
    mean = float(pixels.mean())
    std = float(pixels.std())
    variation = std / (mean + 1e-6)

    if variation >= HIGH_VARIATION_THRESHOLD:
        label = "high_variation_region"
        distance = variation - HIGH_VARIATION_THRESHOLD
    elif variation <= LOW_VARIATION_THRESHOLD:
        label = "low_variation_region"
        distance = LOW_VARIATION_THRESHOLD - variation
    else:
        label = "moderate_variation_region"
        distance = min(variation - LOW_VARIATION_THRESHOLD, HIGH_VARIATION_THRESHOLD - variation)

    confidence = round(min(0.99, 0.6 + distance), 3)
    return label, confidence


def run_xray_inference(pixels):
    """Runs the real TorchXRayVision DenseNet model over a grayscale
    image and returns every pathology's probability, plus the top
    findings sorted by probability. Raises if the model isn't loaded
    or the image can't be processed - the caller falls back to
    classify_pixels() in that case."""
    if XRAY_MODEL is None:
        raise RuntimeError("X-ray model is not loaded")

    img = pixels.astype(np.float32)
    img = xrv.datasets.normalize(img, 255)
    img = img[None, :, :]
    img = XRAY_TRANSFORM(img)
    tensor = torch.from_numpy(img).unsqueeze(0)

    with torch.no_grad():
        outputs = XRAY_MODEL(tensor)[0]

    probabilities = {
        label: round(float(prob), 4)
        for label, prob in zip(XRAY_MODEL.pathologies, outputs.detach().numpy())
    }
    top_findings = sorted(probabilities.items(), key=lambda item: -item[1])[:TOP_FINDINGS_COUNT]
    top_label, top_confidence = top_findings[0]

    return {
        "mode": "xray",
        "model_name": XRAY_MODEL_NAME,
        "model_version": XRAY_MODEL_VERSION,
        "prediction_label": top_label,
        "confidence": top_confidence,
        "top_findings": [{"label": label, "probability": prob} for label, prob in top_findings],
        "finding_probabilities": probabilities,
    }


def run_stat_inference(pixels):
    label, confidence = classify_pixels(pixels)
    return {
        "mode": "stat",
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "prediction_label": label,
        "confidence": confidence,
        "top_findings": [{"label": label, "probability": confidence}],
        "finding_probabilities": None,
    }


def run_inference(pixels, mode, object_path):
    if mode == "xray" and XRAY_MODEL is not None:
        try:
            return run_xray_inference(pixels)
        except Exception as exc:  # noqa: BLE001 - any x-ray failure falls back to the stat classifier
            log_event(
                "xray_fallback", status="fallback", level="WARNING",
                error=str(exc), input_object=object_path,
            )
    return run_stat_inference(pixels)


class InferRequest(BaseModel):
    object_path: str = Field(..., min_length=1)
    mode: Literal["xray", "stat"] = "xray"


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_xray_model()
    yield


app = FastAPI(title="Demo AI Inference Service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "xray_model_loaded": XRAY_MODEL is not None}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/config")
def get_config():
    """Everything in model_config.py, over HTTP - so the dashboard can show
    the running model's configuration without needing its own copy of
    these values baked in."""
    return {
        "xray_model_name": XRAY_MODEL_NAME,
        "xray_model_version": XRAY_MODEL_VERSION,
        "xray_weights": XRAY_WEIGHTS,
        "xray_model_source": XRAY_MODEL_SOURCE,
        "xray_input_size": XRAY_INPUT_SIZE,
        "xray_preprocessing": XRAY_PREPROCESSING,
        "top_findings_count": TOP_FINDINGS_COUNT,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "heatmap_target_rule": HEATMAP_TARGET_RULE,
        "runtime_mode": RUNTIME_MODE,
        "fallback_model_name": MODEL_NAME,
        "fallback_model_version": MODEL_VERSION,
        "disclaimer": DISCLAIMER,
    }


@app.post("/infer")
def infer(request: InferRequest):
    INFERENCE_REQUESTS.inc()
    started = time.monotonic()
    client = get_minio_client()

    try:
        response = client.get_object(MINIO_BUCKET, request.object_path)
        try:
            image_bytes = response.read()
        finally:
            response.close()
            response.release_conn()
    except S3Error as exc:
        INFERENCE_DURATION.observe(time.monotonic() - started)
        INFERENCE_FAILURES.labels(reason="not_found").inc()
        log_event(
            "infer", status="not_found", level="ERROR",
            error=str(exc), input_object=request.object_path,
        )
        raise HTTPException(status_code=404, detail="Input object not found in MinIO") from exc

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("L")
        pixels = np.array(image)
    except (UnidentifiedImageError, OSError) as exc:
        INFERENCE_DURATION.observe(time.monotonic() - started)
        INFERENCE_FAILURES.labels(reason="invalid_image").inc()
        log_event(
            "infer", status="invalid_image", level="ERROR",
            error=str(exc), input_object=request.object_path,
        )
        raise HTTPException(status_code=422, detail="Input object is not a valid image") from exc

    outcome = run_inference(pixels, request.mode, request.object_path)

    elapsed = time.monotonic() - started
    INFERENCE_DURATION.observe(elapsed)
    inference_time_ms = round(elapsed * 1000, 1)

    result = {
        "model_name": outcome["model_name"],
        "model_version": outcome["model_version"],
        "input_object": request.object_path,
        "mode": outcome["mode"],
        "prediction_label": outcome["prediction_label"],
        "confidence": outcome["confidence"],
        "top_findings": outcome["top_findings"],
        "finding_probabilities": outcome["finding_probabilities"],
        "inference_time_ms": inference_time_ms,
        "disclaimer": DISCLAIMER,
    }
    log_event(
        "infer", status="success", input_object=request.object_path,
        mode=outcome["mode"], prediction_label=outcome["prediction_label"],
        inference_time_ms=inference_time_ms,
    )
    return result
