import { describe, expect, it } from "vitest";
import { describeEditEvent, editActivities, editStage, editImages, editMessages, editorImageUrl, turnFromRun } from "../game-editor";
import type { ModificationRunEvent } from "../api";

describe("editing activity", () => {
  it("keeps distinct commentary in order without repeating reasoning or the final response", () => {
    const events: ModificationRunEvent[] = [
      { type: "thinking", content: "Inspecting the scene" },
      { type: "text", content: "Inspecting the scene" },
      { type: "text", content: "Updating the sky" },
      { type: "tool_result", content: "Updating the sky" },
      { type: "text", content: "Updating the sky" },
      { type: "text", content: " " },
      { type: "text", content: "Ready to play" },
    ];
    expect(editMessages(events, "Ready to play").map((event) => event.content)).toEqual(["Updating the sky"]);
    expect(editMessages(events).map((event) => event.content)).toEqual(["Updating the sky", "Ready to play"]);
  });
  it("only reports a build or verification stage after observing that pipeline event", () => {
    expect(editStage([])).toBe("Getting ready…");
    expect(editStage([{ type: "thinking", content: "I will export and verify after changing the sky" }])).toBe("Making your change…");
    expect(editStage([{ type: "status", content: "Re-exporting to browser..." }])).toBe("Putting your game together…");
    expect(editStage([{ type: "status", content: "Checking the updated game in the browser…" }])).toBe("Testing your game…");
    expect(editStage([{ type: "status", content: "Checking the updated game in the browser…" }, { type: "thinking", content: "Summary of the edit" }])).toBe("Testing your game…");
  });
  it("matches parallel tool results by invocation identity rather than finish order", () => {
    const events: ModificationRunEvent[] = [
      { type: "tool_use", metadata: { item_id: "item_1", tool_name: "command_execution", input: { command: "rg Score scripts/" } } },
      { type: "tool_use", metadata: { item_id: "item_2", tool_name: "command_execution", input: { command: "godot --headless --path . --quit" } } },
      { type: "tool_result", content: "Parser error", metadata: { item_id: "item_2", success: false, exit_code: 1 } },
      { type: "tool_result", content: "scripts/main.gd:28: Score", metadata: { item_id: "item_1", success: true, exit_code: 0 } },
    ];
    const activity = editActivities(events);
    expect(activity).toHaveLength(2);
    expect(activity[0].state).toBe("completed");
    expect(activity[0].result?.content).toContain("Score");
    expect(activity[1].state).toBe("failed");
    expect(activity[1].result?.content).toBe("Parser error");
    expect(events[0].metadata).not.toHaveProperty("result");
  });

  it("keeps reads, searches, unfamiliar tools and uncorrelated results visible", () => {
    const events: ModificationRunEvent[] = [
      { type: "tool_use", metadata: { tool_name: "Read", input: { file_path: "scripts/player.gd" } } },
      { type: "tool_use", metadata: { tool_name: "Grep", input: { pattern: "jump" } } },
      { type: "tool_use", metadata: { tool_name: "inspect_scene", input: { path: "scenes/main.tscn" } } },
      { type: "tool_result", content: "", metadata: { tool_use_id: "unavailable", success: true } },
    ];
    const activity = editActivities(events);
    expect(activity).toHaveLength(4);
    expect(activity.map((item) => item.summary)).toEqual(["Read scripts/player.gd", "Search jump", "Use inspect_scene · scenes/main.tscn", "Result"]);
    expect(activity[0].state).toBe("started");
  });

  it("preserves server timing and does not infer success from an agent's completion", () => {
    const activity = editActivities([
      { type: "complete", content: "Source updated", timestamp: "2026-10-14T17:00:00Z" },
      { type: "status", content: "Checking the updated game in the browser…" },
      { event_type: "failed", type: "error", content: "Canvas is blank" },
    ]);
    expect(activity[0].state).toBe("observed");
    expect(activity[0].event.timestamp).toBe("2026-10-14T17:00:00Z");
    expect(activity[2].state).toBe("failed");
    expect(turnFromRun({ run_id: "abc123", instruction: "Add clouds", status: "partial", error: "Canvas is blank" }).status).toBe("failed");
  });

  it("keeps the user's attached-image request readable after a refresh", () => {
    const turn = turnFromRun({
      run_id: "abc123", status: "success",
      instruction: "Use this palette\n\nReference image attached at: /game/_user_uploads/reference.png\nUse the Read tool to view this image.",
      explanation: "Updated the sky and terrain colors.", has_playable_build: true,
      attachments: [{ path: "_user_uploads/reference.png", name: "reference.png", media_type: "image/png" }],
      new_screenshots: ["screenshots/after.png"],
    });
    expect(turn.instruction).toBe("Use this palette");
    expect(turn.hasImage).toBe(true);
    expect(turn.response).toBe("Updated the sky and terrain colors.");
    expect(turn.verified).toBe(true);
    expect(turn.attachments?.[0].path).toBe("_user_uploads/reference.png");
    expect(editImages(turn)).toEqual(["screenshots/after.png"]);
  });

  it("uses an encoded owner-authorized image URL and rejects host paths and traversal", () => {
    expect(editorImageUrl("godot", "godot-test", "_user_uploads/my palette.png")).toContain("/api/v1/godot/games/godot-test/assets/_user_uploads/my%20palette.png");
    for (const path of ["/etc/private.png", "assets/../../private.png", "assets/../private.png", "https://example.com/x.png", "assets/x.png?token=bad", "assets/x.svg", "assets/./x.png"]) {
      expect(editorImageUrl("godot", "godot-test", path)).toBeNull();
    }
  });

  it("renders distinct image outputs instead of replacing history with the latest screenshot", () => {
    const turn = turnFromRun({ run_id: "images", instruction: "Add clouds", status: "success", new_screenshots: ["screenshots/after.png"] });
    turn.events = [
      { type: "thinking", content: "I could generate assets/not-made.png" },
      { type: "tool_result", content: "Saved /work/generated_games/godot-test/assets/sky.png" },
      { type: "tool_result", content: "Saved screenshots/after.png" },
      { type: "tool_result", content: "assets/failed.png", metadata: { success: false } },
    ];
    expect(editImages(turn)).toEqual(["screenshots/after.png", "assets/sky.png"]);
  });

  it("summarizes observed commands without claiming that they succeeded", () => {
    expect(describeEditEvent({ type: "tool_use", metadata: { tool_name: "Bash", input: { command: "godot --headless --export-release Web dist/index.html" } } })).toBe("Get the game ready to play");
  });

  it("marks an identified tool as failed when its error arrives outside tool_result", () => {
    const activity = editActivities([
      { type: "tool_use", metadata: { item_id: "scene-check", tool_name: "mcp_tool_call", input: { tool: "inspect_scene" } } },
      { type: "error", content: "Scene inspector failed", metadata: { item_id: "scene-check" } },
    ]);
    expect(activity).toHaveLength(1);
    expect(activity[0].state).toBe("failed");
    expect(activity[0].result?.content).toBe("Scene inspector failed");
  });

  it("does not leave tools running after their run is interrupted", () => {
    const activity = editActivities([
      { type: "tool_use", metadata: { item_id: "export", tool_name: "command_execution", input: { command: "godot --headless --export-release Web" } } },
      { event_type: "interrupted", content: "Edit cancelled" },
    ]);
    expect(activity[0].state).toBe("interrupted");
  });
});
