# v0.1 publication verification, November 20

Repository: [nickyeager/tinyworlds-oss](https://github.com/nickyeager/tinyworlds-oss).
This is a source-only developer preview for local Codex + Godot on macOS arm64.
Original code is Apache-2.0; original documentation is CC BY 4.0.
Upstream material retains its own notices and extensive
[attribution](../../ATTRIBUTION.md).

## Verification

- Backend unit/API and admin/auth flow checks: **410 passed**, exit 0.
- Frontend: frozen dependency install, **51 tests passed**, TypeScript check and
  production build all exited 0 in an isolated source snapshot.
- Initial snapshot: **544 manifest files**, 24 public Markdown documents checked;
  hashes, distribution exclusions and relative links passed.
- Source scan: one finding, an upstream SHA-256 checksum in
  `vendor/godogen-runtime/SHA256SUMS.json`. Its value was verified against the
  SHA-256 of `asset-gen/api.md`; no credential was identified in that finding.
- Fresh real Codex/Godot run from an empty database: create **179 seconds**,
  edit **68 seconds**, both completed. Trusted browser checks exercised keyboard,
  pointer and touch input without reported errors. Screenshots were inspected:
  the game rendered and the requested blue-to-magenta player edit appeared.
  This is one successful example, not a game-quality benchmark.
- Initial GitHub CI exposed an API test isolation problem: `/health` accessed
  the default disk database when the API suite ran alone without `data/`.
  The API fixtures now select a real disposable in-memory database before app
  imports. The endpoint and its assertions remain unchanged.
  Isolated API rerun with the same signing-key environment as CI: **127 passed**,
  exit 0. A prior local invocation omitted that required environment variable
  and failed during settings import, before any tests ran.
- Public snapshot after documentation updates: **545 manifest files**, 25 public
  Markdown documents checked. Its new Git history was scanned separately; the
  only finding was the same verified upstream file checksum.

Tests used the retained constrained Python 3.12 acceptance environment and a
fresh frozen frontend install. The final distribution manifest records source
hashes; documentation and release configuration changes are separate from the
tested application code. Earlier browser and provider evidence is retained in
the dated release reports and does not imply it was all repeated today.

## Distribution and limitations

The public repository starts with new Git history. No private history, provider
credentials, accounts, uploads, generated games, installed dependencies or
deployment automation are included. Source scans do not establish security or
prove revocation of credentials retained in private operational history.

Eleven dependency notice texts remain uncollected; all eleven declared licenses
are known (ten MIT, one CC0-1.0). These are documented collection gaps, not
findings of absent licenses. This source release does not bundle those installed
packages. Container/binary distribution requires separate review.

Claude, Bevy, voice, agent play, other platforms, fresh OAuth completion and
shared public hosting are outside this release's tested support claim. No
marketing demo or generated asset is licensed or distributed with the source.

GitHub CI results are available in the
[Actions dashboard](https://github.com/nickyeager/tinyworlds-oss/actions).
Private vulnerability reporting is enabled. The main branch requires backend,
frontend and worker-image checks and resolved review conversations; force pushes
and branch deletion are disabled. Administrators retain GitHub's bypass ability.
Actions tokens default to read-only and cannot approve pull requests. GitHub
recognizes the source license as Apache-2.0.
Report vulnerabilities through the private channel described in
[SECURITY.md](../../SECURITY.md).
