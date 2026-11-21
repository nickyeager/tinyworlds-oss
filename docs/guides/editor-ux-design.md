# Editor UX review and test process

The editor's job is to turn a player's idea into a reviewed change, while keeping the playable game and their next idea close at hand. This continues the existing TinyWorlds visual identity and the continuous-chat workspace.

## Design direction

Keep Fredoka for the site identity and Nunito for the editing conversation. Use the existing garden-charcoal `#191b17`, preview `#121411`, warm yellow `#FFDB58`, lime `#C7F464`, and secondary text `#B0B2A9`. Reserve yellow for sending and lime for verified readiness. Left-align conversation and instructions; keep the playable world as the visual centerpiece.

Desktop remains conversation beside game; phone remains Change / Play. The change is in the interaction: visible action labels, recoverable draft replacements, concise progress beside the composer, and a reachable way to play a verified change. Do not add decorative dashboards or make engine diagnostics part of writing a request.

```
Conversation                            Playable game
  Your request  [Use again]           [Game view ▾] [Share]
  Response + observable activity         Current playable export

  Current build stage / verified readiness
  Reference or missing-reference guidance
  Draft
  [Attach] [Voice]          [Send change / Stop edit]
  Draft recovery / storage status
```

The first critique removed an extra progress tracker, category tabs and onboarding overlay: they would duplicate the existing conversation and interrupt editing. A short status tied to real events supplies the needed feedback. All available tool actions remain accessible in live activity.

## Research used

- [Nielsen Norman Group: usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/): visible system state, familiar language, control, error prevention and recovery. Application: recover replaced drafts, label actions and preserve requests.
- [W3C: status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html): expose useful feedback without moving focus. Application: polite, concise composer feedback; no repeated timer announcements.
- [W3C: target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html): make controls reachable. Application: labeled primary actions and generous touch controls, including reduced phone viewports.

These are design inputs, not evidence that users have tested this implementation. Automated task checks establish behavior; a human playtest is still needed to assess perceived ease.

## Acceptance tasks

| Task | Required behavior |
| --- | --- |
| Choose an idea after writing | New draft can be undone to recover the previous text and reference. No automatic build. |
| Rework an earlier request | Use again fills the composer; sending remains explicit. Replaced draft can be recovered. |
| Refresh with an image draft | Text survives. The unavailable reference is named; sending waits for reattachment or explicit removal. |
| Lose network before sending | Draft remains editable; Send is unavailable with an actionable explanation. Recovery preserves the text. |
| Wait for a build | Composer shows the latest observed stage, with real elapsed time and an explicit stop action. |
| Finish an edit | A verified-ready action is available near the composer, including when earlier conversation is being read. |
| Use a phone | Touch controls, draft recovery, image guidance and Send fit the actual chat-panel height. Preview switching preserves the game. |

## Testing cadence

1. Turn each behavior into a real browser task before or alongside implementation; use no API interception or simulated backend successes.
2. Fast checks: frontend unit tests, TypeScript, changed editor lint, and browser tasks that do not launch generation.
3. Full checks: real authenticated edit, export, trusted verification, refresh/reconnection and cancellation. These run explicitly at acceptance, not on every keystroke.
4. Inspect desktop, phone and short-viewport screenshots. Record fresh-owner and existing-history walkthroughs and include test outcomes and limits in a proof package.
5. A local background watcher reruns fast checks after changes, serializes runs, retains recent logs/reports, and exposes status and stop commands. It reports unavailable services instead of claiming a pass.

Background runs do not establish results for changed source served by a stale production build. Use the development frontend while watching; the full acceptance pass also checks the production build.

## Core UI follow-up — 2 November 2026

The game view selector now holds Play, Pictures, Video (when present), How it was made and Past changes, with owner-only views still restricted. Switching views must keep the playable iframe mounted. Create-page examples and the asset budget are collapsed by default; a nonzero budget remains visible in its summary. See the retained internal simplification review for scope and evaluation candidates.
