import json
from pathlib import Path
import shutil

from publish_model import build_model
from publish_search import search_records, search_text, write_search

SEARCH_JS = Path(__file__).resolve().parents[1] / "scripts" / "publish_assets" / "search.js"


def test_records_public_only(fixture_bundle):
    model, _findings = build_model(fixture_bundle)
    records = search_records(model)
    assert [record["id"] for record in records] == model.public_ids()
    assert all("ZZ-PRIVATE" not in json.dumps(record) for record in records)
    rule = next(record for record in records if record["id"] == "rules/no-spoilers")
    assert rule["url"] == "rules/no-spoilers.html"
    assert rule["title"] == "No spoilers"
    assert "incident" in rule["text"]
    assert "/ops/incident-42.md" not in rule["text"]
    assert "[^s1]" not in rule["text"]
    assert sorted(rule) == ["description", "id", "text", "title", "type", "url"]


def test_search_text():
    body = "Intro ![a diagram](d.png) and [a link](x.md#y).[^n]\n\n```python\nprint(1)\n```\n\n[^n]: Note."
    assert search_text(body) == "Intro a diagram and a link. print(1) Note."


def test_search_html_shell(fixture_bundle, tmp_path):
    model, _findings = build_model(fixture_bundle)
    write_search(model, tmp_path, "Stream Rules Knowledge")
    page = (tmp_path / "search.html").read_text(encoding="utf-8")
    assert page.count("<script") == 1
    assert '<script src="assets/search.js"></script>' in page
    assert '<ol id="okf-results"></ol>' in page
    assert (tmp_path / "assets" / "search.js").read_bytes() == SEARCH_JS.read_bytes()


def test_search_js_is_safe():
    script = SEARCH_JS.read_text(encoding="utf-8")
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "http://", "https://"):
        assert forbidden not in script
    assert "textContent" in script
    assert 'fetch("search-index.json")' in script


def test_json_is_deterministic(fixture_bundle, tmp_path):
    model, _findings = build_model(fixture_bundle)
    write_search(model, tmp_path / "a", "T")
    write_search(model, tmp_path / "b", "T")
    first = (tmp_path / "a" / "search-index.json").read_bytes()
    assert first == (tmp_path / "b" / "search-index.json").read_bytes()
    assert json.loads(first)[0]["id"] == "rules/no-spoilers"


def test_record_urls_are_quoted(fixture_bundle, tmp_path):
    bundle = tmp_path / "bundle"
    shutil.copytree(fixture_bundle, bundle)
    (bundle / "rules" / "c#.md").write_text("---\ntitle: Sharp\n---\n\nBody.\n", encoding="utf-8")
    (bundle / "javascript:x.md").write_text("---\ntitle: Colon\n---\n\nBody.\n", encoding="utf-8")
    model, findings = build_model(bundle)
    assert findings == []
    urls = {record["id"]: record["url"] for record in search_records(model)}
    assert urls["rules/c#"] == "rules/c%23.html"
    assert urls["javascript:x"] == "javascript%3Ax.html"
