"""Read-only export selection review; OPEN evidence never grants file access."""

import json
from datetime import date
from typing import Annotated, Callable, Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from service.cases import CaseView, RevisionCommand, _case_rows, _duplicates, _view
from service.reporting import BulkCaseRevision
from service.settings import Settings
from service.storage import saved_result


class ExportGate(BaseModel):
    key: str
    label: str
    status: Literal["OPEN"] = "OPEN"


def export_gates() -> list[ExportGate]:
    # These are unresolved evidence groups, not switches an operator may flip.
    # Closing them requires the linked M0 evidence workflow and a reviewed gate
    # implementation; an environment flag cannot substitute for that evidence.
    return [ExportGate(key=key, label=label) for key, label in (
        ("live_his_contract", "實際 HIS 來源鍵、欄位、鎖檔與唯讀驗證"),
        ("official_export_contract", "官方必填／條件必填、數量、多批號與補正規則"),
        ("synthetic_smis_import", "保留受控合成資料通過 SMIS 匯入的證據"),
        ("operator_authorization", "代理作業、憑證使用與責任授權"),
        ("deployment_and_restore", "正式帳號、網路、裝置撤銷與異機備份還原"),
        ("outage_recovery", "正式啟用紀錄、停機補掃與系統外完成流程"),
    )]


class ExportCandidate(BaseModel):
    case: CaseView
    defaultSelected: bool
    selected: bool
    internalIssues: list[str]
    warnings: list[str]
    officialBlockers: list[str]
    officiallyExportable: Literal[False] = False


class ExportPreview(BaseModel):
    items: list[ExportCandidate]
    selectedCount: int
    internallyCompleteCount: int
    gates: list[ExportGate]
    operationalFlagEnabled: bool
    productionExportEnabled: Literal[False] = False


class CreateExport(RevisionCommand):
    cases: list[BulkCaseRevision] = Field(min_length=1)


class PreviewSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dateFrom: date | None = None
    dateTo: date | None = None
    selected: list[UUID]


def candidate(row, case):
    issues = []
    if case["outsideCompletion"]:
        issues.append("outside_completed")
    if case["excluded"]:
        issues.append("excluded")
    if not case["reason"]:
        issues.append("reason_missing")
    if not case["lots"]:
        issues.append("lots_missing")
    elif sum(lot["quantity"] for lot in case["lots"]) != case["reportedQuantity"]:
        issues.append("lot_total_mismatch")
    if not 0 < case["reportedQuantity"] <= case["sourceQuantity"]:
        issues.append("quantity_out_of_range")
    if case["sourceUnresolved"]:
        issues.append("source_unresolved")
    if case["sourceReviewRequired"]:
        issues.append("source_review_required")
    warnings = []
    if case["duplicateConcern"]:
        warnings.append("duplicate_concern")
    if case["sourceReviewRequired"]:
        warnings.append("source_changed")
    blockers = ["official_required_fields_unverified", "official_quantity_rules_unverified",
                "official_lot_rules_unverified", "live_source_unverified"]
    if row["mapping_version"] is None:
        blockers.append("mapping_unassigned")
    complete = case["internallyComplete"] and not issues
    # This release cannot create an export or upload declaration. Later export
    # lifecycle work must exclude uploaded versions from the default selection.
    return {"case": case, "defaultSelected": complete, "selected": complete,
            "internalIssues": issues, "warnings": warnings, "officialBlockers": blockers,
            "officiallyExportable": False}


def register_export_routes(app: FastAPI, settings: Settings, active_session: Callable, mutation_result):
    def reporting_session(db, authorization, session_id):
        device, session = active_session(db, authorization, session_id)
        if "reporting" not in json.loads(device["capabilities"]):
            raise HTTPException(403, "Reporting capability required")
        return device, session

    @app.get("/api/v1/export-preview", response_model=ExportPreview, operation_id="getExportPreview")
    def preview(request: Request, dateFrom: date | None = None, dateTo: date | None = None,
                manualSelection: bool = False, selected: Annotated[list[UUID] | None, Query()] = None,
                authorization: Annotated[str | None, Header()] = None,
                x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            reporting_session(db, authorization, x_session_id)
            if dateFrom and dateTo and dateFrom > dateTo:
                raise HTTPException(422, "Invalid preview date range")
            if selected and not manualSelection:
                raise HTTPException(422, "Explicit selections require manual selection mode")
            rows = _case_rows(db)
            duplicates = _duplicates(rows)
            items = [candidate(row, _view(row, facts, duplicates)) for row, facts in rows
                     if (dateFrom is None or facts["CH011M1.SDATE"] >= dateFrom.isoformat())
                     and (dateTo is None or facts["CH011M1.SDATE"] <= dateTo.isoformat())]
            if manualSelection:
                requested = {str(case_id) for case_id in selected or []}
                available = {item["case"]["caseId"] for item in items}
                if not requested <= available:
                    raise HTTPException(422, "A selected case is unavailable in this preview range")
                for item in items:
                    item["selected"] = (item["case"]["caseId"] in requested and not item["case"]["excluded"]
                                        and item["case"]["outsideCompletion"] is None)
            items.sort(key=lambda item: (item["case"]["reportingDate"], item["case"]["caseId"]))
            return {"items": items, "selectedCount": sum(item["selected"] for item in items),
                    "internallyCompleteCount": sum(item["case"]["internallyComplete"] for item in items),
                    "gates": export_gates(), "operationalFlagEnabled": settings.export_enabled,
                    "productionExportEnabled": False}

    @app.post("/api/v1/export-preview", response_model=ExportPreview, operation_id="reviewExportSelection")
    def review_selection(selection: PreviewSelection, request: Request,
                         authorization: Annotated[str | None, Header()] = None,
                         x_session_id: Annotated[str | None, Header()] = None):
        # Read-only projection: no command, persisted selection or audit mutation.
        # A body avoids putting large sets of selected identifiers in the URL.
        return preview(request, dateFrom=selection.dateFrom, dateTo=selection.dateTo,
                       manualSelection=True, selected=selection.selected,
                       authorization=authorization, x_session_id=x_session_id)

    def refuse_production():
        raise HTTPException(403, {"code": "production_export_gated",
            "operationalFlagEnabled": settings.export_enabled,
            "gates": [gate.model_dump() for gate in export_gates()]})

    @app.post("/api/v1/exports", response_model=mutation_result, operation_id="createExport")
    def generate(command: CreateExport, request: Request,
                 authorization: Annotated[str | None, Header()] = None,
                 x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, _ = reporting_session(db, authorization, x_session_id)
            # Preserve the global request-ID contract even for a command retried
            # on another route. No new generation request is accepted by this slice.
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            refuse_production()

    @app.get("/api/v1/exports/{export_id}/file", operation_id="downloadExport")
    def download(export_id: UUID, request: Request,
                 authorization: Annotated[str | None, Header()] = None,
                 x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            reporting_session(db, authorization, x_session_id)
            refuse_production()
