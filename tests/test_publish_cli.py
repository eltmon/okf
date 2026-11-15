from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import unquote

import pytest

from publish_redact import load_profile, scan

EXPECTED_PAGES = {
    "index.html",
    "rules/index.html",
    "rules/no-spoilers.html",
    "rules/old-spoiler-rule.html",
    "schema.html",
    "search.html",
}


@pytest.fixture
def bundle_copy(fixture_bundle, tmp_path) -> Path:
    target = tmp_path / "bundle"
    shutil.copytree(fixture_bundle, target)
    return target


def run_publish(scripts_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(scripts_dir / "publish.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def files_under(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src", "action") and value is not None:
                self.targets.append(value)


def test_publish_fixture_pages(scripts_dir, bundle_copy, tmp_path):
    out = tmp_path / "site"
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("ok - published 3 public concept(s) to ")
    assert "(2 private excluded, 0 redaction(s) applied)" in result.stdout
    assert {path for path in files_under(out) if path.endswith(".html")} == EXPECTED_PAGES
    assert set(files_under(out)) == EXPECTED_PAGES | {
        ".okf-publish",
        "assets/search.js",
        "assets/style.css",
        "search-index.json",
    }
    for absent in ("ops/incident-42.html", "rules/mod-notes.html", "ops/index.html", "log.html"):
        assert not (out / absent).exists()


def test_no_unresolved_links(scripts_dir, bundle_copy, tmp_path):
    out = tmp_path / "site"
    assert run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out)).returncode == 0
    checked = 0
    for page in out.rglob("*.html"):
        collector = LinkCollector()
        collector.feed(page.read_text(encoding="utf-8"))
        for target in collector.targets:
            if target.lower().startswith(("http:", "https:", "mailto:", "#")):
                continue
            assert not target.startswith("/"), (page, target)
            path = unquote(target.split("#", 1)[0].split("?", 1)[0])
            resolved = (page.parent / path).resolve()
            assert resolved.is_file(), (page.relative_to(out).as_posix(), target)
            assert out.resolve() in resolved.parents
            checked += 1
    assert checked > 20


def test_no_private_or_secret_bytes(scripts_dir, bundle_copy, tmp_path, fixture_bundle):
    out = tmp_path / "site"
    assert run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out)).returncode == 0
    profile, errors = load_profile(fixture_bundle)
    assert errors == []
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for needle in ("zz-private", "/home/alice", "10.0.0.12", "alice example"):
            assert needle not in lowered, (path, needle)
        assert scan(text, profile) == [], path


def test_redaction_applied(scripts_dir, bundle_copy, tmp_path):
    edit(
        bundle_copy / "rules" / "old-spoiler-rule.md",
        "Replaced by",
        "Mirror lives at /home/bob/vod on stream-box.lan.\n\nReplaced by",
    )
    out = tmp_path / "site"
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out))
    assert result.returncode == 0, result.stdout
    assert "(2 private excluded, 2 redaction(s) applied)" in result.stdout
    page = (out / "rules" / "old-spoiler-rule.html").read_text(encoding="utf-8")
    assert "Mirror lives at ~/vod on [internal-host]." in page
    assert "/home/bob" not in page and "stream-box.lan" not in page
    assert "/home/bob" not in (out / "search-index.json").read_text(encoding="utf-8")


def test_deterministic(scripts_dir, bundle_copy, tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    assert run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(first)).returncode == 0
    assert run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(second)).returncode == 0
    assert files_under(first) == files_under(second)
    for relative in files_under(first):
        assert (first / relative).read_bytes() == (second / relative).read_bytes(), relative


def test_out_inside_bundle_is_skipped(scripts_dir, bundle_copy):
    out = bundle_copy / "site"
    assert run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out)).returncode == 0
    again = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out))
    assert again.returncode == 0, again.stdout
    assert {path for path in files_under(out) if path.endswith(".html")} == EXPECTED_PAGES


def test_out_safety(scripts_dir, bundle_copy, tmp_path):
    same = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(bundle_copy))
    assert same.returncode == 2
    assert "ERROR P_OUT_UNSAFE" in same.stdout
    ancestor = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(tmp_path))
    assert ancestor.returncode == 2 and "P_OUT_UNSAFE" in ancestor.stdout

    a_file = tmp_path / "file.txt"
    a_file.write_text("keep\n", encoding="utf-8")
    as_file = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(a_file))
    assert as_file.returncode == 2 and "P_OUT_UNSAFE" in as_file.stdout

    unmarked = tmp_path / "unmarked"
    unmarked.mkdir()
    (unmarked / "keep.txt").write_text("keep\n", encoding="utf-8")
    refused = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(unmarked))
    assert refused.returncode == 2 and "P_OUT_UNSAFE" in refused.stdout
    assert files_under(unmarked) == ["keep.txt"]

    out = tmp_path / "site"
    assert run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out)).returncode == 0
    assert (out / "rules" / "old-spoiler-rule.html").is_file()
    (out / "stale.txt").write_text("old\n", encoding="utf-8")
    edit(bundle_copy / "rules" / "old-spoiler-rule.md", "status: deprecated\n", "status: deprecated\nx_visibility: private\n")
    rerun = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out))
    assert rerun.returncode == 0, rerun.stdout
    assert not (out / "rules" / "old-spoiler-rule.html").exists()
    assert not (out / "stale.txt").exists()
    assert "Old spoiler rule" not in (out / "search-index.json").read_text(encoding="utf-8")


def test_id_redaction_blocks(scripts_dir, bundle_copy, tmp_path):
    (bundle_copy / "hosts").mkdir()
    (bundle_copy / "hosts" / "stream-box.lan.md").write_text(
        "---\ntype: Host\ntitle: Box\n---\n\nThe box.\n", encoding="utf-8"
    )
    out = tmp_path / "site"
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out))
    assert result.returncode == 2
    assert (
        "ERROR P_ID_REDACTION hosts/stream-box.lan.md: rule stream-box-host matches the concept ID; "
        "rename the concept or make it private"
    ) in result.stdout
    assert not out.exists()


def test_errors_write_nothing(scripts_dir, bundle_copy, tmp_path):
    edit(bundle_copy / "rules" / "no-spoilers.md", "status: stable\n", "status: stable\nx_visibility: yes\n")
    out = tmp_path / "site"
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out))
    assert result.returncode == 2
    assert "ERROR P_VISIBILITY_INVALID rules/no-spoilers.md: x_visibility must be public or private" in result.stdout
    assert not out.exists()


def test_bundle_and_profile_errors(scripts_dir, bundle_copy, tmp_path):
    missing = run_publish(scripts_dir, "--bundle", str(tmp_path / "nope"), "--out", str(tmp_path / "site"))
    assert missing.returncode == 2 and "ERROR P_BUNDLE_MISSING" in missing.stdout
    (bundle_copy / "okf-publish.yaml").write_text('okf_publish_version: "9"\n', encoding="utf-8")
    bad = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(tmp_path / "site"))
    assert bad.returncode == 2
    assert "ERROR P_PROFILE_INVALID okf-publish.yaml: okf_publish_version" in bad.stdout
    assert not (tmp_path / "site").exists()


def test_zero_public_note(scripts_dir, bundle_copy, tmp_path):
    (bundle_copy / "schema.md").unlink()
    out = tmp_path / "site"
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out))
    assert result.returncode == 0, result.stdout
    assert "ok - published 0 public concept(s)" in result.stdout
    assert "note - no public concepts" in result.stdout
    assert "no schema.md at bundle root" in result.stdout
    assert (out / "index.html").is_file()


def file_line(path: Path, text: str) -> int:
    return path.read_text(encoding="utf-8").split("\n").index(text) + 1


def test_check_passes_on_fixture(scripts_dir, bundle_copy):
    before = files_under(bundle_copy)
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert result.returncode == 0, result.stdout
    assert result.stdout.startswith("ok - publish check passed: 3 public concept(s)")
    assert files_under(bundle_copy) == before


def test_check_fails_on_home_path_then_passes(scripts_dir, bundle_copy):
    concept = bundle_copy / "rules" / "no-spoilers.md"
    edit(concept, "Proposed in chat.[^s1]\n", "Proposed in chat.[^s1]\n\nSetup notes: /home/alice/obs.json\n")
    line = file_line(concept, "Setup notes: /home/alice/obs.json")
    failed = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert failed.returncode == 2
    assert (
        f"ERROR P_REDACTION rules/no-spoilers.md:{line}: rule home-path-unix matches published text (field body)"
        in failed.stdout
    )
    assert "/home/alice" not in failed.stdout + failed.stderr

    edit(concept, "Setup notes: /home/alice/obs.json", "Setup notes: ~/obs.json")
    passed = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert passed.returncode == 0, passed.stdout


def test_check_ignores_private(scripts_dir, bundle_copy):
    private = (bundle_copy / "ops" / "incident-42.md").read_text(encoding="utf-8")
    assert "/home/alice" in private and "10.0.0.12" in private and "Alice Example" in private
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert result.returncode == 0, result.stdout


def test_check_frontmatter_field(scripts_dir, bundle_copy):
    edit(bundle_copy / "rules" / "old-spoiler-rule.md", "description: Replaced rule.", "description: Runs on 10.0.0.12")
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert result.returncode == 2
    assert (
        "ERROR P_REDACTION rules/old-spoiler-rule.md: rule ipv4 matches published text (field description)"
        in result.stdout
    )
    assert "10.0.0.12" not in result.stdout


def test_check_index_text(scripts_dir, bundle_copy):
    index = bundle_copy / "index.md"
    edit(index, "(/ops/incident-42.md).\n", "(/ops/incident-42.md).\n\nHosted on stream-box.lan\n")
    line = file_line(index, "Hosted on stream-box.lan")
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert result.returncode == 2
    assert f"ERROR P_REDACTION index.md:{line}: rule stream-box-host matches published text (field index)" in result.stdout
    assert "stream-box.lan" not in result.stdout


def test_check_index_line_after_frontmatter_and_dropped_lines(scripts_dir, bundle_copy):
    index = bundle_copy / "index.md"
    text = index.read_text(encoding="utf-8")
    index.write_text('---\nokf_version: "0.1"\n---\n' + text + "\nHosted on stream-box.lan\n", encoding="utf-8")
    line = file_line(index, "Hosted on stream-box.lan")
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert result.returncode == 2
    assert f"ERROR P_REDACTION index.md:{line}: rule stream-box-host" in result.stdout


def test_check_and_out_exclusive(scripts_dir, bundle_copy, tmp_path):
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check", "--out", str(tmp_path / "site"))
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
    assert not (tmp_path / "site").exists()


def all_output_text(out: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(out.rglob("*")) if path.is_file())


LEAKY_PRIVATE_CONCEPTS = {
    "rules/secret-plan.md": '---\ntitle: "Layoffs [draft]"\ndescription: ZZ-LEAK-BRACKET-DESC\nx_visibility: private\n---\n\nBody.\n',
    "rules/unbal.md": '---\ntitle: "a] ZZ-LEAK-UNBAL"\ndescription: ZZ-LEAK-UNBAL-DESC\nx_visibility: private\n---\n\nBody.\n',
    "rules/my file.md": "---\ntitle: ZZ-LEAK-SPACE-TITLE\ndescription: ZZ-LEAK-SPACE-DESC\nx_visibility: private\n---\n\nBody.\n",
    "rules/hr.md": "---\ntitle: ZZ-LEAK-HR\ndescription: |\n  First line ZZ-LEAK-FIRST\n  ZZ-LEAK-SECOND-LINE about Bob\nx_visibility: private\n---\n\nBody.\n",
}
LEAK_NEEDLES = ("ZZ-LEAK", "Layoffs", "secret-plan", "unbal.md", "my file", "my%20file", "about Bob")


def test_reindexed_private_entries_never_reach_the_site(scripts_dir, bundle_copy, tmp_path):
    for relative, text in LEAKY_PRIVATE_CONCEPTS.items():
        (bundle_copy / relative).write_text(text, encoding="utf-8")
    (bundle_copy / "rules" / "bracketed.md").write_text(
        '---\ntitle: "Public [v2]"\ndescription: Shown rule.\n---\n\nBody.\n', encoding="utf-8"
    )
    # reindex.py walks dot-directories and fails on the fixture's frontmatter-less .github/notes.md.
    shutil.rmtree(bundle_copy / ".github")
    reindex = subprocess.run(
        [sys.executable, str(scripts_dir / "reindex.py"), "--bundle", str(bundle_copy)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert reindex.returncode == 0, reindex.stdout + reindex.stderr
    rules_index = (bundle_copy / "rules" / "index.md").read_text(encoding="utf-8")
    assert "* [Layoffs [draft]](secret-plan.md) - ZZ-LEAK-BRACKET-DESC" in rules_index
    assert "ZZ-LEAK-SECOND-LINE about Bob" in rules_index
    assert "(my file.md)" in rules_index

    check = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert check.returncode == 0, check.stdout
    out = tmp_path / "site"
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out))
    assert result.returncode == 0, result.stdout

    published = all_output_text(out)
    for needle in LEAK_NEEDLES:
        assert needle not in published, needle
    page = (out / "rules" / "index.html").read_text(encoding="utf-8")
    assert '<a href="bracketed.html">Public [v2]</a> - Shown rule.' in page
    assert '<a href="no-spoilers.html">No spoilers</a>' in page
    assert "ZZ-PRIVATE" not in published


def test_hand_written_lines_outside_markers_keep_prose(scripts_dir, bundle_copy, tmp_path):
    index = bundle_copy / "index.md"
    edit(index, "<!-- OKF:INDEX:BEGIN -->", "* [Old notes [v1]](/ops/incident-42.md) - ZZ-LEAK-HAND\n\n<!-- OKF:INDEX:BEGIN -->")
    out = tmp_path / "site"
    assert run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out)).returncode == 0
    root = (out / "index.html").read_text(encoding="utf-8")
    assert "ZZ-LEAK-HAND" not in root
    assert "See the incident." in root


def test_search_text_drops_nested_bracket_targets(scripts_dir, bundle_copy, tmp_path):
    edit(bundle_copy / "rules" / "no-spoilers.md", "Proposed in chat.[^s1]", "Proposed in chat.[^s1] See [notes [v2]](team-notes.md).")
    out = tmp_path / "site"
    assert run_publish(scripts_dir, "--bundle", str(bundle_copy), "--out", str(out)).returncode == 0
    index = (out / "search-index.json").read_text(encoding="utf-8")
    assert "team-notes" not in index
    assert "See notes [v2]." in index


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ("Esc: /home\\/alice/obs.json", "home-path-unix"),
        ("Box 10.0.0\\.12 is up", "ipv4"),
        ("Thanks **Alice** Example", "private-string-1"),
        ("Thanks [Alice](https://example.com/a) Example", "private-string-1"),
    ],
)
def test_check_catches_matches_split_by_markup(scripts_dir, bundle_copy, line, rule):
    concept = bundle_copy / "rules" / "no-spoilers.md"
    edit(concept, "Proposed in chat.[^s1]\n", f"Proposed in chat.[^s1]\n\n{line}\n")
    number = file_line(concept, line)
    result = run_publish(scripts_dir, "--bundle", str(bundle_copy), "--check")
    assert result.returncode == 2, result.stdout
    assert f"ERROR P_REDACTION rules/no-spoilers.md:{number}: rule {rule} matches published text (field body)" in result.stdout
    assert "alice" not in result.stdout.lower()
