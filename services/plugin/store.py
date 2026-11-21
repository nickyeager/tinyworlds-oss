"""Encrypted durable OAuth records and atomic one-use receipts."""

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager

from cryptography.fernet import Fernet

from services.plugin.config import Config


class Store:
    def __init__(self, config: Config):
        config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = config.encryption_key
        if key is None:
            path = config.data_dir / "encryption.key"
            if not path.exists():
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write(Fernet.generate_key())
            key = path.read_text().strip()
        self.cipher = Fernet(key.encode())
        self.path = config.data_dir / "oauth.sqlite3"
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data BLOB, expires REAL, PRIMARY KEY(kind,id))"
            )
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def digest(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def put(self, kind: str, key: str, data: dict, ttl: float = 30 * 86400):
        encrypted = self.cipher.encrypt(json.dumps(data).encode())
        with self.connection() as db:
            db.execute("DELETE FROM records WHERE expires <= ?", (time.time(),))
            db.execute(
                "INSERT OR REPLACE INTO records VALUES(?,?,?,?)",
                (kind, self.digest(key), encrypted, time.time() + ttl),
            )

    def get(self, kind: str, key: str, *, consume: bool = False) -> dict | None:
        with self.connection() as db:
            if consume:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data,expires FROM records WHERE kind=? AND id=?",
                (kind, self.digest(key)),
            ).fetchone()
            if consume:
                db.execute(
                    "DELETE FROM records WHERE kind=? AND id=?",
                    (kind, self.digest(key)),
                )
        if not row or row[1] <= time.time():
            return None
        return json.loads(self.cipher.decrypt(row[0]))

    def remove(self, kind: str, key: str):
        with self.connection() as db:
            db.execute(
                "DELETE FROM records WHERE kind=? AND id=?", (kind, self.digest(key))
            )

    def reserve_operation(self, key: str, fingerprint: str) -> dict | None:
        """A duplicate never enqueues a second game, even after an uncertain timeout."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data FROM records WHERE kind='operation' AND id=?",
                (self.digest(key),),
            ).fetchone()
            if row:
                return json.loads(self.cipher.decrypt(row[0]))
            payload = self.cipher.encrypt(
                json.dumps({"fingerprint": fingerprint, "status": "pending"}).encode()
            )
            db.execute(
                "INSERT INTO records VALUES('operation',?,?,?)",
                (self.digest(key), payload, time.time() + 30 * 86400),
            )
        return None
