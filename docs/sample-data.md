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
