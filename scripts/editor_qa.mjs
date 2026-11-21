/** Local editor QA: run once, or rerun fast checks in the background on changes. */
import { watch, openSync, closeSync } from "node:fs";
import { access, mkdir, readFile, writeFile, readdir, rm } from "node:fs/promises";
import { spawn, execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(import.meta.url);
const repo = path.resolve(path.dirname(script), "..");
const web = path.join(repo, "web");
const root = path.resolve(process.env.EDITOR_QA_ROOT ?? path.join(repo, "test_output/editor-qa"));
const controlPath = path.join(root, "controller.json");
const statusPath = path.join(root, "latest.json");
const command = process.argv[2] ?? "run";
const full = process.argv.includes("--full");
const watched = ["web/src", "web/tests/e2e", "web/playwright.editor.config.ts", "web/playwright.config.ts", "web/package.json", "web/tsconfig.json", "scripts/editor_qa.mjs"];
let child = null;
let stopping = false;

async function readJson(file) { try { return JSON.parse(await readFile(file, "utf8")); } catch { return null; } }
function isController(record) {
  if (!record?.pid || record.repo !== repo) return false;
  try { return execFileSync("ps", ["-p", String(record.pid), "-o", "command="], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).includes(`${script} watch`); }
  catch { return false; }
}
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
async function status(value) {
  const record = { ...value, updatedAt: new Date().toISOString(), watcherPid: command === "watch" ? process.pid : null };
  const temporary = `${statusPath}.${randomUUID()}.tmp`;
  await writeFile(temporary, JSON.stringify(record, null, 2));
  // A single owner serializes writes; replacement avoids partially read JSON.
  const { rename } = await import("node:fs/promises");
  await rename(temporary, statusPath);
  await writeFile(path.join(root, "index.html"), `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TinyWorlds editor QA</title><style>body{font:16px/1.6 system-ui;max-width:900px;margin:48px auto;padding:0 24px;background:#171915;color:#eceee5}a{color:#c7f464}li{margin:12px 0}code{overflow-wrap:anywhere}small{color:#b0b2a9}</style><h1>Editor background checks</h1><h2>${escape(record.status)}</h2><p>${escape(record.message ?? record.currentStep ?? "Waiting for editor changes.")}</p><small>Updated ${escape(record.updatedAt)}. Reopen to refresh.</small><ul>${(record.steps ?? []).map((step) => `<li>${escape(step.name)}: <strong>${escape(step.status)}</strong> <a href="${escape(step.log)}">Log</a></li>`).join("")}</ul>${record.runDir ? `<p><a href="${escape(record.runDir)}/browser/playwright-report/index.html">Browser report</a> · <a href="${escape(record.runDir)}/result.json">Run details</a></p>` : ""}<p>Fast mode runs unit tests, TypeScript, editor lint, and real browser tasks without generation. The full suite is an explicit command.</p><p><code>node scripts/editor_qa.mjs status</code><br><code>node scripts/editor_qa.mjs stop</code></p><p>Source fingerprint: <code>${escape(record.sourceHash)}</code></p></html>`);
  return record;
}

async function filesAt(item) {
  const absolute = path.join(repo, item);
  const { stat } = await import("node:fs/promises");
  if ((await stat(absolute)).isFile()) return [absolute];
  const entries = await readdir(absolute, { recursive: true, withFileTypes: true });
  return entries.filter((entry) => entry.isFile() && /\.(tsx?|mjs|json|css)$/.test(entry.name)).map((entry) => path.join(entry.parentPath, entry.name));
}
async function fingerprint() {
  const hash = createHash("sha256");
  for (const file of (await Promise.all(watched.map(filesAt))).flat().sort()) { hash.update(file); hash.update(await readFile(file)); }
  return hash.digest("hex");
}
async function step(name, args, directory, runDir, environment = {}) {
  const log = path.join(runDir, `${name}.log`);
  const fd = openSync(log, "w");
  const started = Date.now();
  let exitCode;
  try {
    exitCode = await new Promise((resolve) => {
      child = spawn("pnpm", args, { cwd: directory, env: { ...process.env, ...environment }, detached: true, stdio: ["ignore", fd, fd] });
      child.once("error", () => resolve(127));
      child.once("exit", (code) => resolve(code ?? 1));
    });
  } finally { closeSync(fd); child = null; }
  return { name, status: exitCode === 0 ? "passed" : "failed", exitCode, seconds: Math.round((Date.now() - started) / 100) / 10, log: path.relative(root, log) };
}
async function browserPrerequisites() {
  const source = process.env.GAME_EDITOR_TEST_SOURCE;
  const games = process.env.GAME_EDITOR_TEST_GAMES_DIR;
  if (!source || !games || path.resolve(games) === path.join(repo, "generated_games")) throw new Error("Set GAME_EDITOR_TEST_SOURCE and an isolated GAME_EDITOR_TEST_GAMES_DIR.");
  await access(path.join(source, "project.godot"));
  await access(path.join(source, "dist/index.wasm"));
  const health = await fetch("http://localhost:8001/health", { signal: AbortSignal.timeout(5000) });
  if (!health.ok) throw new Error(`Backend health returned ${health.status}.`);
  const frontend = await fetch(process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3333", { signal: AbortSignal.timeout(10000) });
  if (!frontend.ok) throw new Error(`Frontend returned ${frontend.status}.`);
  if (!full && !/next-devtools|hmr-client/.test(await frontend.text())) throw new Error("Start pnpm dev before background browser checks; a production build may serve stale source.");
}
async function run(reason = "manual") {
  const sourceHash = await fingerprint();
  const name = new Date().toISOString().replace(/[:.]/g, "-");
  const runDir = path.join(root, "runs", name);
  await mkdir(runDir, { recursive: true });
  let record = { status: "running", reason, mode: full ? "full" : "fast", startedAt: new Date().toISOString(), sourceHash, runDir: path.relative(root, runDir), steps: [] };
  for (const [name, args] of [
    ["unit", ["test:run"]],
    ["typecheck", ["exec", "tsc", "--noEmit"]],
    ["lint", ["exec", "eslint", "--max-warnings", "0", "src/components/game-editor.tsx", "src/hooks/use-editor-draft.ts", "src/lib/game-editor.ts", "src/lib/__tests__/game-editor.test.ts", "src/app/games/[id]/page.tsx", "tests/e2e/game-editor.spec.ts", "playwright.editor.config.ts"]],
  ]) {
    if (stopping) break;
    await status({ ...record, currentStep: name });
    record.steps.push(await step(name, args, web, runDir));
    if (record.steps.at(-1).status === "failed") { record.status = "failed"; break; }
  }
  if (record.status === "running" && !stopping) {
    try {
      await browserPrerequisites();
      await status({ ...record, currentStep: "browser" });
      record.steps.push(await step("browser", ["exec", "playwright", "test", "--config", "playwright.editor.config.ts", ...(!full ? ["--grep-invert", "@generation"] : [])], web, runDir, { EDITOR_PROOF_DIR: path.join(runDir, "browser"), EDITOR_QA_EXTERNAL_SERVERS: "1" }));
      record.status = record.steps.at(-1).status;
    } catch (error) { record.status = "blocked"; record.message = error.message; }
  }
  if (await fingerprint() !== sourceHash) { record.status = "superseded"; record.message = "Editor changed during this run; another run is required."; }
  if (stopping) record.status = "stopped";
  record.finishedAt = new Date().toISOString();
  await writeFile(path.join(runDir, "result.json"), JSON.stringify(record, null, 2));
  await status(record);
  const retained = (await readdir(path.join(root, "runs"))).sort().reverse();
  for (const old of retained.slice(10)) await rm(path.join(root, "runs", old), { recursive: true, force: true });
  return record;
}

await mkdir(root, { recursive: true });
const controller = await readJson(controlPath);
if (command === "status") {
  console.log(JSON.stringify({ watching: isController(controller), ...(await readJson(statusPath)) }, null, 2));
} else if (command === "stop") {
  if (isController(controller)) { process.kill(controller.pid, "SIGTERM"); console.log("Stopping the editor QA watcher."); }
  else console.log("Editor QA watcher is not running.");
} else if (command === "start") {
  if (isController(controller)) { console.log(`Editor QA is already watching (PID ${controller.pid}).`); process.exit(0); }
  const fd = openSync(path.join(root, "watcher.log"), "a");
  const worker = spawn(process.execPath, [script, "watch"], { cwd: repo, detached: true, stdio: ["ignore", fd, fd], env: { ...process.env, EDITOR_QA_ROOT: root } });
  worker.unref(); closeSync(fd);
  console.log(JSON.stringify({ watchingPid: worker.pid, status: statusPath, report: path.join(root, "index.html") }));
} else if (command === "run") {
  if (isController(controller)) throw new Error("The watcher owns this output directory. Use another EDITOR_QA_ROOT for a one-off run.");
  const result = await run();
  console.log(JSON.stringify({ status: result.status, report: path.join(root, "index.html") }));
  process.exitCode = result.status === "passed" ? 0 : 1;
} else if (command === "watch") {
  if (isController(controller)) throw new Error("Another editor QA watcher is already running.");
  await writeFile(controlPath, JSON.stringify({ pid: process.pid, repo, startedAt: new Date().toISOString() }), { mode: 0o600 });
  let running = false;
  let pending = false;
  let timer;
  let previousHash = "";
  const execute = async () => {
    if (running || stopping) { pending = true; return; }
    running = true;
    try {
      do {
        pending = false;
        previousHash = await fingerprint();
        await run("source change or startup");
        if (await fingerprint() !== previousHash) pending = true;
      } while (pending && !stopping);
    } catch (error) { await status({ status: "failed", message: error.message }); }
    finally { running = false; }
  };
  const watchers = watched.map((item) => watch(path.join(repo, item), { recursive: item.endsWith("/src") || item.endsWith("/e2e") }, () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (await fingerprint() !== previousHash) void execute();
    }, 1200);
  }));
  process.on("SIGTERM", async () => {
    stopping = true; clearTimeout(timer); watchers.forEach((watcher) => watcher.close());
    if (child?.pid) { try { process.kill(-child.pid, "SIGTERM"); } catch { /* It completed first. */ } }
    await rm(controlPath, { force: true });
    await status({ ...(await readJson(statusPath)), status: "stopped", message: "Background watcher stopped." });
    if (!running) process.exit(0);
  });
  await execute();
} else throw new Error("Usage: node scripts/editor_qa.mjs start|status|stop|run [--full]");
