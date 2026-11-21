#!/usr/bin/env bash
# Run the canonical generation eval set against prod (default) or local.
#
# Per prompt, posts the description to /api/v1/{godot|bevy}/games as the
# canary user, follows the SSE stream until a terminal event, then checks
# for each expected path under the generated game tree. One pass/fail row
# per prompt lands in data/eval_runs.jsonl with the run timestamp.
#
# Usage:
#   scripts/run_evals.sh                                # runs against prod
#   BASE_URL=http://localhost:8001 scripts/run_evals.sh # runs locally
#
# Required env:
#   TINYWORLDS_TOKEN — JWT for the canary user (see /test-game-e2e for mint
#                      pattern). Token must have ~30min of life left per
#                      prompt to cover the SSE stream.
#
# Optional env:
#   BASE_URL  — backend root (default https://tinyworlds.us)
#   PROMPTS   — path to canonical_prompts.json (default evals/canonical_prompts.json)
#   OUTPUT    — append target (default data/eval_runs.jsonl)
#   MAX_WAIT  — per-prompt SSE timeout in seconds (default 900)

set -euo pipefail

BASE_URL="${BASE_URL:-https://tinyworlds.us}"
PROMPTS="${PROMPTS:-evals/canonical_prompts.json}"
OUTPUT="${OUTPUT:-data/eval_runs.jsonl}"
MAX_WAIT="${MAX_WAIT:-900}"

if [ -z "${TINYWORLDS_TOKEN:-}" ]; then
  echo "TINYWORLDS_TOKEN is required" >&2
  exit 2
fi
if [ ! -f "$PROMPTS" ]; then
  echo "prompts file not found: $PROMPTS" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUTPUT")"
RUN_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_ID="eval-$(date -u +%Y%m%d-%H%M%S)"

echo "=== eval run $RUN_ID — base=$BASE_URL prompts=$PROMPTS ==="

prompts_count=$(python3 -c "import json,sys; print(len(json.load(open('$PROMPTS'))['prompts']))")
# Game-creation rate limit on the backend is 2/min; pause between prompts
# so the second-in-flight request doesn't get 429'd by the leaky bucket.
INTER_PROMPT_SLEEP="${INTER_PROMPT_SLEEP:-35}"
for i in $(seq 0 $((prompts_count - 1))); do
  if [ "$i" -gt 0 ]; then
    echo "(sleeping ${INTER_PROMPT_SLEEP}s to respect game-creation rate limit)"
    sleep "$INTER_PROMPT_SLEEP"
  fi
  # Fields are TAB-separated so the description can contain spaces.
  # EXPECTS becomes a comma-joined string the shell can split later.
  FIELDS=$(python3 -c "
import json,sys
p = json.load(open('$PROMPTS'))['prompts'][$i]
print('\\t'.join([p['slug'], p['engine'], p['description'], ','.join(p['expects'])]))
")
  SLUG=$(printf '%s' "$FIELDS" | cut -f1)
  ENGINE=$(printf '%s' "$FIELDS" | cut -f2)
  DESC=$(printf '%s' "$FIELDS" | cut -f3)
  EXPECTS_CSV=$(printf '%s' "$FIELDS" | cut -f4)

  echo
  echo "--- [$((i+1))/$prompts_count] $SLUG ($ENGINE) ---"
  # Persistent per-prompt scratch — kept after the run so failures can
  # be inspected. EVAL_KEEP_TMP=0 to opt back into auto-cleanup.
  TMP="${EVAL_TMP_ROOT:-/tmp/tinyworlds-evals}/$RUN_ID/$SLUG"
  mkdir -p "$TMP"
  SSE="$TMP/sse.log"

  # Fire the build. SSE streams until done/failed; cap at MAX_WAIT.
  # Build the JSON body via python to avoid shell-quoting hell for
  # descriptions with quotes / backslashes / unicode.
  # Use curl --max-time instead of GNU `timeout` so the script runs on
  # macOS without coreutils.
  BODY=$(python3 -c "import json,sys; print(json.dumps({'description': sys.argv[1]}))" "$DESC")
  # Retry once on transient errors (429, 502) — the rate-limit window may
  # have closed between bursts even with the inter-prompt sleep.
  for attempt in 1 2; do
    curl -sN --max-time "$MAX_WAIT" -X POST "$BASE_URL/api/v1/$ENGINE/games" \
      -H "Authorization: Bearer $TINYWORLDS_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$BODY" \
      > "$SSE" 2>&1 || true
    # If the response is a single-line error JSON (no init event), retry.
    if grep -q '"event_type": "init"' "$SSE"; then
      break
    fi
    if [ "$attempt" = 1 ]; then
      echo "(attempt 1 produced no init event; retrying after 35s)"
      sleep 35
    fi
  done

  # Parse SSE JSON with Python. BSD sed does not understand \s, which
  # previously caused valid init events to be recorded as no_game_id.
  PARSED=$(python3 - "$SSE" <<'PY'
import json
import sys
from pathlib import Path

game_id = ""
done = "0"
failed = "0"
session_limited = "0"
for line in Path(sys.argv[1]).read_text(errors="replace").splitlines():
    if not line.startswith("data: "):
        continue
    try:
        event = json.loads(line[6:])
    except json.JSONDecodeError:
        continue
    if not game_id and event.get("game_id"):
        game_id = str(event["game_id"])
    if event.get("event_type") == "done":
        done = "1"
    if event.get("event_type") == "failed":
        failed = "1"
    content = str(event.get("content") or "")
    if "session limit" in content.lower() or "out of extra usage" in content.lower():
        session_limited = "1"
print("|".join([game_id, done, failed, session_limited]))
PY
)
  IFS='|' read -r GAME_ID DONE FAILED SESSION_LIMITED <<< "$PARSED"

  status="unknown"
  missing=""
  if [ -n "$GAME_ID" ]; then
    # Walk expected paths inside the prod backend container OR local fs.
    if [[ "$BASE_URL" == *"localhost"* ]]; then
      GAME_ROOT="generated_games/$GAME_ID"
      lister() { [ -e "$GAME_ROOT/$1" ] && echo OK || echo MISSING; }
    else
      lister() { ssh tinyworlds "docker exec tinyworlds-backend-1 bash -c '[ -e /app/generated_games/$GAME_ID/$1 ] && echo OK || echo MISSING'" 2>/dev/null; }
    fi
    miss=()
    IFS=',' read -ra paths <<< "$EXPECTS_CSV"
    for p in "${paths[@]}"; do
      [ "$(lister "$p")" = "OK" ] || miss+=("$p")
    done
    if [ "$FAILED" = "1" ] && [ "$SESSION_LIMITED" = "1" ]; then
      status="agent_session_limited"
    elif [ "$FAILED" = "1" ]; then
      status="fail_event"
    elif [ ${#miss[@]} -ne 0 ]; then
      status="missing_artifacts"
      missing=$(printf "%s," "${miss[@]}"); missing=${missing%,}
    elif [ "$DONE" = "1" ]; then
      status="pass"
    else
      status="timeout"
    fi
  else
    if [ "$SESSION_LIMITED" = "1" ]; then
      status="agent_session_limited"
    else
      status="no_game_id"
    fi
  fi

  printf '%s\n' "$status: $GAME_ID  (missing: ${missing:-none})"

  python3 -c "
import json, time
rec = {
  'run_id': '$RUN_ID',
  'run_ts': '$RUN_TS',
  'slug': '$SLUG',
  'engine': '$ENGINE',
  'game_id': '$GAME_ID' or None,
  'status': '$status',
  'missing': '$missing'.split(',') if '$missing' else [],
  'base_url': '$BASE_URL',
}
with open('$OUTPUT', 'a') as f:
  f.write(json.dumps(rec) + '\\n')
"
  if [ "${EVAL_KEEP_TMP:-1}" = "0" ]; then rm -rf "$TMP"; fi
done

echo
echo "=== eval run $RUN_ID complete — results in $OUTPUT ==="
python3 -c "
import json
rows = [json.loads(l) for l in open('$OUTPUT') if l.strip()]
this_run = [r for r in rows if r['run_id'] == '$RUN_ID']
passes = sum(1 for r in this_run if r['status'] == 'pass')
print(f'pass rate this run: {passes}/{len(this_run)}')
"
