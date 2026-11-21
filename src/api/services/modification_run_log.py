"""Helpers for persisted game modification run logs.

Each modify request writes an append-only event log under
``<game>/.modifications/<run_id>/events.jsonl`` plus a ``summary.json``. This
module keeps the summary shape consistent across engines and provides read
helpers for API routes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.api.services.game_event_log import GameEventLog


def reference_attachments(game_path: Path, instruction: str) -> list[dict[str, str]]:
    """Recover uploaded references from current and legacy persisted requests.

    Return only existing images inside this game's upload directory. Never turn
    an arbitrary absolute path from an instruction into a browser asset URL.
    """
    marker = "\n\nReference image attached at: "
    if marker not in instruction:
        return []
    candidate = instruction.split(marker, 1)[1].split("\n", 1)[0].strip()
    if not candidate:
        return []
    root = game_path.resolve()
    path = Path(candidate)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(root)
        if relative.parts[0] != "_user_uploads" or not resolved.is_file():
            return []
    except (ValueError, OSError, IndexError):
        return []
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(resolved.suffix.lower())
    if not media_type:
        return []
    from src.api.services.visual_reference import reference_details
    details = reference_details(resolved)
    return [{"path": relative.as_posix(), "name": resolved.name, "media_type": media_type, **({"purpose": details["purpose"]} if details else {})}]


def infer_image_outputs(events: list[dict[str, Any]]) -> list[str]:
    """Persist image outputs separately from tool text for history rendering."""
    images: dict[str, None] = {}
    for event in events:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        kind = event.get("stream_type") or event.get("type") or event.get("event_type")
        if kind not in {"tool_result", "file_changed"} or metadata.get("success") is False:
            continue
        for match in re.finditer(r"(?:^|[\s\"'`(/])((?:assets|screenshots)/[^\s\"'`<>\n)]+\.(?:png|jpe?g|webp))(?=$|[\s\"'`)>,])", str(event.get("content") or ""), re.IGNORECASE):
            path = match.group(1)
            if ".." not in Path(path).parts:
                images[path] = None
    return list(images)


def _with_attachments(summary: dict[str, Any], game_path: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        **summary,
        "attachments": reference_attachments(game_path, str(summary.get("instruction") or "")),
        "generated_images": summary["generated_images"] if "generated_images" in summary else infer_image_outputs(events),
    }


def utc_now_iso() -> str:
    """Return a compact UTC timestamp suitable for API JSON."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def screenshot_names_since(game_path: Path, start_mtime: float) -> list[str]:
    """Return screenshot paths written after ``start_mtime``.

    Paths are relative to the game directory so they are safe to expose in run
    summaries and stable across local/prod roots.
    """
    screenshots_dir = game_path / "screenshots"
    if not screenshots_dir.exists():
        return []
    screenshots: list[Path] = []
    for path in screenshots_dir.rglob("*.png"):
        try:
            if path.stat().st_mtime >= start_mtime:
                screenshots.append(path)
        except OSError:
            continue
    screenshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p.relative_to(game_path)) for p in screenshots]


def infer_changed_files(events: list[dict[str, Any]]) -> list[str]:
    """Best-effort changed-file extraction from agent metadata/events."""
    changed: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        candidate = value.strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        changed.append(candidate)

    for event in events:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("changed_files", "files", "file_paths"):
            value = metadata.get(key)
            if isinstance(value, list):
                for item in value:
                    add(item)
        add(metadata.get("file_path"))
        add(metadata.get("path"))
    return changed


def build_modification_summary(
    *,
    game_id: str,
    engine: str,
    run_id: str,
    instruction: str,
    status: str,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    event_count: int,
    final_message: str,
    error: Optional[str],
    has_export: bool,
    has_playable_build: bool,
    verification_failures: list[str],
    events: list[dict[str, Any]],
    new_screenshots: list[str],
    rebuild_status: Optional[str] = None,
    export_status: Optional[str] = None,
    explanation: Optional[str] = None,
    changes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build the normalized summary persisted for each modification run."""
    return {
        "run_id": run_id,
        "game_id": game_id,
        "engine": engine,
        "instruction": instruction,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 2),
        "event_count": event_count,
        "final_message": final_message,
        "explanation": explanation,
        "changes": changes or [],
        "error": error,
        "has_export": has_export,
        "has_playable_build": has_playable_build,
        "rebuild_status": rebuild_status,
        "export_status": export_status,
        "new_screenshots": new_screenshots,
        "generated_images": infer_image_outputs(events),
        "changed_files": infer_changed_files(events),
        "verification_failures": verification_failures,
    }


def _summary_from_events(
    events: list[dict[str, Any]], *, game_id: str, engine: str, run_id: str,
) -> dict[str, Any]:
    init = events[0]
    metadata = init.get("metadata") if isinstance(init.get("metadata"), dict) else {}
    terminal = next(
        (event for event in reversed(events) if event.get("event_type") in {"done", "failed", "crashed", "interrupted"}),
        None,
    )
    status = "running" if terminal is None else {
        "done": "success", "failed": "failed", "crashed": "crashed", "interrupted": "interrupted",
    }[terminal["event_type"]]
    message = (terminal.get("content") or terminal.get("reason")) if terminal else None
    return {
        "run_id": run_id, "game_id": game_id, "engine": engine,
        "instruction": metadata.get("instruction", ""), "status": status,
        "started_at": init.get("timestamp"), "event_count": len(events),
        "final_message": message,
        "error": message if status not in {"running", "success"} else None,
    }


def read_modification_run(
    game_path: Path,
    *,
    game_id: str,
    engine: str,
    run_id: str,
) -> dict[str, Any]:
    """Read one modification run as ``summary`` plus parsed events."""
    event_log = GameEventLog(game_path, log_dir=f".modifications/{run_id}")
    events = event_log.read_all()
    summary = event_log.read_summary()
    if summary is None and events:
        summary = _summary_from_events(events, game_id=game_id, engine=engine, run_id=run_id)
    if summary is not None:
        summary = _with_attachments(summary, game_path, events)
    return {
        "game_id": game_id,
        "engine": engine,
        "run_id": run_id,
        "summary": summary,
        "events": events,
    }


def list_modification_runs(game_path: Path, *, game_id: str, engine: str) -> list[dict[str, Any]]:
    """List modification run summaries, newest first."""
    root = game_path / ".modifications"
    if not root.is_dir():
        return []

    runs: list[dict[str, Any]] = []
    for run_dir in root.iterdir():
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        if not run_id.isalnum() or len(run_id) > 32:
            continue
        event_log = GameEventLog(game_path, log_dir=f".modifications/{run_id}")
        summary = event_log.read_summary()
        events = None
        if summary is None:
            events = event_log.read_all()
            if not events:
                continue
            summary = _summary_from_events(events, game_id=game_id, engine=engine, run_id=run_id)
        if "generated_images" not in summary and events is None:
            events = event_log.read_all()
        runs.append(_with_attachments(summary, game_path, events or []))

    def sort_key(summary: dict[str, Any]) -> str:
        value = summary.get("started_at") or summary.get("finished_at")
        if isinstance(value, str):
            return value
        run_id = summary.get("run_id")
        run_dir = root / str(run_id)
        try:
            return datetime.fromtimestamp(
                run_dir.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            return ""

    return sorted(runs, key=sort_key, reverse=True)


def read_json_events(path: Path) -> list[dict[str, Any]]:
    """Read JSONL events directly from ``path``; useful in tests/migrations."""
    events: list[dict[str, Any]] = []
    if not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
