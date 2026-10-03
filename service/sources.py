"""Append-only synthetic source history and explicit human reconciliation.

The scenarios exercise the confirmed policy without claiming a live HIS key or
reading any HIS file. The real reader and quarantine retry scheduler are separate.
"""

import json
import time
from typing import Annotated, Callable, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from service.cases import RefreshCommand, _case_rows, _duplicates, _view
from service.storage import saved_result, save_result


class ReviewSource(RefreshCommand):
    sourceSnapshot: int = Field(gt=0, strict=True)
    resolution: Literal["update", "retain", "exclude"]
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class QuarantineView(BaseModel):
    sequence: int
    sourceKey: str
    diagnosis: str
    capturedAt: float
    lastSeen: float
    attempts: int
    resolved: bool


def quarantine(db, key, facts, diagnosis, row, device, session):
    serialized = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    prior = db.execute("SELECT sequence FROM source_quarantine WHERE source_key=? AND diagnosis=? "
                       "AND facts=? AND resolved=0", (key, diagnosis, serialized)).fetchone()
    if prior:
        db.execute("UPDATE source_quarantine SET attempts=attempts+1,last_seen=? WHERE sequence=?",
                   (time.time(), prior["sequence"]))
        return
    db.execute("INSERT INTO source_quarantine(source_key,captured_at,last_seen,facts,diagnosis) VALUES (?,?,?,?,?)",
               (key, time.time(), time.time(), serialized, diagnosis))
    if row:
        db.execute("UPDATE report_cases SET reviewed_snapshot=NULL,revision=revision+1 WHERE id=?", (row["id"],))
    db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
               ("source_quarantined", device["id"], session["operator"], time.time(), json.dumps({
                   "caseId": row["id"] if row else None, "sourceKey": key, "diagnosis": diagnosis, "source": "synthetic"})))


def ingest_synthetic(db, orders, scenario, device, session):
    counts = {"created": 0, "changed": 0, "unchanged": 0, "quarantined": 0}
    for original in orders:
        facts = dict(original)
        key = "synthetic-v1:" + facts["CH012M1.SYS_2015"]
        row = db.execute("SELECT * FROM report_cases WHERE source_key=?", (key,)).fetchone()
        if facts["CH012M1.SYS_2015"] == "SYN-ORDER-1":
            if scenario in ("deleted", "missing"):
                if row:
                    quarantine(db, key, {}, "source_not_observed", row, device, session)
                    counts["quarantined"] += 1
                continue
            if scenario == "modified":
                facts["CH012M1.USE_TAMT"] = "5"
                facts["PD011M1.NAME"] = "合成病人甲（來源更正）"
            if scenario in ("cancelled", "unseen"):
                facts["RG011M1.TREAT"] = "C" if scenario == "cancelled" else "N"
        serialized = json.dumps(facts, ensure_ascii=False, sort_keys=True)
        if facts["RG011M1.TREAT"] == "N":
            quarantine(db, key, facts, "registration_not_seen_with_order", row, device, session)
            counts["quarantined"] += 1
            continue
        recovered = [q["sequence"] for q in db.execute(
            "SELECT sequence FROM source_quarantine WHERE source_key=? AND resolved=0", (key,))]
        db.execute("UPDATE source_quarantine SET resolved=1 WHERE source_key=? AND resolved=0", (key,))
        if recovered and row:
            db.execute("UPDATE report_cases SET revision=revision+1 WHERE id=?", (row["id"],))
        if recovered:
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("source_recovered", device["id"], session["operator"], time.time(), json.dumps({
                           "caseId": row["id"] if row else None, "sourceKey": key, "quarantineSequences": recovered,
                           "revisionBefore": row["revision"] if row else None,
                           "revisionAfter": row["revision"] + 1 if row else None, "source": "synthetic"})))
        old = db.execute("SELECT * FROM source_snapshots WHERE case_id=? ORDER BY sequence DESC LIMIT 1",
                         (row["id"],)).fetchone() if row else None
        if old is not None and json.loads(old["facts"]) == facts:
            counts["unchanged"] += 1
            continue
        case_id = row["id"] if row else str(uuid4())
        if row is None:
            db.execute("INSERT INTO report_cases(id,source_key,revision,reported_quantity) VALUES (?,?,1,?)",
                       (case_id, key, int(facts["CH012M1.USE_TAMT"])))
        snapshot = db.execute("INSERT INTO source_snapshots(case_id,captured_at,facts) VALUES (?,?,?)",
                              (case_id, time.time(), serialized)).lastrowid
        if row is None:
            db.execute("UPDATE report_cases SET reporting_snapshot=?,reviewed_snapshot=? WHERE id=?",
                       (snapshot, snapshot if facts["RG011M1.TREAT"] == "Y" else None, case_id))
        else:
            db.execute("UPDATE report_cases SET revision=revision+1 WHERE id=?", (case_id,))
        kind = "source_changed" if row else "case_created"
        db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                   (kind, device["id"], session["operator"], time.time(), json.dumps({
                       "caseId": case_id, "sourceKey": key, "synthetic": True,
                       "sourceSnapshot": snapshot, "previousSnapshot": old["sequence"] if old else None,
                       "source": "synthetic", "before": json.loads(old["facts"]) if old else None,
                       "after": facts}, ensure_ascii=False)))
        counts["changed" if row else "created"] += 1
    return counts


def register_source_routes(app: FastAPI, permitted: Callable, mutation_result) -> None:
    @app.get("/api/v1/source-quarantine", response_model=list[QuarantineView], operation_id="listSourceQuarantine")
    def diagnostics(request: Request, authorization: Annotated[str | None, Header()] = None,
                    x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, _ = permitted(db, authorization, x_session_id)
            if not set(json.loads(device["capabilities"])) & {"admin", "reporting"}:
                raise HTTPException(403, "Reporting or administrative capability required")
            return [{"sequence": row["sequence"], "sourceKey": row["source_key"], "diagnosis": row["diagnosis"],
                     "capturedAt": row["captured_at"], "lastSeen": row["last_seen"], "attempts": row["attempts"],
                     "resolved": bool(row["resolved"])} for row in db.execute("SELECT * FROM source_quarantine ORDER BY sequence")]

    @app.post("/api/v1/cases/{case_id}/source-review", response_model=mutation_result, operation_id="reviewSource")
    def review(case_id: UUID, command: ReviewSource, request: Request,
               authorization: Annotated[str | None, Header()] = None,
               x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = permitted(db, authorization, x_session_id)
            if "reporting" not in json.loads(device["capabilities"]):
                raise HTTPException(403, "Reporting capability required")
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            rows = _case_rows(db)
            selected = next(((row, facts) for row, facts in rows if row["id"] == str(case_id)), None)
            if selected is None:
                raise HTTPException(404, "Case not found")
            row, facts = selected
            before = _view(row, facts, _duplicates(rows))
            if (row["revision"] != command.expectedRevision or
                    row["latest_sequence"] != command.sourceSnapshot or not before["sourceReviewRequired"] or
                    before["sourceUnresolved"]):
                raise HTTPException(409, {"caseId": str(case_id), "currentRevision": row["revision"],
                                         "differences": before})
            reporting_snapshot = command.sourceSnapshot if command.resolution == "update" else row["reporting_snapshot"]
            db.execute("UPDATE report_cases SET reporting_snapshot=?,reviewed_snapshot=?,revision=revision+1 WHERE id=?",
                       (reporting_snapshot, command.sourceSnapshot, str(case_id)))
            if command.resolution == "exclude":
                db.execute("UPDATE report_cases SET excluded=1,exclusion_reason=? WHERE id=?", (command.reason, str(case_id)))
            rows = _case_rows(db)
            updated, facts = next((r, f) for r, f in rows if r["id"] == str(case_id))
            after = _view(updated, facts, _duplicates(rows))
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("source_reviewed", device["id"], session["operator"], time.time(), json.dumps({
                           "caseId": str(case_id), "sourceSnapshot": command.sourceSnapshot,
                           "resolution": command.resolution, "reason": command.reason, "source": "human",
                           "before": before, "after": after}, ensure_ascii=False)))
            return save_result(db, device["id"], str(command.requestId), after)
