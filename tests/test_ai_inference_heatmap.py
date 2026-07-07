import numpy as np
from PIL import Image

from main import apply_colormap, build_heatmap_overlay, compute_cam


def test_compute_cam_picks_out_the_weighted_channel():
    # Two channels, weight only the first one - the CAM should just be
    # that channel's feature map, ReLU'd and normalized to max 1.
    feature_maps = np.array([[[1.0, 2.0], [3.0, 4.0]], [[5.0, 5.0], [5.0, 5.0]]])
    class_weights = np.array([1.0, 0.0])
    cam = compute_cam(feature_maps, class_weights)
    assert cam.shape == (2, 2)
    assert cam.max() == 1.0
    assert np.allclose(cam, feature_maps[0] / feature_maps[0].max())


def test_compute_cam_clips_negative_values_to_zero():
    feature_maps = np.array([[[-1.0, -2.0]]])
    class_weights = np.array([1.0])
    cam = compute_cam(feature_maps, class_weights)
    assert cam.min() >= 0
    assert cam.max() == 0


def test_apply_colormap_maps_zero_to_black_and_one_to_white():
    norm = np.array([[0.0, 1.0]])
    rgb = apply_colormap(norm)
    assert rgb.shape == (1, 2, 3)
    assert tuple(rgb[0, 0]) == (0, 0, 0)
    assert tuple(rgb[0, 1]) == (255, 255, 255)


def test_build_heatmap_overlay_matches_the_base_image_size():
    base_pixels = np.random.rand(32, 32).astype(np.float32) * 255
    cam = np.random.rand(7, 7).astype(np.float32)
    overlay = build_heatmap_overlay(base_pixels, cam)
    assert isinstance(overlay, Image.Image)
    assert overlay.size == (32, 32)
    assert overlay.mode == "RGB"
