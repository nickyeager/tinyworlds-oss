# Bevy lessons

Cross-cutting lessons specific to the Bevy engine path. Load alongside `general.md` when generating or modifying Bevy games. Most quirks here are toolchain or web-export specific — Bevy 0.18 + wasm-bindgen 0.2.121 + binaryen.

## Type system & API

- **`WindowResolution::from` in Bevy 0.18 takes `(u32, u32)`, not `(f32, f32)`.** Cast literals explicitly: `resolution: (WIDTH as u32, HEIGHT as u32).into()`. Same constraint applies to `[u32; 2]` and `UVec2`. If your `WINDOW_W`/`WINDOW_H` constants are `f32` (typical for use elsewhere as Bevy coords), do the cast at the point of construction, not at the constant declaration.
  (why: Breakout / bevy-4b86463c 2026-05-11 — `cargo check` caught `the trait bound 'WindowResolution: From<(f32, f32)>' is not satisfied`; the agent fixed it inside a retry cycle costing ~20 min. Cheap if it stays in scaffold reference snippets.)

## Build pipeline

- **`cargo check` passing is necessary but not sufficient for browser-loadable WASM.** The build can produce a binary that Chrome refuses to instantiate with `invalid value type 0x6B at offset N` — a GC/reference-types heap-type byte the runtime doesn't enable. The pre-export validate gate (`src/api/services/wasm_validate.py`) now catches this at build time and records `rule=wasm_browser_unsafe_value_type` in `data/godogen_failures.jsonl`. If the validate gate flags a build, `cargo check`-only verification is the wrong loop.
  (why: Breakout / bevy-4b86463c 2026-05-11 — cargo check + wasm-bindgen + walrus all succeeded; dist/*.wasm was 18MB and well-formed at the file level; browser instantiateStreaming rejected it immediately. Root cause: `wasm-opt --all-features` in `scripts/bevy_build.sh` enabled reference-types lowering. Now pinned to explicit features.)

- **Never pass `--all-features` to `wasm-opt`.** The optimizer's `--all-features` flag enables every WASM proposal it knows — including reference-types and GC — and then emits `(ref null heap-type)` bytes (0x6B) into the type section that browsers reject. The safe baseline that matches what rustc 1.89 + wasm-bindgen 0.2.121 actually emit: `--enable-bulk-memory --enable-sign-ext --enable-multivalue --enable-mutable-globals --enable-nontrapping-float-to-int`.
  (why: same incident as above. The previous comment in `scripts/bevy_build.sh` rationalized `--all-features` as "matching whatever cargo generates" — the inverse was true. Three-hour debugging cycle. Pinned values now live in that script.)

## Web export & runtime

- **Bevy's wasm-bindgen output has no `<canvas>` in `index.html`.** Bevy's web template ships:
  ```html
  <body><script type="module">
    import init from "./crate.js";
    init({ module_or_path: "./crate_bg.wasm" });
  </script></body>
  ```
  The canvas element is created during WASM main-loop startup, not by the HTML. Two implications: (a) don't try to add a `<canvas>` element manually in the template — the engine creates its own and won't find yours; (b) if init() fails before the canvas appears, the page is permanently black with no visible affordance. The telemetry shim's `canvas_missing` watchdog (5s timeout) is the only automatic surfacing of this failure mode today.

- **Bevy WASM bundles are large: 18–21 MB** for a Breakout-class game. wasm-opt's `-Oz` is enabled and that's the floor — Bevy's render pipeline alone is most of the binary. Don't try to prematurely shrink this; it's working as designed. For first-load UX, expect ~5s on a fast connection, longer on slow. The `Cache-Control: no-store` we serve means every reload re-downloads; production should add ETag/asset-hashing if first-paint metrics matter.

- **The capture pipeline (screenshots/video) runs natively, not in WASM.** Bevy game capture happens through `cargo run --release` on the build machine, NOT in the browser iframe. Implication: features that "work" in the captured video may still fail in WASM (different render backend, missing browser APIs, threading differences). Trust the WASM result over the capture for "does this play" questions.
