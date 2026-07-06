from rules import ANONYMIZATION_RULES

EXPECTED_FIELDS = {
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "AccessionNumber",
    "InstitutionName",
    "ReferringPhysicianName",
}


def test_anonymization_rules_cover_the_expected_fields():
    assert EXPECTED_FIELDS.issubset(ANONYMIZATION_RULES.keys())


def test_anonymization_rules_replace_patient_id_with_a_demo_value():
    assert ANONYMIZATION_RULES["PatientID"] == "ANON0001"
    assert ANONYMIZATION_RULES["PatientName"] != ""
