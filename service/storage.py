"""Single-owner SQLite lifecycle and transactional central history."""

from contextlib import contextmanager
import hashlib
import json
import msvcrt
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Iterator


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.owner = (directory / "service-owner.lock").open("a+b")
        self.owner.seek(0)
        try:
            msvcrt.locking(self.owner.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.owner.close()
            raise RuntimeError("The central state directory already has an owner") from None
        self.lock = RLock()
        try:
            self.db = sqlite3.connect(directory / "central.sqlite3", check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("Central schema is newer than this service")
            if version == 0:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE devices (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL, credential_hash TEXT UNIQUE NOT NULL,
                        capabilities TEXT NOT NULL, revision INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                    );
                    CREATE TABLE sessions (
                        id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id),
                        operator TEXT NOT NULL, expires_at REAL NOT NULL
                    );
                    CREATE TABLE commands (
                        actor TEXT NOT NULL, request_id TEXT NOT NULL, result TEXT NOT NULL,
                        PRIMARY KEY(actor, request_id)
                    );
                    CREATE TABLE audit_events (
                        sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, device_id TEXT NOT NULL,
                        operator TEXT NOT NULL, occurred_at REAL NOT NULL, changes TEXT NOT NULL
                    );
                    PRAGMA user_version=1;
                    COMMIT;
                """)
            if version < 2:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE pairings (
                        code_hash TEXT PRIMARY KEY, capabilities TEXT NOT NULL,
                        expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0,
                        issuer TEXT NOT NULL REFERENCES devices(id)
                    );
                    PRAGMA user_version=2;
                    COMMIT;
                """)
        except Exception:
            if hasattr(self, "db"):
                self.db.close()
            self.owner.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def close(self) -> None:
        self.db.close()
        self.owner.close()


def saved_result(db: sqlite3.Connection, actor: str, request_id: str) -> dict | None:
    row = db.execute("SELECT result FROM commands WHERE actor=? AND request_id=?", (actor, request_id)).fetchone()
    return json.loads(row["result"]) if row else None


def save_result(db: sqlite3.Connection, actor: str, request_id: str, result: dict) -> dict:
    db.execute("INSERT INTO commands VALUES (?,?,?)", (actor, request_id, json.dumps(result)))
    return result
