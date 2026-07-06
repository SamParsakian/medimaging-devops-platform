"""
Demo AI inference microservice. Reads a preview PNG that already
exists in MinIO (produced earlier by services/preview-generator) and
returns a JSON result from a small pixel-statistics classifier - not a
trained neural network. CPU only, no GPU, no model training, no
external AI service calls. Every response carries a disclaimer making
clear this is a technical demo only.
"""

import io
import json
import os
import time
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, HTTPException
from minio import Minio
from minio.error import S3Error
from PIL import Image
from pydantic import BaseModel

SERVICE_NAME = "ai-inference"
MODEL_NAME = "demo-image-stat-classifier"
MODEL_VERSION = "0.1.0"
DISCLAIMER = "Technical demo only. Not for clinical diagnosis."

# Demo thresholds for bucketing an image by how much its pixel
# intensities vary relative to their average brightness. Not tuned
# against any clinical meaning - just descriptive image statistics.
LOW_VARIATION_THRESHOLD = 0.4
HIGH_VARIATION_THRESHOLD = 0.9


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
    pathology."""
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


class InferRequest(BaseModel):
    object_path: str


app = FastAPI(title="Demo AI Inference Service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/infer")
def infer(request: InferRequest):
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
        log_event(
            "infer", status="not_found", level="ERROR",
            error=str(exc), input_object=request.object_path,
        )
        raise HTTPException(status_code=404, detail="Input object not found in MinIO") from exc

    image = Image.open(io.BytesIO(image_bytes)).convert("L")
    pixels = np.array(image)
    label, confidence = classify_pixels(pixels)

    inference_time_ms = round((time.monotonic() - started) * 1000, 1)

    result = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "input_object": request.object_path,
        "prediction_label": label,
        "confidence": confidence,
        "inference_time_ms": inference_time_ms,
        "disclaimer": DISCLAIMER,
    }
    log_event(
        "infer", status="success", input_object=request.object_path,
        prediction_label=label, inference_time_ms=inference_time_ms,
    )
    return result
