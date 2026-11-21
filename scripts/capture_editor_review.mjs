/** Capture an actual local editor walkthrough, including a real verified edit.
 * Requires an isolated backend on :8001 and frontend on :3333. No network mocks.
 * REVIEW_SOURCE_GAME must already pass the application's browser verification.
 */
import { createRequire } from "node:module";
import { cp, mkdir, readFile, writeFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(repo, "web/package.json"));
const { chromium, expect } = require("@playwright/test");
const output = path.resolve(process.env.EDITOR_PROOF_DIR ?? path.join(repo, "test_output/editor-review"));
const games = process.env.GAME_EDITOR_TEST_GAMES_DIR;
const source = process.env.REVIEW_SOURCE_GAME;
if (!games || !source) throw new Error("Set GAME_EDITOR_TEST_GAMES_DIR and REVIEW_SOURCE_GAME to isolated review paths.");
if (path.resolve(games) === path.join(repo, "generated_games")) throw new Error("Use an isolated games directory.");
await mkdir(path.join(output, "screenshots"), { recursive: true });
await mkdir(path.join(output, "videos"), { recursive: true });
const backend = "http://localhost:8001";
const baseURL = "http://localhost:3333";
const response = await fetch(`${backend}/api/v1/auth/anonymous`, { method: "POST" });
if (!response.ok) throw new Error(`Anonymous login failed: ${response.status}`);
const { access_token: token } = await response.json();
const headers = { Authorization: `Bearer ${token}` };
const ownerResponse = await fetch(`${backend}/api/v1/auth/me`, { headers });
if (!ownerResponse.ok) throw new Error(`Owner lookup failed: ${ownerResponse.status}`);
const owner = await ownerResponse.json();
const id = `godot-editor-review-${Date.now().toString(36)}`;
const project = path.join(games, id);
await cp(source, project, { recursive: true, filter: (file) => ![".git", ".godot", ".modifications", ".creation", "telemetry"].includes(path.basename(file)) });
for (const file of await readdir(project, { recursive: true })) {
  if (file.endsWith(".gd")) {
    const target = path.join(project, file);
    await writeFile(target, (await readFile(target, "utf8")).replaceAll(path.basename(source), id));
  }
}
const access = path.resolve(games, "..", "data", "game-metadata", `${id}.json`);
await mkdir(path.dirname(access), { recursive: true });
await writeFile(access, JSON.stringify({ owner_user_id: owner.id, visibility: "public" }), { mode: 0o600 });
// Keep credentials outside the proof package; useful for an owner review later.
await writeFile(path.resolve(games, "..", "review-session.json"), JSON.stringify({ id, token }), { mode: 0o600 });

const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE });
const evidence = { gameId: id, gameUrl: `${baseURL}/games/${id}`, createdAt: new Date().toISOString(), checks: [], errors: [], httpErrors: [] };
const composer = (page) => page.getByRole("textbox", { name: "Tell us what to change" });
async function context(options = {}) {
  const context = await browser.newContext({ baseURL, ...options });
  await context.addInitScript(({ token }) => {
    localStorage.setItem("tinyworlds_access_token", token);
    localStorage.setItem("tinyworlds_token_expiry", String(Date.now() + 86400000));
  }, { token });
  const page = await context.newPage();
  page.on("pageerror", (error) => evidence.errors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400) evidence.httpErrors.push({ path: new URL(response.url()).pathname, status: response.status() });
  });
  return { context, page };
}
async function screenshot(page, name) {
  await page.screenshot({ path: path.join(output, "screenshots", `${name}.png`) });
  // A reading pause for the review video, not a wait used to establish correctness.
  await page.waitForTimeout(1200);
}
async function loadedGame(page) {
  await expect.poll(() => page.frames().some((frame) => frame.url().includes("/play"))).toBeTruthy();
  const frame = page.frames().find((frame) => frame.url().includes("/play"));
  await expect.poll(() => frame.evaluate(() => {
    const canvas = document.querySelector("canvas");
    const status = document.getElementById("status");
    return Boolean(canvas?.width) && (!status || getComputedStyle(status).display === "none" || getComputedStyle(status).visibility === "hidden");
  }), { timeout: 30000 }).toBeTruthy();
  return frame;
}
async function saveVideo(context, page, name) {
  const video = page.video();
  await context.close();
  if (video) await video.saveAs(path.join(output, "videos", `${name}.webm`));
}

try {
  // Fresh owner entry and an actual model/export/browser-check cycle.
  const desktop = await context({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: path.join(output, "videos", "raw"), size: { width: 1440, height: 900 } } });
  const { page } = desktop;
  await page.goto(`/games/${id}`);
  await expect(composer(page)).toBeVisible();
  await loadedGame(page);
  await screenshot(page, "01-desktop-fresh");
  await composer(page).pressSequentially("Keep the movement playful, with a gentle sunset.", { delay: 35 });
  await page.getByLabel("Picture file").setInputFiles(path.join(project, "screenshots", "thumbnail.png"));
  await expect.poll(() => page.getByAltText("Picture to send").evaluate((img) => img.naturalWidth)).toBeGreaterThan(0);
  await screenshot(page, "02-reference-and-draft");
  if (process.argv.includes("--ux")) {
    await page.locator(".editor-starter").first().click();
    await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeVisible();
    await screenshot(page, "02a-undo-available");
    await page.getByRole("button", { name: "Undo", exact: true }).click();
    await expect(composer(page)).toHaveValue("Keep the movement playful, with a gentle sunset.");
    await screenshot(page, "02b-draft-restored");
    await page.reload();
    await expect(page.getByText("Your picture is missing.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Send change", exact: true })).toBeDisabled();
    await screenshot(page, "02c-reference-recovery");
    await page.getByLabel("Picture file").setInputFiles(path.join(project, "screenshots", "thumbnail.png"));
    await expect.poll(() => page.getByAltText("Picture to send").evaluate((img) => img.naturalWidth)).toBeGreaterThan(0);
    await page.context().setOffline(true);
    try {
      await expect(page.getByText("You're offline. Keep writing.", { exact: true })).toBeVisible();
      await screenshot(page, "02d-offline-draft");
    } finally { await page.context().setOffline(false); }
    evidence.checks.push("Draft UX: suggestion replacement can be undone with its image; refresh explains a missing reference and blocks sending; offline drafts remain editable.");
  }
  await page.getByRole("button", { name: "Remove picture" }).click();
  const instruction = "Change only the game's display name to Editor Review Verified in project.godot. Preserve gameplay, controls and assets. Do not generate assets.";
  await composer(page).fill(instruction);
  await page.getByRole("button", { name: "Send change", exact: true }).click();
  await expect(page.getByRole("button", { name: "Stop change" })).toBeVisible();
  await composer(page).pressSequentially("My next idea stays safely in this draft.", { delay: 25 });
  await screenshot(page, "03-live-edit");
  await expect(page.getByRole("button", { name: "Play your game" }).or(page.getByRole("button", { name: "Try again" }))).toBeVisible({ timeout: 270000 });
  await expect(page.getByRole("button", { name: "Play your game" })).toBeVisible();
  await expect(composer(page)).toHaveValue("My next idea stays safely in this draft.");
  if (process.argv.includes("--ux")) {
    await page.getByRole("button", { name: "Use again", exact: true }).click();
    await expect(composer(page)).toHaveValue(instruction);
    await screenshot(page, "05b-edit-request");
    await page.getByRole("button", { name: "Undo", exact: true }).click();
    await expect(composer(page)).toHaveValue("My next idea stays safely in this draft.");
    evidence.checks.push("Earlier requests can be edited directly in chat; replacing the next draft is recoverable with Undo.");
  }
  await loadedGame(page);
  await expect(composer(page)).toBeFocused();
  await page.getByRole("button", { name: /^Steps/ }).click();
  await screenshot(page, "04-verified-edit-and-activity");
  await page.getByText("Tested and working", { exact: true }).scrollIntoViewIfNeeded();
  await screenshot(page, "04b-browser-check-passed");
  await page.reload();
  await expect(page.getByRole("article")).toHaveCount(1);
  await expect(composer(page)).toHaveValue("My next idea stays safely in this draft.");
  await page.getByRole("button", { name: "See past changes" }).click();
  await expect(page.getByRole("heading", { name: "Past changes", exact: true })).toBeVisible();
  await screenshot(page, "05-persisted-history");
  await page.getByRole("main").getByRole("button", { name: "Use again", exact: true }).click();
  await expect(composer(page)).toHaveValue(instruction);
  await page.getByRole("combobox", { name: "Game view" }).selectOption("play");
  await page.getByRole("button", { name: "Play game" }).click();
  await page.keyboard.press("ArrowUp");
  await screenshot(page, "06-play-updated-game");
  evidence.checks.push("Fresh owner: image attach/remove, real edit, verified export, retained next draft, typing focus, refresh, history reuse, and game activation.");
  await saveVideo(desktop.context, page, "desktop-real-edit");

  // Existing saved edit, with a real touch browser context and independent storage.
  const mobile = await context({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1, recordVideo: { dir: path.join(output, "videos", "raw"), size: { width: 390, height: 844 } } });
  await mobile.page.goto(`/games/${id}`);
  await expect(mobile.page.getByRole("article")).toHaveCount(1);
  await composer(mobile.page).pressSequentially("Add fireflies to the next level.", { delay: 50 });
  await expect(composer(mobile.page)).toHaveValue("Add fireflies to the next level.");
  await screenshot(mobile.page, "07-mobile-existing-history");
  await mobile.page.getByRole("tab", { name: "Play", exact: true }).tap();
  const frame = await loadedGame(mobile.page);
  const origin = await frame.evaluate(() => performance.timeOrigin);
  await mobile.page.getByRole("button", { name: "Play game" }).tap();
  await screenshot(mobile.page, "08-mobile-play");
  await mobile.page.getByRole("tab", { name: "Change", exact: true }).tap();
  await expect(composer(mobile.page)).toHaveValue("Add fireflies to the next level.");
  await mobile.page.getByRole("tab", { name: "Play", exact: true }).tap();
  expect(await frame.evaluate(() => performance.timeOrigin)).toBe(origin);
  evidence.checks.push("Existing saved edit: phone touch navigation, draft preservation, playable export loaded, preview remains mounted.");
  await mobile.page.getByRole("tab", { name: "Change", exact: true }).tap();
  await mobile.page.setViewportSize({ width: 390, height: 420 });
  await composer(mobile.page).fill(Array.from({ length: 12 }, (_, index) => `Idea ${index + 1}: Keep the game playful.`).join("\n"));
  await mobile.page.getByLabel("Picture file").setInputFiles(path.join(project, "screenshots", "thumbnail.png"));
  await expect(mobile.page.getByRole("button", { name: "Send change", exact: true })).toBeInViewport({ ratio: 1 });
  await screenshot(mobile.page, "10-phone-keyboard-after");
  evidence.checks.push("Phone keyboard-height viewport: long multiline draft plus reference image leaves Send reachable. Native software keyboard was not exercised.");
  await saveVideo(mobile.context, mobile.page, "mobile-existing-game");

  const viewer = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const publicPage = await viewer.newPage();
  await publicPage.goto(`${baseURL}/games/${id}`);
  await loadedGame(publicPage);
  await expect(composer(publicPage)).toHaveCount(0);
  await screenshot(publicPage, "09-public-viewer");
  await viewer.close();
  evidence.checks.push("Fresh signed-out visitor: public play works and owner conversation is absent.");
  expect(evidence.errors).toEqual([]);
  expect(evidence.httpErrors).toEqual([]);
  const runsResponse = await fetch(`${backend}/api/v1/godot/games/${id}/modifications`, { headers });
  const { runs } = await runsResponse.json();
  evidence.runs = runs;
  evidence.success = true;
} finally {
  await writeFile(path.join(output, "walkthrough.json"), JSON.stringify(evidence, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ success: evidence.success, gameUrl: evidence.gameUrl, checks: evidence.checks.length, errors: evidence.errors, httpErrors: evidence.httpErrors }));
