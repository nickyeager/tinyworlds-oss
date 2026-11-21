# Third-party notices and provenance

The root license does not relicense these sources. Preserve their notices when
redistributing them. Current license snapshots and their exact revisions/hashes
are recorded in [LICENSES/upstream-license-sources.json](LICENSES/upstream-license-sources.json).

**Public release boundary:** optional skills and development workflows with
unresolved provenance in the ledger below are excluded from this distribution.
Their blockers apply to redistributing those files, not to the included source.
See [distribution scope](RELEASE_SCOPE.md). License texts are retained as credit
and historical reference. Python/npm installations, engine binaries, images,
model weights and generated assets are not bundled. The eleven dependency
notice-collection gaps described below remain disclosed; a binary or container
distribution requires a separate notice review.

| Component / local scope | Source revision | License notice | Status |
|---|---|---|---|
| Fredoka, Nunito and Geist Mono fonts: `web/src/app/fonts/` | Google Fonts `bbda7253fc363238b05d97515ca71f8ae49c4fa9`; individual paths and hashes in `web/src/app/fonts/sources.json` | Each family's original `*-OFL.txt` alongside the font | Unmodified font files; served locally without build-time Google Fonts requests |
| Chat primitives: `@assistant-ui/react` | npm `0.15.32`; resolved dependencies in `web/pnpm-lock.yaml` | [MIT, AgentbaseAI Inc.](LICENSES/assistant-ui-MIT.txt) | Used as a package; TinyWorlds supplies its own backend adapter and presentation |
| Active Godogen: `vendor/godogen-runtime/` | `40542b6c8efbdc40112c2b004fbaa6d67141846d` | [MIT, Alex Ermolov](vendor/godogen-runtime/LICENSE.md) | Source manifest retained; app changes are separate overlays |
| Legacy Godogen: `.claude/skills/godogen/` | `51954f9f34d18044c501a09c0645ff0e680edbdf`; all 87 source files matched Git blob hashes on 2026-11-04 | [MIT](.claude/skills/godogen/LICENSE.md) | Capture/legacy consumers remain; not a second current runtime |
| Local `godot-patterns` skill | Agency Agents; exact imported revision unknown | [Current MIT notice](LICENSES/agency-agents-MIT.txt) | Historical content/notice matching pending |
| Local `csharp-patterns` skill | gd-agentic-skills, now Game-Dev-Agentic-Skills; exact source revision unknown | [Current upstream LGPL-3.0 snapshot](LICENSES/gd-agentic-skills-LGPL-3.0.txt) | **Release blocker:** upstream relicensed March 19, 2026; local MIT claim not established. Trace source/permission and fulfill applicable notices before distribution |
| Optional Gemini image skill | antigravity-awesome-skills, now agentic-awesome-skills; exact source revision unknown | [Current MIT notice](LICENSES/antigravity-awesome-skills-MIT.txt) | Locally edited; historical import provenance pending |
| Game Studios evaluation adaptation | `05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418` | [MIT notice](LICENSES/game-studios-MIT.txt) | Experiment only; adapted guidance, not full package |
| `build-with-agent-team` development skill | Corresponding Context Engineering Intro source `38113371a1ac8d3f8ca1e586ec402e6d7c47370d`; exact import revision unknown | [MIT notice](LICENSES/context-engineering-intro-MIT.txt) | Substantial corresponding text; local version modified |
| `agent-browser` development skill | Vercel agent-browser lineage; exact local source/revision unknown | [Upstream Apache-2.0](LICENSES/agent-browser-Apache-2.0.txt) | Match the historical skill and its workflow reference before distribution |

Older `.github/chatmodes/`, `.github/instructions/` and command templates require
source-provenance review too. The original-work license does not grant rights to
unidentified third-party content. No workflow was removed or enabled during this audit.

The current gd-agentic-skills license is LGPLv3, which incorporates GPLv3
terms; the [GPLv3 text](LICENSES/GPL-3.0.txt) is included for reference too.
Keeping these texts does not resolve the uncertain source revision by itself.

Installed Python, JavaScript, Rust, engine, system and container dependencies
retain their own licenses. Produce and review a dependency inventory from the
actual release lockfiles/container versions before publishing an artifact.
Downloaded model weights and generated assets need their own rights review.

The November 4 source candidate has a [resolved dependency inventory](LICENSES/dependency-inventory-20261104.json)
and [collected dependency license texts](LICENSES/DEPENDENCY_NOTICES-20261104.txt).
These cover the fresh macOS API, separate plugin environment and frozen frontend
install, including development packages. Missing notices are explicit. This is
not a Linux image SBOM or a redistribution review of container/system dependencies.

The [November 8 follow-up inventory](LICENSES/dependency-inventory-20261108.json)
collects 13 of the 26 previously missing notices and preserves original source
bytes under `LICENSES/collected-20261108/`. Keep the November 4 bundle and the
[additional November 8 bundle](LICENSES/DEPENDENCY_NOTICES-20261108.txt) together.
The [follow-up report](docs/releases/2026-11-08-notice-inventory.md) identifies
the 13 remaining complete-notice gaps and the scope of verification.

No endorsement by the credited maintainers is implied. License snapshots are
not evidence of a skill's effectiveness. See [ATTRIBUTION.md](ATTRIBUTION.md)
for the human-readable project showcase and [LICENSING.md](LICENSING.md) for
the original-work license scope.

The [November 9 inventory](LICENSES/dependency-inventory-20261109.json) records
770 entries from the newly installed API, optional OTLP exporter and frozen
frontend environments. Its [notice bundle](LICENSES/DEPENDENCY_NOTICES-20261109.txt)
supplements the retained November 4/8 bundles; version-matched recovered notices
are explicitly carried forward. Thirteen collection gaps remain. The earlier
inventory still covers the separately installed plugin environment. This is a
source-only candidate, not a redistribution of those installed dependencies.

The [November 13 inventory](LICENSES/dependency-inventory-20261113.json) adds
two collected texts under `LICENSES/collected-20261113/`. Eleven collection gaps
remain; each of those packages declares its licence but publishes no licence
file for that version. See the [November 13 report](docs/releases/2026-11-13-source-candidate.md).
