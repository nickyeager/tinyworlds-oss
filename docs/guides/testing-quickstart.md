# Testing quickstart

Run commands from the repository root unless noted. Install backend and frontend
dependencies using the [setup guide](setup.md) first.

## Local checks

```bash
.venv/bin/python -m pytest tests/unit/ tests/api/ -x -q
.venv/bin/python -m pytest tests/e2e/test_admin_e2e.py tests/e2e/test_auth_flows.py -x -q
cd web
pnpm test:run
pnpm exec tsc --noEmit
pnpm build
```

The backend and frontend test selections match [CI](../../.github/workflows/ci.yml).
The two explicitly selected `tests/e2e/` files are in-process tests; their
directory name does not mean they launch a live generator. Backend fixtures use
temporary files and test databases, with paid providers stubbed at their
boundaries. Some verification tests launch a local browser or check
operating-system sandbox support.

`pytest.ini` excludes tests marked `integration` or `e2e` by default. Running
`pytest tests/` therefore does not run every live workflow. Coverage reports are
enabled by default; add `--no-cov` when only checking test outcomes.

## Browser and real generation checks

See the [end-to-end guide](e2e-testing.md) for editor browser checks, isolated
fixtures, and explicit live generation checks. Live provider tests require
credentials and may spend inference or asset credits.

The old template-generation API and `scripts/run_e2e_tests.sh` are retired.
Use the current commands above rather than historical template test examples.
