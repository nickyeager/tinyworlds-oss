import { defineConfig } from "@playwright/test";

/**
 * Minimal Playwright config for API-only e2e tests.
 * Expects backend already running on port 8001.
 * No webServer startup — use when servers are already running.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
  },
  projects: [{ name: "chromium" }],
});
