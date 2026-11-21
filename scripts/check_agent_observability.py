"""Real CLI -> TinyWorlds event adapter -> Phoenix acceptance check (uses inference)."""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.api.core.config import Settings
from src.api.observability.agent_traces import flush_agent_traces
from src.api.services.executors import get_executor


async def main(args):
    project = "tinyworlds-check-" + uuid4().hex[:10]
    settings = Settings(
        _env_file=None, SECRET_KEY=secrets.token_urlsafe(32), DEBUG=False, GAME_AGENT_PROVIDER=args.provider,
        CODEX_CLI_MODEL=args.model if args.provider == "codex" else "",
        CLAUDE_CLI_MODEL=args.model if args.provider == "claude" else "",
        AGENT_TRACE_ENDPOINT=args.endpoint.rstrip("/") + "/v1/traces",
        AGENT_TRACE_PROJECT=project, AGENT_TRACE_CONTENT=False,
        GAME_AGENT_TIMEOUT_SECONDS=90,
    )
    # Public application entry point; no model, API or collector doubles.
    prompt = (
        "This is a bounded observability acceptance check. Execute these three shell commands "
        "in separate tool calls, in order, without combining them: "
        "1. python3 -c 'print(\"TW_OBSERVABILITY_PRIVATE_CANARY\"); raise SystemExit(3)' "
        "2. python3 -c 'print(\"trace-recovered\")' "
        "3. python3 -c 'print(\"trace-recovered\")' "
        "The first nonzero exit is intentional. Do not repair it or read other files. "
        "Finally reply TRACE_CHECK_COMPLETE."
    )
    started = time.monotonic()
    output = await get_executor(settings).run_oneshot(prompt, timeout=90)
    assert "TRACE_CHECK_COMPLETE" in output, "Provider did not finish the acceptance task"
    assert await asyncio.to_thread(flush_agent_traces, settings)
    async with httpx.AsyncClient(base_url=args.endpoint, trust_env=False, timeout=10) as client:
        spans = []
        for _ in range(30):
            response = await client.get(f"/v1/projects/{project}/spans", params={"limit": 100})
            if response.status_code == 200:
                spans = response.json()["data"]
                if any(s["name"].endswith(".utility") for s in spans):
                    break
            await asyncio.sleep(.5)
    Path(args.output).mkdir(parents=True, exist_ok=True)
    Path(args.output, "spans.json").write_text(json.dumps(spans, indent=2))
    roots = [s for s in spans if s["name"].endswith(".utility")]
    assert len(roots) == 1, "Completed agent run missing from Phoenix"
    root = roots[0]
    attrs = root["attributes"]
    assert root["status_code"] == "OK", root["status_code"]
    assert attrs["tinyworlds.state"] == "completed"
    assert attrs["tinyworlds.tool_calls"] >= 3
    assert attrs["tinyworlds.tool_failures"] >= 1
    assert attrs["tinyworlds.repeated_tool_calls"] >= 1
    assert attrs["llm.token_count.total"] > 0
    assert "TW_OBSERVABILITY_PRIVATE_CANARY" not in json.dumps(spans)
    assert all("input.value" not in s["attributes"] and "output.value" not in s["attributes"] for s in spans)
    tools = [s for s in spans if s["span_kind"] == "TOOL"]
    assert any(s["status_code"] == "ERROR" for s in tools)
    assert any(s["status_code"] == "OK" for s in tools)
    result = {"passed": True, "provider": args.provider, "project": project, "span_count": len(spans), "elapsed_seconds": round(time.monotonic() - started, 2), "checks": ["real CLI", "tool failure and recovery", "repeated command", "reported tokens", "content excluded", "Phoenix persisted trace"]}
    Path(args.output, "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://localhost:6006")
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    parser.add_argument("--model", default="")
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
