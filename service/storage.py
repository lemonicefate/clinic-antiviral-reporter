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
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 10:
                raise RuntimeError("Central schema is newer than this service")
            self.db.execute("PRAGMA journal_mode=WAL")
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
            if version < 3:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE ingestion_state (
                        id TEXT PRIMARY KEY, revision INTEGER NOT NULL, anchor_date TEXT NOT NULL
                    );
                    CREATE TABLE report_cases (
                        id TEXT PRIMARY KEY, source_key TEXT UNIQUE NOT NULL,
                        revision INTEGER NOT NULL, reported_quantity INTEGER NOT NULL
                    );
                    CREATE TABLE source_snapshots (
                        sequence INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES report_cases(id),
                        captured_at REAL NOT NULL, facts TEXT NOT NULL
                    );
                    CREATE INDEX snapshots_case ON source_snapshots(case_id,sequence);
                    PRAGMA user_version=3;
                    COMMIT;
                """)
            if version < 4:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE report_cases ADD COLUMN reason TEXT;
                    PRAGMA user_version=4;
                    COMMIT;
                """)
            if version < 5:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE report_cases ADD COLUMN lots TEXT NOT NULL DEFAULT '[]';
                    ALTER TABLE report_cases ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;
                    ALTER TABLE report_cases ADD COLUMN exclusion_reason TEXT;
                    PRAGMA user_version=5;
                    COMMIT;
                """)
            if version < 6:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE report_cases ADD COLUMN reporting_snapshot INTEGER REFERENCES source_snapshots(sequence);
                    ALTER TABLE report_cases ADD COLUMN reviewed_snapshot INTEGER REFERENCES source_snapshots(sequence);
                    UPDATE report_cases SET reporting_snapshot=(SELECT MAX(sequence) FROM source_snapshots WHERE case_id=report_cases.id);
                    UPDATE report_cases SET reviewed_snapshot=reporting_snapshot;
                    CREATE TABLE source_quarantine (
                        sequence INTEGER PRIMARY KEY, source_key TEXT NOT NULL,
                        captured_at REAL NOT NULL, facts TEXT NOT NULL, diagnosis TEXT NOT NULL,
                        last_seen REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
                        resolved INTEGER NOT NULL DEFAULT 0
                    );
                    PRAGMA user_version=6;
                    COMMIT;
                """)
            if version < 7:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE scan_state (
                        id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
                        current_job TEXT, last_success REAL
                    );
                    INSERT INTO scan_state VALUES (1,0,NULL,NULL);
                    CREATE TABLE scan_runs (
                        id TEXT PRIMARY KEY, status TEXT NOT NULL, date_from TEXT NOT NULL,
                        date_to TEXT NOT NULL, device_id TEXT NOT NULL, operator TEXT NOT NULL,
                        requested_at REAL NOT NULL, started_at REAL, finished_at REAL,
                        diagnostic TEXT, counts TEXT NOT NULL DEFAULT '{}'
                    );
                    PRAGMA user_version=7;
                    COMMIT;
                """)
            if version < 8:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE mapping_versions (
                        sequence INTEGER PRIMARY KEY, effective_from TEXT NOT NULL UNIQUE,
                        initial_date_from TEXT NOT NULL, internal_code TEXT NOT NULL,
                        nhi_code TEXT NOT NULL, material_value TEXT NOT NULL,
                        quantity_rule TEXT NOT NULL, enabled INTEGER NOT NULL,
                        reason TEXT NOT NULL, device_id TEXT NOT NULL,
                        operator TEXT NOT NULL, created_at REAL NOT NULL
                    );
                    ALTER TABLE source_snapshots ADD COLUMN mapping_version INTEGER REFERENCES mapping_versions(sequence);
                    ALTER TABLE scan_runs ADD COLUMN mapping_revision INTEGER NOT NULL DEFAULT 0;
                    PRAGMA user_version=8;
                    COMMIT;
                """)
            if version < 9:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    ALTER TABLE scan_runs ADD COLUMN outage_recovery INTEGER NOT NULL DEFAULT 0;
                    CREATE TABLE scan_case_observations (
                        scan_job_id TEXT NOT NULL REFERENCES scan_runs(id),
                        case_id TEXT NOT NULL REFERENCES report_cases(id),
                        source_snapshot INTEGER NOT NULL REFERENCES source_snapshots(sequence),
                        PRIMARY KEY(scan_job_id,case_id)
                    );
                    CREATE TABLE outside_completions (
                        case_id TEXT PRIMARY KEY REFERENCES report_cases(id),
                        source_snapshot INTEGER NOT NULL REFERENCES source_snapshots(sequence),
                        scan_job_id TEXT NOT NULL REFERENCES scan_runs(id),
                        device_id TEXT NOT NULL REFERENCES devices(id), operator TEXT NOT NULL,
                        recorded_at REAL NOT NULL, reason TEXT NOT NULL
                    );
                    PRAGMA user_version=9;
                    COMMIT;
                """)
            if version < 10:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE backup_state (
                        id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
                        current_job TEXT
                    );
                    INSERT INTO backup_state VALUES (1,0,NULL);
                    CREATE TABLE backup_runs (
                        id TEXT PRIMARY KEY, status TEXT NOT NULL,
                        requested_at REAL NOT NULL, snapshot_at REAL, finished_at REAL,
                        device_id TEXT NOT NULL, operator TEXT NOT NULL,
                        reason TEXT NOT NULL, diagnostic TEXT
                    );
                    PRAGMA user_version=10;
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
