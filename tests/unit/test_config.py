"""Configuration parsing tests."""

from src.api.core.config import Settings


def test_debug_accepts_release_mode_string() -> None:
    settings = Settings(SECRET_KEY="test", DEBUG="release", _env_file=None)

    assert settings.DEBUG is False


def test_debug_accepts_development_mode_string() -> None:
    settings = Settings(SECRET_KEY="test", DEBUG="development", _env_file=None)

    assert settings.DEBUG is True
