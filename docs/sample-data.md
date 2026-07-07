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

## Fourth and fifth samples: chest X-rays for the real AI model

Step 24 replaced the ai-inference service's placeholder classifier with a real pre-trained model ([TorchXRayVision](https://github.com/mlmed/torchxrayvision)), which is trained specifically on chest X-rays rather than the CT/MRI images used everywhere else in this project. Two individual PNG images from the NIH ChestX-ray14 dataset are used to test it:

```text
00000001_000.png  - NIH ground-truth label: Cardiomegaly (abnormal)
00027426_000.png  - NIH ground-truth label: No Finding (normal)
```

- Source: both files are mirrored in the TorchXRayVision project's own GitHub repository, at `https://github.com/mlmed/torchxrayvision/raw/master/tests/`, where the library's own maintainers use them as test fixtures for exactly this kind of inference.
- Original dataset: [NIH ChestX-ray14](https://nihcc.app.box.com/v/ChestXray-NIHCC), released by the NIH Clinical Center - 112,120 chest X-ray images from 30,805 patients, each labeled for 14 possible thoracic findings (or "No Finding").
- License: public domain, a work of the U.S. federal government - there is no restriction on how the images may be used. The NIH's own release asks that anyone using the data link back to their download page and credit the NIH Clinical Center as the source, which this file does.
- The ground-truth labels above come from the dataset's own `Data_Entry_2017.csv` metadata file (Image Index `00000001_000.png` -> `Cardiomegaly`; `00027426_000.png` -> `No Finding`), not from this project's model - they're what the NIH radiologist-derived labels say each image actually shows, independent of whatever the model predicts for it.
- Both are small individual PNG files (~180 KB each), not the full 112,120-image, 42 GB dataset - only these two files are downloaded, and only on demand.

Downloaded with:

```bash
./scripts/download-xray-samples.sh
```

This saves both files to `sample-data/downloads/xray/` (git-ignored). See `docs/local-stack.md` for how the ai-inference service uses them.

## Sixth source: a balanced 24-image evaluation set

Step 26 needed enough labeled images to evaluate the model properly, not just look at one or two results by eye - 24 chest X-rays, 12 labeled "No Finding" and 12 each with one single, distinct abnormal finding (Infiltration, Effusion, Atelectasis, Nodule, Pneumothorax, Mass, Consolidation, Pleural_Thickening, Cardiomegaly, Emphysema, Edema, Pneumonia). The two samples above aren't enough for that on their own.

- Source: [Kaggle's "Random Sample of NIH Chest X-ray Dataset"](https://www.kaggle.com/datasets/nih-chest-xrays/sample) (`nih-chest-xrays/sample`) - NIH's own official 5% sample release of the full ChestX-ray14 dataset (5,606 images), re-hosted on Kaggle with its own `sample_labels.csv` ground-truth file.
- License: CC0: Public Domain, shown directly on the dataset page.
- Each of the 24 images was picked by matching against `sample_labels.csv`: the 12 abnormal picks are each the only sample carrying that single finding label (no other finding mixed in, so the expected answer is unambiguous) from a patient not already used elsewhere in the set; the 12 normal picks are "No Finding" images spread across the label file so no two come from the same patient. See `evaluation/manifest.csv` for the exact 24 filenames, expected labels, and the reason each one was picked.
- Downloading requires a (free) Kaggle account and API token, unlike every other sample above - Kaggle's own API requires authentication even for public datasets. See `scripts/download-xray-evaluation-set.sh`.

Downloaded with:

```bash
./scripts/download-xray-evaluation-set.sh
```

This saves the 24 images plus a copy of the labels reference file to `sample-data/downloads/xray-eval/` (git-ignored). See `docs/ai-evaluation-notes.md` for how they're used.
