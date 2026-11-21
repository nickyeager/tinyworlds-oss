"""Durable, atomic prepaid reservations for game asset generation.

This ledger belongs to the trusted launcher, outside agent-writable projects.
A reservation is never refunded: a failed remote request may still be billed.
"""
from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from contextlib import contextmanager


class AssetBudgetExceeded(ValueError):
    """The game does not have enough unreserved budget."""


class InvalidAssetJob(ValueError):
    """The job capability is unknown, revoked, or malformed."""


def _cents(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


class AssetBudgetLedger:
    def __init__(self, root: Path):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / "asset-budget.sqlite3"
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS games (
                    game_id TEXT PRIMARY KEY,
                    limit_cents INTEGER NOT NULL CHECK(limit_cents >= 0),
                    spent_cents INTEGER NOT NULL DEFAULT 0 CHECK(spent_cents >= 0)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    token TEXT PRIMARY KEY,
                    game_id TEXT NOT NULL REFERENCES games(game_id),
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS asset_requests (
                    game_id TEXT NOT NULL REFERENCES games(game_id),
                    request_key TEXT NOT NULL,
                    record TEXT NOT NULL,
                    PRIMARY KEY (game_id, request_key)
                );
            """)
        finally:
            conn.close()
        self.path.chmod(0o600)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _lookup(conn, token):
        if not isinstance(token, str) or not token:
            raise InvalidAssetJob("invalid asset job")
        row = conn.execute("""
            SELECT jobs.game_id, games.limit_cents, games.spent_cents
            FROM jobs JOIN games USING (game_id)
            WHERE token = ? AND revoked = 0
        """, (token,)).fetchone()
        if row is None:
            raise InvalidAssetJob("invalid or revoked asset job")
        return row

    def create_job(self, game_id: str, limit_cents: int) -> str:
        limit_cents = _cents(limit_cents, "limit_cents")
        if not isinstance(game_id, str) or not game_id:
            raise ValueError("game_id must be a nonempty string")
        token = secrets.token_urlsafe(32)
        with self._transaction() as conn:
            # Repeated turns cannot reset spend or raise an existing game cap.
            conn.execute("""
                INSERT INTO games (game_id, limit_cents) VALUES (?, ?)
                ON CONFLICT(game_id) DO UPDATE
                SET limit_cents = MIN(games.limit_cents, excluded.limit_cents)
            """, (game_id, limit_cents))
            conn.execute("INSERT INTO jobs (token, game_id) VALUES (?, ?)", (token, game_id))
        return token

    def job(self, token: str) -> dict:
        with self._transaction() as conn:
            row = self._lookup(conn, token)
            return {**dict(row), "remaining_cents": max(0, row["limit_cents"] - row["spent_cents"])}

    def reserve(self, token: str, cost_cents: int) -> int:
        cost_cents = _cents(cost_cents, "cost_cents")
        with self._transaction() as conn:
            row = self._lookup(conn, token)
            remaining = row["limit_cents"] - row["spent_cents"]
            if cost_cents > remaining:
                raise AssetBudgetExceeded("asset budget exhausted")
            conn.execute("UPDATE games SET spent_cents = spent_cents + ? WHERE game_id = ?",
                         (cost_cents, row["game_id"]))
            return remaining - cost_cents

    def revoke(self, token: str) -> None:
        with self._transaction() as conn:
            self._lookup(conn, token)
            conn.execute("UPDATE jobs SET revoked = 1 WHERE token = ?", (token,))

    def claim_asset(self, token: str, request_key: str, cost_cents: int) -> tuple[bool, dict]:
        """Reserve once per game/content key, including across retries and processes."""
        import json
        cost_cents = _cents(cost_cents, "cost_cents")
        with self._transaction() as conn:
            job = self._lookup(conn, token)
            previous = conn.execute(
                "SELECT record FROM asset_requests WHERE game_id=? AND request_key=?",
                (job["game_id"], request_key),
            ).fetchone()
            if previous:
                return False, json.loads(previous["record"])
            if cost_cents > job["limit_cents"] - job["spent_cents"]:
                raise AssetBudgetExceeded("asset budget exhausted")
            conn.execute("UPDATE games SET spent_cents=spent_cents+? WHERE game_id=?", (cost_cents, job["game_id"]))
            record = {"status": "submission_started", "cost_cents": cost_cents}
            conn.execute("INSERT INTO asset_requests VALUES (?, ?, ?)", (job["game_id"], request_key, json.dumps(record)))
            return True, record

    def record_asset(self, token: str, request_key: str, record: dict) -> None:
        import json
        with self._transaction() as conn:
            job = self._lookup(conn, token)
            changed = conn.execute(
                "UPDATE asset_requests SET record=? WHERE game_id=? AND request_key=?",
                (json.dumps(record), job["game_id"], request_key),
            ).rowcount
            if changed != 1:
                raise InvalidAssetJob("asset request not claimed")
