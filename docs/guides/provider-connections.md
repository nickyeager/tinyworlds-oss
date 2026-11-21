# Connect your own AI provider

Personal installations use `PERSONAL_MODE=true` and `AGENT_EXECUTION_MODE=local`.
Open `/create`; an installation without a connection takes you to `/connect`.
No provider subscription is included with TinyWorlds.

## Personal setup

1. Install the official Codex or Claude Code CLI on the machine running the backend.
2. Open TinyWorlds using `localhost` on that same computer.
3. Choose your provider and optionally enter a model identifier available to you.
4. Connect using one of the following methods.
5. Use **Check connection** to send one small real model request, then create a game.

| Provider | Connection choices |
| --- | --- |
| Codex | ChatGPT sign-in through the official Codex app-server; your OpenAI API key; or an existing local CLI login |
| Claude Code | Your Anthropic API key; or run `claude auth login` in the official CLI, then connect that existing local login |

The browser opens the provider's sign-in page; TinyWorlds does not ask for your
provider password. Return and select **I've signed in** after completion. Pending
sign-ins expire after ten minutes and can be cancelled. A saved API key or an
existing CLI login is not proof of quota or model access: the explicit check
confirms a real response. It consumes provider allowance or API credit. Separate
image/audio services still require their own credentials and paid-asset budget.

The selected provider and model apply to subsequent creation and editing jobs.
Finish or stop active game jobs before changing/disconnecting the provider.
The existing CLI option leaves that CLI's login untouched. Disconnect removes
TinyWorlds-managed credentials from this installation, but does not revoke the
credential at the provider or sign out your independent CLI.

## Credential storage and local boundary

Managed credentials are saved in `~/.local/share/tinyworlds/providers`, or the
operator's `PERSONAL_PROVIDER_DIR`. The directory has owner-only permissions;
credential and selection files use mode `0600`. Codex owns its isolated auth
store and token refresh. These files are sensitive local files, not an encrypted
vault. Keep them outside source distributions and generated-game directories.
Keys are submitted to the local backend and never saved in browser storage or
returned by the connection API. New connections do not alter the global CLI login.

Setup endpoints require personal mode, local execution, a loopback client/Host,
the explicit setup header, and an allowed loopback browser Origin. Generated
games run on the separate backend origin, which is not an allowed setup origin.
Configure `CORS_ORIGINS` for the actual local frontend port. Bind the backend and
frontend to loopback; do not expose a personal install through a tunnel or proxy.
Run one backend process for this single-user mode; pending login and active-job
coordination are in process. This is not multi-tenant credential isolation.

## Shared-server follow-up

Keep `PERSONAL_MODE=false` on shared or public deployments. They continue to use
operator-configured provider authentication; there is no per-user provider vault
or subscription handoff in this release. That work needs credentials bound to
each authenticated TinyWorlds account, job-scoped access, encrypted storage,
revocation/deletion, independent limits and provider-approved hosted login.

[OpenAI's app-server documentation](https://learn.chatgpt.com/docs/app-server)
describes the local/open-source authentication surface and directs hosted or
commercial integrations to Sign in with ChatGPT. Do not deploy this local flow
as hosted OAuth. [Anthropic's guidance](https://code.claude.com/docs/en/legal-and-compliance)
distinguishes an end user's login through unmodified Claude Code from a third-party
Claude.ai login or collection of subscription tokens. TinyWorlds keeps that
subscription sign-in in the official CLI.

## Verification

`tests/unit/test_personal_provider.py` checks local request boundaries, private
storage, explicit provider selection, missing connections and disconnection.
The browser suite needs an isolated, disposable personal-mode server and a real
local Codex login. It changes that installation's provider selection and sends
one real model request. Run it separately from routine editor tests:

```bash
cd web
PLAYWRIGHT_BASE_URL=http://localhost:3336 \
PROVIDER_TEST_BACKEND=http://localhost:8515 \
PROVIDER_TEST_MODEL=gpt-6.1-sol \
pnpm exec playwright test --config=playwright.provider.config.ts
```

The suite exercises first-visit setup, a real existing-login connection/check,
persistence, desktop/mobile layouts, origin/Host rejection and real Codex OAuth
start/cancel. Completing a fresh provider sign-in requires the account owner.
API billing and Claude generation need separate checks with valid credentials;
they are not established by saving a key or by Codex acceptance.
