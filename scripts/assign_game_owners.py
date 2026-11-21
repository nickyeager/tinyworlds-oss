#!/usr/bin/env python3
"""Explicit operator migration for legacy games; dry-run unless --apply."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.api.services.game_access import create_access, game_path, read_access


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mapping", type=Path, help="JSON object mapping game IDs to existing user UUIDs"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text())
    if not isinstance(mapping, dict):
        parser.error("Mapping must be a JSON object")
    records = []
    for game_id, owner in mapping.items():
        owner = str(UUID(owner))
        if not game_path(game_id).is_dir():
            parser.error(f"Missing game: {game_id}")
        if read_access(game_id).owner_user_id is not None:
            parser.error(f"Game already has an owner: {game_id}")
        records.append((game_id, owner))
    for game_id, owner in records:
        print(f"{game_id} -> {owner}")
        if args.apply:
            create_access(game_id, owner)
    print(
        "Applied"
        if args.apply
        else "Dry run; use --apply to persist these exact assignments"
    )


if __name__ == "__main__":
    main()
