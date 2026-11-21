import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for TinyWorlds E2E tests.
 *
 * Runs both Next.js frontend (port 3333) and FastAPI backend (port 8001).
 * Tests run against real backend for true integration testing.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["html", { open: "never" }], ["list"]],

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3333",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: [
    {
      // FastAPI backend
      command: "cd .. && uvicorn src.api.main:app --host 0.0.0.0 --port 8001",
      url: "http://localhost:8001/health",
      reuseExistingServer: !process.env.CI,
      timeout: 30000,
    },
    {
      // Next.js frontend — package.json `dev` script runs on :3333.
      command: "pnpm dev",
      url: "http://localhost:3333",
      reuseExistingServer: !process.env.CI,
      timeout: 30000,
    },
  ],
});
