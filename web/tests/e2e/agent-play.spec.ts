import { test, expect, type Page } from "@playwright/test";

const backend = process.env.AGENT_PLAY_BACKEND_URL ?? "http://localhost:8011";
async function session(page: Page) {
  const token = await page.evaluate(() => localStorage.getItem("tinyworlds_access_token"));
  const headers = { Authorization: `Bearer ${token}` };
  const response = await page.request.get(`${backend}/api/v1/agent-play/current`, { headers });
  expect(response.ok()).toBeTruthy();
  return { ...(await response.json()), headers };
}

test("Pip joins automatically on a phone with no setup or duplicate rounds", async ({ page }) => {
  let anonymousStarts = 0;
  const ids = new Set<string>();
  page.on("request", (request) => { if (request.method() === "POST" && request.url().endsWith("/auth/anonymous")) anonymousStarts++; });
  page.on("response", async (response) => {
    if (response.url().endsWith("/agent-play/connect") && response.ok()) ids.add((await response.json()).session_id);
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/agent-play");
  await expect(page.getByRole("status")).toHaveText("Your turn");
  await expect(page.getByText("Pip · local companion", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Sign in/i })).toHaveCount(0);
  await expect(page.getByTestId("user-menu")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Start playing|Start a new round|Copy session/ })).toHaveCount(0);
  await expect(page.getByText(/Session:|Invite your agent/)).toHaveCount(0);
  for (const name of ["Move up", "Move left", "Wait one turn", "Move right", "Move down"]) {
    await expect(page.getByRole("button", { name, exact: true })).toBeInViewport();
  }
  await page.getByRole("button", { name: "Move right", exact: true }).click();
  await expect.poll(async () => (await session(page)).revision).toBe(2);
  const state = await session(page);
  expect(state.positions.human).toEqual([1, 3]);
  expect(state.positions.agent).toEqual([6, 3]);
  expect(state.revision).toBe(2);
  await page.getByLabel("Game board. Use arrow keys or WASD to move.").focus();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => (await session(page)).revision).toBe(4);
  await page.reload();
  await expect(page.getByRole("status")).toHaveText("Your turn");
  await expect(page.getByLabel("Game board. Use arrow keys or WASD to move.")).toBeFocused();
  const resumed = await session(page);
  expect(resumed.session_id).toBe(state.session_id);
  expect(resumed.revision).toBe(4);
  expect(anonymousStarts).toBe(1);
  expect(ids.size).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: "../data/pip-20261109/phone.png", fullPage: true });
  await page.request.delete(`${backend}/api/v1/agent-play/${state.session_id}`, { headers: state.headers });
});

test("a linked agent finds the human's current round without setup or a session ID", async ({ page }) => {
  await page.goto("/agent-play");
  await expect(page.getByRole("status")).toHaveText("Your turn");
  await page.getByRole("button", { name: "Play against Pip", exact: true }).click();
  await expect(page.getByRole("heading", { name: "You vs Pip", exact: true })).toBeVisible();
  const state = await session(page);
  const joined = await page.request.post(`${backend}/api/v1/agent-play/join`, { headers: state.headers, data: {} });
  expect((await joined.json()).session_id).toBe(state.session_id);
  await expect(page.getByText("Pip · connected agent", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Move right", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Pip is thinking…");
  const data = { player: "agent", action: "left", expected_revision: 1 };
  const url = `${backend}/api/v1/agent-play/${state.session_id}/actions`;
  const moved = await page.request.post(url, { headers: state.headers, data });
  expect(moved.status()).toBe(200);
  expect((await moved.json()).positions.agent).toEqual([5, 3]);
  expect((await page.request.post(url, { headers: state.headers, data })).status()).toBe(409);
  await expect(page.getByRole("status")).toHaveText("Your turn");
  await page.screenshot({ path: "../data/pip-20261109/connected.png", fullPage: true });
  await page.getByRole("button", { name: "Leave game", exact: true }).click();
  await expect(page).toHaveURL(/\/create$/);
  expect((await page.request.get(`${backend}/api/v1/agent-play/${state.session_id}`, { headers: state.headers })).status()).toBe(404);
});

test("an expired round reconnects automatically without replaying a move", async ({ page }) => {
  await page.goto("/agent-play");
  await expect(page.getByRole("status")).toHaveText("Your turn");
  const old = await session(page);
  await page.request.delete(`${backend}/api/v1/agent-play/${old.session_id}`, { headers: old.headers });
  await expect.poll(async () => {
    const response = await page.request.get(`${backend}/api/v1/agent-play/current`, { headers: old.headers });
    return response.ok() && (await response.json()).session_id !== old.session_id;
  }, { timeout: 10000 }).toBe(true);
  const next = await session(page);
  expect(next.revision).toBe(0);
  await expect(page.getByRole("status")).toHaveText("Your turn");
  await page.request.delete(`${backend}/api/v1/agent-play/${next.session_id}`, { headers: next.headers });
});
