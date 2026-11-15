from pathlib import Path
import re
import shutil

import pytest

from publish_model import build_model
from publish_render import filter_index_markdown, kept_index_lines, relative_href, render_site, site_title


@pytest.fixture
def bundle_copy(fixture_bundle, tmp_path) -> Path:
    target = tmp_path / "bundle"
    shutil.copytree(fixture_bundle, target)
    return target


def filtered_texts(model):
    return {d: filter_index_markdown(t, d, model) for d, t in model.index_files.items() if d in model.public_dirs()}


def render(bundle: Path, out: Path) -> list[str]:
    model, findings = build_model(bundle)
    assert findings == []
    return render_site(model, filtered_texts(model), out)


def test_relative_href():
    assert relative_href("rules/no-spoilers.html", "schema.html") == "../schema.html"
    assert relative_href("index.html", "rules/a.html") == "rules/a.html"
    assert relative_href("rules/a.html", "rules/b.html") == "b.html"
    assert relative_href("a/b/c.html", "a/x/y.html") == "../x/y.html"
    assert relative_href("a/b/c.html", "index.html") == "../../index.html"
    assert relative_href("index.html", "my notes/a b.html") == "my%20notes/a%20b.html"


def test_filter_index_drops_private_lines(fixture_bundle):
    model, _findings = build_model(fixture_bundle)
    texts = filtered_texts(model)
    assert sorted(texts) == ["", "rules"]
    assert "[ops/]" not in texts[""]
    assert "* [rules/](rules/) - Subdirectory" in texts[""]
    assert "See [the incident](/ops/incident-42.md)." in texts[""]
    assert "ZZ-PRIVATE-MOD-NOTES" not in texts["rules"]
    assert "* [No spoilers](no-spoilers.md) - Do not reveal plot points." in texts["rules"]
    kept = [number for number, _line in kept_index_lines(model.index_files[""], "", model)]
    assert 6 not in kept and 7 in kept


def test_concept_page_contents(fixture_bundle, tmp_path):
    render(fixture_bundle, tmp_path)
    page = (tmp_path / "rules" / "no-spoilers.html").read_text(encoding="utf-8")
    assert "<code>rules/no-spoilers</code>" in page
    assert "human-reviewed" in page
    assert 'class="badge status status-stable">stable<' in page
    assert '<a href="https://example.com/vod/1">Chat proposal</a> — viewer-anna' in page
    assert '<section class="backlinks"><h2>Linked from</h2><ul><li><a href="old-spoiler-rule.html">Old spoiler rule</a></li>' in page
    assert '<a class="home" href="../index.html">Stream Rules Knowledge</a>' in page
    assert '<link rel="stylesheet" href="../assets/style.css">' in page
    assert "<li>Background: the incident that prompted the rule.</li>" in page
    assert "<li>Next: a future rule on hints.</li>" in page
    assert re.search(r"<a [^>]*>incident</a>", page) is None
    assert re.search(r"<a [^>]*>future rule</a>", page) is None
    assert "incident" in page and "future rule" in page
    assert '<a href="old-spoiler-rule.html">old rule</a>' in page
    assert '<a href="index.html">rules home</a>' in page
    assert "ops/incident-42" not in page
    assert "<script" not in page


def test_written_pages(fixture_bundle, tmp_path):
    assert render(fixture_bundle, tmp_path) == [
        "assets/style.css",
        "index.html",
        "rules/index.html",
        "rules/no-spoilers.html",
        "rules/old-spoiler-rule.html",
        "schema.html",
    ]
    root = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "OKF:INDEX" not in root
    assert '<a href="rules/index.html">rules/</a>' in root
    assert '<a href="schema.html">Schema</a>' in root
    assert "ops" not in root.replace("Stream Rules", "")
    rules_index = (tmp_path / "rules" / "index.html").read_text(encoding="utf-8")
    assert "<title>Rules · Stream Rules Knowledge</title>" in rules_index
    assert "ZZ-PRIVATE" not in rules_index


def test_generated_listing_without_index_md(bundle_copy, tmp_path):
    (bundle_copy / "rules" / "index.md").unlink()
    (bundle_copy / "index.md").unlink()
    out = tmp_path / "out"
    written = render(bundle_copy, out)
    assert "rules/index.html" in written
    rules_index = (out / "rules" / "index.html").read_text(encoding="utf-8")
    assert '<a href="no-spoilers.html">No spoilers</a> - Do not reveal plot points.' in rules_index
    assert '<a href="old-spoiler-rule.html">Old spoiler rule</a>' in rules_index
    assert "ZZ-PRIVATE-MOD-NOTES" not in rules_index
    root = (out / "index.html").read_text(encoding="utf-8")
    assert '<a href="rules/index.html">rules/</a>' in root
    assert '<a href="schema.html">Schema</a>' in root
    assert "ops" not in root


def test_site_title_default():
    assert site_title({}) == "Knowledge"
    assert site_title({"": "intro\n# My Bundle \n"}) == "My Bundle"
