from pathlib import Path

from generate_preview import build_output_name


def test_build_output_name_strips_the_anonymized_prefix():
    assert build_output_name(Path("anonymized_CT_small.dcm")) == "preview_CT_small.png"


def test_build_output_name_without_a_prefix():
    assert build_output_name(Path("CT_small.dcm")) == "preview_CT_small.png"
