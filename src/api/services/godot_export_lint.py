"""Pre-export static lint for Godot games targeting web.

Catches the failure class where the agent verifies under one renderer
(typically forward_plus, used by the capture wrapper for bloom + write-movie)
but exports under another (gl_compatibility, required for WebGL2). Forward+
features silently no-op or hang the WASM thread under gl_compatibility, so
the game "exports successfully" but freezes in the browser.

Usage:
    failures = lint_for_web_export(game_path)
    if failures: ...  # block export, append to failure_log
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class LintFailure:
    rule: str
    detail: str
    file: str

    def as_message(self) -> str:
        return f"[{self.rule}] {self.detail} ({self.file})"


# Features set on Environment / WorldEnvironment that only work under
# forward_plus or mobile renderers. On gl_compatibility they are silently
# ignored at best, hang the renderer at worst. Strings match what the agent
# typically writes in scripts (e.g. `e.glow_enabled = true`).
_FORWARD_PLUS_ONLY_PATTERNS = [
    (r"\bglow_enabled\s*=\s*true\b", "Environment.glow_* requires forward_plus"),
    (r"\bglow_(intensity|strength|bloom|blend_mode|hdr_threshold)\s*=", "Environment.glow_* requires forward_plus"),
    (r"\btonemap_mode\s*=\s*Environment\.TONE_MAPPER_FILMIC\b", "Filmic tonemap requires forward_plus (use LINEAR or REINHARD on gl_compatibility)"),
    (r"\btonemap_mode\s*=\s*Environment\.TONE_MAPPER_ACES\b", "ACES tonemap requires forward_plus"),
    (r"\bsdfgi_enabled\s*=\s*true\b", "SDFGI requires forward_plus"),
    (r"\bssao_enabled\s*=\s*true\b", "SSAO requires forward_plus"),
    (r"\bssil_enabled\s*=\s*true\b", "SSIL requires forward_plus"),
    (r"\bssr_enabled\s*=\s*true\b", "Screen-space reflections require forward_plus"),
    (r"\bvolumetric_fog_enabled\s*=\s*true\b", "Volumetric fog requires forward_plus"),
]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _is_web_target(project_godot_text: str) -> bool:
    """Web target means rendering_method is gl_compatibility.

    Agents typically set:
        renderer/rendering_method="gl_compatibility"
        renderer/rendering_method.mobile="gl_compatibility"
    """
    return bool(
        re.search(
            r'^renderer/rendering_method\s*=\s*"gl_compatibility"',
            project_godot_text,
            re.MULTILINE,
        )
    )


# Per-pattern auto-patches applied to .gd/.cs lines before export. Each entry
# is (pattern, replacement_or_None). When `replacement` is None the matched
# line is commented out; otherwise the matched substring is replaced inline.
_AUTO_PATCHES = [
    (re.compile(r"\bglow_enabled\s*=\s*true\b"), None),
    (re.compile(r"\bglow_(intensity|strength|bloom|blend_mode|hdr_threshold)\s*=.*$", re.MULTILINE), None),
    (re.compile(r"\btonemap_mode\s*=\s*Environment\.TONE_MAPPER_FILMIC\b"), "tonemap_mode = Environment.TONE_MAPPER_LINEAR"),
    (re.compile(r"\btonemap_mode\s*=\s*Environment\.TONE_MAPPER_ACES\b"), "tonemap_mode = Environment.TONE_MAPPER_LINEAR"),
    (re.compile(r"\bsdfgi_enabled\s*=\s*true\b"), "sdfgi_enabled = false"),
    (re.compile(r"\bssao_enabled\s*=\s*true\b"), "ssao_enabled = false"),
    (re.compile(r"\bssil_enabled\s*=\s*true\b"), "ssil_enabled = false"),
    (re.compile(r"\bssr_enabled\s*=\s*true\b"), "ssr_enabled = false"),
    (re.compile(r"\bvolumetric_fog_enabled\s*=\s*true\b"), "volumetric_fog_enabled = false"),
]


def auto_patch_for_web_export(game_path: Path) -> List[str]:
    """Rewrite forward_plus-only writes to safe gl_compatibility equivalents.

    Returns the list of relative file paths that were modified. No-op when the
    project does not target gl_compatibility.
    """
    project_godot = game_path / "project.godot"
    if not project_godot.exists() or not _is_web_target(_read(project_godot)):
        return []

    modified: List[str] = []
    code_files = list((game_path / "scripts").rglob("*.gd")) + list(
        (game_path / "scripts").rglob("*.cs")
    )
    for cf in code_files:
        original = _read(cf)
        if not original:
            continue
        new_lines = []
        changed = False
        for line in original.splitlines(keepends=True):
            patched = line
            for pattern, replacement in _AUTO_PATCHES:
                if pattern.search(patched):
                    if replacement is None:
                        stripped = patched.lstrip()
                        indent = patched[: len(patched) - len(stripped)]
                        patched = f"{indent}# [auto-patch: forward_plus-only] {stripped}"
                    else:
                        patched = pattern.sub(replacement, patched)
                    changed = True
            new_lines.append(patched)
        if changed:
            cf.write_text("".join(new_lines), encoding="utf-8")
            modified.append(str(cf.relative_to(game_path)))
    return modified


def lint_for_web_export(game_path: Path) -> List[LintFailure]:
    """Lint a Godot project before exporting to web.

    Returns an empty list if the project is safe to export. Returns a list
    of :class:`LintFailure` describing each violation otherwise.

    Only runs the forward_plus-feature check when the project is configured
    for gl_compatibility (the web export target). Native targets are exempt.
    """
    failures: List[LintFailure] = []

    project_godot = game_path / "project.godot"
    if not project_godot.exists():
        return failures
    project_text = _read(project_godot)

    if not _is_web_target(project_text):
        return failures

    # Scan all .gd and .cs files for forward_plus-only API calls.
    code_files = list((game_path / "scripts").rglob("*.gd")) + list(
        (game_path / "scripts").rglob("*.cs")
    )
    # Also scan scene files — feature flags can be authored in .tscn.
    code_files += list((game_path / "scenes").rglob("*.tscn"))

    for cf in code_files:
        text = _read(cf)
        if not text:
            continue
        for pattern, message in _FORWARD_PLUS_ONLY_PATTERNS:
            for match in re.finditer(pattern, text):
                line_no = text[: match.start()].count("\n") + 1
                line_start = text.rfind("\n", 0, match.start()) + 1
                if text[line_start:match.start()].lstrip().startswith("#"):
                    continue
                failures.append(
                    LintFailure(
                        rule="forward_plus_only_feature",
                        detail=f"line {line_no}: {match.group(0)} — {message}",
                        file=str(cf.relative_to(game_path)),
                    )
                )

    return failures
