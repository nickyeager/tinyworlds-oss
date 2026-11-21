# TinyWorlds tests

See the [testing quickstart](../docs/guides/testing-quickstart.md) for the current
CI test selections and the [end-to-end guide](../docs/guides/e2e-testing.md) for
editor browser checks and live generation acceptance.

| Location | Purpose |
| --- | --- |
| `tests/unit/` | Local service, budget, execution, logging, and verification contracts |
| `tests/api/` | In-process FastAPI route, authentication, ownership, and asset contracts |
| `tests/e2e/` | Mixed: two in-process CI suites plus explicitly marked live workflows |
| `tests/integration/` | Explicitly selected external-service tests |
| `tests/fixtures/` | Test inputs and small engine projects |
| `web/src/**/__tests__/` | Frontend Vitest checks |
| `web/tests/e2e/` | Playwright browser workflows |

Run from the repository root:

```bash
.venv/bin/python -m pytest tests/unit/ tests/api/ -x -q
```

The default marker filter excludes `integration` and `e2e`. Directory names do
not override that filter. Select live tests deliberately with `-m integration`
or `-m e2e`, after checking their prerequisites and potential provider costs.

Keep fixtures disposable and isolated from user games and production databases.
Exercise real route/filesystem/authentication behavior where practical; stub
paid or external services at the boundary. Prefer assertions about observable
results and failures over tests that mirror implementation details.
