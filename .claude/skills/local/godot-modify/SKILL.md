---
name: godot-modify
description: |
  Modify an existing Godot game based on a natural language instruction. Use when the user wants to change, tweak, add, or fix something in an already-generated game.
context: fork
---

# Godot Game Modifier

Modify an existing Godot game project. The game already has working scripts, scenes, and a project.godot. Your job is to make the requested change without breaking what works.

## Reference images

If the user instruction contains "Reference image attached at: <path>", the user has uploaded a visual reference.

1. **`Read` the image first.** Your `Read` tool is multimodal — passing a PNG/JPG/WEBP path returns the image visually. Look at it before planning changes.
2. **For asset regeneration**, when calling `asset_gen.py image`, you may pass the reference path as `--input-image` to use image-to-image style transfer (xAI Grok supports this).
3. **For visual instructions** like "make it look like this", prioritize matching the reference's colors, shapes, and overall style.
4. The reference lives under `_user_uploads/` in the game dir. Don't move or modify it.

## Browser runtime references

Read the generated workspace's `godot.md` and its `AGENTS.md` or `CLAUDE.md`
manifest. These are the pinned engine guide and TinyWorlds runtime constraints.
This path targets Godot GDScript Web exports. Do not invoke omitted repository
skills, C# builders, or Mono/dotnet workflows. Consult the project's existing
`.gd` scripts and `.tscn` scenes for their actual structure.

## Modification Request

$ARGUMENTS

## Workflow

1. **Preflight context first** — before planning or editing, read `MEMORY.md`, `PLAN.md`, `STRUCTURE.md`, and `RUNTIME_DIAGNOSTICS.md` if they exist. Then read the scripts and scenes relevant to the requested change. Treat runtime diagnostics as evidence: if the request mentions a crash, freeze, broken input, or bad game flow, correlate the diagnosis with the relevant code path before editing. Understand the current mechanics, controls, and known constraints before changing anything.

2. **Plan the change** — identify which files need to change. Prefer minimal, surgical edits. Don't rewrite files that don't need to change.

3. **Make the changes**:
   - For **script changes** (`.gd`) — edit the existing file. Don't rewrite from scratch unless necessary.
   - For **scene changes** (`.tscn`) — edit the existing text scene or its actual project generator, preserving node paths and script references
   - For **new features** — add new scripts/nodes. Wire them into the existing scenes.
   - For **project settings** — edit `project.godot` directly.
   - Preserve existing working mechanics unless the user explicitly asks to change them.
   - Preserve mobile/touch controls, gestures, safe areas, and viewport behavior unless the user explicitly asks to remove or replace them.

4. **Validate** — run the engine-specific checks from the game directory:
   - `godot --headless --path . --editor --quit 2>&1`
   Fix validation errors before proceeding. If a required tool is unavailable, record the command and failure reason in `MEMORY.md` and the final response.

5. **Re-export if needed** — if the game has a `dist/` folder (WebAssembly export), the export will be handled by the caller. Focus on getting the Godot project correct.

6. **Browser verification** — the application verifies and captures the exported game after the agent finishes. Report this as pending; do not launch a browser, video capture, or a preview server inside the worker.

7. **Update MEMORY.md** — append a concise entry with the user instruction, changed files, and validation result. Keep it factual and short:
   - `Instruction: ...`
   - `Changed files: ...`
   - `Validation: Godot import/parse ..., export ..., browser verification pending`

8. **Final response** — emit a structured summary with:
   - `Changed files`
   - `Key changes`
   - `Validation outcome`

## Rules

- **Don't re-scaffold.** The game structure exists. Work within it.
- **Don't rewrite PLAN.md or STRUCTURE.md** unless the user explicitly asks for architectural changes.
- **Preserve what works.** If the ball bounces correctly, don't touch ball physics unless asked. If touch controls work, keep them working.
- **Don't revert unrelated changes.** Other work may be present in the game directory.
- **Commit after success:** `git add -A && git commit -m "modify: <short description>"`
