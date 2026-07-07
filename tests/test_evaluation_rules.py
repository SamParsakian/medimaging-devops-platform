from run_evaluation import confidence_bucket, judge


def make_result(top_findings, finding_probabilities):
    return {"top_findings": top_findings, "finding_probabilities": finding_probabilities}


def test_judge_abnormal_matches_when_expected_label_clears_threshold():
    row = {"expected_group": "abnormal", "expected_label": "Cardiomegaly"}
    result = make_result(
        top_findings=[{"label": "Cardiomegaly", "probability": 0.62}],
        finding_probabilities={"Cardiomegaly": 0.62},
    )
    status, _ = judge(row, result, threshold=0.5)
    assert status == "match"


def test_judge_abnormal_matches_via_top_k_even_below_threshold():
    row = {"expected_group": "abnormal", "expected_label": "Nodule"}
    result = make_result(
        top_findings=[{"label": "Fibrosis", "probability": 0.5}, {"label": "Nodule", "probability": 0.33}],
        finding_probabilities={"Fibrosis": 0.5, "Nodule": 0.33},
    )
    status, _ = judge(row, result, threshold=0.5)
    assert status == "match"


def test_judge_abnormal_mismatch_when_expected_label_is_clearly_low():
    row = {"expected_group": "abnormal", "expected_label": "Pneumonia"}
    result = make_result(
        top_findings=[{"label": "Fracture", "probability": 0.51}],
        finding_probabilities={"Fracture": 0.51, "Pneumonia": 0.0022},
    )
    status, _ = judge(row, result, threshold=0.5)
    assert status == "mismatch"


def test_judge_normal_matches_when_nothing_clears_threshold():
    row = {"expected_group": "normal", "expected_label": "No Finding"}
    result = make_result(
        top_findings=[{"label": "Fibrosis", "probability": 0.3}],
        finding_probabilities={"Fibrosis": 0.3, "Nodule": 0.1},
    )
    status, _ = judge(row, result, threshold=0.5)
    assert status == "match"


def test_judge_normal_mismatch_when_a_finding_clearly_clears_threshold():
    row = {"expected_group": "normal", "expected_label": "No Finding"}
    result = make_result(
        top_findings=[{"label": "Lung Opacity", "probability": 0.8}],
        finding_probabilities={"Lung Opacity": 0.8},
    )
    status, _ = judge(row, result, threshold=0.5)
    assert status == "mismatch"


def test_judge_normal_review_needed_when_borderline():
    row = {"expected_group": "normal", "expected_label": "No Finding"}
    result = make_result(
        top_findings=[{"label": "Infiltration", "probability": 0.51}],
        finding_probabilities={"Infiltration": 0.51},
    )
    status, _ = judge(row, result, threshold=0.5)
    assert status == "review_needed"


def test_confidence_bucket_boundaries():
    assert confidence_bucket(0.3) == "low"
    assert confidence_bucket(0.5) == "uncertain"
    assert confidence_bucket(0.69) == "uncertain"
    assert confidence_bucket(0.7) == "stronger_signal"
    assert confidence_bucket(None) is None
