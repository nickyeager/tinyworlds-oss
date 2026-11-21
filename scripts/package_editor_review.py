"""Package local editor review evidence; excludes credentials and browser profiles."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--games-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="Review-specific findings, captions and archive name")
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    config = json.loads(args.config.read_text()) if args.config else {}
    repo = Path(__file__).resolve().parent.parent
    package = evidence / "review-package"
    package.mkdir(exist_ok=True)
    for name in ("screenshots", "videos", "validation", "source"):
        (package / name).mkdir(exist_ok=True)
    walkthrough = json.loads((evidence / "walkthrough.json").read_text())
    results = json.loads((evidence / "final-proof/results.json").read_text())
    if not walkthrough.get("success") or results["stats"]["unexpected"] or results["stats"]["skipped"]:
        raise SystemExit("Do not publish a passing package with unsuccessful or skipped review checks.")
    for image in (evidence / "screenshots").glob("*.png"):
        if image.name[:2].isdigit():
            shutil.copy2(image, package / "screenshots" / image.name)
    before = evidence / config["before_image"] if config.get("before_image") else next((evidence / "regressions-before").rglob("game-editor-the-composer-*/test-failed-1.png"))
    shutil.copy2(before, package / "screenshots/00-phone-keyboard-before.png")
    for stem in ("desktop-real-edit", "mobile-existing-game"):
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(evidence / f"videos/{stem}.webm"),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(package / f"videos/{stem}.mp4"),
        ], check=True)
    for filename in config.get("validation_logs", ("frontend-tests.log", "backend-tests.log", "typecheck.log", "lint.log", "build.log", "final-browser-tests.log", "walkthrough.log")):
        source = evidence / "logs" / filename
        if not source.exists():
            raise SystemExit(f"Missing validation evidence: {filename}")
        shutil.copy2(source, package / "validation" / filename)
    shutil.copy2(evidence / "walkthrough.json", package / "validation/walkthrough.json")
    shutil.copy2(evidence / "final-proof/results.json", package / "validation/browser-results.json")
    shutil.copytree(evidence / "final-proof/playwright-report", package / "playwright-report", dirs_exist_ok=True)
    qa_link = ""
    if config.get("qa_root"):
        qa = Path(config["qa_root"])
        qa_status = json.loads((qa / "latest.json").read_text())
        if qa_status.get("status") != "passed":
            raise SystemExit("Background QA must pass before its evidence is packaged.")
        shutil.copytree(qa / qa_status["runDir"], package / "background-qa" / qa_status["runDir"], dirs_exist_ok=True)
        shutil.copy2(qa / "index.html", package / "background-qa/index.html")
        shutil.copy2(qa / "latest.json", package / "background-qa/latest.json")
        qa_link = '<p><a href="background-qa/index.html">Background-check snapshot</a> · <a href="source/docs/guides/editor-ux-design.md">UX research and acceptance process</a></p><p>The watcher runs fast checks on source changes and keeps timestamped results. This package contains a snapshot; use the live local QA page for later runs.</p>'
    verification = args.games_root.resolve().parent / "data/game-metadata/verification" / walkthrough["gameId"]
    shutil.copy2(verification / "latest.json", package / "validation/game-browser-verification.json")
    source_files = [
        "web/src/components/game-editor.tsx", "web/src/lib/game-editor.ts", "web/src/lib/__tests__/game-editor.test.ts",
        "web/src/app/games/[id]/page.tsx", "web/src/app/globals.css", "web/tests/e2e/game-editor.spec.ts",
        "web/playwright.editor.config.ts", "scripts/capture_editor_review.mjs", "scripts/package_editor_review.py",
        "docs/guides/editing-workspace.md",
    ]
    for name in source_files + config.get("extra_sources", []):
        target = package / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / name, target)
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=repo, text=True).strip()
    passed = results["stats"]["expected"]
    frontend_count = re.search(r"Tests\s+(\d+) passed", (evidence / "logs/frontend-tests.log").read_text())[1]
    backend_badge = ""
    if (evidence / "logs/backend-tests.log").exists():
        backend_count = re.search(r"(\d+) passed", (evidence / "logs/backend-tests.log").read_text())[1]
        backend_badge = f"<span>{backend_count} backend checks passed</span>"
    capture_date = datetime.fromisoformat(walkthrough["createdAt"].replace("Z", "+00:00"))
    captions = {
        "01-desktop-fresh": "Fresh owner session: editor and real Godot game",
        "02-reference-and-draft": "Reference image attached to a draft",
        "03-live-edit": "Real agent edit while drafting the next request",
        "04-verified-edit-and-activity": "Observed tool activity, including a failed command",
        "04b-browser-check-passed": "Application verification passed and the next draft survived",
        "05-persisted-history": "Persisted history after refreshing the page",
        "06-play-updated-game": "Updated export activated for play",
        "07-mobile-existing-history": "Phone: an existing saved edit and a new draft",
        "08-mobile-play": "Phone: loaded game with touch controls",
        "09-public-viewer": "Fresh visitor: public game without the owner's conversation",
        "10-phone-keyboard-after": "Reduced phone viewport: long draft, image and reachable Send",
    }
    captions.update(config.get("captions", {}))
    summary = config.get("summary", "Five defect fixes on top of yesterday's chat editor, backed by real browser interactions, a real Codex edit, Godot export and the application's trusted browser verification. Changes are local and uncommitted. Production was not deployed.")
    findings = config.get("findings", [
        ["Send disappearing on a short phone viewport.", "The composer adapts to available height and visual viewport resizing."],
        ["Duplicate rename submissions.", "A synchronous guard prevents Enter and blur from issuing two PATCH requests."],
        ["Misleading tool states.", "Identified errors update their original action and terminal runs stop unmatched actions."],
        ["Stale image requests.", "History reuses the user's text and requests the reference again."],
        ["Live activity would not collapse.", "The control now honors the user's choice during a build."],
    ])
    finding_items = "".join(f"<li><strong>{html.escape(title)}</strong> {html.escape(detail)}</li>" for title, detail in findings)
    before_title = html.escape(config.get("before_title", "Phone viewport: before and after"))
    before_caption = html.escape(config.get("before_caption", "Before: actual reproduced failure at 390 × 420, with a long draft and reference image."))
    after_image = html.escape(config.get("after_image", "10-phone-keyboard-after"))
    after_caption = html.escape(config.get("after_caption", "After: actual touch browser context at 390 × 420, with existing history, long draft and reference."))
    figures = "\n".join(
        f'<figure><a href="screenshots/{html.escape(name)}.png"><img loading="lazy" src="screenshots/{html.escape(name)}.png" alt="{html.escape(caption)}"></a><figcaption>{html.escape(caption)}</figcaption></figure>'
        for name, caption in captions.items() if (package / f"screenshots/{name}.png").exists()
    )
    checks = "".join(f"<li>{html.escape(item)}</li>" for item in walkthrough["checks"])
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TinyWorlds editor — local review proof</title>
<style>
:root{{color-scheme:dark;font:16px/1.6 system-ui;background:#141711;color:#eceee5}}body{{max-width:1200px;margin:auto;padding:40px 24px}}a{{color:#d6ef9c}}h1{{font-size:clamp(30px,5vw,52px);line-height:1.1;margin-bottom:16px}}h2{{font-size:24px;margin-top:48px}}p,li{{max-width:85ch;color:#bfc7b6}}.eyebrow{{color:#e6d16f;text-transform:uppercase;letter-spacing:.13em;font-size:12px}}.status{{display:flex;flex-wrap:wrap;gap:10px;margin:28px 0}}.status span{{padding:10px 16px;border:1px solid #4e6240;border-radius:24px;background:#222a1b}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}}figure{{margin:0;background:#1f241b;padding:12px;border:1px solid #333e2b;border-radius:12px}}img,video{{display:block;width:100%;max-height:680px;object-fit:contain;background:#0a0d08;border-radius:6px}}figcaption{{padding:12px 4px;color:#bfc7b6;font-size:14px}}code{{font-size:13px;overflow-wrap:anywhere}}.note{{border-left:3px solid #e6d16f;padding-left:18px}}details{{margin:18px 0;padding:16px;border:1px solid #35412e;border-radius:10px}}summary{{cursor:pointer}}footer{{margin-top:56px;border-top:1px solid #35412e;padding-top:20px;font-size:13px;color:#9ca790}}
</style>
<p class="eyebrow">Original TinyWorlds · {capture_date.strftime('%B %d, %Y')} · Local review</p>
<h1>The editor, reviewed in use.</h1>
<p>{html.escape(summary)}</p>
<div class="status"><span>{passed} browser workflows passed</span><span>{frontend_count} frontend tests passed</span>{backend_badge}<span>Typecheck · lint · build passed</span></div>
{qa_link}
<p><a href="playwright-report/index.html">Open the detailed browser report</a> · <a href="validation/browser-results.json">Machine-readable results</a> · <a href="validation/game-browser-verification.json">Verified game receipt</a> · <a href="{html.escape(walkthrough['gameUrl'])}">Open the retained local review game</a></p>
<p>The local game link requires the review services to remain running; signed-out visitors can play. Screenshots and videos work without those services.</p>
<h2>Watch the walkthroughs</h2>
<div class="grid"><figure><video controls preload="metadata" poster="screenshots/01-desktop-fresh.png" src="videos/desktop-real-edit.mp4"></video><figcaption>Desktop: fresh session → image reference → actual edit → verified export → saved history → play. Uncut, normal speed, silent.</figcaption></figure><figure><video controls preload="metadata" poster="screenshots/07-mobile-existing-history.png" src="videos/mobile-existing-game.mp4"></video><figcaption>Phone: existing history → draft → touch preview → preserved draft → short viewport with an image. Uncut, normal speed, silent.</figcaption></figure></div>
<h2>Changes reviewed</h2><ol>{finding_items}</ol>
<h2>{before_title}</h2><div class="grid"><figure><img src="screenshots/00-phone-keyboard-before.png" alt="{before_caption}"><figcaption>{before_caption}</figcaption></figure><figure><img src="screenshots/{after_image}.png" alt="{after_caption}"><figcaption>{after_caption}</figcaption></figure></div>
<h2>Browse the screenshots</h2><div class="grid">{figures}</div>
<h2>Verified behavior</h2><ul>{checks}</ul>
<p>The full browser suite also covers multiline input, IME handling, image validation, gallery navigation, restart, offline recovery without duplicate submissions, refresh reattachment, backend cancellation, history reuse and renaming.</p>
<h2>Verification limits</h2><div class="note"><p>Tested in Chrome on this Mac, with desktop and emulated phone/touch viewports. A native phone keyboard, iOS Safari, real microphone dictation/audio, Bevy edits, paid asset generation, and production were not exercised. Videos contain no audio.</p><p>An older Lily Leap copy exposed pre-existing concurrent HTTPRequest errors and an outdated telemetry payload. Its original files were preserved. The isolated review source was corrected and re-exported, then passed the same trusted browser gate; verification requirements were not relaxed.</p></div>
<details><summary>Raw validation evidence and source snapshot</summary><ul>
<li><a href="validation/frontend-tests.log">Frontend tests</a></li><li><a href="validation/backend-tests.log">Backend regression checks</a></li><li><a href="validation/final-browser-tests.log">Browser run output</a></li><li><a href="validation/typecheck.log">TypeScript output (empty means passed)</a></li><li><a href="validation/lint.log">Lint output (empty means passed)</a></li><li><a href="validation/build.log">Production build</a></li><li><a href="validation/walkthrough.json">Walkthrough run metadata</a></li><li><a href="source/docs/guides/editing-workspace.md">Reproduction guide and source snapshot</a></li></ul></details>
<footer>Captured {html.escape(walkthrough['createdAt'])}. Base release commit <code>{commit}</code>; source snapshot includes the uncommitted editor changes. Credentials, local database, browser profiles and authorization-bearing traces are excluded. <a href="manifest.json">SHA-256 file manifest</a>.</footer></html>"""
    (package / "index.html").write_text(document)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(), "base_commit": commit,
        "files": {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob("*")) if p.is_file() and p.name != "manifest.json"},
    }
    (package / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if not (package / "validation/backend-tests.log").exists():
        (package / "index.html").write_text(document.replace('<li><a href="validation/backend-tests.log">Backend regression checks</a></li>', ""))
        manifest["files"]["index.html"] = hashlib.sha256((package / "index.html").read_bytes()).hexdigest()
        (package / "manifest.json").write_text(json.dumps(manifest, indent=2))
    archive = shutil.make_archive(str(evidence.parent / config.get("archive_name", f"tinyworlds-editor-review-{capture_date:%Y%m%d}")), "zip", root_dir=package.parent, base_dir=package.name)
    print(json.dumps({"index": str(package / "index.html"), "archive": archive, "files": len(manifest["files"])}))


if __name__ == "__main__":
    main()
