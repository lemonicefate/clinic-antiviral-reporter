"""Administrator-owned, append-only versions of verified product mappings."""

from datetime import date, datetime, timedelta, timezone
import json
import time
from typing import Annotated, Callable, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from service.cases import RevisionCommand, clinic_today
from service.storage import saved_result, save_result


class MappingProfile(BaseModel):
    internalCode: Literal["ERA"] = "ERA"
    nhiCode: Literal["A059653100"] = "A059653100"
    materialValue: Literal["DDMTR2018090002:易剋冒膠囊(顆)"] = "DDMTR2018090002:易剋冒膠囊(顆)"
    quantityRule: Literal["integer_capsules"] = "integer_capsules"


class SaveMapping(RevisionCommand, MappingProfile):
    effectiveFrom: datetime
    initialDateFrom: date
    enabled: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")

    @field_validator("effectiveFrom")
    @classmethod
    def unambiguous_boundary(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An explicit timezone is required")
        try:
            local = value.astimezone(timezone(timedelta(hours=8)))
        except OverflowError:
            raise ValueError("Boundary is outside supported dates") from None
        if (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0):
            raise ValueError("Date-only sources require a clinic midnight boundary")
        return local


class MappingVersion(MappingProfile):
    version: int
    effectiveFrom: str
    enabled: bool
    reason: str
    createdAt: float
    deviceId: str
    operator: str


class MappingView(BaseModel):
    revision: int
    goLiveAt: str | None
    initialDateFrom: date | None
    confirmedProfile: MappingProfile = MappingProfile()
    versions: list[MappingVersion]
    openGates: list[str] = ["live_his_contract", "official_export_contract", "synthetic_smis_import",
                            "operator_authorization", "deployment_and_restore", "outage_recovery"]
    productionExportEnabled: Literal[False] = False


def mapping_view(db):
    rows = db.execute("SELECT * FROM mapping_versions ORDER BY sequence").fetchall()
    return MappingView(revision=rows[-1]["sequence"] if rows else 0,
        goLiveAt=rows[0]["effective_from"] if rows else None,
        initialDateFrom=rows[0]["initial_date_from"] if rows else None,
        versions=[MappingVersion(version=row["sequence"], effectiveFrom=row["effective_from"],
            internalCode=row["internal_code"], nhiCode=row["nhi_code"], materialValue=row["material_value"],
            quantityRule=row["quantity_rule"], enabled=bool(row["enabled"]), reason=row["reason"],
            createdAt=row["created_at"], deviceId=row["device_id"], operator=row["operator"]) for row in rows]
        ).model_dump(mode="json")


def scan_configuration(db):
    first = db.execute("SELECT initial_date_from FROM mapping_versions ORDER BY sequence LIMIT 1").fetchone()
    return date.fromisoformat(first["initial_date_from"]) if first else None


def mapping_for_date(db, source_date: str, revision: int):
    # Compare dates with date-aligned configuration boundaries, without creating
    # a source event timestamp. A queued scan uses one fixed mapping revision.
    return db.execute("SELECT * FROM mapping_versions WHERE sequence<=? AND substr(effective_from,1,10)<=? "
                      "ORDER BY sequence DESC LIMIT 1", (revision, source_date)).fetchone()


def register_mapping_routes(app: FastAPI, active_session: Callable, mutation_result):
    @app.get("/api/v1/mappings", response_model=MappingView, operation_id="getMappings")
    def get_mappings(request: Request, authorization: Annotated[str | None, Header()] = None,
                     x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            active_session(db, authorization, x_session_id, admin=True)
            return mapping_view(db)

    @app.post("/api/v1/mappings", response_model=mutation_result, operation_id="saveMapping")
    def save_mapping(command: SaveMapping, request: Request,
                     authorization: Annotated[str | None, Header()] = None,
                     x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = active_session(db, authorization, x_session_id, admin=True)
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            before = mapping_view(db)
            if command.expectedRevision != before["revision"]:
                raise HTTPException(409, {"currentRevision": before["revision"], "differences": before})
            if before["versions"]:
                if (command.initialDateFrom.isoformat() != before["initialDateFrom"] or
                        command.effectiveFrom <= datetime.fromisoformat(before["versions"][-1]["effectiveFrom"])):
                    raise HTTPException(422, "Preserve the initial range and append a later effective version")
            elif not command.enabled or not command.effectiveFrom.date() <= command.initialDateFrom <= clinic_today():
                raise HTTPException(422, "First activation requires an enabled mapping and an explicit range from go-live through today")
            db.execute("INSERT INTO mapping_versions(effective_from,initial_date_from,internal_code,nhi_code,"
                       "material_value,quantity_rule,enabled,reason,device_id,operator,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (command.effectiveFrom.isoformat(), command.initialDateFrom.isoformat(), command.internalCode,
                        command.nhiCode, command.materialValue, command.quantityRule, int(command.enabled),
                        command.reason, device["id"], session["operator"], time.time()))
            after = mapping_view(db)
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("mapping_version_created", device["id"], session["operator"], time.time(),
                        json.dumps({"before": before, "after": after, "reason": command.reason})))
            return save_result(db, device["id"], str(command.requestId), after)
