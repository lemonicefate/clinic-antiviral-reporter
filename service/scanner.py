"""Single central scan worker, durable requests and bounded read-only retries."""

from datetime import date
import json
from pathlib import Path
from threading import Event, Thread
import time
from typing import Annotated, Callable, Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from service.cases import RefreshCommand, clinic_today
from service.his_reader import NAMESPACE, ReadFailure, read_sources
from service.settings import Settings
from service.sources import ingest_observation, quarantine
from service.storage import Store, saved_result, save_result
from service.mappings import scan_configuration, mapping_for_date


class ScanCommand(RefreshCommand):
    dateFrom: date
    dateTo: date


class ScanView(BaseModel):
    revision: int
    enabled: bool
    status: Literal["disabled", "awaiting_configuration", "idle", "queued", "running", "succeeded", "partial", "failed", "interrupted"]
    jobId: str | None = None
    dateFrom: date | None = None
    dateTo: date | None = None
    startedAt: float | None = None
    finishedAt: float | None = None
    lastSuccessAt: float | None = None
    stale: bool = True
    diagnostic: str | None = None
    counts: dict[str, int] = {}
    intervalSeconds: int
    synthetic: Literal[True] = True


class Scanner:
    def __init__(self, store: Store, settings: Settings):
        self.store, self.settings = store, settings
        self.enabled = bool(settings.environment == "development" and settings.synthetic_enabled and
                            settings.synthetic_dbf_enabled)
        self.stop_event, self.wake = Event(), Event()
        self.worker: Thread | None = None

    def audit(self, db, kind, device, operator, changes):
        db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                   (kind, device, operator, time.time(), json.dumps(changes)))

    def view(self, db):
        state = db.execute("SELECT * FROM scan_state WHERE id=1").fetchone()
        job = db.execute("SELECT * FROM scan_runs WHERE id=?", (state["current_job"],)).fetchone()
        configured = scan_configuration(db) is not None
        return {"revision": state["revision"], "enabled": self.enabled,
                "status": ((job["status"] if job else "idle") if configured else "awaiting_configuration") if self.enabled else "disabled",
                "jobId": job["id"] if job else None, "dateFrom": job["date_from"] if job else None,
                "dateTo": job["date_to"] if job else None, "startedAt": job["started_at"] if job else None,
                "finishedAt": job["finished_at"] if job else None, "lastSuccessAt": state["last_success"],
                "stale": state["last_success"] is None or time.time() - state["last_success"] > 2 * self.settings.scan_interval_seconds,
                "diagnostic": job["diagnostic"] if job else None,
                "counts": json.loads(job["counts"]) if job else {}, "intervalSeconds": self.settings.scan_interval_seconds}

    def enqueue(self, db, date_from, date_to, device, operator):
        job = str(uuid4())
        revision = db.execute("SELECT COALESCE(MAX(sequence),0) FROM mapping_versions").fetchone()[0]
        db.execute("INSERT INTO scan_runs(id,status,date_from,date_to,device_id,operator,requested_at,mapping_revision) VALUES (?,?,?,?,?,?,?,?)",
                   (job, "queued", date_from.isoformat(), date_to.isoformat(), device, operator, time.time(), revision))
        db.execute("UPDATE scan_state SET current_job=?,revision=revision+1 WHERE id=1", (job,))
        self.audit(db, "scan_requested", device, operator, {"jobId": job, "dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()})

    def start(self):
        if not self.enabled:
            return
        with self.store.transaction() as db:
            for job in db.execute("SELECT * FROM scan_runs WHERE status='running'").fetchall():
                db.execute("UPDATE scan_runs SET status='interrupted',finished_at=?,diagnostic='service_restarted' WHERE id=?", (time.time(), job["id"]))
                db.execute("UPDATE scan_state SET revision=revision+1 WHERE id=1")
                self.audit(db, "scan_interrupted", "central-scanner", "central-scanner", {"jobId": job["id"]})
        self.worker = Thread(target=self.loop, name="clinic-source-scanner", daemon=True)
        self.worker.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.worker:
            self.worker.join()

    def loop(self):
        next_scan = 0.0
        while not self.stop_event.is_set():
            with self.store.transaction() as db:
                state = self.view(db)
                initial_date = scan_configuration(db)
                if initial_date and state["status"] not in ("queued", "running") and time.monotonic() >= next_scan:
                    self.enqueue(db, initial_date, clinic_today(), "central-scanner", "central-scanner")
                    next_scan = time.monotonic() + self.settings.scan_interval_seconds
                job = db.execute("SELECT * FROM scan_runs WHERE status='queued' ORDER BY requested_at LIMIT 1").fetchone() if initial_date else None
                if job:
                    db.execute("UPDATE scan_runs SET status='running',started_at=? WHERE id=?", (time.time(), job["id"]))
                    self.audit(db, "scan_started", job["device_id"], job["operator"], {"jobId": job["id"]})
            if job:
                try:
                    self.run(job)
                except Exception:
                    # Failed ingestion rolls back; record only a generic code in
                    # a fresh transaction, and keep the worker available to retry.
                    with self.store.transaction() as db:
                        db.execute("UPDATE scan_runs SET status='failed',finished_at=?,diagnostic='ingestion_failed' WHERE id=?",
                                   (time.time(), job["id"]))
                        db.execute("UPDATE scan_state SET revision=revision+1 WHERE id=1")
                        self.audit(db, "scan_failed", job["device_id"], job["operator"], {"jobId": job["id"], "diagnostic": "ingestion_failed"})
            else:
                self.wake.wait(.1)
                self.wake.clear()

    def run(self, job):
        result = None
        diagnostic = None
        for attempt in range(3):
            try:
                result = read_sources(Path(self.settings.state_dir) / "synthetic-dbf")
                break
            except ReadFailure as error:
                diagnostic = str(error)
                if self.stop_event.wait(.05 * (2 ** attempt)):
                    diagnostic = "service_stopping"
                    break
            except Exception:
                diagnostic = "reader_failure"
                break
        with self.store.transaction() as db:
            counts = {"created": 0, "changed": 0, "unchanged": 0, "quarantined": 0}
            if result is not None:
                actor, session = {"id": job["device_id"]}, {"operator": job["operator"]}
                observed = {key for key, _ in result.observations} | {key for key, _, _ in result.problems}
                mapping_problems = set()
                def existing_in_range(key):
                    prior = db.execute("SELECT c.*,s.facts FROM report_cases c JOIN source_snapshots s ON s.sequence="
                                       "(SELECT MAX(sequence) FROM source_snapshots WHERE case_id=c.id) WHERE c.source_key=?", (key,)).fetchone()
                    selected = bool(prior and job["date_from"] <= json.loads(prior["facts"])["CH011M1.SDATE"] <= job["date_to"])
                    return prior, selected
                for key, facts, problem in result.problems:
                    row, selected = existing_in_range(key)
                    try:
                        current_date = date.fromisoformat(facts.get("raw.CH011M1.SDATE", "").strip()).isoformat()
                    except ValueError:
                        current_date = None
                    # A known source moving into the range still needs isolation.
                    # Unknown dates cannot prove the source is outside the range.
                    if row and not selected and current_date is not None and not job["date_from"] <= current_date <= job["date_to"]:
                        continue
                    quarantine(db, key, facts, problem, row, actor, session)
                    counts["quarantined"] += 1
                for key, facts in result.observations:
                    row, selected = existing_in_range(key)
                    if selected or job["date_from"] <= facts["CH011M1.SDATE"] <= job["date_to"]:
                        mapping = mapping_for_date(db, facts["CH011M1.SDATE"], job["mapping_revision"])
                        if mapping is None or not mapping["enabled"]:
                            mapping_problems.add(key)
                            quarantine(db, key, facts, "mapping_not_effective", row, actor, session)
                            counts["quarantined"] += 1
                        else:
                            counts[ingest_observation(db, key, facts, actor, session, mapping["sequence"])] += 1
                # Full stable reads may retire file/invalid-key diagnostics that
                # cannot be matched to a case. Case-bound recovery is audited by
                # ingest_observation and remains pending explicit human review.
                problem_keys = {key for key, _, _ in result.problems} | mapping_problems
                problem_keys |= {key for key, facts in result.observations if facts["RG011M1.TREAT"] == "N"}
                for diagnostic_row in db.execute("SELECT * FROM source_quarantine q WHERE source_key LIKE ? AND resolved=0 "
                                                 "AND NOT EXISTS(SELECT 1 FROM report_cases c WHERE c.source_key=q.source_key)",
                                                 (NAMESPACE + "%",)).fetchall():
                    if diagnostic_row["source_key"] not in problem_keys:
                        db.execute("UPDATE source_quarantine SET resolved=1 WHERE sequence=?", (diagnostic_row["sequence"],))
                        self.audit(db, "source_diagnostic_resolved", job["device_id"], job["operator"], {
                            "jobId": job["id"], "quarantineSequence": diagnostic_row["sequence"], "sourceKey": diagnostic_row["source_key"]})
                for row in db.execute("SELECT c.*,s.facts FROM report_cases c JOIN source_snapshots s ON s.sequence="
                                      "(SELECT MAX(sequence) FROM source_snapshots WHERE case_id=c.id) WHERE c.source_key LIKE ?",
                                      (NAMESPACE + "%",)).fetchall():
                    facts = json.loads(row["facts"])
                    if row["source_key"] not in observed and job["date_from"] <= facts["CH011M1.SDATE"] <= job["date_to"]:
                        quarantine(db, row["source_key"], {}, "source_not_observed", row, actor, session)
                        counts["quarantined"] += 1
                status = "partial" if counts["quarantined"] else "succeeded"
                diagnostic = "quarantined_sources" if counts["quarantined"] else None
            else:
                status = "failed"
                counts["quarantined"] = 1
                # A file-level fault is central-only diagnostic history, not a case.
                quarantine(db, NAMESPACE + "scan-files", {}, diagnostic, None,
                           {"id": job["device_id"]}, {"operator": job["operator"]})
            finished = time.time()
            db.execute("UPDATE scan_runs SET status=?,finished_at=?,diagnostic=?,counts=? WHERE id=?",
                       (status, finished, diagnostic, json.dumps(counts), job["id"]))
            db.execute("UPDATE scan_state SET revision=revision+1,last_success=CASE WHEN ?='succeeded' THEN ? ELSE last_success END WHERE id=1",
                       (status, finished))
            self.audit(db, "scan_finished", job["device_id"], job["operator"], {"jobId": job["id"], "status": status, "diagnostic": diagnostic, "counts": counts})


def register_scan_routes(app: FastAPI, permitted: Callable, mutation_result):
    @app.get("/api/v1/scans/status", response_model=ScanView, operation_id="getScanStatus")
    def status(request: Request, authorization: Annotated[str | None, Header()] = None,
               x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            permitted(db, authorization, x_session_id)
            return request.app.state.scanner.view(db)

    @app.post("/api/v1/scans", response_model=mutation_result, operation_id="requestScan")
    def refresh(command: ScanCommand, request: Request, authorization: Annotated[str | None, Header()] = None,
                x_session_id: Annotated[str | None, Header()] = None):
        scanner = request.app.state.scanner
        with request.app.state.store.transaction() as db:
            device, session = permitted(db, authorization, x_session_id)
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            if not scanner.enabled:
                raise HTTPException(403, "Production HIS reader is gated; synthetic DBF scanner is not enabled")
            current = scanner.view(db)
            if command.expectedRevision != current["revision"] or current["status"] in ("queued", "running"):
                raise HTTPException(409, {"currentRevision": current["revision"], "differences": current})
            initial_date = scan_configuration(db)
            if initial_date is None:
                raise HTTPException(409, "An administrator must configure the mapping and initial range first")
            if not initial_date <= command.dateFrom <= command.dateTo <= clinic_today():
                raise HTTPException(422, "Scan dates must stay within the explicitly configured initial range")
            scanner.enqueue(db, command.dateFrom, command.dateTo, device["id"], session["operator"])
            result = save_result(db, device["id"], str(command.requestId), scanner.view(db))
        scanner.wake.set()
        return result
