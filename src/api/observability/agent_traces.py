"""Optional, backend-owned agent traces over OTLP (Phoenix/OpenInference).

No exporter credentials or hooks enter the agent workspace. Explicit parent
contexts avoid leaking a current span across async-generator yield boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)
MAX_TOOLS = 512
MAX_TEXT = 4000


def _text(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;]+", r"\1[redacted]", text)
    return text[:MAX_TEXT]


@lru_cache(maxsize=8)
def _provider(endpoint: str, project: str):
    # Lazy imports: disabled installations need no OTLP dependencies.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({
        "service.name": "tinyworlds-agents", "openinference.project.name": project,
    }))
    provider.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=endpoint, timeout=2),
        max_queue_size=2048, max_export_batch_size=128, schedule_delay_millis=1000,
    ))
    return provider


def flush_agent_traces(settings) -> bool:
    """For explicit shutdown/test handoff; never called on the streaming hot path."""
    if not settings.AGENT_TRACE_ENDPOINT:
        return True
    return _provider(settings.AGENT_TRACE_ENDPOINT, settings.AGENT_TRACE_PROJECT).force_flush(timeout_millis=5000)


class AgentTrace:
    def __init__(self, settings, *, provider: str, engine: str, mode: str, game_path: Path, prompt: str):
        from opentelemetry.context import Context
        from opentelemetry.trace import set_span_in_context

        self.content = settings.AGENT_TRACE_CONTENT
        self.provider = provider
        self.tracer = _provider(settings.AGENT_TRACE_ENDPOINT, settings.AGENT_TRACE_PROJECT).get_tracer(__name__)
        self.tools = {}
        self.signatures = set()
        self.counts = {"tool_calls": 0, "tool_failures": 0, "repeated_tool_calls": 0, "file_changes": 0, "messages": 0}
        self.complete = False
        self.failed = False
        self.root = self.tracer.start_span(f"{provider}.{engine}.{mode}", context=Context(), attributes={
            "openinference.span.kind": "AGENT",
            "session.id": game_path.name,
            "tinyworlds.game_id": game_path.name,
            "tinyworlds.provider": provider,
            "tinyworlds.engine": engine,
            "tinyworlds.operation": mode,
            "tinyworlds.execution_mode": settings.AGENT_EXECUTION_MODE,
            "tinyworlds.content_recorded": self.content,
            "tinyworlds.model_requested": settings.CODEX_CLI_MODEL if provider == "codex" else settings.CLAUDE_CLI_MODEL,
            "tinyworlds.usage_scope": "provider-reported CLI total; child-agent coverage unverified",
        })
        self.context = set_span_in_context(self.root)
        # Fingerprint the instructions supplied, without claiming they were used.
        manifest = game_path / ("AGENTS.md" if provider == "codex" else "CLAUDE.md")
        if manifest.is_file() and not manifest.is_symlink():
            self.root.set_attribute("tinyworlds.runtime_manifest_sha256", hashlib.sha256(manifest.read_bytes()).hexdigest())
        if self.content:
            self.root.set_attribute("input.value", _text(prompt))
        # Export a completed child immediately so active work appears before the
        # long-lived root finishes. Phoenix stores completed spans, not open ones.
        self._instant("Run started", {"tinyworlds.state": "running"})

    def _instant(self, name: str, attributes: dict):
        span = self.tracer.start_span(name, context=self.context, attributes={"openinference.span.kind": "CHAIN", **attributes})
        span.end()

    def observe(self, event):
        from opentelemetry.trace import Status, StatusCode

        meta = event.metadata or {}
        key = str(meta.get("tool_use_id") or meta.get("item_id") or "")
        if event.type == "tool_use":
            self.counts["tool_calls"] += 1
            if self.counts["tool_calls"] > MAX_TOOLS:
                return
            name = str(meta.get("tool_name", "tool"))
            name = name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,99}", name) else "tool"
            # Provider item IDs/status are not semantic inputs for repetition.
            inputs = dict(meta.get("input", {})) if isinstance(meta.get("input"), dict) else meta.get("input", {})
            if isinstance(inputs, dict):
                inputs = {k: v for k, v in inputs.items() if k not in {"id", "status", "aggregated_output", "exit_code"}}
            signature = hashlib.sha256(json.dumps([name, inputs], sort_keys=True, default=str).encode()).hexdigest()
            repeated = signature in self.signatures
            self.signatures.add(signature)
            self.counts["repeated_tool_calls"] += int(repeated)
            attributes = {"openinference.span.kind": "TOOL", "tool.name": name, "tinyworlds.repeated_input": repeated}
            if self.content:
                attributes["input.value"] = _text(inputs)
            if key in self.tools:
                self.tools.pop(key).end()
            self.tools[key] = self.tracer.start_span(name, context=self.context, attributes=attributes)
            self._instant(f"Started {name}", {"tinyworlds.tool_call_number": self.counts["tool_calls"]})
        elif event.type == "tool_result" or (event.type == "error" and key in self.tools):
            success = event.type != "error" and meta.get("success", True)
            self.counts["tool_failures"] += int(not success)
            span = self.tools.pop(key, None)
            if span is not None:
                span.set_status(Status(StatusCode.OK if success else StatusCode.ERROR))
                if isinstance(meta.get("exit_code"), int):
                    span.set_attribute("tinyworlds.exit_code", meta["exit_code"])
                if self.content:
                    span.set_attribute("output.value", _text(event.content))
                span.end()
            if event.type == "error":
                self.failed = True
        elif event.type == "error":
            self.failed = True
            self.root.add_event("Agent error", {"message": _text(event.content)} if self.content else {})
        elif event.type == "file_changed":
            self.counts["file_changes"] += 1
        elif event.type == "thinking":
            self.counts["messages"] += 1
            # These events mix public agent messages and provider reasoning.
            # Do not export them as a chain-of-thought transcript.
        elif event.type == "complete":
            self.complete = True
            self.failed |= not meta.get("success", False)
            usage = meta.get("usage") or {}
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            cached = usage.get("cached_input_tokens", usage.get("cache_read_input_tokens", 0))
            cache_write = usage.get("cache_creation_input_tokens", 0)
            for label, value in (("input", input_tokens), ("output", output_tokens), ("cache_read", cached), ("cache_write", cache_write)):
                if isinstance(value, int) and value >= 0:
                    self.root.set_attribute(f"tinyworlds.tokens.{label}", value)
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                # Codex includes cached input; Claude reports cache buckets apart.
                prompt_tokens = input_tokens + (cached + cache_write if self.provider == "claude" else 0)
                self.root.set_attribute("llm.token_count.prompt", prompt_tokens)
                self.root.set_attribute("llm.token_count.completion", output_tokens)
                self.root.set_attribute("llm.token_count.total", prompt_tokens + output_tokens)
            if isinstance(meta.get("cost_usd"), (int, float)):
                self.root.set_attribute("tinyworlds.provider_reported_cost_usd", meta["cost_usd"])

    def finish(self, interrupted: str | None = None):
        from opentelemetry.trace import Status, StatusCode

        state = interrupted or ("failed" if self.failed else "completed" if self.complete else "incomplete")
        for span in self.tools.values():
            span.set_attribute("tinyworlds.result_missing", True)
            span.set_status(Status(StatusCode.ERROR, "Tool ended without an observed result"))
            span.end()
        self.root.set_attributes({f"tinyworlds.{key}": value for key, value in self.counts.items()})
        self.root.set_attribute("tinyworlds.state", state)
        self.root.set_status(Status(StatusCode.OK if state == "completed" else StatusCode.ERROR))
        self.root.end()


async def trace_agent_stream(stream, settings, **identity):
    """Pass through every event; exporter/config failures cannot fail generation."""
    trace = None
    interrupted = None
    if settings.AGENT_TRACE_ENDPOINT:
        try:
            trace = AgentTrace(settings, **identity)
        except Exception as exc:
            logger.warning("Agent tracing unavailable (%s)", type(exc).__name__)
    try:
        async for event in stream:
            if trace is not None:
                try:
                    trace.observe(event)
                except Exception as exc:
                    logger.warning("Agent trace event omitted (%s)", type(exc).__name__)
            yield event
    except BaseException as exc:
        interrupted = "cancelled" if isinstance(exc, (GeneratorExit, asyncio.CancelledError)) else "exception"
        raise
    finally:
        try:
            await stream.aclose()
        finally:
            if trace is not None:
                try:
                    trace.finish(interrupted)
                except Exception as exc:
                    logger.warning("Agent trace finalization failed (%s)", type(exc).__name__)
