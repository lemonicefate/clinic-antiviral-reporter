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
    synthetic: Literal[True] = True


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
    status: Literal["awaiting_reason"] = "awaiting_reason"
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
        "SELECT c.*,s.facts FROM report_cases c JOIN source_snapshots s ON s.sequence="
        "(SELECT MAX(sequence) FROM source_snapshots WHERE case_id=c.id)")]


def _view(row, facts, duplicates: set[tuple[str, str]]) -> dict:
    reporting_date = facts["CH011M1.SDATE"]
    return {
        "caseId": row["id"], "revision": row["revision"],
        "chartNumber": facts["PD011M1.NUM"], "patientName": facts["PD011M1.NAME"],
        "birthDate": facts["PD011M1.BIRTH"], "physician": facts["CH011M1.DOC"],
        "reportingDate": reporting_date, "sourceOrder": facts["CH012M1.SYS_2015"],
        "sourceQuantity": int(facts["CH012M1.USE_TAMT"]), "reportedQuantity": row["reported_quantity"],
        "material": "DDMTR2018090002:易剋冒膠囊(顆)",
        "overdue": reporting_date < clinic_today().isoformat(),
        "duplicateConcern": (facts["PD011M1.NUM"], reporting_date) in duplicates,
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
    def refresh(command: RefreshCommand, request: Request,
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
            created = 0
            for facts in synthetic_orders(anchor):
                key = "synthetic-v1:" + facts["CH012M1.SYS_2015"]
                if db.execute("SELECT 1 FROM report_cases WHERE source_key=?", (key,)).fetchone():
                    continue
                case_id = str(uuid4())
                db.execute("INSERT INTO report_cases VALUES (?,?,1,?)", (case_id, key, 10))
                db.execute("INSERT INTO source_snapshots(case_id,captured_at,facts) VALUES (?,?,?)",
                           (case_id, time.time(), json.dumps(facts, ensure_ascii=False)))
                db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                           ("case_created", device["id"], session["operator"], time.time(),
                            json.dumps({"caseId": case_id, "sourceKey": key, "synthetic": True})))
                created += 1
            db.execute("INSERT INTO ingestion_state VALUES ('synthetic-v1',?,?) ON CONFLICT(id) "
                       "DO UPDATE SET revision=excluded.revision", (revision + 1, anchor.isoformat()))
            result = {"revision": revision + 1, "created": created, "unchanged": 4 - created, "synthetic": True}
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("synthetic_refreshed", device["id"], session["operator"], time.time(), json.dumps(result)))
            return save_result(db, device["id"], str(command.requestId), result)

    @app.get("/api/v1/cases", response_model=QueueView, operation_id="listCases")
    def queue(request: Request, physician: Annotated[str | None, Query(max_length=100)] = None,
              chart: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
              authorization: Annotated[str | None, Header()] = None,
              x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            _, session = permitted(db, authorization, x_session_id)
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
            return {"items": items, "total": len(items), "overdue": sum(item["overdue"] for item in items),
                    "physicians": sorted({facts["CH011M1.DOC"] for _, facts in rows}), "physician": selected,
                    "syntheticRefreshEnabled": settings.synthetic_enabled and settings.environment == "development",
                    "refreshRevision": state["revision"] if state else 0}

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
