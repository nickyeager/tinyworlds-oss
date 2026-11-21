"""Report real Godot web startup to the embedding editor, preserving export hooks."""

_MARKER = 'id="tinyworlds-preview-lifecycle"'
_SHIM = r'''<script id="tinyworlds-preview-lifecycle">
(function () {
  var settled = false;
  var latest = {type: 'tinyworlds:preview-status', state: 'loading', progress: null};
  function report(state, progress) {
    latest = {type: 'tinyworlds:preview-status', state: state, progress: progress};
    if (window.parent !== window) window.parent.postMessage(latest, '*');
  }
  window.addEventListener('message', function (event) {
    if (event.source === window.parent && event.data && event.data.action === 'tinyworlds:preview-status-request') {
      if (window.parent !== window) window.parent.postMessage(latest, '*');
    }
  });
  function failed() { if (!settled) { settled = true; report('error', null); } }
  window.addEventListener('error', failed);
  window.addEventListener('unhandledrejection', failed);
  window.__tinyworldsStartGame = function (engine, options) {
    var original = options && options.onProgress;
    var config = Object.assign({}, options, {onProgress: function (loaded, total) {
      report('loading', total > 0 ? Math.min(100, Math.round(loaded / total * 100)) : null);
      if (original) original(loaded, total);
    }});
    var started;
    try { started = engine.startGame(config); }
    catch (error) { failed(); throw error; }
    return Promise.resolve(started).then(function (result) {
      settled = true;
      report('ready', 100);
      return result;
    }, function (error) { failed(); throw error; });
  };
})();
</script>'''


def inject_preview_lifecycle(html: str) -> str:
    """Wrap the standard export's startup promise; unknown shells keep loading.

    Call after telemetry config rewriting and before adding other scripts that
    mention the startup call. Do not infer readiness from iframe HTML load.
    """
    if _MARKER in html:
        return html
    html = html.replace('engine.startGame(', 'window.__tinyworldsStartGame(engine, ', 1)
    if '<head>' in html:
        return html.replace('<head>', '<head>' + _SHIM, 1)
    return _SHIM + html
