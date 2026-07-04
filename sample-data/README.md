# Sample Data

This folder is only for public or demo DICOM data used to exercise the platform locally.

Rules:

- Only public/demo DICOM data is allowed here.
- No real patient data, ever.
- No clinical use of this data or this platform.

## Current sample

One test file is used to check that Orthanc receives images correctly: `CT_small.dcm` from the [pydicom](https://github.com/pydicom/pydicom) project, MIT licensed, already anonymized, and published as public test data.

It is not committed to this repo — it's downloaded on the fly by `scripts/upload-sample-dicom.sh` into `sample-data/downloads/` (git-ignored). See `docs/sample-data.md` for details.
