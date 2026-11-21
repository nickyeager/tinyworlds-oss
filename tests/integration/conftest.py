"""Shared fixtures for integration tests.

These fixtures provide common test data and setup for tests that call
real external services (Gemini, Azure, etc.).
"""
import shutil
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load environment variables from .env file for integration tests
# This ensures Azure, OpenAI, and other API keys are available
load_dotenv()


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to the fixtures directory."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def minimal_godot_project(fixtures_dir: Path, tmp_path: Path) -> Path:
    """Copy minimal Godot project to temp directory for test isolation.

    Returns the path to the copied project.
    """
    source = fixtures_dir / "godot_projects" / "minimal_project"
    dest = tmp_path / "test_project"
    shutil.copytree(source, dest)
    return dest


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Create a temporary output directory for generated files."""
    output = tmp_path / "output"
    output.mkdir()
    return output
