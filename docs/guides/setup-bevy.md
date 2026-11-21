# Bevy builder setup

Bevy exports run through the trusted launcher. The backend sends an authenticated
build request; only the launcher has Docker access. It starts a non-root,
read-only worker with one game's volume subdirectory mounted, dropped
capabilities, resource limits and per-game Cargo caches.

## Prerequisites and image

Use Docker Engine/Desktop with Compose v2, the repository Python dependencies,
and the generation launcher configuration described in [generation.md](generation.md).
Build the image before requesting a Bevy export:

```bash
docker compose --profile bevy build bevy-builder
```

The launcher selects `BEVY_BUILDER_IMAGE`; the backend's constructor cannot
change the image. Start the configured launcher with access to the Docker
socket, `AGENT_GAMES_VOLUME`, `AGENT_NETWORK`, and its `LAUNCHER_TOKEN`.
The backend needs the matching token and `SIDECAR_LAUNCHER_URL`.

## Shared project storage

The backend's `GODOT_GAMES_DIR` and launcher's `BEVY_PROJECTS_ROOT` must refer to
the same games volume at the same absolute path. A project must be a direct,
non-symlink child with a valid game ID. Arbitrary temporary directories are
rejected. Docker Desktop volumes live inside its VM; a host directory with the
same name is not automatically the shared volume.

From a backend environment with that volume mounted, scaffold and build with:

```python
from pathlib import Path
from uuid import uuid4
from src.api.core.config import get_settings
from src.api.services.bevy_game_service import BevyGameService
from src.api.services.bevy_builder import BevyBuilder

settings = get_settings()
project = BevyGameService(settings).create_game(
    "bevy-check-" + uuid4().hex[:12], Path(settings.GODOT_GAMES_DIR)
)
dist = BevyBuilder().build(project)
print(dist)
```

Output is `dist/index.html`, the JavaScript module and its `_bg.wasm` file.
The binary artifact keeps the application crate name, including hyphens; the
HTML loader references that same module name.

## Version contract

- Bevy: `=0.18.1` with `webgl2`.
- Rust image: `1.89-slim-bookworm`.
- `wasm-bindgen` crate and CLI: exactly `0.2.121`.
- Binaryen: Debian Bookworm package (108 in the reviewed image).

The scaffold pins Bevy and wasm-bindgen. The TinyWorlds runtime overlay overrides
upstream's instruction to select the latest Bevy release. Do not update either
pin independently of the image and a real browser check.

The build first resolves/fetches dependencies, verifies the wasm-bindgen version,
and then compiles with `--locked`. A mismatching existing project gets an early
error. Update its Cargo.toml deliberately to the builder's version and allow
Cargo to resolve a matching lockfile; do not delete every project's lockfile.
Keep generated Cargo.lock files for reproducible subsequent builds.

Caches now live under each game's `.build-cache/cargo-home` and
`.build-cache/cargo-target` in the games volume. The older global cache-volume
instructions and old warm/cold timing estimates do not describe this launcher.

## Verification

Run from the configured backend environment with shared storage and installed
Playwright Chromium:

```bash
python -m pytest tests/e2e/test_bevy_builder.py -v -m slow --no-cov
```

This creates a uniquely named application scaffold, calls the real launcher,
checks matching artifact names and loads the WASM in a fresh browser. It
retains the generated project and trusted browser receipt for inspection.
A successful render is not a full game-generation or gameplay-quality test.
Allow several minutes for a cold build and use a separate games volume for tests.

The retained internal October 29 review records scaffold/build evidence, not
full provider-generated gameplay acceptance. Bevy remains outside v0.1's validated path.
