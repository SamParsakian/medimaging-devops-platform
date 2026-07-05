# Sample Data

This folder is only for public or demo DICOM data used to exercise the platform locally.

Rules:

- Only public/demo DICOM data is allowed here.
- No real patient data, ever.
- No clinical use of this data or this platform.

## Current samples

- `CT_small.dcm` - used to check that Orthanc receives images correctly. From the [pydicom](https://github.com/pydicom/pydicom) project, MIT licensed, already anonymized, and published as public test data. Downloaded on the fly by `scripts/upload-sample-dicom.sh`.
- `examples_overlay.dcm` - a larger, clearer sample (real Siemens abdominal MR slice, originally from the GDCM project, BSD-style license) used to feed the anonymizer/preview-generator/MinIO-uploader pipeline. Downloaded on the fly by `scripts/download-better-dicom-sample.sh`.

Neither file is committed to this repo - both land in `sample-data/downloads/` (git-ignored). See `docs/sample-data.md` for details.
