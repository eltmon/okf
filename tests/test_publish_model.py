from pathlib import Path
import shutil

import pytest

from publish_model import LinkTarget, build_model, classify_link, trust_tier, walk_markdown


@pytest.fixture
def bundle_copy(fixture_bundle, tmp_path) -> Path:
    target = tmp_path / "bundle"
    shutil.copytree(fixture_bundle, target)
    return target


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_fixture_public_and_private(fixture_bundle):
    model, findings = build_model(fixture_bundle)
    assert findings == []
    assert model.public_ids() == ["rules/no-spoilers", "rules/old-spoiler-rule", "schema"]
    assert model.concepts["ops/incident-42"].visibility == "private"
    assert model.concepts["rules/mod-notes"].visibility == "private"
    assert model.default_visibility == "public"
    assert all(not concept_id.startswith(".github") for concept_id in model.concepts)
    walked = [path.relative_to(fixture_bundle.resolve()).as_posix() for path in walk_markdown(fixture_bundle)]
    assert ".github/notes.md" not in walked
    assert "log.md" in walked
    assert "log" not in model.concepts
    assert sorted(model.index_files) == ["", "ops", "rules"]


def test_walk_skips_excluded_out_dir(bundle_copy):
    out = bundle_copy / "site"
    (out / "nested").mkdir(parents=True)
    (out / "nested" / "page.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (bundle_copy / "node_modules").mkdir()
    (bundle_copy / "node_modules" / "pkg.md").write_text("no frontmatter\n", encoding="utf-8")
    model, findings = build_model(bundle_copy, exclude=out)
    assert findings == []
    assert "site/nested/page" not in model.concepts


def test_default_private_without_schema(bundle_copy):
    (bundle_copy / "schema.md").unlink()
    model, findings = build_model(bundle_copy)
    assert findings == []
    assert model.public_ids() == []
    assert model.default_reason == "no schema.md at bundle root"


def test_default_private_without_key(bundle_copy):
    edit(bundle_copy / "schema.md", "x_visibility_default: public\n", "")
    model, findings = build_model(bundle_copy)
    assert findings == []
    assert model.public_ids() == ["schema"]
    assert model.default_reason == "schema.md has no x_visibility_default"


def test_invalid_default_value(bundle_copy):
    edit(bundle_copy / "schema.md", "x_visibility_default: public", "x_visibility_default: yes")
    model, findings = build_model(bundle_copy)
    assert [(f.code, f.location) for f in findings] == [("P_VISIBILITY_INVALID", "schema.md")]
    assert model.default_visibility == "private"


def test_invalid_visibility(bundle_copy):
    edit(bundle_copy / "rules" / "no-spoilers.md", "status: stable\n", "status: stable\nx_visibility: Public\n")
    model, findings = build_model(bundle_copy)
    assert len(findings) == 1
    assert findings[0].code == "P_VISIBILITY_INVALID"
    assert findings[0].line() == "ERROR P_VISIBILITY_INVALID rules/no-spoilers.md: x_visibility must be public or private"
    assert not model.is_public("rules/no-spoilers")


def test_parse_error_finding(bundle_copy):
    (bundle_copy / "notes").mkdir()
    (bundle_copy / "notes" / "bad.md").write_text("no frontmatter here\n", encoding="utf-8")
    model, findings = build_model(bundle_copy)
    assert [(f.code, f.location) for f in findings] == [("P_FRONTMATTER_PARSE", "notes/bad.md")]
    assert "notes/bad" not in model.concepts


def test_trust_tier():
    assert trust_tier({"verified": [{"by": "process:ci"}, {"by": "human:host"}]}) == "human-reviewed"
    assert trust_tier({"verified": {"by": "process:ci", "at": "x"}}) == "machine-confirmed"
    assert trust_tier({}) == "unverified"
    assert trust_tier({"verified": None}) == "unverified"
    assert trust_tier({"verified": ["human:host"]}) == "unverified"


def test_classify_link():
    # Rules 1-2: fragment split and fragment-only links.
    assert classify_link("rules", "#part") == LinkTarget("fragment", "#part", "part")
    # Rule 3: external schemes stay unchanged.
    assert classify_link("rules", "HTTPS://example.com/a#b") == LinkTarget("external", "HTTPS://example.com/a#b", "b")
    assert classify_link("", "mailto:a@example.com").kind == "external"
    # Rule 4: any other scheme.
    assert classify_link("rules", "javascript:x").kind == "other"
    assert classify_link("rules", "repo:a.md@abc").kind == "other"
    # Rule 5: root-relative, source-relative and climbing above the root.
    assert classify_link("rules", "/ops/incident-42.md#a") == LinkTarget("concept", "ops/incident-42", "a")
    assert classify_link("rules", "../schema.md") == LinkTarget("concept", "schema", "")
    assert classify_link("rules", "../../x.md").kind == "other"
    # Rule 6: directory links.
    assert classify_link("rules", "/rules/") == LinkTarget("directory", "rules", "")
    assert classify_link("", "ops/") == LinkTarget("directory", "ops", "")
    assert classify_link("rules", "../") == LinkTarget("directory", "", "")
    # Rule 7: index.md.
    assert classify_link("rules", "index.md") == LinkTarget("directory", "rules", "")
    assert classify_link("rules", "/index.md") == LinkTarget("directory", "", "")
    # Rule 8: log.md.
    assert classify_link("", "log.md").kind == "other"
    # Rule 9: concepts.
    assert classify_link("rules", "old-spoiler-rule.md") == LinkTarget("concept", "rules/old-spoiler-rule", "")
    # Rule 10: anything else.
    assert classify_link("rules", "diagram.png").kind == "other"


def test_backlinks_public_only(bundle_copy):
    (bundle_copy / "rules" / "secret.md").write_text(
        "---\ntitle: Secret\nx_visibility: private\n---\n\nSee [No spoilers](no-spoilers.md).\n", encoding="utf-8"
    )
    model, findings = build_model(bundle_copy)
    assert findings == []
    assert model.backlinks("rules/no-spoilers") == ["rules/old-spoiler-rule"]
    assert model.backlinks("rules/old-spoiler-rule") == ["rules/no-spoilers"]


def test_public_dirs(fixture_bundle):
    model, _findings = build_model(fixture_bundle)
    assert model.public_dirs() == {"", "rules"}


def test_body_start_line(fixture_bundle):
    model, _findings = build_model(fixture_bundle)
    concept = model.concepts["rules/no-spoilers"]
    lines = (fixture_bundle / "rules" / "no-spoilers.md").read_text(encoding="utf-8").split("\n")
    assert lines[concept.body_start_line - 1] == concept.body.split("\n")[0]
    assert lines[concept.body_start_line - 1] == "Proposed in chat.[^s1]"
    assert lines[concept.body_start_line - 2] == ""


def test_concept_fields(fixture_bundle):
    model, _findings = build_model(fixture_bundle)
    concept = model.concepts["rules/no-spoilers"]
    assert concept.tags == ("chat", "rules")
    assert concept.status == "stable"
    assert concept.trust_tier == "human-reviewed"
    assert [(s.title, s.resource, s.author) for s in concept.sources] == [
        ("Chat proposal", "https://example.com/vod/1", "viewer-anna")
    ]
    assert model.concepts["rules/old-spoiler-rule"].trust_tier == "machine-confirmed"
    assert model.concepts["schema"].status == "stable"
