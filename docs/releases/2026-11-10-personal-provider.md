# Personal provider setup — November 10

The open-source personal install now starts with **Connect your AI** rather than
silently using the backend operator's provider login. This is a local feature,
not a shared-server credential system. See [setup](../guides/setup.md) and
[provider connections](../guides/provider-connections.md).

## Implemented

- First-visit setup when `PERSONAL_MODE=true` and no connection is saved.
- Codex's official ChatGPT browser sign-in, start/cancel/finish and expiration.
- Explicit use of an existing local Codex or Claude Code login.
- OpenAI/Anthropic API-key entry and optional model selection.
- A real connection check that consumes one small provider request.
- Persistent local selection, private credential files and disconnection.
- Provider/model selection applied to creation, editing and utility executors;
  no implicit fallback to environment credentials in personal mode.
- Loopback/Origin/Host restrictions, generated-game-directory exclusion and
  exclusion of credential-entry requests from Sentry capture.

Claude subscription sign-in stays in the official CLI. The personal path uses
that CLI's native auth store without copying subscription tokens. API-key mode
does not copy subscription credentials. Shared/production instances cannot use
these setup endpoints and retain their existing operator configuration.

## Checked

| Check | Result |
| --- | --- |
| Focused backend suite | 33 passed: connection boundaries, filesystem permissions, selection, missing credentials, disconnection, reporting filter and existing executor contracts |
| Frontend unit suite | 54 passed |
| TypeScript and production build | Passed |
| Real browser onboarding | Passed against isolated local services; desktop and 390px layout visually reviewed |
| Existing Codex login | Selected through the UI, real model response returned, selection/model survived refresh |
| Official ChatGPT sign-in | Real app-server start and cancel passed; pending login cleanup preserved the existing connection |
| Local request restrictions | Missing setup header, untrusted Origin and untrusted Host rejected |
| Real personal Codex/Godot creation | Passed in 139.9 seconds, zero paid-asset budget |
| Real edit | Passed in 48.1 seconds; requested project-name change confirmed in source |
| Updated Web export | Trusted browser verification passed with keyboard, pointer and touch exercised |

The exercised provider was Codex CLI 0.167.0 with `gpt-6.1-sol`; Godot was
4.6 stable. Tests used a private, disposable application database and separate
credential/game directories. The frontend and backend snapshots are recorded in
private proof receipts; final source comparison covers the application files.
No new package dependency was introduced. Provider CLI binaries are not bundled.

## Not established by these checks

Completing a fresh ChatGPT sign-in requires its account owner. That completion,
valid-key API billing, live Claude generation, subscription expiry/refresh over
time, a real phone, and hosted per-user credentials were not verified. A stored
key or CLI status alone is not proof of available credit or model access. Shared
hosting needs a separate, provider-approved account integration and per-user
credential isolation; it must not expose this personal setup API.

The production-build check cleared compiled files belonging to an older local
preview. That frontend was restarted and checked again with its existing backend
and provider preserved. It did not affect the isolated personal setup test.

This work does not clear the broader release gates in the
[November 9 report](2026-11-09-source-candidate.md): the paused admin-fixture/full
backend check, prior gallery acceptance, notice gaps, historical credential
disposition and public repository configuration remain separate. No release has
been published and no provider login or credential is included in the source.
