"""
Demo-grade anonymization rules.

This is NOT guaranteed clinical-grade de-identification (like DICOM
Supplement 142 / PS3.15). It just replaces a handful of the most
obviously identifying tags with fixed demo values, for a portfolio
project that never touches real patient data anyway.
"""

ANONYMIZATION_RULES = {
    "PatientName": "Anonymous^Demo",
    "PatientID": "ANON0001",
    "PatientBirthDate": "",
    "AccessionNumber": "",
    "InstitutionName": "Demo Institution",
    "ReferringPhysicianName": "",
}

# StudyInstanceUID is intentionally left unchanged. A real de-identification
# pipeline would usually regenerate it (and SeriesInstanceUID/SOPInstanceUID)
# to fully break the link back to the source data. Here it's kept on purpose,
# so the anonymized file can still be compared against the original study
# already stored in Orthanc for this demo.
KEEP_STUDY_INSTANCE_UID = True
