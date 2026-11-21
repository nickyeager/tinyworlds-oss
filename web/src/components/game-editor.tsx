"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  ArrowUp, Check, CheckCircle2, ChevronDown, ChevronRight,
  Circle, FileText, History, Loader2, Mic, RotateCcw,
  Sparkles, Square, Terminal, X, AlertCircle, ImagePlus, Undo2, WifiOff,
} from "lucide-react";
import {
  cancelGameBuild, getGodotGameHistory, getModificationRunEvents,
  getModificationRuns, getSuggestions, modifyGameStreaming,
  type Engine, type ModificationRunEvent,
} from "@/lib/api";
import {
  durationLabel, editActivities, editEventDetails, editEventKind, editStage, editImages, editMessages, editorImageUrl, loadEditorReference,
  turnFromRun, type EditStatus, type EditTurn, type EditActivity,
} from "@/lib/game-editor";
import { ALLOWED_IMAGE_MIME, MAX_UPLOAD_BYTES } from "@/lib/limits";
import { useAuth } from "@/hooks/use-auth";
import { useEditorDraft } from "@/hooks/use-editor-draft";
import { Response } from "@/components/ui/response";
import { EditorConversation } from "@/components/editor-conversation";
import { EditorImage } from "@/components/editor-image";
import { referencePrompt } from "@/lib/visual-reference";
import { DrawingInput } from "@/components/drawing-input";
import { createClientId } from "@/lib/client-id";

const READY_MESSAGE = "Your change is ready to play.";
const STARTER_IDEAS = ["Make it easier", "Give the world new colors", "Add a surprise"];

interface GameEditorProps {
  engine: Engine;
  gameId: string;
  gameName: string;
  requestedDraft?: { text: string; key: number; hasImage?: boolean; image?: File } | null;
  onBusyChange: (busy: boolean) => void;
  onComplete: () => void;
  onShowHistory: (runId?: string) => void;
  onShowPreview: () => void;
  onComposeFocus: () => void;
}

type SpeechResult = { isFinal: boolean; 0: { transcript: string } };
interface SpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<SpeechResult> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

function Elapsed({ startedAt }: { startedAt?: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  if (!startedAt || !Number.isFinite(Date.parse(startedAt))) return null;
  return <span className="shrink-0 text-xs tabular-nums text-txt-muted">{durationLabel((now - Date.parse(startedAt)) / 1000)}</span>;
}

function ActivityRow({ activity, busy }: { activity: EditActivity; busy: boolean }) {
  const { event, result, summary, state } = activity;
  const failed = state === "failed";
  const details = [editEventDetails(event), result ? editEventDetails(result) : ""].filter(Boolean).join("\n\nResult\n");
  return (
    <details data-tool-name={event.tool_name ?? event.metadata?.tool_name as string | undefined} data-activity-state={state} className={`editor-activity-row group ${failed ? "text-pop-red" : "text-txt-secondary"}`}>
      <summary className="flex cursor-pointer list-none items-start gap-2 py-2 text-xs leading-5">
        {failed ? <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
          : state === "completed" ? <Check className="mt-0.5 size-3.5 shrink-0 text-pop-lime/70" />
            : state === "started" && busy ? <Loader2 className="mt-0.5 size-3.5 shrink-0 animate-spin text-pop-cyan/80" />
              : editEventKind(event) === "tool_use" ? <Terminal className="mt-0.5 size-3.5 shrink-0 text-pop-cyan/80" />
                : <Circle className="mt-1.5 size-2 shrink-0 text-txt-muted" />}
        <span className="min-w-0 flex-1 break-words line-clamp-2">{summary}</span>
        {state === "interrupted" && <span className="shrink-0 text-txt-muted">Stopped</span>}
        <ChevronRight className="mt-1 size-3 shrink-0 text-txt-muted transition-transform group-open:rotate-90" />
      </summary>
      {details && <pre className="mb-2 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-black/20 p-3 font-mono text-[11px] leading-relaxed text-txt-secondary">{details}</pre>}
    </details>
  );
}

function Turn({ turn, engine, gameId, canRetry, onRetry, onReconnect, onPreview, onHistory, onLoadEvents }: {
  engine: Engine;
  gameId: string;
  turn: EditTurn;
  canRetry: boolean;
  onRetry: (turn: EditTurn) => void;
  onReconnect: (turn: EditTurn) => void;
  onPreview: () => void;
  onHistory: (runId?: string) => void;
  onLoadEvents: (runId: string) => Promise<ModificationRunEvent[]>;
}) {
  const [activityOpen, setActivityOpen] = useState(false);
  const [loadingActivity, setLoadingActivity] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [loadedEvents, setLoadedEvents] = useState<ModificationRunEvent[]>([]);
  const [activityFetched, setActivityFetched] = useState(false);
  const busy = turn.status === "running";
  const events = turn.eventsLoaded ? turn.events : loadedEvents;
  const activity = useMemo(() => editActivities(events, turn.status), [events, turn.status]);
  const messages = useMemo(() => editMessages(events, busy ? undefined : turn.response), [events, busy, turn.response]);
  const images = useMemo(() => editImages({ ...turn, events }), [turn, events]);

  return (
    <article data-run-id={turn.runId} data-edit-status={turn.status} className="editor-turn space-y-5" aria-label={`Change: ${turn.instruction}`}>
      <div className="flex gap-3">
        <div className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-xl ${busy ? "bg-pop-yellow/10 text-pop-yellow" : "bg-surface-overlay text-pop-yellow/80"}`}>
          <Sparkles className={`size-3.5 ${busy ? "motion-safe:animate-pulse" : ""}`} />
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="font-bold text-txt-primary">TinyWorlds</span>
            {!busy && typeof turn.duration === "number" && <span className="text-txt-muted">{durationLabel(turn.duration)}</span>}
          </div>
          {messages.map((event, index) => <Response key={index} className="editor-response text-sm leading-relaxed text-txt-secondary">{event.content}</Response>)}
          {(activity.length > 0 || (!busy && turn.runId)) && (
            <div>
              <button
                type="button"
                disabled={loadingActivity}
                onClick={async () => {
                  if (!turn.eventsLoaded && !activityFetched && turn.runId && !activityOpen) {
                    setLoadingActivity(true);
                    setActivityError(null);
                    try {
                      const result = await onLoadEvents(turn.runId);
                      setLoadedEvents(result);
                      setActivityFetched(true);
                    } catch { setActivityError("We couldn’t load the steps. Try again."); }
                    finally { setLoadingActivity(false); }
                  }
                  setActivityOpen(!activityOpen);
                }}
                aria-expanded={activityOpen}
                className="studio-activity-toggle"
              >
                {loadingActivity ? <Loader2 className="size-3 animate-spin" /> : <ChevronDown className={`size-3 transition-transform ${activityOpen ? "" : "-rotate-90"}`} />}
                Steps{activity.length > 0 ? ` · ${activity.length}` : ""}
              </button>
              {activityOpen && <div className="mt-1 border-l border-white/10 pl-3">
                {activity.map((item, index) => <ActivityRow key={index} activity={item} busy={busy} />)}
                {events.filter((event) => editEventKind(event) === "thinking").map((event, index) => <p key={index} className="py-2 text-xs leading-5 text-txt-muted">{event.content}</p>)}
                {activityError && <p className="py-2 text-xs text-pop-red">{activityError}</p>}
              </div>}
            </div>
          )}
          <div className="studio-output-images">{images.map((path) => {
            const src = editorImageUrl(engine, gameId, path);
            return src ? <EditorImage key={path} src={src} name={path.split("/").pop() || "Game picture"} label="Game picture" /> : null;
          })}</div>
          {!busy && (
            <div className="space-y-3">
              <div className={`flex items-start gap-2 text-sm leading-relaxed ${turn.status === "success" ? "text-txt-secondary" : "text-pop-red"}`}>
                {turn.status === "success" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-pop-lime" /> : <AlertCircle className="mt-0.5 size-4 shrink-0" />}
                {turn.status === "success" ? <Response className="editor-response min-w-0 text-sm leading-relaxed">{turn.response || READY_MESSAGE}</Response>
                  : <p className="whitespace-pre-wrap break-words">{turn.response || "That didn’t work. Try again."}</p>}
              </div>
              {turn.changes && turn.changes.length > 0 && <ul className="space-y-1 pl-6 text-sm leading-relaxed text-txt-secondary">{turn.changes.map((change, index) => <li key={index} className="list-disc">{change}</li>)}</ul>}
              {turn.status === "success" && turn.verified && <p className="flex items-center gap-1.5 text-xs text-pop-lime"><CheckCircle2 className="size-3.5" /> Tested and working</p>}
              <div className="flex flex-wrap items-center gap-3 text-xs">
                {turn.status === "success" ? <button onClick={onPreview} className="inline-flex items-center gap-1.5 rounded-full border border-pop-lime/20 bg-pop-lime/5 px-3 py-1.5 text-pop-lime hover:bg-pop-lime/10"><Check className="size-3" /> Play your game</button>
                  : turn.status === "disconnected" ? <button onClick={() => onReconnect(turn)} className="inline-flex items-center gap-1.5 text-pop-yellow hover:text-pop-lime"><RotateCcw className="size-3" /> Reconnect</button>
                    : <button disabled={!canRetry} onClick={() => onRetry(turn)} className="inline-flex items-center gap-1.5 text-txt-secondary hover:text-pop-yellow disabled:opacity-40"><RotateCcw className="size-3" /> {turn.hasImage && !turn.image ? "Use again" : "Try again"}</button>}
                {turn.runId && <button onClick={() => onHistory(turn.runId)} className="text-txt-muted hover:text-txt-primary">Details</button>}
              </div>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

export function GameEditor({ engine, gameId, gameName, requestedDraft, onBusyChange, onComplete, onShowHistory, onShowPreview, onComposeFocus }: GameEditorProps) {
  const { user } = useAuth();
  const draftKey = `tinyworlds:edit-draft:${user?.id ?? "guest"}:${gameId}`;
  const draftState = useEditorDraft(draftKey);
  const { text: draft, image: attachment, setText: setDraft, setImage: setAttachment, replace: replaceDraft, clear: clearDraft } = draftState;
  const [turns, setTurns] = useState<EditTurn[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [attachmentUrl, setAttachmentUrl] = useState<string | null>(null);
  const [online, setOnline] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [recording, setRecording] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const activeRef = useRef<string | null>(null);
  const disconnectRef = useRef<(() => void) | null>(null);
  const mountedRef = useRef(true);
  const loadVersionRef = useRef(0);
  const retryHistoryAfterOfflineRef = useRef(false);
  const historyRetryCountRef = useRef(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const imageUrlsRef = useRef<string[]>([]);
  const suggestionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suggestionAttemptsRef = useRef(0);
  const callbacksRef = useRef({ onBusyChange, onComplete });
  const activeTurn = turns.find((turn) => turn.status === "running" || turn.status === "disconnected");
  const activeRunId = activeTurn?.runId;
  const activeInstruction = activeTurn?.instruction;
  const busy = Boolean(activeTurn);
  const latestTurn = turns.at(-1);
  const readyToPlay = !busy && latestTurn?.status === "success" && latestTurn.verified;

  useEffect(() => { callbacksRef.current = { onBusyChange, onComplete }; }, [onBusyChange, onComplete]);
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  useEffect(() => {
    if (!requestedDraft) return;
    setError(null);
    replaceDraft(requestedDraft.text, { image: requestedDraft.image, hasImage: Boolean(requestedDraft.hasImage), notice: "Copied. Check it, then send." });
    if (requestedDraft.hasImage && !requestedDraft.image) setError("Add your picture again, then send.");
    textareaRef.current?.focus();
    // A requested draft is an explicit action, not an effect of typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedDraft]);
  useEffect(() => {
    const update = () => {
      if (!navigator.onLine) { retryHistoryAfterOfflineRef.current = true; historyRetryCountRef.current = 0; }
      setOnline(navigator.onLine);
    };
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); };
  }, []);
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) { textarea.style.height = "auto"; textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`; }
  }, [draft]);
  useEffect(() => {
    if (!attachment) { setAttachmentUrl(null); return; }
    const url = URL.createObjectURL(attachment);
    setAttachmentUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [attachment]);
  useEffect(() => {
    mountedRef.current = true;
    const imageUrls = imageUrlsRef.current;
    return () => {
      mountedRef.current = false;
      disconnectRef.current?.();
      activeRef.current = null;
      loadVersionRef.current += 1;
      recognitionRef.current?.abort();
      if (suggestionTimerRef.current) clearTimeout(suggestionTimerRef.current);
      imageUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);
  const refreshSuggestions = useCallback(async function refresh(): Promise<void> {
    if (suggestionTimerRef.current) clearTimeout(suggestionTimerRef.current);
    try {
      const result = await getSuggestions(engine, gameId);
      if (!mountedRef.current) return;
      setSuggestions(result.suggestions.slice(0, 3));
      if (result.pending && suggestionAttemptsRef.current++ < 3) {
        suggestionTimerRef.current = setTimeout(() => void refresh(), 5000);
      }
    } catch { /* Suggestions are optional. */ }
  }, [engine, gameId]);

  const updateTurn = useCallback((id: string, update: Partial<EditTurn>) => {
    if (!mountedRef.current) return;
    setTurns((current) => current.map((turn) => turn.id === id ? { ...turn, ...update } : turn));
  }, []);

  const connect = useCallback((turn: EditTurn, resume = false) => {
    if (activeRef.current) return;
    const id = turn.id;
    activeRef.current = id;
    setError(null);
    setReconnecting(false);
    updateTurn(id, { status: "running" });
    const finish = (status: EditStatus, response: string, terminal?: ModificationRunEvent) => {
      if (!mountedRef.current || activeRef.current !== id) return;
      const metadata = terminal?.metadata ?? {};
      updateTurn(id, {
        ...(Array.isArray(metadata.new_screenshots) ? { screenshots: metadata.new_screenshots as string[] } : {}),
        status, response, verified: metadata.has_playable_build === true,
        ...(turn.startedAt && Number.isFinite(Date.parse(turn.startedAt)) ? { duration: (Date.now() - Date.parse(turn.startedAt)) / 1000 } : {}),
        ...(Array.isArray(metadata.changes) ? { changes: metadata.changes as string[] } : {}),
      });
      activeRef.current = null;
      disconnectRef.current = null;
      setReconnecting(false);
      setStopping(false);
      if (status !== "success") {
        setDraft((current) => current || turn.instruction);
        if (turn.image) setAttachment((current) => current ?? turn.image ?? null);
      }
      if (status === "success") {
        callbacksRef.current.onComplete();
        setSuggestions([]);
        suggestionAttemptsRef.current = 0;
        void refreshSuggestions();
      }
    };
    disconnectRef.current = modifyGameStreaming(engine, gameId, turn.instruction, () => {},
      (message) => finish(/connection|acknowledged|already in progress/i.test(message) ? "disconnected" : "failed", message),
      (event) => finish("success", typeof event.metadata?.explanation === "string" && event.metadata.explanation.trim() ? event.metadata.explanation : READY_MESSAGE, event),
      resume ? undefined : turn.image,
      {
        resumeRunId: resume ? turn.runId : undefined,
        onInterrupted: (reason) => finish("interrupted", reason),
        onConnectionChange: (value) => { if (mountedRef.current) setReconnecting(value); },
        onRawEvent: (event) => {
          if (!mountedRef.current || activeRef.current !== id) return;
          setTurns((current) => current.map((item) => {
            if (item.id !== id) return item;
            const events = resume && event.seq === 0 ? [] : item.events;
            const runId = event.event_type === "init" ? event.metadata?.run_id : undefined;
            return {
              ...item, events: [...events, event], eventsLoaded: true,
              ...(typeof runId === "string" ? { runId } : {}),
              ...(event.metadata?.has_image ? { hasImage: true } : {}),
              ...(Array.isArray(event.metadata?.attachments) ? { attachments: event.metadata.attachments as EditTurn["attachments"] } : {}),
            };
          }));
        },
      });
  }, [engine, gameId, refreshSuggestions, updateTurn, setDraft, setAttachment]);

  const loadConversation = useCallback(async () => {
    const version = ++loadVersionRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getModificationRuns(engine, gameId);
      if (!mountedRef.current || version !== loadVersionRef.current) return;
      let loaded = [...result.runs].reverse().map(turnFromRun);
      if (!loaded.length && engine === "godot") {
        const legacy = await getGodotGameHistory(gameId);
        loaded = legacy.map((entry, index) => ({
          id: `legacy-${index}`, instruction: entry.instruction, status: "success" as const,
          response: READY_MESSAGE, changes: entry.changes,
          events: [], eventsLoaded: true,
        }));
      }
      if (!mountedRef.current || version !== loadVersionRef.current) return;
      retryHistoryAfterOfflineRef.current = false;
      historyRetryCountRef.current = 0;
      setTurns(loaded);
      const running = loaded.find((turn) => turn.status === "running");
      if (running) connect(running, true);
      void refreshSuggestions();
      return loaded;
    } catch (error) {
      if (mountedRef.current && version === loadVersionRef.current) setLoadError(error instanceof Error ? error.message : "We couldn’t load your changes.");
    } finally { if (mountedRef.current && version === loadVersionRef.current) setLoading(false); }
  }, [engine, gameId, connect, refreshSuggestions]);
  useEffect(() => { void loadConversation(); }, [loadConversation]);
  useEffect(() => {
    if (!online || !loadError || !retryHistoryAfterOfflineRef.current || activeRef.current || historyRetryCountRef.current >= 3) return;
    // The browser's online event can arrive before its first request succeeds.
    const timer = setTimeout(() => {
      historyRetryCountRef.current++;
      void loadConversation();
    }, Math.min(250 * 2 ** historyRetryCountRef.current, 1000));
    return () => clearTimeout(timer);
  }, [online, loadError, loadConversation]);

  const attach = useCallback((file?: File) => {
    if (!file) return;
    if (!(ALLOWED_IMAGE_MIME as readonly string[]).includes(file.type)) { setError("Pick a PNG, JPG or WebP picture."); return; }
    if (file.size > MAX_UPLOAD_BYTES) { setError("That picture is too big. Pick one under 10 MB."); return; }
    setError(null);
    setAttachment(file);
    textareaRef.current?.focus();
  }, [setAttachment]);

  const startEdit = useCallback((instruction: string, image?: File, clearComposer = false) => {
    if (!instruction.trim() || !online || busy || activeRef.current || loading || loadError || recording) return;
    const imageUrl = image ? URL.createObjectURL(image) : undefined;
    if (imageUrl) imageUrlsRef.current.push(imageUrl);
    const turn: EditTurn = {
      id: createClientId(), instruction: instruction.trim(), status: "running", startedAt: new Date().toISOString(),
      events: [], eventsLoaded: true, image, imageUrl, hasImage: Boolean(image),
    };
    setTurns((current) => [...current, turn]);
    if (clearComposer) clearDraft();
    connect(turn);
    textareaRef.current?.focus();
  }, [online, busy, loading, loadError, recording, connect, clearDraft]);
  const submit = useCallback(() => {
    if (!draftState.ready || draftState.missingReference) return;
    startEdit(draft, attachment ?? undefined, true);
  }, [startEdit, draft, attachment, draftState.ready, draftState.missingReference]);

  const selectIdea = (text: string) => {
    setError(null);
    replaceDraft(text);
    textareaRef.current?.focus();
  };
  const reuseRequest = async (turn: EditTurn) => {
    setError(null);
    let image = turn.image;
    const attachment = turn.attachments?.[0];
    if (!image && attachment) {
      try { image = await loadEditorReference(engine, gameId, attachment); }
      catch { setError("We couldn’t load your picture. Add it again or skip it."); }
    }
    replaceDraft(turn.instruction, { image, hasImage: Boolean(turn.hasImage), notice: "Copied. Check it, then send." });
    textareaRef.current?.focus();
  };

  const stop = useCallback(async () => {
    if (!activeRunId) return;
    setStopping(true);
    setError(null);
    try {
      const cancelled = await cancelGameBuild(gameId);
      if (!mountedRef.current) return;
      if (cancelled) {
        // The server has awaited cancellation. The terminal event may arrive first.
        disconnectRef.current?.();
        const id = activeRef.current;
        if (id) updateTurn(id, { status: "interrupted", response: "Stopped. Change your words and try again." });
        else setTurns((current) => current.map((turn) => turn.status === "disconnected" ? { ...turn, status: "interrupted", response: "Stopped." } : turn));
        activeRef.current = null;
        setReconnecting(false);
        if (activeInstruction) setDraft((current) => current || activeInstruction);
      } else {
        // A finished run can race the click; re-read its persisted outcome.
        disconnectRef.current?.();
        activeRef.current = null;
        const loaded = await loadConversation();
        if (loaded?.some((turn) => turn.runId === activeRunId && turn.status === "success")) {
          callbacksRef.current.onComplete();
        }
      }
    } catch (error) { setError(error instanceof Error ? error.message : "We couldn’t stop. Try again."); }
    finally { if (mountedRef.current) setStopping(false); }
  }, [gameId, updateTurn, loadConversation, activeRunId, activeInstruction, setDraft]);

  const toggleVoice = useCallback(() => {
    if (recording) { recognitionRef.current?.stop(); return; }
    const speechWindow = window as unknown as { SpeechRecognition?: new () => SpeechRecognition; webkitSpeechRecognition?: new () => SpeechRecognition };
    const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Recognition) { setError("Talking works in Chrome and Edge. Type your change here."); return; }
    setError(null);
    const recognition = new Recognition();
    const prefix = draft.trim() ? `${draft.trim()} ` : "";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onresult = (event) => setDraft(prefix + Array.from(event.results).map((result) => result[0].transcript).join(" "));
    recognition.onend = () => { if (mountedRef.current) { setRecording(false); textareaRef.current?.focus(); } };
    recognition.onerror = (event) => {
      if (!mountedRef.current) return;
      setRecording(false);
      if (event.error !== "aborted") setError(event.error === "not-allowed" ? "Turn on your microphone to talk." : "We stopped listening. Your words are still here.");
    };
    recognitionRef.current = recognition;
    try { recognition.start(); setRecording(true); } catch { setError("The microphone didn’t start. Try again."); }
  }, [recording, draft, setDraft]);

  const handleDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    attach(event.dataTransfer.files[0]);
  };

  return (
    <aside aria-label={`Change ${gameName}`} className="editor-chat studio-chat">
      <div className="flex shrink-0 items-center justify-between border-b border-white/[0.06] px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Sparkles className="size-4 text-pop-yellow" />
          <h2 className="text-sm font-semibold tracking-tight">Change your game</h2>
        </div>
        <button onClick={() => onShowHistory()} className="editor-icon-button" aria-label="See past changes" title="Past changes"><History className="size-4" /></button>
      </div>
      <EditorConversation turns={turns} engine={engine} gameId={gameId} loading={loading} busy={busy}
        onSend={(text) => startEdit(text)} onCancel={stop} onReuse={reuseRequest}
        renderTurn={(turn) => <Turn turn={turn} engine={engine} gameId={gameId} canRetry={!busy && !loading && online}
          onRetry={(item) => {
            if (item.hasImage && !item.image) void reuseRequest(item);
            else startEdit(item.instruction, item.image);
          }}
          onReconnect={(item) => { if (item.runId) connect(item, true); else void loadConversation(); }}
          onPreview={onShowPreview} onHistory={onShowHistory}
          onLoadEvents={async (runId) => (await getModificationRunEvents(engine, gameId, runId)).events} />}>
        {loading ? <div className="flex h-full items-center justify-center gap-2 text-sm text-txt-secondary"><Loader2 className="size-4 animate-spin" /> Loading…</div>
            : loadError ? <div className="rounded-xl border border-pop-red/20 p-4 text-sm"><p className="text-pop-red">{loadError}</p><button onClick={() => void loadConversation()} className="mt-3 text-pop-yellow">Try again</button></div>
              : turns.length === 0 ? <div className="editor-welcome flex min-h-full flex-col justify-center pb-5">
                <div className="editor-welcome-mark mb-5 flex size-12 items-center justify-center rounded-2xl border border-pop-yellow/15 bg-pop-yellow/5"><Sparkles className="size-5 text-pop-yellow" /></div>
                <h3 className="max-w-72 text-3xl font-medium leading-tight tracking-tight">What should we change?</h3>
                <div className="editor-welcome-suggestions mt-6 space-y-2">
                  {(suggestions.length ? suggestions : STARTER_IDEAS).map((suggestion, index) => (
                    <button key={suggestion} onClick={() => selectIdea(suggestion)} className="editor-starter group flex w-full items-center gap-3 rounded-xl border border-white/[0.07] px-3.5 py-3 text-left text-sm text-txt-secondary transition-colors hover:border-pop-yellow/25 hover:bg-pop-yellow/[0.03] hover:text-txt-primary">
                      {index === 0 ? <Sparkles className="size-4 shrink-0 text-pop-yellow/70" /> : index === 1 ? <ImagePlus className="size-4 shrink-0 text-pop-cyan/70" /> : <FileText className="size-4 shrink-0 text-pop-pink/70" />}
                      <span className="flex-1">{suggestion}</span><ArrowUp className="size-3.5 rotate-45 text-txt-muted group-hover:text-pop-yellow" />
                    </button>
                  ))}
                </div>
              </div>: null}
      </EditorConversation>
      <div className="editor-compose-area shrink-0 px-4 pb-3 pt-2">
        {turns.length > 0 && suggestions.length > 0 && !busy && <details className="studio-ideas"><summary><Sparkles size={12} /> Ideas<ChevronDown size={12} /></summary><div>{suggestions.map((suggestion) => <button type="button" key={suggestion} onClick={(event) => { selectIdea(suggestion); event.currentTarget.closest("details")?.removeAttribute("open"); }}>{suggestion}</button>)}</div></details>}
        {busy && <div className="editor-build-state mb-2 flex items-center gap-2 px-1 text-xs text-txt-secondary"><Loader2 className="size-3 shrink-0 animate-spin text-pop-yellow" /><span className="min-w-0 flex-1" role="status">{activeTurn?.status === "disconnected" ? "We lost the connection. Tap Reconnect." : reconnecting || !online ? "Reconnecting…" : editStage(activeTurn?.events ?? [])}</span><span aria-hidden="true"><Elapsed startedAt={activeTurn?.startedAt} /></span></div>}
        {readyToPlay && <div className="editor-build-state editor-ready-state mb-2 flex items-center justify-between gap-2 px-1 text-xs"><span className="flex items-center gap-1.5 text-pop-lime"><CheckCircle2 className="size-3.5" /> Your change is ready</span><button type="button" onClick={onShowPreview} className="min-h-8 font-medium text-pop-lime hover:underline">Play now</button></div>}
        {!online && !busy && <p role="status" className="mb-2 flex items-center gap-2 px-1 text-xs text-pop-yellow"><WifiOff className="size-3.5 shrink-0" />{"You're offline. Keep writing."}</p>}
        {error && <div role="alert" className="mb-2 flex items-start gap-2 rounded-lg border border-pop-red/20 bg-pop-red/5 p-3 text-xs leading-5 text-pop-red"><AlertCircle className="mt-0.5 size-3.5 shrink-0" /><span className="flex-1">{error}</span><button onClick={() => setError(null)} aria-label="Close message"><X className="size-3.5" /></button></div>}
        <form
          onSubmit={(event) => { event.preventDefault(); submit(); }}
          className={`editor-composer rounded-2xl border bg-[#20211e] p-3 transition-colors focus-within:border-pop-yellow/40 ${dragging ? "border-pop-yellow" : "border-white/10"}`}
          onDragOver={(event) => { event.preventDefault(); if (event.dataTransfer.types.includes("Files")) setDragging(true); }}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }}
          onDrop={handleDrop}
        >
          {draftState.missingReference && <div className="editor-missing-reference mb-2 rounded-xl border border-pop-yellow/20 bg-pop-yellow/5 p-2.5 text-xs leading-5"><p className="font-medium text-txt-primary">Your picture is missing.</p><p className="truncate text-txt-muted" title={draftState.missingReference}>{draftState.missingReference}</p><div className="mt-1 flex flex-wrap items-center gap-x-3"><button type="button" onClick={() => fileRef.current?.click()} className="min-h-8 text-pop-yellow">Add it again</button><button type="button" onClick={() => { setAttachment(null); setError(null); }} className="min-h-8 text-txt-secondary hover:text-txt-primary">Skip the picture</button></div></div>}
          {attachmentUrl && <div className="editor-reference-chip studio-draft-image"><EditorImage key={attachmentUrl} src={attachmentUrl} name={attachment?.name || "Picture"} label="Picture" alt="Picture to send" compact /><button type="button" onClick={() => setAttachment(null)} aria-label="Remove picture" className="editor-icon-button"><X className="size-4" /></button></div>}
          <label htmlFor={`edit-prompt-${gameId}`} className="sr-only">Tell us what to change</label>
          <textarea
            id={`edit-prompt-${gameId}`} ref={textareaRef} value={draft} rows={2}
            aria-describedby={`edit-help-${gameId}`}
            placeholder={dragging ? "Drop your picture here" : busy ? "Write your next idea…" : "Type your idea…"}
            onChange={(event) => setDraft(event.target.value)}
            onFocus={onComposeFocus}
            onPaste={(event) => {
              const image = Array.from(event.clipboardData.files).find((file) => file.type.startsWith("image/"));
              if (image) { event.preventDefault(); attach(image); }
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
                // Preserve Enter for drafting during a run and for touch keyboards.
                if (busy || (window.matchMedia("(pointer: coarse)").matches && !event.metaKey && !event.ctrlKey)) return;
                event.preventDefault(); submit();
              }
              if (event.key === "Escape" && recording) recognitionRef.current?.stop();
            }}
            className="editor-scroll block max-h-44 min-h-14 w-full resize-none bg-transparent px-1 py-1 text-sm leading-6 text-txt-primary outline-none placeholder:text-txt-muted"
          />
          <div className="mt-2 flex items-center justify-between">
            <div className="flex items-center gap-1">
              <input ref={fileRef} type="file" accept={ALLOWED_IMAGE_MIME.join(",")} className="hidden" aria-label="Picture file" onChange={(event) => { attach(event.target.files?.[0]); event.target.value = ""; }} />
              <DrawingInput onAttach={(file) => { attach(file); if (!draft.trim()) setDraft(referencePrompt(file)); }} />
              <button type="button" onClick={toggleVoice} aria-pressed={recording} className={`editor-icon-button ${recording ? "!bg-pop-red/10 !text-pop-red motion-safe:animate-pulse" : ""}`} aria-label={recording ? "Stop listening" : "Say your change"} title={recording ? "Stop listening" : "Say your change"}>{recording ? <Square className="size-3.5" /> : <Mic className="size-4" />}</button>
              {recording && <span className="ml-1 text-xs text-pop-red" role="status">Listening…</span>}
            </div>
            {busy ? <button type="button" onClick={() => void stop()} disabled={stopping || !activeRunId} aria-label="Stop change" title={activeRunId ? "Stop this change" : "Starting…"} className="editor-send-button flex min-h-10 items-center justify-center gap-2 rounded-full border border-white/15 bg-surface-overlay px-4 text-xs font-medium text-txt-primary transition-colors hover:border-pop-red/40 hover:text-pop-red disabled:opacity-50">{stopping ? <Loader2 className="size-4 animate-spin" /> : <Square className="size-3 fill-current" />}<span>{stopping ? "Stopping…" : "Stop"}</span></button>
              : <button type="submit" disabled={!draft.trim() || !draftState.ready || Boolean(draftState.missingReference) || !online || loading || Boolean(loadError) || recording} aria-label="Send change" title="Send change" className="editor-send-button flex min-h-10 items-center justify-center gap-2 rounded-full bg-pop-yellow px-4 text-xs font-semibold text-surface transition-colors hover:bg-pop-lime disabled:bg-white/10 disabled:text-txt-muted"><span>Send change</span><ArrowUp className="size-3.5" /></button>}
          </div>
        </form>
        <div id={`edit-help-${gameId}`} className="editor-draft-feedback flex min-h-7 flex-wrap items-center justify-between gap-x-2 gap-y-1 px-1 pt-2 text-[11px] text-txt-muted">
          <span role="status">{recording ? "Check your words, then send." : draftState.notice || (draft.trim() && draftState.saved ? "Saved" : "")}</span>
          {draftState.canUndo ? <button type="button" onClick={() => { draftState.undo(); setError(null); textareaRef.current?.focus(); }} className="inline-flex min-h-7 items-center gap-1 text-pop-yellow hover:underline"><Undo2 className="size-3" />Undo</button> : !busy && <span className="editor-keyboard-hint hidden sm:inline">Enter to send</span>}
        </div>
      </div>
    </aside>
  );
}
