# End-to-end testing

Start with the [local checks](testing-quickstart.md). Passing route and unit
tests does not establish that a generated game exports, plays, or survives a
real edit in the browser.

## Editor browser checks

The current editor suite is
[`web/tests/e2e/game-editor.spec.ts`](../../web/tests/e2e/game-editor.spec.ts).
It checks draft recovery, image references, mobile layout, navigation, rename,
and visitor access. Two tests tagged `@generation` launch real edits.

Use a disposable local database and an isolated games directory. The backend's
`GODOT_GAMES_DIR` must match `GAME_EDITOR_TEST_GAMES_DIR`; the tests create and
delete fixture games and use anonymous sessions. Never target production.
Set `GAME_EDITOR_TEST_SOURCE` to an existing browser-exported Godot project
with `project.godot`, `dist/index.wasm`, `PLAN.md`, and a PNG in `screenshots/`.
The suite copies that project instead of generating a new game for every check.

With the backend on port 8001 and `pnpm dev` on port 3333, export these variables
in the shell running the checks:

```bash
export GAME_EDITOR_TEST_SOURCE=/absolute/path/to/exported-godot-project
export GAME_EDITOR_TEST_GAMES_DIR=/absolute/path/to/disposable/generated_games
cd web
pnpm qa:editor
```

The QA runner performs frontend tests, TypeScript, editor lint, and browser
checks excluding `@generation`. It requires the two servers to be running and
verifies that the frontend is a development server. Results are written under
`test_output/editor-qa/`.

```bash
pnpm qa:editor:watch
pnpm qa:editor:status
pnpm qa:editor:stop
```

The watcher reruns checks when its watched source files change. It does not fix
failures automatically. To include the real-edit tests, deliberately run:

```bash
pnpm qa:editor:full
```

That command invokes the configured generation provider and may spend inference
or asset credits. It is separate from routine background checks.

## Release acceptance

In a fresh checkout and database, create a small game, play it, request one
specific edit, refresh during editing, and verify the resulting playable export.
Check cancellation and mobile controls as well. Repeat for each engine/provider
combination advertised as supported. Record the commit, configuration, failures,
elapsed time, and actual provider usage; distinguish observed results from
unmeasured cases.

## Other live tests

Backend tests marked `e2e` or `integration` require explicit marker selection:

```bash
.venv/bin/python -m pytest tests/e2e/test_godot_e2e.py -m e2e -q
.venv/bin/python -m pytest tests/integration/azure/test_voice_transcription.py -m integration -q
```

Inspect each test's prerequisites before running. These suites can require live
servers, engine/export tools, the sidecar launcher, provider credentials, and
paid services. They are not part of the ordinary local baseline. The Azure
suite uses speech synthesis as well as transcription; see
the voice test suite under `tests/` (outside v0.1 acceptance).
