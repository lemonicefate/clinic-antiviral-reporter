"""Administrator paper-workflow completion, independent of export history."""

import json
import time
from datetime import date
from typing import Annotated, Callable
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from service.cases import RevisionCommand, _case_rows, _duplicates, _view
from service.storage import saved_result, save_result


class CompleteOutside(RevisionCommand):
    sourceSnapshot: int = Field(gt=0, strict=True)
    scanJobId: UUID
    paperAndSmisCompleted: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class OutageRescanView(BaseModel):
    jobId: str
    dateFrom: date
    dateTo: date
    status: str
    finishedAt: float | None


def register_outage_routes(app: FastAPI, active_session: Callable, mutation_result):
    @app.get("/api/v1/outage-rescans/latest", response_model=OutageRescanView | None, operation_id="getLatestOutageRescan")
    def latest_rescan(request: Request, authorization: Annotated[str | None, Header()] = None,
                      x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            active_session(db, authorization, x_session_id, admin=True)
            scan = db.execute("SELECT * FROM scan_runs WHERE outage_recovery=1 ORDER BY requested_at DESC LIMIT 1").fetchone()
            if scan is None:
                return None
            return {"jobId": scan["id"], "dateFrom": scan["date_from"], "dateTo": scan["date_to"],
                    "status": scan["status"], "finishedAt": scan["finished_at"]}

    @app.post("/api/v1/cases/{case_id}/outside-completion", response_model=mutation_result,
              operation_id="completeOutsideSystem")
    def complete(case_id: UUID, command: CompleteOutside, request: Request,
                 authorization: Annotated[str | None, Header()] = None,
                 x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = active_session(db, authorization, x_session_id, admin=True)
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            rows = _case_rows(db)
            selected = next(((r, f) for r, f in rows if r["id"] == str(case_id)), None)
            if selected is None:
                raise HTTPException(404, "Case not found")
            row, facts = selected
            before = _view(row, facts, _duplicates(rows))
            if (command.expectedRevision != row["revision"] or command.sourceSnapshot != row["latest_sequence"]
                    or before["outsideCompletion"] or before["excluded"] or before["sourceUnresolved"]):
                raise HTTPException(409, {"currentRevision": row["revision"], "differences": before})
            if not command.paperAndSmisCompleted:
                raise HTTPException(422, "Confirm completion of the paper and SMIS workflow")
            scan = db.execute("SELECT * FROM scan_runs WHERE id=?", (str(command.scanJobId),)).fetchone()
            source = db.execute("SELECT * FROM source_snapshots WHERE sequence=?", (command.sourceSnapshot,)).fetchone()
            source_date = json.loads(source["facts"])["CH011M1.SDATE"]
            observed = db.execute("SELECT 1 FROM scan_case_observations WHERE scan_job_id=? AND case_id=? AND source_snapshot=?",
                                  (str(command.scanJobId), str(case_id), command.sourceSnapshot)).fetchone()
            if (not observed or scan is None or not scan["outage_recovery"] or scan["status"] not in ("succeeded", "partial") or
                    not scan["date_from"] <= source_date <= scan["date_to"] or
                    scan["finished_at"] < source["captured_at"]):
                raise HTTPException(422, "A completed rescan covering the current source is required")
            recorded = time.time()
            db.execute("INSERT INTO outside_completions VALUES (?,?,?,?,?,?,?)",
                       (str(case_id), command.sourceSnapshot, str(command.scanJobId), device["id"],
                        session["operator"], recorded, command.reason))
            db.execute("UPDATE report_cases SET revision=revision+1 WHERE id=?", (str(case_id),))
            updated = _case_rows(db)
            row, facts = next((r, f) for r, f in updated if r["id"] == str(case_id))
            after = _view(row, facts, _duplicates(updated))
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("outside_completed", device["id"], session["operator"], recorded, json.dumps({
                           "caseId": str(case_id), "source": "human", "sourceSnapshot": command.sourceSnapshot,
                           "reason": command.reason, "paperAndSmisCompleted": True,
                           "before": {"status": before["status"], "revision": before["revision"]},
                           "after": {"status": after["status"], "revision": after["revision"],
                                     "outsideCompletion": after["outsideCompletion"]}}, ensure_ascii=False)))
            return save_result(db, device["id"], str(command.requestId), after)
