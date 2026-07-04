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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
