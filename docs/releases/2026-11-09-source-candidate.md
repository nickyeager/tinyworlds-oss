# Source review candidate, November 9

This is a local review package, **not a published or fully accepted release**.
The supported acceptance target is [local Codex + Godot](v0.1-developer-preview.md).
The source snapshot has a per-file SHA-256 manifest and no inherited Git history.
Private operator logs, authentication sessions, generated games and screenshots
remain outside the distribution.

## Changes prepared

- Clarified the small create/play/edit scope, setup and experimental paths.
- Kept Apache-2.0 original code, CC BY 4.0 original prose and upstream notices.
- Recorded a fresh Python resolution and separated the optional OTLP exporter.
- Removed the implicit personal admin address from application defaults.
- Corrected the Godot modifier's obsolete C#/Mono and excluded-skill references
  to use the GDScript guide actually supplied to the worker. Its previous text
  and exact hashes are retained privately. This is a compatibility correction,
  not a measured claim that this skill outperforms a no-skill baseline.
- Refreshed the dependency inventory and public documentation links.

## Verification performed

| Check | Result and scope |
| --- | --- |
| Fresh Python installation | Passed dependency resolution and `pip check`, with optional OTLP exporter installed separately |
| Fresh frontend installation | Frozen pnpm lockfile installed successfully |
| Frontend tests | 54 passed; TypeScript check and production build passed |
| Backend release suite | Incomplete: 591 passed, 2 skipped, 1 failed; stopped at the first failure |
| Real Codex/Godot create | Passed from an empty database with zero paid-asset budget; 173.1 seconds |
| Real edit | Passed; requested project-name change confirmed in source, Web export rebuilt; 72.7 seconds |
| Trusted export verification | Passed after create/edit; keyboard, pointer and touch exercised, no reported verifier errors |
| Editor visual check | Actual generated game rendered; before/after screenshots show the square moving right after keyboard input |
| Optional Phoenix tracing | Real Codex tool activity, failure/recovery and token reporting persisted as 8 spans; content excluded; fresh exporter run passed in 19.35 seconds |
| Source package checks | Manifest hashes and links in 21 public documents passed; secret scanner finding was a recorded upstream SHA-256 checksum, with no unreviewed findings |
| Full editor browser acceptance | Pending on this candidate; prior dated results are not counted as current passes |

Frontend checks ran on the initial fresh staging copy. Subsequent staging
changes did not alter frontend implementation. Backend and real generation
checks ran on the later staging copy with the corrected modifier. The final
review package includes subsequent documentation/example changes; its manifest
defines the exact distribution. Private evidence records those comparisons.

## Failures and limits retained

The first backend attempt stopped after 89 passes because the fresh Playwright
version required its matching Chromium download. After installing that browser,
the suite reached 591 passes and stopped at `test_admin_lists_users`, with
`assert 403 == 200`. That fixture still assumes a personal email is an admin by
default. The release intentionally has no default admin. The proposed fix is
to explicitly configure a test-only admin within the fixture; that correction
and another suite run remain pending under the repository's retry rule.

An additional local browser script first attempted to interact before activating
the editor's Play control. After correcting that harness step, it captured the
rendered game and keyboard movement, then failed at the gallery assertion
`img.complete && img.naturalWidth > 0`. It checks immediately after visibility;
waiting for image loading is the next diagnostic correction. This is not a
gallery pass and does not by itself prove an application defect. Further retries
and the complete editor suite are pending confirmation under the same rule.

Visual inspection also found missing arrow glyphs on this generated game's
direction buttons. The verifier's input exercise did not catch that usability
problem. This test game is not an approved marketing demo. No human fun rating,
real-phone check, fresh-machine external tester result, current Claude/Bevy
acceptance, or public-hosting acceptance is claimed.

The [fresh dependency inventory](../../LICENSES/dependency-inventory-20261109.json)
has 770 entries and 13 remaining version-matched notice-collection gaps. Missing
collected text is distinct from unknown declared licensing. Original recovered
notice evidence is retained; binaries and containers need a separate review.

Before publication: finish the failed/pending checks, review distribution notices,
resolve suspected historical credential disposition with owners, verify the
public repository's reporting channel/CI/protections, and review a real demo.
The source snapshot omits old history; this does not establish credential revocation.
