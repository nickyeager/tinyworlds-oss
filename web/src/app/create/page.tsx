"use client";
import { referencePrompt } from "@/lib/visual-reference";
import { DrawingInput } from "@/components/drawing-input";
import { EditorImage } from "@/components/editor-image";

import { Suspense, useState, useCallback, useRef, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { SpeechInput } from "@/components/ui/speech-input";
import { useAuth } from "@/hooks/use-auth";
import {
  transcribeAudio,
  createGameStreaming,
  cancelGameBuild,
  getGodotBuildProgress,
  listAllGames,
  getGenerationCapabilities,
  ObservabilityEvent,
  type Engine,
  type GodotBuildProgress,
} from "@/lib/api";
import { StreamCard, classifyEvent } from "@/lib/stream-cards";
import { renderLayout } from "@/components/build-layouts";
import { SiteNav } from "@/components/site-nav";
import { Loader2, RotateCcw, AlertCircle, Mic, X, ArrowDown } from "lucide-react";

interface LogEntry {
  timestamp: string;
  message: string;
  type: "status" | "tool" | "thinking" | "output" | "error";
}

interface BuildState {
  status: "idle" | "creating" | "error";
  log: LogEntry[];
  error: string | null;
}

const IDLE: BuildState = { status: "idle", log: [], error: null };

const IDEAS = [
  { label: "Maze chase", text: "A glowing maze. Collect all the orbs while 3 ghosts chase you.", color: "pop-yellow" },
  { label: "Rooftop cat", text: "A cat jumps across rooftops at sunset. It can double jump. Watch out for pigeons.", color: "pop-cyan" },
  { label: "Space shooter", text: "A space shooter with 3 kinds of enemies and a big bomb that clears the screen.", color: "pop-pink" },
];

const LOG_COLOR: Record<LogEntry["type"], string> = {
  status: "text-pop-yellow",
  tool: "text-pop-cyan",
  thinking: "text-txt-muted",
  output: "text-txt-secondary whitespace-pre-wrap break-all opacity-70",
  error: "text-pop-red",
};

function formatTime(ts: string) {
  const date = new Date(ts);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function LogLines({ log }: { log: LogEntry[] }) {
  return log.map((entry, i) => (
    <div key={i} className="flex gap-3 py-0.5">
      <span className="shrink-0 text-txt-muted select-none">{formatTime(entry.timestamp)}</span>
      <span className={LOG_COLOR[entry.type]}>{entry.message}</span>
    </div>
  ));
}

const now = () => new Date().toISOString();

export default function CreatePage() {
  return (
    <Suspense fallback={null}>
      <CreatePageInner />
    </Suspense>
  );
}

function CreatePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { ensureToken } = useAuth();
  const [input, setInput] = useState("");
  const [reference, setReference] = useState<File | null>(null);
  const [referenceUrl, setReferenceUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!reference) { setReferenceUrl(null); return; }
    const url = URL.createObjectURL(reference); setReferenceUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [reference]);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const submissionRef = useRef(false);
  const mountedRef = useRef(false);
  const [starting, setStarting] = useState(false);
  const [personalMode, setPersonalMode] = useState(false);
  useEffect(() => {
    let active = true;
    getGenerationCapabilities().then(capabilities => {
      if (!active) return;
      setPersonalMode(Boolean(capabilities.personal_mode));
      if (capabilities.requires_provider_connection) router.replace("/connect");
    }).catch(() => { /* The existing creation error handling covers unavailable backends. */ });
    return () => { active = false; };
  }, [router]);
  const [reconnecting, setReconnecting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const [budgetCents, setBudgetCents] = useState(0);
  const [hasGames, setHasGames] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const logScrollRef = useRef<HTMLDivElement>(null);
  const cardEndRef = useRef<HTMLDivElement>(null);
  const previousLogCountRef = useRef(0);

  const [build, setBuild] = useState<BuildState>(IDLE);
  const cancelStreamRef = useRef<(() => void) | null>(null);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; submissionRef.current = false; cancelStreamRef.current?.(); };
  }, []);
  const [buildingGameId, setBuildingGameId] = useState<string | null>(null);
  // SSE handlers are bound once at stream start with a stale closure over
  // buildingGameId (still null). Mirror into a ref so classifyEvent can
  // read the latest id after the init event arrives — otherwise screenshot
  // cards never resolve their imageUrl.
  const buildingGameIdRef = useRef<string | null>(null);
  // The last idea sent. Survives handleReset so "Try again" can resend it.
  const lastSubmittedPromptRef = useRef<string>("");
  const lastSubmittedImageRef = useRef<File | null>(null);
  const [buildProgress, setBuildProgress] = useState<GodotBuildProgress | null>(null);
  const lastEventTimeRef = useRef<number>(Date.now());

  const [cards, setCards] = useState<StreamCard[]>([]);
  // Developer detail (raw log + file counts) stays hidden until asked for.
  const [showDetails, setShowDetails] = useState(false);
  const [newLogCount, setNewLogCount] = useState(0);

  const isIdle = build.status === "idle";
  const isCreating = build.status === "creating";
  const isError = build.status === "error";

  const scrollLogToBottom = useCallback(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
    setNewLogCount(0);
  }, []);

  const handleLogScroll = useCallback(() => {
    const el = logScrollRef.current;
    if (!el) return;
    const away = el.scrollHeight - el.scrollTop - el.clientHeight > 80;
    if (!away) setNewLogCount(0);
  }, []);

  // New raw-log entries should not move the viewport by themselves.
  useEffect(() => {
    const delta = build.log.length - previousLogCountRef.current;
    previousLogCountRef.current = build.log.length;
    if (delta < 0) setNewLogCount(0);
    else if (delta > 0 && showDetails) setNewLogCount((count) => count + delta);
  }, [build.log.length, showDetails]);

  // Poll build progress when SSE goes quiet (sub-agent execution)
  useEffect(() => {
    // Only Godot has a progress route.
    if (!isCreating || !buildingGameId || !buildingGameId.startsWith("godot-")) return;

    const interval = setInterval(async () => {
      const silentMs = Date.now() - lastEventTimeRef.current;
      if (silentMs < 5000) return;

      try {
        const progress = await getGodotBuildProgress(buildingGameId);
        setBuildProgress(progress);
      } catch {
        // ignore
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [isCreating, buildingGameId]);

  // The Games link only shows once there is a game to see.
  useEffect(() => {
    listAllGames()
      .then((games) => setHasGames(games.length > 0))
      .catch(() => {});
  }, []);

  const resetFeed = useCallback(() => {
    setCards([]);
    setShowDetails(false);
    setNewLogCount(0);
  }, []);

  // Shared SSE-handler block used by both "create new" and "attach to
  // existing build" entry points.
  const buildEventCallbacks = useCallback(() => {
    const onEvent = (event: ObservabilityEvent) => {
      lastEventTimeRef.current = Date.now();
      const ev = event as unknown as Record<string, unknown>;
      const msg = (ev.message as string) || (ev.content as string) || "";
      if (msg) {
        const step = (ev.step as string) || "";
        const streamType = (ev.stream_type as string) || "";
        const type: LogEntry["type"] =
          step === "tool_result" || streamType === "tool_result"
            ? "output"
            : msg.startsWith("Using ") || streamType === "tool_use"
              ? "tool"
              : streamType === "error"
                ? "error"
                : "thinking";
        const timestamp = (ev.timestamp as string) || now();
        setBuild((prev) => ({ ...prev, log: [...prev.log, { timestamp, message: msg, type }] }));
      }
      const card = classifyEvent(event, buildingGameIdRef.current);
      if (card) setCards((prev) => [...prev, card]);
    };
    const onError = (error: string) => {
      submissionRef.current = false;
      setStarting(false);
      setBuild((prev) => ({
        status: "error",
        error,
        log: [...prev.log, { timestamp: now(), message: `Error: ${error}`, type: "error" }],
      }));
    };
    const onDone = (newGameId: string) => {
      submissionRef.current = false;
      setBuildProgress(null);
      router.push(`/games/${newGameId}`);
    };
    const onInit = (initGameId: string) => {
      setBuildingGameId(initGameId);
      buildingGameIdRef.current = initGameId;
      setBuildProgress(null);
      // Stamp the gameId into the URL so refresh / share / network blip
      // lands on a page that can resume from server-persisted state.
      router.replace(`/create?gameId=${initGameId}`);
    };
    return { onEvent, onError, onDone, onInit };
  }, [router]);

  const handleSubmit = useCallback(
    async (text: string, imageOverride?: File | null) => {
      const idea = text.trim();
      if (!idea || submissionRef.current) return;
      submissionRef.current = true;
      setStarting(true);
      setStopError(null);

      lastSubmittedPromptRef.current = idea;
      const image = imageOverride === undefined ? reference : imageOverride;
      lastSubmittedImageRef.current = image;

      const { onEvent, onError, onDone, onInit } = buildEventCallbacks();
      // Ensure we have a token (anonymous if needed) before hitting the auth-gated POST.
      try { await ensureToken(); }
      catch (cause) {
        if (mountedRef.current) onError(cause instanceof Error ? cause.message : "Couldn't start. Try again.");
        return;
      }
      if (!mountedRef.current) return;
      setStarting(false);
      setBuildingGameId(null);
      buildingGameIdRef.current = null;
      setBuild({
        status: "creating",
        log: [{ timestamp: now(), message: `Making game: "${idea}"`, type: "status" }],
        error: null,
      });
      resetFeed();

      cancelStreamRef.current = createGameStreaming(
        idea,
        budgetCents,
        onEvent,
        onError,
        onDone,
        onInit,
        { onConnectionChange: setReconnecting, image: image ?? undefined },
      );
      setInput("");
    },
    [buildEventCallbacks, ensureToken, budgetCents, reference, resetFeed]
  );

  // Attach mode: if the page loads with ?gameId=X in the URL, reattach
  // to the resume endpoint instead of asking for a fresh idea. Survives
  // refresh / share / network blip.
  useEffect(() => {
    const attachId = searchParams.get("gameId");
    if (!attachId) return;
    if (build.status !== "idle") return;
    submissionRef.current = true;
    const attachEngine: Engine = attachId.startsWith("bevy-") ? "bevy" : "godot";
    setBuild({
      status: "creating",
      log: [{ timestamp: now(), message: `Reattaching to ${attachId}`, type: "status" }],
      error: null,
    });
    setBuildingGameId(attachId);
    buildingGameIdRef.current = attachId;
    resetFeed();
    const { onEvent, onError, onDone, onInit } = buildEventCallbacks();
    cancelStreamRef.current = createGameStreaming(
      null,
      null,
      onEvent,
      onError,
      onDone,
      onInit,
      { attachGameId: attachId, attachEngine, onConnectionChange: setReconnecting },
    );
    // Run once on mount only; subsequent renders must not re-attach.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleVoiceRecording = useCallback(
    async (blob: Blob) => {
      try {
        const authToken = await ensureToken();
        const result = await transcribeAudio(blob, authToken);
        if (result.transcript) {
          setInput(result.transcript);
          await handleSubmit(result.transcript);
        }
      } catch (err) {
        console.error("Transcription failed:", err);
      }
    },
    [ensureToken, handleSubmit]
  );

  const handleReset = useCallback(() => {
    setReference(null);
    cancelStreamRef.current?.();
    cancelStreamRef.current = null;
    submissionRef.current = false;
    setStarting(false);
    setReconnecting(false);
    setStopError(null);
    setBuildingGameId(null);
    buildingGameIdRef.current = null;
    router.replace("/create");
    setBuild(IDLE);
    setInput("");
    resetFeed();
  }, [router, resetFeed]);

  const handleCancel = useCallback(async () => {
    const gameId = buildingGameIdRef.current;
    if (!gameId || stopping) return;
    setStopping(true);
    setStopError(null);
    try {
      const stopped = await cancelGameBuild(gameId);
      if (!mountedRef.current) return;
      if (!stopped) { cancelStreamRef.current?.(); router.push(`/games/${gameId}`); return; }
      handleReset();
      setInput(lastSubmittedPromptRef.current);
    } catch (cause) { if (mountedRef.current) setStopError(cause instanceof Error ? cause.message : "Couldn't stop. Try again."); }
    finally { if (mountedRef.current) setStopping(false); }
  }, [handleReset, router, stopping]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.nativeEvent.keyCode !== 229 && !window.matchMedia("(pointer: coarse)").matches) {
      e.preventDefault();
      handleSubmit(input);
    }
  };

  const textButton = "flex items-center gap-1.5 font-mono text-xs font-bold uppercase tracking-wider text-txt-muted transition-colors cursor-pointer disabled:cursor-default disabled:opacity-40";

  return (
    <div className="flex min-h-screen flex-col bg-surface text-txt-primary selection:bg-pop-yellow/30">
      <SiteNav>
        {personalMode && <Link href="/connect" className="text-sm font-bold text-txt-secondary hover:text-pop-yellow">AI connection</Link>}
        {hasGames && (
          <Link
            href="/games"
            className="text-sm font-bold uppercase tracking-wider text-txt-secondary transition-colors hover:text-pop-yellow"
          >
            Games
          </Link>
        )}
      </SiteNav>

      <main className="flex flex-1 flex-col items-center justify-center px-6 pb-16">
        {/* ============ IDLE STATE ============ */}
        {isIdle && (
          <div className="flex w-full max-w-2xl flex-col items-center gap-10">
            <h1 className="text-center font-[family-name:var(--font-heading)] text-5xl font-bold leading-tight">
              What game do you want to make?
            </h1>

            <div className="w-full rounded-lg bg-surface-raised brutal-border brutal-shadow-yellow p-5">
              <textarea
                ref={promptRef}
                aria-label="Your game idea"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="A cat jumping between rooftops at sunset…"
                rows={3}
                className="w-full resize-none bg-transparent text-base font-medium leading-relaxed text-txt-primary placeholder-txt-muted outline-none mb-4"
              />
              {referenceUrl && <div className="mb-3 flex items-center gap-3"><EditorImage src={referenceUrl} name={reference?.name || "Drawing"} label="Your picture" alt="Your picture for the new game" compact /><button type="button" aria-label="Remove picture" onClick={() => setReference(null)} className="min-h-10 text-sm text-txt-secondary cursor-pointer">Remove</button></div>}
              <DrawingInput onAttach={(file) => { setReference(file); if (!input.trim()) setInput(referencePrompt(file, false)); }} />
              <details className="mb-4 text-sm text-txt-secondary">
                <summary className="cursor-pointer py-2">{budgetCents ? `Asset budget: $${(budgetCents / 100).toFixed(2)}` : "Options"}</summary>
                <div className="flex flex-wrap items-center gap-3 pt-2">
                  <label className="flex items-center gap-2 text-sm font-bold text-txt-secondary">
                    Asset budget (cents)
                    <input
                      type="number"
                      min={0}
                      max={10000}
                      step={1}
                      value={budgetCents}
                      onChange={(event) => setBudgetCents(Math.min(10000, Math.max(0, Math.trunc(Number(event.target.value) || 0))))}
                      className="w-24 rounded-md bg-surface px-3 py-2 brutal-border text-txt-primary"
                    />
                  </label>
                  <p className="text-xs text-txt-muted">Covers generated pictures and 3D models. 0 uses your drawings and free assets.</p>
                </div>
              </details>
              <div className="flex items-center justify-between">
                <SpeechInput
                  onSpeechEnd={handleVoiceRecording}
                  state="idle"
                  size="icon"
                  icon={<Mic className="h-4 w-4 text-txt-muted" />}
                  className="h-10 w-10 rounded-md bg-surface-overlay brutal-border text-txt-muted hover:text-pop-pink hover:border-pop-pink transition-all cursor-pointer"
                  enableSpacebarShortcut={true}
                />
                <button
                  onClick={() => handleSubmit(input)}
                  disabled={!input.trim() || starting}
                  className="rounded-md bg-pop-yellow px-7 py-2.5 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime disabled:opacity-30 cursor-pointer disabled:cursor-default"
                >
                  {starting ? "Starting…" : "Make my game"}
                </button>
              </div>
            </div>

            <details className="w-full text-center text-sm text-txt-secondary">
              <summary className="cursor-pointer py-2">Need an idea?</summary>
              <div className="mt-3 flex flex-wrap justify-center gap-3">
                {IDEAS.map(({ label, text, color }) => (
                  <button
                    key={label}
                    title={text}
                    onClick={() => {
                      setInput(text);
                      promptRef.current?.focus();
                    }}
                    className={`brutal-chip rounded-md bg-surface-raised border-2 border-${color}/40 px-4 py-2 text-sm font-bold text-${color} cursor-pointer`}
                    style={{
                      boxShadow: `3px 3px 0 color-mix(in srgb, var(--${color}) 30%, transparent)`,
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </details>
          </div>
        )}

        {/* ============ CREATING STATE ============ */}
        {isCreating && (
          <div className="flex w-full max-w-7xl flex-col items-center gap-4">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
              <h2 className="font-[family-name:var(--font-heading)] text-xl font-bold">
                {reconnecting ? "Reconnecting…" : "Making your game…"}
              </h2>
            </div>

            {reconnecting && <p role="status" className="text-sm text-txt-secondary">Your game is still being made.</p>}
            {stopError && <p role="alert" className="text-sm text-pop-red">{stopError}</p>}

            {/* The shared feed has its own pause controls; this page never pauses. */}
            {renderLayout("two-pane", { cards, cardEndRef })}

            <div className="flex items-center gap-3">
              <button onClick={() => setShowDetails((shown) => !shown)} aria-expanded={showDetails} className={`${textButton} hover:text-txt-primary`}>
                {showDetails ? "Hide details" : "Show details"}
              </button>
              <span className="text-[var(--card-border)]">|</span>
              <button onClick={() => void handleCancel()} disabled={!buildingGameId || stopping} className={`${textButton} hover:text-pop-red`}>
                <X className="h-3 w-3" />
                {stopping ? "Stopping…" : "Stop"}
              </button>
            </div>

            {/* Developer detail: file counts, task list and the raw log. */}
            {showDetails && buildProgress && (
              <div className="w-full rounded-lg brutal-card bg-surface-raised px-4 py-3">
                <div className="grid grid-cols-4 gap-3 mb-2">
                  {[
                    { label: "scripts", value: buildProgress.scripts },
                    { label: "scenes", value: buildProgress.scenes },
                    { label: "screenshots", value: buildProgress.screenshots },
                    { label: "assets", value: buildProgress.assets },
                  ].map(({ label, value }) => (
                    <div key={label} className="text-center">
                      <div className="font-[family-name:var(--font-heading)] text-xl font-bold text-txt-primary">
                        {value}
                      </div>
                      <div className="font-mono text-xs font-bold uppercase text-txt-muted">
                        {label}
                      </div>
                    </div>
                  ))}
                </div>
                {buildProgress.tasks.length > 0 && (
                  <div className="border-t-2 border-[var(--card-border)] pt-2 space-y-1">
                    {buildProgress.tasks.map((task) => (
                      <div key={task.number} className="flex items-center gap-2 font-mono text-xs">
                        <span
                          className={
                            task.status === "done"
                              ? "text-pop-lime"
                              : task.status === "in_progress"
                                ? "text-pop-yellow"
                                : "text-txt-muted"
                          }
                        >
                          {task.status === "done" ? "●" : task.status === "in_progress" ? "◐" : "○"}
                        </span>
                        <span className="text-txt-secondary font-bold">
                          {task.number}. {task.name}
                        </span>
                        <span className="text-txt-muted">{task.status}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {showDetails && (
              <div className="w-full rounded-lg brutal-card overflow-hidden bg-surface">
                <div
                  ref={logScrollRef}
                  onScroll={handleLogScroll}
                  className="relative h-[640px] overflow-y-auto p-4 font-mono text-xs leading-relaxed"
                >
                  <LogLines log={build.log} />
                  <div ref={logEndRef} />
                  {newLogCount > 0 && (
                    <button
                      onClick={scrollLogToBottom}
                      className="sticky bottom-2 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border-2 border-[var(--card-border)] bg-surface-raised px-3 py-1.5 font-mono text-xs font-bold uppercase tracking-wider text-pop-yellow shadow-[3px_3px_0_#0a0a0a] transition-colors hover:text-pop-lime cursor-pointer"
                    >
                      <ArrowDown className="h-3.5 w-3.5" />
                      {newLogCount} new
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ============ ERROR STATE ============ */}
        {isError && (
          <div className="flex w-full max-w-3xl flex-col items-center gap-6">
            <div className="text-center">
              <AlertCircle className="mx-auto mb-2 h-8 w-8 text-pop-red" />
              <h2 className="font-[family-name:var(--font-heading)] text-2xl font-bold text-pop-red">
                That didn’t work
              </h2>
              <p className="mt-2 text-sm font-bold text-txt-secondary">
                {build.error}
              </p>
            </div>

            {/* When init already fired, the server-side build may still be
                running. Point at the game page instead of starting over. */}
            {buildingGameId && (
              <div className="flex flex-col items-center gap-3 text-center">
                <p className="text-sm text-txt-secondary">Your game may still be getting made.</p>
                <Link
                  href={`/games/${buildingGameId}`}
                  className="rounded-md bg-pop-yellow px-5 py-2 text-sm font-bold uppercase tracking-wider text-surface brutal-border transition-colors hover:bg-pop-lime"
                >
                  Open my game
                </Link>
              </div>
            )}

            <div className="flex items-center gap-4">
              {lastSubmittedPromptRef.current && (
                <button
                  onClick={() => {
                    const prompt = lastSubmittedPromptRef.current;
                    const image = lastSubmittedImageRef.current;
                    handleReset();
                    setReference(image);
                    // Wait a tick so the new submit doesn't race the
                    // state-clearing batch above.
                    setTimeout(() => handleSubmit(prompt, image), 0);
                  }}
                  className="flex items-center gap-1.5 rounded-md bg-pop-yellow/15 border-2 border-pop-yellow/40 px-3 py-1.5 font-mono text-sm font-bold uppercase tracking-wider text-pop-yellow transition-colors hover:bg-pop-yellow/25 cursor-pointer"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Try again
                </button>
              )}
              <button
                onClick={handleReset}
                className="font-mono text-sm font-bold uppercase tracking-wider text-txt-secondary transition-colors hover:text-txt-primary cursor-pointer"
              >
                Start over
              </button>
            </div>

            {build.log.length > 0 && (
              <details className="w-full">
                <summary className="cursor-pointer text-center text-sm text-txt-muted">Show details</summary>
                <div className="mt-2 max-h-60 overflow-y-auto rounded-lg border-2 border-pop-red bg-pop-red/10 p-4 font-mono text-xs leading-relaxed">
                  <LogLines log={build.log} />
                </div>
              </details>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
