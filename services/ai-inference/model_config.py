"""
Central configuration for the ai-inference service: which model runs,
how its input is prepared, and how its output should be read - kept
in one place instead of scattered as bare constants through main.py.
See docs/ai-model-config.md for the full explanation of each value.
"""

# --- Stat classifier (fallback model, Step 21) ---
MODEL_NAME = "demo-image-stat-classifier"
MODEL_VERSION = "0.1.0"

# Demo thresholds for bucketing an image by how much its pixel
# intensities vary relative to their average brightness. Not tuned
# against any clinical meaning - just descriptive image statistics.
LOW_VARIATION_THRESHOLD = 0.4
HIGH_VARIATION_THRESHOLD = 0.9

# --- X-ray model (primary model, Step 24) ---
XRAY_MODEL_NAME = "torchxrayvision-densenet121-res224-all"
XRAY_MODEL_VERSION = "1.5.2"
XRAY_WEIGHTS = "densenet121-res224-all"
XRAY_MODEL_SOURCE = "https://github.com/mlmed/torchxrayvision"
XRAY_INPUT_SIZE = 224
XRAY_PREPROCESSING = (
    f"convert to grayscale, normalize pixel values to the [-1024, 1024] "
    f"range TorchXRayVision's own models expect, center-crop, then "
    f"resize to {XRAY_INPUT_SIZE}x{XRAY_INPUT_SIZE}"
)

# --- How the output should be interpreted ---
TOP_FINDINGS_COUNT = 5
# TorchXRayVision's own convention treats 0.5 as the line between a
# positive and negative signal for a finding. This project doesn't
# filter findings by it - the top 5 are always shown regardless - it's
# only used to help read the numbers, which is why the dashboard notes
# that values near 50% aren't confident either way.
CONFIDENCE_THRESHOLD = 0.5
# Decided ahead of the heatmap feature (Step 25): a heatmap explains
# exactly one finding, and it's always the single highest-probability
# one, not every finding shown in the table.
HEATMAP_TARGET_RULE = "top_finding"

# --- Runtime ---
RUNTIME_MODE = "cpu"

DISCLAIMER = "Technical demo only. Not for clinical diagnosis."
