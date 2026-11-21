# TinyWorlds

TinyWorlds is a web app you run on your own machine. You describe a small game,
play it in your browser and ask for changes. It uses
[Codex](https://github.com/openai/codex) and the
[Godogen](https://github.com/htdt/godogen) runtime to build a small Godot game
from your description, and saves the Godot project on your computer.

**Status: v0.1 open-source developer preview.** You need your own Codex
account; this is not a free hosted service. Check generated code and gameplay
before you rely on them.

## Quick start

You need Python 3.12, Node.js 22, pnpm 10, Godot 4 with matching Web export
templates (`godot` on your PATH), and the Codex CLI.

```bash
git clone https://github.com/nickyeager/tinyworlds-oss.git
cd tinyworlds-oss
```

Backend, from the repository root (runs on http://localhost:8001):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c constraints-v0.1.txt
python -m playwright install chromium
cp .env.example .env
openssl rand -hex 32   # put this value in .env as SECRET_KEY
mkdir -p data
uvicorn src.api.main:app --host 127.0.0.1 --port 8001
```

Frontend, in a second terminal (runs on http://localhost:3333):

```bash
cd web
pnpm install --frozen-lockfile
NEXT_PUBLIC_API_URL=http://localhost:8001 NEXT_PUBLIC_GAME_PLAY_URL=http://localhost:8001 pnpm dev --hostname 127.0.0.1
```

Open http://localhost:3333/create. The first visit asks you to
[connect your own AI](docs/guides/provider-connections.md): pick Codex, then
sign in with ChatGPT or enter an OpenAI API key. Then describe a game.

Stuck? See the full [setup guide](docs/guides/setup.md).

## What works

| Path | v0.1 status |
| --- | --- |
| Codex + Godot on your machine: create, play, edit | The supported path. Create and edit tested on a fresh install. |
| Claude Code, Bevy, voice, agent play | Experimental. Not tested for v0.1. |
| Hosting it for other people | Not covered by the quick start. Read the [generation guide](docs/guides/generation.md) first. |

Tested on macOS arm64. Games use code-drawn art unless you set up a paid asset
budget and keys. [tinyworlds.us](https://tinyworlds.us) is a separate deployment and may
not match this code. Details: [release scope](docs/releases/v0.1-developer-preview.md).

## How it works

1. You describe a game in the web app.
2. The backend starts Codex (or Claude Code) with the pinned Godogen
   instructions in a folder for that game.
3. The agent writes a Godot project in `generated_games/`.
4. Godot exports it for the web and a browser check loads it.
5. You play it, then ask for changes.

`GAME_AGENT_PROVIDER` picks the agent (`codex` or `claude`) and
`DEFAULT_GAME_ENGINE` picks the engine (`godot` or `bevy`). Both are set in
`.env`.

## Learn more

- [Setup](docs/guides/setup.md): full install, database, checks
- [Generation](docs/guides/generation.md): how jobs run, isolation, budgets, hosting
- [Provider connections](docs/guides/provider-connections.md): Codex and Claude sign-in
- [Bevy setup](docs/guides/setup-bevy.md): experimental, needs Docker
- [Agent play](docs/guides/agent-play.md): experimental human-and-agent game at `/agent-play`
- [Tracing](docs/guides/agent-observability.md): optional Phoenix dashboard, separate install and license
- [Roadmap](docs/ROADMAP.md) and [release checklist](docs/open-source-readiness.md)
- API reference: http://localhost:8001/docs while the backend is running

## Credits

Thank you to **Alex Ermolov / htdt** for Godogen, and the maintainers of Godot,
Bevy and the skill collections this project learned
from.
[ATTRIBUTION.md](ATTRIBUTION.md) says what each one contributes.

## Contributing and security

Start with [CONTRIBUTING.md](CONTRIBUTING.md). To report a security problem,
follow [SECURITY.md](SECURITY.md); do not put details in a public issue.

## License

Original code: [Apache-2.0](LICENSE). Original documentation: [CC BY 4.0](LICENSE-DOCS).
Third-party material keeps its own terms. See [LICENSING.md](LICENSING.md) for
scope and exceptions and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for
upstream licenses and open provenance issues. Generated assets and hosted
service access are not covered by these grants.
