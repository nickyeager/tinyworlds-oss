# Built with other people's work

TinyWorlds brings existing generation skills, game engines and asset tools into
one application. Much of the craft in its generation workflow comes from the
projects below. Please explore, credit and support their maintainers.

This public distribution includes the pinned Godogen runtime, legacy Godogen
helpers and TinyWorlds' own runtime overlays. Historical optional skills and
research workflows credited below are **not bundled**: `godot-patterns`,
`csharp-patterns`, the Gemini image skill, `build-with-agent-team`,
`agent-browser`, and the Game Studios experiment. Their paths describe the
private development checkout, not files available in this release. Credit is
retained without redistributing material whose import provenance is unresolved.

## Skills at the heart of TinyWorlds

| Project and creators | What they contributed here | Where it lives and how it runs |
|---|---|---|
| [Godogen](https://github.com/htdt/godogen) — **Alex Ermolov / htdt** | Game-generation orchestration, engine guides, asset creation tools, and practical engine lessons | Active pinned source in `vendor/godogen-runtime/`; rendered into Claude Code or Codex workspaces with TinyWorlds' browser, isolation and budget constraints. [Exact pin](vendor/godogen-runtime/PROVENANCE.md). MIT. |
| [Agency Agents](https://github.com/msitarzewski/agency-agents) — **msitarzewski and contributors** | Godot/GDScript and shader guidance curated into the local Godot patterns reference | `.claude/skills/local/godot-patterns/SKILL.md`. Optional repository guidance, not automatically part of every generation job. MIT source; historical import revision needs recording. |
| [Game Dev Agentic Skills](https://github.com/thedivergentai/Game-Dev-Agentic-Skills) — **thedivergentai and contributors** | GDScript patterns credited as the source of the C# translation/curation | `.claude/skills/local/csharp-patterns/SKILL.md`. Retained optional reference, not the browser GDScript generation guide. Historical license unresolved; current upstream is LGPL-3.0. |
| [Antigravity / Agentic Awesome Skills](https://github.com/sickn33/agentic-awesome-skills) — **sickn33 and contributors** | The source collection credited by our optional Gemini image skill | `.agents/skills/antigravity-awesome-skills-gemini-3-pro-image/`, with a Claude skill symlink. Locally adapted; not a required runtime dependency. Current collection license is MIT; exact import revision needs recording. |

TinyWorlds adds application integration, the scoped paid-asset broker, game
ownership and lifecycle handling, browser verification, editing workflows and
its accumulated local lessons. Those additions do not make upstream work ours.
The older `.claude/skills/godogen/` subtree is retained for capture helpers and
unmigrated consumers; the active runtime is the separately pinned vendor copy.

The application now renders a concise contract with on-demand Godogen engine
guidance and budget-conditional asset instructions. Historical orchestration and
lesson files are preserved as sources, rather than automatically injected into
each job. Workspace engine references omit upstream capture instructions because
TinyWorlds performs that check separately. This adaptation does not change the
vendored files, their MIT license, or the credit due to Godogen's maintainers.

Additional repository workflows deserve credit too:

- [Context Engineering Intro](https://github.com/coleam00/context-engineering-intro/tree/38113371a1ac8d3f8ca1e586ec402e6d7c47370d/use-cases/build-with-agent-team)
  by **Cole Medin / coleam00 and contributors** contains the corresponding
  `build-with-agent-team` workflow. Our local version shares substantial text
  but is modified; the exact import revision is not established. The source
  project's MIT notice is retained. This development workflow is not part of
  every generated-game job.
- [agent-browser](https://github.com/vercel-labs/agent-browser) by **Vercel and
  contributors** provides the browser automation tool and published skill
  lineage reflected by `.claude/skills/agent-browser/`. Its source project is
  Apache-2.0. The precise origin/version of our old skill copy and its
  project-specific workflow reference still need matching; tool credit is not
  a claim that this local copy is byte-identical to today's upstream skill.

Older Copilot chat modes, instruction files and command templates also need
their import origins checked before release. Unknown provenance must not be
silently converted into a claim of TinyWorlds authorship.

## Engines and rendering foundations

- [Godot](https://godotengine.org/) and its contributors provide the engine,
  GDScript, scene system and web exporter.
- [Bevy](https://bevyengine.org/) and its contributors provide the Rust ECS game
  engine used by the alternative generation/build path.

## Application and development foundations

Thank you to the maintainers of [FastAPI](https://fastapi.tiangolo.com/),
[SQLAlchemy](https://www.sqlalchemy.org/), [Alembic](https://alembic.sqlalchemy.org/),
[Next.js](https://nextjs.org/), [React](https://react.dev/),
[Tailwind CSS](https://tailwindcss.com/), [Radix UI](https://www.radix-ui.com/),
[shadcn/ui](https://ui.shadcn.com/), [Lucide](https://lucide.dev/),
[Playwright](https://playwright.dev/), [pytest](https://pytest.org/),
[Vitest](https://vitest.dev/), and the many transitive dependencies they maintain.
Dependency manifests and lockfiles identify installed packages; each package's
own license remains authoritative. This page is a curated acknowledgment, not
a claim that a complete dependency/license inventory has been finished.

## Services and optional tools

The optional local agent dashboard uses [Arize Phoenix](https://github.com/Arize-ai/phoenix)
by Arize AI and contributors, with [OpenTelemetry](https://opentelemetry.io/) and
[OpenInference](https://github.com/Arize-ai/openinference) conventions. Phoenix is
a separately installed service under [Elastic License 2.0](https://github.com/Arize-ai/phoenix/blob/main/LICENSE),
not an MIT-licensed component of TinyWorlds. The OpenTelemetry Python SDK is
Apache-2.0. See [agent observability](docs/guides/agent-observability.md).

[Claude Code](https://claude.com/claude-code) and
[Codex](https://github.com/openai/codex) are interchangeable execution providers.
Optional asset/voice paths integrate xAI, Google Gemini and Azure Speech.
These are separate services
with their own access requirements, costs and terms, not bundled open-source
model licenses.

## Research credit is distinct from runtime dependency

[Claude Code Game Studios](https://github.com/Donchitos/Claude-Code-Game-Studios)
by **Donchitos and contributors** informed the bounded evaluation adaptation in
`experiments/skill-comparison/`. It is not installed as TinyWorlds' studio,
hooks or agent hierarchy. Its MIT license is retained alongside the experiment.

Godogen Assets, GodotPrompter, haxqer's Godot skill, awesome-gamedev-agent-skills,
Godot MCP and other candidates appear in research notes. Review or evaluation
alone does not make them application dependencies or establish improvement.
We evaluate optional skills against no-skill baselines and preserve negative,
inconclusive and unmeasured outcomes.

The retained internal October 29 review specifically
examines [haxqer/godot-skill](https://github.com/haxqer/godot-skill), credited to
**Qian Xiao and contributors** under MIT, and the Bevy ECS guidance in
[awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills),
whose reviewed repository carries Apache-2.0. Exact revisions and skill hashes
are recorded in the review. Neither package has been added to the generation runtime.

## Help keep credit accurate

If attribution, a source revision or a license is missing or wrong, please open
an issue with the affected path and upstream source. We want both the visible
credit and the redistribution notices to be accurate. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the current ledger.
