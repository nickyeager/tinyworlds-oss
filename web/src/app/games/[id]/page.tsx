"use client";

/* eslint-disable @next/next/no-img-element -- Game media uses authenticated asset URLs. */

import { useState, useEffect, useRef, useCallback, useMemo, type KeyboardEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import { useGameHistory } from "@/hooks/use-game-history";
import {
  API_BASE,
  authenticatedAssetUrl,
  getGameInfo,
  getGameMedia,
  getPlayUrl,
  getVideoUrl,
  type Engine,
  type GodotGameInfo,
  type GameMedia,
  type ModificationRunEvent,
  type ObservabilityEvent,
} from "@/lib/api";
import { StreamCard, classifyEvent } from "@/lib/stream-cards";
import { BuildLogReplay } from "@/components/build-log-replay";
import { GameEditor } from "@/components/game-editor";
import { EditorPanel } from "@/components/editor-panel";
import { durationLabel, editRequest, loadEditorReference, whenLabel } from "@/lib/game-editor";
import { StreamCardView } from "@/components/stream-cards";
import { GameCompanion } from "@/components/game-companion";
import { DrawingInput } from "@/components/drawing-input";
import { referencePrompt } from "@/lib/visual-reference";
import { SiteNav } from "@/components/site-nav";
import { GameNameControl } from "@/components/game-name-control";
import { ShareLinkButton } from "@/components/share-link-button";
import {
  Play,
  Maximize2,
  ArrowLeft,
  Loader2,
  AlertCircle,
  Image as ImageIcon,
  Pause,
  Gamepad2,
  Images,
  ChevronLeft,
  ChevronRight,
  RotateCcw,
  History,
  Sparkles,
  PanelLeftClose,
  PanelLeftOpen,
  RotateCw,
} from "lucide-react";

type ViewTab = "play" | "gallery" | "video" | "buildlog" | "modifications";

function handleTabKeys(event: KeyboardEvent<HTMLDivElement>) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
  const index = tabs.indexOf(event.target as HTMLButtonElement);
  if (index < 0) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
    : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next]?.focus();
  tabs[next]?.click();
}

/** A plain word and a color for a past change's status. */
function StatusChip({ status }: { status?: string | null }) {
  const normalized = (status || "").toLowerCase();
  const [label, classes] =
    ["ok", "success", "completed", "complete", "done"].includes(normalized) ? ["Done", "border-pop-lime bg-pop-lime/10 text-pop-lime"]
    : ["failed", "error", "crashed"].includes(normalized) ? ["Didn’t work", "border-pop-red bg-pop-red/10 text-pop-red"]
    : ["running", "pending"].includes(normalized) ? ["Working", "border-pop-yellow bg-pop-yellow/10 text-pop-yellow"]
    : normalized === "partial" ? ["Not finished", "border-pop-yellow bg-pop-yellow/10 text-pop-yellow"]
    : [normalized === "interrupted" ? "Stopped" : "Unknown", "border-[var(--card-border)] bg-surface-raised text-txt-secondary"];
  return <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold ${classes}`}>{label}</span>;
}

function modificationEventToCard(
  event: ModificationRunEvent,
  idx: number,
  gameId: string,
): StreamCard | null {
  const metadata = event.metadata ?? {};
  const eventType = typeof event.event_type === "string" ? event.event_type : "CLIStreamEvent";
  let streamType =
    typeof event.stream_type === "string"
      ? event.stream_type
      : typeof event.type === "string"
        ? event.type
        : undefined;

  if (!streamType) {
    if (eventType === "done") streamType = "complete";
    else if (eventType === "failed" || eventType === "crashed") streamType = "error";
    else streamType = "status";
  }

  const content =
    typeof event.content === "string"
      ? event.content
      : typeof event.message === "string"
        ? event.message
        : typeof event.error === "string"
          ? event.error
          : eventType === "init"
            ? "Started"
            : eventType === "done"
              ? "Done"
              : "";

  return classifyEvent(
    {
      timestamp: typeof event.timestamp === "string" ? event.timestamp : new Date().toISOString(),
      level: streamType === "error" ? "error" : "info",
      category: "user",
      service:
        typeof event.service === "string"
          ? event.service
          : "game_modification",
      event_type: "CLIStreamEvent",
      stream_type: streamType as ObservabilityEvent["stream_type"],
      content,
      tool_name:
        typeof event.tool_name === "string"
          ? event.tool_name
          : typeof metadata.tool_name === "string"
            ? metadata.tool_name
            : undefined,
      tool_input:
        event.tool_input ??
        (metadata.input && typeof metadata.input === "object"
          ? (metadata.input as Record<string, unknown>)
          : undefined),
      _replay_idx: idx,
    } as unknown as ObservabilityEvent,
    gameId,
  );
}

export default function GamePage() {
  const params = useParams();
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const gameId = params.id as string;
  // Derive engine from id prefix — backend mints `bevy-<hex8>` /
  // `godot-<hex8>`, so the engine is fixed at this URL.
  const engine: Engine = gameId.startsWith("bevy-") ? "bevy" : "godot";
  const [game, setGame] = useState<GodotGameInfo | null>(null);
  const canEdit = game?.can_edit === true;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modifying, setModifying] = useState(false);
  const [isGamePaused, setIsGamePaused] = useState(false);
  const [previewRevision, setPreviewRevision] = useState(0);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [previewProgress, setPreviewProgress] = useState<number | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewInteractive, setPreviewInteractive] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<"chat" | "preview">("chat");
  const [chatHidden, setChatHidden] = useState(false);
  const [editDraft, setEditDraft] = useState<{ text: string; key: number; hasImage?: boolean; image?: File } | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const viewport = window.visualViewport;
    const workspace = workspaceRef.current;
    if (!viewport || !workspace) return;
    const resize = () => workspace.style.setProperty("--editor-viewport-height", `${viewport.height}px`);
    resize();
    viewport.addEventListener("resize", resize);
    return () => viewport.removeEventListener("resize", resize);
  }, [loading]);

  const [activeTab, setActiveTab] = useState<ViewTab>("play");

  const [media, setMedia] = useState<GameMedia | null>(null);
  const [galleryIndex, setGalleryIndex] = useState(0);
  const [requestedRunId, setSelectedModificationRunId] = useState<string | null>(null);
  const history = useGameHistory({ engine, gameId, ownerKey: user?.id ?? "visitor", canEdit: canEdit && !authLoading && isAuthenticated, activeTab, requestedRunId });
  const { selectedRunId: selectedModificationRunId } = history;
  const modificationRuns = history.modifications.data?.runs ?? [];
  const modificationRunsState = history.modifications.status;
  const modificationRunsError = history.modifications.error;
  const loadModificationRuns = history.modifications.refresh;
  const modificationEvents = history.detail.data?.events ?? null;
  const modificationEventsSummary = history.detail.data?.summary ?? null;
  const modificationEventsState = history.detail.status;
  const modificationEventsError = history.detail.error;

  useEffect(() => {
    if (engine !== "godot" || !game?.has_export) return;
    let ready = false;
    let failed = false;
    const expectedOrigin = new URL(getPlayUrl(engine, gameId, true), window.location.href).origin;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow || event.origin !== expectedOrigin) return;
      if (event.data?.type !== "tinyworlds:preview-status") return;
      if (event.data.state === "ready") {
        ready = true;
        setPreviewLoading(false);
        setPreviewError(null);
      } else if (event.data.state === "error" && !ready) {
        failed = true;
        setPreviewLoading(false);
        setPreviewError("Your game didn’t start. Try again.");
      } else if (event.data.state === "loading" && !ready) {
        const progress = event.data.progress;
        if (typeof progress === "number" && Number.isFinite(progress)) setPreviewProgress(Math.max(0, Math.min(100, progress)));
      }
    };
    window.addEventListener("message", onMessage);
    iframeRef.current?.contentWindow?.postMessage({ action: "tinyworlds:preview-status-request" }, expectedOrigin);
    const timer = window.setTimeout(() => {
      if (!ready && !failed) {
        setPreviewLoading(false);
        setPreviewError("Your game is slow to start. Try again.");
      }
    }, 45000);
    return () => { window.removeEventListener("message", onMessage); window.clearTimeout(timer); };
  }, [engine, gameId, game?.has_export, previewRevision]);

  const sendGameMessage = useCallback((action: "pause" | "resume") => {
    iframeRef.current?.contentWindow?.postMessage({ action }, "*");
  }, []);

  const pauseGame = useCallback(() => {
    sendGameMessage("pause");
    setIsGamePaused(true);
  }, [sendGameMessage]);

  const reloadPreview = useCallback(() => {
    setPreviewLoading(true);
    setPreviewProgress(null);
    setPreviewError(null);
    setIsGamePaused(false);
    setPreviewRevision((revision) => revision + 1);
  }, []);

  const handleEditComplete = useCallback(() => {
    reloadPreview();
    getGameInfo(engine, gameId).then(setGame).catch(() => {});
    loadModificationRuns();
    setMedia(null);
    setGalleryIndex(0);
    getGameMedia(engine, gameId).then(setMedia).catch(() => {});
  }, [engine, gameId, reloadPreview, loadModificationRuns]);

  const focusComposer = useCallback(() => {
    setPreviewInteractive(false);
    iframeRef.current?.contentWindow?.postMessage({ action: "tinyworlds:focus-editor" }, "*");
  }, []);

  const activatePreview = useCallback(() => {
    setPreviewInteractive(true);
    sendGameMessage("resume");
    setIsGamePaused(false);
    requestAnimationFrame(() => {
      iframeRef.current?.contentWindow?.postMessage({ action: "tinyworlds:activate-preview" }, "*");
      iframeRef.current?.focus();
    });
  }, [sendGameMessage]);

  const showPreview = useCallback(() => {
    setActiveTab("play");
    setMobilePanel("preview");
    activatePreview();
  }, [activatePreview]);

  const showEditHistory = useCallback((runId?: string) => {
    if (runId) setSelectedModificationRunId(runId);
    setActiveTab("modifications");
    setMobilePanel("preview");
  }, []);

  useEffect(() => {
    if (!gameId || authLoading) return;
    getGameInfo(engine, gameId)
      .then(setGame)
      .catch(() => setError("We can’t find that game."))
      .finally(() => setLoading(false));
  }, [gameId, engine, authLoading, isAuthenticated]);

  useEffect(() => {
    if (canEdit) getGameMedia(engine, gameId).then(setMedia).catch(() => {});
  }, [canEdit, engine, gameId]);

  const selectedModificationRun =
    modificationRuns.find((run) => run.run_id === selectedModificationRunId) ?? null;
  const selectedModificationDetail =
    modificationEventsSummary?.run_id === selectedModificationRunId
      ? modificationEventsSummary
      : selectedModificationRun;
  const selectedChangedFiles = selectedModificationDetail?.changed_files ?? [];
  const selectedNewScreenshots = selectedModificationDetail?.new_screenshots ?? [];
  const selectedVerificationFailures = selectedModificationDetail?.verification_failures ?? [];

  const modificationCards = useMemo<StreamCard[]>(
    () => (modificationEvents ?? []).flatMap((event, idx) => modificationEventToCard(event, idx, gameId) ?? []),
    [modificationEvents, gameId],
  );

  if (loading) {
    return (
      <div role="status" aria-label="Loading" className="flex min-h-screen items-center justify-center bg-surface">
        <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
      </div>
    );
  }

  if (error || !game) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-surface text-txt-primary">
        <AlertCircle className="h-8 w-8 text-pop-red" />
        <p className="text-base font-bold text-txt-secondary">
          {error || "We can’t find that game."}
        </p>
        <Link
          href="/games"
          className="rounded-md bg-pop-yellow px-5 py-2 text-sm font-bold text-surface brutal-border transition-colors hover:bg-pop-lime"
        >
          See all games
        </Link>
      </div>
    );
  }

  return (
    <div ref={workspaceRef} style={{ height: "var(--editor-viewport-height, 100dvh)" }} className="game-workspace flex h-dvh min-h-0 flex-col bg-surface text-txt-primary selection:bg-pop-yellow/30 overflow-hidden">
      <SiteNav compact>
        <GameNameControl engine={engine} game={game} canEdit={!authLoading && canEdit} onRename={setGame} onDeleted={() => router.push("/games")} />
        <Link
          href="/games"
          className="flex items-center gap-1.5 text-sm font-bold text-txt-secondary transition-colors hover:text-pop-yellow shrink-0"
          aria-label="All games"
        >
          <ArrowLeft className="h-4 w-4" />
          <span className="hidden sm:inline">All games</span>
        </Link>
      </SiteNav>

      {canEdit && <div className="flex shrink-0 gap-1 border-b border-white/[0.07] px-3 py-2 md:hidden" role="tablist" aria-label="Change or play" onKeyDown={handleTabKeys}>
        <button role="tab" tabIndex={mobilePanel === "chat" ? 0 : -1} aria-selected={mobilePanel === "chat"} onClick={() => setMobilePanel("chat")} className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-sm ${mobilePanel === "chat" ? "bg-pop-yellow/10 text-pop-yellow" : "text-txt-secondary"}`}><Sparkles className="size-4" /> Change {modifying && <span className="size-1.5 rounded-full bg-pop-yellow motion-safe:animate-pulse" />}</button>
        <button role="tab" tabIndex={mobilePanel === "preview" ? 0 : -1} aria-selected={mobilePanel === "preview"} onClick={() => setMobilePanel("preview")} className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-sm ${mobilePanel === "preview" ? "bg-pop-yellow/10 text-pop-yellow" : "text-txt-secondary"}`}><Gamepad2 className="size-4" /> Play</button>
      </div>}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {!authLoading && canEdit && <EditorPanel className={`${mobilePanel === "chat" ? "flex" : "hidden"} ${chatHidden ? "md:hidden" : "md:flex"} min-h-0 w-full shrink-0 flex-col border-r border-white/[0.07]`}>
          <GameEditor key={gameId} engine={engine} gameId={gameId} gameName={game.name || gameId}
            onBusyChange={setModifying} onComplete={handleEditComplete} requestedDraft={editDraft}
            onShowHistory={showEditHistory} onShowPreview={showPreview} onComposeFocus={focusComposer} />
        </EditorPanel>}

        {/* Right: the game and its other views */}
        <main aria-label="Game" className={`${canEdit && mobilePanel !== "preview" ? "hidden" : "flex"} md:flex min-w-0 min-h-0 flex-1 flex-col overflow-hidden bg-[#121411]`}>
          {/* View picker + game buttons */}
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/[0.07] px-3 py-2.5 lg:px-5">
            <div className="flex min-w-0 items-center gap-1">
              {canEdit && <button onClick={() => setChatHidden((hidden) => !hidden)} className="editor-icon-button mr-2 hidden md:flex" aria-label={chatHidden ? "Show chat" : "Hide chat"} title={chatHidden ? "Show chat" : "Hide chat"}>{chatHidden ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}</button>}
              {(canEdit || game.has_video) && (
                <select aria-label="Game view" value={activeTab} onChange={(event) => setActiveTab(event.target.value as ViewTab)}
                  className="min-h-10 max-w-44 cursor-pointer rounded-lg bg-surface-raised px-2 text-sm text-txt-primary">
                  <option value="play">Play</option>
                  {canEdit && <option value="gallery">Pictures</option>}
                  {game.has_video && <option value="video">Video</option>}
                  {canEdit && <option value="buildlog">How it was made</option>}
                  {canEdit && <option value="modifications">Past changes</option>}
                </select>
              )}
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-1.5">
              {game.has_export && activeTab === "play" && <button onClick={reloadPreview} className="editor-icon-button" aria-label="Restart game" title="Restart game"><RotateCw className="size-3.5" /></button>}
              {game.has_export && activeTab === "play" && (
                <button
                  onClick={isGamePaused ? activatePreview : pauseGame}
                  className={`flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs transition-colors ${
                    isGamePaused
                      ? "bg-pop-yellow text-surface hover:bg-pop-lime"
                      : "bg-surface-raised text-txt-secondary hover:bg-surface-overlay"
                  }`}
                >
                  {isGamePaused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
                  {isGamePaused ? "Resume" : "Pause"}
                </button>
              )}
              {game.has_export && activeTab === "play" && (
                <button
                  onClick={() => window.open(getPlayUrl(engine, gameId), "_blank")}
                  className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs text-txt-secondary transition-colors hover:bg-white/5"
                >
                  <Maximize2 className="h-3.5 w-3.5" />
                  Full screen
                </button>
              )}
              <ShareLinkButton title={game.name || "TinyWorlds game"} />
            </div>
          </div>

          <div className="relative min-h-0 flex-1 overflow-auto flex items-center justify-center p-3 lg:p-6">
            {/* Play. The iframe stays mounted while other views show. */}
            {game.has_export ? (
              <div className={activeTab === "play" ? "editor-preview flex h-full w-full flex-col items-center justify-center gap-4" : "hidden"}>
                <div className="editor-game-frame relative w-full max-w-5xl overflow-hidden rounded-xl border border-white/10 bg-black shadow-2xl"
                  style={{ touchAction: "none", overscrollBehavior: "contain", aspectRatio: "4/3", maxHeight: "100%" }}>
                  <iframe key={`${gameId}:${previewRevision}`} title={game.name || "Your game"}
                    sandbox="allow-scripts allow-same-origin allow-pointer-lock" ref={iframeRef}
                    inert={!previewInteractive || activeTab !== "play"} tabIndex={previewInteractive ? 0 : -1}
                    src={getPlayUrl(engine, gameId, true)}
                    className="absolute inset-0 h-full w-full border-0" allow="autoplay; fullscreen; cross-origin-isolated" scrolling="no"
                    onLoad={() => {
                      if (engine !== "godot") setPreviewLoading(false);
                      iframeRef.current?.contentWindow?.postMessage({ action: "tinyworlds:preview-status-request" }, new URL(getPlayUrl(engine, gameId, true), window.location.href).origin);
                      iframeRef.current?.contentWindow?.postMessage({ action: previewInteractive ? "tinyworlds:activate-preview" : "tinyworlds:focus-editor" }, "*");
                    }} onError={() => { setPreviewLoading(false); setPreviewError("Your game didn’t load. Try again."); }} style={{ touchAction: "none" }} />
                  {!previewInteractive && !previewLoading && !previewError && <button type="button" aria-label="Play game" onClick={activatePreview} className="absolute inset-0 flex items-center justify-center bg-black/10 focus-visible:!outline-offset-[-4px]"><span className="flex items-center gap-2 rounded-full bg-pop-yellow px-6 py-3 font-bold text-surface shadow-lg transition-transform hover:scale-105 motion-reduce:transform-none"><Play className="size-5" fill="currentColor" /> Play</span></button>}
                  {previewLoading && <div role="status" aria-label="Game loading" className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[#121411] text-sm text-txt-secondary"><Loader2 className="size-6 animate-spin text-pop-yellow" /><span>{previewProgress === 100 ? "Starting your game…" : "Loading your game…"}</span>{previewProgress !== null && previewProgress < 100 && <progress aria-label="Loading progress" value={previewProgress} max={100} className="h-1.5 w-40 accent-pop-yellow" />}</div>}
                  {previewError && <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[#121411] p-6 text-center text-sm text-txt-secondary"><p>{previewError}</p><button onClick={reloadPreview} className="rounded-lg bg-pop-yellow px-5 py-3 font-bold text-surface">Try again</button></div>}
                </div>
                <GameCompanion key={`${gameId}:${previewRevision}`} gameId={gameId} playUrl={getPlayUrl(engine, gameId, true)} iframe={iframeRef} active={previewInteractive && activeTab === "play" && !previewLoading && !previewError} />
                <p className="flex max-w-full shrink-0 items-center justify-center gap-2 text-xs text-txt-muted" role="status">
                  {modifying && <><span className="size-1.5 shrink-0 rounded-full bg-pop-yellow motion-safe:animate-pulse" />Making your change…</>}
                </p>
              </div>
            ) : activeTab === "play" && (
              <div className="flex w-full max-w-5xl flex-col items-center justify-center gap-3 rounded-xl border border-white/10 bg-surface-raised p-8" style={{ aspectRatio: "4/3" }}>
                <ImageIcon className="size-7 text-txt-muted" />
                <p className="text-center text-sm text-txt-secondary">Your game will show up here when it’s ready.</p>
              </div>
            )}

            {/* Pictures */}
            {activeTab === "gallery" && (
              <div className="w-full max-w-5xl">
                {media && media.screenshots.length > 0 ? (
                  <div className="flex flex-col items-center gap-4">
                    <div className="relative w-full">
                      <img
                        src={authenticatedAssetUrl(`${API_BASE}${media.screenshots[galleryIndex].url}`)}
                        alt={media.screenshots[galleryIndex].name}
                        className="w-full rounded-lg brutal-border bg-black"
                        style={{ maxHeight: "60vh", objectFit: "contain" }}
                      />
                      {media.screenshots.length > 1 && (
                        <>
                          <button
                            aria-label="Previous picture"
                            onClick={() => setGalleryIndex((i) => (i - 1 + media.screenshots.length) % media.screenshots.length)}
                            className="absolute left-2 top-1/2 -translate-y-1/2 flex h-10 w-10 items-center justify-center rounded-full bg-surface/80 text-txt-primary brutal-border transition-colors hover:bg-surface"
                          >
                            <ChevronLeft className="h-5 w-5" />
                          </button>
                          <button
                            aria-label="Next picture"
                            onClick={() => setGalleryIndex((i) => (i + 1) % media.screenshots.length)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 flex h-10 w-10 items-center justify-center rounded-full bg-surface/80 text-txt-primary brutal-border transition-colors hover:bg-surface"
                          >
                            <ChevronRight className="h-5 w-5" />
                          </button>
                        </>
                      )}
                    </div>
                    {canEdit && media.screenshots[galleryIndex] && <DrawingInput imageSource={authenticatedAssetUrl(`${API_BASE}${media.screenshots[galleryIndex].url}`)} onAttach={image => {
                      setEditDraft(previous => ({ text: referencePrompt(image), image, hasImage: true, key: (previous?.key ?? 0) + 1 }));
                      setMobilePanel("chat"); setChatHidden(false); setActiveTab("play");
                    }} />}
                    <span className="font-mono text-xs font-bold text-txt-muted">
                      {galleryIndex + 1} / {media.screenshots.length}
                    </span>
                    <div className="flex gap-1.5 overflow-x-auto pb-2 max-w-full">
                      {media.screenshots.map((ss, i) => (
                        <button
                          key={ss.path}
                          onClick={() => setGalleryIndex(i)}
                          className={`shrink-0 rounded-md overflow-hidden border-2 transition-all ${
                            i === galleryIndex
                              ? "border-pop-yellow brutal-shadow-yellow"
                              : "border-[var(--card-border)] opacity-60 hover:opacity-100"
                          }`}
                        >
                          <img
                            src={authenticatedAssetUrl(`${API_BASE}${ss.url}`)}
                            alt={ss.name}
                            className="h-12 w-16 object-cover"
                            loading="lazy"
                          />
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-2 text-center">
                    <Images className="h-8 w-8 text-txt-muted" />
                    <span className="text-sm font-bold text-txt-muted">
                      No pictures yet
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* How it was made: saved steps from making the game */}
            {activeTab === "buildlog" && (
              <BuildLogReplay
                gameId={gameId}
                events={history.creation.data?.events ?? null}
                summary={history.creation.data?.summary ?? null}
                state={history.creation.status}
                error={history.creation.error}
              />
            )}

            {/* Past changes */}
            {activeTab === "modifications" && (
              <div className="flex h-full w-full max-w-7xl flex-col gap-3 self-stretch">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="flex items-center gap-2 text-sm font-bold text-txt-secondary">
                    <History className="h-4 w-4 text-pop-yellow" />
                    Past changes
                  </h2>
                  <button
                    type="button"
                    onClick={() => void loadModificationRuns()}
                    disabled={modificationRunsState === "loading"}
                    className="flex h-8 items-center gap-1.5 rounded-md bg-surface-raised px-3 text-xs font-bold text-txt-secondary brutal-border transition-colors hover:bg-surface-overlay disabled:opacity-40"
                  >
                    {modificationRunsState === "loading" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RotateCcw className="h-3.5 w-3.5" />
                    )}
                    Refresh
                  </button>
                </div>

                {modificationRunsState === "loading" && (
                  <div className="flex flex-1 items-center justify-center gap-3 text-sm text-txt-muted">
                    <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
                    Loading…
                  </div>
                )}

                {modificationRunsState === "error" && (
                  <div role="alert" className="rounded-lg border-2 border-pop-red bg-pop-red/10 p-4">
                    <p className="flex items-center gap-2 text-sm font-bold text-pop-red">
                      <AlertCircle className="h-5 w-5" />
                      We couldn’t load your past changes. Tap Refresh.
                    </p>
                    <p className="mt-1 font-mono text-xs text-txt-secondary">{modificationRunsError}</p>
                  </div>
                )}

                {modificationRunsState === "loaded" && modificationRuns.length === 0 && (
                  <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-lg brutal-card bg-surface-raised p-6 text-center">
                    <History className="h-7 w-7 text-txt-muted" />
                    <p className="text-sm font-bold text-txt-secondary">No changes yet</p>
                  </div>
                )}

                {modificationRunsState === "loaded" && modificationRuns.length > 0 && (
                  <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
                    <div className="max-h-[280px] min-h-0 space-y-2 overflow-y-auto rounded-lg brutal-card bg-surface p-2 lg:max-h-[calc(100vh-190px)]">
                      {modificationRuns.map((run) => (
                        <button
                          key={run.run_id}
                          type="button"
                          aria-pressed={run.run_id === selectedModificationRunId}
                          onClick={() => setSelectedModificationRunId(run.run_id)}
                          className={`w-full rounded-md border-2 p-3 text-left transition-colors ${
                            run.run_id === selectedModificationRunId
                              ? "border-pop-yellow bg-pop-yellow/10"
                              : "border-[var(--card-border)] bg-surface-raised hover:bg-surface-overlay"
                          }`}
                        >
                          <div className="mb-2 flex items-start justify-between gap-2">
                            <span className="min-w-0 flex-1 truncate text-xs font-bold text-txt-primary">
                              {editRequest(run.instruction).text || "(no words)"}
                            </span>
                            <StatusChip status={run.status} />
                          </div>
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-txt-muted">
                            <span>{whenLabel(run.started_at)}</span>
                            {typeof run.duration_seconds === "number" && <span>{durationLabel(run.duration_seconds)}</span>}
                          </div>
                        </button>
                      ))}
                    </div>

                    <div className="min-h-0 rounded-lg brutal-card bg-surface">
                      {selectedModificationRun ? (
                        <>
                          <div className="border-b-2 border-[var(--card-border)] bg-surface-raised p-3">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="min-w-0 flex-1">
                                <StatusChip status={selectedModificationRun.status} />
                                <p className="mt-2 text-sm font-bold leading-relaxed text-txt-primary">
                                  {editRequest(selectedModificationRun.instruction).text}
                                </p>
                              </div>
                              <button
                                type="button"
                                onClick={async () => {
                                  const attachment = selectedModificationRun.attachments?.[0];
                                  let image: File | undefined;
                                  if (attachment) {
                                    try { image = await loadEditorReference(engine, gameId, attachment); } catch { /* The chat box offers to add the picture again. */ }
                                  }
                                  setEditDraft((previous) => ({ ...editRequest(selectedModificationRun.instruction), image, key: (previous?.key ?? 0) + 1 }));
                                  setMobilePanel("chat");
                                  setChatHidden(false);
                                }}
                                disabled={!selectedModificationRun.instruction.trim() || modifying}
                                className="flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-pop-yellow px-3 text-xs font-bold text-surface brutal-border transition-colors hover:bg-pop-lime disabled:opacity-40"
                              >
                                <RotateCcw className="h-3.5 w-3.5" />
                                Use again
                              </button>
                            </div>

                            {(modificationEventsSummary?.error || selectedModificationRun.error) && (
                              <p className="mt-3 rounded border border-pop-red/50 bg-pop-red/10 px-2 py-1.5 text-xs text-pop-red">
                                {modificationEventsSummary?.error || selectedModificationRun.error}
                              </p>
                            )}

                            {(modificationEventsSummary?.final_message || selectedModificationRun.final_message) && (
                              <p className="mt-3 border-l-2 border-[var(--card-border)] pl-3 text-xs italic text-txt-secondary">
                                {modificationEventsSummary?.final_message || selectedModificationRun.final_message}
                              </p>
                            )}

                            {selectedVerificationFailures.length > 0 && (
                              <div className="mt-3 rounded border border-pop-red/50 bg-pop-red/10 px-2 py-1.5 text-xs text-pop-red">
                                <p className="font-bold">What went wrong</p>
                                <ul className="mt-1 space-y-1">
                                  {selectedVerificationFailures.map((failure) => <li key={failure}>{failure}</li>)}
                                </ul>
                              </div>
                            )}

                            {/* Developer detail, closed by default. */}
                            {selectedModificationDetail && (
                              <details className="mt-3 font-mono text-[11px] text-txt-muted">
                                <summary className="cursor-pointer font-sans text-xs">More details</summary>
                                <p className="mt-2">
                                  ID {selectedModificationRun.run_id} · Rebuild {selectedModificationDetail.rebuild_status ?? "unknown"} · Export {selectedModificationDetail.export_status ?? "unknown"}
                                </p>
                                {selectedChangedFiles.length > 0 && <p className="mt-2 break-all">Files changed: {selectedChangedFiles.join(", ")}</p>}
                                {selectedNewScreenshots.length > 0 && <p className="mt-2 break-all">New pictures: {selectedNewScreenshots.join(", ")}</p>}
                              </details>
                            )}
                          </div>

                          <div className="max-h-[calc(100vh-310px)] min-h-[360px] space-y-2 overflow-y-auto p-3">
                            {modificationEventsState === "loading" && (
                              <div className="flex items-center justify-center gap-3 py-12 text-sm text-txt-muted">
                                <Loader2 className="h-5 w-5 animate-spin text-pop-yellow" />
                                Loading…
                              </div>
                            )}
                            {modificationEventsState === "error" && (
                              <div role="alert" className="rounded-lg border-2 border-pop-red bg-pop-red/10 p-4">
                                <p className="flex items-center gap-2 text-sm font-bold text-pop-red">
                                  <AlertCircle className="h-5 w-5" />
                                  We couldn’t load the steps. Tap Refresh.
                                </p>
                                <p className="mt-1 font-mono text-xs text-txt-secondary">{modificationEventsError}</p>
                              </div>
                            )}
                            {modificationEventsState === "loaded" && modificationCards.length === 0 && (
                              <p className="rounded-lg border-2 border-[var(--card-border)] bg-surface-raised p-4 text-center text-sm font-bold text-txt-secondary">
                                No steps to show
                              </p>
                            )}
                            {modificationCards.map((card) => (
                              <StreamCardView key={card.id} card={card} />
                            ))}
                          </div>
                        </>
                      ) : (
                        <p className="flex h-full items-center justify-center p-6 text-center text-sm text-txt-muted">
                          Pick a change
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === "video" && game.has_video && (
              <div className="w-full max-w-5xl">
                <video
                  src={getVideoUrl(engine, gameId)}
                  controls
                  autoPlay
                  className="w-full rounded-lg brutal-border bg-black"
                  style={{ maxHeight: "70vh" }}
                />
                {media && media.videos.length > 1 && (
                  <div className="mt-4 grid grid-cols-2 gap-3">
                    {media.videos.slice(1).map((vid) => (
                      <video
                        key={vid.path}
                        src={authenticatedAssetUrl(`${API_BASE}${vid.url}`)}
                        controls
                        className="w-full rounded-md brutal-border bg-black"
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
