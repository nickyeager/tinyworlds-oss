import { API_BASE, authenticatedAssetUrl, type Engine, type ObservabilityEvent } from "./api";
import { describeEditEvent } from "./game-editor";

export type CardType =
  | "file"
  | "command"
  | "asset"
  | "plan"
  | "screenshot"
  | "preview"
  | "thinking"
  | "error"
  | "status";

export interface StreamCard {
  id: string;
  type: CardType;
  timestamp: string;

  // File card
  filePath?: string;
  fileContent?: string;
  fileAction?: "created" | "edited";

  // Command card
  command?: string;
  commandOutput?: string;

  // Asset/screenshot card
  imageUrl?: string;
  imageName?: string;

  // Preview card (inline image/video)
  previewUrl?: string;
  previewType?: "image" | "video";
  previewName?: string;

  // Thinking card
  thinkingText?: string;

  // Error card
  errorMessage?: string;

  // Status card
  statusMessage?: string;
  details?: string;

  // Plan card
  planContent?: string;

}

const PREVIEW_IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".svg"];
const PREVIEW_VIDEO_EXTS = [".mp4", ".webm"];

function extractAssetPath(text: string, gameId: string | null): { path: string; type: "image" | "video" } | null {
  if (!gameId) return null;
  // Match file paths that look like assets/screenshots/etc with image or video extensions
  const allExts = [...PREVIEW_IMAGE_EXTS, ...PREVIEW_VIDEO_EXTS];
  const extPattern = allExts.map(e => e.replace(".", "\\.")).join("|");
  const regex = new RegExp(`(?:^|\\s|[/"'(])([^\\s"'()]*(?:${extPattern}))`, "gi");
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    const filePath = match[1];
    // Skip paths that are clearly not game assets
    if (filePath.includes("node_modules") || filePath.includes(".claude")) continue;
    const ext = filePath.slice(filePath.lastIndexOf(".")).toLowerCase();
    const isVideo = PREVIEW_VIDEO_EXTS.includes(ext);
    // Try to extract a relative path from the game directory
    const gameIdIdx = filePath.indexOf(gameId);
    const relativePath = gameIdIdx !== -1 ? filePath.slice(gameIdIdx + gameId.length + 1) : filePath;
    return { path: relativePath, type: isVideo ? "video" : "image" };
  }
  return null;
}

/** Game ids carry their engine as a prefix: `godot-…` or `bevy-…`. */
function engineOf(gameId: string): Engine {
  return gameId.startsWith("bevy-") ? "bevy" : "godot";
}

let cardCounter = 0;

export function classifyEvent(
  event: ObservabilityEvent,
  gameId: string | null
): StreamCard | null {
  const id = `card-${++cardCounter}`;
  const timestamp = event.timestamp || new Date().toISOString();

  // CLIStreamEvent — the enriched events
  if (event.event_type === "CLIStreamEvent") {
    const streamType = event.stream_type;
    const toolName = event.tool_name || "";
    const toolInput = event.tool_input || {};
    const content = event.content || "";

    // Tool use events — classify by tool name
    if (streamType === "tool_use") {
      const filePath = (toolInput.file_path as string) || "";

      // Write tool → file card
      if (toolName === "Write") {
        const fileContent = (toolInput.content as string) || "";
        const isPlan = filePath.endsWith("PLAN.md");
        const isStructure = filePath.endsWith("STRUCTURE.md");

        if (isPlan || isStructure) {
          return {
            id,
            type: "plan",
            timestamp,
            planContent: fileContent,
            filePath,
          };
        }

        return {
          id,
          type: "file",
          timestamp,
          filePath,
          fileContent,
          fileAction: "created",
        };
      }

      // Edit tool → file card (edited)
      if (toolName === "Edit") {
        const oldStr = (toolInput.old_string as string) || "";
        const newStr = (toolInput.new_string as string) || "";
        return {
          id,
          type: "file",
          timestamp,
          filePath,
          fileContent: `--- old\n${oldStr}\n+++ new\n${newStr}`,
          fileAction: "edited",
        };
      }

      // Bash tool → command card (or asset card for asset_gen.py)
      if (toolName === "Bash") {
        const command = (toolInput.command as string) || "";
        if (command.includes("asset_gen.py")) {
          return {
            id,
            type: "asset",
            timestamp,
            command,
            imageName: "Making a picture…",
          };
        }
        return {
          id,
          type: "command",
          timestamp,
          command,
        };
      }

      // Reads and unfamiliar tools remain visible, with their actual inputs.
      const summary = describeEditEvent({ type: "tool_use", tool_name: toolName, tool_input: toolInput, content });
      return {
        id, type: "status", timestamp, statusMessage: summary,
        details: JSON.stringify(toolInput, null, 2),
      };
    }

    // Tool results
    if (streamType === "tool_result") {
      // Check for screenshot captures
      if (
        content.includes(".png") &&
        (content.includes("screenshot") || content.includes("Screenshot"))
      ) {
        return {
          id,
          type: "screenshot",
          timestamp,
          imageUrl: gameId
            ? authenticatedAssetUrl(`${API_BASE}/api/v1/${engineOf(gameId)}/games/${gameId}/screenshot?t=${Date.now()}`)
            : undefined,
          imageName: "Picture of your game",
        };
      }

      // Check for asset files (images, videos) — show inline preview
      const asset = extractAssetPath(content, gameId);
      if (asset && gameId) {
        const previewUrl = `${API_BASE}/api/v1/${engineOf(gameId)}/games/${gameId}/assets/${asset.path}?t=${Date.now()}`;
        const fileName = asset.path.split("/").pop() || "picture";
        return {
          id,
          type: "preview",
          timestamp,
          previewUrl: authenticatedAssetUrl(previewUrl),
          previewType: asset.type,
          previewName: fileName,
        };
      }

      return {
        id, type: "status", timestamp,
        statusMessage: content.trim() ? "Result" : "No result",
        details: content,
      };
    }

    // Thinking
    if (streamType === "thinking" || streamType === "text") {
      return {
        id,
        type: "thinking",
        timestamp,
        thinkingText: content,
      };
    }

    // Error
    if (streamType === "error") {
      return {
        id,
        type: "error",
        timestamp,
        errorMessage: content,
      };
    }

    // Complete
    if (streamType === "complete") {
      return {
        id,
        type: "status",
        timestamp,
        statusMessage: content || "Step done",
      };
    }

    // Status — filter out noisy CLI system events
    if (streamType === "status") {
      if (
        content.startsWith("system:hook_") ||
        content === "system:init" ||
        content === "system:connect"
      ) {
        return null;
      }
      return {
        id,
        type: "status",
        timestamp,
        statusMessage: content,
      };
    }
  }

  // Fallback for legacy StatusEvent / other event types
  const msg = event.message || event.error_message || "";
  if (!msg) return null;

  if (event.event_type === "ErrorEvent") {
    return {
      id,
      type: "error",
      timestamp,
      errorMessage: msg,
    };
  }

  return {
    id,
    type: "status",
    timestamp,
    statusMessage: msg,
  };
}
