import { API_BASE } from "./api-config";
import { followJsonEventStream } from "./event-stream";
import { getToken } from "./token-storage";
import { encodeVisualReference } from "./visual-reference";
import type { Engine, ModificationRunEvent, ObservabilityEvent } from "./api";

export interface ModificationStreamOptions {
  resumeRunId?: string;
  onRawEvent?: (event: ModificationRunEvent) => void;
  onInterrupted?: (reason: string) => void;
  onConnectionChange?: (reconnecting: boolean) => void;
}

export function modifyGameStreaming(
  engine: Engine, gameId: string, instruction: string,
  onEvent: (event: ObservabilityEvent) => void,
  onError?: (error: string) => void,
  onDone?: (event: ModificationRunEvent) => void,
  image?: File,
  options: ModificationStreamOptions = {},
): () => void {
  const controller = new AbortController();
  let runId = options.resumeRunId;
  let lastSeq = -1;
  let reference: ReturnType<typeof encodeVisualReference> | undefined;
  void followJsonEventStream<ModificationRunEvent>({
    signal: controller.signal,
    request: async (signal) => {
      const token = getToken();
      const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
      headers["Content-Type"] = "application/json";
      const reference_image = !runId && image ? await (reference ??= encodeVisualReference(image, signal)) : undefined;
      return fetch(runId
        ? `${API_BASE}/api/v1/${engine}/games/${gameId}/modifications/${runId}/events/stream?since=${lastSeq}`
        : `${API_BASE}/api/v1/${engine}/games/${gameId}/modify/stream`, {
        method: runId ? "GET" : "POST", headers, signal,
        ...(runId ? {} : { body: JSON.stringify({ instruction, ...(reference_image ? { reference_image } : {}) }) }),
      });
    },
    canResume: () => Boolean(runId),
    onEvent: (data) => {
      if (typeof data.seq === "number" && data.seq >= 0) {
        if (data.seq <= lastSeq) return true;
        lastSeq = data.seq;
      }
      if (data.event_type === "init" && typeof data.metadata?.run_id === "string") runId = data.metadata.run_id;
      options.onRawEvent?.(data);
      onEvent({
        timestamp: data.timestamp ?? "", level: data.type === "error" ? "error" : "info", category: "user",
        service: `${engine}_modification`, event_type: "CLIStreamEvent",
        stream_type: (data.stream_type ?? data.type) as ObservabilityEvent["stream_type"],
        content: data.content ?? data.message,
        tool_name: data.tool_name ?? data.metadata?.tool_name as string | undefined,
        tool_input: data.tool_input ?? data.metadata?.input as Record<string, unknown> | undefined,
      });
      if (data.event_type === "done") { onDone?.(data); return false; }
      if (["failed", "crashed", "interrupted"].includes(data.event_type ?? "")) {
        const message = data.content ?? data.error ?? String(data.reason ?? "Edit interrupted");
        if (data.event_type === "interrupted" && options.onInterrupted) options.onInterrupted(message);
        else onError?.(message);
        return false;
      }
      return true;
    },
    onError: (message) => onError?.(message), onConnectionChange: options.onConnectionChange,
    httpError: "Unable to edit",
    missingAcknowledgement: "The connection closed before the edit was acknowledged. Check edit history before trying again.",
    reconnectFailure: "Connection lost. Your edit may still be running. Reconnect to continue following it.",
  });
  return () => controller.abort();
}

export function createGameStreaming(
  description: string | null, budgetCents: number | null,
  onEvent: (event: ObservabilityEvent) => void,
  onError?: (error: string) => void,
  onDone?: (gameId: string, engine: Engine) => void,
  onInit?: (gameId: string, engine: Engine) => void,
  options?: { attachGameId?: string; attachEngine?: Engine; maxReconnects?: number; image?: File; onConnectionChange?: (reconnecting: boolean) => void },
): () => void {
  const controller = new AbortController();
  let gameId = options?.attachGameId;
  let engine: Engine = options?.attachEngine ?? (gameId?.startsWith("bevy-") ? "bevy" : "godot");
  let lastSeq = -1;
  let reference: ReturnType<typeof encodeVisualReference> | undefined;
  void followJsonEventStream<Record<string, unknown>>({
    signal: controller.signal,
    request: async (signal) => {
      if (!gameId && !description) throw new Error("A game description or existing game is required");
      const token = getToken();
      const headers: Record<string, string> = { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
      const reference_image = !gameId && options?.image ? await (reference ??= encodeVisualReference(options.image, signal)) : undefined;
      return fetch(gameId
        ? `${API_BASE}/api/v1/${engine}/games/${gameId}/events/stream?since=${lastSeq}`
        : `${API_BASE}/api/v1/games`, {
        method: gameId ? "GET" : "POST", headers, signal,
        ...(gameId ? {} : { body: JSON.stringify({ description, budget_cents: budgetCents ?? 0, ...(reference_image ? { reference_image } : {}) }) }),
      });
    },
    canResume: () => Boolean(gameId),
    onEvent: (data) => {
      if (typeof data.seq === "number" && data.seq >= 0) {
        if (data.seq <= lastSeq) return true;
        lastSeq = data.seq;
      }
      if (data.event_type === "init" && typeof data.game_id === "string") {
        gameId = data.game_id;
        if (data.engine === "godot" || data.engine === "bevy") engine = data.engine;
        onInit?.(gameId, engine);
      } else if (data.event_type === "done" && typeof data.game_id === "string") {
        onDone?.(data.game_id, engine); return false;
      } else if (["failed", "crashed", "interrupted"].includes(String(data.event_type))) {
        // seq=-1 is a temporary idle notification; it is not a persisted outcome.
        if (data.event_type === "interrupted" && !(typeof data.seq === "number" && data.seq >= 0)) return true;
        onError?.(String(data.error ?? data.content ?? data.reason ?? "Generation did not finish")); return false;
      } else onEvent(data as unknown as ObservabilityEvent);
      return true;
    },
    onError: (message) => onError?.(message), onConnectionChange: options?.onConnectionChange,
    maxReconnects: options?.maxReconnects, httpError: "Unable to create game",
    missingAcknowledgement: "The connection closed before creation was acknowledged. Check your games before starting again.",
    reconnectFailure: "Connection lost. Your build may still be running. Open the game to check its progress.",
  });
  return () => controller.abort();
}
