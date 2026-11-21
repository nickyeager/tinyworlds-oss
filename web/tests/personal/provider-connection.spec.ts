import { test, expect } from "@playwright/test";

// Run only against an explicitly configured, disposable PERSONAL_MODE instance.
const backend = process.env.PROVIDER_TEST_BACKEND;
const headers = { "X-TinyWorlds-Local": "1" };

test("personal setup connects a real local Codex login and rejects cross-origin changes", async ({ page, request }, info) => {
  test.setTimeout(120000);
  expect(backend, "Set PROVIDER_TEST_BACKEND to an isolated personal test server").toBeTruthy();
  const endpoint = `${backend}/api/v1/provider-connection`;
  expect((await request.get(endpoint)).status()).toBe(403);
  expect((await request.post(endpoint, { headers: { ...headers, Origin: "https://untrusted.example" }, data: { provider: "codex", method: "existing_cli" } })).status()).toBe(403);
  expect((await request.get(endpoint, { headers: { ...headers, Host: "untrusted.example" } })).status()).toBe(403);
  expect((await request.delete(endpoint, { headers })).ok()).toBeTruthy();

  await page.goto("/create");
  await expect(page).toHaveURL(/\/connect$/);
  await expect(page.getByRole("heading", { name: "Connect your AI" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("setup-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Sign in with ChatGPT", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: info.outputPath("setup-mobile.png") });

  await page.getByText("Model (optional)", { exact: true }).click();
  await page.getByRole("textbox", { name: "Model identifier" }).fill(process.env.PROVIDER_TEST_MODEL || "gpt-6.1-sol");
  await page.getByRole("button", { name: "Use existing Codex login", exact: true }).click();
  await expect(page.getByText("Codex is connected", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Check connection", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Connected", { timeout: 60000 });
  await page.reload();
  await expect(page.getByText("Codex is connected", { exact: true })).toBeVisible();
  await page.getByText("Model (optional)", { exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Model identifier" })).toHaveValue(process.env.PROVIDER_TEST_MODEL || "gpt-6.1-sol");
  await page.getByRole("link", { name: "Make a game", exact: true }).click();
  await expect(page).toHaveURL(/\/create$/);
  await expect(page.getByRole("link", { name: "AI connection" })).toBeVisible();
  await page.getByRole("link", { name: "AI connection" }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: info.outputPath("connected-desktop.png") });

  // Official OAuth start/cancel is real; completing a new account sign-in needs its owner.
  await page.getByRole("button", { name: "Sign in with ChatGPT", exact: true }).click();
  const login = page.getByRole("link", { name: "Open ChatGPT sign-in" });
  await expect(login).toBeVisible({ timeout: 35000 });
  const url = new URL((await login.getAttribute("href"))!);
  expect(["auth.openai.com", "auth.chatgpt.com", "chatgpt.com"]).toContain(url.hostname);
  expect(url.protocol).toBe("https:");
  await page.getByRole("button", { name: "Cancel sign-in", exact: true }).click();
  await expect(login).toHaveCount(0);
  await expect(page.getByText("Codex is connected", { exact: true })).toBeVisible();
  const state = await (await request.get(endpoint, { headers })).json();
  expect(state.pending_login).toBe(false);
  expect(state.connection.model).toBe(process.env.PROVIDER_TEST_MODEL || "gpt-6.1-sol");
  expect(Object.keys(state.connection).sort()).toEqual(["kind", "model", "provider"]);
  expect(await page.evaluate(() => Object.keys(localStorage).filter(key => /provider|api.?key|codex|claude/i.test(key)))).toEqual([]);
});
