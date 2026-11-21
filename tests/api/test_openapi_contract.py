"""
Contract snapshot tests for the game API surfaces.

Catches accidental backend schema drift across the seam between the route
modules (godot_games / bevy_games / games umbrella) and `web/src/lib/api.ts`.
A failing test means the backend schema changed; verify `web/src/lib/api.ts`
was updated to match, then re-seed the snapshot:

    UPDATE_SNAPSHOTS=1 pytest tests/api/test_openapi_contract.py
"""
import json
import os
from pathlib import Path

import pytest
from httpx import AsyncClient

SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__"

# (snapshot name, tracked path prefix). godot keeps its historical filename.
SURFACES = [
    ("godot", "/api/v1/godot"),
    ("bevy", "/api/v1/bevy"),
    ("games", "/api/v1/games"),
]


def _extract_surface(openapi: dict, prefix: str) -> dict:
    """Narrow the full OpenAPI doc to one route prefix + its schemas."""
    paths = {
        path: spec
        for path, spec in openapi.get("paths", {}).items()
        if path.startswith(prefix)
    }
    referenced_schemas = set()
    blob = json.dumps(paths)
    for name in openapi.get("components", {}).get("schemas", {}):
        if f'"#/components/schemas/{name}"' in blob:
            referenced_schemas.add(name)
    schemas = {
        name: openapi["components"]["schemas"][name]
        for name in sorted(referenced_schemas)
    }
    return {"paths": paths, "schemas": schemas}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,prefix", SURFACES)
async def test_openapi_contract(client: AsyncClient, name: str, prefix: str):
    snapshot_path = SNAPSHOT_DIR / f"{name}_openapi.json"
    response = await client.get("/openapi.json")
    assert response.status_code == 200, "OpenAPI doc unavailable"
    current = _extract_surface(response.json(), prefix)
    assert current["paths"], f"no routes matched prefix {prefix!r} — wrong prefix?"

    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not snapshot_path.exists():
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        if not os.environ.get("UPDATE_SNAPSHOTS"):
            pytest.fail(
                f"Seeded new snapshot at {snapshot_path}. Review and commit it."
            )
        return

    expected = json.loads(snapshot_path.read_text())
    if current != expected:
        diff_path = snapshot_path.with_suffix(".actual.json")
        diff_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        pytest.fail(
            f"{name} API contract drift detected.\n"
            f"  expected: {snapshot_path}\n"
            f"  actual:   {diff_path}\n"
            "If intentional, update web/src/lib/api.ts to match, then re-seed:\n"
            "  UPDATE_SNAPSHOTS=1 pytest tests/api/test_openapi_contract.py"
        )
