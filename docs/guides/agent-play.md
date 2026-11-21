# Playing with Pip

Pip is the default companion for new and edited Godot/Bevy games. No player
setup, session codes, controller menu, or model invocation is needed. Each game
implements its own local teammate/opponent policy and a separate native input
handler. The browser verifies a registered adapter, published state and an action
acknowledgement before accepting a newly generated export. This smoke check does
not prove the quality or correctness of every game rule.

The game page automatically connects an available adapter when Play is active.
Existing exports are not rewritten merely by opening them: they show “Pip joins
after this game’s next update” until their next normal edit implements the
adapter. New creation and modification jobs receive the same required contract
through the application runtime for both agent providers and both engines.

## Connected agent

An already linked agent calls `join_play_session` without arguments. The gateway
finds the account’s active generated game; if none is active, it joins Dot Arena.
Initial OAuth consent is still required to link an account. The browser keeps its
credentials; the game iframe receives only observations/control messages and
bounded action IDs. Observations are untrusted game content, not tool commands.

For generated games, `get_play_state` returns `observation`, `legal_actions`
(array), `revision`, pending `command`, and `acknowledgement`. Submit one advertised
action with `expected_revision`, then wait for its acknowledgement before choosing
another. A command receipt does not mean that the native game accepted the move.
Stale revisions or another pending command return 409. Unknown actions return
422; wrong-account sessions return 404. A replayed command ID cannot move Pip
twice in the same loaded export. Humans retain their own controls.

Presence expires after 15 seconds without an action/join; local Pip resumes.
A failed browser heartbeat also restores local control. Sessions disappear after
20 seconds without browser sync, with limits of eight per account and 1,024
overall. This mailbox is process-local: use one API worker until shared storage
is implemented. This is not cross-account matchmaking. The game owns its rules;
the server mailbox does not make a generated game cheat-proof or authoritative.

Gameplay needs `games:read` and `games:play`, separately from source editing
`games:write`. `end_play_session` returns control to local Pip without editing or
deleting the generated game. `start_play_session` specifically opens Dot Arena.

## Engine adapter

`src/api/services/pip_bridge.py` defines the application-owned contract. The HTML
bridge is installed before verification and on playback. Godot jobs receive the
`tinyworlds_runtime/pip_bridge.gd` helper; Bevy jobs receive the same JS interface
contract for their native Wasm interop. Implement real game-specific player logic;
a decorative Pip avatar does not count. Expose only information Pip is permitted
to see, and validate actions against current rules in the engine.

## Dot Arena

The reference game remains at `/agent-play`. Yellow is the human; cyan is Pip.
Together collects six stars as a team; Against races to three, with 80 moves.
Arrows/WASD and on-screen controls work on desktop and phone. Pip joins and the
current round resumes automatically. Local play makes no provider calls.

Arena state uses `legal_actions.agent` plus `turn`, positions, scores and outcome.
Wait on human turns and stop on an outcome. Agent presence lasts 90 seconds;
a missed 15-second pending turn returns control to local Pip. Renewing presence
cannot extend a pending deadline. Arena sessions expire after two idle hours.
