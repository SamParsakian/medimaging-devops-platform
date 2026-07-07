"""
AI inference microservice. Reads a preview PNG that already exists in
MinIO (produced earlier by services/preview-generator) and returns a
JSON result. The primary path runs a real pre-trained chest X-ray
model (TorchXRayVision's DenseNet, "densenet121-res224-all" weights);
a small pixel-statistics classifier, kept from Step 21, is used as a
fallback if the X-ray model isn't available or a caller asks for it
directly. X-ray results also come with a heatmap image (Step 25),
showing which part of the image most influenced the top finding,
uploaded to MinIO alongside the original preview. CPU only, no GPU, no
model training, no external AI service calls. Every response carries
a disclaimer making clear this is a technical demo only.
"""

import io
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
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


def compute_cam(feature_maps, class_weights):
    """Class Activation Mapping (Zhou et al., 2016). TorchXRayVision's
    DenseNet ends with global-average-pooling straight into one Linear
    layer, which is exactly the architecture CAM was designed for - so
    the heatmap is computed directly from the classifier's own weights
    for the target finding, with no backward pass needed (a plain
    Grad-CAM reduces to this exact computation for this architecture,
    it just does it a longer way round). feature_maps: (C, H, W) numpy
    array from the last conv layer. class_weights: (C,) numpy array,
    the classifier's weights for one finding. Returns an (H, W) array
    scaled to [0, 1]."""
    cam = np.tensordot(class_weights, feature_maps, axes=([0], [0]))
    cam = np.maximum(cam, 0)
    if cam.max() > 0:
        cam = cam / cam.max()
    return cam


def apply_colormap(norm):
    """norm: 2D float array in [0, 1]. Returns an (H, W, 3) uint8 RGB
    array using a simple black -> red -> yellow -> white "hot"
    colormap, so no extra plotting library is needed just for this."""
    r = np.clip(norm * 3, 0, 1)
    g = np.clip(norm * 3 - 1, 0, 1)
    b = np.clip(norm * 3 - 2, 0, 1)
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)


def build_heatmap_overlay(base_pixels, cam, alpha=0.45):
    """base_pixels: 2D array, the same model-input-sized grayscale
    image the CAM was computed from (so the two line up spatially).
    cam: 2D float array in [0, 1], any size - resized up to match.
    Returns a PIL Image blending the colorized heatmap over the
    grayscale image."""
    height, width = base_pixels.shape
    cam_image = Image.fromarray((cam * 255).astype(np.uint8)).resize((width, height), Image.BILINEAR)
    cam_resized = np.array(cam_image).astype(np.float32) / 255.0
    heatmap_rgb = apply_colormap(cam_resized)

    base = base_pixels.astype(np.float32)
    base = (base - base.min()) / (base.max() - base.min() + 1e-6) * 255
    base_rgb = np.stack([base.astype(np.uint8)] * 3, axis=-1)

    overlay = (alpha * heatmap_rgb + (1 - alpha) * base_rgb).astype(np.uint8)
    return Image.fromarray(overlay)


def upload_heatmap(overlay_image, object_path):
    """Uploads a heatmap PNG to MinIO next to the "heatmaps/" prefix,
    named after the input object plus a short random suffix so
    repeated runs on the same image don't overwrite each other."""
    client = get_minio_client()
    stem = Path(object_path).stem
    heatmap_object = f"heatmaps/{stem}_{uuid.uuid4().hex[:8]}.png"

    buffer = io.BytesIO()
    overlay_image.save(buffer, format="PNG")
    buffer.seek(0)
    client.put_object(
        MINIO_BUCKET, heatmap_object, buffer, length=buffer.getbuffer().nbytes,
        content_type="image/png",
    )
    return heatmap_object


def run_xray_inference(pixels, object_path):
    """Runs the real TorchXRayVision DenseNet model over a grayscale
    image and returns every pathology's probability, plus the top
    findings sorted by probability and a heatmap for the top finding.
    Raises if the model isn't loaded or the image can't be processed -
    the caller falls back to classify_pixels() in that case."""
    if XRAY_MODEL is None:
        raise RuntimeError("X-ray model is not loaded")

    img = pixels.astype(np.float32)
    img = xrv.datasets.normalize(img, 255)
    img = img[None, :, :]
    img = XRAY_TRANSFORM(img)
    tensor = torch.from_numpy(img).unsqueeze(0)

    # The last conv layer's own output feature maps are needed for the
    # heatmap, so a forward hook grabs them on the way through - no
    # backward pass required (see compute_cam).
    feature_maps = {}
    handle = XRAY_MODEL.features.register_forward_hook(
        lambda module, module_in, module_out: feature_maps.update(value=module_out)
    )
    try:
        with torch.no_grad():
            outputs = XRAY_MODEL(tensor)[0]
    finally:
        handle.remove()

    probabilities = {
        label: round(float(prob), 4)
        for label, prob in zip(XRAY_MODEL.pathologies, outputs.detach().numpy())
    }
    top_findings = sorted(probabilities.items(), key=lambda item: -item[1])[:TOP_FINDINGS_COUNT]
    top_label, top_confidence = top_findings[0]

    heatmap_object = None
    try:
        top_index = XRAY_MODEL.pathologies.index(top_label)
        class_weights = XRAY_MODEL.classifier.weight[top_index].detach().numpy()
        cam = compute_cam(feature_maps["value"][0].detach().numpy(), class_weights)
        overlay_image = build_heatmap_overlay(img[0], cam)
        heatmap_object = upload_heatmap(overlay_image, object_path)
    except Exception as exc:  # noqa: BLE001 - a heatmap failure shouldn't lose the actual result
        log_event(
            "generate_heatmap", status="failed", level="WARNING",
            error=str(exc), input_object=object_path,
        )

    return {
        "mode": "xray",
        "model_name": XRAY_MODEL_NAME,
        "model_version": XRAY_MODEL_VERSION,
        "prediction_label": top_label,
        "confidence": top_confidence,
        "top_findings": [{"label": label, "probability": prob} for label, prob in top_findings],
        "finding_probabilities": probabilities,
        "heatmap_object": heatmap_object,
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
        "heatmap_object": None,
    }


def run_inference(pixels, mode, object_path):
    if mode == "xray" and XRAY_MODEL is not None:
        try:
            return run_xray_inference(pixels, object_path)
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
        "heatmap_object": outcome["heatmap_object"],
        "inference_time_ms": inference_time_ms,
        "disclaimer": DISCLAIMER,
    }
    log_event(
        "infer", status="success", input_object=request.object_path,
        mode=outcome["mode"], prediction_label=outcome["prediction_label"],
        inference_time_ms=inference_time_ms,
    )
    return result
