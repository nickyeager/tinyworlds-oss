# Capture lessons

Screenshots, video, final-result bundle.

- `.capture/run_godot` and `.capture/env` are pre-created by the backend before the agent starts (`GodotGameService.ensure_capture_wrapper`, 2026-06-06). You can `source .capture/env` and call `.capture/run_godot ...` immediately — do NOT re-run the Setup block from `capture.md`. It will overwrite the wrapper with one that may not match the backend's GPU detection.
  (why: ~50% historical skip rate when the agent had to remember to run Setup. Pre-creating removes that failure class. Re-running Setup is fine but pointless; the wrapper is identical.)
- A `screenshots/result/{N}/` bundle with at least 1 PNG is the minimum proof that capture executed. Missing dir = capture path never ran. Producing fewer than the requested frames is acceptable; producing zero is not.
- Source `.capture/env` (`$GPU_AVAILABLE`, `$TIMEOUT_CMD`) before any `--write-movie` invocation. If `$GPU_AVAILABLE` is false, skip `video.mp4` but still produce `screenshots/result/N/` with at least the static-frame sequence.
  (why: a missing `screenshots/result/` directory entirely is a stronger failure signal than a thin one — having even a few PNGs proves the capture path executed.)
