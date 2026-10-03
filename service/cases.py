"""Central case projection and explicit, built-in synthetic ingestion only.

No HIS reader or arbitrary fixture-upload endpoint is exposed by this slice.
The synthetic identity namespace is not evidence for live HIS key semantics.
"""

from datetime import date, datetime, timedelta, timezone
import json
import time
from typing import Annotated, Callable, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from service.settings import Settings
from service.storage import saved_result, save_result
from service.reason_options import reason_options, TEMPLATE_SHA256


def clinic_today() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


class RefreshCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: UUID
    expectedRevision: int = Field(ge=0, strict=True)


class RefreshView(BaseModel):
    revision: int
    created: int
    unchanged: int
    changed: int = 0
    quarantined: int = 0
    synthetic: Literal[True] = True


class SyntheticRefresh(RefreshCommand):
    scenario: Literal["original", "modified", "cancelled", "unseen", "deleted", "missing"] = "original"


class SaveReason(RefreshCommand):
    reason: str = Field(min_length=1, max_length=1000)
    patientConfirmed: bool = Field(strict=True)


class ReasonOptionsView(BaseModel):
    values: list[str]
    templateSha256: str
    officialRulesVerified: Literal[False] = False


class LotAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lot: str = Field(min_length=1, max_length=100, pattern=r"\S")
    quantity: int = Field(gt=0, strict=True)


class CaseView(BaseModel):
    caseId: str
    revision: int
    chartNumber: str
    patientName: str
    birthDate: date
    physician: str
    reportingDate: date
    sourceOrder: str
    sourceQuantity: int
    reportedQuantity: int
    material: str
    overdue: bool
    duplicateConcern: bool
    status: Literal["awaiting_reason", "awaiting_reconciliation", "internally_complete", "excluded"] = "awaiting_reason"
    reason: str | None = None
    lots: list[LotAllocation] = Field(default_factory=list)
    excluded: bool = False
    exclusionReason: str | None = None
    sourceReviewRequired: bool = False
    sourceUnresolved: bool = False
    reportingSourceSnapshot: int = 0
    latestSourceSnapshot: int = 0
    sourceDifferences: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    sourceTreatment: str = "Y"
    internallyComplete: bool = False
    exportEligible: Literal[False] = False
    synthetic: Literal[True] = True
    liveIdentityVerified: Literal[False] = False


class SnapshotView(BaseModel):
    sequence: int
    capturedAt: float
    raw: dict[str, str]


class CaseDetail(CaseView):
    snapshots: list[SnapshotView]


class QueueView(BaseModel):
    items: list[CaseView]
    total: int
    overdue: int
    awaitingReason: int
    physicians: list[str]
    physician: str
    syntheticRefreshEnabled: bool
    refreshRevision: int


def synthetic_orders(anchor: date) -> list[dict[str, str]]:
    rows = []
    for order, chart, name, doctor, days in [
        ("SYN-ORDER-1", "SYN-0001", "合成病人甲", "SYN-DR-A", 0),
        ("SYN-ORDER-2", "SYN-0001", "合成病人甲", "SYN-DR-A", 0),
        ("SYN-ORDER-3", "SYN-0002", "合成病人乙", "SYN-DR-A", 1),
        ("SYN-ORDER-4", "SYN-0003", "合成病人丙", "SYN-DR-B", 0),
    ]:
        rows.append({
            "CH012M1.SYS_2015": order, "CH012M1.RELKEY": "SYN ENCOUNTER " + chart,
            "PD011M1.NUM": chart, "PD011M1.NAME": name, "PD011M1.BIRTH": "1990-01-01",
            "CH011M1.DOC": doctor, "CH011M1.SDATE": (anchor - timedelta(days=days)).isoformat(),
            "CH012M1.MED1": "ERA", "H_INV.ITEMN": "ERA", "H_INV.LABNUM": "A059653100",
            "CH012M1.PRICE1": "SYN-A059653100", "CH012M1.USE_TAMT": "10",
            "RG011M1.TREAT": "Y",
        })
    return rows


def _case_rows(db):
    return [(row, json.loads(row["facts"])) for row in db.execute(
        "SELECT c.*,s.facts,latest.sequence AS latest_sequence,latest.facts AS latest_facts, "
        "EXISTS(SELECT 1 FROM source_quarantine q WHERE q.source_key=c.source_key AND q.resolved=0) AS unresolved "
        "FROM report_cases c JOIN source_snapshots s ON s.sequence=c.reporting_snapshot "
        "JOIN source_snapshots latest ON latest.sequence="
        "(SELECT MAX(sequence) FROM source_snapshots WHERE case_id=c.id)")]


def _view(row, facts, duplicates: set[tuple[str, str]]) -> dict:
    reporting_date = facts["CH011M1.SDATE"]
    lots = json.loads(row["lots"])
    latest = json.loads(row["latest_facts"])
    pending = row["reviewed_snapshot"] != row["latest_sequence"] or bool(row["unresolved"])
    complete = bool(not pending and row["reason"] and lots and
                    row["reported_quantity"] <= int(facts["CH012M1.USE_TAMT"]) and
                    sum(lot["quantity"] for lot in lots) == row["reported_quantity"])
    excluded = bool(row["excluded"])
    return {
        "caseId": row["id"], "revision": row["revision"],
        "chartNumber": facts["PD011M1.NUM"], "patientName": facts["PD011M1.NAME"],
        "birthDate": facts["PD011M1.BIRTH"], "physician": facts["CH011M1.DOC"],
        "reportingDate": reporting_date, "sourceOrder": facts["CH012M1.SYS_2015"],
        "sourceQuantity": int(facts["CH012M1.USE_TAMT"]), "reportedQuantity": row["reported_quantity"],
        "material": "DDMTR2018090002:易剋冒膠囊(顆)",
        "overdue": not excluded and reporting_date < clinic_today().isoformat(),
        "duplicateConcern": (facts["PD011M1.NUM"], reporting_date) in duplicates,
        "reason": row["reason"],
        "lots": lots, "excluded": excluded, "exclusionReason": row["exclusion_reason"],
        "sourceReviewRequired": pending, "reportingSourceSnapshot": row["reporting_snapshot"],
        "sourceUnresolved": bool(row["unresolved"]),
        "latestSourceSnapshot": row["latest_sequence"], "sourceTreatment": latest.get("RG011M1.TREAT", ""),
        "sourceDifferences": {key: {"before": facts.get(key), "after": latest.get(key)}
                              for key in sorted(facts.keys() | latest.keys()) if facts.get(key) != latest.get(key)},
        "internallyComplete": complete and not excluded, "exportEligible": False,
        "status": "excluded" if excluded else "internally_complete" if complete else
                  "awaiting_reconciliation" if row["reason"] else "awaiting_reason",
    }


def _duplicates(rows) -> set[tuple[str, str]]:
    counts: dict[tuple[str, str], int] = {}
    for _, facts in rows:
        key = (facts["PD011M1.NUM"], facts["CH011M1.SDATE"])
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def register_case_routes(app: FastAPI, settings: Settings, active_session: Callable,
                         mutation_result) -> None:
    def permitted(db, authorization, session_id):
        device, session = active_session(db, authorization, session_id)
        if not set(json.loads(device["capabilities"])) & {"admin", "physician", "reporting"}:
            raise HTTPException(403, "Case capability required")
        return device, session

    @app.post("/api/v1/synthetic/refresh", response_model=mutation_result, operation_id="refreshSyntheticOrders")
    def refresh(command: SyntheticRefresh, request: Request,
                authorization: Annotated[str | None, Header()] = None,
                x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = active_session(db, authorization, x_session_id, admin=True)
            if not settings.synthetic_enabled or settings.environment != "development":
                raise HTTPException(403, "Synthetic refresh is disabled")
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            state = db.execute("SELECT * FROM ingestion_state WHERE id='synthetic-v1'").fetchone()
            revision = state["revision"] if state else 0
            if revision != command.expectedRevision:
                raise HTTPException(409, {"currentRevision": revision, "differences": {"refresh": "reload status"}})
            anchor = date.fromisoformat(state["anchor_date"]) if state else clinic_today()
            from service.sources import ingest_synthetic
            counts = ingest_synthetic(db, synthetic_orders(anchor), command.scenario, device, session)
            db.execute("INSERT INTO ingestion_state VALUES ('synthetic-v1',?,?) ON CONFLICT(id) "
                       "DO UPDATE SET revision=excluded.revision", (revision + 1, anchor.isoformat()))
            result = {"revision": revision + 1, **counts, "synthetic": True}
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("synthetic_refreshed", device["id"], session["operator"], time.time(), json.dumps(result)))
            return save_result(db, device["id"], str(command.requestId), result)

    @app.get("/api/v1/cases", response_model=QueueView, operation_id="listCases")
    def queue(request: Request, physician: Annotated[str | None, Query(max_length=100)] = None,
              chart: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
              caseStatus: Literal["active", "all", "unfinished", "excluded", "awaiting_reason", "awaiting_reconciliation", "internally_complete"] = "active",
              dateFrom: date | None = None, dateTo: date | None = None,
              exception: Literal["all", "duplicate", "overdue", "quantity_changed", "source_changed"] = "all",
              authorization: Annotated[str | None, Header()] = None,
              x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            _, session = permitted(db, authorization, x_session_id)
            if dateFrom is not None and dateTo is not None and dateFrom > dateTo:
                raise HTTPException(422, "Date range is reversed")
            selected = session["operator"] if physician is None else physician
            rows = _case_rows(db)
            duplicates = _duplicates(rows)
            items = [_view(row, facts, duplicates) for row, facts in rows
                     if (facts["PD011M1.NUM"] == chart if chart is not None
                         else not selected or facts["CH011M1.DOC"] == selected)]
            # Calendar dates have no ordering within a day. Stable identifier order
            # is presentation only; no tied case is silently selected.
            items.sort(key=lambda item: (not item["overdue"],
                       -date.fromisoformat(item["reportingDate"]).toordinal(), item["sourceOrder"]))
            state = db.execute("SELECT revision FROM ingestion_state WHERE id='synthetic-v1'").fetchone()
            items = [item for item in items if
                     (caseStatus == "all" or (caseStatus == "active" and not item["excluded"]) or
                      (caseStatus == "unfinished" and not item["excluded"] and not item["internallyComplete"]) or
                      caseStatus == item["status"]) and
                     (dateFrom is None or item["reportingDate"] >= dateFrom.isoformat()) and
                     (dateTo is None or item["reportingDate"] <= dateTo.isoformat()) and
                     (exception == "all" or (exception == "duplicate" and item["duplicateConcern"]) or
                      (exception == "overdue" and item["overdue"]) or
                      (exception == "source_changed" and item["sourceReviewRequired"]) or
                      (exception == "quantity_changed" and item["sourceQuantity"] != item["reportedQuantity"]))]
            return {"items": items, "total": len(items), "overdue": sum(item["overdue"] for item in items),
                    "awaitingReason": sum(item["reason"] is None and not item["excluded"] for item in items),
                    "physicians": sorted({facts["CH011M1.DOC"] for _, facts in rows}), "physician": selected,
                    "syntheticRefreshEnabled": settings.synthetic_enabled and settings.environment == "development",
                    "refreshRevision": state["revision"] if state else 0}

    @app.get("/api/v1/reason-options", response_model=ReasonOptionsView, operation_id="getReasonOptions")
    def options(request: Request, authorization: Annotated[str | None, Header()] = None,
                x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            permitted(db, authorization, x_session_id)
        return {"values": reason_options(), "templateSha256": TEMPLATE_SHA256, "officialRulesVerified": False}

    @app.post("/api/v1/cases/{case_id}/reason", response_model=mutation_result, operation_id="saveReason")
    def save_reason(case_id: UUID, command: SaveReason, request: Request,
                    authorization: Annotated[str | None, Header()] = None,
                    x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = permitted(db, authorization, x_session_id)
            if not set(json.loads(device["capabilities"])) & {"physician", "reporting"}:
                raise HTTPException(403, "Physician or reporting capability required")
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            if command.patientConfirmed is not True or command.reason not in reason_options():
                raise HTTPException(422, "Confirm the selected patient and select an official reason option")
            row = db.execute("SELECT * FROM report_cases WHERE id=?", (str(case_id),)).fetchone()
            if row is None:
                raise HTTPException(404, "Case not found")
            if row["revision"] != command.expectedRevision:
                raise HTTPException(409, {"currentRevision": row["revision"],
                                         "differences": {"reason": row["reason"]}})
            db.execute("UPDATE report_cases SET reason=?,revision=revision+1 WHERE id=?",
                       (command.reason, str(case_id)))
            snapshot = row["reporting_snapshot"]
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("reason_saved", device["id"], session["operator"], time.time(), json.dumps({
                           "caseId": str(case_id), "sourceSnapshot": snapshot, "source": "human",
                           "before": row["reason"], "after": command.reason,
                           "revisionBefore": row["revision"], "revisionAfter": row["revision"] + 1,
                           "patientConfirmed": True}, ensure_ascii=False)))
            rows = _case_rows(db)
            updated, facts = next((r, f) for r, f in rows if r["id"] == str(case_id))
            return save_result(db, device["id"], str(command.requestId), _view(updated, facts, _duplicates(rows)))

    @app.get("/api/v1/cases/{case_id}", response_model=CaseDetail, operation_id="getCase")
    def detail(case_id: UUID, request: Request,
               authorization: Annotated[str | None, Header()] = None,
               x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            permitted(db, authorization, x_session_id)
            rows = _case_rows(db)
            for row, facts in rows:
                if row["id"] == str(case_id):
                    return _view(row, facts, _duplicates(rows)) | {"snapshots": [
                        {"sequence": snapshot["sequence"], "capturedAt": snapshot["captured_at"],
                         "raw": json.loads(snapshot["facts"])} for snapshot in db.execute(
                             "SELECT * FROM source_snapshots WHERE case_id=? ORDER BY sequence", (str(case_id),))]}
            raise HTTPException(404, "Case not found")

    from service.reporting import register_reporting_routes
    register_reporting_routes(app, permitted, mutation_result)
    from service.sources import register_source_routes
    register_source_routes(app, permitted, mutation_result)
    from service.scanner import register_scan_routes
    register_scan_routes(app, permitted, mutation_result)
