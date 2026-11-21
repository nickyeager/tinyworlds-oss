"""Append-only structured log of failures across all godogen runs.

Every failure the system catches — pre-export lint, post-export verify,
runtime telemetry freezes — appends one JSON record here. The file is the
corpus for passive learning: a periodic review (human or scheduled agent)
scans it, identifies recurring patterns, and turns them into bullets in
`.claude/skills/local/godogen-lessons/`.

Format: NDJSON (one JSON object per line) at `data/godogen_failures.jsonl`.
Schema:
    {
      "ts": ISO-8601 string,
      "game_id": str,
      "engine": "godot" | "bevy",
      "stage": "lint" | "verify" | "telemetry" | str,
      "rule": str,            # e.g. "forward_plus_only_feature"
      "detail": str,          # human-readable specifics
      "file": str | null,     # path within the game dir, if applicable
    }

Append is best-effort: a write failure must NOT break the calling pipeline.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOG_PATH = Path("data/godogen_failures.jsonl")


def record_failure(
    *,
    game_id: str,
    engine: str,
    stage: str,
    rule: str,
    detail: str,
    file: Optional[str] = None,
    log_path: Path = _LOG_PATH,
) -> None:
    """Append one failure record. Never raises."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "game_id": game_id,
        "engine": engine,
        "stage": stage,
        "rule": rule,
        "detail": detail,
        "file": file,
    }
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("failed to append failure record: %s", exc)
