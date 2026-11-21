import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base, testDir: "./tests/personal", testMatch: "**/provider-connection.spec.ts", fullyParallel: false, workers: 1,
  webServer: undefined, retries: 0,
  outputDir: process.env.PROVIDER_PROOF_DIR || "test-results/provider-connection",
  use: { ...base.use, video: "on", trace: "off", launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } },
});
