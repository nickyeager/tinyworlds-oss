import { withReferencePurpose } from "./visual-reference";
import { API_BASE, authenticatedAssetUrl, type Engine, type GameAttachment, type ModificationRun, type ModificationRunEvent } from "./api";

export type EditStatus = "running" | "success" | "failed" | "interrupted" | "disconnected";
export interface EditTurn {
  id: string;
  runId?: string;
  instruction: string;
  status: EditStatus;
  startedAt?: string | null;
  duration?: number | null;
  response?: string | null;
  changes?: string[];
  events: ModificationRunEvent[];
  eventsLoaded: boolean;
  image?: File;
  imageUrl?: string;
  hasImage?: boolean;
  attachments?: GameAttachment[];
  screenshots?: string[];
  verified?: boolean;
}

export function editRequest(instruction: string): { text: string; hasImage: boolean } {
  const referenceAt = instruction.indexOf("\n\nReference image attached at:");
  return { text: referenceAt >= 0 ? instruction.slice(0, referenceAt) : instruction, hasImage: referenceAt >= 0 };
}

export function turnFromRun(run: ModificationRun): EditTurn {
  const status: EditStatus = run.status === "success" ? "success"
    : ["running", "pending"].includes(run.status) ? "running"
    : run.status === "interrupted" ? "interrupted" : "failed";
  const request = editRequest(run.instruction);
  return {
    id: run.run_id, runId: run.run_id,
    instruction: request.text,
    hasImage: request.hasImage || Boolean(run.attachments?.length),
    attachments: run.attachments,
    screenshots: [...(run.new_screenshots ?? []), ...(run.generated_images ?? [])],
    verified: run.has_playable_build === true,
    status, startedAt: run.started_at, duration: run.duration_seconds,
    response: run.error || run.explanation || run.final_message, changes: run.changes, events: [], eventsLoaded: false,
  };
}

/** Asset URLs are always resolved through the game's owner-authorized route. */
export function editorImageUrl(engine: Engine, gameId: string, path: string): string | null {
  if (!/^(assets|screenshots|_user_uploads)\//.test(path) || path.split("/").some((part) => !part || part === ".." || part === ".") || /[\\\u0000-\u001f?#]/.test(path)) return null;
  if (!/\.(png|jpe?g|webp)$/i.test(path)) return null;
  return authenticatedAssetUrl(`${API_BASE}/api/v1/${engine}/games/${encodeURIComponent(gameId)}/assets/${path.split("/").map(encodeURIComponent).join("/")}`);
}

export async function loadEditorReference(engine: Engine, gameId: string, attachment: GameAttachment): Promise<File> {
  const url = editorImageUrl(engine, gameId, attachment.path);
  if (!url) throw new Error("Invalid saved reference");
  const response = await fetch(url);
  if (!response.ok) throw new Error("Saved reference is unavailable");
  return withReferencePurpose(new File([await response.blob()], attachment.name, { type: attachment.media_type }), attachment.purpose ?? "idea");
}

/** Extract only image outputs, keeping reasoning and unrelated host paths out. */
export function editImages(turn: EditTurn): string[] {
  const images = new Set(turn.screenshots ?? []);
  for (const event of turn.events) {
    if (!["tool_result", "file_changed"].includes(editEventKind(event)) || event.metadata?.success === false) continue;
    for (const match of (event.content ?? "").matchAll(/(?:^|[\s\"'`(\/])((?:assets|screenshots)\/[^\s\"'`<>\n)]+\.(?:png|jpe?g|webp))(?=$|[\s\"'`)>,])/gi)) images.add(match[1]);
  }
  return [...images];
}

/** Describe only observed actions; a tool start does not establish success. */
export function describeEditEvent(event: ModificationRunEvent): string {
  const name = event.tool_name ?? String(event.metadata?.tool_name ?? "");
  const input = event.tool_input ?? (event.metadata?.input as Record<string, unknown> | undefined) ?? {};
  const path = String(input.file_path ?? input.path ?? input.pattern ?? "");
  const shortPath = path.split("/").slice(-2).join("/");
  const command = String(input.command ?? input.cmd ?? "");
  if (["Read", "read_file"].includes(name)) return `Read ${shortPath || "file"}`;
  if (["Grep", "Glob", "LS", "web_search"].includes(name)) return `Search ${shortPath || String(input.query ?? input.search_term ?? "game files")}`;
  if (["Write", "Edit", "apply_patch", "file_change"].includes(name)) {
    const changes = Array.isArray(input.changes) ? input.changes as { path?: string }[] : [];
    return `Update ${shortPath || changes.map((change) => change.path?.split("/").pop()).filter(Boolean).join(", ") || "game files"}`;
  }
  if (["Bash", "command_execution", "exec_command"].includes(name)) {
    const description = typeof input.description === "string" ? input.description : "";
    if (description) return description;
    if (/godot.*--export|export_html5/.test(command)) return "Get the game ready to play";
    if (/asset_gen|generate_asset/.test(command)) return "Make pictures for the game";
    if (/godot.*--headless/.test(command)) return "Check the game";
    if (/\bgit diff\b/.test(command)) return "Look at what changed";
    if (/\brg\b|\bfind\b/.test(command)) return "Search game files";
    if (/\bcat\b|\bsed -n\b/.test(command)) return "Read game files";
    if (/\bpython3?\b/.test(command)) return "Run a script";
    return command ? `Run ${command.split("\n")[0]}` : "Run command";
  }
  if (name) return `Use ${name}${shortPath ? ` · ${shortPath}` : ""}`;
  return event.content ?? event.message ?? String(event.reason ?? event.event_type ?? "Update");
}

export function editEventDetails(event: ModificationRunEvent): string {
  const input = event.tool_input ?? event.metadata?.input;
  const parts: string[] = [];
  if (input) parts.push(typeof input === "string" ? input : JSON.stringify(input, null, 2));
  if (event.content) parts.push(event.content);
  if (event.metadata && !input) parts.push(JSON.stringify(event.metadata, null, 2));
  return parts.join("\n\n");
}

export function editEventKind(event: ModificationRunEvent): string {
  return event.stream_type ?? event.type ?? event.event_type ?? "status";
}

/** Select distinct conversation text in one pass, without rescanning history. */
export function editMessages(events: ModificationRunEvent[], response?: string | null): ModificationRunEvent[] {
  const seen = new Set<string>();
  const messages: ModificationRunEvent[] = [];
  for (const event of events) {
    const kind = editEventKind(event);
    if (!["thinking", "text"].includes(kind) || !event.content?.trim()) continue;
    const duplicate = seen.has(event.content);
    seen.add(event.content);
    if (kind === "text" && !duplicate && event.content !== response) messages.push(event);
  }
  return messages;
}

/** Kid-first progress line. Only pipeline status events establish build/test stages. */
export function editStage(events: ModificationRunEvent[]): string {
  for (const event of [...events].reverse()) {
    if (editEventKind(event) !== "status") continue;
    if (/checking.*browser|browser verification/i.test(event.content ?? "")) return "Testing your game…";
    if (/re-export|rebuild|browser export|wasm.*build/i.test(event.content ?? "")) return "Putting your game together…";
  }
  return events.some((event) => !["init"].includes(event.event_type ?? "") && !["thread.started", "turn.started"].includes(event.content ?? ""))
    ? "Making your change…" : "Getting ready…";
}

/** Short local date and time, e.g. "Oct 29, 11:00 AM". */
export function whenLabel(value?: string | null): string {
  const date = new Date(value ?? "");
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function durationLabel(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return total < 60 ? `${total}s` : `${Math.floor(total / 60)}m ${total % 60}s`;
}

export interface EditActivity {
  event: ModificationRunEvent;
  result?: ModificationRunEvent;
  summary: string;
  state: "observed" | "started" | "completed" | "failed" | "interrupted";
}

function resultFailed(event: ModificationRunEvent): boolean {
  return editEventKind(event) === "error" || event.level === "error" || event.metadata?.success === false
    || (typeof event.metadata?.exit_code === "number" && event.metadata.exit_code !== 0);
}

/** Pair only events with an observed invocation identity, never by completion order. */
export function editActivities(events: ModificationRunEvent[], runStatus: EditStatus = "running"): EditActivity[] {
  const activities: EditActivity[] = [];
  const tools = new Map<string, EditActivity>();
  for (const event of events) {
    const kind = editEventKind(event);
    if (["done", "failed", "crashed", "interrupted"].includes(event.event_type ?? "")) {
      for (const activity of activities) {
        if (activity.state === "started") activity.state = "interrupted";
      }
    }
    if (["thinking", "text"].includes(kind) || ["init", "done"].includes(event.event_type ?? "")) continue;
    if (kind === "status" && /^(system:|thread\.started$|turn\.started$)/.test(event.content ?? "")) continue;
    const identity = event.metadata?.tool_use_id ?? event.metadata?.item_id;
    if (["tool_result", "error"].includes(kind) && typeof identity === "string" && identity && tools.has(identity)) {
      const activity = tools.get(identity)!;
      activity.result = event;
      activity.state = resultFailed(event) ? "failed" : event.metadata?.success === true ? "completed" : "observed";
      continue;
    }
    const activity: EditActivity = {
      event,
      summary: kind === "complete" ? "Step done"
        : kind === "tool_result" ? (resultFailed(event) ? "Something went wrong" : "Result")
          : kind === "file_changed" ? `Update ${String(event.metadata?.path ?? event.content ?? "game file").split("/").slice(-2).join("/")}`
            : describeEditEvent(event),
      state: resultFailed(event) ? "failed" : kind === "tool_use" ? "started" : "observed",
    };
    activities.push(activity);
    if (kind === "tool_use" && typeof identity === "string" && identity) tools.set(identity, activity);
  }
  if (!["running", "disconnected"].includes(runStatus)) {
    for (const activity of activities) {
      if (activity.state === "started") activity.state = "interrupted";
    }
  }
  return activities;
}
