"""Durable scheduled backups and administrator-only health without file paths."""

import json
from pathlib import Path
import sqlite3
from threading import Event, Thread
import time
from typing import Annotated, Callable, Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from service.backup_archive import (BackupError, artifact_files, check_database, copy_new,
                                    fingerprint, reject_reparse, runtime_configuration,
                                    verify_archive, write_new)
from service.cases import RevisionCommand
from service.settings import Settings, same_share_name
from service.storage import Store, saved_result, save_result
from service.synthetic_paths import fixture_root


class BackupCommand(RevisionCommand):
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class BackupView(BaseModel):
    revision: int
    enabled: bool
    status: Literal["disabled", "idle", "queued", "running", "ready", "failed", "interrupted"]
    backupId: str | None
    lastSuccessfulAt: float | None
    lastSnapshotAt: float | None
    lastFailureAt: float | None
    diagnostic: str | None
    rpoBreached: bool
    rpoSeconds: Literal[3600] = 3600
    intervalSeconds: int
    destinationKind: Literal["disabled", "local_synthetic", "configured_share"]
    deploymentVerified: Literal[False] = False


class Backups:
    def __init__(self, store: Store, settings: Settings, tls_files: tuple[Path, Path] | None = None):
        self.store, self.settings = store, settings
        self.stop_event, self.wake = Event(), Event()
        self.worker: Thread | None = None
        self.tls_files = tls_files

    def destination(self) -> Path:
        if self.settings.synthetic_backup_enabled:
            return fixture_root(Path(self.settings.state_dir)).parent / "synthetic-backups"
        # Recheck even for Settings constructed directly by an integration.
        if same_share_name(self.settings.his_source_path, self.settings.backup_root):
            raise BackupError("unsafe_backup_destination")
        return Path(self.settings.backup_root)

    def audit(self, db, kind, job, extra=None):
        db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                   (kind, job["device_id"], job["operator"], time.time(), json.dumps({
                       "backupId": job["id"], "reason": job["reason"], **(extra or {})})))

    def view(self, db):
        state = db.execute("SELECT * FROM backup_state WHERE id=1").fetchone()
        current = db.execute("SELECT * FROM backup_runs WHERE id=?", (state["current_job"],)).fetchone()
        success = db.execute("SELECT * FROM backup_runs WHERE status='ready' ORDER BY snapshot_at DESC LIMIT 1").fetchone()
        failure = db.execute("SELECT * FROM backup_runs WHERE status IN ('failed','interrupted') ORDER BY finished_at DESC LIMIT 1").fetchone()
        enabled = self.settings.backup_enabled
        return {"revision": state["revision"], "enabled": enabled,
                "status": (current["status"] if current else "idle") if enabled else "disabled",
                "backupId": current["id"] if current else None,
                "lastSuccessfulAt": success["finished_at"] if success else None,
                "lastSnapshotAt": success["snapshot_at"] if success else None,
                "lastFailureAt": failure["finished_at"] if failure else None,
                "diagnostic": failure["diagnostic"] if failure else None,
                "rpoBreached": not success or not 0 <= time.time() - success["snapshot_at"] <= 3600,
                "intervalSeconds": self.settings.backup_interval_seconds,
                "destinationKind": "disabled" if not enabled else "local_synthetic" if self.settings.synthetic_backup_enabled else "configured_share",
                "deploymentVerified": False}

    def enqueue(self, db, device, operator, reason):
        job = str(uuid4())
        db.execute("INSERT INTO backup_runs(id,status,requested_at,device_id,operator,reason) VALUES (?,'queued',?,?,?,?)",
                   (job, time.time(), device, operator, reason))
        db.execute("UPDATE backup_state SET current_job=?,revision=revision+1 WHERE id=1", (job,))
        row = db.execute("SELECT * FROM backup_runs WHERE id=?", (job,)).fetchone()
        self.audit(db, "backup_requested", row)

    def start(self):
        with self.store.transaction() as db:
            for job in db.execute("SELECT * FROM backup_runs WHERE status='running'").fetchall():
                recovered = None
                if self.settings.backup_enabled:
                    try:
                        recovered = verify_archive(self.destination() / ("backup-" + job["id"]))
                    except Exception:
                        pass
                db.execute("UPDATE backup_runs SET status=?,snapshot_at=?,finished_at=?,diagnostic=? WHERE id=?",
                           ("ready" if recovered else "interrupted", recovered["snapshotAt"] if recovered else job["snapshot_at"],
                            recovered["completedAt"] if recovered else time.time(), None if recovered else "service_restarted", job["id"]))
                db.execute("UPDATE backup_state SET revision=revision+1 WHERE id=1")
                self.audit(db, "backup_recovered" if recovered else "backup_interrupted", job)
        if self.settings.backup_enabled:
            self.worker = Thread(target=self.loop, name="clinic-backup-worker", daemon=True)
            self.worker.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.worker:
            self.worker.join()

    def loop(self):
        with self.store.transaction() as db:
            last_snapshot = self.view(db)["lastSnapshotAt"]
        age = time.time() - (last_snapshot or 0)
        next_backup = time.monotonic() + (max(0, self.settings.backup_interval_seconds - age) if age >= 0 else 0)
        while not self.stop_event.is_set():
            with self.store.transaction() as db:
                status = self.view(db)
                if status["status"] not in ("queued", "running") and time.monotonic() >= next_backup:
                    self.enqueue(db, "central-backup", "central-backup", "Scheduled central backup")
                job = db.execute("SELECT * FROM backup_runs WHERE status='queued' ORDER BY requested_at LIMIT 1").fetchone()
                if job:
                    next_backup = time.monotonic() + self.settings.backup_interval_seconds
                    db.execute("UPDATE backup_runs SET status='running' WHERE id=?", (job["id"],))
                    self.audit(db, "backup_started", job)
            if job:
                try:
                    manifest = self.publish(job["id"])
                    with self.store.transaction() as db:
                        db.execute("UPDATE backup_runs SET status='ready',snapshot_at=?,finished_at=?,diagnostic=NULL WHERE id=?",
                                   (manifest["snapshotAt"], manifest["completedAt"], job["id"]))
                        db.execute("UPDATE backup_state SET revision=revision+1 WHERE id=1")
                        self.audit(db, "backup_ready", job, {"snapshotAt": manifest["snapshotAt"]})
                except Exception as error:
                    diagnostic = str(error) if isinstance(error, BackupError) else "backup_failed"
                    with self.store.transaction() as db:
                        db.execute("UPDATE backup_runs SET status='failed',finished_at=?,diagnostic=? WHERE id=?",
                                   (time.time(), diagnostic, job["id"]))
                        db.execute("UPDATE backup_state SET revision=revision+1 WHERE id=1")
                        self.audit(db, "backup_failed", job, {"diagnostic": diagnostic})
            else:
                self.wake.wait(.2)
                self.wake.clear()

    def publish(self, job_id):
        state = Path(self.settings.state_dir)
        destination = self.destination()
        reject_reparse(destination)
        staging = state / "backup-staging" / job_id
        reject_reparse(staging)
        staging.mkdir(parents=True)
        files = ["central.sqlite3", "runtime.json"]
        with self.store.lock:
            snapshot = time.time()
            copied = sqlite3.connect(staging / "central.sqlite3")
            try:
                self.store.db.backup(copied)
            finally:
                copied.close()
            check_database(staging / "central.sqlite3")
            write_new(staging / "runtime.json", json.dumps(runtime_configuration(self.settings), ensure_ascii=False).encode("utf-8"))
            for artifact in artifact_files(state / "immutable-artifacts"):
                name = artifact.relative_to(state).as_posix()
                copy_new(artifact, staging / name)
                files.append(name)
            if self.tls_files:
                for source, name in zip(self.tls_files, ("tls.crt", "tls.key")):
                    copy_new(source, staging / name)
                    files.append(name)
        manifest = {"format": 1, "backupId": job_id, "snapshotAt": snapshot,
                    "synthetic": self.settings.synthetic_enabled,
                    "files": {name: fingerprint(staging / name) for name in files}}
        pending = destination / (".pending-" + job_id)
        reject_reparse(pending)
        pending.mkdir(parents=True)
        for name in files:
            if self.stop_event.is_set():
                raise BackupError("service_stopping")
            copy_new(staging / name, pending / name)
        for name, expected in manifest["files"].items():
            if fingerprint(pending / name) != expected:
                raise BackupError("backup_integrity_failed")
        # Payload-copy verification time; success is exposed only after the
        # manifest and published directory also verify below.
        manifest["completedAt"] = time.time()
        write_new(pending / "manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        verify_archive(pending, published=False)
        published = destination / ("backup-" + job_id)
        pending.rename(published)
        verify_archive(published)
        return manifest


def register_backup_routes(app: FastAPI, active_session: Callable, mutation_result):
    @app.get("/api/v1/backups/status", response_model=BackupView, operation_id="getBackupStatus")
    def status(request: Request, authorization: Annotated[str | None, Header()] = None,
               x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            active_session(db, authorization, x_session_id, admin=True)
            return request.app.state.backups.view(db)

    @app.post("/api/v1/backups", response_model=mutation_result, operation_id="requestBackup")
    def backup(command: BackupCommand, request: Request, authorization: Annotated[str | None, Header()] = None,
               x_session_id: Annotated[str | None, Header()] = None):
        manager = request.app.state.backups
        with request.app.state.store.transaction() as db:
            device, session = active_session(db, authorization, x_session_id, admin=True)
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            if not manager.settings.backup_enabled:
                raise HTTPException(403, "Backups are not enabled in central runtime configuration")
            current = manager.view(db)
            if command.expectedRevision != current["revision"] or current["status"] in ("queued", "running"):
                raise HTTPException(409, {"currentRevision": current["revision"], "differences": current})
            manager.enqueue(db, device["id"], session["operator"], command.reason)
            result = save_result(db, device["id"], str(command.requestId), manager.view(db))
        manager.wake.set()
        return result
