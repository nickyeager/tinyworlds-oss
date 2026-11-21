import { readApiError } from "./api-errors";

/** Decode SSE JSON frames across byte, Unicode, line and connection boundaries. */
export async function* readJsonEventStream<T extends object = Record<string, unknown>>(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<T> {
  if (!response.body) throw new Error("The server returned an empty event stream");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let data: string[] = [];
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener("abort", cancel, { once: true });
  const flush = (): T | null => {
    const payload = data.join("\n");
    data = [];
    if (!payload) return null;
    try {
      const value: unknown = JSON.parse(payload);
      return value !== null && typeof value === "object" && !Array.isArray(value) ? value as T : null;
    } catch { return null; }
  };
  const line = (value: string): T | null => {
    if (value === "") return flush();
    if (value.startsWith("data:")) data.push(value.slice(5).replace(/^ /, ""));
    return null;
  };
  try {
    while (!signal?.aborted) {
      const { done, value } = await reader.read();
      if (signal?.aborted) return;
      buffer += decoder.decode(value, { stream: !done });
      let end: number;
      while ((end = buffer.search(/[\r\n]/)) >= 0) {
        // A CRLF delimiter can itself be split between byte chunks.
        if (!done && buffer[end] === "\r" && end === buffer.length - 1) break;
        const event = line(buffer.slice(0, end));
        buffer = buffer.slice(end + (buffer.slice(end, end + 2) === "\r\n" ? 2 : 1));
        if (event) yield event;
        if (signal?.aborted) return;
      }
      if (done) {
        const event = buffer ? line(buffer) : null;
        if (event) yield event;
        const final = flush();
        if (final) yield final;
        return;
      }
    }
  } finally {
    signal?.removeEventListener("abort", cancel);
    cancel();
    reader.releaseLock();
  }
}

async function waitForOnline(signal: AbortSignal): Promise<void> {
  if (typeof window === "undefined" || navigator.onLine || signal.aborted) return;
  await new Promise<void>((resolve) => {
    const finish = () => {
      window.removeEventListener("online", finish);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    window.addEventListener("online", finish, { once: true });
    signal.addEventListener("abort", finish, { once: true });
    if (navigator.onLine || signal.aborted) finish();
  });
}

async function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return;
  await new Promise<void>((resolve) => {
    const finish = () => { clearTimeout(timer); signal.removeEventListener("abort", finish); resolve(); };
    const timer = setTimeout(finish, milliseconds);
    signal.addEventListener("abort", finish, { once: true });
  });
}

/** A submission is never retried: only a positively identified run can reconnect. */
export async function followJsonEventStream<T extends object>({
  signal, request, canResume, onEvent, onError, onConnectionChange,
  missingAcknowledgement, reconnectFailure, httpError, maxReconnects = 6,
}: {
  signal: AbortSignal;
  request: (signal: AbortSignal) => Promise<Response>;
  canResume: () => boolean;
  onEvent: (event: T) => boolean;
  onError: (message: string) => void;
  onConnectionChange?: (reconnecting: boolean) => void;
  missingAcknowledgement: string;
  reconnectFailure: string;
  httpError: string;
  maxReconnects?: number;
}): Promise<void> {
  let connection: AbortController | null = null;
  const abort = () => connection?.abort();
  const offline = () => { onConnectionChange?.(true); abort(); };
  signal.addEventListener("abort", abort);
  if (typeof window !== "undefined") window.addEventListener("offline", offline);
  try {
    for (let attempt = 0; attempt <= maxReconnects; attempt++) {
      if (typeof navigator !== "undefined" && !navigator.onLine) onConnectionChange?.(true);
      await waitForOnline(signal);
      if (signal.aborted) return;
      connection = new AbortController();
      let callbackFailed = false;
      try {
        const response = await request(connection.signal);
        if (signal.aborted) return;
        if (!response.ok) {
          if (response.status >= 500 && canResume()) {
            await response.body?.cancel().catch(() => {});
            throw new Error("Reconnect temporarily unavailable");
          }
          onError(await readApiError(response, `${httpError} (${response.status})`)); return;
        }
        onConnectionChange?.(false);
        for await (const event of readJsonEventStream<T>(response, connection.signal)) {
          if (signal.aborted) return;
          try { if (!onEvent(event)) return; }
          catch { callbackFailed = true; throw new Error("Progress callback failed"); }
        }
      } catch {
        if (signal.aborted) return;
        if (callbackFailed) { onError("Unable to display build progress. Reconnect to check its status."); return; }
      } finally { connection = null; }
      if (!canResume()) { onError(missingAcknowledgement); return; }
      if (attempt === maxReconnects) { onError(reconnectFailure); return; }
      onConnectionChange?.(true);
      await delay(Math.min(1000 * 2 ** attempt, 16000), signal);
    }
  } finally {
    signal.removeEventListener("abort", abort);
    if (typeof window !== "undefined") window.removeEventListener("offline", offline);
    onConnectionChange?.(false);
  }
}
