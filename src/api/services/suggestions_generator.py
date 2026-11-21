"""Generate short modification suggestions for a game via a one-shot CLI call.

Best-effort: failures are logged and swallowed. The sidecar
`suggestions.json` is written only on success.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are suggesting modifications to an existing {engine} game.

Game description / plan:
{description}

Files in the project root:
{files}

Return STRICT JSON of the form:
{{"suggestions": ["...", "...", "...", "...", "..."]}}

Constraints:
- exactly 5 suggestions
- each is a short imperative phrase, no more than 6 words
- specific to THIS game's mechanics and entities (named in the plan/files above) — do NOT return generic gamedev advice like "add music" or "make harder"
- no commentary outside the JSON
"""


def _read_first(path: Path, names: list[str], max_chars: int = 4000) -> str:
    for n in names:
        p = path / n
        if p.exists():
            try:
                return p.read_text()[:max_chars]
            except Exception:
                continue
    return "(no description available)"


def _list_root_files(path: Path, limit: int = 30) -> str:
    try:
        names = sorted(p.name for p in path.iterdir())[:limit]
        return "\n".join(names) if names else "(empty)"
    except Exception:
        return "(unreadable)"


def parse_suggestions_json(raw: str) -> List[str]:
    """Extract a {"suggestions": [...]} list from raw model output.

    Tolerates code fences and surrounding prose. Returns [] on any failure.
    """
    if not raw:
        return []
    # Try direct parse first.
    candidates = [raw]
    # Then any {...} block.
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        candidates.append(match.group(0))

    for c in candidates:
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        items = data.get("suggestions")
        if not isinstance(items, list):
            continue
        clean = [s for s in items if isinstance(s, str) and s.strip()]
        return clean[:5]
    return []


async def generate_suggestions(
    game_path: Path,
    engine: str,
    *,
    executor,
) -> List[str]:
    """Generate suggestions, write sidecar, return list. Never raises."""
    try:
        description = _read_first(
            game_path,
            ["PLAN.md", "STRUCTURE.md", "MEMORY.md"],
        )
        files = _list_root_files(game_path)
        prompt = PROMPT_TEMPLATE.format(
            engine=engine, description=description, files=files,
        )
        raw = await executor.run_oneshot(prompt, timeout=30.0)
    except Exception as e:
        logger.warning("suggestions: executor failed for %s: %s", game_path.name, e)
        return []

    suggestions = parse_suggestions_json(raw)
    if not suggestions:
        logger.warning(
            "suggestions: parse failed for %s; raw=%r",
            game_path.name, raw[:300],
        )
        return []

    sidecar = game_path / "suggestions.json"
    payload = {
        "suggestions": suggestions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sidecar.write_text(json.dumps(payload, indent=2))
    except Exception as e:
        logger.warning("suggestions: write failed for %s: %s", game_path.name, e)
        return suggestions  # parsing succeeded; caller can still use the list

    return suggestions
