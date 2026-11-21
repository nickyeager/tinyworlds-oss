import { describe, it, expect } from "vitest";
import { classifyEvent } from "../stream-cards";
import type { ObservabilityEvent } from "../api";

function makeCLIEvent(
  overrides: Partial<ObservabilityEvent>
): ObservabilityEvent {
  return {
    timestamp: new Date().toISOString(),
    level: "info",
    category: "user",
    service: "godot_creation_agent",
    event_type: "CLIStreamEvent",
    ...overrides,
  } as ObservabilityEvent;
}

describe("classifyEvent", () => {
  it("retains read-only tools and their inputs in historical replay", () => {
    const card = classifyEvent(makeCLIEvent({
      stream_type: "tool_use", tool_name: "Read", tool_input: { file_path: "scripts/player.gd" },
    }), "godot-abc123");
    expect(card?.statusMessage).toBe("Read scripts/player.gd");
    expect(card?.details).toContain("scripts/player.gd");
  });
  it("classifies Write tool_use as file card with created badge", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "tool_use",
        tool_name: "Write",
        tool_input: {
          file_path: "scripts/PlayerController.cs",
          content: "using Godot;\n\npublic partial class PlayerController : CharacterBody2D\n{\n    [Export] public float Speed = 200f;\n}",
        },
      }),
      "godot-abc123"
    );
    expect(card).not.toBeNull();
    expect(card!.type).toBe("file");
    expect(card!.fileAction).toBe("created");
    expect(card!.filePath).toBe("scripts/PlayerController.cs");
    expect(card!.fileContent).toContain("CharacterBody2D");
  });

  it("classifies Edit tool_use as file card with edited badge", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "tool_use",
        tool_name: "Edit",
        tool_input: {
          file_path: "scripts/Enemy.cs",
          old_string: "[Export] public int Hp = 100;",
          new_string: "[Export] public int Hp = 50;",
        },
      }),
      "godot-abc123"
    );
    expect(card!.type).toBe("file");
    expect(card!.fileAction).toBe("edited");
    expect(card!.fileContent).toContain("--- old");
    expect(card!.fileContent).toContain("[Export] public int Hp = 50;");
  });

  it("classifies Bash tool_use as command card", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "tool_use",
        tool_name: "Bash",
        tool_input: { command: "godot --headless --quit" },
      }),
      "godot-abc123"
    );
    expect(card!.type).toBe("command");
    expect(card!.command).toBe("godot --headless --quit");
  });

  it("classifies Bash asset_gen.py as asset card", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "tool_use",
        tool_name: "Bash",
        tool_input: { command: "python3 asset_gen.py image --prompt 'a cat'" },
      }),
      "godot-abc123"
    );
    expect(card!.type).toBe("asset");
  });

  it("classifies PLAN.md Write as plan card", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "tool_use",
        tool_name: "Write",
        tool_input: {
          file_path: "/tmp/game/PLAN.md",
          content: "# Game Plan\n## 1. Player movement\n## 2. Enemies",
        },
      }),
      "godot-abc123"
    );
    expect(card!.type).toBe("plan");
    expect(card!.planContent).toContain("Game Plan");
  });

  it("classifies thinking as thinking card", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "thinking",
        content: "I need to implement the physics body",
      }),
      "godot-abc123"
    );
    expect(card!.type).toBe("thinking");
    expect(card!.thinkingText).toContain("physics body");
  });

  it("classifies error as error card", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "error",
        content: "Parser Error: unexpected token at line 12",
      }),
      "godot-abc123"
    );
    expect(card!.type).toBe("error");
    expect(card!.errorMessage).toContain("Parser Error");
  });

  it("classifies screenshot tool_result as screenshot card", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "tool_result",
        content: "Screenshot saved to screenshots/task_1.png",
      }),
      "godot-abc123"
    );
    expect(card!.type).toBe("screenshot");
    expect(card!.imageUrl).toContain("/api/v1/godot/games/godot-abc123/screenshot");
  });

  it("builds screenshot and preview URLs for the game's own engine", () => {
    const result = (content: string, gameId: string) =>
      classifyEvent(makeCLIEvent({ stream_type: "tool_result", content }), gameId)!;

    const bevyPreview = result("Wrote /games/bevy-abc123/assets/img/ship.png", "bevy-abc123");
    expect(bevyPreview.type).toBe("preview");
    expect(bevyPreview.previewUrl).toContain("/api/v1/bevy/games/bevy-abc123/assets/assets/img/ship.png");
    expect(bevyPreview.previewUrl).not.toContain("/godot/");

    const bevyShot = result("Screenshot saved to screenshots/task_1.png", "bevy-abc123");
    expect(bevyShot.imageUrl).toContain("/api/v1/bevy/games/bevy-abc123/screenshot");

    const godotPreview = result("Wrote /games/godot-abc123/assets/img/ship.png", "godot-abc123");
    expect(godotPreview.previewUrl).toContain("/api/v1/godot/games/godot-abc123/assets/assets/img/ship.png");
  });

  it("classifies unknown non-read-only tool as status card", () => {
    const card = classifyEvent(
      makeCLIEvent({
        stream_type: "tool_use",
        tool_name: "TodoWrite",
        tool_input: { todos: [] },
      }),
      "godot-abc123"
    );
    expect(card!.type).toBe("status");
    expect(card!.statusMessage).toContain("TodoWrite");
  });

  it("returns null for events with no message or content", () => {
    const card = classifyEvent(
      {
        timestamp: new Date().toISOString(),
        level: "info",
        category: "user",
        service: "test",
        event_type: "StatusEvent",
      } as ObservabilityEvent,
      null
    );
    expect(card).toBeNull();
  });

  it("handles legacy StatusEvent as status card", () => {
    const card = classifyEvent(
      {
        timestamp: new Date().toISOString(),
        level: "info",
        category: "user",
        service: "test",
        event_type: "StatusEvent",
        message: "Exporting to browser...",
      } as ObservabilityEvent,
      "godot-abc123"
    );
    expect(card!.type).toBe("status");
    expect(card!.statusMessage).toBe("Exporting to browser...");
  });

  it("handles ErrorEvent as error card", () => {
    const card = classifyEvent(
      {
        timestamp: new Date().toISOString(),
        level: "error",
        category: "error",
        service: "test",
        event_type: "ErrorEvent",
        error_message: "Godot binary not found",
      } as ObservabilityEvent,
      null
    );
    expect(card!.type).toBe("error");
    expect(card!.errorMessage).toBe("Godot binary not found");
  });
});
