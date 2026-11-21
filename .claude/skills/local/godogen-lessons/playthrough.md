# Playthrough lessons

Render / export / runtime issues spotted only at play time. Append-only,
one-bullet-per-rule, no edits to prior bullets.

- **`telemetry: frozen_thread` from a backgrounded tab is a false positive — gate the watchdog on `document.visibilityState`, and reset the drift baseline on unhide.**
  (why: 2026-06-06 godot-73154077 emitted one `frozen_thread drift≈59000ms` event per minute for over an hour despite the WASM thread being healthy. Browsers clamp `setInterval` and pause RAF in hidden tabs, so the next tick after unhide sees `Date.now() - lastTick ≈ tabHiddenMs` and the watchdog reads it as a 59-second freeze. ~2,000 prior false-positives are sitting in `data/godogen_failures.jsonl`; future analyses should `WHERE rule != 'frozen_thread' OR ts < 2026-06-06`. The fix landed in the shared `_TELEMETRY_SHIM` in `src/api/routes/{godot,bevy}_games.py`.)

- **`telemetry: godot_print_err` for `still waiting on run dependencies` / `dependency: …` / `(end of list)` is a false positive — these are Godot's HTML5 loader status lines routed through `printErr`, not errors.**
  (why: 2026-06-06 the failure corpus had 1,942 godot_print_err rows out of 2,505 total; sampling 5 of them returned only WASM bootstrap status. Together with frozen_thread false positives this accounted for 100% of the corpus — the failure log was capturing zero real failures. Server-side allowlist landed in `src/api/routes/godot_games.py` `submit_telemetry`. When auditing corpus trends, treat any pre-2026-06-06 godot_print_err row as suspect.)
