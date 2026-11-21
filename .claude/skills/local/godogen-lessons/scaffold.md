# Scaffold lessons

Decomposition, project skeleton, architecture choices.

- Default to GDScript for new projects unless the prompt explicitly asks for C#.
  (why: 2026-05-04 godot-43e9a53b started in C#, hit `No loader found for resource: res://scenes/BuildMain.cs`, pivoted to GDScript mid-pipeline, then declared `complete` *after deleting the C# scaffolding without writing replacement GDScript* — produced an empty project that "exported successfully" but had no scenes or scripts. Starting in GDScript would have avoided the pivot entirely.)
- After ANY mid-pipeline pivot (C#→GDScript or similar), do NOT emit `CompletionEvent` until you have re-verified on disk: `scenes/<main>.tscn` exists and has nodes, at least one non-`pause_bridge.gd` script exists in `scripts/` with `func _process` or `func _physics_process` AND a call into `Input.*`, and `godot --headless --quit` returns 0.
  (why: same C#→GDScript pivot bug — the agent reported "complete" 6 seconds after deleting C# files without re-scaffolding. Server-side `verify_playable` correctly rejected this on disk; emitting `complete` over SSE before that check now produces a user-visible `failed` event instead of `done`.)
- For projects that need C# specifically, verify `dotnet --version` works AND `Godot.NET.Sdk` is reachable BEFORE declaring scaffold complete.
  (why: when dotnet/SDK is unavailable, the C# build silently leaves an unloadable project and the only way out is the pivot above.)
