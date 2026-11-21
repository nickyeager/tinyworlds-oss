"""Small authoritative two-player arena for human/agent play experiments.

Sessions are private to an account, bounded, and process-local. This is a
turn-based reference game, not an adapter for arbitrary generated games.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import secrets
import threading
import time
import uuid

from fastapi import HTTPException

DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0), "wait": (0, 0)}
SIZE = 7
MAX_MOVES = 80
TTL_SECONDS = 7200
AGENT_NAME = "Pip"
AGENT_LEASE_SECONDS = 90
AGENT_REPLY_SECONDS = 15


@dataclass
class Session:
    owner: str
    mode: str
    controller: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    updated: float = field(default_factory=time.monotonic)
    positions: dict = field(default_factory=lambda: {"human": [0, 3], "agent": [6, 3]})
    scores: dict = field(default_factory=lambda: {"human": 0, "agent": 0})
    target: list = field(default_factory=lambda: [3, 3])
    revision: int = 0
    turn: str = "human"
    outcome: str | None = None
    agent_until: float = 0
    reply_by: float = 0


class Arena:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()

    def create(self, owner: str, mode: str, controller: str) -> dict:
        if mode not in {"coop", "versus"} or controller not in {"builtin", "external", "auto"}:
            raise HTTPException(422, "Unknown play mode or controller")
        with self.lock:
            now = time.monotonic()
            self.sessions = {k: v for k, v in self.sessions.items() if now - v.updated < TTL_SECONDS}
            if len(self.sessions) >= 1024 or sum(s.owner == owner for s in self.sessions.values()) >= 8:
                raise HTTPException(429, "Too many active play sessions; finish or close a session")
            session = Session(owner, mode, controller)
            self.sessions[session.id] = session
            return self._view(session)

    def connect(self, owner: str, *, mode: str | None = None, session_id: str | None = None, new_round: bool = False, join: bool = False) -> dict:
        """Resume one account's current round, or create it once under the lock."""
        if mode is not None and mode not in {"coop", "versus"}:
            raise HTTPException(422, "Unknown play mode")
        with self.lock:
            now = time.monotonic()
            self.sessions = {k: s for k, s in self.sessions.items() if now - s.updated < TTL_SECONDS}
            if session_id:
                current = self._get(session_id, owner)
            else:
                current = next((s for s in reversed(self.sessions.values()) if s.owner == owner), None)
            if current and (new_round or mode is not None and mode != current.mode):
                del self.sessions[current.id]
                current = None
            if current is None:
                if len(self.sessions) >= 1024:
                    raise HTTPException(429, "Pip is busy. Try again shortly")
                current = Session(owner, mode or "coop", "auto")
                self.sessions[current.id] = current
            if current.controller != "auto":
                current.controller = "auto"
                if current.turn == "agent":
                    current.reply_by = now + AGENT_REPLY_SECONDS
            self._settle(current)
            if join:
                current.agent_until = now + AGENT_LEASE_SECONDS
                if current.turn == "agent" and not current.reply_by:
                    current.reply_by = now + AGENT_REPLY_SECONDS
            return self._view(current)

    def current(self, owner: str) -> dict:
        with self.lock:
            session = next((s for s in reversed(self.sessions.values()) if s.owner == owner and time.monotonic() - s.updated < TTL_SECONDS), None)
            if session is None:
                raise HTTPException(404, "No current play session")
            self._settle(session)
            return self._view(session)

    def _settle(self, s: Session) -> None:
        # Resolve a scheduled turn timeout once. A disconnected client must not
        # strand the human, and a late move must not replay the fallback's turn.
        if s.controller == "auto" and not s.outcome and s.turn == "agent" and s.reply_by and time.monotonic() >= s.reply_by:
            s.agent_until = 0
            self._step(s, "agent", self._bot_action(s))

    def _get(self, session_id: str, owner: str) -> Session:
        s = self.sessions.get(session_id)
        if not s or s.owner != owner or time.monotonic() - s.updated >= TTL_SECONDS:
            raise HTTPException(404, "Play session not found or expired")
        return s

    def read(self, session_id: str, owner: str) -> dict:
        with self.lock:
            s = self._get(session_id, owner)
            self._settle(s)
            return self._view(s)

    def close(self, session_id: str, owner: str) -> None:
        with self.lock:
            self._get(session_id, owner)
            del self.sessions[session_id]

    @staticmethod
    def _legal(s: Session, player: str) -> list[str]:
        x, y = s.positions[player]
        return [name for name, (dx, dy) in DIRECTIONS.items() if 0 <= x + dx < SIZE and 0 <= y + dy < SIZE]

    def _view(self, s: Session) -> dict:
        return deepcopy({
            "session_id": s.id, "game": "dot-arena-v1", "mode": s.mode,
            "controller": s.controller, "size": SIZE, "positions": s.positions,
            "agent_name": AGENT_NAME, "agent_connected": s.agent_until > time.monotonic(),
            "scores": s.scores, "target": s.target, "revision": s.revision,
            "turn": None if s.outcome else s.turn, "outcome": s.outcome,
            "moves_remaining": MAX_MOVES - s.revision,
            "goal": 6 if s.mode == "coop" else 3,
            "legal_actions": {p: self._legal(s, p) if not s.outcome and s.turn == p else [] for p in ("human", "agent")},
        })

    def _step(self, s: Session, player: str, action: str) -> None:
        dx, dy = DIRECTIONS[action]
        x, y = s.positions[player]
        s.positions[player] = [x + dx, y + dy]
        s.revision += 1
        if s.positions[player] == s.target:
            s.scores[player] += 1
            if s.mode == "coop" and sum(s.scores.values()) >= 6:
                s.outcome = "team"
            elif s.mode == "versus" and s.scores[player] >= 3:
                s.outcome = player
            if not s.outcome:
                s.target = secrets.choice([[x, y] for x in range(SIZE) for y in range(SIZE) if [x, y] not in s.positions.values()])
        if not s.outcome and s.revision >= MAX_MOVES:
            if s.mode == "coop":
                s.outcome = "out-of-moves"
            else:
                s.outcome = "tie" if s.scores["human"] == s.scores["agent"] else max(s.scores, key=s.scores.get)
        s.turn = "agent" if player == "human" else "human"
        s.reply_by = 0
        s.updated = time.monotonic()

    def _bot_action(self, s: Session) -> str:
        # In co-op, leave a nearer target to the human instead of racing them.
        distance = lambda p: sum(abs(a - b) for a, b in zip(s.positions[p], s.target))
        if s.mode == "coop" and distance("human") <= distance("agent"):
            return "wait"
        x, y = s.positions["agent"]
        tx, ty = s.target
        if x != tx:
            return "right" if x < tx else "left"
        if y != ty:
            return "down" if y < ty else "up"
        return "wait"

    def action(self, session_id: str, owner: str, player: str, action: str, revision: int) -> dict:
        with self.lock:
            s = self._get(session_id, owner)
            self._settle(s)
            if player not in {"human", "agent"} or action not in DIRECTIONS:
                raise HTTPException(422, "Unknown player or action")
            if s.revision != revision:
                raise HTTPException(409, "State changed; read the current state before acting again")
            if s.outcome or s.turn != player:
                raise HTTPException(409, "It is not this player's turn")
            if player == "agent" and s.controller != "external":
                if s.controller != "auto" or s.agent_until <= time.monotonic():
                    raise HTTPException(409, "Join the current round before moving Pip")
            if action not in self._legal(s, player):
                raise HTTPException(409, "That move leaves the board")
            self._step(s, player, action)
            if player == "agent":
                s.agent_until = time.monotonic() + AGENT_LEASE_SECONDS
            if not s.outcome and player == "human":
                if s.controller == "builtin" or s.controller == "auto" and s.agent_until <= time.monotonic():
                    self._step(s, "agent", self._bot_action(s))
                elif s.controller == "auto":
                    s.reply_by = time.monotonic() + AGENT_REPLY_SECONDS
            return self._view(s)


arena = Arena()
