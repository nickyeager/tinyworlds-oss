"""Backfill touch controls into existing games that lack them.

Iterates ``generated_games/`` and runs :func:`lint_touch_handlers` against
each. For failures, optionally calls the local modification API to patch the
game in place.

Usage::

    # Dry-run: just report which games need backfilling.
    python scripts/backfill_touch_controls.py

    # Actually call the modify API for each failing game.
    python scripts/backfill_touch_controls.py --apply

    # Limit to specific engine.
    python scripts/backfill_touch_controls.py --engine godot --apply

Bounded cost: ~$1–2 per modification call; 8 games today ≈ $10–15 worst case.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable, Literal

import urllib.request
import urllib.error

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.api.services.touch_input_lint import lint_touch_handlers  # noqa: E402

Engine = Literal["godot", "bevy"]

BACKFILL_INSTRUCTION = (
    "Add touch controls to this game. Implement a virtual joystick (left side, "
    "lower) for movement and one or two action buttons (right side) for primary "
    "actions. For Godot, handle InputEventScreenTouch / InputEventScreenDrag in "
    "_unhandled_input. For Bevy, read the Touches resource or TouchInput events. "
    "Keep existing keyboard controls — touch is additive, not replacing. The "
    "game must be playable end-to-end on a phone in portrait or landscape with "
    "no keyboard."
)


def discover_games(games_dir: Path, engine_filter: Engine | None) -> Iterable[tuple[Path, Engine]]:
    for game in sorted(games_dir.iterdir()):
        if not game.is_dir():
            continue
        if game.name.startswith("godot-"):
            engine: Engine = "godot"
        elif game.name.startswith("bevy-"):
            engine = "bevy"
        else:
            continue
        if engine_filter and engine != engine_filter:
            continue
        yield game, engine


def call_modify(api_base: str, token: str, engine: Engine, game_id: str, instruction: str) -> bool:
    """POST to the modify endpoint. Streams SSE; we just wait for completion."""
    url = f"{api_base}/api/v1/{engine}/games/{game_id}/modify"
    body = json.dumps({"instruction": instruction}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            for line in resp:
                txt = line.decode("utf-8", errors="replace").rstrip()
                if txt.startswith("data:"):
                    print(f"    {txt[:200]}")
        return True
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}")
        return False
    except Exception as e:
        print(f"    error: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--games-dir", default=str(REPO_ROOT / "generated_games"))
    ap.add_argument("--engine", choices=["godot", "bevy"], default=None)
    ap.add_argument("--apply", action="store_true", help="Actually call the modify API")
    ap.add_argument("--api-base", default="http://localhost:8001")
    ap.add_argument("--token", default=None, help="Bearer token (required with --apply)")
    args = ap.parse_args()

    games_dir = Path(args.games_dir)
    if not games_dir.exists():
        print(f"games dir not found: {games_dir}", file=sys.stderr)
        return 2

    if args.apply and not args.token:
        print("--apply requires --token <bearer>", file=sys.stderr)
        return 2

    pending: list[tuple[Path, Engine]] = []
    skipped = 0
    for game, engine in discover_games(games_dir, args.engine):
        failures = lint_touch_handlers(game, engine)
        if failures:
            print(f"FAIL {engine}/{game.name}: {failures[0].detail}")
            pending.append((game, engine))
        else:
            skipped += 1

    print(f"\nSummary: {len(pending)} need backfill, {skipped} already OK")

    if not args.apply or not pending:
        return 0

    print(f"\nApplying to {len(pending)} game(s)...")
    succeeded = failed = 0
    for game, engine in pending:
        print(f"\n>>> modify {engine}/{game.name}")
        ok = call_modify(args.api_base, args.token, engine, game.name, BACKFILL_INSTRUCTION)
        # Re-lint to confirm the modification actually added touch.
        time.sleep(2)
        post = lint_touch_handlers(game, engine)
        if ok and not post:
            succeeded += 1
            print(f"    OK — touch handlers now present")
        else:
            failed += 1
            print(f"    STILL FAILING — manual review needed")

    print(f"\nDone: {succeeded} succeeded, {failed} still failing")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
