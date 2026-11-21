import { afterEach, describe, expect, it, vi } from "vitest";
import { followJsonEventStream, readJsonEventStream } from "../event-stream";
import { createGameStreaming, modifyGameStreaming } from "../api";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

function events(...chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({ start(controller) {
    for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
    controller.close();
  } }));
}

describe("shared event reader", () => {
  it("reads split Unicode, CRLF, multiline data and the final unterminated event", async () => {
    const bytes = new TextEncoder().encode(': ping\r\ndata: {"text":\r\ndata: "🌎"}\r\n\r\ndata: broken\n\ndata: []\n\ndata:{"event_type":"done"}');
    const response = new Response(new ReadableStream({ start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    } }));
    const received = [];
    for await (const event of readJsonEventStream(response)) received.push(event);
    expect(received).toEqual([{ text: "🌎" }, { event_type: "done" }]);
    expect(response.body!.locked).toBe(false);
  });

  it("cancels and unlocks the reader when its consumer stops early", async () => {
    const cancel = vi.fn();
    const response = new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode('data:{"game_id":"godot-test"}\n\n')); }, cancel,
    }));
    for await (const event of readJsonEventStream(response)) { expect(event.game_id).toBe("godot-test"); break; }
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body!.locked).toBe(false);
  });

  it("stops an in-flight reader immediately on abort", async () => {
    const controller = new AbortController();
    const cancel = vi.fn();
    const response = new Response(new ReadableStream({ cancel }));
    const iterator = readJsonEventStream(response, controller.signal);
    const waiting = iterator.next();
    controller.abort();
    expect(await waiting).toMatchObject({ done: true });
    expect(cancel).toHaveBeenCalledOnce();
    expect(response.body!.locked).toBe(false);
  });
});

describe("game stream lifecycle", () => {
  it("submits creation once, resumes with its cursor, deduplicates replay and reads a final event without a newline", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn()
      .mockResolvedValueOnce(events('data:{"seq":0,"event_type":"init","game_id":"bevy-test","engine":"bevy"}\n\n', 'data:{"seq":1,"content":"Building"}\n\n'))
      .mockResolvedValueOnce(events('data:{"seq":1,"content":"Building"}\n\n', 'data:{"seq":2,"event_type":"done","game_id":"bevy-test"}'));
    vi.stubGlobal("fetch", fetcher);
    const event = vi.fn(); const done = vi.fn(); const error = vi.fn(); const init = vi.fn();
    const disconnect = createGameStreaming("A maze", 0, event, error, done, init);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0][1].method).toBe("POST");
    expect(fetcher.mock.calls[1][1].method).toBe("GET");
    expect(fetcher.mock.calls[1][0]).toContain("/api/v1/bevy/games/bevy-test/events/stream?since=1");
    expect(init).toHaveBeenCalledOnce();
    expect(init).toHaveBeenCalledWith("bevy-test", "bevy");
    expect(event).toHaveBeenCalledOnce();
    expect(done).toHaveBeenCalledOnce();
    expect(done).toHaveBeenCalledWith("bevy-test", "bevy");
    expect(error).not.toHaveBeenCalled();
    disconnect();
  });

  it.each(["create", "edit"])("does not submit a second %s when acknowledgement is lost", async (kind) => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValue(events());
    vi.stubGlobal("fetch", fetcher);
    const error = vi.fn(); const done = vi.fn();
    if (kind === "edit") modifyGameStreaming("godot", "godot-test", "Add clouds", vi.fn(), error, done);
    else createGameStreaming("A maze", 0, vi.fn(), error, done);
    await vi.runAllTimersAsync();
    expect(fetcher).toHaveBeenCalledOnce();
    expect(error).toHaveBeenCalledWith(expect.stringContaining("acknowledged"));
    expect(done).not.toHaveBeenCalled();
  });

  it("reattaches an edit to its persisted run without resubmitting it", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn()
      .mockResolvedValueOnce(events('data:{"seq":0,"event_type":"init","metadata":{"run_id":"run123"}}\n\n'))
      .mockResolvedValueOnce(events('data:{"seq":0,"event_type":"init","metadata":{"run_id":"run123"}}\n\ndata:{"seq":1,"event_type":"done","metadata":{"has_playable_build":true}}'));
    vi.stubGlobal("fetch", fetcher);
    const done = vi.fn(); const raw = vi.fn(); const error = vi.fn();
    modifyGameStreaming("godot", "godot-test", "Add clouds", vi.fn(), error, done, undefined, { onRawEvent: raw });
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][0]).toContain("/modifications/run123/events/stream?since=0");
    expect(fetcher.mock.calls[1][1].method).toBe("GET");
    expect(raw).toHaveBeenCalledTimes(2);
    expect(done).toHaveBeenCalledOnce();
    expect(error).not.toHaveBeenCalled();
  });

  it.each(["network", "HTTP 503"])("retries %s failures on GET reconnections within its budget", async (failure) => {
    vi.useFakeTimers();
    const request = vi.fn().mockResolvedValueOnce(events());
    if (failure === "network") request.mockRejectedValueOnce(new TypeError("Network lost"));
    else request.mockResolvedValueOnce(new Response("Unavailable", { status: 503 }));
    request.mockResolvedValueOnce(events('data:{"event_type":"done"}'));
    const controller = new AbortController(); const error = vi.fn(); const received = vi.fn(() => false);
    const run = followJsonEventStream({ signal: controller.signal, request, canResume: () => true, onEvent: received, onError: error, missingAcknowledgement: "missing", reconnectFailure: "disconnected", httpError: "failed", maxReconnects: 2 });
    await vi.advanceTimersByTimeAsync(3000);
    await run;
    expect(request).toHaveBeenCalledTimes(3);
    expect(received).toHaveBeenCalledWith({ event_type: "done" });
    expect(error).not.toHaveBeenCalled();
  });

  it("aborting during backoff prevents another request", async () => {
    vi.useFakeTimers();
    const controller = new AbortController(); const request = vi.fn().mockResolvedValue(events());
    const run = followJsonEventStream({ signal: controller.signal, request, canResume: () => true, onEvent: () => true, onError: vi.fn(), onConnectionChange: (reconnecting) => { if (reconnecting) controller.abort(); }, missingAcknowledgement: "missing", reconnectFailure: "disconnected", httpError: "failed" });
    await vi.runAllTimersAsync();
    await run;
    expect(request).toHaveBeenCalledOnce();
  });

  it("waits for connectivity before opening a stream", async () => {
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    const request = vi.fn().mockResolvedValue(events('data:{"event_type":"done"}'));
    const run = followJsonEventStream({ signal: new AbortController().signal, request, canResume: () => true, onEvent: () => false, onError: vi.fn(), missingAcknowledgement: "missing", reconnectFailure: "disconnected", httpError: "failed" });
    await Promise.resolve();
    expect(request).not.toHaveBeenCalled();
    online.mockReturnValue(true);
    window.dispatchEvent(new Event("online"));
    await run;
    expect(request).toHaveBeenCalledOnce();
  });

  it("reports a broken progress consumer without treating it as a network retry", async () => {
    const request = vi.fn().mockResolvedValue(events('data:{"content":"Working"}'));
    const error = vi.fn();
    await followJsonEventStream({ signal: new AbortController().signal, request, canResume: () => true, onEvent: () => { throw new Error("Rendering failed"); }, onError: error, missingAcknowledgement: "missing", reconnectFailure: "disconnected", httpError: "failed" });
    expect(request).toHaveBeenCalledOnce();
    expect(error).toHaveBeenCalledWith(expect.stringContaining("Unable to display build progress"));
  });
});
