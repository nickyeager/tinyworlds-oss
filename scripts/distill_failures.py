#!/usr/bin/env python3
"""Distill recurring failures into proposed godogen-lessons bullets.

Reads `data/godogen_failures.jsonl`, groups by (engine, stage, rule), and
emits a markdown file of proposed lessons for any (engine, rule) pair that
fires across >= MIN_GAMES distinct games and isn't already covered.

Outputs two artifacts:
  - data/proposed_lessons.md   — human-readable proposals (rule, count,
    distinct games, sample details, suggested bucket)
  - data/proposed_lessons.json — machine-readable for downstream automation

This is the deterministic half of the loop. A scheduled Claude routine
reads `proposed_lessons.md`, decides which proposals are real lessons
worth keeping, and edits the `godogen-lessons/` markdown files.

Run via cron / launchd / `schedule` skill, ideally 1-2x daily.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
FAILURES = ROOT / "data" / "godogen_failures.jsonl"
LESSONS_DIR = ROOT / ".claude" / "skills" / "local" / "godogen-lessons"
PROPOSAL_MD = ROOT / "data" / "proposed_lessons.md"
PROPOSAL_JSON = ROOT / "data" / "proposed_lessons.json"

MIN_GAMES = 3       # Pattern must hit >=N distinct games to propose
LOOKBACK_DAYS = 30  # Only consider recent failures

STAGE_TO_BUCKET = {
    "lint": "general.md",
    "verify": "general.md",
    "telemetry": "general.md",
    "scaffold": "scaffold.md",
    "scripts": "scripts.md",
    "scenes": "scenes.md",
    "assets": "assets.md",
    "capture": "capture.md",
}


def load_failures(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            ts = datetime.fromisoformat(rec["ts"])
        except (KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        out.append(rec)
    return out


def load_existing_lessons() -> str:
    """Concatenate all lesson markdown so we can keyword-match coverage."""
    if not LESSONS_DIR.exists():
        return ""
    chunks: list[str] = []
    for p in sorted(LESSONS_DIR.glob("*.md")):
        chunks.append(p.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def is_covered(rule: str, sample_detail: str, lessons_text: str) -> bool:
    """Heuristic: rule name or a distinctive phrase from the detail already
    appears in lessons. Conservative — false negatives just mean the routine
    sees the same proposal twice; that's fine."""
    if rule in lessons_text:
        return True
    # Pull distinctive tokens (CamelCase / dotted / snake words ≥6 chars)
    tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9.]{5,}", sample_detail or "")
    for tok in tokens[:3]:
        if tok in lessons_text:
            return True
    return False


def group(records: Iterable[dict]) -> dict[tuple, dict]:
    groups: dict[tuple, dict] = defaultdict(
        lambda: {"count": 0, "games": set(), "samples": [], "last_ts": ""}
    )
    for rec in records:
        key = (rec.get("engine", "?"), rec.get("stage", "?"), rec.get("rule", "?"))
        g = groups[key]
        g["count"] += 1
        g["games"].add(rec.get("game_id", "?"))
        if len(g["samples"]) < 3:
            g["samples"].append(rec.get("detail", "")[:200])
        if rec.get("ts", "") > g["last_ts"]:
            g["last_ts"] = rec.get("ts", "")
    return groups


def main() -> int:
    records = load_failures(FAILURES)
    if not records:
        PROPOSAL_MD.write_text("# Proposed lessons\n\n_No failures in lookback window._\n")
        PROPOSAL_JSON.write_text("[]")
        print("no failures to distill")
        return 0

    lessons_text = load_existing_lessons()
    groups = group(records)

    proposals: list[dict] = []
    for (engine, stage, rule), g in groups.items():
        if len(g["games"]) < MIN_GAMES:
            continue
        if is_covered(rule, g["samples"][0] if g["samples"] else "", lessons_text):
            continue
        proposals.append({
            "engine": engine,
            "stage": stage,
            "rule": rule,
            "count": g["count"],
            "distinct_games": sorted(g["games"]),
            "last_seen": g["last_ts"],
            "samples": g["samples"],
            "suggested_bucket": STAGE_TO_BUCKET.get(stage, "general.md"),
        })

    proposals.sort(key=lambda p: (-p["count"], p["rule"]))

    # Markdown for human / agent review
    lines = ["# Proposed lessons\n"]
    lines.append(
        f"_Generated {datetime.now(timezone.utc).isoformat()} — "
        f"{len(records)} failures over {LOOKBACK_DAYS}d, "
        f"{len(proposals)} proposals (>= {MIN_GAMES} distinct games, not already covered)._\n"
    )
    if not proposals:
        lines.append("\nNo new patterns rise above threshold.\n")
    for p in proposals:
        lines.append(f"\n## `{p['engine']}` / `{p['stage']}` / `{p['rule']}`")
        lines.append(f"- **{p['count']}** occurrences across **{len(p['distinct_games'])}** games")
        lines.append(f"- Last seen: {p['last_seen']}")
        lines.append(f"- Suggested bucket: `{p['suggested_bucket']}`")
        lines.append(f"- Sample details:")
        for s in p["samples"]:
            lines.append(f"  - {s}")

    PROPOSAL_MD.parent.mkdir(parents=True, exist_ok=True)
    PROPOSAL_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    PROPOSAL_JSON.write_text(json.dumps(proposals, indent=2), encoding="utf-8")
    print(f"wrote {len(proposals)} proposals to {PROPOSAL_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
