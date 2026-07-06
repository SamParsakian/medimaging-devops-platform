# Sample Data

To check that Orthanc actually receives and stores images, one small public/demo DICOM file is used: `CT_small.dcm` from the [pydicom](https://github.com/pydicom/pydicom) project's test files.

- Source: https://github.com/pydicom/pydicom/raw/main/src/pydicom/data/test_files/CT_small.dcm
- License: pydicom is MIT licensed, and this file ships as part of its public test suite specifically for testing DICOM tools like this one.
- It is a small, already-anonymized test file - not real patient data.

The file itself is not stored in this repo. It's downloaded on demand by `scripts/upload-sample-dicom.sh`, which also uploads it straight to the local Orthanc instance through its REST API.

## Running it

Make sure the stack is running (`docker compose up -d`), then:

```bash
./scripts/upload-sample-dicom.sh
```

This downloads the file into `sample-data/downloads/` (git-ignored) and POSTs it to `http://localhost:8042/instances`.

## Second sample: examples_overlay.dcm

`CT_small.dcm` is only 128x128, which made for a very small, blurry PNG preview in Step 6. For Step 6B, a second, larger sample is used to feed the anonymizer/preview-generator/MinIO-uploader pipeline instead: `examples_overlay.dcm`, also from pydicom's test files.

- Source: https://github.com/pydicom/pydicom/raw/main/src/pydicom/data/test_files/examples_overlay.dcm
- Original dataset: a cropped copy of `MR-SIEMENS-DICOM-WithOverlays.dcm`, from the [GDCM](https://github.com/malaterre/GDCM) project (BSD-style license, reproduced in pydicom's `test_files/README.txt`).
- It's a real Siemens abdominal MR slice, 300x484, which makes for a much clearer preview than `CT_small.dcm`'s 128x128.
- Small file (~315 KB) - not committed to this repo, downloaded on demand.
- pydicom's own README notes patient-name-looking fields were already scrubbed in these test files, but the raw file still has a real hospital name in `InstitutionName` (`AKH - WIEN`). This project's own anonymizer (Step 4) replaces that field anyway, so it never reaches the anonymized output or the generated preview.

Downloaded with:

```bash
./scripts/download-better-dicom-sample.sh
```

This saves it to `sample-data/downloads/examples_overlay.dcm` (git-ignored). It does not touch Orthanc - it's only used as input to the anonymizer/preview-generator/MinIO-uploader pipeline described in `docs/local-stack.md`.

## Third sample: a real multi-slice MRI series

Both samples above are a single DICOM instance each - one slice, no series to page through. For Step 18, a genuine multi-slice series is used instead: 15 slices from a real structural T1-weighted brain MRI scan.

- Source: [datalad/example-dicom-structural](https://github.com/datalad/example-dicom-structural), a public demo DICOM dataset maintained by the [DataLad](https://www.datalad.org/) project.
- License: [Open Data Commons Public Domain Dedication and Licence (PDDL)](https://github.com/datalad/example-dicom-structural/blob/master/LICENSE) - explicitly public domain, no attribution required, commercial use allowed.
- Original scan: a 7-Tesla structural MRI from the [studyforrest](http://studyforrest.org/) project, published in Hanke et al., *A high-resolution 7-Tesla fMRI dataset from complex natural stimulation with an audio movie*, Scientific Data 1:140003 (2014).
- The repo's own README explains how it was prepared: the original NIfTI image was de-faced (the face/skin surface removed, a standard research privacy technique that leaves the brain itself untouched) before being converted to DICOM, and every identifying DICOM tag was then replaced with fake values (`PatientName` set to `Jane_Doe`, etc.) using `gdcmanon`. This project's own anonymizer (Step 4) still runs over it anyway, on the same "anonymize every file regardless" habit as the other two samples.
- The full series has 384 slices (~80 MB total). Only 15 are used here, evenly spaced through the part of the volume that actually shows brain anatomy - the very first and last slices in the series are below the neck or above the top of the skull, and mostly blank.

Downloaded with:

```bash
./scripts/download-multislice-mri-sample.sh
```

This saves the 15 selected slices to `sample-data/downloads/multislice-mri/` (git-ignored, ~3 MB total). Unlike the other two samples, this one is uploaded to Orthanc as a real multi-instance series:

```bash
./scripts/upload-multislice-series-to-orthanc.sh
```

Since every slice shares the same `StudyInstanceUID` and `SeriesInstanceUID`, Orthanc groups all 15 into one study with one series automatically. See `docs/local-stack.md` for how the rest of the pipeline (anonymize, preview, upload to MinIO, and slice navigation in the dashboard) handles this series.
