# Generation providers and isolation

`GAME_AGENT_PROVIDER=claude|codex` selects the generation CLI (default `claude`). `DEFAULT_GAME_ENGINE=godot|bevy` selects the engine independently. The frontend posts to `/api/v1/games`; the initialization event identifies both engine and provider. Creation events persist in the game's event log, and reconnects attach to the engine's `/games/{id}/events/stream?since=N` endpoint without starting another job.

`GET /api/v1/games/capabilities` reports the configured provider, execution mode, engines and pinned upstream revision. This describes configuration; it does not prove provider authentication or paid API readiness.

## Choosing a model

Leave `CLAUDE_CLI_MODEL` and `CODEX_CLI_MODEL` blank to use each CLI's default model. To pick one, set the name the CLI accepts for `--model`, for example `CLAUDE_CLI_MODEL=opus` or a full model ID. TinyWorlds does not keep a list of models: the name is passed straight to the CLI, so a new model works once the installed CLI supports it.

To use a model that came out after your CLI:

- Local: update the CLI (`claude update`, or `npm install -g @openai/codex`).
- Worker image: raise `CLAUDE_CODE_VERSION` or `CODEX_VERSION` in `Dockerfile.agent`, rebuild, and run `scripts/verify_agent_worker.py`.

Both paths build their command line in `src/api/services/agent_commands.py`.

## Local development

`AGENT_EXECUTION_MODE=local` preserves host development. CLI execution starts in the game's directory with a minimal environment and provider sandboxing. Codex workspace sandboxing restricts writes; local development still trusts the operator's machine and permits host reads. Use the isolated worker for untrusted prompts requiring a read boundary. It fails closed when the required isolation is unavailable. Authenticate the configured CLI through its official login flow before generation. Application signing/database/mail credentials and asset API keys are never copied into the generation subprocess.

Godogen source is pinned under `vendor/godogen-runtime`; its revision is reported
by capabilities. Generated workspaces receive one application contract in
`CLAUDE.md` or `AGENTS.md`, plus an on-demand engine reference. The model's
selected name passes through to its CLI; this path does not add model-specific
prompt recipes or require a new model allowlist.

Zero-budget jobs receive no optional skill definitions. With a paid budget,
`asset-gen` provides the broker commands and asset-specific guidance. Budget
enforcement, credential isolation, export requirements and the Pip protocol stay
in the application contract. The broker tool still rejects unauthorized calls
independently of the instructions.

The edit skill, automatic lesson preamble and copies of the complete application
contract inside skills are no longer loaded. Existing project notes are linked
when already on disk instead of copied into the prompt. Relevant Godogen engine
guidance remains available on demand; its capture section is omitted from the
workspace copy because browser verification belongs to the application.
Vendored source and its licenses remain unchanged.

Old generated skill directories in workspaces with recognized TinyWorlds runtime
provenance are moved to `.tinyworlds-context-archive/` before replacement. That
directory is outside skill discovery and is never linked into the active
instructions. Original lesson sources and experiment records remain in the
repository. Their removal from default context is scoped to this user-requested
simplification, not a claim that all optional skills are ineffective. Restore an
earlier application tag for the old rendering behavior; retain archive contents
if historical workspace instructions are needed for diagnosis.

The October 27 update pins Godogen `40542b6c8efbdc40112c2b004fbaa6d67141846d`.
Godot now uses upstream's GDScript guide (rendered as `godot.md`); Bevy uses
its existing guide. `vendor/godogen-runtime/SHA256SUMS.json` records the
unaltered upstream source. The full upstream asset CLI runs only in the
trusted launcher; agent workspaces receive the budget broker and applicable
image planning/review guidance. The SDK minimums in `requirements.txt` match
this CLI. The vendored Three.js guide does not enable a third application
engine. Local GPU assets, audio, video and direct paid API calls remain
unprovisioned in the application runtime.

The create page exposes an asset budget in cents, defaulting to zero. Zero denies paid asset calls. The trusted broker reserves the maximum estimated charge atomically before making a request; repeated and concurrent requests share the job cap. Only its supported fixed image operation is accepted. CLI usage and other application workflows are separate from this asset cap.

## Isolated production workers

Production Compose sets `AGENT_EXECUTION_MODE=worker` and requires explicit `LAUNCHER_TOKEN`, `SECRET_KEY`, and `POSTGRES_PASSWORD`. Set unique secrets in the server environment or `.env` (signing and launcher secrets at least 32 characters, database password at least 16); the production launcher rejects the known development launcher token. Keep the current database password for an existing installation until an operator has deliberately rotated it. Never print `docker compose config` with values; use `config --quiet` for validation.

For the default generated database URL, use a strong URL-safe password containing only letters, digits, `_` and `-`. If the password contains URL-reserved characters, set `DATABASE_URL` explicitly with a percent-encoded password matching `POSTGRES_PASSWORD`. Existing PostgreSQL volumes keep their original role password: changing the environment variable alone does not rotate it. An operator must run `ALTER ROLE tinyworlds WITH PASSWORD ...` through a secure database session, then update both application connection configuration and `POSTGRES_PASSWORD` together. Do not run a rotation automatically during deployment.

Build the images before starting the application:

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile agents build agent-worker
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile bevy build bevy-builder
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The launcher starts with plain `up`; the `agents` profile provides the worker build recipe only. The launcher creates a non-root container per job using `tinyworlds/agent-worker:dev`, with only that game's subdirectory writable. Workers have no application/config/database mounts or Docker socket. Docker Engine API 1.45 or later is required for named-volume subpaths. Workers use the explicitly named `tinyworlds_agents` Docker network, with the launcher attached to both this network and the application network `tinyworlds_default`. The backend and database are attached only to the application network. Workers retain provider internet access; their internal network exposes only the broker. The games volume is `tinyworlds_games`.

Provider login files live in the dedicated `tinyworlds_agent-auth` volume, mounted read-only at `/agent-auth` on the launcher. Provision only the selected provider's official credentials:

- Claude: `claude/.credentials.json`.
- Codex: `codex/auth.json`.

Credential files must be owned by UID 1000 and readable by that worker (mode `0400`); provider directories must be searchable (mode `0755`). The fixed worker entrypoint copies only the required login file into its temporary home. Do not copy personal hooks, MCP configuration, API keys, application `.env`, or the entire home directory into this volume. Backend local-Claude authentication remains in its existing separate volume.

The trusted launcher receives the asset provider keys explicitly. Existing trusted backend asset workflows retain their own configuration. Workers receive only a per-job broker capability, never the upstream asset keys or launcher secret. `ASSET_BUDGET_ROOT=/app/trusted/asset-budget` persists reservations in a separate volume. Trusted ownership and verification records persist at `/app/data/game-metadata`, outside the agent workspace.

Backend port 8001 and frontend port 3333 bind only to `127.0.0.1`. Caddy remains the public entry point in production. The launcher port is loopback-only for host development and uses the internal Compose network in production.

## Readiness and deployment

The authenticated launcher `/capabilities` endpoint returns `ready` and checks provider auth, trusted asset runtime, game directory, Docker API, worker image, games/auth volumes, and network. Checks do not generate assets or invoke paid APIs. Verify it without echoing credentials:

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend python -c 'import os, json, urllib.request; req = urllib.request.Request("http://sidecar-launcher:8500/capabilities", headers={"X-Launcher-Token": os.environ["LAUNCHER_TOKEN"]}); result = json.load(urllib.request.urlopen(req, timeout=30)); assert result["ready"], "generation launcher prerequisites unavailable"'
curl -fsS http://localhost:8001/health
curl -fsS http://localhost:8001/api/v1/games/capabilities
```

Deploy runs the reusable CI workflow first, including backend checks, frontend build, Compose validation and the agent image build. Deployment checks out the exact validated `github.sha`, builds profile-gated images explicitly, starts services, and verifies backend/frontend/launcher readiness. Deployment is not a substitute for a local browser verification of a real generated build.

## Ownership and playback

New games receive trusted owner and visibility records. Public basic metadata and playback remain available to viewers; source, history, logs and mutations require owner or administrator access. Private gameplay also requires that access. The frontend uses authenticated reads and browser asset URLs, hides editing controls when `can_edit` is false, and uses the playback credential exchange for relative iframe assets.

Legacy games without a trusted owner remain publicly playable and cannot be edited by arbitrary authenticated users. Use the explicit operator migration before assigning existing games: prepare a JSON object mapping game IDs to known owner UUIDs, run `python scripts/assign_game_owners.py owners.json`, inspect its default dry-run report, then run `python scripts/assign_game_owners.py owners.json --apply` only after checking the assignments. Never infer ownership from an agent-written project file or guess owners. Keep both the games and metadata volumes when moving or restoring an installation. Browser verification is tied to artifact hashes; changing the build requires fresh verification.

## Provider login provisioning

Create the dedicated volume and provider directories without copying application secrets:

```sh
docker volume create tinyworlds_agent-auth
docker run --rm --user 0 --entrypoint sh -v tinyworlds_agent-auth:/auth tinyworlds/agent-worker:dev -c 'mkdir -p /auth/claude /auth/codex; chown -R 1000:1000 /auth; chmod 755 /auth /auth/claude /auth/codex'
# Choose the configured provider's official interactive login:
docker run --rm -it --entrypoint claude -e CLAUDE_CONFIG_DIR=/auth/claude -v tinyworlds_agent-auth:/auth tinyworlds/agent-worker:dev auth login
docker run --rm -it --entrypoint codex -e CODEX_HOME=/auth/codex -v tinyworlds_agent-auth:/auth tinyworlds/agent-worker:dev login --device-auth
```

Check launcher readiness after login. Workers use ephemeral copies of authentication; renew the trusted login through these commands when needed. Do not use the agent to administer credentials. On macOS local Claude authentication is copied from the official Keychain item into a temporary, private CLI configuration; global hooks and MCP settings are excluded.

The browser smoke test exercises keyboard, pointer, and touch, rejects runtime errors and blank canvases, and saves an artifact hash and screenshot outside the project. It does not prove that game rules, difficulty, or every interaction are correct. The creation/modification pipeline runs this test against each current export rather than trusting an agent's claimed completion. The local overlay tells the agent to finish after export; browser verification belongs to this trusted pipeline because provider sandboxes cannot reliably launch browsers. Cancel a background run through `POST /api/v1/games/{id}/cancel`; cancellation and server shutdown dispose its CLI/worker and persist an interruption event.

Production Godot export also runs in a fixed non-root worker, with no network or provider credentials, so generated editor/tool scripts cannot execute in the backend's secret-bearing process. Bevy builds mount the named volume's game subpath rather than a path from the launcher's filesystem; dependency/target caches are per game to prevent cross-game cache writes.

## Isolated browser playback

Before production deployment, create a DNS record for `games.tinyworlds.us` pointing at the application server and allow Caddy to obtain its TLS certificate. Production `GAME_PLAY_ORIGIN` and the frontend `NEXT_PUBLIC_GAME_PLAY_URL` point there. The playback host proxies only game runtime/telemetry routes; application API routes remain on `tinyworlds.us`. Old application-origin playback URLs redirect to the isolated origin. Never set the production playback origin equal to the frontend origin: generated HTML must not have access to the parent's login storage. If changing domains, update Caddy, both origin settings and the frontend image build argument together.

Local development already uses separate origins: frontend `localhost:3333` and backend playback `localhost:8001`. The iframe allows game scripts and pointer lock while prohibiting parent navigation. Private playback exchanges the URL credential for a short HttpOnly cookie scoped to that game's path, and its relative runtime assets load with that cookie.
