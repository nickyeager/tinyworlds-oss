"""Summarize browser/runtime telemetry for game repair prompts."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.api.services.game_runtime_log import default_runtime_log


INTERESTING_TELEMETRY_KINDS = {
    "error",
    "unhandledrejection",
    "console.error",
    "console.warn",
    "godot.printErr",
    "frozen",
    "webglcontextlost",
    "webglcontextrestored",
}


def _compact_json(value: Any, *, limit: int = 700) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except TypeError:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _read_latest_browser_telemetry(game_path: Path, *, max_files: int = 4) -> list[dict[str, Any]]:
    telemetry_dir = game_path / "telemetry"
    if not telemetry_dir.is_dir():
        return []
    files = sorted(
        telemetry_dir.glob("*.ndjson"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:max_files]

    events: list[dict[str, Any]] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines[-80:]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event["_session_file"] = path.name
            events.append(event)
    return events


def build_runtime_diagnostics(
    game_path: Path,
    *,
    game_id: str,
    engine: str,
    max_events: int = 12,
) -> str | None:
    """Return a concise Markdown runtime diagnosis for modify agents.

    The goal is not to dump telemetry. It is to give the next repair pass the
    few facts that matter: recent browser failures, playthrough events, and
    sampled game state around freezes/hits.
    """
    browser_events = _read_latest_browser_telemetry(game_path)
    runtime_events = default_runtime_log.events_for_game(game_id, limit=80)
    if not browser_events and not runtime_events:
        return None

    lines = [
        "# Runtime Diagnostics",
        "",
        f"- Engine: {engine}",
        f"- Game ID: {game_id}",
        "- Use this telemetry as evidence when debugging crashes, freezes, input failures, or broken game flow.",
        "- Prefer deterministic fixes and add/update in-game state telemetry when repairing runtime bugs.",
    ]

    if browser_events:
        kind_counts = Counter(str(event.get("kind", "unknown")) for event in browser_events)
        lines.extend([
            "",
            "## Browser Telemetry Summary",
            f"- Sessions inspected: {len({event.get('_session_file') for event in browser_events})}",
            f"- Event counts: {_compact_json(dict(kind_counts), limit=900)}",
        ])
        latest_samples = [
            event for event in browser_events
            if event.get("kind") == "sample" and isinstance(event.get("godot"), dict)
        ][-5:]
        if latest_samples:
            lines.append("- Recent game-state samples:")
            for event in latest_samples:
                lines.append(f"  - {_compact_json(event.get('godot'))}")

        interesting = [
            event for event in browser_events
            if event.get("kind") in INTERESTING_TELEMETRY_KINDS
            or event.get("_reason") in {"frozen", "webglcontextlost", "printErr"}
        ][-max_events:]
        if interesting:
            lines.append("- Recent failure signals:")
            for event in interesting:
                detail = {
                    "kind": event.get("kind"),
                    "reason": event.get("_reason"),
                    "message": event.get("message") or event.get("msg"),
                    "drift": event.get("drift"),
                    "session": event.get("_session_file"),
                    "godot": event.get("godot"),
                }
                lines.append(f"  - {_compact_json({k: v for k, v in detail.items() if v is not None})}")

    if runtime_events:
        summary = default_runtime_log.summary_for_game(game_id)
        lines.extend([
            "",
            "## Playthrough Event Summary",
            f"- Event counts: {_compact_json(summary.get('kind_counts', {}), limit=900)}",
            "- Recent events:",
        ])
        for event in runtime_events[:max_events]:
            lines.append(
                f"  - kind={event.get('kind')} session={event.get('session_id')} "
                f"data={_compact_json(event.get('data', {}))}"
            )

    return "\n".join(lines).strip() + "\n"
