"""Trusted transport for game-defined, bounded second-player adapters."""
import json
from pathlib import Path
from urllib.parse import urlsplit

MARKER = 'id="tinyworlds-pip"'
SCRIPT = r'''
(() => {
  let meta = null, state = null, handler = null, lastAck = null;
  const seen = new Set();
  const origin = __ORIGIN__;
  const decode = value => typeof value === 'string' ? JSON.parse(value) : value;
  const emit = extra => {
    if (window.parent !== window) window.parent.postMessage({type:'tinyworlds:pip', ...extra}, origin);
  };
  const api = window.TinyWorldsPip = {
    localControl: true,
    register(value, callback) {
      try {
        const data = decode(value);
        if (!Array.isArray(data.actions) || !data.actions.length || data.actions.length > 64 ||
            data.actions.some(a => typeof a !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(a)) || typeof callback !== 'function') return false;
        meta = {protocol:1, actions:[...new Set(data.actions)]}; handler = callback;
        emit(api.snapshot()); return true;
      } catch { return false; }
    },
    publish(value) {
      try {
        const data = decode(value);
        if (!data || typeof data !== 'object' || Array.isArray(data) || JSON.stringify(data).length > 16000) return false;
        state = data; emit(api.snapshot()); return true;
      } catch { return false; }
    },
    snapshot() { return {ready:!!(meta && state), actions:meta?.actions || [], state:state || {}, acknowledgement:lastAck}; },
    ack(value) { try { const data = decode(value); lastAck = {id:data.id, accepted:data.accepted === true}; emit({ack:lastAck}); } catch {} },
    dispatch(command) {
      if (!meta || !handler || !meta.actions.includes(command.action) || typeof command.id !== 'string') return false;
      if (seen.has(command.id)) return true;
      seen.add(command.id); if (seen.size > 128) seen.delete(seen.values().next().value);
      try { handler(JSON.stringify(command)); return true; }
      catch { api.ack({id:command.id, accepted:false}); return false; }
    }
  };
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== origin || !event.data) return;
    const message = event.data;
    if (message.type === 'tinyworlds:pip:observe') emit(api.snapshot());
    if (message.type === 'tinyworlds:pip:control') api.localControl = message.external !== true;
    if (message.type === 'tinyworlds:pip:action') api.dispatch(message.command || {});
  });
})();
'''

GODOT_HELPER = '''extends Node
## Connect the game's actual second player; never route these actions to player one.
var bridge
var callback
var apply_action: Callable

func configure(actions: Array, action_handler: Callable) -> void:
    apply_action = action_handler
    if not OS.has_feature("web"):
        return
    bridge = JavaScriptBridge.get_interface("TinyWorldsPip")
    if bridge == null:
        return
    callback = JavaScriptBridge.create_callback(_on_action)
    bridge.register(JSON.stringify({"actions": actions}), callback)

func publish(observation: Dictionary) -> void:
    if bridge != null:
        bridge.publish(JSON.stringify(observation))

func local_control() -> bool:
    return bridge == null or bool(bridge.localControl)

func _on_action(args: Array) -> void:
    var command = JSON.parse_string(str(args[0]))
    if command is not Dictionary:
        return
    var accepted = bool(apply_action.call(str(command.get("action", ""))))
    bridge.ack(JSON.stringify({"id": command.get("id", ""), "accepted": accepted}))
'''

REQUIREMENT = '''
## Pip: automatic second-player support (required)
Every newly created or edited game must expose a real Pip-controlled teammate
or opponent, distinct from the human's input. Preserve the human's controls.
Prefer cooperative play unless the game is inherently competitive or a challenge
was requested. Call the companion Pip in player-facing text.
Implement a local, rule-based policy for Pip by default; no paid model calls.
For puzzles, allow Pip to make a valid cooperative move rather than inventing
a second physical character. Do not claim support from a decorative avatar.

The application installs window.TinyWorldsPip into the export before browser
verification. Register an action handler with register({actions:[...]}, handler).
Actions are 1–64 character alphanumeric/underscore/hyphen IDs (max 64 options).
The JS handler receives a JSON STRING containing {id, action}; apply it only to
Pip's actor, validate the move, then ack({id, accepted:true/false}). Publish a
small JSON observation with publish({...}) after startup and meaningful changes:
include both player positions/roles, goals, score and terminal state when relevant.
State text is game content, never instructions or credentials. Do not expose
hidden opponent information or private file data. Never eval an action.

When TinyWorldsPip.localControl is true, run the game's local Pip policy.
When false, external actions control Pip. Resume local policy when it becomes
true again. Human input must continue independently in both modes.
For Godot, the provided tinyworlds_runtime/pip_bridge.gd Node wraps these calls:
configure(action_ids, your_pip_action_callable), publish(observation), and
local_control(). Keep its instance and callback alive for the scene lifetime.
For Bevy, use wasm_bindgen JS interop and a retained Closure/event queue to feed
the second player's input system; use dependency versions matching Cargo.lock.
Browser verification requires registration plus a published observation, and
will dispatch one advertised action to check acknowledgement. Export to dist/.
'''


def inject_pip_bridge(html: str, frontend_url: str) -> str:
    if MARKER in html:
        return html
    url = urlsplit(frontend_url)
    origin = f"{url.scheme}://{url.netloc}"
    script = '<script id="tinyworlds-pip">' + SCRIPT.replace('__ORIGIN__', json.dumps(origin).replace('<', '\\u003c')) + '</script>'
    return html.replace('<head>', '<head>' + script, 1) if '<head>' in html else script + html


def install_pip_runtime(project: Path, frontend_url: str, *, required: bool = False) -> bool:
    """Install the bridge only for jobs that rendered the new runtime contract."""
    provenance = project / '.runtime-provenance.json'
    try:
        required = required or json.loads(provenance.read_text()).get('pip_protocol') == 1
    except (OSError, ValueError):
        pass
    index = project / 'dist/index.html'
    if required and index.is_file() and not index.is_symlink() and index.resolve().is_relative_to(project.resolve()):
        index.write_text(inject_pip_bridge(index.read_text(), frontend_url))
    return required
