"""Bounded, account-private mailbox for generated games' native Pip adapters.

Game state is untrusted content. Only registered action IDs reach the game;
no source edits, inference, credentials or executable code travel this channel.
Sessions deliberately expire with the playing browser, and are process-local.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import json
import threading
import time
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator


class GameSync(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    actions: list[str] = Field(min_length=1, max_length=64)
    observation: dict
    acknowledgement: dict | None = None

    @model_validator(mode='after')
    def bounded(self):
        import re
        if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', a) for a in self.actions):
            raise ValueError('Invalid action ID')
        if len(json.dumps(self.observation, allow_nan=False)) > 16000:
            raise ValueError('Observation too large')
        if self.acknowledgement is not None and (set(self.acknowledgement) != {'id', 'accepted'} or not isinstance(self.acknowledgement['id'], str) or len(self.acknowledgement['id']) > 64 or type(self.acknowledgement['accepted']) is not bool):
            raise ValueError('Invalid acknowledgement')
        return self


class GameAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    expected_revision: int = Field(ge=0, strict=True)


@dataclass
class Session:
    owner: str
    game_id: str
    client: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    updated: float = 0
    lease: float = 0
    revision: int = 0
    actions: list = field(default_factory=list)
    observation: dict = field(default_factory=dict)
    command: dict | None = None
    acknowledgement: dict | None = None


class Companions:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()

    def _prune(self):
        now = time.monotonic()
        self.sessions = {k: s for k, s in self.sessions.items() if now - s.updated < 20}
        for s in self.sessions.values():
            if s.lease <= now and s.command:
                s.command = None
                s.revision += 1

    def _get(self, owner, session_id=None):
        self._prune()
        s = self.sessions.get(session_id) if session_id else max((s for s in self.sessions.values() if s.owner == owner), key=lambda s: s.updated, default=None)
        if not s or s.owner != owner:
            raise HTTPException(404, 'No active game companion')
        return s

    def _view(self, s):
        return deepcopy(dict(session_id=s.id, game=s.game_id, agent_name='Pip', agent_connected=s.lease > time.monotonic(), revision=s.revision, legal_actions=s.actions if not s.command else [], observation=s.observation, command=s.command, acknowledgement=s.acknowledgement))

    def sync(self, owner: str, game_id: str, body: GameSync):
        with self.lock:
            self._prune()
            s = next((s for s in self.sessions.values() if (s.owner, s.game_id, s.client) == (owner, game_id, body.client_id)), None)
            if s is None:
                if len(self.sessions) >= 1024 or sum(s.owner == owner for s in self.sessions.values()) >= 8:
                    raise HTTPException(429, 'Too many active games')
                s = Session(owner, game_id, body.client_id)
                self.sessions[s.id] = s
            changed = s.actions != body.actions or s.observation != body.observation
            s.updated = time.monotonic()
            s.actions, s.observation = list(body.actions), deepcopy(body.observation)
            if s.command and body.acknowledgement and body.acknowledgement.get('id') == s.command['id']:
                s.acknowledgement = deepcopy(body.acknowledgement)
                s.command = None
                changed = True
            if changed:
                s.revision += 1
            return self._view(s)

    def read(self, owner, session_id=None, *, join=False):
        with self.lock:
            s = self._get(owner, session_id)
            if join:
                s.lease = time.monotonic() + 15
            return self._view(s)

    def close(self, owner, session_id):
        with self.lock:
            s = self._get(owner, session_id)
            # Keep the browser session; immediately return control to local Pip.
            s.lease = 0
            s.command = None
            s.revision += 1

    def action(self, owner, session_id, body: GameAction):
        with self.lock:
            s = self._get(owner, session_id)
            if s.revision != body.expected_revision or s.command:
                raise HTTPException(409, 'Game changed; reread state before acting')
            if body.action not in s.actions:
                raise HTTPException(422, 'Action not advertised by this game')
            s.lease = time.monotonic() + 15
            s.command = dict(id=uuid.uuid4().hex, action=body.action)
            s.revision += 1
            return self._view(s)


companions = Companions()
