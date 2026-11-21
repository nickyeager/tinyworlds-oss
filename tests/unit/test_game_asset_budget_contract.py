"""Asset-spend authorization contracts; no asset provider calls are made."""
from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest


def _api():
    module = importlib.import_module("src.api.services.game_asset_budget")
    return module.AssetBudgetLedger, module.AssetBudgetExceeded, module.InvalidAssetJob


@pytest.mark.parametrize("invalid", [-1, True, False, 1.5, "5", None])
@pytest.mark.parametrize("operation", ["create_job", "reserve"])
def test_limits_and_costs_require_nonnegative_integers(tmp_path, invalid, operation):
    Ledger, _, _ = _api()
    ledger = Ledger(tmp_path / "outside-agent-workspace")
    if operation == "create_job":
        with pytest.raises((TypeError, ValueError)):
            ledger.create_job("game-input-validation", invalid)
    else:
        token = ledger.create_job("game-input-validation", 12)
        with pytest.raises((TypeError, ValueError)):
            ledger.reserve(token, invalid)
        assert ledger.reserve(token, 0) == 12, "invalid input must not alter authorized spend"


@pytest.mark.parametrize("limit,first,second", [(0, 0, 0), (1, 0, 1), (100, 40, 60)])
def test_zero_is_a_hard_limit_and_exact_budget_exhaustion_is_allowed(
    tmp_path, limit, first, second,
):
    Ledger, Exceeded, _ = _api()
    ledger = Ledger(tmp_path / "outside-agent-workspace")
    token = ledger.create_job("game-budget-boundary", limit)
    assert ledger.reserve(token, first) == limit - first
    assert ledger.reserve(token, second) == 0
    with pytest.raises(Exceeded):
        ledger.reserve(token, 1)
    assert ledger.reserve(token, 0) == 0, "a rejected charge must not corrupt the balance"


def test_tokens_are_distinct_game_authorizations_and_unknown_or_revoked_tokens_fail(tmp_path):
    Ledger, _, Invalid = _api()
    ledger = Ledger(tmp_path / "outside-agent-workspace")
    fox_token = ledger.create_job("game-fox", 9)
    frog_token = ledger.create_job("game-frog", 21)
    assert isinstance(fox_token, str) and isinstance(frog_token, str)
    assert len(fox_token) >= 22 and len(frog_token) >= 22
    assert fox_token != frog_token
    assert "game-fox" not in fox_token and "game-frog" not in frog_token
    assert ledger.reserve(fox_token, 9) == 0
    assert ledger.reserve(frog_token, 1) == 20, "spending in one game must not consume another game's balance"
    for unknown in ("", "unknown-job", fox_token + "tampered"):
        with pytest.raises(Invalid):
            ledger.reserve(unknown, 0)
    ledger.revoke(frog_token)
    for cost in (0, 1):
        with pytest.raises(Invalid):
            ledger.reserve(frog_token, cost)
    assert ledger.reserve(fox_token, 0) == 0, "revocation must be scoped to its token"


def test_reservations_and_revocations_survive_reinstantiation_and_provider_failure(tmp_path):
    Ledger, Exceeded, Invalid = _api()
    root = tmp_path / "outside-agent-workspace"
    ledger = Ledger(root)
    token = ledger.create_job("game-failed-provider", 15)
    revoked = ledger.create_job("game-revoked", 10)

    def failed_provider_request():
        assert ledger.reserve(token, 8) == 7
        raise RuntimeError("provider failed after accepting the request")

    with pytest.raises(RuntimeError, match="provider failed"):
        failed_provider_request()
    ledger.revoke(revoked)
    restored = Ledger(root)
    assert restored.reserve(token, 0) == 7, "unprovable provider failures must retain reserved spend"
    with pytest.raises(Exceeded):
        restored.reserve(token, 8)
    assert restored.reserve(token, 7) == 0
    assert ledger.reserve(token, 0) == 0, "existing instances must observe durable spending"
    with pytest.raises(Invalid):
        restored.reserve(revoked, 0)


def test_concurrent_reservations_across_instances_cannot_overspend(tmp_path):
    Ledger, Exceeded, _ = _api()
    root = tmp_path / "outside-agent-workspace"
    token = Ledger(root).create_job("game-concurrent", 31)
    start = Event()

    def charge(_):
        ledger = Ledger(root)
        start.wait(timeout=5)
        try:
            return ledger.reserve(token, 3)
        except Exceeded:
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        pending = [pool.submit(charge, index) for index in range(64)]
        start.set()
        outcomes = [future.result(timeout=10) for future in pending]
    successful = [remaining for remaining in outcomes if remaining is not None]
    assert len(successful) == 10
    assert sorted(successful) == list(range(1, 29, 3)), "each successful atomic reservation returns its own remaining balance"
    restored = Ledger(root)
    assert restored.reserve(token, 0) == 1
    assert restored.reserve(token, 1) == 0
    with pytest.raises(Exceeded):
        restored.reserve(token, 1)
