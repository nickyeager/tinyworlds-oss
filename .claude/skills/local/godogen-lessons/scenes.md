# Scenes lessons

`.tscn` scene authoring.

- A scene can be tiny (under 500 bytes) when gameplay logic lives in an attached script — that's a legitimate, often preferable, pattern.
  (why: 2026-05-04 a 486-byte `main.tscn` with a 36-line `player.gd` was a fully playable input-driven game. An earlier validator gated on scene size and false-failed it; the rule was removed. Don't pad scenes with placeholder nodes to hit a byte threshold — attach a real script instead.)
- Two `ColorRect` nodes alone (background + sprite) WITHOUT an attached script that handles input + state is a static image, not a game. The server-side validator rejects this.
  (why: 2026-05-04 godot-b9dcb519 followed "a single red square sitting still on a black background" literally — produced exactly that, but it's not playable. When the prompt sounds passive, you still need to attach an interaction script. If the user really wants a static image, they'd ask for one.)
- Use `build_main.gd` (or any `extends SceneTree` script) to compose scenes programmatically when the scene has more than ~5 interactive nodes. Pack with `PackedScene.new().pack(root)` then `ResourceSaver.save(packed, "res://scenes/main.tscn")`.
  (why: pattern used by the project's existing Neon Pong + Square Jumper. Keeps scene composition deterministic and re-buildable; avoids hand-editing dense `.tscn` syntax.)
