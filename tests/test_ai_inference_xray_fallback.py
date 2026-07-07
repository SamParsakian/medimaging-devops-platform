import numpy as np

from main import run_inference, run_stat_inference


def test_run_stat_inference_returns_a_single_top_finding():
    pixels = np.full((32, 32), 120, dtype=np.uint8)
    outcome = run_stat_inference(pixels)
    assert outcome["mode"] == "stat"
    assert outcome["finding_probabilities"] is None
    assert len(outcome["top_findings"]) == 1
    assert outcome["top_findings"][0]["label"] == outcome["prediction_label"]


def test_run_inference_falls_back_to_stat_when_the_xray_model_is_not_loaded():
    # The X-ray model is only loaded by the app's real startup lifespan,
    # never by plain module import - so XRAY_MODEL is still None here,
    # and asking for "xray" mode should fall back to the stat classifier.
    pixels = np.full((32, 32), 120, dtype=np.uint8)
    outcome = run_inference(pixels, "xray", "some/object.png")
    assert outcome["mode"] == "stat"


def test_run_inference_uses_stat_mode_directly_when_requested():
    pixels = np.full((32, 32), 120, dtype=np.uint8)
    outcome = run_inference(pixels, "stat", "some/object.png")
    assert outcome["mode"] == "stat"
