"""Real Chromium checks of the verification boundary, without model/API calls."""

import json

import pytest

from src.api.core.config import get_settings
from src.api.services.browser_verification import artifact_digest, verify_browser
from src.api.services.game_access import metadata_path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["valid", "telemetry", "unexpected-post", "blank", "runtime-error", "external-resource"]
)
async def test_browser_gate_exercises_current_export_and_rejects_failures(
    tmp_path, monkeypatch, case
):
    root = tmp_path / "generated_games"
    project = root / "godot-probe"
    dist = project / "dist"
    dist.mkdir(parents=True)
    monkeypatch.setattr(get_settings(), "GODOT_GAMES_DIR", str(root))
    (dist / "game.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
    drawing = "ctx.fillStyle='blue';ctx.fillRect(0,0,320,240);ctx.fillStyle='gold';ctx.fillRect(20,20,80,80);"
    if case == "blank":
        drawing = "ctx.fillStyle='blue';ctx.fillRect(0,0,320,240);"
    extra = {
        "valid": "",
        "telemetry": "fetch('/api/v1/godot/games/godot-probe/playthrough',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'started',data:{}})});",
        "unexpected-post": "fetch('/unexpected-api',{method:'POST',body:'{}'});",
        "blank": "",
        "runtime-error": "setTimeout(()=>{throw new Error('broken game runtime')},20);",
        "external-resource": "fetch('https://example.invalid/asset').catch(()=>{});",
    }[case]
    (dist / "index.html").write_text(
        "<html><body><canvas width='320' height='240'></canvas><script>"
        "const ctx=document.querySelector('canvas').getContext('2d');"
        + drawing
        + "fetch('game.wasm').then(r=>r.arrayBuffer()).then(b=>WebAssembly.instantiate(b));"
        + extra
        + "</script></body></html>"
    )
    failures = await verify_browser(project, "godot", [])
    assert bool(failures) == (case not in {"valid", "telemetry"}), failures
    proof = json.loads(
        (
            metadata_path(project.name).parent
            / "verification"
            / project.name
            / "latest.json"
        ).read_text()
    )
    assert proof["success"] == (case in {"valid", "telemetry"})
    if case == "telemetry":
        assert proof["telemetry_requests"][0]["path"].endswith("/playthrough")
    assert proof["artifact_sha256"] == artifact_digest(project)
    assert set(proof["input_exercised"]) == {"keyboard", "pointer", "touch"}


@pytest.mark.asyncio
async def test_missing_artifacts_do_not_start_browser(tmp_path):
    assert await verify_browser(tmp_path / "missing", "godot", ["missing wasm"]) == [
        "missing wasm"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize('adapter', [True, False])
async def test_new_runtime_requires_a_real_registered_pip_adapter(tmp_path, monkeypatch, adapter):
    project = tmp_path / 'godot-pip-probe'
    dist = project / 'dist'; dist.mkdir(parents=True)
    monkeypatch.setattr(get_settings(), 'GODOT_GAMES_DIR', str(tmp_path))
    if adapter:
        (project / '.runtime-provenance.json').write_text('{"pip_protocol":1}')
    (dist / 'game.wasm').write_bytes(b'\x00asm\x01\x00\x00\x00')
    native = """
      let human=1, pip=5;
      const api=window.TinyWorldsPip;
      api.register({actions:['left']}, text => {
        const cmd=JSON.parse(text); pip--;
        api.publish({human,pip}); api.ack({id:cmd.id,accepted:true});
      });
      api.publish({human,pip});
    """ if adapter else ''
    (dist / 'index.html').write_text("<html><head></head><body><canvas width='320' height='240'></canvas><script>"
        "const ctx=document.querySelector('canvas').getContext('2d');ctx.fillStyle='blue';ctx.fillRect(0,0,320,240);ctx.fillStyle='gold';ctx.fillRect(10,10,50,50);"
        "fetch('game.wasm').then(r=>r.arrayBuffer()).then(b=>WebAssembly.instantiate(b));" + native + '</script></body></html>')
    failures = await verify_browser(project, 'godot', [], require_pip=True)
    assert bool(failures) is (not adapter), failures
    if not adapter:
        assert any('Pip' in f for f in failures)
