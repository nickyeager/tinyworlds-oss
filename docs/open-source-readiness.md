# Open-source release status

The **v0.1 developer preview** targets local Codex + Godot.
Source: [nickyeager/tinyworlds-oss](https://github.com/nickyeager/tinyworlds-oss).
See the [release page](releases/v0.1-developer-preview.md) for scope and checks.

## Included

- First-run setup with your own provider login or API key
  ([details and limits](releases/2026-11-10-personal-provider.md)).
- Apache-2.0 for original code, CC BY 4.0 for original documentation, with
  [attribution](../ATTRIBUTION.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).
- Application source, tests, pinned runtime guidance and dependency notices.
- A fresh Git history. Private history, accounts, provider credentials, generated
  games, uploads and deployment automation are excluded.

## Remaining work

- Eleven dependency notice texts remain uncollected; all eleven declared
  licenses are known. This release contains source, not installed dependencies.
  Containers and binaries require their own distribution review.
- Claude, Bevy, voice and agent play remain experimental. Shared public hosting
  is outside the supported local preview.
- Additional platforms, fresh provider OAuth completion and the full provider
  matrix need acceptance testing.
- Historical credential revocation is a separate private operational task;
  publishing a new history does not revoke credentials or audit a live service.

Optional development skills with unresolved provenance are excluded from the
release, with credit preserved. This is a distribution boundary, not a verdict
on skill effectiveness. A clean secret scan is not a security audit.
