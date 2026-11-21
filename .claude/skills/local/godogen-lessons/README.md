# Godogen Lessons

Append-only project memory for the godogen pipeline. Bucketed by stage so each
generation only loads the lessons relevant to the work it's doing — keeps
context bounded as the corpus grows.

## Buckets

| File | Loaded during |
|------|---------------|
| `scaffold.md` | Decomposition, project skeleton, architecture choices |
| `scripts.md`  | Writing C# / GDScript (task execution) |
| `scenes.md`   | `.tscn` scene authoring |
| `assets.md`   | Asset planning + generation (xAI, Tripo3D) |
| `capture.md`  | Screenshots, video, final-result bundle |
| `bevy.md`     | Bevy-specific quirks (type API, wasm-opt features, web export, runtime size) — load on every Bevy-engine generation |
| `general.md`  | Cross-cutting (build, export, quirks not tied to a stage or engine) |

`bevy.md` and `general.md` are usually loaded together for Bevy work. Godot work loads only the Godot-relevant buckets plus `general.md`.

## Format

One lesson per bullet. Lead with the rule, follow with a `(why: …)` clause so
future readers (and the compaction pass) can judge whether it still applies.

```markdown
- Always set `Camera2D.zoom = Vector2(2, 2)` for top-down 320x180 scenes.
  (why: default zoom showed too much empty space; visual-QA failed on 3 games)
```

## When to add a lesson

After a generation fails or produces a low-quality result, distill the fix into
**one bullet** in the right bucket. If you can't write the lesson in one bullet,
it probably belongs in the skill itself, not here.

## When NOT to add a lesson

- One-off bugs that won't recur.
- Anything already covered in the godogen skill or `quirks.md`.
- Speculation about what *might* help — only proven fixes.

## Compaction

When any bucket exceeds ~50 lines, run a dedupe pass and drop lessons that
haven't fired in recent generations. Raw history stays in git.
