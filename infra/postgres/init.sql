-- Initial schema for imaging metadata.
-- Orthanc stores the actual DICOM data; this table just tracks
-- a minimal reference back to it for querying/reporting later.

CREATE TABLE IF NOT EXISTS studies (
    id SERIAL PRIMARY KEY,
    orthanc_study_id TEXT NOT NULL UNIQUE,
    patient_id TEXT,
    study_date DATE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
