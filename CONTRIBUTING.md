# Contributing to TinyWorlds

Start with the [README](README.md), the [setup guide](docs/guides/setup.md) and
the [roadmap](docs/ROADMAP.md). How generation works is in the
[generation guide](docs/guides/generation.md). Release work still open is in
[open-source readiness](docs/open-source-readiness.md).

## Making a change

- Say what the problem is and what should happen instead.
- Keep the patch to one thing. Leave out unrelated formatting, dependency
  upgrades and generated files.
- Never commit real secrets, user games, uploaded media or private logs.
  `.env.example` holds variable names and placeholders only.
- Run the checks that cover your change, and say exactly what you ran and what
  you did not. For a UI change, try it in a browser. For game generation, check
  for engine errors and play the exported game; a canvas that shows up does not
  prove the game works.

```bash
source .venv/bin/activate
python -m pytest tests/unit/ -q
cd web
pnpm test:run
```

Tests that use providers, Docker, engines or paid assets need the setup in the
guides and a spending limit. Do not point a local test at production.

## Skills and upstream code

- Pin upstream sources to a revision. Keep their licence and copyright files
  and add a link in [ATTRIBUTION.md](ATTRIBUTION.md).
- Record changed paths in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Do
  not relabel third-party Markdown as TinyWorlds documentation.
- Do not edit the vendored Godogen files. Put TinyWorlds behaviour in the
  renderer or the app, and update the hash manifest when you sync upstream.
- To claim a skill helps, compare it with a no-skill run on the same task,
  model, tools and budget, and keep the results. A skill that has not been
  measured is unproven, not harmful, so do not remove it for that reason.
  Keep experiment receipts outside distributable runtime files; the historical
  private evaluation corpus is not included in this source release.

## Pull requests

Say what changes for the user, why, what you tested and what is still limited.
Mention new runtime requirements and anything that costs money. Include
licence and attribution details for borrowed material. Keep credentials and
private data out of the PR.

By contributing original material you submit it under the licence in
[LICENSING.md](LICENSING.md). Only contribute work you have the right to share.
