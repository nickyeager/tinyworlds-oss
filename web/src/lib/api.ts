import { formatApiError, readApiError } from "./api-errors";
import { getAudioExtension, ensureAudioBlobType } from "./audio-utils";
import { getToken } from "./token-storage";

import { API_BASE, GAME_PLAY_BASE } from "./api-config";
export { API_BASE } from "./api-config";
export { createGameStreaming, modifyGameStreaming, type ModificationStreamOptions } from "./game-streams";

function gameReadHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Browser resource tags cannot send bearer headers. */
export function authenticatedAssetUrl(url: string): string {
  const token = getToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

// ============================================================================
// Observability event types (emitted by backend EventBus)
// ============================================================================

export type ObservabilityEventType =
  | "StatusEvent"
  | "ProgressEvent"
  | "CompletionEvent"
  | "ErrorEvent"
  | "DebugEvent"
  | "PerformanceEvent"
  | "GitCloneEvent"
  | "AssetGenerationEvent"
  | "ThinkingEvent"
  | "ToolUseEvent"
  | "ToolResultEvent"
  | "CodeChangedEvent"
  | "AssetGeneratedEvent"
  | "ValidationEvent"
  | "FollowUpReceivedEvent"
  | "CLIStreamEvent";

export interface ObservabilityEvent {
  timestamp: string;
  level: "debug" | "info" | "warning" | "error";
  category: "user" | "debug" | "perf" | "error";
  service: string;
  event_type: ObservabilityEventType;
  message?: string;
  error_message?: string;
  suggestion?: string;
  step?: string;
  status?: string;
  size_mb?: number;
  duration_seconds?: number;
  item_count?: number;
  current?: number;
  total?: number;
  percentage?: number;
  operation?: string;
  repo_url?: string;
  commit_hash?: string;
  is_cached?: boolean;
  cache_key?: string;
  result_path?: string;
  context?: Record<string, unknown>;
  file_path?: string;
  line_number?: number;
  stream_type?: "thinking" | "text" | "tool_use" | "tool_result" | "status" | "error" | "complete";
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  content?: string;
  cost_usd?: number;
  function_name?: string;
  stack_trace?: string;
  duration_ms?: number;
}

// ============================================================================
// Voice transcription (shared with Godot create flow)
// ============================================================================

export interface TranscriptionResponse {
  success: boolean;
  transcript?: string;
  error?: string;
}

export async function transcribeAudio(
  audioBlob: Blob,
  token?: string
): Promise<TranscriptionResponse> {
  const blobWithType = ensureAudioBlobType(audioBlob);
  const ext = getAudioExtension(blobWithType.type);

  const formData = new FormData();
  formData.append("audio_file", blobWithType, `recording.${ext}`);

  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}/api/v1/voice/transcribe`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(formatApiError(errorData, response.statusText));
  }

  return response.json();
}

// ============================================================================
// Auth
// ============================================================================

export async function getAnonymousToken(): Promise<string> {
  const response = await fetch(`${API_BASE}/api/v1/auth/anonymous`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error("Failed to get anonymous token");
  }

  const data = await response.json();
  return data.access_token;
}

// ============================================================================
// Engine selection (Godot vs Bevy)
// ============================================================================

export type Engine = "godot" | "bevy";

// ============================================================================
// Godot game APIs
// ============================================================================

export interface GodotGameInfo {
  game_id: string;
  can_edit?: boolean;
  visibility?: "public" | "private" | "unlisted";
  name?: string | null;
  game_path?: string;
  has_plan: boolean;
  has_structure: boolean;
  has_video: boolean;
  has_export: boolean;
  plan_summary?: string | null;
}

export interface GameHistoryEntry {
  instruction: string;
  changes: string[];
}

export interface GameMedia {
  game_id: string;
  screenshots: { path: string; name: string; url: string }[];
  videos: { path: string; name: string; url: string }[];
}

export interface GodotBuildProgress {
  game_id: string;
  scripts: number;
  scenes: number;
  screenshots: number;
  assets: number;
  has_plan: boolean;
  has_structure: boolean;
  has_video: boolean;
  has_export: boolean;
  tasks: Array<{ number: number; name: string; status: string }>;
}

export async function getGodotGameInfo(gameId: string): Promise<GodotGameInfo> {
  const response = await fetch(`${API_BASE}/api/v1/godot/games/${gameId}`, { headers: gameReadHeaders() });
  if (!response.ok) throw new Error("Failed to get Godot game info");
  return response.json();
}

export async function renameGodotGame(
  gameId: string,
  name: string
): Promise<GodotGameInfo> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(`${API_BASE}/api/v1/godot/games/${gameId}`, {
    method: "PATCH",
    headers,
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Rename failed"));
  }
  return response.json();
}

export async function getGodotGameHistory(gameId: string): Promise<GameHistoryEntry[]> {
  const response = await fetch(`${API_BASE}/api/v1/godot/games/${gameId}/history`, { headers: gameReadHeaders() });
  if (!response.ok) return [];
  const data = await response.json();
  return data.history || [];
}

export async function getGodotGameMedia(gameId: string): Promise<GameMedia> {
  return getGameMedia("godot", gameId);
}

export async function getGameMedia(engine: Engine, gameId: string): Promise<GameMedia> {
  const response = await fetch(`${API_BASE}/api/v1/${engine}/games/${gameId}/media`, { headers: gameReadHeaders() });
  if (!response.ok) throw new Error("Failed to get game media");
  return response.json();
}

export async function modifyGodotGame(
  gameId: string,
  instruction: string
): Promise<{ success: boolean; changes: string[]; explanation: string }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(
    `${API_BASE}/api/v1/godot/games/${gameId}/modify`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ instruction }),
    }
  );
  if (!response.ok) throw new Error("Failed to modify Godot game");
  return response.json();
}

export function getGodotAssetUrl(gameId: string, filePath: string): string {
  return authenticatedAssetUrl(`${API_BASE}/api/v1/godot/games/${gameId}/assets/${filePath}`);
}

export async function cancelGameBuild(gameId: string): Promise<boolean> {
  const response = await fetch(`${API_BASE}/api/v1/games/${gameId}/cancel`, {
    method: "POST",
    headers: gameReadHeaders(),
  });
  if (!response.ok) throw new Error(await readApiError(response, "Unable to stop this edit"));
  const data = await response.json();
  return data.cancelled === true;
}

export function getGodotScreenshotUrl(gameId: string): string {
  return authenticatedAssetUrl(`${API_BASE}/api/v1/godot/games/${gameId}/screenshot`);
}

export function getGodotVideoUrl(gameId: string): string {
  return authenticatedAssetUrl(`${API_BASE}/api/v1/godot/games/${gameId}/video`);
}

export function getGodotPlayUrl(gameId: string): string {
  return authenticatedAssetUrl(`${GAME_PLAY_BASE}/api/v1/godot/games/${gameId}/play`);
}

export async function listGodotGames(): Promise<GodotGameInfo[]> {
  const response = await fetch(`${API_BASE}/api/v1/godot/games`, { headers: gameReadHeaders() });
  if (!response.ok) throw new Error("Failed to list Godot games");
  return response.json();
}

export async function getGodotBuildProgress(
  gameId: string
): Promise<GodotBuildProgress> {
  const response = await fetch(
    `${API_BASE}/api/v1/godot/games/${gameId}/progress`,
    { headers: gameReadHeaders() }
  );
  if (!response.ok) throw new Error("Failed to get build progress");
  return response.json();
}

export async function getGodotPlan(gameId: string): Promise<string> {
  const response = await fetch(
    `${API_BASE}/api/v1/godot/games/${gameId}/plan`,
    { headers: gameReadHeaders() }
  );
  if (!response.ok) throw new Error("Failed to get plan");
  const data = await response.json();
  return data.content;
}

// ============================================================================
// Engine-aware game APIs
//
// These dispatch to /api/v1/{engine}/games/... — Bevy and Godot share the
// same endpoint shape for create/list/info/rename/play/screenshot/video.
// Godot media/history helpers remain for its engine-specific features.
// ============================================================================

function engineBase(engine: Engine): string {
  return `${API_BASE}/api/v1/${engine}/games`;
}

export interface GenerationCapabilities {
  provider: "claude" | "codex";
  execution_mode: "local" | "worker";
  engines: Engine[];
  asset_budget_required: boolean;
  upstream_revision: string;
  personal_mode?: boolean;
  requires_provider_connection?: boolean;
}

export async function getGenerationCapabilities(): Promise<GenerationCapabilities> {
  const response = await fetch(`${API_BASE}/api/v1/games/capabilities`);
  if (!response.ok) throw new Error("Generation configuration unavailable");
  return response.json();
}

export interface UnifiedGameInfo extends GodotGameInfo {
  engine: Engine;
}

/** Merged list of games across both engines. */
export async function listAllGames(): Promise<UnifiedGameInfo[]> {
  const response = await fetch(`${API_BASE}/api/v1/games`, { headers: gameReadHeaders() });
  if (!response.ok) throw new Error("Failed to list games");
  return response.json();
}

export function getPlayUrl(engine: Engine, gameId: string, embedded = false): string {
  return authenticatedAssetUrl(`${GAME_PLAY_BASE}/api/v1/${engine}/games/${gameId}/play${embedded ? "?embedded=1" : ""}`);
}

export function getVideoUrl(engine: Engine, gameId: string): string {
  return authenticatedAssetUrl(`${engineBase(engine)}/${gameId}/video`);
}

export function getScreenshotUrl(engine: Engine, gameId: string): string {
  return authenticatedAssetUrl(`${engineBase(engine)}/${gameId}/screenshot`);
}

export async function getGameInfo(
  engine: Engine,
  gameId: string
): Promise<GodotGameInfo> {
  const response = await fetch(`${engineBase(engine)}/${gameId}`, { headers: gameReadHeaders() });
  if (!response.ok) throw new Error(`Failed to get ${engine} game info`);
  return response.json();
}

export type SuggestionsResponse = {
  suggestions: string[];
  generated_at?: string;
  pending?: boolean;
};

export async function getSuggestions(
  engine: Engine,
  gameId: string,
): Promise<SuggestionsResponse> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(
    `${engineBase(engine)}/${gameId}/suggestions`,
    { headers },
  );
  if (!response.ok) return { suggestions: [], pending: true };
  const data = await response.json();
  const suggestions = Array.isArray(data?.suggestions)
    ? data.suggestions.filter((s: unknown): s is string => typeof s === "string")
    : [];
  return {
    suggestions,
    generated_at: typeof data?.generated_at === "string" ? data.generated_at : undefined,
    pending: data?.pending === true ? true : undefined,
  };
}

export async function listGames(engine: Engine): Promise<GodotGameInfo[]> {
  const response = await fetch(engineBase(engine), { headers: gameReadHeaders() });
  if (!response.ok) throw new Error(`Failed to list ${engine} games`);
  return response.json();
}

export async function renameGame(
  engine: Engine,
  gameId: string,
  name: string
): Promise<GodotGameInfo> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(`${engineBase(engine)}/${gameId}`, {
    method: "PATCH",
    headers,
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Rename failed"));
  }
  return response.json();
}

// Hard-delete: server `rm -rf`s the on-disk directory. Two-step confirm
// gating happens in the UI — this function does NOT prompt.
export async function deleteGame(engine: Engine, gameId: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(`${engineBase(engine)}/${gameId}`, {
    method: "DELETE",
    headers,
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Delete failed"));
  }
}

/**
 * One raw event from the creation-time JSONL log. Schema mirrors what
 * the godot_creation_agent's observability bus emits — minimal subset
 * the UI needs to render. Extra fields are tolerated.
 */
export interface GameCreationEvent {
  timestamp: string;
  level?: string;
  service?: string;
  event_type?: string;
  stream_type?: "thinking" | "tool_use" | "tool_result" | "status" | "error";
  tool_name?: string | null;
  tool_input?: Record<string, unknown>;
  content?: string;
  cost_usd?: number | null;
}

export interface GameCreationSummary {
  started_at: string;
  ended_at?: string;
  duration_seconds?: number;
  status?: string;
  error?: string | null;
  final_message?: string | null;
  explanation?: string | null;
  changes?: string[];
  event_count?: number;
  total_cost_usd?: number | null;
  has_export?: boolean;
  has_video?: boolean;
}

export interface GameEventsResponse {
  game_id: string;
  events: GameCreationEvent[];
  summary: GameCreationSummary | null;
}

/**
 * Fetch the persisted creation log for a game. Used by the replay view
 * on /games/[id]. Returns 404 if the game doesn't exist; events array
 * is empty (not error) if the game predates the recording.
 */
export async function getGameCreationLog(
  engine: Engine,
  gameId: string,
  signal?: AbortSignal,
): Promise<GameEventsResponse> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(
    `${API_BASE}/api/v1/${engine}/games/${gameId}/events`,
    { headers, signal },
  );
  if (!response.ok) {
    throw new Error(
      await readApiError(response, "Failed to load creation log"),
    );
  }
  return response.json();
}

export interface GameAttachment {
  purpose?: import("./visual-reference").ReferencePurpose;
  path: string;
  name: string;
  media_type: string;
}

export interface ModificationRun {
  run_id: string;
  instruction: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  event_count?: number | null;
  final_message?: string | null;
  explanation?: string | null;
  changes?: string[];
  error?: string | null;
  has_export?: boolean;
  has_playable_build?: boolean;
  rebuild_status?: string | null;
  export_status?: string | null;
  new_screenshots?: string[];
  changed_files?: string[];
  verification_failures?: string[];
  attachments?: GameAttachment[];
  generated_images?: string[];
}

export interface ModificationRunsResponse {
  game_id: string;
  engine: Engine;
  runs: ModificationRun[];
}

export interface ModificationRunEvent {
  timestamp?: string;
  level?: string;
  service?: string;
  event_type?: string;
  stream_type?: string;
  type?: string;
  tool_name?: string | null;
  tool_input?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  content?: string;
  message?: string;
  error?: string;
  cost_usd?: number | null;
  [key: string]: unknown;
}

export interface ModificationRunEventsResponse {
  game_id: string;
  engine: Engine;
  run_id: string;
  summary: ModificationRun | null;
  events: ModificationRunEvent[];
}

export async function getModificationRuns(
  engine: Engine,
  gameId: string,
  signal?: AbortSignal,
): Promise<ModificationRunsResponse> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(
    `${engineBase(engine)}/${gameId}/modifications`,
    { headers, signal },
  );
  if (!response.ok) {
    throw new Error(
      await readApiError(response, "Failed to load modification runs"),
    );
  }
  return response.json();
}

export async function getModificationRunEvents(
  engine: Engine,
  gameId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<ModificationRunEventsResponse> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(
    `${engineBase(engine)}/${gameId}/modifications/${runId}/events`,
    { headers, signal },
  );
  if (!response.ok) {
    throw new Error(
      await readApiError(response, "Failed to load modification events"),
    );
  }
  return response.json();
}
