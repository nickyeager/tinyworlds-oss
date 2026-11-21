# Vendored Godogen runtime

Source: https://github.com/htdt/godogen

Immutable upstream commit: `40542b6c8efbdc40112c2b004fbaa6d67141846d`.
Retrieved 2026-10-27. The prompts, engines, asset-gen and scripts directories,
publish script and MIT license are preserved verbatim. SHA256SUMS.json records
these source bytes. Application constraints and the broker asset tool are
rendered by `src/api/services/executors/runtime.py`, not edits to upstream.

TinyWorlds maps its `godot` engine to `engines/godot-gdscript.md` and keeps
`bevy` on `engines/bevy.md`. The additional upstream engine guides are source
references, not enabled application engines. The upstream local GPU pipeline,
direct paid API skill, and audio generation are not provisioned in game
sandboxes. Images continue through the trusted, budget-limited broker; its
trusted launcher uses the upstream asset CLI. No upstream setup script runs.
