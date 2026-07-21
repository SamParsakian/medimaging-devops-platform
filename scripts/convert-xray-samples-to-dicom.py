#!/usr/bin/env python3
"""
Wraps the existing NIH ChestX-ray14 PNG samples (sample-data/downloads/
xray-eval/, see docs/sample-data.md) into real DICOM files, so they can
go through the same Orthanc -> metadata-extractor -> anonymizer ->
preview-generator -> MinIO pipeline every other DICOM sample in this
project uses. The NIH dataset's own public release only ever shipped
PNG, not DICOM - the pixel data here is the real, unmodified chest
X-ray, just packaged in a standard DICOM container with plausible
placeholder tags (Modality CR, fake patient/study identifiers) instead
of a scanner ever having produced it directly.

Does not touch sample-data/downloads/xray-eval/ - only reads from it.
Output goes to sample-data/downloads/xray-dicom/ (git-ignored, created
if missing).
"""

import os
import uuid

import numpy as np
import pydicom
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage

ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
SRC_DIR = os.path.join(ROOT_DIR, "sample-data", "downloads", "xray-eval")
DEST_DIR = os.path.join(ROOT_DIR, "sample-data", "downloads", "xray-dicom")


def build_dicom(png_path, study_uid, patient_id, patient_name):
    image = Image.open(png_path).convert("L")
    pixel_array = np.array(image)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(png_path, {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = ""
    ds.PatientSex = ""

    ds.Modality = "CR"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = pydicom.uid.generate_uid()
    ds.StudyDate = "20260101"
    ds.StudyTime = "000000"
    ds.StudyDescription = "Chest X-ray (demo DICOM wrapper, see docs/sample-data.md)"
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1

    ds.Rows, ds.Columns = pixel_array.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = pixel_array.tobytes()

    ds.is_little_endian = True
    ds.is_implicit_VR = False

    return ds


def main():
    os.makedirs(DEST_DIR, exist_ok=True)

    png_files = sorted(f for f in os.listdir(SRC_DIR) if f.endswith(".png"))
    if not png_files:
        print(f"No PNG files found in {SRC_DIR}")
        return

    for filename in png_files:
        png_path = os.path.join(SRC_DIR, filename)
        stem = os.path.splitext(filename)[0]

        # Each source PNG becomes its own one-instance DICOM study - these
        # are 24 unrelated patients in the real NIH data, not slices of
        # one series, so they must not share a StudyInstanceUID.
        study_uid = pydicom.uid.generate_uid()
        patient_id = f"demo-{stem}"
        patient_name = f"Anonymous^{stem}"

        ds = build_dicom(png_path, study_uid, patient_id, patient_name)

        out_path = os.path.join(DEST_DIR, f"{stem}.dcm")
        ds.save_as(out_path, enforce_file_format=True)
        print(f"{filename} -> {out_path}")

    print(f"\nConverted {len(png_files)} PNG samples to DICOM in {DEST_DIR}")


if __name__ == "__main__":
    main()
