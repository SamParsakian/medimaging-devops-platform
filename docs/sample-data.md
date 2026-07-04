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
