"""Versioned central API. Device authority is independent of operator identity."""

from contextlib import asynccontextmanager
from pathlib import Path
import json
import secrets
import time
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field

from service.settings import Settings
from service.storage import Store, digest, saved_result, save_result
from service.cases import CaseView, RefreshView, register_case_routes
from service.reporting import BulkLotView
from service.scanner import Scanner, ScanView
from service.mappings import MappingView, register_mapping_routes
from service.export_preview import register_export_routes


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: UUID
    expectedRevision: int = Field(ge=0, strict=True)


class CreateSession(Command):
    operator: str = Field(min_length=1, max_length=100, pattern=r"\S")


class SessionView(BaseModel):
    sessionId: str
    deviceId: str
    operator: str
    capabilities: list[str]
    revision: int
    expiresAt: float


Capability = Literal["admin", "physician", "reporting"]


class CreatePairing(Command):
    capabilities: list[Capability] = Field(min_length=1, max_length=3)


class PairingView(BaseModel):
    pairingCode: str
    expiresAt: float


class EnrollDevice(Command):
    pairingCode: str = Field(min_length=43, max_length=43)
    credential: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")


class RevokeDevice(Command):
    reason: str = Field(min_length=1, max_length=500, pattern=r"\S")


class DeviceView(BaseModel):
    deviceId: str
    name: str
    capabilities: list[Capability]
    revision: int
    revoked: bool


class AuditView(BaseModel):
    sequence: int
    kind: str
    deviceId: str
    operator: str
    occurredAt: float
    changes: dict


# requestId identifies the original command, even when a caller accidentally
# retries it on another mutation route. Document every possible replay shape.
MutationResult = SessionView | PairingView | DeviceView | RefreshView | CaseView | BulkLotView | ScanView | MappingView


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = Store(Path(settings.state_dir))
        app.state.scanner = Scanner(app.state.store, settings)
        try:
            app.state.scanner.start()
            yield
        finally:
            app.state.scanner.close()
            app.state.store.close()

    app = FastAPI(title="Clinic Antiviral Reporter", version="1.0.0", lifespan=lifespan,
                  openapi_url="/api/v1/openapi.json", docs_url=None, redoc_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        return JSONResponse({"detail": "Invalid request fields",
                             "fields": [list(item["loc"]) for item in error.errors()]}, status_code=422)

    @app.middleware("http")
    async def transport(request: Request, call_next):
        # No proxy headers are trusted by this application.
        if request.url.scheme != "https":
            response = JSONResponse({"detail": "HTTPS is required"}, status_code=400)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def authorized(db, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Device authorization required")
        device = db.execute("SELECT * FROM devices WHERE credential_hash=? AND revoked=0",
                            (digest(authorization[7:]),)).fetchone()
        if not device:
            raise HTTPException(401, "Device authorization required")
        return device

    def view(device, session):
        return {"sessionId": session["id"], "deviceId": device["id"], "operator": session["operator"],
                "capabilities": json.loads(device["capabilities"]), "revision": device["revision"],
                "expiresAt": session["expires_at"]}

    def active_session(db, authorization, session_id, *, admin=False):
        device = authorized(db, authorization)
        session = db.execute("SELECT * FROM sessions WHERE id=? AND device_id=? AND expires_at>?",
                             (session_id, device["id"], time.time())).fetchone()
        if not session:
            raise HTTPException(401, "An active session is required")
        if admin and "admin" not in json.loads(device["capabilities"]):
            raise HTTPException(403, "Administrator device capability required")
        return device, session

    def device_view(device):
        return {"deviceId": device["id"], "name": device["name"],
                "capabilities": json.loads(device["capabilities"]), "revision": device["revision"],
                "revoked": bool(device["revoked"])}

    @app.post("/api/v1/sessions", response_model=MutationResult, operation_id="createSession")
    def create_session(command: CreateSession, request: Request,
                       authorization: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device = authorized(db, authorization)
            actor = device["id"]
            previous = saved_result(db, actor, str(command.requestId))
            if previous is not None:
                return previous
            if command.expectedRevision != 0:
                raise HTTPException(409, {"currentRevision": 0, "differences": {"session": "new session"}})
            session = {"id": str(uuid4()), "operator": command.operator, "expires_at": time.time() + 8 * 3600}
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                       (session["id"], actor, command.operator, session["expires_at"]))
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("session_created", actor, command.operator, time.time(), json.dumps({"sessionId": session["id"]})))
            return save_result(db, actor, str(command.requestId), view(device, session))

    @app.get("/api/v1/session", response_model=SessionView, operation_id="getSession")
    def get_session(request: Request, authorization: Annotated[str | None, Header()] = None,
                    x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = active_session(db, authorization, x_session_id)
            return view(device, session)

    @app.get("/api/v1/devices", response_model=list[DeviceView], operation_id="listDevices")
    def list_devices(request: Request, authorization: Annotated[str | None, Header()] = None,
                     x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            active_session(db, authorization, x_session_id, admin=True)
            return [device_view(row) for row in db.execute("SELECT * FROM devices ORDER BY name,id")]

    @app.get("/api/v1/audit", response_model=list[AuditView], operation_id="listAuditEvents")
    def list_audit(request: Request, authorization: Annotated[str | None, Header()] = None,
                   x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            active_session(db, authorization, x_session_id, admin=True)
            return [{"sequence": row["sequence"], "kind": row["kind"], "deviceId": row["device_id"],
                     "operator": row["operator"], "occurredAt": row["occurred_at"],
                     "changes": json.loads(row["changes"])}
                    for row in db.execute("SELECT * FROM audit_events ORDER BY sequence")]

    @app.post("/api/v1/pairings", response_model=MutationResult, operation_id="createPairing")
    def create_pairing(command: CreatePairing, request: Request,
                       authorization: Annotated[str | None, Header()] = None,
                       x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            device, session = active_session(db, authorization, x_session_id, admin=True)
            previous = saved_result(db, device["id"], str(command.requestId))
            if previous is not None:
                return previous
            if command.expectedRevision != 0:
                raise HTTPException(409, {"currentRevision": 0, "differences": {"pairing": "new pairing"}})
            code = secrets.token_urlsafe(32)
            result = {"pairingCode": code, "expiresAt": time.time() + 600}
            capabilities = sorted(set(command.capabilities))
            db.execute("INSERT INTO pairings VALUES (?,?,?,0,?)", (digest(code),
                        json.dumps(capabilities), result["expiresAt"], device["id"]))
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("pairing_created", device["id"], session["operator"], time.time(),
                        json.dumps({"capabilities": capabilities})))
            return save_result(db, device["id"], str(command.requestId), result)

    @app.post("/api/v1/devices/enroll", response_model=DeviceView, operation_id="enrollDevice")
    def enroll_device(command: EnrollDevice, request: Request):
        with request.app.state.store.transaction() as db:
            # Retry identity binds both secrets; the pairing code alone cannot recover enrollment.
            actor = "enroll:" + digest(command.pairingCode + ":" + command.credential)
            previous = saved_result(db, actor, str(command.requestId))
            if previous is not None:
                device = db.execute("SELECT revoked FROM devices WHERE id=?", (previous["deviceId"],)).fetchone()
                if device["revoked"]:
                    raise HTTPException(401, "Device authorization required")
                return previous
            pairing = db.execute("SELECT p.* FROM pairings p JOIN devices d ON d.id=p.issuer "
                                 "WHERE p.code_hash=? AND p.used=0 AND p.expires_at>? AND d.revoked=0",
                                 (digest(command.pairingCode), time.time())).fetchone()
            if not pairing:
                raise HTTPException(401, "Pairing code is invalid, expired, or already used")
            if command.expectedRevision != 0:
                raise HTTPException(409, {"currentRevision": 0, "differences": {"device": "new device"}})
            if db.execute("SELECT 1 FROM devices WHERE credential_hash=?", (digest(command.credential),)).fetchone():
                raise HTTPException(409, "Device credential is already registered")
            device_id = str(uuid4())
            db.execute("INSERT INTO devices VALUES (?,?,?,?,1,0)", (device_id, command.name,
                        digest(command.credential), pairing["capabilities"]))
            db.execute("UPDATE pairings SET used=1 WHERE code_hash=?", (digest(command.pairingCode),))
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("device_enrolled", device_id, "pairing", time.time(),
                        json.dumps({"issuer": pairing["issuer"], "name": command.name,
                                    "capabilities": json.loads(pairing["capabilities"])})))
            result = device_view(db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone())
            return save_result(db, actor, str(command.requestId), result)

    @app.post("/api/v1/devices/{device_id}/revoke", response_model=MutationResult, operation_id="revokeDevice")
    def revoke_device(device_id: UUID, command: RevokeDevice, request: Request,
                      authorization: Annotated[str | None, Header()] = None,
                      x_session_id: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            actor, session = active_session(db, authorization, x_session_id, admin=True)
            previous = saved_result(db, actor["id"], str(command.requestId))
            if previous is not None:
                return previous
            device = db.execute("SELECT * FROM devices WHERE id=?", (str(device_id),)).fetchone()
            if not device:
                raise HTTPException(404, "Device not found")
            if device["revision"] != command.expectedRevision:
                raise HTTPException(409, {"currentRevision": device["revision"],
                                          "differences": {"revoked": bool(device["revoked"])}})
            if not device["revoked"] and "admin" in json.loads(device["capabilities"]):
                other_admin = db.execute(
                    "SELECT 1 FROM devices d, json_each(d.capabilities) c "
                    "WHERE d.revoked=0 AND d.id<>? AND c.value='admin' LIMIT 1",
                    (str(device_id),),
                ).fetchone()
                if not other_admin:
                    raise HTTPException(409, "Pair another administrator device before revoking the last administrator")
            db.execute("UPDATE devices SET revoked=1,revision=revision+1 WHERE id=?", (str(device_id),))
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("device_revoked", actor["id"], session["operator"], time.time(),
                        json.dumps({"deviceId": str(device_id), "before": bool(device["revoked"]),
                                    "after": True, "reason": command.reason})))
            result = device_view(db.execute("SELECT * FROM devices WHERE id=?", (str(device_id),)).fetchone())
            return save_result(db, actor["id"], str(command.requestId), result)

    register_case_routes(app, settings, active_session, MutationResult)
    register_mapping_routes(app, active_session, MutationResult)
    register_export_routes(app, settings, active_session, MutationResult)
    return app
