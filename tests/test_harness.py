from pathlib import Path

import okf_common


def test_okf_common_importable():
    assert okf_common.concept_id_for_path(Path("a/b.md")) == "a/b"
