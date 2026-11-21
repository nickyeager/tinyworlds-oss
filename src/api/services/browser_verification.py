"""Exercise exported artifacts in a browser; keep evidence outside agent mounts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from src.api.services.game_access import metadata_path


def artifact_digest(project: Path) -> str:
    digest = hashlib.sha256()
    dist = project / "dist"
    if dist.is_symlink() or not dist.is_dir():
        raise ValueError("Export directory is missing or is a symlink")
    for file in sorted(dist.rglob("*")):
        if file.is_symlink():
            raise ValueError("Export contains a symlink")
        if file.is_file():
            digest.update(str(file.relative_to(dist)).encode())
            with file.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()


async def verified_screenshot(project: Path) -> Path | None:
    """Use trusted capture evidence only while its export hash still matches."""
    directory = metadata_path(project.name).parent / "verification" / project.name
    image = directory / "canvas.png"
    try:
        proof = json.loads((directory / "latest.json").read_text())
        if (
            proof.get("success")
            and image.is_file()
            and not image.is_symlink()
            and proof.get("artifact_sha256")
            == await asyncio.to_thread(artifact_digest, project)
        ):
            return image
    except (OSError, ValueError):
        pass
    return None


class _Artifacts(SimpleHTTPRequestHandler):
    def __init__(self, *args, telemetry_paths=frozenset(), telemetry_requests=None, **kwargs):
        self.telemetry_paths = telemetry_paths
        self.telemetry_requests = telemetry_requests if telemetry_requests is not None else []
        super().__init__(*args, **kwargs)

    def do_POST(self):
        # Production serves these application-owned telemetry endpoints. Capture
        # bounded receipts locally so the smoke test exercises the same contract.
        # Arbitrary application POSTs still fail verification.
        path = urlparse(self.path).path
        if path not in self.telemetry_paths:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536 or len(self.telemetry_requests) >= 128:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                self.send_error(400)
                return
        except (ValueError, UnicodeError):
            self.send_error(400)
            return
        self.telemetry_requests.append({"path": path, "bytes": length})
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        root = Path(self.directory).resolve()
        relative = unquote(urlparse(self.path).path).lstrip("/")
        candidate = root / relative
        if not candidate.resolve().is_relative_to(root) or any(
            p.is_symlink() for p in [candidate, *candidate.parents] if p != root
        ):
            self.send_error(404)
            return
        super().do_GET()


async def verify_browser(
    project: Path, engine: str, preliminary: list[str], *, require_pip: bool = False
) -> list[str]:
    """Fail closed on startup/render errors and record keyboard/pointer/touch exercise.

    This is a smoke test. It does not establish game rules, difficulty, or fun.
    Every invocation launches a fresh browser against the current artifact hash.
    """
    if preliminary:
        return preliminary
    errors: list[str] = []
    telemetry_requests: list[dict] = []
    server = None
    thread = None
    evidence = metadata_path(project.name).parent / "verification" / project.name
    evidence.mkdir(parents=True, exist_ok=True)
    proof = evidence / "latest.json"
    proof.unlink(missing_ok=True)
    try:
        from playwright.async_api import async_playwright
        from PIL import Image, ImageStat

        from src.api.core.config import get_settings
        from src.api.services.pip_bridge import install_pip_runtime
        pip_required = install_pip_runtime(project, get_settings().FRONTEND_URL, required=require_pip)
        before = await asyncio.to_thread(artifact_digest, project)
        mimetypes.add_type("application/wasm", ".wasm")
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(
                _Artifacts,
                directory=str(project / "dist"),
                telemetry_paths=frozenset(
                    f"/api/v1/{engine}/games/{project.name}/{endpoint}"
                    for endpoint in ("telemetry", "playthrough")
                ),
                telemetry_requests=telemetry_requests,
            ),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        async with asyncio.timeout(60), async_playwright() as playwright:
            browser_env = {
                key: os.environ[key]
                for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
                if key in os.environ
            }
            browser = await playwright.chromium.launch(
                headless=True,
                executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"),
                env=browser_env,
                args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 960, "height": 640}, has_touch=True
                )

                async def isolate(route):
                    url = route.request.url
                    if url.startswith(origin + "/") or url.startswith(
                        ("data:", "blob:")
                    ):
                        await route.continue_()
                    else:
                        errors.append(
                            "Export requested an external resource: "
                            + urlparse(url).netloc
                        )
                        await route.abort()

                await context.route("**/*", isolate)
                page = await context.new_page()
                loaded_wasm: set[str] = set()
                page.on(
                    "response",
                    lambda response: (
                        loaded_wasm.add(response.url)
                        if response.ok and urlparse(response.url).path.endswith(".wasm")
                        else None
                    ),
                )
                page.on("pageerror", lambda error: errors.append(str(error)[:1000]))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text[:1000])
                        if message.type == "error"
                        else None
                    ),
                )
                await page.goto(
                    origin + "/index.html", wait_until="load", timeout=30000
                )
                canvas = page.locator("canvas").first
                await canvas.wait_for(state="visible", timeout=20000)
                await asyncio.sleep(3)
                await page.keyboard.press("Enter")
                await page.keyboard.press("Space")
                box = await canvas.bounding_box()
                if not box or box["width"] < 16 or box["height"] < 16:
                    errors.append("Export has no visible game canvas")
                else:
                    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    await page.mouse.click(x, y)
                    await page.touchscreen.tap(x, y)
                    await page.keyboard.down("ArrowRight")
                    await asyncio.sleep(0.3)
                    await page.keyboard.up("ArrowRight")
                    await asyncio.sleep(1)
                    image = await canvas.screenshot(
                        path=str(evidence / "canvas.png"), timeout=5000
                    )
                    import io

                    stats = ImageStat.Stat(Image.open(io.BytesIO(image)).convert("RGB"))
                    if max(stats.var) < 1:
                        errors.append("Game canvas is blank or uniformly colored")
                if pip_required:
                    try:
                        await page.wait_for_function("window.TinyWorldsPip?.snapshot().ready === true", timeout=8000)
                        await page.evaluate("""() => {
                            const api = window.TinyWorldsPip;
                            api.localControl = false;
                            api.dispatch({id:'verification-pip', action:api.snapshot().actions[0]});
                        }""")
                        await page.wait_for_function("window.TinyWorldsPip?.snapshot().acknowledgement?.id === 'verification-pip'", timeout=5000)
                    except Exception:
                        errors.append("Pip's native player adapter did not publish state and acknowledge an action")
                if not loaded_wasm:
                    errors.append("Export did not load its WebAssembly runtime")
            finally:
                await browser.close()
        after = await asyncio.to_thread(artifact_digest, project)
        if before != after:
            errors.append("Export changed during browser verification")
        proof.write_text(
            json.dumps(
                {
                    "engine": engine,
                    "artifact_sha256": after,
                    "success": not errors,
                    "input_exercised": ["keyboard", "pointer", "touch"],
                    "errors": errors,
                    "telemetry_requests": telemetry_requests,
                },
                indent=2,
            )
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        errors.append(f"Browser verification failed: {type(exc).__name__}: {exc}")
    finally:
        if server:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
        if thread:
            await asyncio.to_thread(thread.join, 2)
    return list(dict.fromkeys(errors))
