"""Unit tests for src.api.services.upload_validator."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.api.services.upload_validator import (
    UploadError,
    sanitize_filename,
    save_upload,
    validate_image,
)


def test_sanitize_strips_path_separators():
    result = sanitize_filename("../../etc/passwd")
    assert "/" not in result
    assert "\\" not in result


def test_sanitize_handles_dot_dot():
    # Dot-only names must never survive sanitization — "." / ".." would
    # otherwise flow into save_upload's on-disk name and world metadata.
    assert sanitize_filename("..") == "upload"
    assert sanitize_filename(".") == "upload"
    assert sanitize_filename("...") == "upload"


def test_sanitize_collapses_special_chars():
    result = sanitize_filename("foo\x00bar;rm -rf.png")
    assert result == "foo_bar_rm_-rf.png"


def test_validate_image_rejects_oversized():
    with pytest.raises(UploadError):
        validate_image("image/png", 11 * 1024 * 1024)


def test_validate_image_rejects_wrong_mime():
    with pytest.raises(UploadError):
        validate_image("application/zip", 1024)


def test_validate_image_accepts_png_jpeg_webp():
    validate_image("image/png", 1024)
    validate_image("image/jpeg", 1024)
    validate_image("image/webp", 1024)


def test_save_upload_writes_inside_uploads_dir(tmp_path: Path):
    game_path = tmp_path / "game"
    game_path.mkdir()
    data = b"hello world"
    target = save_upload(game_path, "ref.png", data)
    assert target.exists()
    assert target.read_bytes() == data
    assert target.parent == (game_path / "_user_uploads").resolve()
    assert target.name.endswith("_ref.png")


def test_validate_image_rejects_spoofed_magic():
    """Declared MIME is caller-controlled — with data provided, magic bytes
    must match or the upload is rejected."""
    with pytest.raises(UploadError):
        validate_image("image/png", 20, b"MZ\x90\x00" + b"\x00" * 16)


def test_validate_image_accepts_matching_magic():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    validate_image("image/png", len(png), png)
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 8
    validate_image("image/jpeg", len(jpeg), jpeg)
    webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP"
    validate_image("image/webp", len(webp), webp)


def test_validate_image_skips_sniff_without_data():
    # Header-only callers (size pre-checks) keep working.
    validate_image("image/png", 10)
