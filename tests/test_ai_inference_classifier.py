import numpy as np

from main import classify_pixels


def test_classify_pixels_labels_a_uniform_image_as_low_variation():
    pixels = np.full((32, 32), 120, dtype=np.uint8)
    label, confidence = classify_pixels(pixels)
    assert label == "low_variation_region"
    assert 0.5 <= confidence <= 0.99


def test_classify_pixels_labels_a_checkerboard_as_high_variation():
    pixels = np.zeros((32, 32), dtype=np.uint8)
    pixels[::2, ::2] = 255
    pixels[1::2, 1::2] = 255
    label, confidence = classify_pixels(pixels)
    assert label == "high_variation_region"
    assert 0.5 <= confidence <= 0.99


def test_classify_pixels_labels_a_mixed_image_as_moderate_variation():
    pixels = np.full((32, 32), 50, dtype=np.uint8)
    pixels[::2, ::2] = 150
    pixels[1::2, 1::2] = 150
    label, confidence = classify_pixels(pixels)
    assert label == "moderate_variation_region"
