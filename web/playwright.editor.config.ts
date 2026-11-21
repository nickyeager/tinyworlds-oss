import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
import path from "node:path";
const proofDir = process.env.EDITOR_PROOF_DIR;
export default defineConfig({
  ...base, testMatch: "**/game-editor.spec.ts", fullyParallel: false, workers: 1,
  ...(process.env.EDITOR_QA_EXTERNAL_SERVERS === "1" ? { webServer: undefined } : {}),
  ...(proofDir ? {
    outputDir: path.resolve(proofDir, "browser-artifacts"),
    reporter: [["html", { open: "never", outputFolder: path.resolve(proofDir, "playwright-report") }], ["json", { outputFile: path.resolve(proofDir, "results.json") }], ["list"]],
  } : {}),
  use: {
    ...base.use,
    ...(proofDir ? { video: "on" as const, trace: "off" as const } : {}),
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
  },
});
