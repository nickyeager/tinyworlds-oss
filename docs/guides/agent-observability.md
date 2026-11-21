# Agent dashboard

TinyWorlds can send Claude Code and Codex execution traces to a local
[Arize Phoenix](https://arize.com/docs/phoenix) dashboard. This is optional and
disabled unless `AGENT_TRACE_ENDPOINT` is set on the backend.

## Start locally

```sh
docker compose -f docker-compose.observability.yml up -d
```

Open <http://localhost:6006>. This local configuration needs no account. It binds
only to loopback and persists traces in the `tinyworlds-observability_phoenix-data`
Docker volume. The image is pinned by digest (Phoenix 21.0.0 when verified).

Install `requirements-observability.txt` into the backend environment after
`requirements.txt`, then add these settings to the backend
environment and restart it, preserving the existing agent provider:

```dotenv
AGENT_TRACE_ENDPOINT=http://localhost:6006/v1/traces
AGENT_TRACE_PROJECT=tinyworlds
AGENT_TRACE_CONTENT=false
```

Use **Tracing → tinyworlds** to inspect runs, or **Dashboards** for aggregates.
Select a run to see its tool spans and timing. Runs for the same game share a
session ID. New create, modify, repair and utility calls through the CLI executor
are traced. Existing saved runs are not imported automatically.

The endpoint above is for a backend running on the host. A containerized backend
needs network access to the collector at its container/service address; its own
`localhost` is not the host. This separate Compose file does not alter production
or expose the dashboard to TinyWorlds players.

## What is recorded

- Provider, engine, operation, game ID, requested model and execution mode.
- Agent-run duration and observed tool durations, tool names, exit codes and failures.
- Repeated identical tool inputs as a count, not an assertion that they are retries.
- Reported input/output/cache tokens. Codex input already includes cached input;
  Claude reports cache buckets separately. Child-agent accounting is not verified.
- Provider-reported cost when present. This is not a subscription invoice.
- The hash of the supplied runtime manifest, not proof of which skills were used.
- Completed, failed, interrupted and incomplete execution states.

The backend observes normalized events outside the agent sandbox. No dashboard
credentials, exporter environment, hooks or extra permissions are passed into
the worker. Both local and worker-mode event streams use the same adapter.

Phoenix ingests completed spans. Short start markers expose ongoing activity
before the root run finishes; refresh the trace to see newly completed calls.
Root totals and final status are only available at the end. A hard backend crash
can leave a trace without a completed root. Long-running tool duration is known
only when its result arrives. Capture is bounded to the first 512 tool calls per
run; the total call counter continues beyond that limit.

## Content and operational behavior

By default no prompt, tool arguments, command text, tool output, file paths or
agent-message text is exported. Set `AGENT_TRACE_CONTENT=true` to record bounded
prompt/argument/result excerpts for debugging. Common credentials are redacted,
but this is best-effort filtering, not a guarantee that arbitrary content is
safe to share. Provider reasoning/message events are counted, not transcribed.

Export uses a bounded background batch queue. A missing/unreachable collector
does not block generation; failed exports can be dropped and logged. This is
observability, not the authoritative job log. Game/build journals remain the
source of truth. Normal backend shutdown flushes queued spans.

This initial integration does not score gameplay, import historical evaluations,
automatically recommend changes, or prove that a skill improves outcomes.
Phoenix supports evaluations, but those require separately defined tasks and
scoring criteria. Existing browser checks remain responsible for game readiness.

Disable tracing by clearing `AGENT_TRACE_ENDPOINT` and restarting the backend.
Stop the dashboard with `docker compose -f docker-compose.observability.yml down`;
the volume is preserved. Do not use `down -v` unless you intend to delete traces.

## Acceptance check

With Phoenix running and an authenticated CLI installed:

```sh
.venv/bin/python scripts/check_agent_observability.py \
  --provider codex --model gpt-6.1-sol \
  --output data/agent-observability-check
```

This uses real model inference and three small shell commands in a temporary
sandbox. It deliberately observes one nonzero tool exit, recovery, and a repeated
command. It checks persisted Phoenix data and content exclusion. Use `--provider
claude --model YOUR_MODEL` to check Claude; no CLI behavior is simulated.

## Choice and attribution

Phoenix's [single-service local deployment](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
and OpenTelemetry support fit the existing provider-neutral executor. Langfuse's
[coding-agent visibility](https://langfuse.com/coding-agents) remains a useful
comparison, particularly for spend analysis. Opik's
[Ollie](https://www.comet.com/docs/opik/ollie) is relevant to later investigation
and evaluation workflows. This choice is about a working local operator view,
not measured superiority across those products.

Phoenix is a separate service under
[Elastic License 2.0](https://github.com/Arize-ai/phoenix/blob/main/LICENSE), which
restricts offering its substantial functionality as a hosted service to third
parties. It is not MIT licensed. TinyWorlds uses OpenTelemetry's Apache-2.0 SDK
and OpenInference attribute conventions. See [attribution](../../ATTRIBUTION.md).
