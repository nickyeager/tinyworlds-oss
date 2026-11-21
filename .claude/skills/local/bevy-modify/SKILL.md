---
name: bevy-modify
description: |
  Modify an existing Bevy game based on a natural language instruction. Use when the user wants to change, tweak, add, or fix something in an already-generated game.
context: fork
---

# Bevy Game Modifier

Modify an existing Bevy 0.18 game project. The game already has working systems, components, and a Cargo.toml that compiles cleanly under the `bevy-builder` docker image. Your job is to make the requested change without breaking what works.

## Reference images

If the user instruction contains "Reference image attached at: <path>", the user has uploaded a visual reference.

1. **`Read` the image first.** Your `Read` tool is multimodal — passing a PNG/JPG/WEBP path returns the image visually. Look at it before planning changes.
2. **For asset regeneration**, when calling `asset_gen.py image`, you may pass the reference path as `--input-image` to use image-to-image style transfer (xAI Grok supports this).
3. **For visual instructions** like "make it look like this", prioritize matching the reference's colors, shapes, and overall style.
4. The reference lives under `_user_uploads/` in the game dir. Don't move or modify it.

Reference files live in `${CLAUDE_SKILL_DIR}/../../godogen/bevy/skills/godogen/`. Load progressively:

| File | Purpose | When to read |
|------|---------|--------------|
| `quirks.md` | Known Bevy 0.18 / WASM gotchas | Before writing any code |
| `scaffold.md` | Crate layout + dependency conventions | Adding new modules |
| `task-execution.md` | How tasks are committed incrementally | Multi-step changes |
| `capture.md` | Screenshot/video capture for verification | After changes validated |

For Bevy API reference, use `Skill(skill="bevy-help")` to look up specific Bevy types.

## Modification Request

$ARGUMENTS

## Workflow

1. **Preflight context first** — before planning or editing, read `MEMORY.md`, `PLAN.md`, `STRUCTURE.md`, and `RUNTIME_DIAGNOSTICS.md` if they exist. Then read the Rust modules relevant to the requested change. Treat runtime diagnostics as evidence: if the request mentions a crash, freeze, broken input, or bad game flow, correlate the diagnosis with the relevant code path before editing. Understand the current mechanics, controls, and known constraints before changing anything.

2. **Plan the change** — identify which files need to change. Prefer minimal, surgical edits. Don't rewrite files that don't need to change.

3. **Make the changes**:
   - For **system changes** — edit the existing module under `src/`. Don't rewrite from scratch unless necessary.
   - For **new components/resources** — add them to the closest topical module, or a new module wired into `main.rs`.
   - For **dependency changes** — edit `Cargo.toml`. Stay on Bevy 0.18.x and only the features the bevy-builder image supports (`webgl2`).
   - For **assets** — drop into `assets/` and load via `AssetServer` like the existing code does.
   - Preserve existing working mechanics unless the user explicitly asks to change them.
   - Preserve mobile/touch controls, gestures, safe areas, and viewport behavior unless the user explicitly asks to remove or replace them.

4. **Validate** — the host has no Rust toolchain. Run the engine-specific Docker build from the game directory:
   - `docker run --rm -v "$(pwd):/project" -v tinyworlds_cargo-cache:/cargo-home -v tinyworlds_cargo-target:/cargo-target tinyworlds/bevy-builder:dev bevy_build /project`
   Fix validation errors before proceeding. If Docker or the builder image is unavailable, record the command and failure reason in `MEMORY.md` and the final response.

5. **Re-export if needed** — the Docker build updates `dist/`. The caller may still handle publishing or iframe reloads after the skill returns.

6. **Update presentation video** — if a presentation script exists in `test/`, update it to reflect the changes, then re-capture using the `capture.md` workflow.

7. **Update MEMORY.md** — append a concise entry with the user instruction, changed files, and validation result. Keep it factual and short:
   - `Instruction: ...`
   - `Changed files: ...`
   - `Validation: bevy_build ...`

8. **Final response** — emit a structured summary with:
   - `Changed files`
   - `Key changes`
   - `Validation outcome`

## Rules

- **Don't re-scaffold.** The game structure exists. Work within it.
- **Don't rewrite PLAN.md or STRUCTURE.md** unless the user explicitly asks for architectural changes.
- **Preserve what works.** If the player movement is correct, don't touch movement systems unless asked. If touch controls work, keep them working.
- **Don't revert unrelated changes.** Other work may be present in the game directory.
- **Stay on Bevy 0.18.1 + `webgl2`.** That's what `bevy-builder` is pinned to.
- **Commit after success:** `git add -A && git commit -m "modify: <short description>"`
