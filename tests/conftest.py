"""Shared pytest setup: put the repo's scripts/ directory on sys.path."""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture
def fixture_bundle() -> Path:
    return Path(__file__).parent / "fixtures" / "publish_bundle"
