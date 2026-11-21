import { test as base, expect, type Page } from "@playwright/test";
import { appendFile, cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

// Generation tasks are explicit acceptance checks; background UX runs exclude them.

const backend = process.env.GAME_EDITOR_BACKEND_URL ?? "http://localhost:8001";
const repo = path.resolve(__dirname, "../../..");
const gamesRoot = process.env.GAME_EDITOR_TEST_GAMES_DIR ?? path.join(repo, "generated_games");
async function existingGame(): Promise<string> {
  if (process.env.GAME_EDITOR_TEST_SOURCE) return process.env.GAME_EDITOR_TEST_SOURCE;
  for (const name of await readdir(path.join(repo, "generated_games"))) {
    const game = path.join(repo, "generated_games", name);
    try { await readFile(path.join(game, "project.godot")); await readFile(path.join(game, "dist", "index.wasm")); return game; }
    catch { /* Find a real browser-exported Godot game. */ }
  }
  throw new Error("Editor E2E needs a real exported Godot game. Set GAME_EDITOR_TEST_SOURCE to its project directory.");
}
const test = base.extend<{ editorGame: { id: string; token: string; project: string } }>({
  editorGame: async ({ page, request }, use) => {
    const response = await request.post(`${backend}/api/v1/auth/anonymous`);
    expect(response.ok()).toBeTruthy();
    const { access_token: token } = await response.json();
    const ownerResponse = await request.get(`${backend}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
    const owner = await ownerResponse.json();
    const id = `godot-editor-${randomUUID().slice(0, 8)}`;
    const project = path.join(gamesRoot, id);
    const accessFile = path.resolve(gamesRoot, "..", "data", "game-metadata", `${id}.json`);
    const source = await existingGame();
    await cp(source, project, { recursive: true, filter: (file) => ![".git", ".godot", ".modifications", ".creation", "telemetry"].includes(path.basename(file)) });
    // Rebind the copied game's own telemetry to its isolated test identity.
    for (const file of await readdir(project, { recursive: true })) {
      if (file.endsWith(".gd")) {
        const target = path.join(project, file);
        const text = await readFile(target, "utf8");
        await writeFile(target, text.replaceAll(path.basename(source), id));
      }
    }
    await rm(path.join(project, "MEMORY.md"), { force: true });
    await mkdir(path.dirname(accessFile), { recursive: true });
    await writeFile(accessFile, JSON.stringify({ owner_user_id: owner.id, visibility: "public" }));
    await page.addInitScript(({ token }) => {
      localStorage.setItem("tinyworlds_access_token", token);
      localStorage.setItem("tinyworlds_token_expiry", String(Date.now() + 86400000));
    }, { token });
    await use({ id, token, project });
    await request.post(`${backend}/api/v1/games/${id}/cancel`, { headers: { Authorization: `Bearer ${token}` } });
    await rm(project, { recursive: true, force: true }); await rm(accessFile, { force: true });
    await rm(path.join(path.dirname(accessFile), "verification", id), { recursive: true, force: true });
  },
});
const composer = (page: Page) => page.getByRole("textbox", { name: "Tell us what to change" });
/** True when an open step row sits inside the visible part of the conversation. */
const stepsInView = (page: Page) => page.getByRole("log").evaluate((log) => {
  const view = log.getBoundingClientRect();
  return [...log.querySelectorAll(".editor-activity-row")].some((row) => {
    const box = row.getBoundingClientRect();
    return box.height > 0 && box.bottom > Math.max(view.top, 0) && box.top < Math.min(view.bottom, window.innerHeight);
  });
});
async function loadedGame(page: Page) {
  await expect.poll(() => page.frames().some((frame) => frame.url().includes("/play"))).toBeTruthy();
  const frame = page.frames().find((frame) => frame.url().includes("/play"))!;
  await expect.poll(() => frame.evaluate(() => {
    const canvas = document.querySelector("canvas");
    const status = document.getElementById("status");
    return document.readyState === "complete" && Boolean(canvas && canvas.width > 0) && (!status || getComputedStyle(status).display === "none" || getComputedStyle(status).visibility === "hidden");
  }), { timeout: 30000 }).toBeTruthy();
  return frame;
}

test("creation examples fill an editable prompt without submitting a build", async ({ page }) => {
  let starts = 0;
  // A regression must fail without spending provider inference.
  await page.route("**/api/v1/games", async (route) => {
    if (route.request().method() === "POST") { starts++; await route.abort(); }
    else await route.continue();
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/create");
  await page.getByText("Need an idea?", { exact: true }).click();
  await page.getByRole("button", { name: "Maze chase", exact: true }).click();
  const prompt = page.getByRole("textbox", { name: "Your game idea" });
  await expect(prompt).toHaveValue(/glowing maze/);
  await expect(prompt).toBeFocused();
  await prompt.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true });
  await page.getByRole("button", { name: "Space shooter", exact: true }).click();
  await expect(prompt).toHaveValue(/space shooter/);
  await expect(page.getByRole("button", { name: "Make my game", exact: true })).toBeEnabled();
  expect(starts).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test("sharing offers a copyable link when secure browser APIs are unavailable", async ({ page, editorGame }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    Object.defineProperty(navigator, "share", { value: undefined, configurable: true });
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`/games/${editorGame.id}`);
  await expect(composer(page)).toBeVisible();
  await page.getByRole("button", { name: "Share", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Share link" })).toHaveValue(page.url());
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  expect(errors).toEqual([]);
});

test("history switches runs and refreshes the selected result without reloading the game", async ({ page, editorGame }) => {
  const root = path.join(editorGame.project, ".modifications");
  for (const [id, instruction, result, minute] of [["historyaaa", "Add clouds", "Clouds added.", "01"], ["historybbb", "Add keys", "Keys added.", "02"]]) {
    await mkdir(path.join(root, id), { recursive: true });
    await writeFile(path.join(root, id, "summary.json"), JSON.stringify({ run_id: id, instruction, final_message: result, status: "success", started_at: `2026-11-01T10:${minute}:00Z` }));
  }
  await page.goto(`/games/${editorGame.id}`);
  const frame = await loadedGame(page);
  const origin = await frame.evaluate(() => performance.timeOrigin);
  await page.getByRole("combobox", { name: "Game view" }).selectOption("modifications");
  const main = page.getByRole("main", { name: "Game" });
  await expect(main.getByText("Keys added.", { exact: true })).toBeVisible();
  await main.getByRole("button", { name: /Add clouds/ }).click();
  await expect(main.getByText("Clouds added.", { exact: true })).toBeVisible();
  await main.getByRole("button", { name: /Add keys/ }).click();
  await expect(main.getByText("Keys added.", { exact: true })).toBeVisible();
  const summaryFile = path.join(root, "historybbb", "summary.json");
  const summary = JSON.parse(await readFile(summaryFile, "utf8"));
  await writeFile(summaryFile, JSON.stringify({ ...summary, final_message: "Keys and doors added." }));
  await main.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(main.getByText("Keys and doors added.", { exact: true })).toBeVisible();
  expect(await frame.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("creation reattaches after going offline without submitting another game", async ({ page, editorGame }) => {
  const creation = path.join(editorGame.project, ".creation");
  await mkdir(creation, { recursive: true });
  await writeFile(path.join(creation, "events.jsonl"), JSON.stringify({ event_type: "init", game_id: editorGame.id, engine: "godot" }) + "\n");
  let starts = 0;
  await page.route("**/api/v1/games", async (route) => {
    if (route.request().method() === "POST") { starts++; await route.abort(); }
    else await route.continue();
  });
  await page.goto(`/create?gameId=${editorGame.id}`);
  await expect(page.getByRole("button", { name: "Stop", exact: true })).toBeEnabled();
  await page.context().setOffline(true);
  try {
    await expect(page.getByRole("heading", { name: "Reconnecting…" })).toBeVisible();
    await appendFile(path.join(creation, "events.jsonl"), JSON.stringify({ event_type: "done", game_id: editorGame.id }) + "\n");
  } finally { await page.context().setOffline(false); }
  await expect(page).toHaveURL(new RegExp(`/games/${editorGame.id}$`), { timeout: 20000 });
  await expect(composer(page)).toBeVisible();
  expect(starts).toBe(0);
});

test("Stop checks server cancellation and opens a build that already finished", async ({ page, editorGame }) => {
  const creation = path.join(editorGame.project, ".creation");
  await mkdir(creation, { recursive: true });
  await writeFile(path.join(creation, "events.jsonl"), JSON.stringify({ event_type: "init", game_id: editorGame.id, engine: "godot" }) + "\n");
  await page.goto(`/create?gameId=${editorGame.id}`);
  const stop = page.getByRole("button", { name: "Stop", exact: true });
  await expect(stop).toBeEnabled();
  const cancellation = page.waitForResponse((response) => response.request().method() === "POST" && response.url() === `${backend}/api/v1/games/${editorGame.id}/cancel`);
  await stop.click();
  expect((await cancellation).status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/games/${editorGame.id}$`));
});

test("suggestions, multiline drafts, IME input, reference images and refresh work together", async ({ page, editorGame }, info) => {
  let starts = 0;
  page.on("request", (request) => { if (request.method() === "POST" && request.url().includes("/modify/stream")) starts++; });
  await page.goto(`/games/${editorGame.id}`);
  await expect(composer(page)).toBeVisible();
  await expect(page.getByRole("button", { name: "Send change", exact: true })).toBeDisabled();
  await page.locator(".editor-starter").first().click();
  await expect(composer(page)).not.toHaveValue("");
  await composer(page).fill("Make the game feel more playful");
  await composer(page).press("Shift+Enter");
  await composer(page).pressSequentially("Keep the controls simple");
  await expect(composer(page)).toHaveValue("Make the game feel more playful\nKeep the controls simple");
  await composer(page).dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true });
  expect(starts).toBe(0);
  await page.reload();
  await expect(composer(page)).toHaveValue("Make the game feel more playful\nKeep the controls simple");
  await page.getByLabel("Picture file").setInputFiles(path.join(editorGame.project, "PLAN.md"));
  await expect(page.getByRole("complementary").getByRole("alert")).toContainText("PNG, JPG or WebP");
  const image = (await readdir(path.join(editorGame.project, "screenshots"))).find((name) => name.endsWith(".png"));
  expect(image).toBeDefined();
  await page.getByLabel("Picture file").setInputFiles(path.join(editorGame.project, "screenshots", image!));
  await expect(page.getByRole("complementary").getByRole("alert")).toHaveCount(0);
  await expect.poll(() => page.getByAltText("Picture to send").evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await loadedGame(page);
  await page.screenshot({ path: info.outputPath("desktop-editor.png") });
  await page.getByRole("button", { name: "Remove picture" }).click();
  await expect(page.getByAltText("Picture to send")).toHaveCount(0);
  expect(starts).toBe(0);
});

test("the game survives gallery navigation and chat focus changes", async ({ page, editorGame }) => {
  await page.goto(`/games/${editorGame.id}`); await expect(composer(page)).toBeVisible();
  const frame = await loadedGame(page); const origin = await frame.evaluate(() => performance.timeOrigin);
  const views = page.getByRole("combobox", { name: "Game view" });
  await expect(views).toHaveValue("play");
  await views.selectOption("gallery");
  const screenshot = page.getByRole("main", { name: "Game" }).getByRole("img").first();
  await expect(screenshot).toBeVisible();
  await expect.poll(() => screenshot.evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await views.selectOption("play");
  expect(await frame.evaluate(() => performance.timeOrigin)).toBe(origin);
  await composer(page).fill("Keep this draft while I play");
  await page.getByRole("button", { name: "Hide chat" }).click(); await expect(composer(page)).toBeHidden();
  await page.getByRole("button", { name: "Show chat" }).click(); await expect(composer(page)).toHaveValue("Keep this draft while I play");
  expect(await frame.evaluate(() => performance.timeOrigin)).toBe(origin);
  await page.getByRole("button", { name: "Restart game" }).click();
  await expect.poll(async () => {
    const restarted = page.frames().find((item) => item.url().includes("/play"));
    return restarted ? restarted.evaluate(() => performance.timeOrigin !== origin).catch(() => false) : false;
  }).toBeTruthy();
  await loadedGame(page);
});

test("screenshots show the verified capture when the legacy folder is empty", async ({ page, request, editorGame }, info) => {
  test.setTimeout(90000);
  await rm(path.join(editorGame.project, "screenshots"), { recursive: true, force: true });
  // Capture the real export using the same trusted verifier as generation.
  await promisify(execFile)(process.env.TINYWORLDS_API_PYTHON ?? path.join(repo, ".venv/bin/python"), ["-c", [
    "import asyncio, sys",
    "from pathlib import Path",
    "from src.api.services.browser_verification import verify_browser",
    "errors = asyncio.run(verify_browser(Path(sys.argv[1]), 'godot', []))",
    "assert not errors, errors",
  ].join("\n"), editorGame.project], { cwd: repo, env: {
    ...process.env, GODOT_GAMES_DIR: gamesRoot, DEBUG: "false",
    SECRET_KEY: "test-secret-key-for-testing-only",
    DATABASE_URL: "sqlite+aiosqlite:///:memory:",
  } });
  await page.goto(`/games/${editorGame.id}`);
  await expect(composer(page)).toBeVisible();
  await page.getByRole("combobox", { name: "Game view" }).selectOption("gallery");
  const screenshot = page.getByRole("main", { name: "Game" }).getByRole("img", { name: "Game preview", exact: true }).first();
  await expect(screenshot).toBeVisible();
  await expect.poll(() => screenshot.evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  const src = await screenshot.getAttribute("src");
  const response = await request.get(src!);
  expect(response.status()).toBe(200);
  const evidence = path.resolve(gamesRoot, "..", "data", "game-metadata", "verification", editorGame.id, "canvas.png");
  expect(await response.body()).toEqual(await readFile(evidence));
  await page.screenshot({ path: info.outputPath("verified-gallery-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "Play", exact: true }).click();
  await expect(screenshot).toBeVisible();
  await page.screenshot({ path: info.outputPath("verified-gallery-mobile.png") });
  await page.reload();
  await page.getByRole("tab", { name: "Play", exact: true }).click();
  await page.getByRole("combobox", { name: "Game view" }).selectOption("gallery");
  await expect(screenshot).toBeVisible();
  // A capture from an older export must not be advertised as the current game.
  await appendFile(path.join(editorGame.project, "dist", "index.html"), "\n<!-- changed export -->\n");
  const stale = await request.get(`${backend}/api/v1/godot/games/${editorGame.id}/media`, { headers: { Authorization: `Bearer ${editorGame.token}` } });
  expect((await stale.json()).screenshots).toEqual([]);
});

test("mobile keeps the composer visible and preserves the game across view changes", async ({ page, editorGame }, info) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto(`/games/${editorGame.id}`);
  await expect(composer(page)).toBeVisible(); await expect(page.getByRole("button", { name: "Hide chat" })).toBeHidden();
  await composer(page).fill("Add a sunset and fireflies");
  await expect(page.getByRole("button", { name: "Send change", exact: true })).toBeEnabled();
  const box = await page.getByRole("button", { name: "Send change", exact: true }).boundingBox();
  expect(box!.y + box!.height).toBeLessThan(844); expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: info.outputPath("mobile-chat.png") });
  await page.getByRole("tab", { name: "Play", exact: true }).click();
  const frame = await loadedGame(page); const origin = await frame.evaluate(() => performance.timeOrigin);
  await page.screenshot({ path: info.outputPath("mobile-preview.png") });
  await page.getByRole("tab", { name: "Change", exact: true }).click(); await expect(composer(page)).toHaveValue("Add a sunset and fireflies");
  await page.getByRole("tab", { name: "Play", exact: true }).click(); expect(await frame.evaluate(() => performance.timeOrigin)).toBe(origin);
});

test("refresh reattaches to the same real edit and Stop cancels the server job", { tag: "@generation" }, async ({ page, request, editorGame }) => {
  test.setTimeout(90000);
  const instruction = "Change only the game's display name to Editor Flow Test in project.godot. Do not generate assets or change gameplay.";
  let starts = 0;
  page.on("request", (request) => { if (request.method() === "POST" && request.url().includes("/modify/stream")) starts++; });
  await page.setViewportSize({ width: 1280, height: 540 });
  await page.goto(`/games/${editorGame.id}`); await composer(page).fill(instruction);
  await page.getByLabel("Picture file").setInputFiles(path.join(editorGame.project, "screenshots", "thumbnail.png"));
  await page.getByRole("button", { name: "Send change", exact: true }).click();
  await expect(page.getByRole("button", { name: "Stop change" })).toBeVisible(); await expect(composer(page)).toBeEnabled();
  const liveActivity = page.getByRole("button", { name: /^Steps/ });
  await expect(liveActivity).toHaveAttribute("aria-expanded", "false", { timeout: 30000 });
  await liveActivity.click();
  await expect(liveActivity).toHaveAttribute("aria-expanded", "true");
  await liveActivity.click();
  await expect(liveActivity).toHaveAttribute("aria-expanded", "false");
  await liveActivity.click();
  await expect(liveActivity).toHaveAttribute("aria-expanded", "true");
  // Opening the steps must leave them on screen.
  await expect.poll(() => stepsInView(page)).toBeTruthy();
  await composer(page).fill("Make the next level more mysterious");
  const headers = { Authorization: `Bearer ${editorGame.token}` };
  const runsUrl = `${backend}/api/v1/godot/games/${editorGame.id}/modifications`;
  await expect.poll(async () => (await (await request.get(runsUrl, { headers })).json()).runs.length).toBe(1);
  await expect(page.getByRole("article")).toHaveAttribute("data-run-id", /^[a-f0-9]{10}$/);
  await page.context().setOffline(true);
  try { await expect(page.getByText("Reconnecting…", { exact: true })).toBeVisible(); }
  finally { await page.context().setOffline(false); }
  await expect(page.getByText("Reconnecting…", { exact: true })).toHaveCount(0);
  await page.reload(); await expect(composer(page)).toHaveValue("Make the next level more mysterious");
  await expect(page.getByRole("article", { name: `Change: ${instruction}` })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Stop change" })).toBeVisible();
  const conversation = page.getByRole("log", { name: "Your changes" });
  await expect.poll(() => conversation.evaluate((el) => el.scrollHeight > el.clientHeight)).toBeTruthy();
  await conversation.hover();
  await page.mouse.wheel(0, -1000);
  await expect.poll(() => conversation.evaluate((el) => el.scrollTop)).toBeLessThan(5);
  await expect(page.getByRole("button", { name: /Jump to latest/ })).toBeVisible({ timeout: 20000 });
  expect(await conversation.evaluate((el) => el.scrollTop)).toBeLessThan(5);
  await page.getByRole("button", { name: "Stop change" }).click();
  await expect(page.getByRole("button", { name: "Stop change" })).toHaveCount(0); await expect(composer(page)).toHaveValue("Make the next level more mysterious");
  expect(starts).toBe(1);
  const { runs } = await (await request.get(runsUrl, { headers })).json(); expect(runs).toHaveLength(1); expect(runs[0].status).toBe("interrupted");
  await page.reload(); await expect(page.getByRole("article")).toHaveCount(1); await expect(page.getByRole("button", { name: "Stop change" })).toHaveCount(0);
  await page.getByRole("button", { name: "See past changes" }).click();
  await page.getByRole("main").getByRole("button", { name: "Use again", exact: true }).click();
  await expect(composer(page)).toHaveValue(instruction);
  await expect.poll(() => page.getByAltText("Picture to send").evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  expect(starts).toBe(1);
});

test("a real edit completes, reloads the playable export and keeps the next draft", { tag: "@generation" }, async ({ page, editorGame }, info) => {
  test.setTimeout(300000);
  let starts = 0;
  page.on("request", (request) => { if (request.method() === "POST" && request.url().includes("/modify/stream")) starts++; });
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`/games/${editorGame.id}`);
  await composer(page).fill("Change only the game's display name to Chat Editor Verified in project.godot. Keep gameplay and all assets the same. Do not generate any assets.");
  await page.getByRole("button", { name: "Send change", exact: true }).click(); await expect(page.getByRole("button", { name: "Stop change" })).toBeVisible();
  await composer(page).fill("My next idea stays here");
  await expect(page.getByRole("button", { name: "Play your game" }).or(page.getByRole("button", { name: "Try again" }))).toBeVisible({ timeout: 270000 });
  await expect(page.getByRole("button", { name: "Play your game" })).toBeVisible();
  await expect(composer(page)).toHaveValue("My next idea stays here");
  await loadedGame(page);
  await expect(composer(page)).toBeFocused();
  const runs = await (await page.request.get(`${backend}/api/v1/godot/games/${editorGame.id}/modifications`, { headers: { Authorization: `Bearer ${editorGame.token}` } })).json();
  const detail = await (await page.request.get(`${backend}/api/v1/godot/games/${editorGame.id}/modifications/${runs.runs[0].run_id}/events`, { headers: { Authorization: `Bearer ${editorGame.token}` } })).json();
  const toolCount = detail.events.filter((event: { type?: string }) => event.type === "tool_use").length;
  expect(toolCount).toBeGreaterThan(0);
  await page.getByRole("button", { name: /^Steps/ }).click();
  await expect(page.locator(".editor-activity-row[data-tool-name]")).toHaveCount(toolCount);
  await expect.poll(() => stepsInView(page)).toBeTruthy();
  expect(await readFile(path.join(editorGame.project, "project.godot"), "utf8")).toContain('config/name="Chat Editor Verified"');
  const latest = page.getByRole("button", { name: /Jump to latest/ });
  if (await latest.isVisible()) await latest.click();
  await expect(page.getByRole("button", { name: "Play your game" })).toBeInViewport();
  await expect(page.getByText("Tested and working", { exact: true })).toBeInViewport();
  const overflow = await page.getByRole("log").evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop);
  expect(overflow).toBeLessThanOrEqual(50);
  await page.screenshot({ path: info.outputPath("completed-edit.png") }); await page.reload();
  await expect(page.getByRole("article")).toHaveCount(1); await expect(page.getByRole("button", { name: "Play your game" })).toBeVisible();
  await expect(composer(page)).toHaveValue("My next idea stays here"); expect(errors).toEqual([]);
  await expect(page.getByRole("button", { name: "Play now", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Use again", exact: true }).click();
  await expect(composer(page)).toHaveValue("Change only the game's display name to Chat Editor Verified in project.godot. Keep gameplay and all assets the same. Do not generate any assets.");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(composer(page)).toHaveValue("My next idea stays here");
  expect(starts).toBe(1);
});

test("choosing an idea can be undone without losing the existing draft or reference", async ({ page, editorGame }, info) => {
  let starts = 0;
  page.on("request", (request) => { if (request.method() === "POST" && request.url().includes("/modify/stream")) starts++; });
  await page.goto(`/games/${editorGame.id}`);
  await composer(page).fill("Keep my hand-written idea and this reference");
  await page.getByLabel("Picture file").setInputFiles(path.join(editorGame.project, "screenshots", "thumbnail.png"));
  await page.locator(".editor-starter").first().click();
  await expect(composer(page)).not.toHaveValue("Keep my hand-written idea and this reference");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(composer(page)).toHaveValue("Keep my hand-written idea and this reference");
  await expect.poll(() => page.getByAltText("Picture to send").evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByText("Your words are back.", { exact: true })).toBeVisible();
  await composer(page).press("End");
  await composer(page).pressSequentially(".");
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  expect(starts).toBe(0);
  await page.screenshot({ path: info.outputPath("draft-recovery.png") });
});

test("a refreshed image draft restores its preview and can be sent", async ({ page, editorGame }, info) => {
  // Phones opening the LAN URL do not have the secure-context randomUUID API.
  await page.addInitScript(() => Object.defineProperty(window.crypto, "randomUUID", { value: undefined, configurable: true }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/games/${editorGame.id}`);
  await composer(page).fill("Use the colors in this reference");
  await page.getByLabel("Picture file").setInputFiles(path.join(editorGame.project, "screenshots", "thumbnail.png"));
  await expect(page.getByAltText("Picture to send")).toBeVisible();
  await page.reload();
  await expect(composer(page)).toHaveValue("Use the colors in this reference");
  await expect.poll(() => page.getByAltText("Picture to send").evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: "Send change", exact: true })).toBeEnabled();
  await page.screenshot({ path: info.outputPath("restored-reference.png") });
  await page.getByRole("button", { name: "Remove picture" }).click();
  await page.reload();
  await expect(page.getByText("Your picture is missing.", { exact: true })).toHaveCount(0);
  await expect(composer(page)).toHaveValue("Use the colors in this reference");
});

test("persisted reference and generated images load, enlarge, and survive refresh", async ({ page, request, editorGame }, info) => {
  const uploads = path.join(editorGame.project, "_user_uploads");
  await mkdir(uploads, { recursive: true });
  await cp(path.join(editorGame.project, "screenshots/thumbnail.png"), path.join(uploads, "palette.png"));
  const run = path.join(editorGame.project, ".modifications", "images1234");
  await mkdir(run, { recursive: true });
  await writeFile(path.join(run, "summary.json"), JSON.stringify({ run_id: "images1234", instruction: `Use this palette\n\nReference image attached at: ${uploads}/palette.png\nUse the Read tool to view this image.`, status: "success", explanation: "Updated the colors.", new_screenshots: ["screenshots/thumbnail.png"] }));
  await page.goto(`/games/${editorGame.id}`);
  await expect.poll(() => page.getByAltText("Your picture").evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await expect.poll(() => page.getByRole("log").getByAltText("thumbnail.png", { exact: true }).evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  // The same persistent asset must not become publicly readable.
  expect((await request.get(`${backend}/api/v1/godot/games/${editorGame.id}/assets/_user_uploads/palette.png`)).status()).toBe(401);
  await page.getByRole("button", { name: "Open picture: palette.png", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.reload();
  await expect.poll(() => page.getByAltText("Your picture").evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await page.screenshot({ path: info.outputPath("persisted-images.png") });
  await page.getByRole("button", { name: "Use again", exact: true }).click();
  await expect(page.getByAltText("Picture to send")).toBeVisible();
});

test("streaming and completion preserve history position until Jump to latest", async ({ page, editorGame }, info) => {
  const root = path.join(editorGame.project, ".modifications");
  for (let index = 0; index < 16; index++) {
    const id = `history${String(index).padStart(3, "0")}`;
    await mkdir(path.join(root, id), { recursive: true });
    await writeFile(path.join(root, id, "summary.json"), JSON.stringify({ run_id: id, status: "success", started_at: `2026-10-29T10:${String(index).padStart(2, "0")}:00Z`, instruction: `Earlier request ${index}`, explanation: "The level has clearer colors, more readable platforms, and responsive controls.\n\n".repeat(4) }));
  }
  const live = path.join(root, "stream1234");
  await mkdir(live, { recursive: true });
  await writeFile(path.join(live, "events.jsonl"), JSON.stringify({ event_type: "init", timestamp: "2026-10-29T11:00:00Z", metadata: { run_id: "stream1234", instruction: "Make the scene brighter" } }) + "\n");
  await page.goto(`/games/${editorGame.id}`);
  await expect(page.getByRole("button", { name: "Stop change" })).toBeVisible();
  const log = page.getByRole("log", { name: "Your changes" });
  await expect.poll(() => log.evaluate((node) => node.scrollTop)).toBeGreaterThan(100);
  await log.hover();
  await page.mouse.wheel(0, -100000);
  await expect.poll(() => log.evaluate((node) => node.scrollTop)).toBeLessThan(5);
  await appendFile(path.join(live, "events.jsonl"), JSON.stringify({ type: "text", content: "I am updating the lighting.\n\n".repeat(15) }) + "\n");
  await expect(page.getByText(/I am updating the lighting/).first()).toBeAttached();
  expect(await log.evaluate((node) => node.scrollTop)).toBeLessThan(5);
  await appendFile(path.join(live, "events.jsonl"), JSON.stringify({ event_type: "done", type: "complete", content: "Complete", metadata: { explanation: "The scene is brighter.", has_playable_build: true } }) + "\n");
  await expect(page.getByRole("button", { name: "Stop change" })).toHaveCount(0);
  expect(await log.evaluate((node) => node.scrollTop)).toBeLessThan(5);
  await page.getByRole("button", { name: "Jump to latest", exact: true }).click();
  await expect(page.getByRole("button", { name: "Play your game" }).last()).toBeInViewport();
  await expect(page.getByRole("button", { name: "Jump to latest", exact: true })).toBeHidden();
  await page.screenshot({ path: info.outputPath("streaming-scroll.png") });
});

test("chat width is adjustable by keyboard and survives refresh", async ({ page, editorGame }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`/games/${editorGame.id}`);
  const divider = page.getByRole("separator", { name: "Resize chat" });
  const panel = page.locator(".studio-side-panel");
  await expect(divider).toBeVisible();
  const before = (await panel.boundingBox())!.width;
  await divider.focus();
  await divider.press("ArrowRight");
  await expect.poll(async () => (await panel.boundingBox())!.width).toBe(before + 24);
  await page.reload();
  await expect.poll(async () => (await panel.boundingBox())!.width).toBe(before + 24);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(divider).toBeHidden();
  await expect(composer(page)).toBeVisible();
});

test("offline drafting preserves the request and explains why Send is unavailable", async ({ page, editorGame }, info) => {
  await page.goto(`/games/${editorGame.id}`);
  await composer(page).fill("Make the controls easier to use");
  await page.context().setOffline(true);
  try {
    await expect(page.getByText("You're offline. Keep writing.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Send change", exact: true })).toBeDisabled();
    await composer(page).pressSequentially(" and keep the same colors");
    await page.screenshot({ path: info.outputPath("offline-draft.png") });
  } finally { await page.context().setOffline(false); }
  await expect(page.getByRole("button", { name: "Send change", exact: true })).toBeEnabled();
  await expect(composer(page)).toHaveValue("Make the controls easier to use and keep the same colors");
});

test("edit history recovers when the first request after returning online also fails", async ({ page, editorGame }) => {
  let restoring = false;
  let failedReconnect = false;
  await page.route(`**/api/v1/godot/games/${editorGame.id}/modifications`, async (route) => {
    if (!restoring) await route.abort("connectionreset");
    else if (!failedReconnect) { failedReconnect = true; await route.abort("connectionreset"); }
    else await route.continue();
  });
  await page.goto(`/games/${editorGame.id}`);
  await composer(page).fill("Keep my draft through the network outage");
  await expect(page.getByRole("complementary").getByRole("button", { name: "Try again" })).toBeVisible();
  await page.context().setOffline(true);
  await expect(page.getByText("You're offline. Keep writing.", { exact: true })).toBeVisible();
  restoring = true;
  await page.context().setOffline(false);
  await expect(page.getByRole("button", { name: "Send change", exact: true })).toBeEnabled();
  expect(failedReconnect).toBe(true);
  await expect(composer(page)).toHaveValue("Keep my draft through the network outage");
});

test("a visitor can play but cannot see the owner's editing conversation", async ({ browser, editorGame }) => {
  const context = await browser.newContext(); const page = await context.newPage();
  const unauthorized: string[] = [];
  page.on("response", (response) => { if (response.status() === 401) unauthorized.push(new URL(response.url()).pathname); });
  await page.goto(`${process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3333"}/games/${editorGame.id}`);
  await loadedGame(page);
  expect(unauthorized).toEqual([]); await expect(composer(page)).toHaveCount(0); await expect(page.getByRole("button", { name: "See past changes" })).toHaveCount(0); await context.close();
});

test("the composer remains reachable with a reference and a long draft above a phone keyboard", async ({ page, editorGame }, info) => {
  await page.setViewportSize({ width: 390, height: 420 });
  await page.goto(`/games/${editorGame.id}`);
  await composer(page).fill(Array.from({ length: 12 }, (_, index) => `Idea ${index + 1}: Keep the game playful.`).join("\n"));
  await page.getByLabel("Picture file").setInputFiles(path.join(editorGame.project, "screenshots", "thumbnail.png"));
  await expect(page.getByAltText("Picture to send")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send change", exact: true })).toBeInViewport({ ratio: 1 });
  await expect(composer(page)).toBeInViewport();
  await page.screenshot({ path: info.outputPath("phone-keyboard.png") });
});

test("renaming submits once and Escape preserves the current name", async ({ page, request, editorGame }) => {
  const headers = { Authorization: `Bearer ${editorGame.token}` };
  const gameUrl = `${backend}/api/v1/godot/games/${editorGame.id}`;
  await page.goto(`/games/${editorGame.id}`);
  await expect(composer(page)).toBeVisible();
  let renames = 0;
  page.on("request", (request) => { if (request.method() === "PATCH" && request.url() === gameUrl) renames++; });
  await page.getByRole("button", { name: "Rename game" }).click();
  await page.getByRole("textbox", { name: "Game name", exact: true }).fill("Reviewed Lily Leap");
  await page.getByRole("textbox", { name: "Game name", exact: true }).press("Enter");
  await expect(page.getByRole("textbox", { name: "Game name", exact: true })).toHaveCount(0);
  expect(renames).toBe(1);
  await page.getByRole("button", { name: "Rename game" }).click();
  await page.getByRole("textbox", { name: "Game name", exact: true }).fill("Discard this name");
  await page.getByRole("textbox", { name: "Game name", exact: true }).press("Escape");
  await expect(page.getByRole("textbox", { name: "Game name", exact: true })).toHaveCount(0);
  const game = await (await request.get(gameUrl, { headers })).json();
  expect(game.name).toBe("Reviewed Lily Leap");
  expect(renames).toBe(1);
});


test("creation keeps optional controls tucked away and preserves the chosen budget", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/create");
  const budget = page.getByRole("spinbutton", { name: "Picture budget (cents)" });
  await expect(budget).toBeHidden();
  await expect(page.getByRole("button", { name: "Maze chase", exact: true })).toBeHidden();
  await page.getByText("Options", { exact: true }).click();
  await expect(budget).toHaveValue("0");
  await budget.fill("250");
  await page.getByText("Picture budget: $2.50", { exact: true }).click();
  await expect(budget).toBeHidden();
  await expect(page.getByText("Picture budget: $2.50", { exact: true })).toBeVisible();
  await page.getByText("Picture budget: $2.50", { exact: true }).click();
  await expect(budget).toHaveValue("250");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test("a failed game startup can be retried without losing the editing draft", async ({ page, editorGame }, info) => {
  const { rename } = await import("node:fs/promises");
  const wasm = path.join(editorGame.project, "dist", "index.wasm");
  const withheld = wasm + ".withheld";
  await rename(wasm, withheld);
  try {
    await page.goto(`/games/${editorGame.id}`);
    await composer(page).fill("Keep this idea while the game loads");
    const retry = page.getByRole("button", { name: "Try again", exact: true });
    await expect(retry).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole("button", { name: "Play game" })).toHaveCount(0);
    // An unrelated frame/window cannot forge a successful startup notification.
    await page.evaluate(() => window.postMessage({ type: "tinyworlds:preview-status", state: "ready" }, "*"));
    await expect(retry).toBeVisible();
    await page.screenshot({ path: info.outputPath("startup-recovery.png") });
    await rename(withheld, wasm);
    await retry.click();
    await loadedGame(page);
    await expect(page.getByRole("status", { name: "Game loading" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Play game" })).toBeVisible();
    await expect(composer(page)).toHaveValue("Keep this idea while the game loads");
    await page.getByRole("button", { name: "Play game" }).click();
    await expect(page.getByRole("button", { name: "Play game" })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath("startup-recovered.png") });
  } finally {
    try { await rename(withheld, wasm); } catch { /* Already restored for the retry. */ }
  }
});
