from pathlib import Path

from register_slice_previews import build_preview_name


def test_build_preview_name_strips_the_anonymized_prefix():
    assert build_preview_name(Path("anonymized_N2D_0105.dcm")) == "preview_N2D_0105.png"
