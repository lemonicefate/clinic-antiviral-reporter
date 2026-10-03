"""Human dispensing and exclusion commands; no inventory or export side effects."""

import json
import time
from typing import Annotated, Callable
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from service.cases import CaseView, LotAllocation, RefreshCommand, _case_rows, _duplicates, _view
from service.storage import saved_result, save_result


class SaveDispensing(RefreshCommand):
    reportedQuantity: int = Field(gt=0, strict=True)
    lots: list[LotAllocation] = Field(min_length=1, max_length=50)
    changeReason: str = Field(default="", max_length=500)


class CaseHistoryEvent(BaseModel):
    sequence: int
    kind: str
    deviceId: str
    operator: str
    occurredAt: float
    changes: dict


class SetExclusion(RefreshCommand):
    excluded: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class BulkCaseRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caseId: UUID
    expectedRevision: int = Field(ge=1, strict=True)


class BulkLot(RefreshCommand):
    lot: str = Field(min_length=1, max_length=100, pattern=r"\S")
    cases: list[BulkCaseRevision] = Field(min_length=1, max_length=100)
    replaceConfirmed: bool = Field(strict=True)


class BulkLotView(BaseModel):
    appliedCases: list[CaseView]


def register_reporting_routes(app: FastAPI, permitted: Callable, mutation_result) -> None:
    def reporting_session(db, authorization, session_id):
        device, session = permitted(db, authorization, session_id)
        if "reporting" not in json.loads(device["capabilities"]):
            raise HTTPException(403, "Reporting capability required")
        return device, session

    def current_case(db, case_id):
        rows = _case_rows(db)
        for row, facts in rows:
            if row["id"] == str(case_id):
                return _view(row, facts, _duplicates(rows))
        raise HTTPException(404, "Case not found")

    def expected(case, revision):
        if case["revision"] != revision:
            raise HTTPException(409, conflict(case))

    def conflict(case):
        return {"caseId": case["caseId"], "currentRevision": case["revision"], "differences": {
            key: case[key] for key in ("reportedQuantity", "lots", "excluded", "reason", "exclusionReason")}}

    def audit(db, device, session, kind, before, after, reason):
        source = before["reportingSourceSnapshot"]
        db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                   (kind, device["id"], session["operator"], time.time(), json.dumps({
                       "caseId": before["caseId"], "sourceSnapshot": source, "source": "human", "reason": reason,
                       "before": {k: before[k] for k in ("reportedQuantity", "lots", "excluded", "exclusionReason", "revision")},
                       "after": {k: after[k] for k in ("reportedQuantity", "lots", "excluded", "exclusionReason", "revision")},
                   }, ensure_ascii=False)))

    @app.post("/api/v1/cases/{case_id}/dispensing", response_model=mutation_result, operation_id="saveDispensing")
    def dispensing(case_id: UUID, command: SaveDispensing, request: Request,
                   authorization: Annotated[str | None, Header()] = None,
                   x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = reporting_session(db, authorization, x_session_id)
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            before = current_case(db, case_id)
            expected(before, command.expectedRevision)
            if before["excluded"]:
                raise HTTPException(409, conflict(before))
            lots = [lot.model_dump() for lot in command.lots]
            if (command.reportedQuantity > before["sourceQuantity"] or
                    sum(lot["quantity"] for lot in lots) != command.reportedQuantity or
                    len({lot["lot"] for lot in lots}) != len(lots)):
                raise HTTPException(422, "Quantity must not exceed source; unique lot allocations must sum exactly")
            if command.reportedQuantity != before["reportedQuantity"] and not command.changeReason.strip():
                raise HTTPException(422, "Quantity changes require a reason")
            db.execute("UPDATE report_cases SET reported_quantity=?,lots=?,revision=revision+1 WHERE id=?",
                       (command.reportedQuantity, json.dumps(lots, ensure_ascii=False), str(case_id)))
            after = current_case(db, case_id)
            audit(db, device, session, "dispensing_saved", before, after, command.changeReason)
            return save_result(db, device["id"], str(command.requestId), after)

    @app.get("/api/v1/cases/{case_id}/history", response_model=list[CaseHistoryEvent], operation_id="getCaseHistory")
    def history(case_id: UUID, request: Request, authorization: Annotated[str | None, Header()] = None,
                x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            reporting_session(db, authorization, x_session_id)
            current_case(db, case_id)
            return [{"sequence": row["sequence"], "kind": row["kind"], "deviceId": row["device_id"],
                     "operator": row["operator"], "occurredAt": row["occurred_at"], "changes": json.loads(row["changes"])}
                    for row in db.execute("SELECT * FROM audit_events WHERE json_extract(changes,'$.caseId')=? ORDER BY sequence",
                                          (str(case_id),))]

    @app.post("/api/v1/cases/{case_id}/exclusion", response_model=mutation_result, operation_id="setCaseExclusion")
    def exclusion(case_id: UUID, command: SetExclusion, request: Request,
                  authorization: Annotated[str | None, Header()] = None,
                  x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = reporting_session(db, authorization, x_session_id)
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            before = current_case(db, case_id)
            expected(before, command.expectedRevision)
            db.execute("UPDATE report_cases SET excluded=?,exclusion_reason=?,revision=revision+1 WHERE id=?",
                       (int(command.excluded), command.reason, str(case_id)))
            after = current_case(db, case_id)
            audit(db, device, session, "exclusion_changed", before, after, command.reason)
            return save_result(db, device["id"], str(command.requestId), after)

    @app.post("/api/v1/cases/bulk-lot", response_model=mutation_result, operation_id="applyBulkLot")
    def bulk_lot(command: BulkLot, request: Request,
                 authorization: Annotated[str | None, Header()] = None,
                 x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = reporting_session(db, authorization, x_session_id)
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            if command.expectedRevision != 0:
                raise HTTPException(409, {"currentRevision": 0, "differences": {"bulk": "new batch command"}})
            if not command.replaceConfirmed or len({item.caseId for item in command.cases}) != len(command.cases):
                raise HTTPException(422, "Confirm replacement for distinct selected cases")
            before = []
            for item in command.cases:
                case = current_case(db, item.caseId)
                if case["revision"] != item.expectedRevision or case["excluded"]:
                    raise HTTPException(409, conflict(case))
                before.append(case)
            applied = []
            for case in before:
                lots = [{"lot": command.lot, "quantity": case["reportedQuantity"]}]
                db.execute("UPDATE report_cases SET lots=?,revision=revision+1 WHERE id=?",
                           (json.dumps(lots, ensure_ascii=False), case["caseId"]))
                after = current_case(db, case["caseId"])
                audit(db, device, session, "bulk_lot_saved", case, after, "")
                applied.append(after)
            return save_result(db, device["id"], str(command.requestId), {"appliedCases": applied})
