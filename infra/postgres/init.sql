-- Schema for imaging metadata.
-- Orthanc stores the actual DICOM data; this table holds a normalized
-- copy of the useful metadata so it can be queried without hitting
-- Orthanc's API every time.

CREATE TABLE IF NOT EXISTS studies (
    id SERIAL PRIMARY KEY,
    orthanc_study_id TEXT NOT NULL UNIQUE,
    study_instance_uid TEXT NOT NULL,
    series_instance_uid TEXT,
    patient_id TEXT,
    patient_name TEXT,
    modality TEXT,
    study_date DATE,
    study_description TEXT,
    series_count INTEGER NOT NULL DEFAULT 0,
    instance_count INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL DEFAULT 'pending',
    preview_object_path TEXT,
    anonymization_status TEXT NOT NULL DEFAULT 'pending',
    preview_status TEXT NOT NULL DEFAULT 'pending',
    upload_status TEXT NOT NULL DEFAULT 'pending',
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Basic audit trail for the API: who looked at what, and when.
-- Demo-grade only - one fixed "demo-user", no real auth yet.

CREATE TABLE IF NOT EXISTS audit_events (
    event_id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'demo-user',
    action TEXT NOT NULL,
    study_id TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_address TEXT,
    status TEXT NOT NULL DEFAULT 'success'
);

-- One row per slice preview, for studies with more than one image
-- (a real multi-slice CT/MRI series). Most studies only ever need the
-- single whole-study preview already on `studies.preview_object_path`;
-- this table is only populated for series with several slices to page
-- through (see services/metadata-extractor/register_slice_previews.py).

CREATE TABLE IF NOT EXISTS study_slices (
    id SERIAL PRIMARY KEY,
    orthanc_study_id TEXT NOT NULL,
    slice_index INTEGER NOT NULL,
    instance_number INTEGER,
    preview_object_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (orthanc_study_id, slice_index)
);
