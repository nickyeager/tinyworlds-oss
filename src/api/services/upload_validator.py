"""Image upload validation + sanitization."""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


class UploadError(Exception):
    """Raised on rejected uploads. Caller maps to HTTP 400."""


def sanitize_filename(name: str) -> str:
    """Strip path separators and control chars; cap length, preserve extension."""
    base = Path(name).name  # drops any directory components
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not base.strip("."):  # "", ".", ".." — never emit a dot-only name
        return "upload"
    if len(base) > 80:
        stem, _, ext = base.rpartition(".")
        if ext:
            base = stem[: 80 - len(ext) - 1] + "." + ext
        else:
            base = base[:80]
    return base or "upload"


def _matches_magic(content_type: str, data: bytes) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def validate_image(
    content_type: str | None, size: int, data: bytes | None = None
) -> None:
    """Raise UploadError if content-type, size, or (when ``data`` is given)
    the file's magic bytes are unacceptable. The declared MIME alone is
    caller-controlled — pass ``data`` to reject spoofed uploads."""
    ct = (content_type or "").lower()
    if ct not in ALLOWED_MIME:
        raise UploadError(f"unsupported content-type: {content_type!r}")
    if size > MAX_BYTES:
        raise UploadError(f"file too large: {size} bytes (max {MAX_BYTES})")
    if data is not None and not _matches_magic(ct, data):
        raise UploadError(f"file content does not match declared content-type {ct}")


def save_upload(game_path: Path, filename: str, data: bytes) -> Path:
    """Persist the upload under ``game_path / _user_uploads / <ts>_<safe>``."""
    uploads = (game_path / "_user_uploads").resolve()
    uploads.mkdir(exist_ok=True)
    safe = sanitize_filename(filename)
    prefix = f"{time.time_ns()}_{uuid.uuid4().hex[:8]}"
    target = (uploads / f"{prefix}_{safe}").resolve()
    if uploads not in target.parents:
        raise UploadError("invalid upload path")
    target.write_bytes(data)
    return target
