"use client";

/**
 * Shows the saved steps from when a game was made.
 *
 * Source: `.creation/events.jsonl`, served by
 * `GET /api/v1/<engine>/games/<id>/events`. Events go through `classifyEvent`
 * so this looks the same as the live view on /create.
 */
import { useMemo, useRef } from "react";
import { ScrollText, CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import { type GameCreationEvent, type GameCreationSummary } from "@/lib/api";
import { durationLabel, whenLabel } from "@/lib/game-editor";
import { StreamCard, classifyEvent } from "@/lib/stream-cards";
import { renderLayout } from "@/components/build-layouts";

interface Props {
  gameId: string;
  events: GameCreationEvent[] | null;
  summary: GameCreationSummary | null;
  state: "idle" | "loading" | "loaded" | "error";
  error: string | null;
}

/** Adapt a saved event to the live `ObservabilityEvent` shape for `classifyEvent`. */
function eventToCard(
  e: GameCreationEvent,
  idx: number,
  gameId: string
): StreamCard | null {
  const adapted = {
    timestamp: e.timestamp,
    service: e.service ?? "godot_creation_agent",
    stream_type: e.stream_type,
    tool_name: e.tool_name ?? undefined,
    tool_input: e.tool_input,
    content: e.content ?? "",
    cost_usd: e.cost_usd ?? null,
    event_type: e.event_type ?? "CLIStreamEvent",
    _replay_idx: idx,
  } as unknown as Parameters<typeof classifyEvent>[0];
  return classifyEvent(adapted, gameId);
}

export function BuildLogReplay({ gameId, events, summary, state, error }: Props) {
  const cards = useMemo<StreamCard[]>(() => {
    if (!events) return [];
    const out: StreamCard[] = [];
    events.forEach((e, i) => {
      const c = eventToCard(e, i, gameId);
      if (c) out.push(c);
    });
    return out;
  }, [events, gameId]);

  const cardEndRef = useRef<HTMLDivElement>(null);

  if (state === "loading") {
    return (
      <div className="flex items-center gap-3 text-txt-muted">
        <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
        <span className="text-sm">Loading…</span>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="w-full max-w-3xl rounded-lg border-2 border-pop-red bg-pop-red/10 p-4">
        <div className="flex items-center gap-2 mb-1">
          <AlertCircle className="h-5 w-5 text-pop-red" />
          <span className="text-sm font-bold text-pop-red">
            We couldn’t load the steps. Try again later.
          </span>
        </div>
        <p className="font-mono text-xs text-txt-secondary">{error}</p>
      </div>
    );
  }

  if (state === "loaded" && (events?.length ?? 0) === 0) {
    return (
      <div className="w-full max-w-3xl rounded-lg border-2 border-[var(--card-border)] bg-surface-raised p-4 text-center">
        <ScrollText className="h-6 w-6 mx-auto mb-2 text-txt-muted" />
        <p className="text-sm text-txt-secondary font-bold">
          No steps were saved for this game.
        </p>
      </div>
    );
  }

  return (
    <div className="w-full max-w-7xl flex flex-col gap-4">
      {/* Summary banner */}
      {summary && (
        <div
          className={`rounded-lg brutal-border p-4 ${
            summary.status === "ok" || summary.has_export
              ? "bg-pop-lime/10 border-pop-lime/60"
              : summary.status === "partial"
                ? "bg-pop-yellow/10 border-pop-yellow/60"
                : "bg-surface-raised"
          }`}
        >
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              {summary.has_export ? (
                <CheckCircle className="h-4 w-4 text-pop-lime" />
              ) : (
                <AlertCircle className="h-4 w-4 text-pop-yellow" />
              )}
              <span className="text-xs font-bold">
                {summary.has_export ? "Ready to play" : "Not finished"}
              </span>
            </div>
            {typeof summary.duration_seconds === "number" && (
              <span className="font-mono text-xs text-txt-secondary">
                {durationLabel(summary.duration_seconds)}
              </span>
            )}
            {typeof summary.event_count === "number" && (
              <span className="font-mono text-xs text-txt-secondary">
                {summary.event_count} steps
              </span>
            )}
            {typeof summary.total_cost_usd === "number" && summary.total_cost_usd > 0 && (
              <span className="font-mono text-xs text-txt-secondary">
                ${summary.total_cost_usd.toFixed(2)}
              </span>
            )}
            <span className="font-mono text-[10px] text-txt-muted ml-auto">
              {whenLabel(summary.started_at)}
            </span>
          </div>
          {summary.error && (
            <p className="mt-2 font-mono text-xs text-pop-red">
              {summary.error}
            </p>
          )}
          {summary.final_message && summary.status !== "ok" && (
            <p className="mt-2 font-mono text-xs text-txt-secondary italic border-l-2 border-[var(--card-border)] pl-3">
              {summary.final_message}
            </p>
          )}
        </div>
      )}

      {/* Same side-by-side layout as the live view. */}
      {renderLayout("two-pane", {
        cards,
        cardEndRef,
      })}
    </div>
  );
}
