# Source review candidate, November 13

Still a local review package. Nothing is published. The supported target is
[local Codex + Godot](v0.1-developer-preview.md).

## What changed since November 9

- The app's wording was rewritten in plain words and the create page was cut
  down. Unused screens, components and seven outdated browser specs were removed.
- The admin test now sets up its own test-only admin. There is still no default
  admin.
- Build previews for Bevy games used a Godot URL. Fixed, with a unit test.
- Two more dependency licence texts were collected (`keyv`, `@types/json5`).
- November 14: Image Blast was removed, along with the voxel tools and the
  vendored voxel importer that only it used. The checks below were run again
  after that.

## Checks run

| Check | Result |
| --- | --- |
| Backend unit and API tests | 358 passed |
| Backend end-to-end set (admin, auth) | 17 passed |
| Frontend unit tests, type-check, lint | 51 passed; type-check clean; 0 lint errors |
| Editor browser suite without real generation | 21 of 21 passed |
| Home and auth browser specs | 22 of 22 passed on the second run; three auth tests returned early when the sign-up rate limit was hit. The first run had one failure, a sign-up test that did not wait for the rate-limit message; the test was fixed |
| Snapshot manifest and links | Passed: 539 files, 24 public documents |
| Frozen frontend install and production build, inside the snapshot | Passed |
| Secret scan of the snapshot | One finding: the known upstream SHA-256 checksum in `vendor/godogen-runtime/SHA256SUMS.json` |

Tests ran on the working tree on macOS arm64. The install and build ran inside
the snapshot. The snapshot must be rebuilt and rechecked after any further
change, including this report.

## Not run this time

- A real Codex/Godot create and edit. The last pass was November 9, before the
  wording changes. The two `@generation` browser tests cover this and need a
  signed-in provider.
- Agent-play, provider-connection and mobile-touch specs.
- Anything on a real phone, a second machine, Linux, Claude or Bevy.

## Dependency notices

The [November 13 inventory](../../LICENSES/dependency-inventory-20261113.json)
has the same 770 entries. Eleven packages still have no complete licence text
collected. Each one declares its licence (ten MIT, one CC0-1.0) in its npm
metadata, but its authors did not publish a licence file for that version, in
the package or in the source repository. These are collection gaps. They are
not findings that the packages are unlicensed. The inventory records the reason
for each one.

## Still needed before publishing

These need the owner:

1. Decide whether the eleven notice gaps are acceptable for a source-only release.
2. Confirm that credentials found in old Git history have been revoked. The
   snapshot has no old history, but that does not revoke anything.
3. Create the public repository, turn on private vulnerability reporting, and
   check CI and branch protection there.
4. Run one real create and edit on the final snapshot and pick a demo game.
