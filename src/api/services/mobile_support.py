"""Shared mobile/touch support helpers for generated browser games."""
from __future__ import annotations


MOBILE_CONTROLS_MARKER = "--- Mobile and Touch Runtime Requirement ---"

MOBILE_CONTROLS_REQUIREMENT = f"""
{MOBILE_CONTROLS_MARKER}
The game must be playable from the TinyWorlds app on phones and tablets, not
only from desktop keyboards:
- Implement touch or pointer controls for every primary action. Keyboard-only
  movement, menus, aiming, or interaction are not acceptable.
- Keep keyboard/gamepad controls where useful, but every gameplay-critical
  action must also have a touch path.
- Use visible or discoverable small-screen controls when needed: virtual
  joystick, large action buttons, tap/drag zones, swipe gestures, or direct
  tap interaction.
- Prevent browser scrolling, zooming, or text selection from stealing gameplay
  touches, and size camera/UI for both portrait and landscape mobile screens.
- For Godot, handle InputEventScreenTouch/InputEventScreenDrag or mouse/pointer
  fallback in _input/_unhandled_input.
- For Bevy, handle Touches/TouchInput or pointer/mouse/tap input in addition
  to keyboard input.
- Verify the browser/WebAssembly build remains playable using touch events, not
  only keyboard events.
"""


MOBILE_PLAY_HTML_MARKER = "tinyworlds-mobile-play-style"

_VIEWPORT_META = (
    '<meta name="viewport" '
    'content="width=device-width, initial-scale=1, viewport-fit=cover, user-scalable=no">'
)

_MOBILE_PLAY_HTML_SHIM = f"""
<style id="{MOBILE_PLAY_HTML_MARKER}">
html, body {{
  width: 100%;
  height: 100%;
  margin: 0;
  overflow: hidden;
  overscroll-behavior: none;
  touch-action: none;
  background: #000;
}}
canvas, #canvas {{
  touch-action: none;
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;
}}
</style>
<script id="tinyworlds-mobile-play-script">
(function() {{
  function isNativeControl(target) {{
    return target && target.closest && target.closest("input, textarea, select, button, a");
  }}
  function applyCanvasTouchPolicy() {{
    document.documentElement.style.touchAction = "none";
    if (document.body) {{
      document.body.style.touchAction = "none";
      document.body.style.overscrollBehavior = "none";
    }}
    document.querySelectorAll("canvas, #canvas").forEach(function(canvas) {{
      canvas.style.touchAction = "none";
      canvas.style.webkitUserSelect = "none";
      canvas.style.userSelect = "none";
      if (!canvas.hasAttribute("tabindex")) canvas.setAttribute("tabindex", "0");
      if (!canvas.__tinyworldsTouchFocus) {{
        canvas.__tinyworldsTouchFocus = true;
        canvas.addEventListener("pointerdown", function() {{ canvas.focus(); }});
        canvas.addEventListener("touchstart", function() {{ canvas.focus(); }}, {{passive: true}});
      }}
    }});
  }}
  document.addEventListener("touchmove", function(e) {{
    if (!isNativeControl(e.target)) e.preventDefault();
  }}, {{passive: false}});
  document.addEventListener("gesturestart", function(e) {{ e.preventDefault(); }}, {{passive: false}});
  window.addEventListener("resize", applyCanvasTouchPolicy);
  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", applyCanvasTouchPolicy);
  }} else {{
    applyCanvasTouchPolicy();
  }}
  new MutationObserver(applyCanvasTouchPolicy).observe(document.documentElement, {{
    childList: true,
    subtree: true
  }});
}})();
</script>
"""


MOBILE_OVERLAY_MARKER = "tinyworlds-mobile-overlay-style"

_MOBILE_OVERLAY_HTML = """
<div id="tinyworlds-mobile-overlay" aria-hidden="true">
  <div id="tw-stick"><div id="tw-stick-knob"></div></div>
  <button id="tw-btn-a" data-key="Space" type="button">A</button>
  <button id="tw-btn-b" data-key="Enter" type="button">B</button>
</div>
"""

_MOBILE_OVERLAY_SHIM = f"""
{_MOBILE_OVERLAY_HTML}
<style id="{MOBILE_OVERLAY_MARKER}">
#tinyworlds-mobile-overlay {{
  display: none;
  position: fixed;
  inset: 0;
  z-index: 2147483000;
  pointer-events: none;
  font-family: system-ui, sans-serif;
}}
@media (pointer: coarse) and (hover: none) and (max-width: 1024px) {{
  #tinyworlds-mobile-overlay {{ display: block; }}
}}
#tinyworlds-mobile-overlay #tw-stick {{
  position: absolute;
  left: 24px;
  bottom: 32px;
  width: 140px;
  height: 140px;
  border-radius: 50%;
  background: rgba(255,255,255,0.12);
  border: 2px solid rgba(255,255,255,0.35);
  pointer-events: auto;
  touch-action: none;
}}
#tinyworlds-mobile-overlay #tw-stick-knob {{
  position: absolute;
  left: 50%;
  top: 50%;
  width: 60px;
  height: 60px;
  margin-left: -30px;
  margin-top: -30px;
  border-radius: 50%;
  background: rgba(255,255,255,0.6);
  pointer-events: none;
  transition: background 0.1s;
}}
#tinyworlds-mobile-overlay button {{
  position: absolute;
  right: 32px;
  width: 84px;
  height: 84px;
  border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.5);
  background: rgba(255,255,255,0.18);
  color: #fff;
  font-size: 24px;
  font-weight: bold;
  pointer-events: auto;
  touch-action: none;
  -webkit-user-select: none;
  user-select: none;
}}
#tinyworlds-mobile-overlay #tw-btn-a {{ bottom: 32px; }}
#tinyworlds-mobile-overlay #tw-btn-b {{ bottom: 132px; right: 120px; }}
#tinyworlds-mobile-overlay button:active {{ background: rgba(255,255,255,0.5); }}
</style>
<script id="tinyworlds-mobile-overlay-script">
(function() {{
  // Opt-out check
  try {{
    if (window.location && window.location.search && window.location.search.indexOf("overlay=off") !== -1) return;
  }} catch (e) {{}}
  function bodyOptOut() {{
    return document.body && document.body.getAttribute && document.body.getAttribute("data-tw-overlay") === "off";
  }}

  var OVERLAY_ID = "tinyworlds-mobile-overlay";
  var KEY_MAP = {{
    up:    {{ key: "w", code: "KeyW" }},
    down:  {{ key: "s", code: "KeyS" }},
    left:  {{ key: "a", code: "KeyA" }},
    right: {{ key: "d", code: "KeyD" }}
  }};
  var activeKeys = {{}};
  var stickActive = false;
  var stickPointerId = null;

  function getCanvas() {{
    return document.querySelector("canvas");
  }}
  function fireKey(type, code, keyName) {{
    var canvas = getCanvas();
    var target = canvas || document.body || document.documentElement;
    if (!target) return;
    try {{
      var ev = new KeyboardEvent(type, {{
        key: keyName,
        code: code,
        bubbles: true,
        cancelable: true,
        composed: true
      }});
      target.dispatchEvent(ev);
      window.dispatchEvent(new KeyboardEvent(type, {{key: keyName, code: code, bubbles: true}}));
    }} catch (e) {{}}
  }}
  function keyDown(code, keyName) {{
    if (activeKeys[code]) return;
    activeKeys[code] = true;
    fireKey("keydown", code, keyName);
  }}
  function keyUp(code, keyName) {{
    if (!activeKeys[code]) return;
    activeKeys[code] = false;
    fireKey("keyup", code, keyName);
  }}
  function clearAllKeys() {{
    Object.keys(activeKeys).forEach(function(code) {{
      if (activeKeys[code]) {{
        var name = code.replace("Key", "").toLowerCase();
        keyUp(code, name);
      }}
    }});
  }}

  function buildOverlay() {{
    var existing = document.getElementById(OVERLAY_ID);
    if (existing) {{
      if (!existing.__twWired) {{
        existing.__twWired = true;
        // Ensure it's at the end of body so it stacks above engine UI
        if (document.body && existing.parentNode !== document.body) {{
          document.body.appendChild(existing);
        }} else if (document.body && existing.nextSibling) {{
          document.body.appendChild(existing);
        }}
        wireOverlay(existing);
      }}
      return existing;
    }}
    var root = document.createElement("div");
    root.id = OVERLAY_ID;
    root.innerHTML = ''
      + '<div id="tw-stick"><div id="tw-stick-knob"></div></div>'
      + '<button id="tw-btn-a" data-key="Space" type="button">A</button>'
      + '<button id="tw-btn-b" data-key="Enter" type="button">B</button>';
    root.__twWired = true;
    document.body.appendChild(root);
    wireOverlay(root);
    return root;
  }}

  function wireOverlay(root) {{
    var stick = root.querySelector("#tw-stick");
    var knob = root.querySelector("#tw-stick-knob");
    var radius = 70;
    var deadzone = radius * 0.15;

    function updateStick(clientX, clientY) {{
      var rect = stick.getBoundingClientRect();
      var cx = rect.left + rect.width / 2;
      var cy = rect.top + rect.height / 2;
      var dx = clientX - cx;
      var dy = clientY - cy;
      var dist = Math.sqrt(dx*dx + dy*dy);
      var clamped = Math.min(dist, radius);
      var nx = dist > 0 ? (dx / dist) * clamped : 0;
      var ny = dist > 0 ? (dy / dist) * clamped : 0;
      knob.style.transform = "translate(" + nx + "px, " + ny + "px)";

      if (dist < deadzone) {{
        keyUp("KeyW", "w"); keyUp("KeyS", "s"); keyUp("KeyA", "a"); keyUp("KeyD", "d");
        return;
      }}
      var angle = Math.atan2(dy, dx) * 180 / Math.PI; // -180..180
      // 8-direction: derive cardinal sets
      var up = angle < -22.5 && angle > -157.5;
      var down = angle > 22.5 && angle < 157.5;
      var right = angle > -67.5 && angle < 67.5;
      var left = angle > 112.5 || angle < -112.5;

      if (up) keyDown("KeyW", "w"); else keyUp("KeyW", "w");
      if (down) keyDown("KeyS", "s"); else keyUp("KeyS", "s");
      if (left) keyDown("KeyA", "a"); else keyUp("KeyA", "a");
      if (right) keyDown("KeyD", "d"); else keyUp("KeyD", "d");
    }}

    function resetStick() {{
      knob.style.transform = "translate(0px, 0px)";
      keyUp("KeyW", "w"); keyUp("KeyS", "s"); keyUp("KeyA", "a"); keyUp("KeyD", "d");
    }}

    stick.addEventListener("pointerdown", function(e) {{
      stickActive = true;
      stickPointerId = e.pointerId;
      try {{ stick.setPointerCapture(e.pointerId); }} catch (err) {{}}
      updateStick(e.clientX, e.clientY);
      e.preventDefault();
    }});
    stick.addEventListener("pointermove", function(e) {{
      if (!stickActive || e.pointerId !== stickPointerId) return;
      updateStick(e.clientX, e.clientY);
      e.preventDefault();
    }});
    function endStick(e) {{
      if (e.pointerId !== stickPointerId) return;
      stickActive = false;
      stickPointerId = null;
      resetStick();
      try {{ stick.releasePointerCapture(e.pointerId); }} catch (err) {{}}
    }}
    stick.addEventListener("pointerup", endStick);
    stick.addEventListener("pointercancel", endStick);
    stick.addEventListener("pointerleave", function(e) {{
      if (!stickActive) return;
      // leaving while held: still tracked via pointer capture, ignore
    }});

    root.querySelectorAll("button[data-key]").forEach(function(btn) {{
      var code = btn.getAttribute("data-key");
      var keyName = code === "Space" ? " " : (code === "Enter" ? "Enter" : code);
      btn.addEventListener("pointerdown", function(e) {{
        keyDown(code, keyName);
        e.preventDefault();
      }});
      var release = function(e) {{ keyUp(code, keyName); }};
      btn.addEventListener("pointerup", release);
      btn.addEventListener("pointercancel", release);
      btn.addEventListener("pointerleave", release);
      btn.addEventListener("contextmenu", function(e) {{ e.preventDefault(); }});
    }});
  }}

  function ensureOverlay() {{
    if (bodyOptOut()) {{
      var existing = document.getElementById(OVERLAY_ID);
      if (existing) existing.remove();
      return;
    }}
    if (!document.body) return;
    if (!document.getElementById(OVERLAY_ID)) buildOverlay();
  }}

  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", ensureOverlay);
  }} else {{
    ensureOverlay();
  }}
  window.addEventListener("blur", clearAllKeys);
  new MutationObserver(function() {{ ensureOverlay(); }}).observe(document.documentElement, {{
    childList: true,
    subtree: true
  }});
}})();
</script>
"""


def append_mobile_controls_requirement(prompt: str) -> str:
    """Append the mobile/touch gameplay contract once to a user instruction."""
    if MOBILE_CONTROLS_MARKER in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{MOBILE_CONTROLS_REQUIREMENT.strip()}"


def inject_mobile_play_shim(html: str) -> str:
    """Inject viewport, touch-action CSS, and canvas focus helpers into play HTML."""
    out = html
    if "name=\"viewport\"" not in out and "name='viewport'" not in out:
        if "</head>" in out:
            out = out.replace("</head>", f"{_VIEWPORT_META}\n</head>", 1)
        else:
            out = f"{_VIEWPORT_META}\n{out}"

    if MOBILE_PLAY_HTML_MARKER not in out:
        if "</head>" in out:
            out = out.replace("</head>", f"{_MOBILE_PLAY_HTML_SHIM}\n</head>", 1)
        else:
            out = f"{_MOBILE_PLAY_HTML_SHIM}\n{out}"

    if MOBILE_OVERLAY_MARKER not in out:
        if "</body>" in out:
            out = out.replace("</body>", f"{_MOBILE_OVERLAY_SHIM}\n</body>", 1)
        elif "</head>" in out:
            out = out.replace("</head>", f"{_MOBILE_OVERLAY_SHIM}\n</head>", 1)
        else:
            out = f"{out}\n{_MOBILE_OVERLAY_SHIM}"

    return out


_EMBEDDED_PLAY_FOCUS_SHIM = """<script id="tinyworlds-embedded-focus">
(function () {
  document.documentElement.inert = true;
  window.addEventListener('message', function (event) {
    if (window.parent === window || event.source !== window.parent) return;
    var action = event.data && event.data.action;
    if (action === 'tinyworlds:focus-editor') document.documentElement.inert = true;
    if (action === 'tinyworlds:activate-preview') {
      document.documentElement.inert = false;
      var canvas = document.querySelector('canvas');
      if (canvas) canvas.focus({preventScroll: true});
    }
  });
})();
</script>"""


def inject_embedded_play_focus(html: str) -> str:
    """Let the editor explicitly activate input without game startup stealing focus."""
    if 'id="tinyworlds-embedded-focus"' in html:
        return html
    if "<head>" in html:
        return html.replace("<head>", "<head>" + _EMBEDDED_PLAY_FOCUS_SHIM, 1)
    return _EMBEDDED_PLAY_FOCUS_SHIM + html
