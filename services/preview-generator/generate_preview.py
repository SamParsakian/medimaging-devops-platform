"""
Generates a viewable PNG preview from a DICOM file's pixel data. Reads
the anonymized DICOM from Step 4, applies simple windowing so the CT
image isn't just black or blown out, and writes a PNG to a local,
git-ignored output folder. Run manually, one file at a time.
"""

import sys
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT_DIR / "services/anonymizer/output/anonymized_CT_small.dcm"
OUTPUT_DIR = ROOT_DIR / "services/preview-generator/output"


def build_output_name(input_path):
    name = input_path.stem
    if name.startswith("anonymized_"):
        name = name[len("anonymized_"):]
    return f"preview_{name}.png"


def to_8bit_pixels(dataset):
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


def generate_preview(input_path, output_path):
    dataset = pydicom.dcmread(input_path)
    pixels = to_8bit_pixels(dataset)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels).save(output_path)

    print(f"Saved preview PNG to {output_path}")


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT

    if not input_path.exists():
        print(f"No anonymized file found at {input_path}")
        print("Run services/anonymizer/anonymize.py first.")
        sys.exit(1)

    output_path = OUTPUT_DIR / build_output_name(input_path)
    generate_preview(input_path, output_path)


if __name__ == "__main__":
    main()
