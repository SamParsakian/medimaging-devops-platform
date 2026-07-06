import pytest
from pydantic import ValidationError

from main import InferRequest


def test_infer_request_accepts_a_normal_object_path():
    request = InferRequest(object_path="processed/previews/study/preview.png")
    assert request.object_path == "processed/previews/study/preview.png"


def test_infer_request_rejects_an_empty_object_path():
    with pytest.raises(ValidationError):
        InferRequest(object_path="")


def test_infer_request_rejects_a_missing_object_path():
    with pytest.raises(ValidationError):
        InferRequest()
