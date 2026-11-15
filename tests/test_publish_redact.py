from pathlib import Path
import re

import pytest

from publish_redact import DEFAULT_RULES, default_profile, load_profile, redact, scan

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "okf-publish.yaml"


def write_profile(tmp_path: Path, text: str):
    (tmp_path / "okf-publish.yaml").write_text(text, encoding="utf-8")
    return load_profile(tmp_path)


def test_default_rules_redact_samples(tmp_path):
    profile, errors = load_profile(tmp_path)
    assert errors == []
    assert profile is not None and profile.path is None
    token = "ghp_" + "A1b2C3d4E5" * 4
    text = "\n".join(
        [
            "/home/alice/x",
            "C:\\Users\\bob\\x",
            "10.0.0.12",
            token,
            "-----BEGIN RSA PRIVATE KEY-----",
        ]
    )
    redacted, counts = redact(text, profile)
    assert redacted.split("\n") == ["~/x", "~\\x", "[ip]", "[token]", "[private-key]"]
    assert counts == {
        "home-path-unix": 1,
        "home-path-windows": 1,
        "ipv4": 1,
        "github-token": 1,
        "private-key-block": 1,
    }


def test_private_strings_case_insensitive(tmp_path):
    profile, errors = write_profile(tmp_path, 'okf_publish_version: "0.1"\nprivate_strings: [Alice Example]\n')
    assert errors == []
    redacted, counts = redact("Thanks, alice example!", profile)
    assert redacted == "Thanks, [redacted]!"
    assert counts == {"private-string-1": 1}


def test_disable_default_rule(tmp_path):
    profile, errors = write_profile(tmp_path, 'okf_publish_version: "0.1"\ndisable_default_rules: [ipv4]\n')
    assert errors == []
    assert redact("serve on 127.0.0.1", profile) == ("serve on 127.0.0.1", {})


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("- just a list\n", "top level"),
        ('okf_publish_version: "0.1"\nextra: 1\n', "extra"),
        ("okf_publish_version: 0.1\n", "okf_publish_version"),
        ("disable_default_rules: []\n", "okf_publish_version"),
        ('okf_publish_version: "0.1"\ndisable_default_rules: [nope]\n', "disable_default_rules"),
        ('okf_publish_version: "0.1"\nrules:\n  - pattern: x\n', "missing id"),
        ('okf_publish_version: "0.1"\nrules:\n  - id: a\n', "rule a is missing pattern"),
        ('okf_publish_version: "0.1"\nrules:\n  - id: Bad_Id\n    pattern: x\n', "Bad_Id"),
        ('okf_publish_version: "0.1"\nrules:\n  - id: a\n    pattern: x\n  - id: a\n    pattern: y\n', "rules id a"),
        ('okf_publish_version: "0.1"\nrules:\n  - id: ipv4\n    pattern: x\n', "rules id ipv4"),
        ('okf_publish_version: "0.1"\nrules:\n  - id: broken\n    pattern: "("\n', "rule broken"),
        ('okf_publish_version: "0.1"\nprivate_strings: [""]\n', "private_strings"),
        ('okf_publish_version: "0.1"\nprivate_strings: [3]\n', "private_strings"),
        ('okf_publish_version: "0.1"\nrules:\n  - id: a\n    pattern: x\n    replace: 5\n', "replace"),
        ("okf_publish_version: [\n", "YAML"),
    ],
)
def test_profile_errors(tmp_path, text, needle):
    profile, errors = write_profile(tmp_path, text)
    assert profile is None
    assert errors
    assert any(needle in error for error in errors), errors


def test_missing_explicit_profile(tmp_path):
    profile, errors = load_profile(tmp_path, tmp_path / "absent.yaml")
    assert profile is None
    assert errors == ["profile file not found."]


def test_scan_reports_lines_not_text():
    hits = scan("a\n/home/alice\n", default_profile())
    assert hits == [("home-path-unix", 2)]
    assert all("alice" not in str(part) for hit in hits for part in hit)


def test_replace_is_literal(tmp_path):
    profile, errors = write_profile(
        tmp_path, "okf_publish_version: \"0.1\"\nrules:\n  - id: grp\n    pattern: '(secret)'\n    replace: '\\1'\n"
    )
    assert errors == []
    assert redact("a secret b", profile) == ("a \\1 b", {"grp": 1})


def test_template_lists_default_ids(tmp_path):
    listed = re.findall(r"^#   - ([a-z0-9-]+)$", TEMPLATE.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert listed == [rule[0] for rule in DEFAULT_RULES]
    profile, errors = load_profile(tmp_path, TEMPLATE)
    assert errors == []
    assert [rule.id for rule in profile.rules] == listed
