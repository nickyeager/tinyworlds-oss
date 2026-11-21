# Local development setup

TinyWorlds runs a FastAPI backend on port 8001 and a Next.js frontend on port
3333. This setup is for a developer's machine. For public hosting, use the worker
isolation and separate playback origin in [generation.md](generation.md).

## Prerequisites

- Python 3.12 and a virtual environment.
- Node.js 22 and pnpm 10 (the frontend records pnpm 10.18.0).
- Godot 4 with matching Web export templates and the `godot` executable on PATH.
  The component pilot uses Godot 4.6; the worker Dockerfile has its own explicit
  engine pin. Do not mix export templates from different engine versions.
- An installed Codex or Claude Code CLI. Connect your own account after opening the app.
- Docker for the optional Bevy builder and production-style workers.

## Configure and start the backend

From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c constraints-v0.1.txt
python -m playwright install chromium
cp .env.example .env
openssl rand -hex 32
```

Put the generated value in `.env` as `SECRET_KEY`. Keep `PERSONAL_MODE=true`
and `AGENT_EXECUTION_MODE=local` for this personal install. On first visit the
app opens `/connect`: choose Codex, then sign in with ChatGPT, supply an OpenAI
API key, or explicitly connect an existing local Codex login. Claude Code also
supports an API key or an existing official CLI login; its subscription sign-in
stays in `claude auth login`. Codex + Godot is the v0.1 acceptance target;
Claude remains experimental. See [provider connections](provider-connections.md).

Your provider connection belongs to this local installation and is separate
from the TinyWorlds account used to save games. CLI access and paid asset APIs
are separate credentials. Existing installations retain their environment-selected
provider unless they explicitly enable personal mode. For shared hosting, keep
personal mode disabled and follow [generation.md](generation.md).

The default database URL is `sqlite+aiosqlite:///./data/tinyworlds.db`.
Application startup initializes its schema on an empty development database:

```bash
mkdir -p data
uvicorn src.api.main:app --host 127.0.0.1 --port 8001
```

Avoid `--reload` while generating or editing a game: source changes can restart
the server and interrupt its background work. There is no default administrator
or shared password. Create a guest session or register your own account; set
`ADMIN_EMAILS` explicitly only if you need to bootstrap an administrator.

Do not delete an existing database to fix a migration error. Back it up, inspect
its Alembic revision and compare it with this checkout's migration files. A
revision from another branch may not exist here. Apply migrations only when
that history is understood; startup schema creation is not a substitute for
migrating an existing database.

## Start the frontend

In a second terminal, from the repository root:

```bash
cd web
pnpm install --frozen-lockfile
NEXT_PUBLIC_API_URL=http://localhost:8001 NEXT_PUBLIC_GAME_PLAY_URL=http://localhost:8001 pnpm dev --hostname 127.0.0.1
```

Open http://localhost:3333/create. The API reference is at
http://localhost:8001/docs and runtime capabilities are available at
http://localhost:8001/api/v1/games/capabilities. Use the application's account
flow for authenticated features. Keep frontend and game playback on separate
origins, including in local development.

## Optional features

- A zero asset budget uses procedural assets. Brokered images require an
  approved budget and configured trusted provider keys. Never pass raw keys
  into a generated game's workspace.
- [Bevy setup](setup-bevy.md) requires its Docker builder image. Selecting
  `DEFAULT_GAME_ENGINE=bevy` does not install that toolchain.
- Voice transcription requires Azure Speech configuration and ffmpeg.

## Check your change

```bash
source .venv/bin/activate
python -m pytest tests/unit/test_vendored_runtime.py tests/unit/test_game_asset_budget_contract.py -q
cd web
pnpm test:run
```

Run additional checks appropriate to the feature. Engine/provider integrations
need actual generation, export and browser tests. Record unavailable checks
explicitly rather than claiming success from a compile or file-existence check.

If a port is occupied, inspect its owning process and stop only a service you
started, or configure a different port consistently on backend and frontend.
For dependency conflicts, use a fresh environment matching the requirements;
do not assume an old environment's installed extras are part of the project.
